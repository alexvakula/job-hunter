"""Notes, contacts and follow-ups on a job (FR-023–FR-025).

Everything is fetched through the owning job (repo.get_job_child), so another user's ids
are "not found". HTMX requests get the refreshed section; plain posts redirect back.
"""

from datetime import date
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_session, utcnow
from jobhunter.models import Contact, FollowUp, Job, Note, UserAccount
from jobhunter.routes.detail import contacts_for, detail_context, followups_for, notes_for
from jobhunter.web import is_htmx, render

router = APIRouter(dependencies=[Depends(csrf_protect)])

MAX_NOTE = 20_000
MAX_FOLLOWUP = 200
SECTIONS = {
    "notes": ("jobs/_notes.html", notes_for),
    "contacts": ("jobs/_contacts.html", contacts_for),
    "followups": ("jobs/_followups.html", followups_for),
}


def _respond(
    request: Request,
    db: Session,
    job: Job,
    section: str,
    errors: dict | None = None,
    form: dict | None = None,
):
    status_code = 422 if errors else 200
    extra = {f"{section}_errors": errors or {}, f"{section}_form": form or {}}
    if is_htmx(request):
        template, loader = SECTIONS[section]
        return render(
            request,
            template,
            status_code=status_code,
            job=job,
            **{section: loader(db, job)},
            **extra,
        )
    if errors:
        return render(
            request, "jobs/detail.html", status_code=status_code, **detail_context(db, job, **extra)
        )
    return RedirectResponse(f"/jobs/{job.id}#{section}", status_code=303)


async def _form(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(v).strip() for k, v in form.items() if k != "csrf_token"}


# --- notes ---------------------------------------------------------------------------------


def _note_errors(body: str) -> dict:
    if not body:
        return {"body": "Write something first."}
    if len(body) > MAX_NOTE:
        return {"body": f"Notes can be at most {MAX_NOTE:,} characters."}
    return {}


@router.post("/jobs/{job_id}/notes")
async def add_note(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    form = await _form(request)
    body = form.get("body", "")
    errors = _note_errors(body)
    if not errors:
        db.add(Note(job_id=job.id, body=body))
        db.commit()
    return _respond(request, db, job, "notes", errors, form if errors else None)


@router.post("/jobs/{job_id}/notes/{note_id}")
async def edit_note(
    job_id: int,
    note_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    note = repo.get_job_child(db, Note, job_id, note_id, user.id)
    job = db.get(Job, job_id)
    form = await _form(request)
    body = form.get("body", "")
    errors = _note_errors(body)
    if not errors:
        note.body = body
        note.updated_at = utcnow()
        db.add(note)
        db.commit()
    return _respond(request, db, job, "notes", errors)


@router.post("/jobs/{job_id}/notes/{note_id}/delete")
def delete_note(
    job_id: int,
    note_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    note = repo.get_job_child(db, Note, job_id, note_id, user.id)
    job = db.get(Job, job_id)
    db.delete(note)
    db.commit()
    return _respond(request, db, job, "notes")


# --- contacts ------------------------------------------------------------------------------

CONTACT_FIELDS = ("name", "role", "email", "phone", "profile_url", "notes")


def _contact_values(form: dict) -> tuple[dict, dict]:
    values = {f: (form.get(f) or None) for f in CONTACT_FIELDS}
    errors = {}
    if not values["name"]:
        errors["name"] = "Name is required."
    if values["email"]:
        try:
            values["email"] = validate_email(values["email"], check_deliverability=False).normalized
        except EmailNotValidError:
            errors["email"] = "Enter a valid email address."
    if values["profile_url"]:
        parts = urlsplit(values["profile_url"])
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            errors["profile_url"] = "Enter a full http(s) link."
    return values, errors


@router.post("/jobs/{job_id}/contacts")
async def add_contact(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    form = await _form(request)
    values, errors = _contact_values(form)
    if not errors:
        db.add(Contact(job_id=job.id, **values))
        db.commit()
    return _respond(request, db, job, "contacts", errors, form if errors else None)


@router.post("/jobs/{job_id}/contacts/{contact_id}")
async def edit_contact(
    job_id: int,
    contact_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    contact = repo.get_job_child(db, Contact, job_id, contact_id, user.id)
    job = db.get(Job, job_id)
    values, errors = _contact_values(await _form(request))
    if not errors:
        for key, value in values.items():
            setattr(contact, key, value)
        db.add(contact)
        db.commit()
    return _respond(request, db, job, "contacts", errors)


@router.post("/jobs/{job_id}/contacts/{contact_id}/delete")
def delete_contact(
    job_id: int,
    contact_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    contact = repo.get_job_child(db, Contact, job_id, contact_id, user.id)
    job = db.get(Job, job_id)
    db.delete(contact)
    db.commit()
    return _respond(request, db, job, "contacts")


# --- follow-ups ----------------------------------------------------------------------------


@router.post("/jobs/{job_id}/followups")
async def add_followup(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    form = await _form(request)
    errors = {}
    due = None
    try:
        due = date.fromisoformat(form.get("due_date", ""))
    except ValueError:
        errors["due_date"] = "Pick a date."
    description = form.get("description", "")
    if len(description) > MAX_FOLLOWUP:
        errors["description"] = f"At most {MAX_FOLLOWUP} characters."
    if not errors:
        db.add(FollowUp(job_id=job.id, due_date=due, description=description))
        db.commit()
    return _respond(request, db, job, "followups", errors, form if errors else None)


@router.post("/jobs/{job_id}/followups/{followup_id}/done")
def followup_done(
    job_id: int,
    followup_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    followup = repo.get_job_child(db, FollowUp, job_id, followup_id, user.id)
    job = db.get(Job, job_id)
    if not followup.done:
        followup.done = True
        followup.done_at = utcnow()
        db.add(followup)
        db.commit()
    return _respond(request, db, job, "followups")


@router.post("/jobs/{job_id}/followups/{followup_id}/delete")
def delete_followup(
    job_id: int,
    followup_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    followup = repo.get_job_child(db, FollowUp, job_id, followup_id, user.id)
    job = db.get(Job, job_id)
    db.delete(followup)
    db.commit()
    return _respond(request, db, job, "followups")
