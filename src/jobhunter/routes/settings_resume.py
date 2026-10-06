"""Settings: the user's uploaded resumes (US7, contracts/http-routes.md "Resume")."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session
from starlette.datastructures import UploadFile

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_session
from jobhunter.models import ResumeFile, UserAccount
from jobhunter.services import resumes as svc
from jobhunter.web import render

router = APIRouter()


def _page(request: Request, db: Session, user: UserAccount, status_code: int = 200, **extra):
    return render(
        request,
        "settings/resume.html",
        status_code=status_code,
        resumes=svc.list_for(db, user.id),
        **extra,
    )


@router.get("/settings/resume")
def resume_page(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    return _page(request, db, user)


@router.post("/settings/resume", dependencies=[Depends(csrf_protect)])
async def upload_resume(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _page(request, db, user, 422, error="Choose a file to upload.")
    data = await upload.read(svc.MAX_BYTES + 1)
    try:
        svc.save_upload(db, user, upload.filename, data)
    except svc.UploadError as exc:
        return _page(request, db, user, 422, error=str(exc))
    return RedirectResponse("/settings/resume", status_code=303)


@router.get("/settings/resume/{resume_id}/download")
def download_resume(
    resume_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    resume = repo.get_owned(db, ResumeFile, resume_id, user.id)
    path = svc.path_for(resume)
    if not path.is_file():
        raise repo.not_found()
    ascii_name = resume.original_name.encode("ascii", "ignore").decode() or "resume"
    ascii_name = ascii_name.replace('"', "")
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(resume.original_name)}"
    )
    return Response(
        content=path.read_bytes(),
        media_type=svc.MEDIA_TYPES[resume.format],
        headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store"},
    )


@router.post("/settings/resume/{resume_id}/current", dependencies=[Depends(csrf_protect)])
def make_current(
    resume_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    svc.set_current(db, repo.get_owned(db, ResumeFile, resume_id, user.id))
    return RedirectResponse("/settings/resume", status_code=303)


@router.post("/settings/resume/{resume_id}/delete", dependencies=[Depends(csrf_protect)])
async def delete_resume(
    resume_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    resume = repo.get_owned(db, ResumeFile, resume_id, user.id)
    form = await request.form()
    if form.get("confirm") != "yes":
        return _page(request, db, user, 400, error='Tick "Yes, delete" to confirm.')
    svc.delete_resume(db, resume)
    return RedirectResponse("/settings/resume", status_code=303)
