"""
DubeyAI companion script — configuration.

Everything environment-specific lives here or in .env (copy .env.example to
.env and fill it in). Nothing below should need editing except APP_LAUNCH_MAP,
which maps intent-engine app names to real paths on *this* machine.
"""

import os
import platform
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Which DubeyAI backend to poll
# ---------------------------------------------------------------------------
# DUBEYAI_ENV selects "production" (the live Vercel deployment) or "local"
# (a Django dev server on this same machine). Override the URL directly with
# DUBEYAI_API_BASE_URL if neither preset fits (e.g. a staging deployment).

_ENV_BASE_URLS = {
    "production": "https://dubeyai.adityadubey.co.in",
    "local": "http://127.0.0.1:8000",
}

DUBEYAI_ENV = os.getenv("DUBEYAI_ENV", "production").strip().lower()
API_BASE_URL = os.getenv(
    "DUBEYAI_API_BASE_URL", _ENV_BASE_URLS.get(DUBEYAI_ENV, _ENV_BASE_URLS["production"])
).rstrip("/")

# ---------------------------------------------------------------------------
# Auth — must match COMPANION_API_KEY in the Django backend's own .env /
# Vercel environment variables.
# ---------------------------------------------------------------------------

API_KEY = os.getenv("DUBEYAI_API_KEY", "")
if not API_KEY:
    raise RuntimeError(
        "DUBEYAI_API_KEY is not set. Copy .env.example to .env in this folder "
        "and fill in the same value configured as COMPANION_API_KEY on the "
        "Django backend."
    )

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECONDS = _env_float("POLL_INTERVAL_SECONDS", 3)
REQUEST_TIMEOUT_SECONDS = _env_float("REQUEST_TIMEOUT_SECONDS", 10)
# Reminders fire at or after target_time; this only widens the window
# slightly *before* target_time too, so a poll landing a few seconds early
# still catches it on time rather than waiting for the next cycle.
REMINDER_TOLERANCE_SECONDS = _env_float("REMINDER_TOLERANCE_SECONDS", 30)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE = BASE_DIR / os.getenv("LOG_FILE", "companion.log")

# ---------------------------------------------------------------------------
# Alarm sound (optional) — path to a .wav/.mp3 file to play when a reminder
# fires. Leave ALARM_SOUND_FILE unset/blank to skip sound and rely on the
# desktop notification alone.
# ---------------------------------------------------------------------------

_alarm_sound_file = os.getenv("ALARM_SOUND_FILE", "").strip()
ALARM_SOUND_PATH = (BASE_DIR / _alarm_sound_file) if _alarm_sound_file else None

# ---------------------------------------------------------------------------
# App launcher — map intent-engine app names (see core/services.py's
# APP_ALIASES on the Django side) to what actually opens them on THIS
# machine. A value starting with http(s):// opens in the default browser
# instead of subprocess.Popen — useful for apps you don't have installed
# natively. EDIT THESE PATHS for your own machine/OS.
# ---------------------------------------------------------------------------

_CURRENT_OS = platform.system().lower()  # "windows", "darwin", "linux"

_APP_LAUNCH_MAPS = {
    "windows": {
        "whatsapp": r"C:\Users\%USERNAME%\AppData\Local\WhatsApp\WhatsApp.exe",
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "spotify": r"C:\Users\%USERNAME%\AppData\Roaming\Spotify\Spotify.exe",
        "facebook": "https://facebook.com",
        "youtube": "https://youtube.com",
        "instagram": "https://instagram.com",
        "twitter": "https://twitter.com",
        "gmail": "https://mail.google.com",
    },
    "darwin": {
        "whatsapp": "/Applications/WhatsApp.app",
        "notepad": "/System/Applications/TextEdit.app",
        "calculator": "/System/Applications/Calculator.app",
        "chrome": "/Applications/Google Chrome.app",
        "spotify": "/Applications/Spotify.app",
        "facebook": "https://facebook.com",
        "youtube": "https://youtube.com",
        "instagram": "https://instagram.com",
        "twitter": "https://twitter.com",
        "gmail": "https://mail.google.com",
    },
    "linux": {
        "whatsapp": "whatsapp-for-linux",
        "notepad": "gedit",
        "calculator": "gnome-calculator",
        "chrome": "google-chrome",
        "spotify": "spotify",
        "facebook": "https://facebook.com",
        "youtube": "https://youtube.com",
        "instagram": "https://instagram.com",
        "twitter": "https://twitter.com",
        "gmail": "https://mail.google.com",
    },
}

APP_LAUNCH_MAP = _APP_LAUNCH_MAPS.get(_CURRENT_OS, {})

# Expand %USERNAME%/~ style placeholders in Windows paths so config entries
# above can stay generic across machines without hardcoding a username.
APP_LAUNCH_MAP = {
    name: os.path.expandvars(os.path.expanduser(value)) if not value.startswith("http") else value
    for name, value in APP_LAUNCH_MAP.items()
}
