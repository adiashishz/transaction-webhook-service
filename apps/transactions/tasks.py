import logging
import time
from concurrent.futures import ThreadPoolExecutor

from celery import shared_task
from django.conf import settings
from django.db import connection

from apps.transactions.services import TransactionService

logger = logging.getLogger(__name__)

# Publishing to the broker happens off the request thread. A broker outage can stall a publish for
# seconds (e.g. DNS timeouts), which must never delay the webhook's 202. If the process dies before a
# queued publish runs, nothing is lost: the row is already committed and the recovery sweep picks it up.
_publisher = ThreadPoolExecutor(max_workers=4, thread_name_prefix="enqueue")


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
    _publisher.submit(enqueue_transaction, txn_pk)


def simulate_external_call():
    """Stand-in for the slow downstream call (bank / ledger API) the assessment asks us to simulate."""
    time.sleep(settings.TRANSACTION_PROCESSING_DELAY_SECONDS)


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=5, default_retry_delay=10)
def process_transaction(self, txn_pk):
    try:
        if not TransactionService.claim(txn_pk):
            return "skipped"
        # Release the DB connection: the simulated external call should not pin one for 30 seconds.
        # Django reconnects lazily for the final update.
        if not connection.in_atomic_block:
            connection.close()
        simulate_external_call()
        completed = TransactionService.complete(txn_pk)
    except Exception as exc:
        logger.exception("Processing transaction %s failed", txn_pk)
        raise self.retry(exc=exc)
    if completed:
        logger.info("Processed transaction %s", txn_pk)
    return "processed" if completed else "skipped"


@shared_task
def recover_stale_transactions():
    stale_pks = TransactionService.claim_stale()
    for pk in stale_pks:
        enqueue_transaction(pk)
    if stale_pks:
        logger.warning("Re-enqueued %d stale transactions", len(stale_pks))
    return len(stale_pks)
