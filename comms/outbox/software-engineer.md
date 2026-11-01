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

### 2026-11-01 software-engineer → coordinator
TYPE: handoff
RE: Q-03, F-06, D-56; cloud_port_report C-10, C-12 to C-18
BODY: Branch `eng/Q-03-ui-port` (from `personal`), one commit per item, `web/src/**` only.
- C-10 toast.js + ToastHost.vue copied from cloud 6be6e46 (personal had no own lines).
- C-13 jd.js + Inbox `descriptionBlocks`/`descriptionPreview` (no v-html). The `aria-live` on the whole description (audit G22) is left as is.
- C-12 Inbox keys s/a/x/o/j/k (cloud `onShortcut` guard), "Turn off" toggle in localStorage (try/catch), `aria-keyshortcuts`. Personal `/` search focus, its `aria-keyshortcuts="/"` and `<kbd class="key-hint">` kept.
- C-14 Applications: inline notes via `setApplicationStatus(job_id, row.status, {notes})`, sort Company A-Z / Recent activity, stage-count pills. No follow-up chip.
- C-15 Companies: "Edit list" / "Type or paste names" before "Clear list", textarea saved as companies.txt via the existing upload (`PUT /api/companies/list`). WatchedCompanies, CountPicker and the view switch untouched.
- C-16 setup.js + SetupChecklist.vue wrap the empty-Inbox state.
- C-17 page heads on Runs, Profile, Settings; `.badge-slot` only with a count; `.page-head + .section-title` CSS. "Read my resume again" wording not applied (personal Profile has no such button).
- C-18 `detailText` + 413/415/422 in `describeError`, `failureText` (used in TitleEditor, Profile, Companies), JobStatus says "cancelled" when `job.reason === 'cancelled'` (needs the C-4 engine half to set `reason`), boot screen with Retry in App.vue (network error only; an ApiError still goes to the tabs), `sgtClock()` in format.js.
EVIDENCE: `cd web; npx vitest run` -> 1 failed | 179 passed (180). The failure is intended: `web/tests/m16.test.js:278` expects `.jd-text` text to equal the raw description; it is now heading/list/paragraph elements (tester to update with the h1/ux1 ports). Scratch build (`vite build --outDir <scratch> --emptyOutDir`) succeeded.
KNOWN LIMITS: not exercised in a browser.

RE: Q-06 / S-2 / F-22, NF-07; docs/architecture/spikes/S-2_tailor_llm.md
BODY: Spike done on branch spike/Q-06-tailor-llm. Qwen3-14B (qwen3:14b, Ollama 0.40.13, RTX 5080): 1.5 s per entry, about 6 s per resume, 177/177 calls valid JSON. 78-79% of bullets returned unchanged; real-JD resumes 0-2% changed; coverage after LLM == after swaps in 54/54 runs. Hard validator rejections 4.8% (all correct); keywords_used check gave 7-11% false positives; retry rescued 0/59. Validator misses verb upgrades, direction flips, number words, unknown lowercase tools. Recommend tailor.llm stays false; fixes listed in the report. Design gap: a "- Kafka" list line is read as a heading (§4.3 step 4); golden oracles need "bullet-marker lines are never headings".
STATUS: open

### 2026-11-02 software-engineer → coordinator
TYPE: handoff
RE: M20 lane T (WP-T1..T8), branch `eng/M20-T-tailor` (from `personal`)
BODY: Deterministic ATS tailor built, no LLM per job. Files: `src/jobscraper/tailor/{__init__,terms,mapping,rewrite,validate,master,render,storage}.py`, `src/jobscraper/tailor_flow.py`; shared blocks: `store.py` (tailored DDL + methods), `config.py` (TailorConfig + `tailor`, `aliases_path`, `master_resume_path`, `tailored_dir`), `config/config.yaml` (`tailor:` + 3 paths), `requirements.txt` (pywin32), `cli.py` (`tailor <job_id> [--report] [--force]`, one line in `cmd_purge`), `web/jobs.py` (kind `tailor`), `pipeline.py` (one `tailor_storage.purge` call beside `purge_descriptions`).
- Auto-apply hook (D-70): `tailor_flow.tailor_for_apply(cfg, store, job_id, backend=...) -> TailorResult` (docx_path, pdf_path, coverage_before/after, ok/error) and `tailor_flow.upload_path(result, "pdf")`; also `master_text(cfg)` and `alias_groups(cfg)` (D-68).
- Evidence: `python tests/run_tests.py -k tailor_golden` 21/21 (no skips); full suite 440/442 (the two known D-69 oracles); layering 7/7; -k store 50/50. Flow scratch run (golden A, temp DB, fake backend): coverage 29% -> 64%, second call returns same row, `--report` writes no row/file, stdout holds no bullet text; B 50%->50%, C 38%->54%. Smoke on a copy of the main DB + synthetic resume + real Ollama master parse: `tailor <id> --report` then full run -> 22% -> 27%, DOCX + PDF (1 page) round-trip, 4.4 s end to end.
- Deviations / notes: (1) lane P (WP-P1/P2) is not on `personal` yet: `master._complete` passes `format=` when the backend has it, else `schema=` (current transport); `tailor_flow.load_applicant` reads `data/applicant.yaml` with yaml (identity names, `skills`, `attested_skills`), to swap for `applicant.load` after P2. (2) `validate.invariants(master, doc, attested, swapped=None)` checks the skills-items rule only when the post-swap doc is passed (the oracle calls it without). (3) `JdTerm` extra strings (applicant skills, attested, master skills items) enter the dictionary per TD 4.2. (4) `tailor.llm_terms`/`llm` are parsed but unused in M20 (always dictionary terms, mode deterministic). (5) No `tests/test_tailor_{terms,mapping,...}.py` exist, so the WP `-k tailor_terms` etc. Verifies were run through `-k tailor_golden` plus scratch scripts; the tester's per-WP files are still to come. (6) pywin32 was pip-installed into the system Python for the PDF path.
KNOWN LIMITS: attested skills are only appended when a Skills section exists; a master with no Skills section never gets one. Word cold start dominates the 4-5 s run. `Dictionary` treats an extra skills string as a hit anywhere in a JD (e.g. an unusual skills item may surface as a JD term).
STATUS: open
