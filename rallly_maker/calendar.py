"""Extract Google Calendar events via CDP browser automation."""

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .cdp import CdpClient, launch_chrome, wait_for_devtools, inject_cookies
from .chrome_cookies import get_google_cookies

WRAPPER_DIR = "/home/luki/codexSandbox/chrome-automation-full"
DEBUG_PORT = 9227


def _handle_google_signin(client: CdpClient):
    """If on Google sign-in, click the primary account to proceed."""
    url = client.evaluate("location.href") or ""
    if "accounts.google.com" not in url:
        return
    pt = client.evaluate("""(() => {
        const items = document.querySelectorAll('li, div[role="link"], a');
        for (const item of items) {
            if ((item.innerText||'').includes('lipka.luki')) {
                item.scrollIntoView({block:'center'});
                const r = item.getBoundingClientRect();
                return {x: r.left+r.width/2, y: r.top+r.height/2};
            }
        }
        return null;
    })()""")
    if pt and pt.get("x", 0) > 0:
        client.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": pt["x"], "y": pt["y"], "button": "left", "clickCount": 1})
        client.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": pt["x"], "y": pt["y"], "button": "left", "clickCount": 1})
        time.sleep(8)


def _extract_events(client: CdpClient) -> list[dict]:
    """Scrape event chips from the loaded Calendar week view."""
    raw = client.evaluate("""(() => {
        const results = [];
        const chips = document.querySelectorAll('[data-eventid]');
        for (const chip of chips) {
            const label = chip.getAttribute('aria-label') || chip.innerText || '';
            if (label.trim()) results.push(label.trim());
        }
        return results;
    })()""")
    return raw or []


def _parse_event_time(label: str, cal_tz: str, target_tz: str) -> dict | None:
    """Parse an aria-label like '3:30pm to 5:50pm, Let Londyn, ..., April 8, 2026'.
    Times in the label are in cal_tz; we convert to target_tz."""
    if label.lower().startswith("all day"):
        return None
    m = re.match(
        r"(\d{1,2}:\d{2}(?:am|pm))\s+to\s+(\d{1,2}:\d{2}(?:am|pm)),\s*(.+?)(?:,\s*(?:Calendar:.*?,\s*)?(?:No location,\s*)?(\w+ \d{1,2}(?:,\s*\d{4}| – \d{1,2},\s*\d{4})))",
        label, re.IGNORECASE,
    )
    if not m:
        return None
    start_str, end_str, summary = m.group(1), m.group(2), m.group(3).strip()
    date_part = m.group(4).strip()
    date_m = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", date_part)
    if not date_m:
        return None
    try:
        date = datetime.strptime(f"{date_m.group(1)} {date_m.group(2)} {date_m.group(3)}", "%B %d %Y")
    except ValueError:
        return None

    def parse_time(s):
        return datetime.strptime(s.upper(), "%I:%M%p")

    st = parse_time(start_str)
    et = parse_time(end_str)

    # Convert from calendar display tz to target tz
    cal_zone = ZoneInfo(cal_tz)
    tgt_zone = ZoneInfo(target_tz)
    start_dt = date.replace(hour=st.hour, minute=st.minute, tzinfo=cal_zone).astimezone(tgt_zone)
    end_dt = date.replace(hour=et.hour, minute=et.minute, tzinfo=cal_zone).astimezone(tgt_zone)

    return {
        "summary": summary,
        "date": start_dt.strftime("%Y-%m-%d"),
        "start": start_dt.strftime("%H:%M"),
        "end": end_dt.strftime("%H:%M"),
    }


def get_events_for_range(start_date: str, end_date: str, tz: str = "Europe/London") -> list[dict]:
    """Launch Chrome, navigate to Calendar, extract timed events."""
    # Detect the system/calendar display timezone
    import subprocess
    try:
        cal_tz = subprocess.check_output(["timedatectl", "show", "-p", "Timezone", "--value"], text=True).strip()
    except Exception:
        cal_tz = "Europe/Bratislava"

    cookies = get_google_cookies()
    proc = launch_chrome(WRAPPER_DIR, DEBUG_PORT, ["--remote-allow-origins=*"])
    try:
        ws_url = wait_for_devtools(DEBUG_PORT)
        client = CdpClient(ws_url)
        client.send("Page.enable")
        client.send("Runtime.enable")
        inject_cookies(client, cookies)
        client.navigate(f"https://calendar.google.com/calendar/u/0/r/week/{start_date.replace('-', '/')}", wait=5)
        _handle_google_signin(client)

        labels = _extract_events(client)
        client.close()

        events = []
        for label in labels:
            parsed = _parse_event_time(label, cal_tz, tz)
            if parsed:
                events.append(parsed)
        return events
    finally:
        proc.kill()
        proc.wait()


def find_conflicts(
    events: list[dict],
    slot_starts: list[str] = ("16:30", "17:00", "17:30", "18:00"),
    tz: str = "Europe/London",
) -> set[str]:
    """Return set of 'YYYY-MM-DD HH:MM' slot keys that overlap with events."""
    conflicts = set()
    for ev in events:
        ev_start = int(ev["start"].replace(":", ""))
        ev_end = int(ev["end"].replace(":", ""))
        for t in slot_starts:
            slot_start = int(t.replace(":", ""))
            slot_end = slot_start + 100  # 1 hour later
            # Overlap check
            if slot_start < ev_end and ev_start < slot_end:
                conflicts.add(f"{ev['date']} {t}")
    return conflicts


def available_slots(
    start_date: str,
    end_date: str,
    slot_starts: list[str] = ("16:30", "17:00", "17:30", "18:00"),
    tz: str = "Europe/London",
) -> list[tuple[str, str]]:
    """Return (date, time) tuples for all available slots after removing calendar conflicts."""
    events = get_events_for_range(start_date, end_date, tz)
    conflicts = find_conflicts(events, slot_starts, tz)

    slots = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        for t in slot_starts:
            if f"{ds} {t}" not in conflicts:
                slots.append((ds, t))
        d += timedelta(days=1)
    return slots
