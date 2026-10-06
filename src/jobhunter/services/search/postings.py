"""Postings from automatic searches, and the rules that match and score them (FR-005, FR-011)."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from jobhunter.models import LocationRule, TargetProfile

HOURS_PER_YEAR = 2080
_WORD = re.compile(r"[a-z0-9+#]+")
_US_STATES = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}
_PROVINCES = {
    "ab",
    "bc",
    "mb",
    "nb",
    "nl",
    "ns",
    "nt",
    "nu",
    "on",
    "pe",
    "qc",
    "sk",
    "yt",
    "alberta",
    "ontario",
    "quebec",
    "manitoba",
    "saskatchewan",
    "yukon",
    "nunavut",
}
_US_WORDS = {"usa", "us", "united states", "america", "u.s.", "u.s.a."}
_CANADA_WORDS = {"canada", "ca"}


@dataclass
class Posting:
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    description: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    period: str | None = None
    remote: bool | None = None
    work_mode: str | None = None  # onsite | hybrid | remote
    posted_at: datetime | None = None
    detail_url: str | None = None  # where a full description can be fetched, if not included


@dataclass
class Match:
    profile_id: int
    score: int
    reasons: list[str] = field(default_factory=list)


# Same discipline, different names: all count as "qa" when matching titles. ("testing" is
# deliberately not mapped to "test": "Compliance Lead, Testing" is not a Test Lead.)
_QA_EQUIVALENTS = re.compile(r"\b(quality assurance|quality engineering|qe)\b")


def words(text: str | None) -> list[str]:
    text = _QA_EQUIVALENTS.sub("qa", (text or "").lower())
    return _WORD.findall(text)


def _title_points(title: str, phrases: list[str]) -> tuple[int, str | None]:
    title_words = words(title)
    joined = " ".join(title_words)
    best, why = 0, None
    for phrase in phrases:
        p = words(phrase)
        if not p:
            continue
        if f" {' '.join(p)} " in f" {joined} ":
            return 50, f"title matches “{phrase}”"
        if all(w in title_words for w in p) and best < 35:
            best, why = 35, f"title has the words of “{phrase}”"
    return best, why


def country_of(location: str | None) -> str | None:
    text = (location or "").lower()
    tokens = set(_WORD.findall(text))
    if any(w in text for w in ("united states", "u.s.")) or tokens & {"usa", "us"}:
        return "US"
    if "canada" in text or tokens & _PROVINCES:
        return "CA"
    parts = [p.strip() for p in re.split(r"[,(]", text) if p.strip()]
    if parts and parts[-1].strip(") ") in _US_STATES:
        return "US"
    return None


def _mode(posting: Posting) -> str | None:
    if posting.work_mode:
        return posting.work_mode
    if posting.remote or "remote" in (posting.location or "").lower():
        return "remote"
    return None


def _rule_country(rule: LocationRule) -> str | None:
    place = rule.place.lower().strip()
    if place in _US_WORDS:
        return "US"
    if place in _CANADA_WORDS:
        return "CA"
    return country_of(rule.place)


def _is_country_rule(rule: LocationRule) -> bool:
    place = rule.place.lower().strip()
    return place in _US_WORDS or place in _CANADA_WORDS


def rule_city(rule: LocationRule) -> str | None:
    if _is_country_rule(rule):
        return None
    return rule.place.split(",")[0].strip() or None


def place_match(posting: Posting, rule: LocationRule) -> str | None:
    mode = _mode(posting)
    if mode and mode not in rule.work_modes:
        return None
    posting_country = country_of(posting.location)
    if _is_country_rule(rule):
        # Unknown work mode only counts when the rule accepts more than remote work.
        confirmed = mode is not None or bool(set(rule.work_modes) - {"remote"})
        if posting_country == _rule_country(rule) and confirmed:
            return f"{rule.place} ({mode or 'any mode'})"
        return None
    city = rule_city(rule)
    if city and set(words(city)) <= set(words(posting.location)):
        return city
    if mode == "remote" and "remote" in rule.work_modes and posting_country == _rule_country(rule):
        return f"remote in {'Canada' if posting_country == 'CA' else posting_country}"
    return None


def _annual(value: int | None, period: str | None) -> int | None:
    if value is None:
        return None
    return value * HOURS_PER_YEAR if period == "hour" else value


def _salary_points(posting: Posting, rule: LocationRule) -> tuple[int, str]:
    if rule.salary_floor is None:
        return 10, "no salary floor set"
    top = _annual(posting.salary_max or posting.salary_min, posting.period)
    if top is None or posting.currency != rule.salary_currency:
        return 10, "salary not stated"
    if top >= rule.salary_floor:
        return 20, f"salary ≥ {rule.salary_currency} {rule.salary_floor:,}"
    return 0, f"salary below {rule.salary_currency} {rule.salary_floor:,}"


def _keywords_ok(posting: Posting, profile: TargetProfile) -> bool:
    text = f"{posting.title}\n{posting.description or ''}".lower()
    if any(k.lower() in text for k in profile.exclude_keywords):
        return False
    if profile.include_keywords and not any(k.lower() in text for k in profile.include_keywords):
        return False
    return True


def match(posting: Posting, profile: TargetProfile, rules: list[LocationRule]) -> Match | None:
    title_pts, title_why = _title_points(posting.title, [profile.name, *profile.synonyms])
    if not title_pts or not _keywords_ok(posting, profile):
        return None
    best: Match | None = None
    for rule in rules:
        where = place_match(posting, rule)
        if where is None:
            continue
        salary_pts, salary_why = _salary_points(posting, rule)
        candidate = Match(profile.id, title_pts + 30 + salary_pts, [title_why, where, salary_why])
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def best_match(
    posting: Posting, profiles: list[tuple[TargetProfile, list[LocationRule]]]
) -> Match | None:
    matches = [m for p, rules in profiles if (m := match(posting, p, rules))]
    return max(matches, key=lambda m: m.score) if matches else None
