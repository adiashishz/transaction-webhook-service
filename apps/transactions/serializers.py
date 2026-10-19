from decimal import Decimal

from rest_framework import serializers

from apps.transactions.models import Transaction


class TransactionWebhookSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(max_length=255)
    source_account = serializers.CharField(max_length=255)
    destination_account = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(min_length=3, max_length=3)

    def validate_currency(self, value):
        if not value.isalpha():
            raise serializers.ValidationError("Currency must be a 3-letter ISO 4217 code.")
        return value.upper()


class WebhookAcknowledgementSerializer(serializers.Serializer):
    message = serializers.CharField()
    transaction_id = serializers.CharField()
    duplicate = serializers.BooleanField()


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            "transaction_id",
            "source_account",
            "destination_account",
            "amount",
            "currency",
            "status",
            "created_at",
            "processed_at",
        ]
        read_only_fields = fields


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    current_time = serializers.CharField()
