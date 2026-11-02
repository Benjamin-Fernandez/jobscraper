# Outbox: architect

Only `architect` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD architect → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 architect → coordinator, engineer, tester (Q-48, D-87)
TYPE: handoff
RE: Q-48, D-87 (extends D-55), KA-2; AD §5.4, §7.5; LF §4 L3/L5/L7; QD §3 rows 4 and 14; contracts v5 (additive)
BODY: Fast-track amendment to tier 4 (declarations). Budget ran out (36/35 calls) before the doc fold-in: **this entry is the amendment of record** until AD §7.5, LF §4, QD §3 and `contracts.py` carry it (about 5 edits, no new design). No S values below; labels are employer text.

**A. Decisions**
- A1 Keep the key `declarations.non_compete`, widened to "any agreement that limits the work you can do". Same fact, same owner answer; a rename changes a `DeclarationLabel` value (breaking, ADR) and needs a D-79 migration for no behaviour gain. Only the form label and the example comment change.
- A2 New standing class and key `government_employment` (bool, default false).
- A3 Disability: no new key. `us_self_id.disability_status` is the disability answer for every country (one value, nothing to drift). A new tier-4 class `disability` (label-only match) reads it: S, filled by the program, `sensitive=True`, locked before the model (L3; G7 already lists disability).
- A4 Agreement rule: when a label matches 2+ classes, all of them **standing** (`pep`, `conflict_audit_independence`, `criminal_record`, `bankruptcy`, `regulatory_disciplinary`, `non_compete`, `government_employment`) and all truth values equal → that value. A set holding an employer-specific class, `health` or `disability` stays AMBIGUOUS: D-70's prefill overwrite and L6's skip key off one employer-specific class, so they stay untouched.
- A5 Checkboxes: the agreement rule does **not** apply to a single CHECKBOX; a multi-class box stays AMBIGUOUS (required → unknown `attestation_unclear`, optional → blank). ADR-0003: a tick is a signed statement, and token rules can't tell the polarity of each class ("I have no conflict of interest and am bound by a non-compete" has one negation and mixed polarity). Single-class boxes keep today's rule; with the new phrases "I confirm I am not bound by any restrictive agreement" is single-class `non_compete` → ticked.
- A6 L7 stays (negated Yes/No → unknown) with two changes: (a) NS-exclusion runs ("not including national service") are removed before the negation test (L7 and `is_negated`); (b) `declarations.answer()` applies L7 itself on non-checkbox fields, so the Greenhouse resolver path fails closed too (the wider tier 4 would otherwise map "Are you free of any non-compete?" → `fit_bool(False)` → "No").
- A7 R1 longest match: a class's hit is dropped when every span it matched lies inside a longer matched span of another class. This changes nothing in today's table (no cross-class nesting). It lets "worked for the government" beat prior_employment's "worked for", "employed by the government" beat "employed by", and pep's "senior government official" beat "government official".
- A8 D-79: for `declarations.<bool>` paths only, `nil`, `none`, `na`, `n_a`, `not_applicable` (key form) read as false. `us_self_id.disability_status`: `none`, `nil`, `no_disability`, `not_disabled` → `no`.

**B. Classifier (AD §7.5)**
- B1 `non_compete` phrases (replace the row): non compete, non competes, noncompete, non competition, non solicitation, non solicit, nonsolicitation, non disclosure, nondisclosure, nda, ndas, confidentiality agreement, confidentiality agreements, confidentiality obligation, confidentiality obligations, restrictive covenant, restrictive covenants, restrictive agreement, restrictive agreements, restraint of trade, garden leave, bound by any agreement, agreement that restricts, agreements that restrict, agreement that would restrict, agreement restricting, agreements restricting, agreement that prevents, agreement that would prevent, agreement that prohibits, agreement that would prohibit, stock option agreement, stock option agreements, stock option or restricted stock, restricted stock grant, restricted stock agreement, restricted stock unit agreement, stock grant agreement, equity grant agreement. ("subject to any restrictions" is left out on purpose: work-rights questions use it.)
- B2 `government_employment` phrases: civil service, civil servant, civil servants, public service, public servant, public sector, public officer, government service, government employee, government employees, government employment, government agency, government agencies, government ministry, government department, government body, government bodies, statutory board, statutory boards, government official, public official, worked for the government, worked for government, worked for a government, worked for any government, worked in the government, worked in government, work for the government, working for the government, employed by the government, employed by government, employed by a government, employed by any government, employed in the government, employed in government, have you worked in government, have you worked in the government, have you worked in the public sector, have you worked in the public service, have you worked in the civil service.
  - MILITARY terms (used by the rule below; not class phrases): military, armed forces, armed services, defence force, defence forces, defense force, army, navy, air force, national service, ns, nsf, nsman, saf, conscription, uniformed service, uniformed services.
  - NS exclusion: an exclusion run (excluding, exclude, excludes, except, other than, apart from, aside from, besides, save for, not including, not counting, does not include, do not include) with an NS term starting within the next 4 tokens, or an NS term followed within 3 tokens by not included / excluded / not counted / does not count. NS terms: national service, full time national service, ns, nsf, mandatory military service, compulsory military service, mandatory national service, military service, mandatory service, compulsory service, conscription.
  - UNSURE phrases: government linked, glc, glcs, government owned, state owned, state enterprise.
  - Rule (gov = a B2 hit after R1; mil = a MILITARY hit; excl = NS exclusion; unsure = an UNSURE hit): (gov or mil) and excl and not unsure → `government_employment`. Gov and not mil and not unsure → `government_employment` (the owner reads "worked for the government" as not counting NS). Gov with (mil and no excl) or with unsure → **AMBIGUOUS** (unknown, never No). Mil, no excl, no gov → no `government_employment`: an NS-inclusive question belongs to L5 / `ns_status`, and tier 4 doesn't answer it unless another class matches.
  - Against `pep`: R1 makes "senior government official" pep only; "public office" stays pep. "Held public office or worked in the civil service?" → {pep, government_employment} → A4 → No; if the profile's two values differ → AMBIGUOUS (a real disagreement).
- B3 `disability` (matched on the **label only**: EEO preambles in descriptions mention disability): disability, disabilities, disabled, person with disability, persons with disabilities, people with disabilities, pwd, pwds, handicap, handicapped. A label that also says veteran, gender, race, ethnic, ethnicity, religion or marital → AMBIGUOUS.
- B4 `classify_all(label_norm, description_norm="") -> tuple[frozenset[DeclarationLabel], bool]` (classes, unsure): phrase hits → R1 → D-69 pair → B2 rule. `classify()` is built on it: unsure → AMBIGUOUS; 1 class → it; 2+ → AMBIGUOUS; 0 → attestation marker → AMBIGUOUS, else None (unchanged contract for callers).

**C. Rules (AD §7.5)**
- `government_employment`: `declarations.government_employment` (default false); joins `_PLAIN_BOOLS`.
- `disability`: `no` → False, `yes` → True, `decline`/absent → None. A bool on a bool-shaped field → `fit_bool`; another choice → `fit_enum` with `DISABILITY_VALUE_MAP` = the EEO disability entry plus "no": no disability, i do not have a disability, i don't have a disability, i do not have any disability, not a person with disability, i am not a person with disability; "yes": i am a person with disability, person with disability. A single checkbox uses today's negation rule. None → the decline option when offered; else required → unknown, optional → blank (notes "disability: declined, no decline option" / "no offered option fits the declaration").
- Agreement (inside `answer()` when label is AMBIGUOUS): `classes, unsure = classify_all(norm_label(f.label), norm_label(f.description))`; when not unsure, 2+ classes, all in `STANDING_DECLARATIONS`, `f.type` not CHECKBOX and all `truth()` equal → `fit_bool` of that value; `rule_id` and the source suffix = the sorted class values joined by `+` (e.g. `conflict_audit_independence+non_compete`), note `agreed: <classes>`, `sensitive=True`, 0.95. Otherwise unchanged (`attestation not recognised`).
- L7 in `answer()` (A6b): a non-checkbox field whose label is negated (not, never, no, none, neither, free of, without; NS-exclusion runs removed first) → `_ended`, note "negated declaration question".
- `health`: unchanged.

**D. Profile schema**
- `config/applicant.example.yaml`: `disability_status: decline  # no | yes | decline. Answers every disability question, in any country (D-87)`; `non_compete: false  # any agreement that limits the work you can do: non-compete, non-solicitation, NDA or confidentiality, stock option or restricted stock terms`; new `government_employment: false  # ever worked for the government, public sector, a statutory board or the military, not counting National Service` (after `non_compete`).
- `applicant.py`: `BOOLS += "declarations.government_employment"`; A8 synonyms. Form rows (QD §3 rows 4 and 14 follow):
  - `_I("declarations.non_compete", "Are you bound by any agreement that limits the work you can do, such as a non-compete, non-solicitation, NDA or stock grant terms?", "bool")`
  - `_I("declarations.government_employment", "Have you ever worked for the government, public sector or military, not counting National Service?", "bool", help="Questions that include National Service use your National Service status instead.")` (after non_compete)
  - `_I("us_self_id.disability_status", "Disability status", "enum", _enum_opts("us_self_id.disability_status"), help="Used for every disability question, in any country, not only US forms.")`

**E. Engineer WP-Q48 (one lane; `apply/declarations.py`, `applicant.py`, `config/applicant.example.yaml`)**
- E1 (architect, with the doc fold-in): `DeclarationLabel.GOVERNMENT_EMPLOYMENT = "government_employment"`, `DeclarationLabel.DISABILITY = "disability"`; v5 additive; not in `EMPLOYER_SPECIFIC_DECLARATIONS`.
- E2 `declarations.py`: B1–B4, R1, `STANDING_DECLARATIONS`, C rules, L7 in `answer()`, NS-exclusion strip in `is_negated`.
- E3 `applicant.py`: BOOLS, A8, the D form rows. E4 the example yaml lines.
- E5 At lane M's merge (`locks.py`): L3 must pass AMBIGUOUS to `declarations.answer()` rather than end it itself, and L7 must use the declarations negation helper. One check, no new code if it already delegates.
- Verify: `python tests/run_tests.py -k declarations`, `-k applicant`, then the full suite.

**F. Tester oracles (employer "Acme"; the example profile defaults, plus a fixture `disability_status: no`)**
- F1 Optional Yes/No: "Have you signed or accepted any agreement, or are you otherwise subject to any restrictions, that 1) will restrict the job responsibilities you may perform or 2) prohibit you from working for Acme, e.g. non-competition agreement, non-disclosure agreement, non-solicitation agreement, stock option or restricted stock grant agreement with your current or former employers or pursuant to applicable government conflict of interest restrictions?" → `classify` AMBIGUOUS; `classify_all` ({non_compete, conflict_audit_independence}, False); `answer` FILLED "No", tier DECLARATION, rule_id `conflict_audit_independence+non_compete`, sensitive.
- F2 F1 with `conflict_audit_independence: true` → optional blank_optional; required → unknown (LF reason `attestation_unclear`).
- F3 "Have you ever worked for the Government (excluding mandatory military service)?" → `government_employment` (prior_employment dropped by R1) → "No".
- F4 "Have you ever worked for the government, not including National Service?" → `government_employment`, L7 doesn't fire → "No".
- F5 "Have you served in the armed forces?" → `classify` None (not this lock).
- F6 "Have you ever been employed by the government or served in the military?" → AMBIGUOUS → required unknown.
- F7 "Have you ever worked for a government-linked company?" → AMBIGUOUS.
- F8 "Are you, or have you ever been, a senior government official?" → pep only → "No"; still pep-only with `government_employment: true`.
- F9 "Have you held public office or worked in the civil service?" → "No" (agreement); with `pep: true` → AMBIGUOUS.
- F10 "Are you a person with disability (PWD)?" Yes/No → "No"; with `decline` and a "Prefer not to say" option → that option; `decline`, no decline option: required → unknown, optional → blank.
- F11 Label "Disability status", options "Yes, I have a disability (or previously had a disability)" / "No, I do not have a disability and have not had one in the past" / "I do not want to answer" → the "No, I do not have…" option.
- F12 Label "Gender" with a description that mentions disability → not `disability`.
- F13 "Do you have any disability or medical condition that may affect your work?" → AMBIGUOUS → optional blank / required unknown.
- F14 "Do you have any medical condition we should know about?" required with a decline option → the decline option; optional → blank (health unchanged).
- F15 Required single checkbox "I confirm I am not bound by any restrictive agreement" → ticked ("true").
- F16 Required single checkbox "I confirm I have no conflict of interest and am not bound by any non-compete" → unknown (A5).
- F17 "Are you free of any non-compete agreement?" Yes/No → unknown (L7, resolver path too).
- F18 "Have you previously worked for us or any government agency?" → AMBIGUOUS (employer-specific in the set).
- F19 Regression: every pre-D-87 classify oracle unchanged (R1 changes nothing on the old table).
- F20 normalise: `government_employment: "NA"` / `"nil"` → false; key missing → false; `disability_status: "none"` → "no".

**G. Open (coordinator)**
- G1 Recommend adding `military`, `armed forces` to G7 `SENSITIVE_LABEL` (lane M `guards.py`, one constant). Without it, an NS-inclusive question that no NS `yes_if` rule matches (F5) can still reach the model.
- G2 No NS `yes_if` rule for "served in the armed forces": it isn't true for every enum value (NS can be served in the police or civil defence), so it stays captured.
- WRITTEN INTO DOCS (2026-11-02, follow-up): AD §5.4 + §7.5, LF §4 L3/L7 + G7 (D-88) + G2(d) (restated-fact rule: accepted, the written option stays the program's fit), QD §3 rows 4 and 14, `contracts.py` (2 additive `DeclarationLabel` members, v5). WP-Q48 and the tester WP are ready to build.
- D-89 (2026-11-02): R1 extended in AD §7.5: a prior/current-employee span that overlaps a government span also loses. The drop is skipped when the label names this employer (`us`/`our`, or `employer_names` via `company_match`). F18 stays AMBIGUOUS; NS-inclusive military questions are unchanged. New oracles: "Have you previously worked for the government?" and "Are you currently employed by a government body?" → `government_employment` → No.
- D-90 (2026-11-02): written into AD §7.5: phrase-table rows for disability and prior/current employment conditioned; the "Negated question" rule is replaced by five gates (field type, status frame, polarity with a grown NEGATIONS list and the negative-attestation checkbox rule, the employer condition shared with Q-46c, disability status frames), plus no S state in notes. Also the "Value onto the field" checkbox clause, and LF §4 L3/L7 (one shared helper, F10). Open: an extension to the WILLINGNESS list, proposed and marked pending in AD (see the report).
STATUS: open

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

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-35, Q-40, D-78 (+ D-70, D-74–D-77, D-79); F-12, F-13, F-31–F-39, NF-02–NF-07; review Q-30 F1, F3, F4
BODY: Worktree `.claude/worktrees/arch-Q-35`, branch `arch/Q-35-llm-fill` (uncommitted: no shell; please commit). New: `docs/architecture/llm_fill_design.md`, `adr/0006-llm-driven-form-filling.md`, `llm_fill_build_plan.md` (READY TO BUILD), `spikes/S-5_workday.md`, `spikes/S-5b_llm_workday.md` (tenants anonymised: A wd1, B wd5, C wd1; no names, req ids or values). Contracts v5 (`apply/contracts.py`): additive types (ValueOrigin, PageField, EntryGroup/Section, FillSource, Fact, ModelDecision, PageOutcome, SiteNavigator, GENERIC_LABELS, TRUSTED_ORIGINS, SITE_VALUE_SOURCES, AnswerSource STANDING/RESUME/JOB/RESUME_IMPORT, Answer.evidence/shown/origin/entry) + ReasonCode `model_unavailable` with copy; superseded parts (AtsAdapter fill methods, PrefillPolicy) stay until WP-C1. Key decisions: the model names the source per field, the program writes every fact-sourced value (S values never in a prompt); deterministic locks first (file, account email, declarations + new negation rule L7, D-75, sensitive tier-2, consents, extra with F1 guard); guards G1–G10 cover all six S-5b error kinds; site modules = navigation only; resume import always, then entries matched/junk deleted/descriptions rechecked; state machine, submit-once, caps unchanged. F1: generic labels matched by label + help/preceding question and only employer-scoped; F3: reviewer's fix adopted; F4: all-caps "US" → {US, job country}, a difference = conflict. Existing WPs: V2 → N1 unchanged; V4 → N4 reduced; V5 → N2 changed; V6, V7 superseded; Q1b → part of N6; B11 retired at C1; F1 → T1.
Evidence: none runnable here (no shell). Please run `python tests/run_tests.py -k apply_contracts` and `-k layering` before committing (expected green: v5 only adds; `REASON_TEXTS` covers the new code).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: question
RE: D-77 gate, D-78, NF-07, ADR-0003
BODY: (Q1, owner) The M20 gate wants real Workday submissions at the 2 approved employers. Tenant A's posting was already submitted by the spike (the duplicate guard will refuse it) and tenant B stops at a required address field until the owner answers it (Profile, or the Questions inbox). Which postings should the gate use? (Q2, owner, optional) D-78 says the LLM fills; the design keeps deterministic locks for declarations, work rights, sensitive values, consents and the owner's own answers (the model sees them as facts). Moving those to the model would change ADR-0003; I recommend keeping them. (Q3, Coordinator) Accept NF-07 deviation: a Workday attempt may take ~5–6 min with the model (`attempt_timeout_s` 900).
STATUS: open

### 2026-11-03 architect → tester
TYPE: request
RE: Q-35; llm_fill_build_plan §2 (WP-T0–T5); llm_fill_design §16
BODY: Nothing blocks the merge of `arch/Q-35-llm-fill` (v5 is additive; `test_contract_version_is_3` asserts `>= 3`). Please write T0 (contract v5) first, then T1: sanitised fixtures from the S-5b recordings (Coordinator's session scratchpad `s5b/`; personal data: rebuild with `applicant.sample.yaml` values, "Example Employer", no req ids; scan before commit) and the fake backend in `tests/llm_fill_support.py`; then T2–T5. Note the spike prompts contain contact details and nationality (the prototype sent them to the local model): never copy prompt text into fixtures; the design forbids those values in prompts and T2 asserts it.
STATUS: open

### 2026-11-03 architect → planner
TYPE: request
RE: D-78; docs/planning/apply_build_plan.md; docs/prd.md; apply_design.md pointers
BODY: (1) Paste `llm_fill_build_plan.md` §0 (WP mapping) into `apply_build_plan.md` §2.4 and mark V6/V7 superseded, V2/V4/V5/Q1b changed. (2) PRD: a D-78 sentence under F-32/F-34 (the model fills every page; facts written by the program; import from resume always), reason code `model_unavailable` in §7.2, NF-07 Workday deviation. (3) Stage-E pointers in `apply_design.md` §6, §7.2, §7.6, §9.1.1, §9.4.2 step 3, §9.4.5–§9.4.10, §15 to `llm_fill_design.md` (list in its §15).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-35 amendment (stage E READY WITH FIXES: `docs/reviews/Q-35-design.md` H1–H7, M1–M14; tester TR-1–TR-13; D-81, D-82, D-83)
BODY: Worktree `.claude/worktrees/arch-Q-35` (no shell: uncommitted, please commit). Amended: `docs/architecture/llm_fill_design.md` (rewritten in place, same section numbers), `llm_fill_build_plan.md` (rewritten; every WP has a STATUS; RUNNING ones have an "Amendment delta"), `adr/0006-llm-driven-form-filling.md` (status + "Amendment" section; the decision stands), `spikes/S-5b_llm_workday.md` (rule ids only), `src/jobscraper/apply/contracts.py` (still v5, additive only).
Change log (finding → where it is closed):
- H1 grounding → LF §7 G3 (copy rule: every content token of a TEXT / entry TEXTAREA / text `keep` value in the evidence; compose rule = `grounded` only for free TEXTAREA outside entries; entry corpus = block + entry facts), §6.4 `recheck` (copy task; unknown/rejected → optional cleared, required unknown, never kept), §16 oracles.
- H2 fact refs → G2 (a) scope incl. TR-3, (b) relevance via `facts.relevant` (§5.3), (c) value, (d) polarity: program option used only with a tier-2/`extra` label match or when the model's option equals it, else unknown (no "program wins"), (e) no fit → G4 + G5. Audit: model-chosen facts = tier LLM, `fill:v2` (§7 answer mapping; ADR amendment).
- H3 untrusted site values → new G9 (clear / reset / untick / PREFILLED 0.5 "unverified"; E6 in entries), §3.2 `reset()`, G5 covers optional Yes/No.
- H4 privacy (TR-1) → new §6.5: `facts.s_values`, `llm_fill.redact` on the whole user prompt of every call, `current_set` withholding rules, redacted debug dump.
- H5 other employers → G12 + `ResolveContext.other_employers`; generic labels cite only this employer's `extra` (§12.1); G8 trusts MyGreenhouse only for non-TEXTAREA, non-cover-letter fields.
- H6 attachments (TR-8) → L1 (keep only files in `ctx.uploaded` name+SHA-256; page-text clause only with one FILE input; cover letter/transcript never the resume), L1b (required cover letter composed + uploaded).
- H7 revealed/required fields → §8 steps 10 and 12 (re-read rounds ≤ 2; `page.scan_required` before Next) and "Before Submit" (scan before the click); oracles in T3/T4.
- M1 → §4 lock order L1, L2, L4/L5, L6, L3/L7 (an unknown consults L6) + §12.1 context-less qualified label (`| @step#n`). M2 → G7 word list. M3 → §3.3 + `AttemptContext.pre_import` (Greenhouse snapshot). M4 (TR-2) → §13.3/§14: cache stores the ModelDecision only, key + `inputs_hash`, row `facts_used_hash`, guards re-run on replay. M5 → `ResolveContext.resume_entries` (owner WP-N6b, `tailor_flow.resume_entries`), G3/G6 reject with no block, `profile_incomplete` check (§5.2), WP-F3 dropped. M6 → `FillServices` Protocol (contracts) + pinned-signature table (LF §8), `classify` before step 9 and the corrective pass, `PageOutcome.transport_failed`. M7 → §9.1 `step_id` `_<N>` + loop guard on field signatures (§8). M8 → §3.2 Enter rule. M9 (TR-7) → §8 step 7 (nothing changed) / step 9, E7. M10 → BP §0 (I1, L1/L2, F2, W8, F3 dropped), §7 = 5 Greenhouse dry runs, N6 split into N6a/N6b. M11 (D-81) → §11 deadline, §13.1, §13.4 (`attempt_timeout_s` 420, `attempt_timeout_workday_s` 900, both exclude the IMAP wait; checked before each chunk and before typing). M12 → G11. M13 (D-83) → G8 (required `resume_import` kept only when grounded), BP §7 row-by-row audit. M14 → §3.2 strict read-back for every family, search miss clears.
- TR-4 → §6.2 exported constants, FIELDS block last, `via` on every decision, `read_page(rng=)`. TR-5 → `facts.today_sg`, `FillServices.today/now`, `apply_flow.run(now=None)`. TR-6 → `keep_alive` only when set (§6.3, §13.4); T4 pins `fill: rules`. TR-9 → list rules renamed LL1–LL4, T3 owns `apply_pagefill`, T5 owns `apply_questions_page`. TR-10 → E2 overlap coefficient ≥ 0.5 (≥ 0.8 no employer), optional resume/job choice without G5 = 0.8, `second_opinion: false` → unknown, module constants. TR-11 → confirmed (§6.2). TR-12 → G11 + optional WP-T6 eval. TR-13 → noted (dry runs prove widget fidelity).
- D-82 → §4 heading, §15, ADR. D-83 → G8, §15, BP §7.
Nothing accepted without a fix: every HIGH and MEDIUM is fixed.
Contracts (additive, v5): `ResolveContext.resume_entries`, `.other_employers`; `AttemptContext.pre_import`, `.uploaded`; `PageOutcome.transport_failed`; `FillServices` Protocol (backend, model, rules, cfg, today, now, deadline_left, classify, cache_get, cache_put, log); `ModelDecision.via` comment widened.
Running WPs, exactly what changes: T0 + oracles for the new fields/Protocol; T1 pre-filled sample phone/address on wd_a My Information, the fake backend routes on the exported constants and parses the FIELDS block, a reveal stub; T3 + M8/M14/H3 widget oracles and the new `tests/test_apply_pagefill.py`; R1 none (optional `rng`, `pre_import` origins, else R3); R2 strict read-back for all families, optional search miss clears, Enter rule, `reset()` (else R3); N2 `step_id` `_<N>`, `workday_entry: manual` (else N6a); N3 `pre_import` snapshot before the MyGreenhouse click (else N6a); N5 `fill_cache` shape (+ `inputs_hash` key, `facts_used_hash`), `attempt_timeout_workday_s`, `max_reveal_rounds`, `workday_entry`, optional `keep_alive` (else N6b migrates); N1, N4 unchanged.
WPs READY now: T2, T4, T5, T6 (optional), M1–M5, Q5, R3; N6a after lanes M and R merge, N6b after N6a. C1 after the gate.
Evidence: none runnable here (no shell). Before committing please run `python tests/run_tests.py -k apply_contracts` and `-k layering` (expected green: only defaulted fields and a new Protocol were added).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: question
RE: D-83 gate; owner
BODY: For the owner: the gate's Workday postings need fresh approval (D-83). Tenant A's spike posting is already submitted (duplicate guard) and tenant B stops at the required address field until the owner answers it in Profile. This replaces my earlier Q1; Q2 is answered by D-82 and Q3 by D-81.
STATUS: open

### 2026-11-03 architect → tester
TYPE: request
RE: Q-35 amendment; llm_fill_build_plan §2 deltas
BODY: The amendment is in (`llm_fill_design.md` §3.2, §6.2, §6.5, §7, §8, §16; contracts v5 additions). For the running WPs: T0 add the new-field and `FillServices` oracles; T1 pre-fill wd_a My Information with the sample phone/address, route the fake on `SYSTEM`/`SECOND_SYSTEM`/`PICK_SYSTEM`/`RECHECK_SYSTEM`, parse the `FIELDS (JSON):` block (last before the fixed final line), add the reveal stub; T3 add the M8/M14/H3 widget oracles and `tests/test_apply_pagefill.py`. T2, T4, T5 are READY with the inputs listed in the plan; T6 (eval) optional. Rule ids changed: list rules are now LL1–LL4; locks stay L1–L7; guards are G1–G12; entries E1–E7.
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-45 and lane M gaps (D-84, D-85, D-86; lane M outbox questions; lane R R3 choices); contracts v5 + tailor v2 (additive)
BODY: Worktree `.claude/worktrees/arch-Q-35` (no shell: uncommitted, please commit). Change log (item → where):
- Task 1, contracts (`apply/contracts.py`, still v5, additive): `QuestionReason.COMPOSE_NEEDED`, `AnswerSource.COMPOSED`, `ResolveContext.job_title` (closes Q-27's first half), `AttemptContext.composed`/`composed_files`, `PageOutcome.compose_needed`. The chip copy for `compose_needed` is in LF §19.6 (owned by WP-K2's QuestionCard edit). `tailor/contracts.py` v2, additive: `ComposeRequest`, `ComposeResult`, `COMPOSE_VERSION`, IssueCode `VERB_UPGRADE`/`PRIVATE_VALUE`/`OTHER_EMPLOYER`/`PLACEHOLDER`. No `FillServices` member was added, so T0's isinstance oracle is unaffected.
- Task 2, Q-45 → LF new §19 (targets, fill_page step 7b, flow loop, the tailor's compose call, checks C1–C7 reusing `validate.numbers`/`facts` and `UPGRADE_WORDS`, owner opt-in `apply.compose.enabled` default false, length limits, S values redacted and checked, audit holds the whole text, copy), L8, §6.1/G3 (targets never go to the page model), §13.4 config, ADR-0006 amendment bullet, `tailor_design.md` §17 pointer. Build plan §5b: WP-K1 READY, WP-K2 READY once `int/Q-35-M` is in personal, WP-K3 not READY (after R3, N6a, K1, K2), WP-T7 READY (skip-clean). The gate runs with composing off.
- Task 3, lane M gaps: (1) `links.*` facts outside entry groups → G2(a), as built. (2) profile_gap without a tier-2 row → G2(f) documents lane M's `_rule_gap` fallback; tier-1-only paths (`contact.city`, `links.*`) stay `no_rule` until tier-2 rows exist (researcher request below). (3) One-word labels generic → §12.1, as designed (only L6 reuse and capture are narrowed). (4) G12 (and R4) rejects captured `no_rule` → §11, as designed. (5) Extra kwargs → §8's pinned table now carries every built signature (decide's `rules/sections/model/prompt_hashes/cfg/blocks` with "must pass" notes, `Decision` fields, `Chunk.locked`, `CallLog`, `pick_option` `sensitive`/`deny`, `lock_page` `page_text`, `field_sig` `key` required, `read_page` extras, widgets). L1b's cover-letter question → Q-45.
- Task 4: D-84 R1 → G12; R2 → G5 + G2(d); R3 → E4; R4 → G2(b) + new G13 (any source). D-85 → LF §9.2 and AD §9.1's `otp_pattern` row. D-86 F7 → G2(e); F8 → §13.3 (HMAC `field_sig`); F9 → §11 + §19.
- Lane R's R3 choices: (a) deadline → `transport_failed` "transport: timed out": **accepted**, with one flow rule (LF §8, §11): N6a checks `services.deadline_left() <= 0` and then ends `failed(error)` "timed out on <step>", else `model_unavailable`. (b) Cache stores no `second`/`corrective` replies: **accepted** (§13.3): replaying a stored second opinion would count one run as two, so G5 re-asks on replay.
- Also seen: the tester/lane R question on `stubs/enter_form.html` (M8). The rule stands; the M14 read-back oracle should move to a prompt outside any form, as lane R proposes.
Changes for already-built code: lane M K2 (compose targets out of the page schema; L8; notes); lane N/N6a the deadline split above; nothing else built changes.
**One known red:** `tests/test_apply_questions.py::test_question_contract_types_are_the_ones_the_design_names` pins the `QuestionReason` set exactly (line 119), so `COMPOSE_NEEDED` breaks it by design. The tester adds "compose_needed" to that set in the same merge (D-86 F9 asked for the member).
Evidence: none runnable here (no shell). Please run `python tests/run_tests.py -k apply_contracts`, `-k apply_questions`, `-k tailor` and `-k layering` before committing. Expected: green apart from the pin above; only defaulted fields, new enum members and new dataclasses were added.
STATUS: open

### 2026-11-03 architect → researcher
TYPE: request
RE: LF §7 G2(f); D-74 rule rows
BODY: Tier-2 rows (A03 style) for tier-1-only profile paths that forms ask as single questions, so an empty one is captured `profile_gap` instead of `no_rule`: `contact.city`, `links.linkedin`, `links.github`, `links.portfolio` (labels and synonyms only, generic; no values). Private paths such as the postal code don't need one: they are listed as set/empty, so G2(c) already captures them as `profile_gap`.
STATUS: open
