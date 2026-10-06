# Feature Specification: More Company Job Boards

**Feature Branch**: `007-more-job-boards`

**Created**: 2026-10-05

**Status**: Implemented

**Input**: User description: "what does it mean 'Unsupported careers link'. Can you scan those
resources and implement their support?"

## Background

The watchlist reads company job boards only through public feeds (constitution V). A careers link
from any other system was refused with "Unsupported careers link". A survey of the 21 watchlist
companies whose board was not found (2026-10-05) showed: Jobvite (2), JazzHR (2), Pinpoint (1),
Rippling (1), Dayforce (1), Greenhouse under an unusual board name (2), and 12 pages that load their
jobs with JavaScript.

## User Story - Watch companies on more job boards (Priority: P1)

The user pastes a careers link (or a link to one job) from Pinpoint, Rippling, JazzHR
(applytojob.com) or Jobvite; the company is added and checked every morning like the others.
Imported companies are also looked up automatically on Pinpoint, Rippling and JazzHR.

**Acceptance Scenarios**:

1. **Given** a link from one of the four systems, **Then** the company is added with that board.
2. **Given** a morning run, **Then** matching postings from those boards become suggestions.
3. **Given** an unsupported link, **Then** the message names every supported system and suggests
   pasting the link of one job page.
4. **Given** companies earlier marked "board not found", **Then** they are looked up again.

## User Story 2 - Big employers (Priority: P1)

"Include big companies like Medtronic, GlobalLogic and others." Large employers mostly use Workday
with hundreds or thousands of open jobs; reading only the newest 200 misses most QA roles. Boards
reporting more than 200 jobs are searched with each target-position title (up to 8 titles, 100
results each) through the same public Workday search the career site uses.

## User Story 3 - Eightfold, Phenom and SuccessFactors (Priority: P1)

"Add support for Phenom, Eightfold and SuccessFactors": the career-site systems of many big
employers (RBC, BMO, Cisco, Manulife, Boston Scientific, ATB, PayPal, Rogers, Scotiabank, Telus).
Eightfold sites are recognised from `<company>.eightfold.ai` links; Phenom and SuccessFactors sites
live on the employer's own domain and are recognised from the pasted page itself.

## Requirements

- **FR-001**: Links MUST be recognised: `<company>.pinpointhq.com`, `ats.rippling.com/<company>`,
  `<company>.applytojob.com`, `jobs.jobvite.com/<company>`.
- **FR-002**: Jobs MUST be read only from public sources allowed by robots.txt:
  `<company>.pinpointhq.com/postings.json`, `api.rippling.com/platform/api/ats/v1/board/<company>/jobs`,
  `app.jazz.co/feeds/export/jobs/<company>` (XML, parsed safely) and the public Jobvite list
  `jobs.jobvite.com/<company>/jobs`.
- **FR-003**: Closed JazzHR jobs are skipped; Rippling's one-entry-per-location is merged into one
  posting; Pinpoint salary is used only when the employer shows it.
- **FR-004**: Automatic lookup MUST try Pinpoint, Rippling and JazzHR (not Jobvite, whose list is a
  full web page) and only the board services, never the company's website.
- **FR-005**: Systems without a public feed (Dayforce, iCIMS, Taleo, SuccessFactors) stay
  unsupported; their jobs are added by link or text.
- **FR-006**: Workday boards with more than 200 jobs MUST be searched per target title; results are
  merged without duplicates.
- **FR-007**: Workday postings shown only as "N Locations" whose title fits a target position MUST
  be looked up once (within the per-run detail budget) to get all places, work mode and
  description; a multi-place posting matches when any one of its places does. Looked-up details are
  cached for 30 days (shared, public data only), so each job costs one request; up to 100 per run.

## Success Criteria

- **SC-001**: Parser, link and lookup tests cover all four systems.
- **SC-002**: The 7 watchlist companies identified in the survey are read in production.
- **FR-008**: Eightfold MUST be read through `/api/pcsx/search`, Phenom through its search-results
  page (job data embedded in the page) and SuccessFactors through its `/search/` page; their RSS
  feeds under `/services/` are disallowed by robots.txt and MUST NOT be used. Sites behind a bot
  challenge (SAP) stay unsupported.
- **FR-009**: robots.txt MUST be evaluated per RFC 9309 (longest match wins, Allow wins ties,
  `*` and `$` wildcards), not first match.
- **FR-010**: A pasted link on an unknown domain MAY be fetched once (robots.txt, rate limit and
  network checks apply) to recognise Phenom/SuccessFactors; a recognised site's host is added to
  that source's domains (visible under Admin -> Job sources).
