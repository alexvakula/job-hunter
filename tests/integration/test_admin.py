from sqlmodel import select

from jobhunter.auth.passwords import verify_password
from jobhunter.models import UserAccount, UserSession
from tests.conftest import PASSWORD, UserClient, login

TEMP = "temporary password 1"


def _user(session, name):
    session.expire_all()
    return session.exec(select(UserAccount).where(UserAccount.username == name)).one()


def _admin(make_user, user_client):
    make_user("sam", role="admin")
    return user_client("sam")


def _create_kid(admin, username="kid1", password=TEMP):
    return admin.post(
        "/admin/users/new",
        data={"username": username, "display_name": "Kid One", "temp_password": password},
    )


def test_non_admin_gets_403_everywhere(two_users):
    alice, _ = two_users
    for path in ("/admin/users", "/admin/users/new", "/admin/sources", "/admin/sources/new"):
        assert alice.get(path).status_code == 403
    assert alice.post("/admin/users/new", data={"username": "x"}).status_code == 403


def test_create_user_validation(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    assert _create_kid(admin, username="Kid One").status_code == 422
    assert _create_kid(admin, password="short").status_code == 422
    assert _create_kid(admin).status_code == 303
    assert _create_kid(admin).status_code == 422  # duplicate
    kid = _user(session, "kid1")
    assert kid.role == "user" and kid.must_change_password and kid.is_active


def test_create_form_has_no_role_choice(make_user, user_client):
    admin = _admin(make_user, user_client)
    page = admin.get("/admin/users/new").text
    assert 'name="role"' not in page
    _create_kid(admin)
    resp = admin.post(
        "/admin/users/new",
        data={"username": "kid2", "display_name": "K", "temp_password": TEMP, "role": "admin"},
    )
    assert resp.status_code == 303


def test_first_login_forces_password_change(make_user, user_client, app, session):
    admin = _admin(make_user, user_client)
    _create_kid(admin)
    from fastapi.testclient import TestClient

    kid = TestClient(app, base_url="http://testserver")
    assert login(kid, "kid1", password=TEMP).status_code == 303
    resp = kid.get("/jobs", follow_redirects=False)
    assert resp.headers["location"] == "/account/password"
    page = kid.get("/account/password")
    from tests.conftest import csrf_from

    token = csrf_from(page.text)
    resp = kid.post(
        "/account/password",
        data={
            "current": TEMP,
            "new": "kid chosen password",
            "confirm": "kid chosen password",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert not _user(session, "kid1").must_change_password
    assert kid.get("/jobs", follow_redirects=False).status_code == 200


def test_change_own_password(two_users, session):
    alice, _ = two_users
    bad = alice.post(
        "/account/password", data={"current": "wrong", "new": "x" * 12, "confirm": "x" * 12}
    )
    assert bad.status_code == 422
    mismatch = alice.post(
        "/account/password", data={"current": PASSWORD, "new": "x" * 12, "confirm": "y" * 12}
    )
    assert mismatch.status_code == 422
    short = alice.post(
        "/account/password", data={"current": PASSWORD, "new": "short", "confirm": "short"}
    )
    assert short.status_code == 422
    ok = alice.post(
        "/account/password",
        data={"current": PASSWORD, "new": "brand new pass", "confirm": "brand new pass"},
    )
    assert ok.status_code == 303
    assert verify_password("brand new pass", _user(session, "alice").password_hash)
    assert alice.get("/jobs").status_code == 200  # current session survives


def test_change_password_ends_other_sessions(make_user, user_client, session):
    make_user("alice")
    first = user_client("alice")
    second = user_client("alice")
    first.post(
        "/account/password",
        data={"current": PASSWORD, "new": "brand new pass", "confirm": "brand new pass"},
    )
    assert first.get("/jobs").status_code == 200
    assert second.get("/jobs").status_code == 303


def test_reset_password_ends_sessions(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    make_user("kid1")
    kid = user_client("kid1")
    kid_id = _user(session, "kid1").id
    resp = admin.post(f"/admin/users/{kid_id}/reset-password", data={"temp_password": TEMP})
    assert resp.status_code == 303
    kid_user = _user(session, "kid1")
    assert kid_user.must_change_password and verify_password(TEMP, kid_user.password_hash)
    assert session.exec(select(UserSession).where(UserSession.user_id == kid_id)).all() == []
    assert kid.get("/jobs").status_code == 303
    assert (
        admin.post(
            f"/admin/users/{kid_id}/reset-password", data={"temp_password": "short"}
        ).status_code
        == 422
    )


def test_disable_and_enable(make_user, user_client, session, app):
    admin = _admin(make_user, user_client)
    make_user("kid1")
    kid = user_client("kid1")
    kid.post("/jobs", data={"title": "Kid job", "company": "C"})
    kid_id = _user(session, "kid1").id
    assert admin.post(f"/admin/users/{kid_id}/disable").status_code == 303
    assert kid.get("/jobs").status_code == 303
    from fastapi.testclient import TestClient

    assert "Invalid username" in login(TestClient(app), "kid1").text
    from jobhunter.models import Job

    assert session.exec(select(Job)).one().title == "Kid job"  # data kept
    assert admin.post(f"/admin/users/{kid_id}/enable").status_code == 303
    UserClient(app, "kid1")  # can log in again


def test_cannot_disable_last_active_admin(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    sam_id = _user(session, "sam").id
    resp = admin.post(f"/admin/users/{sam_id}/disable")
    assert resp.status_code == 422
    assert _user(session, "sam").is_active


def test_admin_cannot_see_kids_jobs(make_user, user_client, session):
    admin = _admin(make_user, user_client)
    make_user("kid1")
    kid = user_client("kid1")
    resp = kid.post("/jobs", data={"title": "Private kid job", "company": "Secret Co"})
    job_path = resp.headers["location"]
    assert admin.get(job_path).status_code == 404
    page = admin.get("/admin/users").text
    assert "kid1" in page and "Secret Co" not in page and "Private kid job" not in page
    assert "Secret Co" not in admin.get("/jobs").text
