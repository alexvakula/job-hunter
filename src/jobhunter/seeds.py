"""Starting data for the first admin (data-model.md "Seed for the first admin", FR-026a)."""

from sqlmodel import Session, select

from jobhunter.models import SenderSettings, Source, TargetProfile, UserAccount
from jobhunter.services import profiles

QA_LEAD = {
    "name": "QA Lead",
    "synonyms": ["Test Manager", "QA Manager", "Test Lead"],
    "include_keywords": [],
    "exclude_keywords": [],
    "seniority": None,
}
QA_LEAD_RULES = [
    {
        "place": "Calgary, AB",
        "work_modes": ["onsite", "hybrid", "remote"],
        "salary_floor": 130000,
        "salary_currency": "CAD",
    },
    {
        "place": "Vancouver, BC",
        "work_modes": ["onsite", "hybrid", "remote"],
        "salary_floor": 130000,
        "salary_currency": "CAD",
    },
    {"place": "USA", "work_modes": ["remote"], "salary_floor": 130000, "salary_currency": "USD"},
]


# Feature 002: applications are sent from the job-only mailbox.
SAM_SENDER = {
    "from_address": "sam.jobs@example.org",
    "display_name": "Sam Rivera",
    "reply_to": "sam.jobs@example.org",
    "smtp_host": "smtp.example.org",
    "smtp_port": 587,
    "smtp_username": "sam.jobs@example.org",
    "signature": "",
    "bcc_self": False,
}


class SeedError(RuntimeError):
    pass


def apply_first_admin_defaults(session: Session, user: UserAccount) -> list[str]:
    """Add whatever of the defaults is missing; returns what was added (FR-026a, FR-029a)."""
    added: list[str] = []
    existing = session.exec(
        select(TargetProfile).where(
            TargetProfile.user_id == user.id, TargetProfile.name == QA_LEAD["name"]
        )
    ).first()
    if existing is None:
        sources = session.exec(select(Source.id).where(Source.enabled.is_(True))).all()
        validated = profiles.Validated(
            profile={**QA_LEAD, "source_ids": list(sources)},
            rules=[dict(r) for r in QA_LEAD_RULES],
        )
        profile = profiles.create_profile(session, user.id, validated)
        profiles.set_default(session, profile)
        added.append("QA Lead profile")
    if session.get(SenderSettings, user.id) is None:
        session.add(SenderSettings(user_id=user.id, **SAM_SENDER))
        session.commit()
        added.append("sender settings")
    if not added:
        raise SeedError(f"'{user.username}' already has the default profile and sender settings")
    return added
