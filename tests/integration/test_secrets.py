"""No secret value ever appears in pages, logs or the database file (SC-006, constitution IV)."""

import logging
import re

from sqlmodel import select

from jobhunter.models import Job, Note, ResumeFile, Source, TargetProfile, UserAccount
from tests.conftest import TEST_SECRET
from tests.integration.test_isolation import PARAM_RE, _routes
from tests.resume_samples import pdf_bytes

MAIL_SECRET = "mail-password-that-must-never-leak"
BCRYPT_RE = re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}")


def test_secrets_never_leak(app, make_user, user_client, session, db_path, monkeypatch, caplog):
    monkeypatch.setenv("SMTP_PASSWORD_SAM", MAIL_SECRET)
    monkeypatch.setenv("SMTP_PASSWORD_KID", MAIL_SECRET)
    make_user("sam", role="admin")
    make_user("kid")
    admin, kid = user_client("sam"), user_client("kid")

    with caplog.at_level(logging.DEBUG):
        for client in (admin, kid):
            client.post(
                "/jobs", data={"title": "QA Lead", "company": "Acme", "url": "https://a.test/1"}
            )
            client.post(
                "/settings/profiles/new",
                data={"name": "P", "rules-0-place": "Calgary", "rules-0-remote": "1"},
            )
            client.post("/settings/resume", files={"file": ("r.pdf", pdf_bytes())})
            client.post(
                "/settings/sender",
                data={
                    "from_address": "x@example.org",
                    "smtp_host": "smtp.invalid",
                    "smtp_port": "587",
                },
            )
        ids_by_user = {}
        for name in ("sam", "kid"):
            uid = session.exec(select(UserAccount).where(UserAccount.username == name)).one().id
            job = session.exec(select(Job).where(Job.user_id == uid)).one()
            admin_or_kid = admin if name == "sam" else kid
            admin_or_kid.post(f"/jobs/{job.id}/notes", data={"body": "note"})
            ids_by_user[name] = {
                "job_id": job.id,
                "note_id": session.exec(select(Note).where(Note.job_id == job.id)).one().id,
                "profile_id": session.exec(
                    select(TargetProfile).where(TargetProfile.user_id == uid)
                )
                .one()
                .id,
                "resume_id": session.exec(select(ResumeFile).where(ResumeFile.user_id == uid))
                .one()
                .id,
                "user_id": uid,
                "source_id": session.exec(select(Source)).first().id,
            }

        pages = []
        for name, client in (("sam", admin), ("kid", kid)):
            ids = ids_by_user[name]
            for route in _routes(app):
                if "GET" not in route.methods:
                    continue
                params = PARAM_RE.findall(route.path)
                if any(p not in ids for p in params):
                    continue
                path = route.path
                for p in params:
                    path = path.replace("{" + p + "}", str(ids[p]))
                resp = client.get(path)
                pages.append((path, resp.content))
        assert len(pages) > 15

    for path, body in pages:
        assert MAIL_SECRET.encode() not in body, path
        assert TEST_SECRET.encode() not in body, path
        assert not BCRYPT_RE.search(body.decode("utf-8", "ignore")), path
    assert MAIL_SECRET not in caplog.text and TEST_SECRET not in caplog.text
    assert not BCRYPT_RE.search(caplog.text)

    session.close()
    raw = db_path.read_bytes() + b"".join(p.read_bytes() for p in db_path.parent.glob("*.db-wal"))
    assert MAIL_SECRET.encode() not in raw and TEST_SECRET.encode() not in raw
