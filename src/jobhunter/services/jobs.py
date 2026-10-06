"""Creating, editing and deleting jobs (FR-005–FR-014).

`create_job` is the single entry point for every way a job enters the system, so the
duplicate rules always apply (FR-014).
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy import delete
from sqlmodel import Session, select

from jobhunter.db import today_local, utcnow
from jobhunter.models import (
    Contact,
    Currency,
    FollowUp,
    Job,
    Note,
    SalaryPeriod,
    Source,
    Status,
    StatusChange,
    TargetProfile,
    WorkMode,
)
from jobhunter.services.dedupe import Duplicates, company_title_key, find_duplicates, normalize_url

MAX_TITLE = 200


@dataclass
class JobInput:
    title: str = ""
    company: str = ""
    location: str = ""
    work_mode: str = WorkMode.UNKNOWN.value
    salary_text: str = ""
    salary_min: str = ""
    salary_max: str = ""
    salary_currency: str = ""
    salary_period: str = ""
    url: str = ""
    source_id: str = ""
    description: str = ""
    profile_id: str = ""


@dataclass
class Validated:
    values: dict = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class DuplicateUrl(Exception):
    def __init__(self, existing: Job):
        self.existing = existing


class PossibleDuplicate(Exception):
    def __init__(self, matches: list[Job]):
        self.matches = matches


def _int_or_none(raw: str, name: str, errors: dict) -> int | None:
    raw = (raw or "").replace(",", "").strip()
    if not raw:
        return None
    try:
        value = int(float(raw))
    except ValueError:
        errors[name] = "Must be a number."
        return None
    if value < 0:
        errors[name] = "Must not be negative."
    return value


def manual_source(session: Session) -> Source:
    return session.exec(select(Source).where(Source.type == "manual")).one()


def validate(session: Session, user_id: int, data: JobInput) -> Validated:
    v = Validated()
    errors = v.errors
    title = data.title.strip()
    company = data.company.strip()
    if not title:
        errors["title"] = "Title is required."
    elif len(title) > MAX_TITLE:
        errors["title"] = f"Title must be at most {MAX_TITLE} characters."
    if not company:
        errors["company"] = "Company is required."
    elif len(company) > MAX_TITLE:
        errors["company"] = f"Company must be at most {MAX_TITLE} characters."

    url = data.url.strip()
    if url and (urlsplit(url).scheme not in {"http", "https"} or normalize_url(url) is None):
        errors["url"] = "Enter a full http(s) link."

    work_mode = data.work_mode if data.work_mode in set(WorkMode) else WorkMode.UNKNOWN.value

    salary_min = _int_or_none(data.salary_min, "salary_min", errors)
    salary_max = _int_or_none(data.salary_max, "salary_max", errors)
    currency = data.salary_currency or None
    period = data.salary_period or None
    if currency is not None and currency not in set(Currency):
        errors["salary_currency"] = "Choose CAD or USD."
    if period is not None and period not in set(SalaryPeriod):
        errors["salary_period"] = "Choose per year or per hour."
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        errors["salary_max"] = "Maximum must not be less than minimum."
    if salary_min is not None or salary_max is not None:
        if currency is None:
            errors["salary_currency"] = "Currency is required when an amount is given."
        if period is None:
            errors["salary_period"] = "Period is required when an amount is given."

    source = None
    if data.source_id.strip():
        try:
            source = session.get(Source, int(data.source_id))
        except ValueError:
            source = None
        if source is None:
            errors["source_id"] = "Unknown source."
    if source is None:
        source = manual_source(session)

    profile_id = None
    if data.profile_id.strip():
        try:
            profile = session.get(TargetProfile, int(data.profile_id))
        except ValueError:
            profile = None
        if profile is None or profile.user_id != user_id:
            errors["profile_id"] = "Unknown profile."
        else:
            profile_id = profile.id

    v.values = {
        "title": title,
        "company": company,
        "location": data.location.strip() or None,
        "work_mode": work_mode,
        "salary_text": data.salary_text.strip() or None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": currency,
        "salary_period": period,
        "url": url or None,
        "url_norm": normalize_url(url),
        "company_title_key": company_title_key(company, title),
        "source_id": source.id,
        "description": data.description.strip(),
        "profile_id": profile_id,
    }
    return v


def check_duplicates(
    session: Session, user_id: int, values: dict, exclude_job_id: int | None = None
) -> Duplicates:
    return find_duplicates(
        session, user_id, values["url_norm"], values["company_title_key"], exclude_job_id
    )


def create_job(session: Session, user_id: int, values: dict, confirm_possible: bool) -> Job:
    """Save the job and its first history row, or raise DuplicateUrl / PossibleDuplicate."""
    dupes = check_duplicates(session, user_id, values)
    if dupes.url_match is not None:
        raise DuplicateUrl(dupes.url_match)
    if dupes.possible and not confirm_possible:
        raise PossibleDuplicate(dupes.possible)
    now = utcnow()
    job = Job(user_id=user_id, date_found=today_local(), status=Status.NEW.value, **values)
    session.add(job)
    session.flush()
    session.add(
        StatusChange(
            job_id=job.id,
            from_status=None,
            to_status=Status.NEW.value,
            effective_at=now,
            recorded_at=now,
        )
    )
    session.commit()
    session.refresh(job)
    return job


def update_job(session: Session, job: Job, values: dict) -> Job:
    """Edit fields (never status). Raises DuplicateUrl if the new URL belongs to another job."""
    dupes = check_duplicates(session, job.user_id, values, exclude_job_id=job.id)
    if dupes.url_match is not None:
        raise DuplicateUrl(dupes.url_match)
    for key, value in values.items():
        setattr(job, key, value)
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def delete_job(session: Session, job: Job) -> None:
    # Explicit child deletes (in addition to ON DELETE CASCADE) keep this independent of
    # whether the connection enforces foreign keys.
    for model in (StatusChange, Note, Contact, FollowUp):
        session.exec(delete(model).where(model.job_id == job.id))
    # Emails and suggestions are kept, unlinked (feature 002 FR-017).
    from sqlalchemy import update

    from jobhunter.models import EmailMessage, JobSuggestion

    session.exec(
        update(EmailMessage)
        .where(EmailMessage.job_id == job.id)
        .values(job_id=None, link_method="none", kind="other")
    )
    session.exec(update(JobSuggestion).where(JobSuggestion.job_id == job.id).values(job_id=None))
    session.delete(job)
    session.commit()
