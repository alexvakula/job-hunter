# Feature Specification: Claude Integration

**Feature Branch**: `005-claude-integration`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "build feature 5 claude integration" (product brief P3: Claude agent
search, Claude fit ranking; P2: Claude-assisted resume import and tailoring).

## Clarifications

### Session 2026-10-05

- Q: Who may use Claude features? → A: The admin only, on the admin's own Claude subscription token
  (constitution VIII amended to v2.0.2). Updated 2026-10-06 (constitution v2.1.0): every user
  who has their own Claude token (`CLAUDE_CODE_OAUTH_TOKEN_<USERNAME>`); each user's jobs run
  only on their own token.
- Q: Which features? → A: Find jobs (web search), fit ranking, tailoring + cover letter, resume
  import.
- Q: How is the CLI run? → A: Verified against Claude Code 2.1.290: `claude -p` with
  `--output-format json --json-schema <schema>` (result in `structured_output`), built-in tools limited
  with `--tools` (only `WebSearch,WebFetch` for Find jobs, none otherwise), `--strict-mcp-config`,
  `--setting-sources ""`, `--no-session-persistence`, in an empty working directory.
  `--bare` cannot be used because it ignores subscription tokens (`CLAUDE_CODE_OAUTH_TOKEN`).

## User Scenarios & Testing *(mandatory)*

Only the admin sees and uses these features; other family members see none of them. Every Claude
call runs as a background job (constitution VI): the page shows it queued/running/done/failed.

### User Story 1 - Claude job queue and status (Priority: P1)

The admin sees a "Claude" page: whether the token is configured, and every Claude job with its kind,
status, timing, cost reported by the CLI and any error in plain language (e.g. "Claude token missing
or expired — run `claude setup-token` and update .env"). Jobs run one at a time with a time limit.

**Why this priority**: The other stories depend on it, and failures must be visible.

**Independent Test**: With a fake CLI, queue two jobs; confirm they run one after another, a timed-out
job is shown as failed with "took too long", and an authentication failure shows the token message.

**Acceptance Scenarios**:

1. **Given** no token, **Then** Claude buttons are disabled with a hint and nothing is queued.
2. **Given** two queued jobs, **Then** only one runs at a time; results or errors are stored.
3. **Given** a job exceeding its time limit, **Then** the process is stopped and the job fails.
4. **Given** output that does not match the expected structure, **Then** the job fails; no partial
   data is used.

---

### User Story 2 - Find jobs with Claude (Priority: P1)

"Find jobs with Claude" (Job sources and Suggestions pages, and once a day automatically) asks Claude
to search the web for current postings matching the admin's active target positions (titles, places,
remote rules, salary floor, keywords). Claude may only use web search and fetch pages from sites that
allow it; it must not fetch LinkedIn, Indeed or Glassdoor pages. Each returned posting (title,
company, location, link, work mode, salary, short summary) goes through the usual checks (link
normalisation, already tracked/suggested, place rules) and becomes a suggestion marked "Claude".

**Why this priority**: The brief's main Claude use: finding roles the fixed sources miss.

**Independent Test**: With a fake CLI returning 4 postings (one duplicate of a tracked job, one in
Toronto, two valid), confirm 2 new suggestions with origin Claude, and that the CLI was called with
only WebSearch/WebFetch available and LinkedIn/Indeed/Glassdoor fetching denied.

**Acceptance Scenarios**:

1. **Given** active target positions, **When** the admin starts Find jobs, **Then** a job is queued and,
   when done, its new suggestions are listed with a link to them.
2. **Given** a returned posting outside every place rule, or already tracked/suggested, **Then** it is
   not added.

---

### User Story 3 - Fit ranking (Priority: P2)

For new suggestions (after each search run or on "Rank with Claude"), Claude compares each posting with
the admin's master resume and gives a 0–100 fit score and a one-line reason. Suggestions show the fit
score next to the rule-based match score and can be sorted by it.

**Independent Test**: With a fake CLI, rank 3 suggestions; confirm scores and reasons are stored, ids
not sent are ignored, and scores outside 0–100 fail the job.

**Acceptance Scenarios**:

1. **Given** unranked new suggestions and a master resume, **Then** they are ranked in batches of up to
   20 and the list can be sorted by fit.
2. **Given** no master resume, **Then** ranking explains it needs one.

---

### User Story 4 - Claude tailoring and cover letter, still honest (Priority: P2)

On the Apply page, "Tailor with Claude" asks Claude to rephrase the summary and existing bullets to
mirror the posting's wording where it is true, and to draft the cover letter, using only the master
resume. Claude refers to bullets by id; new bullets, employers, titles, dates, degrees or certifications
cannot be introduced (they are not part of the output). The result replaces the tailored draft's
wording, and the honesty check (feature 004) still blocks generation if any term not in the master
appears.

**Independent Test**: With a fake CLI that rewrites two bullets and adds "Kubernetes" to the summary,
confirm the rewrites are applied, an unknown bullet id is ignored, and generation is blocked by the
"Kubernetes" flag.

**Acceptance Scenarios**:

1. **Given** a finished tailoring job, **Then** the summary, referenced bullets and cover letter are
   updated; employers/titles/dates are unchanged.
2. **Given** Claude text with a term absent from the master, **Then** it is flagged and generation is
   refused until fixed.

---

### User Story 5 - Claude resume import (Priority: P3)

On the master resume page, "Import with Claude" sends the text of the uploaded resume to Claude, which
returns the structured master resume. When done, the editor opens pre-filled (not saved) for review.

**Independent Test**: With a fake CLI returning a structured resume, confirm the editor shows it unsaved.

**Acceptance Scenarios**:

1. **Given** a finished import job, **Then** the editor opens with its content and nothing is saved until
   the admin clicks Save.

---

### Edge Cases

- Token expired mid-run: the job fails with the token message; later jobs keep failing until fixed.
- The CLI is missing in the image: jobs fail with "Claude CLI not installed".
- App restarts with a job "running": on start it is marked failed ("interrupted") and the next runs.
- Very long job descriptions/resumes: truncated to fixed limits before sending (description 6,000
  characters, resume 15,000).
- Non-admin users requesting Claude routes: refused (403).

## Requirements *(mandatory)*

- **FR-001**: Claude features MUST be available only to the admin and only when
  `CLAUDE_CODE_OAUTH_TOKEN` is configured; the token MUST never be stored, shown or logged.
- **FR-002**: Every Claude call MUST run as a persisted background job, one at a time globally, with a
  per-kind time limit (Find jobs 10 min, others 3 min) and a turn limit, never inside a web request.
- **FR-003**: Each call MUST use `--output-format json` with a strict JSON Schema; the result MUST be
  re-validated by the app; any mismatch, error result or non-zero exit fails the job.
- **FR-004**: Built-in tools MUST be limited to WebSearch and WebFetch for Find jobs and to none for the
  other kinds; WebFetch MUST be denied for linkedin.com, indeed.com and glassdoor domains; no MCP
  servers, settings, hooks or project files are loaded; runs happen in an empty temporary directory.
- **FR-005**: Job status, timing, reported cost and plain-language errors MUST be visible to the admin.
- **FR-006**: Find jobs results MUST become suggestions (origin "claude") only after link
  normalisation, duplicate checks against tracked jobs and suggestions, and the target positions' place
  rules; nothing becomes a tracked job without "Add".
- **FR-007**: Fit ranking MUST store a 0–100 score and a reason (≤ 200 characters) per suggestion.
- **FR-008**: Tailoring output MUST only reference existing bullet ids; facts are never part of the
  output; the feature 004 honesty check applies unchanged.
- **FR-009**: Import output MUST be shown unsaved in the editor for review.
- **FR-010**: A daily Find jobs + ranking run MUST be queued for the admin after the morning searches
  when Claude is configured (can be turned off with `CLAUDE_DAILY=off`).

### Key Entities

- **Claude job**: kind (find_jobs, fit_rank, tailor, import), owner (admin), status
  (queued/running/done/failed), payload references, result (validated structured output), error,
  created/started/finished, duration, reported cost.
- **Job suggestion** (feature 002/003): gains origin "claude", fit score, fit reason.

## Success Criteria *(mandatory)*

- **SC-001**: 100% of Claude invocations in tests use the schema, the tool limits and the isolation
  flags (verified by inspecting the CLI arguments).
- **SC-002**: A hung CLI process is stopped within its time limit plus 5 seconds.
- **SC-003**: No Claude route or button is reachable by a non-admin (isolation/permission tests).
- **SC-004**: No Claude output can change an employer, title, date, degree or certification in a
  generated document (tests).

## Assumptions

- The admin creates the token with `claude setup-token` (interactive, browser) on their own machine
  and adds it to `/opt/docker/job-hunter/.env`; tokens last about a year.
- The CLI is pinned (2.1.290) and installed in the image with auto-updates and non-essential traffic
  disabled.
