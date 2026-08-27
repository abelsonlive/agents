#!/usr/bin/env python3
"""Auto-book 9AM STRENGTH & CONDITIONING 14 days out. Run MWF at 9AM ET."""

import json
import os
import subprocess
import sys
from datetime import date, timedelta, timezone

SCRIPT = "/mnt/nvme/homelab/hermes/agents/skills/pike13/scripts/pike13.py"
TARGET_NAME = "STRENGTH & CONDITIONING"
TARGET_HOUR_ET = 9  # 9AM ET
FOURTEEN_DAYS = timedelta(days=14)


def et_now() -> date:
    """Today's date in America/New_York."""
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


def find_target_class(classes: list[dict]) -> dict | None:
    """Find STRENGTH & CONDITIONING at 9AM ET (13:00 UTC in EDT, 14:00 in EST)."""
    for c in classes:
        name = c.get("name", "").strip()
        if name != TARGET_NAME:
            continue
        start = c["start_at"]  # "2026-09-09T13:00:00Z"
        # EDT is UTC-4 → 9AM ET = 13:00Z. EST is UTC-5 → 9AM ET = 14:00Z.
        # Both hit +d for the month (Sep = EDT = -4).
        # Extract hour from ISO: T13:00:00Z
        try:
            hour_utc = int(start.split("T")[1].split(":")[0])
        except (IndexError, ValueError):
            continue
        if hour_utc in (13, 14):  # 9AM EDT or EST
            return c
    return None


def get_enrolled_ids() -> set[int]:
    """Return set of occurrence ids already booked from `mine` output."""
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


def main():
    today = et_now()
    target_day = today + FOURTEEN_DAYS
    target_date_str = target_day.strftime("%Y-%m-%d")
    target_weekday = target_day.strftime("%A")

    print(f"Today: {today} ({today.strftime('%A')})", flush=True)
    print(f"Target: {target_date_str} ({target_weekday})", flush=True)

    # Check if already booked
    enrolled = get_enrolled_ids()
    if enrolled:
        print(f"Already booked: {len(enrolled)} upcoming classes", flush=True)

    classes = run_pike13("schedule", f"+{FOURTEEN_DAYS.days}d", "--json")

    target = find_target_class(classes)
    if target is None:
        print(
            f"NO CLASS: No {TARGET_NAME} at {TARGET_HOUR_ET}AM ET on "
            f"{target_weekday}, {target_date_str}. Skipping.",
            flush=True,
        )
        sys.exit(0)

    cid = target["id"]
    if cid in enrolled:
        print(
            f"ALREADY BOOKED: {TARGET_NAME} at {TARGET_HOUR_ET}AM ET on "
            f"{target_weekday}, {target_date_str} (id={cid}). Skipping.",
            flush=True,
        )
        sys.exit(0)
    cname = target["name"]
    full = target.get("full", True)
    cap_rem = target.get("capacity_remaining", 0)
    waitlist_full = target.get("waitlist", {}).get("full", True)

    print(f"Found: {cname} id={cid} full={full} cap={cap_rem} wl_full={waitlist_full}", flush=True)

    if not full and cap_rem > 0:
        print(f"Booking class {cid} …", flush=True)
        result = subprocess.run(
            ["uv", "run", SCRIPT, "book", str(cid), "--yes"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ,
                 "PIKE13_USERNAME": os.environ["PIKE13_USERNAME"],
                 "PIKE13_PASSWORD": os.environ["PIKE13_PASSWORD"],
                 "PIKE13_DOMAIN": os.environ.get("PIKE13_DOMAIN", "fuerzatrainingsystems")},
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            print(f"BOOKED {cid}: {target_date_str} 9AM {TARGET_NAME}", flush=True)
        else:
            print(f"BOOK FAILED (rc={result.returncode}):\n{output}", flush=True)
            # Try waitlist as fallback
            print(f"Trying waitlist for {cid} …", flush=True)
            wl = subprocess.run(
                ["uv", "run", SCRIPT, "waitlist", str(cid), "--yes"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ,
                     "PIKE13_USERNAME": os.environ["PIKE13_USERNAME"],
                     "PIKE13_PASSWORD": os.environ["PIKE13_PASSWORD"],
                     "PIKE13_DOMAIN": os.environ.get("PIKE13_DOMAIN", "fuerzatrainingsystems")},
            )
            print((wl.stdout + wl.stderr).strip(), flush=True)

    elif full and not waitlist_full:
        print(f"Class full — waitlisting {cid} …", flush=True)
        result = subprocess.run(
            ["uv", "run", SCRIPT, "waitlist", str(cid), "--yes"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ,
                 "PIKE13_USERNAME": os.environ["PIKE13_USERNAME"],
                 "PIKE13_PASSWORD": os.environ["PIKE13_PASSWORD"],
                 "PIKE13_DOMAIN": os.environ.get("PIKE13_DOMAIN", "fuerzatrainingsystems")},
        )
        print((result.stdout + result.stderr).strip(), flush=True)
    else:
        print(f"FULL & WAITLIST FULL — nothing to do for {cid}", flush=True)


if __name__ == "__main__":
    main()