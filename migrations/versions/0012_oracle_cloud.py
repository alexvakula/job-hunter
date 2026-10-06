"""Oracle Recruiting Cloud career sites (feature 007).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-06
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Public job search (hcmRestApi recruitingCEJobRequisitions) used by the career site; Oracle hosts
# have no robots.txt (checked 2026-10-06). Sites on an employer's own domain are added when a user
# pastes a link to them.
NAME, DOMAINS = "Oracle Cloud", ["oraclecloud.com"]


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO source (name, type, domains, fetch_allowed, enabled, is_system, "
            "alert_sender) SELECT :n, 'ats', :d, 1, 1, 0, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM source WHERE name = :n)"
        ).bindparams(n=NAME, d=json.dumps(DOMAINS))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM source WHERE name = :n "
            "AND NOT EXISTS (SELECT 1 FROM job WHERE job.source_id = source.id) "
            "AND NOT EXISTS (SELECT 1 FROM job_suggestion s WHERE s.source_id = source.id)"
        ).bindparams(n=NAME)
    )
