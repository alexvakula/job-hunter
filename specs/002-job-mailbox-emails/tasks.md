---
description: "Task list for 002-job-mailbox-emails"
---

# Tasks: Job Mailbox & Saved Emails

**Input**: `specs/002-job-mailbox-emails/` (plan, spec, research, data-model, contracts, quickstart)

**Tests**: Required (constitution VII: parsers, dedupe; VIII: isolation). Tests first per story.

## Phase 1: Setup

- [X] T001 Add `nh3` to `pyproject.toml` and `uv.lock`
- [X] T002 [P] Create email fixtures in `tests/fixtures/emails/`: LinkedIn, Indeed, Glassdoor, Job Bank alerts (≥ 2 each for LinkedIn/Indeed), a recruiter reply, a reply threaded to an app-sent email, a multipart email with attachments, an HTML-only email with scripts/remote images/forms, a non-alert email from linkedin.com; `expected.json` with the jobs each alert lists

## Phase 2: Foundational

- [X] T003 Add models `MailboxSettings`, `MailboxFolderState`, `EmailMessage`, `EmailAttachment`, `JobSuggestion` and `Source.alert_sender` to `src/jobhunter/models.py` per data-model.md; migration `migrations/versions/0003_job_mailbox.py` seeding `alert_sender`; extend `repo.OWNED_TOP_LEVEL`
- [X] T004 Implement `src/jobhunter/services/mail_store.py`: parse bytes → dataclass, dedupe key (R2), text/HTML extraction, nh3 sanitising (R3), save raw `.eml` + attachments (25 MB limit, sanitised names) under `uploads/emails/<user>/`, delete helper; unit tests `tests/unit/test_mail_store.py` (dedupe, decoding, sanitising, attachment limit)
- [X] T005 Implement `src/jobhunter/services/imap_client.py` (connect/login with timeout, LIST + delimiter, modified UTF-7 names, select, UID search/fetch PEEK, create folder, UID MOVE with fallback, APPEND) and a `FakeImap` for tests in `tests/fake_imap.py`
- [X] T006 Delete-job path in `src/jobhunter/services/jobs.py` unlinks emails and suggestions (FR-017)

## Phase 3: US1 Connect job mailbox, see every email (P1) 🎯

- [X] T007 [P] [US1] Tests `tests/integration/test_mailbox_check.py`: settings save/validation (address unique across users, password status only), check via FakeImap saves all, re-check no duplicates (×10), moved message not duplicated, error states shown, PEEK only, overlap lock
- [X] T008 [P] [US1] Tests `tests/integration/test_mail_pages.py`: list/filters/search/pagination, view sanitised HTML with CSP header, attachment download headers, delete app copy only
- [X] T009 [US1] `src/jobhunter/services/mailbox.py` `check_mailbox(session, user, imap_factory)` + `src/jobhunter/services/scheduler.py` (lifespan loop every 15 min, per-user locks)
- [X] T010 [US1] Routes `src/jobhunter/routes/settings_mailbox.py`, `src/jobhunter/routes/mail.py` and templates `settings/mailbox.html`, `mail/list.html`, `mail/view.html`; nav link "Mail"

## Phase 4: US2 Sent log (P1)

- [X] T011 [P] [US2] Tests `tests/integration/test_sent_log.py`: test email success/failure recorded with result; Sent-folder APPEND on success when mailbox set; works without mailbox
- [X] T012 [US2] Record sends in `src/jobhunter/services/mailer.py` (`record_and_send`), APPEND to Sent via imap_client; update `routes/settings_sender.py`

## Phase 5: US3 Employer emails linked to jobs (P2)

- [X] T013 [P] [US3] Tests `tests/unit/test_mail_link.py` (reply/contact/domain rules, free-mail and job-site exclusion, ties → candidates, manual never overridden) and `tests/integration/test_job_emails.py` (job page conversation, manual link/unlink, delete job keeps emails)
- [X] T014 [US3] `src/jobhunter/services/mail_link.py`; call from mailbox check; `POST /mail/{email_id}/link`; `jobs/_emails.html` on the job page

## Phase 6: US4 Alerts → suggested jobs (P2)

- [X] T015 [P] [US4] Tests `tests/unit/test_alerts.py` (fixtures → expected jobs, ≥ 95 % extracted, no invention, link cleaning, unknown format → none) and `tests/integration/test_suggestions.py` (created on check, dedup across alerts, already-tracked state, Add → prefilled form with source, Dismiss)
- [X] T016 [US4] `src/jobhunter/services/alerts.py`; suggestions creation in mailbox check; routes `src/jobhunter/routes/suggestions.py`; templates; admin source form "Sends job-alert emails"

## Phase 7: US6 Job sources page (P2)

- [X] T017 [P] [US6] Tests `tests/integration/test_sources_page.py`: cards per enabled source, setup text with the user's job address, no password inputs, Import from all runs a check and shows counts
- [X] T018 [US6] `src/jobhunter/routes/sources_page.py` + `templates/sources/index.html`; nav link "Sources"

## Phase 8: US5 Folders (P3)

- [X] T019 [P] [US5] Tests `tests/integration/test_filing.py` (alerts → `Job Alerts/<site>`, linked → `Employers/<Company> - <Title>`, re-link moves, hand-moved never moved back, filing off → no changes)
- [X] T020 [US5] Filing in `src/jobhunter/services/mailbox.py` and on re-link

## Phase 9: Polish & deploy

- [X] T021 Extend isolation sweep (`email_id`, `attachment_id`, `suggestion_id`) and secret-leak scan to new routes
- [X] T022 Lint, full test suite, README update
- [X] T023 Create `sam.jobs@`, `robin.jobs@`, `casey.jobs@example.org` with generated passwords written only to `/opt/docker/job-hunter/.env`; switch sam's sender and mailbox settings to `sam.jobs@example.org`
- [X] T024 Deploy, run quickstart steps 3–7 against production with sam's job mailbox, record in `checklists/validation.md`; merge to main

## Dependencies

Setup → Foundational → US1 → (US2, US3, US4 in any order) → US6 → US5 → Polish. US5 needs US3/US4
classification.
