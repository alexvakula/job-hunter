"""The Claude job queue: persisted, one job at a time, failures visible (FR-002, FR-005)."""

import asyncio
import logging
import threading

from sqlmodel import Session, select

from jobhunter.db import get_engine, utcnow
from jobhunter.models import ClaudeJob, UserAccount
from jobhunter.services.claude import cli

log = logging.getLogger(__name__)
_run_lock = threading.Lock()
POLL_SECONDS = 3


class NotAllowed(Exception):
    pass


def enabled_for(user: UserAccount | None) -> bool:
    return bool(user and user.is_active and cli.token_configured(user))


def enqueue(
    session: Session, user: UserAccount, kind: str, payload: dict | None = None
) -> ClaudeJob:
    if not enabled_for(user):
        raise NotAllowed
    payload = payload or {}
    existing = session.exec(
        select(ClaudeJob).where(
            ClaudeJob.user_id == user.id,
            ClaudeJob.kind == kind,
            ClaudeJob.status.in_(["queued", "running"]),
        )
    ).all()
    for job in existing:
        if job.payload == payload:
            return job
    job = ClaudeJob(user_id=user.id, kind=kind, payload=payload)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_interrupted(session: Session) -> None:
    for job in session.exec(select(ClaudeJob).where(ClaudeJob.status == "running")).all():
        job.status, job.error, job.finished_at = "failed", "Interrupted by a restart.", utcnow()
        session.add(job)
    session.commit()


def process_next(session: Session) -> ClaudeJob | None:
    """Run the oldest queued job, if any. Only one runs at a time in the whole app."""
    from jobhunter.services.claude import tasks

    if not _run_lock.acquire(blocking=False):
        return None
    try:
        job = session.exec(
            select(ClaudeJob)
            .where(ClaudeJob.status == "queued")
            .order_by(ClaudeJob.created_at, ClaudeJob.id)
        ).first()
        if job is None:
            return None
        job.status, job.started_at = "running", utcnow()
        job.model = cli.model_for(job.kind) if job.kind in cli.DEFAULT_MODELS else None
        session.add(job)
        session.commit()
        try:
            user = session.get(UserAccount, job.user_id)
            if not enabled_for(user):
                raise cli.ClaudeError(cli.TOKEN_HELP)
            from jobhunter.services.claude.prep import prep_job
            from jobhunter.services.claude.reply import draft_reply

            handlers = {**tasks.HANDLERS, "prep": prep_job, "reply": draft_reply}
            with cli.account(user):  # the user's own token, never another user's
                outcome = handlers[job.kind](session, user, job)
            job.status, job.summary = "done", outcome.summary
            job.result, job.cost_usd = outcome.result, outcome.cost_usd
        except cli.ClaudeError as exc:
            session.rollback()
            job.status, job.error = "failed", str(exc)
        except Exception:  # noqa: BLE001 - never let one job stop the worker
            session.rollback()
            log.exception("claude job %s failed", job.id)
            job.status, job.error = "failed", "Unexpected error while processing Claude's answer."
        job.finished_at = utcnow()
        session.add(job)
        session.commit()
        return job
    finally:
        _run_lock.release()


async def worker() -> None:
    with Session(get_engine()) as session:
        mark_interrupted(session)
    while True:
        try:
            await asyncio.to_thread(_drain)
        except Exception:  # noqa: BLE001
            log.exception("claude worker iteration failed")
        await asyncio.sleep(POLL_SECONDS)


def _drain() -> None:
    with Session(get_engine()) as session:
        while process_next(session) is not None:
            pass
