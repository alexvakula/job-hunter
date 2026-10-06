# Feature Specification: Automatic Job Search

**Feature Branch**: `003-automatic-job-search`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "build feature 3 automatic job search" (product brief P3: pluggable
source adapters with saved searches on a schedule; target-company watchlists via public ATS
endpoints; ABTEC 5000 company list noted 2026-10-05).

## Clarifications

### Session 2026-10-05

- Q: Which sources may be searched automatically? → A: Verified 2026-10-05 against each site's
  robots.txt and published interfaces: Job Bank (official Atom search feed; crawl-delay 5 s),
  Greenhouse, Lever and Ashby (public job-board APIs) and Workday career sites (public JSON used
  by the site; robots allow the career site). Not searched: Eluta (robots.txt disallows search and
  RSS), LinkedIn/Indeed/Glassdoor (terms forbid; alerts only, feature 002), GC Jobs (deferred),
  ABTEC 5000 (Cloudflare bot challenge; imported from a file the user downloads).
- Q: Is Claude-powered searching and AI fit ranking part of this feature? → A: No. They become
  feature 004 (they need the Claude CLI in the image and a decision on subscription use for other
  family members, constitution VIII). This feature adds a rule-based match score instead.

## User Scenarios & Testing *(mandatory)*

Users, privacy and the admin role are as in features 001/002. Results of automatic searches are
**suggested jobs** (feature 002): nothing becomes a tracked job until the user clicks "Add".

### User Story 1 - Daily Job Bank search from my target positions (Priority: P1)

Every morning the app searches Job Bank for each of the user's active target positions (title and
other titles) in each Canadian place of that position, keeps postings that really match (title,
place, keywords to skip), and adds them as suggested jobs with a match score. "Import from all" on
the Job sources page runs the same search now.

**Why this priority**: It turns the target positions into a working automatic search with an
official, allowed source.

**Independent Test**: With the QA Lead position (Calgary, Vancouver), run "Import from all" against
saved Job Bank feed fixtures; confirm matching Calgary/Vancouver QA lead postings appear as
suggestions with score, salary text and link, and that an Ontario QA technician posting does not.

**Acceptance Scenarios**:

1. **Given** an active target position that includes Job Bank among its sources, **When** the daily
   search runs, **Then** Job Bank is queried for each title × Canadian place, waiting at least 5 s
   between requests.
2. **Given** a posting whose title matches but whose place is outside the position's places,
   **Then** it is not suggested.
3. **Given** a posting already tracked or already suggested (same normalised link), **Then** it is
   not suggested again.
4. **Given** a posting containing a "skip if it mentions" keyword in its title or summary, **Then**
   it is not suggested.

---

### User Story 2 - Company watchlist (Priority: P1)

The user keeps a list of companies they would like to work for. For each company the app knows its
job board (Greenhouse, Lever, Ashby or Workday), checks it daily, and suggests postings that match
any of the user's active target positions (title, places incl. remote rules, keywords). Companies are
added by pasting their careers-page link (e.g. `https://jobs.lever.co/acme`,
`https://boards.greenhouse.io/acme`, `https://acme.wd3.myworkdayjobs.com/en-US/Careers`).

**Why this priority**: Most tech employers post on these boards; watching them directly finds roles
before they reach the big job sites.

**Independent Test**: Add a Greenhouse and a Lever company using fixture boards; run the search;
confirm only postings matching QA Lead with an allowed place/remote rule are suggested, with their
full description available when adding.

**Acceptance Scenarios**:

1. **Given** a careers link from a supported board, **When** the user adds it, **Then** the company is
   saved with its board type and identifier; an unsupported link is refused with a clear message.
2. **Given** a remote posting located in the United States, **When** the user's position allows
   "USA: remote", **Then** it matches; an on-site US posting does not.
3. **Given** a board that returns an error or no longer exists, **Then** the company shows the error
   and last successful check, and other companies are still checked.
4. **Given** "Add" on a watchlist suggestion, **Then** the add-job form is pre-filled with title,
   company, place, link and the full description.

---

### User Story 3 - Import a company list (e.g. ABTEC 5000) (Priority: P2)

The user uploads a spreadsheet (CSV) of companies, for example the ABTEC 5000 list downloaded in
their browser from Technology Alberta. Each row's company name and website are imported into the
watchlist. In the background the app tries to find each company's public job board on Greenhouse,
Lever and Ashby (by asking those services' public APIs whether a board with the company's name
exists) and shows progress. Companies without a found board stay in the list as "board not found"
so the user can paste the careers link by hand or remove them.

**Why this priority**: Makes the 5,000-company Alberta directory usable without manual work, but the
watchlist already works with hand-added companies.

**Independent Test**: Upload a CSV of 5 companies where 2 have fixture boards; confirm 5 rows are
imported, discovery finds the 2 boards, and the rest are marked "board not found".

**Acceptance Scenarios**:

1. **Given** a CSV with a header row containing a company-name column and optionally a website column,
   **Then** each row becomes a watchlist company; duplicates (same name or website) are skipped.
2. **Given** a file that is not CSV, has no name column, or exceeds 10,000 rows / 5 MB, **Then** it is
   rejected with a clear message and nothing is imported.
3. **Given** discovery is running, **Then** the watchlist shows "N of M checked, K boards found" and
   discovery continues across restarts without re-checking finished companies.
4. **Given** discovery, **Then** the app only contacts the Greenhouse, Lever and Ashby public APIs,
   at most one request per second to each, and never the companies' own websites.

---

### User Story 4 - Match score and search status (Priority: P2)

Each search suggestion gets a 0–100 match score from simple, visible rules (how well the title
matches, whether the place/work mode fits, whether the salary meets the floor when stated) and the
suggestions list sorts best-first. The Job sources page shows, per source, the last search time, how
many postings were found and suggested, and any error; "Import from all" starts the mailbox check and
the searches together and shows the results when they finish.

**Why this priority**: Keeps a growing number of suggestions manageable.

**Independent Test**: Run searches over fixtures; confirm an exact-title Calgary posting with salary
above the floor scores higher than a partial-title one with unknown salary, and that the sources page
shows per-source counts and an injected error.

**Acceptance Scenarios**:

1. **Given** suggestions with scores, **Then** the list is sorted by score, then newest, and each shows
   its score and the reasons ("title match", "Calgary", "salary ≥ CAD 130,000").
2. **Given** a source fails during a run, **Then** the run completes for the other sources and the
   failure is shown on that source's card.
3. **Given** a run is already in progress for the user, **Then** "Import from all" does not start a
   second one and says a run is in progress.

---

### Edge Cases

- A position with no Canadian places: Job Bank is skipped for it (Job Bank is Canada-only).
- A position with no places or titles: nothing is searched for it.
- Archived positions are never searched.
- Job Bank feed returns nationwide results: place filtering is done by the app.
- A board with hundreds of postings: only matching postings are kept; descriptions are fetched only
  for matches where the board does not include them in the list.
- The same posting found by Job Bank and a watched board, or by an alert: suggested once (normalised
  link); later sources do not overwrite an earlier suggestion.
- A suggestion the user dismissed is never re-suggested by later runs.
- Workday boards discovered only by pasted link (not auto-discovered).
- Very large CSV (ABTEC 5000): discovery runs in the background in batches; the app stays responsive.

## Requirements *(mandatory)*

### Functional Requirements

**Searching**

- **FR-001**: The app MUST search, once a day at 06:00 (app time zone) and when the user starts
  "Import from all", for each user with at least one active (not archived) target position.
- **FR-002**: Job Bank MUST be queried through its public search feed for each combination of the
  position's titles (name and other titles, at most 4) and its Canadian places, only if Job Bank is
  among the position's selected sources, waiting at least 5 seconds between requests to Job Bank.
- **FR-003**: Each watchlist company with a known board MUST be checked at most once per run, and
  its postings matched against all of the user's active positions.
- **FR-004**: All requests MUST follow feature 001's fetching rules (allowed sources only, robots.txt,
  identifying user agent, rate limits, size and time limits, no private addresses).
- **FR-005**: A posting MUST be suggested only if it matches a position: (a) its title contains all
  words of the position's name or of one of its other titles (ignoring case and punctuation);
  (b) its place matches one of the position's places, or it is remote and the place rule allows
  remote and the country is compatible; (c) it mentions none of the "skip" keywords; (d) if "must
  mention" keywords exist, at least one appears in the title or description.
- **FR-006**: Suggestions MUST be de-duplicated per user by normalised link against existing
  suggestions (any state) and tracked jobs, across alerts and searches.
- **FR-007**: Each run MUST record start/end time, trigger (daily or user), per-source counts
  (postings seen, matched, suggested) and errors; one run per user at a time.

**Watchlist**

- **FR-008**: Each user MUST be able to add a company by careers link for Greenhouse, Lever, Ashby and
  Workday, edit its name, pause it, or remove it; the watchlist is private to the user.
- **FR-009**: The user MUST be able to upload a CSV (≤ 5 MB, ≤ 10,000 rows) with a company-name column
  (header containing "company" or "name") and an optional website column (header containing
  "website", "url" or "domain"); rows are added as companies without a board, skipping duplicates.
- **FR-010**: Board discovery MUST run in the background, try name- and website-derived identifiers
  against the Greenhouse, Lever and Ashby public board APIs only, at most 1 request/second per
  service, record found/not found per company, and resume after a restart.

**Scoring and display**

- **FR-011**: Each search suggestion MUST have a 0–100 match score: title (exact name/other title
  50, all words present 35), place (matching place 30, remote allowed 30), salary (stated and ≥
  floor 20, not stated 10, below floor 0); the reasons MUST be shown.
- **FR-012**: The suggestions list MUST sort by score (alerts without a score last), then newest, and
  show origin (alert, Job Bank search, watchlist).
- **FR-013**: The Job sources page MUST show Job Bank and the watchlist as automatic sources with last
  run time, counts and errors; "Import from all" MUST start the mailbox check and the searches in the
  background and show their results when finished.

**General**

- **FR-014**: Searching MUST NOT create tracked jobs or send anything; only "Add" creates a job.
- **FR-015**: Postings' descriptions MUST be stored with the suggestion so "Add" pre-fills them.

### Key Entities

- **Watch company**: owned by a user: name, website, board type (greenhouse/lever/ashby/workday/
  unknown), board identifier (and Workday host/site), status (ok, board not found, error, pending
  discovery), last checked, last error, paused, imported flag.
- **Search run**: owned by a user: trigger, started/finished, status, per-source counts and errors.
- **Job suggestion** (feature 002): gains origin (alert/jobbank/watchlist), watch company, description,
  posted date, match score and reasons.

## Success Criteria *(mandatory)*

- **SC-001**: With fixtures, 100% of postings that satisfy FR-005 are suggested and 0 postings outside
  the position's places/titles are suggested.
- **SC-002**: A daily run for one user with 2 positions, 3 places and 50 watched companies finishes in
  under 10 minutes while the app stays responsive.
- **SC-003**: Requests to Job Bank are never closer than 5 s apart; to each board API never closer than
  1 s (verified with a fake clock).
- **SC-004**: Importing a 5,000-row CSV takes under 30 seconds; discovery processes all rows within a
  day without manual action.
- **SC-005**: No search-related page shows another user's watchlist, runs or suggestions (isolation
  sweep).

## Assumptions

- Job Bank's Atom feed (`/jobsearch/feed/jobSearchRSSfeed?searchstring=…&locationstring=…`) stays
  available; its location parameter is loose, so the app filters by place.
- Board APIs: `boards-api.greenhouse.io/v1/boards/<token>/jobs`, `api.lever.co/v0/postings/<company>`,
  `api.ashbyhq.com/posting-api/job-board/<name>`, Workday `…/wday/cxs/<tenant>/<site>/jobs`.
- The ABTEC 5000 list is obtained by the user in a browser and saved as CSV; its exact columns are
  unknown, hence the flexible header detection.
- Out of scope: Claude search and AI fit ranking (feature 004), GC Jobs, Eluta searching,
  notifications.
