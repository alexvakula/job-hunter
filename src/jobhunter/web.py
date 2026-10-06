"""Template rendering shared by all route modules."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from jobhunter.db import to_local
from jobhunter.services.claude import cli as claude_cli
from jobhunter.services.statuses import STATUS_LABELS

TEMPLATE_DIR = Path(__file__).parent / "templates"

FLASH_MESSAGES = {
    "session_expired": "Your session expired; please check and resubmit your changes.",
    "password_changed": "Your password has been changed.",
    "password_reset": "Temporary password set. They'll choose a new one when they log in.",
}


def _context(request: Request) -> dict:
    auth = getattr(request.state, "auth", None)
    flash_key = getattr(request.state, "flash", None)
    return {
        "current_user": auth.user if auth else None,
        "csrf_token": auth.session.csrf_token if auth else "",
        "claude_enabled": bool(auth and _claude_enabled(auth.user)),
        "flash": FLASH_MESSAGES.get(flash_key) if flash_key else None,
    }


def _claude_enabled(user) -> bool:
    from jobhunter.services.claude.queue import enabled_for

    return enabled_for(user)


def _local_dt(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    local = to_local(value)
    return local.strftime(fmt) if local else ""


templates = Jinja2Templates(directory=str(TEMPLATE_DIR), context_processors=[_context])
templates.env.filters["local_dt"] = _local_dt
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["model_name"] = claude_cli.model_name


def render(request: Request, name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
