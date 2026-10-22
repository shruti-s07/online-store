from django.conf import settings
from django.db import models


class CustomerSegment(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="segment")
    segment = models.CharField(max_length=20, db_index=True)
    cluster = models.PositiveSmallIntegerField()
    recency_days = models.FloatField()
    frequency = models.PositiveIntegerField()
    monetary = models.DecimalField(max_digits=12, decimal_places=2)
    tenure_days = models.FloatField()
    computed_at = models.DateTimeField()
