import pytest

from apps.transactions import tasks


@pytest.fixture(autouse=True)
def _instant_processing(settings):
    """Tests never wait out the simulated 30s external call."""
    settings.TRANSACTION_PROCESSING_DELAY_SECONDS = 0


@pytest.fixture(autouse=True)
def enqueued(monkeypatch):
    """Tests never touch the Celery broker: enqueued transaction PKs are recorded instead."""
    calls = []
    monkeypatch.setattr(tasks.process_transaction, "delay", lambda txn_pk: calls.append(txn_pk))
    return calls


class InlineExecutor:
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture(autouse=True)
def _inline_publisher(monkeypatch):
    """Run the off-request broker publish inline so tests are deterministic."""
    monkeypatch.setattr(tasks, "_publisher", InlineExecutor())
