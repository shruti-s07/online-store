from django.conf import settings
from django.db import models


class Inventory(models.Model):
    product = models.OneToOneField("catalog.Product", on_delete=models.CASCADE, related_name="inventory")
    on_hand = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "inventory"
        constraints = [models.CheckConstraint(condition=models.Q(on_hand__gte=0), name="inventory_on_hand_non_negative")]


class StockMovement(models.Model):
    class Reason(models.TextChoices):
        INITIAL = "INITIAL"
        RESTOCK = "RESTOCK"
        SALE = "SALE"
        CANCEL = "CANCEL"
        RETURN = "RETURN"
        ADJUSTMENT = "ADJUSTMENT"
        DAMAGE = "DAMAGE"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="stock_movements")
    delta = models.IntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    reference = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
