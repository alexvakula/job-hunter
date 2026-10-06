"""Context for the job detail page, shared by every route that re-renders it."""

from sqlmodel import Session, select

from jobhunter.models import (
    Contact,
    EmailMessage,
    FollowUp,
    Job,
    Note,
    Source,
    TargetProfile,
    WorkMode,
)
from jobhunter.services import statuses

WORK_MODE_LABELS = {
    WorkMode.UNKNOWN.value: "Unknown",
    WorkMode.ONSITE.value: "On-site",
    WorkMode.HYBRID.value: "Hybrid",
    WorkMode.REMOTE.value: "Remote",
}


def notes_for(db: Session, job: Job) -> list[Note]:
    return list(
        db.exec(
            select(Note)
            .where(Note.job_id == job.id)
            .order_by(Note.created_at.desc(), Note.id.desc())
        ).all()
    )


def contacts_for(db: Session, job: Job) -> list[Contact]:
    return list(db.exec(select(Contact).where(Contact.job_id == job.id).order_by(Contact.id)).all())


def followups_for(db: Session, job: Job) -> list[FollowUp]:
    return list(
        db.exec(
            select(FollowUp)
            .where(FollowUp.job_id == job.id)
            .order_by(FollowUp.done, FollowUp.due_date, FollowUp.id)
        ).all()
    )


def _prep_for(db: Session, job: Job):
    from jobhunter.models import JobPrep

    return db.exec(
        select(JobPrep).where(JobPrep.job_id == job.id, JobPrep.user_id == job.user_id)
    ).first()


def detail_context(db: Session, job: Job, **extra) -> dict:
    context = {
        "job": job,
        "source": db.get(Source, job.source_id),
        "profile": db.get(TargetProfile, job.profile_id) if job.profile_id else None,
        "timeline": statuses.timeline(db, job),
        "work_modes": WORK_MODE_LABELS,
        "notes": notes_for(db, job),
        "contacts": contacts_for(db, job),
        "followups": followups_for(db, job),
        "prep": _prep_for(db, job),
        "job_emails": list(
            db.exec(
                select(EmailMessage)
                .where(EmailMessage.job_id == job.id, EmailMessage.user_id == job.user_id)
                .order_by(EmailMessage.sent_at, EmailMessage.id)
            ).all()
        ),
        **statuses.picker_context(),
    }
    context.update(extra)
    return context
