#!/usr/bin/env python3
"""ralllyMaker CLI — scan Google Calendar, create a Rallly poll with available slots."""

import argparse
import json
import sys

from .calendar import available_slots
from .rallly import create_poll


def main():
    p = argparse.ArgumentParser(description="Create a Rallly poll from Google Calendar availability")
    p.add_argument("--title", required=True, help="Poll title")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument("--times", default="16:30,17:00,17:30,18:00",
                   help="Comma-separated slot start times (default: 16:30,17:00,17:30,18:00)")
    p.add_argument("--tz", default="Europe/London", help="Timezone (default: Europe/London)")
    p.add_argument("--skip-calendar", action="store_true",
                   help="Skip calendar check, use all slots")
    p.add_argument("--dry-run", action="store_true",
                   help="Show slots without creating the poll")
    args = p.parse_args()

    times = [t.strip() for t in args.times.split(",")]

    if args.skip_calendar:
        from datetime import datetime, timedelta
        slots = []
        d = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")
        while d <= end:
            for t in times:
                slots.append((d.strftime("%Y-%m-%d"), t))
            d += timedelta(days=1)
    else:
        print(f"Scanning Google Calendar {args.start} → {args.end}...", file=sys.stderr)
        slots = available_slots(args.start, args.end, times, args.tz)

    print(f"{len(slots)} available slots:", file=sys.stderr)
    for date, time_str in slots:
        print(f"  {date} {time_str}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps([{"date": d, "time": t} for d, t in slots], indent=2))
        return

    if not slots:
        print("No available slots — aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"\nCreating Rallly poll '{args.title}'...", file=sys.stderr)
    result = create_poll(args.title, slots, args.tz)

    print("\n✓ Poll created!", file=sys.stderr)
    if result.get("manage_link"):
        print(f"  Manage: {result['manage_link']}", file=sys.stderr)
    if result.get("invite_link"):
        print(f"  Invite: {result['invite_link']}", file=sys.stderr)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
