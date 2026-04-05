# ralllyMaker

Scan Google Calendar for conflicts, then create a [Rallly](https://rallly.co) scheduling poll with the remaining available time slots.

## How it works

1. **Chrome cookie decryption** — reads and decrypts cookies from your real Chrome profile (`~/.config/google-chrome/Default/Cookies`) using the GNOME keyring secret and the `saltysalt` PBKDF2 derivation.
2. **Google Calendar extraction** — launches a headless Chrome wrapper, injects the decrypted cookies, navigates to Google Calendar, and scrapes visible events for the target date range.
3. **Rallly poll creation** — injects the same Google cookies into the wrapper browser, authenticates to Rallly via "Continue with Google" OAuth, fills in the poll form (title, dates, time slots, timezone), and submits.

## Prerequisites

- Linux with GNOME keyring (for Chrome cookie decryption via `secret-tool`)
- Google Chrome installed at `/usr/bin/google-chrome`
- A Chrome profile signed in to Google at `~/.config/google-chrome/Default`
- Python 3.11+

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Full workflow: scan calendar, create poll with available slots
python -m rallly_maker.cli \
  --title "equity meeting" \
  --start 2026-04-06 \
  --end 2026-04-12 \
  --times "16:30,17:00,17:30,18:00" \
  --tz "Europe/London"

# Skip calendar check, offer all slots
python -m rallly_maker.cli \
  --title "equity meeting" \
  --start 2026-04-06 \
  --end 2026-04-12 \
  --skip-calendar

# Dry run — show available slots without creating the poll
python -m rallly_maker.cli \
  --title "equity meeting" \
  --start 2026-04-06 \
  --end 2026-04-12 \
  --dry-run
```

## Output

On success, prints JSON with `manage_link` and `invite_link` to stdout. Progress and slot info go to stderr.

## Architecture

```
rallly_maker/
├── chrome_cookies.py   # Decrypt Chrome cookies from the real profile
├── cdp.py              # Shared Chrome DevTools Protocol client
├── calendar.py         # Google Calendar event extraction via CDP
├── rallly.py           # Rallly poll creation via CDP
└── cli.py              # CLI entrypoint
```
