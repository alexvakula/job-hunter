# Implementation Plan: Claude Integration

**Branch**: `005-claude-integration` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary
A persisted queue (`claude_job`) processed by one background worker; each job runs the pinned Claude
Code CLI headlessly with a strict JSON Schema, restricted tools and no external configuration, in an
empty temp dir, with a timeout. Four job kinds: find_jobs (WebSearch/WebFetch, LinkedIn/Indeed/
Glassdoor fetch denied) → suggestions; fit_rank → scores; tailor → tailored draft wording + cover
letter (bullet ids only, honesty check unchanged); import → unsaved master resume. Admin only.

## Technical Context
CLI in image: multi-stage copy of Node 22 + `@anthropic-ai/claude-code@2.1.290`; env
`CLAUDE_CONFIG_DIR=/data/claude`, `DISABLE_AUTOUPDATER=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`;
token `CLAUDE_CODE_OAUTH_TOKEN` from `.env`. Invocation (prompt on stdin):
`claude -p --output-format json --json-schema <schema> --tools <list> --allowedTools <list>
 [--disallowedTools "WebFetch(domain:linkedin.com)" …] --strict-mcp-config --setting-sources ""
 --no-session-persistence --max-turns N`. Result validated with `jsonschema`. Tests use a fake CLI
(`CLAUDE_BIN`) script that records its arguments.

## Constitution Check (v2.0.2) — PASS
II honesty (facts not in outputs; feature 004 check) · III nothing sent · IV token only in env, never
logged · V Claude may not fetch LinkedIn/Indeed/Glassdoor; results go through allow-listed flows ·
VI background queue, concurrency 1, timeouts, strict schemas, WebSearch/WebFetch only, failures
visible · VII tests with fake CLI (args, schema failure, timeout, auth error) · VIII admin only.
