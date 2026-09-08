---
name: reddit-search
description: |
  Search Reddit without an API key — posts, comments, whole threads, and which
  subreddits discuss a topic. Use when the user asks what people say on Reddit
  about something, wants community/anecdotal experience on a product, symptom,
  or decision, names a subreddit to search, or gives a Reddit link to read.
license: ISC
---

# Reddit Search

`scripts/reddit_search.py` — stdlib Python, no key, no install.

## Two sources

Every command reads one of two, and the split governs every choice below:

| | **live** (default) | **archive** (`--archive`) |
|---|---|---|
| data | current | **nothing after 2025-05-19** |
| scores | ranked by score, numbers hidden | numbers shown |
| comment search | none | full-text |
| date filters | `-t hour…year\|all` | `--since/--until` |

Reach for **live** by default — the **archive** is over a year stale, so it answers
"what did people say" and never "what do people say". Reach for it when you need a
visible score, a full-text comment search, or a bounded date range.

## Workflow

Widen, then narrow — each step feeds the next:

1. **`subs <topic>`** — find where the conversation actually lives. Returns
   subreddits ranked by how many matching posts each holds. Skip only when the
   user already named a subreddit.
2. **`search <query> -r <sub>`** — titles only, one line each. Read the titles
   and pick the few worth opening.
3. **`thread <id>`** — the post plus its top comments. This is where the substance
   is; a title list alone rarely answers a question.

Ends when the claims you report trace back to threads you actually opened.

## Commands

```bash
S=scripts/reddit_search.py
$S subs "cast iron seasoning"                    # → r/castiron 48, r/Cooking 6, …
$S search "sourdough starter" -r Sourdough -n 20 # live, in one sub
$S search "sleep regression" -r sleeptrain --sort top -t year  # best of last year
$S search "lodge skillet" -r castiron --archive  # with visible ^score c<count>
$S thread 1nizcqb -n 25                          # post + 25 top comments
$S thread https://reddit.com/r/x/comments/abc123/… # permalink works too
$S comments "lodge vs griswold" -r castiron      # archive-only, full-text
```

Output flags (either position): `--full` adds bodies, `--chars N` sets the
truncation budget (default 500), `--json` for piping. `-h` for the rest.

## Token discipline

Search prints titles and no bodies on purpose. Keep it that way while surveying —
add `--full` only for a sub-25 result set you've already narrowed, and lower
`--chars` when you want the gist rather than the argument.

## Gotchas

- **Quote a multi-word phrase** (`'"cast iron seasoning"'`) to keep results on
  topic; unquoted words match loosely. `subs` does this for you.
- **Sitewide `--sort top -t all` drifts off-topic** — all-time viral posts outrank
  topical ones. Prefer the default `relevance`, or pair `top` with `-r <sub>`.
- **Archive scores run low.** Pullpush captured the score at ingest, often minutes
  after posting, so `^2` means "unmeasured", not "unpopular" — never read archive
  score as a popularity signal, and rank by `live --sort top` instead.
- **Slow is not hung.** Reddit rate-limits RSS; the script backs off and retries
  for up to a couple of minutes. Let it finish.
- Reddit's own JSON API, `old.reddit.com`, and reader proxies are all 403 to
  keyless clients. RSS is the one live door — don't burn time re-testing them.
