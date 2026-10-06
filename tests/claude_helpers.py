"""Fixtures for feature 005: a fake `claude` binary configured through environment variables."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(f"#!{sys.executable}\n" + (Path(__file__).parent / "fake_claude.py").read_text())
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("CLAUDE_BIN", str(exe))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-test-token")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("SMTP_PASSWORD_ALICE", "mail-secret-should-not-leak")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))

    class Fake:
        def respond(self, data, mode="ok"):
            path = tmp_path / "response.json"
            path.write_text(json.dumps(data))
            monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", str(path))
            monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

        def mode(self, mode):
            monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

        @property
        def calls(self):
            if not log.exists():
                return []
            return [json.loads(line) for line in log.read_text().splitlines()]

    return Fake()


__all__ = ["fake_claude", "os"]
