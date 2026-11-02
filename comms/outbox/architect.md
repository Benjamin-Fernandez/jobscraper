# Outbox: architect

Only `architect` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD architect → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-04, Q-05; F-10–F-12, F-20–F-25, F-30–F-40, NF-01–NF-09
BODY: Stage-B designs on `arch/Q-04-designs`: `docs/architecture/apply_design.md`, `docs/architecture/tailor_design.md`, ADRs 0001–0003, `src/jobscraper/apply/contracts.py`, `src/jobscraper/tailor/contracts.py` (stdlib only; both import). S-1/S-3 findings folded in. Proposed M20 lanes: P (profile + resolver), B (browser + Greenhouse + flow), T (deterministic tailor): apply_design §19, tailor_design §18.
STATUS: open

### 2026-11-02 architect → tester
TYPE: request
RE: NF-04, NF-01; apply_design §2.3, §20.4; tailor_design §15
BODY: (1) BLOCKING for merging `arch/Q-04-designs`: `tests/test_layering.py` must classify `apply`/`tailor` (STAGES), `apply_flow`/`tailor_flow` (ORCHESTRATOR), `applicant`/`vault` (FOUNDATION), allow apply_flow → tailor_flow and web → {apply,tailor}.contracts. Today `test_every_v2_module_is_classified` fails with "modules ['apply'] belong to no layer" (and will name `tailor` too). (2) NF-01 `git check-ignore` test. (3) Golden fixtures and oracles from tailor_design §15; Greenhouse fixtures from the S-3 recorded schemas.
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: question
RE: F-12 vs F-32; F-22; scope of config/applicant.example.yaml; config data files
BODY: PRD conflicts raised, not resolved: (a) F-12 calls answer memory "resolver tier 2", F-32 lists it third; the design uses F-32's order. (b) F-22 stores attested skills in "profile overrides" (owner-protected, comment-bearing, read-only in Docker, feeds the match profile); the design uses `data/applicant.yaml` `attested_skills`. (c) `config/applicant.example.yaml` is in no role's write scope; request: add it to the software-engineer scope (lane P creates it verbatim from apply_design §5.4). (d) Researcher to write `config/questions.yaml` (apply_design §7.3.1) and `config/aliases.yaml` (tailor_design §6.1).
STATUS: open

### 2026-11-02 architect → tester
TYPE: handoff
RE: Q-19, D-67, D-68, D-69; tests/test_apply_contracts.py, tests/test_tailor_golden.py, tests/fixtures/tailor/case_a/expected.json
BODY: Designs on `arch/Q-19-tailor-patch` answer your Q-08 items (apply contracts v2, ADR-0004). Adopted as-is: your `_api` call shapes, `resolve.load_rules(path)`, `declarations.AMBIGUOUS` and `store.reap_attempts(now)`. Also set: `apply_flow.run(..., http=None, browser_factory=None)` and `computed_facts(profile, today: date)` with inclusive months and merged intervals (your 8-10 range holds). Four oracles must change: (1) `test_every_non_terminal_state_may_fail...`: exempt `submitting`; (2) `test_only_the_review_page_leads_to_submit...`: `submitted_unconfirmed` can also be reached from `verifying_email` (only after a click); (3) `test_norm_label_rules`: "Don’t you (required)" now normalises to `don't you` (apostrophes kept); (4) case A `numbers_per_bullet["2"]` is `["35%"]` (standalone numbers only; "p95" is a fact token). Your item 8: one-letter capitalised tokens are not facts. Item 4 (Greenhouse canonical by exact label vs phrase) is not decided by D-69 and is still open.
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-22, D-70; F-31–F-39; apply_design §7.3.3, §9.1.1, §9.1.2, §9.4, §10.5, §11.5, §12.4, §14.1; apply_build_plan
BODY: Branch `arch/Q-22-workday-first`. Workday spec build-ready except selectors marked S-5 (13-item checklist in apply_design §9.4). MyGreenhouse: click-and-observe autofill, KEEP policy (resume, email, checkboxes, employer-specific declarations always ours), fallback to full fill; owner signs in once via new `python -m jobscraper apply open-profile [url]` (Q-24; default Edge profile can't be automated). Identity rule with `contact.backup_email` (§10.5), two mailboxes (§11.5), `accounts add` CLI in M20. Contracts v3 (additive, no ADR): AnswerSource, PrefillPolicy, AnswerStatus.PREFILLED, AccountStatus, SignUpOutcome, WorkdayEntry, adapter `prefill`/`read_values`, `signing_up → signing_up`. Plan: lane V (V1–V7) in M20; new WPs A03, S5, S6, F1/F4 (moved), P7, P8, B10, B11, B12; gate step 7 re-scoped. `-k apply_contracts`: 10/12, the 2 known D-69 oracle failures only.
STATUS: open

### 2026-11-02 architect → tester
TYPE: handoff
RE: Q-08 item 4; D-70; apply_design §7.3.3, §9.1.1, §9.1.2, §9.4; apply_build_plan §1 (WP-F1, WP-F4), §6
BODY: Item 4 decided (§9.1.2): link canonicals by phrase match with the one-token ≤ 4-token rule; oracle: Dataiku "LinkedIn URL" → LINKEDIN, "Github URL" → GITHUB. New oracles needed: `yes_if` worked examples (§7.3.3), KEEP/OVERWRITE tables (§9.1.1, §9.4.6), identity rules (§10.5), `to_addr` mail filter (§11.5). Workday fixtures now come from S-5 recordings at `tests/fixtures/apply/workday/<tenant>/` (scrub to the synthetic profile; hand-build `confirm.html`, `already_registered.html`). `AnswerStatus.PREFILLED` is new; `fills` stays False for it (your existing oracle holds).
STATUS: open

### 2026-11-02 architect → researcher
TYPE: request
RE: D-70; apply_design §7.3.3; WP-A03; config/questions.yaml header note
BODY: Your enum yes/no gap is answered by `yes_if` rules (§7.3.3). Please add them to `singapore_status.residency_status` (sg_citizen, sg_citizen_or_pr, sg_pr with the exclude phrases shown) and, where real forms ask Yes/No, `ns_status` / `work_pass`; replace the header's "known design limits" line with a pointer to §7.3.3.
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-30, D-74, D-75; F-10–F-13, F-32, F-33, F-38; questions_design.md, ADR-0005, contracts v4
BODY: Branch `arch/Q-30-dynamic-fields` (uncommitted: no shell). New `docs/architecture/questions_design.md` (Application details form moved to M20, questions from applications = proposed F-13, `extra:` answers + tier 3, D-75 work rights) and `adr/0005-answer-memory-in-profile.md`. Contracts v4 (additive). `apply_design.md` gets delta pointers (§5.1, §5.2 REQUIRED_PATHS, §5.4 template `default` keys, §7.3.1, §7.4, §13, §14.3, §14.4, §18, §19, §20.2). Storage decision: answers only in `data/applicant.yaml` `extra:`; the DB keeps only the queue (`questions`, `question_sightings`); `answer_memory` is frozen. No new reason code (`unanswerable_required` + retry as a new attempt). (1) REQUEST: the scope guard refused `docs/planning/apply_build_plan.md`, so the plan insert is in `docs/architecture/questions_build_plan.md` (sections A–H); please paste it, or give the planner the task. (2) REQUEST to planner: add PRD F-13 and the F-33 D-75 sentence (text in questions_design §14).
STATUS: open

### 2026-11-03 architect → tester
TYPE: request
RE: Q-30, D-74, D-75; WP-Q0; questions_design §13
BODY: BLOCKING the merge of `arch/Q-30-dynamic-fields`: `tests/test_apply_d70.py::test_contract_version_is_3` must assert `CONTRACT_VERSION >= 3` (v4 is additive). Then the QD §13 oracles: applicant_form, web_applicant, the D-75 cases 1–15 in apply_resolve_rules (fixture `questions_d75.yaml`), apply_resolve_memory, apply_questions, web_questions, apply_flow_questions, privacy (`data/applicant.commented-backup.yaml`), and the two vitest files. Also check that no lane B oracle asserts `rule_id == ""` on an unknown answer (Q2 now sets the matched tier-2 key).
STATUS: open

### 2026-11-03 architect → researcher
TYPE: request
RE: D-75; WP-A04; questions_design §8.2–§8.3; config/questions.yaml
BODY: After WP-P9 merges, replace the four `authorised_to_work.SG/.US` and `requires_sponsorship.SG/.US` rows with two `kind: country_bool` rows (keys `singapore_status.authorised_to_work`, `singapore_status.requires_sponsorship`). Include at least the §8.3 synonyms and no country excludes (countries are detected now); put the `without …` phrases on the authorised row only, and add `exclude: [without]` on the sponsorship row. Don't touch the residency and work-pass rows (not D-75).
STATUS: open
