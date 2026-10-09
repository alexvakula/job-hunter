"""Login history: time, IP, approximate place and device of each successful login.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("ip", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("device", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("login_event") as batch_op:
        batch_op.create_index(batch_op.f("ix_login_event_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("login_event") as batch_op:
        batch_op.drop_index(batch_op.f("ix_login_event_user_id"))
    op.drop_table("login_event")
