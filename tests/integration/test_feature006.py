import csv
import datetime as dt
import io

import httpx
import pytest
from sqlmodel import select

from jobhunter.db import utcnow
from jobhunter.models import (
    ClaudeJob,
    EmailMessage,
    JobPrep,
    NotificationSettings,
    StatusChange,
    UserAccount,
)
from jobhunter.routes.notifications import get_sender
from jobhunter.services import reminders, telegram
from jobhunter.services.claude import queue
from tests.claude_helpers import fake_claude  # noqa: F401
from tests.integration.test_apply import _master_form


def _uid(session, name):
    return session.exec(select(UserAccount.id).where(UserAccount.username == name)).one()


def _job(client, title, company="Acme", **extra):
    resp = client.post("/jobs", data={"title": title, "company": company, **extra})
    return int(resp.headers["location"].rsplit("/", 1)[1])


def _backdate_applied(session, job_id, days):
    entry = session.exec(
        select(StatusChange).where(
            StatusChange.job_id == job_id, StatusChange.to_status == "applied"
        )
    ).one()
    entry.effective_at = utcnow() - dt.timedelta(days=days)
    session.add(entry)
    session.commit()


# --- reminders -----------------------------------------------------------------------------


def test_no_reply_rules(two_users, session):
    alice, bob = two_users
    uid = _uid(session, "alice")
    quiet = _job(alice, "Quiet")
    replied = _job(alice, "Replied")
    recent = _job(alice, "Recent")
    moved = _job(alice, "Moved on")
    for j in (quiet, replied, recent, moved):
        alice.post(f"/jobs/{j}/status", data={"status": "applied"})
    for j in (quiet, replied, moved):
        _backdate_applied(session, j, 9)
    _backdate_applied(session, recent, 2)
    alice.post(f"/jobs/{moved}/status", data={"status": "screening"})
    session.add(EmailMessage(user_id=uid, dedupe_key="r", direction="in", job_id=replied))
    session.commit()
    b = _job(bob, "Bob quiet")
    bob.post(f"/jobs/{b}/status", data={"status": "applied"})
    _backdate_applied(session, b, 30)
    got = [(j.title, d) for j, d in reminders.no_reply(session, uid, 7)]
    assert got == [("Quiet", 9)]
    assert "Quiet" in alice.get("/").text and "Bob quiet" not in alice.get("/").text


def test_daily_send_once_and_only_own_jobs(two_users, session, monkeypatch):
    alice, bob = two_users
    uid, bid = _uid(session, "alice"), _uid(session, "bob")
    j = _job(alice, "QA Lead")
    alice.post(
        f"/jobs/{j}/followups", data={"due_date": str(dt.date.today()), "description": "call Jane"}
    )
    bj = _job(bob, "Bob's job")
    bob.post(
        f"/jobs/{bj}/followups",
        data={"due_date": str(dt.date.today()), "description": "bob secret"},
    )
    session.add(NotificationSettings(user_id=uid, telegram_chat_id="111"))
    session.add(NotificationSettings(user_id=bid, telegram_chat_id=None))
    session.commit()
    sent = []
    from jobhunter.services import reminders as r

    monkeypatch.setattr(r, "utcnow", lambda: dt.datetime(2026, 10, 6, 16, 0, tzinfo=dt.UTC))
    monkeypatch.setenv("PUBLIC_URL", "https://jobs.example.org")
    stub = lambda chat, text: (sent.append((chat, text)), telegram.Result(True, "ok"))[1]  # noqa: E731
    assert r.send_due(session, stub) == 1
    assert r.send_due(session, stub) == 0  # once per day
    [(chat, text)] = sent
    assert chat == "111" and "call Jane" in text and "bob secret" not in text
    assert f"https://jobs.example.org/jobs/{j}" in text


def test_before_8am_nothing(two_users, session, monkeypatch):
    from jobhunter.services import reminders as r

    session.add(NotificationSettings(user_id=_uid(session, "alice"), telegram_chat_id="1"))
    session.commit()
    monkeypatch.setattr(r, "utcnow", lambda: dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.UTC))
    assert r.send_due(session, lambda c, t: telegram.Result(True, "")) == 0


def test_telegram_send_and_errors(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert "isn't configured" in telegram.send("1", "x").message
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET-TOKEN")
    seen = {}

    def ok(request):
        seen["url"], seen["body"] = str(request.url), request.content
        return httpx.Response(200, json={"ok": True, "result": {}})

    assert telegram.send("42", "hi", transport=httpx.MockTransport(ok)).ok
    assert seen["url"].endswith("/sendMessage") and b'"chat_id":"42"' in seen["body"]

    def chat_missing(request):
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    r = telegram.send("42", "hi", transport=httpx.MockTransport(chat_missing))
    assert not r.ok and "/start" in r.message and "SECRET" not in r.message

    def down(request):
        raise httpx.ConnectError("boom", request=request)

    r = telegram.send("42", "hi", transport=httpx.MockTransport(down))
    assert not r.ok and "SECRET" not in r.message


def test_notifications_settings_page(two_users, session, app, monkeypatch):
    alice, bob = two_users
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET-TOKEN")
    page = alice.get("/settings/notifications").text
    assert "SECRET-TOKEN" not in page
    assert (
        alice.post(
            "/settings/notifications", data={"telegram_chat_id": "abc", "stale_days": "7"}
        ).status_code
        == 422
    )
    assert (
        alice.post(
            "/settings/notifications", data={"telegram_chat_id": "123456", "stale_days": "90"}
        ).status_code
        == 422
    )
    assert (
        alice.post(
            "/settings/notifications",
            data={"telegram_chat_id": "123456", "stale_days": "10", "reminders_enabled": "1"},
        ).status_code
        == 303
    )
    ns = session.get(NotificationSettings, _uid(session, "alice"))
    assert (ns.telegram_chat_id, ns.stale_days, ns.reminders_enabled) == ("123456", 10, True)
    sent = []
    app.dependency_overrides[get_sender] = lambda: (
        lambda chat, text: (sent.append(chat), telegram.Result(True, "ok"))[1]
    )
    try:
        assert "Test message sent" in alice.post("/settings/notifications/test").text
        bob.post("/settings/notifications/test")
    finally:
        app.dependency_overrides.clear()
    assert sent == ["123456", ""]  # bob has no chat id: never alice's


# --- CSV export ----------------------------------------------------------------------------


def test_csv_export(two_users, session):
    alice, bob = two_users
    a = _job(alice, "QA Lead", "Acme", url="https://jobs.lever.co/acme/1")
    alice.post(f"/jobs/{a}/status", data={"status": "applied"})
    alice.post(f"/jobs/{a}/contacts", data={"name": "Jane", "email": "jane@acmerobotics.com"})
    _job(alice, '=HYPERLINK("http://evil")', "@Evil")
    _job(bob, "Bob only", "Bob Co")
    resp = alice.get("/jobs/export.csv")
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"].startswith("attachment")
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert rows[0][:5] == ["Title", "Company", "Location", "Work mode", "Status"]
    titles = [r[0] for r in rows[1:]]
    assert "Bob only" not in titles and len(rows) == 3
    evil = next(r for r in rows[1:] if "HYPERLINK" in r[0])
    assert evil[0].startswith("'=") and evil[1] == "'@Evil"
    qa = next(r for r in rows[1:] if r[0] == "QA Lead")
    assert qa[4] == "applied" and qa[8] and "Jane <jane@acmerobotics.com>" in qa[12]
    filtered = list(
        csv.reader(
            io.StringIO(alice.get("/jobs/export.csv?status=applied").content.decode("utf-8-sig"))
        )
    )
    assert [r[0] for r in filtered[1:]] == ["QA Lead"]
    assert "Export CSV" in alice.get("/jobs").text


# --- interview prep ------------------------------------------------------------------------


@pytest.fixture
def admin(make_user, user_client, session, fake_claude):  # noqa: F811
    make_user("alice", role="admin")
    make_user("bob")
    a = user_client("alice")
    a.post("/resume", data=_master_form())
    return a, user_client("bob"), fake_claude


def test_prep_with_claude(admin, session):
    alice, bob, fake = admin
    job_id = _job(alice, "QA Lead", "Acme Robotics", description="Lead QA with Selenium.")
    fake.respond(
        {
            "company_overview": "Acme builds robots.",
            "questions": [
                {
                    "question": "How do you scale test automation?",
                    "why": "Posting stresses automation.",
                    "answer_outline": "Describe the Selenium framework.",
                    "resume_refs": ["e1:1", "nope:9"],
                }
            ],
            "questions_to_ask": ["What does success look like in 90 days?"],
        }
    )
    assert alice.post(f"/jobs/{job_id}/prep").status_code == 303
    while queue.process_next(session) is not None:
        pass
    job = session.exec(select(ClaudeJob).where(ClaudeJob.kind == "prep")).one()
    assert job.status == "done", job.error
    prep = session.exec(select(JobPrep)).one()
    assert prep.data["questions"][0]["resume_refs"] == ["e1:1"]
    page = alice.get(f"/jobs/{job_id}").text
    assert "Acme builds robots." in page and "Built a Selenium and Python" in page
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert bob.post(f"/jobs/{job_id}/prep").status_code == 403
