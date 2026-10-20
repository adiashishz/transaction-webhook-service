from decouple import config
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False

# Refuse to start with a missing or placeholder key instead of silently using a publicly known one.
SECRET_KEY = config("SECRET_KEY", default="")
if not SECRET_KEY or SECRET_KEY.startswith("dev-insecure") or SECRET_KEY.startswith("change-me"):
    raise ImproperlyConfigured("Set SECRET_KEY to a long random value for production.")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
