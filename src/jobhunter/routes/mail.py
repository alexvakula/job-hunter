"""Job mailbox pages: settings, saved mail, suggestions and the Job sources page (feature 002)."""

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_
from sqlmodel import Session, select

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.config import smtp_password_env_name, smtp_password_for
from jobhunter.db import get_session
from jobhunter.models import (
    EmailAttachment,
    EmailMessage,
    Job,
    JobSuggestion,
    MailboxSettings,
    Source,
    UserAccount,
)
from jobhunter.routes.detail import WORK_MODE_LABELS
from jobhunter.routes.watchlist import get_launcher
from jobhunter.services import imap_client, mail_store, mailbox, profiles
from jobhunter.services.fetch import get_fetcher
from jobhunter.services.jobs import manual_source
from jobhunter.services.resumes import sanitize_name
from jobhunter.web import render

router = APIRouter()
PAGE_SIZE = 50
VIEWS = {"all", "linked", "unlinked", "alerts", "sent"}
EMAIL_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)


def get_connector():
    """Dependency so tests can replace the IMAP connection."""
    return imap_client.connect


def _settings(db: Session, user: UserAccount) -> MailboxSettings | None:
    return db.get(MailboxSettings, user.id)


# --- settings ------------------------------------------------------------------------------


def _settings_page(request, user, s, status_code=200, **extra):
    return render(
        request,
        "settings/mailbox.html",
        status_code=status_code,
        s=s,
        password_configured=smtp_password_for(user.username) is not None,
        password_env=smtp_password_env_name(user.username),
        **extra,
    )


@router.get("/settings/mailbox")
def mailbox_settings(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    s = _settings(db, user) or MailboxSettings(user_id=user.id, address="")
    return _settings_page(request, user, s)


@router.post("/settings/mailbox", dependencies=[Depends(csrf_protect)])
async def save_mailbox_settings(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    form = await request.form()
    errors: dict[str, str] = {}
    address = str(form.get("address") or "").strip()
    try:
        address = validate_email(address, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        errors["address"] = "Enter the job mailbox address, e.g. sam.jobs@example.org."
    taken = db.exec(select(MailboxSettings).where(MailboxSettings.address == address)).first()
    if taken is not None and taken.user_id != user.id:
        errors["address"] = "This mailbox is already used by another account."
    host = str(form.get("imap_host") or "").strip()
    if not host or " " in host:
        errors["imap_host"] = "Enter the mail server host."
    try:
        port = int(str(form.get("imap_port") or "993"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        errors["imap_port"] = "Enter a port between 1 and 65535."
        port = 993
    s = _settings(db, user) or MailboxSettings(user_id=user.id, address=address)
    s.address, s.imap_host, s.imap_port = address, host, port
    s.checking_enabled = form.get("checking_enabled") == "1"
    s.filing_enabled = form.get("filing_enabled") == "1"
    if errors:
        db.expunge_all()
        return _settings_page(request, user, s, 422, errors=errors)
    db.add(s)
    db.commit()
    return RedirectResponse("/settings/mailbox?saved=1", status_code=303)


# --- checking ------------------------------------------------------------------------------


@router.post("/mail/check", dependencies=[Depends(csrf_protect)])
async def check_now(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    connect=Depends(get_connector),
):
    result = await run_in_threadpool(mailbox.check_mailbox, db, user, connect)
    back = request.headers.get("referer") or "/mail"
    target = "/sources" if back.rstrip("/").endswith("/sources") else "/mail"
    return render(request, "mail/check_result.html", result=result, back=target)


@router.post("/sources/import", dependencies=[Depends(csrf_protect)])
async def import_all(
    request: Request,
    user: UserAccount = Depends(current_user),
    connect=Depends(get_connector),
    launcher=Depends(get_launcher),
    fetcher=Depends(get_fetcher),
):
    """Mailbox check + automatic searches (feature 003 FR-013), in the background."""
    from jobhunter.db import get_engine
    from jobhunter.services.search import runner

    if runner.is_running(user.id):
        return RedirectResponse("/sources?running=1", status_code=303)
    user_id = user.id

    def job():
        # expire_on_commit=False: the results are read after this session closes.
        with Session(get_engine(), expire_on_commit=False) as s:
            u = s.get(UserAccount, user_id)
            has_mailbox = s.get(MailboxSettings, user_id) is not None
            mail = mailbox.check_mailbox(s, u, connect) if has_mailbox else None
            try:
                run = runner.run_searches(s, u, "user", fetcher)
            except runner.AlreadyRunning:
                run = None
            return mail, run

    result = launcher(job)
    if result is None:
        return RedirectResponse("/sources?started=1", status_code=303)
    mail, run = result
    return render(request, "mail/import_result.html", mail=mail, run=run)


# --- saved mail ----------------------------------------------------------------------------


@router.get("/mail")
def mail_list(
    request: Request,
    view: str = "all",
    q: str = "",
    page: int = 1,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    view = view if view in VIEWS else "all"
    stmt = select(EmailMessage).where(EmailMessage.user_id == user.id)
    if view == "linked":
        stmt = stmt.where(EmailMessage.job_id.is_not(None))
    elif view == "unlinked":
        stmt = stmt.where(
            EmailMessage.job_id.is_(None), EmailMessage.kind.in_(["other", "employer"])
        )
    elif view == "alerts":
        stmt = stmt.where(EmailMessage.kind == "alert")
    elif view == "sent":
        stmt = stmt.where(EmailMessage.direction == "out")
    if q.strip():
        needle = q.strip().lower()
        stmt = stmt.where(
            or_(
                func.lower(EmailMessage.subject).contains(needle, autoescape=True),
                func.lower(EmailMessage.from_addr).contains(needle, autoescape=True),
                func.lower(EmailMessage.from_name).contains(needle, autoescape=True),
                func.lower(EmailMessage.body_text).contains(needle, autoescape=True),
            )
        )
    total = db.exec(select(func.count()).select_from(stmt.subquery())).one()
    page = max(page, 1)
    emails = db.exec(
        stmt.order_by(EmailMessage.saved_at.desc(), EmailMessage.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    jobs = {j.id: j for j in db.exec(repo.scoped(Job, user.id)).all()}
    return render(
        request,
        "mail/list.html",
        emails=emails,
        total=total,
        view=view,
        q=q,
        page=page,
        pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        jobs=jobs,
        mailbox=_settings(db, user),
    )


@router.get("/mail/{email_id}")
def mail_view(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = repo.get_owned(db, EmailMessage, email_id, user.id)
    jobs = db.exec(repo.scoped(Job, user.id).order_by(Job.company, Job.title)).all()
    suggestions = db.exec(
        select(JobSuggestion).where(JobSuggestion.email_id == email.id).order_by(JobSuggestion.id)
    ).all()
    response = render(
        request,
        "mail/view.html",
        email=email,
        attachments=mail_store.attachments_of(db, email),
        jobs=jobs,
        job=db.get(Job, email.job_id) if email.job_id else None,
        candidates=[j for j in jobs if j.id in (email.candidates or [])],
        suggestions=suggestions,
    )
    response.headers["Content-Security-Policy"] = EMAIL_CSP
    return response


@router.get("/mail/{email_id}/attachments/{attachment_id}")
def mail_attachment(
    email_id: int,
    attachment_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = repo.get_owned(db, EmailMessage, email_id, user.id)
    att = db.get(EmailAttachment, attachment_id)
    if att is None or att.email_id != email.id or att.skipped:
        raise repo.not_found()
    path = mail_store.attachment_path(email, att)
    if path is None or not path.is_file():
        raise repo.not_found()
    from urllib.parse import quote

    name = sanitize_name(att.filename)
    ascii_name = name.encode("ascii", "ignore").decode().replace('"', "") or "attachment"
    return Response(
        content=path.read_bytes(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(name)}",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/mail/{email_id}/link", dependencies=[Depends(csrf_protect)])
async def mail_link(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    connect=Depends(get_connector),
):
    email = repo.get_owned(db, EmailMessage, email_id, user.id)
    form = await request.form()
    raw_job = str(form.get("job_id") or "").strip()
    if raw_job:
        try:
            job = repo.get_owned(db, Job, int(raw_job), user.id)
        except ValueError:
            raise repo.not_found() from None
        email.job_id = job.id
    else:
        email.job_id = None
    email.link_method = "manual"
    email.candidates = []
    if email.direction == "in" and email.kind != "alert":
        email.kind = "employer" if email.job_id else "other"
    db.add(email)
    db.commit()
    await run_in_threadpool(mailbox.refile, db, user, email, connect)
    return RedirectResponse(f"/mail/{email.id}", status_code=303)


@router.post("/mail/{email_id}/delete", dependencies=[Depends(csrf_protect)])
async def mail_delete(
    email_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    email = repo.get_owned(db, EmailMessage, email_id, user.id)
    form = await request.form()
    if form.get("confirm") != "yes":
        return RedirectResponse(f"/mail/{email.id}?confirm=1", status_code=303)
    mail_store.delete_email(db, email)
    return RedirectResponse("/mail", status_code=303)


# --- suggestions ---------------------------------------------------------------------------


@router.get("/suggestions")
def suggestions(
    request: Request,
    state: str = "new",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    states = {"new", "added", "dismissed", "tracked", "all"}
    state = state if state in states else "new"
    stmt = select(JobSuggestion).where(JobSuggestion.user_id == user.id)
    if state != "all":
        stmt = stmt.where(JobSuggestion.state == state)
    if request.query_params.get("sort") == "fit":
        stmt = stmt.order_by(JobSuggestion.fit_score.is_(None), JobSuggestion.fit_score.desc())
    rows = db.exec(
        stmt.order_by(
            JobSuggestion.score.is_(None),
            JobSuggestion.score.desc(),
            JobSuggestion.created_at.desc(),
            JobSuggestion.id.desc(),
        )
    ).all()
    sources = {s.id: s.name for s in db.exec(select(Source)).all()}
    counts = dict(
        db.exec(
            select(JobSuggestion.state, func.count())
            .where(JobSuggestion.user_id == user.id)
            .group_by(JobSuggestion.state)
        ).all()
    )
    return render(
        request,
        "mail/suggestions.html",
        suggestions=rows,
        state=state,
        sources=sources,
        counts=counts,
    )


@router.post("/suggestions/{suggestion_id}/add", dependencies=[Depends(csrf_protect)])
def suggestion_add(
    suggestion_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    from jobhunter.routes.jobs import _choices
    from jobhunter.services.dedupe import company_title_key, find_duplicates, normalize_url

    s = repo.get_owned(db, JobSuggestion, suggestion_id, user.id)
    source_id = s.source_id or manual_source(db).id
    draft = {
        "title": s.title,
        "company": s.company or "",
        "location": s.location or "",
        "url": s.url,
        "source_id": source_id,
        "work_mode": s.work_mode or "unknown",
        "salary_text": s.salary_text or "",
        "profile_id": s.profile_id or profiles.default_profile_id(db, user.id),
        "description": s.description or "",
    }
    dupes = find_duplicates(
        db, user.id, normalize_url(s.url), company_title_key(s.company or "", s.title)
    )
    return render(
        request,
        "jobs/new.html",
        draft=draft,
        dupes=dupes,
        suggestion_id=s.id,
        messages=[
            (
                "flash",
                "From an automatic search. Check the details, then save."
                if s.description
                else "From a job alert. Add the posting text or details, then save.",
            )
        ],
        show_text=False,
        **_choices(db, user, source_id),
    )


@router.post("/suggestions/{suggestion_id}/dismiss", dependencies=[Depends(csrf_protect)])
def suggestion_dismiss(
    suggestion_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
):
    s = repo.get_owned(db, JobSuggestion, suggestion_id, user.id)
    if s.state == "new":
        s.state = "dismissed"
        db.add(s)
        db.commit()
    return RedirectResponse("/suggestions", status_code=303)


# --- Job sources page ----------------------------------------------------------------------

ALERT_SETUP = {
    "LinkedIn": (
        "https://www.linkedin.com/jobs/",
        "Search for your role and location, then switch on “Set alert”. LinkedIn sends "
        "alerts to your account's primary email: add {address} under Settings → Sign in "
        "& security → Email addresses and make it primary, or forward alerts to it.",
    ),
    "Indeed": (
        "https://ca.indeed.com/",
        "Search for your role and location, then choose “Get new jobs for this search by "
        "email” and enter {address}.",
    ),
    "Glassdoor": (
        "https://www.glassdoor.ca/Job/index.htm",
        "Search, then “Create job alert”. Alerts go to your Glassdoor account email: "
        "sign up with {address}, or forward alerts to it.",
    ),
    "Job Bank": (
        "https://www.jobbank.gc.ca/jobsearch/",
        "Search, then “Save search / Create job alert” and enter {address}.",
    ),
    "Workopolis": (
        "https://www.workopolis.com/",
        "Create an email alert for {address}. Alerts are saved as emails; job "
        "suggestions from Workopolis aren't supported yet.",
    ),
    "Eluta.ca": (
        "https://www.eluta.ca/",
        "Create an email alert for {address}. Alerts are saved as emails; job "
        "suggestions from Eluta aren't supported yet.",
    ),
}


DIRECTORY_SETUP = {
    "ABTEC 5000": (
        "https://technologyalberta.com/abtec-5000/",
        "Technology Alberta's directory of Alberta technology companies, a good list of "
        "employers to target. Browse it in your browser; when a company's careers page lists a "
        "role you like, paste the link on Add job. Importing the list as an automatic company "
        "watchlist comes with the next update. (The site blocks automated access, so Job Hunter "
        "never downloads it.)",
    ),
}


def _add_one_hint(source: Source) -> str:
    if source.fetch_allowed and source.enabled:
        return "paste its link and the details are filled in for you."
    return (
        f"paste its link, then copy the whole posting text from {source.name} and paste it "
        f"too ({source.name} doesn't let Job Hunter download its pages)."
    )


@router.get("/sources")
def sources_page(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    from jobhunter.services.alerts import PARSERS

    settings = _settings(db, user)
    address = settings.address if settings else None
    sources = db.exec(select(Source).where(Source.enabled.is_(True)).order_by(Source.name)).all()
    alerts_by_source = dict(
        db.exec(
            select(EmailMessage.source_id, func.count())
            .where(EmailMessage.user_id == user.id, EmailMessage.kind == "alert")
            .group_by(EmailMessage.source_id)
        ).all()
    )
    last_alert = dict(
        db.exec(
            select(EmailMessage.source_id, func.max(EmailMessage.saved_at))
            .where(EmailMessage.user_id == user.id, EmailMessage.kind == "alert")
            .group_by(EmailMessage.source_id)
        ).all()
    )
    sugg = {}
    for source_id, state, n in db.exec(
        select(JobSuggestion.source_id, JobSuggestion.state, func.count())
        .where(JobSuggestion.user_id == user.id)
        .group_by(JobSuggestion.source_id, JobSuggestion.state)
    ).all():
        sugg.setdefault(source_id, {})[state] = n
    jobs_by_source = dict(
        db.exec(
            select(Job.source_id, func.count())
            .where(Job.user_id == user.id)
            .group_by(Job.source_id)
        ).all()
    )
    cards = []
    for s in sources:
        if s.name == "Job Bank":
            url = "https://www.jobbank.gc.ca/"
            steps = (
                "Searched automatically every morning for each target position (titles × "
                "Canadian places) using Job Bank's public feed. You can also create email alerts "
                "to {address}."
            )
            method = "Automatic search (daily) + alerts"
        elif s.name in ("Greenhouse", "Lever", "Ashby", "Workday"):
            url = "/watchlist"
            steps = (
                "Add companies that use it to your watchlist (or import a list such as ABTEC "
                "5000): their boards are checked every morning. You can also paste one job link."
            )
            method = "Company watchlist (daily)"
        elif s.type == "company_directory":
            url, steps = DIRECTORY_SETUP.get(
                s.name, (None, "A directory of employers: browse it and paste job links you find.")
            )
            method = "Company directory (browse)"
        elif s.alert_sender:
            url, steps = ALERT_SETUP.get(s.name, (None, "Create an email alert for {address}."))
            method = (
                "Job-alert emails → suggested jobs" if s.name in PARSERS else "Job-alert emails"
            )
        elif s.fetch_allowed:
            url, steps = (
                None,
                (
                    "Paste a job link on Add job: details are downloaded "
                    "automatically. Automatic searches arrive in the next update."
                ),
            )
            method = "Paste a link (auto-filled)"
        else:
            url, steps = None, "Paste the job link or the posting text on Add job."
            method = "Paste a link or text"
        cards.append(
            {
                "source": s,
                "method": method,
                "url": url,
                "steps": steps.format(address=address or "your job mailbox"),
                "alerts": alerts_by_source.get(s.id, 0),
                "last_alert": last_alert.get(s.id),
                "suggested": sum(sugg.get(s.id, {}).values()),
                "added": sugg.get(s.id, {}).get("added", 0),
                "jobs": jobs_by_source.get(s.id, 0),
                "needs_mailbox": s.alert_sender and not address,
                "add_one": _add_one_hint(s) if s.alert_sender else None,
            }
        )
    from jobhunter.services.search import runner

    return render(
        request,
        "sources/index.html",
        cards=cards,
        mailbox=settings,
        work_modes=WORK_MODE_LABELS,
        runs=runner.last_runs(db, user.id),
        running=runner.is_running(user.id),
    )
