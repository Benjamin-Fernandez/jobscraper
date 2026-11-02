# Build-plan insert for Q-30 (D-74, D-75): paste into `docs/planning/apply_build_plan.md`

The architect wrote this as planner for Q-30. The scope guard blocks `docs/planning/`, so the Coordinator (or the planner) pastes it into `apply_build_plan.md`, as this file says. Design: `questions_design.md` (**QD §n**); `apply_design.md` (**AD §n**); contracts v4; ADR-0005.

## A. Header line (add under the D-70 revision line)

> **Revised for D-74/D-75 (Q-30, architect acting as planner, 2026-11-03):** the applicant API (WP-W1, minus `applicant init`, which stays in M21 as WP-W1b) and the Profile → Application details form (WP-W5) move into M20. New "Questions from applications" (F-13) WPs Q0–Q4, the D-75 work-rights WPs P9 and A04, and two new M20 lanes, **Q** (Python) and **U** (Vue): §2.5. Design: `docs/architecture/questions_design.md` (QD), contracts v4, ADR-0005.

## B. §2 lane table: add two rows

| Lane | Branch | Own files (only these) | Shared-file blocks |
|---|---|---|---|
| **Q** questions + profile API (D-74/D-75) | `eng/M20-Q-questions` | `src/jobscraper/apply/questions.py` (new), `src/jobscraper/web/routers/applicant.py` (new), `src/jobscraper/web/routers/questions.py` (new); lane P's finished files `src/jobscraper/applicant.py`, `src/jobscraper/apply/resolve.py`, `config/applicant.example.yaml` pass to lane Q | `store.py` Q-block; `config.py` Q-block; `config/config.yaml` Q-block; `apply_flow.py` Q-block (WP-Q1b only, after lane B merges) |
| **U** profile UI (D-74) | `eng/M20-U-profile-ui` | `web/src/tabs/Profile.vue`, `web/src/components/ApplicationDetails.vue`, `web/src/components/QuestionsInbox.vue`, `web/src/components/FieldInput.vue` (all new except Profile.vue) | `web/src/api.js` U-block (end of file) |

## C. New section §2.5 (insert before "## 3. M20 integration and gate")

### 2.5 Lanes Q and U: Application details and questions from applications (D-74, D-75)

**Slots.** At most 3 engineer lanes and 4 agents. Lane B (B7–B12) keeps its slot. Lane Q starts in the next free engineer slot. Lane U takes lane V's slot when lane V parks: after V3, V4 waits for lane B to merge and V5–V7 wait for S-5. When lane V resumes, U pauses at a WP boundary, or V waits for U, whichever is closer to done. The tester's WP-Q0 runs in the tester slot. The researcher's WP-A04 runs when an agent slot is free (it is one file).

**Order.** Lane Q: P9 → W1 → Q2 → Q1a → Q3 → (lane B merged) Q1b. Lane U: W5 (needs W1's payload shape, which is fixed in QD §9.1, so it can start from fixtures at once) → Q4 (needs Q3's shape, QD §9.2). Tester Q0 goes first (each test file is skip-clean until its module exists).

**Interleaving with lanes B and V.** Lane Q doesn't touch any lane B or lane V file until Q1b. Its `store.py`/`config.py`/`config/config.yaml` blocks are appended at the end of the file, after B's and V's, and the Coordinator resolves the textual merge as usual. WP-Q1b adds a small Q-block to `apply_flow.py` after lane B has merged (B7, B9, B11). If V4 is merged first, Q1b rebases on it; if not, V4 rebases on Q1b (both are small, separate blocks). Q2 changes `rule_id` on unknown answers from "" to the matched tier-2 key: the tester checks that no lane B oracle (WP-B9 e2e) asserts the empty string.

#### WP-Q0 · Oracles and fixtures for Q-30 (tester)
- **STATUS:** TODO
- **Inputs:** QD §13 (every row), §6.1, §8, §9; contracts v4.
- **Files:** `tests/test_apply_d70.py` (one line), `tests/test_applicant_form.py`, `tests/test_web_applicant.py`, `tests/test_apply_resolve_rules.py` (D-75 cases), `tests/fixtures/apply/questions_d75.yaml`, `tests/test_apply_resolve_memory.py`, `tests/test_apply_questions.py`, `tests/test_web_questions.py`, `tests/test_apply_flow_questions.py`, `tests/test_privacy.py` (one path), `web/tests/ApplicationDetails.test.js`, `web/tests/QuestionsInbox.test.js`, `tests/fixtures/apply/applicant_extra.sample.yaml` (synthetic `extra` entries for every kind, one `by_employer`).
- **Depends on:** this design merged.
- **Lane:** tester (`test/Q-30-questions-oracles`).
- **Do:** **first** change `test_contract_version_is_3` to assert `CONTRACT_VERSION >= 3` (this blocks the merge of `arch/Q-30-dynamic-fields`). Then write the QD §13 oracles, each skip-clean until its module or function exists (`needs`).
- **Verify:** `python tests/run_tests.py -k apply_d70`
- **Done when:** that passes with contracts v4; the new files import and are skip-clean; `python tests/run_tests.py -k nf01` still passes.
- **Requirements:** F-10, F-11, F-12, F-13, F-32, NF-01, NF-02.

#### WP-A04 · Work-rights rows in `config/questions.yaml` (D-75)
- **STATUS:** TODO
- **Inputs:** QD §8.2 (the `country_bool` kind and the D-75 scope), §8.3 (minimum synonyms, the `without` rule).
- **Files:** `config/questions.yaml`.
- **Depends on:** WP-P9 merged (the loader must accept `country_bool`).
- **Lane:** researcher (`research/Q-30-work-rights`).
- **Do:** replace the four rows `singapore_status.authorised_to_work.SG/.US` and `requires_sponsorship.SG/.US` with two `kind: country_bool` rows keyed `singapore_status.authorised_to_work` and `singapore_status.requires_sponsorship`. Include at least the QD §8.3 synonyms and no country excludes; put the `without …` phrases only on the authorised row, and give the sponsorship row `exclude: [without]`. Leave the residency and work-pass rows untouched.
- **Verify:** `python -c "import yaml; d=yaml.safe_load(open('config/questions.yaml',encoding='utf-8')); q={e['key']:e for e in d['questions']}; assert not [k for k in q if k.startswith(('singapore_status.authorised_to_work.','singapore_status.requires_sponsorship.'))]; a=q['singapore_status.authorised_to_work']; s=q['singapore_status.requires_sponsorship']; assert a['kind']==s['kind']=='country_bool'; need_a={'right to work','eligible to work','authorized to work','work authorization','without sponsorship'}; need_s={'require sponsorship','visa sponsorship','now or in the future require','work permit required','require an employment pass'}; assert need_a<=set(a['synonyms']) and need_s<=set(s['synonyms']); assert 'without' in (s.get('exclude') or []) and not any('without' in x for x in s['synonyms']); print('work rights ok')"`
- **Done when:** it prints `work rights ok` and `python tests/run_tests.py -k apply_resolve_rules` passes on the real file.
- **Requirements:** F-32 (tier 2), F-33 (D-75).

#### WP-P9 · Work-rights defaults and the `country_bool` tier-2 kind (D-75)
- **STATUS:** TODO
- **Inputs:** QD §8.1 (`default` key, validation message, `work_rights`, `work_rights_text`, REQUIRED_PATHS change, template lines), §8.2 (detection, the `us` rule, aliases, job/residence country, the `without` rule, conflict stop, no tier 5, source strings); contracts v4 `ResolveContext.job_country`.
- **Files:** `src/jobscraper/applicant.py`, `src/jobscraper/apply/resolve.py`, `config/applicant.example.yaml`.
- **Depends on:** WP-Q0 (the D-75 oracles), lane P merged (it is).
- **Lane:** Q.
- **Do:** validation of `default`; `work_rights`, `work_rights_text`; drop the two `.SG` REQUIRED_PATHS; append `work_rights_text` to `grounding_text`; `"work_rights"` in the tier-5 APPLICANT JSON; loader support for `kind: country_bool` (only the two map keys; no `value_map`/`yes_if`); `label_countries`; the §8.2 value rules; template lines.
- **Verify:** `python tests/run_tests.py -k apply_resolve_rules`
- **Done when:** QD §13 D-75 oracles 1–15 pass with the fixture rules file; `python tests/run_tests.py -k apply_contracts` stays green.
- **Requirements:** F-10, F-32, F-33 (D-75).

#### WP-W1 · Applicant API, FORM schema, etag, commented backup, `extra` validation (moved from M21)
- **STATUS:** TODO
- **Inputs:** QD §3.1 (save behaviour, etag, backup, unknown keys, unreadable file), §3.2 (FORM table and `form_json`), §6.1 (`extra` rules), §9.1 (GET/PUT shapes, 409/422), §11 (redaction skips `extra` metadata).
- **Files:** `src/jobscraper/applicant.py`, `src/jobscraper/web/routers/applicant.py`.
- **Depends on:** WP-P9 (same file, same lane).
- **Lane:** Q.
- **Do:** `FormItem`/`FormGroup`/`FORM`/`form_json`, `etag`, `save(..., keep_commented_copy=True)`, `extra` validation, the `redaction_values` skip list; router per QD §9.1 (foundation imports only). `applicant init`/`from_resume` are **not** in this WP (M21, WP-W1b).
- **Verify:** `python tests/run_tests.py -k applicant`
- **Done when:** `test_applicant_form.py` and `test_web_applicant.py` pass (FORM covers every template leaf, backup once, 409 on a stale etag and on an unreadable file, 422 names the path, unknown keys round-trip); `-k layering` green.
- **Requirements:** F-10, F-11, NF-01, NF-02.

#### WP-Q2 · Tier 3 reads `extra` (answer memory brought forward)
- **STATUS:** TODO
- **Inputs:** QD §6.2 (the lookup steps, the employer-specific skip, scope, fit per kind, source/rule_id, the order change, `rule_id` on unknown), ADR-0005.
- **Files:** `src/jobscraper/apply/resolve.py`.
- **Depends on:** WP-W1 (`extra` validation shape), WP-Q0.
- **Lane:** Q.
- **Do:** `_extra_answer` before the existing memory lookup; the `resolve_field` order change; `rule_id` on final unknowns.
- **Verify:** `python tests/run_tests.py -k apply_resolve_memory`
- **Done when:** QD §13 `apply_resolve_memory` oracles pass; `-k apply_resolve` (all resolver files) stays green.
- **Requirements:** F-12, F-13, F-32, F-39.

#### WP-Q1a · Capture module, store tables and config
- **STATUS:** TODO
- **Inputs:** QD §4.2 (qualifying fields, reasons, `CANONICAL_PATHS`, kind, sensitive), §5 (sig, key rules 1–5, slug, naming prompt/schema/parse), §7 (DDL, methods), §7.2 (config); contracts v4 `CapturedQuestion`, `QuestionKind`, `QuestionReason`, `QuestionStatus`.
- **Files:** `src/jobscraper/apply/questions.py` (new), `src/jobscraper/store.py` (Q-block: DDL appended at the end of `SCHEMA` after `-- M20 questions (questions_design §7)`, and a section `# ---------------- questions (M20 lane Q) ----------------` at the end of `Store`), `src/jobscraper/config.py` (Q-block), `config/config.yaml` (Q-block: `question_capture:` at the end of the file).
- **Depends on:** WP-Q2.
- **Lane:** Q.
- **Do:** pure functions `kind_for`, `capture`, `signature`, `slug_key`, `naming_user_prompt`, `NAMING_SYSTEM`, `NAMING_SCHEMA`, `parse_naming`, `assign_key`; the store methods of QD §7.1; `QuestionCaptureConfig`. No `SCHEMA_VERSION` change.
- **Verify:** `python tests/run_tests.py -k apply_questions`
- **Done when:** QD §13 `apply_questions` oracles pass (incl. no model call for a sensitive question and no profile value in any naming prompt); `-k layering` green.
- **Requirements:** F-13, NF-02, NF-03, NF-04.

#### WP-Q3 · `/api/questions` (list, answer, dismiss, retry)
- **STATUS:** TODO
- **Inputs:** QD §9.2 (endpoints, the answer algorithm steps 1–4, mode, busy), §7.1 (`question_groups`, `retry_candidates`), AD §14.2 (`apply` job argv).
- **Files:** `src/jobscraper/web/routers/questions.py` (new).
- **Depends on:** WP-Q1a, WP-W1; `apply` job kind from WP-B8 for retry (until lane B merges, the retry test uses a fake `JobManager`).
- **Lane:** Q.
- **Do:** endpoints as specified; foundation imports and `apply.contracts` only.
- **Verify:** `python tests/run_tests.py -k web_questions`
- **Done when:** QD §13 `web_questions` oracles pass.
- **Requirements:** F-13, F-38 (retry), NF-01.

#### WP-Q1b · Capture in the orchestrator
- **STATUS:** TODO after lane B merged (B7, B9, B11).
- **Inputs:** QD §4.1 (the two capture points, all qualifying fields, dry run too, the log line, exceptions never change the outcome), §5.2 rule 4 / §5.3 (naming call through the attempt's backend, timeout, per-attempt cap).
- **Files:** `src/jobscraper/apply_flow.py` (Q-block: `_capture_questions` at the end of the file plus one call at each of the two `unanswerable_required` raise points).
- **Depends on:** WP-Q1a, lane B merged into `personal` and lane Q rebased on it.
- **Lane:** Q.
- **Do:** as QD §4.1.
- **Verify:** `python tests/run_tests.py -k apply_flow_questions`
- **Done when:** QD §13 `apply_flow_questions` oracles pass; `-k apply_flow` (all flow files) stays green.
- **Requirements:** F-13, F-38, NF-02, NF-09.

#### WP-W5 · Profile → Application details form (moved from M21)
- **STATUS:** TODO
- **Inputs:** QD §3.2 (FORM groups and labels), §3.3, §10.1 (sub-views, remembered view, count), §10.2 (copy, verbatim), §10.3 (widgets, accessibility), §9.1 (payloads).
- **Files:** `web/src/tabs/Profile.vue`, `web/src/components/ApplicationDetails.vue` (new), `web/src/components/FieldInput.vue` (new), `web/src/api.js` (U-block).
- **Depends on:** WP-Q0 (component test); WP-W1 for the live API (the component test uses JSON payloads).
- **Lane:** U.
- **Do:** the sub-view control; "Needed before auto-apply"; the full generic form from `form`; tags; meter; Save with etag; 409/422 handling; comments note; group 15 rendering of `extra` with Remove; group 16 read-only.
- **Verify:** `npm --prefix web test -- tests/ApplicationDetails.test.js`
- **Done when:** the component test passes; `cd web; npx vitest run` green. The SPA is built only by the Coordinator in the main checkout.
- **Requirements:** F-10, F-11.

#### WP-Q4 · Questions from applications (UI)
- **STATUS:** TODO
- **Inputs:** QD §10.1 (placement between Missing and the form), §10.2 (card, chips, scope control, toasts, ready banner, auto-mode confirm, empty state, answered list), §10.3, §9.2 (payloads).
- **Files:** `web/src/components/QuestionsInbox.vue` (new), `web/src/components/ApplicationDetails.vue` (mount it), `web/src/api.js` (U-block).
- **Depends on:** WP-W5 (same lane), WP-Q0.
- **Lane:** U.
- **Do:** as specified; after Save, refresh both the questions list and the form (the etag changes).
- **Verify:** `npm --prefix web test -- tests/QuestionsInbox.test.js`
- **Done when:** the component test passes; `cd web; npx vitest run` green.
- **Requirements:** F-13, F-38.

## D. §3 WP-I1: add step 5b

> 5b. (D-74/D-75) Merge `arch/Q-30-dynamic-fields` together with WP-Q0's `test_apply_d70.py` fix. Lane Q's P9 → W1 → Q2 → Q1a → Q3 merge before lane B if ready (they don't touch B's files except the appended blocks). Then WP-A04. Lane U (W5, Q4) merges whenever it is green; the Coordinator builds the SPA in the main checkout after it. Q1b merges after lane B (and before or after V4, whichever is ready). Smoke-check after lane U merges: Profile → Application details loads against a copy of the DB on port 8768, a save writes `applicant.commented-backup.yaml` once, and an answer appears in `extra`.

M20 gate addition (step 7, owner): at least one dry run stops on an unanswered required question; the owner answers it in Profile → Application details → Questions from applications; Retry reaches `ready_to_submit` with the answer shown in `apply show` as `memory:extra.<key>`.

## E. §4.3 M21: change W1 and W5

- WP-W1 heading becomes **"WP-W1 · (moved to M20, §2.5)"**. Add **WP-W1b · `applicant init` and `from_resume`** (M21, lane W): Files `src/jobscraper/applicant.py`, `src/jobscraper/cli.py` (W-block); Inputs AD §5.5; Verify `python tests/run_tests.py -k applicant_init`; Done when `init` writes entries with `from_resume: true` from a fixture master and refuses an existing file.
- WP-W5 heading becomes **"WP-W5 · (moved to M20, §2.5)"**.
- WP-W2 depends on WP-W1 (now in M20, so it's satisfied). WP-W6 also shows "Answer it in Profile" and **Retry** on a `failed(unanswerable_required)` attempt (AD §14.4, D-74 bullet), using `POST /api/questions/retry`.
- §4 table, lane W own files: remove `web/routers/applicant.py` (M20 lane Q).

## F. §5 critical path: add

> **Questions chain (D-74/D-75):** design merged + WP-Q0 → P9 → W1 → Q2 → Q1a → Q3 ∥ lane U (W5 → Q4) → (lane B merged) Q1b → gate addition. Not on the longest path; Q1b waits on lane B.

## G. §6 tests table: add rows

| WP | Test file (needle) | Fixtures |
|---|---|---|
| Q0 | `tests/test_apply_d70.py` (`apply_d70`): version ≥ 3 | — |
| P9, A04 | `tests/test_apply_resolve_rules.py` (`apply_resolve_rules`): D-75 cases | `tests/fixtures/apply/questions_d75.yaml`, then `config/questions.yaml` |
| W1 | `tests/test_applicant_form.py` (`applicant_form`), `tests/test_web_applicant.py` (`web_applicant`) | synthetic profile with and without comments; `applicant_extra.sample.yaml` |
| Q2 | `tests/test_apply_resolve_memory.py` (`apply_resolve_memory`) | `applicant_extra.sample.yaml` |
| Q1a | `tests/test_apply_questions.py` (`apply_questions`) | scripted fake backend; a copied fixture DB |
| Q3 | `tests/test_web_questions.py` (`web_questions`) | TestClient, copied fixture DB, fake JobManager |
| Q1b | `tests/test_apply_flow_questions.py` (`apply_flow_questions`) | fake adapter with two required unknowns |
| W5, Q4 | `web/tests/ApplicationDetails.test.js`, `web/tests/QuestionsInbox.test.js` | JSON payloads per QD §9 |

## H. §7 coverage: change rows

| Req | WPs |
|---|---|
| F-10 | P2, P3, P5, P8, **P9, W1, W5** (M20), W1b (M21) |
| F-11 | P2, P3, P8, **W1, W5** (M20) |
| F-12 | P4 (lookup), **Q2** (`extra`); M22 writes `extra` |
| **F-13** (proposed) | **Q0, Q1a, Q1b, Q2, Q3, Q4** |
| F-32 | … + **P9, A04, Q2** |
| F-33 | … + **P9, A04** |
| F-38 | … + **Q1b, Q3, Q4** |
