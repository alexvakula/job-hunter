# Implementation Plan: Automatic Job Search

**Branch**: `003-automatic-job-search` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary
Daily (06:00) and on-demand searches per user: Job Bank Atom feed per title × Canadian place, and a
per-user company watchlist checked through Greenhouse, Lever, Ashby and Workday public endpoints.
Postings are matched against active target positions by explicit rules, scored 0–100 and stored as
feature 002 suggestions. CSV import (ABTEC 5000) with background board discovery via the board APIs.

## Technical Context
Python 3.12, existing stack; stdlib `xml.etree` (Atom) and `json`; all HTTP through the feature 001
`Fetcher` (allow-list, robots, SSRF guard) extended with POST-JSON and a per-call size limit; search
runs in a background thread started from the existing scheduler loop; SQLite migration 0005.
Constraints: Job Bank ≥ 5 s between requests (its crawl-delay); board APIs ≥ 1 s per host.

## Constitution Check (pre and post design: PASS)
I single container (in-app background work) · III no sending, suggestions need "Add" · IV no secrets
involved · V only allowed sources, robots.txt honoured, official feed/APIs, crawl-delay respected,
Eluta/LinkedIn/Indeed/Glassdoor/ABTEC never searched · VI no Claude · VII tests: feed/ATS parsers on
saved fixtures, matching/scoring, rate limits with fake clock, discovery, isolation sweep · VIII all
new tables per user · IX data in the DB backup.

## Structure
```text
src/jobhunter/services/search/
  postings.py     # Posting dataclass, matching + scoring (pure)
  jobbank.py      # feed URL builder + Atom parser (pure) + search()
  boards.py       # parse_board_link(), Greenhouse/Lever/Ashby/Workday list parsers + fetch
  discovery.py    # slug candidates + background discovery batches
  runner.py       # run_searches(user): per-user lock, SearchRun record, suggestions
src/jobhunter/routes/watchlist.py   # /watchlist (+ add, import CSV, pause, remove)
migrations/versions/0005_automatic_search.py
tests/fixtures/search/  # jobbank feed, greenhouse/lever/ashby/workday JSON
```
