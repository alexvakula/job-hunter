from datetime import timedelta

from sqlmodel import select

from jobhunter.db import today_local
from jobhunter.models import Contact, FollowUp, Job, Note, Source


def _add(client, **fields):
    data = {"title": "QA Lead", "company": "Acme", **fields}
    resp = client.post("/jobs", data=data)
    assert resp.status_code == 303, resp.text
    return int(resp.headers["location"].rsplit("/", 1)[1])


def _titles(resp):
    import re

    return re.findall(r'class="job-title"><a href="/jobs/\d+">([^<]+)</a>', resp.text)


def _source_id(session, name):
    return session.exec(select(Source).where(Source.name == name)).one().id


def test_filters_and_search(two_users, session):
    alice, _ = two_users
    a = _add(
        alice,
        title="Alpha QA",
        company="Acme",
        work_mode="remote",
        description="kubernetes testing",
    )
    _add(
        alice,
        title="Beta Dev",
        company="Globex",
        work_mode="onsite",
        source_id=str(_source_id(session, "LinkedIn")),
    )
    c = _add(alice, title="Gamma QA", company="Initech")
    alice.post(f"/jobs/{a}/status", data={"status": "applied"})
    alice.post(f"/jobs/{c}/status", data={"status": "interview"})

    assert _titles(alice.get("/jobs?status=applied")) == ["Alpha QA"]
    assert sorted(_titles(alice.get("/jobs?status=applied&status=interview"))) == [
        "Alpha QA",
        "Gamma QA",
    ]
    assert _titles(alice.get("/jobs?company=globe")) == ["Beta Dev"]
    assert _titles(alice.get(f"/jobs?source={_source_id(session, 'LinkedIn')}")) == ["Beta Dev"]
    assert _titles(alice.get("/jobs?work_mode=remote")) == ["Alpha QA"]
    assert _titles(alice.get("/jobs?q=kubernetes")) == ["Alpha QA"]
    assert sorted(_titles(alice.get("/jobs?q=qa"))) == ["Alpha QA", "Gamma QA"]
    today = today_local().isoformat()
    assert len(_titles(alice.get(f"/jobs?found_from={today}&found_to={today}"))) == 3
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    assert _titles(alice.get(f"/jobs?found_from={tomorrow}")) == []


def test_filters_are_in_the_url_and_survive_reload(two_users):
    alice, _ = two_users
    _add(alice)
    resp = alice.get("/jobs?status=new&q=qa")
    assert 'name="q" value="qa"' in resp.text
    assert '<option value="new" selected>' in resp.text


def test_htmx_returns_rows_only(two_users):
    alice, _ = two_users
    _add(alice)
    resp = alice.get("/jobs?q=qa", headers={"HX-Request": "true", "HX-Target": "job-rows"})
    assert "<html" not in resp.text and "QA Lead" in resp.text


def test_sorting(two_users):
    alice, _ = two_users
    for title in ("Bravo", "Alpha", "Charlie"):
        _add(alice, title=title, company=title)
    assert _titles(alice.get("/jobs?sort=title&dir=asc")) == ["Alpha", "Bravo", "Charlie"]
    assert _titles(alice.get("/jobs?sort=title&dir=desc")) == ["Charlie", "Bravo", "Alpha"]
    assert alice.get("/jobs?sort=password_hash").status_code == 200  # unknown sort ignored


def test_pagination_50_per_page(two_users, session):
    alice, _ = two_users
    from jobhunter.models import UserAccount

    uid = session.exec(select(UserAccount).where(UserAccount.username == "alice")).one().id
    manual = _source_id(session, "Manual")
    for i in range(55):
        session.add(
            Job(
                user_id=uid,
                title=f"Job {i:02d}",
                company="C",
                company_title_key=f"c|{i}",
                source_id=manual,
                date_found=today_local(),
            )
        )
    session.commit()
    assert len(_titles(alice.get("/jobs?sort=title&dir=asc"))) == 50
    page2 = _titles(alice.get("/jobs?sort=title&dir=asc&page=2"))
    assert page2 == [f"Job {i}" for i in range(50, 55)]


def test_followup_due_filter(two_users):
    alice, _ = two_users
    a = _add(alice, title="Has followup")
    _add(alice, title="No followup")
    alice.post(
        f"/jobs/{a}/followups",
        data={"due_date": today_local().isoformat(), "description": "call back"},
    )
    assert _titles(alice.get("/jobs?followup_due=1")) == ["Has followup"]


def test_notes_crud(two_users, session):
    alice, _ = two_users
    job_id = _add(alice)
    alice.post(f"/jobs/{job_id}/notes", data={"body": "first note"})
    alice.post(f"/jobs/{job_id}/notes", data={"body": "second note"})
    page = alice.get(f"/jobs/{job_id}").text
    assert page.index("second note") < page.index("first note")  # newest first
    note = session.exec(select(Note).where(Note.body == "first note")).one()
    alice.post(f"/jobs/{job_id}/notes/{note.id}", data={"body": "edited note"})
    session.refresh(note)
    assert note.body == "edited note"
    assert alice.post(f"/jobs/{job_id}/notes", data={"body": "x" * 20_001}).status_code == 422
    assert alice.post(f"/jobs/{job_id}/notes", data={"body": "  "}).status_code == 422
    note_id = note.id
    alice.post(f"/jobs/{job_id}/notes/{note_id}/delete")
    session.expire_all()
    assert session.exec(select(Note).where(Note.id == note_id)).first() is None


def test_htmx_note_returns_section(two_users):
    alice, _ = two_users
    job_id = _add(alice)
    resp = alice.post(
        f"/jobs/{job_id}/notes", data={"body": "hello"}, headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200 and 'id="notes"' in resp.text and "<html" not in resp.text


def test_contacts_crud_and_validation(two_users, session):
    alice, _ = two_users
    job_id = _add(alice)
    resp = alice.post(
        f"/jobs/{job_id}/contacts",
        data={
            "name": "Jane Recruiter",
            "role": "Recruiter",
            "email": "jane@example.com",
            "phone": "+1 403 555 0100",
            "profile_url": "https://linkedin.com/in/jane",
            "notes": "met at meetup",
        },
    )
    assert resp.status_code == 303
    assert "Jane Recruiter" in alice.get(f"/jobs/{job_id}").text
    assert (
        alice.post(
            f"/jobs/{job_id}/contacts", data={"name": "X", "email": "not-an-email"}
        ).status_code
        == 422
    )
    assert (
        alice.post(
            f"/jobs/{job_id}/contacts", data={"name": "X", "profile_url": "javascript:alert(1)"}
        ).status_code
        == 422
    )
    assert alice.post(f"/jobs/{job_id}/contacts", data={"name": ""}).status_code == 422
    contact = session.exec(select(Contact)).one()
    alice.post(f"/jobs/{job_id}/contacts/{contact.id}", data={"name": "Jane R.", "role": "HM"})
    session.refresh(contact)
    assert contact.name == "Jane R." and contact.role == "HM"
    alice.post(f"/jobs/{job_id}/contacts/{contact.id}/delete")
    session.expire_all()
    assert session.exec(select(Contact)).all() == []


def test_followups_add_done_delete(two_users, session):
    alice, _ = two_users
    job_id = _add(alice)
    today = today_local().isoformat()
    assert (
        alice.post(
            f"/jobs/{job_id}/followups", data={"due_date": today, "description": "x" * 201}
        ).status_code
        == 422
    )
    assert (
        alice.post(
            f"/jobs/{job_id}/followups", data={"due_date": "soon", "description": "x"}
        ).status_code
        == 422
    )
    alice.post(f"/jobs/{job_id}/followups", data={"due_date": today, "description": "email HR"})
    fu = session.exec(select(FollowUp)).one()
    assert "email HR" in alice.get("/").text  # due on dashboard
    alice.post(f"/jobs/{job_id}/followups/{fu.id}/done")
    session.refresh(fu)
    assert fu.done and fu.done_at is not None
    assert "email HR" not in alice.get("/").text
    alice.post(f"/jobs/{job_id}/followups/{fu.id}/delete")
    session.expire_all()
    assert session.exec(select(FollowUp)).all() == []


def test_child_of_other_job_is_not_found(two_users, session):
    alice, _ = two_users
    a = _add(alice, title="A")
    b = _add(alice, title="B")
    alice.post(f"/jobs/{a}/notes", data={"body": "on A"})
    note = session.exec(select(Note)).one()
    assert alice.post(f"/jobs/{b}/notes/{note.id}/delete").status_code == 404


def test_dashboard(two_users):
    alice, _ = two_users
    a = _add(alice)
    alice.post(f"/jobs/{a}/status", data={"status": "applied"})
    resp = alice.get("/")
    assert resp.status_code == 200
    assert "Applications per week" in resp.text
    assert "Response rate" in resp.text
    assert "0%" in resp.text  # 1 applied, no response yet


def test_dashboard_empty(two_users):
    _, bob = two_users
    resp = bob.get("/")
    assert "no data yet" in resp.text
