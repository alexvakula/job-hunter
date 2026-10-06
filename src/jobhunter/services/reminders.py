"""Daily follow-up reminders and "no reply yet" detection (feature 006 US1, FR-002, FR-003)."""

from sqlmodel import Session, select

from jobhunter.config import public_url
from jobhunter.db import to_local, today_local, utcnow
from jobhunter.models import (
    EmailMessage,
    Job,
    NotificationSettings,
    Status,
    StatusChange,
    UserAccount,
)
from jobhunter.services import stats, telegram

SEND_HOUR = 8


def no_reply(session: Session, user_id: int, days: int) -> list[tuple[Job, int]]:
    """Jobs in `applied` for ≥ days with no later status change and no linked incoming email."""
    out = []
    jobs = session.exec(
        select(Job).where(Job.user_id == user_id, Job.status == Status.APPLIED.value)
    ).all()
    for job in jobs:
        # The latest *recorded* change (a backdated "applied" may predate the creation entry).
        last = session.exec(
            select(StatusChange)
            .where(StatusChange.job_id == job.id)
            .order_by(StatusChange.id.desc())
        ).first()
        if last is None or last.to_status != Status.APPLIED.value:
            continue
        since = last.effective_at
        replied = session.exec(
            select(EmailMessage.id).where(
                EmailMessage.user_id == user_id,
                EmailMessage.job_id == job.id,
                EmailMessage.direction == "in",
                EmailMessage.saved_at >= since,
            )
        ).first()
        if replied is not None:
            continue
        waited = (today_local() - to_local(since).date()).days
        if waited >= days:
            out.append((job, waited))
    out.sort(key=lambda x: -x[1])
    return out


def message_for(session: Session, user: UserAccount, days: int) -> str | None:
    due = stats.due_follow_ups(session, user.id)
    quiet = no_reply(session, user.id, days)
    if not due and not quiet:
        return None
    base = public_url().rstrip("/")
    lines = [f"Job Hunter — {today_local():%a %b %-d}"]
    if due:
        lines.append("")
        lines.append("Follow-ups due:")
        lines += [
            f"• {f.due_date:%b %-d}: {f.description or 'follow up'} — {j.title} at "
            f"{j.company}\n  {base}/jobs/{j.id}"
            for f, j in due[:15]
        ]
    if quiet:
        lines.append("")
        lines.append(f"No reply for {days}+ days:")
        lines += [
            f"• {j.title} at {j.company} (applied {d} days ago)\n  {base}/jobs/{j.id}"
            for j, d in quiet[:15]
        ]
    return "\n".join(lines)


def settings_for(session: Session, user_id: int) -> NotificationSettings:
    return session.get(NotificationSettings, user_id) or NotificationSettings(user_id=user_id)


def send_due(session: Session, sender: telegram.Sender = telegram.send) -> int:
    """Called by the scheduler: at most one message per user per day, after 08:00."""
    now_local = to_local(utcnow())
    if now_local.hour < SEND_HOUR:
        return 0
    sent = 0
    rows = session.exec(
        select(NotificationSettings, UserAccount)
        .join(UserAccount, UserAccount.id == NotificationSettings.user_id)
        .where(
            NotificationSettings.reminders_enabled.is_(True),
            NotificationSettings.telegram_chat_id.is_not(None),
            UserAccount.is_active.is_(True),
        )
    ).all()
    for ns, user in rows:
        if ns.last_sent_on == now_local.date():
            continue
        text = message_for(session, user, ns.stale_days)
        ns.last_sent_on = now_local.date()  # also on "nothing due": checked once a day
        if text is not None:
            result = sender(ns.telegram_chat_id, text)
            ns.last_error = None if result.ok else result.message
            sent += int(result.ok)
        session.add(ns)
        session.commit()
    return sent
