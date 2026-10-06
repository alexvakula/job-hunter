"""The "send test email" action (research R9, FR-029–FR-032, constitution III and IV).

The only email this feature ever sends: triggered by the user's click, addressed only to the
user's own from-address (plus a BCC to self), using that user's settings and the password
from `SMTP_PASSWORD_<USERNAME>`. The whole exchange must finish within 25 seconds.
"""

import logging
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from jobhunter.config import public_url, smtp_password_env_name, smtp_password_for
from jobhunter.models import SenderSettings

log = logging.getLogger(__name__)
DEADLINE_SECONDS = 25.0


@dataclass
class Result:
    ok: bool
    message: str


class _Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        left = self.end - time.monotonic()
        if left <= 0:
            raise TimeoutError
        return left


def _message(settings: SenderSettings) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.display_name, settings.from_address))
    msg["To"] = settings.from_address
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    msg["Subject"] = "Job Hunter test email"
    msg["Date"] = formatdate(localtime=False)
    domain = settings.from_address.rpartition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    body = (
        f"This is a test email from Job Hunter ({public_url()}).\n\n"
        "If you can read this, your sender settings work: application emails will be sent "
        "from this address, and only after you preview and confirm each one."
    )
    if settings.signature:
        body += "\n\n" + settings.signature
    msg.set_content(body)
    return msg


def _explain(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "The mail server rejected the username or password."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "The mail server refused the sender (from) address for this login."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the recipient address."
    if isinstance(exc, smtplib.SMTPNotSupportedError | ssl.SSLError):
        return "A secure connection (STARTTLS) to the mail server could not be set up."
    if isinstance(exc, TimeoutError | socket.timeout):
        return "The mail server did not respond in time."
    if isinstance(exc, socket.gaierror):
        return "The mail server's address could not be found. Check the host name."
    if isinstance(exc, ConnectionRefusedError):
        return "The mail server refused the connection. Check the host and port."
    if isinstance(exc, smtplib.SMTPResponseException):
        return f"The mail server returned error {exc.smtp_code}."
    if isinstance(exc, smtplib.SMTPException | OSError):
        return "Could not talk to the mail server."
    return "Sending failed for an unexpected reason."


def build_test_message(settings: SenderSettings) -> EmailMessage:
    return _message(settings)


def _missing(settings: SenderSettings, username: str) -> Result | None:
    if not settings.from_address:
        return Result(False, "Set your from-address in Settings → Sender email first.")
    if smtp_password_for(username) is None:
        name = smtp_password_env_name(username)
        return Result(
            False,
            f"The mail password isn't configured. Ask the admin to add {name} to the "
            "server's .env file and restart the app.",
        )
    return None


def send_message(
    settings: SenderSettings, username: str, message: EmailMessage, recipients: list[str]
) -> Result:
    """Send one message to exactly `recipients` within the overall deadline."""
    missing = _missing(settings, username)
    if missing is not None:
        return missing
    password = smtp_password_for(username)
    deadline = _Deadline(DEADLINE_SECONDS)
    smtp = None
    try:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=deadline.remaining())

        def step(fn, *args, **kwargs):
            smtp.sock.settimeout(deadline.remaining())
            return fn(*args, **kwargs)

        step(smtp.ehlo)
        step(smtp.starttls, context=ssl.create_default_context())
        step(smtp.ehlo)
        step(smtp.login, settings.smtp_username or settings.from_address, password)
        step(smtp.send_message, message, from_addr=settings.from_address, to_addrs=recipients)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a readable message
        log.warning("email for %s failed: %s", username, type(exc).__name__)
        return Result(False, _explain(exc))
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                smtp.close()
    log.info("email sent for %s", username)
    return Result(True, "Sent.")


def send_test_email(
    settings: SenderSettings, username: str, message: EmailMessage | None = None
) -> Result:
    if not settings.from_address:
        return Result(False, "Set your from-address and save before sending a test.")
    missing = _missing(settings, username)
    if missing is not None:
        return missing
    recipients = [settings.from_address]  # only ever the user's own address (FR-031)
    result = send_message(settings, username, message or _message(settings), recipients)
    if result.ok:
        return Result(True, f"Test email sent to {settings.from_address}. Check your inbox.")
    return result
