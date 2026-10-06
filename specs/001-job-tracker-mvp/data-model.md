# Data Model: Job Tracker MVP

SQLite, all ids are integer primary keys, all timestamps UTC. "Owned" tables carry a non-null
`user_id` and are only accessed through the owner-scoped repository (research R5).
Deleting a job cascades to its status changes, notes, contacts and follow-ups.

## Enumerations

| Name | Values |
|------|--------|
| `Role` | `admin`, `user` |
| `Status` | `new`, `interested`, `applied`, `screening`, `interview`, `offer`, `accepted`, `rejected`, `withdrawn`, `ghosted` |
| `ActiveStatus` (kanban columns) | `new` … `accepted` (first seven) |
| `ClosedStatus` | `rejected`, `withdrawn`, `ghosted` |
| `WorkMode` | `onsite`, `hybrid`, `remote`, `unknown` |
| `Currency` | `CAD`, `USD` |
| `SalaryPeriod` | `year`, `hour` |
| `SourceType` | `manual`, `job_board`, `ats`, `alert_email`, `careers_page`, `assistant` |

## Shared / account tables

### user_account
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| username | text, unique | `^[a-z0-9]{2,32}$` (FR-002b) |
| display_name | text | required, ≤ 80 |
| role | Role | default `user` |
| password_hash | text | bcrypt; never rendered or logged |
| must_change_password | bool | true for admin-created accounts |
| is_active | bool | default true |
| created_at, last_login_at | datetime | |

Invariant: at least one row with `role=admin AND is_active` (FR-002a); enforced in service.

### user_session
| Field | Type | Rules |
|-------|------|-------|
| id | text PK | random 256-bit, URL-safe |
| user_id | FK user_account | cascade delete |
| csrf_token | text | random |
| created_at, last_seen_at | datetime | expires when `now - last_seen_at > 30 days` |

All rows for a user are deleted on disable, password reset and password change (except the
current session on self-change).

### login_attempt
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| username, ip | text | |
| succeeded | bool | |
| at | datetime | rows older than 1 day purged |

### source (shared, admin-managed)
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| name | text, unique | |
| type | SourceType | |
| domains | JSON list[str] | lower-case hosts, e.g. `["jobbank.gc.ca"]`; matched on host or subdomain |
| fetch_allowed | bool | FR-007 |
| enabled | bool | disabled: hidden from pickers, never fetched, still matched for tagging (FR-028) |
| is_system | bool | true for `manual`, which cannot be deleted |

Seeded by migration (FR-028):

| name | type | domains | fetch_allowed |
|------|------|---------|---------------|
| Manual | manual | – | no |
| Job Bank | job_board | jobbank.gc.ca | yes |
| GC Jobs | job_board | emploisfp-psjobs.cfp-psc.gc.ca | yes |
| Eluta.ca | job_board | eluta.ca | yes |
| CharityVillage | job_board | charityvillage.com | yes |
| Greenhouse | ats | boards.greenhouse.io, job-boards.greenhouse.io | yes |
| Lever | ats | jobs.lever.co | yes |
| Ashby | ats | jobs.ashbyhq.com | yes |
| Workday | ats | myworkdayjobs.com | yes |
| LinkedIn | job_board | linkedin.com | no |
| Indeed | job_board | indeed.com, ca.indeed.com | no |
| Glassdoor | job_board | glassdoor.com, glassdoor.ca | no |
| Workopolis | job_board | workopolis.com | no |

## Owned tables

### job
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| user_id | FK user_account | |
| title, company | text | required (FR-008), ≤ 200 |
| location | text | optional |
| work_mode | WorkMode | default `unknown` |
| salary_text | text | as written |
| salary_min, salary_max | int | optional, `min ≤ max` |
| salary_currency | Currency | required if min/max given |
| salary_period | SalaryPeriod | required if min/max given |
| url | text | optional, http(s) only |
| url_norm | text | derived (R6); unique per user when not null |
| company_title_key | text | derived (R6); indexed per user |
| source_id | FK source | default Manual |
| description | text | full text, no length limit |
| date_found | date | default today (app TZ) |
| status | Status | default `new`; changed only via status service |
| profile_id | FK target_profile, nullable | must belong to same user; set null when profile deleted |
| created_at, updated_at | datetime | |

Indexes: `(user_id, status)`, `(user_id, company_title_key)`, unique `(user_id, url_norm)`
where `url_norm IS NOT NULL`, `(user_id, date_found)`.

Future (additive, later migrations, FR-033): `fit_score int NULL`, `fit_reason text NULL`;
child tables `document_version(job_id, …)`, `application_email(job_id, …)` hang off `job.id`.

### status_change (append-only)
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| job_id | FK job | cascade delete with job only |
| from_status | Status, nullable | NULL for creation entry |
| to_status | Status | ≠ `from_status` |
| effective_at | datetime | default now; user-editable at creation of the entry; not in the future by more than 1 day (FR-017) |
| recorded_at | datetime | server time |

No update/delete endpoints exist (FR-017). Timeline ordered by `effective_at, id`.

**State model**: any status → any other status. `new` is the initial state; there is no
terminal lock (corrections allowed). Same-status change is a no-op.

### note
`id`, `job_id` FK, `body` text (required, ≤ 20,000), `created_at`, `updated_at`.

### contact
`id`, `job_id` FK, `name` (required), `role`, `email` (validated if given), `phone`,
`profile_url` (http(s) if given), `notes`.

### follow_up
`id`, `job_id` FK, `due_date` date (required), `description` (≤ 200), `done` bool,
`done_at` datetime. "Due" = `done = false AND due_date ≤ today (app TZ)`.

### target_profile
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| user_id | FK user_account | |
| name | text | required; unique per user |
| synonyms | JSON list[str] | |
| include_keywords, exclude_keywords | JSON list[str] | |
| seniority | text | optional (free text, e.g. "Lead", "Senior") |
| source_ids | JSON list[int] | must reference existing sources |
| is_default | bool | at most one true per user (FR-027) |
| is_archived | bool | archived profiles hidden from pickers, kept on jobs |
| created_at, updated_at | datetime | |

Future: `saved_search(profile_id, source_id, …)` hangs off this table (FR-033).

### location_rule
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| profile_id | FK target_profile | cascade delete |
| place | text | required, e.g. "Calgary, AB", "USA" |
| work_modes | JSON list[WorkMode] | non-empty subset of onsite/hybrid/remote |
| salary_floor | int, nullable | per year |
| salary_currency | Currency, nullable | required if floor given |

A profile must have ≥ 1 location rule.

### resume_file (US7, migration 0002)
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| user_id | FK user_account | cascade delete |
| original_name | text | sanitised base name, ≤ 200 chars, shown and used for downloads |
| storage_name | text, unique | random `<uuid4>.<ext>` under `/data/uploads/resumes/<user_id>/` |
| format | text | `docx` or `pdf`, detected from content (`%PDF-` magic; DOCX = ZIP containing `word/document.xml`) |
| size_bytes | int | 1 … 10,485,760 |
| sha256 | text | content hash (lets Feature 2 detect re-uploads) |
| is_current | bool | at most one true per user (FR-037) |
| uploaded_at | datetime | |

Files are never served inline: downloads use `Content-Disposition: attachment`. Deleting the
row deletes the file. Feature 2: `master_resume(user_id, source_resume_id, data JSON)`.

### sender_settings (one per user)
| Field | Type | Rules |
|-------|------|-------|
| user_id | PK, FK user_account | |
| from_address | text | valid email or empty |
| display_name | text | |
| reply_to | text | valid email or empty |
| smtp_host | text | default `smtp.example.org` |
| smtp_port | int | default 587 |
| smtp_username | text | |
| signature | text | optional |
| bcc_self | bool | default false |

Never contains a password; "password configured" is computed from env
`SMTP_PASSWORD_<USERNAME>` at render time (FR-030).

## Seed for the first admin (`create-admin`, FR-026a, FR-029a)

- `target_profile`: name "QA Lead", synonyms [Test Manager, QA Manager, Test Lead],
  is_default true, sources = all enabled sources; location rules:
  Calgary, AB [onsite, hybrid, remote] 130000 CAD; Vancouver, BC [onsite, hybrid, remote]
  130000 CAD; USA [remote] 130000 USD.
- `sender_settings`: sam@example.org / "Sam Rivera" / reply-to sam@example.org /
  smtp.example.org:587 / username sam@example.org / bcc_self false.

Applied only when the `--seed-defaults` flag is given (so the command stays generic).
