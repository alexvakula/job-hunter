# Tasks: Claude Integration

- [X] T001 Constitution v2.0.2 (admin-only decision); jsonschema dependency
- [X] T002 Migration 0007: `claude_job`; `job_suggestion.fit_score`, `fit_reason`; origin "claude"
- [X] T003 [US1] `services/claude/cli.py` (invoke, isolation flags, timeout, envelope + schema validation, readable errors) + `tests/fake_claude.py`; tests `tests/unit/test_claude_cli.py`
- [X] T004 [US1] `services/claude/queue.py` (enqueue, worker loop, one at a time, interrupted-on-start, dispatch by kind) + `/claude` page; tests
- [X] T005 [US2] find_jobs prompt/schema/apply → suggestions; buttons on Sources/Suggestions; tests
- [X] T006 [US3] fit_rank batches → suggestion fit score/reason; sort by fit; tests
- [X] T007 [US4] tailor prompt/schema/apply → TailoredResume; button on Apply page; tests (unknown ids ignored, honesty still blocks)
- [X] T008 [US5] import prompt/schema → editor unsaved; tests
- [X] T009 Admin-only checks (403 + hidden for users); daily run; isolation/secret sweeps; lint; README
- [X] T010 Dockerfile: Node 22 + pinned CLI; deploy; token instructions; validation; merge
