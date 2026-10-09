"""Login history: recorded at login, visible to the person and the admin only."""

import gzip
import os
import time
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlmodel import select

from jobhunter.models import LoginEvent
from jobhunter.services import login_history
from tests.conftest import UserClient, login

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
CALGARY = {
    "city": {"names": {"en": "Calgary"}},
    "subdivisions": [{"names": {"en": "Alberta"}}],
    "country": {"names": {"en": "Canada"}},
}


class FakeReader:
    def get(self, ip):
        return CALGARY if ip == "70.77.86.53" else None


def _login_from(app, username, ip, ua=CHROME_WINDOWS):
    client = TestClient(
        app, base_url="http://testserver", headers={"x-real-ip": ip, "user-agent": ua}
    )
    assert login(client, username).status_code == 303


def test_login_is_recorded_with_place_and_device(app, make_user, session, monkeypatch):
    monkeypatch.setattr(login_history, "_open_reader", lambda: FakeReader())
    user = make_user("karo")
    _login_from(app, "karo", "70.77.86.53")
    _login_from(app, "karo", "8.8.4.4", ua="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1")
    events = session.exec(select(LoginEvent).where(LoginEvent.user_id == user.id)).all()
    got = sorted((e.ip, e.location, e.device) for e in events)
    assert got == [
        ("70.77.86.53", "Calgary, Alberta, Canada", "Chrome on Windows"),
        ("8.8.4.4", "", "Safari on iPhone"),  # not in the database: unknown, login still works
    ]


def test_missing_database_never_blocks_login(app, make_user, session):
    user = make_user("karo")  # no database file in the test data folder
    _login_from(app, "karo", "70.77.86.53")
    [event] = session.exec(select(LoginEvent).where(LoginEvent.user_id == user.id)).all()
    assert event.location == "" and event.ip == "70.77.86.53"


def test_people_see_their_own_history_and_the_admin_sees_all(app, make_user, monkeypatch):
    monkeypatch.setattr(login_history, "_open_reader", lambda: FakeReader())
    make_user("sam", role="admin")
    karo = make_user("karo")
    bob = make_user("bob")
    _login_from(app, "karo", "70.77.86.53")

    karo_client = UserClient(app, "karo")
    page = karo_client.get("/account/logins").text
    assert "Calgary, Alberta, Canada" in page and "Chrome on Windows" in page
    assert "the admin can see this list" in page and "DB-IP" in page

    bob_client = UserClient(app, "bob")
    assert "70.77.86.53" not in bob_client.get("/account/logins").text
    assert bob_client.get(f"/admin/users/{karo.id}/logins").status_code == 403

    admin = UserClient(app, "sam")
    page = admin.get(f"/admin/users/{karo.id}/logins").text
    assert "Calgary, Alberta, Canada" in page and "can see this list too" in page
    assert admin.get(f"/admin/users/{bob.id + 99}/logins").status_code == 404
    assert f"/admin/users/{karo.id}/logins" in admin.get("/admin/users").text


def test_old_history_is_pruned(app, make_user, session):
    from datetime import timedelta

    from jobhunter.db import utcnow

    user = make_user("karo")
    session.add(LoginEvent(user_id=user.id, at=utcnow() - timedelta(days=200), ip="1.1.1.1"))
    session.commit()
    _login_from(app, "karo", "70.77.86.53")
    session.expire_all()
    ips = [e.ip for e in session.exec(select(LoginEvent)).all()]
    assert ips == ["70.77.86.53"]


def test_locate_and_device_helpers():
    assert login_history.locate("192.168.1.20") == "local network"
    assert login_history.locate("not an ip") == ""
    assert login_history.device("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Firefox/130.0") == (
        "Firefox on Mac"
    )


def test_monthly_database_download(db_path, monkeypatch):
    payload = b"fake mmdb bytes"
    urls = []

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield gzip.compress(payload)

    @contextmanager
    def stream(method, url, timeout):
        urls.append(url)
        yield Resp()

    monkeypatch.setattr(login_history.httpx, "stream", stream)
    monkeypatch.setattr(login_history, "_last_attempt", 0.0)
    assert login_history.refresh_if_due() is False  # GEOIP_DOWNLOAD=off in tests
    monkeypatch.setenv("GEOIP_DOWNLOAD", "on")
    assert login_history.refresh_if_due() is True
    path = login_history.db_path()
    assert path.read_bytes() == payload and "dbip-city-lite-" in urls[0]
    assert login_history.refresh_if_due() is False  # fresh: nothing to do
    old = time.time() - 40 * 86400
    os.utime(path, (old, old))
    assert login_history.refresh_if_due() is False  # a retry waits for the cooldown
