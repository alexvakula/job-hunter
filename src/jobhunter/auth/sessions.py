"""Server-side sessions, CSRF protection and the auth dependencies (research R3, R4).

The browser only holds a random session id. Session rows live in `user_session`, so
disabling a user or changing a password can end sessions immediately.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from fastapi import Depends, Request
from sqlalchemy import delete
from sqlmodel import Session

from jobhunter.config import get_settings
from jobhunter.db import get_session, utcnow
from jobhunter.models import UserAccount, UserSession

SESSION_COOKIE = "jh_session"
LOGIN_CSRF_COOKIE = "jh_login_csrf"
FLASH_COOKIE = "jh_flash"
IDLE_TIMEOUT = timedelta(days=30)
TOUCH_INTERVAL = timedelta(hours=1)
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"

# Paths a user with must_change_password may still use.
PASSWORD_CHANGE_PATH = "/account/password"  # noqa: S105 - a URL path, not a secret
_ALLOWED_WHILE_MUST_CHANGE = {PASSWORD_CHANGE_PATH, "/logout"}


@dataclass
class Auth:
    user: UserAccount
    session: UserSession


class LoginRequired(Exception):
    def __init__(self, next_path: str, expired: bool = False):
        self.next_path = next_path
        self.expired = expired


class PasswordChangeRequired(Exception):
    pass


class Forbidden(Exception):
    pass


class CsrfFailed(Exception):
    pass


# --- cookies -----------------------------------------------------------------------------


def set_cookie(response, name: str, value: str, max_age: int | None = None) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


def set_flash(response, message_key: str) -> None:
    set_cookie(response, FLASH_COOKIE, message_key, max_age=300)


# --- session lifecycle -------------------------------------------------------------------


def create_session(db: Session, user: UserAccount) -> UserSession:
    row = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_session(db: Session, session_id: str) -> None:
    db.exec(delete(UserSession).where(UserSession.id == session_id))
    db.commit()


def delete_sessions_for_user(db: Session, user_id: int, except_id: str | None = None) -> None:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if except_id is not None:
        stmt = stmt.where(UserSession.id != except_id)
    db.exec(stmt)
    db.commit()


def load_auth(db: Session, request: Request) -> Auth | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None
    row = db.get(UserSession, session_id)
    if row is None:
        return None
    now = utcnow()
    if now - row.last_seen_at > IDLE_TIMEOUT:
        delete_session(db, row.id)
        return None
    user = db.get(UserAccount, row.user_id)
    if user is None or not user.is_active:
        delete_sessions_for_user(db, row.user_id)
        return None
    if now - row.last_seen_at > TOUCH_INTERVAL:
        row.last_seen_at = now
        db.add(row)
        db.commit()
    return Auth(user=user, session=row)


def _next_path(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    if request.method != "GET":
        # After re-login, send the user back to the page they were on, not a POST target.
        referer_path = request.headers.get("HX-Current-URL") or request.headers.get("referer")
        path = _same_origin_path(referer_path, request) or "/"
    return path


def _same_origin_path(url: str | None, request: Request) -> str | None:
    if not url:
        return None
    base = str(request.base_url).rstrip("/")
    if url.startswith(base):
        url = url[len(base) :] or "/"
    return safe_next(url)


def safe_next(value: str | None) -> str | None:
    """Only same-origin absolute paths are allowed as redirect targets."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    return value


def login_redirect_url(next_path: str, expired: bool) -> str:
    url = "/login?next=" + quote(next_path, safe="")
    return url + "&expired=1" if expired else url


# --- dependencies ------------------------------------------------------------------------


def get_auth(request: Request, db: Session = Depends(get_session)) -> Auth:
    auth = load_auth(db, request)
    if auth is None:
        had_cookie = bool(request.cookies.get(SESSION_COOKIE))
        raise LoginRequired(_next_path(request), expired=had_cookie)
    request.state.auth = auth
    if auth.user.must_change_password and request.url.path not in _ALLOWED_WHILE_MUST_CHANGE:
        raise PasswordChangeRequired()
    return auth


def current_user(auth: Auth = Depends(get_auth)) -> UserAccount:
    return auth.user


def require_claude(auth: Auth = Depends(get_auth)) -> UserAccount:
    """Claude pages: users with their own Claude token; the admin always (to see the setup hint)."""
    from jobhunter.services.claude.queue import enabled_for

    if not (auth.user.is_admin or enabled_for(auth.user)):
        raise Forbidden()
    return auth.user


def require_admin(auth: Auth = Depends(get_auth)) -> UserAccount:
    if not auth.user.is_admin:
        raise Forbidden()
    return auth.user


async def csrf_protect(request: Request, auth: Auth = Depends(get_auth)) -> None:
    """Every state-changing request must echo the session's CSRF token."""
    token = request.headers.get(CSRF_HEADER)
    if token is None:
        form = await request.form()
        token = form.get(CSRF_FIELD)
    if not isinstance(token, str) or not hmac.compare_digest(token, auth.session.csrf_token):
        raise CsrfFailed()


# --- pre-login CSRF (double-submit cookie signed with SESSION_SECRET) --------------------


def _sign(token: str) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def new_login_csrf() -> tuple[str, str]:
    """Returns (form token, cookie value)."""
    token = secrets.token_urlsafe(24)
    return token, f"{token}.{_sign(token)}"


def check_login_csrf(request: Request, form_token: str | None) -> bool:
    cookie = request.cookies.get(LOGIN_CSRF_COOKIE) or ""
    token, _, signature = cookie.partition(".")
    if not token or not form_token:
        return False
    return hmac.compare_digest(signature, _sign(token)) and hmac.compare_digest(token, form_token)
