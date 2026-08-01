"""
DubeyAI — Django project settings.

Environment variables are loaded from a .env file at project root (local) or
from the host process environment (Render / production). Never hardcode secrets.

DB_ENV selects between "local" (SQLite) and "production" (Neon/PostgreSQL) —
see the Database section below.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Helpers for reading environment variables
# ---------------------------------------------------------------------------

def env_bool(name, default=False):
    """Parse a boolean from an environment variable string."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Parse a comma-separated list from an environment variable."""
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_int(name, default):
    """Parse an integer from an environment variable with a safe fallback."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Core security settings
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-dev-key-change-in-prod")

# SECURITY: default to False. An unset DEBUG env var must fail closed, not
# open — this project's live Vercel deployment was found running with
# DEBUG=True precisely because nothing had set it explicitly there.
DEBUG = env_bool("DEBUG", False)

if not DEBUG and SECRET_KEY == "unsafe-dev-key-change-in-prod":
    raise RuntimeError(
        "SECRET_KEY must be set to a real value when DEBUG is False. "
        "Set it in your Vercel/Render environment variables or .env file."
    )

# The production custom domain is always allowed, regardless of whether the
# ALLOWED_HOSTS env var is set on the host — this must not depend on someone
# remembering to configure it. Add any *additional* hosts (e.g. a staging
# domain) via the env var; local dev always gets 127.0.0.1/localhost too.
PRODUCTION_HOST = "dubeyai.adityadubey.co.in"

_allowed_hosts_raw = os.getenv("ALLOWED_HOSTS", "").strip()
ALLOWED_HOSTS = list(
    {
        PRODUCTION_HOST,
        "127.0.0.1",
        "localhost",
        *(h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()),
    }
)

_csrf_raw = os.getenv("CSRF_TRUSTED_ORIGINS", "").strip()
CSRF_TRUSTED_ORIGINS = list(
    {
        f"https://{PRODUCTION_HOST}",
        "http://localhost:8000",
        *(o.strip() for o in _csrf_raw.split(",") if o.strip()),
    }
)

# Render sets RENDER_EXTERNAL_HOSTNAME automatically for every service.
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
if RENDER_EXTERNAL_HOSTNAME:
    if RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

# Vercel sets VERCEL_URL automatically for every deployment (including preview
# deployments, which get a random *.vercel.app URL each time).
VERCEL_URL = os.getenv("VERCEL_URL", "")
if VERCEL_URL:
    if VERCEL_URL not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(VERCEL_URL)
    origin = f"https://{VERCEL_URL}"
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

# Vercel preview deployments each get a unique *.vercel.app hostname that
# VERCEL_URL alone won't cover retroactively — allow the whole subdomain.
if os.getenv("VERCEL", ""):
    ALLOWED_HOSTS.append(".vercel.app")
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chatbot",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise must come right after SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dubeyai.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # project-level templates directory
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_settings",
                "core.context_processors.content_blocks",
                "core.context_processors.vapid_public_key",
            ],
        },
    },
]

WSGI_APPLICATION = "dubeyai.wsgi.application"
ASGI_APPLICATION = "dubeyai.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# DB_ENV selects the environment profile: "local" (SQLite, default) or
# "production" (Neon/PostgreSQL via NEON_DATABASE_URL). DATABASE_URL is kept
# as the primary switch for backward compatibility with the existing Render
# deployment, which sets it directly without setting DB_ENV.

DB_ENV = os.getenv("DB_ENV", "local").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "")
NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "")

_postgres_url = DATABASE_URL or (NEON_DATABASE_URL if DB_ENV == "production" else "")

if _postgres_url:
    import dj_database_url  # noqa: PLC0415

    DATABASES = {
        "default": dj_database_url.config(
            default=_postgres_url,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (CSS, JS, images)
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Project-level static files live in /static/
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # CompressedManifestStaticFilesStorage adds hash fingerprints and
        # gzip/brotli compression for WhiteNoise in production.
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ---------------------------------------------------------------------------
# Media files (user uploads — e.g. SiteSettings.logo)
# ---------------------------------------------------------------------------
# WhiteNoise only serves STATIC_ROOT; in production, MEDIA_ROOT needs an
# object-storage backend (S3/Cloudinary/etc.) — not configured in this phase.

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Django defaults
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Auth redirects — these reference URL *names* defined in chatbot/urls.py
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "chatbot"
LOGOUT_REDIRECT_URL = "login"

# ---------------------------------------------------------------------------
# NVIDIA / OpenAI-compatible API
# ---------------------------------------------------------------------------

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NVIDIA_TIMEOUT_SECONDS = env_int("NVIDIA_TIMEOUT_SECONDS", 90)
NVIDIA_MAX_TOKENS = env_int("NVIDIA_MAX_TOKENS", 4096)

# ---------------------------------------------------------------------------
# Chatbot limits
# ---------------------------------------------------------------------------

CHAT_MAX_MESSAGE_LENGTH = env_int("CHAT_MAX_MESSAGE_LENGTH", 12000)
CHAT_HISTORY_LIMIT = env_int("CHAT_HISTORY_LIMIT", 50)

# ---------------------------------------------------------------------------
# core app — encryption key + companion script auth
# ---------------------------------------------------------------------------
# FIELD_ENCRYPTION_KEY encrypts AIProvider.api_key at rest (see core/fields.py).
#
# SECURITY: this repo is public. The fallback below is a placeholder value for
# a from-scratch local checkout only — it is committed source code, so it can
# never be treated as a secret. Real deployments (and your own local .env, if
# you've configured a real AIProvider) MUST set FIELD_ENCRYPTION_KEY explicitly
# via the environment; never rely on this fallback for anything that encrypts
# real data. Generate your own with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

FIELD_ENCRYPTION_KEY = os.getenv(
    "FIELD_ENCRYPTION_KEY", "yMbAMRyXeDD3dNL_JtMPMg6VCX_ayWWLpZ-63dakpxQ="
)

# Check that the env var was actually SET, not that its value differs from the
# dev fallback — the fallback is itself a real, usable Fernet key (so that
# local dev works out of the box), meaning a value-equality check would wrongly
# reject a production deployment that has correctly been configured with this
# exact value (e.g. because existing encrypted data was created under it).
if not DEBUG and not os.getenv("FIELD_ENCRYPTION_KEY"):
    raise RuntimeError(
        "FIELD_ENCRYPTION_KEY must be set explicitly when DEBUG is False."
    )

# Static API key the local companion script sends as `X-DubeyAI-Key` (Phase 5).
COMPANION_API_KEY = os.getenv("COMPANION_API_KEY", "")

# ---------------------------------------------------------------------------
# Web Push (VAPID) — see .env.example for key-generation instructions
# ---------------------------------------------------------------------------

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "admin@example.com")

# ---------------------------------------------------------------------------
# Security hardening (auto-configured per DEBUG flag)
# ---------------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Must be False so JS can read it if needed
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
# Trust X-Forwarded-Proto from Render's load balancer
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "chatbot": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "core": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
