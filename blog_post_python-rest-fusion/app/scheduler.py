"""Timezone-aware scheduler using only the Python standard library."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.jobs import create_new_post, optimize_posts
from app.utils.time import get_schedule_config
from config.settings import settings

logger = logging.getLogger(__name__)
_stop = threading.Event()
_wake = threading.Event()
_thread: threading.Thread | None = None


def reset_schedule() -> None:
    # get_scheduled_hour validates/reads the persisted scheduler setting. Wake the
    # loop so an operator's update takes effect without a restart.
    config = get_schedule_config()
    hour, minute = (int(part) for part in config["hour"].split(":"))
    if hour not in range(24) or minute not in range(60):
        raise ValueError("Hora de scheduler inválida")
    ZoneInfo(config["timezone"])
    _wake.set()


def _scheduler_loop() -> None:
    last_run_date = None
    local_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="local-publish")
    try:
        while not _stop.is_set():
            try:
                config = get_schedule_config()
                if not config["enabled"]:
                    _wake.wait(timeout=15)
                    _wake.clear()
                    continue
                now = datetime.now(ZoneInfo(config["timezone"]))
                hour, minute = (int(part) for part in config["hour"].split(":"))
                if (now.hour, now.minute) >= (hour, minute) and last_run_date != now.date():
                    # Setting this before dispatch prevents a second run if execution is slow.
                    last_run_date = now.date()
                    logger.info("Starting daily publishing batch at %s", now.isoformat())
                    create_future = local_pool.submit(create_new_post)
                    optimize_future = local_pool.submit(optimize_posts)
                    for future in (create_future, optimize_future):
                        try:
                            future.result()
                        except Exception:
                            logger.exception("A scheduler batch failed")
            except Exception:
                logger.exception("Scheduler loop encountered an error")
            _wake.wait(timeout=15)
            _wake.clear()
    finally:
        local_pool.shutdown(wait=True, cancel_futures=False)


def start_scheduler() -> None:
    global _thread
    if not settings.SCHEDULER_ENABLED or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    reset_schedule()
    _thread = threading.Thread(target=_scheduler_loop, name="post-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()
    _wake.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=60)
