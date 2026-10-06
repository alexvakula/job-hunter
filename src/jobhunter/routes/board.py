"""Kanban board (FR-019). Cards are moved with SortableJS, which posts to the status route."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.sessions import current_user
from jobhunter.db import get_session, to_local, today_local
from jobhunter.models import ACTIVE_STATUSES, CLOSED_STATUSES, Job, StatusChange, UserAccount
from jobhunter.services.statuses import picker_context
from jobhunter.web import render

router = APIRouter()


def _since_label(days: int) -> str:
    if days <= 0:
        return "today"
    return "1 day" if days == 1 else f"{days} days"


def card_context(db: Session, jobs: list[Job]) -> dict:
    """{'since': {job_id: '3 days'}} based on each job's latest history entry."""
    ids = [j.id for j in jobs]
    since: dict[int, str] = {}
    if ids:
        latest = (
            select(StatusChange.job_id, func.max(StatusChange.effective_at))
            .where(StatusChange.job_id.in_(ids))
            .group_by(StatusChange.job_id)
        )
        today = today_local()
        for job_id, effective in db.exec(latest).all():
            since[job_id] = _since_label((today - to_local(effective).date()).days)
    return {"since": since}


@router.get("/board")
def board(
    request: Request,
    closed: str | None = None,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    show_closed = closed == "1"
    statuses = list(ACTIVE_STATUSES) + (list(CLOSED_STATUSES) if show_closed else [])
    jobs = db.exec(
        repo.scoped(Job, user.id)
        .where(Job.status.in_([s.value for s in statuses]))
        .order_by(Job.updated_at.desc())
    ).all()
    columns = [(s.value, [j for j in jobs if j.status == s.value]) for s in statuses]
    return render(
        request,
        "board/board.html",
        columns=columns,
        show_closed=show_closed,
        closed_values=[s.value for s in CLOSED_STATUSES],
        **card_context(db, jobs),
        **picker_context(),
    )
