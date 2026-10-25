from django.conf import settings
from django.db import models
from django.utils import timezone


class Review(models.Model):
    class Status(models.TextChoices):
        VISIBLE = "VISIBLE"
        FLAGGED = "FLAGGED"
        HIDDEN = "HIDDEN"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    order_item = models.ForeignKey("orders.OrderItem", null=True, blank=True, on_delete=models.SET_NULL)
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=150, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.VISIBLE, db_index=True)
    verified_purchase = models.BooleanField(default=False)
    sentiment = models.CharField(max_length=10, blank=True)
    sentiment_score = models.FloatField(null=True, blank=True)
    fake_score = models.FloatField(default=0)
    fake_reasons = models.JSONField(default=list, blank=True)
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    moderated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="one_review_per_user_product"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="rating_1_to_5"),
        ]
