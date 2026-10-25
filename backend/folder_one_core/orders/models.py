from django.conf import settings
from django.db import models
from django.utils import timezone

from backend.shared.order_states import STATUS_CHOICES, OrderStatus


class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=OrderStatus.PENDING.value, db_index=True)
    payment_method = models.CharField(max_length=10)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    discount_code = models.CharField(max_length=40, blank=True)
    discounts = models.JSONField(default=list, blank=True)
    shipping_address = models.JSONField(default=dict)
    billing_address = models.JSONField(default=dict)
    address_match = models.BooleanField(default=True)
    risk_score = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    risk_level = models.CharField(max_length=8, blank=True, db_index=True)
    risk_reasons = models.JSONField(default=list, blank=True)
    risk_model = models.CharField(max_length=40, blank=True)
    otp_hash = models.CharField(max_length=64, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    checkout_key = models.CharField(max_length=100, blank=True)
    # Set by staff after investigation (also the label for the fraud model)
    fraud_confirmed = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=300, blank=True)
    return_reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "checkout_key"], condition=~models.Q(checkout_key=""),
                                    name="unique_checkout_key_per_user"),
        ]

    def __str__(self):
        return f"Order #{self.id} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="order_items")
    sku = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    actor_label = models.CharField(max_length=20)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
