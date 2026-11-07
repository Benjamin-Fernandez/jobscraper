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

### 2026-11-02 tester → coordinator
TYPE: handoff
RE: Q-26 (D-70 oracles, WP-F4)
BODY: `tests/test_apply_mail.py` (WP-V3 oracles against fake IMAP; fixtures `tests/fixtures/mail/*.eml`, 6 synthetic messages incl. backup-address, stale, 2 phishing) and `tests/test_apply_d70.py` (contracts v3, `yes_if` via temp rules file, backup_email, account_email tier 1) run. Skip-clean until built: identity rule (`apply.accounts.choose_identity`, exact per 10.5), Workday choice (ASSUMED `apply.ats.workday.choose_entry(offered, applied_on_tenant, setting="auto") -> (WorkdayEntry, prefill_source)`), KEEP table (ASSUMED `apply_flow.keep_decision(field, answer, shown, ctx_email) -> "keep"|"overwrite"|"fill"`), MyGreenhouse browser test (fixtures `form_mygreenhouse_signed_{in,out}.html` ready). Engineers: expose those pure helpers or tell me the real names. Mail API assumed: see docstring of test_apply_mail.py. Note: FILLING -> FILLING is legal (wizard steps), so the "only signing_up may repeat" oracle exempts it.
STATUS: open

### 2026-11-02 tester → coordinator
TYPE: handoff
RE: Q-30 · WP-Q0 · questions_design.md §13 · branch test/Q-30-questions-oracles
BODY: Version fix committed alone first (0da363f: `test_contract_version_is_at_least_3`, `>= 3`); it unblocks the merge of `arch/Q-30-dynamic-fields`. Then all §13 oracles, skip-clean until each module or function exists. Python: `tests/test_applicant_form.py`, `test_web_applicant.py`, `test_apply_resolve_rules.py` (D-75 1-15 plus `label_countries`, over the fixture rules file and, once WP-A04 lands, over `config/questions.yaml` too), `test_apply_resolve_memory.py`, `test_apply_questions.py`, `test_web_questions.py`, `test_apply_flow_questions.py`, one path added to `test_nf01_gitignore.py` (the plan says `test_privacy.py`; no such file exists, NF-01 lives in `test_nf01_gitignore.py`, needle `nf01`). Shared helpers: `tests/questions_support.py` (not a test file; every ASSUMED call shape for a missing module sits in ONE helper at the top of each test file, named in its docstring). Fixtures: `tests/fixtures/apply/questions_d75.yaml`, `applicant_extra.sample.yaml`. Web: `web/tests/ApplicationDetails.test.js`, `QuestionsInbox.test.js` (`describe.skip` while the component file is absent, via `import.meta.glob`). Smoke switch for engineers: `Q30_FORCE=1 python tests/run_tests.py -k <needle>` defines every oracle even when its module is missing, to see how each fails. Lane B review: no lane B oracle asserts an empty `rule_id` on an unknown answer (grep over `eng/M20-B-browser-greenhouse` tests: `rule_id` is asserted only on tier-2 and declaration answers; lane B's own `_employer_specific` reads `rule_id` only for tier-4 answers; `cli apply show` prints it only when non-empty). So Q2's `rule_id` change breaks nothing there. The flow oracles need lane B's `apply_flow.run` and Store attempts; the harness (fake adapter, fake page, routing backend) was proved against lane B's source read-only (schema plan and DOM step both end `failed(unanswerable_required)` as designed).
STATUS: open

### 2026-11-02 tester → architect
TYPE: question
RE: questions_design.md §8.2 vs §13 oracles 8, 9, 10; §4.2 reason order; §6.1 vs §9.2; §5.2 assign_key; WP-Q0
BODY: Findings from writing the oracles. The tests follow the design's intent where it is clear; please confirm or correct the rest.
1. **Bare "US" cannot be detected (design conflict).** §8.2 says the token `us` alone is never a country ("work for us"), and the aliases are `u s`, `u s a`, `usa`, `united states`, `america`. But §13 oracles (8) "Can you work in the US without sponsorship?" and (9) "...the US or Canada?" use a bare "US": after `norm_label` that is `us`, so no country is named, the job country SG applies, and (8) answers Yes for a profile where a(US)=true, s(US)=true (expected No), and (9) never conflicts. The tests use "U.S." (alias `u s`) so they are consistent with the alias list. Real forms say "US" a lot. Options: give `label_countries` the raw label and count an upper-case standalone `US` after in/to/the/within/across (never "for us"); or add `in the us`, `to the us`, `within the us` as phrase aliases. Which one? A third oracle pinning the choice is easy once decided.
2. **§4.2 table order vs conflict.** "First that holds": a D-75 conflict Answer carries `rule_id` = the map key (§6.2 sets it on every final unknown), so `no_option_fits` (rule_id names a key with a value) would win over `conflict`. The oracle expects `conflict` (design text: "captured with reason conflict"). Please state that `conflict` is checked first.
3. **§6.1 vs §9.2 step 3: an employer-scoped first answer.** For `choice`, validate requires non-empty base `picks`, but a first answer scoped to one employer writes only `by_employer`. Either the base may be empty when `by_employer` is non-empty, or the answer endpoint refuses a scoped first answer. The oracle only scopes after a base answer. Decide and I add the case.
4. **§5.2 assign_key signature and §5.3 split.** The design names the model call as made by `apply_flow` but lists `assign_key` as pure. The oracle assumes `assign_key(q, extra, rows, suggestion=None) -> key | (key, ...) | object` with `named_by`, and `parse_naming(reply, existing, q)` feeding `suggestion`; `existing` as `(key, title, kind, sensitive)` tuples (what `store.question_keys()` returns), the sensitive filter and the 50 cap inside `naming_user_prompt`. Name yours and I change one helper (`_assign`, `_prompt`).
5. **`upsert_question(q: dict, now)` dict shape.** Assumed: the DDL columns minus id and timestamps, `options` as `[{"label","norm"}]` and `options_json` as its JSON text, `sig` per §5.1 (`tests/questions_support.question_row`). One place to change.
6. **Notes through tier 3 (§6.2, §11):** `memory ambiguous: k1, k2` and `memory entry invalid: <key>` must survive to the final Answer's `note`, but tier 5 already sets its own note ("model unavailable") and `_tier3` returns only an Answer or None. Two separate oracles (`..._note`) pin it; if you prefer the note lives elsewhere, say where.
STATUS: open

### 2026-11-02 tester → coordinator
TYPE: request
RE: web test runs in worktrees
BODY: `web/node_modules` is absent in agent worktrees, so `cd web; npx vitest run` fails at start. I made a directory junction `web/node_modules` -> the main checkout's `web/node_modules` (gitignored, read-only use) to run it. Suggest adding `web/node_modules` handling to the worktree brief (a junction, never `npm ci` per worktree). Removing a junction: `cmd /c rmdir <link>` (never `Remove-Item -Recurse`, which can delete the target's contents in PowerShell 5.1).

RE: Q-31 (lane B tests; docs/reviews/M20-lane-B.md F1 F2 F4 F10; Q-29 pins)
BODY: Branch `test/Q-31-laneB-tests` (from `eng/M20-B-browser-greenhouse`, then lane B's review fixes `c82216d` merged as you instructed). New: `tests/test_apply_flow.py` (fake adapter + fake browser through `apply_flow.run`), `tests/test_apply_cli.py` (cli.main with a fake flow, apply show, job kind, open-profile, one real-CLI subprocess smoke), `tests/test_apply_e2e.py` (real flow + real Greenhouse adapter, headless Edge, local fixture board/API on 127.0.0.1), `tests/test_greenhouse_fill.py` (adapter driven directly, MyGreenhouse both pages, section 9.1.2 link labels), `tests/test_apply_resolve_excludes.py` (Q-29 pins), helper `tests/apply_flow_support.py` (not a test file). Changed: `tests/test_apply_contracts.py` (`test_a_posting_can_succeed_only_once` records the click before `submitting`; new F2/F4 store oracles). Review oracles: F1 (3 tests, flow + `apply_prefill_policy`), F2 (store refuses submitting without a click, store/contract parity for every state pair, reaper never fails `submitting`), F4 (a run lock held by a second PROCESS makes the flow start and reap nothing; lock released after a run; pre-click duplicate and cap re-check; `mark_submit_clicked` refuses a non-live row), plus locks for F3, F5, F6, F11. All of them pass against c82216d.
- Note 1 (low, cosmetic): in `apply_flow.apply_prefill_policy` the line `... and f.type is not FieldType.FILE                 and same_value(f, a, val):` has a run of spaces where a line continuation was; valid Python, tidy it.
- Note 2 (low): `apply_answers.value_json` is documented "JSON" but plain string answers are stored as raw text (`Alex`, not `"Alex"`), while files and lists are JSON. `cli._shown_answer` json.loads it, so a text answer `true` / `null` shows as `True` / `(blank)`. The tests decode tolerantly (`stored_value`). Pick one rule before the M21 attempt panel reads these rows.
- Note 3 (info): `HttpClient(max_retries=0)` raises `FetchError(unknown)` without trying once; `apply_flow.make_http` uses 3, so only a caller passing 0 is hit.
- Q-29: `tests/test_apply_resolve_excludes.py` fails 3 of 5 on this branch because the fix (`eng/Q-29-exclude-match`, 8e2e3c8) is on `personal`, not in lane B's base. Checked against personal's code with a scratch overlay (Rule.score from personal plus personal's questions.yaml): 5/5 pass. They go green when this branch is merged into `personal`.
- Not covered: the real deterministic tailor on a fixture master through the real flow (WP-B9 e2e wording). Tailor plumbing is tested with a patched `tailor_for_apply` (flow tests); the real tailor needs Word for PDF. Say if you want a DOCX-format variant.
STATUS: open

### 2026-11-02 tester → coordinator
TYPE: handoff
RE: Q-37 (make both suites green on `int/Q-30`; test-side fixes only)
BODY: Python R1-R3 (lane Q's outbox) all hold, all three fixed in the tests. R1 `test_web_applicant`: the etag is now read inside the `_world()` block (the temp dir is gone after it). R2 `test_apply_questions`: the "employer is not part of the signature" assert now passes the same options (Citizen, PR, Other). R3 `test_applicant_form`: the empty-picks error case drops `by_employer` first; new `test_a_choice_with_employer_answers_may_have_empty_base_picks_d76` pins D-76 item 3 (empty base picks valid with `by_employer`).
- Web, 6 failures, all test-side; the components follow questions_design.md §10. (1) "Needed" / "Private" tags: `wrapper.text()` joins sibling elements with no space ("...applicationsNeededPrivate: never sent..."), so `\bNeeded\b` never matched; regex now `/Needed(?! before)/g`. The "does not tag a filled field" test used the same regex and was passing vacuously; it now uses the fixed regex, so it is a real check. (2)-(4) saving PUT, 422, 409: the Save button is the submit button of a `<form @submit.prevent>`; jsdom submits only a connected form, so the click did nothing. `mountDetails` now uses `attachTo: document.body`. (5) retry in dry run: "Started. Dry run: ..." is a toast (QD 10.2 does not say inline), test now asserts `toast.current.message`. (6) empty state: title and hint are two paragraphs, `text()` has no space between them; the test asserts both sentences in order.
- Component notes (no defect, for the owner to judge): PUT 409 `unreadable` carries no error text, so `ApplicationDetails.vue` shows "JobScraper can't read data/applicant.yaml. Fix the file by hand..." without the "(<error>)" part QD 10.2 shows; the full text appears after Reload via GET `file.error`. Low.
STATUS: closed

### 2026-11-02 tester → coordinator
TYPE: handoff
RE: Q-36 (D-78) lenient profile: tests on `int/Q-36`
BODY: `tests/test_applicant_form.py::test_a_lowercase_country_key_and_a_non_bool_default_are_errors` now uses `"maybe"` and `3` for the default (D-78 reads a quoted yes/no/true/false as a bool, superseding QD 8.1 for those words); new pin `test_a_quoted_yes_or_no_in_a_work_rights_map_is_read_as_a_bool_q36`. New `tests/test_applicant_normalise.py` (36 tests): every enum value in any case/space/hyphen, pay-period and decline synonyms (and that neither leaks into enums without them), YAML bool only for yes/no enums, plain bools and both work-rights maps from quoted words (keys untouched), ord_date / day-field / entry-date tables including every invalid or ambiguous form staying as typed with the validate message, idempotence and fixed points (sample, template), no mutation, validate messages never echo the value, `load` of a hand-typed file, `save` then `load` round trip. No code defect found. Mutation check (scratch, not committed): disabling each of bool, date, enum, decline-synonym, pay-synonym, no-op normalise, swapped day/month, entry-date cut makes 8, 10, 13, 5, 8, 24, 10, 10 of the 36 fail.
- Observation, not pinned (not promised by the docstrings): an entry end of "Present" / "present" stays as typed and `validate` reports `must be a date as YYYY-MM or YYYY-MM-DD`; if D-78 should read it as null (the template's "null = present"), that is a small normalise addition and I will pin it.
STATUS: open

### 2026-11-02 tester → coordinator
TYPE: handoff
RE: Q-39 (pins for the Q-30 review fixes F2, F6, F7) on `int/Q-39`
BODY: Added 24 Python and 26 Vitest tests, all synthetic data in temp folders. F6 and F7: `tests/test_applicant_q39_pins.py` (23; load_with_etag missing/valid/empty/broken/non-UTF-8/not-a-mapping, a swap after the first read cannot split profile and etag in `load_with_etag`, GET and the PUT reply, GET on an unreadable file is 200 with the etag of those bytes, prev written/rolled/not rolled on an identical save/not on first save/not on an invalid save/not with keep_previous=False, writes only inside the profile folder, PUT with a partial profile leaves the old file in prev, 422 and 409 write no prev), plus `test_web_questions.py` (an answer rolls prev, a refused one does not) and two names in `test_nf01_gitignore.py`. F2: `web/tests/applicantForm.mergeEdits.test.js` (19 pure oracles) and a new "F2" suite in `web/tests/ApplicationDetails.test.js` (7: a profile-gap answer survives Save details of an edited section with the new etag; same leaf both places, the file wins; an extra answer edited here plus a new one from the file; removeAnswer confirm says "Your other unsaved changes will be saved too." only when dirty and sends them). Mutation-checked: the old two-read load, no prev, a prev rolled on identical saves, and the old section-level merge each fail the pins.
- DEFECT (low), request to software-engineer: `test_q39_f7_the_temp_name_of_the_profile_write_is_gitignored_too` fails on purpose. Repro: `applicant.save` over an existing file writes through `applicant.yaml.<rand>.tmp` (`tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp")`). `git check-ignore --no-index data/applicant.yaml.ab12cd.tmp` is NOT ignored (`.gitignore` has only `data/applicant*.yaml`). Expected: every temp name `save` uses matches the NF-01 pattern, as the prev temp (`applicant.prev.<rand>.yaml`) now does. Actual: a crash or kill between the write and `os.replace` leaves the owner's profile in an untracked, committable file in a public repo. Not caused by Q-39 (the profile temp name is older). Fix: give that temp a `.yaml` suffix (for example `suffix=".tmp.yaml"`), nothing else changes; the test then passes.
- Not pinned (said in the engineer's KNOWN LIMITS): the window between `load_for_write`'s read and the `os.replace`; `has_comments` / `file.exists` in GET are separate reads.
- Note: `int/Q-39` was green at 789 before these pins; the only red test now is the defect above, so it needs the one-line fix (or the test marked known) before the merge gate says "all pass".

### 2026-11-03 tester → architect (cc coordinator)
TYPE: review
RE: Q-35 stage C · llm_fill_design.md (LF) · llm_fill_build_plan.md · contracts v5 · tests/plans/llm_fill_test_plan.md
BODY: Testability cross-review. TR-1 to TR-3 block the work packages named in each item. The rest don't block, and each oracle in that group follows the rule proposed in its item until you answer.

**Blocking**

- **TR-1 (BLOCKING WP-M4 and the T2 privacy oracle): S values reach the prompt.**
  - Problem: they get in two ways.
    - RESUME is `ctx.resume_text`, and its header holds the email, phone and address (all S per AD §5.3).
    - The `current` value of import-prefilled fields: Workday's import fills the phone, address and email, and LF §3.3 shows site values as `current`.
  - Effect: LF §16's own oracle ("every recorded prompt: no S value, no email") fails by construction.
  - Proposal:
    - Add a pure `llm_fill.redact(text, s_values) -> str` and apply it to the whole user prompt. `s_values` = every S value of the profile plus the account email; the email matches case-insensitively, and the phone also as digits with and without the country code.
    - Omit `current` (send `current_set: true` instead) when a field's shown value contains an S value, or its label matches the G7 pattern.
- **TR-2 (BLOCKING the WP-N5/N6 cache key and the T4 cache oracle): the cache can never replay after an answer.**
  - Problem: `facts_hash` includes the profile file bytes. Answering a captured question writes `extra` into `data/applicant.yaml` (ADR-0005), so every key changes.
  - Effect: the use case in §13.3 ("a retry after the owner answers replays earlier steps with no model calls") never happens.
  - Proposal (or drop the claim):
    - Hash the profile without `extra`.
    - Store, per row, the value hash of each `extra:<key>` the decision cited. A changed cited entry is a cache miss.
- **TR-3 (BLOCKING WP-M3, G6): a fact ref bypasses entry scope.**
  - Problem: G6 checks only `resume` and `keep`. The model can cite `profile:contact.city` for a job entry's Location; G2 accepts it, and the program writes the home city.
  - Effect: S-5b failure 3 comes back through a fact ref.
  - Proposal: inside an entry group, a `profile` ref must be a fact whose `Fact.entry` is that group's matched entry (plus `standing:today`). Anything else → UNKNOWN, note `G6`. The G6 oracle is parked until you decide.

**Non-blocking**

- **TR-4: model replies can't be matched by field id.**
  - Problem: reader ids are random (`f<n>_<rand>`), so reply fixtures can't key on them. The fake keys on `group|question` instead, which it gets by parsing the FIELDS block.
  - Ask:
    - MUST: the `FIELDS (JSON):` block is valid JSON on its own and is the last block before the fixed final line.
    - Expose `SYSTEM`, `PICK_SYSTEM` and `RECHECK_SYSTEM` as constants (the fake routes on them).
    - Every call sets `ModelDecision.via`.
    - Optional: `read_page(..., rng=None)`.
- **TR-5: missing clock seam.**
  - Problem: facts and locks take `today`, but `fill_page(page, nav, ctx, rctx, services)` has none, and the 30-day purge needs `now`.
  - Ask:
    - Pass `services["today"]`, computed by one pure `facts.today_sg(now_utc: datetime) -> str`. Oracle: 16:30Z → the next day.
    - Add `apply_flow.run(..., now=None)` for the purge and `created_at`.
- **TR-6: existing tests break on the new path.**
  - Problem 1: `warm()` and `llm_fill` send `keep_alive=`, which the existing test stubs reject.
  - Problem 2: when N6 makes `fill: llm` the default, lane B's flow tests (`test_apply_flow.py`, `test_apply_e2e.py`, `test_apply_flow_questions.py`) run with no reply files.
  - Proposal:
    - Send `keep_alive` only when it is configured (WP-M4 already says "sent only when given").
    - The tester pins `fill: rules` for those tests in `apply_flow_support` within the T4 pair, until WP-C1.
- **TR-7: what does "nothing typed" mean on a stopped page?**
  - Problem: §8 step 7 says nothing is typed on a stopped page, but step 2 deletes and adds entries before the stop. E6 deletes appear in no §8 step.
  - Oracle: zero widget fill or clear calls after the stop decision.
  - Ask: confirm, and place E6 in §8.
- **TR-8: L1 can put the resume in the wrong slot.**
  - Problem: L1 also matches on page text. On a page that mentions "resume", a required "Cover letter" or "Portfolio" file field gets the resume.
  - Proposal: apply the page-text clause only when the page has exactly one file field (the S-5b Autofill step). The oracle is written that way.
- **TR-9: traceability.**
  - Label collisions: "L1" (category expansion, §3.1) and "L2" (pick_option, §6.4 and G1) collide with locks L1 and L2 in §4. The S-5b report also cites "§6.4 / L3".
  - Dangling reference: `WP-F3` (§15 O-2) is not in the build plan.
  - Unowned Verify commands: R3's `-k apply_pagefill` and M5's F1 capture oracles (`-k apply_questions`) had no tester WP. The plan puts them under T3 and T5.
- **TR-10: unnamed parameters.** Until these are named, the oracles test clear cases only.
  - E2's "token overlap ≥ 0.5": Jaccard or overlap coefficient, and over which tokens?
  - Confidence of an optional resume/job choice without G5: 0.8 or 0.9?
  - `second_opinion: false`: accept without G5, or fail closed? Suggest: a required risky answer → unknown.
  - Expose the G4 stop words and level synonyms and the G7 pattern as module constants, with word bounds ("Sussex" and "embrace" must not match).
- **TR-11: shared prompt prefix.** §13.2 says FACTS+RESUME is byte-identical across an attempt, but entry chunks send `RESUME ENTRY` only. Oracle: FACTS identical across all calls; FACTS+RESUME identical across non-entry chunks. Confirm.
- **TR-12: no deterministic oracle is possible for:**
  - model accuracy;
  - prompt rules 5 and 7, beyond "the rule is in SYSTEM";
  - latency (NF-07), prefix reuse and the warm-up;
  - real widget timing and the parser's output;
  - the review check's "text present in another form".

  Proposal:
  - A deterministic G11 for rule 5: in an entry group, a title/position/role TEXT value must not contain the matched entry's employer tokens (the oracle is parked).
  - An eval, `tests/evals/llm_fill.py`, running the real model over the sanitised fixtures. It replaces the AD tier-5 eval; hard thresholds are 0 S leaks and 0 ungrounded fills.
- **TR-13 (info): T3 green is not proof on Workday.** Static recordings hold no listbox or prompt pop-ups, so the reader and widget tests run on a test-owned `shim.js`. Real widget fidelity is proven only in dry runs.

**Seams.** Present: backend (`apply_flow.run(backend=, browser_factory=)`, `llm_fill.ask(backend)`, `guards.decide(second=)`, `fill_page(services)`) and navigator (REGISTRY). Missing: TR-1 `redact`, TR-4 prompt constants and a parseable FIELDS block, TR-5 clock.

**Privacy, for the Coordinator.** The S-5b recording folder also holds live browser profiles for both tenant accounts (session cookies). Never copy them into a worktree, and consider deleting them after the gate. The T1 deny-list (`JOBSCRAPER_FIXTURE_DENYLIST`, a file outside the repo) is yours to build.
STATUS: open

### 2026-11-03 tester → coordinator (cc lane R engineer, architect)
TYPE: handoff
RE: Q-35 WP-T0, WP-T1, WP-T3 · branch test/Q-35-llm-fill-oracles
BODY: T0 `tests/test_apply_contracts_v5.py` (14). T1 `tests/llm_fill_pages.py` (builder), `tests/llm_fill_support.py` (FakeFillBackend keyed `<group_title>|<question>`, FixtureDir, secret scan), `tests/test_llm_fill_fixtures.py` (14, incl. a headless-Edge shim walk), fixtures `tests/fixtures/apply/llm_fill/**` (wd_a 7 steps, wd_b stop page, 7 stubs, shim.js, README). T3 `tests/test_apply_page_reader.py` (9 + 1 always-run), `tests/test_apply_widgets.py` (8 + 1), skip-clean until `jobscraper.apply.page` / `widgets` exist.
- Fixtures are GENERATED from a spec that copies only the Workday DOM structure seen in S-5b; no recorded text, value, id or screenshot is copied; values are the sample profile's; question GUIDs synthetic.
- Lane R, ASSUMED shapes (one helper each, tell me yours): `page.read_page(page, *, scope, sections, origin)`, `page.entry_sections(page, scope)`, `widgets.fill(page, field: PageField, value) -> bool` (True only on an equal read-back), `widgets.read(page, field) -> Value`. Fixture field identity in the oracles is `(group_title, label)`; `shown` for dates is compared as digits.
- Architect (non-blocking, from writing T3): (1) LF §3.1 makes a prompt MULTI_CHOICE only when it "holds several pills", so an empty or one-pill multi prompt (Workday skills) reads as TYPEAHEAD; fields.json follows the rule as written; suggest detecting multi from the widget. (2) `PageField` has no `parts`, but the field view (§6.2) sends date `parts`; add `PageField.parts` or say where they come from. (3) The `click_filter` fallback has no stub yet; it goes with T4/N2.
- Privacy: the owner deny-list scan (T1 part b) needs `JOBSCRAPER_FIXTURE_DENYLIST` pointing at a file outside the repo (yours to build). For these commits I scanned the staged trees against an in-memory list built from the recordings (names, e-mails, phone, address, past employers/schools, employer names, tenant hosts): 0 identifier hits.
STATUS: open

### 2026-11-03 tester → coordinator (cc lane N, lane R, lane M engineers)
TYPE: handoff
RE: Q-35 int/Q-35-NR oracles: M14 fix, T4 lane N, review F1/F3/F4/F7/F8, T2 (lane M) · branch int/Q-35-NR
BODY: Commits on int/Q-35-NR (tests only): 7fcd508 M14 (the search-driven prompt moved outside the form; new pin: inside a form a search-only prompt fails safely, `formSubmits` 0, no text or pill left). b6ce72f `test_workday_nav.py` (13: job_url, entry_choice, step ids M7, forms A/B, external_id, no Enter; headless Edge on `tests/fixtures/apply/workday_nav/*` + wd_a/wd_b: entry dialog, account form beats the progress bar, beecatcher untouched, click_filter fallback, step ids/scope/entry_sections, review never clicked, errors as labels, confirmations); D-70 `test_workday_apply_choice_rule` rewritten against `entry_choice` (D-78). 334c121 `test_store_fill_cache.py` (7), `test_greenhouse_nav.py` (6), `test_accounts_cli.py` (6, in-memory keyring), `test_apply_flow_accounts.py` (10: F3 gate, identity, sign-up order and rollback, F4 code path), `tests/vault_support.py`. da82193 F1 pin. Last commit: T2 `test_llm_fill_{facts,locks,guards,model}.py` (+ `tests/llm_fill_t2.py`), skip-clean on int; 31/31 against lane M a4f1c8c via an in-memory overlay (lane M modules loaded from git objects; nothing written). `find_secrets` fixed per lane M's report (digit runs, not all digits joined) and pinned.
- Failing pins (code defects; each needs its lane's fix, then goes green):
  1. F1 HIGH (lane R): `test_apply_widgets::test_a_react_select_never_settles_on_an_option_that_only_contains_the_words`. Repro: `tests/fixtures/apply/widgets/react_select.html`, decided "Computer Engineering", the search shows only "Computer Engineering Technology". Expected: `fill_field` -> ok False, note `search_miss`, `pick` asked, nothing chosen. Actual: the option is clicked (the page shows "Computer Engineering Technology").
  2. F8 MEDIUM (lane N): `test_accounts_cli::test_confirm_marks_only_the_accounts_the_export_held`. Expected: an account created after `export-edge` stays unexported after `--confirm`. Actual: it is stamped exported.
  3. NEW, MEDIUM, live with the int/Q-35-NR merge (lane N, D-85): `test_apply_flow_accounts::test_the_greenhouse_code_pattern_reads_the_code_not_a_word` and `::test_d85_the_code_is_the_only_short_alphanumeric_line_after_the_sentence`. Today `GreenhouseAdapter.otp_pattern` `([A-Za-z0-9]{8})` makes `mail.find_code` return the word "security" from "...into the security code field...". Expected per D-85: the only trimmed line of 6-12 letters/digits after the sentence (a letters-only code is valid); zero or two candidate lines -> None. Both oracles go through one helper, `_gh_code(body) = find_code(body, GreenhouseAdapter.otp_pattern)`; if D-85 lands as its own function, only that helper changes (tell me the name).
- F5 (lane N 081b338): `test_greenhouse_nav` snapshot oracles rewritten against the reader keys (fake `page.read_page`/`audit_keys`: read before the click, `options=False`, `step="form"`, lists joined "; ", skipped without MyGreenhouse or its button, a read error leaves it empty and prefill runs). They skip-clean with a note until 081b338 is on int; 7/7 against lane N's greenhouse.py via the overlay.
- Skip-clean until N6a: F7 (`test_on_workday_choose_entry_runs_before_the_account_wall`). The F3 pin asserts the gate and must be replaced when N6a lands (its message says so).
STATUS: open

### 2026-11-03 tester → coordinator
TYPE: request
RE: merging eng/Q-35-M-llmfill into int/Q-35-NR
BODY: `git merge eng/Q-35-M-llmfill` conflicts only in `comms/outbox/software-engineer.md` (both sides appended entries; keeping both resolves it). That file is outside my scope, so I aborted the merge. The src files don't overlap. Please merge it yourself; T2 then runs for real (`-k llm_fill_`).
STATUS: open

### 2026-11-03 tester → coordinator
TYPE: handoff
RE: Q-35 tester items not done in this delegation (budget)
BODY: Not started: the M5 capture oracles (`questions.capture_page`, `page_reason`, `TRANSPORT_NOTES`; lane M's names), T5 (`test_apply_resolve_memory.py` F1, `test_apply_resolve_rules.py` F4, `test_questions_variants.py` F3, `test_apply_questions_page.py`, `web/tests/QuestionCard.test.js`), the T4 flow part `test_apply_flow_llm.py` (skip-clean until N6a), TR-6 (pin `apply.fill: rules` in `apply_flow_support`). T2 is a core set (privacy, lock precedence, Decision shape, G1/G10, prompt order, retry); the guard table of test plan §4 (G2-G12, E1-E7 cases) is still to write.
STATUS: open

### 2026-11-07 tester → coordinator
TYPE: handoff
RE: Q-70 lane B · branch `eng/Q-70-B-applications`
BODY: 4 failing Applications tests fixed as the engineer listed; new web/tests/applications-flow.test.js (22 tests: StatusSelect keyboard/pointer/Enter/Escape, Undo writes one more event (D-101), Active chip default + persistence + fallback, follow-up at 15 vs 13 days, Remove + Undo, Clear filters, search Escape, applications.js helpers). `cd web; npx vitest run` = 18 files, 301 passed | 1 skipped. No src defects found.
STATUS: done
