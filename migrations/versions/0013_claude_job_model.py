"""The Claude model each job ran with (feature 007).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("claude_job") as batch_op:
        batch_op.add_column(sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("claude_job") as batch_op:
        batch_op.drop_column("model")
