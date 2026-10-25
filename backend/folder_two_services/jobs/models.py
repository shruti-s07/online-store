from django.db import models


class JobRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "RUNNING"
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"

    name = models.CharField(max_length=60, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    detail = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
