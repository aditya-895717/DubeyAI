# DubeyAI — System Architecture Document

**Domain:** adityadubey.co.in
**Project:** DubeyAI — Personalized AI Assistant (PWA)
**Author:** Aditya Dubey
**Version:** 1.0
**Last Updated:** July 2026

---

## 1. Overview

DubeyAI is a personalized AI assistant built as a Progressive Web Application (PWA), inspired by Jarvis-style assistants. It resolves general user queries via an AI API, executes web-based and OS-level commands (via a local companion script), manages time-based reminders/alarms, and provides a fully admin-configurable backend (branding, content, AI provider, and user management) through a custom superadmin dashboard.

### 1.1 Core Capabilities
- Conversational query resolution (mini ChatGPT-style interface)
- Natural language command execution (e.g., "WhatsApp khol do")
- Time-based reminders/alarms (e.g., "kal 9 baje uthana")
- Installable, offline-capable PWA
- Fully admin-configurable: theme, branding, content, AI provider, user records
- Pluggable AI provider system (not hardcoded to one vendor)

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Backend Framework | Django + Django Template Engine |
| Local Database | SQLite |
| Production Database | Neon (PostgreSQL, serverless) |
| AI/LLM Provider | NVIDIA API (NIM) — pluggable, configurable via admin panel |
| Frontend | Django Templates + HTML/CSS/JS (PWA) |
| Hosting/Deployment | Vercel (serverless Python/WSGI functions) |
| Local Companion Script | Python (Flask/FastAPI), runs on user's machine |
| Push Notifications | Web Push API + Service Worker |
| Auth (User) | Django Auth (session-based, open signup) |
| Auth (Companion Script) | Static API key via `.env`, sent in request header |

---

## 3. High-Level Architecture Diagram

```
┌───────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser / Installed PWA)         │
│  ┌─────────────────┐   ┌───────────────────┐   ┌─────────────┐  │
│  │  Chat UI          │   │ Service Worker     │   │ Manifest.json│ │
│  │  (mini ChatGPT)   │   │ (offline cache,    │   │ (installable)│ │
│  │                   │   │  push notif.)      │   │              │ │
│  └────────┬──────────┘   └─────────┬─────────┘   └─────────────┘  │
└───────────┼────────────────────────┼───────────────────────────┘
            │ HTTPS                  │ Push
            ▼                        ▼
┌───────────────────────────────────────────────────────────────┐
│                    DJANGO BACKEND (on Vercel)                    │
│                                                                   │
│  ┌────────────────┐  ┌─────────────────┐  ┌───────────────────┐ │
│  │ Intent Engine    │  │ Superadmin       │  │ User Auth          │ │
│  │ (query/command/  │  │ Dashboard        │  │ (open signup)      │ │
│  │  alarm classify)  │  │ (custom, full CRUD)│ │                    │ │
│  └────────┬─────────┘  └─────────┬───────┘  └────────────────────┘ │
│           │                       │                                  │
│           ▼                       ▼                                  │
│  ┌────────────────┐   ┌─────────────────────────────────────────┐  │
│  │ AI Provider      │   │  Models: SiteSettings, ContentBlock,     │  │
│  │ Abstraction Layer│   │  AIProvider, LoginLog, ChatMessage,      │  │
│  │ (calls active     │   │  Reminder, Command, User                │  │
│  │  provider config) │   └─────────────────────────────────────────┘  │
│  └────────┬─────────┘                                                │
└───────────┼───────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────┐        ┌──────────────────────────────────┐
│   NVIDIA API         │        │       Neon (Production DB)         │
│   (or any active      │        │       SQLite (Local Dev DB)        │
│   provider, per        │        └──────────────────────────────────┘
│   AIProvider model)    │
└────────────────────┘

            ▲
            │ Polling every 2–5 sec (API key auth)
            │
┌───────────────────────────────────────────────────────────────┐
│           LOCAL COMPANION SCRIPT (runs on user's PC)             │
│  ┌────────────────┐  ┌───────────────────┐  ┌────────────────┐  │
│  │ Polling Loop     │  │ App Launcher        │  │ Alarm Checker   │  │
│  │ (fetch pending   │  │ (subprocess.Popen   │  │ (system clock,  │  │
│  │  commands/       │  │  to open native     │  │  fires sound/   │  │
│  │  reminders)      │  │  apps)              │  │  notification)  │  │
│  └────────────────┘  └───────────────────┘  └────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

---

## 4. Roles & Access Control

### 4.1 Superadmin (Single, Fixed Account)
Full control via a **custom-built dashboard** (not Django's default `/admin/`). Capabilities:
- Edit site content dynamically (no hardcoded text/redeployment needed)
- Change branding: logo, theme colors, fonts (full theme control)
- View user login records (audit log: who logged in, when)
- Add/edit/switch AI providers (structured form: name, API key, endpoint, model name)
- Manage users (view list, potentially deactivate)

Access restricted via `is_superuser` check + dedicated URL namespace (e.g., `/control-panel/`).

### 4.2 Normal User (Open Signup)
- Can sign up freely (no approval needed)
- Access limited to: Chat/Assistant interface, command execution, reminders/alarms
- No access to admin/control panel routes

---

## 5. Data Models

### 5.1 `SiteSettings` (Singleton)
| Field | Type | Notes |
|---|---|---|
| site_name | CharField | |
| logo | ImageField | |
| primary_color | CharField | hex code |
| secondary_color | CharField | hex code |
| accent_color | CharField | hex code |
| font_family | CharField | |
| updated_at | DateTimeField | auto |

Enforced as a single row (singleton pattern via `pk=1` override on save).

### 5.2 `AIProvider`
| Field | Type | Notes |
|---|---|---|
| name | CharField | e.g. "NVIDIA", "OpenAI" |
| api_key | CharField (encrypted) | use `django-cryptography` or env-vault approach |
| endpoint_url | URLField | |
| model_name | CharField | |
| is_active | BooleanField | only one active at a time (enforced in `save()`) |
| created_at | DateTimeField | auto |

### 5.3 `ContentBlock`
| Field | Type | Notes |
|---|---|---|
| key | CharField (unique) | e.g. "homepage_heading" |
| value | TextField | rich text/plain |
| updated_at | DateTimeField | auto |

### 5.4 `LoginLog`
| Field | Type | Notes |
|---|---|---|
| user | ForeignKey(User) | |
| timestamp | DateTimeField | auto_now_add |
| ip_address | GenericIPAddressField | optional, nullable |

Populated via Django's `user_logged_in` signal.

### 5.5 `ChatMessage`
| Field | Type | Notes |
|---|---|---|
| user | ForeignKey(User) | |
| message | TextField | user input |
| response | TextField | AI response |
| intent | CharField | query / open_app / set_alarm |
| timestamp | DateTimeField | auto_now_add |

### 5.6 `Reminder`
| Field | Type | Notes |
|---|---|---|
| user | ForeignKey(User) | |
| raw_text | TextField | original message, e.g. "kal 9 baje uthana" |
| target_time | DateTimeField | parsed time |
| status | CharField | pending / completed |
| created_at | DateTimeField | auto_now_add |

### 5.7 `Command`
| Field | Type | Notes |
|---|---|---|
| user | ForeignKey(User) | |
| command_type | CharField | open_app / open_web |
| target | CharField | e.g. "whatsapp", "facebook" |
| status | CharField | pending / executed |
| created_at | DateTimeField | auto_now_add |

---

## 6. Intent Classification Flow

Every incoming chat message is routed through an **Intent Engine** before reaching the AI provider:

```
User Message
     │
     ▼
Intent Engine (rule-based pre-filter + AI-assisted classification)
     │
     ├── "query"      → forwarded to active AIProvider → response saved in ChatMessage
     ├── "open_app"    → saved in Command model (status: pending) → awaiting companion script
     └── "set_alarm"   → parsed for time → saved in Reminder model (status: pending)
                          → awaiting companion script
```

The Intent Engine can itself use the active AI provider (few-shot prompt) to classify intent + extract entities (app name, time), or use a lightweight rule-based regex/keyword pre-filter for speed, falling back to AI classification for ambiguous inputs.

---

## 7. AI Provider Abstraction Layer

To support pluggable AI providers (not hardcoded to NVIDIA):

```python
# Conceptual structure
class AIProviderService:
    def __init__(self):
        self.config = AIProvider.objects.get(is_active=True)

    def get_response(self, prompt: str) -> str:
        # Uses self.config.endpoint_url, self.config.api_key, self.config.model_name
        # Makes HTTP request accordingly
        ...
```

All chat/intent calls go through this abstraction — switching providers in the admin panel changes behavior app-wide without code changes or redeployment.

---

## 8. Local Companion Script

**Purpose:** Handle OS-level actions that a browser/PWA sandbox cannot perform (real app launching, real-time alarms).

### 8.1 Responsibilities
- Poll Django backend every 2–5 seconds for:
  - Pending `Command` entries (open_app/open_web)
  - Pending `Reminder` entries (checked against local system clock)
- On match:
  - **Command:** execute `subprocess.Popen([app_path/command])` to launch the native app; update status to `executed`
  - **Reminder:** when local time reaches `target_time`, fire a desktop notification + alarm sound; update status to `completed`

### 8.2 Authentication
- Simple static API key stored in companion script's `.env`
- Sent as a custom header (e.g., `X-DubeyAI-Key`) on every request to Django API endpoints
- Django validates the key before processing any command/reminder fetch

### 8.3 Why Local (Not Vercel Cron)
Vercel serverless functions are stateless and short-lived — they cannot run persistent background schedulers. Real-time alarm firing and OS app-launching **must** happen locally, using the local machine's own clock and OS access. Django's role is limited to storing/logging intent; execution happens on the companion script side.

---

## 9. PWA Layer

### 9.1 Components
- `manifest.json` — app name, icons, theme colors (pulled from `SiteSettings` where possible), start_url, display: standalone
- `service-worker.js` — handles:
  - Offline caching of static shell (HTML/CSS/JS)
  - Push notification reception and display
- Install prompt handling (`beforeinstallprompt` event)

### 9.2 Web-Based Command Execution (No Companion Script Needed)
For actions that can work purely via browser:
- `https://wa.me/<number>` — opens WhatsApp Web/app if OS handles the URI scheme
- `https://facebook.com` — opens in new tab
- These work directly from the PWA without companion script involvement

### 9.3 Limitation Acknowledged
True native OS automation (launching desktop apps, system-level control) is **not possible from the PWA alone** — this is why the companion script exists as a secondary, locally-run component.

---

## 10. Deployment Architecture

| Environment | Detail |
|---|---|
| Production Backend | Django app deployed on Vercel (serverless Python functions) |
| Production DB | Neon (PostgreSQL) |
| Local Dev DB | SQLite |
| Static Files | Served via Whitenoise or Vercel static handling |
| Domain | adityadubey.co.in (pointed to Vercel deployment) |
| Companion Script | Runs independently on user's local machine (not deployed to Vercel) |

---

## 11. Security Considerations

- API keys for AI providers stored encrypted in DB (not plaintext)
- Companion script authenticates via static API key in header — recommend rotating periodically
- Superadmin routes protected by `is_superuser` decorator/middleware, separate URL namespace
- CSRF protection enabled on all Django forms
- Rate-limiting recommended on chat/query endpoints to control AI API costs
- HTTPS enforced across all endpoints (Vercel handles this by default)

---

## 12. Build Roadmap

| Phase | Task |
|---|---|
| 1 | Django project setup, all models, migrations |
| 2 | Custom superadmin dashboard (Site Settings, Content, AI Provider CRUD, Login Logs, User list) |
| 3 | User auth (signup/login, open registration) |
| 4 | Intent Engine + AI Provider abstraction layer + Chat interface |
| 5 | PWA layer (manifest, service worker, install flow, push notifications) |
| 6 | Local companion script (polling, app launcher, alarm checker) |
| 7 | Neon DB migration for production |
| 8 | Vercel deployment + domain mapping (adityadubey.co.in) |

---

## 13. Known Constraints / Non-Negotiable Facts

1. PWA cannot launch native OS apps directly — companion script is mandatory for this feature.
2. Vercel cannot run persistent background schedulers — alarms are fired locally by the companion script's system clock, not by the server.
3. Companion script must have internet access and a valid API key to sync with the Django backend.
4. Only one AI provider can be "active" at a time; switching is instant via admin panel but affects all users simultaneously.
5. Superadmin is a single, fixed account — no multi-admin role system in this version.
