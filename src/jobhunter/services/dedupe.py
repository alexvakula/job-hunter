"""Duplicate detection (research R6, FR-011–FR-014).

Pure normalisation functions plus one owner-scoped lookup. Every way a job is created goes
through `jobhunter.services.jobs`, which calls `find_duplicates` (FR-014).
"""

import re
import string
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlmodel import Session, select

from jobhunter.models import Job

TRACKING_PARAMS = {
    "ref",
    "refid",
    "trk",
    "trackingid",
    "src",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "lipi",
    "from",
}
LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "llc",
    "corp",
    "corporation",
    "co",
    "company",
    "ulc",
    "lp",
    "llp",
    "gmbh",
    "plc",
}
_PUNCT = re.compile(rf"[{re.escape(string.punctuation)}’‘“”–—·•]+")
_SPACE = re.compile(r"\s+")


def normalize_url(url: str | None) -> str | None:
    """Canonical form used for the hard duplicate check; None for unusable input."""
    if not url or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host or "." not in host:
        return None
    if host.startswith("www."):
        host = host[4:]
    netloc = host if parts.port in (None, 80, 443) else f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    )
    # http and https point at the same posting.
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def _norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("&", " and ")
    value = _PUNCT.sub(" ", value)
    return _SPACE.sub(" ", value).strip()


def normalize_title(title: str) -> str:
    return _norm_text(title)


def normalize_company(company: str) -> str:
    words = _norm_text(company).split(" ")
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def company_title_key(company: str, title: str) -> str:
    return f"{normalize_company(company)}|{normalize_title(title)}"


@dataclass
class Duplicates:
    url_match: Job | None = None
    possible: list[Job] = field(default_factory=list)


def find_duplicates(
    session: Session,
    user_id: int,
    url_norm: str | None,
    key: str,
    exclude_job_id: int | None = None,
) -> Duplicates:
    """Only ever compares against this user's own jobs (FR-013a)."""
    result = Duplicates()
    if url_norm:
        stmt = select(Job).where(Job.user_id == user_id, Job.url_norm == url_norm)
        if exclude_job_id is not None:
            stmt = stmt.where(Job.id != exclude_job_id)
        result.url_match = session.exec(stmt).first()
    stmt = select(Job).where(Job.user_id == user_id, Job.company_title_key == key)
    if exclude_job_id is not None:
        stmt = stmt.where(Job.id != exclude_job_id)
    result.possible = [j for j in session.exec(stmt).all() if j is not result.url_match]
    return result
