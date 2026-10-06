"""Dashboard (FR-021, FR-022)."""

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from jobhunter.auth.sessions import current_user
from jobhunter.db import get_session
from jobhunter.models import ACTIVE_STATUSES, CLOSED_STATUSES, UserAccount
from jobhunter.services import stats
from jobhunter.web import render

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    weeks = stats.applications_per_week(db, user.id)
    peak = max((n for _, n in weeks), default=0)
    return render(
        request,
        "dashboard.html",
        weeks=weeks,
        peak=peak,
        rate=stats.response_rate(db, user.id),
        counts=stats.counts_per_status(db, user.id),
        due=stats.due_follow_ups(db, user.id),
        status_order=[s.value for s in ACTIVE_STATUSES + CLOSED_STATUSES],
    )
