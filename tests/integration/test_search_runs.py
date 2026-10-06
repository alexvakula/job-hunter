import json

import httpx
import pytest
from sqlmodel import select

from jobhunter.models import (
    JobSuggestion,
    PostingDetail,
    SearchRun,
    UserAccount,
    WatchCompany,
)
from jobhunter.routes.watchlist import get_launcher
from jobhunter.services.fetch import FETCH_FAILED, FETCHED, Fetcher, FetchResult, get_fetcher
from jobhunter.services.search import runner
from tests.search_helpers import FIX, FakeFetcher, qa_lead, standard_routes


def _uid(session, name="alice"):
    return session.exec(select(UserAccount.id).where(UserAccount.username == name)).one()


def _watch(session, user_id, board_type, board_id="acme", host=None, site=None, name="Acme"):
    session.add(
        WatchCompany(
            user_id=user_id,
            name=name,
            board_type=board_type,
            board_id=board_id,
            board_host=host,
            board_site=site,
            status="ok",
            discovery_done=True,
        )
    )
    session.commit()


@pytest.fixture
def setup(two_users, session, app):
    alice, bob = two_users
    uid = _uid(session)
    qa_lead(session, uid)
    for t in ("greenhouse", "lever", "ashby"):
        _watch(session, uid, t)
    _watch(session, uid, "workday", host="acme.wd3.myworkdayjobs.com", site="Careers")
    fake = FakeFetcher(standard_routes())
    app.dependency_overrides[get_fetcher] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    yield alice, bob, uid, fake
    app.dependency_overrides.clear()


def _titles(session, uid):
    session.expire_all()
    return sorted(
        (s.title, s.origin)
        for s in session.exec(select(JobSuggestion).where(JobSuggestion.user_id == uid)).all()
    )


EXPECTED = sorted(
    [
        ("QA lead", "jobbank"),
        ("Software quality assurance (QA) lead", "jobbank"),
        ("QA Lead", "watchlist"),
        ("Senior QA Lead", "watchlist"),  # greenhouse
        ("Test Lead", "watchlist"),
        ("Quality Assurance Lead", "watchlist"),  # lever
        ("QA Lead", "watchlist"),
        ("Manager, QA", "watchlist"),  # ashby
        ("QA Lead", "watchlist"),
        ("Test Lead", "watchlist"),  # workday
    ]
)


def test_import_from_all_runs_searches(setup, session):
    alice, _, uid, fake = setup
    resp = alice.post("/sources/import")
    assert resp.status_code == 200
    assert "Job Bank: 9 postings checked, 2 matched, 2 new suggestions" in resp.text
    assert _titles(session, uid) == EXPECTED
    jb_calls = [u for _, u, _ in fake.calls if "jobbank" in u]
    assert len(jb_calls) == 8  # 4 titles × 2 Canadian places
    wd = [b for m, u, b in fake.calls if m == "POST"]
    assert wd and wd[0]["offset"] == 0
    gh = session.exec(select(JobSuggestion).where(JobSuggestion.url.like("%greenhouse%/101"))).one()
    assert "Own quality" in gh.description and gh.score == 90
    run = session.exec(select(SearchRun)).one()
    assert run.status == "ok" and run.trigger == "user"


def test_more_boards_are_searched(two_users, session, app):
    alice, _ = two_users
    uid = _uid(session)
    qa_lead(session, uid)
    for t in ("pinpoint", "rippling", "jazzhr", "jobvite"):
        _watch(session, uid, t, name=f"Acme {t}")
    _watch(session, uid, "eightfold", site="acme.example", name="Acme eightfold")
    _watch(session, uid, "phenom", "h1", "jobs.acme.example", "ca/en", name="Acme phenom")
    _watch(session, uid, "successfactors", "h2", "careers.acme.example", name="Acme sf")
    _watch(session, uid, "oracle", "CX_1", "abcd.fa.us2.oraclecloud.com", name="Acme oracle")
    routes = standard_routes()
    routes.pop("https://www.jobbank.gc.ca/jobsearch/feed/")
    fake = FakeFetcher(routes)
    app.dependency_overrides[get_fetcher] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    try:
        assert alice.post("/sources/import").status_code == 200
    finally:
        app.dependency_overrides.clear()
    session.expire_all()
    got = sorted(
        (s.company, s.title)
        for s in session.exec(
            select(JobSuggestion).where(
                JobSuggestion.user_id == uid, JobSuggestion.origin == "watchlist"
            )
        ).all()
    )
    assert got == [
        ("Acme eightfold", "QA Lead"),
        ("Acme jazzhr", "QA Lead"),
        ("Acme jobvite", "QA Lead & Test Architect"),
        ("Acme oracle", "QA Lead"),
        ("Acme phenom", "QA Lead"),
        ("Acme pinpoint", "QA Lead"),
        ("Acme rippling", "QA Lead"),
        ("Acme sf", "QA Lead"),
    ]
    companies = session.exec(select(WatchCompany).where(WatchCompany.user_id == uid)).all()
    assert {c.status for c in companies} == {"ok"}


class BigWorkday(FakeFetcher):
    """A Workday board with 1,500 jobs: the full list holds no QA roles, searches do."""

    def fetch(self, url, source, *, method="GET", json_body=None, max_bytes=0):
        if "myworkdayjobs.com" not in url or json_body is None:  # job details: not found
            return super().fetch(url, source, method=method, json_body=json_body)
        self.calls.append((method, url, dict(json_body)))
        text, offset = json_body["searchText"], json_body["offset"]
        if not text:
            jobs = [
                {"title": f"Sales Rep {offset + i}", "externalPath": f"/job/X/S{offset + i}"}
                for i in range(20)
            ]
            return FetchResult(FETCHED, html=json.dumps({"total": 1500, "jobPostings": jobs}))
        hits = {
            "QA Lead": [
                {
                    "title": "QA Lead",
                    "externalPath": "/job/Calgary/QA_R1",
                    "locationsText": "Calgary, AB",
                }
            ],
            "Test Manager": [
                {
                    "title": "Test Manager",
                    "externalPath": "/job/Vancouver/TM_R2",
                    "locationsText": "Vancouver, BC",
                },
                {
                    "title": "QA Lead",
                    "externalPath": "/job/Calgary/QA_R1",
                    "locationsText": "Calgary, AB",
                },
            ],
        }.get(text, [])
        total = len(hits) if offset == 0 else 0
        return FetchResult(FETCHED, html=json.dumps({"total": total, "jobPostings": hits}))


def test_big_workday_boards_are_searched_by_title(two_users, session, app):
    alice, _ = two_users
    uid = _uid(session)
    qa_lead(session, uid)
    _watch(session, uid, "workday", host="big.wd1.myworkdayjobs.com", site="Careers", name="Big")
    fake = BigWorkday({})
    app.dependency_overrides[get_fetcher] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    try:
        assert alice.post("/sources/import").status_code == 200
    finally:
        app.dependency_overrides.clear()
    session.expire_all()
    got = sorted(
        s.title
        for s in session.exec(select(JobSuggestion).where(JobSuggestion.user_id == uid)).all()
    )
    assert got == ["QA Lead", "Test Manager"]
    searches = [b["searchText"] for _m, u, b in fake.calls if "myworkdayjobs" in u and b]
    assert searches.count("") == 1  # the first page shows 1,500 jobs: searches only
    assert {"QA Lead", "Test Manager", "QA Manager", "Test Lead"} <= set(searches)


def test_workday_multi_location_jobs_get_their_places(two_users, session, app):
    alice, _ = two_users
    uid = _uid(session)
    qa_lead(session, uid)
    _watch(session, uid, "workday", "multi", host="multi.wd1.myworkdayjobs.com", site="Careers")
    base = "https://multi.wd1.myworkdayjobs.com/wday/cxs/multi/Careers"
    fake = FakeFetcher(
        {
            f"{base}/jobs": "workday_multi.json",
            f"{base}/job/Toronto/QA-Lead_R10": "workday_detail_r10.json",
            f"{base}/job/Toronto/Test-Lead_R11": "workday_detail_r11.json",
        }
    )
    app.dependency_overrides[get_fetcher] = lambda: fake
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    try:
        assert alice.post("/sources/import").status_code == 200
        details = [u for _m, u, _b in fake.calls if "/job/" in u]
        # only postings whose title fits a target position are looked up
        assert details == [f"{base}/job/Toronto/QA-Lead_R10", f"{base}/job/Toronto/Test-Lead_R11"]
        session.expire_all()
        (sug,) = session.exec(select(JobSuggestion).where(JobSuggestion.user_id == uid)).all()
        assert sug.title == "QA Lead" and "Calgary, Alberta" in sug.location
        assert "test automation" in sug.description
        # details are cached: the next run looks nothing up again
        fake.calls.clear()
        alice.post("/sources/import")
        assert [u for _m, u, _b in fake.calls if "/job/" in u] == []
        cached = session.exec(select(PostingDetail)).all()
        assert sorted(c.location for c in cached) == [
            "Toronto, Ontario; Calgary, Alberta; Montreal, Quebec",
            "Toronto, Ontario; Ottawa, Ontario",
        ]
    finally:
        app.dependency_overrides.clear()


def test_second_run_and_dismissed_are_not_resuggested(setup, session):
    alice, _, uid, _ = setup
    alice.post("/sources/import")
    first = len(_titles(session, uid))
    s = session.exec(select(JobSuggestion).where(JobSuggestion.state == "new")).first()
    alice.post(f"/suggestions/{s.id}/dismiss")
    alice.post("/sources/import")
    assert len(_titles(session, uid)) == first
    session.refresh(s)
    assert s.state == "dismissed"


def test_already_tracked_is_marked(setup, session):
    alice, _, uid, _ = setup
    alice.post(
        "/jobs",
        data={
            "title": "QA Lead",
            "company": "Prairie",
            "url": "https://www.jobbank.gc.ca/jobsearch/jobposting/90000001",
        },
    )
    alice.post("/sources/import")
    s = session.exec(select(JobSuggestion).where(JobSuggestion.url.like("%90000001"))).one()
    assert s.state == "tracked" and s.job_id is not None


def test_errors_are_isolated_and_shown(setup, session):
    alice, _, uid, fake = setup
    fake.routes = {
        "https://api.lever.co": (FETCH_FAILED, "The site answered with error 500."),
        **standard_routes(),
    }
    alice.post("/sources/import")
    lever = session.exec(select(WatchCompany).where(WatchCompany.board_type == "lever")).one()
    session.refresh(lever)
    assert lever.status == "error" and "500" in lever.last_error
    run = session.exec(select(SearchRun)).one()
    assert (
        run.status == "partial"
        and "Acme: The site answered with error 500." in run.summary["Watchlist"]["error"]
    )
    titles = [t for t, _ in _titles(session, uid)]
    assert "Test Lead" in titles  # workday still checked
    page = alice.get("/sources").text
    assert "error 500" in page


def test_suggestions_sorted_by_score_with_reasons_and_prefill(setup, session):
    alice, _, uid, _ = setup
    alice.post("/sources/import")
    page = alice.get("/suggestions").text
    assert page.index("Manager, QA") > page.index("Software quality assurance")  # 75 after 100
    assert "salary ≥ CAD 130,000" in page and "Job Bank search" in page
    s = session.exec(select(JobSuggestion).where(JobSuggestion.url.like("%greenhouse%/101"))).one()
    form = alice.post(f"/suggestions/{s.id}/add").text
    assert "Own quality" in form and "From an automatic search" in form


def test_one_run_at_a_time(setup, session):
    alice, _, uid, _ = setup
    lock = runner.lock_for(uid)
    lock.acquire()
    try:
        resp = alice.post("/sources/import")
        assert resp.status_code == 303 and "running=1" in resp.headers["location"]
        assert "A search is running" in alice.get("/sources?running=1").text
    finally:
        lock.release()


def test_other_users_get_nothing(setup, session):
    _, bob, uid, _ = setup
    bob.post("/sources/import")
    bob_id = _uid(session, "bob")
    assert _titles(session, bob_id) == []  # bob has no positions or watchlist
    assert "Senior QA Lead" not in bob.get("/suggestions").text


def test_background_mode_redirects(two_users, app, session):
    alice, _ = two_users
    started = []
    app.dependency_overrides[get_launcher] = lambda: lambda job: started.append(job)
    try:
        resp = alice.post("/sources/import")
        assert resp.status_code == 303 and "started=1" in resp.headers["location"]
        assert len(started) == 1
        assert "Import started" in alice.get("/sources?started=1").text
    finally:
        app.dependency_overrides.clear()


def test_rate_limits_with_real_fetcher(two_users, session):
    """Job Bank ≥ 5 s apart; board APIs ≥ 1 s apart (SC-003)."""
    _, _ = two_users
    uid = _uid(session)
    qa_lead(session, uid)
    _watch(session, uid, "greenhouse", "acme")
    _watch(session, uid, "greenhouse", "beta", name="Beta")
    now = [1000.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    def handler(request: httpx.Request):
        now[0] += 0.01
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n")
        if "jobbank" in request.url.host:
            return httpx.Response(200, text=(FIX / "jobbank_feed.xml").read_text())
        return httpx.Response(200, json={"jobs": []})

    from jobhunter.services.fetch import API_HOST_INTERVALS

    fetcher = Fetcher(
        transport=httpx.MockTransport(handler),
        resolver=lambda h: ["104.18.1.1"],
        sleep=sleep,
        clock=lambda: now[0],
        host_intervals=API_HOST_INTERVALS,
    )
    user = session.get(UserAccount, uid)
    run = runner.run_searches(session, user, fetcher=fetcher)
    assert run.summary["Job Bank"]["seen"] == 9
    jb_waits = [w for w in waits if w > 1.5]
    assert len(jb_waits) == 7 and all(w >= 4.9 for w in jb_waits)  # 8 Job Bank requests
    api_waits = [w for w in waits if 0 < w <= 1.5]
    assert api_waits and all(w >= 0.9 for w in api_waits)


def test_daily_schedule(two_users, session, monkeypatch):
    from jobhunter.services import scheduler

    uid = _uid(session)
    qa_lead(session, uid)
    calls = []
    monkeypatch.setattr(
        runner,
        "run_searches",
        lambda s, u, trigger="user", fetcher=None: calls.append((u.id, trigger)),
    )
    import datetime as dt

    from jobhunter import db as dbmod

    monkeypatch.setattr(
        scheduler, "utcnow", lambda: dt.datetime(2026, 10, 6, 11, 0, tzinfo=dt.UTC)
    )  # 05:00 MDT
    scheduler.run_due_searches(session)
    assert calls == []
    monkeypatch.setattr(
        scheduler, "utcnow", lambda: dt.datetime(2026, 10, 6, 13, 0, tzinfo=dt.UTC)
    )  # 07:00 MDT
    scheduler.run_due_searches(session)
    assert calls == [(uid, "daily")]
    session.add(
        SearchRun(
            user_id=uid, trigger="daily", started_at=dt.datetime(2026, 10, 6, 13, 0, tzinfo=dt.UTC)
        )
    )
    session.commit()
    scheduler.run_due_searches(session)
    assert calls == [(uid, "daily")]  # already ran today
    assert dbmod  # silence unused import warning in some linters
    assert json  # used by other tests in this module
