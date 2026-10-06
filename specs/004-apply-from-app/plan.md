# Implementation Plan: Apply From the App

**Branch**: `004-apply-from-app` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary
Structured master resume per user (imported best-effort from the uploaded DOCX/PDF), local ATS keyword
scoring, rule-based tailoring with an honesty check, ATS-safe DOCX (python-docx) and PDF (fpdf2 with
bundled DejaVu fonts) for resume and cover letter, immutable numbered versions per job, and an
application email with preview bound to an HMAC of the exact content before sending through the
feature 002 outbox; the job moves to "applied".

## Technical Context
Python 3.12 + feature 001–003 stack; new deps python-docx, pypdf (text extraction), fpdf2 (PDF).
Fonts: DejaVu Sans regular/bold bundled in `src/jobhunter/fonts/` (free licence) for Unicode PDFs.
Storage: migration 0006; generated files under `data/uploads/documents/<user>/`.

## Constitution Check (pre/post: PASS)
II honest resumes: facts rendered only from the master; tailoring can only reorder/hide/reword;
FR-008 flags unknown skills/tools/certs and blocks generation · III preview + confirmation bound to
content hash; nothing sent otherwise · IV mail password from env only · VI no Claude · VII tests for
DOCX structure (re-parsed), ATS scorer, honesty check, import parser, send flow, isolation · VIII
per-user data · IX documents under data/uploads (archived nightly).
Deviation from brief: PDF via fpdf2 instead of LibreOffice (image size/simplicity), recorded in spec.

## Structure
```text
src/jobhunter/services/resume/
  model.py      # dataclasses for master/tailored content, (de)serialisation, validation
  importer.py   # DOCX/PDF text → sections (pure heuristics)
  ats.py        # keyword list + extraction + coverage (pure)
  tailor.py     # draft from master + keywords; visible text; honesty flags (pure)
  render.py     # DOCX + PDF for resume and cover letter
  versions.py   # generate + store versions
  apply_email.py# compose, preview token, send via outbox, status → applied
src/jobhunter/routes/resume.py   # /resume editor, import; /jobs/{id}/apply…; document downloads
src/jobhunter/fonts/DejaVuSans*.ttf
migrations/versions/0006_apply.py
tests/fixtures/resume/ (sample resume DOCX built in tests, QA Lead posting text)
```
