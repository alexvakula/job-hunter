# Validation: Job Mailbox & Saved Emails

**Run**: 2026-10-05. Automated: `uv run pytest` → 284 passed (fake-IMAP flows, alert fixtures,
linking rules, HTML sanitising, isolation sweep incl. email/attachment/suggestion routes,
secret-leak scan); ruff clean.

**Production** (jobs.example.org, real mail server):

| Step | Result |
|------|--------|
| Mailboxes sam.jobs@, robin.jobs@, casey.jobs@example.org created; passwords generated straight into `.env` (600), never displayed | PASS |
| Migration 0003 ran on start | PASS |
| sam: job mailbox + sender switched to sam.jobs@example.org | PASS |
| Real IMAP login and first check ("0 new emails") | PASS |
| Real test email sent via smtp.example.org as sam.jobs@ | PASS |
| Re-check: delivered copy (INBOX) and Sent copy recognised as the logged email, saved once | PASS (doveadm: INBOX 1, Sent 1; DB: 1 email, status sent) |

**Not yet validated with real data**: real LinkedIn/Indeed/Glassdoor/Job Bank alert emails (parsers
built from representative fixtures; first real alerts should be checked and added as fixtures).
