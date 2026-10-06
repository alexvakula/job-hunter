"""Sending with a permanent record (feature 002 US2, FR-010–FR-012).

Every email the app sends is saved first (status pending), then updated with the result, and on
success a copy is appended to the job mailbox's Sent folder.
"""

from collections.abc import Callable
from email.message import EmailMessage

from sqlmodel import Session

from jobhunter.models import SenderSettings, UserAccount
from jobhunter.services import mail_store, mailbox, mailer


def send_test(
    session: Session, user: UserAccount, settings: SenderSettings, job_id: int | None = None
) -> mailer.Result:
    if not settings.from_address:
        return mailer.send_test_email(settings, user.username)  # explains what is missing
    message = mailer.build_test_message(settings)
    return send_recorded(
        session,
        user,
        settings,
        message,
        job_id,
        lambda: mailer.send_test_email(settings, user.username, message=message),
    )


def send_application(
    session: Session,
    user: UserAccount,
    settings: SenderSettings,
    message: EmailMessage,
    recipients: list[str],
    job_id: int,
) -> mailer.Result:
    """Feature 004: send an application the user previewed and confirmed (constitution III)."""
    return send_recorded(
        session,
        user,
        settings,
        message,
        job_id,
        lambda: mailer.send_message(settings, user.username, message, recipients),
    )


def send_recorded(
    session: Session,
    user: UserAccount,
    settings: SenderSettings,
    message: EmailMessage,
    job_id: int | None,
    send: Callable[[], mailer.Result],
) -> mailer.Result:
    raw = bytes(message)
    email, _ = mail_store.store(session, user.id, raw, direction="out")
    email.kind, email.send_status, email.job_id = "sent", "pending", job_id
    email.link_method = "manual" if job_id else "none"
    session.add(email)
    session.commit()

    result = send()
    email.send_status = "sent" if result.ok else "failed"
    email.send_error = None if result.ok else result.message
    session.add(email)
    session.commit()
    if result.ok and _has_mailbox(session, user):
        if not mailbox.append_sent_copy(session, user, email, raw):
            result = mailer.Result(True, result.message + " (Could not save a copy in Sent.)")
    return result


def _has_mailbox(session: Session, user: UserAccount) -> bool:
    from jobhunter.models import MailboxSettings

    return session.get(MailboxSettings, user.id) is not None
