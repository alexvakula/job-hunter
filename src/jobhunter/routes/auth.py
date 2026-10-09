"""Login and logout (FR-001–FR-004, contracts/http-routes.md "Auth & account")."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from jobhunter.auth import throttle
from jobhunter.auth.passwords import DUMMY_HASH, verify_password
from jobhunter.auth.sessions import (
    LOGIN_CSRF_COOKIE,
    SESSION_COOKIE,
    Auth,
    check_login_csrf,
    create_session,
    csrf_protect,
    delete_session,
    get_auth,
    load_auth,
    new_login_csrf,
    safe_next,
    set_cookie,
    set_flash,
)
from jobhunter.db import get_session, utcnow
from jobhunter.models import UserAccount
from jobhunter.services import login_history
from jobhunter.web import render

router = APIRouter()

INVALID = "Invalid username or password."


def _client_ip(request: Request) -> str:
    # nginx-proxy overwrites X-Real-IP with the real peer address, so clients cannot spoof
    # it (unlike X-Forwarded-For). The app is only reachable through the proxy.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _login_page(request: Request, status_code: int = 200, **context):
    token, cookie_value = new_login_csrf()
    response = render(
        request, "auth/login.html", status_code=status_code, login_csrf=token, **context
    )
    set_cookie(response, LOGIN_CSRF_COOKIE, cookie_value, max_age=3600)
    return response


@router.get("/login")
def login_form(
    request: Request,
    next: str | None = None,
    expired: str | None = None,
    db: Session = Depends(get_session),
):
    if load_auth(db, request) is not None:
        return RedirectResponse(safe_next(next) or "/", status_code=303)
    return _login_page(request, next=safe_next(next), expired=bool(expired))


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    expired: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_session),
):
    username = username.strip().lower()
    context = {"next": safe_next(next), "expired": bool(expired), "username": username}
    if not check_login_csrf(request, csrf_token):
        return _login_page(
            request, 400, error="The login form expired. Please try again.", **context
        )

    ip = _client_ip(request)
    if throttle.is_blocked(db, username, ip):
        return render(request, "errors/429.html", status_code=429)

    user = db.exec(select(UserAccount).where(UserAccount.username == username)).first()
    if user is None:
        verify_password(password, DUMMY_HASH)  # same cost as a real check
        ok = False
    else:
        ok = verify_password(password, user.password_hash) and user.is_active
    throttle.record_attempt(db, username, ip, succeeded=ok)
    if not ok:
        return _login_page(request, 200, error=INVALID, **context)

    user.last_login_at = utcnow()
    db.add(user)
    db.commit()
    login_history.record(db, user, ip, request.headers.get("user-agent", ""))
    session_row = create_session(db, user)
    response = RedirectResponse(safe_next(next) or "/", status_code=303)
    set_cookie(response, SESSION_COOKIE, session_row.id)
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
    if expired:
        set_flash(response, "session_expired")
    return response


@router.post("/logout", dependencies=[Depends(csrf_protect)])
def logout(auth: Auth = Depends(get_auth), db: Session = Depends(get_session)):
    delete_session(db, auth.session.id)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/account/password")
def password_form(request: Request, auth: Auth = Depends(get_auth)):
    return render(request, "auth/password.html", forced=auth.user.must_change_password)


@router.post("/account/password", dependencies=[Depends(csrf_protect)])
def change_password(
    request: Request,
    current: str = Form(""),
    new: str = Form(""),
    confirm: str = Form(""),
    auth: Auth = Depends(get_auth),
    db: Session = Depends(get_session),
):
    from jobhunter.auth.passwords import PolicyError
    from jobhunter.services.accounts import change_own_password

    user = db.get(UserAccount, auth.user.id)
    try:
        change_own_password(db, user, current, new, confirm, keep_session_id=auth.session.id)
    except PolicyError as exc:
        return render(
            request,
            "auth/password.html",
            status_code=422,
            error=str(exc),
            forced=user.must_change_password,
        )
    response = RedirectResponse("/", status_code=303)
    set_flash(response, "password_changed")
    return response


@router.get("/account/logins")
def my_logins(request: Request, auth: Auth = Depends(get_auth), db: Session = Depends(get_session)):
    return render(
        request,
        "auth/logins.html",
        person=auth.user,
        events=login_history.for_user(db, auth.user.id),
        own=True,
        attribution=login_history.ATTRIBUTION,
    )
