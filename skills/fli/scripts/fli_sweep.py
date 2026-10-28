#!/usr/bin/env python3
"""Sweep fli over origins x destinations x dates; print cheapest per date x airline.

Usage:
  fli_sweep.py --from JFK,EWR --to LAX --dates 2026-12-28..2026-12-31 \
      [--time 5-21] [--stops NON_STOP] [--no-redeye] [--json out.json]

--dates takes a comma list, a START..END range, or both (2026-12-28,2027-01-02..2027-01-04).
--time filters on departure hour (HH-HH, 24h, inclusive start, exclusive end).
--no-redeye drops flights that land on a later calendar day than they depart.
"""
import argparse, json, os, subprocess, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

FLI = os.environ.get("FLI_BIN", "/opt/data/venvs/fli/bin/fli")


def expand_dates(spec):
    out = []
    for part in spec.split(","):
        if ".." in part:
            a, b = (date.fromisoformat(x) for x in part.split(".."))
            out += [(a + timedelta(n)).isoformat() for n in range((b - a).days + 1)]
        else:
            out.append(part)
    return out


def search(job, stops, extra):
    o, d, dt = job
    cmd = [FLI, "flights", o, d, dt, "--stops", stops, "--sort", "CHEAPEST", "--format", "json", *extra]
    for _ in range(3):  # ~1 in 60 pages arrives empty; retry
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        try:
            j = json.loads(r.stdout)
            if j.get("success"):
                return job, j["flights"]
        except ValueError:
            pass
    return job, None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="origins", required=True)
    p.add_argument("--to", dest="dests", required=True)
    p.add_argument("--dates", required=True)
    p.add_argument("--time", help="departure hour window, e.g. 5-21")
    p.add_argument("--stops", default="NON_STOP")
    p.add_argument("--no-redeye", action="store_true")
    p.add_argument("--json", help="write raw rows here")
    p.add_argument("--extra", nargs=argparse.REMAINDER, default=[], help="extra fli flags, e.g. --passengers 2")
    a = p.parse_args()

    jobs = [(o, d, dt) for o in a.origins.split(",") for d in a.dests.split(",") for dt in expand_dates(a.dates)]
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda j: search(j, a.stops, a.extra), jobs))

    lo, hi = (int(x) for x in a.time.split("-")) if a.time else (0, 24)
    rows = []
    for job, flights in results:
        if flights is None:
            print(f"FAIL {job}", file=sys.stderr)
            continue
        for f in flights:
            leg = f["legs"][0]
            dep, arr = leg["departure_time"], leg["arrival_time"]
            if not lo <= int(dep[11:13]) < hi:
                continue
            if a.no_redeye and arr[:10] != dep[:10]:
                continue
            rows.append(dict(origin=job[0], dest=job[1], date=job[2], price=f["price"],
                             airline=leg["airline"]["name"], flight=leg["airline"]["code"] + leg["flight_number"],
                             dep=dep[11:16], arr=arr[11:16], minutes=f["duration"], stops=f["stops"]))
    if a.json:
        json.dump(rows, open(a.json, "w"))

    if not rows:
        print("No flights. Empty is a real answer for routes with no service on those dates.")
        return
    for route in sorted({(r["origin"], r["dest"]) for r in rows}):
        print(f"\n{route[0]} -> {route[1]}")
        for dt in sorted({r["date"] for r in rows if (r["origin"], r["dest"]) == route}):
            by = defaultdict(list)
            for r in rows:
                if (r["origin"], r["dest"], r["date"]) == (*route, dt):
                    by[r["airline"]].append(r)
            cells = []
            for al, l in sorted(by.items()):
                m = min(l, key=lambda x: x["price"])
                cells.append(f'{al} ${m["price"]:.0f} @{m["dep"]}')
            print(f"  {dt}  " + " | ".join(cells))


if __name__ == "__main__":
    main()
