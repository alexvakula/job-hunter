"""Checking a user's job mailbox (feature 002 US1, US3, US4, US5; FR-003–FR-006, FR-023).

`check_mailbox` fetches new mail from the Inbox, Sent and the app's folders, saves each email
once, classifies and links it, creates suggestions for alerts and, when filing is on, moves it into
`Job Alerts/<site>` or `Employers/<Company> - <Title>`. Checks for one user never overlap.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session, select

from jobhunter.config import smtp_password_env_name, smtp_password_for
from jobhunter.db import utcnow
from jobhunter.models import (
    EmailMessage,
    Job,
    MailboxFolderState,
    MailboxSettings,
    Source,
    UserAccount,
)
from jobhunter.services import alerts, imap_client, mail_link, mail_store

log = logging.getLogger(__name__)
ALERTS_ROOT = "Job Alerts"
EMPLOYERS_ROOT = "Employers"
SENT = "Sent"
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()

Connector = Callable[[str, int, str, str], imap_client.Mailbox]


@dataclass
class CheckResult:
    ok: bool
    message: str
    new: int = 0
    alerts: int = 0
    suggestions: int = 0
    linked: int = 0


def _lock_for(user_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(user_id, threading.Lock())


def _clean_folder_part(value: str, delimiter: str) -> str:
    value = value.replace(delimiter, " ").replace("/", " ").replace(".", " ")
    value = re.sub(r"[\x00-\x1f\x7f*%\"\\]", "", value)
    return " ".join(value.split())[:80] or "Unknown"


def target_folder(session: Session, email: EmailMessage, delimiter: str) -> str | None:
    if email.kind == "alert" and email.source_id:
        source = session.get(Source, email.source_id)
        name = _clean_folder_part(source.name if source else "Other", delimiter)
        return f"{ALERTS_ROOT}{delimiter}{name}"
    if email.job_id and email.direction == "in":
        job = session.get(Job, email.job_id)
        if job is not None:
            name = _clean_folder_part(f"{job.company} - {job.title}", delimiter)
            return f"{EMPLOYERS_ROOT}{delimiter}{name}"
    return None


def _folders_to_read(mailbox: imap_client.Mailbox) -> list[str]:
    d = mailbox.delimiter
    wanted = []
    for folder in mailbox.list_folders():
        if folder.upper() == "INBOX" or folder == SENT:
            wanted.append(folder)
        elif folder.startswith((ALERTS_ROOT + d, EMPLOYERS_ROOT + d)):
            wanted.append(folder)
    wanted.sort(key=lambda f: (f.upper() != "INBOX", f))
    return wanted


def classify_and_link(
    session: Session, email: EmailMessage, own_address: str | None = None
) -> tuple[bool, int]:
    """Returns (is_alert, suggestions_created)."""
    if own_address and email.from_addr == own_address.lower():
        # Sent by the user from their mail client: a sent email, linked by its recipient.
        email.direction, email.kind = "out", "sent"
        if email.to_addrs and email.link_method != "manual":
            probe = EmailMessage(user_id=email.user_id, dedupe_key="", from_addr=email.to_addrs[0])
            found = mail_link.find_link(session, email.user_id, probe)
            email.job_id, email.candidates = found.job_id, found.candidates
            email.link_method = found.method if found.job_id else "none"
        session.add(email)
        session.commit()
        return False, 0
    if email.direction == "out":
        email.kind = "sent"
        return False, 0
    source = mail_link.alert_source(session, email.from_addr)
    if source is not None:
        email.kind = "alert"
        email.source_id = source.id
        session.add(email)
        session.commit()
        return True, alerts.create_suggestions(session, email, source)
    mail_link.apply_link(email, mail_link.find_link(session, email.user_id, email))
    session.add(email)
    session.commit()
    return False, 0


def _file(session: Session, mailbox: imap_client.Mailbox, email: EmailMessage) -> None:
    dest = target_folder(session, email, mailbox.delimiter)
    if dest is None or dest == email.folder or email.moved_by_user or email.folder_uid is None:
        return
    mailbox.move(email.folder_uid, dest)
    email.folder, email.folder_uid = dest, None  # new UID learned on the next check
    session.add(email)
    session.commit()


def _state(session: Session, user_id: int, folder: str) -> MailboxFolderState:
    state = session.exec(
        select(MailboxFolderState).where(
            MailboxFolderState.user_id == user_id, MailboxFolderState.folder == folder
        )
    ).first()
    if state is None:
        state = MailboxFolderState(user_id=user_id, folder=folder)
    return state


def _process_folder(session, user, settings, mailbox, folder, result: CheckResult) -> None:
    uidvalidity = mailbox.select(folder)
    state = _state(session, user.id, folder)
    if state.uidvalidity != uidvalidity:
        state.uidvalidity, state.last_uid = uidvalidity, 0
    for uid in mailbox.uids_after(state.last_uid):
        raw = mailbox.fetch(uid)
        if raw:
            email, created = mail_store.store(session, user.id, raw, folder=folder, folder_uid=uid)
            if created:
                result.new += 1
                is_alert, made = classify_and_link(session, email, settings.address)
                result.alerts += int(is_alert)
                result.suggestions += made
                result.linked += int(email.job_id is not None)
                if settings.filing_enabled:
                    _file(session, mailbox, email)
            elif email.folder == folder:
                email.folder_uid = uid  # after the app moved it here
            else:
                email.folder, email.folder_uid = folder, uid
                email.moved_by_user = email.direction == "in"
            session.add(email)
        state.last_uid = max(state.last_uid, uid)
        session.add(state)
        session.commit()


def check_mailbox(
    session: Session, user: UserAccount, connect: Connector | None = None
) -> CheckResult:
    connect = connect or imap_client.connect
    settings = session.get(MailboxSettings, user.id)
    if settings is None or not settings.address:
        return CheckResult(False, "Set up your job mailbox in Settings first.")
    lock = _lock_for(user.id)
    if not lock.acquire(blocking=False):
        return CheckResult(False, "A check is already running; try again in a moment.")
    result = CheckResult(True, "")
    try:
        password = smtp_password_for(user.username)
        if password is None:
            raise imap_client.ImapError(
                f"The mailbox password isn't configured. Ask the admin to add "
                f"{smtp_password_env_name(user.username)} to the server's .env file."
            )
        mailbox = connect(settings.imap_host, settings.imap_port, settings.address, password)
        try:
            for folder in _folders_to_read(mailbox):
                _process_folder(session, user, settings, mailbox, folder, result)
        finally:
            mailbox.close()
        result.message = (
            f"{result.new} new email{'s' if result.new != 1 else ''}, "
            f"{result.alerts} alert{'s' if result.alerts != 1 else ''}, "
            f"{result.suggestions} suggested job{'s' if result.suggestions != 1 else ''}, "
            f"{result.linked} linked to jobs."
        )
        settings.last_error = None
        settings.last_result = result.message
    except Exception as exc:  # noqa: BLE001 - every failure becomes a readable status
        session.rollback()
        result.ok = False
        result.message = _explain(exc)
        settings = session.get(MailboxSettings, user.id)
        settings.last_error = result.message
        log.warning("mailbox check for %s failed: %s", user.username, type(exc).__name__)
    finally:
        settings.last_check_at = utcnow()
        session.add(settings)
        session.commit()
        lock.release()
    return result


def _explain(exc: BaseException) -> str:
    import socket
    import ssl

    if isinstance(exc, imap_client.ImapError):
        text = str(exc)
        if text == "login rejected":
            return "The mail server rejected the mailbox address or password."
        return text if text.startswith("The ") else "The mail server returned an error."
    if isinstance(exc, socket.gaierror):
        return "The mail server's address could not be found."
    if isinstance(exc, TimeoutError | socket.timeout):
        return "The mail server did not respond in time."
    if isinstance(exc, ssl.SSLError):
        return "A secure connection to the mail server could not be set up."
    if isinstance(exc, OSError):
        return "Could not connect to the mail server."
    return "Checking the mailbox failed unexpectedly."


def refile(
    session: Session,
    user: UserAccount,
    email: EmailMessage,
    connect: Connector | None = None,
) -> None:
    """Move an email after the user re-linked it (best effort; FR-023)."""
    connect = connect or imap_client.connect
    settings = session.get(MailboxSettings, user.id)
    password = smtp_password_for(user.username)
    if (
        settings is None
        or not settings.filing_enabled
        or password is None
        or email.direction != "in"
        or email.moved_by_user
        or not email.folder
        or email.folder_uid is None
    ):
        return
    try:
        mailbox = connect(settings.imap_host, settings.imap_port, settings.address, password)
    except Exception:  # noqa: BLE001
        return
    try:
        mailbox.select(email.folder)
        if not mailbox.has_uid(email.folder_uid):
            email.moved_by_user = True
            session.add(email)
            session.commit()
            return
        _file(session, mailbox, email)
    except Exception:  # noqa: BLE001
        log.warning("refile failed for email %s", email.id)
    finally:
        mailbox.close()


def append_sent_copy(
    session: Session,
    user: UserAccount,
    email: EmailMessage,
    raw: bytes,
    connect: Connector | None = None,
) -> bool:
    connect = connect or imap_client.connect
    settings = session.get(MailboxSettings, user.id)
    password = smtp_password_for(user.username)
    if settings is None or password is None:
        return False
    try:
        mailbox = connect(settings.imap_host, settings.imap_port, settings.address, password)
        try:
            mailbox.append(SENT, raw)
        finally:
            mailbox.close()
    except Exception:  # noqa: BLE001
        log.warning("could not append sent copy for %s", user.username)
        return False
    email.folder, email.folder_uid = SENT, None
    session.add(email)
    session.commit()
    return True
