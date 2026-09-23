"""independent post monitor

Revision ID: 0004_post_monitor
Revises: 0003_execution_checkpoints
Create Date: 2026-09-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_post_monitor"
down_revision = "0003_execution_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_monitor_bots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bot_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=80)),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reported_status", sa.String(length=20), nullable=False),
        sa.Column("current_jobs", sa.Integer(), nullable=False),
        sa.Column("outbox_pending", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_post_monitor_bots_bot_key",
        "post_monitor_bots",
        ["bot_key"],
        unique=True,
    )
    op.create_index(
        "ix_post_monitor_bots_last_seen_at",
        "post_monitor_bots",
        ["last_seen_at"],
    )

    op.create_table(
        "post_monitor_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_monitor_bots.id"),
            nullable=False,
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "bot_id",
            "event_id",
            name="uq_post_monitor_events_bot_event",
        ),
    )
    op.create_index("ix_post_monitor_events_bot_id", "post_monitor_events", ["bot_id"])
    op.create_index(
        "ix_post_monitor_events_event_type",
        "post_monitor_events",
        ["event_type"],
    )

    op.create_table(
        "post_monitor_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_monitor_bots.id"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_external_id", sa.String(length=240)),
        sa.Column("target_url", sa.Text()),
        sa.Column("target_title", sa.String(length=500)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("summary", sa.Text()),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("error", postgresql.JSONB()),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("bot_id", "run_id", name="uq_post_monitor_runs_bot_run"),
    )
    op.create_index("ix_post_monitor_runs_bot_id", "post_monitor_runs", ["bot_id"])
    op.create_index("ix_post_monitor_runs_status", "post_monitor_runs", ["status"])
    op.create_index(
        "ix_post_monitor_runs_target_external_id",
        "post_monitor_runs",
        ["target_external_id"],
    )
    op.create_index(
        "ix_post_monitor_runs_finished_at",
        "post_monitor_runs",
        ["finished_at"],
    )

    op.create_table(
        "post_monitor_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_monitor_bots.id"),
            nullable=False,
        ),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("metric", sa.String(length=160), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("operator", sa.String(length=8), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=80)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("rule_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("target", postgresql.JSONB(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "bot_id",
            "alert_id",
            name="uq_post_monitor_alerts_bot_alert",
        ),
    )
    op.create_index("ix_post_monitor_alerts_bot_id", "post_monitor_alerts", ["bot_id"])
    op.create_index("ix_post_monitor_alerts_run_id", "post_monitor_alerts", ["run_id"])
    op.create_index("ix_post_monitor_alerts_severity", "post_monitor_alerts", ["severity"])
    op.create_index("ix_post_monitor_alerts_metric", "post_monitor_alerts", ["metric"])
    op.create_index("ix_post_monitor_alerts_status", "post_monitor_alerts", ["status"])
    op.create_index(
        "ix_post_monitor_alerts_occurred_at",
        "post_monitor_alerts",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_monitor_alerts_occurred_at", table_name="post_monitor_alerts")
    op.drop_index("ix_post_monitor_alerts_status", table_name="post_monitor_alerts")
    op.drop_index("ix_post_monitor_alerts_metric", table_name="post_monitor_alerts")
    op.drop_index("ix_post_monitor_alerts_severity", table_name="post_monitor_alerts")
    op.drop_index("ix_post_monitor_alerts_run_id", table_name="post_monitor_alerts")
    op.drop_index("ix_post_monitor_alerts_bot_id", table_name="post_monitor_alerts")
    op.drop_table("post_monitor_alerts")
    op.drop_index("ix_post_monitor_runs_finished_at", table_name="post_monitor_runs")
    op.drop_index("ix_post_monitor_runs_target_external_id", table_name="post_monitor_runs")
    op.drop_index("ix_post_monitor_runs_status", table_name="post_monitor_runs")
    op.drop_index("ix_post_monitor_runs_bot_id", table_name="post_monitor_runs")
    op.drop_table("post_monitor_runs")
    op.drop_index("ix_post_monitor_events_event_type", table_name="post_monitor_events")
    op.drop_index("ix_post_monitor_events_bot_id", table_name="post_monitor_events")
    op.drop_table("post_monitor_events")
    op.drop_index("ix_post_monitor_bots_last_seen_at", table_name="post_monitor_bots")
    op.drop_index("ix_post_monitor_bots_bot_key", table_name="post_monitor_bots")
    op.drop_table("post_monitor_bots")
