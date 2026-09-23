"""Move WordPress credentials out of campaigns and prepare REST publishing.

Revision ID: d91c8f5b3a20
Revises: ae8309ee9b7d
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d91c8f5b3a20"
down_revision: Union[str, Sequence[str], None] = "ae8309ee9b7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wordpress_sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("credential_ref", sa.String(120), nullable=False, unique=True),
        sa.Column("yoast_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.execute("""
        INSERT INTO wordpress_sites (id, name, url, username, credential_ref, is_active, created_at)
        SELECT id, name, url, email,
               'WP_SITE_' || id::text || '_APP_PASSWORD', is_active, created_at
        FROM campaigns
    """)
    op.execute("SELECT setval(pg_get_serial_sequence('wordpress_sites', 'id'), COALESCE(MAX(id), 1)) FROM wordpress_sites")

    op.add_column("campaigns", sa.Column("wordpress_site_id", sa.Integer(), nullable=True))
    op.execute("UPDATE campaigns SET wordpress_site_id = id")
    op.alter_column("campaigns", "wordpress_site_id", nullable=False)
    op.create_foreign_key("fk_campaigns_wordpress_site", "campaigns", "wordpress_sites", ["wordpress_site_id"], ["id"])
    # Legacy passwords are deliberately removed. Set a new WordPress Application Password
    # in the environment variable named by wordpress_sites.credential_ref before deployment.
    op.drop_column("campaigns", "email")
    op.drop_column("campaigns", "password")
    op.drop_column("campaigns", "url")

    op.add_column("posts", sa.Column("image_prompt", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("state", sa.String(24), nullable=False, server_default="pending"))
    op.add_column("posts", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("posts", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE posts SET state = CASE WHEN status THEN 'succeeded' ELSE 'pending' END")
    op.add_column("optimized_posts", sa.Column("image_prompt", sa.Text(), nullable=True))
    op.add_column("optimized_posts", sa.Column("wp_post_id", sa.Integer(), nullable=True))
    op.add_column("optimized_posts", sa.Column("wp_route", sa.String(16), nullable=True))
    op.add_column("optimized_posts", sa.Column("slug", sa.String(255), nullable=True))
    op.add_column("optimized_posts", sa.Column("previous_snapshot", sa.Text(), nullable=True))
    op.add_column("optimized_posts", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("optimized_posts", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("optimized_posts", sa.Column("state", sa.String(24), nullable=False, server_default="pending"))
    op.add_column("optimized_posts", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE optimized_posts SET state = CASE WHEN status THEN 'succeeded' ELSE 'pending' END")

    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(160), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="local"),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("external_id", name="ux_executions_external_id"),
    )
    op.create_index("ix_executions_external_id", "executions", ["external_id"])
    op.create_table(
        "schedule_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hour", sa.String(5), nullable=False, server_default="02:00"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Bogota"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    # Password values cannot be restored because this migration intentionally deletes them.
    op.drop_table("schedule_config")
    op.drop_index("ix_executions_external_id", table_name="executions")
    op.drop_table("executions")
    for column in ("claimed_at", "state", "attempts", "last_error", "previous_snapshot", "slug", "wp_route", "wp_post_id", "image_prompt"):
        op.drop_column("optimized_posts", column)
    for column in ("claimed_at", "last_error", "attempts", "state"):
        op.drop_column("posts", column)
    op.drop_column("posts", "image_prompt")
    op.drop_constraint("fk_campaigns_wordpress_site", "campaigns", type_="foreignkey")
    op.drop_column("campaigns", "wordpress_site_id")
    op.add_column("campaigns", sa.Column("url", sa.String(255), nullable=True))
    op.add_column("campaigns", sa.Column("email", sa.String(), nullable=True))
    op.add_column("campaigns", sa.Column("password", sa.String(), nullable=True))
    op.execute("UPDATE campaigns SET url = wordpress_sites.url, email = wordpress_sites.username FROM wordpress_sites WHERE campaigns.id = wordpress_sites.id")
    op.drop_table("wordpress_sites")
