"""Login history: when, from which IP, roughly where and on what device each login happened.

Every user sees their own history (Settings -> Login history) and the admin sees everyone's,
so recording is never hidden from the person. Places come from DB-IP's free "IP to City
Lite" database (CC BY 4.0, https://db-ip.com), kept next to the SQLite file and refreshed
monthly by the scheduler: login IPs are looked up locally and never sent anywhere. A place is
the city of the internet provider's network, not a street address, and can be wrong.
"""

import gzip
import ipaddress
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

import httpx
from sqlmodel import Session, col, delete, select

from jobhunter.config import get_settings
from jobhunter.db import utcnow
from jobhunter.models import LoginEvent, UserAccount

log = logging.getLogger(__name__)

KEEP_DAYS = 180
REFRESH_DAYS = 32  # DB-IP publishes a new file on the 1st of each month
DOWNLOAD_URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
ATTRIBUTION = '<a href="https://db-ip.com">IP Geolocation by DB-IP</a>'

RETRY_SECONDS = 6 * 3600

_reader = None
_reader_mtime = 0.0
_last_attempt = 0.0


def db_path() -> Path:
    return Path(get_settings().database_path).parent / "geoip" / "dbip-city-lite.mmdb"


def _open_reader():
    """The database reader, reopened when the file is replaced; None if it is missing."""
    global _reader, _reader_mtime
    path = db_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _reader is None or mtime != _reader_mtime:
        import maxminddb

        _reader, _reader_mtime = maxminddb.open_database(str(path), maxminddb.MODE_MMAP), mtime
    return _reader


def locate(ip: str) -> str:
    """ "Calgary, Alberta, Canada", "local network", or "" when unknown."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if addr.is_private or addr.is_loopback:
        return "local network"
    try:
        reader = _open_reader()
        rec = reader.get(ip) if reader else None
    except Exception:  # noqa: BLE001 - a broken database must never block a login
        log.exception("IP location lookup failed")
        return ""
    if not rec:
        return ""

    def name(part) -> str:
        return ((part or {}).get("names") or {}).get("en", "")

    subdivisions = rec.get("subdivisions") or [{}]
    parts = [name(rec.get("city")), name(subdivisions[0]), name(rec.get("country"))]
    return ", ".join(dict.fromkeys(p for p in parts if p))


_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("CriOS/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("Windows", "Windows"),
    ("Android", "Android"),
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Mac OS X", "Mac"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def device(user_agent: str) -> str:
    """ "Chrome on Windows" from a User-Agent header (best effort)."""
    ua = user_agent or ""
    browser = next((name for key, name in _BROWSERS if key in ua), "")
    system = next((name for key, name in _SYSTEMS if key in ua), "")
    return " on ".join(p for p in (browser, system) if p) or ua[:60]


def record(session: Session, user: UserAccount, ip: str, user_agent: str) -> LoginEvent:
    event = LoginEvent(user_id=user.id, ip=ip, location=locate(ip), device=device(user_agent))
    session.add(event)
    cutoff = utcnow() - timedelta(days=KEEP_DAYS)
    session.exec(delete(LoginEvent).where(col(LoginEvent.at) < cutoff))
    session.commit()
    return event


def for_user(session: Session, user_id: int, limit: int = 100) -> list[LoginEvent]:
    return list(
        session.exec(
            select(LoginEvent)
            .where(LoginEvent.user_id == user_id)
            .order_by(col(LoginEvent.at).desc())
            .limit(limit)
        ).all()
    )


def refresh_if_due() -> bool:
    """Download this month's database when ours is missing or over a month old."""
    path = db_path()
    if path.exists() and time.time() - path.stat().st_mtime < REFRESH_DAYS * 86400:
        return False
    if os.environ.get("GEOIP_DOWNLOAD", "on").lower() in {"off", "0", "false", "no"}:
        return False
    global _last_attempt
    if time.time() - _last_attempt < RETRY_SECONDS:
        return False
    _last_attempt = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    months = [now.strftime("%Y-%m"), (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")]
    tmp_gz, tmp = path.with_suffix(".gz.part"), path.with_suffix(".part")
    for month in months:  # early on the 1st this month's file may not be out yet
        try:
            with httpx.stream("GET", DOWNLOAD_URL.format(month=month), timeout=120) as r:
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                with tmp_gz.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            with gzip.open(tmp_gz, "rb") as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            tmp.replace(path)
            log.info("IP location database updated (%s)", month)
            return True
        except Exception:  # noqa: BLE001 - try again at the next scheduler run
            log.exception("IP location database download failed")
            return False
        finally:
            tmp_gz.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
    return False
