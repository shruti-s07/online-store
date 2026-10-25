from django.conf import settings
from django.db import models


def snapcheck_path(instance, filename):
    return f"snapcheck/{instance.user_id}/{filename}"


class SnapCheck(models.Model):
    class Verdict(models.TextChoices):
        MATCH = "MATCH"
        UNCERTAIN = "UNCERTAIN"
        MISMATCH = "MISMATCH"

    class Status(models.TextChoices):
        OPEN = "OPEN"
        RESOLVED = "RESOLVED"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="snapchecks")
    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.CASCADE, related_name="snapchecks")
    image = models.ImageField(upload_to=snapcheck_path)
    similarity = models.FloatField()
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    method = models.CharField(max_length=120)
    fast_tracked = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    customer_note = models.CharField(max_length=300, blank=True)
    resolution = models.CharField(max_length=300, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fast_tracked", "-created_at"]
