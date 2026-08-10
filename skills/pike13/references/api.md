# Pike13 API reference

Findings verified against `fuerzatrainingsystems.pike13.com` on 2026-08-10.
Official docs: <https://developer.pike13.com/docs/api/v2>.

## Why reads need no credentials

Unauthenticated front-API calls require *a* `client_id`. Pike13's own Angular
schedule app ships one in the page source:

```sh
curl -s https://<domain>.pike13.com/schedule | grep -o 'client_id = "[^"]*"'
```

That value drives every read command. `scripts/pike13.py` hardcodes it as
`FALLBACK_CLIENT_ID` and re-scrapes automatically on a 401/403, so rotation
self-heals. Override with `$PIKE13_CLIENT_ID`.

This gets **reads only**. Any endpoint scoped to a person (`people/me`,
eligibility, visits, waitlist entries) returns `404 Object not found` without a
Bearer token — the app is resolved, but no person is attached.

## Base

```text
https://<domain>.pike13.com/api/v2/front/<path>?client_id=<id>
```

`front` is the client-facing namespace; `desk` is staff-only and returns 403
here. Rate limits: **180 req/min** per token, **360 req/min** per IP. Headers:
`RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`. Pagination via
`page`, default 20 per page, `per_page` max 100.

## Reads that work keyless

### `GET event_occurrences`

Params: `from`, `to` (ISO8601, both required together), `location_ids`,
`service_ids`, `event_ids`.

```json
{"id": 270871754, "event_id": 9173392, "name": "STRENGTH & CONDITIONING",
 "service_id": 271494, "location_id": 37787,
 "start_at": "2026-08-10T22:00:00Z", "end_at": "2026-08-10T22:50:00Z",
 "url": "https://…/e/270871754", "timezone": "America/New_York",
 "state": "active", "full": true, "capacity_remaining": 0,
 "show_capacity_to_clients": true,
 "staff_members": [{"id": 9107413, "name": "Janibell Suero"}],
 "waitlist": {"full": false}}
```

`full` + `capacity_remaining` + `waitlist.full` are the three fields that decide
book-vs-waitlist-vs-nothing. Note `waitlist.full` is the waitlist's *own*
capacity, unrelated to the class being full.

### `GET event_occurrences/:id`

Same shape, single record.

### `GET event_occurrences/summary`

Counts grouped by `day` or `hour`. Params: `from`, `to`, `group_by`,
`location_ids`, `service_ids`, `service_types`.

## Reads that need a Bearer token

- `GET people/me` — resolves the token's person
- `GET people/:id/visits` — `from`/`to`/`event_occurrence_id`; sorted by start
- `GET people/:id/waitlist_entries` — same filters
- `GET event_occurrences/:id/enrollment_eligibilities` — can this person book
- `GET event_occurrences/:id/waitlist_eligibilities` — can they waitlist

### Enrollment restriction codes

`already_enrolled`, `cancelled`, `client_mode_booking_not_allowed`,
`client_purchase_disabled`, `clients_not_allowed`, `deleted`, `full`,
`in_the_past`, `inside_blackout_window` (too late), `too_far_in_advance` (too
early — this is the registration-opens gate), `members_not_allowed`,
`plan_required`, `plan_required_allocated`.

Warning (not blocking): `credit_card_required`.

### Waitlist restriction codes

`person_already_waitlisted`, `waitlist_full`, `waitlist_disabled`,
`waitlist_unavailable`.

## Writes (Bearer token only — hence Playwright)

### `POST bookings`

```json
{"booking": {"idempotency_token": "unique-string", "complete_booking": true,
  "leases": [{"event_occurrence_id": 1000, "person": {"id": 1}}]}}
```

`expires_at` defaults to 10 minutes, max 20. **A booking is only real when the
response has `completed_at` set** — without `complete_booking: true` you have
merely reserved capacity, and the hold silently expires.

### `POST visits`

```json
{"visit": {"person_id": 1, "event_occurrence_id": 1}}
```

Single-step alternative to bookings; always notifies the client.

### `POST waitlist_entries`

```json
{"waitlist_entry": {"person_id": 1, "event_occurrence_id": 1}}
```

### Cancelling

- `DELETE visits/:id` — cancels attendance. Optional `remove_recurring_enrollment`.
- `DELETE waitlist_entries/:id` — leaves the waitlist.
- `DELETE bookings/:id` — **does not cancel a completed booking's visits.** Once
  completed, this destroys only the booking record; the visit and invoice
  survive. Cancel the *visit* instead.

## The waitlist has no position

A `waitlist_entry` is, in full:

| field | notes |
| --- | --- |
| `id` |  |
| `person_id` |  |
| `event_occurrence_id` |  |
| `state` | `pending` \| `waiting` \| `enrolled` \| `removed` \| `expired` |
| `created_at` | desk namespace only |
| `updated_at` | desk namespace only |

No `position`, `rank`, or `priority` field exists in either namespace, and there
is no endpoint that reorders entries. Ordering is implicitly `created_at`, so
**entering earlier is the only way to be further up**, and no API call can read
back what place someone holds.

`pending` means a spot opened and is being held while that person completes
enrolment — which implies freed capacity may be routed to the waitlist head
rather than returned to open capacity. Unconfirmed; worth testing by watching
`capacity_remaining` on a class with a live waitlist when someone cancels.

## What the browser path actually touches

Verified against a live account, since the client UI is server-rendered Rails:

| page | holds |
| --- | --- |
| `/accounts/sign_in` | `#account_email`, `#account_password`, `#account_remember_me`, `button[type=submit].confirm_button` |
| `/e/:occurrence_id` | `.actions` — `Enroll` \| `Add to waitlist` \| `Already waitlisted` \| `Plan or pass required…` |
| `/e/:id/group_class_enrollment_confirmation/new?workflow=…` | the second step; submit is `Finish`, sibling `Cancel` abandons it |
| `/people/:id` | `#plans-and-passes-content` (`.plan-name` + `small`), and a **5-row truncated** `#upcoming` |
| `/people/:id/upcoming` | complete `#upcoming` and `#waitlist_entries`; rows link `/e/:occ/visits/:visit` |
| `/e/:occ/visits/:visit` | `a.cancel-visit`, behind a `data-confirm` modal submitting `Cancel Visit` |

The dashboard's `#upcoming` ends in a "view all" row carrying no `/e/` link —
parse by requiring an occurrence id, and read the full list from
`/people/:id/upcoming`.

## The OAuth route

An approved OAuth app would replace Playwright entirely with the write API
above. Two gates, neither of which a gym member controls:

1. **The business must be on Pike13 Premium** — API access is a plan feature.
2. **Pike13 must approve the registered app** at
   <https://developer.pike13.com> before credentials activate.

Flow, if both clear: authorization-code only (no password or client-credentials
grant).

```text
GET  https://<domain>.pike13.com/oauth/authorize
       ?client_id=…&response_type=code&redirect_uri=…
POST https://pike13.com/oauth/token
       ?grant_type=authorization_code&code=…&redirect_uri=…
       &client_id=…&client_secret=…
```

Use the gym subdomain on `/oauth/authorize` — a token minted on a subdomain is
only valid against that subdomain. Tokens do not expire, so this is a one-time
exchange, but they can be revoked. Supply as `Authorization: Bearer <token>` or
`?access_token=`.

Webhooks (push notification the instant capacity frees) and the Reporting API
both require **owner** role, so they are unavailable to a client account
regardless of the above.
