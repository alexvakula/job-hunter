from tests.conftest import login


def test_eleventh_failed_login_is_refused(client, make_user):
    make_user("alice")
    for _ in range(10):
        resp = login(client, "alice", password="wrong password!!")
        assert resp.status_code == 200
    resp = login(client, "alice")  # even the right password is refused now
    assert resp.status_code == 429
    assert "Too many" in resp.text


def test_throttle_is_per_username(client, make_user):
    make_user("alice")
    make_user("bob")
    for _ in range(10):
        login(client, "alice", password="wrong password!!")
    assert login(client, "bob").status_code == 303


def test_post_without_csrf_is_rejected(two_users):
    alice, _ = two_users
    resp = alice.client.post("/logout", follow_redirects=False)
    assert resp.status_code == 403


def test_post_with_wrong_csrf_is_rejected(two_users):
    alice, bob = two_users
    resp = alice.post("/logout", data={"csrf_token": bob.csrf})
    assert resp.status_code == 403


def test_csrf_header_is_accepted(two_users):
    alice, _ = two_users
    resp = alice.client.post(
        "/logout", headers={"X-CSRF-Token": alice.csrf}, follow_redirects=False
    )
    assert resp.status_code == 303


def test_throttle_uses_real_ip_header_not_forwarded_for(client, make_user):
    make_user("alice")
    for i in range(10):
        page = client.get("/login")
        from tests.conftest import csrf_from

        client.post(
            "/login",
            data={
                "username": "alice",
                "password": "wrong password!!",
                "csrf_token": csrf_from(page.text),
            },
            headers={"X-Real-IP": "203.0.113.7", "X-Forwarded-For": f"198.51.100.{i}"},
        )
    page = client.get("/login")
    resp = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "correct horse battery",
            "csrf_token": csrf_from(page.text),
        },
        headers={"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.99"},
        follow_redirects=False,
    )
    assert resp.status_code == 429
