"""Shared company watchlist: one list for all users instead of one per user.

Companies that several users watched are merged into the oldest entry (their suggestions
point at it); it stays paused only if every copy was paused. `user_id` becomes `added_by`,
kept when that user is deleted.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _merge_duplicates() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, name, board_type, board_id, board_host, board_site, paused "
            "FROM watch_company ORDER BY id"
        )
    ).all()
    keep: dict[tuple, tuple[int, bool]] = {}
    for id_, name, btype, bid, host, site, paused in rows:
        if btype == "unknown":
            key = ("unknown", name.strip().lower())
        else:
            key = (btype, bid, host, site)
        if key not in keep:
            keep[key] = (id_, bool(paused))
            continue
        kept_id, kept_paused = keep[key]
        conn.execute(
            sa.text("UPDATE job_suggestion SET watch_company_id = :k WHERE watch_company_id = :d"),
            {"k": kept_id, "d": id_},
        )
        conn.execute(sa.text("DELETE FROM watch_company WHERE id = :d"), {"d": id_})
        if kept_paused and not paused:
            conn.execute(
                sa.text("UPDATE watch_company SET paused = 0 WHERE id = :k"), {"k": kept_id}
            )
            keep[key] = (kept_id, False)


def _suggestion_links() -> list[dict]:
    """Rebuilding watch_company deletes its rows, and with foreign keys on that clears
    job_suggestion.watch_company_id (ON DELETE SET NULL); the links are put back after."""
    rows = op.get_bind().execute(
        sa.text(
            "SELECT id, watch_company_id FROM job_suggestion WHERE watch_company_id IS NOT NULL"
        )
    )
    return [{"s": s, "w": w} for s, w in rows]


def _restore(links: list[dict]) -> None:
    if links:
        op.get_bind().execute(
            sa.text("UPDATE job_suggestion SET watch_company_id = :w WHERE id = :s"), links
        )


def upgrade() -> None:
    _merge_duplicates()
    links = _suggestion_links()
    with op.batch_alter_table("watch_company") as batch_op:
        batch_op.drop_index("ix_watch_company_user_id")
        batch_op.alter_column(
            "user_id", new_column_name="added_by", existing_type=sa.Integer(), nullable=True
        )
    # SQLite cannot change a foreign key in place, so the table is recreated with the new one.
    with op.batch_alter_table(
        "watch_company",
        recreate="always",
        reflect_args=[
            sa.Column(
                "added_by",
                sa.Integer(),
                sa.ForeignKey("user_account.id", ondelete="SET NULL"),
                nullable=True,
            )
        ],
    ) as batch_op:
        batch_op.create_index("ix_watch_company_added_by", ["added_by"], unique=False)
    _restore(links)


def downgrade() -> None:
    # Ownerless rows go to the first admin so the column can be required again.
    op.execute(
        "UPDATE watch_company SET added_by = "
        "(SELECT id FROM user_account ORDER BY role != 'admin', id LIMIT 1) "
        "WHERE added_by IS NULL"
    )
    links = _suggestion_links()
    with op.batch_alter_table("watch_company") as batch_op:
        batch_op.drop_index("ix_watch_company_added_by")
        batch_op.alter_column(
            "added_by", new_column_name="user_id", existing_type=sa.Integer(), nullable=False
        )
    with op.batch_alter_table(
        "watch_company",
        recreate="always",
        reflect_args=[
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user_account.id", ondelete="CASCADE"),
                nullable=False,
            )
        ],
    ) as batch_op:
        batch_op.create_index("ix_watch_company_user_id", ["user_id"], unique=False)
    _restore(links)
