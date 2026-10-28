#!/usr/bin/env python3
"""Auto-book Fuerza classes 14 days out (window-open day).

Target schedule (weekly):
  Mon/Wed/Fri 10:00 AM ET  -> STRENGTH (BARBELL)
  Thu/Sun 9:00 AM ET       -> STRENGTH & CONDITIONING
Run daily at 9AM ET. Rest days (Tue/Sat targets) stay silent.
"""

import json
import os
import subprocess
import sys
from datetime import date, timedelta

SCRIPT = "/mnt/nvme/homelab/hermes/agents/skills/pike13/scripts/pike13.py"
FOURTEEN_DAYS = timedelta(days=14)

# weekday (Mon=0) -> (kind, hour_et)
# kind "strength" = STRENGTH (BARBELL) at 10AM; "sc" = STRENGTH & CONDITIONING at 9AM
PLAN = {
    0: ("strength", 10),  # Mon
    2: ("strength", 10),  # Wed
    4: ("strength", 10),  # Fri
    3: ("sc", 9),         # Thu
    6: ("sc", 9),         # Sun
}


def et_now() -> date:
    env = os.environ.copy()
    env["TZ"] = "America/New_York"
    return date.today()


def run_pike13(*args: str) -> dict:
    env = os.environ.copy()
    env["PIKE13_USERNAME"] = os.environ["PIKE13_USERNAME"]
    env["PIKE13_PASSWORD"] = os.environ["PIKE13_PASSWORD"]
    env["PIKE13_DOMAIN"] = os.environ.get("PIKE13_DOMAIN", "fuerzatrainingsystems")
    r = subprocess.run(
        ["uv", "run", SCRIPT, *args],
        capture_output=True, text=True, timeout=60, env=env,
    )
    if r.returncode != 0:
        print(f"ERROR: {' '.join(args)} failed:\n{r.stderr}", flush=True)
        sys.exit(1)
    return json.loads(r.stdout)


def find_target_class(classes: list[dict], kind: str, hour_et: int) -> dict | None:
    """Find the target class at the target hour.

    hour_et 9 -> UTC 13 (EDT) or 14 (EST); hour_et 10 -> UTC 14 (EDT) or 15 (EST).
    """
    utc_hours = {hour_et + 4, hour_et + 5}  # EDT / EST
    for c in classes:
        name = c.get("name", "").strip().upper()
        if kind == "strength":
            if "BARBELL" not in name or "CONDITIONING" in name:
                continue
        else:  # "sc"
            if "CONDITIONING" not in name:
                continue
        start = c.get("start_at", "")
        try:
            hour_utc = int(start.split("T")[1].split(":")[0])
        except (IndexError, ValueError):
            continue
        if hour_utc in utc_hours:
            return c
    return None


def get_enrolled_ids() -> set[int]:
    try:
        data = run_pike13("mine", "--json")
    except Exception:
        return set()
    if isinstance(data, dict):
        upcoming = data.get("upcoming", []) if isinstance(data.get("upcoming"), list) else []
    elif isinstance(data, list):
        upcoming = data
    else:
        return set()
    return {int(e.get("occurrence_id", 0)) for e in upcoming if isinstance(e, dict) and e.get("occurrence_id")}


def write_action(action: str, cid: int):
    result = subprocess.run(
        ["uv", "run", SCRIPT, action, str(cid), "--yes"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ,
             "PIKE13_USERNAME": os.environ["PIKE13_USERNAME"],
             "PIKE13_PASSWORD": os.environ["PIKE13_PASSWORD"],
             "PIKE13_DOMAIN": os.environ.get("PIKE13_DOMAIN", "fuerzatrainingsystems")},
    )
    print((result.stdout + result.stderr).strip(), flush=True)
    return result.returncode


def main():
    today = et_now()
    target_day = today + FOURTEEN_DAYS
    target_wd = target_day.weekday()

    if target_wd not in PLAN:
        sys.exit(0)  # rest day (Tue/Sat target) — silent

    kind, hour_et = PLAN[target_wd]
    cls_label = ("STRENGTH (BARBELL)" if kind == "strength" else "STRENGTH & CONDITIONING")

    print(f"Target: {target_day} ({target_day.strftime('%A')}) — {hour_et}AM {cls_label}", flush=True)

    enrolled = get_enrolled_ids()
    classes = run_pike13("schedule", f"+{FOURTEEN_DAYS.days}d", "--json")

    target = find_target_class(classes, kind, hour_et)
    if target is None:
        print(
            f"NO CLASS: no {cls_label} at {hour_et}AM ET on "
            f"{target_day.strftime('%A')}, {target_day}. Skipping.",
            flush=True,
        )
        sys.exit(0)

    cid = target["id"]
    if cid in enrolled:
        print(f"ALREADY BOOKED: {cls_label} {hour_et}AM on {target_day} (id={cid}). Skipping.", flush=True)
        sys.exit(0)

    full = target.get("full", True)
    cap_rem = target.get("capacity_remaining", 0)
    waitlist_full = target.get("waitlist", {}).get("full", True)

    print(f"Found: {cls_label} id={cid} full={full} cap={cap_rem} wl_full={waitlist_full}", flush=True)

    if not full and cap_rem > 0:
        print(f"Booking {cid} …", flush=True)
        rc = write_action("book", cid)
        if rc == 0:
            print(f"BOOKED {cid}: {target_day} {hour_et}AM {cls_label}", flush=True)
        else:
            print(f"Book failed — trying waitlist for {cid} …", flush=True)
            write_action("waitlist", cid)
    elif full and not waitlist_full:
        print(f"Class full — waitlisting {cid} …", flush=True)
        write_action("waitlist", cid)
    else:
        print(f"FULL & WAITLIST FULL — nothing to do for {cid}", flush=True)


if __name__ == "__main__":
    main()