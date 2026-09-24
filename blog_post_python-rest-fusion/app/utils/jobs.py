"""Atomic scheduler jobs with one durable execution row per post."""

import logging
from datetime import datetime

from sqlalchemy import text, update

from app.controllers.orchestrator import PostOrchestrator
from app.core.execution_logging import execution_context, flush_execution_logs
from app.models.execution import Execution
from app.models.optimize import OptimizedPost
from app.models.post import Post
from config.database import SessionLocal
from config.settings import settings

logger = logging.getLogger(__name__)


def _claim_due_ids(db, model, *, limit: int) -> list[int]:
    """Claim due rows in one UPDATE; SKIP LOCKED prevents competing workers."""
    table = model.__tablename__
    result = db.execute(text(f"""
        UPDATE {table}
        SET state = 'claimed', claimed_at = now(), attempts = attempts + 1
        WHERE id IN (
            SELECT id FROM {table}
            WHERE state = 'pending'
              AND date::date = (now() AT TIME ZONE :timezone)::date
            ORDER BY date, id
            FOR UPDATE SKIP LOCKED
            LIMIT :batch_size
        )
        RETURNING id
    """), {"timezone": _timezone(db), "batch_size": limit})
    ids = [int(row[0]) for row in result.fetchall()]
    db.commit()
    return ids


def _timezone(db) -> str:
    from app.models.schedule_config import ScheduleConfig

    row = db.query(ScheduleConfig).filter(ScheduleConfig.id == 1).first()
    return row.timezone if row else settings.SCHEDULER_TIMEZONE


def _mark_stale_claimed_failed(db, model) -> None:
    """Surface abandoned claims; never silently republish them on a later run."""
    db.execute(
        update(model)
        .where(model.state.in_(["claimed", "running"]), model.claimed_at < text("now() - interval '30 minutes'"))
        .values(state="failed", last_error="Execution interrupted before completion", claimed_at=None)
    )
    db.commit()


def _finish(db, model, item_id: int, *, error: str | None = None) -> None:
    item = db.query(model).filter(model.id == item_id).first()
    if item:
        item.state = "failed" if error else "done"
        item.last_error = error[:4000] if error else None
        item.claimed_at = None
        db.commit()


def _run(model, capability: str) -> None:
    db = SessionLocal()
    try:
        _mark_stale_claimed_failed(db, model)
        ids = _claim_due_ids(db, model, limit=settings.SCHEDULER_BATCH_SIZE)
        logger.info("Scheduler claimed %d pending items for %s", len(ids), capability)
        orchestrator = PostOrchestrator(db)
        for item_id in ids:
            item = db.query(model).filter(model.id == item_id).first()
            if item is None or item.state != "claimed":
                continue
            item.state = "running"
            db.commit()
            external_id = f"scheduler:{capability}:{item_id}"
            execution = db.query(Execution).filter(Execution.external_id == external_id).first()
            if execution and execution.status == "completed":
                item.state, item.claimed_at = "done", None
                db.commit()
                continue
            if execution is None:
                execution = Execution(
                    source="scheduler", kind="optimize" if capability.endswith("optimize") else "create",
                    campaign_id=item.campaign_id, post_id=item.id, external_id=external_id,
                    status="running", title=item.title, started_at=datetime.utcnow(),
                )
                db.add(execution)
            else:
                execution.status, execution.error = "running", None
                execution.result = None
                execution.started_at = datetime.utcnow()
                execution.completed_at = None
            db.commit()
            try:
                with execution_context(execution.id):
                    logger.info("Starting %s for post %s", capability, item_id)
                    if capability == "posts.create":
                        result = orchestrator.create_new_post(
                            item.campaign_id, item, item.language, external_id=external_id
                        )
                    else:
                        result = orchestrator.optimize_post(item.campaign_id, item, item.language)
                    _finish(db, model, item_id)
                    execution.status = "completed"
                    execution.result = result
                    execution.completed_at = datetime.utcnow()
                    db.commit()
                    logger.info("Completed %s for post %s", capability, item_id)
                flush_execution_logs()
            except Exception as exc:
                db.rollback()
                with execution_context(execution.id):
                    logger.exception("Scheduled %s item %s failed", capability, item_id)
                _finish(db, model, item_id, error=str(exc))
                execution = db.query(Execution).filter(Execution.external_id == external_id).first()
                if execution:
                    execution.status = "failed"
                    execution.error = str(exc)[:4000]
                    execution.completed_at = datetime.utcnow()
                    db.commit()
                flush_execution_logs()
    finally:
        db.close()


def create_new_post() -> None:
    _run(Post, "posts.create")


def optimize_posts() -> None:
    _run(OptimizedPost, "posts.optimize")
