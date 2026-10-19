import uuid

from django.db import models


class Transaction(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "PROCESSING"
        PROCESSED = "PROCESSED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The processor's ID. The unique constraint is what makes webhook ingestion idempotent.
    transaction_id = models.CharField(max_length=255, unique=True)
    source_account = models.CharField(max_length=255)
    destination_account = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Serves the recovery sweep: PROCESSING rows not touched recently.
            models.Index(fields=["status", "updated_at"], name="txn_status_updated_idx"),
        ]

    def __str__(self):
        return f"{self.transaction_id} ({self.status})"
