# Research: Job Tracker MVP

All Technical Context items are resolved below. Format: Decision / Rationale / Alternatives.

## R1. Web stack and packaging

- **Decision**: Python 3.12, FastAPI + Uvicorn (one worker), Jinja2 templates, HTMX for partial
  updates, SortableJS for kanban drag-and-drop. HTMX and SortableJS are vendored into
  `static/vendor/` (no CDN). Dependencies managed with `uv` (`pyproject.toml` + `uv.lock`).
- **Rationale**: Fixed by constitution (Principle I, VIII, Tech Constraints). Vendoring keeps
  the app free of external SaaS at runtime. One worker keeps SQLite writes simple.
- **Alternatives**: CDN-hosted JS (rejected: external dependency); Django (heavier, not the
  agreed stack); pip + requirements.txt (works, but uv is already installed and gives a lock).

## R2. Persistence

- **Decision**: SQLite file at `/data/jobhunter.db`, WAL mode, `foreign_keys=ON`, accessed via
  SQLModel (SQLAlchemy 2). Schema managed by Alembic; the first migration also seeds the shared
  source list. List-valued fields (synonyms, keywords, domains) stored as JSON columns.
  Timestamps stored in UTC; displayed in the app time zone.
- **Rationale**: Constitution Principle I. Scale (≈5 users × ≤2,000 jobs) is tiny for SQLite.
  JSON columns avoid join tables for short tag lists that are only read/written as a whole.
- **Alternatives**: Separate tables for synonyms/keywords (more joins, no query need yet);
  Postgres (forbidden: separate DB server).

## R3. Authentication and sessions

- **Decision**: Accounts in a `user_account` table with bcrypt hashes (`bcrypt` library,
  cost 12). **Server-side sessions** in a `user_session` table; the browser holds only a random
  256-bit session id in a cookie (`HttpOnly`, `Secure`, `SameSite=Lax`). Sessions expire after
  30 days of inactivity (`last_seen_at`, refreshed at most once per hour). Disabling a user or
  resetting their password deletes their sessions. Login throttling via a `login_attempt`
  table: more than 10 failures per username+IP in 15 minutes → refuse with a generic message
  until the window passes. First admin created by CLI `jobhunter create-admin` (prompts for
  password; never via env).
- **Rationale**: FR-002a requires that disabling ends sessions; signed-cookie sessions cannot
  be revoked. DB-backed throttling survives restarts. Constitution IV permits hashes in DB.
- **Alternatives**: Starlette `SessionMiddleware` signed cookies (no revocation); passlib
  (unmaintained, bcrypt warnings); in-memory throttling (lost on restart).

## R4. CSRF protection

- **Decision**: Per-session CSRF token stored in `user_session`, rendered into every form as a
  hidden field and sent by HTMX via `hx-headers` (`X-CSRF-Token`). All state-changing requests
  are POST and must carry a matching token. Login form uses a pre-session token cookie.
- **Rationale**: Cookie auth + forms needs CSRF defence; `SameSite=Lax` alone does not cover
  every case. No JS framework needed.
- **Alternatives**: `starlette-csrf`/`fastapi-csrf-protect` packages (extra dependency for
  ~40 lines of code).

## R5. Per-user data isolation

- **Decision**: Every per-user table has a non-null `user_id` FK. All reads/writes go through
  a small repository layer whose functions require the current `user_id` and add it to every
  query; fetching by id uses `get_owned(model, id, user_id)` which returns 404 when the row is
  missing **or** owned by someone else. Child rows (notes, contacts, follow-ups, history) are
  fetched through their owning job. Admin role checks are a separate dependency and grant no
  data access. An automated test logs in as two users and requests every route with the other
  user's ids (SC-009).
- **Rationale**: Constitution VIII and FR-002c; one choke point is easy to test.
- **Alternatives**: SQLite has no row-level security; per-user database files (complicates
  shared sources, backups, migrations).

## R6. Duplicate detection

- **Decision**:
  - `url_norm`: lower-case scheme and host, drop leading `www.`, drop fragment, drop trailing
    slash, drop tracking params (`utm_*`, `ref`, `refid`, `trk`, `trackingid`, `src`, `gclid`,
    `fbclid`, `mc_cid`, `mc_eid`, `lipi`, `from`), sort remaining params. Job-identifying params
    (e.g. Indeed `jk`, LinkedIn `currentJobId`) are kept.
  - `company_title_key`: `norm(company) + "|" + norm(title)`, where `norm` = Unicode NFKC,
    casefold, `&`→`and`, strip punctuation, collapse whitespace; company additionally drops
    legal suffixes (`inc`, `incorporated`, `ltd`, `limited`, `llc`, `corp`, `corporation`,
    `co`, `company`, `ulc`, `lp`, `llp`, `gmbh`, `plc`).
  - Unique index on `(user_id, url_norm)` (partial: url present) → hard block (FR-012);
    plain index on `(user_id, company_title_key)` → warning (FR-013).
  - Implemented as a pure module `services/dedupe.py` used by every job-creation path (FR-014).
- **Rationale**: Deterministic, testable with fixture tables (SC-003, Principle VII).
- **Alternatives**: Fuzzy matching (false positives, harder to explain); global uniqueness
  (would leak other users' jobs, FR-013a).

## R7. Pre-filling from URL and pasted text

- **Decision**:
  - **URL**: match host against `source.domains` (FR-028a). Fetch only when that source has
    `fetch_allowed` and `robots.txt` permits (`urllib.robotparser`, cached 24 h). Fetch with
    `httpx`: GET, 10 s timeout, 2 MB cap, ≤3 redirects (each re-checked against the allow-list),
    `User-Agent: JobHunter/1.0 (+https://jobs.example.org; personal use)`, at most 1 request per
    host per 5 s. Resolved IPs in private/loopback ranges are refused (SSRF guard).
  - **Extraction** (`services/extract.py`, pure functions on HTML/text): 1) schema.org
    `JobPosting` JSON-LD (used by Job Bank, Greenhouse, Lever, Ashby, Workday and most boards);
    2) OpenGraph / `<title>` fallback; 3) for pasted text, heuristics: first non-empty line as
    title, "Company:"/"at <Company>" patterns, salary regex (`$`, `CAD`, `USD`, `k`, ranges,
    `/hr`, `per year`), work-mode keywords (remote/hybrid/on-site), Canadian/US location
    patterns. Whatever is not found stays empty (FR-006). HTML parsed with BeautifulSoup
    (`html.parser`).
  - Fetch failure or disallowed site → form opens with URL set, message shown, and a textarea
    for pasted text (edge cases).
- **Rationale**: JSON-LD gives structured data without site-specific scrapers; respects
  Principle V. Pure extractor functions are fixture-testable (Principle VII).
- **Alternatives**: Per-site HTML scrapers (brittle); headless browser (heavy, against
  Principle V spirit); Claude extraction (P3, and Claude calls must be background jobs).

## R8. Statuses, history and statistics

- **Decision**: `job.status` holds the current status; `status_change` is append-only
  (`from_status`, `to_status`, `effective_at`, `recorded_at`). Creating a job writes an entry
  with `from_status = NULL, to_status = new`. Changing to the same status writes nothing.
  Any-to-any transitions are allowed (spec). Stats are computed with SQL over `status_change`:
  - applications/week = first `effective_at` with `to_status='applied'` per job, bucketed by
    ISO week in the app time zone, last 12 weeks;
  - response rate = jobs with an `applied` entry and a later entry in
    {screening, interview, offer, accepted, rejected} ÷ jobs with an `applied` entry; shows
    "no data yet" when the denominator is 0.
  Status logic lives in `services/statuses.py` (pure + one DB write function).
- **Rationale**: FR-015–FR-022; deriving from history keeps one source of truth.

## R9. Email test

- **Decision**: Python stdlib `smtplib` with STARTTLS on port 587, an overall 25 s deadline for
  the whole exchange (socket timeout set to the remaining time before each step: connect,
  STARTTLS, login, send; exceeding it reports "mail server did not respond in time"), run in a
  thread from the request (`run_in_threadpool`). Password read from env
  `SMTP_PASSWORD_<USERNAME uppercased>`. Message built with `email.message.EmailMessage`;
  recipient is always the user's own from-address (+ BCC to self if enabled). SMTP errors are
  mapped to plain-language messages (auth failed, host unreachable, TLS failed, sender refused).
- **Rationale**: FR-029–FR-032, SC-007; no extra dependency. Not a Claude call, so Principle VI's
  background-job rule does not apply; 20 s timeout keeps the request bounded.
- **Alternatives**: aiosmtplib (extra dependency, no benefit at this volume).

## R10. Time zone

- **Decision**: One app-wide time zone from env `APP_TIMEZONE`, default `America/Edmonton`
  (same as the existing analytics deployment; covers Calgary). Effective-date inputs are
  interpreted in this zone and stored as UTC.
- **Rationale**: Resolves the spec's outstanding time-zone item; all family members are in
  the same zone. Per-user zones are YAGNI.

## R11. Deployment, backups

- **Decision**: `Dockerfile` (`python:3.12-slim`, `tzdata`, uv-installed deps, non-root user,
  `HEALTHCHECK` on `/health`), started with `alembic upgrade head && uvicorn`. Compose file in
  `deploy/` mirrors `/opt/docker/analytics`: `expose: 8000`, `./data:/data`, `env_file: .env`,
  `VIRTUAL_HOST=jobs.example.org`, `VIRTUAL_PORT=8000`, `LETSENCRYPT_HOST=jobs.example.org`, network
  `webserver_default` (external), `restart: unless-stopped`. Node and the Claude CLI are **not**
  installed in this feature; they arrive with P3.
  Backups: `deploy/backup.sh` run nightly by host cron → `docker compose exec` runs
  `jobhunter backup /data/backups/<date>.db` (SQLite online backup API), then the host copies it
  to `/mnt/backup/job-hunter/` and keeps the last 30.
- **Rationale**: Principles I and IX; consistent with existing server conventions.

## R12. Testing

- **Decision**: pytest + FastAPI `TestClient` against a temporary SQLite file per test.
  Suites: `unit/` (dedupe, extract with saved HTML/text fixtures, statuses, stats, mailer with a
  fake SMTP), `integration/` (auth, throttling, CSRF, isolation over every route, admin, job
  flows, settings). `ruff` for lint/format. No browser tests in the MVP; kanban drag-and-drop
  posts to the same status endpoint that integration tests cover.
- **Rationale**: Principle VII coverage (parsers, dedupe, status transitions, isolation).
