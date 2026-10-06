# Job Hunter: a job-search web app, built with spec-kit

## Context
You want one place to (1) track every job and its status, (2) generate ATS-optimized resumes and cover letters for each job and email applications, (3) search Canadian job boards, and (4) let Claude do the searching and tailoring. Your choices: **jobs.example.org behind a login**, **headless Claude CLI** (your subscription, no API bill), **FastAPI + SQLite + HTMX**, and **DOCX/PDF generation + emailing from the app + an ATS match score**.

The build will follow GitHub **spec-kit** (spec-driven development). It isn't installed: there's no `uv` and no `specify` on this server, and spec-kit isn't in the official Claude plugin marketplace. It's a CLI that adds `/speckit.*` slash commands to a project.

## Step 1: Install spec-kit (no sudo needed)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # installs to ~/.local/bin
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
specify check
specify init ~/job-hunter --ai claude --script sh        # also runs git init
```
This creates `~/job-hunter/.specify/` (templates, scripts, memory/constitution.md) and `.claude/commands/speckit.*.md`. **A new Claude Code session started in `~/job-hunter` is needed** before the slash commands appear.

## Step 2: The spec-kit pipeline (run in ~/job-hunter)
1. `/speckit.constitution`: principles: single container, SQLite, no SaaS dependencies, secrets only in `.env`, honest resumes (Claude may rephrase or reorder real experience but must **never invent** skills or jobs), respect site ToS/robots, tests for parsers and the scorer.
2. `/speckit.specify`: the feature spec from the scope below.
3. `/speckit.clarify`: settle open questions (job-site list, resume source format).
4. `/speckit.plan`: technical plan using the architecture below.
5. `/speckit.tasks`, then `/speckit.analyze` (consistency check), then `/speckit.implement`, one MVP phase at a time.

## Product scope (input for /speckit.specify)
**P1: Tracker (MVP)**
- Jobs table: title, company, location, remote/hybrid, salary, URL, source, description (full text saved, because postings disappear), date found, dedupe key (normalized company+title+URL).
- Statuses: `new → interested → applied → screening → interview → offer → accepted`, plus `rejected`, `withdrawn`, `ghosted`. Every status change is logged with a timestamp. Notes, contacts, and follow-up dates per job.
- Kanban board and filterable table views; add a job by pasting a URL or text; dashboard stats (applications per week, response rate).

**P1b: Settings: target positions + sender email (requested 2026-10-05)**
- **Target positions**: one or more saved profiles you set up in the UI. Each has a job title and its synonyms (e.g. "QA Lead", "Test Manager"), keywords to include and exclude, locations/remote preference, a salary floor, seniority, and which sources to search. Searches, Claude job hunting, fit scoring, and resume tailoring all run against the selected target position.
- **Email "from" setup**: configurable in the UI. Includes from-address, display name, reply-to, SMTP host/port/user, an optional signature, a BCC-to-self option, and a "send test email" button. The SMTP password stays in `.env`/a secret and is never shown in the UI.

**P2: Resume and ATS**
- A master resume stored as structured YAML/JSON (imported once from your current DOCX/PDF with Claude's help).
- Per job, Claude tailors the summary, reorders bullets, and mirrors the JD's keywords where true. Output is an **ATS-safe DOCX** (single column, standard headings, no tables or graphics; uses python-docx) plus a PDF (LibreOffice headless in the container). Cover letter is generated the same way.
- **ATS match score**: local keyword extraction (skills/tools/certs) from the JD compared against the resume, showing a coverage %, matched/missing lists, and the score before and after tailoring.
- Every generated version is stored and linked to the job, so you always know what was sent.
- **Email application**: compose from a template with the tailored attachments and send via smtp.example.org:587 (your DMS mail server). The job's status is set to `applied` automatically. Always requires a preview and confirmation before sending.

**P3: Search and Claude integration**
- Pluggable source adapters with saved searches (keywords, location, salary floor) on a schedule (daily, using APScheduler in-app).
- Suggested Canadian sources (you'll provide the final list):
  - **Job Bank (jobbank.gc.ca)**: government site, scrape-friendly.
  - **GC Jobs**
  - **Eluta.ca**
  - **CharityVillage**
  - **Indeed.ca / LinkedIn / Glassdoor / Workopolis**: these block scrapers and forbid it in their ToS, so use the next item instead.
  - **Job-alert emails → IMAP ingestion** (recommended): create LinkedIn/Indeed/Glassdoor alerts that go to a dedicated mailbox on your mail server (like the otp@ box), and the app parses the job links out of them. This is reliable, ToS-friendly, and free.
  - Company career pages on **Greenhouse / Lever / Workday / Ashby** via their public JSON endpoints, for target-company watchlists.
  - **ABTEC 5000** (https://technologyalberta.com/abtec-5000/, Technology Alberta's directory of Alberta tech companies), added 2026-10-05 as a company-directory source. The site is behind a Cloudflare bot challenge, so it is never fetched; Feature 3 should let the user import the list (downloaded in a browser) as a company watchlist whose career pages are then checked via the ATS endpoints above.
- **Claude agent search**: a "Find jobs" button and a daily job run `claude -p` with WebSearch/WebFetch, a prompt describing your profile, and `--output-format json` against a strict schema. The results are deduped and inserted as `new`.
- **Claude fit ranking**: each new job gets a 0–100 fit score and a one-line "why" against your master resume, so the board sorts best-first.

**Additional suggestions:** follow-up reminders (Telegram via your existing @example_bot sendMessage, e.g. "applied 7 days ago, no reply"), interview-prep notes generated per job, a company-research blurb, and CSV export.

## Architecture (input for /speckit.plan)
- `~/job-hunter/` git repo (code), deployed at `/opt/docker/job-hunter/` with the same compose pattern as `/opt/docker/analytics/docker-compose.yml`: `python:3.12-slim` image, `webserver_default` external network, `VIRTUAL_HOST=jobs.example.org` + `LETSENCRYPT_HOST`, and `./data:/data` for SQLite + generated files.
- FastAPI + Jinja2 + HTMX (+ SortableJS for the kanban), SQLModel/SQLite, Alembic migrations.
- **Auth**: in-app session login (username + bcrypt hash in `.env`), like the analytics app's in-app auth.
- **Claude in the container**: install Node + `@anthropic-ai/claude-code` in the image; authenticate with a long-lived token from `claude setup-token` passed as `CLAUDE_CODE_OAUTH_TOKEN` in `.env`. This avoids mounting `~/.claude`. Calls run as background jobs with a queue table, timeouts, a concurrency of 1, and `--allowedTools WebSearch,WebFetch`, with no shell or file tools.
- **Backups**: a nightly SQLite `.backup` copied to `/mnt/backup/job-hunter/`, per your backup rule.
- **DNS**: add a `jobs.example.org` A record at the DNS registrar using the same routing as tracker.example.org (verify whether that points at home or at the cloud proxy before choosing), plus an local-DNS rewrite if split-horizon is needed.

## Things I'll need from you during /speckit.clarify
- The list of job sites.
- Your current resume (DOCX/PDF) and target roles/locations.
- Initial target positions and from-address (both editable later in Settings).

## Verification
- `specify check` passes, and `/speckit.*` commands show up in a new session in `~/job-hunter`.
- pytest: dedupe, status transitions, ATS scorer, each source parser (using saved HTML/email fixtures), and DOCX generation (re-parse with python-docx to confirm single-column, standard headings).
- Locally: `docker compose up`, log in, add a job by URL, move it across the kanban, generate a tailored resume and check its score improves, and send a test email to yourself.
- Claude job: run "Find jobs" and confirm it returns schema-valid JSON and inserts deduped rows; confirm a failing or expired token surfaces as an error in the UI.
- Production: `curl -I https://jobs.example.org` returns 200/302 with a valid cert, and an unauthenticated request redirects to the login page.
