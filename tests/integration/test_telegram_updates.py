import datetime as dt

from sqlmodel import select

from jobhunter.models import (
    ClaudeJob,
    EmailMessage,
    JobSuggestion,
    NotificationSettings,
    UserAccount,
)
from jobhunter.services import telegram, updates

NOON = dt.datetime(2026, 10, 7, 18, 0, tzinfo=dt.UTC)  # 12:00 in Edmonton


def _uid(session, name):
    return session.exec(select(UserAccount.id).where(UserAccount.username == name)).one()


def _suggestion(session, uid, n, **extra):
    s = JobSuggestion(
        user_id=uid,
        title=f"QA Lead {n}",
        company="Acme",
        url=f"https://x/{n}",
        url_norm=f"x/{n}",
        **extra,
    )
    session.add(s)
    session.commit()
    return s


def _stub(sent, ok=True):
    return lambda chat, text: (sent.append((chat, text)), telegram.Result(ok, "nope"))[1]


def _clock(monkeypatch, at):
    monkeypatch.setattr(updates, "utcnow", lambda: at)


def test_updates_flow(two_users, session, monkeypatch):
    alice, bob = two_users
    uid, bid = _uid(session, "alice"), _uid(session, "bob")
    monkeypatch.setenv("PUBLIC_URL", "https://jobs.example.org")
    _suggestion(session, uid, "old")
    _suggestion(session, bid, "bob-old")
    alice.post(
        "/settings/notifications",
        data={"telegram_chat_id": "111", "stale_days": "7", "updates_enabled": "1"},
    )
    session.add(NotificationSettings(user_id=bid, telegram_chat_id="222", updates_enabled=True))
    session.commit()
    sent = []
    _clock(monkeypatch, NOON)
    assert updates.send_due(session, _stub(sent)) == 0  # first check: start from now
    assert sent == []

    _suggestion(session, uid, 1, score=40)
    _suggestion(session, uid, 2, fit_score=90, location="Calgary")
    _suggestion(session, uid, 3, state="dismissed")
    _suggestion(session, bid, "bob-new")
    job = alice.post("/jobs", data={"title": "SDET", "company": "Initech"})
    job_id = int(job.headers["location"].rsplit("/", 1)[1])
    session.add(
        EmailMessage(
            user_id=uid,
            dedupe_key="e1",
            direction="in",
            kind="employer",
            job_id=job_id,
            from_name="Jane HR",
            subject="Interview?",
        )
    )
    session.add(EmailMessage(user_id=uid, dedupe_key="e2", direction="in", kind="alert"))
    later = NOON + dt.timedelta(minutes=15)
    session.add(
        ClaudeJob(
            user_id=uid,
            kind="tailor",
            status="done",
            summary="Resume ready",
            finished_at=NOON + dt.timedelta(minutes=5),
        )
    )
    session.add(
        ClaudeJob(
            user_id=uid,
            kind="find_jobs",
            status="done",
            summary="silent",
            finished_at=NOON + dt.timedelta(minutes=5),
        )
    )
    session.add(
        ClaudeJob(
            user_id=uid,
            kind="find_jobs",
            status="failed",
            error="token expired",
            finished_at=NOON + dt.timedelta(minutes=6),
        )
    )
    session.commit()
    _clock(monkeypatch, later)
    assert updates.send_due(session, _stub(sent)) == 2
    by_chat = dict(sent)
    text = by_chat["111"]
    assert "2 new suggestions" in text and "QA Lead 3" not in text and "old" not in text
    assert text.index("QA Lead 2") < text.index("QA Lead 1")  # best fit first
    assert "https://jobs.example.org/suggestions" in text
    assert "Jane HR about SDET at Initech: Interview?" in text
    assert "Tailored resume: Resume ready" in text and "token expired" in text
    assert "silent" not in text and "bob" not in text
    assert "1 new suggestion:" in by_chat["222"] and "bob-new" in by_chat["222"]

    sent.clear()
    _clock(monkeypatch, later + dt.timedelta(minutes=15))
    assert updates.send_due(session, _stub(sent)) == 0  # nothing new
    assert sent == []


def test_quiet_hours_and_retry(two_users, session, monkeypatch):
    uid = _uid(session, "alice")
    ns = NotificationSettings(user_id=uid, telegram_chat_id="111", updates_enabled=True)
    session.add(ns)
    session.commit()
    _clock(monkeypatch, NOON)
    updates.send_due(session, _stub([]))
    _suggestion(session, uid, 1)
    sent = []
    _clock(monkeypatch, dt.datetime(2026, 10, 8, 5, 0, tzinfo=dt.UTC))  # 23:00 local
    assert updates.send_due(session, _stub(sent)) == 0 and sent == []
    _clock(monkeypatch, dt.datetime(2026, 10, 8, 14, 0, tzinfo=dt.UTC))  # 08:00 local
    assert updates.send_due(session, _stub(sent, ok=False)) == 0
    session.refresh(ns)
    assert ns.last_error == "nope"
    assert updates.send_due(session, _stub(sent)) == 1  # the failed batch is sent again
    assert "QA Lead 1" in sent[-1][1]


def test_disabled_by_default_and_settings_form(two_users, session):
    alice, _ = two_users
    page = alice.get("/settings/notifications")
    assert (
        'name="updates_enabled"' in page.text
        and 'updates_enabled" value="1" checked' not in page.text
    )
    alice.post("/settings/notifications", data={"telegram_chat_id": "111", "stale_days": "7"})
    ns = session.get(NotificationSettings, _uid(session, "alice"))
    assert ns.updates_enabled is False
    assert updates.send_due(session, _stub([])) == 0
