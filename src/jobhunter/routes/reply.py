"""Replying to an email, by hand or from a Claude draft (constitution III: preview + confirm)."""

import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user, require_claude
from jobhunter.db import get_session
from jobhunter.models import (
    ClaudeJob,
    EmailMessage,
    Job,
    MasterResume,
    SenderSettings,
    UserAccount,
)
from jobhunter.services import reply, statuses
from jobhunter.services.claude import queue
from jobhunter.services.claude.reply import INSTRUCTIONS_LIMIT
from jobhunter.services.resume import apply_email, model
from jobhunter.web import render

router = APIRouter()


def _email(db: Session, email_id: int, user: UserAccount) -> EmailMessage:
    email = repo.get_owned(db, EmailMessage, email_id, user.id)
    if not reply.can_reply(email):
        raise repo.not_found()
    return email


def _job(db: Session, email: EmailMessage) -> Job | None:
    return db.get(Job, email.job_id) if email.job_id else None


def _name(db: Session, user: UserAccount) -> str:
    master = db.get(MasterResume, user.id)
    return (model.normalise(master.data)["name"] if master else "") or user.display_name


def _compose_page(
    request, db, user, email, compose, errors=None, status_code=200, intent=None, **extra
):
    return render(
        request,
        "mail/reply.html",
        status_code=status_code,
        email=email,
        job=_job(db, email),
        compose=compose,
        errors=errors or {},
        sender=db.get(SenderSettings, user.id),
        quote=reply.quote(email),
        intent=intent,
        intents=reply.INTENTS,
        **extra,
    )


def _preview_page(request, db, user, email, compose, intent, status_code=200, error=None):
    sender = db.get(SenderSettings, user.id)
    job = _job(db, email)
    return render(
        request,
        "mail/reply_preview.html",
        status_code=status_code,
        email=email,
        job=job,
        compose=compose,
        sender=sender,
        body=reply.full_body(sender, compose, email),
        gaps=reply.placeholders(compose),
        token=reply.token(compose, user.id, email.id),
        intent=intent,
        new_status=reply.status_after(intent, job),
        error=error,
    )


@router.get("/mail/{email_id}/reply")
def reply_page(
    email_id: int,
    request: Request,
    draft: int | None = None,
    intent: str | None = None,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = _email(db, email_id, user)
    intent = reply.intent_of(intent)
    compose, drafted = reply.defaults(email), None
    if intent:
        compose.body = reply.template(email, _job(db, email), intent, _name(db, user))
    if draft is not None:
        job = repo.get_owned(db, ClaudeJob, draft, user.id)
        if (
            job.kind != "reply"
            or job.status != "done"
            or (job.result or {}).get("email_id") != email.id
        ):
            raise repo.not_found()
        compose = reply.defaults(email, job.result["subject"], job.result["body"])
        drafted, intent = job, reply.intent_of(job.payload.get("intent"))
    return _compose_page(request, db, user, email, compose, intent=intent, drafted=drafted)


@router.post("/mail/{email_id}/reply/claude", dependencies=[Depends(csrf_protect)])
async def reply_with_claude(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    email = _email(db, email_id, user)
    form = await request.form()
    instructions = str(form.get("instructions") or "").strip()[:INSTRUCTIONS_LIMIT]
    payload = {"email_id": email.id, "instructions": instructions}
    if intent := reply.intent_of(form.get("intent")):
        payload["intent"] = intent
    try:
        job = queue.enqueue(db, user, "reply", payload)
    except queue.NotAllowed:
        return _compose_page(
            request,
            db,
            user,
            email,
            reply.defaults(email),
            status_code=409,
            claude_error="Claude isn't set up for your account.",
        )
    return RedirectResponse(f"/claude/jobs/{job.id}", status_code=303)


@router.post("/mail/{email_id}/reply/preview", dependencies=[Depends(csrf_protect)])
async def reply_preview(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = _email(db, email_id, user)
    form = await request.form()
    compose, errors = apply_email.from_form(form)
    intent = reply.intent_of(form.get("intent"))
    sender = db.get(SenderSettings, user.id)
    if sender is None or not sender.from_address:
        errors["sender"] = "Set up your sender email first."
    if errors:
        return _compose_page(
            request, db, user, email, compose, errors, status_code=422, intent=intent
        )
    return _preview_page(request, db, user, email, compose, intent)


@router.post("/mail/{email_id}/reply/edit", dependencies=[Depends(csrf_protect)])
async def reply_edit(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = _email(db, email_id, user)
    form = await request.form()
    compose, _ = apply_email.from_form(form)
    return _compose_page(
        request, db, user, email, compose, intent=reply.intent_of(form.get("intent"))
    )


@router.post("/mail/{email_id}/reply/send", dependencies=[Depends(csrf_protect)])
async def reply_send(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = _email(db, email_id, user)
    form = await request.form()
    compose, errors = apply_email.from_form(form)
    intent = reply.intent_of(form.get("intent"))
    sender = db.get(SenderSettings, user.id)
    expected = reply.token(compose, user.id, email.id)
    if errors or sender is None or not hmac.compare_digest(str(form.get("token") or ""), expected):
        errors["preview"] = "The email changed after the preview. Preview it again before sending."
        return _compose_page(
            request, db, user, email, compose, errors, status_code=400, intent=intent
        )
    if form.get("confirm") != "yes":
        return _preview_page(
            request,
            db,
            user,
            email,
            compose,
            intent,
            status_code=400,
            error="Tick “I have reviewed this email” to send it.",
        )
    ok, message = await run_in_threadpool(reply.send, db, user, sender, email, compose)
    job = _job(db, email)
    new_status = reply.status_after(intent, job)
    if ok and new_status and form.get("set_status") == "1":
        statuses.change_status(db, job, new_status)
        message += f" The job is now marked {statuses.STATUS_LABELS[new_status]}."
    return render(
        request,
        "mail/reply_sent.html",
        status_code=200 if ok else 502,
        email=email,
        ok=ok,
        message=message,
    )
