import smtplib
import socket
import ssl

import pytest

from jobhunter.models import SenderSettings
from jobhunter.services import mailer

SECRET = "super-secret-mail-pw"


def _settings(**kw):
    values = {
        "user_id": 1,
        "from_address": "sam@example.org",
        "display_name": "Sam Rivera",
        "reply_to": "sam@example.org",
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_username": "sam@example.org",
        "signature": "-- \nAlex",
        "bcc_self": False,
    }
    values.update(kw)
    return SenderSettings(**values)


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_on: str | None = None
    exc: Exception | None = None

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeouts = host, port, [timeout]
        self.calls: list[str] = []
        self.sent = None
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, step):
        self.calls.append(step)
        if FakeSMTP.fail_on == step:
            raise FakeSMTP.exc

    @property
    def sock(self):
        return self

    def settimeout(self, value):
        self.timeouts.append(value)

    def ehlo(self):
        self._maybe_fail("ehlo")

    def starttls(self, context=None):
        assert isinstance(context, ssl.SSLContext)
        self._maybe_fail("starttls")

    def login(self, user, password):
        self.login_args = (user, password)
        self._maybe_fail("login")

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self._maybe_fail("send")
        self.sent = (msg, from_addr, to_addrs)

    def quit(self):
        self.calls.append("quit")

    def close(self):
        self.calls.append("close")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances.clear()
    FakeSMTP.fail_on = None
    FakeSMTP.exc = None
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_PASSWORD_SAM", SECRET)
    return FakeSMTP


def test_sends_to_own_address_with_headers():
    result = mailer.send_test_email(_settings(), "sam")
    assert result.ok, result.message
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.org", 587)
    assert smtp.calls[:5] == ["connect", "ehlo", "starttls", "ehlo", "login"]
    assert smtp.login_args == ("sam@example.org", SECRET)
    msg, from_addr, to_addrs = smtp.sent
    assert msg["From"] == "Sam Rivera <sam@example.org>"
    assert msg["To"] == "sam@example.org"
    assert msg["Reply-To"] == "sam@example.org"
    assert "Bcc" not in msg
    assert to_addrs == ["sam@example.org"]
    assert "-- \nAlex" in msg.get_content()


def test_bcc_self_adds_envelope_recipient_without_header():
    mailer.send_test_email(_settings(bcc_self=True, from_address="sam@example.org"), "sam")
    msg, _, to_addrs = FakeSMTP.instances[0].sent
    assert to_addrs == ["sam@example.org", "sam@example.org"] or to_addrs == ["sam@example.org"]
    assert "Bcc" not in msg


def test_missing_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD_SAM")
    result = mailer.send_test_email(_settings(), "sam")
    assert not result.ok and "SMTP_PASSWORD_SAM" in result.message
    assert FakeSMTP.instances == []


def test_missing_from_address():
    result = mailer.send_test_email(_settings(from_address=""), "sam")
    assert not result.ok and "from-address" in result.message


@pytest.mark.parametrize(
    ("step", "exc", "words"),
    [
        ("login", smtplib.SMTPAuthenticationError(535, b"bad creds"), "rejected the username"),
        ("connect", ConnectionRefusedError(), "refused"),
        ("connect", socket.gaierror(-2, "Name or service not known"), "could not be found"),
        ("starttls", ssl.SSLError("bad cert"), "secure connection"),
        ("connect", TimeoutError(), "did not respond in time"),
        (
            "send",
            smtplib.SMTPSenderRefused(553, b"not owner", "sam@example.org"),
            "refused the sender",
        ),
        ("send", smtplib.SMTPRecipientsRefused({"x": (550, b"no")}), "refused the recipient"),
    ],
)
def test_errors_are_plain_language(step, exc, words):
    FakeSMTP.fail_on, FakeSMTP.exc = step, exc
    result = mailer.send_test_email(_settings(), "sam")
    assert not result.ok
    assert words in result.message
    assert SECRET not in result.message


def test_overall_deadline_is_25_seconds(monkeypatch):
    clock = iter([0.0, 0.0, 10.0, 20.0, 26.0, 26.0, 26.0, 26.0])
    monkeypatch.setattr(mailer.time, "monotonic", lambda: next(clock, 30.0))
    result = mailer.send_test_email(_settings(), "sam")
    assert not result.ok and "did not respond in time" in result.message
    smtp = FakeSMTP.instances[0]
    assert smtp.timeouts[0] <= 25
    assert all(t <= 25 for t in smtp.timeouts)
    assert "send" not in smtp.calls


def test_password_never_logged(caplog):
    FakeSMTP.fail_on, FakeSMTP.exc = "login", smtplib.SMTPAuthenticationError(535, SECRET.encode())
    with caplog.at_level("DEBUG"):
        result = mailer.send_test_email(_settings(), "sam")
    assert SECRET not in caplog.text and SECRET not in result.message
