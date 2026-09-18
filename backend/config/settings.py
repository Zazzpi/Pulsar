"""Environment-based settings. Production requires explicit secrets and hosts."""
import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
APP_ENV = os.getenv("APP_ENV", "development")
PRODUCTION = APP_ENV == "production"
DEBUG = os.getenv("DJANGO_DEBUG", "0").lower() in {"1", "true"} and not PRODUCTION
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if PRODUCTION:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production")
    SECRET_KEY = secrets.token_urlsafe(64)

ALLOWED_HOSTS = [value.strip() for value in os.getenv(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]"
).split(",") if value.strip()]
if PRODUCTION and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Explicit DJANGO_ALLOWED_HOSTS are required in production")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "accounts",
    "monitoring",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "config.middleware.SafeApiErrorsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "ru"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False
DATA_UPLOAD_MAX_MEMORY_SIZE = 32 * 1024

if os.getenv("APP_DB_ENGINE", "sqlite") == "postgresql":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("APP_DB_NAME", "pulsar"),
        "USER": os.getenv("APP_DB_USER", "pulsar"),
        "PASSWORD": os.getenv("APP_DB_PASSWORD", ""),
        "HOST": os.getenv("APP_DB_HOST", "localhost"),
        "PORT": os.getenv("APP_DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 5},
    }}
else:
    if PRODUCTION:
        raise ImproperlyConfigured("APP_DB_ENGINE=postgresql is required in production")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("APP_SQLITE_PATH", str(BASE_DIR / "app.sqlite3")),
        "OPTIONS": {"timeout": 5},
    }}

WMS_MODE = os.getenv("WMS_MODE", "mock")
if WMS_MODE not in {"mock", "postgres"}:
    raise ImproperlyConfigured("WMS_MODE must be mock or postgres")
WMS_DB_SSLMODE = os.getenv("WMS_DB_SSLMODE", "require")
if PRODUCTION and WMS_DB_SSLMODE not in {"require", "verify-ca", "verify-full"}:
    raise ImproperlyConfigured("Production WMS_DB_SSLMODE requires TLS: require, verify-ca or verify-full")
DATABASES["wms"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.getenv("WMS_DB_NAME", "wms"),
    "USER": os.getenv("WMS_DB_USER", "wms_readonly"),
    "PASSWORD": os.getenv("WMS_DB_PASSWORD", ""),
    "HOST": os.getenv("WMS_DB_HOST", "localhost"),
    "PORT": os.getenv("WMS_DB_PORT", "5432"),
    "CONN_MAX_AGE": 60,
    "OPTIONS": {
        "options": "-c default_transaction_read_only=on -c statement_timeout=5000",
        "sslmode": WMS_DB_SSLMODE,
        "connect_timeout": 5,
    },
}
DATABASE_ROUTERS = ["config.routers.ApplicationRouter"]

CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "pulsar-api",
    "OPTIONS": {"MAX_ENTRIES": 3000},
}}
CACHE_TTLS = {
    "clients": int(os.getenv("CLIENTS_CACHE_TTL", "60")),
    "client": int(os.getenv("CLIENTS_CACHE_TTL", "60")),
    "summary": int(os.getenv("SUMMARY_CACHE_TTL", "60")),
    "stock": int(os.getenv("STOCK_CACHE_TTL", "60")),
    "orders": int(os.getenv("ORDERS_CACHE_TTL", "60")),
    "receivings": int(os.getenv("RECEIVING_CACHE_TTL", "60")),
    "shipments": int(os.getenv("SHIPMENTS_CACHE_TTL", "60")),
    "movements": int(os.getenv("MOVEMENTS_CACHE_TTL", "60")),
}
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))
DEADLINE_WARNING_HOURS = int(os.getenv("DEADLINE_WARNING_HOURS", "24"))
INTEGRATION_STALE_HOURS = int(os.getenv("INTEGRATION_STALE_HOURS", "1"))
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "20"))
LOGIN_RATE_WINDOW = int(os.getenv("LOGIN_RATE_WINDOW", "300"))
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = PRODUCTION
SECURE_HSTS_PRELOAD = PRODUCTION
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
if os.getenv("TRUST_PROXY_HEADERS", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # Never print SQL parameters or request bodies, even when DEBUG is enabled.
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
