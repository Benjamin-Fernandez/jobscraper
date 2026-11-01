# Auto-apply test plan (stage C, M20 → M21)

Design: `docs/architecture/apply_design.md` · contracts `src/jobscraper/apply/contracts.py` · PRD F-10–F-12, F-30–F-40, NF-01–NF-09. Profile: product first (`instructions/03_methods.md` §4). Queue Q-08, tester, 2026-11-02.

**Rules for every test:** no network (schemas from `tests/fixtures`, browser pages from local files); synthetic applicant only; the model is a scripted `StubBackend`; stores are temp DBs, never `data/jobscraper.db`.

## 1. What runs, and when

| Check | Command | Runs |
|---|---|---|
| Contract + fixture tests (12) | `python tests/run_tests.py -k apply_contracts` | now |
| Layering §2.3, NF-01 check-ignore | `python tests/run_tests.py -k layering` · `-k nf01` | now |
| Module oracles (33) | `-k apply_contracts` | each appears when its module exists (`@needs`); the import line names what is still waiting |
| **Smoke / replay (lane B Verify)** | `PYTHONPATH=src python -m jobscraper apply <job_id> --dry-run` on a copied DB, port 8768, against **one** real Greenhouse posting → ends `ready_to_submit`, screenshots in `data/apply/<id>/`, answers table complete | once per lane B handoff |

## 2. Oracle tests (in `tests/test_apply_contracts.py`)

| Area | Test function → expected |
|---|---|
| State machine (§4) | `test_every_non_terminal_state_may_fail_and_terminal_states_are_final`; `test_only_the_review_page_leads_to_submit_and_a_dry_run_never_submits` → SUBMITTING only from FILLING/VERIFYING_EMAIL; SUBMITTED/UNCONFIRMED only from SUBMITTING; READY_TO_SUBMIT terminal |
| Reason copy (§4.4) | `test_every_reason_code_has_owner_copy_and_detail_fills_cleanly`; `test_stop_reasons_tell_the_owner_nothing_was_sent` |
| Answers (§7) | `test_answer_tiers_follow_the_f32_order`; `test_an_answer_fills_only_when_filled_with_a_value`; `test_apply_failure_carries_its_reason_and_only_dry_run_or_submitted_is_ok` |
| Secrets (NF-02) | `test_secrets_never_print_and_vault_names_are_per_tenant` → `jobscraper:workday:<host lowercased>` |
| Profile (§5) | `test_sample_profile_validates_clean_and_is_complete` → `[]`, missing ⊆ {documents.resume}; `test_validation_names_each_bad_field` → postal, email, phone (+65 rule), country code, months 12–14, travel 0–100, nric_last4, enum, salary > 0, start ≤ end, full NRIC anywhere; `test_missing_for_apply_lists_required_paths`; `test_llm_extract_and_logs_never_carry_sensitive_values`; `test_computed_facts_from_experience_and_education` → graduation 2025, years 0 |
| Labels (§7.1) | `test_norm_label_rules` → `"1. What is your <b>Email</b> Address? *"` → `what is your email address`; `Don’t` → `dont`; `c++ c#` kept |
| Declarations (§7.5, F-33) | `test_declaration_classifier_labels_each_class_and_flags_ambiguity` (7 classes, None, marker → AMBIGUOUS, two classes → AMBIGUOUS); `test_company_match_rules` (DBS Bank Ltd ~ DBS, Grab ~ Grab Financial Group); `test_declarations_answer_no_by_default_from_the_profile` (pep, audit, bankruptcy, regulatory → "No", tier 4, `sensitive`, `declaration:<label>`); `test_prior_employment_is_deduced_from_experience_including_internships` (employer / alias / 2025 internship → Yes; other → No); `test_holdings_relatives_and_previously_applied_answer_yes_when_true` |
| Fail closed (§7, ADR-0003) | `test_unlabelled_attestation_fails_closed_and_never_reaches_the_model` (required → UNKNOWN, optional → BLANK_OPTIONAL, 0 model calls); `test_a_required_checkbox_is_never_ticked_on_a_false_statement`; `test_health_questions_take_decline_or_fail`; `test_a_sensitive_question_with_no_matching_option_stops_without_the_model`; `test_model_unavailable_leaves_a_required_field_unknown_and_an_optional_one_blank` |
| Tiers 1–2 | `test_tier1_field_map_answers_from_the_profile` (name, email, "Singapore +65", resume path, EEO decline → "I don't wish to answer"); `test_tier2_profile_rules_map_onto_offered_options` (sponsorship → No, residency → "Singapore Citizen" sensitive, salary → "5000") |
| Tier 5 + grounding (§7.6–7.7) | `test_tier5_text_with_an_invented_number_is_rejected_after_one_retry` ("12" → UNGROUNDED, 2 calls, retry prompt); `test_tier5_text_with_an_invented_employer_is_rejected` ("Google"); `test_tier5_grounded_text_is_filled_and_recorded` (conf 0.8, model id, 16-hex prompt hash, no S value in the prompt); `test_tier5_choice_needs_two_agreeing_runs_and_a_verbatim_quote` (temps [0, 0.7], seed 7; disagreement / invented quote → not filled) |
| Greenhouse (§9.1) | `test_greenhouse_urls_give_the_tenant`; `test_greenhouse_plan_from_the_dataiku_schema` (exact API URL, canonicals, `alt_of`, demographic `4000563004`, GDPR boxes, location, phone country); `test_greenhouse_vercel_plan_has_no_consent_boxes_when_the_flags_are_off`; `test_greenhouse_schema_404_is_posting_closed` |
| Detection (§9.0) | `test_no_adapter_is_unsupported_ats` |
| Guards (§12, NF-06) | `test_store_refuses_a_transition_the_table_does_not_allow` (ValueError); `test_a_posting_can_succeed_only_once` (unique index); `test_duplicate_guard_covers_applied_twins_and_clicked_attempts` ("applied …", "same posting as …", "already submitted by JobScraper", None); `test_caps_count_only_clicked_attempts` ((2, 2); dry runs don't count); `test_the_reaper_never_fails_a_clicked_attempt` |
| Classifier (§8.4) | `test_classifier_ignores_the_invisible_recaptcha_and_stops_on_a_visible_challenge` → form `ok`, challenge `captcha`, closed `closed`, bot `bot_challenge` (headless Edge, local files) |

## 3. Reason codes testable offline (M20)

| Code | Where pinned |
|---|---|
| `captcha`, `bot_challenge`, `posting_closed` (page) | classifier test on `form_challenge.html`, `bot_check.html`, `closed.html` |
| `posting_closed` (schema 404), `unsupported_ats` | Greenhouse 404 test, detect test |
| `unanswerable_required` | resolver UNKNOWN/UNGROUNDED tests; **flow test (to add when `apply_flow` exists):** Dataiku schema + a profile without the answer → `failed(unanswerable_required)` before Edge opens, detail = the label |
| `duplicate`, `cap_reached`, `profile_incomplete` | store guard tests; flow test: same job twice in one batch → second `duplicate` |
| `validation_error` | flow/adapter test on `form.html?after=errors` (one re-fill, then the code) |
| `cancelled` | reaper test |
| `sms_or_2fa`, `login_failed`, `email_verification_timeout`, `mail_not_set_up`, `page_unrecognised`, `error` | M21 (Workday/mail) or flow tests with a stub adapter; not M20 |
| Submit path | `form.html` (inline confirmation), `?after=navigate` → `confirm.html`, `?after=code` → `code_required`; `body[data-submit-count]` must equal **1** after an `auto` run (duplicate-submission oracle at the page level) |

## 4. Fixtures

`tests/fixtures/apply/`: `applicant.sample.yaml` (fake person; same keys as the design template, enforced), `questions.sample.yaml` (6 keys, §7.3.1 format), `greenhouse/gh_dataiku.json`, `gh_vercel.json` (public schemas, spike S-3), `greenhouse/form.html` (Dataiku form: `[id=<name>]`, react-select look-alikes with `.select__menu [role=option]`, hidden intl-tel list, hidden file inputs, GDPR checkboxes, invisible reCAPTCHA anchor + `.grecaptcha-badge`, Submit → confirmation), `form_challenge.html` (visible `bframe`), `confirm.html`, `closed.html`, `bot_check.html`, `recaptcha/{anchor,bframe}.html` (stubs, no network).

## 5. Evals for tier 5 (M21; not in the unit suite)

`python tests/evals/resolver_tier5.py` (to write in M21) with the real Ollama model on 20 recorded questions from the two schemas + Lever/Ashby fixtures, each labelled with the expected answer or `unknown`. **Thresholds:** 0 ungrounded fills (hard), 0 S-value leaks in prompts (hard), ≥ 90 % of answerable choice questions answered correctly, ≥ 95 % of unanswerable ones end `unknown`/`blank_optional`, text answers pass grounding on first try ≥ 70 %, p95 latency ≤ 20 s per field. Run once per model or prompt change; record numbers in the M21 gate.

## 6. Not covered / assumptions

- `resolve.load_rules(path)` is **assumed** (the design names only `QuestionRules`); `reap_attempts(now)` vs `(now, job_running)` differ between §4.3 and §13. Both raised to the architect.
- Real browser fill of `form.html` by the adapter is a lane B test to add with `browser.py` (needs `ApplyConfig`).
- Experience-month counting (inclusive or not) is undefined; the test accepts 8–10.
