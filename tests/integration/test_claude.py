import json

import pytest
from sqlmodel import select

from jobhunter.models import ClaudeJob, JobSuggestion, TailoredResume, UserAccount
from jobhunter.services.claude import queue
from tests.claude_helpers import fake_claude  # noqa: F401
from tests.integration.test_apply import _master_form
from tests.resume_data import POSTING, resume_docx_bytes
from tests.search_helpers import qa_lead


@pytest.fixture
def admin(make_user, user_client, session, fake_claude):  # noqa: F811
    make_user("alice", role="admin")
    make_user("bob")
    a = user_client("alice")
    assert a.post("/resume", data=_master_form()).status_code == 303
    uid = session.exec(select(UserAccount.id).where(UserAccount.username == "alice")).one()
    qa_lead(session, uid)
    return a, user_client("bob"), uid, fake_claude


def _run_queue(session):
    done = []
    while (job := queue.process_next(session)) is not None:
        done.append(job)
    return done


def test_non_admin_cannot_use_claude(admin):
    _, bob, _, _ = admin
    for path in ("/claude", "/claude/jobs/1"):
        assert bob.get(path).status_code == 403
    for path in ("/claude/find", "/claude/rank", "/resume/claude-import", "/jobs/1/apply/claude"):
        assert bob.post(path).status_code == 403
    assert "Find jobs with Claude" not in bob.get("/suggestions").text
    assert "/claude" not in bob.get("/jobs").text.split("<main")[0]


def test_buttons_hidden_without_token(admin, monkeypatch):
    alice, _, _, _ = admin
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    assert "Find jobs with Claude" not in alice.get("/suggestions").text
    page = alice.get("/claude").text
    assert "not configured" in page and "setup-token" in page
    assert alice.post("/claude/find").status_code == 409


def test_find_jobs_creates_checked_suggestions_and_ranks(admin, session):
    alice, _, uid, fake = admin
    alice.post(
        "/jobs",
        data={
            "title": "QA Lead",
            "company": "Tracked Co",
            "url": "https://jobs.lever.co/tracked/1",
        },
    )
    fake.respond(
        {
            "jobs": [
                {
                    "title": "QA Lead",
                    "company": "Acme",
                    "location": "Calgary, AB",
                    "url": "https://jobs.lever.co/acme/1?utm_source=x",
                    "work_mode": "hybrid",
                    "summary": "Lead QA.",
                },
                {
                    "title": "Test Manager",
                    "company": "Beta",
                    "location": "Remote - United States",
                    "url": "https://boards.greenhouse.io/beta/jobs/2",
                    "work_mode": "remote",
                },
                {
                    "title": "QA Lead",
                    "company": "Gamma",
                    "location": "Toronto, ON",
                    "url": "https://jobs.lever.co/gamma/3",
                },
                {
                    "title": "QA Lead",
                    "company": "Tracked Co",
                    "location": "Calgary, AB",
                    "url": "https://jobs.lever.co/tracked/1",
                },
            ]
        }
    )
    resp = alice.post("/claude/find")
    assert resp.status_code == 303
    job_url = resp.headers["location"]
    assert "queued" in alice.get(job_url).text
    [find] = _run_queue(session)[:1]
    assert find.status == "done", find.error
    assert "4 postings found, 2 new suggestions" in find.summary
    rows = session.exec(
        select(JobSuggestion).where(JobSuggestion.origin == "claude", JobSuggestion.state == "new")
    ).all()
    assert sorted(r.company for r in rows) == ["Acme", "Beta"]
    tracked = session.exec(select(JobSuggestion).where(JobSuggestion.state == "tracked")).one()
    assert tracked.company == "Tracked Co" and tracked.job_id is not None
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert "Calgary, AB" in fake.calls[0]["stdin"] and "QA Lead" in fake.calls[0]["stdin"]
    rank = session.exec(select(ClaudeJob).where(ClaudeJob.kind == "fit_rank")).one()
    assert rank.payload["suggestion_ids"] == sorted(r.id for r in rows)


def test_fit_rank(admin, session):
    alice, _, uid, fake = admin
    for i, title in enumerate(("QA Lead", "Test Lead", "QA Manager")):
        session.add(
            JobSuggestion(
                user_id=uid,
                title=title,
                url=f"https://x.io/{i}",
                url_norm=f"https://x.io/{i}",
                description="Selenium",
            )
        )
    session.commit()
    ids = [s.id for s in session.exec(select(JobSuggestion)).all()]
    fake.respond(
        {
            "rankings": [
                {"id": ids[0], "score": 88, "reason": "Strong QA leadership."},
                {"id": ids[1], "score": 40, "reason": "Different stack."},
                {"id": 99999, "score": 100, "reason": "not sent"},
            ]
        }
    )
    alice.post("/claude/rank")
    [job] = _run_queue(session)
    assert job.status == "done" and job.summary == "2 suggestions ranked."
    session.expire_all()
    s0 = session.get(JobSuggestion, ids[0])
    assert (s0.fit_score, s0.fit_reason) == (88, "Strong QA leadership.")
    assert session.get(JobSuggestion, ids[2]).fit_score is None
    assert "Strong QA leadership." in alice.get("/suggestions?sort=fit").text
    assert "Ship" not in json.dumps(fake.calls[0]["argv"])
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--tools") + 1] == ""


def test_fit_rank_out_of_range_fails(admin, session):
    alice, _, uid, fake = admin
    session.add(
        JobSuggestion(user_id=uid, title="QA", url="https://x.io/1", url_norm="https://x.io/1")
    )
    session.commit()
    fake.respond({"rankings": [{"id": 1, "score": 150, "reason": "x"}]})
    alice.post("/claude/rank")
    [job] = _run_queue(session)
    assert job.status == "failed" and "expected structure" in job.error


def test_tailor_with_claude_stays_honest(admin, session):
    alice, _, uid, fake = admin
    job_id = int(
        alice.post(
            "/jobs", data={"title": "QA Lead", "company": "Acme Robotics", "description": POSTING}
        )
        .headers["location"]
        .rsplit("/", 1)[1]
    )
    fake.respond(
        {
            "summary": "QA leader driving test automation. Expert in Kubernetes.",
            "bullets": [
                {
                    "ref": "e1:1",
                    "text": "Built a Selenium/Python test automation framework (1,200 cases).",
                },
                {"ref": "zz:9", "text": "Invented bullet at Google."},
            ],
            "cover_letter": "Dear Hiring Manager,\n\nI lead QA teams.\n\nSam",
        }
    )
    alice.post(f"/jobs/{job_id}/apply/claude")
    [job] = _run_queue(session)
    assert job.status == "done" and "Kubernetes" in job.summary
    # writing for employers uses the strongest model
    argv = fake.calls[-1]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5" == job.model
    assert "Opus 5.5" in alice.get("/claude").text
    t = session.exec(select(TailoredResume)).one()
    texts = [b["text"] for e in t.experience for b in e["bullets"]]
    assert "Built a Selenium/Python test automation framework (1,200 cases)." in texts
    assert not any("Google" in x for x in texts) and len(texts) == 6
    page = alice.get(f"/jobs/{job_id}/apply").text
    assert "Not in your master resume:</strong> Kubernetes" in page
    assert alice.post(f"/jobs/{job_id}/apply/generate").status_code == 409


def test_import_with_claude_opens_unsaved(admin, session):
    alice, _, uid, fake = admin
    alice.post("/settings/resume", files={"file": ("cv.docx", resume_docx_bytes())})
    data = {
        "name": "Sam Rivera",
        "email": "a@example.org",
        "phone": "",
        "location": "",
        "links": [],
        "summary": "QA leader.",
        "skills": ["Selenium"],
        "education": [],
        "certifications": [],
        "experience": [
            {
                "employer": "Northwind Imaging",
                "title": "QA Lead",
                "location": "",
                "start": "2020",
                "end": "Present",
                "bullets": ["Built it."],
            }
        ],
    }
    fake.respond(data)
    alice.post("/resume/claude-import")
    [job] = _run_queue(session)
    assert job.status == "done"
    assert "Built a Selenium test automation framework." in fake.calls[0]["stdin"]
    page = alice.get(f"/resume/claude-import/{job.id}").text
    assert "Imported from" in page and 'value="QA Lead"' in page and "QA leader." in page
    from jobhunter.models import MasterResume

    session.expire_all()
    assert session.get(MasterResume, uid).data["summary"] != "QA leader."  # not saved


def test_one_at_a_time_and_interrupted(admin, session):
    alice, _, uid, _ = admin
    queue._run_lock.acquire()
    try:
        alice.post("/claude/rank")
        assert queue.process_next(session) is None  # another job holds the lock
    finally:
        queue._run_lock.release()
    job = session.exec(select(ClaudeJob)).one()
    job.status = "running"
    session.add(job)
    session.commit()
    queue.mark_interrupted(session)
    session.refresh(job)
    assert job.status == "failed" and "Interrupted" in job.error


def test_duplicate_enqueue_returns_same_job(admin, session):
    alice, _, _, _ = admin
    first = alice.post("/claude/find").headers["location"]
    second = alice.post("/claude/find").headers["location"]
    assert first == second


def test_daily_queue(admin, session, monkeypatch):
    import datetime as dt

    from jobhunter.services import scheduler

    monkeypatch.setattr(scheduler, "utcnow", lambda: dt.datetime(2026, 10, 6, 13, 0, tzinfo=dt.UTC))
    scheduler.queue_daily_claude(session)
    scheduler.queue_daily_claude(session)
    jobs = session.exec(select(ClaudeJob).where(ClaudeJob.kind == "find_jobs")).all()
    assert len(jobs) == 1
    monkeypatch.setenv("CLAUDE_DAILY", "off")
    session.delete(jobs[0])
    session.commit()
    scheduler.queue_daily_claude(session)
    assert session.exec(select(ClaudeJob)).all() == []
