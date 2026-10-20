import hashlib
import hmac
import json

import pytest
from rest_framework.test import APIClient

from apps.transactions.models import Transaction
from apps.transactions.tests.factories import webhook_payload

pytestmark = pytest.mark.django_db

URL = "/v1/webhooks/transactions"
SECRET = "whsec_test"


def sign(body):
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def body():
    return json.dumps(webhook_payload()).encode()


def test_unsigned_webhook_is_accepted_when_no_secret_is_configured(client, body):
    response = client.post(URL, body, content_type="application/json")

    assert response.status_code == 202


@pytest.mark.parametrize("signature", [None, "", "deadbeef"])
def test_missing_or_wrong_signature_is_rejected_when_secret_is_configured(settings, client, body, signature):
    settings.TRANSACTION_WEBHOOK_SECRET = SECRET
    headers = {} if signature is None else {"HTTP_X_WEBHOOK_SIGNATURE": signature}

    response = client.post(URL, body, content_type="application/json", **headers)

    assert response.status_code == 403
    assert Transaction.objects.count() == 0


def test_correctly_signed_webhook_is_accepted_when_secret_is_configured(settings, client, body):
    settings.TRANSACTION_WEBHOOK_SECRET = SECRET

    response = client.post(URL, body, content_type="application/json", HTTP_X_WEBHOOK_SIGNATURE=sign(body))

    assert response.status_code == 202
    assert Transaction.objects.count() == 1
