# Quickstart Validation: Job Tracker MVP

**Run**: 2026-10-05, against a throwaway container built from the release image
(`job-hunter:latest`), its own empty database, on `127.0.0.1:18000`. Script-driven over HTTP.

**Automated suite**: `uv run pytest` → 242 passed (incl. isolation sweep, secret-leak scan,
2,000-job performance test); `ruff check` and `ruff format --check` clean.

| # | Scenario (quickstart §3–4) | Result | Notes |
|---|----------------------------|--------|-------|
| 1 | Logged-out `/jobs` redirects to login | PASS | |
| 2 | Admin login | PASS | |
| 3 | US1 Greenhouse link pre-filled from the live page | PASS | job-boards.greenhouse.io/gitlab/jobs/8860302002, 0.5 s |
| 4 | US1 LinkedIn link not fetched, source LinkedIn | PASS | |
| 5 | US1 pre-fill from pasted text | PASS | company, salary range parsed |
| 6 | US1 job saved | PASS | |
| 7 | US1 same URL with `?utm_source=x#top` blocked (409) | PASS | |
| 8 | US1 "ACME Robotics" + same title → possible duplicate | PASS | |
| 9 | US2 kanban moves + backdated change in timeline | PASS | |
| 10 | US2 board has 7 active columns | PASS | |
| 11 | US3 dashboard: follow-up due + response rate | PASS | First script run expected 100% after back-dating "screening" before "applied"; 0% is correct per FR-022. Re-checked with applied → screening: follow-up shown, 100%. |
| 12 | US3 filtered table (`status=screening&q=acme`) | PASS | |
| 13 | US4 seeded QA Lead profile (Calgary, Vancouver CAD 130k; USA remote USD 130k) | PASS | |
| 14 | US7 resume upload/download byte-identical, attachment | PASS | |
| 15 | US5 sender seeded; password shown only as "configured" | PASS | |
| 16 | US5 test email with unreachable host → readable error ≤ 30 s | PASS | 0.1 s, "address could not be found". (An earlier run hit the real smtp.example.org with a dummy password: "rejected the username or password" after ~8 s; fail2ban showed 0 bans.) |
| 17 | US6 admin creates kid account | PASS | |
| 18 | US6 kid forced to change password at first login | PASS | |
| 19 | US6 kid sees none of sam's jobs; sam's job URL → 404 | PASS | |
| 20 | US6 kid gets 403 on admin pages | PASS | |
| 21 | US6 disabling kid logs them out | PASS | |
| 22 | Security: 11th failed login → 429 | PASS | |

**Not validated here**: a real test email delivered to sam@example.org (needs the real
`SMTP_PASSWORD_SAM` in production `.env`, which only the admin sets).
