"""Background mailbox checks every 15 minutes (feature 002 research R6, FR-003)."""

import asyncio
import logging
import os

from sqlmodel import Session, select

from jobhunter.db import get_engine, to_local, utcnow
from jobhunter.models import MailboxSettings, SearchRun, UserAccount
from jobhunter.services import mailbox
from jobhunter.services.search import discovery, runner

DAILY_HOUR = 6

log = logging.getLogger(__name__)
INTERVAL_SECONDS = 15 * 60
FIRST_RUN_DELAY = 60


def run_all_checks() -> None:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(MailboxSettings, UserAccount)
            .join(UserAccount, UserAccount.id == MailboxSettings.user_id)
            .where(MailboxSettings.checking_enabled.is_(True), UserAccount.is_active.is_(True))
        ).all()
        for _settings, user in rows:
            try:
                mailbox.check_mailbox(session, user)
            except Exception:  # noqa: BLE001 - one user's failure must not stop the others
                log.exception("scheduled check failed for user %s", user.id)
        run_due_searches(session)
        queue_daily_claude(session)
        try:
            from jobhunter.services import reminders

            reminders.send_due(session)
        except Exception:  # noqa: BLE001
            log.exception("reminders failed")
        try:
            discovery.run_batch(session)
        except Exception:  # noqa: BLE001
            log.exception("board discovery batch failed")


def queue_daily_claude(session: Session) -> None:
    """After the morning searches, queue Claude Find jobs for the admin (feature 005 FR-010)."""
    import os

    from jobhunter.models import ClaudeJob
    from jobhunter.services.claude import queue as claude_queue

    if os.environ.get("CLAUDE_DAILY", "on").lower() in {"off", "0", "false", "no"}:
        return
    now_local = to_local(utcnow())
    if now_local.hour < DAILY_HOUR:
        return
    for user in session.exec(select(UserAccount).where(UserAccount.is_active.is_(True))).all():
        if not claude_queue.enabled_for(user) or not runner.active_profiles(session, user.id):
            continue
        last = session.exec(
            select(ClaudeJob)
            .where(ClaudeJob.user_id == user.id, ClaudeJob.kind == "find_jobs")
            .order_by(ClaudeJob.created_at.desc())
        ).first()
        if last is not None and to_local(last.created_at).date() == now_local.date():
            continue
        claude_queue.enqueue(session, user, "find_jobs", {})


def run_due_searches(session: Session) -> None:
    """Daily searches at 06:00 app time for users with active target positions (FR-001)."""
    now_local = to_local(utcnow())
    if now_local.hour < DAILY_HOUR:
        return
    for user in session.exec(select(UserAccount).where(UserAccount.is_active.is_(True))).all():
        if not runner.active_profiles(session, user.id):
            continue
        runs = session.exec(
            select(SearchRun)
            .where(SearchRun.user_id == user.id, SearchRun.trigger == "daily")
            .order_by(SearchRun.started_at.desc())
        ).first()
        if runs is not None and to_local(runs.started_at).date() == now_local.date():
            continue
        try:
            runner.run_searches(session, user, trigger="daily")
        except runner.AlreadyRunning:
            continue
        except Exception:  # noqa: BLE001
            log.exception("daily search failed for user %s", user.id)


async def loop() -> None:
    await asyncio.sleep(FIRST_RUN_DELAY)
    while True:
        try:
            await asyncio.to_thread(run_all_checks)
        except Exception:  # noqa: BLE001
            log.exception("mailbox scheduler iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)


def enabled() -> bool:
    return os.environ.get("MAILBOX_SCHEDULER", "on").lower() not in {"0", "off", "false", "no"}
