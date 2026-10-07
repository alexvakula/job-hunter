"""Fetching one job page when a URL is pasted (research R7, FR-007, constitution V).

Only sources marked fetch-allowed (and enabled) are fetched, robots.txt is honoured, every
request identifies itself, is rate-limited per host, size- and time-limited, and private
network addresses are refused (SSRF guard). Redirects are followed manually so each hop is
re-checked against the same rules.
"""

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from sqlmodel import Session, select

from jobhunter.config import public_url
from jobhunter.models import Source
from jobhunter.services.robots import Robots

USER_AGENT = f"JobHunter/1.0 (+{public_url()}; personal use)"
TIMEOUT_SECONDS = 10.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MIN_INTERVAL_SECONDS = 5.0
ROBOTS_TTL_SECONDS = 24 * 3600
ROBOTS_RETRY_SECONDS = 3600  # after a temporary robots.txt failure (429/5xx/unreachable)

FETCHED = "fetched"
NOT_FETCHED_DISALLOWED = "not_fetched_disallowed"
FETCH_FAILED = "fetch_failed"


@dataclass
class FetchResult:
    status: str
    html: str = ""
    message: str = ""


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, domain: str) -> bool:
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith("." + domain)


def match_source(session: Session, url: str) -> Source:
    """Source whose domain matches the URL (disabled sources still match, FR-028), else Manual."""
    sources = session.exec(select(Source).order_by(Source.id)).all()
    manual = next(s for s in sources if s.type == "manual")
    return source_for_url(sources, url) or manual


def source_for_url(sources: list[Source], url: str) -> Source | None:
    """The source with the longest domain matching the URL's host, if any."""
    host = _host(url)
    best, best_len = None, 0
    for source in sources if host else []:
        for domain in source.domains or []:
            if _host_matches(host, domain) and len(domain) > best_len:
                best, best_len = source, len(domain)
    return best


def site_of(url: str) -> str:
    """The URL's host without www., for showing where a link points."""
    return _host(url)


def _default_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return addr.is_global and not addr.is_multicast


class Fetcher:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str], list[str]] = _default_resolver,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = MIN_INTERVAL_SECONDS,
        host_intervals: dict[str, float] | None = None,
    ):
        self._client = httpx.Client(
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={
                "User-Agent": USER_AGENT,
                # Feeds (Atom/XML) and JSON APIs must be acceptable too: Job Bank answers 406
                # to an HTML-only Accept header.
                "Accept": "text/html,application/xhtml+xml,application/atom+xml,"
                "application/xml;q=0.9,*/*;q=0.8",
            },
        )
        self._resolve = resolver
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval
        self._host_intervals = host_intervals or {}
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, tuple[float, Robots]] = {}  # origin -> (expires, rules)

    # -- guards --------------------------------------------------------------------------

    def _check_url(self, url: str, source: Source) -> str | None:
        """Error message if the URL may not be requested, else None."""
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "Only http(s) links can be downloaded."
        host = _host(url)
        if not any(_host_matches(host, d) for d in source.domains or []):
            return "The link points to a site that is not on the allowed list."
        try:
            addresses = self._resolve(parts.hostname)
        except OSError:
            return "The site's address could not be found."
        if not addresses or not all(_is_public(ip) for ip in addresses):
            return "The site resolves to a private network address."
        return None

    def _throttle(self, host: str) -> None:
        interval = self._host_intervals.get(host, self._min_interval)
        now = self._clock()
        last = self._last_request.get(host)
        if last is not None and now - last < interval:
            self._sleep(interval - (now - last))
        self._last_request[host] = self._clock()

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(origin)
        if cached is None or self._clock() > cached[0]:
            parser = Robots()
            ttl = ROBOTS_TTL_SECONDS
            try:
                resp = self._client.get(origin + "/robots.txt")
                # RFC 9309 §2.3.1: 4xx (except 429) means there is no robots.txt, so access
                # is allowed; 429 and 5xx mean "unavailable", so assume everything is
                # disallowed until a later check succeeds.
                if resp.status_code == 429 or resp.status_code >= 500:
                    parser.disallow_all = True
                    ttl = ROBOTS_RETRY_SECONDS
                elif resp.status_code >= 400:
                    parser.allow_all = True
                else:
                    parser.parse(resp.text.splitlines())
            except httpx.HTTPError:
                parser.disallow_all = True  # unreachable: be conservative (RFC 9309 §2.3.1.4)
                ttl = ROBOTS_RETRY_SECONDS
            cached = (self._clock() + ttl, parser)
            self._robots[origin] = cached
        return cached[1].can_fetch(USER_AGENT, url)

    # -- public API ----------------------------------------------------------------------

    def fetch(
        self,
        url: str,
        source: Source,
        *,
        method: str = "GET",
        json_body: dict | None = None,
        max_bytes: int = MAX_BYTES,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        if not (source.fetch_allowed and source.enabled):
            return FetchResult(
                NOT_FETCHED_DISALLOWED,
                message=f"{source.name} doesn't let Job Hunter download its pages. Open the "
                "posting, select and copy its whole text, paste it under Posting text and click "
                "Fill in details. Or type the details in the form below.",
            )
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            problem = self._check_url(current, source)
            if problem:
                return FetchResult(FETCH_FAILED, message=problem)
            if not self._robots_allows(current):
                return FetchResult(
                    NOT_FETCHED_DISALLOWED,
                    message="This site's robots.txt doesn't allow downloading this page. "
                    "Paste the posting text below.",
                )
            self._throttle(_host(current))
            try:
                sent = {"Accept": "application/json"} if method != "GET" or json_body else {}
                sent.update(headers or {})
                with self._client.stream(
                    method, current, json=json_body, headers=sent or None
                ) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            return FetchResult(FETCH_FAILED, message="Bad redirect from the site.")
                        current = urljoin(current, location)
                        continue
                    if resp.status_code >= 400:
                        return FetchResult(
                            FETCH_FAILED,
                            message=f"The site answered with error {resp.status_code}.",
                        )
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            return FetchResult(FETCH_FAILED, message="The page is too large.")
                    encoding = resp.encoding or "utf-8"
                    return FetchResult(FETCHED, html=body.decode(encoding, errors="replace"))
            except httpx.TimeoutException:
                return FetchResult(FETCH_FAILED, message="The site did not respond in time.")
            except httpx.HTTPError:
                return FetchResult(FETCH_FAILED, message="The page could not be downloaded.")
        return FetchResult(FETCH_FAILED, message="Too many redirects.")


_FETCHER: Fetcher | None = None


# Board APIs are official interfaces with generous limits; Job Bank asks for 5 s (crawl-delay).
API_HOST_INTERVALS = {
    "boards-api.greenhouse.io": 1.0,
    "api.lever.co": 1.0,
    "api.ashbyhq.com": 1.0,
    "api.rippling.com": 1.0,
    "app.jazz.co": 1.0,
}


def get_fetcher() -> Fetcher:
    """FastAPI dependency; one shared fetcher so rate limits apply across requests."""
    global _FETCHER
    if _FETCHER is None:
        _FETCHER = Fetcher(host_intervals=API_HOST_INTERVALS)
    return _FETCHER
