import re
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from jobhunter.db import today_local
from jobhunter.models import Job, Source, StatusChange
from jobhunter.services.fetch import Fetcher, get_fetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def mock_fetch(app):
    calls = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(200, text=(FIXTURES / "pages/lever.html").read_text())

    fetcher = Fetcher(
        transport=httpx.MockTransport(handler),
        resolver=lambda h: ["104.18.1.1"],
        sleep=lambda s: None,
    )
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    yield calls
    app.dependency_overrides.clear()


def _jobs(session, title=None):
    stmt = select(Job)
    if title:
        stmt = stmt.where(Job.title == title)
    return session.exec(stmt).all()


def _source_name(session, job):
    return session.get(Source, job.source_id).name


def test_new_job_page(two_users):
    alice, _ = two_users
    resp = alice.get("/jobs/new")
    assert resp.status_code == 200
    assert 'name="url"' in resp.text and 'name="text"' in resp.text


def test_prefill_from_text(two_users):
    alice, _ = two_users
    text = (FIXTURES / "texts/range_dollars.txt").read_text()
    resp = alice.post("/jobs/prefill", data={"url": "", "text": text})
    assert resp.status_code == 200
    assert 'value="QA Lead"' in resp.text
    assert 'value="Acme Robotics Inc."' in resp.text


def test_prefill_from_allowed_url_fetches(two_users, mock_fetch):
    alice, _ = two_users
    resp = alice.post("/jobs/prefill", data={"url": "https://jobs.lever.co/lumen/1", "text": ""})
    assert resp.status_code == 200
    assert 'value="Test Lead"' in resp.text
    assert 'value="Lumen Health"' in resp.text
    assert any(c.endswith("/lumen/1") for c in mock_fetch)
    assert re.search(r'<option value="\d+" selected>Lever</option>', resp.text)


def test_prefill_from_linkedin_is_not_fetched(two_users, mock_fetch):
    alice, _ = two_users
    resp = alice.post(
        "/jobs/prefill", data={"url": "https://www.linkedin.com/jobs/view/42/", "text": ""}
    )
    assert resp.status_code == 200
    assert "let Job Hunter download its pages" in resp.text
    assert re.search(r'<option value="\d+" selected>LinkedIn</option>', resp.text)
    assert mock_fetch == []


def test_create_requires_title_and_company(two_users, session):
    alice, _ = two_users
    resp = alice.post("/jobs", data={"title": "", "company": ""})
    assert resp.status_code == 422
    assert "Title is required" in resp.text and "Company is required" in resp.text
    assert _jobs(session) == []


def test_create_from_text_defaults(two_users, session):
    alice, _ = two_users
    text = (FIXTURES / "texts/no_salary.txt").read_text()
    resp = alice.post(
        "/jobs", data={"title": "Quality Lead", "company": "Widgets", "description": text}
    )
    assert resp.status_code == 303
    job = _jobs(session)[0]
    assert resp.headers["location"] == f"/jobs/{job.id}"
    assert job.status == "new"
    assert job.date_found == today_local()
    assert _source_name(session, job) == "Manual"
    assert job.description == text.strip()
    history = session.exec(select(StatusChange).where(StatusChange.job_id == job.id)).all()
    assert [(h.from_status, h.to_status) for h in history] == [(None, "new")]
    page = alice.get(f"/jobs/{job.id}")
    assert "Quality Lead" in page.text and "Apply now" in page.text


def test_salary_validation(two_users, session):
    alice, _ = two_users
    resp = alice.post(
        "/jobs",
        data={
            "title": "T",
            "company": "C",
            "salary_min": "150000",
            "salary_max": "100000",
            "salary_currency": "CAD",
            "salary_period": "year",
        },
    )
    assert resp.status_code == 422
    resp = alice.post("/jobs", data={"title": "T", "company": "C", "salary_min": "100000"})
    assert resp.status_code == 422
    assert _jobs(session) == []


def test_duplicate_url_is_blocked(two_users, session):
    alice, _ = two_users
    url = "https://jobs.lever.co/acme/abc"
    assert alice.post("/jobs", data={"title": "A", "company": "B", "url": url}).status_code == 303
    resp = alice.post(
        "/jobs", data={"title": "X", "company": "Y", "url": url + "?utm_source=x#top"}
    )
    assert resp.status_code == 409
    job = _jobs(session)[0]
    assert f"/jobs/{job.id}" in resp.text
    assert len(_jobs(session)) == 1


def test_duplicate_url_shown_at_prefill(two_users):
    alice, _ = two_users
    url = "https://www.linkedin.com/jobs/view/42/"
    alice.post("/jobs", data={"title": "A", "company": "B", "url": url})
    resp = alice.post("/jobs/prefill", data={"url": url + "?trk=x", "text": ""})
    assert "already tracking this job" in resp.text


def test_possible_duplicate_warns_then_saves_with_confirm(two_users, session):
    alice, _ = two_users
    alice.post("/jobs", data={"title": "QA Lead", "company": "ACME Inc."})
    resp = alice.post("/jobs", data={"title": "QA lead", "company": "Acme"})
    assert resp.status_code == 200
    assert "Possible duplicate" in resp.text
    assert len(_jobs(session)) == 1
    resp = alice.post(
        "/jobs", data={"title": "QA lead", "company": "Acme", "confirm_possible_duplicate": "1"}
    )
    assert resp.status_code == 303
    assert len(_jobs(session)) == 2


def test_duplicate_checks_ignore_other_users(two_users, session):
    alice, bob = two_users
    url = "https://jobs.lever.co/acme/abc"
    alice.post("/jobs", data={"title": "QA Lead", "company": "Acme", "url": url})
    resp = bob.post("/jobs/prefill", data={"url": url, "text": ""})
    assert "already tracking" not in resp.text and "Possible duplicate" not in resp.text
    resp = bob.post("/jobs", data={"title": "QA Lead", "company": "Acme", "url": url})
    assert resp.status_code == 303
    assert len(_jobs(session)) == 2


def test_edit_rechecks_duplicates_excluding_itself(two_users, session):
    alice, _ = two_users
    alice.post("/jobs", data={"title": "One", "company": "C", "url": "https://a.test/1"})
    alice.post("/jobs", data={"title": "Two", "company": "C", "url": "https://a.test/2"})
    one, two = sorted(_jobs(session), key=lambda j: j.id)
    resp = alice.post(
        f"/jobs/{one.id}/edit", data={"title": "One!", "company": "C", "url": "https://a.test/1"}
    )
    assert resp.status_code == 303
    resp = alice.post(
        f"/jobs/{two.id}/edit", data={"title": "Two", "company": "C", "url": "https://a.test/1/"}
    )
    assert resp.status_code == 409


def test_status_not_editable_via_edit(two_users, session):
    alice, _ = two_users
    alice.post("/jobs", data={"title": "T", "company": "C"})
    job = _jobs(session)[0]
    alice.post(f"/jobs/{job.id}/edit", data={"title": "T", "company": "C", "status": "offer"})
    session.refresh(job)
    assert job.status == "new"


def test_delete_requires_confirmation(two_users, session):
    alice, _ = two_users
    alice.post("/jobs", data={"title": "T", "company": "C"})
    job = _jobs(session)[0]
    assert alice.post(f"/jobs/{job.id}/delete").status_code == 400
    assert alice.post(f"/jobs/{job.id}/delete", data={"confirm": "yes"}).status_code == 303
    session.expire_all()
    assert _jobs(session) == []
    assert session.exec(select(StatusChange)).all() == []


def test_long_description_kept_in_full(two_users, session):
    alice, _ = two_users
    text = "word " * 10_000
    alice.post("/jobs", data={"title": "T", "company": "C", "description": text})
    assert _jobs(session)[0].description == text.strip()


def test_jobs_list_shows_own_jobs(two_users):
    alice, _ = two_users
    alice.post("/jobs", data={"title": "QA Lead", "company": "Acme"})
    resp = alice.get("/jobs")
    assert resp.status_code == 200 and "QA Lead" in resp.text
