# Validation: Claude Integration

**Run**: 2026-10-05. Automated: 398 tests pass, incl. a fake `claude` binary that records argv,
stdin, working directory and environment: schema + `--tools` limits + blocked fetch domains +
isolation flags on every call; no SMTP password or session secret in the CLI environment; timeout
kills within limit + 5 s; auth/invalid/mismatched output → readable failures; queue one-at-a-time and
restart-safe; Find jobs → checked suggestions → ranking; tailoring cannot add bullets and the honesty
check still blocks; import opens unsaved; non-admins get 403 on every Claude route; ruff clean.

**CLI facts verified on Claude Code 2.1.290** (this server): `--json-schema` result in
`structured_output`; `--tools ""` disables all tools; `--bare` ignores `CLAUDE_CODE_OAUTH_TOKEN`
(so not used); structured output needs ≥ 2 turns.

**Production**: migration 0007 ran; `claude --version` = 2.1.290 inside the container as uid 1000;
token not configured yet → Claude page shows setup steps, buttons hidden. A real Claude run is pending
the admin adding `CLAUDE_CODE_OAUTH_TOKEN`.
