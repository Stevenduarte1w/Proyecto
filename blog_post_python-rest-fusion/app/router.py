from __future__ import annotations

import json
import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.controllers.orchestrator import PostOrchestrator
from app.core.content_assembler import build_links
from app.core.execution_logging import execution_context, flush_execution_logs
from app.core.publishing_service import PublishRequest, PublishingService
from app.models.campaign import Campaign
from app.models.execution import Execution, ExecutionLog
from app.models.optimize import OptimizedPost
from app.models.post import Post
from app.models.wordpress_site import WordPressSite
from app.schemas.orchestrator import OrchestratorJob, OrchestratorPost
from app.services.post import PostService
from app.services.optimize import OptimizedPostService
from app.utils.image_resolver import resolve_image
from app.utils.massive_uploader import upload_new_posts, upload_optimize_posts
from app.utils.time import get_schedule_config, set_scheduled_hour
from app.scheduler import reset_schedule
from config.database import get_db
from config.settings import settings

router = APIRouter(prefix="/api", tags=["api"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db)):
    rows = db.query(Campaign, WordPressSite).join(
        WordPressSite, Campaign.wordpress_site_id == WordPressSite.id
    ).order_by(Campaign.name).all()
    return [{"id": campaign.id, "name": campaign.name, "is_active": campaign.is_active,
             "wordpress_site_id": site.id, "site_url": site.url,
             "credential_configured": bool(os.getenv(site.credential_ref)),
             "yoast_enabled": site.yoast_enabled}
            for campaign, site in rows]


@router.get("/schedule")
def get_schedule():
    return get_schedule_config()


@router.put("/schedule")
@router.post("/schedule")
async def set_schedule(request: Request):
    data = await request.json()
    hour = data.get("hour")
    try:
        datetime.strptime(hour, "%H:%M")
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="La hora debe tener formato HH:MM")
    timezone = data.get("timezone")
    if timezone:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, TypeError):
            raise HTTPException(status_code=422, detail="Zona horaria IANA no válida")
    enabled = data.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled debe ser booleano")
    set_scheduled_hour(hour, timezone=timezone, enabled=enabled)
    reset_schedule()
    return {"message": "Horario actualizado", **get_schedule_config()}


@router.get("/queue")
def list_local_queue(kind: str | None = None, state: str | None = None,
                     limit: int = 100, db: Session = Depends(get_db)):
    if kind not in {None, "create", "optimize"}:
        raise HTTPException(status_code=422, detail="kind debe ser create u optimize")
    if state not in {None, "pending", "claimed", "running", "done", "failed"}:
        raise HTTPException(status_code=422, detail="state no válido")
    rows = []
    if kind in {None, "create"}:
        query = db.query(Post)
        if state:
            query = query.filter(Post.state == state)
        rows.extend({"kind": "create", "id": item.id, "campaign_id": item.campaign_id,
                     "title": item.title, "date": item.date, "state": item.state,
                     "attempts": item.attempts, "last_error": item.last_error,
                     "wp_post_id": item.wp_post_id, "wp_post_url": item.wp_post_url}
                    for item in query.order_by(Post.date, Post.id).limit(min(max(limit, 1), 500)))
    if kind in {None, "optimize"}:
        query = db.query(OptimizedPost)
        if state:
            query = query.filter(OptimizedPost.state == state)
        rows.extend({"kind": "optimize", "id": item.id, "campaign_id": item.campaign_id,
                     "title": item.title, "date": item.date, "state": item.state,
                     "attempts": item.attempts, "last_error": item.last_error,
                     "wp_post_id": item.wp_post_id, "wp_post_url": item.edition_url}
                    for item in query.order_by(OptimizedPost.date, OptimizedPost.id).limit(min(max(limit, 1), 500)))
    return sorted(rows, key=lambda row: (row["date"], row["id"]))[:min(max(limit, 1), 500)]


@router.post("/posts/upload/new")
def upload_posts(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or Path(file.filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=415, detail="El archivo debe ser .xlsx")
    return upload_new_posts(file.file, db)


@router.post("/posts/upload/optimized")
def upload_optimized_posts(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or Path(file.filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=415, detail="El archivo debe ser .xlsx")
    return upload_optimize_posts(file.file, db)


def _claim_manual(db: Session, model, item_id: int):
    if not db.query(model.id).filter(model.id == item_id).first():
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    from sqlalchemy import update
    from sqlalchemy import and_, or_
    now = datetime.utcnow()
    stale_before = now - timedelta(seconds=900)
    result = db.execute(update(model).where(
                            model.id == item_id, or_(
                                model.state.in_(["pending", "failed"]),
                                and_(model.state == "running", model.claimed_at < stale_before),
                            ))
                        .values(state="running", attempts=model.attempts + 1, claimed_at=now)
                        .execution_options(synchronize_session=False))
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="El trabajo ya está en ejecución o ya terminó")


def _run_manual(item_id: int, model, capability: str, db: Session) -> dict[str, Any]:
    _claim_manual(db, model, item_id)
    item = db.query(model).filter(model.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    execution = Execution(
        source="api", kind="optimize" if capability.endswith("optimize") else "create",
        campaign_id=item.campaign_id, post_id=item.id, external_id=f"manual:{uuid.uuid4()}",
        status="running", title=item.title, started_at=datetime.utcnow(),
    )
    db.add(execution)
    db.commit()
    try:
        with execution_context(execution.id):
            logger.info("Starting manual %s for item %s", capability, item.id)
            orchestrator = PostOrchestrator(db)
            if capability == "posts.create":
                result = orchestrator.create_new_post(item.campaign_id, item, item.language)
                item.wp_post_id = result.get("wp_post_id")
                item.wp_post_url = result.get("wp_post_url")
                item.published_at = datetime.utcnow()
            else:
                result = orchestrator.optimize_post(item.campaign_id, item, item.language)
                item.optimized_at = datetime.utcnow()
            item.state, item.last_error, item.claimed_at = "done", None, None
            execution.status, execution.result = "completed", result
            execution.completed_at = datetime.utcnow()
            db.commit()
            logger.info("Completed manual %s for item %s", capability, item.id)
        flush_execution_logs()
        return {"execution_id": str(execution.id), **(result or {})}
    except Exception as exc:
        db.rollback()
        with execution_context(execution.id):
            logger.exception("Manual %s failed for item %s", capability, item_id)
        item = db.query(model).filter(model.id == item_id).first()
        if item:
            item.state, item.last_error, item.claimed_at = "failed", str(exc)[:4000], None
        execution = db.query(Execution).filter(Execution.id == execution.id).first()
        if execution:
            execution.status, execution.error = "failed", str(exc)[:4000]
            execution.completed_at = datetime.utcnow()
        db.commit()
        flush_execution_logs()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/posts/{post_id}/run")
def run_post(post_id: int, db: Session = Depends(get_db)):
    return _run_manual(post_id, Post, "posts.create", db)


@router.post("/optimized/{post_id}/run")
def run_optimization(post_id: int, db: Session = Depends(get_db)):
    return _run_manual(post_id, OptimizedPost, "posts.optimize", db)


@router.post("/optimized/{post_id}/rollback")
def rollback_optimization(post_id: int, db: Session = Depends(get_db)):
    item = db.query(OptimizedPost).filter(OptimizedPost.id == post_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Optimización no encontrada")
    try:
        return PublishingService(db).rollback(item)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/executions")
def list_executions(source: str | None = None, status: str | None = None,
                    limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(Execution)
    if source:
        query = query.filter(Execution.source == source)
    if status:
        query = query.filter(Execution.status == status)
    return query.order_by(Execution.created_at.desc()).limit(min(max(limit, 1), 500)).all()


@router.get("/executions/{execution_id}")
def get_execution(execution_id: UUID, db: Session = Depends(get_db)):
    result = db.query(Execution).filter(Execution.id == execution_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    logs = db.query(ExecutionLog).filter(ExecutionLog.execution_id == execution_id).order_by(ExecutionLog.id).all()
    return {"execution": result, "logs": logs}


def _orchestrator_auth(authorization: str | None) -> None:
    if not settings.ORCHESTRATOR_ENABLED:
        raise HTTPException(status_code=404, detail="Canal del orquestador deshabilitado")
    if not settings.ORCHESTRATOR_TOKEN:
        raise HTTPException(status_code=503, detail="ORCHESTRATOR_TOKEN no está configurado")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, settings.ORCHESTRATOR_TOKEN):
        raise HTTPException(status_code=401, detail="Bearer token inválido")


def _normalize_post(raw: dict[str, Any], fallback_campaign: int | None) -> OrchestratorPost:
    aliases = {"post_title": "title", "body": "content", "text": "content",
               "category": "categories", "image_url": "image", "post_url": "edition_url",
               "tags": "hashtags", "wp_post_id": "wp_post_id", "campaign": "campaign_id"}
    normalized = dict(raw)
    for old, new in aliases.items():
        if new not in normalized and old in normalized:
            normalized[new] = normalized[old]
    normalized.setdefault("campaign_id", fallback_campaign)
    try:
        return OrchestratorPost.model_validate(normalized)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Payload de post inválido: {exc}") from exc


def _publish_external(db: Session, post: OrchestratorPost, capability: str, external_id: str) -> dict[str, Any]:
    image_path = original_path = None
    try:
        keep_image = capability == "posts.optimize" and post.keep_featured_image
        if not keep_image:
            image_path, original_path = resolve_image(
                drive_url=post.image, image_prompt=post.image_prompt, title=post.title,
                output_dir=str(Path(settings.IMAGE_OUTPUT_DIR) / uuid.uuid4().hex), api_key=settings.OPENAI_API_KEY,
                image_model=settings.OPENAI_IMAGE_MODEL,
            )
        external_links = build_links(post.external, post.external_url, strict=True)
        publisher = PublishingService(db)
        if capability == "posts.create":
            return publisher.publish(PublishRequest(
                campaign_id=post.campaign_id, title=post.title, content=post.content,
                seo_title=post.seo_title, slug=post.slug,
                meta_description=post.meta_description, keyphrase=post.keyphrase or post.title,
                categories=post.categories, hashtags=post.hashtags,
                image_path=str(image_path), external_link=post.external_link or (external_links[0] if external_links else ""),
                citys=post.citys, citys_urls=post.citys_urls,
                create_category=post.create_category, external_id=external_id,
            ))
        target = post.edition_url or (str(post.wp_post_id) if post.wp_post_id else "")
        if not target:
            raise ValueError("posts.optimize requiere edition_url, post_url o wp_post_id")
        execution = db.query(Execution).filter(Execution.external_id == external_id).first()
        saved = execution.result if execution and isinstance(execution.result, dict) else {}
        target = str(saved.get("wp_post_id") or target)
        item = OptimizedPost(
            campaign_id=post.campaign_id, title=post.title, seo_title=post.seo_title,
            keywords="", keywords_urls="", conclusions="", conclusions_urls="",
            citys=post.citys, citys_urls=post.citys_urls, external=post.external,
            external_url=post.external_url, hashtags=post.hashtags, categories=post.categories,
            language="", image=post.image, image_prompt=post.image_prompt,
            date=datetime.now(), edition_url=target, wp_post_id=post.wp_post_id,
            wp_route=post.wp_route, slug=post.slug,
        )
        return publisher.optimize(
            item, content=post.content, meta_description=post.meta_description,
            image_path=str(image_path) if image_path else None,
            external_link=post.external_link or "", create_category=post.create_category,
            keep_slug=post.keep_slug, execution=execution,
        )
    finally:
        for path in (image_path, original_path):
            if path and Path(path).exists():
                Path(path).unlink(missing_ok=True)
        if image_path:
            try:
                Path(image_path).parent.rmdir()
            except OSError:
                pass


@router.post("/orchestrator/jobs")
def orchestrator_job(job: OrchestratorJob, authorization: str | None = Header(default=None),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                     db: Session = Depends(get_db)):
    _orchestrator_auth(authorization)
    raw = job.model_dump(exclude_none=True)
    payload = job.payload or {key: value for key, value in raw.items()
                              if key not in {"id", "job_id", "execution_id", "external_ref", "capability",
                                             "campaign_id", "posts", "post", "payload"}}
    capability = payload.get("capability") or job.capability or "posts.create"
    if capability not in {"posts.create", "posts.optimize"}:
        raise HTTPException(status_code=422, detail=f"Capability no soportada: {capability}")
    payload = raw.get("payload") or payload or {}
    execution_id = (job.job_id or job.id or job.execution_id or job.external_ref
                    or payload.get("execution_id") or payload.get("external_ref") or idempotency_key)
    if not execution_id:
        raise HTTPException(status_code=422, detail="execution_id o external_ref es obligatorio para deduplicar")
    payload_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    existing = db.query(Execution).filter(Execution.external_id == execution_id).first()
    if existing:
        if existing.payload_hash and existing.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="execution_id ya fue usado con otro contenido")
        if existing.status == "completed":
            return {"duplicate": True, "execution_id": execution_id, "result": existing.result}
        if existing.status == "running" and existing.created_at > datetime.now() - timedelta(minutes=30):
            raise HTTPException(status_code=409, detail="Esta ejecución ya está en curso")
        existing.status, existing.error, existing.result = "running", None, None
        existing.started_at, existing.completed_at = datetime.utcnow(), None
        existing.payload_hash = payload_hash
        db.commit()
        execution = existing
    else:
        execution = Execution(
            external_id=execution_id, payload_hash=payload_hash, source="orchestrator",
            kind="optimize" if capability == "posts.optimize" else "create",
            campaign_id=job.campaign_id or payload.get("campaign_id"),
            status="running", title=str(payload.get("title") or payload.get("post_title") or "")[:500],
            started_at=datetime.utcnow(),
        )
        db.add(execution)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(Execution).filter(Execution.external_id == execution_id).first()
            if existing and existing.payload_hash and existing.payload_hash != payload_hash:
                raise HTTPException(status_code=409, detail="execution_id ya fue usado con otro contenido")
            if existing and existing.status == "completed":
                return {"duplicate": True, "execution_id": execution_id, "result": existing.result}
            raise HTTPException(status_code=409, detail="Esta ejecución ya está en curso")
    raw_posts = raw.get("posts") or payload.get("posts") or []
    if not raw_posts:
        raw_posts = [raw.get("post") or payload.get("post") or payload]
    output, failures = [], []
    for index, entry in enumerate(raw_posts):
        child_id = f"{execution_id}:{index}"
        child = db.query(Execution).filter(Execution.external_id == child_id).first()
        if child and child.status == "completed":
            output.append(child.result or {})
            continue
        if child and child.status == "running" and child.created_at > datetime.now() - timedelta(minutes=30):
            failures.append({"index": index, "error": "Esta publicación ya está en curso"})
            continue
        if child:
            child.status, child.error = "running", None
            child.started_at, child.completed_at = datetime.utcnow(), None
            child.result = None
        else:
            child = Execution(
                external_id=child_id, source="orchestrator",
                kind="optimize" if capability == "posts.optimize" else "create",
                campaign_id=job.campaign_id or payload.get("campaign_id"),
                status="running", started_at=datetime.utcnow(),
            )
            db.add(child)
        db.commit()
        try:
            post = _normalize_post(entry, job.campaign_id or payload.get("campaign_id"))
            with execution_context(child.id):
                child.title = post.title
                item_result = _publish_external(db, post, capability, child_id)
                child.status = "completed"
                child.result = {**(child.result or {}), **item_result}
                child.completed_at = datetime.utcnow()
                db.commit()
                logger.info("Completed orchestrator item %s", child_id)
            flush_execution_logs()
            output.append(item_result)
        except Exception as exc:
            db.rollback()
            child = db.query(Execution).filter(Execution.external_id == child_id).first()
            if child:
                child.status, child.error = "failed", str(exc)[:4000]
                child.completed_at = datetime.utcnow()
                db.commit()
            failures.append({"index": index, "error": str(exc)})
            if child:
                with execution_context(child.id):
                    logger.exception("Orchestrator post %s failed", child_id)
            flush_execution_logs()
    result = {"posts": output} if not failures else {"partial_posts": output, "errors": failures}
    execution.status = "failed" if failures else "completed"
    execution.result = result
    execution.error = json.dumps(failures, ensure_ascii=False) if failures else None
    execution.completed_at = datetime.utcnow()
    db.commit()
    flush_execution_logs()
    if failures and not output:
        raise HTTPException(status_code=502, detail=result)
    return {"execution_id": execution_id, **result}
