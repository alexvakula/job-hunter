"""Application factory: middleware, error handling, routers and /health."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from jobhunter.auth.sessions import (
    FLASH_COOKIE,
    PASSWORD_CHANGE_PATH,
    CsrfFailed,
    Forbidden,
    LoginRequired,
    PasswordChangeRequired,
    login_redirect_url,
)
from jobhunter.config import get_settings
from jobhunter.routes import admin as admin_routes
from jobhunter.routes import auth as auth_routes
from jobhunter.routes import board as board_routes
from jobhunter.routes import claude as claude_routes
from jobhunter.routes import dashboard as dashboard_routes
from jobhunter.routes import job_children as job_children_routes
from jobhunter.routes import jobs as jobs_routes
from jobhunter.routes import mail as mail_routes
from jobhunter.routes import notifications as notifications_routes
from jobhunter.routes import resume as resume_routes
from jobhunter.routes import settings_profiles as settings_profiles_routes
from jobhunter.routes import settings_resume as settings_resume_routes
from jobhunter.routes import settings_sender as settings_sender_routes
from jobhunter.routes import watchlist as watchlist_routes
from jobhunter.web import is_htmx, render

STATIC_DIR = Path(__file__).parent / "static"


def _redirect(request: Request, url: str) -> Response:
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def create_app() -> FastAPI:
    settings = get_settings()
    # Never log request bodies or headers; uvicorn's access log only records method+path.
    logging.basicConfig(level=settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from jobhunter.services import scheduler
        from jobhunter.services.claude import queue as claude_queue

        tasks = []
        if scheduler.enabled():
            tasks = [
                asyncio.create_task(scheduler.loop()),
                asyncio.create_task(claude_queue.worker()),
            ]
        yield
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="Job Hunter", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def flash_and_headers(request: Request, call_next):
        request.state.flash = request.cookies.get(FLASH_COOKIE)
        response = await call_next(request)
        if request.state.flash and response.status_code == 200:
            response.delete_cookie(FLASH_COOKIE, path="/")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return _redirect(request, login_redirect_url(exc.next_path, exc.expired))

    @app.exception_handler(PasswordChangeRequired)
    async def _password_change(request: Request, _exc):
        return _redirect(request, PASSWORD_CHANGE_PATH)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, _exc):
        return render(request, "errors/403.html", status_code=403)

    @app.exception_handler(CsrfFailed)
    async def _csrf(request: Request, _exc):
        return render(request, "errors/403.html", status_code=403, reason="csrf")

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        if exc.status_code == 404:
            return render(request, "errors/404.html", status_code=404)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    @app.get("/health", include_in_schema=False)
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    app.include_router(auth_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(job_children_routes.router)
    app.include_router(board_routes.router)
    app.include_router(settings_profiles_routes.router)
    app.include_router(settings_resume_routes.router)
    app.include_router(settings_sender_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(mail_routes.router)
    app.include_router(notifications_routes.router)
    app.include_router(resume_routes.router)
    app.include_router(claude_routes.router)
    app.include_router(watchlist_routes.router)
    return app


def __getattr__(name: str):
    # `uvicorn jobhunter.main:app` builds the app lazily so tests can configure env first.
    if name == "app":
        return create_app()
    raise AttributeError(name)
