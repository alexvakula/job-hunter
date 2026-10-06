"""Database engine, request-scoped sessions, and time helpers.

All timestamps are timezone-aware UTC (SQLModel's UTCDateTime); the app time zone is only
used for display and for interpreting dates the user types.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from jobhunter.config import get_settings


def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def make_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def utcnow() -> datetime:
    """Current time, aware UTC (the storage convention)."""
    return datetime.now(UTC)


def to_local(value: datetime | None) -> datetime | None:
    """Stored UTC datetime -> aware datetime in the app time zone."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(get_settings().tz)


def local_to_utc(value: datetime) -> datetime:
    """Naive datetime typed by the user (app time zone) -> aware UTC for storage."""
    return value.replace(tzinfo=get_settings().tz).astimezone(UTC)


def today_local() -> date:
    return datetime.now(get_settings().tz).date()
