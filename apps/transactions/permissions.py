import hashlib
import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission

SIGNATURE_HEADER = "X-Webhook-Signature"


class WebhookSignaturePermission(BasePermission):
    """Verify that a webhook really comes from the payment processor.

    Enabled only when TRANSACTION_WEBHOOK_SECRET is set: the X-Webhook-Signature header must then equal
    the hex HMAC-SHA256 of the raw request body (the scheme Razorpay uses for X-Razorpay-Signature).
    """

    message = f"Missing or invalid {SIGNATURE_HEADER} header."

    def has_permission(self, request, view):
        secret = settings.TRANSACTION_WEBHOOK_SECRET
        if not secret:
            return True
        # Permissions run before DRF parses the body, so the raw bytes are still available to sign.
        expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, request.headers.get(SIGNATURE_HEADER, ""))
