# Outbox: architect

Only `architect` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD architect → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-07 architect → coordinator
TYPE: handoff + request
RE: Q-74 (D-105, D-107), review `docs/reviews/Q-74.md` F1/F2/F3/F5/F8; `docs/architecture/q74_model_sees_sensitive.md`, `adr/0008-model-sees-sensitive.md`, `config/applicant.example.yaml`
BODY: Spec amended to match the fix round as built (worktree eng-q74; no shell, please commit, e.g. `docs(arch): Q-74 amend design + ADR-0008 for review F1-F8 (D-107)`). Design §1/§3: under the flag, the tier-5 corpus holds contact details only, and a protected hit is UNGROUNDED with `sensitive=True`. Notes are scrubbed and token violations reduced to their kind. The cloud-tag rule and `is_local_config` are added. §4: ten llm_fill hook points, including the `pick_option` decision (keep the full redaction), G3 ≈421, text guard ≈691, and the flag folded into the fill-cache `inputs_hash`. §6 T5 is marked superseded. ADR-0008: Decision and Consequences amended; the old "cached fills re-run once" claim is corrected. Changelog line at the top of the design.
REQUEST 1 (config/ is outside my scope): in `config/applicant.example.yaml`, replace line 3 with exactly:
`# S = sensitive: never written to logs. The AI reads S values only when apply.model_sees_sensitive is on and the model runs on this computer; except contact details, they never ground an AI-written answer (those questions wait for you).`
This supersedes the engineer's proposed wording.
REQUEST 2: record D-107 in `instructions/02_status.md` §4 (no row exists yet). Suggested row: `| D-107 | Ollama cloud model tags are not local (review Q-74 F3) | backends.is_local / is_local_config are False when the model tag ends in -cloud or :cloud (case-insensitive), even on 127.0.0.1, since Ollama forwards those to ollama.com; D-105 then stays off | Architect, 2026-11-07 | DECIDED |`.
Open questions: none.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff + request
RE: Q-74 (D-105), Q-44 + Q-73, Q-76; `docs/architecture/q74_model_sees_sensitive.md`, `adr/0008-model-sees-sensitive.md`, `apply_design.md` §5.3 (D-105 amendment paragraph), `q44_refresh_from_resume.md`, `q76_application_detail.md`, `src/jobscraper/apply/contracts.py`
BODY: All three are fast-track designs, each ending with "READY TO BUILD: yes". Please review, mark them READY, and commit (I have no shell). Suggested message: `docs(arch): Q-74 Q-44 Q-73 Q-76 lean designs + ADR-0008 + contracts D-105`.
- **Q-74.** `apply.model_sees_sensitive` (owner value true in config/config.yaml) takes effect only when `backends.is_local` holds (Ollama on localhost, 127.0.0.1 or ::1). A Docker or LAN URL counts as remote.
  - It widens prompts only: `llm_extract` / `grounding_text` gain `sensitive=`, used in the tier-5 prompt and corpus.
  - It leaves alone: logging, naming, tier-1/2/4 routing, EEO, G7.
  - Contract (done, additive): `ResolveContext.model_sees_sensitive: bool = False`, plus D-105 notes on `Answer.sensitive`, `CapturedQuestion.sensitive` and `Fact.private`.
  - Q-35 merge rule: design §4.
  - Badge: "Private: local AI only". It follows the effective value.
  - 9 steps, 1 lane.
- **Q-44 + Q-73.** The profile job also writes `data/applicant.refresh.json` (resume facts only). The pure plan in applicant.py runs against the current applicant.yaml on every GET.
  - It updates or removes only `from_resume: true` entries and template placeholders. It adds new entries and skills (only skills that appear in the resume text). Owner entries and languages/links are never touched.
  - Dates are parsed deterministically. Unread dates are left null, never "present".
  - Summary card plus a collapsed log; no absolute paths.
  - 8 steps, 2 lanes (P: Python, V: Vue).
- **Q-76.** `store.last_attempts()` (one GROUP BY query) feeds a `last_attempt` pill on `/api/applications`, plus `GET /api/applications/{id}/attempts` with texts from REASON_TEXTS/STATE_TEXTS.
  - `JobDetail.vue` extraction is step 5, only after Q-75 lane I merges. Touch points: design §4.
  - 6 steps, 1 lane.
REQUEST: record D-105 in 02_status §4, and update the Q-74/Q-44/Q-73/Q-76 queue rows (status READY, design links).
Open questions: none for the owner.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff
RE: Q-72 (a), D-161, D-160; `docs/architecture/mail_status_design.md` header + changelog (4), §3, §7, §8 row 7a + its note, §11.3, §15, §16, §17 (F-50l)
BODY: MS amended, READY (Q-72, D-161); please record D-161 and commit (no shell). The rule: rows 4–9 settle every matched candidate (single or ambiguous) as NONE `terminal`, and `match.signals` has no `role`/`req_id`/`thread`, and the mail is newer than every candidate's `last_event_at`, and the category is `acknowledged` or `rejected`. Then the result is SUGGEST(to=None, `maybe_untracked`), offering all matched candidates.
Exact changes: §3 `Reason.MAYBE_UNTRACKED = "maybe_untracked"` (suggested section, in `SUGGEST_REASONS`); `REASON_TEXTS` "This email may be about an application you haven't added."; `CONTRACT_VERSION` stays 1; no SKIP or COUNT key (it counts as `suggested`). §8 new row 7a plus the note "Row 7a, maybe untracked" (categories, rows 5/6/11, signals, code location, storage). §7 "Mail for untracked roles" gets one sentence. §11.3 gets a "Maybe untracked" copy row: Got it plus Open in Gmail; the app line falls back to `candidates[0].company`. §15 records the D-161 decision. §16 has 10 named oracles. §17 F-50l cites it.
Category ruling: assessment, interview and offer are already never silent (row 7 `reopen` / row 4 `several_applications`), so 7a adds only `acknowledged` and `rejected`. `withdrawn`, `posting_closed` and `kept_on_file` are excluded as noise.
Schema: no change confirmed (`mail_evidence.job_id` NULL + `candidates_json`, `to_status` NULL; `reason` has no CHECK). One flow change the engineer must make: for `maybe_untracked`, `mail_messages.job_id` stays NULL and evidence `job_id` is NULL even on a STRONG match. Today `mailstatus_flow.decide` sets both from `m.job_id` for STRONG (lines 453, 477).
This supersedes the Q-72 row's `untracked_hint` count idea; please update the queue row text.
Open questions: (1) "Find the role" link: ruled no (the Inbox has no company-search URL). Raise it if the owner wants one. (2) Expected noise: a role-less late rejection for an app already rejected will hint. Accepted as cheap; revisit after real use.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff + request
RE: Q-60 MS amendment for D-157 (a)–(j), D-156 (1)(3)(4)(5); `docs/architecture/mail_status_design.md` §2.3, §3, §5.1, §5.4, §5.5, §6.5, §7, §8, §9, §10.1–§10.4, §11.1, §11.4 (new), §12, §15 R3
BODY: MS amended, still READY; no ADR change (all additive; ADR-0007 never mentioned retry_after). §3 matches lane S's contracts.py (c076f68) exactly: `AppCandidate.first_event_at`, `Reason.BACKFILLED` + `SUGGEST_REASONS`, `REASON_TEXTS` "You added this application after this email arrived." Please run `-k mail_contracts`.
Points to decide (no silent pick):
1. REQUEST (lane F, FL-1): D-157 (a) stores a `skipped/internal` row and counts `errors`, but contracts.py has no `Reason.INTERNAL` and `COUNT_KEYS` has no `errors`. MS §5.4 uses the value `"internal"` and `counts["errors"]` and marks them "not yet in §3". Recommend adding `INTERNAL = "internal"` (skipped section, in `SKIP_REASONS`) and `"errors"` to `COUNT_KEYS`; tell me and I'll add both to §3 in the same commit as the code, or lane F transcribes them into §3 too.
2. D-157 (i) says "suffix words"; lane S drops the words *anywhere* in the name and compares with any company variant; it also blocks a role/req id from lifting an extra-words sender name to STRONG (MS §7, decision step 4), where D-157 says only "→ WEAK". I wrote MS to the built code plus your "<words> at <name>" addendum. Confirm the role rule; note that a body name plus a role still gives STRONG, so "Globex Labs" mail that names "Globex" in the body with a matching role still matches the Globex application.
3. D-157 (a) isolation: I excluded the busy-DB `sqlite3.OperationalError` from per-message isolation (otherwise a locked DB would mark messages skipped forever); it keeps the §12 "stop, retry next time" row. Confirm.
4. D-157 (b) covers `mail_record` / `mail_resolve_pending` only. The duplicate path and the end-of-scan path call `mail_cursor_set` (an upsert), which can still create an orphan cursor after a disconnect. Recommend the same account check there.
5. D-157 (d): "a call was made and gave no usable answer" read as `BackendError` from `backend.complete`; a parsed but unusable reply is already an `unclear` suggestion (§6.5), so it resolves the row rather than counting a retry.
6. D-157 (f): I named the write path `store.mail_supersede(now)` (end of sync) plus accept/dismiss for their own application. Rename freely if lane F built another name.
7. D-157 (h) accept: a `backfilled` suggestion would always fail §8 row 6 on accept (the owner change is newer by definition), so MS says accept skips row 6 for it. Lane F/S must build that, or Accept gives 409 `changed`.
8. `POST /api/mail/sync` `400 {code: "no_mailbox"}` is also a command result, not a SyncCode; D-156 (5) didn't list it, so I left it out of the "Command results" paragraph.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff
RE: Q-60 MS alignment (D-153, D-154 a–g, D-155 renumber); `docs/architecture/mail_status_design.md`, `mail_status_build_plan.md`, `adr/0007-mail-status-imap.md`
BODY: MS now describes the code as built on int/Q-60-mail-status e2b3998: §5.6 (F4 argument refusal, F5 URL forms, T4 punctuation), §6.2 (shared domains dropped from the gate; Reply-To still opens the gate and triggers `job_board`), §6.3/§6.4 (D-152 assessment vendors, live included), §6.5 (quote ≥ 15 chars and ≥ 3 words on the normalised quote, `model:short_quote`), §7 (employer_domains/is_shared_domain; restricted names as-written everywhere, never STRONG, not via role/req id), §8 (D-153 row 2; `as_bool`), §10.4, §11.3 (F8), §12, §13. Q-60 IDs renumbered to D-150..D-154 in docs/architecture. MS stays READY; §3 contracts unchanged (the code didn't change them).
Points to check (no silent pick):
1. D-155 says "the architect already uses the new IDs in docs/architecture/"; before this pass it didn't (D-90/D-91 were still there). Now true.
2. D-154 g names `enabled` and `model` too; only `require_auth` (transition.build_policy) is built. `MailStatusConfig` is lane F's: MS §10.4 asks it to use the `as_bool` truth table. Whether config.py may import `mailstatus.transition` is a layering question (`tests/test_layering.py`); a local copy of the same table is fine. The per-account `enabled` in `PATCH /api/mail/accounts/{id}` is JSON; I did not check the router.
3. Code comments in `mailstatus/match.py` (`_evaluate` docstring, step-4 comment) use a real employer name as the common-word example; the doc uses "Summit"/"Acme". Public repo: suggest an engineer swaps it to a neutral word at the next touch.
4. The `stale` emit and the F8 password behaviour are written from the review fix text and `MailEvidence.vue` lines 9/48; `MailCard.vue`'s consent order was not re-read.
5. `contracts.py` comment on `AppCandidate.employer_domains` ("careers_url and a non-ATS posting host") is still true as input; the filter is in the stage. No contract change needed.
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

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-60 / F-50 (D-90, D-91); docs/architecture/mail_status_design.md, mail_status_build_plan.md, adr/0007-mail-status-imap.md
BODY: Stage-B design for application status from email is READY for stage E. Written only in `.claude/worktrees/feat-Q-60/` on `int/Q-60-mail-status`; not committed (no shell): please commit as `docs(architecture): Q-60 stage-B design, build plan, ADR-0007`.
- Placement (ADR-0007): foundation `imapread.py` (the only F-50 IMAP code; web/ may not import it) + stage package `mailstatus/` (contracts, rules, match, transition, model; pure) + orchestrator `mailstatus_flow.py`. The web timer (`web/mailsync.py`) spawns `python -m jobscraper mail sync` as its own child (not JobManager), with a DB lease (`mail_sync_runs`, BEGIN IMMEDIATE + heartbeat).
- Contracts: new `mailstatus/contracts.py` v1 (full listing in MS §3; WP-S0 transcribes it, and I sign off at review). `apply/contracts.py` is untouched.
- New tables (SCHEMA_VERSION 4 → 5): `mail_accounts`, `mail_cursors`, `mail_messages`, `mail_evidence`, `mail_sync_runs`. If the concurrent session also bumps to 5, make it 6 at merge, with the comment listing both (MS §9).
- Lanes: S (S0–S3 stage), I (I1 imapread, I2 apply/mail Spam fix, U1 Settings card, U2 Applications), F (F1 store, F2 config, F5a web backend, F3 flow, F4 CLI, F5b real children). Tester T0–T6, researcher R1 (rules file) + R2 (spike, owner consent), planner P1. T0 must merge together with S0 (the layering sets).
- Decided (MS §6.4, §8, §15): HireVue on-demand → assessment; posting closed and lone kept-on-file → suggestions; `assessment` added to `applications.statuses`; model-tier verdicts never automatic; automatic changes need Gmail DKIM/DMARC pass and (except acknowledgements) not Spam; no unmatched-mail list; no X-GM-RAW; no IDLE.
- D-91 readings (no contradiction): "anything else → suggestion" = forward moves below the confidence bar plus the explicit cases. Backwards, same-status and stale (older than an owner change) mail change nothing and raise no suggestion. "Confident" excludes model-tier verdicts.
Requests:
(1) Add `config/mail_rules.yaml` to the researcher's write scope (`.claude/scopes.json`) for WP-R1.
(2) Add `JOBSCRAPER_MAIL_SYNC=0` to the dev-instance command in CLAUDE.md: a copied DB would otherwise read the real mailbox (MS §15 R3).
(3) If ADR-0007 is taken on `personal` at merge time, renumber this ADR and its two references.
Owner questions (recommendations in MS §15; none blocks the build): which mailboxes (application Gmail first); keep automatic offer and rejected under the bar; the `assessment` status; the owner triggers the first real sync after the merge go-ahead.
Evidence: none runnable (docs only). After the commit, `python tests/run_tests.py -k layering` should stay green (no code changed).
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-60 stage-E amendment E1 (Oleeo tenants); mail_status_design.md §3, §6.1, §7, §9, §14; mail_status_build_plan.md WP-S1, S2, F1, T3, R1, R2
BODY: E1 is in.
- §6.1: platform keys `tenant_from_subdomain` (strict subdomain of a platform domain; at most one tenant flag per platform) and `tenant_sites`; Oleeo `{id: oleeo, kind: ats, domains: [tal.net], tenant_from_subdomain: true, tenant_sites: [tal.net]}` in the seed; Workday gains `tenant_sites: [myworkdayjobs.com]`.
- §7: `compact()` (normalised, spaces removed); the `tenant` signal covers both flags and compares in compact form against `app.tenants` and every company variant (both flags: yes, as asked).
- §3, §9: `mail_match_context` returns raw `tenant_hosts` (attempt `tenant_host` plus the hosts of `jobs.url`, `applications.url` and `companies.careers_url`); `match.tenants_from_hosts` builds `AppCandidate.tenants`.
- BP: S1, S2, F1, R1 and T3 point at E1; R2 is DONE.
CONTRACT_VERSION stays 1: only the `AppCandidate.tenants` comment changed.
One deviation from the literal ask: the host suffixes come from the rules key `tenant_sites` rather than a hard-coded `myworkdayjobs.com` / `tal.net` list in store or code. That keeps "a new ATS without code edits" (§14) true and keeps domain data out of `store.py`. Please commit as `docs(architecture): Q-60 E1 Oleeo tenants (tenant_from_subdomain, compact match)`.
STATUS: open
