"""Job Bank search through its public Atom feed (FR-002). Job Bank is Canada-only."""

import re
from datetime import datetime
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from jobhunter.models import LocationRule, TargetProfile
from jobhunter.services.extract import parse_salary
from jobhunter.services.search.postings import Posting, _rule_country, rule_city

FEED = "https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}
MAX_TITLES = 4


def queries(profile: TargetProfile, rules: list[LocationRule]) -> list[str]:
    """Feed URLs for each title (max 4) × Canadian place of a position."""
    titles = [profile.name, *profile.synonyms][:MAX_TITLES]
    places = []
    for rule in rules:
        if _rule_country(rule) != "CA":
            continue
        places.append(rule_city(rule) or "")
    urls = []
    for title in titles:
        for place in dict.fromkeys(places):
            urls.append(
                FEED
                + "?"
                + urlencode({"searchstring": title, "locationstring": place, "sort": "D"})
            )
    return urls


def _field(summary: str, label: str) -> str | None:
    m = re.search(rf"{label}:\s*(.+?)(?:\n|$)", summary)
    return m.group(1).strip() if m else None


def parse_feed(xml_text: str) -> list[Posting]:
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, DefusedXmlException):
        return []
    postings = []
    for entry in root.findall("a:entry", _ATOM):
        link = entry.find("a:link", _ATOM)
        url = (link.get("href") if link is not None else "") or ""
        title = (entry.findtext("a:title", "", _ATOM) or "").strip()
        if not url or not title:
            continue
        summary_html = entry.findtext("a:summary", "", _ATOM) or ""
        summary = BeautifulSoup(
            summary_html.replace("<br />", "\n").replace("<br/>", "\n"), "html.parser"
        ).get_text()
        salary_text = _field(summary, "Salary")
        salary = parse_salary(salary_text or "")
        updated = entry.findtext("a:updated", "", _ATOM)
        try:
            posted = datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
        except ValueError:
            posted = None
        postings.append(
            Posting(
                title=title[:1].upper() + title[1:],
                url=url.split("?")[0],
                company=_field(summary, "Employer"),
                location=_field(summary, "Location"),
                description=summary.strip(),
                salary_text=salary_text,
                salary_min=salary.get("salary_min"),
                salary_max=salary.get("salary_max"),
                currency="CAD" if salary else None,
                period=salary.get("salary_period"),
                posted_at=posted,
            )
        )
    return postings
