# Feature Specification: Job Mailbox & Saved Emails

**Feature Branch**: `002-job-mailbox-emails`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Save emails in the database, per user and private. (1) A log of every email Job Hunter sends (today the settings test email; later application emails), with from, to, subject, body, time and send result, viewable in the app. (2) Replies from employers/recruiters: read the user's own example.org mailbox over IMAP, save emails that relate to a tracked job (e.g. from a job's contact or company domain, or replies to an email sent from the app), link them to that job and show them on the job page. (3) Job-alert emails (LinkedIn, Indeed, Glassdoor, Job Bank, etc.) arriving in a mailbox: save them, extract the job links, and offer them as new jobs through the existing duplicate checks (this is the IMAP alert-ingestion part of P3 in docs/product-brief.md; no scraping of sites that forbid it). Nothing is ever sent automatically. Builds on feature 001 (job tracker MVP, deployed at jobs.example.org)."

Follow-up input from the user (2026-10-05): "what do you think if we create a separate mail box for jobs" and "we could sort them by folders".

## Clarifications

### Session 2026-10-05

- Q: Should the app read a personal mailbox or a separate one? → A: A separate job-only mailbox per
  person: sam.jobs@example.org, robin.jobs@example.org, casey.jobs@example.org. The app may save
  everything in it; sender settings use the job address.
- Q: Folder layout in the job mailbox? → A: `Job Alerts/<site>`, `Employers/<Company> - <Job title>`,
  `Sent`; everything else stays in the Inbox.
- Q: How are jobs imported from all services, and may the app store passwords for LinkedIn, Indeed,
  etc.? → A: No third-party passwords are ever stored (constitution IV, V). A "Job sources" page lists
  every service with how it connects (alert emails to the job mailbox for LinkedIn/Indeed/Glassdoor/
  Workopolis; paste a link for anything), setup steps and status, and an "Import from all" button.
  Automatic searches of Job Bank/GC Jobs/Eluta and company career-page watchlists follow as feature
  003 and plug into the same page.

## User Scenarios & Testing *(mandatory)*

Users and the admin are as in feature 001: one family, about 5 accounts, each person's data private
to them. This feature adds a **job mailbox** per person: a mail account used only for the job search
(subscribing to job alerts, applying, and receiving replies). Because the mailbox is job-only, the
app may save every email in it. The app never reads anyone's personal mailbox.

### User Story 1 - Connect my job mailbox and see every email in the app (Priority: P1)

The user enters their job mailbox address in Settings (the password is set by the admin on the
server, never in the app). The app then checks the mailbox regularly and when the user clicks
"Check now", and saves every new email: sender, recipients, subject, date, the readable text, and
the attachments. A Mail page lists all saved emails newest first, with search, and opens any one.

**Why this priority**: Saving the emails is the core of the request; linking, alerts and folders
all build on it.

**Independent Test**: Configure a job mailbox, send it two emails from another address, click
"Check now", and confirm both appear on the Mail page with the right subject, sender and body, and
that checking again does not duplicate them.

**Acceptance Scenarios**:

1. **Given** a job mailbox address and its password configured, **When** the user clicks "Check now",
   **Then** new emails are saved and shown within 60 seconds, and a status line shows the last check
   time and how many emails were added.
2. **Given** emails already saved, **When** the mailbox is checked again, **Then** no email is saved
   twice, even if it was moved between folders.
3. **Given** the password is missing or wrong, or the server cannot be reached, **When** a check runs,
   **Then** the Mail page shows a plain-language error with the time it happened, and nothing else
   breaks.
4. **Given** an email with attachments, **When** the user opens it, **Then** they can download each
   attachment (as a file, never displayed inline).
5. **Given** an HTML-only email, **When** the user opens it, **Then** they see a safe readable version
   (no scripts, no remote images loaded automatically).

---

### User Story 2 - Log of every email the app sends (Priority: P1)

Every email Job Hunter sends on the user's behalf (today: the settings test email; later:
application emails from Feature 2) is recorded with from, to, subject, body, time and the result
(sent, or the error). A copy is also put in the job mailbox's Sent folder so the mailbox stays a
complete record.

**Why this priority**: Knowing exactly what was sent, and when, is essential once applications are
emailed; it is cheap to add now.

**Independent Test**: Send a test email from Settings, once with correct and once with wrong
settings; confirm both attempts are listed on the Mail page under "Sent by Job Hunter" with their
result, and that the successful one is in the mailbox's Sent folder.

**Acceptance Scenarios**:

1. **Given** the user sends a test email, **When** it succeeds or fails, **Then** a record is saved
   with the full message and the result text.
2. **Given** a successful send and a configured job mailbox, **Then** a copy appears in its Sent folder.
3. **Given** a send to a job (Feature 2), **Then** the record is linked to that job.

---

### User Story 3 - Employer emails linked to my jobs (Priority: P2)

Emails from employers and recruiters are linked automatically to the job they are about, and shown
on that job's page in a "Emails" section, oldest first, as a conversation. Matching uses, in order:
replies to an email the app sent for that job; the sender being one of the job's contacts; the
sender's email domain matching the job's company or posting domain. The user can link, re-link or
unlink any email by hand.

**Why this priority**: Seeing the whole conversation with an employer next to the job is the main
day-to-day benefit, but it needs User Story 1 first.

**Independent Test**: Add a job with a contact jane@acme.com, send an email from that address to the
job mailbox, check mail, and confirm it shows on the job page; then unlink it and link it to another
job by hand.

**Acceptance Scenarios**:

1. **Given** a job with contact `jane@acme.com`, **When** an email from her arrives, **Then** it is
   linked to that job.
2. **Given** an email whose sender's domain matches the company of exactly one of the user's
   active jobs, **Then** it is linked to that job; if several jobs match, it is left unlinked and
   marked "needs a decision" with the candidates listed.
3. **Given** an unlinked email, **When** the user picks a job, **Then** it is linked; a manual choice
   is never overridden by automatic matching.
4. **Given** emails linked to a job, **When** the job is deleted, **Then** the emails are kept and
   become unlinked.

---

### User Story 4 - Job-alert emails become suggested jobs (Priority: P2)

Alert emails from job sites (LinkedIn, Indeed, Glassdoor, Job Bank, and others the admin adds) are
recognised by their sender. The app extracts each job listed in the alert (title, company, location
and link where present) and shows them as **suggested jobs**. The user clicks "Add" to open the
normal add-a-job form pre-filled (existing duplicate checks apply; pages are downloaded only from
sites that allow it) or "Dismiss". Suggestions already tracked are marked as such.

**Why this priority**: Alerts are the recommended, terms-friendly way to get jobs from LinkedIn,
Indeed and Glassdoor (constitution V); it depends on User Story 1.

**Independent Test**: Put a saved LinkedIn alert and an Indeed alert (test fixtures) into the job
mailbox, check mail, and confirm each listed job appears as a suggestion with title, company and a
link; adding one goes through the normal form and duplicate check; dismissing hides it.

**Acceptance Scenarios**:

1. **Given** an alert email with 5 jobs, **Then** 5 suggestions appear, each with its link, linked
   back to the alert email.
2. **Given** a suggested job whose link matches a job already tracked (after link normalisation),
   **Then** it is shown as "already tracked" with a link to it, and cannot be added again.
3. **Given** the same job in two alerts, **Then** it is suggested once.
4. **Given** the user adds a suggestion, **Then** the new job's source is the alert's site, and the
   suggestion is marked "added".
5. **Given** an email from a job site that is not in a recognised alert format, **Then** it is saved
   like any other email and no suggestions are invented from it.

---

### User Story 5 - Mailbox sorted into folders (Priority: P3)

After saving and classifying an email, the app files it into a folder in the job mailbox, so the
mailbox itself is organised when read in webmail or on a phone: alerts go to `Job Alerts/<site>`
(e.g. `Job Alerts/LinkedIn`), emails linked to a job go to `Employers/<Company> - <Job title>`, copies
of app-sent mail go to `Sent`, and everything else stays in the Inbox. Filing can be turned off per
user.

**Why this priority**: Nice to have on top of the app view; the app works the same without it.

**Independent Test**: With filing on, receive an alert and an employer email linked to a job; confirm
they are moved to the expected folders, and that re-linking the employer email moves it again.

**Acceptance Scenarios**:

1. **Given** filing is on, **When** an alert is saved, **Then** it is moved to its alert folder,
   creating the folder if needed.
2. **Given** the user re-links an email to a different job, **Then** it is moved to that job's folder.
3. **Given** filing is off, **Then** the app never moves or changes anything in the mailbox (it only
   reads, and adds Sent copies).
4. **Given** the user moves an email by hand in webmail, **Then** the app does not move it back.

---

### User Story 6 - Job sources page with "Import from all" (Priority: P2)

A "Job sources" page lists every source the family uses. Each card says how jobs get in from that
service and what the user must do once: for LinkedIn, Indeed, Glassdoor and Workopolis, create job
alerts on that site sent to the user's job mailbox (with a direct link to the site's alert page and
the address to use); for any site, paste a link on the Add-job page; automatic searches (Job Bank,
GC Jobs, Eluta, company career pages) are shown as "coming next" until feature 003 adds them. Each
card shows status: alerts received, jobs suggested and added, and the last time anything arrived. An
"Import from all" button checks the job mailbox now (and, from feature 003, runs the automatic
searches) and reports what was found. The page never asks for a password of any external service.

**Why this priority**: Gives one obvious place to start an import and to see which services are
actually delivering jobs.

**Independent Test**: With a job mailbox containing one LinkedIn alert, open Job sources, confirm the
LinkedIn card explains alert setup with the user's job address, click "Import from all", and confirm
the LinkedIn card then shows 1 alert and its suggested jobs.

**Acceptance Scenarios**:

1. **Given** the page, **Then** every enabled source has a card with its connection method and setup
   steps, and no password field exists anywhere on it.
2. **Given** no job mailbox is set, **Then** alert-based cards say so and link to the mailbox settings.
3. **Given** "Import from all" is clicked, **Then** the mailbox is checked and the page shows the
   number of new emails, alerts and suggestions within 60 seconds.

---

### Edge Cases

- Very large emails or attachments: emails over 25 MB are saved without attachments, and the email
  shows which attachments were skipped.
- Duplicate deliveries (same Message-ID twice) are saved once.
- Emails without a Message-ID are identified by a hash of sender, date, subject and body.
- Malformed or unusual encodings: saved with best-effort decoding; never crash the check.
- The job mailbox is changed to another address: emails already saved stay; checking starts
  fresh on the new mailbox.
- Two users configure the same mailbox address: refused (each mailbox belongs to one user).
- A check is already running when another is requested: the second request waits or is skipped,
  never runs in parallel for the same user.
- Alert emails that list jobs only as tracking/redirect links: links are cleaned to the real job
  link where the redirect format is known; otherwise the redirect link is kept as is.
- The user deletes a saved email in the app: [assumption] it is deleted from the app only; the
  mailbox copy is untouched.
- Spam in the job mailbox: saved like any other email; the user can delete it in the app.

## Requirements *(mandatory)*

### Functional Requirements

**Job mailbox**

- **FR-001**: Each user MUST be able to set one job mailbox address (an account on the family mail
  server) and turn checking on or off. The mailbox password MUST NOT be entered, stored or shown in
  the app; it is read from the deployment configuration under the user's username (constitution IV).
- **FR-002**: A job mailbox address MUST belong to at most one user.
- **FR-003**: When checking is on, the app MUST check each user's job mailbox at least every 15
  minutes and when the user clicks "Check now"; checks for one user MUST never overlap.
- **FR-004**: Each check MUST save every email not yet saved from the Inbox and from the app's own
  folders, and MUST record the time, the number of new emails, and any error.
- **FR-005**: Each saved email MUST keep: sender, recipients (to/cc), reply-to, subject, date,
  Message-ID and thread references, plain-text body, sanitised HTML body (if any), the original raw
  message, attachments (file name, type, size, content), folder, and when it was saved.
- **FR-006**: Emails MUST NOT be saved twice (by Message-ID, else by content hash), including after
  being moved between folders.
- **FR-007**: The Mail page MUST list the user's saved emails newest first with filters (all,
  linked to a job, unlinked, alerts, sent by Job Hunter) and search over sender, subject and body.
- **FR-008**: HTML emails MUST be shown sanitised: no scripts, styles that load content, forms or
  automatic remote images. Attachments MUST only be downloadable, never shown inline.
- **FR-009**: The user MUST be able to delete a saved email in the app; this MUST NOT delete it from
  the mailbox.

**Sent email log**

- **FR-010**: Every email the app sends MUST be saved before sending with its full content and
  updated with the result (sent, or the error message), whether or not a job mailbox is configured.
- **FR-011**: After a successful send, if the user has a job mailbox, a copy MUST be added to its
  Sent folder.
- **FR-012**: The test email from feature 001 MUST be recorded this way; Feature 2's application
  emails MUST use the same mechanism and link the record to the job.

**Linking to jobs**

- **FR-013**: Incoming emails MUST be linked automatically to at most one of the user's jobs using,
  in priority order: (a) replies to an app-sent email linked to a job; (b) sender address equal to a
  contact of exactly one job; (c) sender domain equal to the domain of the company website, contact
  emails or posting link of exactly one active job (not closed). Free-mail domains (gmail.com,
  outlook.com, etc.) and job-site domains never match by domain.
- **FR-014**: When more than one job matches at the same priority, the email MUST stay unlinked and
  show the candidate jobs.
- **FR-015**: The user MUST be able to link, re-link or unlink any email; manual choices MUST never
  be changed automatically.
- **FR-016**: The job page MUST show linked emails as a conversation (oldest first), including
  emails sent by the app for that job.
- **FR-017**: Deleting a job MUST keep its emails, unlinked.

**Job alerts**

- **FR-018**: An email MUST be treated as a job alert when its sender's domain belongs to a source
  marked as an alert sender. Seeded alert senders: LinkedIn, Indeed, Glassdoor, Job Bank, Eluta.ca,
  Workopolis; the admin can add more.
- **FR-019**: For each supported alert format the app MUST extract every listed job's title,
  company, location (if present) and link; unknown formats MUST NOT produce suggestions.
- **FR-020**: Extracted links MUST be cleaned of tracking parameters and known redirect wrappers,
  and compared with the user's tracked jobs and earlier suggestions using the feature 001 link
  normalisation; matches are shown as "already tracked" or not repeated.
- **FR-021**: "Add" on a suggestion MUST open the feature 001 add-a-job form pre-filled with the
  suggestion's details and the alert's site as source; all feature 001 rules (duplicate checks,
  downloading only from allowed sites) apply. "Dismiss" hides the suggestion.
- **FR-022**: Alert parsing MUST NOT request any web page; only the email content is used.

**Folders**

- **FR-023**: When filing is on, the app MUST move classified emails into folders of the job mailbox
  per the agreed layout (US5), creating folders as needed, and MUST move an email again when the
  user re-links it. Emails the user moved by hand MUST NOT be moved back.
- **FR-024**: When filing is off, the app MUST NOT modify the mailbox except adding Sent copies
  (FR-011).

**General**

- **FR-025**: All saved emails, attachments and suggestions MUST be private to their owner
  (feature 001 FR-002c); the admin has no access to them.
- **FR-026**: The app MUST NEVER send an email as a result of reading the mailbox (constitution III).
- **FR-027**: Saved emails and attachments MUST be included in the nightly backup (constitution IX).

**Job sources page**

- **FR-028**: The app MUST show a Job sources page listing every enabled source with its connection
  method (alert emails, paste a link, automatic search), setup instructions and links, and per-user
  status (alerts received, suggestions, jobs added, last activity).
- **FR-029**: An "Import from all" action MUST run a mailbox check for the user immediately and report
  the results; feature 003's automatic searches MUST plug into the same action.
- **FR-030**: The app MUST NOT ask for, store or use passwords or session cookies of external job
  sites (constitution IV, V).

### Key Entities

- **Mailbox settings**: per user: job mailbox address, checking on/off, filing on/off, last check
  time, last result/error, and per-folder progress markers so each check only fetches new mail.
- **Email**: one saved message, owned by a user: direction (received / sent by the app), the fields
  in FR-005, kind (alert, employer, other, sent), linked job (optional), link method (automatic rule
  or manual), match candidates, mailbox folder, send result for sent emails.
- **Attachment**: file name, type, size and stored content, belonging to one email.
- **Job suggestion**: one job extracted from an alert email: title, company, location, link and its
  normalised form, source, state (new, added, dismissed, already tracked), the job it became.
- **Source** (from feature 001): gains an "alert sender" flag and alert sender domains.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of emails delivered to a configured job mailbox appear in the app within 15
  minutes without user action, or within 60 seconds of clicking "Check now".
- **SC-002**: Re-checking the same mailbox 10 times never creates a duplicate saved email.
- **SC-003**: 100% of test emails sent from Settings appear in the sent log with the correct result.
- **SC-004**: For the saved alert fixtures (at least 2 per supported site), at least 95% of listed jobs
  are extracted with title and link, and none are invented.
- **SC-005**: An email from a job's contact is linked to that job automatically in 100% of test cases;
  ambiguous cases are never linked automatically.
- **SC-006**: No user can see, search or download another user's emails or attachments (verified by
  the per-route isolation test).
- **SC-007**: No script runs and no remote image loads when viewing any saved email (verified with
  malicious HTML fixtures).

## Assumptions

- Each person gets a new job-only mailbox on the family mail server: sam.jobs@, robin.jobs@ and
  casey.jobs@example.org, created by the admin on the mail server; the app reads it with the same password it uses to send (one secret per
  user, `SMTP_PASSWORD_<USERNAME>`), and sender settings switch to the job address.
- Mail server: smtp.example.org / imap at the same host, TLS, as already used by webmail.
- Supported alert formats at launch: LinkedIn, Indeed, Glassdoor, Job Bank (others are saved as
  normal emails until a parser is added).
- Retention: saved emails are kept until the user deletes them; attachments up to 25 MB per email.
- Reading mail is a background job in the app, bounded by timeouts; it is not a Claude job.
- Out of scope: sending application emails and replies (Feature 2), Claude-based classification or
  summaries (Feature 3), reading personal mailboxes, notifications (Telegram) for new mail.
