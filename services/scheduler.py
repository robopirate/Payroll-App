"""In-process background scheduler for daily attendance maintenance tasks.

Render free-tier instances spin down after inactivity, so jobs will not run
while the app is asleep. On every startup the scheduler runs a catch-up for
today's backfill and yesterday's auto-checkout so missed days are not lost.
"""
import os
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def _with_app_context(app, fn):
    """Wrap a callable in the Flask app context for background threads."""
    def wrapper():
        with app.app_context():
            fn()
    return wrapper


def start_scheduler(app):
    """Start APScheduler with the daily backfill and auto-checkout jobs."""
    if os.environ.get('RUN_SCHEDULER', 'true').lower() != 'true':
        return None

    from services.attendance_service import (
        run_monthly_attendance_backfill,
        auto_close_missing_checkouts,
        today_ist,
    )

    scheduler = BackgroundScheduler()

    def backfill_job():
        run_monthly_attendance_backfill(today_ist().year, today_ist().month)

    def checkout_job():
        auto_close_missing_checkouts(today_ist() - timedelta(days=1))

    scheduler.add_job(
        func=_with_app_context(app, backfill_job),
        trigger=CronTrigger(hour=0, minute=5, timezone='Asia/Kolkata'),
        id='backfill_attendance',
        name='Daily attendance backfill (Sundays + absent)',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=_with_app_context(app, checkout_job),
        trigger=CronTrigger(hour=23, minute=55, timezone='Asia/Kolkata'),
        id='auto_checkout',
        name='Daily auto-checkout for missing punch-outs',
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()

    # Catch-up in case the instance was asleep during scheduled times.
    try:
        with app.app_context():
            run_monthly_attendance_backfill(today_ist().year, today_ist().month)
            auto_close_missing_checkouts(today_ist() - timedelta(days=1))
    except Exception:
        app.logger.exception('Scheduler startup catch-up failed')

    return scheduler
