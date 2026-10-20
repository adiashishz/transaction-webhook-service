import os
import subprocess
import sys

import pytest
from django.conf import settings


def import_production_settings(secret_key):
    env = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"}
    if secret_key is not None:
        env["SECRET_KEY"] = secret_key
    return subprocess.run(
        [sys.executable, "-c", "import config.settings.production"],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("secret_key", [None, "", "dev-insecure-key-change-in-production", "change-me-to-a-long-random-string"])
def test_production_refuses_to_start_without_a_real_secret_key(secret_key):
    result = import_production_settings(secret_key)

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr


def test_production_starts_with_a_real_secret_key():
    assert import_production_settings("a-long-random-production-secret-value").returncode == 0
