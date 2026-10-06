"""Shared helpers for feature 003 tests: a QA Lead position and a fake fetcher."""

from pathlib import Path

from sqlmodel import select

from jobhunter.models import LocationRule, Source, TargetProfile
from jobhunter.services.fetch import FETCH_FAILED, FETCHED, FetchResult

FIX = Path(__file__).resolve().parent / "fixtures" / "search"


def qa_lead(session, user_id, exclude=("junior",), sources=None):
    if sources is None:
        sources = [s.id for s in session.exec(select(Source)).all()]
    p = TargetProfile(
        user_id=user_id,
        name="QA Lead",
        synonyms=["Test Manager", "QA Manager", "Test Lead"],
        exclude_keywords=list(exclude),
        source_ids=sources,
        is_default=True,
    )
    session.add(p)
    session.commit()
    for place, modes, cur in (
        ("Calgary, AB", ["onsite", "hybrid", "remote"], "CAD"),
        ("Vancouver, BC", ["onsite", "hybrid", "remote"], "CAD"),
        ("USA", ["remote"], "USD"),
    ):
        session.add(
            LocationRule(
                profile_id=p.id,
                place=place,
                work_modes=modes,
                salary_floor=130000,
                salary_currency=cur,
            )
        )
    session.commit()
    return p


class FakeFetcher:
    """Answers by URL prefix from fixtures; records calls."""

    def __init__(self, routes: dict[str, tuple[str, str] | str] | None = None):
        self.routes = routes or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def fetch(self, url, source, *, method="GET", json_body=None, max_bytes=0):
        self.calls.append((method, url, dict(json_body) if json_body else None))
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                if isinstance(answer, tuple):
                    status, body = answer
                    return FetchResult(status, html=body, message=body if status != FETCHED else "")
                return FetchResult(FETCHED, html=(FIX / answer).read_text())
        return FetchResult(FETCH_FAILED, message="The site answered with error 404.")


def standard_routes():
    return {
        "https://www.jobbank.gc.ca/jobsearch/feed/": "jobbank_feed.xml",
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/101": "greenhouse_job_101.json",
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs": "greenhouse_jobs.json",
        "https://api.lever.co/v0/postings/acme": "lever_postings.json",
        "https://api.ashbyhq.com/posting-api/job-board/acme": "ashby_board.json",
        "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/jobs": "workday_jobs.json",
        "https://acme.pinpointhq.com/postings.json": "pinpoint_postings.json",
        "https://api.rippling.com/platform/api/ats/v1/board/acme/jobs": "rippling_jobs.json",
        "https://app.jazz.co/feeds/export/jobs/acme": "jazzhr_feed.xml",
        "https://jobs.jobvite.com/acme/jobs": "jobvite_jobs.html",
        "https://acme.eightfold.ai/api/pcsx/search": "eightfold_search.json",
        "https://jobs.acme.example/ca/en/search-results": "phenom_search.html",
        "https://careers.acme.example/search/": "successfactors_search.html",
    }
