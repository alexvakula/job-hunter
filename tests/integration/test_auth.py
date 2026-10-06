from datetime import timedelta

from sqlmodel import select

from jobhunter.models import UserSession
from tests.conftest import csrf_from, login


def test_unauthenticated_redirects_to_login(client):
    resp = client.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=%2Fjobs"


def test_htmx_unauthenticated_gets_hx_redirect(client):
    resp = client.get("/jobs", headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp.headers["HX-Redirect"].startswith("/login?next=")


def test_wrong_password_shows_generic_error(client, make_user):
    make_user("alice")
    resp = login(client, "alice", password="wrong password!!")
    assert resp.status_code == 200
    assert "Invalid username or password." in resp.text
    assert "jh_session" not in resp.cookies


def test_unknown_user_same_error(client):
    resp = login(client, "nobody")
    assert "Invalid username or password." in resp.text


def test_login_redirects_to_next(client, make_user):
    make_user("alice")
    resp = login(client, "alice", next="/jobs?status=applied")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/jobs?status=applied"


def test_open_redirect_is_ignored(client, make_user):
    make_user("alice")
    for target in ("https://evil.example", "//evil.example", "/\\evil.example"):
        client.cookies.clear()
        resp = login(client, "alice", next=target)
        assert resp.headers["location"] == "/"


def test_login_form_requires_csrf_cookie(client, make_user):
    make_user("alice")
    page = client.get("/login")
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"username": "alice", "password": "x" * 12, "csrf_token": csrf_from(page.text)},
    )
    assert resp.status_code == 400


def test_logout_ends_session(two_users, session):
    alice, _ = two_users
    sid = alice.client.cookies.get("jh_session")
    assert alice.post("/logout").status_code == 303
    assert session.get(UserSession, sid) is None
    assert alice.get("/jobs").status_code == 303


def test_inactive_user_refused(client, make_user):
    make_user("carol", is_active=False)
    resp = login(client, "carol")
    assert "Invalid username or password." in resp.text


def test_disabled_while_logged_in_loses_session(two_users, session):
    from jobhunter.models import UserAccount

    alice, _ = two_users
    user = session.exec(select(UserAccount).where(UserAccount.username == "alice")).one()
    user.is_active = False
    session.add(user)
    session.commit()
    assert alice.get("/jobs").status_code == 303


def test_idle_session_expires_and_shows_message(two_users, session):
    alice, _ = two_users
    row = session.get(UserSession, alice.client.cookies.get("jh_session"))
    row.last_seen_at = row.last_seen_at - timedelta(days=31)
    session.add(row)
    session.commit()

    resp = alice.get("/jobs")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=%2Fjobs&expired=1"

    alice.client.cookies.delete("jh_session")
    page = alice.client.get(resp.headers["location"])
    assert "Your session expired" in page.text
    resp = alice.client.post(
        "/login",
        data={
            "username": "alice",
            "password": "correct horse battery",
            "next": "/jobs",
            "expired": "1",
            "csrf_token": csrf_from(page.text),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    target = alice.client.get("/jobs")
    assert "Your session expired; please check and resubmit your changes." in target.text


def test_health_is_public(client):
    assert client.get("/health").text == "ok"
