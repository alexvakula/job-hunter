from sqlmodel import select

from jobhunter.models import SenderSettings
from jobhunter.services import mailer

SECRET = "super-secret-mail-pw"
VALID = {
    "from_address": "alice@example.org",
    "display_name": "Alice",
    "reply_to": "",
    "smtp_host": "smtp.example.org",
    "smtp_port": "587",
    "smtp_username": "alice@example.org",
    "signature": "Thanks,\nAlice",
    "bcc_self": "1",
}


def test_defaults_for_new_user(two_users):
    alice, _ = two_users
    page = alice.get("/settings/sender").text
    assert 'value="smtp.example.org"' in page and 'value="587"' in page
    assert "password: not configured" in page


def test_save_and_validate(two_users, session):
    alice, _ = two_users
    bad = alice.post("/settings/sender", data={**VALID, "from_address": "nope"})
    assert bad.status_code == 422 and "valid email" in bad.text
    bad = alice.post("/settings/sender", data={**VALID, "reply_to": "nope@"})
    assert bad.status_code == 422
    bad = alice.post("/settings/sender", data={**VALID, "smtp_port": "99999"})
    assert bad.status_code == 422
    assert alice.post("/settings/sender", data=VALID).status_code == 303
    row = session.exec(select(SenderSettings)).one()
    assert row.from_address == "alice@example.org" and row.bcc_self and row.reply_to == ""


def test_password_status_shown_never_value(two_users, monkeypatch):
    alice, _ = two_users
    monkeypatch.setenv("SMTP_PASSWORD_ALICE", SECRET)
    page = alice.get("/settings/sender").text
    assert "password: configured" in page and SECRET not in page
    assert 'name="password"' not in page and "SMTP_PASSWORD_ALICE" in page


def test_test_email_without_password_explains(two_users, monkeypatch):
    alice, _ = two_users
    monkeypatch.delenv("SMTP_PASSWORD_ALICE", raising=False)
    alice.post("/settings/sender", data=VALID)
    resp = alice.post("/settings/sender/test")
    assert resp.status_code == 200 and "SMTP_PASSWORD_ALICE" in resp.text


def test_test_email_requires_csrf_and_post(two_users):
    alice, _ = two_users
    assert alice.get("/settings/sender/test").status_code == 405
    resp = alice.client.post("/settings/sender/test", follow_redirects=False)
    assert resp.status_code == 403


def test_test_email_uses_own_settings_only(two_users, monkeypatch):
    alice, bob = two_users
    alice.post("/settings/sender", data=VALID)
    seen = []

    def fake_send(settings, username, message=None):
        seen.append((settings.from_address, username))
        return mailer.Result(ok=True, message="sent")

    monkeypatch.setattr(mailer, "send_test_email", fake_send)
    bob.post("/settings/sender/test")  # bob saved nothing: his own empty settings are used
    resp = alice.post("/settings/sender/test")
    assert seen == [("", "bob"), ("alice@example.org", "alice")]
    assert "sent" in resp.text


def test_seed_defaults_adds_sender(session):
    from jobhunter.cli import create_admin

    create_admin("sam", "Sam Rivera", True, password="a long enough password")
    row = session.exec(select(SenderSettings)).one()
    assert (row.from_address, row.display_name, row.reply_to) == (
        "sam.jobs@example.org",
        "Sam Rivera",
        "sam.jobs@example.org",
    )
    assert (row.smtp_host, row.smtp_port, row.smtp_username, row.bcc_self) == (
        "smtp.example.org",
        587,
        "sam.jobs@example.org",
        False,
    )


def test_seed_defaults_fills_missing_sender_for_existing_profile(session):
    from jobhunter.cli import create_admin, seed_defaults

    create_admin("sam", "Sam Rivera", False, password="a long enough password")
    assert seed_defaults("sam") == 0
    session.exec(select(SenderSettings)).one().from_address  # noqa: B018
    for row in session.exec(select(SenderSettings)).all():
        session.delete(row)
    session.commit()
    assert seed_defaults("sam") == 0  # profile exists, sender re-added
    assert session.exec(select(SenderSettings)).one().from_address == "sam.jobs@example.org"
    assert seed_defaults("sam") == 1  # nothing left to add
