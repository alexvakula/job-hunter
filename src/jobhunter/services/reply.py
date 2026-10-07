"""Replying to an email from the job mailbox (constitution III).

Same rules as an application: the user sees the full preview (recipients, subject, body with the
quoted original) and confirms; the preview token binds the confirmation to that exact content.
The reply is threaded with In-Reply-To / References and recorded like every sent email.
"""

import hashlib
import hmac
import json
import re
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, formatdate, make_msgid

from sqlmodel import Session

from jobhunter.config import get_settings
from jobhunter.db import to_local
from jobhunter.models import (
    EmailDraft,
    EmailMessage,
    Job,
    SenderSettings,
    Status,
    UserAccount,
)
from jobhunter.services import drafts, mailer, outbox
from jobhunter.services.resume.apply_email import Compose

QUOTE_LIMIT = 8000
_RE = re.compile(r"^\s*(re|aw|sv)\s*:", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\[[^\]\n]{2,80}\]")


# Ready-made replies: a template to start from by hand, what Claude should write, and the status
# the job can move to once the reply is sent (only from the listed earlier statuses).
INTENTS = {
    "continue": {
        "label": "Continue the interview process",
        "status": Status.INTERVIEW.value,
        "from": {"new", "interested", "applied", "screening"},
        "claude": "Confirm the candidate is still interested in the role and glad to continue "
        "with the interview process or next step. Answer scheduling questions with the "
        "candidate's instructions, or a placeholder such as [your availability].",
        "template": "{greeting}\n\nThank you for getting back to me. I'm still very interested "
        "in the {role} and would be glad to continue with the next step.\n\n"
        "[your availability]\n\nBest regards,\n{name}",
    },
    "withdraw": {
        "label": "Withdraw my application",
        "status": Status.WITHDRAWN.value,
        "from": {"new", "interested", "applied", "screening", "interview", "offer"},
        "claude": "Politely withdraw the candidate's application from consideration. Thank them "
        "for their time, keep it brief and warm, give no reason unless the candidate's "
        "instructions give one, and leave the door open for future opportunities.",
        "template": "{greeting}\n\nThank you for your time and for considering me for the "
        "{role}. After careful thought, I have decided to withdraw my application.\n\n"
        "I appreciate the opportunity and wish you and the team all the best.\n\n"
        "Best regards,\n{name}",
    },
}


def intent_of(value) -> str | None:
    value = str(value or "")
    return value if value in INTENTS else None


def template(email: EmailMessage, job: Job | None, intent: str, name: str) -> str:
    first = (email.from_name or "").split(" ")[0].strip(",")
    return INTENTS[intent]["template"].format(
        greeting=f"Hi {first}," if first else "Hello,",
        role=f"{job.title} role" if job else "role",
        name=name,
    )


def status_after(intent: str | None, job: Job | None) -> str | None:
    """The status the job may move to after sending this kind of reply, if any."""
    if intent is None or job is None or job.status not in INTENTS[intent]["from"]:
        return None
    return INTENTS[intent]["status"]


def can_reply(email: EmailMessage) -> bool:
    return email.direction == "in" and email.kind != "alert" and bool(email.from_addr)


def defaults(email: EmailMessage, subject: str | None = None, body: str = "") -> Compose:
    original = email.subject or ""
    return Compose(
        to=[email.reply_to or email.from_addr],
        subject=subject or (original if _RE.match(original) else f"Re: {original}".strip()),
        body=body,
    )


def quote(email: EmailMessage) -> str:
    when = to_local(email.sent_at or email.saved_at)
    who = f"{email.from_name} <{email.from_addr}>" if email.from_name else email.from_addr
    text = (email.body_text or "").strip()[:QUOTE_LIMIT]
    quoted = "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
    return f"On {when:%a, %b %-d, %Y at %H:%M}, {who} wrote:\n{quoted}"


def full_body(settings: SenderSettings, compose: Compose, email: EmailMessage) -> str:
    body = compose.body
    if settings.signature and settings.signature not in body:
        body += "\n\n" + settings.signature
    return f"{body}\n\n{quote(email)}"


def placeholders(compose: Compose) -> list[str]:
    """Bracketed gaps like [your availability] that Claude left for the user to fill in."""
    return PLACEHOLDER.findall(compose.body)


def token(compose: Compose, user_id: int, email_id: int) -> str:
    canonical = json.dumps(
        {
            "u": user_id,
            "reply": email_id,
            "to": compose.to,
            "s": compose.subject,
            "b": compose.body,
        },
        sort_keys=True,
    )
    key = get_settings().session_secret.encode()
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def build_message(settings: SenderSettings, compose: Compose, email: EmailMessage) -> MimeMessage:
    msg = MimeMessage()
    msg["From"] = formataddr((settings.display_name, settings.from_address))
    msg["To"] = ", ".join(compose.to)
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    msg["Subject"] = compose.subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=settings.from_address.rpartition("@")[2] or None)
    if email.message_id:
        msg["In-Reply-To"] = email.message_id
        msg["References"] = " ".join([*(email.references or [])[-10:], email.message_id])
    msg.set_content(full_body(settings, compose, email))
    return msg


def send(
    session: Session,
    user: UserAccount,
    settings: SenderSettings,
    email: EmailMessage,
    compose: Compose,
) -> tuple[bool, str]:
    message = build_message(settings, compose, email)
    recipients = list(
        dict.fromkeys(compose.to + ([settings.from_address] if settings.bcc_self else []))
    )
    result = outbox.send_recorded(
        session,
        user,
        settings,
        message,
        email.job_id,
        lambda: mailer.send_message(settings, user.username, message, recipients),
    )
    if not result.ok:
        return False, result.message
    discard_draft(session, user.id, email.id)
    return True, f"Reply sent to {', '.join(compose.to)}."


# --- drafts --------------------------------------------------------------------------------


def draft_for(session: Session, user_id: int, email_id: int) -> EmailDraft | None:
    return drafts.find(session, user_id, email_id=email_id)


def save_draft(
    session: Session,
    user_id: int,
    email_id: int,
    compose: Compose,
    intent: str | None,
    by_claude: bool = False,
) -> EmailDraft:
    return drafts.save(
        session, user_id, compose, email_id=email_id, intent=intent, by_claude=by_claude
    )


def discard_draft(session: Session, user_id: int, email_id: int) -> None:
    drafts.discard(session, user_id, email_id=email_id)
