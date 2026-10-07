"""Drafts for application emails too: reply_draft becomes email_draft.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_draft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("to_addrs", sa.JSON(), nullable=False),
        sa.Column("subject", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("body", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("intent", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("by_claude", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["email_id"], ["email_message.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("email_draft") as batch_op:
        batch_op.create_index(batch_op.f("ix_email_draft_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_email_draft_email_id"), ["email_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_email_draft_job_id"), ["job_id"], unique=False)
        batch_op.create_index("ux_email_draft_user_email", ["user_id", "email_id"], unique=True)
        batch_op.create_index("ux_email_draft_user_job", ["user_id", "job_id"], unique=True)
    op.execute(
        "INSERT INTO email_draft (id, user_id, kind, email_id, job_id, to_addrs, subject, body, "
        "attachments, intent, by_claude, updated_at) SELECT id, user_id, 'reply', email_id, NULL, "
        "to_addrs, subject, body, '[]', intent, by_claude, updated_at FROM reply_draft"
    )
    op.drop_table("reply_draft")


def downgrade() -> None:
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
    op.execute(
        "INSERT INTO reply_draft (id, user_id, email_id, to_addrs, subject, body, intent, "
        "by_claude, updated_at) SELECT id, user_id, email_id, to_addrs, subject, body, intent, "
        "by_claude, updated_at FROM email_draft WHERE kind = 'reply'"
    )
    op.drop_table("email_draft")
