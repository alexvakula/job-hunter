"""SC-004: table, board and dashboard load in under 2 s with 2,000 jobs."""

import time
from datetime import timedelta

import pytest
from sqlalchemy import insert, select

from jobhunter.db import today_local, utcnow
from jobhunter.models import Job, Source, StatusChange, UserAccount

STATUSES = ["new", "interested", "applied", "screening", "interview", "rejected", "ghosted"]


@pytest.mark.slow
def test_pages_fast_with_2000_jobs(make_user, user_client, session):
    make_user("sam")
    client = user_client("sam")
    uid = session.exec(select(UserAccount.id).where(UserAccount.username == "sam")).scalar_one()
    manual = session.exec(select(Source.id).where(Source.type == "manual")).scalar_one()
    now = utcnow()
    rows = [
        {
            "user_id": uid,
            "title": f"QA Lead {i}",
            "company": f"Company {i % 300}",
            "company_title_key": f"company {i}|qa lead {i}",
            "source_id": manual,
            "date_found": today_local() - timedelta(days=i % 120),
            "status": STATUSES[i % 7],
            "description": "Lorem ipsum " * 200,
            "work_mode": "unknown",
            "created_at": now,
            "updated_at": now,
        }
        for i in range(2000)
    ]
    session.execute(insert(Job), rows)
    job_ids = session.exec(select(Job.id).where(Job.user_id == uid)).scalars().all()
    history = []
    for n, job_id in enumerate(job_ids):
        start = now - timedelta(days=n % 90)
        history.append(
            {
                "job_id": job_id,
                "from_status": None,
                "to_status": "new",
                "effective_at": start,
                "recorded_at": start,
            }
        )
        history.append(
            {
                "job_id": job_id,
                "from_status": "new",
                "to_status": "applied",
                "effective_at": start + timedelta(days=1),
                "recorded_at": now,
            }
        )
    session.execute(insert(StatusChange), history)
    session.commit()

    for path in ("/jobs", "/jobs?q=lead&sort=company&dir=asc", "/board", "/board?closed=1", "/"):
        started = time.perf_counter()
        resp = client.get(path)
        elapsed = time.perf_counter() - started
        assert resp.status_code == 200, path
        assert elapsed < 2.0, f"{path} took {elapsed:.2f}s"
