from datetime import timedelta

from django.conf import settings
from django.db import transaction
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
        """Touch a PROCESSING row so the recovery sweep sees it as in-flight. Returns False if the
        transaction was already processed (e.g. a redelivered task)."""
        claimed = Transaction.objects.filter(pk=txn_pk, status=Transaction.Status.PROCESSING).update(
            updated_at=timezone.now()
        )
        return bool(claimed)

    @staticmethod
    def complete(txn_pk):
        """Mark a transaction processed. The status condition makes this a no-op for a transaction
        that was already completed, so a redelivered task can never process twice."""
        now = timezone.now()
        updated = Transaction.objects.filter(pk=txn_pk, status=Transaction.Status.PROCESSING).update(
            status=Transaction.Status.PROCESSED, processed_at=now, updated_at=now
        )
        return bool(updated)

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
