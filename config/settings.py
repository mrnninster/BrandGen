"""
Django settings for the BrandGen proof-of-concept.

API keys and secrets are loaded from the project-root .env file.
"""

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, True),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    OPENAI_IMAGE_MODEL=(str, "gpt-image-1"),
    OPENAI_TEXT_MODEL=(str, "gpt-4o-mini"),
    DEMO_MAX_SLIDES=(int, 1),
    ANALYTICS_DASHBOARD_TOKEN=(str, ""),
    LOG_LEVEL=(str, ""),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-key")
ON_RENDER = os.environ.get("RENDER") == "true"

if ON_RENDER and "DJANGO_DEBUG" not in os.environ:
    DEBUG = False
else:
    DEBUG = env("DJANGO_DEBUG")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_IMAGE_MODEL = env("OPENAI_IMAGE_MODEL")
OPENAI_TEXT_MODEL = env("OPENAI_TEXT_MODEL")
DEMO_MAX_SLIDES = env("DEMO_MAX_SLIDES")
ANALYTICS_DASHBOARD_TOKEN = env("ANALYTICS_DASHBOARD_TOKEN")

# User API keys live in the session only — cleared when the browser closes.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "brandgen.apps.BrandgenConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "brandgen.middleware.request_logging.RequestLoggingMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "brandgen.context_processors.api_key_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database — Postgres when DATABASE_URL is set (Render), SQLite locally
if env("DATABASE_URL", default=""):
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.config(
            conn_max_age=600,
            ssl_require=env.bool("DATABASE_SSL_REQUIRE", default=True),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": 30,
            },
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
if os.environ.get("MEDIA_ROOT"):
    MEDIA_ROOT = Path(os.environ["MEDIA_ROOT"])
elif ON_RENDER:
    MEDIA_ROOT = Path("/var/data/media")
else:
    MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
_render_url = os.environ.get("RENDER_EXTERNAL_URL")
if _render_url:
    origin = _render_url.rstrip("/")
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Logging — stdout for Render / Docker (not Postgres logs).
_LOG_LEVEL = env("LOG_LEVEL", default="DEBUG" if DEBUG else "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": _LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "brandgen": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "gunicorn.error": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
