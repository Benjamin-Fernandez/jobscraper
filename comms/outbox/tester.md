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

### 2026-11-03 tester → software-engineer (lane M), coordinator
TYPE: defect
RE: Q-35 / Q-46 failing pins on `int/Q-35-M` (tests only; reproduce with `python tests/run_tests.py -k <needle>`)
BODY:
- HIGH, fails open (Q-46 a; `guards` G2(a)/(b) + `facts.relevant`): `test_llm_fill_q46::test_q46a_a_location_in_a_work_experience_section_never_takes_the_home_city`. Repro: required "Location", no `group`, `field.section="Work Experience"`, context "Company"; decision `profile:contact.city` "Singapore". Expected not FILLED (unknown, stop); actual FILLED "Singapore". Grouped + matched entries already refuse it (G2a) and an empty entry location stops (passing oracle in the same file).
- HIGH, fails open (Q-46 b; `guards` G3 for MULTI values): `test_q46b_no_skill_off_the_resume_or_profile_is_ever_filled`. Repro: search-driven MULTI_CHOICE "Type to Add Skills", decision `resume` ["Python","SQL","PyTorch","Raven DB","HTML Design"], evidence "Python, SQL", agreeing second. Expected no item outside resume/profile/attested skills; actual all five FILLED (the evidence grounds the list as a whole).
- Q-46 b rule (same module): `test_q46b_ungrounded_and_duplicate_skills_are_dropped_and_the_rest_kept`: expected FILLED ["Python","HTML"] (drop, not reject; "HTML Design" after "HTML" is a duplicate); actual the whole list.
- Q-46 b pick (`llm_fill.pick_option`, or lane R's multiselect fill that calls it): `test_q46b_a_skill_suggestion_must_name_the_wanted_skill`: wanted "Python", options ["PyTorch","Python (Programming Language)"], model picks "PyTorch". Expected None; actual "PyTorch".
- MEDIUM, right answer on the wrong basis (Q-46 c; `locks` L3 declaration match + `facts.relevant`): `test_q46c_worked_here_does_not_answer_a_government_service_question`: "Have you ever worked for the Government (excluding mandatory military service)?" is locked "No" by `declaration:prior_employment_at_company`, and `relevant("standing:worked_here")` is True. Expected unknown or a relevant basis.
- MEDIUM, fails closed (`guards._fact_field` non-enum branch): `test_llm_fill_guard_table::test_g2d_a_model_value_naming_the_fitted_option_by_its_leaf_is_the_programs_value`: options "Online > Company careers website", ...; decision `standing:how_heard` "Company careers website" (the option's leaf, which is also the fact's own value). Expected FILLED with the option; actual unknown "G2d". `same_value(mv, pv)` lacks the `option_for` step the enum branch has.
- LOW, fails closed (`resolve.grounded`, used by G3's compose rule): `test_llm_fill_guard_table::test_g3_compose_accepts_a_verbatim_resume_line_that_names_c_plus_plus`: the verbatim resume line naming "C++" is rejected "word C".
STATUS: open

### 2026-11-03 tester → architect
TYPE: question
RE: LF §7 G2(d) "must equal the program value" vs a model that writes the fact's own words
BODY: S-5b showed the model writing "Company careers website" (the fact) for a hierarchical how-heard list whose program fit is "Company Website > Careers Page" (mapped by pick). G2(d) then ends it unknown "G2d", so every such Workday question would stop the run. Should G2(d) also accept a model value equal (normalised) to the fact's raw value, keeping the program's option? The wd_a/wd_b fixtures now cite the fact with an empty value (conformant either way); the leaf-form case is pinned above.
STATUS: open

### 2026-11-03 tester → coordinator
TYPE: handoff
RE: Q-35 tester delegation 5 on `int/Q-35-M` (+ contracts v5 pin, Q-46 a-c)
BODY: Committed: lane M probe pins F1-F9 (baf1d2b); T2 guard table G1-G7/E3 + M5 `capture_page` oracles (6705e52); T5 QuestionCard vitest (62f1391), WP-Q5 answer oracles (801fb53), F1 generic reuse matrix + F4 all-caps US (fb1dc60); R3 fixture gaps: G5 seconds for Phone Device Type/how-heard, G11 Job Title recheck, a corrective reply, the upload hash read after the temp dir is gone (e83e9f5; `-k apply_pagefill` 8/8 with lane R's pagefill from 0bdd140 loaded in memory, 4/8 before); QuestionReason pin + F9 tightened to `compose_needed` (c0ac58b; already passes: `questions.COMPOSE_NEEDED` resolves the enum); Q-46 a-c (8461c44). Observation for lane R: on wd_a 02 with lane R's pagefill, "How Did You Hear About Us?" and "Country Phone Code" end in `fill_failed` after one corrective (read-back), not diagnosed. Not done (budget): `tests/test_apply_flow_llm.py` skeleton; guard table G8/G9/G11/G12, E1/E2/E4-E7.
STATUS: open

### 2026-11-02 tester → coordinator, software-engineer (WP-Q48, lane M, lane N)
TYPE: handoff
RE: Q-48 / D-87 / D-88 oracles and T2/T4 additions on `int/Q-35-M`
BODY:
- WP-Q48: `tests/test_apply_declarations_q48.py` has F1-F20 (employer "Acme"). 13 are gated on `declarations.classify_all` + `STANDING_DECLARATIONS` and skip until WP-Q48 merges, then must pass. F14 (health) and F19 (pre-D-87 table) run now. With the gate off, the harness runs and every gated oracle fails only on missing D-87 behaviour, except F2, which already passes. ASSUMED in the oracles: `answer()` agreement sets `rule_id` and the source suffix to "conflict_audit_independence+non_compete"; F20 reads `applicant.normalise(p)["declarations"]["government_employment"] is False` for "NA"/"nil".
- Lane M pins (fail now): `test_llm_fill_guard_table::test_g7_d88_military_and_national_service_labels_are_sensitive` (D-88: "armed forces" and "military" are not sensitive today; "ns" must stay whole-token: "transactions"/"DNS" are not). `::test_g2d_a_restated_non_private_fact_writes_the_programs_option` (LF G2(d) restated fact: "Company careers website" cited from `standing:how_heard` on options with "Corporate Website" -> today unknown "G2d"; the program's fit is already "Corporate Website"). The earlier leaf-form pin should pass with the same change. A private fact restated stays not filled (passing oracle).
- T2 part 2 (`tests/test_llm_fill_guard_table_entries.py`, all pass): G8 trusted keep, G9 clear/untick, G11 title recheck target, E5 add, E6 delete.
- Lane N: `tests/test_apply_flow_llm.py` is a skeleton gated on `pagefill.fill_page` + `apply_flow._fill_services` (ASSUMED name: tell me N6a's FillServices builder). Its 5 stubs fail with "T4 stub" once the gate opens, until the tester writes them.
- Not done: G12, E1/E2/E4/E7 rows.
STATUS: open

### 2026-11-02 tester → software-engineer (WP-Q48 fix round, lane M), coordinator
TYPE: defect
RE: Q-48 review pins (docs/reviews/Q-48-and-lane-M-fixes.md F1-F10, D-90) on `int/Q-35-M` 4911696
BODY: Each pin reproduces the review's scenario with employer "Acme" and the sample profile. Reproduce with `python tests/run_tests.py -k declarations_review` / `-k guard_table`. Expected values are D-90 (unknown when required, blank when optional, never a filled value).
- `test_apply_declarations_review` (11 pins, declarations/locks):
  - F1: willingness to sign an NDA, for both non_compete values; an acknowledgement checkbox "ticked" on a stray "no".
  - F2: five essay TEXTAREAs typed "No" by tier 4, and by lock L3 too.
  - F3: four unlisted negations get an inverted answer.
  - F4: five employment questions that don't name this employer, including "the US government", are answered "No".
  - F5: an accommodation/"prevent you from performing" frame is classed as disability; a decline-to-disclose checkbox is ticked from "no".
  - F7: a compound clause gets an answer.
  - F8: a note says "declined".
  - F10: locks keeps its own NS_TERMS. The same-result check passes; the pin is on one list.
  The positives pass now: "I am not bound by any non-compete" ticked, PEP in a TEXT box "No", "Are you bound by any non-compete?" "No", Acme / "us" filled by data.
- `test_llm_fill_guard_table` (2 pins, lane M):
  - F6 `ground_items`: keeps R, Go, C, Word, Excel and Swift from the prose quote.
  - F9 `deterministic_pick("65", ["Level +65 items"])`: returns the option.
- The 4 earlier guard pins now pass on 4911696: G2d leaf, G2(d) restated, G3 C++, D-88.
### 2026-11-07 tester → software-engineer
TYPE: handoff
RE: Q-70 lane A tests (reply to your request)
BODY: Inbox.test.js updated (6 tests; no fake timers) and new web/tests/inbox-flow.test.js (19 tests, all Verify A bullets plus the Show N in Not interested notice). Full vitest: 298 passed | 1 skipped. No src defects found. Note: with every role dismissed and the section opened, the "all caught up" panel stays above the open section (src behaviour; pinned only as the section appearing).
STATUS: closed
### 2026-11-07 tester → coordinator
TYPE: handoff
RE: Q-70 lane B · branch `eng/Q-70-B-applications`
BODY: 4 failing Applications tests fixed as the engineer listed; new web/tests/applications-flow.test.js (22 tests: StatusSelect keyboard/pointer/Enter/Escape, Undo writes one more event (D-101), Active chip default + persistence + fallback, follow-up at 15 vs 13 days, Remove + Undo, Clear filters, search Escape, applications.js helpers). `cd web; npx vitest run` = 18 files, 301 passed | 1 skipped. No src defects found.
STATUS: done

### 2026-11-07 tester → coordinator
TYPE: handoff
RE: Q-70 lane C pins (test/Q-70-C-pins, base eng/Q-70-C-shell b511561 + C4 ea5f7d9 merged)
BODY: Before: 2 files failed, 5 tests failed / 332 passed (exactly the 5 listed). The 5 are fixed (App.test.js x4 for the Choose runs… button; Runs.test.js counts relaxed to 2..3 for the shell's doubled reload). New: web/tests/shell-job.test.js (19 tests: Verify C a-f plus announce and consume checks) and web/tests/keepalive.test.js (4: Inbox state kept and no refetch, Applications kept and refreshes on return, Profile not kept, Inbox keys off while away). After: `npx vitest run` 21 files, all passed. Mutation checks, each red as expected then src restored: shell onFinish reload removed (2 fail), toast removed (4), JobPill v-if false (4), starter listener removed (2), visibility ignored (2), useJob consume ignored (1), label for broken (1), choosable ignored (1), more-right never (2), KeepAlive off (2), Profile in KeepAlive (1), Inbox onDeactivated removed (1), Applications reload on activation removed (1). No src changes committed.
Note for the engineer: Inbox has no quiet refresh on activation (it uses the shell's data); only Applications reloads when it comes back. The App.vue comment says "Their onActivated hooks do the quiet refresh", slightly inexact for Inbox.
STATUS: open

### 2026-11-07 tester → coordinator
TYPE: handoff
RE: Q-70 lane E Overview pins (test/Q-70-E-pins; int/Q-70-ux ad2df54 + eng/Q-70-E-overview 8eecba3 merged)
BODY: Baseline on the merge: 21 failed / 339 passed (the 20 empty-hash cases plus "Choose runs… opens the picker", which also assumed an Inbox default). Step 5 applied (App.test.js beforeEach #/inbox, tab order, Overview default and unknown hash, brand link, ArrowLeft/Home; Applications.test.js). After: `npx vitest run` 24 files, 409 passed, 1 skipped. New: web/tests/overview.helpers.test.js (20, pure, now injected), web/tests/Overview.test.js (25, fakeApi + vi.setSystemTime), Runs.test.js describe "failed N tone" (3). helpers.js fakeApi gained `questions` and `applicationRows` options.
NAMING: the design's `overview.test.js` and `Overview.test.js` are the same file on Windows (case-insensitive), so the pure-helper file is `overview.helpers.test.js`. Please fix the name in overview_design.md §8.
MUTATIONS (22 source breaks, all red except one noted): nextUp ordering (2), run card while a job runs, responseRate (rejection-after-apply, withdrawn, rejected-from-Saved, null rate), pastWeek (dry runs, window), followUps order, lastRunState (threshold, dry runs), openStages unknown append, single primary CTA (all primary, none primary), Answer questions (wrong view value, no navigation), caught-up despite failed questions check, 409 text, Runs tone (always red, never red), `:disabled="starting"` removed. Survivor: removing the `if (starting.value) return` guard in Overview.vue start() stays green because the disabled button already blocks a second click; the guard is unreachable from the UI (harmless defence, not a defect).
SOURCE DEFECTS: none found. Notes: design §3 lists `waiting` in nextUp's arguments but the implementation reads it only in Overview.vue (fine); day counts use whole-day floor, so a run finished 15.9 days ago reads "15 days ago".
STATUS: open

### 2026-11-07 tester → coordinator
TYPE: handoff
RE: Q-71 expected salary pins (test/Q-71-pins on int/Q-70-ux 81c0950)
BODY: FieldInput.test.js gains "FieldInput salary (required, Q-71)" and "(nullable)" (14 tests: null/undefined show Amount, Currency, Period, Negotiable; typing emits {amount, SGD, monthly}; untouched emits nothing; nullable null/undefined show "I don't have one" checked with no grid, unticking emits the defaults, ticking emits null; no Negotiable when nullable). ApplicationDetails.test.js gains "Expected salary (Q-71)" (4: pay missing / no pay section / null show #f-pay-expected-salary-in, Save disabled until typed, PUT carries pay.expected_salary = {amount, SGD, monthly}; untouched is not written). Mutations red: `v-if="salary"` (8 fail), shownSalary without defaults (7), nullable ignored (2). Full run 24 files, 423 passed, 1 skipped.
### 2026-11-07 tester → coordinator (cc lanes S, I, F, researcher)
TYPE: handoff
RE: Q-60 / F-50 oracles WP-T0..T3 · branch test/Q-60-mail-oracles
BODY: Commits: 3a9e6d3 T0 alone (layering sets, read-only mailbox guard, SQL token fix, contracts oracles), 629573c T1 (FakeImap in `tests/mail_support.py`, `tests/fixtures/mail/rules_min.yaml`, 49-case golden set), 6379749 T2 (rules/gates/classifier, D-92 pins; the golden HireVue-live row is `assessment` per D-92), then T3 (matcher incl. E1, transitions rows 1-11, model prompt/parse) on top of a fast-forward to lane S 1ee2241. All T0-T3 oracles pass against lane S S1-S3, including the real-file half (config/mail_rules.yaml classifies the golden set the same as rules_min). Mutation checks (tenant strict subdomain, D-92, row 6 `>`, row 11c, MAX_TOKENS) each turn an oracle red. No lane S code defects found.
- Call shapes the oracles use (wrapped in `tests/mail_support.py`, so a rename is a one-line change there): `rules.load_rules(path)` / `RulesError` (its message or `entry_id` names the entry), `header_gate(h, rules, *, own, window_start, threads, employer_regs)`, `content_gate(h, body, rules, *, in_matched_thread)`, `classify`, `quote_around(text, start, end)`, `needs_model`, `platform_of`; `match.match(h, body, apps, rules)`, `tenants_from_hosts(tuple, rules)`, `compact`, `norm_company(name, suffixes)`, `norm_role`, `variants`; `transition.build_policy(statuses, raw)`, `decide(app, verdict, match, h, policy, *, candidates=())` (for AMBIGUOUS: candidates[0] as `app`, every candidate in matcher order); `model.user_prompt(h, body, max_chars)`, `parse(reply, h, body, model_id)`. All of these match lane S.
- Lane F (flow): `Change` has no candidates field; lane S added `transition.remaining_candidates(...)` for MS 8 row 4. The flow must call it to fill the suggestion's candidates (no oracle yet: flow tests). Row 4's "first candidate's reason" follows `match.candidates` order.
- Lane I (imapread): use `FakeMailServer.patched(module)`; every write command is refused (logged, then AssertionError). The layering write scanner is AST-based: no literal "STORE"/"COPY"/"MOVE"/"EXPUNGE"/"APPEND" strings in mailbox modules, and `.select(` needs `readonly=True`. LIST gives mailbox names as raw mUTF-7.
- Design notes for the Coordinator to confirm or amend in MS: (1) MS 8 row 2 "(or no target)" would catch portal_update before row 3; the oracles and lane S both let row 3 decide it. (2) The golden employers Northwind and Contoso use the reserved `.example` TLD, so the "first domain label" variant doesn't make every employer "example".
- Researcher: to try a draft rules file, set `JOBSCRAPER_TEST_MAIL_RULES=<path>` and run `-k mail_rules`.
STATUS: open

### 2026-11-07 tester → coordinator (cc lanes F, S, I)
TYPE: handoff
RE: Q-60 WP-T5, WP-T6, D-156/D-157/D-158 pins · branch test/Q-60-mail-oracles
BODY: Commits dbfbd14 T5 (`test_store_mail`, `test_mail_flow`, `test_config_mail`, `mail_flow_support`), d552680 T6 (`test_cli_mail`, `test_web_mail`, `web/tests/MailCard|MailSuggestions.test.js`, `web/tests/mailFake.js`), 33ea215 D-156 pins + neutral names (Grab/Sea → Claim/Ocean; rules_min `common_word_names: [ocean, claim]`; the review pins add those two words to the shipped file's list in memory), 1b351f3 D-157 pins, 31fe682 D-157(i) addendum + D-158 pins.
- Pins expected to fail until lanes F/S land: D-157 a (both), b, c, d, e, f, h, i; D-158 cursor-after-disconnect, backfilled accept, poison `Reason.INTERNAL`. D-158 locked-DB already passes.
- Defect (LOW, lane F): `config.py` `MailStatusConfig.from_raw` crashes with OverflowError on `.inf`/"inf"/"1e400" (it catches only TypeError/ValueError around `int(float(v))`). Pin: `test_config_mail_an_infinite_number_keeps_the_default`.
- Not covered: FL-2 (6) migration 4 to 5 (needs a v4 DB built with the old Store); the web child's job log is checked only for its `$ mail sync` line.
- Real company names still in tests outside mail (not common-word examples, left alone): `test_apply_contracts.py:407` ("Grab"), `test_applicant_form.py:310-312` ("shopee"). Coordinator's call.
STATUS: open

### 2026-11-07 tester -> coordinator
TYPE: handoff
RE: Q-71 lanes F+G pins and fixes (test/Q-71-FG-pins on int/Q-70-ux incl. 7772b5b)
BODY: Fixed: FieldInput salary Amount text/inputmode, error-summary wording, comments-note copy (ApplicationDetails.test.js), test_apply_flow_accounts consent case (PROFILE_INCOMPLETE + "consents.privacy_consent"; added a direct test of the sign-up "account terms" guard), test_filter CLI tests now use a temp config/profile (hermetic, no data/ read). New: tests/test_applicant_q71_pins.py (15: country validation/options, control/show_when/autocomplete JSON, consents only when True, documents_status names only, POST /check writes nothing), web/tests/ApplicationDetails.q71.test.js (41: Q71-02/03/04/05/06/07/09/11/12/13/14/15/16/17/18/20 plus the narrow minmax(0,1fr) layout check, which reads the SFC style text because jsdom has no layout). Mutations: 24 frontend source breaks all red (list in the report); 4 python breaks red.
SOURCE DEFECTS: none. Note: a profile with an empty section dict (e.g. `pay: {}`) shows as "Other keys in your file" with a rail entry; the server's real profiles carry null leaves, so it only appears for hand-edited files.
STATUS: open

### 2026-11-07 tester → coordinator
TYPE: handoff
RE: Q-72 (a, D-161) · branch test/Q-72-untracked-oracles (base int/Q-72-mail-untracked 10c6d01)
BODY: MS 16 "Row 7a oracles" pinned in `tests/test_mail_q72_pins.py` (15 tests) and one vitest case in `web/tests/MailSuggestions.test.js`. Expected values are from MS 3, 8 (row 7a and its note), 11.3 and 16, not from the build. Oracle -> test:
1. `test_q72_o1_the_d160_acknowledgement_over_three_closed_applications_asks_a_question` (AMBIGUOUS x3 -> SUGGEST maybe_untracked, to=None)
2. `test_q72_o2_a_single_closed_application_gives_the_same_reason` (STRONG and WEAK); flow: `test_q72_o2_flow_stores_a_suggestion_with_no_target_and_leaves_the_message_unattached` (evidence job_id/from/to NULL, candidates_json = the one app, mail_messages.job_id NULL, `suggested` +1, status unchanged, a later rejection in the same thread is also a suggestion)
3. `test_q72_o3_a_role_or_req_id_in_the_mail_keeps_a_late_duplicate_silent`
4. `test_q72_o4_a_thread_signal_keeps_it_silent`
5. `test_q72_o5_an_open_sibling_means_7a_never_fires` (ack: same_status when the sibling is first, terminal when last; rejection: several_applications offering only the sibling)
6. `test_q72_o6_mail_not_newer_than_every_candidates_last_event_stays_silent` (later, equal, plus a strictly-older control that must ask)
7. `test_q72_o7_the_d160_rejection_asks_unless_a_role_is_named`
8. `test_q72_o8_other_categories_are_unchanged` (withdrawn, posting_closed, kept_on_file, no_change, unknown without/with status words) and `test_q72_o8_interview_on_the_same_fixture_is_the_reopen_path_not_7a` (also assessment, offer)
9. `test_q72_o9_adding_the_application_afterwards_is_unchanged` (ack owner_newer, rejection backfilled); flow: `test_q72_o9_flow_backfilled_retest_is_unchanged`
10. `test_q72_o10_an_owner_added_status_is_custom_status_not_7a` (single: custom_status; mixed with closed candidates: several_applications)
Also `test_q72_contract_has_the_reason_its_text_and_is_a_suggestion` (MS 3: member, SUGGEST_REASONS, REASON_TEXTS, CONTRACT_VERSION 1). Web: `"maybe untracked" shows the company alone, ...` (company from candidates[0], reason text verbatim, Got it + Open in Gmail only, no select or candidate list).
- Pre-merge, expected FAIL (7 py + 1 vitest): contract (no `Reason.MAYBE_UNTRACKED`), o1, o2 pure, o2 flow (`suggested` is 0; decide gives NONE terminal), o6 (its control), o7, vitest (`.ms-app` is empty: no fallback to candidates[0].company in `appLine`). Pre-merge PASS by design (they guard the rows that must not move): o3, o4, o5, o8 x2, o9 x2, o10.
- Existing suite: `test_mail_contracts_module_is_the_design_listing` already fails on this base because the design lists `MAYBE_UNTRACKED` and contracts.py doesn't; it clears when the member and text are added.
- Flow fixture: Northwind stands in for Acme (one closed application, owner-closed 2026-10-13); the crafted ack names an untracked role, so signals are employer-only (probed: name_in_sender/subject/body).
STATUS: open

## 2026-11-07 handoff: Q-75 lanes I+J pins (branch test/Q-75-pins, base int/Q-75-wave3 b3908e1)
Baseline `cd web; npx vitest run` on b3908e1: 8 failed | 474 passed | 1 skipped (the 8 = the changes lanes I and J listed). After: 546 passed | 1 expected fail | 1 skipped, 29 files, green 3 runs in a row.
- Listed changes applied: m16 Clear list (inline confirm, no window.confirm), Runs x2 (failed-link title), Settings x2 (cadence wording), Applications/Profile times (local zone + UTC tooltip), ux1 kbd list (adds Z and ?).
- Time tests are machine-independent: `pinZone()` in web/tests/helpers.js sets process.env.TZ and throws if it did not take; Applications, Profile and q75-shell pin Asia/Singapore, unit cases also run America/New_York.
- shell-job "page becoming visible" made deterministic: `quiet()` flushes until the fake API sees no new request for 4 turns, `until()` waits on the request itself; visibilityState override is restored in `finally`. I could not make the old version fail even with 24 CPU burners, so the root cause is unproven; the new one cannot depend on a fixed flush count.
- New: web/tests/q75-shell.test.js (29: g-sequences for all 8 tabs, lapse at 1.5 s, typing/Ctrl/Meta ignored, switch off, `/`, ? sheet open/close/Esc/focus return/backdrop/Tab trap/inert/blocks Inbox keys/switch, Z undo incl. 60 s and X, Profile badge x4, Inbox write-error Dismiss, when/shortDate/exactTime in two zones) and web/tests/q75-pages.test.js (36: Clear list inline confirm, one set of counts, density/A-Z/chip, Runs error state incl. end to end through App, aborted reason, separators, num/matchLabel/runsPerDayLabel, Settings cycle keys + notices clear, theme incl. blocked storage).
- Mutation check (break src, red, `git checkout -- src`): 13/13 caught: g-window never lapses; go keys while typing; no Tab trap; unbounded Z window; Keep list not focused; arrow saves at once; when() in UTC; Runs error state removed; System theme leaves data-theme; Dismiss does nothing; badge counts answered; no inline ask; App clears runsError after shortlist load.
### defect (engineer, low): failed-link title/aria-label lacks thousands separators
Repro: Runs with `stats.companies_failed: 1234`. Expected title "1,234 companies could not be read in this run..."; actual "1234 companies ..." beside the visible "1,234" (`plural()` in format.js has no separator; lane J flagged it). Pinned as `it.fails` in q75-pages.test.js (goes red when fixed: convert to `it`).
### not covered
G41 `content-visibility`, G17 pinned action bar, G38 phone selected style, G31 touch-target sizes, N18 heading levels, and the `<meta theme-color>`: CSS/layout, not observable in jsdom; need the browser check lane I did by hand.
### addendum: Q-76 (D1-D5) merged into the same branch
Merged int/Q-75-wave3 (f56bb1c, includes Q-76) into test/Q-75-pins with no conflicts; the Q-75 pins stayed green after JobDetail was extracted from Inbox.vue.
- tests/test_q76_attempts.py (15): D1 last_attempts (newest per job by id, count, absent when none, empty map), D2 attempt_view (every kind, every ReasonCode has kind+text+hint, {detail} formatting, unknown reason/state/None never raise, key set = no job_log/end_url/tenant_host/resume_sha256/resume_file/confirmation), D3 /api/applications rows (last_attempt, attempts, posting; posting null off-shortlist; exactly one last_attempts call for 5 rows via a spy), D4 /attempts (newest first, [] and 200 for none or unknown job, bad id 422).
- web/tests/q76-detail.test.js (38): attemptLabel/modeLabel/needsInput, pill per kind + title + newest-only, needs-input is a button -> profile.view=details + #/profile (and end to end through App to the selected Application details tab), Details one row at a time with aria-expanded/controls/label, attempts Loading/empty/list (order, mode, time with UTC tooltip)/error + Try again, JobDetail facts/why/skills/JD/closed/no-description/Show more+less/collapse on job change/slots/titleId, posting cache (one fetch shared by two details, failed fetch kept, clear drops late answers, dropped after last unmount, kept alive across tab switches in App).
- helpers.js fakeApi: new `attempts` and `attemptsFail` options, GET api/applications/<id>/attempts, and /api/applications rows now carry last_attempt, attempts and posting like the server.
- Mutations (all red): pill opens the wrong Profile view; attempts error shown as empty; posting cache refetches; JD never cut; sent label changed; aria-expanded stuck; attempt_view leaks end_url (13/15); last_attempts takes the oldest (12/15); attempts route oldest first (14/15).
- shell-job root cause found (this corrects the earlier "unproven" note): the open tab (#/profile) is a lazily imported chunk whose mount starts its own `api/jobs/current` poll. Under load the chunk landed after the baseline was read, so 3 extra polls were counted as the "visible" one (saw `expected 4 to be 2`). The test now waits for `.profile-tab` (real-time deadline) before the baseline; 14 full-suite runs in a row green after the fix (it failed within 6 before).
### addendum: Q-44 / Q-73 / D-106 (int/Q-75-wave3 9f48f38 + cb76699 merged, no conflicts)
- tests/test_q44_refresh.py (46): R1 dates (every accepted form, Present/Current/Now/To date/Ongoing open end, Expected/Expected:/Exp./Anticipated prefix incl. single token = end only; "2021 – 2025", "Aug 2021 – Expected 2025", end-before-start and junk give (None, None, False)), R2 owner entries kept and never removed, R3 placeholders removed/updated, from_resume updated, unread dates kept only from a from_resume entry, promotion by employer, R4 languages/links/attested_skills and the rest identical after apply, contact.location never used, projects and org-less entries left out, description cut at a space before 500, R5 skills add-only/case-insensitive/template replaced/implied in not_on_resume + shared fixture tests/fixtures/skill_labels.json, R6 stable ids, `#2` suffix, only accepted ids applied, unknown ids reported, R7 order rule and no plan-only keys, R8 web (GET no_profile/none/stale/ready/unreadable; POST saves and the file validates; 409 changed/none/stale/unreadable/no_profile; unknown ids write nothing), Q-73 `/api/profile` years_experience/graduation, R9 cli (skip line when the model is down, `RuntimeError`-only line with no path, counts line, `_rel`, `refresh-resume` plan then `--yes`, argv has --plan-applicant).
- web/tests/q44-refresh.test.js (23): summary card lines and no path, 0/N years, 12 chips + "and k more", Details closed on success/open on failure, "Reading your resume…", panel rows (label, entry, before/after, kept without checkbox, skills, not-on-resume), default ticks, Save n count, POST {etag, accept}, saved line + Application details link, Not now (hash remembered), 409 changed/stale, 500, empty/stale/none/404 states, unavailable from the job log, reload after each job, skillLabel on the shared fixture.
- Expectation changes (follow design §4/§5, not loosened): test_web_control argv `profile --refresh --plan-applicant`; /api/profile exact key set + payload gain years_experience/graduation (the serve test now also sets them); Profile.test.js success note `Resume read: 3 skills, 2 job titles.` (`Profile refreshed.` pinned for the no-profile case). helpers.js: defaultProfile gains years_experience/graduation; fakeApi `refresh` option and GET/POST api/applicant/refresh.
- Mutations (red): drop "anticipated" (44/46); owner entries replaceable (44/46); "to date" not an open end (45/46); router ignores the etag (45/46); panel ticks everything; card shows data/ folder; Details open on success.
STATUS: open

## 2026-11-07 handoff: Q-35 WP-N6a oracles settled (branch eng/Q-35-N6a-flow, base 0b2516c)
Commits `test(apply): Q-35 N6a ...` 8c14bfd..e924d86 (tests/** only). The 19 failures from the engineer's result line are settled; two real code defects found (D1, D2), pinned by failing tests.
### Decisions, with the spec line behind each
- Draft loop tests: adopted as `tests/test_apply_flow_n6a.py` (12/12). Reviewed against LF §8 "The flow per step" and §11: warm-up before the browser, `transport_failed` -> model_unavailable "timed out on <step>", expired deadline -> error (§11 deadline paragraph), stop = capture then unanswerable_required, `fill_failed` on a required field -> validation_error, one corrective pass after Next errors, loop guard (step id + signatures), no fields on a non-review step, `fill: rules` keeps the old path. Sound; only the hard-coded path was fixed.
- T4 stubs (`test_apply_flow_llm.py`, 5 bodies, build plan WP-T4 "Do" + N6a "Done when"), all over the REAL `apply_flow.run`, `fill_page`, Workday navigator (subclassed only to `open` a local fixture URL) and headless Edge on 127.0.0.1, scripted `FakeFillBackend`: (1) wd_b stop: unanswerable_required "Address Line 2", exactly one capture (profile_gap, contact.address_line2, verbatim label), page snapshot identical, 0 input events, 0 Next clicks (LF §8 step 7, §11, M9/TR-7); (2) failed warm-up: model_unavailable, factory count 0, navigator.open never called, no vault/account rows, `llm_fill.keep_alive` reaches the warm-up (None when unset) (LF §13.1, §11 table); (3) page timeout: "timed out on my_information", nothing captured or typed (LF §11 "Not captured"); (4) loop guard on two tiny synthetic pages `tests/fixtures/apply/flow_llm/{stay,empty}.html`: "shown again" and "no fields on my_information" (LF §8 loop guard, §11 table); (5) wd_a 7-step replay: ready_to_submit, data-submit-count 0, one audit row per field per step, no unknown/ungrounded rows, nothing captured, prompts pass `assert_no_secrets` (LF §16 Flow). Cache replay and pre-Submit scan stay gated for N6b (`_Run.pre_submit_scan` is an ASSUMED name; change `N6B_GATE` only).
- Workday F3 pin (`test_apply_flow_accounts`): flipped as written. Under the default `fill: llm` Workday is no longer unsupported_ats: it reaches the warm-up and, with no model, ends model_unavailable before Edge, vault, account row and answers (LF §11 table). Kept `fill: rules` pin: still unsupported_ats, same "nothing opened or created" assertions. GAP (not a test): apply_design has no rule that a DRY RUN skips account creation (sign-up runs in dry runs by design: §10.2, spike S-5 "stop at Review"), and the flow has no "owner-triggered" flag; every attempt is started by the owner's CLI/web action. So no such pin can be written without a spec change. What is pinned: warm-up precedes the account wall, so an unavailable model never leaves an account. Needs an architect decision if the owner wants dry-run to avoid creating accounts.
- Questions oracles: the employer IS the by_employer key (company "Shopee", `visa_status.by_employer.shopee` picks [citizen], options Citizen/PR/Others), so tier 3 correctly answers VISA ("memory:extra.visa_status"). Not a code defect. Fixture changed to `_extra_without_visa()` (all other entries kept, so the redaction checks keep their secrets). New pin `test_a_by_employer_pick_answers_the_visa_field_for_its_own_employer_only`: Shopee -> not captured; another employer with the same extra -> captured (override not applied to the wrong employer). `-k apply_flow_questions` 13/13.
- `test_apply_e2e`: `edge_acfg` now defaults `fill="rules"` (caller can pass `fill="llm"`), so the 12 old-path e2e pass again (12/12). Added `test_fill_llm_dry_run_fills_the_greenhouse_form_with_a_scripted_model_and_stops_at_review` (real flow + Greenhouse navigator + reader + fill_page + Edge, scripted model, owner answers in `extra:`): the harness allows it. It FAILS today on D1 (and would on D2). With CHOICE_TYPES patched to include TYPEAHEAD in a scratch run it fills 24 fields and reaches ready_to_submit, so the script itself is sound.
- F7 oracle (`test_on_workday_choose_entry_runs_before_the_account_wall`): re-gated on `fill_page`, `_fill_services`, `_Run.body_llm` (what N6a built), not N6b, and written: scripted navigator with an account wall (sign-up -> emailed code through the fake IMAP -> candidate home -> reopen). Asserts open -> choose_entry -> account_wall -> sign_up -> enter_code, then a second open and a second choose_entry before the first Next. Passes.
- Fixture fix (test-owned): tests/fixtures/apply/greenhouse/form.html react-select look-alike now closes its menu on Escape like the real component; before, stale menus stayed open for 150 ms and the reader's option lists bled into the next field (Gender listed the how-heard options). Old-path e2e unaffected.
### Defects found (to software-engineer; pins in `tests/test_apply_n6a_defect_pins.py`, both fail now)
- D1 HIGH (blocks the live Greenhouse path under the default `apply.fill: llm`): `contracts.CHOICE_TYPES = {DROPDOWN, MULTI_CHOICE, RADIO}` but `page.py` types every react-select / combobox / prompt as TYPEAHEAD. All deterministic option fits (resolve.fit_decline / fit_kind / fit_bool, declarations, facts) are gated on CHOICE_TYPES and return None for TYPEAHEAD. Repro: `resolve.fit_decline(FormField("g","Gender",FieldType.TYPEAHEAD,True,options=(Male, Female, Non-Binary, "I don't wish to answer")))` -> None; as DROPDOWN -> the decline option. Flow repro: `python tests/run_tests.py -k apply_e2e` (llm test): unanswerable_required, log "profile rule identity.gender: no offered option fits" and Location (City) "G2e: no_option_fits". Expected: same fits as a dropdown. Actual: a required Gender/EEO question stops the attempt. Suggested fix: add TYPEAHEAD to the choice check where the field has options (not to CHOICE_TYPES blindly: check guards.py:261 and facts.py:497/1067 uses).
- D2 HIGH: Greenhouse's resume `<input type=file style=display:none>` behind an "Attach" button is not read as a FILE field (page.py candidate loop: `vis(el) || vis(cont)`), so the resume is never attached under `fill: llm` (no audit row, `files.resume` empty; the form marks it required). Repro: `-k apply_n6a_defect_pins`. Expected: a required FILE field "Resume/CV". N6b's pre-Submit scan would catch the empty field, but the upload itself is missing.
- Observation (low, N6b): `cache_get`/`cache_put` are no-ops, as the engineer said; the job-row key `job["id"]` vs `job_id` note stands.
STATUS: open

## 2026-11-07 handoff: Q-35 N6a D-167 pins and the llm e2e audit keys
- Audit key: llm_fill_design §3.1 "Key" says `<step>:<automation id or html id or slug(label)>`, so `form:first_name` is the specified key and the old bare-name assertion was wrong. Fixed in test_apply_e2e (asserts form:first_name/last_name/email/phone/resume filled). `-k apply_e2e` 13/13.
- `tests/test_apply_fit_type.py` (9 tests, 6 of the architect's 7 groups; 9/9): g1 parity with DROPDOWN (fit_decline, fit_enum decline/male, fit_bool both ways, fit_text, fit_country, fit_number, bool_shaped, _extra_fit choice, kind_for CHOICE and YES_NO, memory tier), g2 search typeahead unchanged, g3 declaration gate + disability, g4 Workday Category > Leaf, g5 memory key stays "typeahead", g6 fit_type not a dataclass field, follows options, CHOICE_TYPES unchanged.
- Group 7 mutation checks run by hand without touching src (scratch patch): fit_decline reading f.type -> g1 red ("Gender: TYPEAHEAD with options gives None"); fit_type ignoring options -> g2 red. Both red, control green.
STATUS: open
