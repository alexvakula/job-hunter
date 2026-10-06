# Implementation Plan: Job Tracker MVP

**Branch**: `001-job-tracker-mvp` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-job-tracker-mvp/spec.md`

## Summary

A family job tracker (admin + children, about 5 accounts) at `jobs.example.org`. Each user captures
jobs by pasting a URL or text (pre-filled via schema.org JSON-LD from allowed sites only), moves
them through ten statuses with an append-only history, works them in kanban, table and dashboard
views with notes, contacts and follow-ups, and keeps their own target-position profiles and
sender settings, including a "send test email" button. The admin manages accounts and the shared
source list. Built as one FastAPI + Jinja2/HTMX container on SQLite with server-side sessions,
strict per-user scoping, and nightly backups. No Claude, resume or application sending in this
feature; the data model leaves room for them.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, Uvicorn, Jinja2, SQLModel (SQLAlchemy 2), Alembic, bcrypt,
httpx, BeautifulSoup4, python-multipart, email-validator; front end: HTMX 2 and SortableJS
(vendored static files); dev: pytest, ruff

**Storage**: SQLite (WAL) at `/data/jobhunter.db` on the `./data` volume

**Testing**: pytest with FastAPI TestClient, temporary SQLite per test, saved HTML/text
fixtures, fake SMTP

**Target Platform**: Linux server (homeserver), Docker, behind the existing nginx-proxy +
Let's Encrypt companion on the `webserver_default` network

**Project Type**: Server-rendered web application (single project)

**Performance Goals**: Table, kanban and dashboard < 2 s with 2,000 jobs per user (SC-004);
prefill fetch ≤ 10 s; test email result ≤ 30 s (SC-007)

**Constraints**: Single container, no external SaaS or CDN at runtime; one Uvicorn worker;
secrets only in `.env`; minimal JS; fetches only to allow-listed, robots-permitted hosts

**Scale/Scope**: ≈5 accounts, ≤2,000 jobs each, ~20 pages, 6 user stories

All items resolved in [research.md](research.md); no NEEDS CLARIFICATION remain. The spec's
open time-zone item is resolved as app-wide `America/Edmonton` (R10).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Pre-design | Post-design | How the design complies |
|---|-----------|-----------|-------------|-------------------------|
| I | Single self-hosted container | ✅ | ✅ | One image; SQLite on `./data`; vendored JS; compose mirrors `/opt/docker/analytics` with `VIRTUAL_HOST`/`LETSENCRYPT_HOST` for jobs.example.org (R1, R11) |
| II | Honest resumes | ✅ n/a | ✅ n/a | No resume generation in this feature |
| III | Human in the loop | ✅ | ✅ | Only email = test email, button-triggered, to own address (R9); no background sending exists |
| IV | Secrets in .env | ✅ | ✅ | `SESSION_SECRET`, `SMTP_PASSWORD_<USER>` from env only; bcrypt hashes in DB as permitted; never rendered or logged; `.env.example` only committed (cli-and-config.md) |
| V | Site terms / robots | ✅ | ✅ | Fetch only `fetch_allowed` sources, robots.txt honoured, identifying UA, rate limit, single page per user action (R7) |
| VI | Bounded Claude jobs | ✅ n/a | ✅ n/a | No Claude calls; Claude CLI not installed until P3 |
| VII | Tests for critical logic | ✅ | ✅ | Unit tests: extractor fixtures, dedupe, statuses, stats; integration: per-user isolation over every route (R12). ATS/DOCX tests arrive with P2 |
| VIII | Simple, family use | ✅ | ✅ | Two roles, no sign-up, owner-scoped repository with 404 for others' ids, admin has no data access, shared admin-managed sources (R3–R5) |
| IX | Backups | ✅ | ✅ | Nightly online SQLite backup copied to `/mnt/backup/job-hunter/` (R11) |

Result: **PASS**, no violations, Complexity Tracking empty.

Node and the Claude CLI are not in this image; per constitution v2.0.1 they are added by the
first feature that calls the Claude CLI (P3).

## Project Structure

### Documentation (this feature)

```text
specs/001-job-tracker-mvp/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── http-routes.md
│   └── cli-and-config.md
├── checklists/requirements.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml, uv.lock, alembic.ini, Dockerfile, .env.example, .dockerignore
src/jobhunter/
├── main.py              # app factory, middleware, router registration, /health
├── config.py            # env settings (APP_TIMEZONE, DATABASE_PATH, COOKIE_SECURE, ...)
├── db.py                # engine (WAL, foreign_keys), session dependency
├── models.py            # SQLModel tables + enums (data-model.md)
├── cli.py               # create-admin, backup
├── seeds.py             # first-admin defaults (QA Lead profile, sender)
├── auth/
│   ├── passwords.py     # bcrypt hash/verify, policy
│   ├── sessions.py      # server-side sessions, CSRF, current_user / require_admin deps
│   └── throttle.py      # login attempt limiting
├── repo.py              # owner-scoped queries, get_owned()
├── services/
│   ├── dedupe.py        # url_norm, company_title_key, duplicate lookup
│   ├── extract.py       # JSON-LD / OpenGraph / text heuristics → JobDraft
│   ├── fetch.py         # allow-list, robots, rate limit, SSRF guard, httpx GET
│   ├── statuses.py      # change_status(), history rules
│   ├── stats.py         # weekly applications, response rate, counts, due follow-ups
│   └── mailer.py        # test email via smtplib STARTTLS, error mapping
├── routes/
│   ├── auth.py  dashboard.py  jobs.py  board.py  job_children.py
│   ├── settings_profiles.py  settings_sender.py  admin.py
├── templates/           # base.html, partials/, jobs/, settings/, admin/
└── static/              # app.css, app.js (CSRF header, sortable hookup), vendor/htmx, vendor/sortable
migrations/              # Alembic env + versions (0001 schema + source seed)
tests/
├── conftest.py          # temp DB, app client, user factories, login helper
├── fixtures/            # saved job pages (Greenhouse, Lever, Job Bank, Workday, Ashby) + pasted texts
├── unit/                # test_dedupe, test_extract, test_statuses, test_stats, test_mailer, test_fetch_policy
└── integration/         # test_auth, test_throttle, test_csrf, test_isolation, test_admin, test_jobs, test_board, test_settings
deploy/
├── docker-compose.yml
└── backup.sh
```

**Structure Decision**: Single Python package under `src/jobhunter` with thin route modules over
pure service modules, so parsers, dedupe, status and stats logic are unit-testable without HTTP.
Templates and static files live inside the package so the image is self-contained.

## Complexity Tracking

No constitution violations; nothing to justify.
