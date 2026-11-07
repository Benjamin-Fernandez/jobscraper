# LLM-driven form filling: build plan (D-78, Q-35 + Q-40)

**Stage D** for `llm_fill_design.md` (cited **LF §n**). Author: architect (acting as planner for this delta), 2026-11-03. **Status:** amended after stage E (review `docs/reviews/Q-35-design.md`, tester TR-1–TR-13, D-81–D-83). Each WP's STATUS below is current; **RUNNING** WPs carry an "Amendment delta" line (also in `comms/outbox/architect.md`).
Conventions as `docs/planning/apply_build_plan.md` §0: a WP is ≤ ~1 day, ≤ ~8 files, one lane, one `Verify:` command; engineers don't write `tests/**`; the tester's test files are skip-clean until their module exists; NF-08 (copied DB, port 8768); real employer pages only in `--dry-run` except the owner-approved gate submissions (D-77, D-83).
Rule ids: locks **L1–L7**, list handling **LL1–LL4**, guards **G1–G12**, entries **E1–E7** (LF reading guide).

## 0. What changes in the existing plan

| Existing WP | Under D-78 |
|---|---|
| WP-V2 accounts half (`accounts list/add/export-edge`) | **unchanged** → runs as WP-N1 |
| WP-V4 identity, accounts, mail in the orchestrator | **kept, smaller** → WP-N4: drop the `applied_on_tenant` entry rule and the review notes (`annotate_answers` stays in the store, used by the review check in WP-N6b) |
| WP-V5 Workday tenant, open, Apply choice, account wall | **changed** → WP-N2: a `SiteNavigator`; entry rule reversed (Autofill with Resume first); S-5 differences (a)–(f) folded in |
| WP-V6 Workday widgets | **superseded** by WP-R2 (generic `widgets.py`) and `entry_sections` in WP-N2 |
| WP-V7 Workday wizard (named steps, review parse) | **superseded**: `step_id`/`next_step`/`submit`/`after_submit` → WP-N2; required scan and review check → WP-R3 (`page.scan_required`) and WP-N6b |
| WP-Q1b capture in the orchestrator | **changed** → WP-N6a: one capture point (the page stop), questions from `PageField`s with qualified labels (WP-M5) |
| WP-B11 prefill policies (built) | **retired** by guards G8/G9 (LF §7); code removed in WP-C1 |
| WP-B12 MyGreenhouse `prefill`/`read_values` | **reused**: `prefill` becomes `choose_entry` (WP-N3, with the `pre_import` snapshot); `read_values` is replaced by the generic reader |
| WP-F1 Workday fixtures from S-5 | **redefined** → WP-T1 (sanitised S-5b pages + fake model replies) |
| WP-A03 `yes_if`, WP-A04 `country_bool` rows | **kept** (locks L4, L5 depend on them; A04 is needed before the gate, review F5) |
| WP-S6 MyGreenhouse spike | unchanged |
| WP-I1 M20 merge order and gate run | **redefined** by §7 below (D-83) |
| WP-L1 Lever, WP-L2 Ashby (M21) | **navigators only** (LF §9.3, §9.4): `open`, `choose_entry` (Ashby: take "autofill from resume"), `next_step`, `submit`, `after_submit`; no field mapping. Their fill is the generic path |
| WP-F2 Lever/Ashby recordings (M21) | **kept**; the tester also writes `fields.json` + `reply.json` per page (WP-T1 format) |
| WP-W8 "What I told this employer" (audit view) | **kept, wider**: shows the new `apply_answers` columns `evidence`, `shown_json`, `shown_origin`, `entry` (LF §14), and the G9 "unverified site value" note. Depends on WP-N5 |
| "WP-F3" (cited by the first draft, LF §15 O-2) | **dropped**: O-2 is closed by WP-N6b (`resume_entries`) |

## 1. Lanes (≤ 3 engineers at once + tester)

| Lane | Branch | Own files | Shared-file blocks |
|---|---|---|---|
| **M** model side (pure, fake backend) | `eng/Q-35-M-llmfill` | `src/jobscraper/apply/facts.py`, `locks.py`, `guards.py`, `llm_fill.py` (new); `src/jobscraper/apply/plan.py`, `resolve.py`, `questions.py` | `backends.py` M-block (keep_alive, `warm`); `store.py` Q-block (WP-Q5 only); `web/routers/questions.py`, `web/src/components/QuestionCard.vue` (WP-Q5) |
| **R** page side (Playwright on fixtures) | `eng/Q-35-R-page` | `src/jobscraper/apply/page.py`, `widgets.py`, `pagefill.py` (new) | none |
| **N** navigation + flow | `eng/Q-35-N-workday` | `src/jobscraper/apply/ats/workday.py` (new), `apply/ats/greenhouse.py`, `apply/ats/__init__.py`, `apply/accounts.py` | `apply_flow.py` N-block; `store.py` N-block; `config.py` + `config/config.yaml` (`llm_fill`, `fill`, timeouts); `cli.py` V-block (accounts); `tailor_flow.py` N-block (`resume_entries`, WP-N6b) |
| **T** tester | `test/Q-35-llm-fill-oracles` | `tests/**`, `web/tests/**` | — |

Disjointness: M and R share no file; N touches `greenhouse.py`, which only lane B wrote (merged). `store.py` gets two separate appended blocks (N5 and Q5); the Coordinator resolves the textual merge (`04_team.md` §2). Lanes M and R build against contracts v5 (with `FillServices`) and fakes; WP-N6a/N6b integrate after both merge.

Order: **M:** M1 → M2 → M3 → M4 → M5 → Q5. **R:** R1 → R2 → R3. **N:** N1 → N2 → N3 → N4 → N5 → (M and R merged) N6a → N6b. **T:** T0 → T1 → T2 → T3 → T4 → T5 (each file skip-clean until its module lands); T6 optional. Cleanup WP-C1 after the M20 gate.

## 2. Tester

#### WP-T0 · Contract v5 oracles
- **STATUS:** RUNNING
- **Amendment delta:** add oracles for the additive v5 fields: `ResolveContext.resume_entries == ()` and `other_employers == ()` by default; `AttemptContext.pre_import`/`uploaded` default to empty dicts that are not shared between instances; `PageOutcome.transport_failed is False` by default; a minimal class with every `FillServices` member passes `isinstance`; `ModelDecision.via` defaults to `"page"`.
- **Inputs:** contracts v5 (version comment), LF §2, §8 (pinned signatures).
- **Files:** `tests/test_apply_contracts_v5.py`.
- **Do:** `CONTRACT_VERSION >= 5`; `ReasonCode.MODEL_UNAVAILABLE` in `REASON_TEXTS`; `ValueOrigin` site values equal `AnswerSource` values; `SITE_VALUE_SOURCES ⊇ PREFILL_SOURCES`; `GENERIC_LABELS` are already `norm_label`-normal; a minimal class implementing every `SiteNavigator` member passes `isinstance`; `Answer` still constructs positionally with 6 args; plus the delta.
- **Verify:** `python tests/run_tests.py -k apply_contracts_v5`
- **Done when:** green on the amended contracts; the full suite stays green.

#### WP-T1 · Sanitised S-5b fixtures and the fake model
- **STATUS:** RUNNING
- **Amendment delta:** (a) `wd_a`'s My Information page keeps the phone, address and postal-code inputs **pre-filled with the sample profile's values** (`applicant.sample.yaml`), for the privacy oracle (H4); (b) `tests/llm_fill_support.py`'s fake backend routes on the exported constants (`SYSTEM`, `SECOND_SYSTEM`, `PICK_SYSTEM`, `RECHECK_SYSTEM`) and keys replies on `group|question` parsed from the `FIELDS (JSON):` block, which is the last block before the fixed final line (TR-4); it records every prompt; (c) one stub page where choosing "Yes" reveals a required textarea (H7), for T3.
- **Inputs:** LF §16; `spikes/S-5b_llm_workday.md`.
- **Files:** `tests/fixtures/apply/llm_fill/wd_a/<NN-step>/{page.html,fields.json,reply.json}`, `.../wd_b/...` (My Information only, with the required "Additional Address"), `tests/fixtures/apply/llm_fill/README.txt`, `tests/llm_fill_support.py`.
- **Do:** rebuild each page with every text value replaced by the sample's values, employer names → "Example Employer", requisition ids and tenant names → placeholders, scripts removed; keep every `data-automation-id`, `aria-*`, `role`. Replies: one per call, including the S-5b error patterns (LF §16). Grep the committed tree for the owner's values before committing.
- **Verify:** `python tests/run_tests.py -k llm_fill_fixtures`
- **Done when:** both tenants' pages load; no personal value or employer name is present.

#### WP-T2 · Pure oracles: facts, locks, guards, prompt
- **STATUS:** READY (skip-clean)
- **Inputs:** LF §4 (L1–L7 and their order), §5 (catalogue, `relevant`, `today_sg`), §6.2–§6.5 (constants, prompt order, schema, follow-ups with `via`, `redact`/`s_values`/`current_set`), §7 (G1–G12, module constants, answer mapping), §10 E2 (overlap coefficient), §12.1 (qualified labels incl. the context-less form).
- **Files:** `tests/test_llm_fill_facts.py`, `tests/test_llm_fill_locks.py`, `tests/test_llm_fill_guards.py`, `tests/test_llm_fill_model.py`.
- **Do:** the LF §16 rows for privacy, G2 (scope, relevance, polarity, entry facts, empty fact), G3 copy/compose, recheck, G5 (optional Yes/No too; `second_opinion: false` → unknown), G7, G8/G9 (decision level), G11, G12, L1 (only uploaded-this-attempt kept; one-FILE page-text clause; cover letter never the resume), lock order (M1), clock (`today_sg`), cache key/`facts_used_hash`; plus: the schema's `ref` enum equals the chunk's allowed refs; FACTS identical across all calls and FACTS+RESUME across non-entry chunks (TR-11); transport failure → `PageOutcome.transport_failed`-ready signal (`BackendError` raised by `ask`); L7 negated declaration; word-bounded G7 ("Sussex", "embrace" don't match).
- **Verify:** `python tests/run_tests.py -k llm_fill`
- **Done when:** files exist, skip-clean before lane M's modules, green after.

#### WP-T3 · Reader, widget and page-fill oracles
- **STATUS:** RUNNING
- **Amendment delta:** (a) widgets: strict read-back for **every** family (a typeahead that picked another suggestion → False), optional search miss clears the typed text (M14); Enter is sent only to a prompt search input not inside a form with a submit control (M8); `reset()` per family, False for a radio group (H3); (b) **new file `tests/test_apply_pagefill.py`** (owns R3's Verify, TR-9): zero fill/clear/reset/delete/add calls when step 7 stops (M9, TR-7); the revealed-textarea stub gets a second round and stops when unanswerable (H7); `scan_required` finds an empty required field; G9 actions applied (clear, untick); `ctx.uploaded` recorded after an upload; deadline ≤ 0 before a chunk → stop before typing; `classify` called before step 9 and before the corrective pass (services fake records calls). (b) may land as a second commit after T3's first half.
- **Inputs:** LF §3.1, §3.2, §8.
- **Files:** `tests/test_apply_page_reader.py`, `tests/test_apply_widgets.py`, `tests/test_apply_pagefill.py`, stubs `tests/fixtures/apply/llm_fill/stubs/{prompt_categories.html,listbox_error.html,dates.html,reveal.html}`.
- **Do:** expected `fields.json` per fixture page (labels, kinds, required, options incl. `Category > Leaf`, shown values, date parts, honeypot dropped); the delta.
- **Verify:** `python tests/run_tests.py -k apply_page_reader` and `-k apply_widgets` and `-k apply_pagefill`
- **Done when:** skip-clean before lane R, green after.

#### WP-T4 · Navigator and flow oracles
- **STATUS:** READY (skip-clean)
- **Inputs:** LF §8 (flow, loop guard, pre-Submit scan), §9.1, §9.2, §11 (deadline, `transport_failed`); AD §10.5; S-5 signed-out recordings (no personal values) for the account pages.
- **Files:** `tests/test_workday_nav.py`, `tests/test_greenhouse_nav.py`, `tests/test_apply_flow_llm.py`, `tests/test_store_fill_cache.py`; `tests/apply_flow_support.py` (pin `apply.fill: rules` for lane B's flow tests until WP-C1; TR-6).
- **Do:** Workday: entry choice order, account wall wins over the progress bar, `click_filter` sibling click, step id prefix strip **with `_<N>` for duplicate titles** (M7), `entry_sections`, Next never clicks Submit, confirmation URL. Greenhouse: `choose_entry` fills `ctx.pre_import` before the MyGreenhouse click (M3). Flow: dry run over `wd_a` with the fake model → `ready_to_submit`; a stop on `wd_b` → `unanswerable_required` + one captured question with `profile_gap`; `model_unavailable` before the browser and on `transport_failed`; loop guard compares step id **and** field signatures; Greenhouse pre-Submit scan stops an empty required field (`validation_error`, no click); deadline per ATS (420/900) excludes a faked IMAP wait; caps/duplicate unchanged; cache: `fill_cache` replay with zero model calls on retry, a changed cited fact → a miss (M4); `apply_flow.run(now=...)` pins the clock.
- **Verify:** `python tests/run_tests.py -k workday_nav` (and `-k greenhouse_nav`, `-k apply_flow_llm`, `-k store_fill_cache`)
- **Done when:** skip-clean, then green as lanes land.

#### WP-T5 · Review findings F1, F3, F4 and page capture
- **STATUS:** READY (skip-clean)
- **Inputs:** LF §11, §12; QD §4.2.
- **Files:** `tests/test_apply_resolve_memory.py` (F1 cases appended), `tests/test_apply_resolve_rules.py` (F4), `tests/test_questions_variants.py` (F3), `tests/test_apply_questions_page.py` (M5's `capture_page`: qualified labels incl. the context-less `| @step#n` form, reasons per guard, transport unknowns never captured; TR-9), `web/tests/QuestionCard.test.js` (F3: cleared variant sends `[]`).
- **Verify:** `python tests/run_tests.py -k questions_variants` and `-k apply_questions_page` and `cd web; npx vitest run tests/QuestionCard.test.js`
- **Done when:** green after WP-M2/M5/Q5.

#### WP-T6 · Model eval (optional; not in the suite)
- **STATUS:** READY (low priority; after T1)
- **Inputs:** LF §16 (TR-12).
- **Files:** `tests/evals/llm_fill.py`.
- **Do:** run the real local model over the sanitised fixtures; report per page: S leaks (threshold 0), ungrounded fills (threshold 0), unknowns, seconds; replaces the AD tier-5 eval. Run by hand (`python tests/evals/llm_fill.py`), never by `run_tests.py`.
- **Verify:** `python tests/evals/llm_fill.py --dry` (loads fixtures, no model call)
- **Done when:** the eval runs against Ollama and prints the thresholds.

## 3. Lane M (model side)

#### WP-M1 · Fact catalogue, `fact_value`, relevance, entry matching, privacy values, clock
- **STATUS:** READY
- **Inputs:** LF §5.1–§5.3, §6.5 (`s_values`), §10 E2, §13.3 (hashes); AD §5.3, §7.3.2; D-79.
- **Files:** `src/jobscraper/apply/facts.py`.
- **Depends on:** contracts v5 (amended).
- **Do:** signatures as LF §8: `fact_catalogue`, `facts_text(facts)` (fixed order), `fact_value`, `relevant` (+ `FACT_TITLE_SYNONYMS`), `match_entries` (overlap coefficient, unique best), `entry_blocks(rctx, profile)` (from `rctx.resume_entries`, else profile entries), `s_values`, `today_sg`, `field_sig`, `inputs_hash`, `facts_used_hash`; `extra` entries filtered by the generic-label and other-employer rules (G12).
- **Verify:** `python tests/run_tests.py -k llm_fill_facts`
- **Done when:** no S value appears in `facts_text` for the sample profile; every ref maps as the oracles expect; E2 matching handles a parser-junk entry; `today_sg` rolls over at 16:00Z.
- **Requirements:** F-32, NF-02.

#### WP-M2 · Locks; F1 and F4 in the resolver
- **STATUS:** READY
- **Inputs:** LF §4 (L1–L7, order, L1 upload rule, L1b), §12.1 (incl. the context-less qualified label), §12.3; QD §6.2; AD §7.5.
- **Files:** `src/jobscraper/apply/locks.py`, `src/jobscraper/apply/plan.py` (`is_generic`, `qualified_label(label, description, context, *, step, ordinal)`), `src/jobscraper/apply/resolve.py` (`_extra_answer` F1 guard; `label_countries` F4).
- **Depends on:** WP-M1.
- **Do:** `lock_page(fields, rctx, rules, *, today, uploaded) -> dict[str, Answer]` in the M1 order (an UNKNOWN from L4/L5 or L3/L7 consults L6); L7 negation rule; F1: generic labels match only qualified + employer-scoped; F4: all-caps `US` → {US, job_country}.
- **Verify:** `python tests/run_tests.py -k llm_fill_locks`
- **Done when:** lock oracles pass and `-k apply_resolve` stays green except the F1/F4 oracles the tester changed in T5.
- **Requirements:** F-12, F-13, F-32, F-33, D-75, D-76.

#### WP-M3 · Guards
- **STATUS:** READY
- **Inputs:** LF §7 (G1–G12, module constants, answer mapping), §10 E3–E7; AD §7.7 (`grounded`).
- **Files:** `src/jobscraper/apply/guards.py`.
- **Depends on:** WP-M1.
- **Do:** `decide(fields, locks, decisions, facts, rctx, *, matches, second, today) -> Decision` (pure; `Decision` = answers, `unknown_required`, `deletes`, `adds`, G9 actions); notes name the guard, never a value; answer mapping incl. tier LLM + `fill:v2` for model-chosen facts.
- **Verify:** `python tests/run_tests.py -k llm_fill_guards`
- **Done when:** every G row's oracle passes; notes carry no values.
- **Requirements:** F-32, F-33, F-39, NF-02.

#### WP-M4 · The model call (+ backend keep_alive and warm-up)
- **STATUS:** READY
- **Inputs:** LF §6 (chunks, constants, prompt order with the FIELDS block last, schema, follow-ups and `via`, `redact`), §11 (length cut, malformed JSON, transport), §13.1–§13.2.
- **Files:** `src/jobscraper/apply/llm_fill.py`, `src/jobscraper/backends.py` (M-block: optional `keep_alive` keyword on `complete`, sent only when given; `warm(backend, keep_alive)`).
- **Depends on:** WP-M1.
- **Do:** export `SYSTEM`, `SECOND_SYSTEM`, `PICK_SYSTEM`, `RECHECK_SYSTEM`, `FILL_PROMPT_VERSION`; `chunks`, `user_prompt`, `schema`, `ask`, `pick_option`, `recheck_entry` (copy check), `second_opinion`, `redact` (whole user prompt, every call); record `model`, `prompt_hash`, tokens, seconds; never log prompt text. Measure `prompt_eval_ns` of a repeated prefix (LF §13.2) and note it in the handoff.
- **Verify:** `python tests/run_tests.py -k llm_fill_model`
- **Done when:** with the fake backend: prompts in the fixed order, no S value in any prompt, schema enums right, a cut reply is split and re-asked once, malformed JSON retried once, `BackendError` propagates.
- **Requirements:** F-32, NF-02, NF-03, NF-09.

#### WP-M5 · Capture from the page (F1)
- **STATUS:** READY
- **Inputs:** LF §11, §12.1; QD §4.2, §5.
- **Files:** `src/jobscraper/apply/questions.py`.
- **Depends on:** WP-M2, WP-M3.
- **Do:** `capture_page(fields: list[PageField], answers, ctx, rules) -> list[CapturedQuestion]` (qualified `label_norm`; reasons from guard notes; transport unknowns never captured); keep `capture()` for the old path until WP-C1.
- **Verify:** `python tests/run_tests.py -k apply_questions_page`
- **Done when:** the T5 capture oracles pass; `-k apply_questions` stays green.
- **Requirements:** F-13.

#### WP-Q5 · Review F3: variant answers and cleared picks
- **STATUS:** READY
- **Inputs:** LF §12.2; QD §9.2; review Q-30 F3.
- **Files:** `src/jobscraper/web/routers/questions.py`, `src/jobscraper/store.py` (Q-block: `set_questions_status` by row ids), `web/src/components/QuestionCard.vue`; generic-label answers saved employer-scoped (LF §12.1).
- **Depends on:** WP-M5.
- **Verify:** `python tests/run_tests.py -k questions_variants`
- **Done when:** T5 F3 oracles (Python and vitest) pass; `-k web_questions` stays green.
- **Requirements:** F-13.

## 4. Lane R (page side)

#### WP-R1 · Generic page reader
- **STATUS:** RUNNING
- **Amendment delta:** none required. Optional if not yet written: `read_page(..., rng=None)` (TR-4) and first-read origins from `ctx.pre_import` (LF §3.3) — otherwise both go into WP-R3.
- **Inputs:** LF §3.1, §3.3; spike `llmfill.py` `READER_JS`, `read_fields`, `_expand_categories`, `ERRORS_JS`.
- **Files:** `src/jobscraper/apply/page.py`.
- **Depends on:** contracts v5; WP-T1 fixtures for the Verify.
- **Do:** `read_page(page, *, scope, sections, origin) -> list[PageField]`; `field_errors(page) -> dict[key, str]`; `entry_sections(page, scope) -> list[EntrySection]`; `page_text(page, scope)`.
- **Verify:** `python tests/run_tests.py -k apply_page_reader`
- **Done when:** every fixture page reads to its `fields.json`.
- **Requirements:** F-34, D-78.

#### WP-R2 · Widget families
- **STATUS:** RUNNING
- **Amendment delta:** strict read-back for every family, incl. typeahead/combobox (M14); an optional search miss clears the typed text (M14); the Enter rule (M8: prompt search input only, never inside a `<form>` with a submit control); `reset(page, loc) -> bool` per family (H3). Whatever isn't in R2 when it merges moves to WP-R3.
- **Inputs:** LF §3.2; AD §8.2 primitives; spike `fill`, `_choose_prompt`, `_type_date`, `file_decision`, `drive.wd_click`.
- **Files:** `src/jobscraper/apply/widgets.py`.
- **Depends on:** WP-R1.
- **Do:** registry of families (detect/options/fill/read/reset), `click(page, loc)` with the `click_filter` fallbacks, date equivalence, multi-select pills, upload read-back by file name; the delta.
- **Verify:** `python tests/run_tests.py -k apply_widgets`
- **Done when:** T3 widget oracles pass.
- **Requirements:** F-34.

#### WP-R3 · `fill_page` and the required scan
- **STATUS:** READY (builds against `FillServices` with fakes for locks/llm_fill/guards until lane M merges; T3's `apply_pagefill` oracles)
- **Inputs:** LF §8 steps 1–13 and the pinned signatures, §3.3, §10 E3–E7, §11 (deadline, transport), §13.3 (cache calls).
- **Files:** `src/jobscraper/apply/pagefill.py`; `src/jobscraper/apply/page.py` (`scan_required`, plus any R1 delta left over); `src/jobscraper/apply/widgets.py` (any R2 delta left over).
- **Depends on:** WP-R2; lane M merged for the real-module oracles.
- **Do:** `fill_page(page, nav, ctx, rctx, services) -> PageOutcome`; entry actions only after `decide`; nothing changed on a page that stops at step 7; `classify` before step 9 and before the corrective pass; `deadline_left()` before each chunk and before step 9; revealed-field rounds (≤ `max_reveal_rounds`); `scan_required`; `ctx.uploaded` after an upload; `transport_failed` on `BackendError`/timeout.
- **Verify:** `python tests/run_tests.py -k apply_pagefill`
- **Done when:** on `wd_a` My Experience with the fake model: junk entry deleted, description replaced by the recheck, a wrong location rejected; on `wd_b`: stop with zero page changes; the reveal stub passes.
- **Requirements:** F-32, F-34, F-39, NF-06.

## 5. Lane N (navigation + flow)

#### WP-N1 · CLI `accounts` (= WP-V2 accounts half, unchanged)
- **STATUS:** RUNNING (no amendment delta)
- **Inputs, Files, Do, Verify, Done when:** as `apply_build_plan.md` WP-V2 (`python tests/run_tests.py -k accounts_cli`); `match_url` from `ats/workday.py` once WP-N2 lands (regex A until then).

#### WP-N2 · Workday navigator
- **STATUS:** RUNNING
- **Amendment delta:** `step_id` appends `_<N>` when another progress item has the same title (M7); `choose_entry` honours `apply.workday_entry: manual`. If N2 merged without them, they go into WP-N6a.
- **Inputs:** LF §9.1; AD §9.4.1, §9.4.3, §9.4.4, §9.4.11, §9.4.12; `spikes/S-5_workday.md` (a)–(f); spike `drive.py`.
- **Files:** `src/jobscraper/apply/ats/workday.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** contracts v5; `widgets.click` (WP-R2) — until it merges, a private copy of the click fallback, removed in WP-N6a.
- **Do:** every `SiteNavigator` member; register `"workday"`.
- **Verify:** `python tests/run_tests.py -k workday_nav`
- **Done when:** T4 Workday oracles pass on the recorded pages.
- **Requirements:** F-31, F-35, F-37.

#### WP-N3 · Greenhouse as a navigator
- **STATUS:** RUNNING
- **Amendment delta:** `choose_entry` stores the form's shown values in `ctx.pre_import` (audit key → shown text) **before** clicking MyGreenhouse (M3). If N3 merged without it, it goes into WP-N6a.
- **Inputs:** LF §9.2; AD §9.1, §9.1.1 (steps 1–5 kept as `choose_entry`).
- **Files:** `src/jobscraper/apply/ats/greenhouse.py`.
- **Depends on:** contracts v5.
- **Do:** add `precheck`, `choose_entry` (wraps the existing `prefill`), `step_id`, `scope`, `entry_sections` (generic default), keeping the old `AtsAdapter` methods until WP-C1.
- **Verify:** `python tests/run_tests.py -k greenhouse_nav`
- **Done when:** T4 Greenhouse oracles pass and `-k greenhouse` stays green.
- **Requirements:** F-31, F-34.

#### WP-N4 · Identity, accounts and mail in the orchestrator (= WP-V4, reduced)
- **STATUS:** RUNNING (no amendment delta; the IMAP wait stays outside the fill deadline, LF §11)
- **Inputs:** `apply_build_plan.md` WP-V4 minus the `applied_on_tenant` entry rule and review notes; AD §10.2, §10.5, §11.5, §4.2.
- **Files:** `src/jobscraper/apply/accounts.py`, `src/jobscraper/apply_flow.py` (N-block), `src/jobscraper/store.py` (N-block: `accounts_for_tenant`, `applied_on_tenant`, `annotate_answers`).
- **Depends on:** WP-N2, WP-P8 (merged).
- **Verify:** `python tests/run_tests.py -k apply_flow_accounts`
- **Done when:** the WP-V4 "Done when" list, minus the two dropped items.
- **Requirements:** F-35, F-36, F-37, NF-02, NF-06.

#### WP-N5 · Store and config for the new path
- **STATUS:** RUNNING
- **Amendment delta:** `fill_cache` per LF §14 (key adds `inputs_hash`; new column `facts_used_hash`; `decision_json` holds the `ModelDecision` only); config adds `attempt_timeout_workday_s: 900`, `llm_fill.max_reveal_rounds: 2`, `apply.workday_entry`, and `keep_alive` is optional (unset = not sent). If N5 merged with the old shape, WP-N6b migrates it (the table has no rows outside tests yet).
- **Inputs:** LF §13.4, §14.
- **Files:** `src/jobscraper/store.py` (N-block: the four `apply_answers` columns in `_migrate`, `fill_cache` DDL + methods, `SCHEMA_VERSION` + 1), `src/jobscraper/config.py`, `config/config.yaml`.
- **Depends on:** none.
- **Verify:** `python tests/run_tests.py -k store_fill_cache`
- **Done when:** migration adds the columns to an existing DB copy; cache put/get/purge round-trip; `ApplyConfig.llm_fill` defaults as LF §13.4.
- **Requirements:** F-39, NF-07.

#### WP-N6a · Flow integration: the FILLING loop, capture, warm-up, deadline, transport
- **STATUS:** READY once lanes M and R are merged into `personal` and lane N rebases (not before)
- **Inputs:** LF §8 (flow part, loop guard), §11 (capture, `model_unavailable`, degradation table, deadline), §13.1 (warm-up), §13.4; QD §4.1.
- **Files:** `src/jobscraper/apply_flow.py` (N-block), `src/jobscraper/cli.py` (apply backend with `llm_fill.num_ctx`).
- **Depends on:** WP-M5, WP-R3, WP-N2–N5.
- **Do:** behind `apply.fill: llm` (default): warm-up before Edge (fail → `model_unavailable`); `choose_entry` → `ctx.prefill` (+ `pre_import`); one `FillServices` per attempt (`run(..., now=None)` clock; `deadline_left` from the per-ATS timeout, IMAP wait excluded; `classify` from `browser.py`); per-step `fill_page`; audit rows with the new columns; `transport_failed` → `model_unavailable`; `_capture_questions` from `capture_page` then `unanswerable_required`; `fill_failed` → `validation_error`; errors-after-Next retry once; loop guard (step id + field signatures); any N2/N3 delta not merged; `apply.fill: rules` keeps the old path.
- **Verify:** `python tests/run_tests.py -k apply_flow_llm`
- **Done when:** the T4 flow oracles except cache and pre-Submit scan pass; every existing `-k apply_flow` file stays green.
- **Requirements:** F-13, F-30–F-39, NF-06, NF-07.

#### WP-N6b · Flow integration: pre-Submit scan, review check, cache, resume entries, other employers
- **STATUS:** READY after WP-N6a
- **Inputs:** LF §5.2 (`resume_entries`, `PROFILE_INCOMPLETE`), §7 G12 (`other_employers`), §8 (before Submit), §13.3, §14.
- **Files:** `src/jobscraper/apply_flow.py` (N-block), `src/jobscraper/tailor_flow.py` (N-block: `resume_entries(cfg) -> tuple[tuple[str, str, str], ...]`, the `master_text` pattern: cached master only, never parses, never raises, `()` on a miss), `src/jobscraper/store.py` (N-block: only if N5 needs the cache migration).
- **Depends on:** WP-N6a.
- **Do:** fill `rctx.resume_entries` and `rctx.other_employers` (watchlist names + sighting employers, this employer and its aliases removed); the `fill_cache` wiring (`cache_get`/`cache_put` on `FillServices`, purge older than 30 days at start); the pre-Submit `page.scan_required` + review check (LF §8), then submit unchanged.
- **Verify:** `python tests/run_tests.py -k apply_flow_llm`
- **Done when:** all T4 flow oracles pass (cache replay, pre-Submit scan); `-k tailor` and every `-k apply_flow` file stay green.
- **Requirements:** F-30, F-32, F-39, NF-06, NF-09.

## 5b. Q-45: composed texts (cover letter, "why join"; LF §19, D-86 F9)

Contracts: apply v5 additive (`QuestionReason.COMPOSE_NEEDED`, `AnswerSource.COMPOSED`, `ResolveContext.job_title`, `AttemptContext.composed`/`composed_files`, `PageOutcome.compose_needed`), tailor v2 additive (`ComposeRequest`, `ComposeResult`, `COMPOSE_VERSION`, four `IssueCode`s). Not a gate item: the gate runs with `apply.compose.enabled: false` (compose targets become questions).

#### WP-K1 · Tailor compose call and checks
- **STATUS:** READY
- **Inputs:** LF §19.4, §19.5; `tailor_design.md` §7.4 (UPGRADE_WORDS), §7.5 (summary-check style), §8.1 (`numbers`, `facts`).
- **Files:** `src/jobscraper/tailor/compose.py` (new), `src/jobscraper/tailor/validate.py` (`UPGRADE_WORDS` constant only, if absent), `src/jobscraper/tailor_flow.py` (T-block: `compose(cfg, req, *, backend, redact) -> ComposeResult` using the cached master only, `error="no master"` on a miss; `write_letter(text, path, fmt) -> str`).
- **Depends on:** tailor contracts v2.
- **Do:** `COMPOSE_SYSTEM`, prompt in the fixed order, `redact` applied to the whole user prompt, checks C1–C7, one retry with a `FIX:` line, no logging of text.
- **Verify:** `python tests/run_tests.py -k tailor_compose`
- **Done when:** with a fake backend and a synthetic master: each of C1–C7 rejects its probe; a clean reply passes; no S value in the recorded prompt; the retry happens once.
- **Requirements:** F-22 (truthfulness reused), F-32, NF-02.

#### WP-K2 · Compose targets on the apply side (lane M files)
- **STATUS:** READY once `int/Q-35-M` is merged into `personal`
- **Inputs:** LF §19.1, §19.2, L8, §6.1, G3.
- **Files:** `src/jobscraper/apply/questions.py` (export `compose_needed`; reason `COMPOSE_NEEDED` now real; notes `off` / `failed check` / `no master`), `src/jobscraper/apply/locks.py` (L8), `src/jobscraper/apply/llm_fill.py` + `guards.py` (compose targets never in the page schema; G3's compose rule only for other free TEXTAREAs), `web/src/components/QuestionCard.vue` (chip and hint copy, LF §19.6).
- **Depends on:** contracts v5 (this delta).
- **Verify:** `python tests/run_tests.py -k llm_fill_locks` and `-k apply_questions_page`
- **Done when:** T7's apply-side oracles pass; `-k llm_fill` stays green.
- **Requirements:** F-13, F-32.

#### WP-K3 · Compose in `fill_page` and the flow
- **STATUS:** not READY (after WP-R3, WP-N6a, K1, K2)
- **Inputs:** LF §8 step 7b, §19.2, §19.3, §13.4 (`apply.compose`).
- **Files:** `src/jobscraper/apply/pagefill.py` (step 7b, FILE upload from `composed_files`), `src/jobscraper/apply_flow.py` (N-block: §19.3 loop, files, capture on failure, `rctx.job_title`), `src/jobscraper/config.py`, `config/config.yaml`.
- **Verify:** `python tests/run_tests.py -k apply_flow_compose`
- **Done when:** off → `compose_needed` capture with the page unchanged; on → text filled and audited; a failing draft → capture; `transport` → `model_unavailable`; no "compose loop".
- **Requirements:** F-13, F-32, F-39, NF-02.

#### WP-T7 · Compose oracles (tester)
- **STATUS:** READY (skip-clean)
- **Files:** `tests/test_tailor_compose.py`, `tests/test_apply_flow_compose.py`, plus rows in `tests/test_llm_fill_locks.py` (L8) and `tests/test_apply_questions_page.py` (reason and notes).
- **Do:** LF §16 "Compose" row; C1–C7 probes on a synthetic master (a JD-only skill → `FACT_ADDED`; "led" absent from the master → `VERB_UPGRADE`; the sample phone → `PRIVATE_VALUE` with no value in the detail; a watchlist employer → `OTHER_EMPLOYER`; "[Name]" → `PLACEHOLDER`).
- **Verify:** `python tests/run_tests.py -k compose`

## 6. After the gate

#### WP-C1 · Cleanup (contracts v6, breaking; covered by ADR-0006)
- **STATUS:** TODO after the M20 gate.
- **Do:** remove `apply.fill: rules`, `AtsAdapter`'s fill-side methods, `PrefillPolicy`/`PREFILL_POLICY`, `apply_prefill_policy` and friends, Greenhouse's schema-to-fields mapping (keep `precheck`), tier-1 tagging and tier 5 in `resolve.py`; the tester retires the matching oracles (incl. the `fill: rules` pin) in the same WP pair.
- **Verify:** `python tests/run_tests.py`
- **Done when:** the full suite is green with the old path gone.

## 7. M20 gate (Coordinator) on the new path (= WP-I1; D-81, D-83)

1. Merge order: T0 → (M ∥ R ∥ N1–N5) → N6a → N6b → smoke `personal` (live app starts; `python -m jobscraper doctor`).
2. **Greenhouse: 5 dry runs** on 5 postings → `ready_to_submit`. Read each audit (`apply show`) **row by row**: no wrong answer, no S value outside its field, every `resume_import` required value marked grounded (G8), no "unverified site value" on a required field. Record the attempt time of each (≤ 4 min typical; D-81).
3. **Workday:** postings need **fresh owner approval** (the spike's earlier approvals don't carry over; the spike already submitted one). Per posting: a dry run to Review; read the audit row by row; then the owner-approved automatic submission (D-70, D-77 as read under D-83). Record the attempt time (≤ 900 s excluding the IMAP wait; D-81).
4. A stop on an unknown required field → the question appears in the Profile tab → the owner answers → Retry proceeds, with the uncited decisions replayed from the cache (QD gate addition).

## 8. Critical path

T1 fixtures → R1 → R2 → R3 ∥ M1 → M2/M3 → M4 → M5 → N6a → N6b → gate. N2–N5 run beside it. Longest: lane R (Playwright on fixtures) and the N6 integration.
