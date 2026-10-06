# Routes (feature 003) — logged-in user, own data only, POST + CSRF

| Method | Path | Behaviour |
|--------|------|-----------|
| GET | `/watchlist` | Companies with board, status, last check, discovery progress; add + import forms |
| POST | `/watchlist` | `careers_url`, optional `name` → add company (422 if unsupported link) |
| POST | `/watchlist/import` | multipart `file` CSV → import rows, start discovery |
| POST | `/watchlist/{company_id}/pause` · `/resume` · `/delete` | manage one company |
| POST | `/sources/import` | (changed) starts mailbox check + searches in background; 303 to `/sources` |
| GET | `/sources` | (changed) shows last run per source, running indicator |
| GET | `/suggestions` | (changed) sorted by score; origin and reasons shown |
