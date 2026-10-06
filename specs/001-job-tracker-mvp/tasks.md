---
description: "Task list for 001-job-tracker-mvp"
---

# Tasks: Job Tracker MVP

**Input**: Design documents from `specs/001-job-tracker-mvp/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. Constitution Principle VII requires tests for parsers, dedupe and status
transitions plus per-user isolation, and SC-003/SC-009 require automated verification. Within
each story, write its tests first and confirm they fail before implementing.

**Organization**: Tasks are grouped by user story. Phases follow spec priority: US1, US2 (P1),
then US3, US4, US6 (P2), then US5 (P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story from spec.md (US1–US6)
- Paths are relative to the repository root (single project, `src/jobhunter/`, `tests/`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, tooling, vendored front-end assets

- [X] T001 Create `pyproject.toml` (project `jobhunter`, Python `>=3.12`, `src/` layout, console script `jobhunter = "jobhunter.cli:main"`) with dependencies fastapi, uvicorn[standard], jinja2, sqlmodel, alembic, bcrypt, httpx, beautifulsoup4, python-multipart, email-validator, tzdata; dev group pytest, ruff; then run `uv lock` to create `uv.lock`
- [X] T002 Create package skeleton per plan.md: `src/jobhunter/__init__.py`, `src/jobhunter/auth/__init__.py`, `src/jobhunter/services/__init__.py`, `src/jobhunter/routes/__init__.py`, `src/jobhunter/templates/`, `src/jobhunter/static/`, `tests/__init__.py`, `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `migrations/`, `deploy/`
- [X] T003 [P] Configure ruff (line length 100, rules E,F,I,B,UP,S) in `pyproject.toml` and pytest settings (`testpaths = ["tests"]`, `pythonpath = ["src"]`)
- [X] T004 [P] Create `.env.example` with placeholder values for `SESSION_SECRET`, `SMTP_PASSWORD_SAM`, `APP_TIMEZONE=America/Edmonton`, `DATABASE_PATH=/data/jobhunter.db`, `COOKIE_SECURE=true`, `LOG_LEVEL=INFO` and a commented `# CLAUDE_CODE_OAUTH_TOKEN=` (reserved for P3), per contracts/cli-and-config.md; create `.dockerignore` excluding `.env`, `data/`, `.git/`, `.venv/`, `tests/`, `specs/`
- [X] T005 [P] Vendor HTMX 2.x to `src/jobhunter/static/vendor/htmx.min.js` and SortableJS 1.15.x to `src/jobhunter/static/vendor/Sortable.min.js` (download once, commit the files, record versions and licences in `src/jobhunter/static/vendor/README.md`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config, database, all models + first migration, auth/sessions/CSRF, owner-scoped
repository, base layout, test harness. **No user story work starts before this phase is done.**

- [X] T006 Implement settings in `src/jobhunter/config.py`: read `SESSION_SECRET` (required, ≥32 chars, fail fast), `APP_TIMEZONE` (default `America/Edmonton`, validated with `zoneinfo`), `DATABASE_PATH` (default `/data/jobhunter.db`), `COOKIE_SECURE` (default true), `LOG_LEVEL`; helper `smtp_password_for(username) -> str | None` reading `SMTP_PASSWORD_<USERNAME upper>`; settings object never exposes secrets in `repr`
- [X] T007 Implement `src/jobhunter/db.py`: SQLAlchemy engine for SQLite with `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` on connect, `get_session()` FastAPI dependency, UTC `now()` helper and app-TZ conversion helpers (`to_local`, `local_to_utc`, `today_local`)
- [X] T008 Implement all enums and tables in `src/jobhunter/models.py` exactly per data-model.md: enums `Role`, `Status`, `WorkMode`, `Currency`, `SalaryPeriod`, `SourceType`; tables `user_account` (username unique, `^[a-z0-9]{2,32}$`), `user_session`, `login_attempt`, `source` (`domains` JSON list), `job` (title/company required ≤ 200, `url_norm`, `company_title_key`, salary fields, `profile_id` nullable with `ON DELETE SET NULL`), `status_change`, `note` (body ≤ 20,000), `contact`, `follow_up` (description ≤ 200), `target_profile` (JSON lists, `is_default`, `is_archived`, name unique per user), `location_rule` (`work_modes` JSON non-empty, cascade), `sender_settings` (PK `user_id`, defaults `smtp.example.org`/587); cascade deletes from `job` to status_change/note/contact/follow_up
- [X] T009 Initialise Alembic (`alembic.ini`, `migrations/env.py` reading `DATABASE_PATH`, `render_as_batch=True` for SQLite) and write `migrations/versions/0001_initial.py` creating all tables and indexes from data-model.md (`(user_id, status)`, `(user_id, company_title_key)`, partial unique `(user_id, url_norm) WHERE url_norm IS NOT NULL`, `(user_id, date_found)`) and seeding the 13 sources from the data-model.md seed table (Manual with `is_system=true`)
- [X] T010 [P] Implement `src/jobhunter/auth/passwords.py`: `hash_password` (bcrypt cost 12), `verify_password`, `validate_password` (minimum 12 characters), `validate_username` (`^[a-z0-9]{2,32}$`)
- [X] T011 [P] Implement `src/jobhunter/auth/throttle.py`: record attempts in `login_attempt`; `is_blocked(username, ip)` true when more than 10 failures for that username+IP in the last 15 minutes; purge rows older than 1 day
- [X] T012 Implement `src/jobhunter/auth/sessions.py`: create session (256-bit URL-safe id, csrf token), cookie `jh_session` (`HttpOnly`, `Secure` per `COOKIE_SECURE`, `SameSite=Lax`), expiry after 30 days of inactivity (`last_seen_at` refreshed at most hourly), `delete_sessions_for_user(user_id, except_id=None)`; dependencies `current_user` (redirect 303 to `/login?next=` or `HX-Redirect` for HTMX; refuse inactive users; redirect users with `must_change_password` to `/account/password`; when a request arrives with an expired or unknown session cookie, the redirect adds `expired=1` so the login page and, after login, the target page show "Your session expired; please check and resubmit your changes") and `require_admin` (403 for non-admins); CSRF check dependency for all POSTs (form `csrf_token` or header `X-CSRF-Token`, 403 on mismatch) and a signed pre-login CSRF cookie for `/login` using `SESSION_SECRET`
- [X] T013 Implement `src/jobhunter/repo.py`: `get_owned(session, model, id, user_id)` raising 404 when missing **or** not owned (for `job`, `target_profile`); `get_job_child(session, model, job_id, child_id, user_id)` resolving through the owning job; `scoped(select, model, user_id)` helper; no function in this module may query an owned table without `user_id`
- [X] T014 Implement app factory in `src/jobhunter/main.py`: mount `/static`, Jinja2 templates with globals (`csrf_token`, `current_user`, app TZ formatting filters), error handlers (404/403/429 pages), `/health` returning `ok`, router registration, logging that never logs request bodies or env values
- [X] T015 [P] Create base layout `src/jobhunter/templates/base.html` (nav: Dashboard, Jobs, Board, Settings, Admin for admins, Logout form; loads `htmx.min.js`, `app.js`, `app.css`; `hx-headers` with CSRF token on `<body>`), `src/jobhunter/templates/errors/{403,404,429}.html`, `src/jobhunter/static/app.css` (readable at phone width), `src/jobhunter/static/app.js` (empty hooks file for later stories)
- [X] T016 Implement login/logout in `src/jobhunter/routes/auth.py` and `src/jobhunter/templates/auth/login.html` per contracts/http-routes.md: generic "invalid username or password" error, 429 "too many attempts" when throttled, safe `next` (same-origin path only), updates `last_login_at`, `POST /logout` deletes session
- [X] T017 Implement CLI in `src/jobhunter/cli.py`: `create-admin <username> --display-name <name> [--seed-defaults]` (password prompted twice without echo, validated; fails if username exists; `--seed-defaults` calls `seeds.apply_first_admin_defaults` once that exists, otherwise prints a notice) and `backup <dest-path>` using the sqlite3 online backup API
- [X] T018 Create test harness `tests/conftest.py`: temp DB per test with `alembic upgrade head`, `TestClient`, factories `make_user(username, role="user", password=...)`, `login(client, user)` helper that handles CSRF, and a `two_users` fixture (alice, bob) for isolation tests
- [X] T019 [P] Write `tests/integration/test_auth.py`: unauthenticated GET of `/` → 303 to `/login?next=/`; wrong password → generic error; correct login → redirect to `next`; open-redirect `next=https://evil` ignored; logout ends session; inactive user refused; session older than 30 days inactive refused; expired session → login page and target page show the session-expired message
- [X] T020 [P] Write `tests/integration/test_throttle_csrf.py`: 11th failed login for the same username+IP within 15 minutes → 429; POST without or with wrong CSRF token → 403
- [X] T021 Write `tests/integration/test_isolation.py`: a generic test that enumerates every route in `app.routes` with an `{id}`-style path parameter, creates the object as alice, requests it as bob (GET and POST with valid CSRF) and asserts 404 with alice's data unchanged; plus a test that every non-public route redirects to login when logged out (SC-005, SC-009). The route list grows automatically as stories add routes

**Checkpoint**: `uv run pytest` passes; an admin created with the CLI can log in and see an empty layout.

---

## Phase 3: User Story 1 - Log in and capture a job (Priority: P1) 🎯 MVP

**Goal**: Add a job by pasting a URL and/or text, review pre-filled fields, save it, and block or warn on duplicates.

**Independent Test**: Log in, add one job from a Greenhouse URL and one from pasted text, then paste the first URL again with `?utm_source=x#top` and confirm the existing job is shown instead of a new one.

### Tests for User Story 1

- [X] T022 [P] [US1] Write `tests/unit/test_dedupe.py`: at least 20 URL variant pairs (tracking params `utm_*`, `ref`, `refid`, `trk`, `trackingid`, `src`, `gclid`, `fbclid`, `mc_cid`, `mc_eid`, `lipi`, `from`; fragment; host case; `www.`; trailing slash; param order) that must normalise equal, plus pairs that must differ (Indeed `jk`, LinkedIn `currentJobId`, different paths); company/title keys ("Acme Inc." == "ACME", "AT&T" == "AT and T", legal suffixes `inc`, `incorporated`, `ltd`, `limited`, `llc`, `corp`, `corporation`, `co`, `company`, `ulc`, `lp`, `llp`, `gmbh`, `plc`)
- [X] T023 [P] [US1] Save fixtures in `tests/fixtures/pages/`: one real-structure HTML page each for Job Bank, Greenhouse, Lever, Ashby and Workday containing schema.org `JobPosting` JSON-LD, one page with only OpenGraph tags, and in `tests/fixtures/texts/` five pasted postings (with salary formats `$130,000 - $150,000`, `CAD 130k`, `USD 65/hr`, `120K–140K per year`, none); record expected fields in `tests/fixtures/expected.json`
- [X] T024 [P] [US1] Write `tests/unit/test_extract.py` asserting each fixture in `tests/fixtures/expected.json` extracts title, company, location, work mode, salary min/max/currency/period and description; unknown fields stay empty
- [X] T025 [P] [US1] Write `tests/unit/test_fetch_policy.py`: source matching by host and subdomain (FR-028a, unmatched → Manual); no fetch for `fetch_allowed=false` sources; robots.txt disallow → no fetch; redirect to a non-allowed host refused; private/loopback IPs refused; >2 MB response truncated/refused; 10 s timeout surfaced as `fetch_failed` (use `httpx.MockTransport`)
- [X] T026 [P] [US1] Write `tests/integration/test_jobs_capture.py`: prefill from text; prefill from allowed URL (mocked fetch); prefill from LinkedIn URL returns `not_fetched_disallowed` with source LinkedIn; create requires title and company; created job has status `new`, today's date (app TZ), Manual source for text, full description stored; duplicate URL → 409 page linking existing job; possible duplicate → warning, saved only with `confirm_possible_duplicate`; duplicate checks ignore other users' jobs (FR-013a); edit re-runs duplicate checks excluding itself; delete requires `confirm=yes`

### Implementation for User Story 1

- [X] T027 [P] [US1] Implement `src/jobhunter/services/dedupe.py` per research R6: `normalize_url`, `normalize_company`, `normalize_title`, `company_title_key`, `find_duplicates(session, user_id, url_norm, key, exclude_job_id=None) -> (url_match | None, possible_matches)`
- [X] T028 [P] [US1] Implement `src/jobhunter/services/extract.py` per research R7: dataclass `JobDraft` (title, company, location, work_mode, salary_text, salary_min, salary_max, salary_currency, salary_period, description); `from_html(html, url)` trying JSON-LD `JobPosting` (incl. `@graph`, `baseSalary`, `jobLocationType=TELECOMMUTE` → remote), then OpenGraph/`<title>`; `from_text(text)` heuristics (first non-empty line title, "Company:"/"at X" patterns, salary regex, remote/hybrid/on-site keywords, Canadian province and US state patterns); never raises on bad input
- [X] T029 [US1] Implement `src/jobhunter/services/fetch.py` per research R7: `match_source(session, url)`, `fetch_posting(url, source) -> FetchResult(status in {fetched, not_fetched_disallowed, fetch_failed}, html, message)` with robots.txt cache (24 h), `User-Agent: JobHunter/1.0 (+https://jobs.example.org; personal use)`, 10 s timeout, 2 MB cap, ≤3 redirects each re-checked against the allow-list, per-host minimum 5 s between requests, SSRF guard rejecting private, loopback, link-local and reserved IPs
- [X] T030 [US1] Implement job create/read/update/delete service functions in `src/jobhunter/services/jobs.py`: compute `url_norm` and `company_title_key` on create/edit, validate (title and company required ≤ 200; url http(s) only; `salary_min ≤ salary_max`; currency and period required if min/max given; `profile_id` must belong to the same user), create the initial `status_change` (`from_status=NULL`, `to_status=new`); the same function is the single entry point for every future job source (FR-014)
- [X] T031 [US1] Implement routes in `src/jobhunter/routes/jobs.py`: `GET /jobs/new`, `POST /jobs/prefill`, `POST /jobs`, `GET /jobs/{id}`, `GET|POST /jobs/{id}/edit`, `POST /jobs/{id}/delete` per contracts/http-routes.md, all via `repo.get_owned`
- [X] T032 [P] [US1] Create templates `src/jobhunter/templates/jobs/new.html` (URL field + text area), `src/jobhunter/templates/jobs/_form.html` (editable draft, fetch messages, duplicate banner with link and "save anyway"), `src/jobhunter/templates/jobs/detail.html` (fields, description rendered with preserved line breaks and long text wrapping, placeholders for timeline/notes/contacts/follow-ups), `src/jobhunter/templates/jobs/duplicate.html`
- [X] T033 [US1] Add a simple "Jobs" list at `GET /jobs` in `src/jobhunter/routes/jobs.py` (newest first, title/company/status/source/date; filters arrive in US3) so captured jobs are visible

**Checkpoint**: US1 tests pass; capture and duplicate detection work end to end.

---

## Phase 4: User Story 2 - Move jobs through the pipeline with full history (Priority: P1)

**Goal**: Change status from the job page or by kanban drag, with an append-only, backdatable history.

**Independent Test**: Move a job new → interested → applied → screening on the board, set `rejected` from the job page with yesterday's date, and confirm the timeline lists all changes in order.

### Tests for User Story 2

- [X] T034 [P] [US2] Write `tests/unit/test_statuses.py`: any-to-any transition allowed for all 10 statuses; same-status change writes nothing; `effective_at` defaults to now, accepts past local datetimes, rejects more than 1 day in the future; entries are never updated or deleted; timeline ordered by `effective_at, id`; invalid status rejected
- [X] T035 [P] [US2] Write `tests/integration/test_board.py`: `/board` shows the seven active columns, closed columns only with `closed=1`; `POST /jobs/{id}/status` from a kanban drop (HTMX) returns the updated card and writes history; from the job page with `effective_at` updates the timeline; invalid status → 422; no route exists to edit or delete a `status_change`

### Implementation for User Story 2

- [X] T036 [US2] Implement `src/jobhunter/services/statuses.py`: `ACTIVE_STATUSES`, `CLOSED_STATUSES`, `change_status(session, job, to_status, effective_at_local | None)` per research R8 and data-model.md state model; `timeline(session, job)`
- [X] T037 [US2] Add `POST /jobs/{id}/status` to `src/jobhunter/routes/jobs.py` and the timeline + status picker (with optional effective date/time input) to `src/jobhunter/templates/jobs/detail.html` via partial `src/jobhunter/templates/jobs/_timeline.html`
- [X] T038 [US2] Implement `GET /board` in `src/jobhunter/routes/board.py` and `src/jobhunter/templates/board/board.html` + `src/jobhunter/templates/board/_card.html` (title, company, location, days in status, link), closed-columns toggle
- [X] T039 [US2] Wire SortableJS in `src/jobhunter/static/app.js`: one sortable list per column with a shared group; on drop, `htmx.ajax('POST', '/jobs/{id}/status', ...)` with the new column's status and CSRF header; revert the card and show an error if the request fails

**Checkpoint**: US1 + US2 make a complete minimal tracker. This is the MVP.

---

## Phase 5: User Story 3 - Work the list: table, filters, notes, contacts, follow-ups (Priority: P2)

**Goal**: Filterable, sortable table; notes, contacts and follow-ups per job; dashboard stats.

**Independent Test**: With about 20 mixed jobs, filter to `applied` from one source, add a note, contact and a due follow-up to one job, and confirm the dashboard shows the follow-up and correct weekly counts.

### Tests for User Story 3

- [X] T040 [P] [US3] Write `tests/unit/test_stats.py`: applications per ISO week (app TZ) for the last 12 weeks using the first `applied` entry per job; response rate = jobs with `applied` and a later entry in {screening, interview, offer, accepted, rejected} ÷ jobs with `applied`; zero applied → "no data yet"; counts per status; due follow-ups = `done = false AND due_date ≤ today (app TZ)`
- [X] T041 [P] [US3] Write `tests/integration/test_table_children.py`: each filter (`status` multi, `company`, `source`, `work_mode`, `profile`, `found_from`/`found_to`, `followup_due`, `q` over title/company/description) and `sort`/`dir`/`page` (50 per page); notes add/edit/delete (newest first, body ≤ 20,000); contacts add/edit/delete (email validated if given, `profile_url` http(s) if given); follow-ups add/done/delete (description ≤ 200)

### Implementation for User Story 3

- [X] T042 [P] [US3] Implement `src/jobhunter/services/stats.py` per research R8 (SQL over `status_change`, scoped by `user_id`)
- [X] T043 [US3] Replace the simple list with the full table in `src/jobhunter/routes/jobs.py` (`GET /jobs` query params per contracts/http-routes.md, filters kept in the URL, HTMX partial for the table body) and `src/jobhunter/templates/jobs/list.html` + `src/jobhunter/templates/jobs/_rows.html`
- [X] T044 [US3] Implement notes, contacts and follow-ups routes in `src/jobhunter/routes/job_children.py` (all via `repo.get_job_child`) and partials `src/jobhunter/templates/jobs/_notes.html`, `_contacts.html`, `_followups.html` included in `detail.html`
- [X] T045 [US3] Implement dashboard `GET /` in `src/jobhunter/routes/dashboard.py` and `src/jobhunter/templates/dashboard.html`: applications per week (simple server-rendered bar list, no chart library), response rate, counts per status, follow-ups due with links

**Checkpoint**: US3 tests pass; dashboard and table usable with 2,000 jobs.

---

## Phase 6: User Story 4 - Define target-position profiles (Priority: P2)

**Goal**: Each user manages profiles with location rules; one default; jobs pre-tagged; admin seeded with QA Lead.

**Independent Test**: Create two profiles, mark one default, tag a job with the other, filter the table by it; confirm the admin's seeded "QA Lead" profile.

### Tests for User Story 4

- [X] T046 [P] [US4] Write `tests/integration/test_profiles.py`: create with location rules ("Calgary, AB" [onsite, hybrid, remote] 130000 CAD; "USA" [remote] 130000 USD); name required and unique per user; at least one location rule with non-empty `work_modes`; currency required when a floor is given; only one default per user; new jobs pre-tagged with the default; archive hides from pickers but keeps tags; delete requires `confirm=yes` and sets tagged jobs' `profile_id` to NULL; `source_ids` must reference existing sources
- [X] T047 [P] [US4] Write `tests/unit/test_seeds.py`: `create-admin --seed-defaults` creates exactly the QA Lead profile from data-model.md (synonyms Test Manager, QA Manager, Test Lead; three location rules; default; all enabled sources) and is idempotent-safe (refuses to seed twice)

### Implementation for User Story 4

- [X] T048 [US4] Implement profile services in `src/jobhunter/services/profiles.py` (create/update with location rules, set default atomically, archive, delete with job un-tagging) and routes in `src/jobhunter/routes/settings_profiles.py` per contracts/http-routes.md
- [X] T049 [P] [US4] Create templates `src/jobhunter/templates/settings/index.html`, `settings/profiles.html`, `settings/profile_form.html` with HTMX add/remove rows for location rules (place, work-mode checkboxes, floor, currency) and comma-separated inputs for synonyms/keywords
- [X] T050 [US4] Implement `src/jobhunter/seeds.py` `apply_first_admin_defaults(session, user)` (QA Lead profile per data-model.md) and hook it into `create-admin --seed-defaults` in `src/jobhunter/cli.py`
- [X] T051 [US4] Add profile pre-tagging (user's default) and profile picker (non-archived, own profiles only) to `src/jobhunter/templates/jobs/_form.html` and the `profile` filter to the table

**Checkpoint**: US4 tests pass.

---

## Phase 7: User Story 6 - Admin manages family accounts (Priority: P2)

**Goal**: Admin creates, resets, disables and re-enables accounts and manages the shared source list; users change their own password.

**Independent Test**: As admin create `kid1`; kid1 must change password at first login, adds a job; admin cannot see it (404 on its URL); disable kid1 and confirm kid1 is logged out and cannot log in.

### Tests for User Story 6

- [X] T052 [P] [US6] Write `tests/integration/test_admin.py`: non-admin → 403 on every `/admin/*`; create user validates username `^[a-z0-9]{2,32}$` and password ≥ 12 chars, sets `must_change_password`; first login forces `/account/password`; reset password ends that user's sessions; disable ends sessions and refuses login, data kept; cannot disable the last active admin; accounts created on the admin page always get role `user` and no route changes roles; admin user list shows no job data; admin requesting a kid's job URL → 404
- [X] T053 [P] [US6] Write `tests/integration/test_sources_admin.py`: admin edits name, type, domains, `fetch_allowed`, `enabled`; Manual cannot be deleted; a source referenced by jobs cannot be deleted (disable instead); non-admin cannot change sources but can select them; a disabled source is hidden from profile and job pickers, is never fetched (prefill returns `not_fetched_disallowed`), but pasted URLs still match it for tagging and existing jobs keep it (FR-028)

### Implementation for User Story 6

- [X] T054 [US6] Implement `src/jobhunter/services/accounts.py` (create user, reset password, disable/enable with last-active-admin guard, change own password ending other sessions) and `GET|POST /account/password` in `src/jobhunter/routes/auth.py` with `src/jobhunter/templates/auth/password.html`
- [X] T055 [US6] Implement admin routes in `src/jobhunter/routes/admin.py` (`/admin/users`, `/admin/users/new`, reset-password, disable, enable, `/admin/sources` CRUD) per contracts/http-routes.md, all behind `require_admin`
- [X] T056 [P] [US6] Create templates `src/jobhunter/templates/admin/users.html`, `admin/user_form.html`, `admin/sources.html`, `admin/source_form.html` (domains as comma-separated hosts)

**Checkpoint**: US6 tests pass; isolation test (T021) covers the new routes.

---

## Phase 8: User Story 5 - Configure the sender email and send a test (Priority: P3)

**Goal**: Per-user sender settings with password status only, and a button-triggered test email to the user's own address.

**Independent Test**: Fill sender settings, click "send test email", receive it; break the host and see a readable error within 30 s.

### Tests for User Story 5

- [X] T057 [P] [US5] Write `tests/unit/test_mailer.py` with a fake `smtplib.SMTP`: message `From: "Sam Rivera" <sam@example.org>`, `Reply-To`, signature appended, recipient only the user's own from-address plus BCC to self when enabled; STARTTLS then login with `SMTP_PASSWORD_<USERNAME>`; overall deadline of 25 s across connect, STARTTLS, login and send (simulate slow steps whose sum exceeds 25 s); auth failure, connection refused, DNS failure, TLS failure and timeout each map to a plain-language message; password never appears in messages or logs
- [X] T058 [P] [US5] Write `tests/integration/test_sender.py`: invalid from/reply-to rejected with field errors; page shows "password: configured"/"not configured" and never the value; test send with no password explains the admin must configure it; test send is POST + CSRF only; settings of one user never used for another; `create-admin --seed-defaults` seeds sam@example.org / "Sam Rivera" / smtp.example.org:587 / username sam@example.org / bcc off

### Implementation for User Story 5

- [X] T059 [P] [US5] Implement `src/jobhunter/services/mailer.py` per research R9: `send_test_email(settings, username) -> Result(ok, message)` using `email.message.EmailMessage` and `smtplib.SMTP` + `starttls()` under an overall 25 s deadline (socket timeout = remaining time before each step); never sends to any address other than the user's own
- [X] T060 [US5] Implement `GET|POST /settings/sender` and `POST /settings/sender/test` (run via `run_in_threadpool`) in `src/jobhunter/routes/settings_sender.py` and `src/jobhunter/templates/settings/sender.html` (+ `_test_result.html` partial); new users get defaults `smtp.example.org`, 587
- [X] T061 [US5] Extend `src/jobhunter/seeds.py` `apply_first_admin_defaults` with the sender settings from data-model.md

**Checkpoint**: All six stories pass their tests.

---

## Phase 8b: User Story 7 - Store my original resume (Priority: P2)

**Goal**: Each user uploads DOCX/PDF resumes (≤ 10 MB, verified by content), keeps versions, one current, private downloads.

**Independent Test**: Upload a DOCX then a PDF; the PDF is current; both download with original names; make the DOCX current; another user gets 404 for both.

### Tests for User Story 7

- [X] T073 [P] [US7] Write `tests/unit/test_resumes.py`: format detection from content (`%PDF-` magic → pdf; ZIP containing `word/document.xml` → docx; a `.docx`-named PDF is pdf; a ZIP without `word/document.xml`, plain text, an image and an empty file are rejected); size limit 10,485,760 bytes; original name sanitised (path parts and control characters removed, ≤ 200 chars)
- [X] T074 [P] [US7] Write `tests/integration/test_resume_upload.py`: upload DOCX then PDF → newest current; download returns identical bytes with `Content-Disposition: attachment; filename*=…` original name and `X-Content-Type-Options: nosniff`; make older current → only one current; renamed text file and oversized file → 422 and nothing stored; delete requires `confirm=yes`, removes the file from disk and promotes the newest remaining; other user → 404 for download/current/delete (also covered by T021 via `resume_id`)

### Implementation for User Story 7

- [X] T075 [US7] Add `ResumeFile` to `src/jobhunter/models.py` per data-model.md and write migration `migrations/versions/0002_resume_file.py`
- [X] T076 [US7] Implement `src/jobhunter/services/resumes.py`: `detect_format(bytes)`, `sanitize_name`, `save_upload(session, user, filename, data)` (writes to `<DATA_DIR>/uploads/resumes/<user_id>/<uuid>.<ext>` atomically, sets current), `set_current`, `delete_resume` (file + row, promote newest), `path_for`; uploads directory derived from `DATABASE_PATH`'s folder
- [X] T077 [US7] Implement routes in `src/jobhunter/routes/settings_resume.py` per contracts/http-routes.md "Resume" (read upload with a 10 MB + 1 byte cap) and template `src/jobhunter/templates/settings/resume.html`; link from Settings
- [X] T078 [US7] Extend `deploy/backup.sh` to archive `data/uploads` as `uploads-YYYYMMDD.tar.gz` next to the DB backup (same retention)

**Checkpoint**: US7 tests pass; isolation sweep includes resume routes.

---

## Phase 9: Polish, Deployment & Cross-Cutting

- [X] T062 [P] Write `tests/integration/test_secrets.py`: with known values for `SESSION_SECRET` and `SMTP_PASSWORD_SAM`, crawl every GET route as admin and as a user and assert neither value nor any bcrypt hash appears in responses; assert neither appears in captured logs or in the DB file bytes (SC-006)
- [X] T063 [P] Write `tests/integration/test_performance.py` (marked `slow`): seed 2,000 jobs with history for one user; `/jobs`, `/board`, `/` each respond in under 2 s (SC-004)
- [X] T064 Create `Dockerfile` per research R11: `python:3.12-slim`, install uv, `uv sync --frozen --no-dev`, copy `src/`, `migrations/`, `alembic.ini`, non-root user, `ENV DATABASE_PATH=/data/jobhunter.db APP_TIMEZONE=America/Edmonton`, `EXPOSE 8000`, `HEALTHCHECK` on `http://127.0.0.1:8000/health`, `CMD` running `alembic upgrade head && uvicorn jobhunter.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'`
- [X] T065 [P] Create `deploy/docker-compose.yml` per contracts/cli-and-config.md (service `job-hunter`, `build` context pointing at the repo checkout, `expose: ["8000"]`, `./data:/data`, `env_file: .env`, `VIRTUAL_HOST=jobs.example.org`, `VIRTUAL_PORT=8000`, `LETSENCRYPT_HOST=jobs.example.org`, external network `webserver_default`, `restart: unless-stopped`)
- [X] T066 [P] Create `deploy/backup.sh` per contracts/cli-and-config.md: run `jobhunter backup /data/backups/jobhunter-$(date +%Y%m%d).db` in the container, verify `/mnt/backup` is mounted (exit 1 otherwise), copy to `/mnt/backup/job-hunter/`, keep the last 30 there and the last 3 in `./data/backups`
- [X] T067 [P] Write `README.md`: what the app is, local dev (`uv sync`, migrations, `create-admin`, run), tests, deployment and backup summary, link to `specs/001-job-tracker-mvp/quickstart.md`; no secret values
- [X] T068 Run `uv run ruff check . && uv run ruff format --check . && uv run pytest` and fix all failures
- [X] T069 Execute every scenario in `specs/001-job-tracker-mvp/quickstart.md` sections 2–4 locally and record results in `specs/001-job-tracker-mvp/checklists/validation.md`
- [X] T070 Manual, needs the admin: at the DNS registrar add `CNAME jobs → home.example.net` (same as tracker, photos, etc.; nothing on the cloud relay, which only serves www/apex; local-DNS already resolves `*.example.org` to 10.0.0.10 locally). Do this a few minutes before T071 so Let's Encrypt can issue the certificate; verify with `dig +short jobs.example.org @1.1.1.1`
- [X] T071 Manual, needs the admin: create `/opt/docker/job-hunter/` with `docker-compose.yml` and `.env` (mode 600, real `SESSION_SECRET` and `SMTP_PASSWORD_SAM`), `docker compose up -d --build`, run `docker compose exec job-hunter jobhunter create-admin sam --display-name "Sam Rivera" --seed-defaults`, verify `curl -I https://jobs.example.org` redirects to `/login` with a valid certificate
- [X] T072 Manual, needs the admin: install the nightly cron entry `30 3 * * * /opt/docker/job-hunter/backup.sh` and run it once by hand to confirm a file appears in `/mnt/backup/job-hunter/`

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (1)** → **Foundational (2)** → user stories → **Polish (9)**
- Foundational blocks every story (models, migration, auth, repo, harness).

### User story dependencies

- **US1** (P1): needs Foundational only.
- **US2** (P1): needs US1 (jobs exist and the job page exists).
- **US3** (P2): needs US1; the dashboard reads history from US2 (stats tests can run on directly inserted history).
- **US4** (P2): needs US1 for job tagging (T051); profile CRUD itself only needs Foundational.
- **US6** (P2): needs Foundational only; can start right after Phase 2.
- **US7** (P2, added during implementation): needs Foundational only.
- **US5** (P3): needs Foundational only (T061 extends `seeds.py` from T050; do T050 first or create the file there).

### Within each story

Tests first (must fail) → services → routes → templates → story checkpoint.

### Parallel opportunities

- Setup: T003, T004, T005 together.
- Foundational: T010, T011, T015 together after T008; T019, T020 together after T018.
- US1: T022–T026 (tests and fixtures) together; T027 and T028 together; T032 alongside T031.
- After Foundational, **US6 and US5** can run in parallel with US1/US2 (different files).
- US3 T040/T041, US4 T046/T047, US6 T052/T053, US5 T057/T058 are parallel test pairs.

## Parallel Example: User Story 1

```text
Together: T022 test_dedupe.py | T023 fixtures | T024 test_extract.py | T025 test_fetch_policy.py | T026 test_jobs_capture.py
Then together: T027 services/dedupe.py | T028 services/extract.py
Then: T029 → T030 → T031 (with T032 templates in parallel) → T033
```

## Implementation Strategy

### MVP first (US1 + US2)

1. Phases 1–2, then US1, then US2.
2. **Stop and validate**: capture, duplicates, statuses and history work for the admin.
3. Optionally deploy at this point (T064–T066, T070–T072) and start using it.

### Incremental delivery

US3 (table, notes, dashboard) → US4 (profiles) → US6 (kids' accounts) → US5 (sender test) → Polish.
Each story ends at a checkpoint with its tests green and the isolation test (T021) still passing.
