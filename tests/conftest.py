"""Shared fixtures: a fresh migrated SQLite DB per test, app client, users, login helper."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session

ROOT = Path(__file__).resolve().parents[1]
TEST_SECRET = "test-session-secret-0123456789abcdef0123456789"
PASSWORD = "correct horse battery"


@pytest.fixture
def db_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "test.db"
    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("APP_TIMEZONE", "America/Edmonton")

    from jobhunter import config, db

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.attributes["database_url"] = f"sqlite:///{path}"
    command.upgrade(cfg, "head")
    yield path
    db.get_engine().dispose()
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture
def session(db_path) -> Iterator[Session]:
    from jobhunter.db import get_engine

    with Session(get_engine()) as s:
        yield s


@pytest.fixture
def app(db_path):
    from jobhunter.main import create_app

    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def make_user(session):
    from jobhunter.auth.passwords import hash_password
    from jobhunter.models import UserAccount

    hashed = hash_password(PASSWORD)  # hash once; bcrypt is slow on purpose

    def _make(username: str, role: str = "user", **fields) -> UserAccount:
        user = UserAccount(
            username=username,
            display_name=username.title(),
            role=role,
            password_hash=hashed,
            **fields,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return _make


_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf_from(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match, "no csrf_token in page"
    return match.group(1)


def login(client: TestClient, username: str, password: str = PASSWORD, next: str = "/"):
    page = client.get("/login", params={"next": next})
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "next": next,
            "csrf_token": csrf_from(page.text),
        },
        follow_redirects=False,
    )


class UserClient:
    """A logged-in TestClient that adds the session CSRF token to POSTs."""

    def __init__(self, app, username: str):
        self.client = TestClient(app, base_url="http://testserver")
        resp = login(self.client, username)
        assert resp.status_code == 303, resp.text
        from jobhunter.db import get_engine
        from jobhunter.models import UserSession

        with Session(get_engine()) as s:
            row = s.get(UserSession, self.client.cookies.get("jh_session"))
            self.csrf = row.csrf_token

    def get(self, url, **kw):
        kw.setdefault("follow_redirects", False)
        return self.client.get(url, **kw)

    def post(self, url, data=None, **kw):
        kw.setdefault("follow_redirects", False)
        data = dict(data or {})
        data.setdefault("csrf_token", self.csrf)
        return self.client.post(url, data=data, **kw)


@pytest.fixture
def user_client(app):
    def _make(username: str) -> UserClient:
        return UserClient(app, username)

    return _make


@pytest.fixture
def two_users(make_user, user_client):
    make_user("alice")
    make_user("bob")
    return user_client("alice"), user_client("bob")
