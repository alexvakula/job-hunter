# Data Model (migration 0006)

### master_resume (one per user)
user_id PK FK, data JSON (FR-001 structure below), source_resume_id FK resume_file SET NULL,
updated_at.

data = {"name","email","phone","location","links":[str],"summary",
        "experience":[{"id","employer","title","location","start","end","bullets":[str]}],
        "education":[{"institution","credential","field","start","end"}],
        "certifications":[{"name","issuer","date"}], "skills":[str]}

### tailored_resume (one per user + job)
id, user_id, job_id FK CASCADE (unique user_id+job_id), summary, experience JSON
[{"id","bullets":[{"text","source_index","hidden"}]}], skills JSON [{"name","hidden"}],
cover_letter text, updated_at.

### document_version (immutable)
id, user_id, job_id FK SET NULL, number (per job, 1..n), created_at, content JSON (rendered
snapshot), ats_master int, ats_tailored int, resume_docx, resume_pdf, letter_docx, letter_pdf
(storage names under uploads/documents/<user>/).
