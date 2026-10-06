# Tasks: Automatic Job Search

- [X] T001 Fixtures `tests/fixtures/search/`: Job Bank Atom feed (Calgary/Vancouver/Ontario mix), Greenhouse list + job detail, Lever list, Ashby board, Workday jobs page
- [X] T002 Migration 0005 + models `WatchCompany`, `SearchRun`, `JobSuggestion` columns, source domain additions; repo owned tables
- [X] T003 [US1] `search/postings.py` matching + scoring; tests `tests/unit/test_matching.py`
- [X] T004 [US1] `search/jobbank.py` feed URLs + Atom parser; tests `tests/unit/test_jobbank.py`
- [X] T005 [US2] `search/boards.py` link parsing + 4 board parsers; tests `tests/unit/test_boards.py`
- [X] T006 Fetcher: POST JSON, per-call max bytes, per-host interval override; tests extend `test_fetch_policy.py`
- [X] T007 [US1/US2/US4] `search/runner.py` run + suggestions + SearchRun; scheduler daily 06:00; tests `tests/integration/test_search_runs.py` (fake fetcher, rate limits, dedupe, dismissed never re-suggested, errors isolated, one run at a time)
- [X] T008 [US2/US3] `routes/watchlist.py` + template; CSV import; tests `tests/integration/test_watchlist.py`
- [X] T009 [US3] `search/discovery.py` background batches; tests `tests/unit/test_discovery.py`
- [X] T010 [US4] Suggestions sort/score/reasons/origin; Sources page automatic cards + background Import from all; tests update
- [X] T011 Isolation sweep (`company_id`), secret scan, lint, full suite, README
- [X] T012 Deploy, run a real Job Bank search for sam's QA Lead position, record validation, merge to main
