from pathlib import Path

from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-insecure-key-change-in-production")
DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")

DJANGO_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = ["rest_framework", "drf_spectacular"]
LOCAL_APPS = ["apps.transactions"]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="payments"),
        "USER": config("DB_USER", default="payments"),
        "PASSWORD": config("DB_PASSWORD", default="payments"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5435"),
        # Reuse connections across requests so the webhook path skips the TCP/TLS handshake.
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": config("DB_SSLMODE", default="prefer")},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Match the assessment's response shape: amounts as JSON numbers, UTC timestamps with a Z suffix.
    "COERCE_DECIMAL_TO_STRING": False,
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Transaction Webhook Service",
    "DESCRIPTION": "Acknowledges payment webhooks immediately and processes transactions in the background.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Transaction processing
TRANSACTION_PROCESSING_DELAY_SECONDS = config("TRANSACTION_PROCESSING_DELAY_SECONDS", default=30, cast=float)
# Only one worker may run the external call for a transaction at a time. A lease older than this is assumed to
# belong to a crashed worker and can be taken over. Must exceed the processing delay and be below the stale window.
TRANSACTION_PROCESSING_LEASE_SECONDS = config("TRANSACTION_PROCESSING_LEASE_SECONDS", default=120, cast=int)
# A PROCESSING row untouched for this long is assumed lost (worker crash, broker outage) and re-enqueued.
# Must comfortably exceed the processing delay so in-flight work is never treated as stale.
TRANSACTION_STALE_AFTER_SECONDS = config("TRANSACTION_STALE_AFTER_SECONDS", default=300, cast=int)
TRANSACTION_RECOVERY_INTERVAL_SECONDS = config("TRANSACTION_RECOVERY_INTERVAL_SECONDS", default=60, cast=int)
TRANSACTION_RECOVERY_BATCH_SIZE = config("TRANSACTION_RECOVERY_BATCH_SIZE", default=500, cast=int)
# Webhooks waiting to be published to the broker; beyond this they are left to the recovery sweep.
TRANSACTION_PUBLISH_BACKLOG = config("TRANSACTION_PUBLISH_BACKLOG", default=1000, cast=int)
# When set, webhooks must carry X-Webhook-Signature: hex HMAC-SHA256 of the raw body with this secret.
# Empty by default so the assessment's unsigned test webhooks are accepted.
TRANSACTION_WEBHOOK_SECRET = config("TRANSACTION_WEBHOOK_SECRET", default="")

# Celery (Redis is the broker only; results live in Postgres)
CELERY_BROKER_URL = config("REDIS_URL", default="redis://localhost:6381/0")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
# Ack only after the task finishes, and requeue if the worker dies mid-task, so a crash never drops a message.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {
    # Unacked messages are redelivered after this long; must exceed the processing delay.
    "visibility_timeout": config("CELERY_VISIBILITY_TIMEOUT", default=300, cast=int),
    "socket_connect_timeout": 1,
    "socket_timeout": 5,
}
# Keep a broker outage from stalling the webhook response; the recovery sweep enqueues the row later.
CELERY_TASK_PUBLISH_RETRY_POLICY = {"max_retries": 1, "interval_start": 0, "interval_step": 0.1, "interval_max": 0.1}
CELERY_BEAT_SCHEDULE = {
    "recover-stale-transactions": {
        "task": "apps.transactions.tasks.recover_stale_transactions",
        "schedule": float(TRANSACTION_RECOVERY_INTERVAL_SECONDS),
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
        },
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}
