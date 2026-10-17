import os
from pathlib import Path
from typing import List

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Automatically load environment variables from .env file if it exists
load_dotenv(BASE_DIR / ".env", override=True)

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-tourmate-production-key-change-in-env-secret-89a12c4",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "t")

ALLOWED_HOSTS: List[str] = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,0.0.0.0,.vercel.app,.now.sh,*",
    ).split(",")
    if host.strip()
]
if ".vercel.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".vercel.app")
if "*" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("*")

CSRF_TRUSTED_ORIGINS = [
    "https://*.vercel.app",
    "https://*.now.sh",
    "http://localhost:8008",
    "http://127.0.0.1:8008",
]

# Allow popups from Google OAuth to postMessage back without being isolated by COOP
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "ninja",
    # Local apps
    "apps.accounts.apps.AccountsConfig",
    "apps.tours.apps.ToursConfig",
    "apps.web.apps.WebConfig",
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

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database & Neon.tech Serverless Connection Pooling Architecture
# ---------------------------------------------------------------------------
# Neon utilizes PgBouncer in transaction pooling mode on port 6543 (hosts with '-pooler').
# When DATABASE_URL is set (e.g. postgresql://...@ep-xxx-pooler.neon.tech:6543/neondb?sslmode=require):
# 1. CONN_MAX_AGE <= 60 (or 0): Neon serverless scales to 0 and suspends inactive computes.
#    Holding long-lived idle connections blocks scale-to-zero and exhausts the pooler limit.
# 2. DISABLE_SERVER_SIDE_CURSORS = True: Essential for PgBouncer transaction pooling mode
#    to prevent 'prepared statement / named cursor' collision errors across transactions.
# 3. sslmode=require is mandatory for Neon.
# For local running without Neon credentials, it seamlessly falls back to SQLite.

LOCAL_SQLITE_URL = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASE_URL = os.environ.get("DATABASE_URL", LOCAL_SQLITE_URL)

import sys
if "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=int(os.environ.get("CONN_MAX_AGE", 300)),  # Persistent connection for fast responses
            conn_health_checks=True,
        )
    }

    # Apply PgBouncer-compatible options when running on PostgreSQL
    if DATABASES["default"].get("ENGINE") == "django.db.backends.postgresql":
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
        DATABASES["default"].setdefault("OPTIONS", {})
        DATABASES["default"]["OPTIONS"]["sslmode"] = "require"


# ---------------------------------------------------------------------------
# Authentication & Google OAuth2 / JWT Configuration
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
JWT_ALGORITHM = "HS256"
JWT_EXP_DAYS = int(os.environ.get("JWT_EXP_DAYS", 7))
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SUPER_ADMIN_EMAILS: List[str] = [
    email.strip().lower()
    for email in os.environ.get(
        "SUPER_ADMIN_EMAILS",
        "warrior.tanveer13@gmail.com,shariful.islam.tanvir13@gmail.com",
    ).split(",")
    if email.strip()
]

# ---------------------------------------------------------------------------
# Email Configuration (Instant Invitation Delivery)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if os.environ.get("EMAIL_HOST_USER") else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    f"TourMate <{EMAIL_HOST_USER or 'noreply@tourmate.test'}>",
)
ENABLE_AUTO_EMAIL_INVITATION = os.environ.get("ENABLE_AUTO_EMAIL_INVITATION", "False").lower() in ("true", "1")

# ---------------------------------------------------------------------------
# Internationalization & Precision
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
WHITENOISE_USE_FINDERS = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
