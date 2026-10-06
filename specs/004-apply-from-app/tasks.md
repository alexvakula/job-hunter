# Tasks: Apply From the App

- [X] T001 Bundle DejaVu fonts; add python-docx, pypdf, fpdf2
- [X] T002 Migration 0006 + models MasterResume, TailoredResume, DocumentVersion; repo owned tables
- [X] T003 [US1] resume/model.py + importer.py; tests test_resume_import.py (DOCX + PDF fixtures built in tests)
- [X] T004 [US2] resume/ats.py; tests test_ats.py
- [X] T005 [US3] resume/tailor.py (ordering, visible text, honesty); tests test_tailor.py
- [X] T006 [US4] resume/render.py DOCX+PDF; tests test_render.py (re-parse: single column, headings, no tables/images, facts match master, Unicode)
- [X] T007 [US4] resume/versions.py; immutable versions
- [X] T008 [US5] resume/apply_email.py + outbox generic send; tests test_apply_email.py (preview token, tamper, confirm, status applied, attachments, missing settings)
- [X] T009 Routes + templates (/resume, /jobs/{id}/apply, downloads, job page button); tests test_apply_pages.py
- [X] T010 Isolation sweep (version_id), secret scan, lint, full suite, README
- [X] T011 Deploy; validate with sam's uploaded resume if present; merge to main
