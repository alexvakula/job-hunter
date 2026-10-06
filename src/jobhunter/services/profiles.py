"""Target-position profiles and their location rules (FR-026–FR-027).

Profiles belong to one user. Each has one or more location rules: a place, the work modes
accepted there and an optional salary floor in that place's currency.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import delete, update
from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import Currency, Job, LocationRule, Source, TargetProfile, WorkMode

RULE_MODES = (WorkMode.ONSITE.value, WorkMode.HYBRID.value, WorkMode.REMOTE.value)
MAX_RULES = 20
_RULE_KEY = re.compile(r"^rules-(\d+)-")


@dataclass
class RuleInput:
    place: str = ""
    work_modes: list[str] = field(default_factory=list)
    floor: str = ""
    currency: str = ""


@dataclass
class ProfileInput:
    name: str = ""
    synonyms: str = ""
    include_keywords: str = ""
    exclude_keywords: str = ""
    seniority: str = ""
    source_ids: list[str] = field(default_factory=list)
    rules: list[RuleInput] = field(default_factory=list)


@dataclass
class Validated:
    profile: dict = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def split_list(raw: str) -> list[str]:
    """'a, b,,c' -> ['a', 'b', 'c'] keeping order, dropping duplicates."""
    seen: list[str] = []
    for part in (raw or "").replace("\n", ",").split(","):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return seen


def parse_form(form) -> ProfileInput:
    """Build input from form fields rules-<i>-place/-onsite/-hybrid/-remote/-floor/-currency."""
    indexes = sorted({int(m.group(1)) for k in form.keys() if (m := _RULE_KEY.match(k))})
    rules = []
    for i in indexes[:MAX_RULES]:
        prefix = f"rules-{i}-"
        rules.append(
            RuleInput(
                place=str(form.get(prefix + "place") or "").strip(),
                work_modes=[m for m in RULE_MODES if form.get(prefix + m)],
                floor=str(form.get(prefix + "floor") or "").strip(),
                currency=str(form.get(prefix + "currency") or "").strip(),
            )
        )
    return ProfileInput(
        name=str(form.get("name") or "").strip(),
        synonyms=str(form.get("synonyms") or ""),
        include_keywords=str(form.get("include_keywords") or ""),
        exclude_keywords=str(form.get("exclude_keywords") or ""),
        seniority=str(form.get("seniority") or "").strip(),
        source_ids=[str(v) for v in form.getlist("source_ids")],
        rules=rules,
    )


def validate(
    session: Session, user_id: int, data: ProfileInput, profile_id: int | None = None
) -> Validated:
    v = Validated()
    errors = v.errors
    if not data.name:
        errors["name"] = "Name is required."
    else:
        clash = session.exec(
            select(TargetProfile).where(
                TargetProfile.user_id == user_id, TargetProfile.name == data.name
            )
        ).first()
        if clash is not None and clash.id != profile_id:
            errors["name"] = "You already have a target position with this name."

    known_sources = set(session.exec(select(Source.id)).all())
    source_ids: list[int] = []
    for raw in data.source_ids:
        try:
            sid = int(raw)
        except ValueError:
            sid = None
        if sid not in known_sources:
            errors["source_ids"] = "Unknown source."
        elif sid not in source_ids:
            source_ids.append(sid)

    for index, rule in enumerate(data.rules):
        if not (rule.place or rule.work_modes or rule.floor):
            continue  # blank row
        prefix = f"rules-{index}"
        if not rule.place:
            errors[f"{prefix}-place"] = "Enter a place."
        if not rule.work_modes:
            errors[f"{prefix}-modes"] = "Pick at least one work mode."
        floor = None
        if rule.floor:
            try:
                floor = int(float(rule.floor.replace(",", "")))
                if floor < 0:
                    raise ValueError
            except ValueError:
                errors[f"{prefix}-floor"] = "Enter a yearly amount, e.g. 130000."
        currency = rule.currency or None
        if currency is not None and currency not in set(Currency):
            errors[f"{prefix}-currency"] = "Choose CAD or USD."
        if floor is not None and currency is None:
            errors[f"{prefix}-currency"] = "Choose the currency for the salary floor."
        v.rules.append(
            {
                "place": rule.place,
                "work_modes": rule.work_modes,
                "salary_floor": floor,
                "salary_currency": currency if floor is not None else None,
            }
        )
    if not v.rules:
        errors["rules"] = "Add at least one place (for example Calgary, AB or USA)."

    v.profile = {
        "name": data.name,
        "synonyms": split_list(data.synonyms),
        "include_keywords": split_list(data.include_keywords),
        "exclude_keywords": split_list(data.exclude_keywords),
        "seniority": data.seniority or None,
        "source_ids": source_ids,
    }
    return v


def _replace_rules(session: Session, profile: TargetProfile, rules: list[dict]) -> None:
    session.exec(delete(LocationRule).where(LocationRule.profile_id == profile.id))
    for rule in rules:
        session.add(LocationRule(profile_id=profile.id, **rule))


def create_profile(session: Session, user_id: int, v: Validated) -> TargetProfile:
    profile = TargetProfile(user_id=user_id, **v.profile)
    session.add(profile)
    session.flush()
    _replace_rules(session, profile, v.rules)
    session.commit()
    session.refresh(profile)
    return profile


def update_profile(session: Session, profile: TargetProfile, v: Validated) -> TargetProfile:
    for key, value in v.profile.items():
        setattr(profile, key, value)
    profile.updated_at = utcnow()
    session.add(profile)
    _replace_rules(session, profile, v.rules)
    session.commit()
    session.refresh(profile)
    return profile


def rules_for(session: Session, profile: TargetProfile) -> list[LocationRule]:
    return list(
        session.exec(
            select(LocationRule)
            .where(LocationRule.profile_id == profile.id)
            .order_by(LocationRule.id)
        ).all()
    )


def set_default(session: Session, profile: TargetProfile) -> None:
    """Make this the user's only default (FR-027). Archived profiles can't be default."""
    session.exec(
        update(TargetProfile)
        .where(TargetProfile.user_id == profile.user_id, TargetProfile.id != profile.id)
        .values(is_default=False)
    )
    profile.is_default = True
    profile.is_archived = False
    session.add(profile)
    session.commit()


def set_archived(session: Session, profile: TargetProfile, archived: bool) -> None:
    profile.is_archived = archived
    if archived:
        profile.is_default = False
    session.add(profile)
    session.commit()


def delete_profile(session: Session, profile: TargetProfile) -> None:
    session.exec(update(Job).where(Job.profile_id == profile.id).values(profile_id=None))
    session.exec(delete(LocationRule).where(LocationRule.profile_id == profile.id))
    session.delete(profile)
    session.commit()


def default_profile_id(session: Session, user_id: int) -> int | None:
    return session.exec(
        select(TargetProfile.id).where(
            TargetProfile.user_id == user_id,
            TargetProfile.is_default.is_(True),
            TargetProfile.is_archived.is_(False),
        )
    ).first()
