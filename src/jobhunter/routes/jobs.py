"""Job capture, list, detail, edit and delete (contracts/http-routes.md "Jobs")."""

from dataclasses import asdict, fields
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import exists, func
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_session, today_local
from jobhunter.models import FollowUp, Job, Source, Status, TargetProfile, UserAccount, WorkMode
from jobhunter.routes.detail import WORK_MODE_LABELS, detail_context
from jobhunter.services import extract, profiles, statuses
from jobhunter.services import jobs as job_service
from jobhunter.services.fetch import FETCHED, Fetcher, get_fetcher, match_source
from jobhunter.web import is_htmx, render

router = APIRouter()

PAGE_SIZE = 50
SORT_COLUMNS = {
    "title": Job.title,
    "company": Job.company,
    "status": Job.status,
    "location": Job.location,
    "work_mode": Job.work_mode,
    "date_found": Job.date_found,
    "updated": Job.updated_at,
}


async def _job_input(request: Request) -> job_service.JobInput:
    form = await request.form()
    names = {f.name for f in fields(job_service.JobInput)}
    return job_service.JobInput(**{k: str(form.get(k) or "") for k in names if k in form})


def _choices(db: Session, user: UserAccount, selected_source_id: int | None = None) -> dict:
    sources = db.exec(select(Source).order_by(Source.name)).all()
    sources = [s for s in sources if s.enabled or s.id == selected_source_id]
    profiles = db.exec(
        repo.scoped(TargetProfile, user.id)
        .where(TargetProfile.is_archived.is_(False))
        .order_by(TargetProfile.name)
    ).all()
    return {"sources": sources, "profiles": profiles, "work_modes": WORK_MODE_LABELS}


def _draft_from(values: dict) -> dict:
    """Template-friendly dict of form values."""
    return {k: ("" if v is None else v) for k, v in values.items()}


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _filters(request: Request) -> dict:
    qp = request.query_params
    valid_status = {s.value for s in Status}
    return {
        "status": [s for s in qp.getlist("status") if s in valid_status],
        "company": (qp.get("company") or "").strip(),
        "source": _int(qp.get("source")),
        "work_mode": qp.get("work_mode") if qp.get("work_mode") in set(WorkMode) else None,
        "profile": _int(qp.get("profile")),
        "found_from": _date(qp.get("found_from")),
        "found_to": _date(qp.get("found_to")),
        "followup_due": qp.get("followup_due") == "1",
        "q": (qp.get("q") or "").strip(),
        "sort": qp.get("sort") if qp.get("sort") in SORT_COLUMNS else "date_found",
        "dir": "asc" if qp.get("dir") == "asc" else "desc",
        "page": max(_int(qp.get("page")) or 1, 1),
    }


def _filtered_query(user_id: int, f: dict):
    stmt = repo.scoped(Job, user_id)
    if f["status"]:
        stmt = stmt.where(Job.status.in_(f["status"]))
    if f["company"]:
        stmt = stmt.where(func.lower(Job.company).contains(f["company"].lower(), autoescape=True))
    if f["source"] is not None:
        stmt = stmt.where(Job.source_id == f["source"])
    if f["work_mode"]:
        stmt = stmt.where(Job.work_mode == f["work_mode"])
    if f["profile"] is not None:
        stmt = stmt.where(Job.profile_id == f["profile"])
    if f["found_from"]:
        stmt = stmt.where(Job.date_found >= f["found_from"])
    if f["found_to"]:
        stmt = stmt.where(Job.date_found <= f["found_to"])
    if f["followup_due"]:
        stmt = stmt.where(
            exists().where(
                FollowUp.job_id == Job.id,
                FollowUp.done.is_(False),
                FollowUp.due_date <= today_local(),
            )
        )
    if f["q"]:
        needle = f["q"].lower()
        stmt = stmt.where(
            func.lower(Job.title).contains(needle, autoescape=True)
            | func.lower(Job.company).contains(needle, autoescape=True)
            | func.lower(Job.description).contains(needle, autoescape=True)
        )
    return stmt


def _page_url(f: dict, **changes) -> str:
    params = {**f, **changes}
    pairs = [("status", s) for s in params["status"]]
    for key in (
        "company",
        "source",
        "work_mode",
        "profile",
        "found_from",
        "found_to",
        "q",
        "sort",
        "dir",
        "page",
    ):
        value = params[key]
        if value not in (None, "", False):
            pairs.append((key, str(value)))
    if params["followup_due"]:
        pairs.append(("followup_due", "1"))
    return "/jobs?" + urlencode(pairs)


@router.get("/jobs")
def list_jobs(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    f = _filters(request)
    base = _filtered_query(user.id, f)
    total = db.exec(select(func.count()).select_from(base.subquery())).one()
    column = SORT_COLUMNS[f["sort"]]
    order = column.asc() if f["dir"] == "asc" else column.desc()
    jobs = db.exec(
        base.order_by(order, Job.id.desc()).offset((f["page"] - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    context = {
        "jobs": jobs,
        "total": total,
        "f": f,
        "pages": pages,
        "page_url": lambda **kw: _page_url(f, **kw),
        "sources": {s.id: s.name for s in db.exec(select(Source).order_by(Source.name)).all()},
        "profiles": db.exec(repo.scoped(TargetProfile, user.id).order_by(TargetProfile.name)).all(),
        "work_modes": WORK_MODE_LABELS,
        "all_statuses": [s.value for s in Status],
    }
    if is_htmx(request) and request.headers.get("HX-Target") == "job-rows":
        return render(request, "jobs/_rows.html", **context)
    return render(request, "jobs/list.html", **context)


@router.get("/jobs/new")
def new_job(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    return render(
        request,
        "jobs/new.html",
        draft=None,
        default_profile_id=profiles.default_profile_id(db, user.id),
        **_choices(db, user),
    )


@router.post("/jobs/prefill", dependencies=[Depends(csrf_protect)])
async def prefill(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    fetcher: Fetcher = Depends(get_fetcher),
):
    form = await request.form()
    url = str(form.get("url") or "").strip()
    text = str(form.get("text") or "")

    draft = extract.JobDraft()
    messages: list[tuple[str, str]] = []
    source = job_service.manual_source(db)
    if url:
        source = match_source(db, url)
        result = fetcher.fetch(url, source)
        if result.status == FETCHED:
            draft = extract.from_html(result.html, url)
            messages.append(("flash", f"Details downloaded from {source.name}. Check them below."))
        else:
            messages.append(("warn", result.message))
    if text.strip():
        from_text = extract.from_text(text)
        # Pasted text wins for the description; page data wins for structured fields.
        for name, value in asdict(from_text).items():
            if (
                name == "description"
                or not getattr(draft, name)
                or (name == "work_mode" and draft.work_mode == WorkMode.UNKNOWN.value)
            ):
                setattr(draft, name, value)

    values = _draft_from(asdict(draft))
    values.update(url=url, source_id=source.id, profile_id=profiles.default_profile_id(db, user.id))
    dupes = None
    if url or (draft.title and draft.company):
        key = job_service.company_title_key(draft.company or "", draft.title or "")
        dupes = job_service.find_duplicates(db, user.id, job_service.normalize_url(url), key)
    return render(
        request,
        "jobs/new.html",
        draft=values,
        messages=messages,
        dupes=dupes,
        show_text=bool(url) and not text.strip() and draft.title is None,
        **_choices(db, user, source.id),
    )


@router.post("/jobs", dependencies=[Depends(csrf_protect)])
async def create_job(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    data = await _job_input(request)
    form = await request.form()
    confirm = form.get("confirm_possible_duplicate") == "1"
    validated = job_service.validate(db, user.id, data)
    draft = {**asdict(data), "source_id": validated.values.get("source_id")}
    if validated.errors:
        return render(
            request,
            "jobs/new.html",
            status_code=422,
            draft=draft,
            errors=validated.errors,
            **_choices(db, user),
        )
    try:
        job = job_service.create_job(db, user.id, validated.values, confirm)
    except job_service.DuplicateUrl as exc:
        return render(request, "jobs/duplicate.html", status_code=409, existing=exc.existing)
    except job_service.PossibleDuplicate as exc:
        dupes = job_service.Duplicates(possible=exc.matches)
        return render(
            request,
            "jobs/new.html",
            draft=draft,
            dupes=dupes,
            confirm_needed=True,
            **_choices(db, user),
        )
    _mark_suggestion_added(db, user, str(form.get("suggestion_id") or ""), job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


def _mark_suggestion_added(db: Session, user: UserAccount, raw_id: str, job: Job) -> None:
    from jobhunter.models import JobSuggestion

    if not raw_id.isdigit():
        return
    suggestion = db.get(JobSuggestion, int(raw_id))
    if suggestion is None or suggestion.user_id != user.id:
        return
    suggestion.state, suggestion.job_id = "added", job.id
    db.add(suggestion)
    db.commit()


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    return render(request, "jobs/detail.html", **detail_context(db, job))


@router.get("/jobs/{job_id}/edit")
def edit_job_form(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    draft = _draft_from(job.model_dump())
    return render(
        request, "jobs/edit.html", job=job, draft=draft, **_choices(db, user, job.source_id)
    )


@router.post("/jobs/{job_id}/edit", dependencies=[Depends(csrf_protect)])
async def edit_job(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    data = await _job_input(request)
    validated = job_service.validate(db, user.id, data)
    if validated.errors:
        return render(
            request,
            "jobs/edit.html",
            status_code=422,
            job=job,
            draft=asdict(data),
            errors=validated.errors,
            **_choices(db, user, job.source_id),
        )
    try:
        job_service.update_job(db, job, validated.values)
    except job_service.DuplicateUrl as exc:
        db.rollback()
        return render(request, "jobs/duplicate.html", status_code=409, existing=exc.existing)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/jobs/{job_id}/delete", dependencies=[Depends(csrf_protect)])
async def delete_job(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    form = await request.form()
    if form.get("confirm") != "yes":
        return render(
            request,
            "jobs/detail.html",
            status_code=400,
            **detail_context(db, job, delete_error=True),
        )
    job_service.delete_job(db, job)
    return RedirectResponse("/jobs", status_code=303)


@router.post("/jobs/{job_id}/status", dependencies=[Depends(csrf_protect)])
async def change_job_status(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    form = await request.form()
    target = request.headers.get("HX-Target", "") if is_htmx(request) else ""
    error = None
    try:
        effective = statuses.parse_effective(str(form.get("effective_at") or ""))
        statuses.change_status(db, job, str(form.get("status") or ""), effective)
    except statuses.StatusError as exc:
        error = str(exc)
    code = 422 if error else 200

    if target.startswith("card-"):
        from jobhunter.routes.board import card_context

        return render(
            request, "board/_card.html", status_code=code, job=job, **card_context(db, [job])
        )
    if target == "status-section":
        return render(
            request,
            "jobs/_timeline.html",
            status_code=code,
            job=job,
            timeline=statuses.timeline(db, job),
            status_error=error,
            **statuses.picker_context(),
        )
    if error:
        return render(
            request,
            "jobs/detail.html",
            status_code=code,
            **detail_context(db, job, status_error=error),
        )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)
