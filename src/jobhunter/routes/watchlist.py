"""Company watchlist and CSV import (feature 003 US2, US3; FR-008–FR-010)."""

import csv
import io
import threading
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session
from starlette.datastructures import UploadFile

from jobhunter import repo
from jobhunter.auth.sessions import csrf_protect, current_user
from jobhunter.db import get_engine, get_session
from jobhunter.models import UserAccount, WatchCompany
from jobhunter.services.fetch import Fetcher, get_fetcher
from jobhunter.services.search import discovery
from jobhunter.web import render

router = APIRouter()
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
UNSUPPORTED_LINK = (
    "This careers link isn't from a job board the app can read. Supported: Greenhouse, Lever, "
    "Ashby, Workday, Pinpoint, Rippling, JazzHR (applytojob.com), Jobvite, BambooHR, HiBob, "
    "Eightfold, Phenom, SuccessFactors and Oracle Cloud career sites. On the company's careers "
    "page, open one job and paste the link of that job page."
)
BOARD_LABELS = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workday": "Workday",
    "pinpoint": "Pinpoint",
    "rippling": "Rippling",
    "jazzhr": "JazzHR",
    "jobvite": "Jobvite",
    "eightfold": "Eightfold",
    "phenom": "Phenom",
    "successfactors": "SuccessFactors",
    "oracle": "Oracle Cloud",
    "bamboohr": "BambooHR",
    "hibob": "HiBob",
    "unknown": "—",
}


def start_in_background(job: Callable[[], object]):
    threading.Thread(target=job, daemon=True).start()
    return None


def get_launcher():
    """Dependency: runs background work. Tests replace it with an inline runner."""
    return start_in_background


def _page(request, db, user, status_code=200, **extra):
    companies = db.exec(
        repo.scoped(WatchCompany, user.id).order_by(
            WatchCompany.status != "ok", func.lower(WatchCompany.name)
        )
    ).all()
    return render(
        request,
        "watchlist/index.html",
        status_code=status_code,
        companies=companies,
        progress=discovery.progress(db, user.id),
        labels=BOARD_LABELS,
        **extra,
    )


@router.get("/watchlist")
def watchlist(
    request: Request, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    return _page(request, db, user)


@router.post("/watchlist", dependencies=[Depends(csrf_protect)])
async def add_company(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    fetcher: Fetcher = Depends(get_fetcher),
):
    form = await request.form()
    url = str(form.get("careers_url") or "").strip()
    board = await run_in_threadpool(discovery.resolve_link, db, url, fetcher)
    if board is None:
        return _page(
            request,
            db,
            user,
            422,
            error=UNSUPPORTED_LINK,
        )
    name = str(form.get("name") or "").strip()[:200] or board.board_id
    clash = db.exec(
        repo.scoped(WatchCompany, user.id).where(
            WatchCompany.board_type == board.type,
            WatchCompany.board_id == board.board_id,
            WatchCompany.board_site == board.site,
        )
    ).first()
    if clash is not None:
        return _page(request, db, user, 422, error=f"{clash.name} is already on your watchlist.")
    db.add(
        WatchCompany(
            user_id=user.id,
            name=name,
            board_type=board.type,
            board_id=board.board_id,
            board_host=board.host,
            board_site=board.site,
            status="ok",
            discovery_done=True,
        )
    )
    db.commit()
    return RedirectResponse("/watchlist", status_code=303)


def _header_index(header: list[str], keys: tuple[str, ...]) -> int | None:
    for i, h in enumerate(header):
        if any(k in h.strip().lower() for k in keys):
            return i
    return None


def parse_csv(data: bytes) -> list[tuple[str, str | None]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ValueError("The file is empty.")
    header = rows[0]
    name_i = _header_index(header, ("company", "name", "organization", "organisation"))
    site_i = _header_index(header, ("website", "url", "domain", "web"))
    if name_i is None:
        raise ValueError(
            "No company-name column found (the header must contain “company” or “name”)."
        )
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"Too many rows (maximum {MAX_ROWS:,}).")
    out = []
    for row in rows[1:]:
        name = row[name_i].strip() if name_i < len(row) else ""
        site = row[site_i].strip() if site_i is not None and site_i < len(row) else ""
        if name:
            out.append((name[:200], site[:300] or None))
    return out


@router.post("/watchlist/import", dependencies=[Depends(csrf_protect)])
async def import_csv(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    launcher=Depends(get_launcher),
    fetcher=Depends(get_fetcher),
):
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _page(request, db, user, 422, error="Choose a CSV file.")
    data = await upload.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        return _page(request, db, user, 422, error="The file is larger than 5 MB.")
    if b"\x00" in data[:4096] or data[:2] == b"PK":
        return _page(request, db, user, 422, error="Save the list as CSV (comma-separated) first.")
    try:
        rows = parse_csv(data)
    except ValueError as exc:
        return _page(request, db, user, 422, error=str(exc))
    existing = {
        (c.name.lower(), (c.website or "").lower())
        for c in db.exec(repo.scoped(WatchCompany, user.id)).all()
    }
    names = {n for n, _ in existing}
    sites = {s for _, s in existing if s}
    added = 0
    for name, site in rows:
        if name.lower() in names or (site and site.lower() in sites):
            continue
        names.add(name.lower())
        if site:
            sites.add(site.lower())
        db.add(WatchCompany(user_id=user.id, name=name, website=site, imported=True))
        added += 1
    db.commit()

    user_id = user.id

    def discover_all():
        with Session(get_engine()) as s:
            while discovery.run_batch(s, fetcher, user_id):
                pass

    launcher(discover_all)
    return _page(
        request,
        db,
        user,
        notice=f"Imported {added} companies "
        f"({len(rows) - added} duplicates skipped). Finding their job boards in the "
        "background.",
    )


@router.post("/watchlist/{company_id}/pause", dependencies=[Depends(csrf_protect)])
def pause(
    company_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    c = repo.get_owned(db, WatchCompany, company_id, user.id)
    c.paused = not c.paused
    db.add(c)
    db.commit()
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/{company_id}/delete", dependencies=[Depends(csrf_protect)])
def delete(
    company_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
):
    db.delete(repo.get_owned(db, WatchCompany, company_id, user.id))
    db.commit()
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/{company_id}/link", dependencies=[Depends(csrf_protect)])
async def set_link(
    company_id: int,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
    fetcher: Fetcher = Depends(get_fetcher),
):
    c = repo.get_owned(db, WatchCompany, company_id, user.id)
    url = str((await request.form()).get("careers_url") or "").strip()
    board = await run_in_threadpool(discovery.resolve_link, db, url, fetcher)
    if board is None:
        return _page(request, db, user, 422, error=UNSUPPORTED_LINK)
    c.board_type, c.board_id, c.board_host, c.board_site = (
        board.type,
        board.board_id,
        board.host,
        board.site,
    )
    c.status, c.discovery_done, c.last_error = "ok", True, None
    db.add(c)
    db.commit()
    return RedirectResponse("/watchlist", status_code=303)
