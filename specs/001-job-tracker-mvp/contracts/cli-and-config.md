# Contract: CLI and configuration

## CLI (`jobhunter`, run inside the container)

| Command | Behaviour |
|---------|-----------|
| `jobhunter create-admin <username> --display-name "<name>" [--seed-defaults]` | Prompts twice for a password (≥ 12 chars, no echo). Creates an active admin. Fails if the username exists. `--seed-defaults` adds the QA Lead profile and Sam's sender settings (data-model.md, "Seed for the first admin"). Exit 0 on success, 1 on error. |
| `jobhunter backup <dest-path>` | SQLite online backup of the live DB to `<dest-path>`; prints the path; exit 0. |

Usage: `docker compose exec job-hunter jobhunter create-admin sam --display-name "Sam Rivera" --seed-defaults`

## Environment (`.env`, never committed; `.env.example` committed with placeholders)

| Variable | Required | Meaning |
|----------|----------|---------|
| `SESSION_SECRET` | yes | Random ≥ 32 bytes; used for the pre-login CSRF cookie signature |
| `SMTP_PASSWORD_<USERNAME>` | per user, optional | Mail password for that user (`<USERNAME>` = username upper-cased), e.g. `SMTP_PASSWORD_SAM` |
| `APP_TIMEZONE` | no | Default `America/Edmonton` |
| `DATABASE_PATH` | no | Default `/data/jobhunter.db` |
| `COOKIE_SECURE` | no | Default `true`; `false` only for local http testing |
| `LOG_LEVEL` | no | Default `INFO` |

Reserved for P3 (not read in this feature): `CLAUDE_CODE_OAUTH_TOKEN`.

Rules: no setting above is ever written to the DB, rendered, or logged; the app logs variable
**names** only (e.g. "SMTP_PASSWORD_SAM not set").

## Deployment (`deploy/docker-compose.yml`, copied to `/opt/docker/job-hunter/`)

- service `job-hunter`, `expose: ["8000"]`, `volumes: ["./data:/data"]`, `env_file: .env`
- `VIRTUAL_HOST=jobs.example.org`, `VIRTUAL_PORT=8000`, `LETSENCRYPT_HOST=jobs.example.org`
- network `webserver_default` (external), `restart: unless-stopped`
- healthcheck: `GET /health`

## Backup (`deploy/backup.sh`, host cron, nightly 03:30)

Runs `jobhunter backup /data/backups/jobhunter-YYYYMMDD.db` in the container, archives
`./data/uploads` (uploaded resumes, FR-039) as `uploads-YYYYMMDD.tar.gz`, copies both to
`/mnt/backup/job-hunter/`, keeps the last 30 copies there and the last
3 in `./data/backups`. Exits non-zero (cron mails) if the backup drive is not mounted.
