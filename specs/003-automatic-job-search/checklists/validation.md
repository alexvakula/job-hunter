# Validation: Automatic Job Search

**Run**: 2026-10-05. Automated: 341 tests pass (matching/scoring rules, Job Bank feed parser,
4 board parsers on real-shape fixtures, rate limits with a fake clock, CSV import + discovery,
search runs end to end with a fake fetcher, isolation sweep incl. watchlist routes); ruff clean.

**Production** (jobs.example.org), sam's QA Lead position:

| Step | Result |
|------|--------|
| Migration 0005 on start | PASS |
| First real run: Job Bank answered **406** to the HTML-only Accept header | FAIL → fixed (Accept now includes Atom/XML and `*/*`), test added |
| Second real run: 8 Job Bank queries, 5 s apart, 36 s total | PASS: 101 unique postings checked, 0 matched |
| Is 0 correct? Direct queries "QA Lead"/Calgary and "Test Manager"/Vancouver | Job Bank returns 0 results for them today; the 101 were unrelated roles → correct |
| Watchlist | Empty for sam (nothing to check yet) |

Notes: Job Bank has few senior QA roles; the watchlist and LinkedIn/Indeed alerts are expected to
provide most suggestions. Board discovery for an ABTEC CSV runs in the background (~1 company every
few seconds).
