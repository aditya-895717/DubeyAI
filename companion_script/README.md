# DubeyAI Companion Script

Standalone script — not part of the Django project, not installed into its
venv. Runs on your own machine, polls the DubeyAI backend, and executes
`open_app` commands and fires `set_alarm` reminders locally.

## Setup

```bash
cd companion_script
python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
copy .env.example .env      # Windows
cp .env.example .env        # macOS/Linux
```

Edit `.env`:
- `DUBEYAI_API_KEY` — must match `COMPANION_API_KEY` set in the Django backend's `.env` (and in Vercel's env vars for production).
- `DUBEYAI_ENV` — `production` (default, hits `https://dubeyai.adityadubey.co.in`) or `local` (hits `http://127.0.0.1:8000` for testing against `manage.py runserver`).

Edit `config.py`'s `APP_LAUNCH_MAP` for your machine — the shipped paths are placeholders (e.g. `notepad.exe`, a guessed WhatsApp install path). Anything not in the map is skipped with a logged warning, not a crash.

Run it directly to confirm it works:

```bash
python main.py
```

You should see poll-cycle log lines in the console and in `companion.log`. Stop with Ctrl+C.

## Running persistently in the background

### Windows — Task Scheduler (no window, starts on login)

1. Open Task Scheduler → **Create Task** (not "Basic Task", so you get the "Run whether user is logged on or not" option).
2. **General** tab: name it `DubeyAI Companion`; check "Run whether user is logged on or not".
3. **Triggers** tab → New → "At log on".
4. **Actions** tab → New:
   - Program/script: full path to `venv\Scripts\pythonw.exe` (the `w` variant runs with no console window)
   - Add arguments: `main.py`
   - Start in: full path to the `companion_script` folder
5. OK, then run it once manually from Task Scheduler to confirm it starts (check `companion.log`).

Equivalent one-liner (run in an elevated prompt, adjust paths):
```powershell
schtasks /create /tn "DubeyAI Companion" /tr "\"C:\path\to\companion_script\venv\Scripts\pythonw.exe\" \"C:\path\to\companion_script\main.py\"" /sc onlogon /rl highest
```

### macOS — launchd

Create `~/Library/LaunchAgents/com.dubeyai.companion.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dubeyai.companion</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/companion_script/venv/bin/python</string>
        <string>/path/to/companion_script/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/companion_script</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/companion_script/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/companion_script/launchd.err.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.dubeyai.companion.plist
# to stop/uninstall:
launchctl unload ~/Library/LaunchAgents/com.dubeyai.companion.plist
```

### Linux — systemd (user service)

Create `~/.config/systemd/user/dubeyai-companion.service`:

```ini
[Unit]
Description=DubeyAI Companion Script
After=network-online.target

[Service]
WorkingDirectory=/path/to/companion_script
ExecStart=/path/to/companion_script/venv/bin/python main.py
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now dubeyai-companion.service
# check status / logs:
systemctl --user status dubeyai-companion.service
journalctl --user -u dubeyai-companion.service -f
```

(Add `loginctl enable-linger $USER` if you want it running even when you're not logged in via a graphical session.)

## Notes

- `playsound` needs GStreamer on some Linux distros for `.mp3`; `.wav` is more portable. If it gives you trouble, drop the `play_alarm_sound()` call in `main.py` and rely on the desktop notification alone.
- `plyer` uses the OS-native notification system (Action Center on Windows, Notification Center on macOS, libnotify on Linux). If it doesn't show anything on Windows, `win10toast` is a drop-in alternative — swap the import in `notify()`.
- The script fires overdue reminders as soon as it notices them (not just within the ±30s window) — if your machine was asleep or the script wasn't running when a reminder was due, it fires as soon as the script next polls, rather than silently missing it forever.
