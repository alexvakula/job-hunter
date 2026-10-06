# Job Hunter Constitution

## Core Principles

### I. Single Self-Hosted Container

- The application MUST ship as one Docker container running FastAPI with Jinja2 templates
  and HTMX, persisting data in SQLite on a mounted volume (`./data:/data`).
- There MUST be no external SaaS dependency and no separate database server. Outbound
  integrations are limited to the user's own infrastructure (e.g. the DMS mail server) and
  the Claude CLI under the user's subscription.
- Production deployment MUST sit behind the existing nginx-proxy at `jobs.example.org`,
  following the compose pattern of `/opt/docker/analytics/` (external `webserver_default`
  network, `VIRTUAL_HOST` / `LETSENCRYPT_HOST` env vars).

Rationale: one container is cheap to run, back up, and reason about on a home server.

### II. Honest Resumes (NON-NEGOTIABLE)

- Claude MAY rephrase, reorder, condense and highlight experience that exists in the master
  resume, and MAY mirror job-description keywords only where they truthfully describe that
  experience.
- Claude MUST NEVER invent or alter skills, employers, job titles, dates, degrees or
  certifications.
- Factual fields (employers, titles, dates, degrees, certifications) MUST be rendered from the
  structured master resume data, not from free-form LLM output. Any skill or certification in
  a generated document that is absent from the master resume MUST be flagged and block export
  until resolved.

Rationale: a fabricated claim can cost an offer or a reputation; the tool must be trustworthy.

### III. Human in the Loop (NON-NEGOTIABLE)

- Nothing MUST ever be emailed, submitted or otherwise sent to a third party without the user
  whose account sends it first seeing a full preview (recipients, subject, body, attachments)
  and giving an explicit confirmation. No user, including the admin, can send on another
  user's behalf.
- Background jobs (scheduled searches, Claude runs) MAY gather and propose data but MUST NOT
  send anything outward on their own.
- The settings "send test email" action is permitted only on an explicit button click and
  only to that user's own configured address.

Rationale: applications are irreversible and represent the user; automation assists, it does
not act on the user's behalf.

### IV. Secrets Stay in .env

- Secrets (each user's SMTP password, `CLAUDE_CODE_OAUTH_TOKEN`, session secret) MUST live
  only in `.env` (or container environment) on the host. Per-user secrets are keyed by
  username, e.g. `SMTP_PASSWORD_SAM`.
- Secrets MUST NOT be stored in the database, rendered in any page or API response, written
  to logs, or committed to git.
- Exception: login passwords are stored in the database only as bcrypt hashes. Hashes MUST NOT
  be shown in any page or response or written to logs, and plain-text passwords MUST NEVER be
  stored anywhere. `.env` MUST be listed in `.gitignore`; a `.env.example` with
  placeholder values MAY be committed.
- The UI MAY show whether a secret is configured (set / not set), never its value.

Rationale: a single leaked token exposes a user's mailbox or the Claude subscription; hashes
in the database let the admin manage accounts without editing `.env`.

### V. Respect Site Terms and robots.txt

- Source adapters MUST honour each site's Terms of Service and `robots.txt`.
- Official feeds, public ATS JSON endpoints (Greenhouse, Lever, Ashby, Workday) and
  job-alert emails ingested via IMAP MUST be preferred over HTML scraping.
- Sites that forbid scraping (e.g. LinkedIn, Indeed, Glassdoor) MUST NOT be scraped; they are
  reached only through their alert emails or links the user pastes.
- Any permitted fetching MUST identify itself, rate-limit, and back off on errors.

Rationale: staying within the rules keeps the tool reliable and the user's accounts safe.

### VI. Bounded Claude CLI Jobs

- Every Claude CLI (`claude -p`) invocation MUST run as a background job from a persisted
  queue, never inside a web request.
- Jobs MUST run with concurrency 1, a hard timeout, and `--output-format json` validated
  against a strict schema; schema-invalid output is a failed job, not partial data.
- Allowed tools MUST be restricted to `WebSearch` and `WebFetch`; shell, file and edit tools
  MUST NOT be granted.
- Failures (timeout, invalid output, expired or missing token) MUST be recorded and visible
  in the UI.

Rationale: bounded, validated jobs keep the server responsive and the LLM's reach contained.

### VII. Tests for Critical Logic

- Automated tests (pytest) are REQUIRED for: source and email parsers (using saved
  HTML/email fixtures), job dedupe logic, status transitions and their history log, the ATS
  scorer, DOCX generation (re-parsed to confirm single column and standard headings), and
  per-user data isolation (one user cannot see or change another user's records).
- A change touching any of these areas MUST include or update tests, and the suite MUST pass
  before merge or deploy.

Rationale: these are the places where silent errors corrupt data or embarrass the user.

### VIII. Keep It Simple, Family Use

- The app serves one family: the admin (Sam Rivera) and the admin's children, about 5
  accounts in total. There are exactly two roles: admin and user. There MUST be no
  self-sign-up; only the admin creates, disables and resets accounts.
- Each user's data (jobs, status history, notes, contacts, follow-ups, target-position
  profiles, sender settings, and later resumes and sent applications) MUST be private to that
  user. Every query and action MUST be scoped to the logged-in user, and a user MUST NOT be able
  to read or change another user's data, including by guessing IDs or URLs. The admin role
  grants account management, not access to other users' data.
- The source list is shared by all users and managed by the admin.
- Claude-powered features are available to each user who has their own Claude credentials:
  their own subscription token in `.env` as `CLAUDE_CODE_OAUTH_TOKEN_<USERNAME>` (the admin may
  use `CLAUDE_CODE_OAUTH_TOKEN`). A user's Claude jobs MUST run only on that user's own token
  and CLI settings; a token MUST NEVER serve another user's jobs, in line with the Claude
  subscription terms (amended 2026-10-06; previously admin only).
- Pages MUST be server-rendered. JavaScript is limited to HTMX and small, justified additions
  (e.g. SortableJS for the kanban); no SPA framework or frontend build step.
- New dependencies, services or abstractions MUST be justified in the plan's Complexity
  Tracking; YAGNI applies.

Rationale: a family tool must stay maintainable by one person in spare time,
and job searches are private.

### IX. Backups

- The SQLite database MUST be backed up nightly with a consistent online backup
  (`sqlite3 .backup` or equivalent), together with generated documents, to
  `/mnt/backup/job-hunter/`.
- Backups MUST NOT be stored only inside the container or its data volume.

Rationale: job history and sent-document records are irreplaceable.

## Technology & Deployment Constraints

- Runtime: `python:3.12-slim` base image; FastAPI, Jinja2, HTMX, SQLModel on SQLite, Alembic
  for schema migrations. Node and `@anthropic-ai/claude-code` are added to the image by the first
  feature that calls the Claude CLI (P3), not before.
- Authentication: in-app session login against user accounts stored in the database (bcrypt
  password hashes). The first admin account is created by a one-time command run inside the
  container. Every route except the login page and static assets MUST require an
  authenticated session; admin pages MUST additionally require the admin role.
- Email: outbound mail via the example.org SMTP server (`smtp.example.org:587`, STARTTLS), each
  user sending from their own mailbox.
- Code lives in `~/job-hunter/` (git); deployment lives in `/opt/docker/job-hunter/`.
- The data model MUST be designed so later features (resume/ATS/email, search/Claude) can be
  added through migrations without rewriting the tracker.

## Development Workflow & Quality Gates

- Work follows the spec-kit flow: specify → clarify → plan → tasks → analyze → implement, with
  the user reviewing after each step.
- Every plan MUST pass a Constitution Check against Principles I–IX before design and again
  after design; violations MUST be listed in Complexity Tracking with a justification or the
  design changed.
- Before deploy: tests pass (Principle VII), no secrets in the diff (Principle IV), and any
  outward-sending path shows preview + confirmation (Principle III).
- Production verification: `https://jobs.example.org` serves a valid certificate and
  unauthenticated requests redirect to the login page.

## Governance

- This constitution supersedes other practices and documents for this project. Where the
  product brief or a spec conflicts with it, the constitution wins until amended.
- Amendments are made via `/speckit-constitution`, reviewed and approved by the user, and
  recorded with a version bump and updated Last Amended date.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle, MINOR
  for adding a principle or materially expanding guidance, PATCH for clarifications and
  wording.
- Compliance is checked at every plan's Constitution Check, during `/speckit-analyze`, and in
  review of each implementation change.

**Version**: 2.1.0 | **Ratified**: 2026-10-05 | **Last Amended**: 2026-10-06
