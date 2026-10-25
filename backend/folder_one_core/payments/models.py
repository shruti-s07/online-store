from django.conf import settings
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"
        REFUNDED = "REFUNDED"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    idempotency_key = models.CharField(max_length=100)
    method = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices)
    gateway_ref = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    message = models.CharField(max_length=200, blank=True)
    request_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "idempotency_key"], name="unique_payment_idempotency")]
