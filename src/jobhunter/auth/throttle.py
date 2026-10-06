"""Login attempt limiting (FR-003): >10 failures per username+IP in 15 minutes blocks."""

from datetime import timedelta

from sqlalchemy import delete, func
from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import LoginAttempt

MAX_FAILURES = 10
WINDOW = timedelta(minutes=15)
RETENTION = timedelta(days=1)


def is_blocked(session: Session, username: str, ip: str) -> bool:
    since = utcnow() - WINDOW
    failures = session.exec(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.username == username,
            LoginAttempt.ip == ip,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.at >= since,
        )
    ).one()
    return failures >= MAX_FAILURES


def record_attempt(session: Session, username: str, ip: str, succeeded: bool) -> None:
    session.add(LoginAttempt(username=username, ip=ip, succeeded=succeeded))
    session.exec(delete(LoginAttempt).where(LoginAttempt.at < utcnow() - RETENTION))
    session.commit()
