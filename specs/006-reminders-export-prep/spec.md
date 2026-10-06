# Feature Specification: Reminders, CSV Export, Interview Prep

**Feature Branch**: `006-reminders-export-prep` | **Created**: 2026-10-05 | **Status**: Draft

**Input**: "continue implementation" → chosen from the brief's additional suggestions: follow-up
reminders (Telegram), CSV export, interview-prep notes and company-research blurb.

## Clarifications

### Session 2026-10-05

- Q: Which Telegram bot? → A: The family server's existing bot. The app only *sends* messages
  (`sendMessage`); it never reads the bot's updates, so the bot's own service keeps working.
- Q: Who gets reminders? → A: Every user who enters their own Telegram chat id; private to them.
- Q: Are Claude features admin only? → A: Yes (constitution VIII v2.0.2).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily follow-up reminders (Priority: P1)

Each morning a user who set up Telegram gets one message listing their follow-ups due today or
earlier and their applications with no reply for N days (default 7), each with a link to the job.
The dashboard shows the same "no reply yet" list. Users enter their chat id in Settings, can send a
test message, choose N, and turn reminders off.

**Independent Test**: With a fake Telegram API, a user with one due follow-up and one job applied 9
days ago with no later status change or linked email gets exactly one message containing both; a
second run the same day sends nothing; a user without chat id gets nothing.

**Acceptance Scenarios**:
1. **Given** nothing due, **Then** no message is sent.
2. **Given** a reply email linked to the job or a status change after "applied", **Then** it is not
   "no reply".
3. **Given** a Telegram error, **Then** it is recorded and shown in Settings; other users still get
   theirs.

### User Story 2 - CSV export (Priority: P2)

From the jobs table, "Export CSV" downloads the user's jobs matching the current filters with:
title, company, location, work mode, status, source, target position, date found, date applied,
last status change, salary, link, contacts (names and emails), next follow-up, notes count.

**Independent Test**: Export with a status filter; the file has a header and exactly the filtered
jobs; cells starting with `=`, `+`, `-` or `@` are neutralised; another user's jobs never appear.

### User Story 3 - Interview prep and company notes (Priority: P3, admin only)

On a job page, "Prepare with Claude" creates notes: a short company overview (Claude may search the
web, never LinkedIn/Indeed/Glassdoor pages), likely interview questions for this posting, for each a
suggested answer outline built only from the master resume (citing the resume bullets used), and
questions to ask the interviewer. Notes are stored with the job and can be regenerated.

**Independent Test**: With a fake Claude CLI, the notes appear on the job page; story references to
unknown resume bullets are dropped.

## Requirements *(mandatory)*

- **FR-001**: The Telegram bot token MUST come from `TELEGRAM_BOT_TOKEN` in `.env`; never stored,
  shown or logged. Chat ids are per-user settings.
- **FR-002**: Reminders MUST be sent at most once per user per day, after 08:00 app time, only to the
  user's own chat id, only when something is due; the app MUST NOT call `getUpdates` or webhooks.
- **FR-003**: "No reply" = status `applied` reached ≥ N days ago (N 1–60) with no later status change
  and no incoming email linked to the job since.
- **FR-004**: CSV export MUST honour the table filters, include only the user's jobs, be UTF-8 with a
  header, and neutralise formula-like cells.
- **FR-005**: Interview prep MUST run as a Claude background job (feature 005 rules), admin only,
  with WebSearch/WebFetch for the company overview; answer outlines MUST reference existing master
  resume bullets; unknown references are dropped.

## Success Criteria *(mandatory)*

- **SC-001**: No duplicate reminder within a day in tests; no reminder text ever contains another
  user's jobs.
- **SC-002**: A spreadsheet opens the CSV with correct columns and no formula execution.
