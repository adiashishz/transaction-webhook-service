import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.transactions.models import Transaction
from apps.transactions.services import TransactionService
from apps.transactions.tests.factories import create_transaction, webhook_payload


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_webhooks_create_one_row():
    """Simultaneous deliveries race on the unique constraint; exactly one wins."""
    workers = 8
    barrier = threading.Barrier(workers)
    results = []

    def deliver():
        try:
            barrier.wait()
            _, created = TransactionService.ingest(**webhook_payload(amount=Decimal("1500")))
            results.append(created)
        finally:
            connection.close()

    threads = [threading.Thread(target=deliver) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [False] * (workers - 1) + [True]
    assert Transaction.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_grant_exactly_one_lease():
    """Racing deliveries of the same task: only one may run the external call."""
    txn = create_transaction()
    workers = 8
    barrier = threading.Barrier(workers)
    tokens = []

    def claim():
        try:
            barrier.wait()
            tokens.append(TransactionService.claim(str(txn.pk)))
        finally:
            connection.close()

    threads = [threading.Thread(target=claim) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len([token for token in tokens if token is not None]) == 1


@pytest.mark.django_db
def test_claim_is_refused_while_lease_is_live_and_granted_once_expired(settings):
    settings.TRANSACTION_PROCESSING_LEASE_SECONDS = 120
    txn = create_transaction()

    assert TransactionService.claim(str(txn.pk)) is not None
    assert TransactionService.claim(str(txn.pk)) is None

    Transaction.objects.filter(pk=txn.pk).update(processing_started_at=timezone.now() - timedelta(seconds=121))
    assert TransactionService.claim(str(txn.pk)) is not None


@pytest.mark.django_db
def test_stale_token_cannot_complete_after_lease_takeover(settings):
    settings.TRANSACTION_PROCESSING_LEASE_SECONDS = 120
    txn = create_transaction()
    stale_token = TransactionService.claim(str(txn.pk))
    Transaction.objects.filter(pk=txn.pk).update(processing_started_at=timezone.now() - timedelta(seconds=121))
    current_token = TransactionService.claim(str(txn.pk))

    assert TransactionService.complete(str(txn.pk), stale_token) is False
    assert TransactionService.complete(str(txn.pk), current_token) is True
    assert Transaction.objects.get(pk=txn.pk).status == "PROCESSED"


@pytest.mark.django_db
def test_released_lease_can_be_claimed_again():
    txn = create_transaction()
    token = TransactionService.claim(str(txn.pk))

    assert TransactionService.release(str(txn.pk), token) is True
    assert TransactionService.claim(str(txn.pk)) is not None
