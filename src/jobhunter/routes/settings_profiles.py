"""Settings: target-position profiles (contracts/http-routes.md "Settings")."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_session
from jobhunter.models import LocationRule, Source, TargetProfile, UserAccount
from jobhunter.routes.detail import WORK_MODE_LABELS
from jobhunter.services import profiles as svc
from jobhunter.web import render

router = APIRouter()
BLANK_ROWS = 2


def _form_context(
    db: Session,
    profile: TargetProfile | None,
    data: svc.ProfileInput | None,
    errors: dict | None = None,
) -> dict:
    if data is None:
        if profile is None:
            data = svc.ProfileInput()
        else:
            data = svc.ProfileInput(
                name=profile.name,
                synonyms=", ".join(profile.synonyms),
                include_keywords=", ".join(profile.include_keywords),
                exclude_keywords=", ".join(profile.exclude_keywords),
                seniority=profile.seniority or "",
                source_ids=[str(i) for i in profile.source_ids],
                rules=[
                    svc.RuleInput(
                        place=r.place,
                        work_modes=list(r.work_modes),
                        floor="" if r.salary_floor is None else str(r.salary_floor),
                        currency=r.salary_currency or "",
                    )
                    for r in svc.rules_for(db, profile)
                ],
            )
    rows = list(data.rules) + [svc.RuleInput() for _ in range(BLANK_ROWS)]
    return {
        "profile": profile,
        "data": data,
        "rows": rows,
        "errors": errors or {},
        # Disabled sources are hidden unless this profile already uses them (FR-028).
        "sources": [
            s
            for s in db.exec(select(Source).order_by(Source.name)).all()
            if s.enabled or str(s.id) in data.source_ids
        ],
        "rule_modes": [(m, WORK_MODE_LABELS[m]) for m in svc.RULE_MODES],
    }


@router.get("/settings")
def settings_index(request: Request, _user: UserAccount = Depends(current_user)):
    return render(request, "settings/index.html")


@router.get("/settings/profiles")
def list_profiles(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    rows = db.exec(
        repo.scoped(TargetProfile, user.id).order_by(TargetProfile.is_archived, TargetProfile.name)
    ).all()
    rules = {
        p.id: db.exec(
            select(LocationRule).where(LocationRule.profile_id == p.id).order_by(LocationRule.id)
        ).all()
        for p in rows
    }
    return render(
        request, "settings/profiles.html", profiles=rows, rules=rules, work_modes=WORK_MODE_LABELS
    )


@router.get("/settings/profiles/new")
def new_profile_form(
    request: Request, _user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    return render(request, "settings/profile_form.html", **_form_context(db, None, None))


@router.post("/settings/profiles/new", dependencies=[Depends(csrf_protect)])
async def create_profile(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    data = svc.parse_form(await request.form())
    v = svc.validate(db, user.id, data)
    if v.errors:
        return render(
            request,
            "settings/profile_form.html",
            status_code=422,
            **_form_context(db, None, data, v.errors),
        )
    svc.create_profile(db, user.id, v)
    return RedirectResponse("/settings/profiles", status_code=303)


@router.get("/settings/profiles/{profile_id}")
def edit_profile_form(
    profile_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    profile = repo.get_owned(db, TargetProfile, profile_id, user.id)
    return render(request, "settings/profile_form.html", **_form_context(db, profile, None))


@router.post("/settings/profiles/{profile_id}", dependencies=[Depends(csrf_protect)])
async def edit_profile(
    profile_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    profile = repo.get_owned(db, TargetProfile, profile_id, user.id)
    data = svc.parse_form(await request.form())
    v = svc.validate(db, user.id, data, profile_id=profile.id)
    if v.errors:
        return render(
            request,
            "settings/profile_form.html",
            status_code=422,
            **_form_context(db, profile, data, v.errors),
        )
    svc.update_profile(db, profile, v)
    return RedirectResponse("/settings/profiles", status_code=303)


@router.post("/settings/profiles/{profile_id}/default", dependencies=[Depends(csrf_protect)])
def make_default(
    profile_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    svc.set_default(db, repo.get_owned(db, TargetProfile, profile_id, user.id))
    return RedirectResponse("/settings/profiles", status_code=303)


@router.post("/settings/profiles/{profile_id}/archive", dependencies=[Depends(csrf_protect)])
async def archive(
    profile_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    profile = repo.get_owned(db, TargetProfile, profile_id, user.id)
    form = await request.form()
    svc.set_archived(db, profile, archived=form.get("restore") != "1")
    return RedirectResponse("/settings/profiles", status_code=303)


@router.post("/settings/profiles/{profile_id}/delete", dependencies=[Depends(csrf_protect)])
async def delete(
    profile_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    profile = repo.get_owned(db, TargetProfile, profile_id, user.id)
    form = await request.form()
    if form.get("confirm") != "yes":
        return render(
            request,
            "settings/profile_form.html",
            status_code=400,
            delete_error=True,
            **_form_context(db, profile, None),
        )
    svc.delete_profile(db, profile)
    return RedirectResponse("/settings/profiles", status_code=303)
