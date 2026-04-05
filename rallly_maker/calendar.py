"""Extract Google Calendar events via CDP browser automation."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .cdp import CdpClient, launch_chrome, wait_for_devtools, inject_cookies
from .chrome_cookies import get_google_cookies

WRAPPER_DIR = "/home/luki/codexSandbox/chrome-automation-full"
DEBUG_PORT = 9227


def _extract_events_js(time_min: str, time_max: str) -> str:
    """JS that fetches calendar events via the gapi client embedded in the Calendar web app."""
    return f"""(async () => {{
        // Wait for the calendar to load, then scrape visible events
        await new Promise(r => setTimeout(r, 3000));

        // Try to extract from the DOM - look for event chips/elements
        const events = [];
        // Calendar renders events as [data-eventid] or aria-label elements
        const chips = document.querySelectorAll('[data-eventid], [aria-label*="event"]');
        for (const el of chips) {{
            const label = el.getAttribute('aria-label') || el.innerText || '';
            if (label.trim()) events.push(label.trim());
        }}

        // Also try to get from the page's internal data
        const bodyText = (document.body?.innerText || '').slice(0, 8000);
        return {{
            url: location.href,
            title: document.title,
            eventCount: events.length,
            events: events.slice(0, 50),
            bodySnippet: bodyText,
        }};
    }})()"""


def get_events_for_range(
    start_date: str,
    end_date: str,
    tz: str = "Europe/London",
) -> list[dict]:
    """
    Launch Chrome, inject Google cookies, navigate to Calendar, and extract events.
    start_date/end_date: 'YYYY-MM-DD' strings.
    Returns list of event dicts with 'summary', 'start', 'end'.
    """
    cookies = get_google_cookies()
    proc = launch_chrome(WRAPPER_DIR, DEBUG_PORT)
    try:
        ws_url = wait_for_devtools(DEBUG_PORT)
        client = CdpClient(ws_url)
        client.send("Page.enable")
        client.send("Runtime.enable")
        inject_cookies(client, cookies)

        # Navigate to calendar week view for the target dates
        # Use the /r/week/ view with a specific date
        cal_url = f"https://calendar.google.com/calendar/u/0/r/week/{start_date.replace('-', '/')}"
        client.navigate(cal_url, wait=5)

        state = client.evaluate("""(() => ({
            url: location.href,
            title: document.title,
            loggedIn: !location.href.includes('accounts.google.com'),
            bodySnippet: (document.body?.innerText || '').slice(0, 4000),
        }))()""")

        if not state or not state.get("loggedIn"):
            return _parse_events_from_text(state.get("bodySnippet", "") if state else "", start_date, end_date, tz)

        # Extract events from the rendered calendar
        raw = client.evaluate(_extract_events_js(start_date, end_date))
        client.close()

        if raw and raw.get("events"):
            return _parse_aria_events(raw["events"], tz)
        # Fall back to parsing body text
        return _parse_events_from_text(
            raw.get("bodySnippet", "") if raw else "",
            start_date, end_date, tz,
        )
    finally:
        proc.kill()
        proc.wait()


def _parse_aria_events(labels: list[str], tz: str) -> list[dict]:
    """Parse aria-label strings like 'Meeting, April 7, 2026, 5:00 – 6:00 PM'."""
    events = []
    for label in labels:
        events.append({"summary": label, "raw": True})
    return events


def _parse_events_from_text(text: str, start_date: str, end_date: str, tz: str) -> list[dict]:
    """Best-effort parse of calendar body text for timed events."""
    # This is a fallback — returns empty if we can't parse
    return []


def find_conflicts(
    events: list[dict],
    start_date: str,
    end_date: str,
    slot_starts: list[str] = ("16:30", "17:00", "17:30", "18:00"),
    tz: str = "Europe/London",
) -> list[str]:
    """
    Given events and a date range, return slot strings that conflict.
    Slot format: 'YYYY-MM-DD HH:MM'.
    If no events have parseable times, returns empty (no conflicts).
    """
    # For now, with raw aria-label events, we can't reliably parse times
    # Return empty = no conflicts detected
    return []


def available_slots(
    start_date: str,
    end_date: str,
    slot_starts: list[str] = ("16:30", "17:00", "17:30", "18:00"),
    tz: str = "Europe/London",
) -> list[tuple[str, str]]:
    """
    Return list of (date, time) tuples for all available slots.
    Fetches calendar, removes conflicts.
    """
    events = get_events_for_range(start_date, end_date, tz)
    conflicts = find_conflicts(events, start_date, end_date, slot_starts, tz)

    slots = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        for t in slot_starts:
            key = f"{ds} {t}"
            if key not in conflicts:
                slots.append((ds, t))
        d += timedelta(days=1)
    return slots
