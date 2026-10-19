import threading
from decimal import Decimal

import pytest
from django.db import connection

from apps.transactions.models import Transaction
from apps.transactions.services import TransactionService
from apps.transactions.tests.factories import webhook_payload


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
