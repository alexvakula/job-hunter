"""Master resume, per-job Apply page, documents and the application email (feature 004)."""

import hmac
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_session, utcnow
from jobhunter.models import (
    Contact,
    DocumentVersion,
    Job,
    MasterResume,
    ResumeFile,
    SenderSettings,
    TailoredResume,
    UserAccount,
)
from jobhunter.services import drafts, resumes
from jobhunter.services.resume import apply_email, ats, importer, model, tailor, versions
from jobhunter.web import render

router = APIRouter()
BLANK = {"experience": 1, "education": 1, "certifications": 1}


# --- master resume -------------------------------------------------------------------------


def _master(db: Session, user: UserAccount) -> MasterResume | None:
    return db.get(MasterResume, user.id)


def _editor(request, db, user, data: dict, status_code=200, **extra):
    current_file = db.exec(
        select(ResumeFile).where(ResumeFile.user_id == user.id, ResumeFile.is_current.is_(True))
    ).first()
    data = model.normalise(data)
    rows = {s: data[s] + [{}] * BLANK[s] for s in BLANK}
    return render(
        request,
        "resume/editor.html",
        status_code=status_code,
        d=data,
        rows=rows,
        skills_text=model.skills_text(data),
        current_file=current_file,
        **extra,
    )


@router.get("/resume")
def resume_editor(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    master = _master(db, user)
    return _editor(
        request,
        db,
        user,
        master.data if master else model.empty(),
        saved=request.query_params.get("saved"),
    )


@router.post("/resume", dependencies=[Depends(csrf_protect)])
async def save_resume(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    data, errors = model.from_form(await request.form())
    if errors:
        return _editor(request, db, user, data, 422, errors=errors)
    master = _master(db, user) or MasterResume(user_id=user.id)
    master.data, master.updated_at = data, utcnow()
    db.add(master)
    db.commit()
    return RedirectResponse("/resume?saved=1", status_code=303)


@router.post("/resume/import", dependencies=[Depends(csrf_protect)])
def import_resume(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    current = db.exec(
        select(ResumeFile).where(ResumeFile.user_id == user.id, ResumeFile.is_current.is_(True))
    ).first()
    if current is None:
        return _editor(
            request,
            db,
            user,
            model.empty(),
            422,
            error="Upload your resume first (Settings → My resume).",
        )
    try:
        data = importer.import_resume(resumes.path_for(current).read_bytes(), current.format)
    except (importer.ImportError_, OSError, ValueError) as exc:
        message = (
            str(exc) if isinstance(exc, importer.ImportError_) else "The file could not be read."
        )
        return _editor(request, db, user, model.empty(), 422, error=message)
    return _editor(request, db, user, data, imported=current.original_name)


# --- per-job apply page --------------------------------------------------------------------


def _keywords(job: Job) -> list[str]:
    return ats.extract_keywords(job.description or "")


def _draft(db, user, job, master: MasterResume, keywords) -> TailoredResume:
    t = db.exec(
        select(TailoredResume).where(
            TailoredResume.user_id == user.id, TailoredResume.job_id == job.id
        )
    ).first()
    if t is None:
        d = tailor.build_draft(master.data, keywords)
        contact = db.exec(select(Contact).where(Contact.job_id == job.id)).first()
        t = TailoredResume(
            user_id=user.id,
            job_id=job.id,
            summary=d["summary"],
            experience=d["experience"],
            skills=d["skills"],
            cover_letter=tailor.default_cover_letter(
                master.data, job, contact.name if contact else None, keywords
            ),
        )
        db.add(t)
        db.commit()
        db.refresh(t)
    else:
        skills = tailor.top_up_from_posting(master.data, t.skills, keywords)
        if len(skills) != len(t.skills):  # drafts made before these were added
            t.skills = skills
            db.add(t)
            db.commit()
            db.refresh(t)
    return t


def _as_draft(t: TailoredResume) -> dict:
    return {"summary": t.summary, "experience": t.experience, "skills": t.skills}


def _apply_context(db, user, job, master, t, keywords) -> dict:
    draft = _as_draft(t)
    snap = tailor.snapshot(master.data, draft)
    master_cov = ats.coverage(keywords, model.full_text(master.data))
    visible = tailor.visible_text(snap)
    tailored_cov = ats.coverage(keywords, visible)
    analysis = tailor.skill_analysis(master.data, t.skills, keywords, visible)
    flags = tailor.honesty_flags(master.data, tailor.editable_text(draft, t.cover_letter), keywords)
    m = model.normalise(master.data)
    facts = {e["id"]: e for e in m["experience"]}
    doc_versions = db.exec(
        select(DocumentVersion)
        .where(DocumentVersion.job_id == job.id, DocumentVersion.user_id == user.id)
        .order_by(DocumentVersion.number.desc())
    ).all()
    sender = db.get(SenderSettings, user.id)
    compose = apply_email.defaults(db, job, m["name"], t.cover_letter)
    return {
        "job": job,
        "t": t,
        "facts": facts,
        "keywords": keywords,
        "master_cov": master_cov,
        "tailored_cov": tailored_cov,
        "analysis": analysis,
        "flags": flags,
        "versions": doc_versions,
        "stale": master.updated_at > t.updated_at,
        "compose": compose,
        "sender": sender,
        "m": m,
    }


def _require_master(db, user):
    master = _master(db, user)
    if master is None or not model.normalise(master.data)["experience"]:
        return None
    return master


@router.get("/jobs/{job_id}/apply")
def apply_page(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    master = _require_master(db, user)
    if master is None:
        return render(request, "resume/no_master.html", job=job)
    keywords = _keywords(job)
    t = _draft(db, user, job, master, keywords)
    return render(
        request, "resume/apply.html", **_apply_context(db, user, job, master, t, keywords)
    )


@router.post("/jobs/{job_id}/apply/tailor", dependencies=[Depends(csrf_protect)])
async def save_tailored(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    master = _require_master(db, user)
    if master is None:
        return RedirectResponse(f"/jobs/{job.id}/apply", status_code=303)
    form = await request.form()
    t = _draft(db, user, job, master, _keywords(job))
    edited = tailor.apply_form(_as_draft(t), form)
    t.summary, t.experience, t.skills = edited["summary"], edited["experience"], edited["skills"]
    t.cover_letter = str(form.get("cover_letter") or "").replace("\r\n", "\n").strip()
    t.updated_at = utcnow()
    db.add(t)
    db.commit()
    return RedirectResponse(f"/jobs/{job.id}/apply?saved=1#tailor", status_code=303)


@router.post("/jobs/{job_id}/apply/reset", dependencies=[Depends(csrf_protect)])
def reset_tailored(
    job_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    job = repo.get_owned(db, Job, job_id, user.id)
    t = db.exec(
        select(TailoredResume).where(
            TailoredResume.user_id == user.id, TailoredResume.job_id == job.id
        )
    ).first()
    if t is not None:
        db.delete(t)
        db.commit()
    return RedirectResponse(f"/jobs/{job.id}/apply#tailor", status_code=303)


@router.post("/jobs/{job_id}/apply/generate", dependencies=[Depends(csrf_protect)])
async def generate(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    master = _require_master(db, user)
    if master is None:
        return RedirectResponse(f"/jobs/{job.id}/apply", status_code=303)
    keywords = _keywords(job)
    t = _draft(db, user, job, master, keywords)
    ctx = _apply_context(db, user, job, master, t, keywords)
    if ctx["flags"]:
        return render(request, "resume/apply.html", status_code=409, blocked=True, **ctx)
    snap = tailor.snapshot(master.data, _as_draft(t))
    version = await run_in_threadpool(
        versions.generate,
        db,
        user.id,
        job,
        snap,
        t.cover_letter,
        ctx["master_cov"].percent,
        ctx["tailored_cov"].percent,
    )
    return RedirectResponse(
        f"/jobs/{job.id}/apply?generated={version.number}#documents", status_code=303
    )


@router.get("/documents/{version_id}/{kind}")
def download(
    version_id: int,
    kind: str,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    version = repo.get_owned(db, DocumentVersion, version_id, user.id)
    if kind not in versions.FILES:
        raise repo.not_found()
    path = versions.path_for(version, kind)
    if path is None or not path.is_file():
        raise repo.not_found()
    name = versions.download_name(version, kind)
    ascii_name = name.encode("ascii", "ignore").decode().replace('"', "") or "document"
    return Response(
        content=path.read_bytes(),
        media_type=versions.MEDIA[kind.rsplit(".", 1)[1]],
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(name)}",
            "Cache-Control": "private, no-store",
        },
    )


# --- application email ---------------------------------------------------------------------


def _attachment_choices(db, user, job) -> list[tuple[str, str]]:
    out = []
    for v in db.exec(
        select(DocumentVersion)
        .where(DocumentVersion.job_id == job.id, DocumentVersion.user_id == user.id)
        .order_by(DocumentVersion.number.desc())
    ).all():
        for kind in versions.FILES:
            out.append((f"{v.id}:{kind}", versions.download_name(v, kind)))
    return out


@router.post("/jobs/{job_id}/apply/preview", dependencies=[Depends(csrf_protect)])
async def preview(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    compose, errors = apply_email.from_form(await request.form())
    sender = db.get(SenderSettings, user.id)
    files, att_error = apply_email.resolve_attachments(db, user.id, job.id, compose.attachments)
    if att_error:
        errors["attachments"] = att_error
    if sender is None or not sender.from_address:
        errors["sender"] = "Set up Settings → Sender email first."
    if errors:
        return render(
            request,
            "resume/compose.html",
            status_code=422,
            job=job,
            compose=compose,
            errors=errors,
            choices=_attachment_choices(db, user, job),
            sender=sender,
        )
    return render(
        request,
        "resume/preview.html",
        job=job,
        compose=compose,
        sender=sender,
        files=[(n, m, len(d)) for n, m, d in files],
        token=apply_email.token(compose, user.id, job.id),
    )


@router.post("/jobs/{job_id}/apply/compose", dependencies=[Depends(csrf_protect)])
async def compose_page(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    """Back from the preview to edit (keeps the values)."""
    job = repo.get_owned(db, Job, job_id, user.id)
    compose, _ = apply_email.from_form(await request.form())
    return render(
        request,
        "resume/compose.html",
        job=job,
        compose=compose,
        errors={},
        choices=_attachment_choices(db, user, job),
        sender=db.get(SenderSettings, user.id),
    )


@router.get("/jobs/{job_id}/apply/compose")
def compose_new(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    t = db.exec(
        select(TailoredResume).where(
            TailoredResume.user_id == user.id, TailoredResume.job_id == job.id
        )
    ).first()
    master = _master(db, user)
    name = model.normalise(master.data)["name"] if master else user.display_name
    compose = apply_email.defaults(db, job, name, t.cover_letter if t else "")
    saved = drafts.find(db, user.id, job_id=job.id)
    if saved is not None and request.query_params.get("fresh") != "1":
        compose = drafts.as_compose(saved, compose)
    return render(
        request,
        "resume/compose.html",
        job=job,
        compose=compose,
        errors={},
        choices=_attachment_choices(db, user, job),
        sender=db.get(SenderSettings, user.id),
        saved=saved,
        fresh=request.query_params.get("fresh") == "1",
        just_saved=request.query_params.get("saved") == "1",
    )


@router.post("/jobs/{job_id}/apply/save", dependencies=[Depends(csrf_protect)])
async def save_draft(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    compose, _ = apply_email.from_form(await request.form())  # a draft may be incomplete
    drafts.save(db, user.id, compose, job_id=job.id)
    return RedirectResponse(f"/jobs/{job.id}/apply/compose?saved=1", status_code=303)


@router.post("/jobs/{job_id}/apply/discard", dependencies=[Depends(csrf_protect)])
def discard_draft(
    job_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    drafts.discard(db, user.id, job_id=job.id)
    return RedirectResponse("/mail?view=drafts", status_code=303)


@router.post("/jobs/{job_id}/apply/send", dependencies=[Depends(csrf_protect)])
async def send(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    form = await request.form()
    compose, errors = apply_email.from_form(form)
    expected = apply_email.token(compose, user.id, job.id)
    given = str(form.get("token") or "")
    if errors or not hmac.compare_digest(given, expected):
        return render(
            request,
            "resume/compose.html",
            status_code=400,
            job=job,
            compose=compose,
            errors={
                **errors,
                "preview": "The email changed after the preview. Preview it again before sending.",
            },
            choices=_attachment_choices(db, user, job),
            sender=db.get(SenderSettings, user.id),
        )
    sender = db.get(SenderSettings, user.id)
    files, att_error = apply_email.resolve_attachments(db, user.id, job.id, compose.attachments)
    if form.get("confirm") != "yes" or att_error or sender is None:
        return render(
            request,
            "resume/preview.html",
            status_code=400,
            job=job,
            compose=compose,
            sender=sender,
            files=[(n, m, len(d)) for n, m, d in files],
            token=expected,
            error=att_error or "Tick “I have reviewed this email” to send it.",
        )
    ok, message = await run_in_threadpool(apply_email.send, db, user, sender, job, compose, files)
    if ok:
        drafts.discard(db, user.id, job_id=job.id)
    return render(
        request, "resume/sent.html", status_code=200 if ok else 502, job=job, ok=ok, message=message
    )
