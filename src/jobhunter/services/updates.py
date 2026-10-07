"""Telegram messages as things happen: new suggestions, employer emails and finished Claude tasks.

Checked by the scheduler every 15 minutes; one message per user per check, only when something
is new. Nothing is sent at night: updates wait for the morning.
"""

from sqlmodel import Session, func, select

from jobhunter.config import public_url
from jobhunter.db import to_local, utcnow
from jobhunter.models import (
    ClaudeJob,
    EmailMessage,
    Job,
    JobSuggestion,
    NotificationSettings,
    UserAccount,
)
from jobhunter.services import telegram

QUIET_FROM, QUIET_UNTIL = 22, 7  # local hours
MAX_ITEMS = 10
# A successful search shows up as new suggestions; only its failure is worth a message.
SILENT_WHEN_DONE = {"find_jobs", "fit_rank"}
CLAUDE_LABELS = {
    "find_jobs": "Find jobs",
    "fit_rank": "Fit ranking",
    "tailor": "Tailored resume",
    "import": "Resume import",
    "prep": "Interview prep",
}


def _max_id(session: Session, model, user_id: int) -> int:
    return session.exec(select(func.max(model.id)).where(model.user_id == user_id)).one() or 0


def _start_from_now(session: Session, ns: NotificationSettings) -> None:
    ns.last_suggestion_id = _max_id(session, JobSuggestion, ns.user_id)
    ns.last_email_id = _max_id(session, EmailMessage, ns.user_id)
    ns.updates_checked_at = utcnow()


def message_for(session: Session, ns: NotificationSettings) -> str | None:
    """The update text since the stored cursors (advanced in place), or None if nothing is new."""
    uid, base = ns.user_id, public_url().rstrip("/")
    checked_at = utcnow()
    suggestions = session.exec(
        select(JobSuggestion)
        .where(JobSuggestion.user_id == uid, JobSuggestion.id > ns.last_suggestion_id)
        .order_by(JobSuggestion.id)
    ).all()
    emails = session.exec(
        select(EmailMessage, Job)
        .outerjoin(Job, Job.id == EmailMessage.job_id)
        .where(
            EmailMessage.user_id == uid,
            EmailMessage.id > ns.last_email_id,
            EmailMessage.direction == "in",
            EmailMessage.kind == "employer",
        )
        .order_by(EmailMessage.id)
    ).all()
    claude = session.exec(
        select(ClaudeJob)
        .where(
            ClaudeJob.user_id == uid,
            ClaudeJob.finished_at.is_not(None),
            ClaudeJob.finished_at > ns.updates_checked_at,
            ClaudeJob.finished_at <= checked_at,
        )
        .order_by(ClaudeJob.finished_at)
    ).all()
    if suggestions:
        ns.last_suggestion_id = suggestions[-1].id
    if emails:
        ns.last_email_id = emails[-1][0].id
    ns.updates_checked_at = checked_at

    fresh = [s for s in suggestions if s.state == "new"]  # skip ones already handled
    claude = [c for c in claude if c.status == "failed" or c.kind not in SILENT_WHEN_DONE]
    if not (fresh or emails or claude):
        return None

    lines = ["Job Hunter update"]
    if fresh:
        fresh.sort(key=lambda s: (-(s.fit_score or -1), -(s.score or -1), -s.id))
        lines += ["", f"{len(fresh)} new suggestion{'s' if len(fresh) != 1 else ''}:"]
        for s in fresh[:MAX_ITEMS]:
            where = ", ".join(p for p in (s.company, s.location) if p)
            fit = f" [fit {s.fit_score}]" if s.fit_score is not None else ""
            lines.append(f"• {s.title}{f' — {where}' if where else ''}{fit}\n  {s.url}")
        if len(fresh) > MAX_ITEMS:
            lines.append(f"…and {len(fresh) - MAX_ITEMS} more")
        lines.append(f"Review: {base}/suggestions")
    if emails:
        lines += ["", "New emails from employers:"]
        for email, job in emails[:MAX_ITEMS]:
            sender = email.from_name or email.from_addr
            about = f" about {job.title} at {job.company}" if job else ""
            lines.append(f"• {sender}{about}: {email.subject or '(no subject)'}")
            lines.append(f"  {base}/mail/{email.id}")
        if len(emails) > MAX_ITEMS:
            lines.append(f"…and {len(emails) - MAX_ITEMS} more")
    if claude:
        lines += ["", "Claude:"]
        for c in claude[:MAX_ITEMS]:
            label = CLAUDE_LABELS.get(c.kind, c.kind)
            outcome = (
                f"failed — {c.error or 'see details'}"
                if c.status == "failed"
                else c.summary or "done"
            )
            lines.append(f"• {label}: {outcome[:200]}\n  {base}/claude/jobs/{c.id}")
    return "\n".join(lines)


def send_due(session: Session, sender: telegram.Sender = telegram.send) -> int:
    """Called by the scheduler: one message per user with what is new since the last check."""
    hour = to_local(utcnow()).hour
    if hour >= QUIET_FROM or hour < QUIET_UNTIL:
        return 0
    sent = 0
    rows = session.exec(
        select(NotificationSettings)
        .join(UserAccount, UserAccount.id == NotificationSettings.user_id)
        .where(
            NotificationSettings.updates_enabled.is_(True),
            NotificationSettings.telegram_chat_id.is_not(None),
            UserAccount.is_active.is_(True),
        )
    ).all()
    for ns in rows:
        if ns.last_suggestion_id is None or ns.last_email_id is None or not ns.updates_checked_at:
            _start_from_now(session, ns)  # just switched on: no flood of old items
            text = None
        else:
            cursors = (ns.last_suggestion_id, ns.last_email_id, ns.updates_checked_at)
            text = message_for(session, ns)
        if text is not None:
            result = sender(ns.telegram_chat_id, text)
            ns.last_error = None if result.ok else result.message
            sent += int(result.ok)
            if not result.ok:  # try again on the next check
                ns.last_suggestion_id, ns.last_email_id, ns.updates_checked_at = cursors
        session.add(ns)
        session.commit()
    return sent
