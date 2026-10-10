"""Turning job-alert emails into suggested jobs (feature 002 research R5, FR-018–FR-022).

Only the email content is used; no web page is requested. Each supported site has a link
pattern; every anchor pointing at a job is a listed job, its text is the title, and the short
text that follows (until the next job link) gives company and location.
"""

import base64
import gzip
import html as html_lib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from sqlmodel import Session, select

from jobhunter.models import EmailMessage, Job, JobSuggestion, Source
from jobhunter.services.dedupe import normalize_url


@dataclass
class AlertJob:
    title: str
    company: str | None
    location: str | None
    url: str


def _linkedin(href: str) -> str | None:
    m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", href)
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}" if m else None


def _unwrap_indeed_cts(href: str) -> str | None:
    """cts.indeed.com/v3/<gzip+base64 JSON>/… click trackers carry the real link as "u"."""
    m = re.search(r"cts\.indeed\.com/v3/([A-Za-z0-9_-]+)", href)
    if not m:
        return None
    seg = m.group(1)
    try:
        data = json.loads(gzip.decompress(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))))
    except (ValueError, OSError, EOFError):
        return None
    url = data.get("u") if isinstance(data, dict) else None
    return url if isinstance(url, str) else None


def _indeed(href: str) -> str | None:
    href = _unwrap_indeed_cts(href) or href
    parts = urlsplit(href)
    host = (parts.hostname or "").lower()
    if not host.endswith("indeed.com"):
        return None
    query = parse_qs(parts.query)
    jk = query.get("jk", [None])[0]
    if not jk and parts.path.startswith("/pagead/clk"):
        # Sponsored listings: jrtk=5-cmh1-1-<tracking>-<job key>
        jrtk = query.get("jrtk", [""])[0]
        jk = jrtk.rsplit("-", 1)[-1] if jrtk.count("-") >= 4 else None
    if not jk or not re.fullmatch(r"[0-9a-f]{8,20}", jk):
        return None
    if host.startswith(("jobalert.", "click.", "engage.", "match.", "cts.")):
        host = "ca.indeed.com"
    return f"https://{host}/viewjob?jk={jk}"


def _glassdoor(href: str) -> str | None:
    parts = urlsplit(href)
    if "glassdoor." not in (parts.hostname or ""):
        return None
    query = parse_qs(parts.query)
    job_id = (query.get("jobListingId") or query.get("jl") or [None])[0]
    if not job_id or not job_id.isdigit():
        return None
    return f"https://www.glassdoor.ca/job-listing/?jl={job_id}"


def _jobbank(href: str) -> str | None:
    m = re.search(r"jobbank\.gc\.ca/jobsearch/jobposting/(\d+)", href)
    return f"https://www.jobbank.gc.ca/jobsearch/jobposting/{m.group(1)}" if m else None


# Source name -> canonicaliser. Sources without an entry (e.g. Eluta, Workopolis) are saved as
# emails but produce no suggestions until a parser is added (FR-019).
PARSERS: dict[str, Callable[[str], str | None]] = {
    "LinkedIn": _linkedin,
    "Indeed": _indeed,
    "Glassdoor": _glassdoor,
    "Job Bank": _jobbank,
}
_SEPARATORS = (" · ", " • ", " | ", " - ", " – ")
# Button labels that link to a job but are not its title; a later link with a real title wins.
_BUTTON_TEXT = {"view job", "apply now", "apply", "learn more", "see job", "view details"}


def _following_lines(anchor: Tag, canon: Callable[[str], str | None], limit: int = 3) -> list[str]:
    lines: list[str] = []
    for el in anchor.next_elements:
        if (
            isinstance(el, Tag)
            and el.name == "a"
            and el.get("href")
            and canon(html_lib.unescape(el["href"]))
        ):
            break
        if (
            isinstance(el, NavigableString)
            and not isinstance(el, Comment)
            and el.find_parent("a") is not anchor
        ):
            text = " ".join(str(el).split())
            if text and el.parent is not None and el.parent.name not in ("script", "style"):
                lines.append(text)
                if len(lines) >= limit:
                    break
    return lines


def _company_location(lines: list[str]) -> tuple[str | None, str | None]:
    if not lines:
        return None, None
    first = lines[0]
    for sep in _SEPARATORS:
        if sep in first:
            company, location = first.split(sep, 1)
            return company.strip() or None, location.strip() or None
    return first, (lines[1] if len(lines) > 1 else None)


def parse_alert(html: str | None, text: str, source_name: str) -> list[AlertJob]:
    canon = PARSERS.get(source_name)
    if canon is None or not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    jobs: dict[str, AlertJob] = {}
    for anchor in soup.find_all("a", href=True):
        url = canon(html_lib.unescape(anchor["href"]))
        if url is None:
            continue
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not title:
            continue  # image-only links
        if url in jobs and (
            jobs[url].title.lower() not in _BUTTON_TEXT or title.lower() in _BUTTON_TEXT
        ):
            continue  # the same job linked twice
        company, location = _company_location(_following_lines(anchor, canon))
        jobs[url] = AlertJob(title=title[:200], company=company, location=location, url=url)
    return list(jobs.values())


def create_suggestions(session: Session, email: EmailMessage, source: Source) -> int:
    """Store suggestions for an alert email; returns how many new ones were created."""
    created = 0
    raw_html = None
    from jobhunter.services.mail_store import parse_email, raw_path

    path = raw_path(email)
    if path is not None and path.exists():
        raw_html = parse_email(path.read_bytes()).body_html  # unsanitised links needed
    for job in parse_alert(raw_html or email.body_html, email.body_text, source.name):
        url_norm = normalize_url(job.url)
        if url_norm is None:
            continue
        exists = session.exec(
            select(JobSuggestion).where(
                JobSuggestion.user_id == email.user_id, JobSuggestion.url_norm == url_norm
            )
        ).first()
        if exists is not None:
            continue
        tracked = session.exec(
            select(Job).where(Job.user_id == email.user_id, Job.url_norm == url_norm)
        ).first()
        session.add(
            JobSuggestion(
                user_id=email.user_id,
                email_id=email.id,
                source_id=source.id,
                title=job.title,
                company=job.company,
                location=job.location,
                url=job.url,
                url_norm=url_norm,
                state="tracked" if tracked else "new",
                job_id=tracked.id if tracked else None,
            )
        )
        created += 1
    session.commit()
    return created
