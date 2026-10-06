"""Dashboard numbers (research R8, FR-021, FR-022). Always scoped to one user."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from jobhunter.db import to_local, today_local
from jobhunter.models import FollowUp, Job, Status, StatusChange

WEEKS = 12
RESPONSE_STATUSES = {
    Status.SCREENING.value,
    Status.INTERVIEW.value,
    Status.OFFER.value,
    Status.ACCEPTED.value,
    Status.REJECTED.value,
}


@dataclass
class ResponseRate:
    applied: int
    responded: int

    @property
    def percent(self) -> int | None:
        if self.applied == 0:
            return None
        return round(100 * self.responded / self.applied)


def _history(session: Session, user_id: int) -> dict[int, list[StatusChange]]:
    rows = session.exec(
        select(StatusChange)
        .join(Job, Job.id == StatusChange.job_id)
        .where(Job.user_id == user_id)
        .order_by(StatusChange.job_id, StatusChange.effective_at, StatusChange.id)
    ).all()
    by_job: dict[int, list[StatusChange]] = {}
    for row in rows:
        by_job.setdefault(row.job_id, []).append(row)
    return by_job


def _first_applied(entries: list[StatusChange]) -> StatusChange | None:
    return next((e for e in entries if e.to_status == Status.APPLIED.value), None)


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def applications_per_week(session: Session, user_id: int) -> list[tuple[date, int]]:
    """[(monday, count)] for the last 12 ISO weeks, oldest first, in the app time zone."""
    this_week = _week_start(today_local())
    weeks = [this_week - timedelta(weeks=i) for i in range(WEEKS - 1, -1, -1)]
    counts = dict.fromkeys(weeks, 0)
    for entries in _history(session, user_id).values():
        first = _first_applied(entries)
        if first is None:
            continue
        week = _week_start(to_local(first.effective_at).date())
        if week in counts:
            counts[week] += 1
    return [(w, counts[w]) for w in weeks]


def response_rate(session: Session, user_id: int) -> ResponseRate:
    applied = responded = 0
    for entries in _history(session, user_id).values():
        first = _first_applied(entries)
        if first is None:
            continue
        applied += 1
        index = entries.index(first)
        if any(e.to_status in RESPONSE_STATUSES for e in entries[index + 1 :]):
            responded += 1
    return ResponseRate(applied=applied, responded=responded)


def counts_per_status(session: Session, user_id: int) -> dict[str, int]:
    counts = {s.value: 0 for s in Status}
    for status in session.exec(select(Job.status).where(Job.user_id == user_id)).all():
        counts[status] = counts.get(status, 0) + 1
    return counts


def due_follow_ups(session: Session, user_id: int) -> list[tuple[FollowUp, Job]]:
    rows = session.exec(
        select(FollowUp, Job)
        .join(Job, Job.id == FollowUp.job_id)
        .where(
            Job.user_id == user_id,
            FollowUp.done.is_(False),
            FollowUp.due_date <= today_local(),
        )
        .order_by(FollowUp.due_date, FollowUp.id)
    ).all()
    return [(f, j) for f, j in rows]
