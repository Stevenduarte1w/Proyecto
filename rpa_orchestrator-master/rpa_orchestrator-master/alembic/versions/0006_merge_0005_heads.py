"""merge execution events and WordPress page setup migrations

Revision ID: 0006_merge_0005_heads
Revises: 0005_execution_events, 0005_wordpress_page_setup_step
Create Date: 2026-09-19
"""

from __future__ import annotations

revision = "0006_merge_0005_heads"
down_revision = (
    "0005_execution_events",
    "0005_wordpress_page_setup_step",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join both migration branches without additional schema changes."""


def downgrade() -> None:
    """Split the migration graph back into its two parent revisions."""
