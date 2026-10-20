from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.transactions import tasks
from apps.transactions.models import Transaction
from apps.transactions.tests.factories import webhook_payload

pytestmark = pytest.mark.django_db

URL = "/v1/webhooks/transactions"


@pytest.fixture
def client():
    return APIClient()


def test_webhook_returns_202_and_stores_processing_transaction(client, enqueued, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(URL, webhook_payload(), format="json")

    assert response.status_code == 202
    assert response.json() == {
        "message": "Webhook accepted.",
        "transaction_id": "txn_abc123def456",
        "duplicate": False,
    }
    txn = Transaction.objects.get(transaction_id="txn_abc123def456")
    assert (txn.status, txn.amount, txn.currency, txn.processed_at) == ("PROCESSING", Decimal("1500.00"), "INR", None)
    assert enqueued == [str(txn.pk)]


def test_duplicate_webhooks_create_one_transaction_and_one_task(client, enqueued, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        responses = [client.post(URL, webhook_payload(), format="json") for _ in range(3)]

    assert [r.status_code for r in responses] == [202, 202, 202]
    assert [r.json()["duplicate"] for r in responses] == [False, True, True]
    assert Transaction.objects.count() == 1
    assert len(enqueued) == 1


def test_duplicate_with_different_payload_keeps_original(client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.post(URL, webhook_payload(amount=1500), format="json")
        response = client.post(URL, webhook_payload(amount=9999), format="json")

    assert response.status_code == 202
    assert Transaction.objects.get().amount == Decimal("1500.00")


def test_trailing_slash_is_accepted(client):
    response = client.post(f"{URL}/", webhook_payload(), format="json")

    assert response.status_code == 202


def test_decimal_amount_and_lowercase_currency_are_normalised(client):
    client.post(URL, webhook_payload(amount=150.50, currency="usd"), format="json")

    txn = Transaction.objects.get()
    assert (txn.amount, txn.currency) == (Decimal("150.50"), "USD")


@pytest.mark.parametrize(
    "payload",
    [
        webhook_payload(transaction_id=""),
        webhook_payload(amount=0),
        webhook_payload(amount=-10),
        webhook_payload(amount=1.234),
        webhook_payload(amount="abc"),
        webhook_payload(currency="RUPEE"),
        webhook_payload(currency="12A"),
        webhook_payload(currency="ßßß"),
        webhook_payload(currency="日本円"),
        webhook_payload(amount="1234567890123456.78"),
        {k: v for k, v in webhook_payload().items() if k != "destination_account"},
    ],
)
def test_invalid_payload_is_rejected_without_storing(client, enqueued, payload):
    response = client.post(URL, payload, format="json")

    assert response.status_code == 400
    assert Transaction.objects.count() == 0
    assert enqueued == []


def test_malformed_json_is_rejected(client):
    response = client.post(URL, "{not json", content_type="application/json")

    assert response.status_code == 400


def test_broker_outage_still_acknowledges_and_persists(client, monkeypatch, django_capture_on_commit_callbacks):
    def broker_down(txn_pk):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(tasks.process_transaction, "delay", broker_down)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(URL, webhook_payload(), format="json")

    assert response.status_code == 202
    assert Transaction.objects.get().status == "PROCESSING"
