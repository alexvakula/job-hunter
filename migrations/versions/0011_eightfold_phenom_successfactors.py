"""Eightfold, Phenom and SuccessFactors career sites (feature 007).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-05
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Eightfold: robots.txt allows /api/pcsx (checked 2026-10-05). Phenom and SuccessFactors sites
# run on each employer's own domain: a site is added to its source's domains when a user pastes
# a link to it and the site is recognised (robots.txt of each site still applies).
SOURCES = (("Eightfold", ["eightfold.ai"]), ("Phenom", []), ("SuccessFactors", []))


def upgrade() -> None:
    for name, domains in SOURCES:
        op.execute(
            sa.text(
                "INSERT INTO source (name, type, domains, fetch_allowed, enabled, is_system, "
                "alert_sender) SELECT :n, 'ats', :d, 1, 1, 0, 0 "
                "WHERE NOT EXISTS (SELECT 1 FROM source WHERE name = :n)"
            ).bindparams(n=name, d=json.dumps(domains))
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
