# Outbox: tester

Only `tester` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD tester → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 tester -> coordinator
TYPE: handoff
RE: Q-07 · F-01..F-07 · branch test/Q-07-m19-tests (worktree int-M19)
BODY: Stubs fixed (7 fake backends take schema=/timeout=). Intended-behaviour tests updated: C-1 (test_store, test_shortlist two misses), C-4 (crashed run now `failed`), C-5 (record carries pid_id; new test: reused PID / non-jobscraper legacy record reads failed and is never killed), C-7 (12 h grace in test_scheduler x2, test_pipeline), m16.test.js:278 (block-rendered JD, every line kept, in order). Ported: test_h1 (8 + 1 skipped), test_small_model (33 of 36; env-override tests dropped, R-12), test_small_model_pipeline (5, deadline via budget.decide_deadline_s), test_schedule_rule (4 grace tests; runs_per_cycle half not ported), test_net (6), test_adapters (cloud D-33/P0 cases, 32 total), test_store (+3 H1-1, +1 D-64 fail_running_runs), test_pipeline (+5 H1-1), web h1.test.js, ux1.test.js (Profile wording test dropped; Companies editor tests click "Your list" first). Merged arch/Q-04-designs; test_layering updated per apply_design 2.3 (+3 tests); new tests/test_nf01.py.
DEFECTS:
- TD-01 (low) JobManager.start(): when the program cannot start (OSError) personal only logs a WARNING via _finish; cloud logs `logger.error("job %s (%s) could not start: %s", job_id, kind, reason)` before raising. Repro: JobManager(tmp, lambda k,o: [missing_exe]).start("run", {}) and capture logger jobscraper.web.jobs. Expected: an ERROR record naming the job. Actual: WARNING only. Test parked as `_skip_td01_a_job_that_cannot_start_is_logged` in tests/test_h1.py (rename to re-enable).
- TD-02 (low, a11y WCAG 2.4.11) web/src/style.css has no `html { scroll-padding-top: calc(var(--header-h) ...) }`; the sticky header can hide a focused element. Test `it.skip` in web/tests/h1.test.js.
STATUS: open
