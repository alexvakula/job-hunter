"""Settings: sender email (FR-029–FR-032). The password is never entered here."""

import re

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.config import smtp_password_env_name, smtp_password_for
from jobhunter.db import get_session
from jobhunter.models import SenderSettings, UserAccount
from jobhunter.services import mailer, outbox  # noqa: F401 - mailer patched in tests
from jobhunter.web import is_htmx, render

router = APIRouter()
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
TEXT_FIELDS = (
    "from_address",
    "display_name",
    "reply_to",
    "smtp_host",
    "smtp_username",
    "signature",
)


def get_or_default(db: Session, user: UserAccount) -> SenderSettings:
    return db.get(SenderSettings, user.id) or SenderSettings(user_id=user.id)


def _email(value: str, field: str, errors: dict) -> str:
    if not value:
        return ""
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        errors[field] = "Enter a valid email address."
        return value


def _page(
    request: Request, user: UserAccount, settings: SenderSettings, status_code: int = 200, **extra
):
    return render(
        request,
        "settings/sender.html",
        status_code=status_code,
        s=settings,
        password_configured=smtp_password_for(user.username) is not None,
        password_env=smtp_password_env_name(user.username),
        **extra,
    )


@router.get("/settings/sender")
def sender_form(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    return _page(request, user, get_or_default(db, user))


@router.post("/settings/sender", dependencies=[Depends(csrf_protect)])
async def save_sender(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    form = await request.form()
    values = {f: str(form.get(f) or "").strip() for f in TEXT_FIELDS}
    values["signature"] = str(form.get("signature") or "").rstrip()
    errors: dict[str, str] = {}
    values["from_address"] = _email(values["from_address"], "from_address", errors)
    values["reply_to"] = _email(values["reply_to"], "reply_to", errors)
    if values["smtp_username"] and " " in values["smtp_username"]:
        errors["smtp_username"] = "The username can't contain spaces."
    if not _HOST_RE.match(values["smtp_host"] or ""):
        errors["smtp_host"] = "Enter the mail server host, e.g. smtp.example.org."
    try:
        port = int(str(form.get("smtp_port") or "587"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        errors["smtp_port"] = "Enter a port between 1 and 65535."
        port = 587
    if len(values["display_name"]) > 100:
        errors["display_name"] = "At most 100 characters."
    if len(values["signature"]) > 2000:
        errors["signature"] = "At most 2,000 characters."

    settings = get_or_default(db, user)
    for key, value in values.items():
        setattr(settings, key, value)
    settings.smtp_port = port
    settings.bcc_self = form.get("bcc_self") == "1"
    if errors:
        db.expunge_all()
        return _page(request, user, settings, 422, errors=errors)
    db.add(settings)
    db.commit()
    return RedirectResponse("/settings/sender?saved=1", status_code=303)


@router.post("/settings/sender/test", dependencies=[Depends(csrf_protect)])
async def send_test(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    settings = get_or_default(db, user)
    result = await run_in_threadpool(outbox.send_test, db, user, settings)
    if is_htmx(request):
        return render(request, "settings/_test_result.html", result=result)
    return _page(request, user, settings, result=result)
