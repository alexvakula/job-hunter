"""Saved reply drafts (Mail → Drafts).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_draft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("to_addrs", sa.JSON(), nullable=False),
        sa.Column("subject", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("body", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("intent", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("by_claude", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["email_id"], ["email_message.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("reply_draft") as batch_op:
        batch_op.create_index(batch_op.f("ix_reply_draft_email_id"), ["email_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_reply_draft_user_id"), ["user_id"], unique=False)
        batch_op.create_index("ux_reply_draft_user_email", ["user_id", "email_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("reply_draft") as batch_op:
        batch_op.drop_index("ux_reply_draft_user_email")
        batch_op.drop_index(batch_op.f("ix_reply_draft_user_id"))
        batch_op.drop_index(batch_op.f("ix_reply_draft_email_id"))
    op.drop_table("reply_draft")
