"""Account management by the admin, and password changes by users (FR-002–FR-002b, US6).

The admin manages accounts but has no access to other users' data. Accounts created here are
always role "user"; admins are only created with the CLI.
"""

from sqlalchemy import func
from sqlmodel import Session, select

from jobhunter.auth.passwords import (
    PolicyError,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)
from jobhunter.auth.sessions import delete_sessions_for_user
from jobhunter.models import Role, UserAccount


class AccountError(ValueError):
    pass


def list_users(session: Session) -> list[UserAccount]:
    return list(session.exec(select(UserAccount).order_by(UserAccount.username)).all())


def create_user(
    session: Session, username: str, display_name: str, temp_password: str
) -> UserAccount:
    username = (username or "").strip()
    display_name = (display_name or "").strip()
    validate_username(username)
    if not display_name:
        raise PolicyError("Display name is required.")
    if len(display_name) > 80:
        raise PolicyError("Display name must be at most 80 characters.")
    validate_password(temp_password)
    if session.exec(select(UserAccount).where(UserAccount.username == username)).first():
        raise PolicyError(f"The username '{username}' is already taken.")
    user = UserAccount(
        username=username,
        display_name=display_name,
        role=Role.USER.value,
        password_hash=hash_password(temp_password),
        must_change_password=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def reset_password(session: Session, user: UserAccount, temp_password: str) -> None:
    validate_password(temp_password)
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    session.add(user)
    session.commit()
    delete_sessions_for_user(session, user.id)


def _active_admins(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(UserAccount)
        .where(UserAccount.role == Role.ADMIN.value, UserAccount.is_active.is_(True))
    ).one()


def set_active(session: Session, user: UserAccount, active: bool) -> None:
    if not active and user.is_admin and user.is_active and _active_admins(session) <= 1:
        raise AccountError("You can't disable the only active admin.")
    user.is_active = active
    session.add(user)
    session.commit()
    if not active:
        delete_sessions_for_user(session, user.id)


def change_own_password(
    session: Session, user: UserAccount, current: str, new: str, confirm: str, keep_session_id: str
) -> None:
    if not verify_password(current, user.password_hash):
        raise PolicyError("Your current password is not correct.")
    if new != confirm:
        raise PolicyError("The new passwords don't match.")
    validate_password(new)
    if verify_password(new, user.password_hash):
        raise PolicyError("Choose a password different from the current one.")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    session.add(user)
    session.commit()
    delete_sessions_for_user(session, user.id, except_id=keep_session_id)
