"""Atomic scheduler jobs. Every item is claimed before any network/AI work starts."""

import logging
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, update

from app.controllers.orchestrator import PostOrchestrator
from app.models.execution import Execution
from app.models.optimize import OptimizedPost
from app.models.post import Post
from config.database import SessionLocal
from app.utils.time import get_schedule_config

logger = logging.getLogger(__name__)


def _today_window() -> tuple[datetime, datetime]:
    local_now = datetime.now(ZoneInfo(get_schedule_config()["timezone"]))
    start = datetime.combine(local_now.date(), time.min)
    return start, start + timedelta(days=1)


def _claim(db, model, item_id: int) -> bool:
    now = datetime.utcnow()
    stale_before = now - timedelta(seconds=900)
    result = db.execute(
        update(model)
        .where(model.id == item_id, model.status.is_(False), or_(
            model.state == "pending",
            and_(model.state == "running", model.claimed_at < stale_before),
        ))
        .values(state="running", attempts=model.attempts + 1, claimed_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _finish(db, model, item_id: int, *, error: str | None = None) -> None:
    item = db.query(model).filter(model.id == item_id).first()
    if not item:
        return
    item.state = "failed" if error else "succeeded"
    item.status = not error
    item.last_error = error[:4000] if error else None
    item.claimed_at = None
    db.commit()


def _run(model, capability: str) -> None:
    db = SessionLocal()
    try:
        start, end = _today_window()
        now = datetime.utcnow()
        stale_before = now - timedelta(seconds=900)
        ids = [row[0] for row in db.query(model.id).filter(
            model.date >= start, model.date < end, model.status.is_(False), or_(
                model.state == "pending",
                and_(model.state == "running", model.claimed_at < stale_before),
            )
        ).order_by(model.id).all()]
        logger.info("Scheduler found %d pending items for %s", len(ids), capability)
        orchestrator = PostOrchestrator(db)
        for item_id in ids:
            if not _claim(db, model, item_id):
                continue
            item = db.query(model).filter(model.id == item_id).first()
            external_id = f"scheduler:{capability}:{item_id}"
            execution = db.query(Execution).filter(Execution.external_id == external_id).first()
            if execution and execution.status == "succeeded":
                item.state, item.status, item.claimed_at = "succeeded", True, None
                db.commit()
                continue
            if execution is None:
                execution = Execution(external_id=external_id, source="scheduler",
                                      capability=capability, status="running")
                db.add(execution)
            else:
                execution.status, execution.error = "running", None
            db.commit()
            try:
                if capability == "posts.create":
                    result = orchestrator.create_new_post(item.campaign_id, item, item.language,
                                                          external_id=external_id)
                else:
                    result = orchestrator.optimize_post(item.campaign_id, item, item.language)
                _finish(db, model, item_id)
                execution.status = "succeeded"
                execution.result = json.dumps(result, ensure_ascii=False)[:16000]
            except Exception as exc:
                logger.exception("Scheduled %s item %s failed", capability, item_id)
                _finish(db, model, item_id, error=str(exc))
                execution.status = "failed"
                execution.error = str(exc)[:4000]
            db.commit()
    finally:
        db.close()


def create_new_post() -> None:
    _run(Post, "posts.create")


def optimize_posts() -> None:
    _run(OptimizedPost, "posts.optimize")
