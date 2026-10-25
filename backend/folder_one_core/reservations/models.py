from django.conf import settings
from django.db import models
from django.utils import timezone


class Reservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        CONSUMED = "CONSUMED"
        RELEASED = "RELEASED"
        EXPIRED = "EXPIRED"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reservations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_expired(self) -> bool:
        return self.status == self.Status.EXPIRED or (
            self.status == self.Status.ACTIVE and self.expires_at <= timezone.now())


class ReservationItem(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
