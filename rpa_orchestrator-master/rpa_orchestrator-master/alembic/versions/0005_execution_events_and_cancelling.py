"""execution progress events and cooperative cancellation

Revision ID: 0005_execution_events
Revises: 0004_post_monitor
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_execution_events"
down_revision = "0004_post_monitor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'cancelling'")
    op.create_table(
        "execution_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("stage", sa.String(length=80)),
        sa.Column("summary", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_execution_events_execution_sequence",
        ),
    )
    op.create_index(
        "ix_execution_events_execution_id",
        "execution_events",
        ["execution_id"],
    )
    op.create_index(
        "ix_execution_events_event_type",
        "execution_events",
        ["event_type"],
    )
    op.create_index("ix_execution_events_stage", "execution_events", ["stage"])


def downgrade() -> None:
    op.drop_index("ix_execution_events_stage", table_name="execution_events")
    op.drop_index("ix_execution_events_event_type", table_name="execution_events")
    op.drop_index("ix_execution_events_execution_id", table_name="execution_events")
    op.drop_table("execution_events")
    # PostgreSQL cannot remove an enum value safely in place. Keeping the value is
    # harmless and avoids rewriting every row in the executions table on downgrade.
