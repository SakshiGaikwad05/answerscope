"""accounts, sessions, usage quotas, project ownership, fix drafts

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('visibility_run', 'question_generation', 'fix_generation')", name="ck_usage_kind"
        ),
    )
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])

    with op.batch_alter_table("projects") as batch:
        # Nullable: projects created before accounts existed are claimed by the first account.
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_projects_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_projects_user_id", ["user_id"])

    op.create_table(
        "fix_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "recommendation_id", sa.Integer(), sa.ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("placeholders", JSONType, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sources", JSONType, nullable=False),
        sa.Column("generator", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("format IN ('markdown', 'html', 'json-ld', 'text')", name="ck_fix_format"),
    )
    op.create_index("ix_fix_drafts_recommendation_id", "fix_drafts", ["recommendation_id"])


def downgrade() -> None:
    op.drop_index("ix_fix_drafts_recommendation_id", table_name="fix_drafts")
    op.drop_table("fix_drafts")
    with op.batch_alter_table("projects") as batch:
        batch.drop_index("ix_projects_user_id")
        batch.drop_constraint("fk_projects_user_id", type_="foreignkey")
        batch.drop_column("user_id")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_user_id", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
