# Validation: Apply From the App

**Run**: 2026-10-05. Automated: 378 tests pass (import from DOCX/PDF, ATS extraction/coverage,
tailoring order, honesty flags blocking generation, snapshot facts from master only, DOCX structure
re-parsed: single section/column, Heading 1 = Summary/Experience/Education/Certifications/Skills,
no tables/images/header-footer text, Unicode in DOCX and PDF; versions immutable; email preview
token, tamper → re-preview, confirmation required, status → applied, attachments, cross-user
attachment refused; isolation sweep incl. `/documents/{version_id}/{kind}`); ruff clean.

**Production** (jobs.example.org):

| Step | Result |
|------|--------|
| Migration 0006 on start | PASS |
| Import of sam's real uploaded DOCX (not saved) | PASS: name, email, summary, 7 jobs / 39 bullets, 1 education, 5 certifications, 38 skills detected |
| DOCX + PDF render from that import | PASS (39 KB / 34 KB) |
| Real application email | Not sent (needs a real job, recipient and the user's confirmation, by design) |

The import is best effort; the user reviews every section in the editor before saving.
