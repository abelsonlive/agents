---
name: pike13
description: |
  Book gym classes on Pike13 — schedule, capacity, booking, and waitlists at
  Fuerza Training Systems. Use when the user asks what classes are on or
  whether one is full, wants to book or reserve a class, wants on or off a
  waitlist, or asks what they're signed up for.
license: ISC
---

# Pike13 Gym Booking

`scripts/pike13.py` — reads need nothing; writes need two env vars.

## Two paths

Every command takes one, and the split governs every choice below:

| | **keyless** | **session** |
|---|---|---|
| commands | `schedule` `find` `show` | `book` `waitlist` `cancel` `mine` `probe` |
| how | front API + Pike13's own public `client_id` | Playwright driving the real booking page |
| needs | nothing | `PIKE13_EMAIL`, `PIKE13_PASSWORD` |
| cost | instant | ~5s browser start |

Stay **keyless** for anything you're only reading — "what's on Thursday", "is
the 6pm full", "when's the next open barbell class" all resolve without a
browser or the user's credentials. Reach for **session** only to change
something.

Writes need `--yes`. Without it every write command prints what it would do and
stops — that is the confirm gate, not a bug to work around.

Run writes through `uv` (`uv run scripts/pike13.py …`) so Playwright resolves;
reads work under plain `python3`. First write on a machine needs a browser once:

```sh
uv run --with playwright==1.49.1 playwright install chromium
```

The pin is deliberate — later Playwright ships no macOS 13 Chromium. The script
falls back to a system Google Chrome if the bundled build is missing.

## Workflow

Narrow with keyless reads, then act once:

1. **Find the occurrence id.** `schedule <day>` for a day, `find <name>` to
   search ahead. Every class instance has its own id — Monday 6pm and Tuesday
   6pm are different ids, and an id from earlier in the conversation is stale.
   Re-read rather than reuse.
2. **Read its capacity.** `full: false` → book it. `FULL, waitlist open` →
   waitlist is the only move. `FULL, waitlist full` → nothing to do; say so.
3. **Confirm with the user**, naming the class, day, and time you resolved to.
   Booking **spends** a plan credit, and cancelling after the cutoff on the
   event page costs a fee — so a misread day is expensive, not merely wrong.
4. **Act**: `book <id> --yes` or `waitlist <id> --yes`.
5. **Verify with `mine`.**

Done when `mine` lists the class. Report what `mine` shows — a click that landed
on a page is a claim, and `mine` is the evidence. This has already caught one
real failure: an `Enroll` that looked like success but had only opened a
confirmation step.

## Commands

```bash
S=scripts/pike13.py
python3 $S schedule today                 # today, every class
python3 $S schedule thursday --open       # next Thursday, hide full ones
python3 $S schedule +3d -d 4              # 4 days starting 3 days out
python3 $S find "BARBELL" -d 14 --open    # next 2 weeks, open slots only
python3 $S show 270871754                 # one class in detail
uv run $S book 286763594 --yes            # spends a credit
uv run $S waitlist 270871754 --yes        # when it's full
uv run $S mine                            # bookings, waitlist, visits left
uv run $S cancel 677313291 --yes          # by visit id, from `mine`
```

`--json` on `schedule`, `find`, `show`, `mine` for piping. `probe <id>` dumps
the live page's controls — reach for it whenever a write can't find its control.

`mine` is also where cancellation starts: it prints a `visit <id>` per booking,
and that visit id is what `cancel` takes.

## Waitlists

**There is no position, and nothing can move the user up.** Pike13's waitlist
entry carries only `id`, `person_id`, `event_occurrence_id`, `state`, and
`created_at` — no rank field, and no reorder endpoint in either the client or
staff API. Order follows `created_at`, so entering earlier is the only lever
that exists. When asked how far up the list they are, say the platform doesn't
expose it.

`state` runs `waiting` → `pending` (a spot opened and is being held for them,
briefly) → `enrolled`. A `pending` entry is a countdown: surface it promptly.

The two things that genuinely help: enter the waitlist as soon as the class
appears, and watch for cancellations, since a freed spot may return to open
capacity where `book` can take it.

## Gotchas

- **Class names are inconsistent in the real data** — `STRENGTH (BARBELL)`,
  `STRENGTH(BARBELL)`, and `STRENGTH (BARBELL))` are all live at this gym.
  Match on a distinctive fragment (`BARBELL`, `CONDITIONING`) rather than a
  whole name.
- **Everything renders in the gym's timezone** (`America/New_York`) while the
  API speaks UTC. Quote the script's printed times back verbatim.
- **`--open` hides full classes**, which is usually what the user means by
  "what can I get into" — but drop it when they ask what's *scheduled*, or
  you'll hide the class they wanted to waitlist.
- **The visits counter doesn't predict what's bookable.** `mine` can read
  "3 of 3 visits remaining this week" while a given class still refuses with
  `Plan or pass required to join waitlist` — and a different class the same week
  offers an enabled `Enroll`. Pike13 weighs plan coverage, allocation to
  upcoming bookings, and class state together, so treat the counter as context
  and the page's own control as the verdict.
- **The page states that verdict in words** — `Enroll`, `Already waitlisted`,
  `Plan or pass required to join waitlist`. `probe <id>` prints them with
  enabled/disabled, diagnosing a refused write in one call. Quote the page's
  wording back to the user rather than inferring a cause.
- **Enrolling is two clicks, not one.** `Enroll` only opens a confirmation
  workflow whose submit is `Finish`; stopping after the first click leaves the
  seat unbooked while the page looks like success. The script drives the
  workflow to the end and warns if the URL still says `workflow`, which is
  exactly the case `mine` exists to catch.
- **A stale session re-authenticates silently** from the env vars, so a write
  failing with a sign-in error means the credentials are wrong, not the cookie.
- The gym runs near capacity — most classes are already `FULL, waitlist open`.
  Expect waitlisting to be the common path, not the exception.

Deeper API detail — endpoint catalog, eligibility codes, rate limits, and the
OAuth route that would remove Playwright entirely — is in
[`references/api.md`](references/api.md). Load it when a call misbehaves or you
need a field this skill doesn't surface.
