"""add wordpress page setup workflow step

Revision ID: 0005_wordpress_page_setup_step
Revises: 0004_post_monitor
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op

revision = "0005_wordpress_page_setup_step"
down_revision = "0004_post_monitor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE seo_flow_step "
        "ADD VALUE IF NOT EXISTS 'wordpress_page_setup' BEFORE 'seo_audit'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely while rows may reference them.
    pass
