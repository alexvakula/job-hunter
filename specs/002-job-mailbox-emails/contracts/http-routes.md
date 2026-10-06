# Contract: HTTP routes (feature 002)

All routes: logged-in user, own data only (others' ids → 404), POSTs need CSRF.

| Method | Path | Behaviour |
|--------|------|-----------|
| GET | `/mail` | List saved emails. Query: `view` = all/linked/unlinked/alerts/sent, `q`, `page` (50). Shows mailbox status + "Check now" |
| POST | `/mail/check` | Run a check now (waits ≤ 60 s); 303 back with result flash, or HTMX status partial |
| GET | `/mail/{email_id}` | Email view: headers, sanitised HTML (strict CSP) or text, attachments, link controls, alert suggestions |
| GET | `/mail/{email_id}/attachments/{attachment_id}` | Download as attachment, `application/octet-stream`, nosniff |
| POST | `/mail/{email_id}/link` | `job_id` (own job) or empty to unlink → `link_method=manual`; refiles if filing on |
| POST | `/mail/{email_id}/delete` | `confirm=yes`; app copy only (mailbox untouched) |
| GET | `/suggestions` | Suggested jobs from alerts: new first; `state` filter |
| POST | `/suggestions/{suggestion_id}/add` | Opens the feature 001 add-job form pre-filled (no fetch of disallowed sites) |
| POST | `/suggestions/{suggestion_id}/dismiss` | Hide |
| GET | `/sources` | Job sources page (cards, setup steps, status, "Import from all") |
| POST | `/sources/import` | Same as `/mail/check` (+ feature 003 searches later); returns to `/sources` with results |
| GET/POST | `/settings/mailbox` | Job mailbox address, IMAP host/port, checking on/off, filing on/off; password status only |

Job page gains an "Emails" section (linked emails, oldest first). Admin source form gains
"Sends job-alert emails" checkbox.
