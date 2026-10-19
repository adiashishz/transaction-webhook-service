from datetime import timedelta

import pytest
from django.utils import timezone

from apps.transactions import tasks
from apps.transactions.models import Transaction
from apps.transactions.tests.factories import create_transaction

pytestmark = pytest.mark.django_db


def make_stale(txn, seconds):
    Transaction.objects.filter(pk=txn.pk).update(updated_at=timezone.now() - timedelta(seconds=seconds))


def test_process_transaction_marks_processed():
    txn = create_transaction()

    assert tasks.process_transaction(str(txn.pk)) == "processed"

    txn.refresh_from_db()
    assert txn.status == "PROCESSED"
    assert txn.processed_at is not None and txn.processed_at >= txn.created_at


def test_redelivered_task_does_not_process_twice():
    txn = create_transaction()
    tasks.process_transaction(str(txn.pk))
    first_processed_at = Transaction.objects.get(pk=txn.pk).processed_at

    assert tasks.process_transaction(str(txn.pk)) == "skipped"
    assert Transaction.objects.get(pk=txn.pk).processed_at == first_processed_at


def test_process_transaction_waits_for_simulated_external_call(monkeypatch):
    txn = create_transaction()
    calls = []
    monkeypatch.setattr(tasks, "simulate_external_call", lambda: calls.append(True))

    tasks.process_transaction(str(txn.pk))

    assert calls == [True]


def test_failure_during_processing_leaves_transaction_retryable(monkeypatch):
    txn = create_transaction()

    def downstream_error():
        raise RuntimeError("downstream timeout")

    monkeypatch.setattr(tasks, "simulate_external_call", downstream_error)
    monkeypatch.setattr(tasks.process_transaction, "retry", lambda exc: exc)

    with pytest.raises(RuntimeError):
        tasks.process_transaction(str(txn.pk))

    assert Transaction.objects.get(pk=txn.pk).status == "PROCESSING"


def test_recovery_sweep_reenqueues_only_stale_processing_rows(settings, enqueued):
    settings.TRANSACTION_STALE_AFTER_SECONDS = 300
    stale = create_transaction(transaction_id="txn_stale")
    make_stale(stale, 600)
    create_transaction(transaction_id="txn_fresh")
    done = create_transaction(transaction_id="txn_done", status="PROCESSED", processed_at=timezone.now())
    make_stale(done, 600)

    assert tasks.recover_stale_transactions() == 1
    assert enqueued == [str(stale.pk)]


def test_recovery_sweep_does_not_reenqueue_same_row_within_window(settings, enqueued):
    settings.TRANSACTION_STALE_AFTER_SECONDS = 300
    stale = create_transaction()
    make_stale(stale, 600)

    tasks.recover_stale_transactions()
    tasks.recover_stale_transactions()

    assert enqueued == [str(stale.pk)]
