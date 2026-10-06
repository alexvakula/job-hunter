"""Running the Claude Code CLI headlessly (constitution VI; feature 005 FR-002–FR-004).

Each call: prompt on stdin, `--output-format json` with a strict JSON Schema, built-in tools limited
with `--tools`, no MCP servers or setting files, no session persistence, an empty temporary working
directory, a minimal environment (no other secrets), and a hard timeout that kills the process
group. The structured result is validated again here; anything unexpected is an error.
"""

import json
import logging
import os
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


def arguments(exe: str, schema: dict, tools: list[str], max_turns: int) -> list[str]:
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


def run(prompt: str, schema: dict, tools: list[str], timeout: int, max_turns: int = 8) -> CliResult:
    if not token_configured():
        raise ClaudeError(TOKEN_HELP)
    exe = binary()
    if exe is None:
        raise ClaudeError("Claude CLI not installed in the container.")
    with tempfile.TemporaryDirectory(prefix="claude-run-") as workdir:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, trusted binary
            arguments(exe, schema, tools, max_turns),
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
