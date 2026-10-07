"""Unsent emails kept under Mail → Drafts: replies (per email) and applications (per job)."""

from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import EmailDraft
from jobhunter.services.resume.apply_email import Compose


def find(
    session: Session, user_id: int, *, email_id: int | None = None, job_id: int | None = None
) -> EmailDraft | None:
    stmt = select(EmailDraft).where(EmailDraft.user_id == user_id)
    if email_id is not None:
        stmt = stmt.where(EmailDraft.kind == "reply", EmailDraft.email_id == email_id)
    else:
        stmt = stmt.where(EmailDraft.kind == "application", EmailDraft.job_id == job_id)
    return session.exec(stmt).first()


def save(
    session: Session,
    user_id: int,
    compose: Compose,
    *,
    email_id: int | None = None,
    job_id: int | None = None,
    intent: str | None = None,
    by_claude: bool = False,
) -> EmailDraft:
    draft = find(session, user_id, email_id=email_id, job_id=job_id) or EmailDraft(
        user_id=user_id,
        kind="reply" if email_id is not None else "application",
        email_id=email_id,
        job_id=job_id if email_id is None else None,
    )
    draft.to_addrs, draft.subject, draft.body = compose.to, compose.subject, compose.body
    draft.attachments = list(compose.attachments)
    draft.intent, draft.by_claude, draft.updated_at = intent, by_claude, utcnow()
    session.add(draft)
    session.commit()
    return draft


def discard(
    session: Session, user_id: int, *, email_id: int | None = None, job_id: int | None = None
) -> None:
    draft = find(session, user_id, email_id=email_id, job_id=job_id)
    if draft is not None:
        session.delete(draft)
        session.commit()


def as_compose(draft: EmailDraft, fallback: Compose) -> Compose:
    return Compose(
        to=draft.to_addrs or fallback.to,
        subject=draft.subject or fallback.subject,
        body=draft.body,
        attachments=list(draft.attachments or []),
    )
