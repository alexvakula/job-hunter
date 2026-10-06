import httpx
import pytest
from sqlmodel import select

from jobhunter.models import Source
from jobhunter.services.fetch import Fetcher, match_source

JOB_HTML = "<html><head><title>QA Lead</title></head><body>ok</body></html>"


def _resolver(ip="104.18.1.1"):
    def resolve(host):
        return [ip]

    return resolve


def _source(session, name):
    return session.exec(select(Source).where(Source.name == name)).one()


def _fetcher(handler, ip="104.18.1.1", **kw):
    return Fetcher(
        transport=httpx.MockTransport(handler), resolver=_resolver(ip), sleep=lambda s: None, **kw
    )


def _ok_handler(robots="User-agent: *\nAllow: /\n", body=JOB_HTML, calls=None):
    def handler(request: httpx.Request):
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    return handler


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://www.jobbank.gc.ca/jobsearch/jobposting/1", "Job Bank"),
        ("https://boards.greenhouse.io/acme/jobs/1", "Greenhouse"),
        ("https://acme.wd3.myworkdayjobs.com/en-US/x/job/1", "Workday"),
        ("https://ca.linkedin.com/jobs/view/1", "LinkedIn"),
        ("https://ca.indeed.com/viewjob?jk=1", "Indeed"),
        ("https://careers.unknown-company.com/jobs/1", "Manual"),
        ("https://notlinkedin.com/jobs/1", "Manual"),
    ],
)
def test_match_source_by_host_and_subdomain(session, url, name):
    assert match_source(session, url).name == name


def test_disabled_source_still_matches_but_is_not_fetched(session):
    src = _source(session, "Greenhouse")
    src.enabled = False
    session.add(src)
    session.commit()
    url = "https://boards.greenhouse.io/acme/jobs/1"
    assert match_source(session, url).name == "Greenhouse"
    calls = []
    result = _fetcher(_ok_handler(calls=calls)).fetch(url, src)
    assert result.status == "not_fetched_disallowed"
    assert calls == []


def test_store_only_source_is_never_fetched(session):
    calls = []
    result = _fetcher(_ok_handler(calls=calls)).fetch(
        "https://www.linkedin.com/jobs/view/1", _source(session, "LinkedIn")
    )
    assert result.status == "not_fetched_disallowed"
    assert calls == []


def test_allowed_source_is_fetched_with_identifying_agent(session):
    seen = {}

    def handler(request):
        seen.setdefault("ua", request.headers["user-agent"])
        return _ok_handler()(request)

    result = _fetcher(handler).fetch("https://jobs.lever.co/acme/1", _source(session, "Lever"))
    assert result.status == "fetched"
    assert "QA Lead" in result.html
    assert seen["ua"].startswith("JobHunter/1.0")


def test_robots_disallow_prevents_fetch(session):
    calls = []
    result = _fetcher(_ok_handler(robots="User-agent: *\nDisallow: /acme\n", calls=calls)).fetch(
        "https://jobs.lever.co/acme/1", _source(session, "Lever")
    )
    assert result.status == "not_fetched_disallowed"
    assert all(c.endswith("/robots.txt") for c in calls)


def test_redirect_to_other_host_is_refused(session):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    result = _fetcher(handler).fetch("https://jobs.lever.co/acme/1", _source(session, "Lever"))
    assert result.status == "fetch_failed"


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "10.0.0.10", "169.254.169.254", "::1"])
def test_private_addresses_are_refused(session, ip):
    calls = []
    result = _fetcher(_ok_handler(calls=calls), ip=ip).fetch(
        "https://jobs.lever.co/acme/1", _source(session, "Lever")
    )
    assert result.status == "fetch_failed"
    assert calls == []


def test_oversized_response_is_refused(session):
    big = "x" * (2 * 1024 * 1024 + 10)
    result = _fetcher(_ok_handler(body=big)).fetch(
        "https://jobs.lever.co/acme/1", _source(session, "Lever")
    )
    assert result.status == "fetch_failed"


def test_timeout_is_reported(session):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        raise httpx.ReadTimeout("slow", request=request)

    result = _fetcher(handler).fetch("https://jobs.lever.co/acme/1", _source(session, "Lever"))
    assert result.status == "fetch_failed"
    assert "time" in result.message.lower()


def test_rate_limit_waits_between_requests_to_same_host(session):
    waits = []
    clock = iter([100.0, 100.0, 101.0, 101.0, 101.0, 101.0])
    fetcher = Fetcher(
        transport=httpx.MockTransport(_ok_handler()),
        resolver=_resolver(),
        sleep=waits.append,
        clock=lambda: next(clock, 200.0),
    )
    src = _source(session, "Lever")
    fetcher.fetch("https://jobs.lever.co/acme/1", src)
    fetcher.fetch("https://jobs.lever.co/acme/2", src)
    assert any(w >= 3.9 for w in waits)


def test_non_http_urls_are_refused(session):
    result = _fetcher(_ok_handler()).fetch("file:///etc/passwd", _source(session, "Lever"))
    assert result.status == "fetch_failed"


def test_accept_header_allows_feeds_and_json(session):
    seen = {}

    def handler(request):
        if request.url.path != "/robots.txt":
            seen["accept"] = request.headers["accept"]
        return _ok_handler()(request)

    _fetcher(handler).fetch(
        "https://www.jobbank.gc.ca/jobsearch/feed/x", _source(session, "Job Bank")
    )
    assert "application/atom+xml" in seen["accept"] and "*/*" in seen["accept"]


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(401, True), (403, True), (404, True), (429, False), (500, False), (503, False)],
)
def test_robots_status_codes_follow_rfc9309(session, status, allowed):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(status, text="nope")
        return httpx.Response(200, text=JOB_HTML)

    result = _fetcher(handler).fetch("https://jobs.lever.co/acme/1", _source(session, "Lever"))
    assert (result.status == "fetched") == allowed


def test_temporary_robots_failure_is_retried_after_an_hour(session):
    now = [0.0]
    robots_status = [503]

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(robots_status[0], text="")
        return httpx.Response(200, text=JOB_HTML)

    fetcher = Fetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver(),
        sleep=lambda s: None,
        clock=lambda: now[0],
    )
    src = _source(session, "Lever")
    assert fetcher.fetch("https://jobs.lever.co/acme/1", src).status == "not_fetched_disallowed"
    robots_status[0] = 404
    now[0] += 3601
    assert fetcher.fetch("https://jobs.lever.co/acme/1", src).status == "fetched"
