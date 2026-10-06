"""Company job boards: link parsing and readers (FR-003, FR-008).

Greenhouse, Lever, Ashby and Workday (feature 003); Pinpoint, Rippling, JazzHR, Jobvite,
Eightfold, Phenom, SuccessFactors and Oracle Cloud (feature 007). Each is read through the
provider's public job feed, public search API or public search page, as the career site does.
"""

import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from jobhunter.services.extract import html_to_text
from jobhunter.services.search.postings import Posting

WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX = 200  # read in full up to this many jobs
WORKDAY_SEARCH_MAX = 100  # per target-title search on larger boards
MAX_SEARCH_TITLES = 8  # target titles searched on big paged boards
# Paged, searchable boards: (read in full up to N jobs, else up to M results per title search)
PAGED_LIMITS = {
    "workday": (WORKDAY_MAX, WORKDAY_SEARCH_MAX),
    "eightfold": (200, 50),
    "phenom": (100, 30),
    "successfactors": (100, 50),
    "oracle": (200, 50),
}
ORACLE_PAGE_SIZE = 50


@dataclass
class Board:
    type: str
    board_id: str
    host: str | None = None
    site: str | None = None

    @property
    def careers_url(self) -> str:
        return {
            "greenhouse": f"https://job-boards.greenhouse.io/{self.board_id}",
            "lever": f"https://jobs.lever.co/{self.board_id}",
            "ashby": f"https://jobs.ashbyhq.com/{self.board_id}",
            "workday": f"https://{self.host}/{self.site}",
            "pinpoint": f"https://{self.board_id}.pinpointhq.com/",
            "rippling": f"https://ats.rippling.com/{self.board_id}/jobs",
            "jazzhr": f"https://{self.board_id}.applytojob.com/apply",
            "jobvite": f"https://jobs.jobvite.com/{self.board_id}/jobs",
            "eightfold": f"https://{self.board_id}.eightfold.ai/careers?domain={self.site}",
            "phenom": f"https://{self.host}/{self.site}/search-results",
            "successfactors": f"https://{self.host}/search/",
            "oracle": f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.board_id}",
        }[self.type]


_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SUBDOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_NOT_COMPANY = {"www", "app", "api", "help", "support", "status", "developers", "blog"}


def _company_subdomain(host: str, suffix: str) -> str | None:
    if not host.endswith("." + suffix):
        return None
    sub = host[: -len(suffix) - 1]
    return sub if _SUBDOMAIN.match(sub) and sub not in _NOT_COMPANY else None


def parse_board_link(url: str) -> Board | None:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        token = (
            parse_qs(parts.query).get("for", [None])[0]
            if segments[:1] == ["embed"]
            else (segments[0] if segments else None)
        )
        return Board("greenhouse", token) if token and _SLUG.match(token) else None
    if host == "jobs.lever.co" and segments and _SLUG.match(segments[0]):
        return Board("lever", segments[0])
    if host == "jobs.ashbyhq.com" and segments and _SLUG.match(segments[0]):
        return Board("ashby", segments[0])
    m = re.fullmatch(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", host)
    if m and segments:
        site_segments = [s for s in segments if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)]
        if site_segments and _SLUG.match(site_segments[0]):
            return Board("workday", m.group(1), host=host, site=site_segments[0])
    if sub := _company_subdomain(host, "pinpointhq.com"):
        return Board("pinpoint", sub)
    if host == "ats.rippling.com" and segments and _SLUG.match(segments[0]):
        return Board("rippling", segments[0]) if segments[0] not in _NOT_COMPANY else None
    if sub := _company_subdomain(host, "applytojob.com"):
        return Board("jazzhr", sub)
    if host == "jobs.jobvite.com" and segments and _SLUG.match(segments[0]):
        return Board("jobvite", segments[0])
    if m := _ORACLE_SITE.search(parts.path):
        return Board("oracle", m.group(1), host=host) if _DOMAIN.match(host) else None
    if sub := _company_subdomain(host, "eightfold.ai"):
        domain = (parse_qs(parts.query).get("domain") or [f"{sub}.com"])[0].lower()
        return Board("eightfold", sub, site=domain) if _DOMAIN.match(domain) else None
    return None


_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
# Oracle Recruiting Cloud career sites, on *.oraclecloud.com or the employer's own domain
_ORACLE_SITE = re.compile(
    r"/hcmUI/CandidateExperience/[A-Za-z-]+/sites/([A-Za-z0-9_-]{1,60})", re.I
)
_PHENOM_BASE = re.compile(r'"baseUrl"\s*:\s*"https://([a-z0-9.-]+)/([a-z]{2,6}/[a-z]{2})/"')


def detect_board(url: str, html: str) -> Board | None:
    """Phenom and SuccessFactors career sites run on the employer's own domain, so they are
    recognised from the page itself (fetched once when the user pastes the link)."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or not _DOMAIN.match(host):
        return None
    if "phApp" in html:
        for page_host, site in _PHENOM_BASE.findall(html):
            if page_host == host:
                return Board("phenom", host, host=host, site=site)
    if "jobTitle-link" in html or "rmkcdn.successfactors.com" in html:
        return Board("successfactors", host, host=host)
    return None


def list_request(board: Board, search: str = "", offset: int = 0) -> tuple[str, str, dict | None]:
    """(method, url, json body) for one page of the board's job list; paged boards
    (PAGED_LIMITS) also take a search text and the offset of the first result."""
    q = quote(search)
    if board.type == "greenhouse":
        return "GET", f"https://boards-api.greenhouse.io/v1/boards/{board.board_id}/jobs", None
    if board.type == "lever":
        return "GET", f"https://api.lever.co/v0/postings/{board.board_id}?mode=json", None
    if board.type == "ashby":
        return (
            "GET",
            f"https://api.ashbyhq.com/posting-api/job-board/{board.board_id}"
            "?includeCompensation=true",
            None,
        )
    if board.type == "pinpoint":
        return "GET", f"https://{board.board_id}.pinpointhq.com/postings.json", None
    if board.type == "rippling":
        return (
            "GET",
            f"https://api.rippling.com/platform/api/ats/v1/board/{board.board_id}/jobs",
            None,
        )
    if board.type == "jazzhr":
        return "GET", f"https://app.jazz.co/feeds/export/jobs/{board.board_id}", None
    if board.type == "jobvite":
        return "GET", f"https://jobs.jobvite.com/{board.board_id}/jobs", None
    if board.type == "eightfold":
        return (
            "GET",
            f"https://{board.board_id}.eightfold.ai/api/pcsx/search"
            f"?domain={quote(board.site or '')}&query={q}&location=&start={offset}&num=10",
            None,
        )
    if board.type == "phenom":
        return (
            "GET",
            f"https://{board.host}/{board.site}/search-results?keywords={q}&from={offset}",
            None,
        )
    if board.type == "successfactors":
        return "GET", f"https://{board.host}/search/?q={q}&startrow={offset}", None
    if board.type == "oracle":
        keyword = f",keyword={quote(search, safe='')}" if search else ""
        return (
            "GET",
            f"https://{board.host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            "?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={board.board_id}{keyword},"
            f"limit={ORACLE_PAGE_SIZE},offset={offset}",
            None,
        )
    return (
        "POST",
        f"https://{board.host}/wday/cxs/{board.board_id}/{board.site}/jobs",
        {
            "appliedFacets": {},
            "limit": WORKDAY_PAGE_SIZE,
            "offset": offset,
            "searchText": search,
        },
    )


def _ts(value) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)  # date-only values
    except (ValueError, OSError):
        return None


def parse_greenhouse(data: dict, company: str) -> list[Posting]:
    out = []
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name")
        content = j.get("content")
        out.append(
            Posting(
                title=j.get("title", ""),
                url=j.get("absolute_url", ""),
                company=j.get("company_name") or company,
                location=location,
                description=html_to_text(html_lib.unescape(content)) if content else None,
                remote="remote" in (location or "").lower(),
                posted_at=_ts(j.get("updated_at")),
                detail_url=None
                if content
                else f"https://boards-api.greenhouse.io/v1/boards/"
                f"{_token(j.get('absolute_url', ''))}/jobs/{j.get('id')}",
            )
        )
    return out


def _token(absolute_url: str) -> str:
    segments = [s for s in urlsplit(absolute_url).path.split("/") if s]
    return segments[0] if segments else ""


def greenhouse_detail(data: dict) -> str | None:
    content = data.get("content")
    return html_to_text(html_lib.unescape(content)) if content else None


def parse_lever(data: list, company: str) -> list[Posting]:
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        mode = (j.get("workplaceType") or "").lower() or None
        salary = j.get("salaryRange") or {}
        period = {"per-year-salary": "year", "per-hour-wage": "hour"}.get(salary.get("interval"))
        out.append(
            Posting(
                title=j.get("text", ""),
                url=j.get("hostedUrl", ""),
                company=company,
                location=cats.get("location"),
                description=j.get("descriptionPlain"),
                work_mode=mode if mode in ("remote", "hybrid", "onsite") else None,
                salary_min=salary.get("min"),
                salary_max=salary.get("max"),
                currency=salary.get("currency"),
                period=period,
                posted_at=_ts(j.get("createdAt")),
            )
        )
    return out


def parse_ashby(data: dict, company: str) -> list[Posting]:
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        mode = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(
            (j.get("workplaceType") or "").lower().replace("-", "")
        )
        out.append(
            Posting(
                title=j.get("title", ""),
                url=j.get("jobUrl", ""),
                company=company,
                location=j.get("location"),
                description=j.get("descriptionPlain"),
                remote=j.get("isRemote"),
                work_mode=mode or ("remote" if j.get("isRemote") else None),
                posted_at=_ts(j.get("publishedAt")),
            )
        )
    return out


_MULTI_PLACE = re.compile(r"^\d+\s+Locations?$", re.I)


def parse_workday(data: dict, board: Board, company: str) -> list[Posting]:
    """Postings in several places only say "3 Locations" here; their places come from
    the detail (``detail_url``, see ``workday_detail``)."""
    out = []
    for j in data.get("jobPostings", []):
        path = j.get("externalPath")
        if not path:
            continue
        place = j.get("locationsText")
        if place and _MULTI_PLACE.match(place.strip()):
            place = None
        out.append(
            Posting(
                title=j.get("title", ""),
                url=f"https://{board.host}/{board.site}{path}",
                company=company,
                location=place,
                remote="remote" in (place or "").lower(),
                detail_url=f"https://{board.host}/wday/cxs/{board.board_id}/{board.site}{path}",
            )
        )
    return out


def workday_detail(data: dict) -> dict:
    """Places, work mode and description from a Workday job detail."""
    info = data.get("jobPostingInfo") or {}
    places = [p for p in [info.get("location"), *(info.get("additionalLocations") or [])] if p]
    mode = _MODES.get((info.get("remoteType") or "").lower().replace("-", "").replace(" ", ""))
    desc = info.get("jobDescription")
    return {
        "location": "; ".join(dict.fromkeys(places)) or None,
        "work_mode": mode,
        "description": html_to_text(html_lib.unescape(desc)) if desc else None,
    }


_MODES = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on_site": "onsite"}


def _html_text(*parts: str | None) -> str | None:
    text = "\n\n".join(html_to_text(html_lib.unescape(p)) for p in parts if p)
    return text or None


def parse_pinpoint(data: dict, company: str) -> list[Posting]:
    out = []
    for j in data.get("data", []) if isinstance(data, dict) else []:
        loc = j.get("location") or {}
        place = ", ".join(
            x.strip() for x in (loc.get("city") or loc.get("name"), loc.get("province")) if x
        )
        mode = _MODES.get((j.get("workplace_type") or "").lower())
        visible = j.get("compensation_visible")
        minimum, maximum = j.get("compensation_minimum"), j.get("compensation_maximum")
        out.append(
            Posting(
                title=j.get("title", ""),
                url=j.get("url", ""),
                company=company,
                location=place or None,
                description=_html_text(
                    j.get("description"),
                    j.get("key_responsibilities"),
                    j.get("skills_knowledge_expertise"),
                ),
                salary_min=int(minimum) if visible and minimum else None,
                salary_max=int(maximum) if visible and maximum else None,
                currency=j.get("compensation_currency") if visible else None,
                period={"year": "year", "hour": "hour"}.get(j.get("compensation_frequency"))
                if visible
                else None,
                remote=mode == "remote",
                work_mode=mode,
            )
        )
    return out


def parse_rippling(data: list, company: str) -> list[Posting]:
    """One entry per job and location in the feed; merged into one posting per job."""
    by_url: dict[str, Posting] = {}
    for j in data if isinstance(data, list) else []:
        url = j.get("url")
        if not url:
            continue
        place = (j.get("workLocation") or {}).get("label")
        if url in by_url:
            p = by_url[url]
            if place and place not in (p.location or ""):
                p.location = f"{p.location}; {place}" if p.location else place
                p.remote = p.remote or "remote" in place.lower()
            continue
        by_url[url] = Posting(
            title=j.get("name", ""),
            url=url,
            company=company,
            location=place,
            remote="remote" in (place or "").lower(),
        )
    return list(by_url.values())


def parse_jazzhr(text: str, company: str) -> list[Posting]:
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, DefusedXmlException):
        return []
    out = []
    for j in root.iter("job"):

        def field(name: str, job=j) -> str:
            return (job.findtext(name) or "").strip()

        if field("status") and field("status").lower() != "open":
            continue
        place = ", ".join(x for x in (field("city"), field("state"), field("country")) if x)
        out.append(
            Posting(
                title=field("title"),
                url=field("url"),
                company=company,
                location=place or None,
                description=_html_text(field("description")),
                remote="remote" in (place + " " + field("title")).lower(),
            )
        )
    return out


_JOBVITE_ROW = re.compile(
    r'jv-job-list-name">\s*<a href="(/[^"/]+/job/[A-Za-z0-9]+)"[^>]*>(.*?)</a>(.*?)'
    r"(?=jv-job-list-name\"|$)",
    re.S,
)
_TAG = re.compile(r"<[^>]+>")


def parse_jobvite(text: str, company: str) -> list[Posting]:
    out, seen = [], set()
    for path, title, rest in _JOBVITE_ROW.findall(text):
        if path in seen:
            continue
        seen.add(path)
        loc_html = (
            rest.split('jv-job-list-location">', 1)[1] if "jv-job-list-location" in rest else ""
        )
        loc_html = re.split(r"</td>|<div class=\"arrow", loc_html, maxsplit=1)[0]
        place = " ".join(html_lib.unescape(_TAG.sub(" ", loc_html)).split())
        place = re.sub(r"\s+,", ",", place)
        title = " ".join(html_lib.unescape(_TAG.sub(" ", title)).split())
        out.append(
            Posting(
                title=title,
                url=f"https://jobs.jobvite.com{path}",
                company=company,
                location=place or None,
                remote="remote" in place.lower(),
            )
        )
    return out


def _places(*values) -> str | None:
    seen: list[str] = []
    for v in values:
        for p in v if isinstance(v, list) else [v]:
            p = (p or "").strip() if isinstance(p, str) else ""
            if p and p.upper() not in ("N/A", "NA", "-") and p not in seen:
                seen.append(p)
    return "; ".join(seen) or None


def parse_eightfold(data: dict, board: Board, company: str) -> list[Posting]:
    out = []
    for j in ((data or {}).get("data") or {}).get("positions") or []:
        path = j.get("positionUrl") or f"/careers/job/{j.get('id')}"
        mode = _MODES.get((j.get("workLocationOption") or "").lower().replace("_local", ""))
        place = _places(j.get("locations") or j.get("standardizedLocations"))
        posted = j.get("postedTs")
        out.append(
            Posting(
                title=j.get("name", ""),
                url=f"https://{board.board_id}.eightfold.ai{path}",
                company=company,
                location=place,
                remote=mode == "remote" or "remote" in (place or "").lower(),
                work_mode=mode,
                posted_at=datetime.fromtimestamp(posted, tz=UTC)
                if isinstance(posted, int | float)
                else None,
            )
        )
    return out


_PHENOM_DDO = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", re.S)


def _phenom_search(text: str) -> dict:
    m = _PHENOM_DDO.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(1)).get("eagerLoadRefineSearch") or {}
    except ValueError:
        return {}


def parse_phenom(text: str, board: Board, company: str) -> list[Posting]:
    out = []
    for j in (_phenom_search(text).get("data") or {}).get("jobs") or []:
        job_id = j.get("jobId") or j.get("reqId")
        if not job_id:
            continue
        place = _places(j.get("multi_location"), j.get("location") or j.get("cityStateCountry"))
        out.append(
            Posting(
                title=j.get("title", ""),
                url=f"https://{board.host}/{board.site}/job/{quote(str(job_id))}",
                company=company,
                location=place,
                description=j.get("descriptionTeaser"),
                remote="remote" in (place or "").lower(),
                posted_at=_ts(j.get("postedDate")),
            )
        )
    return out


_SF_ROW = re.compile(r'<tr class="data-row">(.*?)</tr>', re.S)
_SF_LINK = re.compile(
    r'<a\s(?=[^>]*jobTitle-link)[^>]*href="(/(?:[^"/]+/)?job/[^"]+)"[^>]*>(.*?)</a>', re.S
)
_SF_PLACE = re.compile(r'class="colLocation[^"]*"[^>]*>(.*?)</td>', re.S)
_SF_TOTAL = re.compile(r"of\s*<b>\s*([\d,]+)\s*</b>")


def parse_successfactors(text: str, board: Board, company: str) -> list[Posting]:
    out = []
    for row in _SF_ROW.findall(text):
        link = _SF_LINK.search(row)
        if not link:
            continue
        place_html = (_SF_PLACE.search(row) or [None, ""])[1]
        place_html = re.sub(r"<small.*?</small>", "", place_html, flags=re.S)  # "+3 more…"
        place = " ".join(html_lib.unescape(_TAG.sub(" ", place_html)).split())
        out.append(
            Posting(
                title=" ".join(html_lib.unescape(_TAG.sub(" ", link.group(2))).split()),
                url=f"https://{board.host}{html_lib.unescape(link.group(1))}",
                company=company,
                location=place or None,
                remote="remote" in place.lower(),
            )
        )
    return out


_ORACLE_MODES = {"ORA_REMOTE": "remote", "ORA_HYBRID": "hybrid", "ORA_ON_SITE": "onsite"}


def _oracle_search(data) -> dict:
    items = (data or {}).get("items") if isinstance(data, dict) else None
    return items[0] if items and isinstance(items[0], dict) else {}


def parse_oracle(data: dict, board: Board, company: str) -> list[Posting]:
    out = []
    for j in _oracle_search(data).get("requisitionList") or []:
        if not j.get("Id"):
            continue
        place = _places(
            j.get("PrimaryLocation"), [x.get("Name") for x in j.get("secondaryLocations") or []]
        )
        mode = _ORACLE_MODES.get(j.get("WorkplaceTypeCode") or "")
        out.append(
            Posting(
                title=j.get("Title", ""),
                url=f"https://{board.host}/hcmUI/CandidateExperience/en/sites/{board.board_id}"
                f"/job/{j['Id']}",
                company=company,
                location=place,
                description=(j.get("ShortDescriptionStr") or "").strip() or None,
                remote=mode == "remote",
                work_mode=mode,
                posted_at=_ts(j.get("PostedDate")),
            )
        )
    return out


def total_jobs(board: Board, text: str) -> int:
    """How many jobs the board reports for this list or search (paged boards)."""
    try:
        if board.type == "workday":
            return int(json.loads(text).get("total") or 0)
        if board.type == "eightfold":
            return int(((json.loads(text) or {}).get("data") or {}).get("count") or 0)
        if board.type == "oracle":
            return int(_oracle_search(json.loads(text)).get("TotalJobsCount") or 0)
    except (ValueError, AttributeError, TypeError):
        return 0
    if board.type == "phenom":
        return int(_phenom_search(text).get("totalHits") or 0)
    if board.type == "successfactors":
        m = _SF_TOTAL.search(text)
        return int(m.group(1).replace(",", "")) if m else 0
    return 0


def parse_list(board: Board, text: str, company: str) -> list[Posting]:
    if board.type == "phenom":
        return parse_phenom(text, board, company)
    if board.type == "successfactors":
        return parse_successfactors(text, board, company)
    if board.type == "jazzhr":
        return parse_jazzhr(text, company)
    if board.type == "jobvite":
        return parse_jobvite(text, company)
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if board.type == "greenhouse":
        return parse_greenhouse(data, company)
    if board.type == "lever":
        return parse_lever(data, company)
    if board.type == "ashby":
        return parse_ashby(data, company)
    if board.type == "pinpoint":
        return parse_pinpoint(data, company)
    if board.type == "rippling":
        return parse_rippling(data, company)
    if board.type == "eightfold":
        return parse_eightfold(data, board, company)
    if board.type == "oracle":
        return parse_oracle(data, board, company)
    return parse_workday(data, board, company)
