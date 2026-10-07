"""Running the automatic searches for a user (FR-001–FR-007, FR-011, FR-015)."""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import unquote

from sqlmodel import Session, delete, select

from jobhunter.db import utcnow
from jobhunter.models import (
    Job,
    JobSuggestion,
    LocationRule,
    PostingDetail,
    SearchRun,
    Source,
    TargetProfile,
    UserAccount,
    WatchCompany,
)
from jobhunter.services.dedupe import normalize_url
from jobhunter.services.fetch import FETCHED, Fetcher, get_fetcher
from jobhunter.services.search import boards, jobbank
from jobhunter.services.search.postings import Posting, best_match, title_matches

log = logging.getLogger(__name__)
MAX_DETAIL_FETCHES = 100
DETAIL_TTL = timedelta(days=30)
JSON_MAX_BYTES = 10 * 1024 * 1024
_locks: dict[int, threading.Lock] = {}
_guard = threading.Lock()


class AlreadyRunning(Exception):
    pass


@dataclass
class SourceStats:
    seen: int = 0
    matched: int = 0
    suggested: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "seen": self.seen,
            "matched": self.matched,
            "suggested": self.suggested,
            "error": "; ".join(self.errors[:3]) or None,
        }


def lock_for(user_id: int) -> threading.Lock:
    with _guard:
        return _locks.setdefault(user_id, threading.Lock())


def is_running(user_id: int) -> bool:
    return lock_for(user_id).locked()


def _source(session: Session, name: str) -> Source | None:
    return session.exec(select(Source).where(Source.name == name)).first()


def active_profiles(session: Session, user_id: int) -> list[tuple[TargetProfile, list]]:
    profiles = session.exec(
        select(TargetProfile).where(
            TargetProfile.user_id == user_id, TargetProfile.is_archived.is_(False)
        )
    ).all()
    out = []
    for p in profiles:
        rules = session.exec(select(LocationRule).where(LocationRule.profile_id == p.id)).all()
        if rules:
            out.append((p, list(rules)))
    return out


def _already_suggested(session, user_id, url_norm) -> bool:
    return (
        session.exec(
            select(JobSuggestion.id).where(
                JobSuggestion.user_id == user_id, JobSuggestion.url_norm == url_norm
            )
        ).first()
        is not None
    )


def _fill_detail(session, posting: Posting, fetcher, budget, url_norm: str) -> None:
    """Completes a posting from its board's job detail (Greenhouse and BambooHR description;
    Workday and SuccessFactors places and description; Workday work mode). Details are cached for
    DETAIL_TTL, so each job costs one request from the per-run budget however often listed."""
    if not (posting.detail_url and url_norm):
        return
    cached = session.get(PostingDetail, url_norm)
    if cached is None or cached.fetched_at < utcnow() - DETAIL_TTL:
        if not (fetcher and budget and budget[0] > 0):
            return
        budget[0] -= 1
        fetched = _fetch_detail(session, posting, fetcher)
        if fetched is None:
            posting.detail_url = None  # one attempt per run
            return
        cached = cached or PostingDetail(url_norm=url_norm)
        cached.location, cached.work_mode, cached.description = fetched
        cached.fetched_at = utcnow()
        session.add(cached)
        session.commit()
    posting.detail_url = None
    posting.location = posting.location or cached.location
    posting.work_mode = posting.work_mode or cached.work_mode
    posting.remote = bool(posting.remote or posting.work_mode == "remote")
    posting.description = posting.description or cached.description


DETAIL_SOURCES = {
    "greenhouse": "Greenhouse",
    "workday": "Workday",
    "successfactors": "SuccessFactors",
    "bamboohr": "BambooHR",
    "smartrecruiters": "SmartRecruiters",
}


def _fetch_detail(session, posting: Posting, fetcher) -> tuple | None:
    """(location, work_mode, description) from a job's detail, or None."""
    kind = posting.detail_kind or "greenhouse"
    src = _source(session, DETAIL_SOURCES.get(kind, ""))
    if src is None:
        return None
    res = fetcher.fetch(posting.detail_url, src, max_bytes=JSON_MAX_BYTES)
    if res.status != FETCHED:
        return None
    if kind in ("successfactors", "smartrecruiters"):
        read = (
            boards.successfactors_detail
            if kind == "successfactors"
            else boards.smartrecruiters_detail
        )
        d = read(res.html)
        return d["location"], d["work_mode"], d["description"]
    try:
        data = json.loads(res.html)
    except ValueError:
        return None
    if kind == "greenhouse":
        return None, None, boards.greenhouse_detail(data)
    if kind == "bamboohr":
        d = boards.bamboohr_detail(data)
        return d["location"], d["work_mode"], d["description"]
    d = boards.workday_detail(data)
    return d["location"], d["work_mode"], d["description"]


def _suggest(
    session,
    user_id,
    posting: Posting,
    profiles,
    origin,
    stats: SourceStats,
    source_id,
    company_id=None,
    fetcher=None,
    detail_budget=None,
) -> None:
    stats.seen += 1
    url_norm = normalize_url(posting.url)
    if (
        posting.location is None
        and posting.detail_url
        and url_norm
        and title_matches(posting, profiles)
        and not _already_suggested(session, user_id, url_norm)
    ):
        # e.g. Workday's "3 Locations": the places are only in the job's detail
        _fill_detail(session, posting, fetcher, detail_budget, url_norm)
    m = best_match(posting, profiles)
    if m is None:
        return
    stats.matched += 1
    if url_norm is None:
        return
    if _already_suggested(session, user_id, url_norm):
        return
    tracked = session.exec(
        select(Job.id).where(Job.user_id == user_id, Job.url_norm == url_norm)
    ).first()
    description = posting.description
    if description is None and posting.detail_url:
        _fill_detail(session, posting, fetcher, detail_budget, url_norm)
        description = posting.description
    session.add(
        JobSuggestion(
            user_id=user_id,
            source_id=source_id,
            origin=origin,
            watch_company_id=company_id,
            profile_id=m.profile_id,
            title=posting.title[:200],
            company=posting.company,
            location=posting.location,
            url=posting.url,
            url_norm=url_norm,
            description=description,
            salary_text=posting.salary_text,
            work_mode=posting.work_mode,
            posted_at=posting.posted_at,
            score=m.score,
            score_reasons=m.reasons,
            state="tracked" if tracked else "new",
            job_id=tracked,
        )
    )
    session.commit()
    stats.suggested += 1


def _run_jobbank(session, user_id, profiles, fetcher, stats: SourceStats) -> None:
    source = _source(session, "Job Bank")
    if source is None or not source.enabled:
        return
    seen_urls: set[str] = set()
    for profile, rules in profiles:  # every target position is searched on every source
        for url in jobbank.queries(profile, rules):
            res = fetcher.fetch(url, source)
            if res.status != FETCHED:
                stats.errors.append(res.message or res.status)
                continue
            for posting in jobbank.parse_feed(res.html):
                if posting.url in seen_urls:
                    continue
                seen_urls.add(posting.url)
                _suggest(session, user_id, posting, profiles, "jobbank", stats, source.id)


SOURCE_FOR_BOARD = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workday": "Workday",
    "pinpoint": "Pinpoint",
    "rippling": "Rippling",
    "jazzhr": "JazzHR",
    "jobvite": "Jobvite",
    "eightfold": "Eightfold",
    "phenom": "Phenom",
    "successfactors": "SuccessFactors",
    "oracle": "Oracle Cloud",
    "bamboohr": "BambooHR",
    "hibob": "HiBob",
    "smartrecruiters": "SmartRecruiters",
}


def _search_titles(profiles) -> list[str]:
    out: list[str] = []
    for profile, _rules in profiles:
        for t in [profile.name, *profile.synonyms]:
            if t and t.strip().lower() not in {o.lower() for o in out}:
                out.append(t.strip())
    return out[: boards.MAX_SEARCH_TITLES]


def _read_pages(fetcher, source, board, company_name, search_text, limit, offset=0):
    """Pages of one job list from `offset` until `limit` results (paged boards) or the
    end; returns (postings, total reported by the board, error)."""
    postings: list[Posting] = []
    total = 0
    while True:
        method, url, body = boards.list_request(board, search_text, offset)
        extra = {"headers": h} if (h := boards.list_headers(board)) else {}
        size = boards.FEED_MAX_BYTES if board.site == boards.SF_FEED else JSON_MAX_BYTES
        res = fetcher.fetch(url, source, method=method, json_body=body, max_bytes=size, **extra)
        if res.status != FETCHED:
            return postings, total, res.message or res.status
        page = boards.parse_list(board, res.html, company_name)
        postings.extend(page)
        if boards.paged_limits(board) is None or not page:
            return postings, total, None
        offset += len(page)
        total = boards.total_jobs(board, res.html) or total
        if offset >= min(total, limit):
            return postings, total, None


SR_MAX_REQUESTS = 60  # per SmartRecruiters board and run


def _read_smartrecruiters(fetcher, source, board, company_name):
    """The careers page, its other group pages, then the rest of each larger place group."""
    budget = [SR_MAX_REQUESTS]

    def get(url):
        budget[0] -= 1
        return fetcher.fetch(url, source, max_bytes=JSON_MAX_BYTES)

    res = get(boards.smartrecruiters_url(board))
    if res.status != FETCHED:
        return [], res.message or res.status
    pages = [res.html]
    total, current = boards.smartrecruiters_pages(res.html)
    for page in range(current + 1, total):
        if budget[0] <= 0:
            break
        more = get(boards.smartrecruiters_url(board, "groups", page=page))
        if more.status != FETCHED:
            return _sr_postings(pages, company_name), more.message or more.status
        pages.append(more.html)
    postings = _sr_postings(pages, company_name)
    for place in boards.smartrecruiters_more("".join(pages)):
        label = unquote(place)
        for page in range(1, 50):
            if budget[0] <= 0:
                break
            url = boards.smartrecruiters_url(board, "more", type="location", value=place, page=page)
            more = get(url)
            if more.status != FETCHED:
                break
            found = boards.parse_smartrecruiters_more(more.html, company_name, label)
            postings += found
            if len(found) < boards.SR_GROUP_JOBS:
                break
    return list({p.url: p for p in postings}.values()), None


def _sr_postings(pages, company_name):
    return [p for html in pages for p in boards.parse_smartrecruiters(html, company_name)]


def _read_board(fetcher, source, board, company_name, titles):
    """A board's postings. Paged boards with more jobs than their PAGED_LIMITS (big
    employers) are searched once per target title instead of being read in full."""
    if board.type == "smartrecruiters":
        return _read_smartrecruiters(fetcher, source, board, company_name)
    limits = boards.paged_limits(board)
    if limits is None:
        postings, _total, error = _read_pages(fetcher, source, board, company_name, "", 0)
        return postings, error
    full, per_search = limits
    postings, total, error = _read_pages(fetcher, source, board, company_name, "", 1)
    if error or not postings:
        return postings, error
    if total <= full or not titles:
        more, _total, error = _read_pages(
            fetcher, source, board, company_name, "", full, offset=len(postings)
        )
        return postings + more, error
    by_url = {p.url: p for p in postings}
    for title in titles:
        found, _total, error = _read_pages(fetcher, source, board, company_name, title, per_search)
        if error:
            return list(by_url.values()), error
        for p in found:
            by_url.setdefault(p.url, p)
    return list(by_url.values()), None


def _run_watchlist(session, user_id, profiles, fetcher, stats: SourceStats) -> None:
    companies = session.exec(
        select(WatchCompany).where(
            WatchCompany.user_id == user_id,
            WatchCompany.paused.is_(False),
            WatchCompany.board_type != "unknown",
        )
    ).all()
    budget = [MAX_DETAIL_FETCHES]
    titles = _search_titles(profiles)
    session.exec(delete(PostingDetail).where(PostingDetail.fetched_at < utcnow() - 2 * DETAIL_TTL))
    session.commit()
    for company in companies:
        board = boards.Board(
            company.board_type, company.board_id, company.board_host, company.board_site
        )
        source = _source(session, SOURCE_FOR_BOARD[board.type])
        if source is None:
            continue
        postings, error = _read_board(fetcher, source, board, company.name, titles)
        company.last_checked_at = utcnow()
        company.last_error = error
        company.status = "error" if error else "ok"
        session.add(company)
        session.commit()
        if error:
            stats.errors.append(f"{company.name}: {error}")
            continue
        for posting in postings:
            _suggest(
                session,
                user_id,
                posting,
                profiles,
                "watchlist",
                stats,
                source.id,
                company.id,
                fetcher,
                budget,
            )


def run_searches(
    session: Session, user: UserAccount, trigger: str = "user", fetcher: Fetcher | None = None
) -> SearchRun:
    lock = lock_for(user.id)
    if not lock.acquire(blocking=False):
        raise AlreadyRunning
    fetcher = fetcher or get_fetcher()
    run = SearchRun(user_id=user.id, trigger=trigger)
    session.add(run)
    session.commit()
    try:
        profiles = active_profiles(session, user.id)
        summary = {}
        for name, step in (("Job Bank", _run_jobbank), ("Watchlist", _run_watchlist)):
            stats = SourceStats()
            try:
                step(session, user.id, profiles, fetcher, stats)
            except Exception as exc:  # noqa: BLE001 - one source failing must not stop others
                session.rollback()
                log.exception("search source %s failed", name)
                stats.errors.append(f"unexpected error ({type(exc).__name__})")
            summary[name] = stats.as_dict()
        run.summary = summary
        run.status = "partial" if any(s["error"] for s in summary.values()) else "ok"
    except Exception:  # noqa: BLE001
        session.rollback()
        run.status = "failed"
        log.exception("search run failed for user %s", user.id)
    finally:
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
        lock.release()
    return run


def last_runs(session: Session, user_id: int, limit: int = 5) -> list[SearchRun]:
    return list(
        session.exec(
            select(SearchRun)
            .where(SearchRun.user_id == user_id)
            .order_by(SearchRun.started_at.desc(), SearchRun.id.desc())
            .limit(limit)
        ).all()
    )
