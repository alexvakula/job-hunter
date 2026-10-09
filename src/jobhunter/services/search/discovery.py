"""Finding a company's public job board on Greenhouse, Lever, Ashby, Pinpoint, Rippling, JazzHR
or BambooHR (FR-010; feature 007). Jobvite and Workday boards are added by pasting a link.

Only the boards' public APIs are contacted (never the company's own website), at most one
request per second per service. Progress is stored per company, so it resumes after restarts.
"""

import json
import logging
import re
import unicodedata
from urllib.parse import urlsplit

from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import Source, WatchCompany
from jobhunter.services.fetch import FETCHED, Fetcher, get_fetcher
from jobhunter.services.mail_link import registrable
from jobhunter.services.search.boards import Board, detect_board, list_request, parse_board_link

log = logging.getLogger(__name__)
BATCH = 60
SERVICES = (
    ("greenhouse", "Greenhouse"),
    ("lever", "Lever"),
    ("ashby", "Ashby"),
    ("pinpoint", "Pinpoint"),
    ("rippling", "Rippling"),
    ("jazzhr", "JazzHR"),
    ("bamboohr", "BambooHR"),
)
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
    if board.type == "jazzhr":
        return "<jobs" in res.html[:2000]
    try:
        data = json.loads(res.html)
    except ValueError:
        return False
    if board.type in ("lever", "rippling"):
        return isinstance(data, list)
    if board.type == "pinpoint":
        return isinstance(data, dict) and isinstance(data.get("data"), list)
    if board.type == "bamboohr":
        return isinstance(data, dict) and isinstance(data.get("result"), list)
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


def pending(session: Session) -> list[WatchCompany]:
    stmt = select(WatchCompany).where(
        WatchCompany.discovery_done.is_(False), WatchCompany.board_type == "unknown"
    )
    return list(session.exec(stmt.order_by(WatchCompany.id).limit(BATCH)).all())


def run_batch(session: Session, fetcher: Fetcher | None = None) -> int:
    fetcher = fetcher or get_fetcher()
    batch = pending(session)
    for company in batch:
        try:
            discover_one(session, company, fetcher)
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("discovery failed for company %s", company.id)
    return len(batch)


def progress(session: Session) -> dict:
    companies = session.exec(select(WatchCompany)).all()
    imported = [c for c in companies if c.imported]
    return {
        "total": len(imported),
        "checked": sum(1 for c in imported if c.discovery_done),
        "found": sum(1 for c in imported if c.board_type != "unknown"),
    }


# Career sites on the employer's own domain are fetched through these sources once recognised.
SITE_SOURCES = {"phenom": "Phenom", "successfactors": "SuccessFactors", "oracle": "Oracle Cloud"}


def resolve_link(session: Session, url: str, fetcher: Fetcher) -> Board | None:
    """The job board behind a pasted careers link. Links on a board's own domain are
    recognised directly; otherwise the page is fetched once (robots.txt, rate limit and
    network checks apply) to recognise a Phenom or SuccessFactors career site, whose host
    is then added to that source's allowed domains."""
    board = parse_board_link(url)
    if board is not None:
        if board.type in SITE_SOURCES:  # e.g. an Oracle site on the employer's own domain
            _allow_host(session, board)
        return board
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return None
    domain = host[4:] if host.startswith("www.") else host
    # A transient source (never saved) that allows only this one site for the check.
    probe = Source(name="Careers link check", type="ats", domains=[domain], fetch_allowed=True)
    for page in (url.strip(), f"https://{host}/search/?q="):
        res = fetcher.fetch(page, probe, max_bytes=3 * 1024 * 1024)
        if res.status == FETCHED and (board := detect_board(page, res.html)):
            _allow_host(session, board)
            return board
    return None


def _allow_host(session: Session, board: Board) -> None:
    source = session.exec(select(Source).where(Source.name == SITE_SOURCES[board.type])).first()
    host = board.host or ""
    domain = host[4:] if host.startswith("www.") else host  # the fetcher compares without www.
    known = source.domains or [] if source else []
    if source is None or not domain or any(domain == d or domain.endswith("." + d) for d in known):
        return
    source.domains = [*(source.domains or []), domain]
    session.add(source)
    session.commit()
