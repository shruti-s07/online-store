from django.conf import settings
from django.db import models
from django.utils import timezone


class DiscountRule(models.Model):
    """A discount stored as data: `conditions` and `action` are interpreted by engine.py."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    class Source(models.TextChoices):
        MANUAL = "MANUAL"
        SUGGESTED = "SUGGESTED"

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=40, null=True, blank=True, unique=True)
    conditions = models.JSONField(default=dict, blank=True)
    action = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    priority = models.IntegerField(default=0)
    stackable = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    rationale = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class PastPromotion(models.Model):
    """Historical promotion periods, used to estimate price sensitivity."""

    name = models.CharField(max_length=150)
    category = models.ForeignKey("catalog.Category", null=True, blank=True, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.CASCADE)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=4)
    starts_on = models.DateField()
    ends_on = models.DateField()

    class Meta:
        ordering = ["-starts_on"]
