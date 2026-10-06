# Data Model (migration 0005)

### watch_company (per user)
id, user_id, name (≤ 200), website, board_type (`greenhouse|lever|ashby|workday|unknown`),
board_id (token/company/name; Workday: tenant), board_host (Workday host), board_site (Workday site),
status (`ok|pending|not_found|error`), paused bool, imported bool, last_checked_at, last_error,
discovery_done bool, created_at. Unique (user_id, lower(name)).

### search_run (per user)
id, user_id, trigger (`daily|user`), started_at, finished_at, status (`running|ok|partial|failed`),
summary JSON `{source: {"seen": n, "matched": n, "suggested": n, "error": str|null}}`.

### job_suggestion (feature 002) — new columns
origin (`alert|jobbank|watchlist`, default `alert`), watch_company_id FK SET NULL, description text,
posted_at datetime, score int nullable, score_reasons JSON list[str], profile_id FK SET NULL.

### source — seeded domain additions
Greenhouse + `boards-api.greenhouse.io`; Lever + `api.lever.co`; Ashby + `api.ashbyhq.com`.
