---
name: farmtopeople
description: |
  Manage the Farm to People grocery cart — search the catalog, check what's in
  season and on sale, add and remove items, and load a default "usual" cart.
  Also handles refund requests for damaged/spoiled items.
  Use when the user asks what's available or in season at Farm to People, wants
  something added to or taken out of their cart, asks what's in the cart or what
  they usually order, or says to add the usual, or reports a damaged item.
license: ISC
---

# Farm to People

`scripts/farmtopeople.py` — reads need nothing; writes need two env vars.

## Two paths

Every command takes one, and the split governs every choice below:

| | **keyless** | **session** |
|---|---|---|
| commands | `search` `show` `suggest`* | `cart` `add` `remove` `usual` `history` `login` |
| how | Algolia + Sanity + the availability endpoint | `api.farmtopeople.com` with a saved cookie jar |
| needs | nothing | `FARM_TO_PEOPLE_USERNAME`, `FARM_TO_PEOPLE_PASSWORD` |
| cost | instant | ~5s browser start |

\* `suggest` is keyless once you pass `--date`; without one it reads the session
to learn which delivery date to price against.

Stay **keyless** for anything you're only reading — "what tomatoes do they have",
"how much are the eggs", "what's cheap this week" all resolve without a browser
or the user's credentials. Reach for **session** only to see or change the cart.

Writes need `--yes`. Without it every write prints what it would do and stops —
that is the confirm gate, not a bug to work around.

Run session commands through `uv` (`uv run scripts/farmtopeople.py …`) so
Playwright resolves. First write on a machine needs a browser once:

```sh
uv run --with playwright==1.49.1 playwright install chromium
```

The pin is deliberate — later Playwright ships no macOS 13 Chromium. The script
falls back to a system Google Chrome if the bundled build is missing.

## The cart is an order

`/api/customers/session` returns `current_orders`, and each carries a
`status_editing`:

- **`Unlocked`** — the cart. The one order you can change.
- **`Locked`** — past its cutoff and on its way. Nothing here can touch it, and
  attempting to is the most likely way to confuse a user about what changed.

**Having no unlocked order is the normal resting state**, not an error. When the
last order locks, there is simply no cart until something is added — and adding
starts one for the next open delivery date, which is what `cart` reports when it
finds nothing editable. So "there's no cart" is never the answer to give; the
answer is which date the next add would land on.

Every price, every stock check, and every write is scoped to **one delivery
date**. The same item can be $5.99 and in stock for Thursday and unavailable for
Friday, so quote the date alongside the price.

## Adding is buying

**There is no checkout.** Farm to People charges the card on file for whatever
sits in the cart when the cutoff passes — the site says so in the drawer: *"No
Checkout Required! You'll be automatically charged for items in your cart after
the cutoff time."*

So `add --yes` is not staging a basket for the user to review later; it commits
them to buying that item unless someone removes it before the cutoff. Confirm
every add with the user and quote the price, and say the cutoff back to them
when `cart` reports one.

The other side of the same rule: **orders under the $20.00 minimum are cancelled
at the cutoff**, not delivered. A cart holding $1.29 of garlic buys nothing and
silently disappears — so when a cart is under the minimum, say so rather than
reporting it as a live order.

## Workflow

Narrow with keyless reads, then act once:

1. **Find the item code.** `search <term>` returns codes like `ADD-VEG-1389`.
   The code is the join key across all three backends and is stable; a search
   term is not. `add` and `remove` accept a search term only when it matches
   exactly one product, and list the candidates when it doesn't.
2. **Check it's available for the date.** `search --available` hides what can't
   be delivered; `show <code>` gives the price, the stock, and any sale badge.
3. **Confirm with the user**, naming the item, the price, and the delivery date
   you resolved to — and remember an add is a purchase, not a draft.
4. **Act**: `add <code> --yes` or `remove <code> --yes`.
5. **Verify with `cart`.**

Done when `cart` shows the item at the quantity you intended. Report what `cart`
shows — a write that returned 200 is a claim, and `cart` is the evidence.

## Commands

```bash
S=scripts/farmtopeople.py
uv run $S search "tomato" --available      # keyless; --date YYYY-MM-DD to price it
uv run $S show ADD-FRU-0355                # price, stock, tags, description
uv run $S suggest --mine                   # in season, in stock, cheap, ranked by what they buy
uv run $S cart                             # every current order; the Unlocked one is the cart
uv run $S add ADD-VEG-1389 --yes           # -q N for quantity
uv run $S remove ADD-VEG-1389 --yes
uv run $S history -n 30                    # most-purchased, with counts and last date
uv run $S usual --list                     # the default cart
uv run $S usual --yes                      # add everything missing from it
uv run $S usual --from-history --min-times 6   # (re)seed it from real purchases
uv run $S login --headed                   # only if a challenge appears
```

`--json` on `search`, `show`, `suggest`, `cart`, `history` for piping.

## The usual

`~/.config/farmtopeople/usual.json` is the default cart — a plain list of item
codes and quantities, safe to hand-edit.

Seed it from evidence rather than guesswork: `usual --from-history` ranks the
account's real purchase history (`number_times_purchased`) and writes the top N.
`usual --yes` then adds only what's **missing** — items already in the cart are
left at their current quantity, so running it twice is safe.

Items in the default cart that are out of stock for the delivery date are
reported as unavailable and skipped, never silently dropped.

Because the whole cart is auto-charged at the cutoff, `usual --yes` is the
highest-value write in this skill and the one most worth confirming first: it
can commit a dozen items at once. Its dry run lists every line and the total it
would build, which is what to show the user before passing `--yes`.

## In season means in stock

`suggest` treats availability as the seasonality signal: a CSA-style shop only
lists what its farms are cutting this week, so what's in stock for the delivery
date *is* what's in season. It pools ~1,200 products from the produce category
tree, prices them all for the date, keeps what's in stock under `--max-price`,
and ranks sale items first — or, with `--mine`, the user's own repeat buys first.

`-c/--category` overrides the pool with any category slug (`citrus`, `greens`,
`tree-fruit`, `roots-tubers`, `bakery`, …).

## Refunds & damaged items

Farm to People's FAQ says: *"If an item is broken/spoiled/etc., please take a photo so we can inform the maker, farmer, and/or packing team."*

**Process:**

1. **Check the order.** Run `cart --json` to get the customer ID (`CUST-XXXXXXX`), order name (`OR-XXXXXXX`), delivery date, and the specific items with their codes and prices.

2. **Get the FAQ policy** from the site if needed: the "Something is wrong with my order. What can I do?" accordion says to email photos to **questions@farmtopeople.com** or text to **(347) 455-0387**.

3. **Compose an email via himalaya** (requires the himalaya skill and ProtonMail Bridge configured for brian@abelson.live). Use MML syntax for photo attachments:

```bash
cat << 'EOF' | himalaya template send
From: Brian Abelson <brian@abelson.live>
To: questions@farmtopeople.com
Subject: Damaged items - <description> (Order <order-name>)

Account: <CUST-ID>
Order: <order-name> (delivered <date>)

<description of what's wrong>

1. <item name> (<item-code>) - $<price>
2. <item name> (<item-code>) - $<price>

Photos of the damaged items attached as received.

Please advise on credit/refund.

Thanks,
Brian

<#multipart type=mixed>
<#part type=image/jpeg filename=<path-to-photo-1>><#/part>
<#part type=image/jpeg filename=<path-to-photo-2>><#/part>
<#/multipart>
EOF
```

4. **Verify delivery** by checking `Message successfully sent!` in the output.

Photos the user sends should be found in `/opt/data/cache/images/` — check the filenames from the user's messages or image URLs.

## Gotchas

- **`batch_availability` is POST-only.** A GET returns `403 "unauthorized"`,
  which reads like an auth problem and is really a method problem.
- **Two-thirds of the Algolia index is hidden.** 3,615 of 5,447 docs carry
  `hiddenInSearch: true`; the script filters them out. Without that filter,
  search surfaces discontinued items that can never be added.
- **Algolia's `objectID` *is* the item code** — no mapping table needed between
  search results, Sanity metadata, and cart writes.
- **Products carry no category field.** Membership lives the other way round, in
  each category's `featuredProducts`, and categories form a `parent`/`children`
  tree — so a category pool must union the category *and* its children.
- **Sanity `description` is Portable Text**, not a string. `portable_text()`
  flattens it; printing the raw field dumps block JSON at the user.
- **A sub-minimum order vanishes at the cutoff.** An order under $20.00 is
  cancelled rather than delivered, so a small cart left alone simply disappears.
  Re-read `cart` rather than trusting an earlier add.
- **POST creates a line, PUT changes one — they are not interchangeable.**
  POST on a line that already exists returns 400, and PUT is what sets a new
  quantity, with `qty_sales_unit: 0` as the removal. `set_qty` picks the verb by
  whether the item is already in the cart.
- **PUT needs the line's identity**, which POST does not: `order_key` (the order
  name, `OR-…`) and `order_line_key`. That second one is the cart item's `name`
  field, whose value is the odd-looking `item_code|ADD-VEG-1389` — it looks like
  a bug and is actually the key. A PUT missing either field returns 400, which
  reads exactly like "qty 0 is invalid" and is not.
- **Emptying an order deletes it.** Removing the last item leaves no unlocked
  order at all, so re-reading the cart after a removal correctly returns nothing
  rather than an empty cart.
- **There is no checkout to withhold.** This skill has no "place order" command
  because the platform has no such step — the cutoff places the order for you.
  That makes the confirm gate on `add` and `usual` the only thing standing
  between a request and a charge, which is why they need `--yes`.
- **A stale session re-authenticates silently** from the env vars, so a write
  failing with a sign-in error means the credentials are wrong, not the cookie.
