"""
Django settings for the K.H.S.S.C. Tipsters app.

Designed to run both locally (SQLite, console email) and on Vercel's serverless
runtime against a managed Postgres pooler. All environment-specific values come
from environment variables (loaded from a local .env in development).
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env file in development. In production (Vercel) the platform
# injects environment variables directly, so a missing .env is fine.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


# --- Core security -----------------------------------------------------------

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-key-change-me-in-production-0000000000000000",
)

DEBUG = env_bool("DEBUG", True)

# Hosts. Allow anything the operator lists, plus Vercel's per-deployment and
# production URLs. On Vercel we also allow the *.vercel.app alias wildcard so the
# production alias (which differs from VERCEL_URL) isn't rejected with a 400.
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
for _var in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL"):
    if os.environ.get(_var):
        ALLOWED_HOSTS.append(os.environ[_var])
if os.environ.get("VERCEL"):
    ALLOWED_HOSTS.append(".vercel.app")
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".localhost"]

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
for _var in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL"):
    if os.environ.get(_var):
        CSRF_TRUSTED_ORIGINS.append(f"https://{os.environ[_var]}")
if os.environ.get("VERCEL"):
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")


# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "competition",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tipsters.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "competition.context_processors.active_season",
            ],
        },
    },
]

WSGI_APPLICATION = "tipsters.wsgi.application"


# --- Database ----------------------------------------------------------------
# Local dev defaults to SQLite. Production points DATABASE_URL at the provider's
# transaction-mode pooler (Supabase :6543 / Neon pooled endpoint).
#
# Serverless rules (see spec §2):
#   * CONN_MAX_AGE = 0  -> never hold connections across suspended invocations.
#   * Disable server-side prepared statements -> transaction poolers reject them.
#   * Disable server-side cursors -> not supported in transaction pooling mode.

if os.environ.get("DATABASE_URL"):
    DATABASES = {
        "default": dj_database_url.config(
            env="DATABASE_URL",
            conn_max_age=0,
            ssl_require=env_bool("DB_SSL_REQUIRE", True),
        )
    }
    # psycopg3: prepare_threshold=None disables auto server-side prepared
    # statements, which transaction-mode poolers do not support.
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["prepare_threshold"] = None
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --- Auth --------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"


# --- Internationalisation / time --------------------------------------------
# Datetimes are stored timezone-aware (UTC) and displayed in UK time.

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True


# --- Static files ------------------------------------------------------------
# Served by WhiteNoise/Vercel's CDN after collectstatic.

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Manifest (hashed, compressed) storage in production; plain storage in dev so
# `runserver` works without a collectstatic step.
_staticfiles_backend = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _staticfiles_backend},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Email -------------------------------------------------------------------
# Swappable behind competition.emailing. Resend in production (when RESEND_API_KEY
# is set), console in development.

EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "auto")  # auto | resend | console | smtp
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "K.H.S.S.C. Tipsters <tipsters@example.com>"
)
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")

# Standard SMTP fallback config (only used when EMAIL_PROVIDER=smtp).
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)

# Django's EMAIL_BACKEND is the fallback used when Resend is not active
# (competition.emailing routes to Resend directly when configured).
if EMAIL_PROVIDER == "smtp":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# --- Results provider --------------------------------------------------------
# Swappable behind competition.providers. API-Football when a key is present,
# otherwise a manual no-op provider.

RESULTS_PROVIDER = os.environ.get("RESULTS_PROVIDER", "auto")  # auto | apifootball | manual
APIFOOTBALL_API_KEY = os.environ.get("APIFOOTBALL_API_KEY", "")
APIFOOTBALL_BASE_URL = os.environ.get(
    "APIFOOTBALL_BASE_URL", "https://v3.football.api-sports.io"
)


# --- Reminders ---------------------------------------------------------------
# Hours-before-deadline windows at which to send a reminder to non-submitters.
REMINDER_WINDOWS_HOURS = [
    int(h) for h in os.environ.get("REMINDER_WINDOWS_HOURS", "24,3").split(",") if h
]
# Shared secret so only Vercel Cron can hit the reminder endpoint.
CRON_SECRET = os.environ.get("CRON_SECRET", "")


# --- Security hardening (production) -----------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "2592000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
