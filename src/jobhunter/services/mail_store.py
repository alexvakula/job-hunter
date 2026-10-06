"""Parsing and storing emails (feature 002 research R2, R3; FR-005, FR-006, FR-008).

Raw messages and attachments live as files under `<data dir>/uploads/emails/<user_id>/`; the
database keeps headers, text, sanitised HTML and file references. Parsing never raises.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage as StdEmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

import nh3
from sqlalchemy import update
from sqlmodel import Session, select

from jobhunter.models import EmailAttachment, EmailMessage, JobSuggestion
from jobhunter.services.extract import html_to_text
from jobhunter.services.resumes import sanitize_name, uploads_dir

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_SUBJECT = 1000
_ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
_ID_RE = re.compile(r"<([^<>\s]+)>")


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class ParsedEmail:
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    from_addr: str = ""
    from_name: str = ""
    reply_to: str | None = None
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    subject: str = ""
    sent_at: datetime | None = None
    body_text: str = ""
    body_html: str | None = None
    attachments: list[ParsedAttachment] = field(default_factory=list)


def _ids(value: str | None) -> list[str]:
    if not value:
        return []
    found = _ID_RE.findall(str(value))
    return found or [str(value).strip()]


def _addresses(value) -> list[tuple[str, str]]:
    if not value:
        return []
    return [(n, a.lower()) for n, a in getaddresses([str(value)]) if a and "@" in a]


def _header(msg: StdEmailMessage, name: str) -> str | None:
    try:
        value = msg.get(name)
    except Exception:  # noqa: BLE001 - malformed headers must not break parsing
        return None
    return str(value) if value is not None else None


def _text_of(part) -> str:
    try:
        return part.get_content()
    except Exception:  # noqa: BLE001
        payload = part.get_payload(decode=True) or b""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def parse_email(raw: bytes) -> ParsedEmail:
    parsed = ParsedEmail()
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:  # noqa: BLE001
        parsed.body_text = raw.decode("utf-8", errors="replace")
        return parsed

    ids = _ids(_header(msg, "Message-ID"))
    parsed.message_id = ids[0] if ids else None
    reply = _ids(_header(msg, "In-Reply-To"))
    parsed.in_reply_to = reply[0] if reply else None
    parsed.references = _ids(_header(msg, "References"))
    sender = _addresses(_header(msg, "From"))
    if sender:
        parsed.from_name, parsed.from_addr = sender[0]
    reply_to = _addresses(_header(msg, "Reply-To"))
    parsed.reply_to = reply_to[0][1] if reply_to else None
    parsed.to_addrs = [a for _, a in _addresses(_header(msg, "To"))]
    parsed.cc_addrs = [a for _, a in _addresses(_header(msg, "Cc"))]
    parsed.subject = (_header(msg, "Subject") or "").strip()[:MAX_SUBJECT]
    try:
        date = parsedate_to_datetime(_header(msg, "Date") or "")
        parsed.sent_at = date if date.tzinfo else date.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        parsed.sent_at = None

    text_parts, html_parts = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        ctype = part.get_content_type()
        if disposition == "attachment" or (disposition == "inline" and part.get_filename()):
            data = part.get_payload(decode=True) or b""
            parsed.attachments.append(
                ParsedAttachment(sanitize_name(part.get_filename() or "attachment"), ctype, data)
            )
        elif ctype == "text/plain":
            text_parts.append(_text_of(part))
        elif ctype == "text/html":
            html_parts.append(_text_of(part))
    parsed.body_html = "\n".join(html_parts) or None
    parsed.body_text = "\n".join(text_parts).strip() or (
        html_to_text(parsed.body_html) if parsed.body_html else ""
    )
    return parsed


def dedupe_key(parsed: ParsedEmail) -> str:
    if parsed.message_id:
        return "mid:" + parsed.message_id.lower()
    basis = "|".join(
        [parsed.from_addr, str(parsed.sent_at or ""), parsed.subject, parsed.body_text[:4096]]
    )
    return "sha:" + hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()


def sanitize_html(html: str | None) -> str | None:
    """Safe subset of the email's HTML: no scripts, styles, images, forms or frames (FR-008)."""
    if not html:
        return None
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
        clean_content_tags={"script", "style"},
    )


def emails_dir(user_id: int) -> Path:
    return uploads_dir().parent / "emails" / str(user_id)


def raw_path(email: EmailMessage) -> Path | None:
    if not email.raw_storage_name:
        return None
    return emails_dir(email.user_id) / email.raw_storage_name


def attachment_path(email: EmailMessage, attachment: EmailAttachment) -> Path | None:
    if not attachment.storage_name:
        return None
    return emails_dir(email.user_id) / "att" / attachment.storage_name


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def find_existing(session: Session, user_id: int, key: str) -> EmailMessage | None:
    return session.exec(
        select(EmailMessage).where(EmailMessage.user_id == user_id, EmailMessage.dedupe_key == key)
    ).first()


def store(
    session: Session,
    user_id: int,
    raw: bytes,
    *,
    direction: str = "in",
    folder: str | None = None,
    folder_uid: int | None = None,
    parsed: ParsedEmail | None = None,
) -> tuple[EmailMessage, bool]:
    """Save an email once per user. Returns (email, created)."""
    parsed = parsed or parse_email(raw)
    key = dedupe_key(parsed)
    existing = find_existing(session, user_id, key)
    if existing is not None:
        return existing, False

    raw_name = f"{uuid.uuid4().hex}.eml"
    _write(emails_dir(user_id) / raw_name, raw)
    email = EmailMessage(
        user_id=user_id,
        direction=direction,
        kind="sent" if direction == "out" else "other",
        dedupe_key=key,
        message_id=parsed.message_id,
        in_reply_to=parsed.in_reply_to,
        references=parsed.references,
        from_addr=parsed.from_addr,
        from_name=parsed.from_name,
        reply_to=parsed.reply_to,
        to_addrs=parsed.to_addrs,
        cc_addrs=parsed.cc_addrs,
        subject=parsed.subject,
        sent_at=parsed.sent_at,
        body_text=parsed.body_text,
        body_html=sanitize_html(parsed.body_html),
        raw_storage_name=raw_name,
        size_bytes=len(raw),
        folder=folder,
        folder_uid=folder_uid,
    )
    session.add(email)
    session.flush()

    total = 0
    for att in parsed.attachments:
        total += len(att.data)
        row = EmailAttachment(
            email_id=email.id,
            filename=att.filename,
            content_type=att.content_type,
            size_bytes=len(att.data),
        )
        if total > MAX_ATTACHMENT_BYTES:
            row.skipped = True
        else:
            row.storage_name = uuid.uuid4().hex
            _write(emails_dir(user_id) / "att" / row.storage_name, att.data)
        session.add(row)
    session.commit()
    session.refresh(email)
    return email, True


def attachments_of(session: Session, email: EmailMessage) -> list[EmailAttachment]:
    return list(
        session.exec(
            select(EmailAttachment)
            .where(EmailAttachment.email_id == email.id)
            .order_by(EmailAttachment.id)
        ).all()
    )


def delete_email(session: Session, email: EmailMessage) -> None:
    """Delete the app's copy only (FR-009); the mailbox is never touched."""
    files = [raw_path(email)] + [attachment_path(email, a) for a in attachments_of(session, email)]
    session.exec(
        update(JobSuggestion).where(JobSuggestion.email_id == email.id).values(email_id=None)
    )
    for att in attachments_of(session, email):
        session.delete(att)
    session.delete(email)
    session.commit()
    for path in files:
        if path is not None:
            path.unlink(missing_ok=True)
