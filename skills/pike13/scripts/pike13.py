#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.49.1"]  # last build with macOS 13 chromium
# ///
"""Pike13 gym class CLI — read the schedule keyless, book/waitlist via a saved login.

Two paths, and the split governs everything:

  keyless — GET /api/v2/front/* with the public client_id embedded in Pike13's
            own web frontend. No login, no app registration, instant.
            Covers: schedule, capacity, waitlist-full, class lookup.

  session — Playwright driving the real booking UI, signed in with
            $PIKE13_EMAIL / $PIKE13_PASSWORD. Pike13 exposes no client-facing
            write API without an approved OAuth app, so writes go through the
            page. Covers: book, waitlist, mine.

Booking spends a plan credit and cancelling late can incur a fee, so every
write requires --yes. The password is read from the environment and never
written to disk; only the resulting session cookies are cached, mode 0600.

Environment:
  PIKE13_DOMAIN     gym subdomain (default fuerzatrainingsystems)
  PIKE13_EMAIL      login email      — writes only
  PIKE13_PASSWORD   login password   — writes only
  PIKE13_STATE_DIR  session cache dir (default ~/.config/pike13)
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DOMAIN = os.environ.get("PIKE13_DOMAIN", "fuerzatrainingsystems")
# Public client_id lifted from Pike13's own schedule page. Unauthenticated
# front-API reads require *a* client_id; this is the one their frontend ships.
# If it ever rotates, `refresh_client_id()` re-scrapes it.
FALLBACK_CLIENT_ID = "WWgvG1fId8iDU3rgoFXvz4A2kLnxDBSsOFacfk8X"
STATE_DIR = Path(os.environ.get("PIKE13_STATE_DIR", Path.home() / ".config" / "pike13"))
STATE_FILE = STATE_DIR / "session.json"
CONF_FILE = STATE_DIR / "config.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def base() -> str:
    return f"https://{DOMAIN}.pike13.com"


# ------------------------------------------------------------------ keyless

def _conf() -> dict:
    try:
        return json.loads(CONF_FILE.read_text())
    except Exception:
        return {}


def client_id() -> str:
    return os.environ.get("PIKE13_CLIENT_ID") or _conf().get("client_id") or FALLBACK_CLIENT_ID


def refresh_client_id() -> str | None:
    """Re-scrape the client_id from the public schedule page."""
    try:
        html = _get_text(f"{base()}/schedule")
    except Exception:
        return None
    m = re.search(r'client_id\s*=\s*"([A-Za-z0-9_-]{20,})"', html)
    if not m:
        return None
    cid = m.group(1)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conf = _conf()
    conf["client_id"] = cid
    CONF_FILE.write_text(json.dumps(conf, indent=2))
    return cid


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def api(path: str, **params) -> dict:
    """GET a front-API endpoint with the public client_id."""
    for attempt in (1, 2):
        params["client_id"] = client_id()
        url = f"{base()}/api/v2/front/{path}?" + urllib.parse.urlencode(params)
        try:
            return json.loads(_get_text(url))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 1 and refresh_client_id():
                continue  # client_id rotated; retry once with the fresh one
            body = e.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"pike13: HTTP {e.code} on {path} — {body}")
        except urllib.error.URLError as e:
            raise SystemExit(f"pike13: network error on {path} — {e.reason}")
    raise SystemExit("pike13: unreachable")


# --------------------------------------------------------------- time utils

def domain_tz(occurrences: list[dict]) -> ZoneInfo:
    for o in occurrences:
        if o.get("timezone"):
            return ZoneInfo(o["timezone"])
    return ZoneInfo("America/New_York")


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_day(s: str, tz: ZoneInfo) -> datetime:
    """Accept today/tomorrow/a weekday name/+Nd/YYYY-MM-DD."""
    now = datetime.now(tz)
    s = (s or "today").strip().lower()
    if s == "today":
        d = now
    elif s == "tomorrow":
        d = now + timedelta(days=1)
    elif m := re.fullmatch(r"\+(\d+)d?", s):
        d = now + timedelta(days=int(m.group(1)))
    elif s in WEEKDAYS:
        ahead = (WEEKDAYS.index(s) - now.weekday()) % 7
        d = now + timedelta(days=ahead or 7)
    else:
        try:
            d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError:
            raise SystemExit(f"pike13: can't read date {s!r} "
                             "(try today, tomorrow, thursday, +3d, 2026-08-14)")
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def local(iso: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)


# ------------------------------------------------------------------- render

def capacity_note(o: dict) -> str:
    if o.get("full"):
        wl = o.get("waitlist") or {}
        return "FULL, waitlist full" if wl.get("full") else "FULL, waitlist open"
    n = o.get("capacity_remaining")
    if n is None:
        return "open"
    return f"{n} left" if n <= 3 else f"{n} open"


def show_schedule(occs: list[dict], tz: ZoneInfo, as_json: bool) -> None:
    if as_json:
        print(json.dumps(occs, indent=2))
        return
    if not occs:
        print("no classes in that range")
        return
    day = None
    for o in sorted(occs, key=lambda x: x["start_at"]):
        st = local(o["start_at"], tz)
        if st.date() != day:
            day = st.date()
            print(f"\n{st:%A %b %-d}")
        staff = ", ".join(s["name"] for s in o.get("staff_members") or []) or "—"
        print(f"  {st.strftime('%-I:%M%p').lower():>8}  {o['id']}  "
              f"{o['name'][:38]:<38} {staff[:20]:<20} {capacity_note(o)}")


# ---------------------------------------------------------------- commands

def cmd_schedule(a) -> None:
    tz = ZoneInfo("America/New_York")
    start = parse_day(a.date, tz)
    end = start + timedelta(days=a.days)
    occs = api("event_occurrences",
               **{"from": start.isoformat(), "to": end.isoformat()}).get("event_occurrences", [])
    tz = domain_tz(occs)
    if a.name:
        occs = [o for o in occs if a.name.lower() in (o.get("name") or "").lower()]
    if a.open:
        occs = [o for o in occs if not o.get("full")]
    show_schedule(occs, tz, a.json)


def cmd_show(a) -> None:
    occs = api(f"event_occurrences/{a.id}").get("event_occurrences", [])
    if not occs:
        raise SystemExit(f"pike13: no class with id {a.id}")
    o = occs[0]
    if a.json:
        print(json.dumps(o, indent=2))
        return
    tz = domain_tz(occs)
    st, en = local(o["start_at"], tz), local(o["end_at"], tz)
    print(f"{o['name']}  (id {o['id']})")
    print(f"  {st:%A %b %-d}  {st.strftime('%-I:%M%p').lower()}–{en.strftime('%-I:%M%p').lower()}")
    print(f"  staff:    {', '.join(s['name'] for s in o.get('staff_members') or []) or '—'}")
    print(f"  capacity: {capacity_note(o)}")
    print(f"  url:      {o['url']}")


def cmd_find(a) -> None:
    """Search the next N days for classes matching a name."""
    tz = ZoneInfo("America/New_York")
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    hits = []
    for chunk in range(0, a.days, 7):  # API caps range; walk it a week at a time
        lo = start + timedelta(days=chunk)
        hi = min(lo + timedelta(days=7), start + timedelta(days=a.days))
        hits += api("event_occurrences",
                    **{"from": lo.isoformat(), "to": hi.isoformat()}).get("event_occurrences", [])
    tz = domain_tz(hits)
    hits = [o for o in hits if a.query.lower() in (o.get("name") or "").lower()]
    if a.open:
        hits = [o for o in hits if not o.get("full")]
    show_schedule(hits, tz, a.json)


# ---------------------------------------------------------------- session

def _play():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("pike13: playwright missing — run via `uv run scripts/pike13.py`, "
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
            f"pike13: no usable browser ({e}).\n"
            "  fix: uv run --with playwright==1.49.1 playwright install chromium\n"
            "  (or install Google Chrome — the script falls back to it)")


def creds() -> tuple[str, str]:
    email = os.environ.get("PIKE13_USERNAME") or os.environ.get("PIKE13_EMAIL") or ""
    password = os.environ.get("PIKE13_PASSWORD", "")
    if not (email and password):
        raise SystemExit(
            "pike13: set PIKE13_USERNAME (or PIKE13_EMAIL) and PIKE13_PASSWORD.\n"
            "  export PIKE13_USERNAME='you@example.com'\n"
            "  export PIKE13_PASSWORD='…'")
    return email, password


def signed_in(page) -> bool:
    return page.locator("a.sign_in_trigger").count() == 0


def do_login(ctx, quiet: bool = False) -> None:
    """Sign in with the env-var credentials and persist the session."""
    email, password = creds()
    page = ctx.new_page()
    page.goto(f"{base()}/accounts/sign_in", wait_until="domcontentloaded")
    page.fill("#account_email", email)
    page.fill("#account_password", password)
    try:
        page.check("#account_remember_me")  # longer-lived session
    except Exception:
        pass
    page.click("button[type=submit].confirm_button")
    page.wait_for_load_state("domcontentloaded")
    time.sleep(1.5)

    if "/accounts/sign_in" in page.url or not signed_in(page):
        err = ""
        for sel in (".flash", ".alert", ".error", "[role=alert]"):
            if page.locator(sel).count():
                err = " ".join((page.locator(sel).first.inner_text() or "").split())
                break
        raise SystemExit(f"pike13: sign-in failed{' — ' + err if err else ''}. "
                         "Check PIKE13_EMAIL/PIKE13_PASSWORD, or run "
                         "`login --headed` if a challenge is being shown.")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ctx.storage_state(path=str(STATE_FILE))
    STATE_FILE.chmod(0o600)
    page.close()
    if not quiet:
        print(f"signed in as {email} — session saved to {STATE_FILE}")


def _context(p, headed: bool):
    """A signed-in context: reuse the saved session, else log in with env creds."""
    b = _browser(p, headed)
    if STATE_FILE.exists():
        ctx = b.new_context(storage_state=str(STATE_FILE), user_agent=UA)
        probe = ctx.new_page()
        probe.goto(base(), wait_until="domcontentloaded")
        alive = signed_in(probe)
        probe.close()
        if alive:
            return b, ctx
        ctx.close()  # stale session — fall through and re-auth
    ctx = b.new_context(user_agent=UA)
    do_login(ctx, quiet=True)
    return b, ctx


def cmd_login(a) -> None:
    creds()  # fail on missing credentials before paying for a browser launch
    with _play()() as p:
        b = _browser(p, headed=a.headed)
        ctx = b.new_context(user_agent=UA)
        do_login(ctx)
        b.close()


ACTION_RE = re.compile(
    r"(add to waitlist|join waitlist|sign up|enroll|register|reserve|book)", re.I)
# Enrolling is a workflow: the first click opens a confirmation step whose
# submit is "Finish". Anchored so the sibling "Cancel" can never match.
CONFIRM_RE = re.compile(r"^(finish|confirm|complete|done|submit|check ?out|join waitlist)\b", re.I)


def _action_links(page) -> list[tuple[str, bool]]:
    """(label, enabled) for every control in the event page's .actions region."""
    out = []
    for el in page.locator(".actions a, .actions button").all():
        try:
            label = " ".join((el.inner_text() or "").split())
        except Exception:
            continue
        if not label:
            continue
        cls = (el.get_attribute("class") or "")
        disabled = ("disabled" in cls) or (el.get_attribute("disabled") is not None)
        out.append((label, not disabled))
    return out


def cmd_probe(a) -> None:
    """Dump what the logged-in event page offers — for verifying selectors."""
    with _play()() as p:
        b, ctx = _context(p, a.headed)
        page = ctx.new_page()
        page.goto(f"{base()}/e/{a.id}", wait_until="domcontentloaded")
        print(f"url:       {page.url}")
        print(f"signed in: {signed_in(page)}")
        acts = _action_links(page)
        print(f"actions ({len(acts)}):")
        for label, enabled in acts:
            print(f"  [{'ENABLED ' if enabled else 'disabled'}] {label}")
        if a.dump:
            Path(a.dump).write_text(page.content())
            print(f"html written to {a.dump}")
        b.close()


def _write_action(a, kind: str) -> None:
    """book|waitlist: click the matching control on the event page."""
    occs = api(f"event_occurrences/{a.id}").get("event_occurrences", [])
    if not occs:
        raise SystemExit(f"pike13: no class with id {a.id}")
    o = occs[0]
    tz = domain_tz(occs)
    st = local(o["start_at"], tz)
    print(f"{o['name']} — {st:%A %b %-d} {st.strftime('%-I:%M%p').lower()} — {capacity_note(o)}")

    want_waitlist = kind == "waitlist"
    if not a.yes:
        if want_waitlist:
            print("\nThis would add you to the waitlist for the class above.")
            print("No credit is spent now — one is spent if the waitlist enrols you.")
        else:
            print("\nThis would book you into the class above.")
            print("That spends a plan credit; cancelling late may incur a fee.")
        print("Re-run with --yes to go through with it.")
        return

    creds()  # fail on missing credentials before paying for a browser launch
    with _play()() as p:
        b, ctx = _context(p, a.headed)
        page = ctx.new_page()
        page.goto(f"{base()}/e/{a.id}", wait_until="domcontentloaded")
        if not signed_in(page):
            b.close()
            raise SystemExit("pike13: session expired — run `pike13.py login` again")

        acts = _action_links(page)
        target = None
        for label, enabled in acts:
            hit = ACTION_RE.search(label)
            if not hit or not enabled:
                continue
            is_wl = "waitlist" in label.lower()
            if is_wl == want_waitlist:
                target = label
                break
        if not target:
            b.close()
            offered = "; ".join(f"{l} ({'enabled' if e else 'disabled'})" for l, e in acts) or "none"
            raise SystemExit(f"pike13: no enabled '{kind}' control on that page.\n"
                             f"  page offers: {offered}")

        page.locator(".actions a, .actions button").filter(has_text=target).first.click()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        print(f"clicked: {target}")

        # The first click only opens the workflow; drive it to the end.
        for _ in range(4):
            nxt = next((l for l, en in _action_links(page)
                        if en and CONFIRM_RE.match(l)), None)
            if not nxt:
                break
            page.locator(".actions a, .actions button").filter(has_text=nxt).first.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            print(f"clicked: {nxt}")

        print(f"landed:  {page.url}")
        left = _action_links(page)
        if left:
            print("page now offers: " + "; ".join(l for l, _ in left))
        if "workflow" in page.url:
            print("WARNING: still mid-workflow — this enrolment is NOT complete.")
        b.close()
    print("\nNot done until you see it — run `pike13.py mine` to confirm.")


def cmd_book(a) -> None:
    _write_action(a, "book")


def cmd_waitlist(a) -> None:
    _write_action(a, "waitlist")


def _dashboard(ctx):
    """Open the account dashboard; return (page, person_id)."""
    page = ctx.new_page()
    page.goto(base(), wait_until="domcontentloaded")
    pid = None
    for el in page.locator('a[href*="/people/"]').all():
        if m := re.search(r"/people/(\d+)", el.get_attribute("href") or ""):
            pid = m.group(1)
            break
    if not pid:
        raise SystemExit("pike13: couldn't find your person id — is the session valid?")
    page.goto(f"{base()}/people/{pid}", wait_until="domcontentloaded")
    return page, pid


def _txt(loc) -> str:
    try:
        return " ".join((loc.inner_text() or "").split())
    except Exception:
        return ""


def _rows(page, sel: str) -> list[dict]:
    """Parse a dashboard table into {name, when, occurrence_id, visit_id}."""
    out = []
    for row in page.locator(f"{sel} tbody tr").all():
        href, occ = "", None
        for link in row.locator("a[href]").all():
            href = link.get_attribute("href") or ""
            if occ := re.search(r"/e/(\d+)", href):
                break
        if not occ:
            continue  # "view all" footer row, not a class
        when = _txt(row.locator("small").first)
        name, _, staff = _txt(row.locator("h3").first).partition("•")
        vis = re.search(r"/visits/(\d+)", href)
        out.append({
            "name": (name or _txt(row.locator("h3").first)).strip(),
            "when": when.split("•")[0].strip(),
            "staff": (when.split("•")[1].strip() if "•" in when else staff.strip()) or None,
            "occurrence_id": occ.group(1) if occ else None,
            "visit_id": vis.group(1) if vis else None,
        })
    return out


def _plans(page) -> list[dict]:
    out = []
    for row in page.locator("#plans-and-passes-content tbody tr").all():
        name = _txt(row.locator(".plan-name").first)
        if not name:
            continue
        smalls = [_txt(s) for s in row.locator("small").all()]
        out.append({"name": name,
                    "remaining": smalls[0] if smalls else "",
                    "expires": smalls[1] if len(smalls) > 1 else ""})
    return out


def cmd_mine(a) -> None:
    """Read back what you're actually signed up for."""
    with _play()() as p:
        b, ctx = _context(p, a.headed)
        page, pid = _dashboard(ctx)
        plans = _plans(page)
        # The dashboard truncates to 5 and links out; this page carries them all.
        page.goto(f"{base()}/people/{pid}/upcoming", wait_until="domcontentloaded")
        data = {"person_id": pid,
                "plans": plans,
                "upcoming": _rows(page, "#upcoming"),
                "waitlist": _rows(page, "#waitlist_entries")}
        b.close()

    if a.json:
        print(json.dumps(data, indent=2))
        return
    for pl in data["plans"]:
        print(f"  {pl['name']:<34} {pl['remaining']}"
              + (f"   ({pl['expires']})" if pl["expires"] else ""))
    print(f"\nUpcoming ({len(data['upcoming'])})")
    for r in data["upcoming"] or [{}]:
        if not r:
            print("  nothing booked")
            break
        print(f"  {r['occurrence_id']}  visit {r['visit_id']}  "
              f"{r['name'][:30]:<30} {r['when']}")
    print(f"\nWaitlist ({len(data['waitlist'])})")
    for r in data["waitlist"] or [{}]:
        if not r:
            print("  none")
            break
        print(f"  {r['occurrence_id']}{' ' * 16}{r['name'][:30]:<30} {r['when']}")


def cmd_cancel(a) -> None:
    """Cancel a booked visit, by visit id (from `mine`)."""
    creds()
    with _play()() as p:
        b, ctx = _context(p, a.headed)
        page, pid = _dashboard(ctx)
        page.goto(f"{base()}/people/{pid}/upcoming", wait_until="domcontentloaded")
        hit = next((r for r in _rows(page, "#upcoming")
                    if r["visit_id"] == str(a.visit_id)), None)
        if not hit:
            b.close()
            raise SystemExit(f"pike13: no upcoming visit {a.visit_id} — check `mine`")
        print(f"{hit['name']} — {hit['when']}")
        if not a.yes:
            b.close()
            print("\nThis would cancel the booking above.")
            print("Past the class's cutoff this incurs a late-cancel fee.")
            print("Re-run with --yes to go through with it.")
            return

        page.goto(f"{base()}/e/{hit['occurrence_id']}/visits/{a.visit_id}",
                  wait_until="domcontentloaded")
        link = page.locator("a.cancel-visit").first
        if not link.count():
            b.close()
            raise SystemExit("pike13: no cancel control on that visit page "
                             "(already cancelled, or past the cutoff)")
        link.click()
        # the control opens a confirm modal whose submit may say "Cancel Visit"
        # or "Late Cancel" depending on cutoff. Match by class, not text.
        try:
            page.locator("a.modal_confirm").first.click(timeout=5000)
        except Exception:
            pass
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        b.close()
    print("\nCancel submitted — run `pike13.py mine` to confirm it's gone.")


# ------------------------------------------------------------- leave waitlist

def cmd_leave_waitlist(a) -> None:
    """Remove yourself from a class waitlist by occurrence id (from `mine`)."""
    creds()
    with _play()() as p:
        b, ctx = _context(p, a.headed)
        page = ctx.new_page()
        page.goto(f"{base()}/e/{a.id}", wait_until="domcontentloaded")

        rm = page.locator(".remove-from-waitlist")
        if not rm.count():
            b.close()
            raise SystemExit(f"pike13: not on the waitlist for class {a.id}, "
                             "or remove control not found.")
        submit = rm.get_attribute("data-confirm-submit") or "Remove"
        print(f"Remove from waitlist for {a.id}")
        if not a.yes:
            b.close()
            print("\nThis would remove you from the waitlist for the class above.")
            print("Re-run with --yes to go through with it.")
            return

        rm.click()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(1.5)
        confirm = page.locator(f".modal_confirm:has-text('{submit}')")
        if confirm.count():
            confirm.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            print(f"Removed from waitlist.")
        else:
            confirm = page.locator(".modal_confirm.fa-check")
            if confirm.count():
                confirm.click()
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                print("Removed from waitlist.")
            else:
                b.close()
                raise SystemExit("pike13: could not find confirm button in modal.")
        b.close()
    print("\nDone — run `pike13.py mine` to verify.")


# -------------------------------------------------------------------- main

def main() -> None:
    global DOMAIN
    ap = argparse.ArgumentParser(
        prog="pike13", description="Gym class schedule and booking (Pike13).")
    ap.add_argument("--domain", help=f"Pike13 subdomain (default: $PIKE13_DOMAIN, else {DOMAIN})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("schedule", cmd_schedule, "list classes (keyless)")
    s.add_argument("date", nargs="?", default="today",
                   help="today|tomorrow|thursday|+3d|YYYY-MM-DD")
    s.add_argument("-d", "--days", type=int, default=1, help="days to cover (default 1)")
    s.add_argument("-n", "--name", help="only classes whose name contains this")
    s.add_argument("--open", action="store_true", help="hide full classes")
    s.add_argument("--json", action="store_true")

    s = add("find", cmd_find, "search upcoming classes by name (keyless)")
    s.add_argument("query")
    s.add_argument("-d", "--days", type=int, default=14, help="days ahead (default 14)")
    s.add_argument("--open", action="store_true", help="hide full classes")
    s.add_argument("--json", action="store_true")

    s = add("show", cmd_show, "detail for one class (keyless)")
    s.add_argument("id")
    s.add_argument("--json", action="store_true")

    s = add("login", cmd_login, "sign in with $PIKE13_EMAIL/$PIKE13_PASSWORD and save the session")
    s.add_argument("--headed", action="store_true", help="show the browser (use if a challenge appears)")

    for name, fn, h in (("book", cmd_book, "book a class"),
                        ("waitlist", cmd_waitlist, "join a class waitlist")):
        s = add(name, fn, h + " (needs login; requires --yes)")
        s.add_argument("id")
        s.add_argument("--yes", action="store_true", help="actually do it")
        s.add_argument("--headed", action="store_true", help="show the browser")

    s = add("mine", cmd_mine, "what you're signed up for (needs login)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--headed", action="store_true")

    s = add("leave-waitlist", cmd_leave_waitlist, "leave a class waitlist by occurrence id (needs login; requires --yes)")
    s.add_argument("id")
    s.add_argument("--yes", action="store_true", help="actually do it")
    s.add_argument("--headed", action="store_true")

    s = add("cancel", cmd_cancel, "cancel a booked visit by visit id (requires --yes)")
    s.add_argument("visit_id")
    s.add_argument("--yes", action="store_true", help="actually do it")
    s.add_argument("--headed", action="store_true")

    s = add("probe", cmd_probe, "dump an event page's controls (needs login)")
    s.add_argument("id")
    s.add_argument("--dump", help="write page HTML to this file")
    s.add_argument("--headed", action="store_true")

    a = ap.parse_args()
    if a.domain:
        DOMAIN = a.domain
    a.fn(a)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
