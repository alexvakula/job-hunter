"""Best-effort pre-filling of a job from a fetched page or pasted text (research R7, FR-006).

Pure functions: no I/O, never raise on bad input. Fields that cannot be determined stay
empty; the user always reviews the draft before saving.
"""

import html as html_lib
import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from jobhunter.models import Currency, SalaryPeriod, WorkMode


@dataclass
class JobDraft:
    title: str | None = None
    company: str | None = None
    location: str | None = None
    work_mode: str = WorkMode.UNKNOWN.value
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    description: str = ""


# --- shared helpers ----------------------------------------------------------------------

_HYBRID = re.compile(r"\bhybrid\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|telecommut\w*|fully distributed)\b", re.I)
_ONSITE = re.compile(r"\b(on[- ]?site|in[- ]office|in the office)\b", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def detect_work_mode(text: str) -> str:
    if _HYBRID.search(text):
        return WorkMode.HYBRID.value
    if _REMOTE.search(text):
        return WorkMode.REMOTE.value
    if _ONSITE.search(text):
        return WorkMode.ONSITE.value
    return WorkMode.UNKNOWN.value


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = _CONTROL.sub("", html_lib.unescape(value)).strip()
    return value or None


_BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "tr", "section", "h1", "h2", "h3", "h4", "h5", "h6"]


def html_to_text(markup: str) -> str:
    if "&lt;" in markup and "<" not in markup:
        markup = html_lib.unescape(markup)
    soup = BeautifulSoup(markup, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "• ")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    lines = [_SPACES.sub(" ", line).strip() for line in soup.get_text().splitlines()]
    text = "\n".join(lines)
    return _MANY_NEWLINES.sub("\n\n", text).strip()


_SPACES = re.compile(r"[ \t ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


# --- salary --------------------------------------------------------------------------------

_MONEY = (
    r"(?P<c{i}>CAD|USD|C\$|CA\$|US\$|\$)?\s?"
    r"(?P<n{i}>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<k{i}>[kK]\b)?"
)
_SALARY_RE = re.compile(_MONEY.format(i=1) + r"(?:\s*(?:-|–|—|to)\s*" + _MONEY.format(i=2) + r")?")
_PERIOD_RE = re.compile(
    r"^\s*(?P<p>per\s+year|per\s+annum|a\s+year|/\s*year|/\s*yr|annually|yearly|"
    r"per\s+hour|an\s+hour|/\s*hour|/\s*hr|hourly)",
    re.I,
)


def _currency(code: str | None) -> str | None:
    if not code:
        return None
    code = code.upper()
    if code in {"CAD", "C$", "CA$"}:
        return Currency.CAD.value
    if code in {"USD", "US$"}:
        return Currency.USD.value
    return None


def _amount(number: str, k: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * 1000 if k else value


def parse_salary(text: str) -> dict:
    """First money-looking amount or range in the text, or {}."""
    for m in _SALARY_RE.finditer(text):
        period_match = _PERIOD_RE.match(text[m.end() : m.end() + 25])
        has_cue = any(m.group(g) for g in ("c1", "c2", "k1", "k2")) or period_match
        if not has_cue:
            continue
        k1, k2 = m.group("k1"), m.group("k2")
        low = _amount(m.group("n1"), k1)
        high = _amount(m.group("n2"), k2) if m.group("n2") else low
        if m.group("n2") and k2 and not k1 and low < 1000:
            low *= 1000
        if low > high:
            low, high = high, low
        if period_match:
            word = period_match.group("p").lower()
            period = SalaryPeriod.HOUR.value if "h" in word else SalaryPeriod.YEAR.value
        elif k1 or k2 or high >= 1000:
            period = SalaryPeriod.YEAR.value
        else:
            period = SalaryPeriod.HOUR.value
        snippet = m.group(0).strip() + (" " + period_match.group(0).strip() if period_match else "")
        return {
            "salary_min": round(low),
            "salary_max": round(high),
            "salary_currency": _currency(m.group("c1") or m.group("c2")),
            "salary_period": period,
            "salary_text": snippet,
        }
    return {}


# --- location ------------------------------------------------------------------------------

_REGIONS = (
    "AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT|"
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|"
    "NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
_CITY_RE = re.compile(r"\b([A-Z][a-zà-ÿ'.\-]+(?:\s[A-Z][a-zà-ÿ'.\-]+)*),\s*(" + _REGIONS + r")\b")


def _find_location(lines: list[str]) -> str | None:
    for line in lines:
        m = _CITY_RE.search(line)
        if m:
            return f"{m.group(1)}, {m.group(2)}"
    return None


# --- JSON-LD / HTML --------------------------------------------------------------------------


def _iter_nodes(data):
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])


def _is_posting(node: dict) -> bool:
    kind = node.get("@type")
    return kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _name(value) -> str | None:
    value = _first(value)
    if isinstance(value, dict):
        return _clean(value.get("name"))
    return _clean(value)


def _posting_location(posting: dict) -> str | None:
    place = _first(posting.get("jobLocation"))
    if isinstance(place, dict):
        address = place.get("address")
        if isinstance(address, dict):
            parts = [_clean(address.get("addressLocality")), _clean(address.get("addressRegion"))]
            parts = [p for p in parts if p]
            if parts:
                return ", ".join(parts)
        elif _clean(address):
            return _clean(address)
    return _name(posting.get("applicantLocationRequirements"))


def _posting_salary(posting: dict) -> dict:
    salary = posting.get("baseSalary")
    if not isinstance(salary, dict):
        return {}
    value = salary.get("value")
    currency = _currency(_clean(salary.get("currency")))
    if isinstance(value, dict):
        low = value.get("minValue", value.get("value"))
        high = value.get("maxValue", value.get("value"))
        unit = (_clean(value.get("unitText")) or "").upper()
    else:
        low = high = value
        unit = (_clean(salary.get("unitText")) or "").upper()
    try:
        low_i = round(float(low)) if low is not None else None
        high_i = round(float(high)) if high is not None else low_i
    except (TypeError, ValueError):
        return {}
    if low_i is None:
        return {}
    period = {"HOUR": SalaryPeriod.HOUR.value, "YEAR": SalaryPeriod.YEAR.value}.get(unit)
    text = f"{currency or ''} {low_i:,}" + (f"–{high_i:,}" if high_i != low_i else "")
    if period:
        text += f" per {period}"
    return {
        "salary_min": low_i,
        "salary_max": high_i,
        "salary_currency": currency,
        "salary_period": period,
        "salary_text": text.strip(),
    }


def _from_posting(posting: dict) -> JobDraft:
    description = (
        html_to_text(posting.get("description") or "")
        if isinstance(posting.get("description"), str)
        else ""
    )
    draft = JobDraft(
        title=_clean(posting.get("title")),
        company=_name(posting.get("hiringOrganization")),
        location=_posting_location(posting),
        description=description,
    )
    location_type = _first(posting.get("jobLocationType"))
    if isinstance(location_type, str) and location_type.upper() == "TELECOMMUTE":
        draft.work_mode = WorkMode.REMOTE.value
    else:
        draft.work_mode = detect_work_mode(f"{draft.title or ''}\n{description}")
    for key, value in _posting_salary(posting).items():
        setattr(draft, key, value)
    return draft


def from_html(markup: str, url: str) -> JobDraft:
    try:
        soup = BeautifulSoup(markup or "", "html.parser")
    except Exception:  # noqa: BLE001 - parser must never break the form
        return JobDraft()
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for node in _iter_nodes(data):
            if _is_posting(node):
                return _from_posting(node)

    def meta(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return _clean(tag.get("content")) if tag else None

    title = meta("og:title") or (_clean(soup.title.string) if soup.title else None)
    description = meta("og:description") or meta("description") or ""
    return JobDraft(title=title, company=meta("og:site_name"), description=description)


# --- pasted text -----------------------------------------------------------------------------

_LABEL_RE = re.compile(r"^(?P<label>[A-Za-z ]{2,20})\s*[:：]\s*(?P<value>.+)$")
_COMPANY_LABELS = {"company", "employer", "organization", "organisation", "hiring company"}
_LOCATION_LABELS = {"location", "where", "job location", "city"}
_TITLE_LABELS = {"title", "job title", "position", "role"}


def from_text(text: str) -> JobDraft:
    text = _CONTROL.sub("", text or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    draft = JobDraft(description=text.strip())
    if not lines:
        return draft

    labels: dict[str, str] = {}
    for line in lines[:15]:
        m = _LABEL_RE.match(line)
        if m:
            labels.setdefault(m.group("label").strip().lower(), m.group("value").strip())

    def labelled(names: set[str]) -> str | None:
        return next((labels[n] for n in names if n in labels), None)

    title = labelled(_TITLE_LABELS)
    company = labelled(_COMPANY_LABELS)
    if title is None:
        first = lines[0]
        if not _LABEL_RE.match(first):
            if " at " in first and company is None:
                title, company = (part.strip() for part in first.rsplit(" at ", 1))
            else:
                title = first
    if company is None:
        for line in lines[1:5]:
            if line.lower().startswith("at "):
                company = line[3:].strip()
                break

    location_label = labelled(_LOCATION_LABELS)
    location = _find_location([location_label] if location_label else []) or _find_location(
        lines[:10]
    )

    draft.title = title or None
    draft.company = company or None
    draft.location = location
    draft.work_mode = detect_work_mode(text)
    for key, value in parse_salary(text).items():
        setattr(draft, key, value)
    return draft
