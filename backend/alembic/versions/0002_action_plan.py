"""action plan: stable recommendation keys, status tracking, effort/confidence

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recommendations are derived data with no user state yet; they are rebuilt
    # (with keys) on the next refresh, so clear them instead of backfilling keys.
    op.execute("DELETE FROM recommendations")
    now = sa.text("CURRENT_TIMESTAMP")
    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(sa.Column("key", sa.String(200), nullable=False))
        batch.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="open"))
        batch.add_column(sa.Column("effort", sa.String(10), nullable=False, server_default="medium"))
        batch.add_column(sa.Column("confidence", sa.String(10), nullable=False, server_default="medium"))
        batch.add_column(sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("score", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("verify", sa.Text(), nullable=True))
        batch.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("detected", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False, server_default=now))
        batch.add_column(sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False, server_default=now))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_rec_effort", "effort IN ('high', 'medium', 'low')")
        batch.create_check_constraint("ck_rec_confidence", "confidence IN ('high', 'medium', 'low')")
        batch.create_check_constraint(
            "ck_rec_status", "status IN ('open', 'planned', 'in_progress', 'completed', 'dismissed')"
        )
        batch.create_unique_constraint("uq_rec_project_key", ["project_id", "key"])


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_constraint("uq_rec_project_key", type_="unique")
        batch.drop_constraint("ck_rec_status", type_="check")
        batch.drop_constraint("ck_rec_confidence", type_="check")
        batch.drop_constraint("ck_rec_effort", type_="check")
        for col in ("status_updated_at", "resolved_at", "last_detected_at", "first_detected_at", "detected", "note",
                    "verify", "score", "blocking", "confidence", "effort", "status", "key"):
            batch.drop_column(col)
