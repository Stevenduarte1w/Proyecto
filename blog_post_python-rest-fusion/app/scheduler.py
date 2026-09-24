"""Timezone-aware daily batch scheduler with a dedicated local worker pool."""

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import RLock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from app.utils.jobs import create_new_post, optimize_posts
from app.utils.time import get_schedule_config
from config.settings import settings

logger = logging.getLogger(__name__)
_guard = RLock()
_scheduler: BackgroundScheduler | None = None
_local_pool = ThreadPoolExecutor(
    max_workers=max(2, settings.LOCAL_MAX_CONCURRENCY),
    thread_name_prefix="local-publish",
)


def _run_daily_batch() -> None:
    """Run create and optimize batches concurrently in the local channel pool."""
    futures = [
        _local_pool.submit(create_new_post),
        _local_pool.submit(optimize_posts),
    ]
    for future in futures:
        try:
            future.result()
        except Exception:
            logger.exception("A scheduler batch failed")


def _ensure_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    return _scheduler


def reset_schedule() -> None:
    """Apply the persisted hour, timezone, and enabled flag immediately."""
    config = get_schedule_config()
    hour, minute = (int(part) for part in config["hour"].split(":"))
    if hour not in range(24) or minute not in range(60):
        raise ValueError("Hora de scheduler inválida")
    timezone = ZoneInfo(config["timezone"])

    with _guard:
        scheduler = _ensure_scheduler()
        if scheduler.get_job("daily_batch"):
            scheduler.remove_job("daily_batch")
        if config["enabled"] and settings.SCHEDULER_ENABLED:
            scheduler.add_job(
                _run_daily_batch,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
                id="daily_batch",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )
        if not scheduler.running:
            scheduler.start()


def start_scheduler() -> None:
    reset_schedule()


def stop_scheduler() -> None:
    global _scheduler
    with _guard:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=True)
        _scheduler = None


def shutdown_local_pool() -> None:
    _local_pool.shutdown(wait=True, cancel_futures=False)
