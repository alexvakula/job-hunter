"""SmartRecruiters public careers pages.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-07
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Only the public careers pages (careers.smartrecruiters.com, jobs.smartrecruiters.com: no
# robots.txt rules, checked 2026-10-07); api.smartrecruiters.com disallows all crawlers and is
# deliberately not an allowed domain.
NAME, DOMAINS = "SmartRecruiters", ["careers.smartrecruiters.com", "jobs.smartrecruiters.com"]


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
