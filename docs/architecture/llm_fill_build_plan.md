# LLM-driven form filling: build plan (D-78, Q-35 + Q-40)

**Stage D** for `llm_fill_design.md` (cited **LF §n**). Author: architect (acting as planner for this delta), 2026-11-03. **Status: READY TO BUILD** after the Coordinator merges `arch/Q-35-llm-fill` (contracts v5) and the tester's T0.
Conventions as `docs/planning/apply_build_plan.md` §0: a WP is ≤ ~1 day, ≤ ~8 files, one lane, one `Verify:` command; engineers don't write `tests/**`; the tester's test files are skip-clean until their module exists; NF-08 (copied DB, port 8768); real employer pages only in `--dry-run` except the owner-approved gate submissions (D-77).

## 0. What changes in the existing plan

| Existing WP | Under D-78 |
|---|---|
| WP-V2 accounts half (`accounts list/add/export-edge`) | **unchanged** → runs as WP-N1 |
| WP-V4 identity, accounts, mail in the orchestrator | **kept, smaller** → WP-N4: drop the `applied_on_tenant` entry rule and the review notes (`annotate_answers` stays in the store, now used by LF §8's review check) |
| WP-V5 Workday tenant, open, Apply choice, account wall | **changed** → WP-N2: a `SiteNavigator`; entry rule reversed (Autofill with Resume first); S-5 differences (a)–(f) folded in |
| WP-V6 Workday widgets | **superseded** by WP-R2 (generic `widgets.py`: prompt, segmented date, listbox) and `entry_sections` in WP-N2 |
| WP-V7 Workday wizard (named steps, review parse) | **superseded**: named-step tables and the review parse retire; `step_id`/`next_step`/`submit`/`after_submit` move to WP-N2; review check → WP-N6 |
| WP-Q1b capture in the orchestrator | **changed** → part of WP-N6: one capture point (the page stop), questions built from `PageField`s with context-qualified labels (WP-M5) |
| WP-B11 prefill policies (built) | **retired** by guard G8 (LF §7); code removed in WP-C1 |
| WP-B12 MyGreenhouse `prefill`/`read_values` | **reused**: `prefill` becomes `choose_entry` (WP-N3); `read_values` is replaced by the generic reader |
| WP-F1 Workday fixtures from S-5 | **redefined** → WP-T1 (sanitised S-5b pages + fake model replies) |
| WP-A03 `yes_if`, WP-A04 `country_bool` rows | **kept** (locks L4, L5 depend on them; A04 is needed before the gate, review F5) |
| WP-S6 MyGreenhouse spike | unchanged |

## 1. Lanes (≤ 3 engineers at once + tester)

| Lane | Branch | Own files | Shared-file blocks |
|---|---|---|---|
| **M** model side (pure, fake backend) | `eng/Q-35-M-llmfill` | `src/jobscraper/apply/facts.py`, `locks.py`, `guards.py`, `llm_fill.py` (new); `src/jobscraper/apply/plan.py`, `resolve.py`, `questions.py` | `backends.py` M-block (keep_alive, `warm`); `store.py` Q-block (WP-Q5 only); `web/routers/questions.py`, `web/src/components/QuestionCard.vue` (WP-Q5) |
| **R** page side (Playwright on fixtures) | `eng/Q-35-R-page` | `src/jobscraper/apply/page.py`, `widgets.py`, `pagefill.py` (new) | none |
| **N** navigation + flow | `eng/Q-35-N-workday` | `src/jobscraper/apply/ats/workday.py` (new), `apply/ats/greenhouse.py`, `apply/ats/__init__.py`, `apply/accounts.py` | `apply_flow.py` N-block; `store.py` N-block; `config.py` + `config/config.yaml` (`llm_fill`, `fill`, timeouts); `cli.py` V-block (accounts) |
| **T** tester | `test/Q-35-llm-fill-oracles` | `tests/**`, `web/tests/**` | — |

Disjointness: M and R share no file; N touches `greenhouse.py`, which only lane B wrote (merged). `store.py` gets two separate appended blocks (N5 and Q5); the Coordinator resolves the textual merge (`04_team.md` §2). Lanes M and R build against contracts v5 with fakes; WP-N6 integrates after both merge.

Order: **M:** M1 → M2 → M3 → M4 → M5 → Q5. **R:** R1 → R2 → R3. **N:** N1 → N2 → N3 → N4 → N5 → (M and R merged) N6. **T:** T0 → T1 → T2 → T3 → T4 → T5 (each file skip-clean until its module lands). Cleanup WP-C1 after the M20 gate.

## 2. Tester

#### WP-T0 · Contract v5 oracles
- **STATUS:** READY
- **Inputs:** contracts v5 (version comment), LF §2.
- **Files:** `tests/test_apply_contracts_v5.py`.
- **Do:** `CONTRACT_VERSION >= 5`; `ReasonCode.MODEL_UNAVAILABLE` in `REASON_TEXTS`; `ValueOrigin` site values equal `AnswerSource` values; `SITE_VALUE_SOURCES ⊇ PREFILL_SOURCES`; `GENERIC_LABELS` are already `norm_label`-normal; a minimal class implementing every `SiteNavigator` member passes `isinstance`; `Answer` still constructs positionally with 6 args.
- **Verify:** `python tests/run_tests.py -k apply_contracts_v5`
- **Done when:** green on `arch/Q-35-llm-fill`; the full suite stays green.

#### WP-T1 · Sanitised S-5b fixtures and the fake model
- **STATUS:** READY (the recordings are in the Coordinator's session scratchpad `s5b/`; the tester reads them locally and never commits them)
- **Inputs:** LF §16; `spikes/S-5b_llm_workday.md`.
- **Files:** `tests/fixtures/apply/llm_fill/wd_a/<NN-step>/{page.html,fields.json,reply.json}`, `.../wd_b/...` (My Information only, with the required "Additional Address"), `tests/fixtures/apply/llm_fill/README.txt`, `tests/llm_fill_support.py` (fake backend: returns replies in order, records `(system, user, format)`; fixture server helper).
- **Do:** rebuild each page with every text value replaced by `tests/fixtures/apply/applicant.sample.yaml` values, employer names → "Example Employer", requisition ids and URLs' tenant names → placeholders, scripts removed; keep every `data-automation-id`, `aria-*`, `role`. Replies: one per call, including the six S-5b error patterns (LF §16 table). Grep the committed tree for the owner's values before committing (the README lists the check).
- **Verify:** `python tests/run_tests.py -k llm_fill_fixtures` (a test that loads every fixture, validates `reply.json` against the schema shape and scans for a deny-list of strings kept outside the repo)
- **Done when:** both tenants' pages load; no personal value or employer name is present.

#### WP-T2 · Pure oracles: facts, locks, guards, prompt
- **STATUS:** READY (skip-clean)
- **Inputs:** LF §4 (L1–L7), §5, §6.2–§6.4, §7 (G1–G10, answer mapping), §10 E2.
- **Files:** `tests/test_llm_fill_facts.py`, `tests/test_llm_fill_locks.py`, `tests/test_llm_fill_guards.py`, `tests/test_llm_fill_model.py`.
- **Do:** one oracle per row of LF §16's table plus: no S value of the sample profile in any recorded prompt; the schema's `ref` enum equals the catalogue; chunking by entry group; `pick_option` on a long hierarchical list; second opinion disagreement; transport failure → `transport:` note; L7 negated declaration.
- **Verify:** `python tests/run_tests.py -k llm_fill`
- **Done when:** files exist, skip-clean before lane M's modules, green after.

#### WP-T3 · Reader and widget oracles
- **STATUS:** READY (skip-clean; Playwright with headless Edge or Chromium, skipped when no browser)
- **Inputs:** LF §3.1, §3.2.
- **Files:** `tests/test_apply_page_reader.py`, `tests/test_apply_widgets.py`, hand-built stubs `tests/fixtures/apply/llm_fill/stubs/{prompt_categories.html,listbox_error.html,dates.html}`.
- **Do:** expected `fields.json` per fixture page (labels, kinds, required, options incl. `Category > Leaf`, shown values, date parts, honeypot dropped); strict listbox read-back; date equivalence; pill removal; upload read-back by file name.
- **Verify:** `python tests/run_tests.py -k apply_page_reader` and `-k apply_widgets`
- **Done when:** skip-clean before lane R, green after.

#### WP-T4 · Navigator and flow oracles
- **STATUS:** READY (skip-clean)
- **Inputs:** LF §8, §9.1, §9.2, §11; AD §10.5 (identity); S-5 signed-out recordings (no personal values) for the account pages.
- **Files:** `tests/test_workday_nav.py`, `tests/test_greenhouse_nav.py`, `tests/test_apply_flow_llm.py`, `tests/test_store_fill_cache.py`.
- **Do:** Workday: entry choice order, account wall wins over the progress bar, `click_filter` sibling click, step id prefix strip, `entry_sections`, Next never clicks Submit, confirmation URL. Flow: dry run over `wd_a` with the fake model → `ready_to_submit`; a stop on `wd_b` → `unanswerable_required` + one captured question with `profile_gap`; `model_unavailable` before the browser; nothing typed on a stopped page; caps/duplicate unchanged; fill_cache replay with zero model calls on retry.
- **Verify:** `python tests/run_tests.py -k workday_nav` (and `-k greenhouse_nav`, `-k apply_flow_llm`, `-k store_fill_cache`)
- **Done when:** skip-clean, then green as lanes land.

#### WP-T5 · Review findings F1, F3, F4
- **STATUS:** READY (skip-clean)
- **Inputs:** LF §12.
- **Files:** `tests/test_apply_resolve_memory.py` (F1 cases appended), `tests/test_apply_resolve_rules.py` (F4), `tests/test_questions_variants.py` (F3), `web/tests/QuestionCard.test.js` (F3: cleared variant sends `[]`).
- **Verify:** `python tests/run_tests.py -k questions_variants` and `cd web; npx vitest run tests/QuestionCard.test.js`
- **Done when:** green after WP-M2/M5/Q5.

## 3. Lane M (model side)

#### WP-M1 · Fact catalogue, `fact_value`, entry matching
- **STATUS:** READY
- **Inputs:** LF §5.1–§5.3, §10 E2; AD §5.3 (S paths, `llm_extract`), §7.3.2 (fit rules); D-79.
- **Files:** `src/jobscraper/apply/facts.py`.
- **Depends on:** contracts v5.
- **Do:** `fact_catalogue(profile, ctx, *, today) -> list[Fact]` (namespaces, private rule, template rows dropped, order); `facts_text(facts) -> str` (one line per fact, fixed order); `fact_value(ref, field, ctx, rules) -> Optional[Fit]` via `resolve.fit_*`; `match_entries(groups, sources) -> dict[group, source_id|None]` (E2); `facts_hash(profile_bytes, resume_text, jd_text) -> str`.
- **Verify:** `python tests/run_tests.py -k llm_fill_facts`
- **Done when:** no S value appears in `facts_text` for the sample profile; every ref maps as the oracles expect; E2 matching handles a parser-junk entry.
- **Requirements:** F-32, NF-02.

#### WP-M2 · Locks; F1 and F4 in the resolver
- **STATUS:** READY
- **Inputs:** LF §4 (L1–L7), §12.1, §12.3; QD §6.2; AD §7.5.
- **Files:** `src/jobscraper/apply/locks.py`, `src/jobscraper/apply/plan.py` (`is_generic`, `qualified_label`), `src/jobscraper/apply/resolve.py` (`_extra_answer` F1 guard; `label_countries` F4).
- **Depends on:** WP-M1.
- **Do:** `lock_page(fields, ctx, rules, *, today) -> dict[str, Answer]`; L7 negation rule; F1: generic labels match only qualified + employer-scoped; F4: all-caps `US` → {US, job_country}.
- **Verify:** `python tests/run_tests.py -k llm_fill_locks`
- **Done when:** lock oracles pass and `-k apply_resolve` stays green except the F1/F4 oracles the tester changed in T5.
- **Requirements:** F-12, F-13, F-32, F-33, D-75, D-76.

#### WP-M3 · Guards
- **STATUS:** READY
- **Inputs:** LF §7 (G1–G10, answer mapping), §10 E6; AD §7.7 (`grounded`).
- **Files:** `src/jobscraper/apply/guards.py`.
- **Depends on:** WP-M1.
- **Do:** `decide(fields, locks, decisions, facts, ctx, *, second=None) -> tuple[dict[str, Answer], list[str]]` (pure; `second` is the injected second-opinion callable); reasons for capture recorded in `Answer.note`/`rule_id` as QD §4.2 reads them.
- **Verify:** `python tests/run_tests.py -k llm_fill_guards`
- **Done when:** every G row's oracle passes; notes carry no values.
- **Requirements:** F-32, F-33, F-39, NF-02.

#### WP-M4 · The model call (+ backend keep_alive and warm-up)
- **STATUS:** READY
- **Inputs:** LF §6 (chunks, SYSTEM, user prompt order, schema, follow-up calls), §11 (length cut, malformed JSON), §13.1–§13.2.
- **Files:** `src/jobscraper/apply/llm_fill.py`, `src/jobscraper/backends.py` (M-block: optional `keep_alive` keyword on `complete`, sent only when given; `warm(backend, keep_alive)`).
- **Depends on:** WP-M1.
- **Do:** `chunks(fields, groups, max_fields)`, `system_prompt()`, `user_prompt(chunk, facts_text, resume, job, step)`, `schema(chunk, refs)`, `ask(backend, chunk, …) -> list[ModelDecision]`, `pick_option`, `recheck_entry`, `second_opinion`; record `model`, `prompt_hash`, tokens, seconds; never log prompt text. Measure and note in the handoff: `prompt_eval_ns` of a second call with the same prefix (LF §13.2).
- **Verify:** `python tests/run_tests.py -k llm_fill_model`
- **Done when:** with the fake backend: prompts in the fixed order, schema enums right, a cut reply is split and re-asked once, malformed JSON retried once, `BackendError` surfaces as transport unknowns.
- **Requirements:** F-32, NF-03, NF-09.

#### WP-M5 · Capture from the page (F1)
- **STATUS:** READY
- **Inputs:** LF §11, §12.1; QD §4.2, §5.
- **Files:** `src/jobscraper/apply/questions.py`.
- **Depends on:** WP-M2, WP-M3.
- **Do:** `capture_page(fields: list[PageField], answers, ctx, rules) -> list[CapturedQuestion]` (qualified `label_norm` for generic labels; reasons from guard notes; transport unknowns never captured); keep `capture()` for the old path until WP-C1.
- **Verify:** `python tests/run_tests.py -k apply_questions`
- **Done when:** QD oracles stay green; the F1 capture oracles pass.
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
- **STATUS:** READY
- **Inputs:** LF §3.1, §3.3; spike `llmfill.py` `READER_JS`, `read_fields`, `_expand_categories`, `ERRORS_JS` (port, then apply the LF rules: date section values, honeypots, context, groups, origin).
- **Files:** `src/jobscraper/apply/page.py`.
- **Depends on:** contracts v5; WP-T1 fixtures for the Verify.
- **Do:** `read_page(page, *, scope, sections, origin) -> list[PageField]`; `field_errors(page) -> dict[key, str]`; `entry_sections(page, scope) -> list[EntrySection]` (generic default); `page_text(page, scope)`.
- **Verify:** `python tests/run_tests.py -k apply_page_reader`
- **Done when:** every fixture page reads to its `fields.json`.
- **Requirements:** F-34, D-78.

#### WP-R2 · Widget families
- **STATUS:** READY
- **Inputs:** LF §3.2; AD §8.2 primitives; spike `fill`, `_choose_prompt`, `_type_date`, `file_decision`, `drive.wd_click`.
- **Files:** `src/jobscraper/apply/widgets.py`.
- **Depends on:** WP-R1.
- **Do:** registry of families (detect/options/fill/read), `click(page, loc)` with the `click_filter` fallbacks, strict listbox read-back, date equivalence, multi-select pills, upload read-back by file name.
- **Verify:** `python tests/run_tests.py -k apply_widgets`
- **Done when:** T3 widget oracles pass.
- **Requirements:** F-34.

#### WP-R3 · `fill_page`
- **STATUS:** READY (builds with injected fakes for locks/ask/decide until lane M merges)
- **Inputs:** LF §8 steps 1–9, §10 E3–E6, §13.3 (cache calls injected).
- **Files:** `src/jobscraper/apply/pagefill.py`.
- **Depends on:** WP-R2; lane M merged for the real-module oracles.
- **Do:** `fill_page(page, nav, ctx, rctx, services) -> PageOutcome` with `services` = `{locks, facts, ask, decide, cache_get, cache_put, log}`; entry delete/add + one re-read; fill only differing values; corrective pass once; nothing typed on a page that stops.
- **Verify:** `python tests/run_tests.py -k apply_pagefill`
- **Done when:** on `wd_a` My Experience with the fake model: junk entry deleted, description replaced by the recheck, a wrong location rejected; on `wd_b`: stop with nothing typed.
- **Requirements:** F-32, F-34, F-39.

## 5. Lane N (navigation + flow)

#### WP-N1 · CLI `accounts` (= WP-V2 accounts half, unchanged)
- **STATUS:** READY (lane B is merged)
- **Inputs, Files, Do, Verify, Done when:** as `apply_build_plan.md` WP-V2 (`python tests/run_tests.py -k accounts_cli`); `match_url` from `ats/workday.py` once WP-N2 lands (regex A until then).

#### WP-N2 · Workday navigator
- **STATUS:** READY
- **Inputs:** LF §9.1; AD §9.4.1, §9.4.3, §9.4.4, §9.4.11, §9.4.12; `spikes/S-5_workday.md` differences (a)–(f); spike `drive.py` (`dismiss_cookies`, `wd_click`, `cmd_account`, `cmd_signin`, `cmd_next`, `cmd_submit`).
- **Files:** `src/jobscraper/apply/ats/workday.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** contracts v5; `widgets.click` (WP-R2) — until it merges, a private copy of the three-step click fallback, removed in WP-N6.
- **Do:** every `SiteNavigator` member; register `"workday"`.
- **Verify:** `python tests/run_tests.py -k workday_nav`
- **Done when:** T4 Workday oracles pass on the recorded pages.
- **Requirements:** F-31, F-35, F-37.

#### WP-N3 · Greenhouse as a navigator
- **STATUS:** READY
- **Inputs:** LF §9.2; AD §9.1, §9.1.1 (steps 1–5 kept as `choose_entry`).
- **Files:** `src/jobscraper/apply/ats/greenhouse.py`.
- **Depends on:** contracts v5.
- **Do:** add `precheck`, `choose_entry` (wraps the existing `prefill`), `step_id`, `scope`, `entry_sections` (generic default), keeping the old `AtsAdapter` methods until WP-C1.
- **Verify:** `python tests/run_tests.py -k greenhouse_nav`
- **Done when:** T4 Greenhouse oracles pass and `-k greenhouse` stays green.
- **Requirements:** F-31, F-34.

#### WP-N4 · Identity, accounts and mail in the orchestrator (= WP-V4, reduced)
- **STATUS:** READY
- **Inputs:** `apply_build_plan.md` WP-V4 minus the `applied_on_tenant` entry rule and review notes; AD §10.2, §10.5, §11.5, §4.2.
- **Files:** `src/jobscraper/apply/accounts.py`, `src/jobscraper/apply_flow.py` (N-block), `src/jobscraper/store.py` (N-block: `accounts_for_tenant`, `applied_on_tenant`, `annotate_answers`).
- **Depends on:** WP-N2 (for the Workday wall), WP-P8 (merged).
- **Verify:** `python tests/run_tests.py -k apply_flow_accounts`
- **Done when:** the WP-V4 "Done when" list, minus the two dropped items.
- **Requirements:** F-35, F-36, F-37, NF-02, NF-06.

#### WP-N5 · Store and config for the new path
- **STATUS:** READY
- **Inputs:** LF §13.4, §14.
- **Files:** `src/jobscraper/store.py` (N-block: the four `apply_answers` columns in `_migrate`, `fill_cache` DDL + methods, `SCHEMA_VERSION` + 1), `src/jobscraper/config.py`, `config/config.yaml`.
- **Depends on:** none.
- **Verify:** `python tests/run_tests.py -k store_fill_cache`
- **Done when:** migration adds the columns to an existing DB copy; cache put/get/purge round-trip; `ApplyConfig.llm_fill` defaults as LF §13.4.
- **Requirements:** F-39, NF-07.

#### WP-N6 · Flow integration (the FILLING loop, capture, review check, warm-up)
- **STATUS:** READY after lanes M and R merge into `personal` and lane N rebases
- **Inputs:** LF §8 (flow part, review check), §11 (capture, `model_unavailable`, degradation table), §13.1 (warm-up), §13.3 (cache); QD §4.1 (capture helper, exceptions never change the outcome).
- **Files:** `src/jobscraper/apply_flow.py` (N-block), `src/jobscraper/cli.py` (apply backend with `llm_fill.num_ctx`).
- **Depends on:** WP-M5, WP-R3, WP-N2–N5.
- **Do:** behind `apply.fill: llm` (default): warm-up before Edge (fail → `model_unavailable`), `choose_entry` → `ctx.prefill`, per-step `fill_page`, audit rows with the new columns, `_capture_questions` from `capture_page` then `unanswerable_required`, `fill_failed` → `validation_error`, errors-after-Next retry once, review check, submit unchanged; `fill_cache` wiring and purge at start; `apply.fill: rules` keeps the old path.
- **Verify:** `python tests/run_tests.py -k apply_flow_llm`
- **Done when:** T4 flow oracles pass and every existing `-k apply_flow` file stays green.
- **Requirements:** F-13, F-30–F-39, NF-06, NF-07.

## 6. After the gate

#### WP-C1 · Cleanup (contracts v6, breaking; covered by ADR-0006)
- **STATUS:** TODO after the M20 gate.
- **Do:** remove `apply.fill: rules`, `AtsAdapter`'s fill-side methods, `PrefillPolicy`/`PREFILL_POLICY`, `apply_prefill_policy` and friends, Greenhouse's schema-to-fields mapping (keep `precheck`), tier-1 tagging and tier 5 in `resolve.py`; the tester retires the matching oracles in the same WP pair.
- **Verify:** `python tests/run_tests.py`
- **Done when:** the full suite is green with the old path gone.

## 7. M20 gate (Coordinator) on the new path

1. Merge order: T0 → (M ∥ R ∥ N1–N5) → N6 → smoke `personal` (live app starts; `python -m jobscraper doctor`).
2. Greenhouse: dry runs on 2 postings → `ready_to_submit`; `apply show` audit has no wrong answer.
3. Workday: dry run at each owner-approved tenant to Review, then the owner-approved automatic submissions (D-70, D-77). See the open question in `comms/outbox/architect.md` about which postings (the spike already submitted one).
4. A stop on an unknown required field → the question appears in the Profile tab → the owner answers → Retry proceeds (QD gate addition).

## 8. Critical path

T1 fixtures → R1 → R2 → R3 ∥ M1 → M2/M3 → M4 → M5 → N6 → gate. N2–N5 run beside it. Longest: lane R (Playwright on fixtures) and N6 integration.
