"""isolated post bot job channel

Revision ID: 0007_post_bot_jobs
Revises: 0006_merge_0005_heads
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_post_bot_jobs"
down_revision = "0006_merge_0005_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_bot_workers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bot_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("bot_type", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=80)),
        sa.Column(
            "capabilities",
            postgresql.ARRAY(sa.String(length=80)),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("available_slots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_post_bot_workers_bot_key",
        "post_bot_workers",
        ["bot_key"],
        unique=True,
    )
    op.create_index(
        "ix_post_bot_workers_last_seen_at",
        "post_bot_workers",
        ["last_seen_at"],
    )

    op.create_table(
        "post_bot_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("capability", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("external_ref", sa.String(length=240)),
        sa.Column("requested_by", sa.String(length=120)),
        sa.Column(
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_bot_workers.id"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_post_bot_jobs_capability", "post_bot_jobs", ["capability"])
    op.create_index("ix_post_bot_jobs_status", "post_bot_jobs", ["status"])
    op.create_index("ix_post_bot_jobs_worker_id", "post_bot_jobs", ["worker_id"])
    op.create_index("ix_post_bot_jobs_created_at", "post_bot_jobs", ["created_at"])
    op.create_index("ix_post_bot_jobs_finished_at", "post_bot_jobs", ["finished_at"])
    op.create_index(
        "ix_post_bot_jobs_external_ref",
        "post_bot_jobs",
        ["external_ref"],
        unique=True,
    )
    # Reparto: los candidatos se buscan siempre por estado, prioridad y antigüedad.
    op.create_index(
        "ix_post_bot_jobs_queue",
        "post_bot_jobs",
        ["status", "capability", "priority", "created_at"],
    )

    op.create_table(
        "post_bot_job_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_bot_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True)),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_post_bot_job_events_job_id", "post_bot_job_events", ["job_id"])
    op.create_index(
        "ix_post_bot_job_events_event_type",
        "post_bot_job_events",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_bot_job_events_event_type", table_name="post_bot_job_events")
    op.drop_index("ix_post_bot_job_events_job_id", table_name="post_bot_job_events")
    op.drop_table("post_bot_job_events")
    op.drop_index("ix_post_bot_jobs_queue", table_name="post_bot_jobs")
    op.drop_index("ix_post_bot_jobs_external_ref", table_name="post_bot_jobs")
    op.drop_index("ix_post_bot_jobs_finished_at", table_name="post_bot_jobs")
    op.drop_index("ix_post_bot_jobs_created_at", table_name="post_bot_jobs")
    op.drop_index("ix_post_bot_jobs_worker_id", table_name="post_bot_jobs")
    op.drop_index("ix_post_bot_jobs_status", table_name="post_bot_jobs")
    op.drop_index("ix_post_bot_jobs_capability", table_name="post_bot_jobs")
    op.drop_table("post_bot_jobs")
    op.drop_index("ix_post_bot_workers_last_seen_at", table_name="post_bot_workers")
    op.drop_index("ix_post_bot_workers_bot_key", table_name="post_bot_workers")
    op.drop_table("post_bot_workers")
