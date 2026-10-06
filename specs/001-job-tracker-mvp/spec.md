# Feature Specification: Job Tracker MVP

**Feature Branch**: `001-job-tracker-mvp`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Build the MVP from docs/product-brief.md, sections P1 (job tracker) and P1b (target-position profiles + sender email settings) only. P2 (resume/ATS/email sending) and P3 (search + Claude) will be separate features later, but design the data model so they fit. Use the statuses from the brief, keep a full status-change history, offer kanban and table views, add a job by pasting a URL or text, dedupe jobs, provide a login page, and include a settings page for target positions and the from-email with a \"send test email\" button."

## Clarifications

### Session 2026-10-05

- Q: Which job sites should the app start with in its source list, and which may it fetch pages
  from? → A: Fetch-allowed: Job Bank, GC Jobs, Eluta.ca, CharityVillage, Greenhouse, Lever,
  Ashby, Workday. Store-only (no fetching; paste text, later alert emails): LinkedIn, Indeed,
  Glassdoor, Workopolis. Plus "manual".
- Q: What should the first target-position profile be? → A: "QA Lead" (synonyms: Test Manager,
  QA Manager, Test Lead); locations: Calgary and Vancouver (on-site, hybrid or remote) with a
  salary floor of CAD 130,000/year, and USA (remote only) with a salary floor of USD
  130,000/year. Set as the default profile.
- Q: What sender identity should application emails use, and who uses the app? → A: Sender
  "Sam Rivera <sam@example.org>" (reply-to the same). The app is used by the admin
  (Sam) and the admin's children, about 5 accounts, each with private data; the admin
  creates the accounts; the source list is shared and admin-managed (constitution v2.0.0).
- Q (added 2026-10-05 by the user during implementation): Can I store my original current
  resume? → A: Yes. Each user uploads their own resume (DOCX or PDF), kept privately with
  earlier versions; one is marked current. Tailoring and ATS scoring stay in Feature 2 (User
  Story 7, FR-035–FR-039).

## User Scenarios & Testing *(mandatory)*

The app is used by one family, about 5 accounts. **The admin** (Sam) runs the deployment
and manages accounts and the shared source list. **A user** is anyone with an account,
including the admin when tracking their own job search. Each user sees and changes only their
own jobs, history, notes, contacts, follow-ups, profiles and sender settings.

### User Story 1 - Log in and capture a job (Priority: P1)

The user logs in and adds a job they found by pasting either the posting's URL or the posting's
text. The app pre-fills what it can (title, company, location, work mode, salary, description),
the user reviews and corrects the fields, and saves. The full posting text is kept, because
postings disappear. If the job is already tracked, the app says so instead of creating a second
copy. The new job appears in the job list with status `new`.

**Why this priority**: Capturing jobs reliably in one place is the core value; everything else
builds on a populated, duplicate-free job list behind a login.

**Independent Test**: Log in, paste a posting URL and a block of posting text as two separate
jobs, save both, then paste the first URL again and confirm the app points to the existing job
instead of creating a duplicate.

**Acceptance Scenarios**:

1. **Given** the user is not logged in, **When** they open any page, **Then** they are sent to
   the login page and, after a successful login, returned to the page they asked for.
2. **Given** the user enters wrong credentials, **When** they submit the login form, **Then**
   they see a generic "invalid username or password" message and are not logged in.
3. **Given** the user is logged in, **When** they paste posting text and confirm the reviewed
   fields, **Then** a job is created with status `new`, today's "date found", source "manual",
   and the full pasted text stored as the description.
4. **Given** the user pastes a URL, **When** the app has extracted details, **Then** the user
   sees an editable pre-filled form before anything is saved, and the URL is stored with the
   job.
5. **Given** a job with the same normalized URL already exists, **When** the user tries to add
   it again, **Then** the app shows the existing job and does not create a new one.
6. **Given** a job with the same normalized company and title (but a different or missing URL)
   exists, **When** the user adds the new job, **Then** the app warns "possible duplicate",
   links to the existing job, and lets the user either open the existing one or save anyway.

---

### User Story 2 - Move jobs through the pipeline with full history (Priority: P1)

The user moves each job through the statuses `new → interested → applied → screening →
interview → offer → accepted`, or closes it as `rejected`, `withdrawn` or `ghosted`. They can do
this by dragging a card on a kanban board or by changing the status on the job's page. Every
change is recorded with when it happened, so the job's page shows a complete timeline.

**Why this priority**: Knowing where every application stands is the second half of the core
tracker; without history, response-rate and follow-up decisions are guesswork.

**Independent Test**: Create a job, move it `new → interested → applied → screening` on the
kanban, then set it to `rejected` from the job page; confirm the job page timeline shows all
four changes with timestamps in order.

**Acceptance Scenarios**:

1. **Given** a job in `interested`, **When** the user drags its card to the `applied` column,
   **Then** the status becomes `applied` and a history entry records old status, new status and
   time.
2. **Given** a job in any status, **When** the user picks any other status on the job page,
   **Then** the change is accepted and logged (no transition is forbidden, so mistakes can be
   corrected).
3. **Given** the user applied yesterday but records it today, **When** they change the status,
   **Then** they can set the effective date of the change (defaulting to now), and the history
   and stats use that date.
4. **Given** a status change was made by mistake, **When** the user changes it back, **Then**
   both changes remain in the history (history is append-only).
5. **Given** the kanban board, **When** it loads, **Then** active statuses are shown as
   columns, and the closed statuses (`rejected`, `withdrawn`, `ghosted`) can be shown or hidden.

---

### User Story 3 - Work the list: table, filters, notes, contacts, follow-ups (Priority: P2)

The user views all jobs in a sortable, filterable table (by status, company, source, work mode,
target position, date found, follow-up due, and free-text search). On each job they keep notes,
contacts (recruiter, hiring manager) and follow-up dates. A dashboard shows applications per
week, response rate, and follow-ups that are due.

**Why this priority**: Makes a growing list manageable and turns the history into actionable
numbers, but the tracker is already useful without it.

**Independent Test**: With about 20 jobs in mixed statuses, filter the table to `applied` jobs
from one source, add a note, a contact and a follow-up date to one of them, and confirm the
dashboard lists that follow-up when it is due and shows correct weekly counts.

**Acceptance Scenarios**:

1. **Given** jobs in several statuses, **When** the user filters by status and searches a
   keyword, **Then** only matching jobs are shown, and the filters survive a page reload.
2. **Given** a job, **When** the user adds a note, **Then** the note is shown with its creation
   time, newest first, and can be edited or deleted.
3. **Given** a job, **When** the user adds a contact (name, role, email, phone, profile link,
   notes), **Then** it is listed on the job page.
4. **Given** a follow-up date that is today or earlier and not marked done, **When** the user
   opens the dashboard, **Then** the job is listed under "follow-ups due".
5. **Given** jobs that entered `applied` in various weeks, **When** the user opens the
   dashboard, **Then** it shows the number of applications per week for at least the last 12
   weeks and the response rate.

---

### User Story 4 - Define target-position profiles (Priority: P2)

In Settings, each user creates their own target-position profiles, e.g. "QA Lead". Each has a
job title and synonyms ("Test Manager", "QA Manager"), keywords to include and exclude,
one or more location rules (a place, the work modes accepted there, and a salary floor in that
place's currency), seniority, and the sources it should be searched on. Each user can mark one
of their profiles as their default. A job can be tagged with one of its owner's profiles. Later features (search, Claude job hunting, fit scoring, resume
tailoring) will run against the selected profile.

**Why this priority**: Needed so later features have something to run against, and useful now
for tagging and filtering jobs, but not needed to track jobs.

**Independent Test**: Create two profiles, mark one as default, tag a job with the other, and
filter the job table by that profile.

**Acceptance Scenarios**:

1. **Given** the Settings page, **When** the user creates a profile with a title, synonyms,
   include/exclude keywords, location rules, seniority and sources, **Then** it is saved and
   listed.
2. **Given** a profile without a title, **When** the user saves, **Then** the app rejects it with
   a clear message.
3. **Given** a profile, **When** the user adds the location rules "Calgary: on-site, hybrid,
   remote; CAD 130,000" and "USA: remote only; USD 130,000", **Then** both are saved with their
   own work modes, amount and currency.
4. **Given** two profiles, **When** the user marks one as default, **Then** the other is no
   longer the default, and newly added jobs are pre-tagged with the default profile (editable).
5. **Given** a profile that jobs are tagged with, **When** the user deletes it, **Then** the app
   asks for confirmation and the jobs keep existing with no profile (or the user archives the
   profile instead).

---

### User Story 5 - Configure the sender email and send a test (Priority: P3)

In Settings, each user sets up how their application emails will be sent later, from their
own mailbox: from-address, display name, reply-to, mail server host, port and username, an
optional signature, and a "BCC myself" option. The mail password is never entered or shown in
the app; the admin puts it in the deployment configuration under the user's username, and the
page only says whether it is configured. A "send test email" button sends a short test message to the user's own from-address
and reports success or the exact error.

**Why this priority**: Only needed once applications are emailed from the app (a later feature),
but setting it up and proving it works now removes risk from that feature.

**Independent Test**: Fill in the sender settings, click "send test email", and confirm the
message arrives in the user's mailbox with the configured display name, reply-to and signature;
then break the host name and confirm a readable error is shown.

**Acceptance Scenarios**:

1. **Given** the sender settings form, **When** the user saves an invalid email address,
   **Then** the app rejects it with a field-level message.
2. **Given** the mail password is configured outside the app, **When** the user opens the
   settings, **Then** the page shows "password: configured" and never the value; if it is
   missing, it shows "password: not configured" and the test button explains why it cannot
   send.
3. **Given** valid settings, **When** the user clicks "send test email", **Then** a test message
   is sent only to the configured from-address (plus the BCC if enabled) and the result is shown
   within 30 seconds.
4. **Given** the mail server rejects the login or cannot be reached, **When** the test runs,
   **Then** the app shows the server's error in plain language and saves nothing secret.

---

### User Story 6 - Admin manages family accounts (Priority: P2)

The admin creates an account for each child (username, display name, temporary password),
can reset a password, and can disable an account without deleting its data. Each user can
change their own password. Nobody can sign themselves up. The admin cannot open other users'
jobs; their data stays private.

**Why this priority**: Needed before the children can use the app, but the admin can track
their own search before any other account exists.

**Independent Test**: As admin, create account "kid1"; log in as kid1 and add a job; log back
in as admin and confirm the job does not appear anywhere for the admin, and that opening kid1's
job address directly shows "not found"; then disable kid1 and confirm kid1 can no longer log in.

**Acceptance Scenarios**:

1. **Given** the admin is logged in, **When** they create a user with a username, display name
   and temporary password, **Then** the user can log in and is asked to set a new password on
   first login.
2. **Given** a non-admin user, **When** they open any admin page, **Then** access is refused.
3. **Given** two users, **When** user A opens the address of user B's job, note, contact,
   follow-up or profile, **Then** the app responds as if it does not exist.
4. **Given** a disabled account, **When** that user tries to log in or uses an existing session,
   **Then** access is refused, and their data is kept.
5. **Given** the admin, **When** they try to disable their own account while they are the
   only active admin, **Then** the app refuses, so there is always at least one active admin.

---

### User Story 7 - Store my original resume (Priority: P2)

Each user uploads their current resume as a Word (DOCX) or PDF file. It is stored privately on
their account and marked as their current resume. Uploading a newer version keeps the earlier
ones, so the user can download any of them, switch which one is current, or delete old ones.
Later features (resume tailoring, ATS score, sending applications) start from the current
resume.

**Why this priority**: The user asked for it, and Feature 2 needs an original resume to tailor;
storing it now is simple and useful on its own (one place for the latest resume).

**Independent Test**: Upload a DOCX, then a PDF; confirm the PDF is current, both can be
downloaded with their original file names, the DOCX can be made current again, and another
user gets "not found" for both files.

**Acceptance Scenarios**:

1. **Given** the Resume page, **When** the user uploads a DOCX or PDF up to 10 MB, **Then** it
   is stored, listed with its original file name, size and upload time, and marked current.
2. **Given** a file that is not a real DOCX or PDF (wrong content, even if renamed), or larger
   than 10 MB, **When** the user uploads it, **Then** it is rejected with a clear message and
   nothing is stored.
3. **Given** several uploaded versions, **When** the user marks an older one as current,
   **Then** only that one is current.
4. **Given** an uploaded resume, **When** its owner downloads it, **Then** they get the exact
   file with its original name; **When** anyone else requests it, **Then** the app responds as
   if it does not exist.
5. **Given** an uploaded resume, **When** the user deletes it after confirming, **Then** the
   file and its record are removed; if it was current, the newest remaining one becomes current.

---

### Edge Cases

- Pasted URL cannot be fetched (site blocks it, login wall, timeout, page removed): the app
  says so and lets the user paste the posting text or fill the form by hand; the URL is still
  stored.
- Pasted URL belongs to a site not on the fetch allow-list: the app does not fetch it, says
  why, and asks for the posting text (FR-007).
- Pasted text has no recognisable title or company: the form opens with those fields empty and
  the user must fill title and company before saving.
- URLs that differ only in tracking parameters (`utm_*`, `ref`, `trk`, etc.), fragment, case of
  host or trailing slash are treated as the same URL.
- Company names that differ only in case, punctuation or legal suffix ("Acme Inc." vs "ACME")
  are treated as the same company for duplicate checks.
- The same job reposted months later after a rejection: flagged as a possible duplicate; the
  user may save it anyway as a new job.
- A status is "changed" to the status it already has: no history entry is written.
- Very long descriptions (e.g. 50,000 characters) are stored in full and displayed without
  breaking the layout.
- Dashboard with no applied jobs: shows zero counts and "no data yet" instead of a division
  error for the response rate.
- Repeated failed logins: the app slows down or temporarily blocks further attempts.
- Session expires while the user is editing: after logging in again they return to the page
  and see the message "Your session expired; please check and resubmit your changes" (unsaved
  input is not restored).
- Two browser tabs change the same job's status: both changes are recorded in order; the last
  one wins as the current status.
- Two family members track the same posting: each has their own copy; duplicate checks only
  compare against the user's own jobs.
- A user whose mail password is not configured: sender settings can be saved, but "send test
  email" explains that the admin must configure the password first.

## Requirements *(mandatory)*

### Functional Requirements

**Access**

- **FR-001**: The app MUST require login for every page and action except the login page itself.
- **FR-002**: The app MUST support multiple user accounts (about 5) with two roles, admin and
  user. There MUST be no self-sign-up. The first admin account MUST be created by a one-time
  setup step run by the administrator on the server.
- **FR-002a**: The admin MUST be able to create accounts (username, display name, temporary
  password), reset a user's password, and disable or re-enable an account. Disabling MUST end
  that user's sessions and keep their data. The admin MUST NOT be able to disable the last
  active admin. Accounts created in the app are always role "user"; admin accounts are created
  only by the one-time setup step (FR-002), and the app has no role-change action.
- **FR-002b**: Usernames MUST be unique, lower-case letters and digits only (so they can key
  per-user secrets such as `SMTP_PASSWORD_<USERNAME>`). Passwords MUST be at least 12
  characters. A user MUST change a temporary password at first login, and MUST be able to
  change their own password at any time.
- **FR-002c**: Every job, status change, note, contact, follow-up, target-position profile and
  sender setting MUST belong to exactly one user. A user MUST only see and change their own
  records; requests for another user's records MUST behave as "not found". The admin role
  MUST NOT grant access to other users' records.
- **FR-003**: The app MUST refuse further login attempts for a username from an address after
  10 failed attempts within 15 minutes, until that window has passed.
- **FR-004**: Users MUST be able to log out; a login session MUST expire after a period of
  inactivity (default 30 days).

**Capturing jobs**

- **FR-005**: The user MUST be able to add a job by pasting a URL, by pasting posting text, or
  both, and MUST see an editable pre-filled form before the job is saved.
- **FR-006**: The app MUST attempt to pre-fill title, company, location, work mode, salary and
  description from pasted text, and leave any field it cannot determine empty.
- **FR-007**: When a URL is pasted, the app MUST fetch that single page to pre-fill fields only
  if the URL belongs to a source marked "fetch allowed" (see FR-028), including company careers
  pages the admin adds. For any other site (e.g. LinkedIn, Indeed, Glassdoor, Workopolis), the
  app MUST NOT fetch the page; it stores the URL and asks the user to paste the posting text.
- **FR-008**: The app MUST require at least a title and a company to save a job.
- **FR-009**: Each job MUST store: title, company, location, work mode (on-site / hybrid /
  remote / unknown), salary as written plus optional minimum and maximum amounts with a
  currency (CAD or USD) and period (year or hour), URL, source,
  full description text, date found, target-position profile (optional) and current status.
- **FR-010**: The user MUST be able to edit any job field later and to delete a job after
  confirming; deleting removes its notes, contacts, follow-ups and history.

**Duplicates**

- **FR-011**: The app MUST compute a normalized URL (lower-case host, no tracking parameters,
  no fragment, no trailing slash) and a normalized company + title key for every job.
- **FR-012**: The app MUST refuse to create a job whose normalized URL matches one of the same
  user's existing jobs, and MUST show the existing job instead.
- **FR-013**: The app MUST warn when the normalized company + title matches one of the same
  user's existing jobs and let the user open the existing job or save anyway.
- **FR-013a**: Duplicate checks MUST never compare against, or reveal, other users' jobs.
- **FR-014**: Duplicate checks MUST apply to every way a job enters the system, including the
  automated sources added in later features.

**Statuses and history**

- **FR-015**: Each job MUST have exactly one current status from: `new`, `interested`,
  `applied`, `screening`, `interview`, `offer`, `accepted`, `rejected`, `withdrawn`, `ghosted`.
  New jobs start as `new`.
- **FR-016**: The user MUST be able to change a job's status to any other status, from the job
  page and by drag-and-drop on the kanban board.
- **FR-017**: Every status change MUST be recorded in an append-only history with the previous
  status, new status, effective date/time (defaulting to now, editable by the user) and the time
  it was recorded. The effective date/time MUST NOT be more than 1 day in the future. History
  entries MUST NOT be editable or deletable on their own.
- **FR-018**: The job page MUST show the full status history as a timeline in effective-date
  order.

**Views**

- **FR-019**: The app MUST offer a kanban board with one column per active status
  (`new` to `accepted`) and a toggle to show or hide the closed statuses (`rejected`,
  `withdrawn`, `ghosted`).
- **FR-020**: The app MUST offer a table view with sorting by any column and filters for status,
  company, source, work mode, target position, date found range, follow-up due, and free-text
  search over title, company and description; the active filters MUST be kept in the page
  address so they survive reloads and can be bookmarked.
- **FR-021**: The app MUST offer a dashboard showing: applications per week (by the effective
  date the job entered `applied`) for at least the last 12 weeks; response rate; counts per
  status; and follow-ups due today or earlier.
- **FR-022**: Response rate MUST be defined as: jobs that ever reached `applied` and later
  reached `screening`, `interview`, `offer`, `accepted` or `rejected`, divided by all jobs that
  ever reached `applied`.

**Notes, contacts, follow-ups**

- **FR-023**: The user MUST be able to add, edit and delete timestamped notes on a job.
- **FR-024**: The user MUST be able to add, edit and delete contacts on a job (name, role,
  email, phone, profile link, notes).
- **FR-025**: The user MUST be able to add follow-up dates to a job with a short description,
  and mark them done.

**Target-position profiles**

- **FR-026**: Each user MUST be able to create, edit, archive and delete their own
  target-position profiles, each with: name/title (required), synonyms, include keywords, exclude keywords,
  seniority, selected sources, and one or more location rules. Each location rule has: a place
  (city, region or country, e.g. "Calgary, AB" or "USA"), the accepted work modes (any
  combination of on-site / hybrid / remote), and an optional salary floor with currency
  (CAD or USD) per year.
- **FR-026a**: The first admin's account MUST be seeded with one default profile: "QA Lead"; synonyms Test
  Manager, QA Manager, Test Lead; location rules: Calgary, AB (on-site, hybrid, remote;
  CAD 130,000), Vancouver, BC (on-site, hybrid, remote; CAD 130,000), USA (remote only;
  USD 130,000).
- **FR-027**: Each user MAY mark at most one of their profiles as their default; the user's new
  jobs MUST be pre-tagged with it, editable before saving. New users start with no profiles.
- **FR-028**: The list of sources MUST be one list shared by all users and editable only by the
  admin (name, type, site domain(s), enabled flag, "fetch allowed" flag) so later search features can
  attach to it; in this feature, sources are never searched, only used for tagging and for the
  FR-007 fetch decision. A disabled source is hidden from profile and job source pickers and
  is never fetched from, but pasted URLs still match it for source tagging and existing jobs
  keep it. The list MUST always include "manual" and MUST be seeded with:
  - Fetch allowed: Job Bank (jobbank.gc.ca), GC Jobs, Eluta.ca, CharityVillage, Greenhouse,
    Lever, Ashby, Workday.
  - Store only (never fetched): LinkedIn, Indeed, Glassdoor, Workopolis.
- **FR-028a**: When a job is added from a URL, its source MUST be set automatically by matching
  the URL's domain to the source list ("manual" when nothing matches), editable before saving.

**Sender email settings**

- **FR-029**: Each user MUST be able to set and save their own: from-address, display name,
  reply-to, mail server host, port, mail username, signature (optional) and "BCC myself"
  (on/off). New users start with host `smtp.example.org`, port 587 and the rest empty.
- **FR-029a**: The first admin's sender settings MUST be seeded with: from-address and reply-to
  `sam@example.org`, display name "Sam Rivera", host `smtp.example.org`, port 587, mail
  username `sam@example.org`, BCC myself off.
- **FR-030**: The mail password MUST NOT be entered, stored, or shown in the app. It is read
  from the deployment configuration under the user's username (e.g. `SMTP_PASSWORD_SAM`);
  the settings page MUST only show whether it is configured for that user.
- **FR-031**: The "send test email" action MUST send only to the user's own configured
  from-address (and the BCC if enabled), using only that user's settings and password, MUST be triggered only by the user clicking the button, and MUST report
  success or a readable error.
- **FR-032**: The app MUST NOT send any email other than the test email in this feature.

**Data and future fit**

- **FR-033**: The data kept by this feature MUST allow later features to attach, without
  reshaping existing records: generated resume and cover-letter versions per job, sent
  applications per job, saved searches per target profile and source, background job runs,
  and a fit score with a one-line reason per job.
- **FR-034**: No secret (mail passwords, assistant access token, session secret) MUST ever be
  stored in the app's data, shown on any page, or written to logs. Login passwords MUST be
  stored only as one-way hashes, which MUST never be shown or logged.

**Resume files**

- **FR-035**: Each user MUST be able to upload resume files in DOCX or PDF format, at most
  10 MB each; the file type MUST be verified from the file content, not only the name.
- **FR-036**: Uploaded resumes MUST be private to their owner and MUST only be downloadable by
  them, as an attachment with the original file name.
- **FR-037**: Each user MUST have at most one current resume; a new upload becomes current, and
  the user MUST be able to make any earlier upload current.
- **FR-038**: The user MUST be able to delete an uploaded resume after confirming; the stored
  file MUST be removed with it.
- **FR-039**: Uploaded resume files MUST be included in the nightly backup.

### Key Entities

- **User account**: A family member who can log in: username, display name, role (admin or
  user), password hash, must-change-password flag, active flag, created and last-login times.
  Owns all of the per-user records below.
- **Job**: One posting being tracked, owned by one user. Title, company, location, work mode, salary text and
  optional min/max, URL and its normalized form, normalized company+title key, source, full
  description, date found, current status, optional target-position profile, created/updated
  times. Has many status changes, notes, contacts and follow-ups. Later features will add a fit
  score and reason, and link resume versions and sent applications to it.
- **Status change**: One entry in a job's history: previous status (empty for creation), new
  status, effective time, recorded time. Append-only.
- **Note**: Free text attached to a job, with created and updated times.
- **Contact**: A person related to a job: name, role, email, phone, profile link, notes.
- **Follow-up**: A dated reminder for a job: due date, description, done flag. Later features
  will send reminders from these.
- **Target-position profile**: What a user is looking for (owned by that user): name/title, synonyms, include and
  exclude keywords, seniority, selected sources, default flag, archived flag. Has one or more
  location rules. Later: saved searches and resume tailoring refer to it.
- **Location rule**: Part of a profile: place, accepted work modes, optional salary floor with
  currency. Later fit scoring compares a job's location, work mode and salary against these.
- **Source**: Where jobs come from: name, type (manual, job board, applicant tracking system
  (ATS), alert email, company careers page, assistant search), site domain(s), enabled flag, fetch-allowed flag. Shared by
  all users, managed by the admin. Jobs and profiles refer to it.
- **Resume file**: An uploaded resume owned by one user: original file name, format (DOCX or
  PDF), size, content hash, upload time, current flag. The file itself is stored on disk
  outside the database under a random name. Feature 2 will derive the structured master resume
  from the current one.
- **Sender settings**: One record per user with from-address, display name, reply-to, mail host,
  port, username, signature, BCC-myself flag. Never contains the password.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The user can add a job from pasted posting text, review it and save it in under
  60 seconds.
- **SC-002**: 100% of status changes made through any view appear in the job's history with the
  correct order and dates.
- **SC-003**: Re-adding a job whose URL differs only by tracking parameters, fragment, host
  case or trailing slash never creates a second job (verified on a set of at least 20 URL
  variants).
- **SC-004**: With 2,000 jobs stored, the table, kanban and dashboard each load in under 2
  seconds on the home server.
- **SC-005**: No page or action other than login is reachable without a session (verified by
  requesting every route while logged out).
- **SC-006**: No secret value appears in any page, in the app's data, or in the logs (verified
  by searching all of them for the configured secret values).
- **SC-007**: A test email with correct settings reaches the user's inbox within 1 minute; with
  wrong settings, a readable error appears within 30 seconds.
- **SC-008**: The user can find any job by company or title keyword in under 10 seconds.
- **SC-009**: With two users, no page, search, filter, dashboard figure or duplicate warning
  ever shows one user's data to the other (verified by an automated test over every route).
- **SC-010**: The admin can create a working account for a child in under 2 minutes.
- **SC-011**: A user can upload their resume and download it again, byte-for-byte identical,
  in under 30 seconds.

## Assumptions

- One family, about 5 accounts; the admin and the admin's children. Children who want to use
  sender settings have their own example.org mailbox, set up by the admin outside this app.
- Desktop browser is the primary device; pages must stay usable on a phone screen, but the
  kanban drag-and-drop is optimised for desktop.
- Times are shown in one app-wide time zone, America/Edmonton (configurable at deployment).
- Salaries carry their own currency (CAD for Canadian jobs, USD for US jobs); amounts are never
  converted between currencies.
- Any status-to-status change is allowed, because a personal tracker must tolerate corrections;
  the `ghosted` status is set manually in this feature (automatic suggestions come later).
- Pre-filling from pasted text is best-effort; the user always reviews before saving.
- Out of scope for this feature: resume parsing and tailoring, cover-letter generation, ATS
  scoring, sending
  application emails (P2); scheduled source searches, alert-email ingestion, assistant search
  and fit ranking, Telegram reminders (P3); CSV export.
- Mail passwords and other secrets are provided through deployment configuration, per the
  project constitution; login passwords are managed in the app as hashes.
- The seeded profile, sender settings and source list come from the clarification session and
  are editable later in Settings.
