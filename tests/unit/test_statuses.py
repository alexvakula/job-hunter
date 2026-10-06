from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from jobhunter.db import local_to_utc, today_local, utcnow
from jobhunter.models import Job, Source, Status, StatusChange
from jobhunter.services.statuses import StatusError, change_status, parse_effective, timeline


@pytest.fixture
def job(session, make_user):
    user = make_user("alice")
    manual = session.exec(select(Source).where(Source.type == "manual")).one()
    job = Job(
        user_id=user.id,
        title="QA Lead",
        company="Acme",
        company_title_key="acme|qa lead",
        source_id=manual.id,
        date_found=today_local(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@pytest.mark.parametrize("target", [s.value for s in Status if s != Status.NEW])
def test_any_status_reachable_from_new(session, job, target):
    entry = change_status(session, job, target)
    assert job.status == target
    assert (entry.from_status, entry.to_status) == ("new", target)


def test_any_to_any_including_backwards(session, job):
    for target in ("offer", "new", "rejected", "interview", "ghosted", "applied"):
        change_status(session, job, target)
        assert job.status == target
    assert len(timeline(session, job)) == 6


def test_same_status_writes_nothing(session, job):
    assert change_status(session, job, "new") is None
    assert timeline(session, job) == []


def test_invalid_status_rejected(session, job):
    with pytest.raises(StatusError):
        change_status(session, job, "hired")
    assert job.status == "new"


def test_effective_defaults_to_now(session, job):
    before = utcnow()
    entry = change_status(session, job, "applied")
    assert before <= entry.effective_at <= utcnow()


def test_backdated_effective_time(session, job):
    yesterday = utcnow() - timedelta(days=1)
    entry = change_status(session, job, "applied", effective_at=yesterday)
    assert entry.effective_at == yesterday
    assert entry.recorded_at > entry.effective_at


def test_future_more_than_one_day_rejected(session, job):
    with pytest.raises(StatusError):
        change_status(session, job, "applied", effective_at=utcnow() + timedelta(days=2))
    assert job.status == "new"
    change_status(session, job, "applied", effective_at=utcnow() + timedelta(hours=12))
    assert job.status == "applied"


def test_timeline_ordered_by_effective_time(session, job):
    now = utcnow()
    change_status(session, job, "applied", effective_at=now)
    change_status(session, job, "interested", effective_at=now - timedelta(days=3))
    assert [e.to_status for e in timeline(session, job)] == ["interested", "applied"]


def test_history_rows_are_never_modified(session, job):
    change_status(session, job, "applied")
    first = session.exec(select(StatusChange)).one()
    snapshot = first.model_dump()
    change_status(session, job, "rejected")
    change_status(session, job, "applied")
    session.refresh(first)
    assert first.model_dump() == snapshot
    assert len(session.exec(select(StatusChange)).all()) == 3


def test_parse_effective_uses_app_timezone(db_path):
    parsed = parse_effective("2026-10-04T09:30")
    assert parsed == local_to_utc(datetime(2026, 10, 4, 9, 30))
    assert parsed.hour == 15  # America/Edmonton is UTC-6 in October
    assert parse_effective("") is None
    with pytest.raises(StatusError):
        parse_effective("yesterday")
