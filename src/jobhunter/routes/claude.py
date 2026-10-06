"""Claude pages and buttons (feature 005), for users with their own Claude token (constitution
VIII)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, require_claude
from jobhunter.db import get_session
from jobhunter.models import ClaudeJob, Job, ResumeFile, UserAccount
from jobhunter.services.claude import cli, queue
from jobhunter.services.resume import model
from jobhunter.web import is_htmx, render

router = APIRouter(dependencies=[Depends(require_claude)])
KIND_LABELS = {
    "find_jobs": "Find jobs",
    "fit_rank": "Fit ranking",
    "tailor": "Tailoring",
    "import": "Resume import",
    "prep": "Interview prep",
}


def _queue(db, user, kind, payload, request):
    try:
        job = queue.enqueue(db, user, kind, payload)
    except queue.NotAllowed:
        return render(
            request, "claude/index.html", status_code=409, **_page(db, user), error=cli.TOKEN_HELP
        )
    return RedirectResponse(f"/claude/jobs/{job.id}", status_code=303)


def _page(db, user) -> dict:
    jobs = db.exec(
        select(ClaudeJob)
        .where(ClaudeJob.user_id == user.id)
        .order_by(ClaudeJob.created_at.desc(), ClaudeJob.id.desc())
        .limit(30)
    ).all()
    return {
        "jobs": jobs,
        "token": cli.token_configured(user),
        "installed": cli.binary() is not None,
        "labels": KIND_LABELS,
        "models": [
            (KIND_LABELS.get(k, k), cli.model_name(cli.model_for(k))) for k in cli.DEFAULT_MODELS
        ],
    }


@router.get("/claude")
def claude_page(
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    return render(request, "claude/index.html", **_page(db, user))


@router.get("/claude/jobs/{claude_job_id}")
def claude_job(
    claude_job_id: int,
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, ClaudeJob, claude_job_id, user.id)
    template = "claude/_job.html" if is_htmx(request) else "claude/job.html"
    return render(request, template, job=job, labels=KIND_LABELS)


@router.post("/claude/find", dependencies=[Depends(csrf_protect)])
def find(
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    return _queue(db, user, "find_jobs", {}, request)


@router.post("/claude/rank", dependencies=[Depends(csrf_protect)])
def rank(
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    return _queue(db, user, "fit_rank", {}, request)


@router.post("/jobs/{job_id}/apply/claude", dependencies=[Depends(csrf_protect)])
def tailor(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    return _queue(db, user, "tailor", {"job_id": job.id}, request)


@router.post("/jobs/{job_id}/prep", dependencies=[Depends(csrf_protect)])
def prep(
    job_id: int,
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    job = repo.get_owned(db, Job, job_id, user.id)
    return _queue(db, user, "prep", {"job_id": job.id}, request)


@router.post("/resume/claude-import", dependencies=[Depends(csrf_protect)])
def claude_import(
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    current = db.exec(
        select(ResumeFile).where(ResumeFile.user_id == user.id, ResumeFile.is_current.is_(True))
    ).first()
    if current is None:
        return RedirectResponse("/resume", status_code=303)
    return _queue(db, user, "import", {"resume_file_id": current.id}, request)


@router.get("/resume/claude-import/{claude_job_id}")
def open_import(
    claude_job_id: int,
    request: Request,
    user: UserAccount = Depends(require_claude),
    db: Session = Depends(get_session),
):
    """Open the Claude import result in the editor, unsaved (FR-009)."""
    from jobhunter.routes.resume import _editor

    job = repo.get_owned(db, ClaudeJob, claude_job_id, user.id)
    if job.kind != "import" or job.status != "done" or not job.result:
        raise repo.not_found()
    return _editor(request, db, user, model.normalise(job.result), imported="Claude import")
