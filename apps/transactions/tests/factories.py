from decimal import Decimal

from apps.transactions.models import Transaction


def webhook_payload(**overrides):
    payload = {
        "transaction_id": "txn_abc123def456",
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": 1500,
        "currency": "INR",
    }
    return {**payload, **overrides}


def create_transaction(**overrides):
    fields = {
        "transaction_id": "txn_abc123def456",
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": Decimal("1500.00"),
        "currency": "INR",
    }
    return Transaction.objects.create(**{**fields, **overrides})
