import email
import re

import pytest
from sqlmodel import select

from jobhunter.models import (
    DocumentVersion,
    EmailMessage,
    Job,
    MasterResume,
    StatusChange,
    UserAccount,
)
from jobhunter.services import mailer
from jobhunter.services.resume import versions
from tests.resume_data import MASTER, POSTING, resume_docx_bytes


def _uid(session, name="alice"):
    return session.exec(select(UserAccount.id).where(UserAccount.username == name)).one()


def _master_form(data=MASTER):
    form = {k: data[k] for k in ("name", "email", "phone", "location", "summary")}
    form["links"] = "\n".join(data["links"])
    form["skills"] = ", ".join(data["skills"])
    for i, e in enumerate(data["experience"]):
        for k in ("employer", "title", "location", "start", "end", "id"):
            form[f"experience-{i}-{k}"] = e[k]
        form[f"experience-{i}-bullets"] = "\n".join(e["bullets"])
    for i, e in enumerate(data["education"]):
        for k, v in e.items():
            form[f"education-{i}-{k}"] = v
    for i, e in enumerate(data["certifications"]):
        for k, v in e.items():
            form[f"certifications-{i}-{k}"] = v
    return form


@pytest.fixture
def ready(two_users, session):
    """alice with a master resume, a job with the QA Lead posting and a contact."""
    alice, bob = two_users
    assert alice.post("/resume", data=_master_form()).status_code == 303
    resp = alice.post(
        "/jobs", data={"title": "QA Lead", "company": "Acme Robotics", "description": POSTING}
    )
    job_id = int(resp.headers["location"].rsplit("/", 1)[1])
    alice.post(f"/jobs/{job_id}/contacts", data={"name": "Jane", "email": "jane@acmerobotics.com"})
    return alice, bob, job_id


def test_master_editor_save_and_validation(two_users, session):
    alice, _ = two_users
    assert "Master resume" in alice.get("/resume").text
    bad = _master_form()
    bad["experience-0-employer"] = ""
    assert alice.post("/resume", data=bad).status_code == 422
    assert alice.post("/resume", data=_master_form()).status_code == 303
    m = session.get(MasterResume, _uid(session))
    assert m.data["experience"][1]["employer"] == "Société Générale Tech"
    assert m.data["experience"][0]["bullets"][1].startswith("Built a Selenium")
    assert "Northwind Imaging" in alice.get("/resume").text


def test_import_from_uploaded_resume(two_users, session):
    alice, _ = two_users
    assert "upload your resume" in alice.get("/resume").text
    alice.post("/settings/resume", files={"file": ("cv.docx", resume_docx_bytes())})
    page = alice.post("/resume/import")
    assert page.status_code == 200 and "Imported from" in page.text
    assert 'value="Northwind Imaging"' in page.text and 'value="Jan 2020"' in page.text
    assert session.get(MasterResume, _uid(session)) is None  # not saved until Save


def test_apply_page_without_master(two_users):
    alice, _ = two_users
    job = alice.post("/jobs", data={"title": "T", "company": "C"}).headers["location"]
    assert "fill in your" in alice.get(job + "/apply").text


def test_apply_page_scores_and_tailors(ready, session):
    alice, _, job_id = ready
    page = alice.get(f"/jobs/{job_id}/apply").text
    assert "ATS match" in page and "Playwright" in page and "Selenium" in page
    assert re.search(r"Master resume: \d+%", page)
    assert page.index("Built a Selenium") < page.index("Introduced quarterly release")
    assert "Dear Jane," in page  # cover letter addressed to the contact
    assert "Northwind Imaging" in page and 'name="employer"' not in page  # facts read-only


def test_honesty_blocks_generation(ready, session):
    alice, _, job_id = ready
    page = alice.get(f"/jobs/{job_id}/apply").text
    form = {"summary": "Expert in Playwright test automation.", "cover_letter": "Hello"}
    alice.post(f"/jobs/{job_id}/apply/tailor", data=form)
    page = alice.get(f"/jobs/{job_id}/apply").text
    assert "Not in your master resume:</strong> Playwright" in page
    resp = alice.post(f"/jobs/{job_id}/apply/generate")
    assert resp.status_code == 409
    assert session.exec(select(DocumentVersion)).all() == []
    alice.post(
        f"/jobs/{job_id}/apply/tailor",
        data={"summary": "QA leader focused on test automation.", "cover_letter": "Hi"},
    )
    assert alice.post(f"/jobs/{job_id}/apply/generate").status_code == 303
    assert page  # first page rendered fine


def test_hide_and_reorder(ready, session):
    alice, _, job_id = ready
    alice.get(f"/jobs/{job_id}/apply")
    form = {
        "summary": "QA leader.",
        "cover_letter": "Hi",
        "b-e1-0-hidden": "1",
        "b-e1-3-pos": "0",
        "s-0-hidden": "1",
    }
    alice.post(f"/jobs/{job_id}/apply/tailor", data=form)
    alice.post(f"/jobs/{job_id}/apply/generate")
    v = session.exec(select(DocumentVersion)).one()
    exp = v.content["resume"]["experience"][0]
    assert exp["bullets"][0] == "Mentored 5 testers; tracked defects in Jira."
    assert "Introduced quarterly release reviews with product owners." not in exp["bullets"]
    assert len(v.content["resume"]["skills"]) == len(MASTER["skills"]) - 1


def test_versions_are_immutable_and_downloadable(ready, session):
    alice, _, job_id = ready
    alice.get(f"/jobs/{job_id}/apply")
    alice.post(f"/jobs/{job_id}/apply/generate")
    alice.post(
        f"/jobs/{job_id}/apply/tailor", data={"summary": "Changed summary.", "cover_letter": "Hi"}
    )
    alice.post(f"/jobs/{job_id}/apply/generate")
    v1, v2 = session.exec(select(DocumentVersion).order_by(DocumentVersion.number)).all()
    assert (v1.number, v2.number) == (1, 2)
    assert v1.content["resume"]["summary"] != "Changed summary."
    assert v2.content["resume"]["summary"] == "Changed summary."
    for kind in versions.FILES:
        r = alice.get(f"/documents/{v1.id}/{kind}")
        assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
        assert len(r.content) > 500
    assert alice.get(f"/documents/{v1.id}/evil.exe").status_code == 404
    page = alice.get(f"/jobs/{job_id}/apply").text
    assert "Version 2" in page and "Version 1" in page


@pytest.fixture
def sendable(ready, session, monkeypatch):
    alice, bob, job_id = ready
    alice.post(
        "/settings/sender",
        data={
            "from_address": "alice.jobs@example.org",
            "display_name": "Alice",
            "smtp_host": "smtp.example.org",
            "smtp_port": "587",
            "signature": "--\nAlice",
        },
    )
    alice.get(f"/jobs/{job_id}/apply")
    alice.post(f"/jobs/{job_id}/apply/generate")
    sent = []

    def fake(settings, username, message, recipients):
        sent.append((message, recipients))
        return mailer.Result(True, "Sent.")

    monkeypatch.setattr(mailer, "send_message", fake)
    return alice, bob, job_id, sent


def _preview(alice, job_id, **override):
    page = alice.get(f"/jobs/{job_id}/apply/compose").text
    assert 'value="jane@acmerobotics.com"' in page
    attachments = re.findall(r'name="attachments" value="([^"]+)" checked', page)
    data = {
        "to": "jane@acmerobotics.com",
        "subject": "Application: QA Lead — Sam Rivera",
        "body": "Dear Jane,\n\nPlease find my application attached.",
        "attachments": attachments,
        **override,
    }
    resp = alice.post(f"/jobs/{job_id}/apply/preview", data=data)
    return resp, data


def test_preview_then_confirm_sends_and_marks_applied(sendable, session):
    alice, _, job_id, sent = sendable
    resp, data = _preview(alice, job_id)
    assert resp.status_code == 200 and "exactly what will be sent" in resp.text
    assert "Resume" in resp.text and ".pdf" in resp.text
    token = re.search(r'name="token" value="([^"]+)"', resp.text).group(1)
    # without the tick: refused
    r = alice.post(f"/jobs/{job_id}/apply/send", data={**data, "token": token})
    assert r.status_code == 400 and sent == []
    r = alice.post(f"/jobs/{job_id}/apply/send", data={**data, "token": token, "confirm": "yes"})
    assert r.status_code == 200 and "Application sent to jane@acmerobotics.com" in r.text
    assert len(sent) == 1
    message, recipients = sent[0]
    assert recipients == ["jane@acmerobotics.com"]
    parsed = email.message_from_bytes(bytes(message))
    names = [p.get_filename() for p in parsed.walk() if p.get_filename()]
    assert len(names) == 2 and all(n.endswith(".pdf") for n in names)
    assert "--\nAlice" in message.get_body(("plain",)).get_content()
    job = session.get(Job, job_id)
    session.refresh(job)
    assert job.status == "applied"
    history = session.exec(select(StatusChange).where(StatusChange.job_id == job_id)).all()
    assert history[-1].to_status == "applied"
    logged = session.exec(select(EmailMessage).where(EmailMessage.direction == "out")).one()
    assert logged.job_id == job_id and logged.send_status == "sent"


def test_changed_content_needs_new_preview(sendable, session):
    alice, _, job_id, sent = sendable
    resp, data = _preview(alice, job_id)
    token = re.search(r'name="token" value="([^"]+)"', resp.text).group(1)
    tampered = {**data, "subject": "Something else", "token": token, "confirm": "yes"}
    r = alice.post(f"/jobs/{job_id}/apply/send", data=tampered)
    assert r.status_code == 400 and "Preview it again" in r.text and sent == []
    extra = {
        **data,
        "to": "jane@acmerobotics.com, other@northwind.io",
        "token": token,
        "confirm": "yes",
    }
    assert alice.post(f"/jobs/{job_id}/apply/send", data=extra).status_code == 400
    assert sent == []


def test_preview_validation(sendable):
    alice, _, job_id, _ = sendable
    resp, _ = _preview(alice, job_id, to="not-an-email")
    assert resp.status_code == 422 and "not a valid email" in resp.text
    resp, _ = _preview(alice, job_id, attachments=["999:resume.pdf"])
    assert resp.status_code == 422 and "Unknown attachment" in resp.text


def test_cannot_attach_other_users_documents(sendable, two_users, session):
    alice, bob, job_id, sent = sendable
    v = session.exec(select(DocumentVersion)).first()
    bob_job = int(
        bob.post("/jobs", data={"title": "X", "company": "Y"}).headers["location"].rsplit("/", 1)[1]
    )
    bob.post(
        "/settings/sender",
        data={"from_address": "bob@example.org", "smtp_host": "h", "smtp_port": "587"},
    )
    r = bob.post(
        f"/jobs/{bob_job}/apply/preview",
        data={
            "to": "hr@beta.io",
            "subject": "s",
            "body": "b",
            "attachments": [f"{v.id}:resume.pdf"],
        },
    )
    assert r.status_code == 422 and "Unknown attachment" in r.text
    assert bob.get(f"/documents/{v.id}/resume.pdf").status_code == 404


def test_failed_send_keeps_status(sendable, session, monkeypatch):
    alice, _, job_id, _ = sendable
    monkeypatch.setattr(mailer, "send_message", lambda *a, **k: mailer.Result(False, "nope"))
    resp, data = _preview(alice, job_id)
    token = re.search(r'name="token" value="([^"]+)"', resp.text).group(1)
    r = alice.post(f"/jobs/{job_id}/apply/send", data={**data, "token": token, "confirm": "yes"})
    assert r.status_code == 502 and "nope" in r.text
    job = session.get(Job, job_id)
    session.refresh(job)
    assert job.status == "new"


def test_application_draft_save_resume_send(sendable):
    alice, bob_client, job_id, sent = sendable
    data = {
        "to": "jane@acmerobotics.com",
        "subject": "Application: QA Lead",
        "body": "Dear Jane, half-written",
    }
    r = alice.post(f"/jobs/{job_id}/apply/save", data=data)
    assert r.status_code == 303 and r.headers["location"] == f"/jobs/{job_id}/apply/compose?saved=1"
    page = alice.get(f"/jobs/{job_id}/apply/compose").text
    assert "Dear Jane, half-written" in page and "Your saved draft" in page
    assert "Dear Jane, half-written" not in alice.get(f"/jobs/{job_id}/apply/compose?fresh=1").text
    drafts = alice.get("/mail?view=drafts").text
    assert f"/jobs/{job_id}/apply/compose" in drafts and ">Application</span>" in drafts
    assert "Application: QA Lead" not in bob_client.get("/mail?view=drafts").text
    assert bob_client.post(f"/jobs/{job_id}/apply/save", data=data).status_code == 404

    resp, form = _preview(alice, job_id)
    token = re.search(r'name="token" value="([^"]+)"', resp.text).group(1)
    alice.post(f"/jobs/{job_id}/apply/send", data={**form, "token": token, "confirm": "yes"})
    assert len(sent) == 1
    assert "No drafts" in alice.get("/mail?view=drafts").text


def test_application_draft_discard(sendable):
    alice, _, job_id, _ = sendable
    alice.post(f"/jobs/{job_id}/apply/save", data={"body": "draft"})
    r = alice.post(f"/jobs/{job_id}/apply/discard")
    assert r.status_code == 303 and "No drafts" in alice.get("/mail?view=drafts").text
