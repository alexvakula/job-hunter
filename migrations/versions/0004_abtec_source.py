"""Add ABTEC 5000 (Technology Alberta company directory) as a source.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Directory of Alberta tech companies. Behind a Cloudflare bot challenge: never fetched.
    op.execute(
        sa.text(
            "INSERT INTO source (name, type, domains, fetch_allowed, enabled, is_system, alert_sender) "
            "SELECT 'ABTEC 5000', 'company_directory', '[\"technologyalberta.com\"]', 0, 1, 0, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM source WHERE name = 'ABTEC 5000')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM source WHERE name = 'ABTEC 5000' "
            "AND NOT EXISTS (SELECT 1 FROM job WHERE job.source_id = source.id)"
        )
    )
