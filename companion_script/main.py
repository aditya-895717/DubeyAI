"""
DubeyAI companion script — polls the Django backend for pending Commands and
Reminders, executes what it can locally (launching apps, firing alarms), and
reports completion back. Runs indefinitely; see README.md for how to keep it
running in the background without a terminal window open.
"""

import logging
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone

import requests

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("dubeyai-companion")

HEADERS = {"X-DubeyAI-Key": config.API_KEY}


def api_get(path):
    url = f"{config.API_BASE_URL}{path}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.warning("GET %s failed: %s", url, exc)
        return None


def api_post(path):
    url = f"{config.API_BASE_URL}{path}"
    try:
        response = requests.post(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.warning("POST %s failed: %s", url, exc)
        return False


def launch_app(target):
    launch_value = config.APP_LAUNCH_MAP.get(target.lower())
    if not launch_value:
        logger.warning(
            "No launch mapping for app '%s' — skipping. Add it to APP_LAUNCH_MAP in config.py.",
            target,
        )
        return False

    if launch_value.startswith("http://") or launch_value.startswith("https://"):
        webbrowser.open(launch_value)
        logger.info("Opened %s in the default browser for '%s'.", launch_value, target)
        return True

    try:
        subprocess.Popen([launch_value])
        logger.info("Launched '%s' -> %s", target, launch_value)
        return True
    except OSError as exc:
        logger.error("Failed to launch '%s' (%s): %s", target, launch_value, exc)
        return False


def play_alarm_sound():
    if not config.ALARM_SOUND_PATH:
        return
    if not config.ALARM_SOUND_PATH.exists():
        logger.warning("ALARM_SOUND_FILE is set but not found at %s — skipping sound.", config.ALARM_SOUND_PATH)
        return
    try:
        from playsound import playsound

        playsound(str(config.ALARM_SOUND_PATH))
    except Exception as exc:  # playsound raises different errors per platform
        logger.warning("Could not play alarm sound: %s", exc)


def notify(title, message):
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="DubeyAI", timeout=10)
    except Exception as exc:
        logger.warning("Desktop notification failed (%s) — reminder still logged here: %s", exc, message)

    play_alarm_sound()


def process_commands():
    data = api_get("/api/pending-commands/")
    if not data:
        return
    for command in data.get("commands", []):
        if command["command_type"] != "open_app":
            continue
        logger.info("Pending command #%s for %s: open '%s'", command["id"], command["user"], command["target"])
        if launch_app(command["target"]):
            api_post(f"/api/mark-command-done/{command['id']}/")


def process_reminders():
    data = api_get("/api/pending-reminders/")
    if not data:
        return
    now = datetime.now(timezone.utc)
    for reminder in data.get("reminders", []):
        target_time = datetime.fromisoformat(reminder["target_time"])
        seconds_until_due = (target_time - now).total_seconds()

        # Fire once we're within the tolerance window before target_time, and
        # for any amount of time *after* it — a reminder that fires late
        # (because the script wasn't running) is far better than one that
        # silently never fires because it missed a narrow window.
        if seconds_until_due > config.REMINDER_TOLERANCE_SECONDS:
            continue

        logger.info("Reminder #%s for %s is due: %s", reminder["id"], reminder["user"], reminder["raw_text"])
        notify("DubeyAI Reminder", reminder["raw_text"])
        api_post(f"/api/mark-reminder-done/{reminder['id']}/")


def main():
    logger.info("DubeyAI companion script starting. Target: %s", config.API_BASE_URL)
    while True:
        try:
            process_commands()
            process_reminders()
        except Exception:
            logger.exception("Unexpected error during poll cycle — continuing.")
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
