"""local business profile, backlinks, answer analysis, api cache

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
OLD_KINDS = "kind IN ('visibility_run', 'question_generation', 'fix_generation')"
NEW_KINDS = "kind IN ('visibility_run', 'question_generation', 'fix_generation', 'backlink_discovery')"


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        for name, type_ in [
            ("city", sa.String(120)), ("region", sa.String(120)), ("country", sa.String(2)),
            ("service_area", sa.String(300)), ("address", sa.String(500)), ("phone", sa.String(40)),
            ("opening_hours", sa.String(300)),
        ]:
            batch.add_column(sa.Column(name, type_, nullable=True))
        batch.add_column(sa.Column("services", JSONType, nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("profile_urls", JSONType, nullable=False, server_default=sa.text("'[]'")))

    with op.batch_alter_table("provider_answers") as batch:
        batch.add_column(sa.Column("analysis", JSONType, nullable=True))

    with op.batch_alter_table("usage_events") as batch:
        batch.drop_constraint("ck_usage_kind", type_="check")
        batch.create_check_constraint("ck_usage_kind", NEW_KINDS)

    op.create_table(
        "backlink_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("submission_url", sa.String(2048), nullable=True),
        sa.Column("relevance", sa.Text(), nullable=True),
        sa.Column("why_it_helps", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(20), nullable=False),
        sa.Column("link_rel", sa.String(20), nullable=False),
        sa.Column("discovered_via", sa.String(300), nullable=True),
        sa.Column("evidence", JSONType, nullable=False),
        sa.Column("outreach", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_error", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "url", name="uq_backlink_project_url"),
        sa.CheckConstraint("kind IN ('existing', 'opportunity')", name="ck_backlink_kind"),
        sa.CheckConstraint(
            "status IN ('found', 'suggested', 'in_progress', 'completed', 'verified', 'not_found', 'dismissed')",
            name="ck_backlink_status",
        ),
        sa.CheckConstraint("value_type IN ('backlink', 'mention', 'both', 'unknown')", name="ck_backlink_value"),
        sa.CheckConstraint("link_rel IN ('follow', 'nofollow', 'ugc', 'sponsored', 'unknown')", name="ck_backlink_rel"),
    )
    op.create_index("ix_backlink_items_project_id", "backlink_items", ["project_id"])

    op.create_table(
        "api_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("value", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_cache_expires_at", "api_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_api_cache_expires_at", table_name="api_cache")
    op.drop_table("api_cache")
    op.drop_index("ix_backlink_items_project_id", table_name="backlink_items")
    op.drop_table("backlink_items")
    op.execute("DELETE FROM usage_events WHERE kind = 'backlink_discovery'")
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_constraint("ck_usage_kind", type_="check")
        batch.create_check_constraint("ck_usage_kind", OLD_KINDS)
    with op.batch_alter_table("provider_answers") as batch:
        batch.drop_column("analysis")
    with op.batch_alter_table("projects") as batch:
        for name in ("profile_urls", "services", "opening_hours", "phone", "address", "service_area", "country", "region", "city"):
            batch.drop_column(name)
