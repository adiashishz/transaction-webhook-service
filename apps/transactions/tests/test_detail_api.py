import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.transactions.tests.factories import create_transaction, webhook_payload

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def test_processing_transaction_is_returned_as_single_item_list(client):
    create_transaction()

    response = client.get("/v1/transactions/txn_abc123def456")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    item = body[0]
    assert set(item) == {
        "transaction_id", "source_account", "destination_account", "amount",
        "currency", "status", "created_at", "processed_at",
    }
    assert (item["status"], item["processed_at"], item["amount"]) == ("PROCESSING", None, 1500.0)
    assert item["created_at"].endswith("Z")


def test_processed_transaction_has_processed_at(client):
    create_transaction(status="PROCESSED", processed_at=timezone.now())

    item = client.get("/v1/transactions/txn_abc123def456/").json()[0]

    assert item["status"] == "PROCESSED"
    assert item["processed_at"].endswith("Z")


def test_unknown_transaction_is_404(client):
    response = client.get("/v1/transactions/txn_missing")

    assert response.status_code == 404


def test_largest_allowed_amount_round_trips_exactly(client):
    client.post("/v1/webhooks/transactions", webhook_payload(transaction_id="txn_big", amount="9999999999999.99"), format="json")

    item = client.get("/v1/transactions/txn_big").json()[0]

    assert item["amount"] == 9999999999999.99
    assert repr(item["amount"]) == "9999999999999.99"


def test_transaction_id_containing_slash_is_retrievable(client):
    create_transaction(transaction_id="order/123")

    response = client.get("/v1/transactions/order/123")

    assert response.status_code == 200
    assert response.json()[0]["transaction_id"] == "order/123"
