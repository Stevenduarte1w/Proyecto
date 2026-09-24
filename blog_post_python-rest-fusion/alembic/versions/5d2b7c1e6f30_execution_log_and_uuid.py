"""Persist execution metadata and buffered logs; use UUID execution IDs.

Revision ID: 5d2b7c1e6f30
Revises: d91c8f5b3a20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5d2b7c1e6f30"
down_revision: Union[str, Sequence[str], None] = "d91c8f5b3a20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Give every existing execution a stable UUID before replacing its integer
    # primary key. The old ID is not referenced by any other table.
    op.add_column(
        "executions",
        sa.Column("id_v3", postgresql.UUID(as_uuid=True), nullable=True,
                  server_default=sa.text("gen_random_uuid()")),
    )
    op.execute("UPDATE executions SET id_v3 = gen_random_uuid() WHERE id_v3 IS NULL")
    op.alter_column("executions", "id_v3", nullable=False, server_default=None)
    op.drop_constraint("executions_pkey", "executions", type_="primary")
    op.drop_column("executions", "id")
    op.alter_column("executions", "id_v3", new_column_name="id")
    op.create_primary_key("executions_pkey", "executions", ["id"])

    op.add_column("executions", sa.Column("kind", sa.String(20), nullable=True))
    op.add_column("executions", sa.Column("campaign_id", sa.Integer(), nullable=True))
    op.add_column("executions", sa.Column("post_id", sa.Integer(), nullable=True))
    op.add_column("executions", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("executions", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("executions", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.execute("""
        UPDATE executions
        SET kind = CASE WHEN capability = 'posts.optimize' THEN 'optimize' ELSE 'create' END,
            started_at = created_at,
            completed_at = CASE WHEN status IN ('succeeded', 'failed') THEN updated_at ELSE NULL END,
            status = CASE WHEN status = 'succeeded' THEN 'completed' ELSE status END,
            source = CASE WHEN source = 'local' THEN 'api' ELSE source END
    """)
    op.alter_column("executions", "kind", nullable=False, server_default="create")
    op.alter_column("executions", "kind", server_default=None)
    op.alter_column(
        "executions", "result", type_=postgresql.JSONB(),
        postgresql_using="CASE WHEN result IS NULL THEN NULL ELSE result::jsonb END",
    )
    op.drop_column("executions", "capability")
    op.create_index("ix_executions_campaign_id", "executions", ["campaign_id"])
    op.create_index("ix_executions_post_id", "executions", ["post_id"])

    op.add_column("posts", sa.Column("wp_post_id", sa.Integer(), nullable=True))
    op.add_column("posts", sa.Column("wp_post_url", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("published_at", sa.DateTime(), nullable=True))
    op.add_column("optimized_posts", sa.Column("optimized_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE posts SET state = 'done' WHERE state = 'succeeded'")
    op.execute("UPDATE optimized_posts SET state = 'done' WHERE state = 'succeeded'")
    op.drop_column("posts", "status")
    op.drop_column("optimized_posts", "status")

    op.create_table(
        "execution_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_execution_logs_execution_id", "execution_logs", ["execution_id"])
    op.create_index("ix_execution_logs_exec", "execution_logs", ["execution_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_execution_logs_exec", table_name="execution_logs")
    op.drop_index("ix_execution_logs_execution_id", table_name="execution_logs")
    op.drop_table("execution_logs")
    op.add_column("posts", sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("optimized_posts", sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE posts SET status = (state = 'done')")
    op.execute("UPDATE optimized_posts SET status = (state = 'done')")
    for table, columns in (("posts", ("published_at", "wp_post_url", "wp_post_id")),
                           ("optimized_posts", ("optimized_at",))):
        for column in columns:
            op.drop_column(table, column)
    op.drop_index("ix_executions_post_id", table_name="executions")
    op.drop_index("ix_executions_campaign_id", table_name="executions")
    op.alter_column("executions", "result", type_=sa.Text(), postgresql_using="result::text")
    op.add_column("executions", sa.Column("capability", sa.String(64), nullable=False, server_default="posts.create"))
    op.execute("UPDATE executions SET capability = CASE WHEN kind = 'optimize' THEN 'posts.optimize' ELSE 'posts.create' END")
    for column in ("completed_at", "started_at", "title", "post_id", "campaign_id", "kind"):
        op.drop_column("executions", column)

    op.add_column("executions", sa.Column("id_int", sa.Integer(), nullable=True))
    op.execute("""
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS new_id
            FROM executions
        )
        UPDATE executions AS e SET id_int = numbered.new_id
        FROM numbered WHERE e.id = numbered.id
    """)
    op.drop_constraint("executions_pkey", "executions", type_="primary")
    op.drop_column("executions", "id")
    op.alter_column("executions", "id_int", new_column_name="id", nullable=False)
    op.create_primary_key("executions_pkey", "executions", ["id"])
    op.execute("CREATE SEQUENCE IF NOT EXISTS executions_id_seq OWNED BY executions.id")
    op.execute("ALTER TABLE executions ALTER COLUMN id SET DEFAULT nextval('executions_id_seq')")
