from django.urls import path, re_path

from apps.transactions.views import HealthCheckView, TransactionDetailView, TransactionWebhookView

# Paths match the spec exactly (no trailing slash); a trailing slash is also accepted so a webhook
# POST is never bounced by an APPEND_SLASH redirect. Transaction IDs may themselves contain '/'.
urlpatterns = [
    path("", HealthCheckView.as_view(), name="health"),
    re_path(r"^v1/webhooks/transactions/?$", TransactionWebhookView.as_view(), name="transaction-webhook"),
    re_path(r"^v1/transactions/(?P<transaction_id>.+?)/?$", TransactionDetailView.as_view(), name="transaction-detail"),
]
