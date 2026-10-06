import pytest

from jobhunter.services.claude import cli
from tests.claude_helpers import fake_claude  # noqa: F401

SCHEMA = {
    "type": "object",
    "required": ["n"],
    "properties": {"n": {"type": "integer"}},
    "additionalProperties": False,
}


def test_successful_call_and_isolation(fake_claude, db_path):  # noqa: F811
    fake_claude.respond({"n": 2})
    out = cli.run("count letters in QA", SCHEMA, [], timeout=20, max_turns=2)
    assert out.data == {"n": 2} and out.cost_usd == 0.0123
    call = fake_claude.calls[0]
    argv = call["argv"]
    assert argv[:3] == ["-p", "--output-format", "json"]
    assert argv[argv.index("--tools") + 1] == ""
    assert "--allowedTools" not in argv and "--disallowedTools" not in argv
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--json-schema") + 1].startswith('{"type": "object"')
    assert call["stdin"] == "count letters in QA" and call["files"] == []
    assert "/claude-run-" in call["cwd"]
    assert "SMTP_PASSWORD_ALICE" not in call["env"] and "SESSION_SECRET" not in call["env"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" in call["env"]


def test_web_tools_and_blocked_domains(fake_claude, db_path):  # noqa: F811
    fake_claude.respond({"n": 1})
    cli.run("find", SCHEMA, ["WebSearch", "WebFetch"], timeout=20)
    argv = fake_claude.calls[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    denied = argv[argv.index("--disallowedTools") + 1 :]
    for d in ("linkedin.com", "indeed.com", "glassdoor.com", "glassdoor.ca"):
        assert f"WebFetch(domain:{d})" in denied


@pytest.mark.parametrize(
    ("mode", "data", "message"),
    [
        ("auth", None, "Claude token missing or expired"),
        ("bad_json", None, "Claude returned an error"),
        ("exit1", None, "Reached max turns"),
        ("is_error", {"n": 1}, "Claude returned an error"),
        ("ok", {"n": "two"}, "expected structure"),
        ("ok", {"n": 1, "extra": True}, "expected structure"),
    ],
)
def test_failures_are_readable(fake_claude, db_path, mode, data, message):  # noqa: F811
    fake_claude.respond(data or {}, mode=mode)
    with pytest.raises(cli.ClaudeError, match=message):
        cli.run("x", SCHEMA, [], timeout=20)


def test_timeout_kills(fake_claude, db_path):  # noqa: F811
    import time

    fake_claude.respond({"n": 1}, mode="sleep")
    started = time.monotonic()
    with pytest.raises(cli.ClaudeError, match="took too long"):
        cli.run("x", SCHEMA, [], timeout=2)
    assert time.monotonic() - started < 7  # SC-002: limit + 5 s


def test_missing_token_or_binary(fake_claude, db_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    with pytest.raises(cli.ClaudeError, match="setup-token"):
        cli.run("x", SCHEMA, [], timeout=5)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    monkeypatch.setenv("CLAUDE_BIN", "/nonexistent/claude")
    with pytest.raises(cli.ClaudeError, match="not installed"):
        cli.run("x", SCHEMA, [], timeout=5)
