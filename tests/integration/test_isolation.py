"""Per-user isolation over every route (SC-005, SC-009, constitution VIII).

Routes are discovered from the app, so new routes are covered automatically. Each path
parameter name must have an entry in `alice_objects`; the test fails loudly otherwise.
"""

import re

import pytest
from fastapi.routing import APIRoute
from sqlmodel import select

from jobhunter.models import (
    Contact,
    FollowUp,
    Job,
    Note,
    ResumeFile,
    TargetProfile,
    UserAccount,
)

PUBLIC = {"/login", "/health"}
PARAM_RE = re.compile(r"{(\w+)}")


def _routes(app):
    """All APIRoutes, including those inside included routers (FastAPI wraps them)."""
    pending = list(app.routes)
    while pending:
        route = pending.pop(0)
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            pending.extend(route.original_router.routes)


def test_route_discovery_finds_job_routes(app):
    paths = {r.path for r in _routes(app)}
    assert {"/jobs", "/jobs/{job_id}", "/login"} <= paths


@pytest.fixture
def alice_objects(two_users, session):
    """Create one of each owned object for alice and return {path_param: id}."""
    alice, _ = two_users
    resp = alice.post(
        "/jobs",
        data={"title": "QA Lead", "company": "Alice Co", "description": "secret alice posting"},
    )
    assert resp.status_code == 303, resp.text
    alice_id = session.exec(select(UserAccount).where(UserAccount.username == "alice")).one().id
    job = session.exec(select(Job).where(Job.user_id == alice_id)).one()
    assert alice.post(f"/jobs/{job.id}/notes", data={"body": "n"}).status_code == 303
    assert alice.post(f"/jobs/{job.id}/contacts", data={"name": "c"}).status_code == 303
    assert (
        alice.post(
            f"/jobs/{job.id}/followups", data={"due_date": "2026-01-01", "description": "f"}
        ).status_code
        == 303
    )
    profile_resp = alice.post(
        "/settings/profiles/new",
        data={"name": "Alice target", "rules-0-place": "Calgary", "rules-0-remote": "1"},
    )
    assert profile_resp.status_code == 303
    from tests.resume_samples import pdf_bytes

    upload = alice.post(
        "/settings/resume", files={"file": ("alice.pdf", pdf_bytes("secret alice posting"))}
    )
    assert upload.status_code == 303
    # Feature 002: an email with an attachment, and an alert that produces a suggestion.
    from pathlib import Path

    from jobhunter.models import EmailAttachment, JobSuggestion
    from jobhunter.services import mail_store, mailbox

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "emails"
    reply, _ = mail_store.store(session, alice_id, (fixtures / "recruiter_reply.eml").read_bytes())
    alert, _ = mail_store.store(session, alice_id, (fixtures / "linkedin_alert_1.eml").read_bytes())
    mailbox.classify_and_link(session, alert)
    from jobhunter.models import WatchCompany

    added = alice.post("/watchlist", data={"careers_url": "https://jobs.lever.co/alicecorp"})
    assert added.status_code == 303
    from tests.integration.test_apply import _master_form

    assert alice.post("/resume", data=_master_form()).status_code == 303
    alice.get(f"/jobs/{job.id}/apply")
    assert alice.post(f"/jobs/{job.id}/apply/generate").status_code == 303
    from jobhunter.models import ClaudeJob, DocumentVersion

    session.add(ClaudeJob(user_id=alice_id, kind="import", status="done", result={}))
    session.commit()
    return {
        "claude_job_id": session.exec(select(ClaudeJob)).one().id,
        "version_id": session.exec(select(DocumentVersion)).one().id,
        "kind": "resume.pdf",
        "company_id": session.exec(select(WatchCompany)).one().id,
        "email_id": reply.id,
        "attachment_id": session.exec(select(EmailAttachment)).first().id,
        "suggestion_id": session.exec(select(JobSuggestion)).first().id,
        "user_id": alice_id,
        "source_id": session.exec(select(Job)).one().source_id,
        "resume_id": session.exec(select(ResumeFile)).one().id,
        "profile_id": session.exec(select(TargetProfile)).one().id,
        "job_id": job.id,
        "note_id": session.exec(select(Note)).one().id,
        "contact_id": session.exec(select(Contact)).one().id,
        "followup_id": session.exec(select(FollowUp)).one().id,
    }


def test_every_private_route_requires_login(app, client):
    for route in _routes(app):
        if route.path in PUBLIC:
            continue
        path = PARAM_RE.sub("1", route.path)
        for method in route.methods - {"HEAD"}:
            resp = client.request(method, path, follow_redirects=False)
            assert resp.status_code == 303, (method, route.path, resp.status_code)
            assert resp.headers["location"].startswith("/login"), route.path


def test_other_users_objects_are_not_found(app, two_users, alice_objects, session):
    _, bob = two_users
    checked = 0
    for route in _routes(app):
        params = PARAM_RE.findall(route.path)
        if not params:
            continue
        missing = [p for p in params if p not in alice_objects]
        assert not missing, f"add {missing} to alice_objects for {route.path}"
        path = route.path
        for p in params:
            path = path.replace("{" + p + "}", str(alice_objects[p]))
        for method in route.methods - {"HEAD"}:
            if method == "GET":
                resp = bob.get(path)
            else:
                resp = bob.post(
                    path,
                    data={
                        "confirm": "yes",
                        "status": "rejected",
                        "title": "hacked",
                        "company": "hacked",
                        "body": "hacked",
                        "name": "hacked",
                        "due_date": "2026-02-02",
                        "description": "hacked",
                    },
                )
            if route.path.startswith("/watchlist/"):
                continue  # the watchlist is shared (test_watchlist.test_watchlist_is_shared)
            # Admin pages refuse non-admins outright; everything else hides alice's objects.
            admin_only = route.path.startswith(
                ("/admin", "/claude", "/resume/claude-import")
            ) or route.path.endswith(("/apply/claude", "/prep", "/reply/claude"))
            expected = 403 if admin_only else 404
            assert resp.status_code == expected, (method, route.path, resp.status_code)
            assert "secret alice posting" not in resp.text
            checked += 1
    assert checked > 0
    job = session.get(Job, alice_objects["job_id"])
    session.refresh(job)
    assert job.title == "QA Lead" and job.status == "new"
    session.expire_all()
    assert session.get(Note, alice_objects["note_id"]).body == "n"
    assert session.get(Contact, alice_objects["contact_id"]).name == "c"
    profile = session.get(TargetProfile, alice_objects["profile_id"])
    assert profile.name == "Alice target" and not profile.is_archived
    followup = session.get(FollowUp, alice_objects["followup_id"])
    assert followup.description == "f" and not followup.done


def test_bob_lists_do_not_show_alice_jobs(two_users, alice_objects):
    _, bob = two_users
    for path in ("/jobs", "/board"):
        resp = bob.get(path)
        assert resp.status_code == 200
        assert "Alice Co" not in resp.text
