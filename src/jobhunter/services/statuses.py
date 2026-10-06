"""Status changes and the append-only history (research R8, FR-015–FR-018).

`change_status` is the only code that changes `job.status`. History rows are only ever
inserted; there is no update or delete path for them.
"""

from datetime import datetime, timedelta

from sqlmodel import Session, select

from jobhunter.db import local_to_utc, utcnow
from jobhunter.models import ACTIVE_STATUSES, CLOSED_STATUSES, Job, Status, StatusChange

STATUS_LABELS = {
    Status.NEW.value: "New",
    Status.INTERESTED.value: "Interested",
    Status.APPLIED.value: "Applied",
    Status.SCREENING.value: "Screening",
    Status.INTERVIEW.value: "Interview",
    Status.OFFER.value: "Offer",
    Status.ACCEPTED.value: "Accepted",
    Status.REJECTED.value: "Rejected",
    Status.WITHDRAWN.value: "Withdrawn",
    Status.GHOSTED.value: "Ghosted",
}
MAX_FUTURE = timedelta(days=1)


class StatusError(ValueError):
    pass


def parse_status(value: str) -> Status:
    try:
        return Status(value)
    except ValueError as exc:
        raise StatusError("Unknown status.") from exc


def parse_effective(value: str | None) -> datetime | None:
    """`YYYY-MM-DDTHH:MM` (datetime-local input, app time zone) -> aware UTC, or None."""
    if not value or not value.strip():
        return None
    try:
        local = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise StatusError("Enter the date and time as YYYY-MM-DD HH:MM.") from exc
    if local.tzinfo is not None:
        local = local.replace(tzinfo=None)
    return local_to_utc(local)


def change_status(
    session: Session, job: Job, to_status: str, effective_at: datetime | None = None
) -> StatusChange | None:
    """Record a change; returns None (and writes nothing) if the status is unchanged."""
    new = parse_status(to_status)
    now = utcnow()
    effective = effective_at or now
    if effective > now + MAX_FUTURE:
        raise StatusError("The date can't be more than one day in the future.")
    if job.status == new.value:
        return None
    entry = StatusChange(
        job_id=job.id,
        from_status=job.status,
        to_status=new.value,
        effective_at=effective,
        recorded_at=now,
    )
    job.status = new.value
    job.updated_at = now
    session.add(entry)
    session.add(job)
    session.commit()
    session.refresh(job)
    return entry


def timeline(session: Session, job: Job) -> list[StatusChange]:
    return list(
        session.exec(
            select(StatusChange)
            .where(StatusChange.job_id == job.id)
            .order_by(StatusChange.effective_at, StatusChange.id)
        ).all()
    )


def picker_context() -> dict:
    return {
        "status_labels": STATUS_LABELS,
        "active_statuses": [s.value for s in ACTIVE_STATUSES],
        "closed_statuses": [s.value for s in CLOSED_STATUSES],
    }
