import email as email_lib
import re

import pytest
from sqlmodel import select

from jobhunter.models import ClaudeJob, EmailMessage, UserAccount
from jobhunter.services import mailer
from jobhunter.services.claude import queue
from tests.claude_helpers import fake_claude  # noqa: F401
from tests.integration.test_apply import _master_form

SENDER = {
    "from_address": "alice.jobs@example.org",
    "display_name": "Alice",
    "smtp_host": "smtp.example.org",
    "smtp_port": "587",
    "signature": "--\nAlice",
}


def _uid(session, name):
    return session.exec(select(UserAccount.id).where(UserAccount.username == name)).one()


def _incoming(session, uid, job_id=None, kind="employer", **extra):
    fields = {
        "from_addr": "jane@acme.com",
        "from_name": "Jane Smith",
        "subject": "Interview for QA Lead",
        "message_id": "<abc@acme.com>",
        "references": ["<first@acme.com>"],
        "body_text": "Hi Alice,\nCan you meet on Tuesday?\nJane",
        **extra,
    }
    e = EmailMessage(
        user_id=uid,
        dedupe_key=f"k{fields['subject']}{kind}",
        direction="in",
        kind=kind,
        job_id=job_id,
        **fields,
    )
    session.add(e)
    session.commit()
    return e.id


@pytest.fixture
def mailer_stub(monkeypatch):
    sent = []

    def fake(settings, username, message, recipients):
        sent.append((message, recipients))
        return mailer.Result(True, "Sent.")

    monkeypatch.setattr(mailer, "send_message", fake)
    return sent


def _job(client, title="QA Lead", company="Acme"):
    resp = client.post("/jobs", data={"title": title, "company": company})
    return int(resp.headers["location"].rsplit("/", 1)[1])


def _preview(client, email_id, **override):
    data = {
        "to": "jane@acme.com",
        "subject": "Re: Interview for QA Lead",
        "body": "Hi Jane,\n\nTuesday works for me.\n\nAlice",
        **override,
    }
    resp = client.post(f"/mail/{email_id}/reply/preview", data=data)
    token = re.search(r'name="token" value="([^"]+)"', resp.text)
    return resp, data, token.group(1) if token else None


def test_reply_preview_confirm_send(two_users, session, mailer_stub):
    alice, _ = two_users
    alice.post("/settings/sender", data=SENDER)
    job_id = _job(alice)
    eid = _incoming(session, _uid(session, "alice"), job_id)
    assert f'href="/mail/{eid}/reply"' in alice.get(f"/mail/{eid}").text
    page = alice.get(f"/mail/{eid}/reply").text
    assert 'value="jane@acme.com"' in page and 'value="Re: Interview for QA Lead"' in page

    resp, data, token = _preview(alice, eid)
    assert resp.status_code == 200 and "exactly what will be sent" in resp.text
    assert "&gt; Can you meet on Tuesday?" in resp.text and "--\nAlice" in resp.text
    r = alice.post(f"/mail/{eid}/reply/send", data={**data, "token": token})
    assert r.status_code == 400 and mailer_stub == []  # no confirmation tick
    changed = {**data, "body": "Something else", "token": token, "confirm": "yes"}
    assert alice.post(f"/mail/{eid}/reply/send", data=changed).status_code == 400
    assert mailer_stub == []
    r = alice.post(f"/mail/{eid}/reply/send", data={**data, "token": token, "confirm": "yes"})
    assert r.status_code == 200 and "Reply sent to jane@acme.com" in r.text

    [(message, recipients)] = mailer_stub
    assert recipients == ["jane@acme.com"]
    parsed = email_lib.message_from_bytes(bytes(message))
    assert parsed["In-Reply-To"] == "<abc@acme.com>"
    assert parsed["References"] == "<first@acme.com> <abc@acme.com>"
    body = message.get_body(("plain",)).get_content()
    assert body.index("Tuesday works") < body.index("--\nAlice") < body.index("> Can you meet")
    out = session.exec(select(EmailMessage).where(EmailMessage.direction == "out")).one()
    assert out.job_id == job_id and out.send_status == "sent"


def test_reply_scope(two_users, session, mailer_stub):
    alice, bob = two_users
    uid = _uid(session, "alice")
    eid = _incoming(session, uid)
    alert = _incoming(session, uid, kind="alert", subject="New jobs")
    assert bob.get(f"/mail/{eid}/reply").status_code == 404
    assert bob.post(f"/mail/{eid}/reply/preview", data={"to": "x@y.org"}).status_code == 404
    assert alice.get(f"/mail/{alert}/reply").status_code == 404
    assert f"/mail/{alert}/reply" not in alice.get(f"/mail/{alert}").text
    resp, _, token = _preview(alice, eid)  # no sender settings yet
    assert resp.status_code == 422 and token is None and "sender email" in resp.text


@pytest.fixture
def claude_user(make_user, user_client, fake_claude):  # noqa: F811
    make_user("alice", role="admin")
    make_user("bob")
    a = user_client("alice")
    a.post("/resume", data=_master_form())
    a.post("/settings/sender", data=SENDER)
    return a, user_client("bob"), fake_claude


def test_claude_draft(claude_user, session, mailer_stub):
    alice, bob, fake = claude_user
    job_id = _job(alice)
    eid = _incoming(session, _uid(session, "alice"), job_id)
    assert "Draft with Claude" in alice.get(f"/mail/{eid}/reply").text
    fake.respond(
        {
            "subject": "Re: Interview for QA Lead",
            "body": "Hi Jane,\n\nTuesday works. You can reach me at [your phone].\n\nAlice",
        }
    )
    r = alice.post(
        f"/mail/{eid}/reply/claude",
        data={"instructions": "accept, Tuesday is fine", "intent": "continue"},
    )
    assert r.status_code == 303
    while queue.process_next(session) is not None:
        pass
    job = session.exec(select(ClaudeJob).where(ClaudeJob.kind == "reply")).one()
    assert job.status == "done", job.error
    assert "1 placeholder" in job.summary
    call = fake.calls[0]
    assert call["argv"][call["argv"].index("--tools") + 1] == ""
    assert (
        "accept, Tuesday is fine" in call["stdin"] and "Can you meet on Tuesday?" in call["stdin"]
    )
    assert "still interested in the role" in call["stdin"]  # the "continue" purpose
    assert "QA Lead at Acme" in call["stdin"] and "Sam Rivera" in call["stdin"]  # job + resume
    assert f"/mail/{eid}/reply?draft={job.id}" in alice.get(f"/claude/jobs/{job.id}").text

    page = alice.get(f"/mail/{eid}/reply?draft={job.id}").text
    assert "You can reach me at [your phone]." in page and "Claude's draft" in page
    assert bob.get(f"/mail/{eid}/reply?draft={job.id}").status_code == 404
    other = _incoming(session, _uid(session, "alice"), subject="Other")
    assert alice.get(f"/mail/{other}/reply?draft={job.id}").status_code == 404

    resp, _, _ = _preview(alice, eid, body=job.result["body"])
    assert "placeholders to fill in: [your phone]" in resp.text
    assert mailer_stub == []  # Claude never sends anything
    assert bob.post(f"/mail/{eid}/reply/claude").status_code in (403, 404)


def test_withdraw_template_and_status(two_users, session, mailer_stub):
    alice, _ = two_users
    alice.post("/settings/sender", data=SENDER)
    job_id = _job(alice)
    alice.post(f"/jobs/{job_id}/status", data={"status": "interview"})
    eid = _incoming(session, _uid(session, "alice"), job_id)
    assert f"/mail/{eid}/reply?intent=withdraw" in alice.get(f"/jobs/{job_id}").text
    page = alice.get(f"/mail/{eid}/reply?intent=withdraw").text
    assert "Hi Jane," in page and "withdraw my application" in page and "QA Lead role" in page
    assert 'name="intent" value="withdraw"' in page
    body = re.search(r'name="body" rows="14">(.*?)</textarea>', page, re.S).group(1)
    body = body.replace("&#39;", "'")
    resp, data, token = _preview(alice, eid, body=body, intent="withdraw")
    assert "as Withdrawn" in resp.text and 'name="set_status" value="1" checked' in resp.text
    r = alice.post(
        f"/mail/{eid}/reply/send",
        data={**data, "token": token, "confirm": "yes", "set_status": "1"},
    )
    assert r.status_code == 200 and "now marked Withdrawn" in r.text
    assert len(mailer_stub) == 1
    session.expire_all()
    from jobhunter.models import Job

    assert session.get(Job, job_id).status == "withdrawn"


def test_continue_keeps_status_when_unticked(two_users, session, mailer_stub):
    alice, _ = two_users
    alice.post("/settings/sender", data=SENDER)
    job_id = _job(alice)
    alice.post(f"/jobs/{job_id}/status", data={"status": "applied"})
    eid = _incoming(session, _uid(session, "alice"), job_id)
    page = alice.get(f"/mail/{eid}/reply?intent=continue").text
    assert "continue with the next step" in page and "[your availability]" in page
    resp, data, token = _preview(alice, eid, intent="continue")
    assert "as Interview" in resp.text
    r = alice.post(f"/mail/{eid}/reply/send", data={**data, "token": token, "confirm": "yes"})
    assert r.status_code == 200 and "now marked" not in r.text
    session.expire_all()
    from jobhunter.models import Job

    assert session.get(Job, job_id).status == "applied"
