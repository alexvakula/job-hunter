# Plan: Reminders, CSV Export, Interview Prep

Migration 0008: `notification_settings` (user_id PK, telegram_chat_id, reminders_enabled,
stale_days, last_sent_on, last_error) and `job_prep` (user_id, job_id unique, data JSON,
updated_at). Services: `telegram.py` (sendMessage over httpx, 10 s timeout, token from env,
errors mapped), `reminders.py` (due follow-ups + no-reply jobs, message text, once-a-day send from
the scheduler loop), CSV in `routes/jobs.py` reusing `_filters`/`_filtered_query`, Claude kind
`prep` in `services/claude/tasks.py`. Constitution: III (notifications go only to the user's own
chat), IV (token in env), V/VI (Claude rules unchanged), VII (tests with fake Telegram and fake CLI),
VIII (per-user settings; prep admin only). PASS.
