import sqlite3

from alembic import command
from alembic.config import Config

from tests.conftest import ROOT


def _insert(con, table, **values):
    """Insert a row, filling every other required column with a placeholder of its type."""
    for _, name, type_, notnull, default, pk in con.execute(f"PRAGMA table_info({table})"):
        if name in values or not notnull or default is not None or pk:
            continue
        t = type_.upper()
        values[name] = (
            0
            if any(k in t for k in ("INT", "BOOL"))
            else "[]"
            if "JSON" in t
            else "2026-10-07 00:00:00"
            if "DATE" in t
            else "x"
        )
    cols = ", ".join(f'"{c}"' for c in values)
    marks = ", ".join("?" for _ in values)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"  # noqa: S608 - test-only, fixed names
    con.execute(sql, list(values.values()))


def test_0016_moves_reply_drafts(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.attributes["database_url"] = f"sqlite:///{path}"
    command.upgrade(cfg, "0015")
    con = sqlite3.connect(path)
    _insert(con, "user_account", id=1, username="a")
    _insert(con, "email_message", id=5, user_id=1, dedupe_key="k")
    con.execute(
        "INSERT INTO reply_draft (id, user_id, email_id, to_addrs, subject, body, intent, "
        "by_claude, updated_at) VALUES (3, 1, 5, '[\"x@y.org\"]', 'Re: s', 'hi', 'withdraw', 1, "
        "'2026-10-07 00:00:00')"
    )
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    row = con.execute(
        "SELECT id, kind, email_id, job_id, body, attachments, intent, by_claude FROM email_draft"
    ).fetchall()
    assert row == [(3, "reply", 5, None, "hi", "[]", "withdraw", 1)]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "reply_draft" not in tables
    con.close()
    command.downgrade(cfg, "0015")  # and back
