# Contract: HTTP routes

Server-rendered HTML. "Partial" = HTMX fragment returned when the request has `HX-Request`.
Auth column: **public**, **user** (any logged-in active user), **admin**.
All POSTs require a valid CSRF token (form field `csrf_token` or header `X-CSRF-Token`);
missing/invalid → 403. Unauthenticated requests to user/admin routes → 303 to
`/login?next=<path>` (HTMX requests get `HX-Redirect`). Owned objects belonging to another
user → 404 (identical to a missing id). Users with `must_change_password` are redirected to
`/account/password` for every user route except logout.

## Auth & account

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/login` | public | Login form |
| POST | `/login` | public | Fields `username`, `password`, `next`. Success → 303 to safe `next` (same-origin path only) or `/`. Failure → 200 with generic error. Throttled → 429 with generic "too many attempts" |
| POST | `/logout` | user | Deletes session → 303 `/login` |
| GET/POST | `/account/password` | user | Change own password (`current`, `new`, `confirm`; ≥ 12 chars) |
| GET | `/health` | public | `200 ok` (no DB details) |

## Jobs

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/` | user | Dashboard (FR-021) |
| GET | `/jobs` | user | Table. Query: `status` (multi), `company`, `source` (id), `work_mode`, `profile` (id), `found_from`, `found_to`, `followup_due` (bool), `q`, `sort` (column), `dir` (`asc`/`desc`), `page` (50 per page). Partial: table body |
| GET | `/board` | user | Kanban. Query: `closed=1` shows closed columns |
| GET | `/jobs/new` | user | Capture form: `url` and/or `text` inputs |
| POST | `/jobs/prefill` | user | Fields `url`, `text`. Returns the editable job form pre-filled (FR-005–FR-007, FR-028a) plus messages: `fetched`, `not_fetched_disallowed`, `fetch_failed`; and duplicate info: `duplicate_url` (link to existing job, save disabled) or `possible_duplicate` (link + "save anyway") |
| POST | `/jobs` | user | Create. Job fields + `confirm_possible_duplicate`. URL duplicate → 409 page linking existing job. Possible duplicate without confirm → 200 form with warning. Success → 303 `/jobs/{id}` |
| GET | `/jobs/{id}` | user | Job page: fields, timeline, notes, contacts, follow-ups |
| GET/POST | `/jobs/{id}/edit` | user | Edit fields (status not editable here); re-runs duplicate checks excluding itself |
| POST | `/jobs/{id}/delete` | user | Requires `confirm=yes` → 303 `/jobs` |
| POST | `/jobs/{id}/status` | user | Fields `status`, optional `effective_at` (local datetime, app TZ). Used by job page and kanban drop. Partial: updated card/timeline. Invalid status → 422 |

## Notes, contacts, follow-ups (all scoped through the job)

| Method | Path | Auth |
|--------|------|------|
| POST | `/jobs/{id}/notes` | user |
| POST | `/jobs/{id}/notes/{note_id}` (edit) · `/jobs/{id}/notes/{note_id}/delete` | user |
| POST | `/jobs/{id}/contacts` · `/jobs/{id}/contacts/{cid}` · `/jobs/{id}/contacts/{cid}/delete` | user |
| POST | `/jobs/{id}/followups` · `/jobs/{id}/followups/{fid}/done` · `/jobs/{id}/followups/{fid}/delete` | user |

Each returns the refreshed section as a partial, or 303 back to `/jobs/{id}` without HTMX.

## Settings (own data)

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/settings` | user | Links to profiles and sender |
| GET | `/settings/profiles` | user | List (archived toggle) |
| GET/POST | `/settings/profiles/new` · `/settings/profiles/{pid}` | user | Create/edit with location rules (dynamic rows via HTMX) |
| POST | `/settings/profiles/{pid}/default` · `/archive` · `/delete` | user | Delete requires `confirm=yes`; tagged jobs get `profile_id = NULL` |
| GET/POST | `/settings/sender` | user | Edit sender settings; shows "password: configured / not configured" only |
| POST | `/settings/sender/test` | user | Sends test email to own from-address (+BCC). Partial: success or plain-language error within ≤ 30 s |

## Resume (own files, US7)

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/settings/resume` | user | List own uploads (name, format, size, uploaded, current) + upload form |
| POST | `/settings/resume` | user | Multipart field `file`. DOCX/PDF verified by content, ≤ 10 MB → stored, made current, 303. Otherwise 422 with message; nothing stored |
| GET | `/settings/resume/{resume_id}/download` | user | Owner only: the file as an attachment with its original name; others 404 |
| POST | `/settings/resume/{resume_id}/current` | user | Make this upload current |
| POST | `/settings/resume/{resume_id}/delete` | user | Requires `confirm=yes`; removes row and file; newest remaining becomes current |

## Admin

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/admin/users` | admin | List: username, display name, role, active, last login (no data counts) |
| GET/POST | `/admin/users/new` | admin | `username`, `display_name`, `temp_password` → role `user`, `must_change_password = true`. No route changes roles; admins are created only by the CLI |
| POST | `/admin/users/{uid}/reset-password` | admin | New temp password; ends that user's sessions |
| POST | `/admin/users/{uid}/disable` · `/enable` | admin | Refused for the last active admin |
| GET | `/admin/sources` | admin | Source list |
| GET/POST | `/admin/sources/new` · `/admin/sources/{sid}` | admin | Name, type, domains, fetch_allowed, enabled. `Manual` cannot be deleted |
| POST | `/admin/sources/{sid}/delete` | admin | Refused if any job references it (disable instead) |

Non-admin on any `/admin/*` → 403.
