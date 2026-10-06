"""Runtime settings read from the environment (.env in production).

Secrets are read here and nowhere else; the Settings object never shows them in repr/logs.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from zoneinfo import ZoneInfo


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    session_secret: str = field(repr=False)
    app_timezone: str = "America/Edmonton"
    database_path: str = "/data/jobhunter.db"
    cookie_secure: bool = True
    log_level: str = "INFO"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


class ConfigError(RuntimeError):
    pass


def load_settings() -> Settings:
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise ConfigError("SESSION_SECRET must be set and at least 32 characters long")
    tz_name = os.environ.get("APP_TIMEZONE") or "America/Edmonton"
    try:
        ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001 - any lookup failure is a config error
        raise ConfigError(f"APP_TIMEZONE is not a valid time zone: {tz_name}") from exc
    return Settings(
        session_secret=secret,
        app_timezone=tz_name,
        database_path=os.environ.get("DATABASE_PATH") or "/data/jobhunter.db",
        cookie_secure=_bool(os.environ.get("COOKIE_SECURE"), True),
        log_level=os.environ.get("LOG_LEVEL") or "INFO",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def public_url() -> str:
    """Where the app is published (used in emails and the fetcher's User-Agent)."""
    return os.environ.get("PUBLIC_URL") or "https://jobs.example.org"


def mail_host() -> str:
    """Default mail server for new users' sender and mailbox settings."""
    return os.environ.get("MAIL_HOST") or "smtp.example.org"


def own_mail_domains() -> set[str]:
    """The family's own mail domains: never treated as an employer's domain."""
    raw = os.environ.get("OWN_MAIL_DOMAINS") or ""
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def smtp_password_env_name(username: str) -> str:
    return f"SMTP_PASSWORD_{username.upper()}"


def smtp_password_for(username: str) -> str | None:
    """The mail password for a user, or None. Never log or render the return value."""
    value = os.environ.get(smtp_password_env_name(username))
    return value or None
