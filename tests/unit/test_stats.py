from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

from jobhunter.db import local_to_utc, today_local
from jobhunter.models import FollowUp, Job, Source, StatusChange
from jobhunter.services import stats


@pytest.fixture
def setup(session, make_user):
    alice = make_user("alice")
    bob = make_user("bob")
    manual = session.exec(select(Source).where(Source.type == "manual")).one()

    def job(user=alice, status="new", title="T", history=()):
        j = Job(
            user_id=user.id,
            title=title,
            company="C",
            company_title_key="c|t",
            source_id=manual.id,
            date_found=today_local(),
            status=status,
        )
        session.add(j)
        session.flush()
        prev = None
        for local_dt, to in history:
            session.add(
                StatusChange(
                    job_id=j.id, from_status=prev, to_status=to, effective_at=local_to_utc(local_dt)
                )
            )
            prev = to
        session.commit()
        session.refresh(j)
        return j

    return {"alice": alice, "bob": bob, "job": job, "session": session}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def test_applications_per_week_uses_first_applied_entry(setup):
    today = today_local()
    this_week = datetime.combine(_monday(today), datetime.min.time()) + timedelta(hours=10)
    last_week = this_week - timedelta(days=7)
    j = setup["job"]
    j(history=[(last_week, "new"), (last_week, "applied")])
    j(
        history=[
            (this_week, "new"),
            (this_week, "applied"),
            (this_week, "rejected"),
            (this_week + timedelta(minutes=5), "applied"),
        ]
    )  # re-applied: counted once
    j(user=setup["bob"], history=[(this_week, "applied")])  # other user ignored
    weeks = stats.applications_per_week(setup["session"], setup["alice"].id)
    assert len(weeks) == 12
    assert weeks[-1] == (_monday(today), 1)
    assert weeks[-2] == (_monday(today) - timedelta(days=7), 1)
    assert sum(n for _, n in weeks) == 2


def test_applications_older_than_12_weeks_not_shown(setup):
    old = datetime.combine(today_local() - timedelta(weeks=20), datetime.min.time())
    setup["job"](history=[(old, "applied")])
    assert sum(n for _, n in stats.applications_per_week(setup["session"], setup["alice"].id)) == 0


def test_response_rate(setup):
    t0 = datetime(2026, 9, 1, 9, 0)
    j = setup["job"]
    j(history=[(t0, "applied"), (t0 + timedelta(days=3), "screening")])  # responded
    j(history=[(t0, "applied"), (t0 + timedelta(days=9), "rejected")])  # responded
    j(history=[(t0, "applied")])  # no response yet
    j(history=[(t0, "applied"), (t0 + timedelta(days=30), "ghosted")])  # no response
    j(history=[(t0, "interview"), (t0 + timedelta(days=1), "applied")])  # interview before apply
    j(history=[(t0, "interested")])  # never applied: not counted
    rate = stats.response_rate(setup["session"], setup["alice"].id)
    assert rate.applied == 5 and rate.responded == 2
    assert rate.percent == 40


def test_response_rate_no_data(setup):
    rate = stats.response_rate(setup["session"], setup["alice"].id)
    assert rate.applied == 0 and rate.percent is None


def test_counts_per_status(setup):
    j = setup["job"]
    j(status="new")
    j(status="new")
    j(status="applied")
    j(user=setup["bob"], status="applied")
    counts = stats.counts_per_status(setup["session"], setup["alice"].id)
    assert counts["new"] == 2 and counts["applied"] == 1 and counts["offer"] == 0


def test_due_follow_ups(setup):
    session = setup["session"]
    j1 = setup["job"](title="Due")
    j2 = setup["job"](user=setup["bob"], title="Bob")
    today = today_local()
    session.add_all(
        [
            FollowUp(job_id=j1.id, due_date=today, description="call"),
            FollowUp(job_id=j1.id, due_date=today - timedelta(days=2), description="late"),
            FollowUp(job_id=j1.id, due_date=today + timedelta(days=1), description="future"),
            FollowUp(job_id=j1.id, due_date=today, description="done", done=True),
            FollowUp(job_id=j2.id, due_date=today, description="bob's"),
        ]
    )
    session.commit()
    due = stats.due_follow_ups(session, setup["alice"].id)
    assert [f.description for f, _ in due] == ["late", "call"]
    assert all(job.title == "Due" for _, job in due)
