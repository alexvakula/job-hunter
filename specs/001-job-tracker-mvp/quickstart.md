# Quickstart & Validation: Job Tracker MVP

How to run the app and prove each user story works. Routes: [contracts/http-routes.md](contracts/http-routes.md);
config and CLI: [contracts/cli-and-config.md](contracts/cli-and-config.md); entities:
[data-model.md](data-model.md).

## Prerequisites

- `uv` (in `~/.local/bin`), Docker + compose, the `webserver_default` network.
- `.env` created from `.env.example` with `SESSION_SECRET` (e.g. `openssl rand -hex 32`) and
  `SMTP_PASSWORD_SAM`.

## 1. Automated checks (must pass before any deploy)

```bash
cd ~/job-hunter
uv sync
uv run ruff check .
uv run pytest -q
```

Expected: all green, including `tests/unit/test_dedupe.py` (≥ 20 URL variants, SC-003),
`test_extract.py` (saved HTML/text fixtures), `test_statuses.py`, `test_stats.py`,
`test_mailer.py`, and `tests/integration/test_isolation.py` (every route, two users, SC-009).

## 2. Local run

```bash
COOKIE_SECURE=false DATABASE_PATH=./data/dev.db uv run alembic upgrade head
COOKIE_SECURE=false DATABASE_PATH=./data/dev.db uv run jobhunter create-admin sam \
    --display-name "Sam Rivera" --seed-defaults
COOKIE_SECURE=false DATABASE_PATH=./data/dev.db uv run uvicorn jobhunter.main:app --port 8000
```

Open http://127.0.0.1:8000 → redirected to `/login`.

## 3. Manual validation by user story

| Story | Steps | Expected |
|-------|-------|----------|
| US1 capture | Paste a Greenhouse job URL → Prefill | Fields filled from the page; source "Greenhouse"; editable before save |
| | Paste a LinkedIn job URL | "Not fetched for this site" message; source "LinkedIn"; paste text box shown |
| | Paste posting text, save | Job in `new`, source Manual, today's date, full text kept |
| | Paste the first URL again with `?utm_source=x#top` | Shows existing job; cannot save duplicate |
| | Same company "ACME Inc." + same title, no URL | "Possible duplicate" warning with link and "save anyway" |
| US2 statuses | Drag card new → interested → applied on `/board`; on job page set `rejected` with effective date yesterday | Timeline shows 4 entries (incl. creation) in order with dates |
| US3 lists | Filter `/jobs?status=applied&q=qa`, reload | Same results; filters in URL |
| | Add note, contact, follow-up due today | Shown on job; dashboard lists follow-up as due |
| US4 profiles | `/settings/profiles` | "QA Lead" default with Calgary, Vancouver (CAD 130k) and USA remote (USD 130k) |
| US5 sender | `/settings/sender` → Send test email | Arrives at sam@example.org from "Sam Rivera"; password shown only as "configured". Change host to `nosuch.invalid` → readable error ≤ 30 s |
| US6 admin | Time it: create user `kid1` (temp password) from `/admin/users` | Done in under 2 minutes (SC-010) |
| | Log in as kid1 | Forced to change password; sees no jobs; `/jobs/<sam's id>` → 404; `/admin/users` → 403 |
| | Disable kid1 while kid1 is logged in | kid1's next request → login page; login refused |

## 4. Security spot checks

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/jobs      # 303 to /login
grep -r "$SMTP_PASSWORD_SAM" data/ logs/ 2>/dev/null | wc -l             # 0 (SC-006)
```

Eleven failed logins in a row for one username → the 11th is refused with "too many attempts".

## 5. Production

```bash
# /opt/docker is owned by sam; no sudo needed. Exact copy steps are in tasks.md.
mkdir -p /opt/docker/job-hunter && cp deploy/docker-compose.yml /opt/docker/job-hunter/
cd /opt/docker/job-hunter && docker compose up -d --build
docker compose exec job-hunter jobhunter create-admin sam --display-name "Sam Rivera" --seed-defaults
curl -I https://jobs.example.org          # 302/303 to /login, valid certificate
```

DNS (`jobs.example.org` A record + optional local-DNS rewrite) and the backup cron entry are
one-time manual steps listed in tasks.md. Verify a backup file appears in
`/mnt/backup/job-hunter/` after the first nightly run (or run
`deploy/backup.sh` once by hand).
