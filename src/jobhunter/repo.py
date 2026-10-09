"""Owner-scoped data access (research R5, FR-002c).

Every read of an owned table goes through here so that it carries the current user's id.
Rows owned by someone else are indistinguishable from missing rows (404).
"""

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, select

from jobhunter.models import (
    ClaudeJob,
    DocumentVersion,
    EmailDraft,
    EmailMessage,
    Job,
    JobSuggestion,
    ResumeFile,
    SearchRun,
    TailoredResume,
    TargetProfile,
)

# Tables that carry user_id directly.
OWNED_TOP_LEVEL = (
    Job,
    TargetProfile,
    ResumeFile,
    EmailMessage,
    JobSuggestion,
    SearchRun,
    TailoredResume,
    DocumentVersion,
    ClaudeJob,
    EmailDraft,
)


def not_found() -> HTTPException:
    return HTTPException(status_code=404)


def get_owned[T: SQLModel](session: Session, model: type[T], obj_id: int, user_id: int) -> T:
    if model not in OWNED_TOP_LEVEL:
        raise TypeError(f"{model.__name__} is not a top-level owned table")
    obj = session.get(model, obj_id)
    if obj is None or obj.user_id != user_id:
        raise not_found()
    return obj


def get_job_child[T: SQLModel](
    session: Session, model: type[T], job_id: int, child_id: int, user_id: int
) -> T:
    """Fetch a note/contact/follow-up/status change through its owning job."""
    job = get_owned(session, Job, job_id, user_id)
    child = session.get(model, child_id)
    if child is None or child.job_id != job.id:
        raise not_found()
    return child


def scoped[T: SQLModel](model: type[T], user_id: int):
    """`select(model)` already filtered to one user's rows."""
    if model not in OWNED_TOP_LEVEL:
        raise TypeError(f"{model.__name__} is not a top-level owned table")
    return select(model).where(model.user_id == user_id)
