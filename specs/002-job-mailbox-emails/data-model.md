# Data Model: Job Mailbox & Saved Emails (migration 0003)

All tables owned by one user; accessed via the owner-scoped repository (feature 001 R5).

### source (feature 001) — new column
| Field | Type | Rules |
|-------|------|-------|
| alert_sender | bool | default false; seeded true for LinkedIn, Indeed, Glassdoor, Job Bank, Eluta.ca, Workopolis |

### mailbox_settings (one per user)
| Field | Type | Rules |
|-------|------|-------|
| user_id | PK FK user_account | |
| address | text, unique | email; one owner per mailbox (FR-002) |
| imap_host / imap_port | text / int | default `smtp.example.org` / 993 |
| checking_enabled, filing_enabled | bool | default true / true |
| last_check_at | datetime | |
| last_result | text | e.g. "3 new emails, 1 alert, 5 suggestions" |
| last_error | text | plain language; cleared on success |

### mailbox_folder_state
`user_id`, `folder` (decoded name), `uidvalidity` int, `last_uid` int — unique (user_id, folder).

### email_message
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| user_id | FK | |
| direction | text | `in` / `out` |
| kind | text | `alert`, `employer`, `other`, `sent` |
| dedupe_key | text | unique per user (R2) |
| message_id, in_reply_to | text | |
| references | JSON list[str] | |
| from_addr, from_name, reply_to | text | |
| to_addrs, cc_addrs | JSON list[str] | |
| subject | text | ≤ 1000 |
| sent_at | datetime | Date header (or send time) |
| body_text | text | |
| body_html | text | sanitised (R3), nullable |
| raw_storage_name | text | `.eml` file under `uploads/emails/<user>/`, nullable for app-sent before send |
| size_bytes | int | |
| folder, folder_uid | text, int | where the app last saw/put it |
| moved_by_user | bool | set when it disappears from the app's folder (R7) |
| job_id | FK job, nullable | SET NULL on job delete |
| link_method | text | `reply`, `contact`, `domain`, `manual`, `none` |
| candidates | JSON list[int] | job ids when ambiguous |
| source_id | FK source, nullable | alert's site |
| send_status, send_error | text | for `out`: `pending`/`sent`/`failed` |
| saved_at | datetime | |

Indexes: (user_id, saved_at), (user_id, job_id), unique (user_id, dedupe_key).

### email_attachment
`id`, `email_id` FK (cascade), `filename` (sanitised ≤ 200), `content_type`, `size_bytes`,
`storage_name` (file under `uploads/emails/<user>/att/`), `skipped` bool (over the 25 MB limit).

### job_suggestion
| Field | Type | Rules |
|-------|------|-------|
| id | int PK | |
| user_id | FK | |
| email_id | FK email_message | SET NULL if email deleted |
| source_id | FK source | |
| title, company, location | text | |
| url, url_norm | text | url_norm unique per user |
| state | text | `new`, `added`, `dismissed`, `tracked` |
| job_id | FK job, nullable | the job it became or matched |
| created_at | datetime | |
