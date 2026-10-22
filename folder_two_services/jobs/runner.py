"""Background job bodies. Each run is recorded as a JobRun row (visible in the UI)."""
from __future__ import annotations

import logging
import traceback

from django.db import close_old_connections, connection
from django.utils import timezone

from .models import JobRun

log = logging.getLogger("jobs")


def _recycle_connection():
    # Long-running scheduler process: drop stale connections between jobs (never inside a transaction)
    if not connection.in_atomic_block:
        close_old_connections()


def record(name: str):
    def deco(fn):
        def wrapper(*a, **kw):
            _recycle_connection()
            run = JobRun.objects.create(name=name)
            try:
                detail = fn(*a, **kw) or {}
                run.status, run.detail = JobRun.Status.SUCCEEDED, detail
            except Exception as exc:
                log.exception("Job %s failed", name)
                run.status, run.detail = JobRun.Status.FAILED, {"error": repr(exc), "trace": traceback.format_exc()[-2000:]}
            run.finished_at = timezone.now()
            run.save()
            _recycle_connection()
            return run
        wrapper.__name__ = fn.__name__
        wrapper.job_name = name
        return wrapper
    return deco


@record("release_reservations")
def release_reservations():
    from backend.folder_one_core.reservations.services import expire_stale
    return {"expired": expire_stale()}


@record("send_notifications")
def send_notifications():
    """Simulated delivery channel: pending notifications are 'sent' to the in-app inbox and the log."""
    from backend.folder_one_core.accounts.models import Notification
    pending = list(Notification.objects.filter(status=Notification.Status.PENDING).select_related("user")[:500])
    for n in pending:
        log.info("notify %s [%s] %s", n.user.email, n.kind, n.title)
    Notification.objects.filter(id__in=[n.id for n in pending]).update(status=Notification.Status.SENT,
                                                                         sent_at=timezone.now())
    return {"sent": len(pending)}


@record("low_stock_alert")
def low_stock_alert():
    from backend.folder_one_core.accounts.models import notify_back_office
    from backend.folder_two_services.reports.functions import low_stock
    rows = low_stock()["rows"]
    if rows:
        notify_back_office("low_stock", f"{len(rows)} product(s) low on stock",
                           ", ".join(r[1] for r in rows[:10]), count=len(rows))
    return {"low_stock": len(rows)}


@record("discount_suggestions")
def discount_suggestions():
    from backend.folder_two_services.discounts.suggest import create_drafts
    created = create_drafts()
    if created:
        from backend.folder_one_core.accounts.models import User, notify
        from backend.shared.roles import ADMIN_ROLES
        for admin in User.objects.filter(role__in=list(ADMIN_ROLES)):
            notify(admin, "discount_drafts", f"{len(created)} discount draft(s) to review",
                   "Slow movers were found; approve or reject the drafts in the Discount manager.")
    return {"drafts_created": len(created)}


@record("nightly_training")
def nightly_training():
    from ai.train import train_all
    return train_all()


JOBS = {f.job_name: f for f in (release_reservations, send_notifications, low_stock_alert, discount_suggestions,
                                nightly_training)}
