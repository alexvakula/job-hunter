# Research: Job Mailbox & Saved Emails

## R1. Reading the mailbox
- **Decision**: Python stdlib `imaplib.IMAP4_SSL` to `smtp.example.org:993` (the mail server's
  Let's Encrypt cert covers it; verified reachable from containers), login with the job address and
  `SMTP_PASSWORD_<USERNAME>`, 30 s socket timeout. Per folder, keep `UIDVALIDITY` + last seen UID and
  fetch `UID last+1:*` with `BODY.PEEK[]` (never marks mail as read). Folders read: `INBOX`, the app's
  `Job Alerts/*`, `Employers/*` and `Sent`. First run reads everything (new mailbox → small).
- **Rationale**: no extra dependency; PEEK keeps the user's read state; UID tracking avoids re-reading.
- **Alternatives**: `imapclient` (nicer API, extra dep); fetchmail into a local maildir (more moving parts).

## R2. De-duplication
- **Decision**: per user, unique `dedupe_key` = `Message-ID` (normalised, without `<>`), or
  `sha256(from|date|subject|first 4 KB of body)` when missing. Moving mail between folders therefore
  never creates a second record (FR-006).

## R3. Parsing and safe display
- **Decision**: `email.parser.BytesParser(policy=email.policy.default)`; plain text from the best
  `text/plain` part, else text derived from HTML. HTML is sanitised with **nh3** (Rust *ammonia*
  binding): allow-list of formatting tags, no `img`, `style`, `script`, `iframe`, `form`; links get
  `rel="noopener noreferrer nofollow"` and `target=_blank`. Rendered with a strict CSP on the email
  view (`default-src 'none'; style-src 'self'`). Attachments ≤ 25 MB total per email are stored as
  files; downloads use `Content-Disposition: attachment` and `application/octet-stream`.
- **Raw message** stored as an `.eml` file next to uploads (`uploads/emails/<user>/<uuid>.eml`), so the
  DB stays small and backups (which archive `uploads/`) include it (FR-027).
- **Alternatives**: bleach (deprecated); storing raw in SQLite (bloats DB).

## R4. Classification and linking (pure functions)
- Kind: `alert` if sender domain matches a source with `alert_sender = true`; `sent` for app-sent;
  otherwise `employer` if linked to a job, else `other`.
- Link order (FR-013): (a) `In-Reply-To`/`References` contains the Message-ID of an app-sent email
  linked to a job; (b) sender address equals a contact email of exactly one job; (c) sender's
  registrable domain equals the domain of a contact email or posting URL of exactly one active job;
  free-mail and job-site domains are excluded. Ties → unlinked with `candidates`.

## R5. Alert parsing
- **Decision**: link-pattern based extractors per site over the HTML part (fallback: text part):
  find anchors whose href (after unwrapping known redirect wrappers) matches the site's job-link
  pattern, take the anchor text as title and the following short text blocks as company/location.
  - LinkedIn: `linkedin.com/(comm/)?jobs/view/<id>` → `https://www.linkedin.com/jobs/view/<id>`
  - Indeed: `indeed.com/(rc/clk|pagead/clk|viewjob)…jk=<id>` → `https://<host>/viewjob?jk=<id>`
  - Glassdoor: `glassdoor.(com|ca)/…(jobListingId|jl)=<id>` → `https://www.glassdoor.ca/job-listing/?jl=<id>`
  - Job Bank: `jobbank.gc.ca/jobsearch/jobposting/<id>` → that URL without query
  No web requests (FR-022). Unknown format = no matching links = no suggestions (FR-019).
- **Risk**: alert templates change; mitigated by link-pattern matching and saved fixtures; real
  alerts will be added as fixtures as they arrive.

## R6. Background checking
- **Decision**: an asyncio task started in the app lifespan runs every 15 min, calling the
  synchronous check for each user with checking enabled in a worker thread; a per-user lock prevents
  overlap with "Check now" (one Uvicorn worker, so an in-process lock suffices).
- **Alternatives**: APScheduler (extra dep for one interval job); host cron (needs a CLI per run).

## R7. Folders
- Hierarchy delimiter read from `LIST`; names encoded with IMAP modified UTF-7; folder names are
  cleaned of the delimiter and control characters and limited to 80 chars. Move = `UID MOVE` (RFC
  6851, supported by Dovecot) with COPY+`\Deleted`+EXPUNGE fallback. If the message is no longer in
  the folder where the app last saw it, the user moved it by hand → never move it again (FR-023).

## R8. Sent log
- `mailer.send_test_email` (and Feature 2 sends) create an outgoing `email_message` before sending
  (status `pending`), update to `sent`/`failed` with the result text, and on success `APPEND` the
  exact bytes to the mailbox's `Sent` folder (best effort, 15 s timeout; failure noted, not fatal).
