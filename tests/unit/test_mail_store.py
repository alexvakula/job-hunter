from pathlib import Path

from sqlmodel import select

from jobhunter.models import EmailAttachment, EmailMessage
from jobhunter.services import mail_store
from jobhunter.services.mail_store import (
    dedupe_key,
    delete_email,
    parse_email,
    sanitize_html,
    store,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "emails"


def raw(name):
    return (FIX / name).read_bytes()


def test_parse_headers_and_bodies():
    p = parse_email(raw("recruiter_reply.eml"))
    assert p.message_id == "jane-1@acmerobotics.com"
    assert (p.from_name, p.from_addr) == ("Jane Recruiter", "jane@acmerobotics.com")
    assert p.to_addrs == ["sam.jobs@example.org"]
    assert p.subject == "Re: QA Lead at Acme Robotics"
    assert "free Tuesday" in p.body_text
    assert "<b>Tuesday</b>" in p.body_html
    assert p.sent_at is not None and p.sent_at.tzinfo is not None
    assert [(a.filename, a.content_type) for a in p.attachments] == [
        ("Interview schedule.pdf", "application/pdf")
    ]


def test_threading_headers():
    p = parse_email(raw("threaded_reply.eml"))
    assert p.in_reply_to == "app-sent-1@example.org"
    assert p.references == ["app-sent-1@example.org"]


def test_dedupe_key_uses_message_id_or_hash():
    assert dedupe_key(parse_email(raw("recruiter_reply.eml"))) == "mid:jane-1@acmerobotics.com"
    key = dedupe_key(parse_email(raw("no_message_id.eml")))
    assert key.startswith("sha:") and key == dedupe_key(parse_email(raw("no_message_id.eml")))


def test_garbage_never_raises():
    for data in (b"", b"\x00\xff\xfe garbage", b"Subject: =?bad?=\n\n\xff"):
        assert isinstance(parse_email(data).body_text, str)


def test_sanitize_strips_dangerous_content():
    clean = sanitize_html(parse_email(raw("malicious.eml")).body_html)
    for bad in (
        "<script",
        "alert(1)",
        "onclick",
        "<img",
        "<iframe",
        "<form",
        "<input",
        "javascript:",
        "<style",
        "evil.example/track",
        "evil.example/bg",
    ):
        assert bad not in clean, bad
    assert 'href="https://evil.example/ok"' in clean
    assert 'rel="noopener noreferrer nofollow"' in clean


def test_store_dedupes_and_keeps_files(session, make_user):
    user = make_user("alice")
    email, created = store(
        session, user.id, raw("recruiter_reply.eml"), folder="INBOX", folder_uid=7
    )
    assert created and email.kind == "other" and email.folder == "INBOX"
    assert mail_store.raw_path(email).read_bytes() == raw("recruiter_reply.eml")
    att = session.exec(select(EmailAttachment)).one()
    assert mail_store.attachment_path(email, att).read_bytes().startswith(b"%PDF")
    again, created = store(session, user.id, raw("recruiter_reply.eml"), folder="Employers/X")
    assert not created and again.id == email.id
    assert len(session.exec(select(EmailMessage)).all()) == 1


def test_same_email_for_two_users_is_two_records(session, make_user):
    a, b = make_user("alice"), make_user("bob")
    store(session, a.id, raw("recruiter_reply.eml"))
    store(session, b.id, raw("recruiter_reply.eml"))
    assert len(session.exec(select(EmailMessage)).all()) == 2


def test_attachment_limit(session, make_user, monkeypatch):
    monkeypatch.setattr(mail_store, "MAX_ATTACHMENT_BYTES", 5)
    user = make_user("alice")
    email, _ = store(session, user.id, raw("recruiter_reply.eml"))
    att = session.exec(select(EmailAttachment)).one()
    assert att.skipped and att.storage_name is None and att.size_bytes > 5


def test_delete_removes_files(session, make_user):
    user = make_user("alice")
    email, _ = store(session, user.id, raw("recruiter_reply.eml"))
    path = mail_store.raw_path(email)
    delete_email(session, email)
    assert not path.exists()
    assert session.exec(select(EmailMessage)).all() == []
    assert session.exec(select(EmailAttachment)).all() == []
