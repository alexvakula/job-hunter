"""Settings → Notifications: per-user Telegram reminders (feature 006 US1)."""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_session
from jobhunter.models import UserAccount
from jobhunter.services import reminders, telegram
from jobhunter.web import render

router = APIRouter()
_CHAT_ID = re.compile(r"^-?\d{3,20}$")


def get_sender():
    """Dependency so tests can replace Telegram."""
    return telegram.send


def _page(request, user, ns, status_code=200, **extra):
    return render(
        request,
        "settings/notifications.html",
        status_code=status_code,
        ns=ns,
        bot_configured=telegram.configured(),
        **extra,
    )


@router.get("/settings/notifications")
def notifications(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    return _page(
        request, user, reminders.settings_for(db, user.id), saved=request.query_params.get("saved")
    )


@router.post("/settings/notifications", dependencies=[Depends(csrf_protect)])
async def save(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    form = await request.form()
    ns = reminders.settings_for(db, user.id)
    errors = {}
    chat = str(form.get("telegram_chat_id") or "").strip()
    if chat and not _CHAT_ID.match(chat):
        errors["telegram_chat_id"] = "A chat id is a number, e.g. 123456789."
    try:
        days = int(str(form.get("stale_days") or "7"))
        if not 1 <= days <= 60:
            raise ValueError
    except ValueError:
        errors["stale_days"] = "Choose between 1 and 60 days."
        days = ns.stale_days
    ns.telegram_chat_id = chat or None
    ns.stale_days = days
    ns.reminders_enabled = form.get("reminders_enabled") == "1"
    updates_on = form.get("updates_enabled") == "1"
    if updates_on and not ns.updates_enabled:
        ns.last_suggestion_id = None  # start from now, not from everything found so far
    ns.updates_enabled = updates_on
    if errors:
        db.expunge_all()
        return _page(request, user, ns, 422, errors=errors)
    db.add(ns)
    db.commit()
    return RedirectResponse("/settings/notifications?saved=1", status_code=303)


@router.post("/settings/notifications/test", dependencies=[Depends(csrf_protect)])
async def test(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    sender=Depends(get_sender),
):
    ns = reminders.settings_for(db, user.id)
    text = reminders.message_for(db, user, ns.stale_days) or (
        "Job Hunter test message: reminders will arrive here each morning when something is due."
    )
    result = await run_in_threadpool(sender, ns.telegram_chat_id or "", text)
    return _page(request, user, ns, test_result=result)
