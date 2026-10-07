"""Telegram messages for new suggestions and other updates.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification_settings") as batch_op:
        batch_op.add_column(
            sa.Column("updates_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("last_suggestion_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_email_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("updates_checked_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_settings") as batch_op:
        batch_op.drop_column("updates_checked_at")
        batch_op.drop_column("last_email_id")
        batch_op.drop_column("last_suggestion_id")
        batch_op.drop_column("updates_enabled")
