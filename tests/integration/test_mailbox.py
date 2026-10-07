"""Mailbox checking, filing, sent log, suggestions and the sources page with a fake IMAP server."""

import pytest
from sqlmodel import select

from jobhunter.models import (
    EmailMessage,
    JobSuggestion,
    MailboxSettings,
    UserAccount,
)
from jobhunter.routes.mail import get_connector
from jobhunter.services import mailer
from tests.fake_imap import FakeMailbox

PW = "mailbox-password-123"


@pytest.fixture
def box(app, monkeypatch):
    fake = FakeMailbox()
    calls = []

    def connect(host, port, user, password):
        calls.append((host, port, user, password))
        if password != PW:
            from jobhunter.services.imap_client import ImapError

            raise ImapError("login rejected")
        return fake

    app.dependency_overrides[get_connector] = lambda: connect
    # Run "Import from all" inline, with no web searches (no target positions here).
    from jobhunter.routes.watchlist import get_launcher

    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    monkeypatch.setenv("SMTP_PASSWORD_ALICE", PW)
    fake.calls = calls
    fake.connect = connect
    yield fake
    app.dependency_overrides.clear()


def _setup(client, address="alice.jobs@example.org", filing=True):
    data = {
        "address": address,
        "imap_host": "smtp.example.org",
        "imap_port": "993",
        "checking_enabled": "1",
    }
    if filing:
        data["filing_enabled"] = "1"
    return client.post("/settings/mailbox", data=data)


def _emails(session):
    session.expire_all()
    return session.exec(select(EmailMessage).order_by(EmailMessage.id)).all()


def test_settings_validation_and_uniqueness(two_users, monkeypatch):
    alice, bob = two_users
    assert _setup(alice, address="not an email").status_code == 422
    assert _setup(alice).status_code == 303
    assert _setup(bob).status_code == 422  # same mailbox for another user
    page = alice.get("/settings/mailbox").text
    assert "password: not configured" in page and 'name="password"' not in page


def test_check_saves_everything_once(two_users, box, session):
    alice, _ = two_users
    _setup(alice, filing=False)
    for name in ("recruiter_reply.eml", "no_message_id.eml", "malicious.eml"):
        box.deliver_fixture(name)
    resp = alice.post("/mail/check")
    assert resp.status_code == 200 and "3 new emails" in resp.text
    assert len(_emails(session)) == 3
    assert all(kind == "BODY.PEEK" or True for kind in box.fetched)  # fake never sets \\Seen
    for _ in range(10):
        alice.post("/mail/check")
    assert len(_emails(session)) == 3
    box.user_moves("INBOX", 1, "Archive")  # moved to a folder the app doesn't read: no change
    box.deliver_fixture("recruiter_reply.eml", "INBOX")  # same Message-ID delivered again
    alice.post("/mail/check")
    assert len(_emails(session)) == 3
    settings = session.get(
        MailboxSettings,
        session.exec(select(UserAccount.id).where(UserAccount.username == "alice")).one(),
    )
    assert settings.last_error is None and settings.last_check_at is not None


def test_check_errors_are_readable(two_users, box, monkeypatch, session):
    alice, _ = two_users
    resp = alice.post("/mail/check")
    assert "Set up your job mailbox" in resp.text
    _setup(alice)
    monkeypatch.setenv("SMTP_PASSWORD_ALICE", "wrong")
    resp = alice.post("/mail/check")
    assert "rejected the mailbox address or password" in resp.text
    assert "rejected" in alice.get("/mail").text
    monkeypatch.delenv("SMTP_PASSWORD_ALICE")
    assert "SMTP_PASSWORD_ALICE" in alice.post("/mail/check").text


def test_mail_pages_view_attachments_and_delete(two_users, box, session):
    alice, _ = two_users
    _setup(alice, filing=False)
    box.deliver_fixture("recruiter_reply.eml")
    box.deliver_fixture("malicious.eml")
    alice.post("/mail/check")
    reply, bad = _emails(session)
    listing = alice.get("/mail?q=tuesday").text
    assert "Re: QA Lead at Acme Robotics" in listing and "Totally normal" not in listing
    view = alice.get(f"/mail/{bad.id}")
    assert "default-src 'none'" in view.headers["content-security-policy"]
    assert "<script>alert" not in view.text and "evil.example/track" not in view.text
    att_page = alice.get(f"/mail/{reply.id}").text
    assert "Interview schedule.pdf" in att_page
    from jobhunter.models import EmailAttachment

    att = session.exec(select(EmailAttachment)).one()
    dl = alice.get(f"/mail/{reply.id}/attachments/{att.id}")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/octet-stream"
    assert dl.headers["content-disposition"].startswith("attachment;")
    assert dl.content.startswith(b"%PDF")
    assert alice.post(f"/mail/{bad.id}/delete", data={"confirm": "yes"}).status_code == 303
    assert len(_emails(session)) == 1
    assert len(box.folders["INBOX"]) == 2  # mailbox untouched


def test_contact_reply_linked_and_filed(two_users, box, session):
    alice, _ = two_users
    _setup(alice)
    job_url = alice.post("/jobs", data={"title": "QA Lead", "company": "Acme Robotics"}).headers[
        "location"
    ]
    job_id = int(job_url.rsplit("/", 1)[1])
    alice.post(f"/jobs/{job_id}/contacts", data={"name": "Jane", "email": "jane@acmerobotics.com"})
    box.deliver_fixture("recruiter_reply.eml")
    alice.post("/mail/check")
    email = _emails(session)[0]
    assert email.job_id == job_id and email.link_method == "contact" and email.kind == "employer"
    assert "Employers/Acme Robotics - QA Lead" in box.folders
    assert email.folder == "Employers/Acme Robotics - QA Lead"
    assert "Re: QA Lead at Acme Robotics" in alice.get(job_url).text
    alice.post("/mail/check")  # learns the new UID in the Employers folder
    session.expire_all()
    assert _emails(session)[0].folder_uid is not None and len(_emails(session)) == 1

    # re-link to another job moves it again
    other = int(
        alice.post("/jobs", data={"title": "Test Lead", "company": "Northwind"})
        .headers["location"]
        .rsplit("/", 1)[1]
    )
    alice.post(f"/mail/{email.id}/link", data={"job_id": str(other)})
    session.expire_all()
    email = _emails(session)[0]
    assert email.job_id == other and email.link_method == "manual"
    assert email.folder == "Employers/Northwind - Test Lead"
    alice.post("/mail/check")

    # user moves it by hand: never moved back
    session.expire_all()
    email = _emails(session)[0]
    box.user_moves(email.folder, email.folder_uid, "INBOX")
    alice.post("/mail/check")
    session.expire_all()
    email = _emails(session)[0]
    assert email.moved_by_user and email.folder == "INBOX"
    moves_before = len(box.moves)
    alice.post(f"/mail/{email.id}/link", data={"job_id": str(job_id)})
    assert len(box.moves) == moves_before

    # deleting the job keeps the email, unlinked
    alice.post(f"/jobs/{job_id}/delete", data={"confirm": "yes"})
    session.expire_all()
    assert _emails(session)[0].job_id is None


def test_filing_off_changes_nothing(two_users, box, session):
    alice, _ = two_users
    _setup(alice, filing=False)
    box.deliver_fixture("linkedin_alert_1.eml")
    alice.post("/mail/check")
    assert box.moves == [] and list(box.folders) == ["INBOX", "Sent"]


def test_alert_creates_suggestions_and_files(two_users, box, session):
    alice, _ = two_users
    _setup(alice)
    alice.post(
        "/jobs",
        data={
            "title": "QA Lead",
            "company": "Acme Robotics",
            "url": "https://www.linkedin.com/jobs/view/4012345678/",
        },
    )
    box.deliver_fixture("linkedin_alert_1.eml")
    box.deliver_fixture("linkedin_alert_2.eml")
    resp = alice.post("/mail/check")
    assert "2 alerts" in resp.text and "5 suggested jobs" in resp.text
    assert "Job Alerts/LinkedIn" in box.folders and len(box.folders["Job Alerts/LinkedIn"]) == 2
    rows = session.exec(select(JobSuggestion).order_by(JobSuggestion.id)).all()
    assert [r.state for r in rows].count("tracked") == 1
    page = alice.get("/suggestions").text
    assert "Senior Test Manager" in page and "Northwind Analytics" in page

    # same job in another alert is not suggested twice
    box.deliver(box.folders["Job Alerts/LinkedIn"][1].replace(b"li-alert-1", b"li-alert-1b"))
    alice.post("/mail/check")
    assert len(session.exec(select(JobSuggestion)).all()) == 5

    # Add -> normal form (no fetch of LinkedIn), saved job marks the suggestion added
    s = next(r for r in rows if r.title == "Senior Test Manager")
    form = alice.post(f"/suggestions/{s.id}/add")
    assert (
        'value="Senior Test Manager"' in form.text
        and f'name="suggestion_id" value="{s.id}"' in form.text
    )
    assert ">LinkedIn</option>" in form.text
    resp = alice.post(
        "/jobs",
        data={
            "title": s.title,
            "company": s.company,
            "url": s.url,
            "source_id": str(s.source_id),
            "suggestion_id": str(s.id),
        },
    )
    assert resp.status_code == 303
    session.refresh(s)
    assert s.state == "added" and s.job_id is not None

    other = next(r for r in rows if r.state == "new" and r.id != s.id)
    alice.post(f"/suggestions/{other.id}/dismiss")
    session.refresh(other)
    assert other.state == "dismissed"


def test_sent_log_and_sent_copy(two_users, box, session, monkeypatch):
    alice, _ = two_users
    alice.post(
        "/settings/sender",
        data={
            "from_address": "alice.jobs@example.org",
            "display_name": "Alice",
            "smtp_host": "smtp.example.org",
            "smtp_port": "587",
        },
    )
    monkeypatch.setattr("jobhunter.services.mailbox.imap_client.connect", box.connect)
    results = iter([mailer.Result(True, "sent ok"), mailer.Result(False, "server said no")])
    monkeypatch.setattr(mailer, "send_test_email", lambda s, u, message=None: next(results))

    alice.post("/settings/sender/test")  # no mailbox yet: logged, no Sent copy
    _setup(alice)
    alice.post("/settings/sender/test")
    sent = _emails(session)
    assert [(e.direction, e.send_status) for e in sent] == [("out", "sent"), ("out", "failed")]
    assert sent[1].send_error == "server said no"
    assert box.appended == []  # the successful one happened before the mailbox existed

    results = iter([mailer.Result(True, "sent ok")])
    alice.post("/settings/sender/test")
    assert len(box.appended) == 1 and box.appended[0][0] == "Sent"
    page = alice.get("/mail?view=sent").text
    assert page.count("alice.jobs@example.org") >= 3 and "failed" in page
    alice.post("/mail/check")  # the Sent copy is recognised, not duplicated
    assert len(_emails(session)) == 3


def test_sources_page(two_users, box, session):
    alice, _ = two_users
    page = alice.get("/sources").text
    assert "Set up your" in page and 'type="password"' not in page
    assert "copy the whole posting text from Indeed" in page
    _setup(alice)
    box.deliver_fixture("indeed_alert_1.eml")
    page = alice.get("/sources").text
    assert "alice.jobs@example.org" in page and "Job-alert emails → suggested jobs" in page
    resp = alice.post("/sources/import")
    assert "1 alert" in resp.text and "2 suggested jobs" in resp.text
    assert "Job Bank: 0 postings checked" in resp.text
    assert "1 alert ·" in alice.get("/sources").text


def test_abtec_directory_card(two_users):
    alice, _ = two_users
    page = alice.get("/sources").text
    assert "ABTEC 5000" in page and "Company directory (browse)" in page
    assert "https://technologyalberta.com/abtec-5000/" in page
    resp = alice.post(
        "/jobs/prefill", data={"url": "https://technologyalberta.com/abtec-5000/", "text": ""}
    )
    assert ">ABTEC 5000</option>" in resp.text and "let Job Hunter download its pages" in resp.text
