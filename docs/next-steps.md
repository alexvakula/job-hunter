# Next steps: spec-kit workflow for Job Hunter

Read `docs/product-brief.md` first. Run these one at a time and wait for my review between steps.

## Step 1: /speckit-constitution
Principles:
1. Single Docker container: FastAPI + Jinja2/HTMX + SQLite. No external SaaS and no separate DB server. Deployed behind the existing nginx-proxy at jobs.example.org (compose pattern like /opt/docker/analytics).
2. Honest resumes: Claude may rephrase, reorder and highlight real experience from the master resume, but must NEVER invent skills, employers, dates, degrees or certifications.
3. Human in the loop: nothing is ever emailed or submitted without a preview and an explicit confirmation from me.
4. Secrets (SMTP password, CLAUDE_CODE_OAUTH_TOKEN, login hash) live only in .env. They are never stored in the DB, shown in the UI, or committed.
5. Respect site ToS and robots.txt. Prefer official feeds and job-alert emails over scraping sites that forbid it.
6. Claude CLI calls run as background jobs with timeouts, concurrency 1, strict JSON output schemas, and only the WebSearch/WebFetch tools.
7. Tests are required for parsers, the dedupe logic, status transitions, the ATS scorer and DOCX generation.
8. Keep it simple: one user (me), server-rendered pages, minimal JavaScript.
9. Backups go to /mnt/backup/job-hunter/.

## Step 2: /speckit-specify
Build the MVP from docs/product-brief.md, sections P1 (job tracker) and P1b (target-position profiles + sender email settings) only. P2 (resume/ATS/email sending) and P3 (search + Claude) will be separate features later, but design the data model so they fit. Use the statuses from the brief, keep a full status-change history, offer kanban and table views, add a job by pasting a URL or text, dedupe jobs, provide a login page, and include a settings page for target positions and the from-email with a "send test email" button.

## Step 3: /speckit-clarify
Ask me the questions. I will supply the job-site list, target roles/locations, the from-address and my resume.

## Step 4 onwards
/speckit-plan → /speckit-tasks → /speckit-analyze → /speckit-implement. Stop for my review after each one.

## Later features (separate specify cycles)
- Feature 2: P2, resume + ATS score + DOCX/PDF + sending application email.
- Feature 3: P3, source adapters, IMAP job-alert ingestion, Claude search + fit ranking, Telegram follow-up reminders.
