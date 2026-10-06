from pathlib import Path

from sqlmodel import select

from jobhunter.models import ResumeFile
from jobhunter.services.resumes import MAX_BYTES, path_for
from tests.resume_samples import docx_bytes, pdf_bytes

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _upload(client, name, data, content_type="application/octet-stream"):
    return client.post("/settings/resume", files={"file": (name, data, content_type)})


def _files(session):
    session.expire_all()
    return session.exec(select(ResumeFile).order_by(ResumeFile.id)).all()


def test_upload_versions_download_and_current(two_users, session):
    alice, _ = two_users
    docx, pdf = docx_bytes(), pdf_bytes()
    assert _upload(alice, "Sam Resume 2025.docx", docx, DOCX_TYPE).status_code == 303
    assert _upload(alice, "Sam Resume 2026.pdf", pdf, "application/pdf").status_code == 303
    first, second = _files(session)
    assert (first.format, first.is_current) == ("docx", False)
    assert (second.format, second.is_current) == ("pdf", True)
    assert first.size_bytes == len(docx)

    page = alice.get("/settings/resume").text
    assert "Sam Resume 2025.docx" in page and "Sam Resume 2026.pdf" in page

    resp = alice.get(f"/settings/resume/{first.id}/download")
    assert resp.status_code == 200 and resp.content == docx
    assert resp.headers["content-disposition"].startswith("attachment;")
    assert "Sam%20Resume%202025.docx" in resp.headers["content-disposition"]
    assert resp.headers["x-content-type-options"] == "nosniff"

    alice.post(f"/settings/resume/{first.id}/current")
    first, second = _files(session)
    assert first.is_current and not second.is_current


def test_rejects_fake_and_oversized_files(two_users, session):
    alice, _ = two_users
    resp = _upload(alice, "resume.pdf", b"just text pretending to be a pdf", "application/pdf")
    assert resp.status_code == 422 and "Word (.docx) or PDF" in resp.text
    big = pdf_bytes() + b"0" * MAX_BYTES
    resp = _upload(alice, "big.pdf", big, "application/pdf")
    assert resp.status_code == 422 and "10 MB" in resp.text
    assert alice.post("/settings/resume", data={}).status_code == 422
    assert _files(session) == []


def test_delete_removes_file_and_promotes_newest(two_users, session):
    alice, _ = two_users
    _upload(alice, "a.pdf", pdf_bytes("a"))
    _upload(alice, "b.pdf", pdf_bytes("b"))
    _upload(alice, "c.pdf", pdf_bytes("c"))
    a, b, c = _files(session)
    path = path_for(c)
    assert Path(path).is_file()
    assert alice.post(f"/settings/resume/{c.id}/delete").status_code == 400
    assert alice.post(f"/settings/resume/{c.id}/delete", data={"confirm": "yes"}).status_code == 303
    assert not Path(path).exists()
    remaining = _files(session)
    assert [r.original_name for r in remaining] == ["a.pdf", "b.pdf"]
    assert [r.is_current for r in remaining] == [False, True]


def test_other_user_cannot_access(two_users, session):
    alice, bob = two_users
    _upload(alice, "secret.pdf", pdf_bytes("alice secret"))
    rid = _files(session)[0].id
    assert bob.get(f"/settings/resume/{rid}/download").status_code == 404
    assert bob.post(f"/settings/resume/{rid}/current").status_code == 404
    assert bob.post(f"/settings/resume/{rid}/delete", data={"confirm": "yes"}).status_code == 404
    assert "secret.pdf" not in bob.get("/settings/resume").text
    assert len(_files(session)) == 1
