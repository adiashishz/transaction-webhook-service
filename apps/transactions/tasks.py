import logging
import queue
import threading
import time

from celery import shared_task
from django.conf import settings
from django.db import connection

from apps.transactions.services import TransactionService

logger = logging.getLogger(__name__)


class _Publisher:
    """Publishes to the broker off the request thread, so a broker outage (which can stall a publish for
    seconds, e.g. on DNS timeouts) never delays the webhook's 202.

    The backlog is bounded and the threads are daemons: when the queue is full, or the process exits with
    publishes still pending, those transactions are simply left to the recovery sweep. Their rows are
    already committed, so nothing is lost and shutdown never waits on a stalled broker.
    """

    def __init__(self, workers, backlog):
        self._workers = workers
        self._queue = queue.Queue(maxsize=backlog)
        self._started = False
        self._lock = threading.Lock()

    def submit(self, txn_pk):
        self._start()
        try:
            self._queue.put_nowait(txn_pk)
        except queue.Full:
            logger.warning("Publish backlog full; transaction %s is left to the recovery sweep", txn_pk)
            return False
        return True

    def _start(self):
        # Threads start lazily, in the process that serves requests (gunicorn forks workers after import).
        with self._lock:
            if self._started:
                return
            for i in range(self._workers):
                threading.Thread(target=self._run, name=f"enqueue-{i}", daemon=True).start()
            self._started = True

    def _run(self):
        while True:
            enqueue_transaction(self._queue.get())


_publisher = _Publisher(workers=4, backlog=settings.TRANSACTION_PUBLISH_BACKLOG)


def enqueue_transaction(txn_pk):
    """Hand a transaction to the worker. A broker outage is logged, never raised: the row is already
    durable and the recovery sweep will enqueue it once the broker is back."""
    try:
        process_transaction.delay(txn_pk)
    except Exception:
        logger.exception("Could not enqueue transaction %s; the recovery sweep will retry it", txn_pk)
        return False
    return True


def schedule_transaction(txn_pk):
    """Enqueue in the background so the caller (the webhook view) returns immediately."""
    return _publisher.submit(txn_pk)


def simulate_external_call():
    """Stand-in for the slow downstream call (bank / ledger API) the assessment asks us to simulate."""
    time.sleep(settings.TRANSACTION_PROCESSING_DELAY_SECONDS)


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=5, default_retry_delay=10)
def process_transaction(self, txn_pk):
    token = None
    try:
        token = TransactionService.claim(txn_pk)
        if token is None:
            # Already processed, or another worker holds the lease: never run the external call twice.
            return "skipped"
        # Release the DB connection: the simulated external call should not pin one for 30 seconds.
        # Django reconnects lazily for the final update.
        if not connection.in_atomic_block:
            connection.close()
        simulate_external_call()
        completed = TransactionService.complete(txn_pk, token)
    except Exception as exc:
        logger.exception("Processing transaction %s failed", txn_pk)
        _release_quietly(txn_pk, token)
        raise self.retry(exc=exc)
    if completed:
        logger.info("Processed transaction %s", txn_pk)
    return "processed" if completed else "skipped"


def _release_quietly(txn_pk, token):
    """Free the lease so the retry can claim immediately. If the DB is unreachable the lease simply expires
    and the recovery sweep picks the transaction up."""
    if token is None:
        return
    try:
        TransactionService.release(txn_pk, token)
    except Exception:
        logger.exception("Could not release the lease on transaction %s", txn_pk)


@shared_task
def recover_stale_transactions():
    stale_pks = TransactionService.claim_stale()
    for pk in stale_pks:
        enqueue_transaction(pk)
    if stale_pks:
        logger.warning("Re-enqueued %d stale transactions", len(stale_pks))
    return len(stale_pks)
