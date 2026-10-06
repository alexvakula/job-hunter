"""Company job boards: link parsing and Greenhouse/Lever/Ashby/Workday readers (FR-003, FR-008)."""

import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from jobhunter.services.extract import html_to_text
from jobhunter.services.search.postings import Posting

WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX = 200


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
        }[self.type]


_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


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
    return None


def list_request(board: Board) -> tuple[str, str, dict | None]:
    """(method, url, json body) for the board's job list."""
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
    return (
        "POST",
        f"https://{board.host}/wday/cxs/{board.board_id}/{board.site}/jobs",
        {"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE, "offset": 0, "searchText": ""},
    )


def _ts(value) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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


def parse_workday(data: dict, board: Board, company: str) -> list[Posting]:
    out = []
    for j in data.get("jobPostings", []):
        path = j.get("externalPath")
        if not path:
            continue
        out.append(
            Posting(
                title=j.get("title", ""),
                url=f"https://{board.host}/{board.site}{path}",
                company=company,
                location=j.get("locationsText"),
                remote="remote" in (j.get("locationsText") or "").lower(),
            )
        )
    return out


def parse_list(board: Board, text: str, company: str) -> list[Posting]:
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
    return parse_workday(data, board, company)
