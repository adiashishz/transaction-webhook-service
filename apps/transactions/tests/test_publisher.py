import threading

from apps.transactions import tasks


def test_publisher_drops_to_recovery_sweep_when_backlog_is_full(monkeypatch):
    picked_up = threading.Event()
    unblock = threading.Event()

    def stalled_broker(txn_pk):
        picked_up.set()
        unblock.wait(timeout=5)

    monkeypatch.setattr(tasks, "enqueue_transaction", stalled_broker)
    publisher = tasks._Publisher(workers=1, backlog=1)

    try:
        assert publisher.submit("first") is True
        assert picked_up.wait(timeout=5)
        assert publisher.submit("second") is True
        assert publisher.submit("third") is False
    finally:
        unblock.set()
