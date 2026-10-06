"""More company job boards: Pinpoint, Rippling, JazzHR and Jobvite (feature 007).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-05
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Public job feeds / careers lists; robots.txt of each allows them (checked 2026-10-05).
SOURCES = (
    ("Pinpoint", ["pinpointhq.com"]),
    ("Rippling", ["ats.rippling.com", "api.rippling.com"]),
    ("JazzHR", ["applytojob.com", "app.jazz.co"]),
    ("Jobvite", ["jobs.jobvite.com"]),
)


def upgrade() -> None:
    for name, domains in SOURCES:
        op.execute(
            sa.text(
                "INSERT INTO source (name, type, domains, fetch_allowed, enabled, is_system, "
                "alert_sender) SELECT :n, 'ats', :d, 1, 1, 0, 0 "
                "WHERE NOT EXISTS (SELECT 1 FROM source WHERE name = :n)"
            ).bindparams(n=name, d=json.dumps(domains))
        )
    # Companies whose board was not found get looked up again on the new services.
    op.execute(
        sa.text(
            "UPDATE watch_company SET discovery_done = 0, status = 'pending' "
            "WHERE board_type = 'unknown' AND status = 'not_found'"
        )
    )


def downgrade() -> None:
    for name, _domains in SOURCES:
        op.execute(
            sa.text(
                "DELETE FROM source WHERE name = :n "
                "AND NOT EXISTS (SELECT 1 FROM job WHERE job.source_id = source.id) "
                "AND NOT EXISTS (SELECT 1 FROM job_suggestion s WHERE s.source_id = source.id)"
            ).bindparams(n=name)
        )
