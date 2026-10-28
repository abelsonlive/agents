---
name: fli
description: |
  Search Google Flights from the CLI — prices, schedules, nonstop filters,
  cheapest-date sweeps. Use when the user asks about flights, airfare, which
  day is cheaper to fly, or comparing airlines/airports for a trip.
license: MIT
---

# fli

[`fli`](https://github.com/punitarani/fli) reads Google Flights directly (no key, no browser). Installed in a venv at `/opt/data/venvs/fli`; binary `/opt/data/venvs/fli/bin/fli`. Also ships `fli-mcp` (stdio) and `fli-mcp-http`, not wired into Hermes yet.

## Workflow

1. **Single date** → `fli flights ORIGIN DEST YYYY-MM-DD --stops NON_STOP --sort CHEAPEST --format json`.
2. **Many dates / airports / airlines** → `scripts/fli_sweep.py`. One call replaces a browser session per date.
   ```
   python3 scripts/fli_sweep.py --from JFK,EWR --to LAX --dates 2026-12-28..2026-12-31 --time 5-21 --no-redeye
   ```
   Prints cheapest per date × airline. `--json out.json` keeps raw rows for deeper cuts (e.g. one airline's full schedule).
3. **Cheapest date in a range** → `fli dates ORIGIN DEST --from D --to D --stops NON_STOP --format json`.
4. **Report** the user's own constraints first (airline, airport, time of day, refundability), then the cheaper alternatives.

Done when every airport pair and date the user named has returned rows or a confirmed-empty result.

## Reference

- **Always `--format json`** for parsing; text output is for humans.
- **`--stops NON_STOP`** (or `0`). `--time 6-20` is a departure-hour window.
- **Airline codes** for `--airlines`/`--exclude-airlines`: DL, B6, AA, UA, AS. JSON names are long ("Delta Air Lines"), except JetBlue.
- **Redeyes**: no flag. Drop rows where `arrival_time` date ≠ `departure_time` date (`--no-redeye` in the sweep script).
- **Airport choice matters**: query every metro airport (JFK + EWR + LGA, LAX + BUR + ONT + LGB + SNA). The cheapest fare is often at the airport the user didn't name.
- **Passengers**: `--passengers N --infants-on-lap N`. Infants thin results, sometimes to zero; run adults-only to see the schedule.

## Limits

- **No refundable-fare filter, no bag filter, no Basic-Economy exclusion.** Prices are the lowest fare, usually Main Basic. Refundable fares need a quote on the airline's site; say so.
- **Google ≠ the airline's site.** Google showed Delta JFK→LAX Dec 31 at $229, yet delta.com's round-trip grid (2 pax) showed Dec 30–31 "Not Offered" and $847–$1,037 elsewhere. Treat fli prices as a scouting pass; confirm on the airline's own site before recommending a date. Ask the user to check the airline grid, or test one-way searches there.
- **Lap infants return zero rows.** `--infants-on-lap 1` gave 0 Delta results on every date; adults-only shows the schedule. This is a known fli limit, not an availability signal.
- **Prices drift ~$10** between pulls and from the Google Flights web UI.
- **Empty result = no nonstop service** on that route and date, which is an answer. (JFK/EWR→BUR returned zero nonstops Dec 28–31 and Jan 8–9, 2026/27; JetBlue's JFK–BUR is summer seasonal.)
- **~20–45 itineraries per search**, and `dates` costs one fetch per date (max 93).
- **Multi-city is unsupported**; search each leg separately.
- ~1 in 60 requests returns empty; retry (the sweep script does).

## Install / repair

```
uv venv /opt/data/venvs/fli && uv pip install --python /opt/data/venvs/fli/bin/python "git+https://github.com/punitarani/fli.git" click
```
Install from GitHub, not PyPI: PyPI `flights` 0.9.0 has **no `--passengers`/`--infants-*` flags** (`No such option: --passengers`); GitHub is 0.10.0+. `click` is not pulled in either; `ModuleNotFoundError: click` means it is missing. If searches return HTTP 200 with no rows across the board, Google changed its page format — check the repo's issues and upgrade (`uv pip install -U flights`).

## Log

Append dated findings here (new flags, route quirks, failures and fixes).

- 2026-10: first use, NYC↔LA holiday trip. Sweep over JFK/EWR→LAX confirmed Dec 31 departures far cheaper than Dec 28–30 (Delta $229 vs $419–539).
- 2026-10: Delta site grid (2 pax round trip) showed Dec 30–31 "Not Offered" while Google showed cheap Dec 31 one-ways. Cheapest on delta.com: Fri Jan 1 depart, $847 (Jan 6–9, 11–12 returns), Dec 28 $992, Dec 29 $1,037. Cause unknown (Delta round-trip pricing rules vs Google one-way pricing).
