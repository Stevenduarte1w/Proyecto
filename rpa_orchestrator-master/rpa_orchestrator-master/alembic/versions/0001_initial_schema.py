"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    execution_status = postgresql.ENUM(
        "pending",
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        name="execution_status",
    )
    execution_status_column = postgresql.ENUM(
        "pending",
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        name="execution_status",
        create_type=False,
    )
    execution_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "bots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bot_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("bot_type", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("capabilities", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_bots_bot_key", "bots", ["bot_key"], unique=True)
    op.create_index("ix_bots_name", "bots", ["name"])
    op.create_index("ix_bots_bot_type", "bots", ["bot_type"])

    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("flow_id", sa.String(length=64), nullable=False),
        sa.Column("requested_capability", sa.String(length=120), nullable=False),
        sa.Column("status", execution_status_column, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bots.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_executions_flow_id", "executions", ["flow_id"])
    op.create_index("ix_executions_requested_capability", "executions", ["requested_capability"])
    op.create_index("ix_executions_status", "executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_executions_status", table_name="executions")
    op.drop_index("ix_executions_requested_capability", table_name="executions")
    op.drop_index("ix_executions_flow_id", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_bots_bot_type", table_name="bots")
    op.drop_index("ix_bots_name", table_name="bots")
    op.drop_index("ix_bots_bot_key", table_name="bots")
    op.drop_table("bots")
    postgresql.ENUM(name="execution_status").drop(op.get_bind(), checkfirst=True)
