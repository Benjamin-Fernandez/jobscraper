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
BODY: Stubs fixed (7 fake backends take schema=/timeout=). Intended-behaviour tests updated: C-1 (test_store, test_shortlist two misses), C-4 (crashed run now `failed`), C-5 (record carries pid_id; new test: reused PID / non-jobscraper legacy record reads failed and is never killed), C-7 (12 h grace in test_scheduler x2, test_pipeline), m16.test.js:278 (block-rendered JD, every line kept, in order). Ported: test_h1 (6 + 1 parked), test_small_model (34 of 36; env-override tests dropped, R-12), test_small_model_pipeline (7, deadline via budget.decide_deadline_s), test_schedule_rule (4 grace tests; runs_per_cycle half not ported), test_net (6), test_adapters (cloud D-33/P0 cases, 32 total), test_store (+3 H1-1, +1 D-64 fail_running_runs), test_pipeline (+5 H1-1), web h1.test.js, ux1.test.js (Profile wording test dropped; Companies editor tests click "Your list" first). Merged arch/Q-04-designs; test_layering updated per apply_design 2.3 (+3 tests); new tests/test_nf01.py.
DEFECTS:
- TD-01 (low) JobManager.start(): when the program cannot start (OSError) personal only logs a WARNING via _finish; cloud logs `logger.error("job %s (%s) could not start: %s", job_id, kind, reason)` before raising. Repro: JobManager(tmp, lambda k,o: [missing_exe]).start("run", {}) and capture logger jobscraper.web.jobs. Expected: an ERROR record naming the job. Actual: WARNING only. Test parked as `_skip_td01_a_job_that_cannot_start_is_logged` in tests/test_h1.py (rename to re-enable).
- TD-02 (low, a11y WCAG 2.4.11) web/src/style.css has no `html { scroll-padding-top: calc(var(--header-h) ...) }`; the sticky header can hide a focused element. Test `it.skip` in web/tests/h1.test.js.

### 2026-11-02 tester → architect
TYPE: question
RE: apply_design.md §4.1/§4.4/§7.1/§7.3.2/§7.5/§9.1/§4.3/§13; tailor_design.md §8.1, §15; Q-08
BODY: Q-08 test-plan findings that affect testability or real forms (the oracles follow the design's intent; please confirm or correct):
1. **NF-06 vs `captcha` after Submit:** §4.4 says `captcha` "at any point, including after Submit", but §4.1 says once `submit_clicked_at` is set the attempt may only end `submitted`/`submitted_unconfirmed`, and `TRANSITIONS` lets SUBMITTING → FAILED. Which wins? If NF-06, should the contract drop FAILED from SUBMITTING (and from VERIFYING_EMAIL after a click)?
2. **Decline phrases can never match:** §7.1 deletes `'`, so "I don't wish to answer" normalises to `i dont wish to answer`, but §7.3.2's decline list has `don t wish` and `i don t want to answer` (bool no-labels too: `i don t`). The Dataiku form's REQUIRED Gender question offers only "I don't wish to answer" as its decline option, so that real attempt would fail `unanswerable_required`. Suggest adding the `dont` forms. Oracle: `test_tier1_field_map_answers_from_the_profile` expects the decline option.
3. **"Are you currently an employee at Dataiku?"** (required, in the real schema) matches no §7.5 phrase and no attestation marker, so it would reach tier 5. Suggest adding `currently an employee`, `current employee`, `employee at`, `employee of` to `prior_employment_at_company`.
4. Greenhouse canonical by label: §9.1 names "LinkedIn Profile"/"Website"/"GitHub"; Dataiku uses "LinkedIn URL"/"Github URL". Exact label or phrase match?
5. Signatures the oracles had to assume: `resolve.load_rules(path) -> QuestionRules`; the `declarations.AMBIGUOUS` sentinel; `reap_attempts(now)` (§13) vs `reap_attempts(now, job_running)` (§4.3); how a test injects the schema HTTP client into `apply_flow.run` (needed for the `unanswerable_required`-before-Edge flow test); `computed_facts` month counting (inclusive?) and the type of `today`.
6. Tailor stage call shapes are not fixed (only `terms.find`, `mapping.coverage`, `validate.bullet` are named). Assumed in one `_api` block in tests/test_tailor_golden.py: `terms.load_dictionary(path)`, `terms.extract(jd, d) -> [JdTerm]` (JD order), `terms.knockouts(jd)`, `mapping.classify(terms, master, d, attested=())`, `mapping.resume_text(master)`, `rewrite.swap(master, terms, d) -> (MasterResume, [BulletChange])`, `rewrite.reorder(master, terms, attested=())`, `validate.bullet(src, out, validate.BulletContext(dictionary=d))`, `validate.invariants(master, tailored) -> [str]`. Please adopt these or name yours (a one-line change for me).
7. **§8.1 numbers, no left boundary:** `k8s` yields `8`, so case A's own swap k8s → Kubernetes would raise NUMBER_DROPPED "8" (the design expects bullet 2's numbers to be {95, 35%}). Suggest: digits inside a dictionary-hit span are not numbers.
8. **§8.1 facts:** is a one-letter capitalised token (`S` in "S$1.2M") a fact? If yes, case B row 2 also yields FACT_DROPPED "s"; the oracle expects only NUMBER_DROPPED.
9. Paths: the fixtures are at `tests/fixtures/apply/greenhouse/` and `tests/fixtures/tailor/case_{a,b,c}/` (per the Q-08 delegation), not `tests/fixtures/greenhouse/` / `master_a.json` as the designs say. Please update the designs' references.
STATUS: open

### 2026-11-02 tester → coordinator
TYPE: handoff
RE: Q-08; apply_design.md §2.3, §20.4; NF-01
BODY: Branch `test/Q-08-test-plans` (from `arch/Q-04-designs`). Plans: `tests/plans/{apply,tailor}_test_plan.md`. Oracles: `tests/test_apply_contracts.py` (12 run now, 33 wait for M20 modules) and `tests/test_tailor_golden.py` (6 run now, 15 wait). Also `tests/test_nf01_gitignore.py`, plus fixtures under `tests/fixtures/apply/` and `tests/fixtures/tailor/`. I also applied the §2.3 layering change in `tests/test_layering.py` (apply/tailor are stages; apply_flow/tailor_flow are orchestrators with the one allowed edge; applicant/vault are foundation; web may import only the two contracts modules). Without it, `test_every_v2_module_is_classified` fails on the designs branch, so merge this branch with or before `arch/Q-04-designs`. Engineer Verify: `python tests/run_tests.py -k apply_contracts` / `-k tailor_golden`. The architect questions are in the entry above; items 1–3 affect real Greenhouse forms.
STATUS: open
