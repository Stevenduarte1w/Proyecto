"""execution checkpoints

Revision ID: 0003_execution_checkpoints
Revises: 0002_workflow_schema
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_execution_checkpoints"
down_revision = "0002_workflow_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("internal_state", sa.String(length=80)))
    op.add_column("executions", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("executions", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_executions_internal_state", "executions", ["internal_state"])
    op.create_unique_constraint(
        "uq_executions_step_id",
        "executions",
        ["step_id"],
    )

    op.create_unique_constraint(
        "uq_flow_steps_flow_step",
        "flow_steps",
        ["flow_id", "step_name"],
    )
    op.create_table(
        "execution_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id"),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id"),
            nullable=False,
        ),
        sa.Column("checkpoint", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("mongo_document_id", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "execution_id",
            "checkpoint",
            name="uq_execution_checkpoints_execution_checkpoint",
        ),
    )
    op.create_index(
        "ix_execution_checkpoints_flow_id",
        "execution_checkpoints",
        ["flow_id"],
    )
    op.create_index(
        "ix_execution_checkpoints_execution_id",
        "execution_checkpoints",
        ["execution_id"],
    )
    op.create_index(
        "ix_execution_checkpoints_status",
        "execution_checkpoints",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_checkpoints_status", table_name="execution_checkpoints")
    op.drop_index(
        "ix_execution_checkpoints_execution_id",
        table_name="execution_checkpoints",
    )
    op.drop_index("ix_execution_checkpoints_flow_id", table_name="execution_checkpoints")
    op.drop_table("execution_checkpoints")
    op.drop_constraint("uq_flow_steps_flow_step", "flow_steps", type_="unique")
    op.drop_constraint("uq_executions_step_id", "executions", type_="unique")
    op.drop_index("ix_executions_internal_state", table_name="executions")
    op.drop_column("executions", "completed_at")
    op.drop_column("executions", "started_at")
    op.drop_column("executions", "internal_state")
