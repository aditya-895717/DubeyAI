# DubeyAI — Master Build Prompts (5 Phases)

These prompts are designed to be used sequentially (with Claude, or any AI coding assistant) to build DubeyAI end-to-end, based on `architecture.md`. Each phase assumes the previous phase's output already exists in the project. Paste one phase at a time — do not skip ahead even if tempted, since later phases depend on models/structure created earlier.

---

## PHASE 1 — Django Core Setup, Models & Migrations

```
You are building "DubeyAI" — a Django-based personalized AI assistant PWA.

Set up the Django project core with the following:

1. Create a Django project named `dubeyai` with an app named `core`.
2. Configure settings.py for:
   - SQLite as default DB (local dev)
   - Environment-based config using python-decouple or django-environ (.env file support)
   - Placeholder for Neon (PostgreSQL) DB config, switchable via .env (DB_ENV=local/production)
   - Static/media file handling (Whitenoise for static, media for logo uploads)

3. Create the following models inside `core/models.py` exactly as specified:

   - SiteSettings (singleton pattern — enforce only one row via save() override):
     site_name, logo (ImageField), primary_color, secondary_color, accent_color, font_family, updated_at

   - AIProvider:
     name, api_key (store encrypted — use django-cryptography or a custom encrypted field), 
     endpoint_url, model_name, is_active (boolean; enforce only one active row at a time via save() override), created_at

   - ContentBlock:
     key (unique), value (TextField), updated_at

   - LoginLog:
     user (FK to User), timestamp (auto_now_add), ip_address (nullable)

   - ChatMessage:
     user (FK to User), message, response, intent (choices: query/open_app/set_alarm), timestamp (auto_now_add)

   - Reminder:
     user (FK to User), raw_text, target_time (DateTimeField), status (choices: pending/completed), created_at

   - Command:
     user (FK to User), command_type (choices: open_app/open_web), target, status (choices: pending/executed), created_at

4. Register all models in Django admin (basic registration, we'll build a custom dashboard later — this is just for my own DB inspection during dev).

5. Add a Django signal (using `user_logged_in`) that automatically creates a `LoginLog` entry every time a user logs in, capturing IP address from the request if available.

6. Generate and apply migrations.

7. Create a `.env.example` file listing all expected environment variables (DB credentials, SECRET_KEY, DEBUG, AI provider defaults, companion script API key placeholder).

Give me the full folder structure, all file contents, and the exact commands to run migrations. Do not build any views/templates yet — this phase is models and project scaffolding only.
```

---

## PHASE 2 — Custom Superadmin Dashboard

```
Continuing the DubeyAI Django project from Phase 1 (models: SiteSettings, AIProvider, ContentBlock, LoginLog, ChatMessage, Reminder, Command already exist).

Build a CUSTOM superadmin dashboard — NOT Django's default /admin/ — under URL namespace `/control-panel/`.

Requirements:

1. Access control: Only accessible if `request.user.is_superuser` is True. Redirect everyone else to a 403 or home page. Use a decorator or mixin applied consistently across all control-panel views.

2. Dashboard Home (`/control-panel/`):
   - Show summary stats: total registered users, total chat messages, pending reminders count, pending commands count, currently active AI provider name.

3. Site Settings page (`/control-panel/settings/`):
   - Form to edit: site_name, logo (upload), primary_color, secondary_color, accent_color, font_family
   - Live preview of colors/font if possible (simple CSS preview block)
   - Save updates the singleton SiteSettings row

4. Content Management page (`/control-panel/content/`):
   - List all ContentBlock entries (key + value)
   - Ability to add new key/value pairs and edit/delete existing ones
   - This will later be used to render dynamic text on the user-facing site instead of hardcoded strings

5. AI Provider Management page (`/control-panel/ai-providers/`):
   - List all AIProvider entries with their active/inactive status
   - Structured form to add new provider: name, api_key (masked input), endpoint_url, model_name
   - "Set Active" button/action on each row — activating one automatically deactivates all others (enforce in view or model save())
   - Edit and delete existing providers

6. User Management page (`/control-panel/users/`):
   - List all registered users (username, email, date joined, last login)
   - Show LoginLog history per user (expandable row or separate detail page)

7. Use Django's built-in forms/ModelForms for all CRUD operations. Keep templates simple but clean — use a shared `control_panel_base.html` layout with a sidebar nav (Dashboard, Site Settings, Content, AI Providers, Users).

8. Apply the theme values FROM SiteSettings dynamically into the control panel's own base template (so admin panel also reflects the current branding — confirm this is possible via context processor).

Give me: urls.py entries, views.py (function or class-based, your choice but be consistent), forms.py, and all templates needed. Do not touch the user-facing chat interface yet — this phase is admin-panel only.
```

---

## PHASE 3 — User Auth, Chat Interface & AI Provider Abstraction Layer

```
Continuing the DubeyAI Django project (Phases 1 & 2 complete: models exist, custom superadmin dashboard exists at /control-panel/).

Now build the USER-FACING side:

1. Authentication:
   - Open signup (no approval needed) — signup, login, logout views using Django's built-in auth
   - Standard forms: username, email, password (with confirmation)
   - After signup, auto-login and redirect to chat interface
   - Ensure LoginLog signal from Phase 1 fires correctly on every login

2. AI Provider Abstraction Layer:
   - Create a service class `AIProviderService` in `core/services.py`
   - On instantiation, fetch the currently `is_active=True` AIProvider from DB
   - Method `get_response(prompt: str) -> str` that makes the actual HTTP call to the provider's endpoint_url using its api_key and model_name
   - Structure this so it works for NVIDIA's API format by default, but is generic enough that swapping to OpenAI/other providers only requires changing the DB row, not the code
   - Handle errors gracefully (timeout, invalid key, provider down) — return a user-friendly fallback message, and log the error

3. Intent Engine:
   - Create a function/class `classify_intent(message: str) -> dict` that returns something like:
     `{"intent": "query" | "open_app" | "set_alarm", "entities": {...}}`
   - For "open_app": extract the app name (e.g., "whatsapp", "facebook") from message using keyword matching first; fall back to AI-based classification via AIProviderService if no keyword match found
   - For "set_alarm": extract target date/time from natural language (support Hindi/Hinglish phrases like "kal 9 baje", "abhi se 2 ghante baad") — use a library like `dateparser` if helpful, or a custom rule-based parser; convert to a proper DateTimeField value
   - For anything else: classify as "query" and pass directly to AIProviderService

4. Chat View & Interface:
   - Chat page template (mini ChatGPT-style UI): message history display, input box, send button
   - On message submit:
     - Run through Intent Engine
     - If intent = "query": get response from AIProviderService, save to ChatMessage, display in UI
     - If intent = "open_app": save to Command model (status=pending), show a UI confirmation like "Command sent — will execute shortly" AND simultaneously attempt web-based fallback (e.g., open wa.me link directly in a new tab if it's a whatsapp/facebook style command)
     - If intent = "set_alarm": save to Reminder model (status=pending), show confirmation with parsed time back to user ("Reminder set for tomorrow 9:00 AM")
   - Use AJAX/fetch (no full page reload) for sending messages and displaying responses

5. Dynamic content: Pull any user-facing text (like homepage heading, chat page title) from the ContentBlock model instead of hardcoding it in templates.

6. Apply SiteSettings branding (logo, colors, fonts) to the user-facing templates dynamically, same as admin panel in Phase 2.

Give me: urls.py, views.py, forms.py, services.py (AI abstraction + intent engine), templates (signup, login, chat interface), and the JS needed for AJAX chat behavior. Do not build the PWA manifest/service worker yet — that's Phase 4.
```

---

## PHASE 4 — PWA Layer (Installability, Offline, Push Notifications)

```
Continuing the DubeyAI Django project (Phases 1-3 complete: models, admin dashboard, user auth, chat interface with intent engine all working).

Convert the existing Django app into a full PWA:

1. manifest.json:
   - Dynamically generate values from SiteSettings model (site_name, theme_color from primary_color, background_color, icons) — serve this via a Django view that returns JSON, not a static file, so it updates automatically if admin changes branding
   - Include icons (multiple sizes: 192x192, 512x512) — assume placeholder icon paths for now, tell me where to place actual icon files
   - display: "standalone", start_url: "/", scope: "/"

2. Service Worker (service-worker.js):
   - Cache the app shell (base template, CSS, JS, offline fallback page) on install
   - Serve cached shell when offline
   - Handle push notification events — on receiving a push, show a system notification with title/body from the push payload
   - Handle notification click — focus/open the chat window

3. Push Notification Backend Support:
   - Add a `PushSubscription` model: user (FK), endpoint, p256dh_key, auth_key, created_at
   - View to save browser's push subscription (called from frontend JS after user grants notification permission)
   - Utility function `send_push_notification(user, title, body)` using `pywebpush` library — this will be used later by the companion script's reminder-fire confirmation flow (or by Django itself for any server-triggered notifications)
   - Add VAPID key generation instructions (for Web Push protocol) and where to store these keys in .env

4. Frontend JS:
   - Register the service worker on page load
   - Request notification permission after signup/login (or via a button, not intrusive)
   - Handle `beforeinstallprompt` event to show a custom "Install DubeyAI" button instead of relying on default browser UI

5. Offline behavior:
   - If chat is used offline, queue the message locally (localStorage or IndexedDB) and show "Message will send once you're back online" — sync via a background sync event when connection returns, if feasible; otherwise just block sending and show a clear offline banner

Give me: the manifest view, service-worker.js full content, PushSubscription model + migration, views for saving subscriptions, the pywebpush utility function, VAPID key setup steps, and all frontend JS needed. Also tell me exactly where in the base template the manifest link and service worker registration script need to go.
```

---

## PHASE 5 — Local Companion Script, Vercel Deployment & Domain Setup

```
Continuing the DubeyAI Django project (Phases 1-4 complete: full Django app with models, admin dashboard, chat, intent engine, and PWA layer all functional).

Two remaining pieces:

PART A — Local Companion Script

Build a standalone Python script (separate from the Django project, meant to run locally on my Windows/Mac/Linux machine) with these requirements:

1. Use Flask or FastAPI for a minimal local server (only needed if Django needs to push anything to it directly; otherwise this can be a pure polling loop with no server).
2. Polling loop (every 2-5 seconds):
   - Calls Django REST endpoint (build this endpoint in Django too: `/api/pending-commands/` and `/api/pending-reminders/`) using a static API key sent via header `X-DubeyAI-Key`
   - Django validates this key against a value stored in its own .env before returning any data
3. App Launcher:
   - For each pending Command with command_type=open_app, map target ("whatsapp", "facebook", "notepad", etc.) to actual local executable paths (make this a configurable dict in the script's own config file, since paths differ per OS/user)
   - Use `subprocess.Popen()` to launch the app
   - Call back to Django to mark that Command as `executed` (build this Django endpoint too: `/api/mark-command-done/<id>/`)
4. Alarm Checker:
   - For each pending Reminder, compare `target_time` against local system time
   - When matched (within a small tolerance window, e.g., ±30 seconds), trigger a local desktop notification (use `plyer` or `win10toast` for Windows, or `plyer` cross-platform) and play an alarm sound (use `playsound` or `simpleaudio`)
   - Call back to Django to mark that Reminder as `completed` (endpoint: `/api/mark-reminder-done/<id>/`)
5. Logging: simple console + log file output showing what the script is doing each poll cycle (for my own debugging)
6. Config: all endpoints, API key, and app-path mappings should live in a `config.py` or `.env` file the script reads on startup — nothing hardcoded inline

Give me the full script (main.py + config.py), the three new Django REST endpoints it depends on (pending-commands, pending-reminders, mark-done for both), and instructions for how I'd run this script persistently on my machine (e.g., as a background process/service, not just a terminal window I have to keep open).

PART B — Vercel Deployment & Domain Mapping

1. Give me the exact `vercel.json` configuration needed to deploy this Django project on Vercel (Python serverless function setup), including handling of static files and the WSGI entry point.
2. List all environment variables I need to set in Vercel's dashboard (SECRET_KEY, Neon DB connection string, active AI provider defaults, VAPID keys, companion script API key, DEBUG=False, ALLOWED_HOSTS).
3. Give me the steps to migrate from SQLite to Neon for production (settings.py DB config switch, running migrations against Neon from local machine before/during deploy).
4. Give me the exact DNS records I need to add on my domain registrar's panel to point `adityadubey.co.in` to my Vercel deployment (A record / CNAME as applicable), and the steps inside Vercel to add this custom domain.
5. Confirm what changes (if any) are needed to ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, and manifest.json's start_url once the custom domain is live.

Give me a clear, ordered checklist I can follow step-by-step for this final deployment phase.
```

---

## Usage Notes

- Run these phases **in order**. Each one assumes the previous phase's models/files/endpoints already exist in the codebase.
- After each phase, test locally before moving to the next (especially Phase 1's models — everything downstream depends on field names matching exactly).
- Phase 5 (companion script) can technically be developed in parallel with Phase 4 (PWA) since they don't depend on each other directly, but keep deployment (Part B of Phase 5) last, after everything is verified working locally.
- If you add features later (e.g., multi-admin support, additional AI providers), treat that as a "Phase 6" and write a similar structured prompt following this same format for consistency.
