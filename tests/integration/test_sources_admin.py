from sqlmodel import select

from jobhunter.models import Source, TargetProfile


def _admin(make_user, user_client):
    make_user("sam", role="admin")
    return user_client("sam")


def _source(session, name):
    session.expire_all()
    return session.exec(select(Source).where(Source.name == name)).first()


def test_list_and_create_source(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    assert "Job Bank" in admin.get("/admin/sources").text
    resp = admin.post(
        "/admin/sources/new",
        data={
            "name": "Acme Careers",
            "type": "careers_page",
            "domains": "careers.acme.com, https://jobs.acme.com/path",
            "fetch_allowed": "1",
            "enabled": "1",
        },
    )
    assert resp.status_code == 303
    src = _source(session, "Acme Careers")
    assert src.domains == ["careers.acme.com", "jobs.acme.com"]
    assert src.fetch_allowed and src.enabled and src.type == "careers_page"


def test_source_validation(make_user, user_client):
    admin = _admin(make_user, user_client)
    assert (
        admin.post("/admin/sources/new", data={"name": "", "type": "job_board"}).status_code == 422
    )
    assert (
        admin.post("/admin/sources/new", data={"name": "Job Bank", "type": "job_board"}).status_code
        == 422
    )
    assert (
        admin.post("/admin/sources/new", data={"name": "X", "type": "nonsense"}).status_code == 422
    )
    assert (
        admin.post(
            "/admin/sources/new",
            data={"name": "X", "type": "job_board", "domains": "not a domain!"},
        ).status_code
        == 422
    )


def test_edit_source(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    lever = _source(session, "Lever")
    resp = admin.post(
        f"/admin/sources/{lever.id}",
        data={"name": "Lever", "type": "ats", "domains": "jobs.lever.co", "enabled": "1"},
    )
    assert resp.status_code == 303
    lever = _source(session, "Lever")
    assert not lever.fetch_allowed and lever.enabled


def test_manual_cannot_be_deleted(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    manual = _source(session, "Manual")
    assert (
        admin.post(f"/admin/sources/{manual.id}/delete", data={"confirm": "yes"}).status_code == 422
    )
    assert _source(session, "Manual") is not None


def test_source_in_use_cannot_be_deleted(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    lever = _source(session, "Lever")
    admin.post("/jobs", data={"title": "T", "company": "C", "source_id": str(lever.id)})
    assert (
        admin.post(f"/admin/sources/{lever.id}/delete", data={"confirm": "yes"}).status_code == 422
    )
    assert _source(session, "Lever") is not None


def test_delete_unused_source_removes_it_from_profiles(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    eluta = _source(session, "Eluta.ca")
    admin.post(
        "/settings/profiles/new",
        data={
            "name": "P",
            "rules-0-place": "Calgary",
            "rules-0-remote": "1",
            "source_ids": str(eluta.id),
        },
    )
    assert admin.post(f"/admin/sources/{eluta.id}/delete").status_code == 400
    assert (
        admin.post(f"/admin/sources/{eluta.id}/delete", data={"confirm": "yes"}).status_code == 303
    )
    assert _source(session, "Eluta.ca") is None
    assert session.exec(select(TargetProfile)).one().source_ids == []


def test_non_admin_cannot_change_but_can_select(two_users, session):
    alice, _ = two_users
    lever = _source(session, "Lever")
    assert alice.post(f"/admin/sources/{lever.id}", data={"name": "Hacked"}).status_code == 403
    assert "Lever" in alice.get("/jobs/new").text
    assert _source(session, "Lever").name == "Lever"


def test_disabled_source_hidden_from_pickers(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    glassdoor = _source(session, "Glassdoor")
    admin.post(
        f"/admin/sources/{glassdoor.id}",
        data={"name": "Glassdoor", "type": "job_board", "domains": "glassdoor.com, glassdoor.ca"},
    )
    assert ">Glassdoor</option>" not in admin.get("/jobs/new").text
    page = admin.get("/settings/profiles/new").text
    assert "Glassdoor" not in page
