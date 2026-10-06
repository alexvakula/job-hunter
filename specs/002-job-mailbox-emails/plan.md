# Implementation Plan: Job Mailbox & Saved Emails

**Branch**: `002-job-mailbox-emails` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-job-mailbox-emails/spec.md`

## Summary

Each family member gets a job-only mailbox (`<name>.jobs@example.org`). The app reads it over IMAP
(every 15 minutes and on demand), saves every email privately (text, sanitised HTML, raw `.eml`,
attachments), logs every email it sends and files a copy in `Sent`, links employer emails to jobs
(reply thread → contact → company domain), turns LinkedIn/Indeed/Glassdoor/Job Bank alert emails into
suggested jobs that go through the feature 001 add-job flow, files emails into `Job Alerts/<site>` and
`Employers/<Company> - <Title>` folders, and offers a Job sources page with "Import from all". No
third-party passwords, no scraping, nothing sent automatically.

## Technical Context

**Language/Version**: Python 3.12 (as feature 001)

**Primary Dependencies**: feature 001 stack + stdlib `imaplib`/`email`; **nh3** for HTML sanitising

**Storage**: SQLite (migration 0003); raw `.eml` and attachments as files under `data/uploads/emails/`

**Testing**: pytest; fake IMAP client for check/move/append flows; saved alert/email fixtures

**Target Platform**: existing `job-hunter` container; IMAP to `smtp.example.org:993`

**Project Type**: server-rendered web application (single project)

**Performance Goals**: "Check now" result ≤ 60 s; background check every 15 min

**Constraints**: read with `BODY.PEEK` (never marks read); 30 s IMAP socket timeout; 25 MB
attachment limit per email; one check per user at a time

**Scale/Scope**: ≈5 mailboxes, hundreds to a few thousand emails each

## Constitution Check

| # | Principle | Pre | Post | How |
|---|-----------|-----|------|-----|
| I | Single container | ✅ | ✅ | Runs inside the app (asyncio background task); files on the existing volume |
| II | Honest resumes | n/a | n/a | |
| III | Human in the loop | ✅ | ✅ | Reading never triggers sending; suggestions need "Add"; only the user-clicked test email is sent |
| IV | Secrets in .env | ✅ | ✅ | Mailbox password = `SMTP_PASSWORD_<USER>` from env; no third-party passwords (FR-030) |
| V | Site terms | ✅ | ✅ | Alerts parsed from email only; adding a suggestion uses 001's allow-list fetch rules |
| VI | Claude jobs | n/a | n/a | No Claude calls |
| VII | Tests | ✅ | ✅ | Parsers (alert fixtures), dedupe, linking, sanitising, isolation sweep for new routes |
| VIII | Family use | ✅ | ✅ | All new tables owned per user; admin has no access |
| IX | Backups | ✅ | ✅ | `.eml` + attachments under `data/uploads` (already archived nightly); rows in DB backup |

Result: **PASS**. New dependency **nh3** justified: safe HTML sanitising is security-critical and
bleach is deprecated.

## Project Structure

```text
src/jobhunter/
├── services/mail_store.py      # parse, dedupe, sanitise, save emails/attachments
├── services/mail_link.py       # classification + job linking rules (pure)
├── services/alerts.py          # alert parsers + link cleaning (pure) → suggestions
├── services/imap_client.py     # IMAP wrapper: list/select/fetch/move/append, UTF-7 folder names
├── services/mailbox.py         # check_mailbox(user): orchestrates fetch → store → link → alerts → file
├── services/scheduler.py       # lifespan background loop, per-user locks
├── routes/mail.py              # /mail, /mail/{id}, attachments, link, delete, check
├── routes/suggestions.py       # /suggestions, add, dismiss
├── routes/sources_page.py      # /sources, /sources/import
├── routes/settings_mailbox.py  # /settings/mailbox
└── templates/mail/, suggestions/, sources/, settings/mailbox.html, jobs/_emails.html
migrations/versions/0003_job_mailbox.py
tests/fixtures/emails/          # LinkedIn/Indeed/Glassdoor/Job Bank alerts, replies, malicious HTML
```

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
|----------|------------|--------------------------------------|
| nh3 dependency | Untrusted HTML from strangers must be rendered safely | Regex stripping is unsafe; text-only loses formatting users need |
