"""Uploaded resumes (US7, FR-035–FR-039).

Files are stored on disk under a random name in the user's own folder next to the database
(`<data dir>/uploads/resumes/<user_id>/`); the database row keeps the original name, format,
size and hash. The format is decided from the file content, never from the name.
"""

import hashlib
import io
import os
import re
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import update
from sqlmodel import Session, select

from jobhunter.config import get_settings
from jobhunter.models import ResumeFile, UserAccount

MAX_BYTES = 10 * 1024 * 1024
MAX_NAME = 200
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class UploadError(ValueError):
    pass


def detect_format(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except (zipfile.BadZipFile, ValueError):
            pass
    raise UploadError("Upload a Word (.docx) or PDF file.")


def sanitize_name(raw: str) -> str:
    name = re.split(r"[\\/]", raw or "")[-1]
    name = _CONTROL.sub("", name).strip().lstrip(".")
    if not name:
        return "resume"
    if len(name) > MAX_NAME:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: MAX_NAME - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_NAME]
    return name


def uploads_dir() -> Path:
    return Path(get_settings().database_path).resolve().parent / "uploads" / "resumes"


def path_for(resume: ResumeFile) -> Path:
    return uploads_dir() / str(resume.user_id) / resume.storage_name


def save_upload(session: Session, user: UserAccount, filename: str, data: bytes) -> ResumeFile:
    if not data:
        raise UploadError("Choose a file to upload.")
    if len(data) > MAX_BYTES:
        raise UploadError("The file is larger than 10 MB.")
    fmt = detect_format(data)
    storage_name = f"{uuid.uuid4().hex}.{fmt}"
    folder = uploads_dir() / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / storage_name
    tmp = folder / (storage_name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, final)

    session.exec(update(ResumeFile).where(ResumeFile.user_id == user.id).values(is_current=False))
    resume = ResumeFile(
        user_id=user.id,
        original_name=sanitize_name(filename),
        storage_name=storage_name,
        format=fmt,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        is_current=True,
    )
    session.add(resume)
    try:
        session.commit()
    except Exception:
        final.unlink(missing_ok=True)
        raise
    session.refresh(resume)
    return resume


def list_for(session: Session, user_id: int) -> list[ResumeFile]:
    return list(
        session.exec(
            select(ResumeFile)
            .where(ResumeFile.user_id == user_id)
            .order_by(ResumeFile.uploaded_at.desc(), ResumeFile.id.desc())
        ).all()
    )


def set_current(session: Session, resume: ResumeFile) -> None:
    session.exec(
        update(ResumeFile)
        .where(ResumeFile.user_id == resume.user_id, ResumeFile.id != resume.id)
        .values(is_current=False)
    )
    resume.is_current = True
    session.add(resume)
    session.commit()


def delete_resume(session: Session, resume: ResumeFile) -> None:
    path = path_for(resume)
    was_current = resume.is_current
    user_id = resume.user_id
    session.delete(resume)
    session.commit()
    path.unlink(missing_ok=True)
    if was_current:
        newest = session.exec(
            select(ResumeFile)
            .where(ResumeFile.user_id == user_id)
            .order_by(ResumeFile.uploaded_at.desc(), ResumeFile.id.desc())
        ).first()
        if newest is not None:
            set_current(session, newest)
