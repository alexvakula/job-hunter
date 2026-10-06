"""Storing generated documents as immutable numbered versions per job (FR-011)."""

import uuid
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from jobhunter.models import DocumentVersion, Job
from jobhunter.services.resume import render
from jobhunter.services.resumes import uploads_dir

FILES = {
    "resume.docx": "resume_docx",
    "resume.pdf": "resume_pdf",
    "letter.docx": "letter_docx",
    "letter.pdf": "letter_pdf",
}
MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def documents_dir(user_id: int) -> Path:
    return uploads_dir().parent / "documents" / str(user_id)


def path_for(version: DocumentVersion, kind: str) -> Path | None:
    name = getattr(version, FILES[kind])
    return documents_dir(version.user_id) / name if name else None


def _write(user_id: int, ext: str, data: bytes) -> str:
    folder = documents_dir(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    tmp = folder / (name + ".part")
    tmp.write_bytes(data)
    tmp.replace(folder / name)
    return name


def generate(
    session: Session,
    user_id: int,
    job: Job,
    snap: dict,
    letter: str,
    ats_master: int | None,
    ats_tailored: int | None,
) -> DocumentVersion:
    number = (
        session.exec(
            select(func.max(DocumentVersion.number)).where(
                DocumentVersion.user_id == user_id, DocumentVersion.job_id == job.id
            )
        ).one()
        or 0
    ) + 1
    version = DocumentVersion(
        user_id=user_id,
        job_id=job.id,
        number=number,
        content={
            "resume": snap,
            "cover_letter": letter,
            "job": {"title": job.title, "company": job.company},
        },
        ats_master=ats_master,
        ats_tailored=ats_tailored,
        resume_docx=_write(user_id, "docx", render.resume_docx(snap)),
        resume_pdf=_write(user_id, "pdf", render.resume_pdf(snap)),
        letter_docx=_write(user_id, "docx", render.letter_docx(snap, letter)),
        letter_pdf=_write(user_id, "pdf", render.letter_pdf(snap, letter)),
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def download_name(version: DocumentVersion, kind: str) -> str:
    who = (version.content.get("resume", {}).get("name") or "Resume").replace(" ", "_")
    company = (version.content.get("job", {}).get("company") or "").replace(" ", "_")
    stem = "Resume" if kind.startswith("resume") else "Cover_Letter"
    ext = kind.rsplit(".", 1)[1]
    return f"{who}_{stem}_{company}_v{version.number}.{ext}".replace("__", "_")
