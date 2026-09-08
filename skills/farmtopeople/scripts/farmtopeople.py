#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.49.1"]  # last build with macOS 13 chromium
# ///
"""Farm to People cart CLI — browse keyless, change the cart via a saved login.

Two paths, and the split governs everything:

  keyless — Algolia (search), Sanity (catalog), and the availability endpoint.
            No login, no browser, instant.
            Covers: search, show, seasonal, deals.

  session — api.farmtopeople.com with the cookie jar from a real sign-in,
            driven through Playwright's request context.
            Covers: cart, add, remove, usual, history.

The cart is an ORDER, not a cart: /api/customers/session returns current_orders,
each with status_editing "Locked" or "Unlocked". Only the Unlocked one can be
changed, and every write is scoped to its delivery_date. A Locked order has
passed its cutoff and is on its way — nothing here can touch it.

Writes require --yes. The password is read from the environment and never
written to disk; only the resulting session cookies are cached, mode 0600.

Environment:
  FARM_TO_PEOPLE_USERNAME      login email
  FARM_TO_PEOPLE_PASSWORD      login password
  FARM_TO_PEOPLE_CUSTOMER_ID   customer key (optional; read from the session)
  FARM_TO_PEOPLE_STATE_DIR     session cache dir (default ~/.config/farmtopeople)
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SITE = "https://farmtopeople.com"
API = "https://api.farmtopeople.com"
SANITY = "https://ec9j7ju7.apicdn.sanity.io/v2021-03-25/data/query/production"
ALGOLIA = ("https://9j1nd5cv9f-dsn.algolia.net/1/indexes/*/queries"
           "?x-algolia-api-key=9ff863b1b52e8c95e07a750549283bf9"
           "&x-algolia-application-id=9J1ND5CV9F")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
STATE_DIR = Path(os.environ.get("FARM_TO_PEOPLE_STATE_DIR",
                                Path.home() / ".config" / "farmtopeople"))
STATE_FILE = STATE_DIR / "session.json"
USUAL_FILE = STATE_DIR / "usual.json"
HDRS = {"User-Agent": UA, "Origin": SITE, "Referer": SITE + "/",
        "Accept": "application/json"}


# ------------------------------------------------------------------ keyless

def _req(url: str, body=None, headers=None) -> dict:
    h = dict(HDRS)
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"ftp: HTTP {e.code} on {url.split('?')[0]} — {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"ftp: network error — {e.reason}")


def algolia(query: str, limit: int = 20, extra: str = "") -> list[dict]:
    """Full-text product search. objectID is the item_code."""
    params = (f"hitsPerPage={limit}&query={urllib.parse.quote(query)}"
              f"&filters=hiddenInSearch:false{extra}")
    out = _req(ALGOLIA, {"requests": [{"indexName": "products_index", "params": params}]},
               {"Content-Type": "application/x-www-form-urlencoded"})
    return out["results"][0]["hits"]


def sanity(groq: str, **params) -> list:
    qs = {"query": groq, "returnQuery": "false"}
    for k, v in params.items():
        qs["$" + k] = json.dumps(v)
    out = _req(f"{SANITY}?{urllib.parse.urlencode(qs)}")
    if out.get("error"):
        raise SystemExit(f"ftp: sanity — {out['error']}")
    return out.get("result") or []


PRODUCT_FIELDS = """{
  _id, name, "slug": slug.current, "producer": producer->name,
  "categories": categories[]->slug.current, salesUnitOfMeasure,
  filter_values, description, can_sell_one_time, is_pre_order
}"""


def catalog(codes: list[str]) -> dict[str, dict]:
    """Product metadata by item_code."""
    if not codes:
        return {}
    rows = sanity(f'*[_type == "product" && _id in $ids] {PRODUCT_FIELDS}', ids=codes)
    return {r["_id"]: r for r in rows}


def availability(codes: list[str], date: str | None) -> dict[str, dict]:
    """Price and stock for a delivery date. POST only — GET is refused."""
    if not codes:
        return {}
    out = _req(f"{API}/api/products/batch_availability/{date or 'null'}",
               {"product_ids": codes, "ids": codes})
    # Items with no price key aren't sellable on that date.
    return {r["item_code"]: r for r in out if isinstance(r, dict) and r.get("item_code")}


def portable_text(v) -> str:
    """Sanity Portable Text -> plain string."""
    if isinstance(v, str):
        return v
    if not isinstance(v, list):
        return ""
    out = []
    for block in v:
        if isinstance(block, dict):
            out.append("".join(c.get("text", "") for c in block.get("children") or []))
    return "\n\n".join(t for t in out if t)


def availability_all(codes: list[str], date: str | None, chunk: int = 200) -> dict[str, dict]:
    """batch_availability in chunks — the endpoint rejects very long id lists."""
    out = {}
    for i in range(0, len(codes), chunk):
        out.update(availability(codes[i:i + chunk], date))
    return out


def price_of(av: dict) -> float | None:
    for k in ("on_sale_sales_price", "standard_sales_price"):
        if av.get(k) not in (None, ""):
            try:
                return float(av[k])
            except ValueError:
                pass
    return None


def in_stock(av: dict) -> bool:
    try:
        return int(av.get("quantity") or 0) > 0 and av.get("can_sell_this_date") == "1"
    except ValueError:
        return False


# ------------------------------------------------------------------ session

def creds() -> tuple[str, str]:
    email = os.environ.get("FARM_TO_PEOPLE_USERNAME", "")
    password = os.environ.get("FARM_TO_PEOPLE_PASSWORD", "")
    if not (email and password):
        raise SystemExit(
            "ftp: set FARM_TO_PEOPLE_USERNAME and FARM_TO_PEOPLE_PASSWORD.\n"
            "  export FARM_TO_PEOPLE_USERNAME='you@example.com'\n"
            "  export FARM_TO_PEOPLE_PASSWORD='…'")
    return email, password


def _play():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("ftp: playwright missing — run via `uv run scripts/farmtopeople.py`, "
                         "then `uv run --with playwright playwright install chromium`")
    return sync_playwright


def _browser(p, headed: bool):
    """Bundled chromium, else the system Chrome (macOS 13 has no bundled build)."""
    try:
        return p.chromium.launch(headless=not headed)
    except Exception:
        pass
    try:
        return p.chromium.launch(headless=not headed, channel="chrome")
    except Exception as e:
        raise SystemExit(
            f"ftp: no usable browser ({e}).\n"
            "  fix: uv run --with playwright==1.49.1 playwright install chromium\n"
            "  (or install Google Chrome — the script falls back to it)")


def do_login(ctx, headed: bool = False, quiet: bool = False) -> None:
    """Two-step sign-in: email, then the password field it reveals."""
    email, password = creds()
    page = ctx.new_page()
    page.goto(f"{SITE}/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    form = page.locator("form").first
    form.locator("input[type=email]").fill(email)
    form.locator("button[type=submit]").click()
    try:
        form.locator("input[type=password]").wait_for(state="visible", timeout=20000)
    except Exception:
        raise SystemExit(f"ftp: no password step appeared for {email} — "
                         "check the address, or run `login --headed` to see the page.")
    form.locator("input[type=password]").fill(password)
    form.locator("button[type=submit]").click()
    page.wait_for_timeout(6000)

    if not _alive(ctx):
        raise SystemExit("ftp: sign-in failed — check FARM_TO_PEOPLE_PASSWORD, "
                         "or run `login --headed` if a challenge is being shown.")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ctx.storage_state(path=str(STATE_FILE))
    STATE_FILE.chmod(0o600)
    page.close()
    if not quiet:
        print(f"signed in as {email} — session saved to {STATE_FILE}")


def _alive(ctx) -> bool:
    try:
        r = ctx.request.get(f"{API}/api/customers/session")
        return r.status == 200 and not (r.json().get("customer") or {}).get("is_anonymous", True)
    except Exception:
        return False


def _context(p, headed: bool = False):
    """A signed-in context: reuse the saved session, else log in with env creds."""
    b = _browser(p, headed)
    common = {"user_agent": UA, "extra_http_headers": {"Origin": SITE, "Referer": SITE + "/"}}
    if STATE_FILE.exists():
        ctx = b.new_context(storage_state=str(STATE_FILE), **common)
        if _alive(ctx):
            return b, ctx
        ctx.close()  # stale session — fall through and re-auth
    ctx = b.new_context(**common)
    do_login(ctx, headed=headed, quiet=True)
    return b, ctx


def session(ctx) -> dict:
    r = ctx.request.get(f"{API}/api/customers/session")
    if r.status != 200:
        raise SystemExit(f"ftp: session read failed — HTTP {r.status}")
    return r.json()


def open_order(sess: dict) -> dict | None:
    """The editable cart: the one order whose status_editing is Unlocked."""
    for o in sess.get("current_orders") or []:
        if o.get("status_editing") == "Unlocked":
            return o
    return None


def next_delivery(sess: dict) -> str | None:
    """First calendar slot still open: deliverable, before cutoff, not sold out."""
    for d in sess.get("deliveryCalendar") or []:
        if d.get("can_deliver") == 1 and not d.get("is_cutoff") and not d.get("is_sold_out"):
            return d.get("date")
    return None


def target_date(sess: dict) -> str | None:
    """Where a write lands: the open order if there is one, else the next open slot.

    Adding to a date with no order yet creates that order, which is what the
    site itself does when you add from a product page.
    """
    o = open_order(sess)
    return o["delivery_date"] if o else next_delivery(sess)


def customer_key(sess: dict) -> str:
    return (os.environ.get("FARM_TO_PEOPLE_CUSTOMER_ID")
            or (sess.get("customer") or {}).get("customer_key") or "")


def set_qty(ctx, code: str, qty: int, date: str, order: dict | None, line: dict | None) -> dict:
    """Cart mutation. POST creates a line; PUT updates one, and qty 0 removes it.

    The verbs are not interchangeable: POST on an existing line returns 400, and
    PUT needs the line's own identity (order_key + order_line_key), which only
    exists once the line does.
    """
    if line is None:
        r = ctx.request.post(f"{API}/api/orders/item", data={
            "item_code": code, "qty_sales_unit": qty, "delivery_date": date,
            "initQuantity": 0, "isPreorder": False})
    else:
        r = ctx.request.put(f"{API}/api/orders/item", data={
            "delivery_date": date, "item_code": code, "isPreorder": False,
            "isSubscribed": bool(line.get("ref_subscription_item")),
            "order_line_key": line.get("name") or f"item_code|{code}",
            "order_key": (order or {}).get("name"),
            "qty_sales_unit": qty, "initQuantity": line.get("qty_sales_unit", 0)})
    if r.status != 200:
        verb = "POST" if line is None else "PUT"
        raise SystemExit(
            f"ftp: cart write refused — {verb} HTTP {r.status} {r.text()[:160]}\n"
            f"  (item={code} qty={qty} date={date})")
    return r.json()


# -------------------------------------------------------------------- usual

def load_usual() -> list[dict]:
    try:
        return json.loads(USUAL_FILE.read_text()).get("items") or []
    except Exception:
        return []


def save_usual(items: list[dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    USUAL_FILE.write_text(json.dumps({"items": items}, indent=2) + "\n")


# ------------------------------------------------------------------ display

def money(v) -> str:
    return f"${float(v):.2f}" if v not in (None, "") else "  —   "


def show_items(items: list[dict], meta: dict, av: dict) -> None:
    for it in items:
        code = it["item_code"]
        m, a = meta.get(code, {}), av.get(code, {})
        unit = it.get("uom_sales") or m.get("salesUnitOfMeasure") or ""
        line = it.get("line_amount")
        flag = "" if in_stock(a) or not a else "  [out of stock]"
        print(f"  {it['qty_sales_unit']:>2} × {it.get('item_name') or m.get('name') or code}")
        print(f"       {unit:<22} {money(it.get('unit_price_sales'))} ea   "
              f"line {money(line)}   {code}{flag}")


# ----------------------------------------------------------------- commands

def cmd_login(a) -> None:
    creds()  # fail on missing credentials before paying for a browser launch
    with _play()() as p:
        b = _browser(p, a.headed)
        ctx = b.new_context(user_agent=UA,
                            extra_http_headers={"Origin": SITE, "Referer": SITE + "/"})
        do_login(ctx, headed=a.headed)
        b.close()


def cmd_cart(a) -> None:
    with _play()() as p:
        b, ctx = _context(p)
        sess = session(ctx)
        orders = sess.get("current_orders") or []
        if a.json:
            print(json.dumps(orders, indent=2))
            b.close()
            return
        cart = open_order(sess)
        codes = sorted({i["item_code"] for o in orders for i in o.get("items") or []})
        meta = catalog(codes)
        for o in orders:
            items = o.get("items") or []
            tag = "CART (editable)" if o.get("status_editing") == "Unlocked" else "locked"
            print(f"\n{o['name']}  {o['delivery_date']}  [{tag}]  "
                  f"{len(items)} items  subtotal {money(o.get('amount_subtotal'))}")
            if o.get("cutoff_date"):
                print(f"  cutoff: {o['cutoff_date']}")
            av = availability([i["item_code"] for i in items], o["delivery_date"]) if items else {}
            show_items(items, meta, av)
        if cart is None:
            nxt = next_delivery(sess)
            print(f"\nNo open order yet. Next delivery date you can order for: {nxt or 'none'}"
                  + ("\nAdding an item will start that order." if nxt else ""))
        b.close()


def cmd_search(a) -> None:
    hits = algolia(a.query, a.limit)
    codes = [h["objectID"] for h in hits]
    av = availability(codes, a.date)
    rows = []
    for h in hits:
        c = h["objectID"]
        p_, s = price_of(av.get(c, {})), in_stock(av.get(c, {}))
        if a.available and not s:
            continue
        rows.append({"item_code": c, "name": h.get("name"), "producer": (h.get("producer") or {}).get("name")
                     if isinstance(h.get("producer"), dict) else h.get("producer"),
                     "unit": h.get("salesUnitOfMeasure"), "price": p_, "in_stock": s,
                     "badge": av.get(c, {}).get("badge_text") or "",
                     "tags": h.get("filter_values") or []})
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("no matches" + (" in stock" if a.available else ""))
        return
    for r in rows:
        mark = " " if r["in_stock"] else "x"
        badge = f"  «{r['badge']}»" if r["badge"] else ""
        print(f"{mark} {money(r['price'])}  {r['name']}")
        print(f"    {(r['unit'] or ''):<20} {(r['producer'] or ''):<28} {r['item_code']}{badge}")
    print(f"\n{len(rows)} shown · 'x' = not available for this delivery date")


def cmd_show(a) -> None:
    meta = catalog([a.code])
    if not meta:
        raise SystemExit(f"ftp: no product {a.code}")
    m = meta[a.code]
    av = availability([a.code], a.date).get(a.code, {})
    if a.json:
        print(json.dumps({"meta": m, "availability": av}, indent=2))
        return
    print(f"{m['name']}  [{a.code}]")
    print(f"  producer   {m.get('producer')}")
    print(f"  unit       {m.get('salesUnitOfMeasure')}")
    print(f"  price      {money(price_of(av))}"
          + (f"   «{av['badge_text']}»" if av.get("badge_text") else ""))
    print(f"  in stock   {in_stock(av)}   qty {av.get('quantity', '—')}")
    print(f"  categories {', '.join(m.get('categories') or []) or '—'}")
    print(f"  tags       {', '.join(m.get('filter_values') or []) or '—'}")
    print(f"  url        {SITE}/product/{m.get('slug')}")
    desc = portable_text(m.get("description"))
    if desc:
        print(f"\n{desc[:600]}")


def _resolve(code_or_query: str) -> str:
    """An item code passes through; anything else is searched, requiring one clear hit."""
    if code_or_query.upper().startswith(("ADD-", "BOX-", "BUN-")):
        return code_or_query.upper()
    hits = algolia(code_or_query, 5)
    if not hits:
        raise SystemExit(f"ftp: nothing matches {code_or_query!r}")
    if len(hits) > 1:
        print(f"ftp: {code_or_query!r} is ambiguous — name the item code:", file=sys.stderr)
        for h in hits:
            print(f"  {h['objectID']}  {h.get('name')}", file=sys.stderr)
        raise SystemExit(1)
    return hits[0]["objectID"]


def _mutate(a, code: str, qty: int, verb: str) -> None:
    with _play()() as p:
        b, ctx = _context(p)
        sess = session(ctx)
        cart = open_order(sess)
        date = target_date(sess)
        if date is None:
            b.close()
            raise SystemExit("ftp: no delivery date is open for ordering right now.")
        cur = next((i for i in (cart or {}).get("items") or [] if i["item_code"] == code), None)
        have = cur.get("qty_sales_unit", 0) if cur else 0
        if qty == have:
            b.close()
            raise SystemExit(f"ftp: {code} is already at qty {have} for {date}.")
        name = (cur or {}).get("item_name") or (catalog([code]).get(code) or {}).get("name") or code
        av = availability([code], date).get(code, {})
        if qty > have and not in_stock(av):
            b.close()
            raise SystemExit(f"ftp: {name} is not available for {date}.")
        where = f"order {cart['name']}" if cart else "a new order"
        print(f"{verb}: {name} [{code}]  {have} → {qty}   {where} for {date}")
        if not a.yes:
            print("\n(dry run — pass --yes to apply)")
            b.close()
            return
        set_qty(ctx, code, qty, date, cart, cur)
        after = open_order(session(ctx))
        if after is None:
            # Emptying an order deletes it — there is no cart left to report.
            print(f"done — {name} removed; the {date} order is now empty and gone.")
        else:
            now = next((i for i in after.get("items") or [] if i["item_code"] == code), None)
            print(f"done — {name} is now {now['qty_sales_unit'] if now else 0} in cart; "
                  f"subtotal {money(after.get('amount_subtotal'))}")
        b.close()


def cmd_add(a) -> None:
    _mutate(a, _resolve(a.item), a.qty, "add")


def cmd_remove(a) -> None:
    _mutate(a, _resolve(a.item), 0, "remove")


def cmd_history(a) -> None:
    with _play()() as p:
        b, ctx = _context(p)
        sess = session(ctx)
        key = customer_key(sess)
        r = ctx.request.get(f"{API}/api/user-items/all-reorder/{key}")
        data = (r.json() or {}).get("data") or {}
        b.close()
    rows = sorted(data.items(), key=lambda kv: -(kv[1].get("number_times_purchased") or 0))
    rows = rows[:a.limit]
    meta = catalog([c for c, _ in rows])
    out = [{"item_code": c, "name": (meta.get(c) or {}).get("name"),
            "times": v.get("number_times_purchased"), "last": v.get("last_date_purchased")}
           for c, v in rows]
    if a.json:
        print(json.dumps(out, indent=2))
        return
    for o in out:
        print(f"  {o['times']:>3}×  last {o['last']}  {o['name'] or ''}  [{o['item_code']}]")


def cmd_usual(a) -> None:
    items = load_usual()
    if a.from_history:
        with _play()() as p:
            b, ctx = _context(p)
            key = customer_key(session(ctx))
            data = (ctx.request.get(f"{API}/api/user-items/all-reorder/{key}").json() or {}).get("data") or {}
            b.close()
        top = sorted(data.items(), key=lambda kv: -(kv[1].get("number_times_purchased") or 0))
        top = [c for c, v in top if (v.get("number_times_purchased") or 0) >= a.min_times][:a.limit]
        meta = catalog(top)
        items = [{"item_code": c, "qty": 1, "name": (meta.get(c) or {}).get("name")} for c in top]
        save_usual(items)
        print(f"seeded {len(items)} items into {USUAL_FILE} "
              f"(purchased ≥{a.min_times}×) — edit it to taste")
    if not items:
        raise SystemExit(f"ftp: no default cart yet — run `usual --from-history` to seed {USUAL_FILE}")
    if a.list:
        for it in items:
            print(f"  {it.get('qty', 1)} × {it.get('name') or ''}  [{it['item_code']}]")
        return
    with _play()() as p:
        b, ctx = _context(p)
        sess = session(ctx)
        cart = open_order(sess)
        date = target_date(sess)
        if date is None:
            b.close()
            raise SystemExit("ftp: no delivery date is open for ordering right now.")
        lines = {i["item_code"]: i for i in (cart or {}).get("items") or []}
        have = {c: l.get("qty_sales_unit", 0) for c, l in lines.items()}
        av = availability([i["item_code"] for i in items], date)
        plan = []
        for it in items:
            c, want = it["item_code"], it.get("qty", 1)
            if not in_stock(av.get(c, {})):
                plan.append((c, it.get("name"), have.get(c, 0), None, "unavailable"))
            elif have.get(c, 0) >= want:
                plan.append((c, it.get("name"), have.get(c, 0), None, "already in cart"))
            else:
                plan.append((c, it.get("name"), have.get(c, 0), want, ""))
        print(f"{cart['name'] if cart else 'new order'} for {date}:")
        for c, name, cur, want, note in plan:
            act = f"{cur} → {want}" if want else note
            print(f"  {money(price_of(av.get(c, {}))):>8}  {(name or c)[:44]:<46} {act}")
        todo = [(c, n, cur, want) for c, n, cur, want, _ in plan if want]
        if not todo:
            print("\nnothing to add — the usual is already in the cart.")
            b.close()
            return
        if not a.yes:
            print(f"\n({len(todo)} to add — dry run, pass --yes to apply)")
            b.close()
            return
        for c, n, cur, want in todo:
            set_qty(ctx, c, want, date, cart, lines.get(c))
            cart = open_order(session(ctx))  # the order appears on the first add
            lines = {i["item_code"]: i for i in (cart or {}).get("items") or []}
            print(f"  added {n or c}")
        after = open_order(session(ctx))
        print(f"done — {len((after or {}).get('items') or [])} items, "
              f"subtotal {money((after or {}).get('amount_subtotal'))}")
        b.close()


SEASONAL_CATS = ["produce", "vegetables", "fruit", "new", "new-seasonal"]

# Products hang off a category's featuredProducts; categories form a parent tree,
# so one level of children pulls in the sub-categories (Tomatoes, Leafy Greens, …).
POOL_GROQ = ('array::unique(*[_type=="productCategory" && '
             '(slug.current in $cats || parent->slug.current in $cats)]'
             '.featuredProducts[]._ref)')


def cmd_suggest(a) -> None:
    """In-season and affordable: whatever is actually in stock for the delivery date.

    Seasonality is not a label here — it is availability. A CSA-style shop only
    lists what its farms are cutting this week, so in-stock *is* in-season.
    """
    cats = a.category or SEASONAL_CATS
    pool = sanity(POOL_GROQ, cats=cats)
    pool = [c for c in pool if isinstance(c, str)]
    if not pool:
        raise SystemExit(f"ftp: no products found for categories {cats}")

    history, date = {}, a.date
    if a.date is None or a.mine:
        with _play()() as p:
            b, ctx = _context(p)
            sess = session(ctx)
            date = a.date or target_date(sess)
            if a.mine:
                key = customer_key(sess)
                r = ctx.request.get(f"{API}/api/user-items/all-reorder/{key}")
                history = (r.json() or {}).get("data") or {}
            b.close()

    av = availability_all(pool, date)
    keep = []
    for c in pool:
        a_ = av.get(c, {})
        if not in_stock(a_):
            continue
        pr = price_of(a_)
        if pr is None or pr > a.max_price:
            continue
        try:
            std = float(a_.get("standard_sales_price") or pr)
        except ValueError:
            std = pr
        keep.append((c, pr, std > pr, a_.get("badge_text") or ""))

    # Rank before naming, so the catalog lookup only covers what we will print.
    keep.sort(key=lambda x: (-(history.get(x[0]) or {}).get("number_times_purchased", 0),
                             not x[2], x[1]))
    keep = keep[:a.limit]
    meta = catalog([c for c, *_ in keep])

    picks = [{"item_code": c, "name": (meta.get(c) or {}).get("name") or c,
              "price": pr, "on_sale": sale, "badge": badge,
              "unit": (meta.get(c) or {}).get("salesUnitOfMeasure"),
              "producer": (meta.get(c) or {}).get("producer"),
              "tags": (meta.get(c) or {}).get("filter_values") or [],
              "times": (history.get(c) or {}).get("number_times_purchased", 0)}
             for c, pr, sale, badge in keep]

    if a.json:
        print(json.dumps({"delivery_date": date, "pool": len(pool), "picks": picks}, indent=2))
        return
    print(f"in season & affordable for {date or 'the next delivery'} "
          f"(under {money(a.max_price)}, {len(pool)} products considered):\n")
    for pk in picks:
        marks = []
        if pk["on_sale"]:
            marks.append("SALE")
        if pk["badge"]:
            marks.append(pk["badge"])
        if pk["times"]:
            marks.append(f"bought {pk['times']}x")
        if "Local" in pk["tags"]:
            marks.append("Local")
        print(f"  {money(pk['price'])}  {pk['name']}")
        print(f"      {(pk['unit'] or ''):<18} {(pk['producer'] or '')[:26]:<28} "
              f"{pk['item_code']}  {' · '.join(marks)}")
    print(f"\n{len(picks)} picks · add one with: add <item_code> --yes")


def main() -> None:
    ap = argparse.ArgumentParser(prog="farmtopeople",
                                description="Farm to People cart (browse keyless, change via login).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("login", cmd_login, "sign in and save the session")
    s.add_argument("--headed", action="store_true", help="show the browser (use if a challenge appears)")

    s = add("cart", cmd_cart, "show current orders; the Unlocked one is the cart")
    s.add_argument("--json", action="store_true")

    s = add("search", cmd_search, "search the catalog (keyless)")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.add_argument("--date", help="delivery date YYYY-MM-DD for price/stock")
    s.add_argument("--available", action="store_true", help="only what's in stock")
    s.add_argument("--json", action="store_true")

    s = add("show", cmd_show, "product detail (keyless)")
    s.add_argument("code")
    s.add_argument("--date")
    s.add_argument("--json", action="store_true")

    s = add("add", cmd_add, "add an item to the cart (requires --yes)")
    s.add_argument("item", help="item code, or a search term matching exactly one product")
    s.add_argument("-q", "--qty", type=int, default=1)
    s.add_argument("--yes", action="store_true", help="actually do it")

    s = add("remove", cmd_remove, "remove an item from the cart (requires --yes)")
    s.add_argument("item", help="item code, or a search term matching exactly one product")
    s.add_argument("--yes", action="store_true", help="actually do it")

    s = add("history", cmd_history, "most-purchased items")
    s.add_argument("-n", "--limit", type=int, default=30)
    s.add_argument("--json", action="store_true")

    s = add("usual", cmd_usual, "add the default cart (requires --yes)")
    s.add_argument("--list", action="store_true", help="print the default cart and stop")
    s.add_argument("--from-history", action="store_true", help="(re)seed it from purchase history")
    s.add_argument("--min-times", type=int, default=4, help="seed threshold (default 4)")
    s.add_argument("-n", "--limit", type=int, default=20, help="seed size (default 20)")
    s.add_argument("--yes", action="store_true", help="actually do it")

    s = add("suggest", cmd_suggest, "in-season, in-stock, affordable picks")
    s.add_argument("-c", "--category", action="append", help="repeatable Sanity category slug")
    s.add_argument("--max-price", type=float, default=12.0)
    s.add_argument("-n", "--limit", type=int, default=15)
    s.add_argument("--pool", type=int, default=300, help="catalog rows to consider")
    s.add_argument("--mine", action="store_true", help="rank things you buy often first")
    s.add_argument("--date")
    s.add_argument("--json", action="store_true")

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
