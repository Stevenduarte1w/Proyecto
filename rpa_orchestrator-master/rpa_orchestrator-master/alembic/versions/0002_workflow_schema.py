"""workflow schema

Revision ID: 0002_workflow_schema
Revises: 0001_initial_schema
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_workflow_schema"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


FLOW_STATUS_VALUES = (
    "received",
    "in_progress",
    "waiting_external",
    "waiting_approval",
    "succeeded",
    "failed",
    "cancelled",
)

FLOW_STEP_STATUS_VALUES = (
    "pending",
    "queued",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "blocked",
    "waiting_approval",
)

SEO_FLOW_STEP_VALUES = (
    "context_building",
    "wordpress_extraction",
    "competitor_analysis",
    "seo_audit",
    "work_plan",
    "service_images",
    "main_page_fix",
    "support_posts",
    "video_request",
    "external_assets_received",
    "auto_review",
    "approval",
    "wordpress_publish",
    "post_publish_check",
    "pagespeed",
    "indexing",
    "final_report",
)


def upgrade() -> None:
    flow_status = postgresql.ENUM(*FLOW_STATUS_VALUES, name="flow_status")
    flow_step_status = postgresql.ENUM(*FLOW_STEP_STATUS_VALUES, name="flow_step_status")
    seo_flow_step = postgresql.ENUM(*SEO_FLOW_STEP_VALUES, name="seo_flow_step")
    flow_status_column = postgresql.ENUM(
        *FLOW_STATUS_VALUES,
        name="flow_status",
        create_type=False,
    )
    flow_step_status_column = postgresql.ENUM(
        *FLOW_STEP_STATUS_VALUES,
        name="flow_step_status",
        create_type=False,
    )
    seo_flow_step_column = postgresql.ENUM(
        *SEO_FLOW_STEP_VALUES,
        name="seo_flow_step",
        create_type=False,
    )

    flow_status.create(op.get_bind(), checkfirst=True)
    flow_step_status.create(op.get_bind(), checkfirst=True)
    seo_flow_step.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "flows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("flow_type", sa.String(length=80), nullable=False),
        sa.Column("page_url", sa.String(length=1000), nullable=False),
        sa.Column("campaign", sa.String(length=120), nullable=True),
        sa.Column("commercial_objective", sa.String(length=500), nullable=True),
        sa.Column("status", flow_status_column, nullable=False),
        sa.Column("current_step", seo_flow_step_column, nullable=False),
        sa.Column("initial_document_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_flows_flow_type", "flows", ["flow_type"])
    op.create_index("ix_flows_page_url", "flows", ["page_url"])
    op.create_index("ix_flows_status", "flows", ["status"])
    op.create_index("ix_flows_current_step", "flows", ["current_step"])
    op.create_index("ix_flows_correlation_id", "flows", ["correlation_id"])

    op.create_table(
        "flow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("step_name", seo_flow_step_column, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", flow_step_status_column, nullable=False),
        sa.Column("requested_capability", sa.String(length=120), nullable=True),
        sa.Column("input_document_id", sa.String(length=64), nullable=True),
        sa.Column("output_document_id", sa.String(length=64), nullable=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_flow_steps_flow_id", "flow_steps", ["flow_id"])
    op.create_index("ix_flow_steps_step_name", "flow_steps", ["step_name"])
    op.create_index("ix_flow_steps_status", "flow_steps", ["status"])
    op.create_index("ix_flow_steps_requested_capability", "flow_steps", ["requested_capability"])
    op.create_index("ix_flow_steps_execution_id", "flow_steps", ["execution_id"])

    op.add_column("executions", sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("executions", sa.Column("input_document_id", sa.String(length=64), nullable=True))
    op.add_column("executions", sa.Column("output_document_id", sa.String(length=64), nullable=True))
    op.create_foreign_key("fk_executions_step_id", "executions", "flow_steps", ["step_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_executions_step_id", "executions", type_="foreignkey")
    op.drop_column("executions", "output_document_id")
    op.drop_column("executions", "input_document_id")
    op.drop_column("executions", "step_id")

    op.drop_index("ix_flow_steps_execution_id", table_name="flow_steps")
    op.drop_index("ix_flow_steps_requested_capability", table_name="flow_steps")
    op.drop_index("ix_flow_steps_status", table_name="flow_steps")
    op.drop_index("ix_flow_steps_step_name", table_name="flow_steps")
    op.drop_index("ix_flow_steps_flow_id", table_name="flow_steps")
    op.drop_table("flow_steps")

    op.drop_index("ix_flows_correlation_id", table_name="flows")
    op.drop_index("ix_flows_current_step", table_name="flows")
    op.drop_index("ix_flows_status", table_name="flows")
    op.drop_index("ix_flows_page_url", table_name="flows")
    op.drop_index("ix_flows_flow_type", table_name="flows")
    op.drop_table("flows")

    postgresql.ENUM(name="seo_flow_step").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="flow_step_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="flow_status").drop(op.get_bind(), checkfirst=True)
