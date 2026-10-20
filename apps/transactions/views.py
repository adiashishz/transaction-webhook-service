from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.transactions.models import Transaction
from apps.transactions.permissions import WebhookSignaturePermission
from apps.transactions.serializers import (
    HealthSerializer,
    TransactionSerializer,
    TransactionWebhookSerializer,
    WebhookAcknowledgementSerializer,
)
from apps.transactions.services import TransactionService
from apps.transactions.tasks import schedule_transaction


class HealthCheckView(APIView):
    @extend_schema(responses=HealthSerializer)
    def get(self, request):
        return Response({"status": "HEALTHY", "current_time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")})


class TransactionWebhookView(APIView):
    permission_classes = [WebhookSignaturePermission]

    @extend_schema(request=TransactionWebhookSerializer, responses={202: WebhookAcknowledgementSerializer})
    def post(self, request):
        serializer = TransactionWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txn, created = TransactionService.ingest(**serializer.validated_data)
        if created:
            # ingest() has committed, so the row is durable before the worker can see it.
            schedule_transaction(str(txn.pk))
        return Response(
            {
                "message": "Webhook accepted." if created else "Duplicate webhook ignored; transaction already received.",
                "transaction_id": txn.transaction_id,
                "duplicate": not created,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class TransactionDetailView(APIView):
    @extend_schema(responses=TransactionSerializer(many=True))
    def get(self, request, transaction_id):
        txn = get_object_or_404(Transaction, transaction_id=transaction_id)
        # The assessment's example response is a single-element list.
        return Response([TransactionSerializer(txn).data])
