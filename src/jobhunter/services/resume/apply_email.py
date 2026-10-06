"""Composing and sending an application email (FR-012–FR-014; constitution III).

The preview produces a token = HMAC(secret, exact content). Sending requires the same token for
the same content plus an explicit confirmation, so nothing differs from what the user saw.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from email_validator import EmailNotValidError, validate_email
from sqlmodel import Session, select

from jobhunter.config import get_settings
from jobhunter.models import Contact, DocumentVersion, Job, SenderSettings, Status, UserAccount
from jobhunter.services import outbox, statuses
from jobhunter.services.resume import versions

MAX_ATTACHMENTS_BYTES = 15 * 1024 * 1024
ADVANCE_FROM = {Status.NEW.value, Status.INTERESTED.value}


@dataclass
class Compose:
    to: list[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    attachments: list[str] = field(default_factory=list)  # "<version_id>:<kind>"

    def canonical(self, user_id: int, job_id: int) -> str:
        return json.dumps(
            {
                "u": user_id,
                "j": job_id,
                "to": self.to,
                "s": self.subject,
                "b": self.body,
                "a": self.attachments,
            },
            sort_keys=True,
        )


def defaults(session: Session, job: Job, name: str, letter: str) -> Compose:
    contacts = session.exec(select(Contact).where(Contact.job_id == job.id)).all()
    latest = session.exec(
        select(DocumentVersion)
        .where(DocumentVersion.job_id == job.id)
        .order_by(DocumentVersion.number.desc())
    ).first()
    attachments = [f"{latest.id}:resume.pdf", f"{latest.id}:letter.pdf"] if latest else []
    return Compose(
        to=[c.email for c in contacts if c.email][:3],
        subject=f"Application: {job.title} — {name}".strip(" —"),
        body=letter
        or f"Hello,\n\nPlease find attached my application for the {job.title} "
        f"position.\n\nKind regards,\n{name}",
        attachments=attachments,
    )


def from_form(form) -> tuple[Compose, dict[str, str]]:
    errors: dict[str, str] = {}
    to = []
    for raw in str(form.get("to") or "").replace(";", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            to.append(validate_email(raw, check_deliverability=False).normalized)
        except EmailNotValidError:
            errors["to"] = f"“{raw}” is not a valid email address."
    if not to and "to" not in errors:
        errors["to"] = "Add at least one recipient."
    subject = str(form.get("subject") or "").strip()
    if not subject:
        errors["subject"] = "Add a subject."
    body = str(form.get("body") or "").replace("\r\n", "\n").strip()
    if not body:
        errors["body"] = "Write a message."
    return Compose(
        to=to,
        subject=subject,
        body=body,
        attachments=sorted(str(a) for a in form.getlist("attachments")),
    ), errors


def token(compose: Compose, user_id: int, job_id: int) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, compose.canonical(user_id, job_id).encode(), hashlib.sha256).hexdigest()


def resolve_attachments(
    session: Session, user_id: int, job_id: int, refs: list[str]
) -> tuple[list[tuple[str, str, bytes]], str | None]:
    files, total = [], 0
    for ref in refs:
        version_id, _, kind = ref.partition(":")
        if kind not in versions.FILES or not version_id.isdigit():
            return [], "Unknown attachment."
        v = session.get(DocumentVersion, int(version_id))
        if v is None or v.user_id != user_id or v.job_id != job_id:
            return [], "Unknown attachment."
        path = versions.path_for(v, kind)
        if path is None or not path.is_file():
            return [], "An attachment file is missing; generate the documents again."
        data = path.read_bytes()
        total += len(data)
        files.append(
            (versions.download_name(v, kind), versions.MEDIA[kind.rsplit(".", 1)[1]], data)
        )
    if total > MAX_ATTACHMENTS_BYTES:
        return [], "Attachments are larger than 15 MB."
    return files, None


def build_message(
    settings: SenderSettings, compose: Compose, files: list[tuple[str, str, bytes]]
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.display_name, settings.from_address))
    msg["To"] = ", ".join(compose.to)
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    msg["Subject"] = compose.subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=settings.from_address.rpartition("@")[2] or None)
    body = compose.body
    if settings.signature and settings.signature not in body:
        body += "\n\n" + settings.signature
    msg.set_content(body)
    for name, media, data in files:
        main, sub = media.split("/", 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg


def send(
    session: Session, user: UserAccount, settings: SenderSettings, job: Job, compose: Compose, files
) -> tuple[bool, str]:
    message = build_message(settings, compose, files)
    recipients = list(
        dict.fromkeys(compose.to + ([settings.from_address] if settings.bcc_self else []))
    )
    result = outbox.send_application(session, user, settings, message, recipients, job.id)
    if not result.ok:
        return False, result.message
    if job.status in ADVANCE_FROM:
        statuses.change_status(session, job, Status.APPLIED.value)
    return True, f"Application sent to {', '.join(compose.to)}."
