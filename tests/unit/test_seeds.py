import pytest
from sqlmodel import select

from jobhunter.cli import create_admin, seed_defaults
from jobhunter.models import LocationRule, Source, TargetProfile, UserAccount
from jobhunter.seeds import SeedError, apply_first_admin_defaults

PW = "a long enough password"


def _sam(session):
    return session.exec(select(UserAccount).where(UserAccount.username == "sam")).one()


def test_create_admin_with_seed_defaults(session):
    assert create_admin("sam", "Sam Rivera", True, password=PW) == 0
    profile = session.exec(select(TargetProfile)).one()
    assert profile.user_id == _sam(session).id
    assert profile.name == "QA Lead" and profile.is_default
    assert profile.synonyms == ["Test Manager", "QA Manager", "Test Lead"]
    enabled = session.exec(select(Source.id).where(Source.enabled.is_(True))).all()
    assert sorted(profile.source_ids) == sorted(enabled)
    rules = session.exec(select(LocationRule).order_by(LocationRule.id)).all()
    assert [(r.place, sorted(r.work_modes), r.salary_floor, r.salary_currency) for r in rules] == [
        ("Calgary, AB", ["hybrid", "onsite", "remote"], 130000, "CAD"),
        ("Vancouver, BC", ["hybrid", "onsite", "remote"], 130000, "CAD"),
        ("USA", ["remote"], 130000, "USD"),
    ]


def test_seed_refuses_twice(session):
    create_admin("sam", "Sam Rivera", True, password=PW)
    with pytest.raises(SeedError):
        apply_first_admin_defaults(session, _sam(session))
    assert len(session.exec(select(TargetProfile)).all()) == 1


def test_seed_existing_user_via_cli(session):
    create_admin("sam", "Sam Rivera", False, password=PW)
    assert session.exec(select(TargetProfile)).all() == []
    assert seed_defaults("sam") == 0
    assert len(session.exec(select(TargetProfile)).all()) == 1
    assert seed_defaults("sam") == 1
    assert seed_defaults("nobody") == 1
