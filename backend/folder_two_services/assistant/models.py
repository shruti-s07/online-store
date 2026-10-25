from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    channel = models.CharField(max_length=20)  # "assistant" or "analytics"
    role = models.CharField(max_length=10)  # user / assistant
    content = models.TextField()
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class PendingAction(models.Model):
    """A data-changing tool call proposed by the assistant, executed only after confirmation."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        CONFIRMED = "CONFIRMED"
        CANCELLED = "CANCELLED"
        EXPIRED = "EXPIRED"
        FAILED = "FAILED"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pending_actions")
    tool = models.CharField(max_length=40)
    args = models.JSONField(default=dict)
    summary = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
