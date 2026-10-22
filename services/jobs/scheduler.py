"""APScheduler process (python store.py jobs). No Redis/broker: jobs run in this process."""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.loader import business

from . import runner

log = logging.getLogger("jobs")


def build_scheduler() -> BlockingScheduler:
    b = business()
    j = b["jobs"]
    s = BlockingScheduler(timezone="UTC")
    s.add_job(runner.release_reservations, IntervalTrigger(seconds=b["reservations"]["cleanup_interval_seconds"]),
              id="release_reservations", max_instances=1, coalesce=True)
    s.add_job(runner.send_notifications, IntervalTrigger(seconds=j["notification_interval_seconds"]),
              id="send_notifications", max_instances=1, coalesce=True)
    s.add_job(runner.low_stock_alert, CronTrigger(hour=j["low_stock_alert_hour"], minute=0), id="low_stock_alert")
    s.add_job(runner.discount_suggestions, CronTrigger(hour=j["discount_suggestion_hour"], minute=0),
              id="discount_suggestions")
    s.add_job(runner.nightly_training, CronTrigger(hour=j["nightly_training_hour"], minute=j["nightly_training_minute"]),
              id="nightly_training", max_instances=1, coalesce=True)
    return s


def run_forever():
    s = build_scheduler()
    for job in s.get_jobs():
        log.info("scheduled %s: %s", job.id, job.trigger)
    s.start()
