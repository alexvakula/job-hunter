# Quickstart & Validation: Job Mailbox & Saved Emails

1. Admin creates mailboxes on the mail server (password generated, stored only in the job-hunter
   `.env` as `SMTP_PASSWORD_<USER>`):
   `docker exec mailserver setup email add sam.jobs@example.org '<generated>'`
2. Settings → Job mailbox: `sam.jobs@example.org`, checking on, filing on. Settings → Sender email:
   from-address `sam.jobs@example.org`.
3. Send an email to sam.jobs@example.org from a personal address → Mail → Check now → it appears once;
   check again → still once (SC-002).
4. Settings → Sender → Send test email → Mail "Sent by Job Hunter" shows it as sent; it is in the
   mailbox's `Sent` folder (SC-003).
5. Add a job with contact = your personal address; reply from it → linked on the job page and filed
   to `Employers/<Company> - <Title>` (SC-005).
6. Forward or create a LinkedIn alert to the job mailbox → Suggestions list its jobs; Add one → normal
   form, duplicate checks; mailbox shows it in `Job Alerts/LinkedIn`.
7. Job sources → cards with setup steps, no password fields; Import from all → result counts.
8. Automated: `uv run pytest` (alert parser fixtures, linking rules, HTML sanitising, dedupe, isolation
   sweep incl. email/attachment/suggestion routes, fake-IMAP check/move flows).
