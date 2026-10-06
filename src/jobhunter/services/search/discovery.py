"""Finding a company's public job board on Greenhouse, Lever or Ashby (FR-010).

Only the boards' public APIs are contacted (never the company's own website), at most one
request per second per service. Progress is stored per company, so it resumes after restarts.
"""

import json
import logging
import re
import unicodedata

from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import Source, WatchCompany
from jobhunter.services.fetch import FETCHED, Fetcher, get_fetcher
from jobhunter.services.mail_link import registrable
from jobhunter.services.search.boards import Board, list_request

log = logging.getLogger(__name__)
BATCH = 60
SERVICES = (("greenhouse", "Greenhouse"), ("lever", "Lever"), ("ashby", "Ashby"))
_SUFFIXES = {
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "co",
    "llc",
    "ulc",
    "lp",
    "technologies",
    "technology",
    "tech",
    "software",
    "solutions",
    "group",
    "the",
}


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def candidates(name: str, website: str | None) -> list[str]:
    out: list[str] = []
    if website:
        host = re.sub(r"^https?://", "", website.strip().lower()).split("/")[0]
        reg = registrable(host)
        if reg:
            out.append(reg.split(".")[0])
    raw = [w for w in re.findall(r"[a-z0-9]+", _ascii(name or ""))]
    core = [w for w in raw if w not in _SUFFIXES] or raw
    if core:
        out += ["".join(core), "-".join(core)]
        if len(core[0]) >= 4:
            out.append(core[0])
    seen: list[str] = []
    for c in out:
        if c and c not in seen and len(c) >= 2:
            seen.append(c)
    return seen[:3]


def _exists(fetcher: Fetcher, source: Source, board: Board) -> bool:
    method, url, body = list_request(board)
    res = fetcher.fetch(url, source, method=method, json_body=body, max_bytes=10 * 1024 * 1024)
    if res.status != FETCHED:
        return False
    try:
        data = json.loads(res.html)
    except ValueError:
        return False
    if board.type == "lever":
        return isinstance(data, list)
    return isinstance(data, dict) and isinstance(data.get("jobs"), list)


def discover_one(session: Session, company: WatchCompany, fetcher: Fetcher) -> None:
    sources = {k: session.exec(select(Source).where(Source.name == n)).first() for k, n in SERVICES}
    for slug in candidates(company.name, company.website):
        for kind, _name in SERVICES:
            source = sources.get(kind)
            if source is None or not source.enabled:
                continue
            if _exists(fetcher, source, Board(kind, slug)):
                company.board_type, company.board_id, company.status = kind, slug, "ok"
                company.discovery_done = True
                company.last_checked_at = utcnow()
                session.add(company)
                session.commit()
                return
    company.status = "not_found"
    company.discovery_done = True
    company.last_checked_at = utcnow()
    session.add(company)
    session.commit()


def pending(session: Session, user_id: int | None = None) -> list[WatchCompany]:
    stmt = select(WatchCompany).where(
        WatchCompany.discovery_done.is_(False), WatchCompany.board_type == "unknown"
    )
    if user_id is not None:
        stmt = stmt.where(WatchCompany.user_id == user_id)
    return list(session.exec(stmt.order_by(WatchCompany.id).limit(BATCH)).all())


def run_batch(session: Session, fetcher: Fetcher | None = None, user_id: int | None = None) -> int:
    fetcher = fetcher or get_fetcher()
    batch = pending(session, user_id)
    for company in batch:
        try:
            discover_one(session, company, fetcher)
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("discovery failed for company %s", company.id)
    return len(batch)


def progress(session: Session, user_id: int) -> dict:
    companies = session.exec(select(WatchCompany).where(WatchCompany.user_id == user_id)).all()
    imported = [c for c in companies if c.imported]
    return {
        "total": len(imported),
        "checked": sum(1 for c in imported if c.discovery_done),
        "found": sum(1 for c in imported if c.board_type != "unknown"),
    }
