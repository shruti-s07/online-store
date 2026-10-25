from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from backend.shared.roles import DEFAULT_ROLE, ROLE_CHOICES, Role


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.update(role=Role.ADMIN, is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=DEFAULT_ROLE.value, db_index=True)
    phone = models.CharField(max_length=32, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    @property
    def account_age_days(self) -> float:
        return (timezone.now() - self.date_joined).total_seconds() / 86400

    def __str__(self):
        return self.email


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=40)
    full_name = models.CharField(max_length=120)
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=60)
    phone = models.CharField(max_length=32, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "id"]

    def snapshot(self) -> dict:
        return {
            "id": self.id, "label": self.label, "full_name": self.full_name, "line1": self.line1,
            "line2": self.line2, "city": self.city, "state": self.state,
            "postal_code": self.postal_code, "country": self.country, "phone": self.phone,
        }


class Notification(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        SENT = "SENT"
        READ = "READ"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40, db_index=True)
    title = models.CharField(max_length=200)
    body = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


def notify(user, kind: str, title: str, body: str, **payload) -> Notification:
    return Notification.objects.create(user=user, kind=kind, title=title, body=body, payload=payload)


def notify_back_office(kind: str, title: str, body: str, **payload) -> None:
    from backend.shared.roles import BACK_OFFICE_ROLES

    users = User.objects.filter(role__in=[r.value for r in BACK_OFFICE_ROLES], is_active=True)
    Notification.objects.bulk_create(
        [Notification(user=u, kind=kind, title=title, body=body, payload=payload) for u in users]
    )
