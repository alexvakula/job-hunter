# Feature Specification: Apply From the App

**Feature Branch**: `004-apply-from-app`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "build feature 2 apply from the app" (product brief P2: master resume,
tailored ATS-safe DOCX/PDF resume and cover letter per job, ATS match score before/after, every
version stored, email the application with preview and confirmation, job set to applied).

## Clarifications

### Session 2026-10-05

- Q: Does this feature use Claude to tailor or import resumes? → A: No. Claude-assisted tailoring and
  import move to the Claude feature (005), which still needs the Claude CLI in the container and the
  subscription decision (constitution VIII). Here tailoring is rule-based (reorder and select real
  content by job keywords) plus the user's own edits, with an honesty check (constitution II).
- Q: How are PDFs produced? → A: Generated directly by the app (pure Python) from the same content as
  the DOCX, instead of LibreOffice in the container (keeps the image small; constitution VIII).

## User Scenarios & Testing *(mandatory)*

Each family member applies with their own resume; everything is private to them (feature 001).

### User Story 1 - My master resume (Priority: P1)

The user builds a structured master resume: contact details, summary, work experience (employer,
title, location, start, end, bullet points), education, certifications and skills. They can start
from their uploaded resume (feature 001 US7): the app reads the DOCX/PDF text and pre-fills the
sections as well as it can, and the user reviews and corrects everything. The master resume is the
single source of truth for facts.

**Why this priority**: Every tailored resume, score and application is built from it.

**Independent Test**: Upload the fixture DOCX resume, choose "Import from my resume", confirm the
contact details, 2 jobs with their bullets, education and skills are pre-filled, correct one field,
save, and reload to see it kept.

**Acceptance Scenarios**:

1. **Given** an uploaded DOCX or PDF resume, **When** the user imports it, **Then** sections are
   pre-filled best-effort and nothing is saved until the user clicks Save.
2. **Given** the editor, **When** the user adds or removes jobs, bullets, schools, certificates or
   skills, **Then** the saved master resume reflects exactly that.
3. **Given** a job entry without employer or title, **Then** saving is refused with a message.

---

### User Story 2 - ATS match score for a job (Priority: P1)

On a job's Apply page the app lists the important keywords of the posting (skills, tools,
certifications, methods) and shows how many appear in the user's resume: a coverage percentage with
matched and missing lists, for the master resume and for the tailored version.

**Why this priority**: Shows at a glance how well the resume fits and what to emphasise.

**Independent Test**: For a fixture QA Lead posting and the fixture master resume, the score lists
"Selenium", "Jira", "test automation" as matched and "Playwright" as missing, with the right
percentage.

**Acceptance Scenarios**:

1. **Given** a job with a description, **Then** its keywords and the coverage % are shown; a job
   without a description says the score needs the posting text.
2. **Given** the tailored resume, **Then** the score is shown before (master) and after (tailored).

---

### User Story 3 - Tailored resume per job, honestly (Priority: P1)

From the Apply page the user creates a tailored resume for the job: the app orders each job's
bullets and the skills by relevance to the posting's keywords (most relevant first) and pre-selects
the summary from the master. The user can hide bullets or skills, reorder them, and edit the
wording of the summary and bullets. Employers, titles, dates, education and certifications always
come from the master resume and cannot be changed here. Any skill, tool or certification mentioned
in the tailored text that is not in the master resume is flagged, and documents cannot be produced
until it is removed or added to the master (because it is true).

**Why this priority**: Tailoring is what raises the match; honesty is non-negotiable
(constitution II).

**Independent Test**: Tailor for the fixture posting, confirm bullets mentioning Selenium/Jira move up,
edit the summary to add "Playwright" (not in master), and confirm generation is blocked with that
term flagged; remove it and generation works.

**Acceptance Scenarios**:

1. **Given** a new tailored resume, **Then** bullets and skills are ordered by keyword relevance and
   nothing from the master is invented or removed (hidden items stay available).
2. **Given** tailored text containing a term that is in the posting's keyword list or the app's
   skills list but not in the master resume, **Then** it is flagged and generation is refused.
3. **Given** the tailored editor, **Then** employer, title, dates, education and certifications are
   shown read-only.

---

### User Story 4 - ATS-safe documents, every version kept (Priority: P1)

The user generates the tailored resume and a cover letter as Word (DOCX) and PDF files. Resumes use
one column, standard section headings, plain text and no tables, images, text boxes or header/footer
content, so applicant-tracking systems can read them. The cover letter starts from a template filled
with the job, company and the user's top matching skills, and is edited by the user. Every
generation is stored as a numbered version linked to the job with its score, and can be downloaded
later, so the user always knows exactly what was sent.

**Why this priority**: These are the files that get attached or uploaded to employers.

**Independent Test**: Generate twice; confirm versions 1 and 2 exist with downloadable DOCX and PDF;
re-open the DOCX and confirm a single column, the standard headings, no tables or images, and that
the employer names and dates match the master.

**Acceptance Scenarios**:

1. **Given** a tailored resume without honesty flags, **When** the user generates, **Then** a new
   version with DOCX and PDF of the resume and the cover letter is stored and listed on the job.
2. **Given** an earlier version, **Then** it stays downloadable unchanged after later edits.

---

### User Story 5 - Email the application, after preview and confirmation (Priority: P2)

The user composes the application email from a template (recipient pre-filled from the job's
contacts, subject "Application: <title> — <name>", body from the cover letter or a short note) and
picks attachments from the job's generated versions. A preview shows the exact email (from, to,
subject, body, attachment names and sizes). Only when the user ticks "I have reviewed this email"
and clicks "Send" is it sent from their job mailbox. The email is logged and linked to the job
(feature 002), a copy goes to Sent, and the job moves to "applied" with a history entry.

**Why this priority**: Completes the flow; many applications are made on employer sites instead, so
documents (US4) come first.

**Independent Test**: Compose for a job with a contact, preview, try to send without ticking (refused),
change the subject after preview (the preview must be redone), send with the tick (fake mail server),
and confirm the logged email with attachments, job status "applied" and its history entry.

**Acceptance Scenarios**:

1. **Given** a composed email, **When** the user previews, **Then** the preview shows exactly what
   will be sent; **When** anything changes after the preview, **Then** sending is refused until it is
   previewed again.
2. **Given** confirmation, **Then** the email is sent once, logged, linked to the job, and the job's
   status becomes "applied" (unless already further along).
3. **Given** missing sender settings or mailbox password, **Then** the user is told what to set up and
   nothing is sent.

---

### Edge Cases

- Uploaded resume unreadable (scanned PDF without text): import says so; the editor starts empty.
- Very long resumes: no length limit on the master; the generated DOCX/PDF may span pages.
- Non-Latin characters (é, ü, Cyrillic) in names and text render correctly in DOCX and PDF.
- Job without a description: tailoring still works (no reordering), score shows "needs posting text".
- Hidden items never appear in generated documents; reordering never changes facts.
- Editing the master after generating: existing versions keep their content (snapshots).
- Attachment total over 15 MB: refused with a message.
- Sending to an address with a typo: email validation before preview.

## Requirements *(mandatory)*

### Functional Requirements

**Master resume**

- **FR-001**: Each user MUST have one master resume with: name, email, phone, location, links;
  summary; experience entries (employer, title, location, start, end, bullets); education entries
  (institution, credential, field, start, end); certifications (name, issuer, date); skills.
- **FR-002**: The user MUST be able to pre-fill it from their current uploaded resume (DOCX or PDF),
  best effort, reviewed before saving.
- **FR-003**: Experience entries MUST have employer and title; education entries MUST have
  institution.

**ATS score**

- **FR-004**: The app MUST extract keywords from the job description using a maintained list of
  skills, tools, methods and certifications (with common spelling variants) plus all-caps acronyms
  of 2–6 letters that appear at least twice, and compute coverage = matched ÷ total keywords for a
  given resume text, with matched and missing lists.
- **FR-005**: The score MUST be shown for the master resume and for the tailored resume, and stored
  with each generated version.

**Tailoring and honesty**

- **FR-006**: A tailored resume per job MUST start from the master: bullets within each job and the
  skills ordered by the number of job keywords they contain (stable for ties), summary from the master.
- **FR-007**: The user MUST be able to hide/show and reorder bullets and skills and edit the wording of
  the summary and bullets; employers, titles, dates, locations, education and certifications MUST be
  read-only in the tailored resume.
- **FR-008**: The app MUST flag every keyword (FR-004 list + the posting's keywords) present in the
  visible tailored text but absent from the full master resume text, and MUST refuse to generate
  documents while any flag exists (constitution II).

**Documents**

- **FR-009**: Generated resumes MUST be single-column, use the headings Summary, Experience,
  Education, Certifications and Skills (omitting empty ones), plain paragraphs and bullet lists only,
  no tables, images, text boxes, or text in headers/footers, in both DOCX and PDF.
- **FR-010**: The cover letter MUST start from a template filled with today's date, company, job
  title, contact name (or "Hiring Manager"), up to 3 of the user's top matching skills and their name,
  and be editable before generating; the honesty check (FR-008) applies to it too.
- **FR-011**: Each generation MUST create a numbered version per job storing the exact content used,
  the DOCX and PDF of both documents, the ATS scores and the time; versions are never modified.

**Application email**

- **FR-012**: The compose form MUST pre-fill To (job contacts' emails), Subject and Body from
  templates and let the user pick attachments from the job's versions (total ≤ 15 MB).
- **FR-013**: Sending MUST require a preview of the exact message and an explicit confirmation; the
  confirmation MUST be bound to the previewed content so any change requires a new preview
  (constitution III).
- **FR-014**: The sent email MUST be recorded via feature 002's sent log, linked to the job, copied to
  the job mailbox's Sent folder, and the job's status MUST change to "applied" with a history entry
  if its current status is new or interested.
- **FR-015**: All resumes, versions and drafts MUST be private to their owner.

### Key Entities

- **Master resume**: one per user, structured content (FR-001), updated time, the uploaded file it
  was imported from.
- **Tailored resume**: one per user and job: summary text, per-experience bullet order/visibility/
  edited text, skill order/visibility, cover-letter text, updated time.
- **Document version**: per job, numbered: content snapshot, DOCX and PDF of resume and cover letter,
  ATS score before/after, created time.

## Success Criteria *(mandatory)*

- **SC-001**: From a job with a description and an existing master resume, the user can produce a
  tailored resume and cover letter (DOCX + PDF) in under 3 minutes.
- **SC-002**: 100% of generated resumes pass the ATS-structure check (single column, standard
  headings, no tables/images, text extractable) in automated tests.
- **SC-003**: No generated document ever contains an employer, title, date, degree or certification
  that is not in the master resume, and no flagged term (verified by tests).
- **SC-004**: No application email is sent without a matching preview and confirmation (verified by
  tests); each sent application is logged with its attachments and moves the job to "applied".
- **SC-005**: For the fixture posting, the tailored resume's ATS score is higher than or equal to the
  master's.

## Assumptions

- The master resume is entered/imported once and maintained by the user; import is best effort.
- Templates (cover letter, email) are plain text with placeholders; per-user custom templates are out
  of scope (the user edits per job).
- Out of scope: Claude-assisted tailoring/import (feature 005), uploading applications to employer
  websites, follow-up email automation.
