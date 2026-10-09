"""Admin pages: family accounts and the shared source list (contracts/http-routes.md "Admin")."""

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.passwords import PolicyError
from jobhunter.auth.sessions import csrf_protect, require_admin, set_flash
from jobhunter.db import get_session
from jobhunter.models import Job, Source, SourceType, TargetProfile, UserAccount
from jobhunter.services import accounts
from jobhunter.web import render

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

SOURCE_TYPE_LABELS = {
    SourceType.MANUAL.value: "Manual",
    SourceType.JOB_BOARD.value: "Job board",
    SourceType.ATS.value: "Applicant tracking system (ATS)",
    SourceType.ALERT_EMAIL.value: "Job-alert email",
    SourceType.CAREERS_PAGE.value: "Company careers page",
    SourceType.ASSISTANT.value: "Assistant search",
    SourceType.COMPANY_DIRECTORY.value: "Company directory",
}
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _get_user(db: Session, user_id: int) -> UserAccount:
    user = db.get(UserAccount, user_id)
    if user is None:
        raise repo.not_found()
    return user


def _get_source(db: Session, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise repo.not_found()
    return source


# --- users ---------------------------------------------------------------------------------


def _users_page(request: Request, db: Session, status_code: int = 200, **extra):
    return render(
        request, "admin/users.html", status_code=status_code, users=accounts.list_users(db), **extra
    )


@router.get("/users")
def users(request: Request, db: Session = Depends(get_session)):
    return _users_page(request, db)


@router.get("/users/{user_id}/logins")
def user_logins(user_id: int, request: Request, db: Session = Depends(get_session)):
    from jobhunter.services import login_history

    person = db.get(UserAccount, user_id)
    if person is None:
        raise repo.not_found()
    return render(
        request,
        "auth/logins.html",
        person=person,
        events=login_history.for_user(db, user_id),
        own=False,
        attribution=login_history.ATTRIBUTION,
    )


@router.get("/users/new")
def new_user_form(request: Request):
    return render(request, "admin/user_form.html", form={})


@router.post("/users/new", dependencies=[Depends(csrf_protect)])
async def create_user(request: Request, db: Session = Depends(get_session)):
    form = await request.form()
    values = {k: str(form.get(k) or "") for k in ("username", "display_name", "temp_password")}
    try:
        accounts.create_user(
            db, values["username"], values["display_name"], values["temp_password"]
        )
    except PolicyError as exc:
        values.pop("temp_password")
        return render(request, "admin/user_form.html", status_code=422, form=values, error=str(exc))
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(csrf_protect)])
async def reset_password(user_id: int, request: Request, db: Session = Depends(get_session)):
    user = _get_user(db, user_id)
    form = await request.form()
    try:
        accounts.reset_password(db, user, str(form.get("temp_password") or ""))
    except PolicyError as exc:
        return _users_page(request, db, 422, error=f"{user.username}: {exc}")
    response = RedirectResponse("/admin/users", status_code=303)
    set_flash(response, "password_reset")
    return response


@router.post("/users/{user_id}/disable", dependencies=[Depends(csrf_protect)])
def disable_user(user_id: int, request: Request, db: Session = Depends(get_session)):
    user = _get_user(db, user_id)
    try:
        accounts.set_active(db, user, False)
    except accounts.AccountError as exc:
        return _users_page(request, db, 422, error=str(exc))
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/enable", dependencies=[Depends(csrf_protect)])
def enable_user(user_id: int, db: Session = Depends(get_session)):
    accounts.set_active(db, _get_user(db, user_id), True)
    return RedirectResponse("/admin/users", status_code=303)


# --- sources -------------------------------------------------------------------------------


def _parse_domains(raw: str) -> tuple[list[str], str | None]:
    domains: list[str] = []
    for part in re.split(r"[,\s]+", raw or ""):
        if not part:
            continue
        host = (urlsplit(part if "//" in part else "//" + part).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if not _HOST_RE.match(host):
            return [], f"'{part}' is not a valid site address (e.g. jobs.example.com)."
        if host not in domains:
            domains.append(host)
    return domains, None


def _source_values(db: Session, form, source_id: int | None) -> tuple[dict, dict]:
    errors: dict[str, str] = {}
    name = str(form.get("name") or "").strip()
    type_ = str(form.get("type") or "")
    if not name:
        errors["name"] = "Name is required."
    else:
        clash = db.exec(select(Source).where(Source.name == name)).first()
        if clash is not None and clash.id != source_id:
            errors["name"] = "Another source already has this name."
    if type_ not in SOURCE_TYPE_LABELS:
        errors["type"] = "Choose a type."
    domains, domain_error = _parse_domains(str(form.get("domains") or ""))
    if domain_error:
        errors["domains"] = domain_error
    values = {
        "name": name,
        "type": type_,
        "domains": domains,
        "fetch_allowed": form.get("fetch_allowed") == "1",
        "enabled": form.get("enabled") == "1",
        "alert_sender": form.get("alert_sender") == "1",
    }
    return values, errors


def _source_form(
    request: Request, source: Source | None, values: dict, status_code: int = 200, **extra
):
    return render(
        request,
        "admin/source_form.html",
        status_code=status_code,
        source=source,
        values=values,
        types=SOURCE_TYPE_LABELS,
        **extra,
    )


@router.get("/sources")
def sources(request: Request, db: Session = Depends(get_session)):
    rows = db.exec(select(Source).order_by(Source.name)).all()
    return render(request, "admin/sources.html", sources=rows, types=SOURCE_TYPE_LABELS)


@router.get("/sources/new")
def new_source_form(request: Request):
    return _source_form(
        request,
        None,
        {
            "type": SourceType.CAREERS_PAGE.value,
            "domains": [],
            "enabled": True,
            "fetch_allowed": False,
            "alert_sender": False,
        },
    )


@router.post("/sources/new", dependencies=[Depends(csrf_protect)])
async def create_source(request: Request, db: Session = Depends(get_session)):
    values, errors = _source_values(db, await request.form(), None)
    if errors:
        return _source_form(request, None, values, 422, errors=errors)
    db.add(Source(**values))
    db.commit()
    return RedirectResponse("/admin/sources", status_code=303)


@router.get("/sources/{source_id}")
def edit_source_form(source_id: int, request: Request, db: Session = Depends(get_session)):
    source = _get_source(db, source_id)
    return _source_form(request, source, source.model_dump())


@router.post("/sources/{source_id}", dependencies=[Depends(csrf_protect)])
async def edit_source(source_id: int, request: Request, db: Session = Depends(get_session)):
    source = _get_source(db, source_id)
    values, errors = _source_values(db, await request.form(), source.id)
    if source.is_system:
        values["type"] = source.type  # Manual stays Manual
        errors.pop("type", None)
    if errors:
        return _source_form(request, source, values, 422, errors=errors)
    for key, value in values.items():
        setattr(source, key, value)
    db.add(source)
    db.commit()
    return RedirectResponse("/admin/sources", status_code=303)


@router.post("/sources/{source_id}/delete", dependencies=[Depends(csrf_protect)])
async def delete_source(source_id: int, request: Request, db: Session = Depends(get_session)):
    source = _get_source(db, source_id)
    form = await request.form()
    if source.is_system:
        return _source_form(
            request, source, source.model_dump(), 422, delete_error="Manual can't be deleted."
        )
    in_use = db.exec(select(func.count()).select_from(Job).where(Job.source_id == source.id)).one()
    if in_use:
        return _source_form(
            request,
            source,
            source.model_dump(),
            422,
            delete_error=f"{in_use} job(s) use this source. Disable it instead.",
        )
    if form.get("confirm") != "yes":
        return _source_form(
            request, source, source.model_dump(), 400, delete_error='Tick "Yes, delete" to confirm.'
        )
    # Profiles store selected sources as a JSON list; drop this id from all of them.
    for profile in db.exec(select(TargetProfile)).all():
        if source.id in profile.source_ids:
            profile.source_ids = [i for i in profile.source_ids if i != source.id]
            db.add(profile)
    db.delete(source)
    db.commit()
    return RedirectResponse("/admin/sources", status_code=303)
