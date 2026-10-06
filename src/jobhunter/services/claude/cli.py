"""Running the Claude Code CLI headlessly (constitution VI; feature 005 FR-002–FR-004).

Each call: prompt on stdin, `--output-format json` with a strict JSON Schema, built-in tools limited
with `--tools`, no MCP servers or setting files, no session persistence, an empty temporary working
directory, a minimal environment (no other secrets), and a hard timeout that kills the process
group. The structured result is validated again here; anything unexpected is an error.
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from jobhunter.config import get_settings

log = logging.getLogger(__name__)
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"  # noqa: S105 - the variable name, not a secret
_HELP = (
    "Claude token missing or expired. Run `claude setup-token` on your computer and put "
    "the token in /opt/docker/job-hunter/.env as CLAUDE_CODE_OAUTH_TOKEN, then restart."
)
TOKEN_HELP = _HELP
BLOCKED_FETCH_DOMAINS = (
    "linkedin.com",
    "indeed.com",
    "ca.indeed.com",
    "glassdoor.com",
    "glassdoor.ca",
)
_AUTH_HINTS = (
    "oauth",
    "authentication",
    "unauthorized",
    "401",
    "invalid api key",
    "login",
    "credential",
    "token",
)


# Model per job kind: cheaper ones for searching and scoring, the strongest for writing what
# employers read. Each can be overridden in .env, e.g. CLAUDE_MODEL_TAILOR=claude-sonnet-5-5.
DEFAULT_MODELS = {
    "find_jobs": "claude-haiku-4-5-20251001",
    "fit_rank": "claude-haiku-4-5-20251001",
    "import": "claude-sonnet-5-5",
    "prep": "claude-sonnet-5-5",
    "tailor": "claude-opus-5-5",
}
MODEL_NAMES = {
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-opus-5-5": "Opus 5.5",
}


def model_name(model: str | None) -> str:
    return MODEL_NAMES.get(model or "", model or "")


_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,63}$")


def model_for(kind: str) -> str:
    """The model for a job kind: CLAUDE_MODEL_<KIND> from the environment if it is a valid
    model id, else the default."""
    configured = os.environ.get(f"CLAUDE_MODEL_{kind.upper()}", "").strip()
    if configured and _MODEL_ID.match(configured):
        return configured
    if configured:
        log.warning("ignoring invalid CLAUDE_MODEL_%s", kind.upper())
    return DEFAULT_MODELS[kind]


class ClaudeError(Exception):
    pass


@dataclass
class CliResult:
    data: dict
    cost_usd: float | None


def token_configured() -> bool:
    return bool(os.environ.get(TOKEN_ENV))


def binary() -> str | None:
    return shutil.which(os.environ.get("CLAUDE_BIN", "claude"))


def config_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured)
    return Path(get_settings().database_path).resolve().parent / "claude"


def _env() -> dict[str, str]:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(cfg),
        "CLAUDE_CONFIG_DIR": str(cfg),
        TOKEN_ENV: os.environ.get(TOKEN_ENV, ""),
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "LANG": "C.UTF-8",
    }
    for passthrough in ("FAKE_CLAUDE_LOG", "FAKE_CLAUDE_RESPONSE", "FAKE_CLAUDE_MODE"):
        if passthrough in os.environ:  # test doubles only
            env[passthrough] = os.environ[passthrough]
    return env


def arguments(
    exe: str, schema: dict, tools: list[str], max_turns: int, model: str | None = None
) -> list[str]:
    args = [
        exe,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--tools",
        ",".join(tools),
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--max-turns",
        str(max_turns),
    ]
    if model:
        args += ["--model", model]
    if tools:
        args += ["--allowedTools", ",".join(tools)]
    if "WebFetch" in tools:
        args += ["--disallowedTools", *[f"WebFetch(domain:{d})" for d in BLOCKED_FETCH_DOMAINS]]
    return args


def _explain(text: str) -> str:
    low = (text or "").lower()
    if any(h in low for h in _AUTH_HINTS):
        return TOKEN_HELP
    return "Claude returned an error: " + (text or "unknown error").strip()[:300]


def run(
    prompt: str,
    schema: dict,
    tools: list[str],
    timeout: int,
    max_turns: int = 8,
    model: str | None = None,
) -> CliResult:
    if not token_configured():
        raise ClaudeError(TOKEN_HELP)
    exe = binary()
    if exe is None:
        raise ClaudeError("Claude CLI not installed in the container.")
    with tempfile.TemporaryDirectory(prefix="claude-run-") as workdir:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, trusted binary
            arguments(exe, schema, tools, max_turns, model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=_env(),
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise ClaudeError(
                f"Claude took too long (over {timeout // 60 or 1} min) and was stopped."
            ) from None
    try:
        envelope = json.loads(stdout)
    except ValueError:
        log.warning("claude exited %s with non-JSON output", proc.returncode)
        raise ClaudeError(_explain(stderr or stdout)) from None
    if (
        proc.returncode != 0
        or envelope.get("is_error")
        or envelope.get("subtype") != "success"
        or envelope.get("type") != "result"
    ):
        raise ClaudeError(
            _explain(str(envelope.get("result") or stderr or envelope.get("subtype")))
        )
    data = envelope.get("structured_output")
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise ClaudeError(
            f"Claude's answer did not have the expected structure ({exc.message[:120]})."
        ) from None
    return CliResult(data=data, cost_usd=envelope.get("total_cost_usd"))
