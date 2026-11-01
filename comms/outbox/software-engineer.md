# Outbox: software-engineer

Only `software-engineer` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD software-engineer → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 software-engineer → coordinator
TYPE: handoff
RE: Q-02 · F-01..F-05, F-07 · cloud port C-1..C-8, C-22
BODY: Ready for review. Branch `eng/Q-02-engine-port` (9 commits on `personal`, one per C-item; `git log --oneline personal..`).
- Done: C-1 missed_runs + close after 2 misses, empty/capped closes nothing (logged); C-2 adapters.py verbatim from 019e975 (no personal-only lines lost) + `scrape.locations`; C-3 decide/backends from 019e975 hunks (p1..pN schema, output cap/done_reason, halve-and-retry, decision_failures parking, outage stop, location-evidence guard, think only if /api/show lists it, optional `budget.decide_deadline_s`); C-5 pid_id identity (legacy record: "-m jobscraper" check once, then adopts the identity); C-4 JobCancelled + run marked failed with stats.reason (rolls back uncommitted writes first), CLI SIGBREAK/SIGTERM handler -> exit 143, web: CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT, grace, taskkill /T /F, proc.kill() fallback, JobStuck -> 500, record `reason: cancelled` (in the view only when set); C-7 grace min(12 h, 10%) + stamps at run start; C-6 configure_logging, UnhandledErrors {detail, request_id}, GET /api/healthz (new routers/health.py, Store.ping); C-8 detect_block + signature in the error text ("HTTP 403 (cloudflare) for ..."), Companies reason sharpened, `kind` unchanged; C-22 http(s) URL validator, DOCX 5 MB unpacked / BadZipFile checks, parse in threadpool.
- Kept: personal SYSTEM_PROMPT, DEFAULT_INTERESTS, judge.interests, rules.yaml lists, batch-size/cycle settings, company_health_view kind/paused, scheduler.status cadence. No Postgres, no env overrides (R-12), no runs_per_cycle, no gate_candidates.
- Decision cache: SYSTEM_PROMPT text unchanged; only the user prompt shows p1..pN ids. Cache key (job_id, profile_version, vital_hash, model) unchanged -> nothing is re-judged. Only cached rejects with the new REJECT_LOCATION_EVIDENCE reason are re-asked when the allow list later covers them.
- Config: `config/config.yaml` gains `scrape: {locations: [Singapore]}`. Optional new key `budget.decide_deadline_s` (unset = no deadline).
- Evidence: `python tests/run_tests.py` -> 299/323 passed. All 24 failures are intended/contract changes for Q-07:
  (a) 17 x `TypeError: complete() got an unexpected keyword argument 'schema'` - test fakes in test_decide (10), test_pipeline (6), test_m17 (1) need `schema=None, timeout=None` (cloud updated its fakes the same way). With only those signatures widened (scratch copy) the suite is 316/323.
  (b) C-1: test_store::test_failed_fetch_must_not_close_jobs, test_shortlist::test_shortlist_keeps_closed_roles_flagged (one miss no longer closes).
  (c) C-4: test_pipeline::test_pipeline_crash_before_stamp_is_a_no_op_and_is_reaped (asserts a crashed run stays `running`; now `failed`. Its no-stamp and re-batch asserts still hold).
  (d) C-5: test_web_control::test_web_jobs_a_recorded_job_still_running_holds_the_slot (records a `python -c` PID with no pid_id; now correctly treated as not ours).
  (e) C-7: test_scheduler::test_scheduler_nothing_rescraped_inside_the_cycle (13 d 23 h is now inside the 12 h grace), test_scheduler::test_scheduler_all_fresh_reports_next_due_date and test_pipeline::test_pipeline_nothing_due_exits_with_next_due_date (next due is 12 h earlier).
  test_layering 7/7; `import jobscraper.web.api` OK; `doctor` exit 0 and `run --dry-run --batch-size 2` exit 0 on a scratch DB copy (migration added missed_runs + decision_failures; log shows "HTTP 403 (cloudflare)" / "(akamai)"). Cloud's test_net.py 6/6 and test_small_model.py 33/36 against this src (3 = env overrides / MU-4 API, not ported).
  Windows cancel checked by hand: a CLI-style child got CTRL_BREAK, ran its cleanup, exit 143 in 0.1 s; a child that ignores the break was killed after the grace period; the parent console was unaffected. Pipeline: cancel -> run `failed`, reason `cancelled`; crash -> reason `ZeroDivisionError: ...`; nothing stamped.
- Known limits: CTRL_BREAK only reaches the child while Python runs bytecode. A run blocked in a long Ollama call ignores it and is hard-killed after `grace_seconds` (5 s), so the run row stays `running` until per_run_timeout reaps it. A longer grace for `run` jobs would fix that (needs a decision). CTRL_BREAK needs the web server to have a console (run.ps1 gives it one). Without one, the kill path is used. The SPA half of C-4 (Runs/JobStatus wording, `job.reason`, `stats.reason`/`stats.message`) is left to M18. Watch `rejected_by_postcondition` on the first real run (C-3 location-evidence guard).
STATUS: open
