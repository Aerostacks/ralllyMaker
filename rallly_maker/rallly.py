"""Create a Rallly poll via CDP browser automation."""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .cdp import CdpClient, launch_chrome, wait_for_devtools, inject_cookies
from .chrome_cookies import get_google_cookies

WRAPPER_DIR = "/home/luki/codexSandbox/chrome-automation-full"
DEBUG_PORT = 9225


def _get_point(client: CdpClient, js_expr: str):
    return client.evaluate(f"""(() => {{
        const el = ({js_expr})();
        if (!el) return null;
        el.scrollIntoView({{ block: 'center', inline: 'center' }});
        const r = el.getBoundingClientRect();
        return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};
    }})()""")


def _click(client: CdpClient, point: dict, delay: float = 0.25):
    if not point:
        raise RuntimeError("Cannot click null point")
    for evt in ("mouseMoved", "mousePressed", "mouseReleased"):
        btn = "none" if evt == "mouseMoved" else "left"
        params = {"type": evt, "x": point["x"], "y": point["y"], "button": btn}
        if evt != "mouseMoved":
            params["clickCount"] = 1
        client.send("Input.dispatchMouseEvent", params)
    time.sleep(delay)


def _click_button(client: CdpClient, text: str, occurrence: int = 0):
    pt = _get_point(client, f"() => Array.from(document.querySelectorAll('button')).filter(el => (el.innerText||el.textContent||'').trim() === {json.dumps(text)})[{occurrence}]")
    if not pt:
        raise RuntimeError(f"Button not found: {text}")
    _click(client, pt)


def _set_input(client: CdpClient, selector: str, value: str):
    client.evaluate(f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return false;
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
        if (setter) setter.call(el, {json.dumps(value)});
        else el.value = {json.dumps(value)};
        el.dispatchEvent(new InputEvent('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }})()""")


def _set_select(client: CdpClient, index: int, value: str, text: str):
    client.evaluate(f"""(() => {{
        const el = document.querySelectorAll('select')[{index}];
        if (!el) return false;
        let opt = Array.from(el.options).find(o => o.value === {json.dumps(value)});
        if (!opt) {{
            opt = new Option({json.dumps(text)}, {json.dumps(value)}, true, true);
            el.add(opt);
        }}
        el.value = {json.dumps(value)};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()""")


def _auth_rallly(client: CdpClient):
    """Authenticate to Rallly via Google OAuth using injected cookies."""
    cookies = get_google_cookies()
    inject_cookies(client, cookies)
    client.navigate("https://app.rallly.co/login?redirectTo=%2Fnew", wait=3)

    pt = _get_point(client, "() => Array.from(document.querySelectorAll('button')).find(el => (el.innerText||'').trim() === 'Continue with Google')")
    _click(client, pt)
    client.wait_event("Page.loadEventFired", timeout=20)
    time.sleep(5)

    # Handle Google account picker
    url = client.evaluate("location.href") or ""
    if "accounts.google.com" in url:
        acct = _get_point(client, "() => Array.from(document.querySelectorAll('*')).find(el => (el.innerText||'').includes('lipka.luki@gmail.com'))")
        if acct:
            _click(client, acct)
            client.wait_event("Page.loadEventFired", timeout=20)
            time.sleep(5)

    # Handle Continue/Next button if still on Google
    url = client.evaluate("location.href") or ""
    if "accounts.google.com" in url:
        btn = _get_point(client, """() => Array.from(document.querySelectorAll('button')).find(el => {
            const t = (el.innerText||'').trim();
            return t === 'Continue' || t === 'Next';
        })""")
        if btn:
            _click(client, btn)
            client.wait_event("Page.loadEventFired", timeout=20)
            time.sleep(5)


def _dismiss_timezone_popup(client: CdpClient):
    body = client.evaluate("(document.body?.innerText||'').slice(0,4000)") or ""
    if "Timezone Change Detected" not in body:
        return
    pt = _get_point(client, """() => Array.from(document.querySelectorAll('button')).find(el =>
        (el.innerText||'').trim() === 'Yes, update my timezone')""")
    if pt:
        _click(client, pt)
        time.sleep(1)


def _time_to_iso(date_str: str, time_str: str, tz: str = "Europe/London") -> str:
    y, m, d = map(int, date_str.split("-"))
    h, mi = map(int, time_str.split(":"))
    local = datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz))
    utc = local.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def create_poll(
    title: str,
    slots: list[tuple[str, str]],
    tz: str = "Europe/London",
) -> dict:
    """
    Create a Rallly poll with the given title and time slots.
    slots: list of (date_str 'YYYY-MM-DD', time_str 'HH:MM') tuples.
    Returns dict with manage_link and invite_link.
    """
    proc = launch_chrome(WRAPPER_DIR, DEBUG_PORT)
    try:
        ws_url = wait_for_devtools(DEBUG_PORT)
        client = CdpClient(ws_url)
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Input.setIgnoreInputEvents", {"ignore": False})
        client.send("Emulation.setTimezoneOverride", {"timezoneId": tz})

        # Navigate to new poll page
        client.navigate("https://app.rallly.co/new", wait=3)
        _dismiss_timezone_popup(client)

        # Check auth
        logged_in = client.evaluate("(document.body?.innerText||'').includes('Lukas Lipka')")
        if not logged_in:
            _auth_rallly(client)
            client.send("Emulation.setTimezoneOverride", {"timezoneId": tz})
            client.navigate("https://app.rallly.co/new", wait=3)
            _dismiss_timezone_popup(client)
            logged_in = client.evaluate("(document.body?.innerText||'').includes('Lukas Lipka')")
            if not logged_in:
                raise RuntimeError("Rallly auth failed")

        # Fill title
        _set_input(client, 'input[name="title"]', title)

        # Click date buttons (day-of-month numbers)
        dates = sorted(set(d for d, _ in slots))
        for date_str in dates:
            day = str(int(date_str.split("-")[2]))  # strip leading zero
            _click_button(client, day, 0)

        # Enable time slots
        switch = _get_point(client, '() => document.querySelector(\'[data-testid="specify-times-switch"]\')')
        _click(client, switch)
        time.sleep(0.5)

        # Set timezone to London
        client.evaluate(f"""(() => {{
            const inputs = Array.from(document.querySelectorAll('input'));
            const visible = inputs.find(el => el.placeholder === 'Search timezone…');
            const hidden = inputs.find(el => /^Europe\\//.test(el.value || ''));
            if (visible) {{
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                if (setter) setter.call(visible, 'London');
                else visible.value = 'London';
                visible.dispatchEvent(new InputEvent('input', {{ bubbles: true }}));
            }}
            if (hidden) {{
                hidden.value = {json.dumps(tz)};
                hidden.dispatchEvent(new Event('input', {{ bubbles: true }}));
                hidden.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }})()""")

        # Add time option rows per date: each date starts with 1 row
        times_per_date = {}
        for d, t in slots:
            times_per_date.setdefault(d, []).append(t)

        # Add exactly the needed extra rows per date
        for date_idx in range(len(dates)):
            needed = len(times_per_date[dates[date_idx]]) - 1
            for _ in range(needed):
                _click_button(client, "Add time option", date_idx)
        time.sleep(0.5)

        # Set each time slot via the hidden <select> elements
        # Selects are ordered by date, each row has 2 selects (start + end)
        select_idx = 0
        for date_str in dates:
            for t in times_per_date[date_str]:
                iso = _time_to_iso(date_str, t, tz)
                _set_select(client, select_idx, iso, t)
                select_idx += 2  # skip end select

        # Submit
        _click_button(client, "Create Poll", 0)
        time.sleep(2)

        # Wait for success
        deadline = time.time() + 30
        while time.time() < deadline:
            state = client.evaluate("""(() => ({
                url: location.href,
                text: (document.body?.innerText||'').slice(0,4000),
                links: Array.from(document.querySelectorAll('a')).map(a => ({
                    text: (a.innerText||'').trim(), href: a.href
                })).filter(x => x.href.includes('rallly.co'))
            }))()""")
            if state and "Poll created" in (state.get("text") or ""):
                break
            if state and state.get("url", "").startswith("https://app.rallly.co/poll/"):
                break
            time.sleep(0.5)

        client.close()

        # Extract links
        result = {"raw": state}
        if state:
            for link in state.get("links", []):
                href = link.get("href", "")
                if "/poll/" in href and "invite" not in href:
                    result["manage_link"] = href
                if "/invite/" in href:
                    result["invite_link"] = href
        return result
    finally:
        proc.kill()
        proc.wait()
