from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.transactions.models import Transaction


class TransactionService:
    @staticmethod
    @transaction.atomic
    def ingest(transaction_id, source_account, destination_account, amount, currency):
        """Persist a webhook as PROCESSING. Returns (transaction, created).

        The row is committed before the caller acknowledges the webhook, so an acknowledged
        transaction can never be lost. get_or_create falls back to a lookup when the unique
        constraint rejects a concurrent duplicate, so replays never create a second row.
        """
        return Transaction.objects.get_or_create(
            transaction_id=transaction_id,
            defaults={
                "source_account": source_account,
                "destination_account": destination_account,
                "amount": amount,
                "currency": currency,
            },
        )

    @staticmethod
    def claim(txn_pk):
        """Take the exclusive processing lease. Returns a claim token, or None if the transaction is already
        processed or another worker holds a live lease.

        A single conditional UPDATE: Postgres re-checks the WHERE clause under the row lock, so when two
        deliveries race exactly one claims the row and runs the external call. A lease older than
        TRANSACTION_PROCESSING_LEASE_SECONDS belongs to a crashed worker and may be taken over. Touching
        updated_at also tells the recovery sweep the row is in flight.
        """
        now = timezone.now()
        lease_expired_before = now - timedelta(seconds=settings.TRANSACTION_PROCESSING_LEASE_SECONDS)
        claimed = (
            Transaction.objects.filter(pk=txn_pk, status=Transaction.Status.PROCESSING)
            .filter(Q(processing_started_at__isnull=True) | Q(processing_started_at__lt=lease_expired_before))
            .update(processing_started_at=now, updated_at=now)
        )
        return now if claimed else None

    @staticmethod
    def complete(txn_pk, token):
        """Mark a transaction processed. The token fences the write: only the worker whose lease is current
        can complete, and a transaction that is already processed is never updated again."""
        now = timezone.now()
        updated = Transaction.objects.filter(
            pk=txn_pk, status=Transaction.Status.PROCESSING, processing_started_at=token
        ).update(status=Transaction.Status.PROCESSED, processed_at=now, updated_at=now)
        return bool(updated)

    @staticmethod
    def release(txn_pk, token):
        """Give up a lease after a failure so a retry can claim the transaction straight away."""
        released = Transaction.objects.filter(
            pk=txn_pk, status=Transaction.Status.PROCESSING, processing_started_at=token
        ).update(processing_started_at=None, updated_at=timezone.now())
        return bool(released)

    @staticmethod
    def claim_stale():
        """Return PKs of PROCESSING rows untouched for longer than the stale window.

        Rows are claimed under SKIP LOCKED and their updated_at bumped, so overlapping sweeps never
        pick the same row and each stale row is re-enqueued at most once per stale window.
        """
        cutoff = timezone.now() - timedelta(seconds=settings.TRANSACTION_STALE_AFTER_SECONDS)
        with transaction.atomic():
            stale_pks = list(
                Transaction.objects.select_for_update(skip_locked=True)
                .filter(status=Transaction.Status.PROCESSING, updated_at__lt=cutoff)
                .order_by("updated_at")
                .values_list("pk", flat=True)[: settings.TRANSACTION_RECOVERY_BATCH_SIZE]
            )
            if stale_pks:
                Transaction.objects.filter(pk__in=stale_pks).update(updated_at=timezone.now())
        return [str(pk) for pk in stale_pks]
