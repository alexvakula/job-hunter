# Job Hunter

A small, self-hosted job-search tracker for one family, running at
**https://jobs.example.org**. Each person has a private account to:

- add jobs by pasting a link or the posting text (details are pre-filled where the site allows it),
- move them through `new → interested → applied → screening → interview → offer → accepted`
  (or `rejected` / `withdrawn` / `ghosted`) on a kanban board, with a full status history,
- keep notes, contacts and follow-up dates per job, and see a dashboard (applications per
  week, response rate, follow-ups due),
- describe target positions (titles, places, work modes, salary floors),
- get a **daily Telegram reminder** (per person) for follow-ups due and applications with no reply,
  export jobs as **CSV**, and (admin, with Claude) generate **interview prep** and company notes,
- keep a structured **master resume** (imported from the uploaded DOCX/PDF) and **apply from the
  app**: per job an ATS keyword match score, a tailored resume (reordered/selected from real
  experience, with an honesty check that blocks anything not in the master resume), an editable
  cover letter, ATS-safe DOCX + PDF versions kept per job, and an application email sent only
  after a preview and explicit confirmation (the job then moves to "applied"),
- connect a **job-only mailbox** (e.g. `sam.jobs@example.org`): every email in it is saved,
  employer emails are linked to their jobs, LinkedIn/Indeed/Glassdoor/Job Bank alert emails become
  suggested jobs, and the mailbox is sorted into `Job Alerts/<site>` and
  `Employers/<Company> - <Title>` folders; every email the app sends is logged,
- see all services on the **Job sources** page and import from all of them at once (no passwords for
  external sites are ever stored),
- get **automatic searches** every morning at 06:00: Job Bank (official feed) for each target
  position, and a **company watchlist** checked through the public job boards of Greenhouse, Lever,
  Ashby, Workday, Pinpoint, Rippling, JazzHR and Jobvite; lists such as ABTEC 5000 can be imported as CSV and their boards are found
  automatically; results are scored 0–100 and sorted best-first in Suggestions,
- keep their original resume (DOCX/PDF), and set up and test their sender email.

One admin manages the family accounts and the shared list of job sources. Nobody, including
the admin, can see another person's jobs or files.

The project follows [spec-kit](https://github.com/github/spec-kit): the rules are in
`.specify/memory/constitution.md`, and this feature's spec, plan and tasks are in
`specs/001-job-tracker-mvp/`.

## Stack

Python 3.12, FastAPI, Jinja2 + HTMX (+ SortableJS for the board), SQLite via SQLModel,
Alembic migrations. One Docker container behind the existing nginx-proxy. No external
services; front-end libraries are vendored in `src/jobhunter/static/vendor/`.

## Develop

```bash
uv sync
export SESSION_SECRET=$(openssl rand -hex 32) DATABASE_PATH=./data/dev.db COOKIE_SECURE=false
uv run alembic upgrade head
uv run jobhunter create-admin sam --display-name "Sam Rivera" --seed-defaults
uv run uvicorn jobhunter.main:app --reload --port 8000
```

Tests and lint (all must pass before deploying):

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest            # includes the per-user isolation sweep and the secret-leak scan
```

## Deploy

Deployment lives in `/opt/docker/job-hunter/` (`docker-compose.yml`, `.env`, `data/`). The
compose file builds from this checkout.

```bash
cd ~/job-hunter && git pull
cd /opt/docker/job-hunter && docker compose up -d --build   # migrations run on start
```

`.env` (mode 600, never committed; see `.env.example`):

| Variable | Meaning |
|----------|---------|
| `SESSION_SECRET` | random, ≥ 32 characters |
| `SMTP_PASSWORD_<USERNAME>` | password of that user's job mailbox (used to send and to read), e.g. `SMTP_PASSWORD_SAM` |
| `MAILBOX_SCHEDULER` | `off` disables the 15-minute background mailbox check (default on) |
| `CLAUDE_CODE_OAUTH_TOKEN` | admin's Claude token from `claude setup-token` (optional) |
| `CLAUDE_DAILY` | `off` disables the daily Claude Find jobs run (default on) |
| `TELEGRAM_BOT_TOKEN` | bot used for daily reminders (only `sendMessage` is called) |
| `APP_TIMEZONE` | default `America/Edmonton` |

## Accounts (run inside the container)

```bash
cd /opt/docker/job-hunter
docker compose exec -it job-hunter jobhunter create-admin sam --display-name "Sam Rivera"
docker compose exec -it job-hunter jobhunter create-user robin --display-name "Robin"
docker compose exec -it job-hunter jobhunter set-password robin
docker compose exec -it job-hunter jobhunter seed-defaults sam   # QA Lead profile + sender
```

Day to day, the admin can also create accounts and reset passwords at **Admin → Family
accounts**; new users choose their own password at first login.

## Claude (admin only)

The admin can use Claude for **Find jobs** (web search), **fit ranking** of suggestions,
**tailoring + cover letter** and **resume import**. Every call is a background job (one at a time,
time-limited, strict JSON schema, only WebSearch/WebFetch for Find jobs, never LinkedIn/Indeed/
Glassdoor pages); the honesty check still applies to anything Claude writes. Setup, once a year:

```bash
claude setup-token                       # on your computer; opens a browser to sign in
nano /opt/docker/job-hunter/.env         # add CLAUDE_CODE_OAUTH_TOKEN=<token>
cd /opt/docker/job-hunter && docker compose up -d
```

`CLAUDE_DAILY=off` in `.env` disables the daily Find jobs run. Status: **Claude** page in the menu.

## Job mailboxes

Create one job-only mailbox per person on the mail server and put its password in `.env`:

```bash
docker exec mailserver setup email add robin.jobs@example.org '<password>'
echo "SMTP_PASSWORD_ROBIN=<password>" >> /opt/docker/job-hunter/.env && docker compose up -d
```

Then the person sets **Settings → Job mailbox** to that address (and **Sender email** to the same).

## Backups

`/opt/docker/job-hunter/backup.sh` runs nightly at 03:30 (cron) and copies a consistent
SQLite backup plus an archive of uploaded files to
`/mnt/backup/job-hunter/` (keeps 30). Log:
`~/logs/job-hunter-backup.log`.

## Not yet included

Ideas welcome. Not searched automatically, by their own rules: LinkedIn,
Indeed, Glassdoor, Eluta (use their alert emails) and ABTEC 5000 (import its list). See
`docs/product-brief.md`.
