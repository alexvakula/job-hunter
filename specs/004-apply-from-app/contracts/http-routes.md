# Routes (feature 004) — logged-in user, own data only, POST + CSRF

| Method | Path | Behaviour |
|--------|------|-----------|
| GET/POST | `/resume` | Master resume editor (indexed fields, add/remove rows) |
| POST | `/resume/import` | Pre-fill editor from current uploaded resume (not saved) |
| GET | `/jobs/{job_id}/apply` | ATS score, tailored editor, cover letter, versions, compose link |
| POST | `/jobs/{job_id}/apply/tailor` | Save tailored draft (re-runs honesty check) |
| POST | `/jobs/{job_id}/apply/reset` | Rebuild draft from master |
| POST | `/jobs/{job_id}/apply/generate` | 409 if honesty flags; else new version |
| GET | `/documents/{version_id}/{kind}` | kind ∈ resume.docx, resume.pdf, letter.docx, letter.pdf |
| POST | `/jobs/{job_id}/apply/preview` | Validate, render exact email + token |
| POST | `/jobs/{job_id}/apply/send` | Requires `confirm=yes` + valid token for same content; sends |
