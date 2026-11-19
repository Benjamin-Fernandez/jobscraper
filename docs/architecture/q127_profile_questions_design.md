# Q-127: no per-company questions on the Profile page; the model fills, each application keeps its own answers (D-215; KA-2, touches KA-1)

**Stage B**, queue Q-127. Author: architect, 2026-11-15. **Revised 2026-11-15** after the independent review `docs/reviews/Q-127-profile-questions-design.md` (READY WITH CHANGES): H1-H3, M1-M6, L1-L6 and pins 13-21 folded in, plus the Coordinator's decisions D1-D5 and owner D-216. B.11 lists where each lands. **Decision record:** `adr/0012-no-per-company-questions.md`. **Input:** D-215 (owner, verbatim in `instructions/02_status.md` §4), with D-203, D-205, D-201, D-208, D-87, D-209, D-213, D-216 standing. **Builds on:** `llm_first_fill_design.md` (**LFF §n**), `questions_design.md` (**QD §n**), `q116_settings_design.md` (**Q116 §n**), `q118_ui_polish_design.md` (**Q118 §n**), `apply_queue_design.md` (**AQ §n**). Line numbers: `personal` @ 9c3982e for Part A.1; `int/Q-121` (this worktree) for A.4 and everything in Part B. Examples use made-up names only ("Example Co", "Sam Sample").

## Part A. Diagnosis

### A.1 The trace on `personal` (the live app: `apply.fill: llm`, `fill_policy` strict by absence)
1. **The answer is thrown away on wording.** `pagefill.fill_page` (pagefill.py:126) asks the model, then the guards rule: G2a "ref out of scope", G2b "fact not relevant to the question", G2c "profile_gap", G2d, G2e "no_option_fits" turn the model's answer into `unknown` (guards.py:554-596). In the resolver, a canonical field without a profile value may only use memory (resolve.py:1683-1694), a tier-2 stop is final ("a stop never reaches tier 5", 1700-1708), and tier 5 never runs for a sensitive or attestation field (1714).
2. **Unknown + required = stop.** `PageOutcome.unknown_required` (pagefill.py:836) → `page_result` stages the rows, captures and raises `unanswerable_required` with the first label (apply_flow.py:1377-1382); the older path is the same (`_unanswerable` 341-351, `correct` 1537).
3. **Every stop field becomes a question.** `_capture_questions` (apply_flow.py:673-712) → `capture_page` (questions.py:341-394): every required unknown that is not a file, hidden or employer-specific declaration. Its reason comes from `page_reason` (306-338). Any model "unknown" without a unique tier-2 row is `no_rule` (325-329): that is where 18 of the 24 cards come from.
4. **A question's identity is its wording.** `label_norm = qualified_label(label, help, context, step, ordinal)` (questions.py:376-377). `signature = sha256(kind, label_norm, sorted options)` (401-412). The key is the first of: an exact label in `extra`, a row with the same `label_norm`, the model's `same_as` (only among the 50 newest non-sensitive keys of the same kind, 566-571, 610), or a slug (`assign_key` 662-689). A sensitive question is never named (650).
5. **One sighting means a card, for good.** `upsert_question` inserts with status `open` (store.py:2089-2097). A row seen again after it was answered reopens (2080).
6. **The card names the company and sits on the owner's page.** `question_groups` makes one group per key, with `employers` set to company names (store.py:2226-2288, at 2283), served by `GET /api/questions` (routers/questions.py:96-122). `ApplicationDetails.vue` stacks three things, in this order:
   - "Needed before auto-apply" (591-602);
   - `QuestionsInbox` (605-612; "Questions from applications", QuestionsInbox.vue:193-194), above "Your details" (618);
   - the `extra` group "Answers you gave to application questions" (751-797).

   `QuestionCard.vue` prints "Asked by <companies>" (71) and offers an employer scope picker (193-197). The tab's subtitle promises "the questions it still needs you to answer" (Profile.vue:280).
7. **Every nudge points at the cards.** Profile badge = open groups (App.vue:248-262, tabs.js:40). Overview "To do": "N questions waiting for your answer" with "Answer questions" (Overview.vue:103, 249-256). Applications: "Needs your answers" with "Answer in Profile" (ApplicationRow.vue:189-193).
8. **Retry hangs off the cards.** A stopped role is "ready" only when every question sighted in its attempt is answered and none is dismissed (store.py:2201-2224; routers/questions.py:75-77, 293-308).

### A.2 The major flaw
**The filler treats "code could not prove an answer for this wording" as "the owner must answer". Each such field becomes a permanent card at its first sighting, keyed by that employer's exact wording, on the owner's own page. So the owner is the resolver of last resort for every employer's phrasing, and the page grows with the number of forms, not with the owner's facts.**

### A.3 Contributing flaws
| # | Flaw | Where |
|---|---|---|
| C1 | "Unknown" means "the wording didn't match", not "the fact is missing". Guards veto answers the profile holds. On the live attempt 28 required fields were unknown, 18 of them `no_rule`, and the facts were in the profile | guards.py:554-596; resolve.py:1700-1714; questions.py:325-329 |
| C2 | Identity per wording plus help, context, step and options. Naming is narrow (50 newest keys, same kind, never sensitive), so equal meanings never merge and the list never converges | questions.py:376-377, 401-412, 566-571, 610, 650 |
| C3 | The threshold is one sighting, and an answered row reopens when seen again | store.py:2080, 2093 |
| C4 | The owner is the only way to recover: retry needs every card answered | store.py:2201-2224 |
| C5 | One page mixes the owner's details with leftovers from applications: cards above the form, company names, employer-scoped answers, employer wordings in the `extra` group. The badge never reaches zero while forms keep arriving | ApplicationDetails.vue:591-618, 751-797; QuestionCard.vue:71, 193-197; App.vue:252-257 |
| C6 | No way for a common question to become a proper field: QD §6.3 says "documented, not built" | questions_design.md §6.3 |
| C7 | The web app has no per-application view of what was sent. The rows live in `apply_answers`, readable only through the CLI `apply show`, so the Profile was the only place the owner could act on a form's question | store.py:1907 (`answers`); no route in routers/applications.py |

**The other 6 of the 24 are not wording mismatches (review Q1).**
- **3 `no_option_fits`:** the guards G2d / G2e. The model's pick was not among the offered options, or no option fit the fact.
- **2 `attestation_unclear`:** the locks L3 / L7. The declaration reader was unsure.
- **1 `compose_needed`:** a required cover letter or "why us" text, with compose off.

The first five are guard and lock vetoes (C1), so C2 does not explain them. Under `always` they end protectively or are answered (B.2d, last row), and they never feed the counter.

### A.4 The same trace on `int/Q-121` (always answer, built, not on)
**What it already fixes:**
- The model answers every field from one briefing: the profile, `extra`, the resume and the job (LFF §1, §3).
- The guards are advisory (LFF §8).
- `unanswerable_required` remains only for the designed stops (LFF §9); the 18 `no_rule` fields would be answered.
- Q-119 removes the phantom fields.
- Rehearsal: 361 fields, 27 of 30 pages ready, 0 never-violations in the last four passes.

**What still breaks D-215:**
| # | Violation | Where |
|---|---|---|
| V1 | "Answered for you": every assumed field, required or optional, becomes a card per wording (status `assumed`), captured after every page and never named, so grouping is by wording only. It shows with Keep / Change and a "who" line | questions.py:410-444; apply_flow.py:771, 1806-1821; store.py:2203, 2220; QuestionsInbox.vue:68-75; QuestionCard.vue:73, 187-194; routers/questions.py:614-627 |
| V2 | Owner-fact and consent stops capture a card. A fact with no field (passport, bank, other ID) becomes a `no_rule` card saved to `extra` | apply_flow.py:1625-1630, 1642-1663; questions.py:447-474 |
| V3 | Retry still needs a captured row, and the copy sends the owner to "Questions" | store.py:2361-2394; LFF §7.1 `OWNER_FACT_MISSING` hint |
| V4 | Applications and Settings send the owner to the Profile cards: "Review answers" opens Answered for you; the fill-policy text says "listed under Answered for you in Profile" | attempts.js:50-57; ApplicationRow.vue:176-201; ApplySettings.vue:279-280 |
| V5 | The badge and the Overview "To do" still count questions | App.vue:256-261; Overview.vue:103 |

**Reused as is:**
- "Needs your input: <fact>" with a link to the field (attempts.js:90-117, 195-205), fed by `owner_fact_path` (store.py:1951-1975; routers/applications.py:115-121, 211-212).
- `assumed_counts` and the "Submitted · 3 answers assumed" chip.
- `apply_answers.assumed`, `apply_answers.corrected_json` / `corrected_at` (M22 columns, unused so far).
- `store.answers(attempt_id)`.

## Part B. Design (decided)

**Two releases, both built on `int/Q-121` (Coordinator D1):**
- **Release 1, the one visible go-live:**
  - no cards and no question badge;
  - Applications → What was sent, with "Use a different answer next time";
  - "Needs one detail" links and the retry notice;
  - the rebuilt Profile page;
  - Settings → "Answers you corrected".

  It reaches `personal` in **one** scrubbed squash of `int/Q-121`, together with the always-answer filler. `fill_policy: always` is its own last commit.
- **Release 2, invisible:** topics, the counter, proposals.

### B.1 The rule
- **R1. The Profile page never shows a question tied to a company or an application, under any fill policy.** The page shows only the owner's details. A question may enter the page in one way only: as **one proposed field** in "More about you", when R2-R4 hold (Release 2).
- **R2. "Different applications" = different employers.** It is a config value, so the owner can change the reading without a release:
  - `apply.topics.count_by: employer | job` (default `employer`);
  - `apply.topics.min_count`, default **16**, i.e. more than 15, clamped to 2..200.

  Why employers: applications to one employer share one form. Sixteen roles at Example Co asking "Why Example Co?" are one company's question, which is what D-215 forbids, and the 10-per-employer daily cap (D-204) could cross 15 job ids in two days.
  - Retries of one job count once.
  - Employer key (L2): `COALESCE(NULLIF(employer_norm,''), 'c:'||company_id, 'job:'||job_id)`.
- **R3. Counted sightings: a REQUIRED field the details and the resume could not answer** (`question_sightings.required = 1`; an optional guess is not something an application needs, M2):
  - under `strict`, a field captured at a stop;
  - under `always`, an `assumed` answer (basis `assumption`, `fallback:F2-F6`, or a failed basis check), or an owner-fact stop for a fact **with no profile field**.

  Never counted:
  - a field whose fact has a profile path: `target_path` set, or a topic mapped to a path (R4 T4);
  - a composed text, an employer-specific declaration, a file;
  - an A1 protected class with a profile home: `declaration:*`, `consent_*`, `marketing`, `work_right`, `sponsorship`, `self_id:*`, and `owner_fact:*` other than the four no-field facts;
  - a topic whose naming says it depends on the employer or the job (`about_you: false`).
- **R4. The same question = the same topic.** Each counted `questions` row gets a `topic` key, assigned by the first rule that holds:
  - **T1 (code):** the A1 class `owner_fact:<which>`, for `which` ∈ passport, bank, national_id, other_id, gives the fixed topic `owner_fact_<which>`, titled by contract (`NO_FIELD_FACTS`), `named_by = class`.
  - **T2 (code):** a stored row with the same `label_norm` (any kind) already has a topic: use it. `label_norm` is qualified only for generic labels (`plan.py:165-170`), so "Please specify | @step#2" never merges across employers.
  - **T3 (provisional):** `slug_key(label_norm)`, `named_by = rule`.
  - **T4 (the local model, after the attempt has ended):** `ask_topic` reuses the naming machinery (QD §5.3: no profile value, no answer, no employer name).
    - The prompt lists up to 50 existing topics (most employers first) **and the Profile form's field titles** (`applicant.FORM` labels, no values).
    - The reply is `{key, title, description, same_as, profile_path, about_you}`.
    - `same_as` may join any listed topic of **any kind**, since "Notice period" arrives as a number, a range list or text.
    - `profile_path` is validated against `questions._form_targets()`. A mapped topic stores `topics.profile_path`, is never proposed, and its sightings feed `needed_by[path]` ("Needed by {n} applications", shown only while that path is empty) (M2).
    - `parse_topic_naming` re-checks everything. A valid `same_as` merges the provisional topic: `questions.topic` is updated and the provisional row is marked `merged`.

    **When it runs (L3):** after the browser session is closed and the attempt row is final; never while the queue is stopping or paused; in order of employers, descending; at most `naming_max_per_attempt` (5) calls of 15 s each; it stops at the first transport failure. Down or unusable → the slug stays.

  A wrong merge or split only moves a counter and a proposal's wording; an added field never answers a label by itself (H1).
- **R5. Counter (store, B.5).** One query over `topics` ⋈ `questions` ⋈ `question_sightings`, counted by `count_by`, against `min_count`.
- **R6. When it is crossed.** After the naming pass the flow calls `store.propose_topics(cfg, now)`.
  - **Only a topic whose `named_by` is `model` or `class`, with no `profile_path`,** goes from `counting` to `proposed` (M1).
  - A provisional topic over the threshold gets one naming call at that moment; if that call fails, the topic stays `counting`.
  - A title or description is refused, and the topic is marked `about_you = 0`, when it holds a sighted employer's name (D-210 match), holds a `?`, or is longer than 60 characters.
  - `owner_fact_national_id` is counted and printed by `apply topics`, but **never proposed**: a full NRIC can never be stored (`applicant.py:1082-1089`) (M3).
  - `owner_fact_passport`, `owner_fact_bank` and `owner_fact_other_id` are proposed with `sensitive: true` (M3).
  - One log line per proposal: key and counts, no labels.

  The owner then sees **one row** in Your details → More about you, with no company and no verbatim wording (copy in B.4). The choices:
  - **Add to details** saves `extra.<topic>` = `{title, description, kind (text | yes_no | number | date; choice and multi become text), labels: [], value, promoted: true, sensitive}` and sets the topic to `added`. **A promoted entry carries no labels.** It reaches forms through the briefing (LFF §3: the model reads the entry's title, description and value next to the question's own wording, and the basis check of `always.py` verifies the `extra:<key>` basis). It is never an exact-label answer: tier 3 and L6 match nothing (H1). `applicant.validate` accepts `labels: []` only with `promoted: true`.
  - **Not needed** → `dismissed`: never proposed again. Removing an added field also → `dismissed`.
  - Sightings keep being recorded after a decision (for `apply topics`), but nothing else is shown.

### B.2 What replaces the cards (Release 1 unless marked)
- **(a) The model fills every field (always answer).** Switch-on preconditions, in order:
  1. A1 passes its fifth review (U9 + fix6) and the LFF §17.8 dress rehearsal.
  2. Release 1 of Q-127 is in the squash: the cards are gone, What was sent exists, the Profile is rebuilt.
  3. The B.8 go-live gate: the data copy, the squash hygiene, the strict rollback exercised.
  4. The owner pastes the `doctor` profile-shape printout.
  5. Last, the `config/config.yaml` line `fill_policy: always`, as its own commit.

  **Owner D-216:** the go-live is direct. The first Auto-apply click after the switch-on sends a real application, and there are no trial runs (`apply.always_trial_runs` stays 0). Release 2 is not a precondition.
- **(b) Assumptions live with the attempt and are shown where the application lives.** They are already stored: `apply_answers.assumed`, `source`, `evidence` (the reason), `entries_note`, the attempt's `trial` flag, and `owner_fact_path`. New: **Applications → the role → "What was sent"** ("What was filled" when nothing was sent). One row per field:
  - the employer's label and the value;
  - the basis in plain words (table below);
  - an **Assumed** badge with its reason, or **Not answered** for an empty required field;
  - the attempt's `entries_note` as a line under the title ("1 of 2 education entries added").

  **"Use a different answer next time"** ("Answer for next time" on a not-answered row) opens the field's own widget, with options from `options_json`, plus one checkbox **"Only for applications to {employer}"**, **checked by default** (H3, review Q11). Unchecking it means every application.
  - **Key rule (H2).** The key is never a `questions` row's key.
    1. If an `extra` entry already lists this exact `label_norm`:
       - its `labels` are exactly `[label_norm]` and it is not `promoted` → update it (by scope);
       - otherwise → **409** `shared_answer` ("This question shares a saved answer with other questions. Change it in Settings → Apply → Answers you corrected.").
    2. Otherwise the key is `slug_key(label_norm)` over the `extra` keys, taking the next free suffix (`_2`, …) when the name is held. The new entry's `labels` is exactly `[label_norm]`.

    The write never changes another entry. `label_norm` = the attempt's captured row's qualified label for that field, else `apply_answers.label_norm`. A generic label (`plan.is_generic`) with no captured row → 422 `too_general`.
  - **Refusals (H3).** `can_remember` is false, and the route answers 422 `follows_your_details`, when either:
    - the row's source is `profile:*`, `field_map*`, `standing:*`, `default:*`, or strict `declaration`;
    - or the row's class (`apply_answers.field_class`, new in Release 1) is `declaration:*`, `consent_*`, `certification`, `acknowledgement`, `marketing`, `work_right`, `sponsorship`, `self_id:*` or `owner_fact:*` (certification and acknowledgement added in contract v10, review S2 L1: they follow the consent rule D5).

    A row with no class (strict, or attempts older than Release 1) is also refused when it took a value and `declarations.classify_field` names a declaration. The row then shows "This answer follows your details. Change it in Your details." with a link to the section. Allowed: strict `no_rule`, `no_option_fits`, `attestation_unclear` rows, and assumed ordinary rows. The check lives in one pure helper, `web/remember.py` `remember_refusal(row)`, used by both the GET (`can_remember`) and the POST.
  - The write stamps `apply_answers.corrected_json` / `corrected_at`, and marks that attempt's `questions` rows for the field `answered`, so `strict` readiness follows.

  **Remembered answers are listed under Settings → Apply → "Answers you corrected"**: title, answer, scope, Forget.
  - The first 20 are shown, then "Show all".
  - It is an owner-visible choice (review Q2): scoped entries show the employer's name, and titles may come from an employer's wording.
  - It sits in Settings, not Profile, because it grows only by the owner's own clicks and keeps the Profile free of question wording (R1).
  - Promoted topics are not in this list.

  | Source | Basis shown |
  |---|---|
  | `profile:<path>`, `field_map`, strict `profile` | From your details: {form label} |
  | `memory:extra.<k>`, strict `memory` | Your saved answer |
  | `standing:<id>` | Worked out from your details |
  | `default:<rule>`, strict `declaration` | Your standing answer |
  | `resume` | From your resume |
  | `job` | From the job posting |
  | `composed` | Written for this application |
  | `field_map:resume` / `:email` | Your resume file / Your application email |
  | `assumption`, `fallback:F*` (assumed) | Assumed: {reason}, or "Assumed: nothing in your details or resume covered it" |
  | strict `llm` | Written by the local AI from your details |
  | `mygreenhouse`, `workday_last_application`, `site_default`, `resume_import`, `keep` | Kept from the site |
  | status `unknown` / `ungrounded` | Not answered |
- **(c) A missing owner-only fact that has a field** (date of birth, a grade, expected or current salary, address, postal code, phone, a consent, a file). The attempt ends `owner_fact_missing` / `consent_refused` / `document_missing` as LFF §9 says.
  - The row's chip reads **"Needs one detail: {field label}"** with **Add it**, which opens Your details at that field (int's `answerTarget` / `openAnswer`; the path comes from `attempt_question_paths`).
  - The captured `questions` row stays a store record only: it carries the path and is never shown.
  - `document_missing` captures no row, so its chip reads "Needs one file: {detail}" and opens the Files section. It is ready to retry when `documents_status` reports a file of that kind.
  - The field shows **"Needed by {n} applications"**, and the badge counts it (B.4).
- **(d) A missing fact with no field.** Per kind, consistent with D-209 (1) and D-213. **A blocking fact with no field (passport number, bank details, full NRIC, another ID) waits for the threshold like any other topic, as the owner's rule says (D4).** Until then, each application that needs it stops and says why on its own row; nothing appears on the Profile page.

  | Kind | What happens | Counted (Release 2) | Seen where |
  |---|---|---|---|
  | Passport number, bank details, other ID (driver licence, employee ID) | stop `owner_fact_missing` before typing; never invented (D-209 (1)) | yes, as T1; proposed at 16 employers (sensitive) | the row: "Stopped: this form asks for your {fact}, which your details can't hold. Nothing was sent."; the Overview "To do" fact line; the AQ same-fact ×3 pause |
  | Full NRIC / national ID | the same stop; it can never be stored, so such forms always stop | yes, but never proposed (M3) | as above |
  | Ordinary question with no basis (a preference, an experience count, a "please specify") | answered with the LFF §4.6 designed assumption, marked assumed (D-208) | yes, when required | What was sent |
  | Grade or salary figure not in the details or resume | these have fields → (c) | no | (c) |
  | A protected class with no truthful option (incl. the 3 `no_option_fits` and 2 `attestation_unclear` kinds, A.3) | LFF §17.2 protective end, else `validation_error` | no | row reason |
- **(e) Retry.** "Try again" on the Applications row already enqueues through `POST /api/apply` (no card check, routers/apply.py:280-301). New, server-side: `last_attempt.ready_to_retry`. It is always false for a job with any `submitted` or `submitted_unconfirmed` attempt. Otherwise:
  - (c) roles: ready when the profile now holds a value at **every** path the attempt waited on;
  - `strict` stops: ready when `retry_candidates` gives open = 0 and dismissed = 0.

  A ready row shows **"Ready to try again"** with Try again as its primary button.

  **After "Save section" with waiting roles (M6),** an inline notice appears **inside the saved section** and stays until dismissed (not a toast): "Saved. {n} applications were waiting for this." with the button **"Apply again to {n} applications"**. {n} = the roles whose every waited path is now filled. The button calls `POST /api/apply` with those job ids, and it is the only new caller of that route; a section save itself never calls it. The AQ same-fact pause and its Resume are unchanged.

### B.3 The existing 24 open, 3 answered, 1 dismissed
**Release 1:** nothing is deleted. The rows stop being shown because no screen reads them: `GET /api/questions` is retired (B.5), and the Profile, Overview and badge no longer call it.

What the owner sees at first launch:
- **Applications:** the one stopped attempt reads "Stopped: 24 questions had no answer", with "See what was filled" and Try again. Under `always` the filler answers those fields.
- **Settings:** the 3 answered answers under "Answers you corrected". They stay in `extra` (or at their profile path) and keep working unchanged (P3, the briefing, tier 3).
- **Nowhere:** the dismissed one.
- The go-live note to the owner mentions the hidden cards once.

**Release 2:** the v10 migration backfills once, in one transaction:
- `questions.topic = key` for rows with no `target_path`, not `compose_needed`, an `EXTRA_KEY_PATTERN` key, and a required sighting;
- one `topics` row per key: `counting` if any row is open or assumed, `remembered` if answered, `dismissed` if dismissed.

So each of the 24 counts as **1 employer of 16**. Sightings written between the go-live and Release 2 are backfilled the same way. The first attempt end after the upgrade runs one capped naming pass over the provisional topics (L3 rules).

### B.4 The Profile page
**Information architecture.** The segmented control keeps its two views and hashes (`#/profile/resume`, `#/profile/details`).
- **"Resume and titles"** is Q-118 §6 unchanged.
- **"Your details"** (renamed from "Application details") holds, top to bottom:
  1. **A status line**: one `ui-card`, one row.
  2. **One card of section rows** in the SettingRow look (Q116 §3): the title over a one-line summary of the values, completeness on the right, a chevron. Every section is collapsed by default; a row opens in place, one at a time.
  3. A muted pointer to "Answers you corrected".

  There is no question list, no "Answered for you", no `extra` list, and no company or wording anywhere. The server owns the sections: `applicant.SECTIONS`, sent as `form_json.sections` (additive).

**Inside an open section (D5).** The group's existing item markup renders unchanged: today's `v-for item` block of `ApplicationDetails.vue`, including the `entries` kind (`FieldInput` with its add / remove / "from your resume" behaviour), wrapped by `DetailSection.vue`. Nothing about entries is redesigned in this release.

**Save section** PUTs the whole profile with the current etag, taking only that section's paths from the draft. The existing draft / etag / `mergeEdits` logic carries over; a remember write from an application bumps the etag, which the existing 409 notice handles. Leaving a dirty section asks first.

| # | Section | Paths | Summary line |
|---|---|---|---|
| 1 | Identity | identity.* | Sam Sample · born 14 Mar 2002 · Male |
| 2 | Contact | contact.* | sam@example.com · +65 9000 0000 · Singapore |
| 3 | Work rights | singapore_status: nationality, residency, work pass, right to work, sponsorship, National Service, ORD date, NRIC last 4 | Singapore Citizen · no pass needed · NS completed |
| 4 | Availability and pay | availability.*, pay.* | 30 days' notice · from 1 Jul 2026 · expects SGD 5,000 a month |
| 5 | Education | education | 2 entries · BSc Computer Science |
| 6 | Experience | experience | 3 entries · Software Intern |
| 7 | Skills, languages and links | skills, attested_skills, languages, links.*, sourcing.how_heard_default | 52 skills · English, Mandarin · LinkedIn, GitHub |
| 8 | Equal-opportunity questions | singapore_status race, race_other, religion, marital_status; us_self_id.* | Chinese · prefer not to say · US forms: Male |
| 9 | Consents and declarations | consents.*, declarations.* | Consents given · every declaration No |
| 10 | Files | documents.* | Resume in use · no transcript |
| 11 | More about you (Release 2; shown only when an added or proposed topic exists) | promoted `extra` entries | Driving licence · 1 suggested |

**Completeness** (right side of a section row; words carry the meaning, not colour alone):
- **Needed** (warn): a REQUIRED_PATHS item is empty, or a waiting application needs a path in this section.
- **{n} to fill** (muted): RECOMMENDED items are empty.
- **Complete** (ok) otherwise.

Inside an open section a field may carry "Needed", "Needed by {n} applications" or "From your resume, please check". An error in another section shows on that section's row as "Fix 1" (`remapErrors`).

**`extra` errors (M4).** An error whose path starts `extra.` is never drawn on the Profile page. It becomes one line in the status line instead: "A saved answer needs attention. Open Settings → Apply → Answers you corrected." Server rule: `PUT /api/applicant` reports `extra.<k>` errors only for entries the request changed. An unchanged invalid entry was already on disk, and tier 3 skips it (QD §11), so the section save still succeeds. "Other keys in your file" never lists `extra.*` (`applicantForm.js:179`).

**Badge.** Profile badge = `len(details_needed)`, where `details_needed` comes from `GET /api/apply/status` (the shell already calls it):
- `applicant.missing_for_apply(profile)` (REQUIRED_PATHS plus `documents.resume`);
- ∪ the `owner_fact_path` of every waiting application whose path is still empty;
- de-duplicated, in that order.

Proposals, remembered answers and assumptions never badge. `badgeLabel` "details needed".

```
1440 (content column 52rem)                                     390
Profile                         [Resume and titles│Your details 2]  Profile
What auto-apply puts on application forms. Change anything…     [Resume and titles│Your details 2]
┌───────────────────────────────────────────────────────────┐   ┌──────────────────────────────┐
│ [2 details needed] Auto-apply waits until these are       │   │[2 details needed]            │
│ filled: Expected salary, Notice period.        [Fill in]  │   │Auto-apply waits until these… │
└───────────────────────────────────────────────────────────┘   │[Fill in]                     │
┌───────────────────────────────────────────────────────────┐   └──────────────────────────────┘
│ Identity                                      Complete  › │   ┌──────────────────────────────┐
│ Sam Sample · born 14 Mar 2002 · Male                      │   │Identity                    › │
├───────────────────────────────────────────────────────────┤   │Complete                      │
│ Availability and pay                          [Needed]  ⌄ │   │Sam Sample · born 14 Mar 2…   │
│  Notice period, in days   [    ]  Needed                  │   ├──────────────────────────────┤
│  Expected salary          [SGD][     ][per month] Needed  │   │Availability and pay        ⌄ │
│  Earliest start date      [2026-07-01]                    │   │[Needed]                      │
│  ┌ Saved. 2 applications were waiting for this. ──────┐   │   │Notice period, in days        │
│  │ [Apply again to 2 applications]          [Dismiss] │   │   │[    ]  Needed                │
│  └────────────────────────────────────────────────────┘   │   │…                             │
│                               [Cancel] [Save section]     │   │[Cancel][Save section] sticky │
├───────────────────────────────────────────────────────────┤   ├──────────────────────────────┤
│ Education                                     Complete  › │   │Education                   › │
│ 2 entries · BSc Computer Science                          │   │2 entries · BSc Computer…     │
└───────────────────────────────────────────────────────────┘   └──────────────────────────────┘
Answers you corrected for next time are in Settings → Apply.
```
- **At 390:** one column. Each section row puts its title over its status badge over a one-line summary. An open section lists one field per line. Save / Cancel stick to the bottom of the open section, above the bottom bar, and never cover the focused field (WCAG 2.2 2.4.11: the editor scrolls the focused field above the sticky bar).
- **Accessibility (L6):**
  - Each section row is a heading holding a `<button aria-expanded aria-controls>`; one is open at a time.
  - A failed save moves focus to the first error.
  - The badge text is not colour only.
  - `aria-busy` sits on the skeleton container, not on each row.
- **States:**
  - Loading: 10 `ui-skeleton` rows.
  - No file: the empty copy, and every summary reads "Nothing filled yet".
  - Load error: a notice with Try again.
  - Unreadable file: today's `fileError` notice.
  - Saving: the section is `aria-busy`, its controls are disabled, and the button reads "Saving…".
  - Saved: the toast "Saved.", or the M6 inline notice when roles were waiting.
  - Failed: errors under their fields; the section stays open.
  - 409: today's conflict notice.
  - Leaving a dirty section: an in-row confirm.
- **Opening at a field:** the field-focus wish (`FIELD_FOCUS_KEY` / `jobscraper:show-field`, `attempts.js` on int, unchanged) opens the section that holds the path and focuses the field.

**Copy (final, sentence case; design:ux-copy):**
| Element | Copy |
|---|---|
| View label / page sub | "Your details" (with the count: "Your details 2") / "What auto-apply puts on application forms. Change anything that stops being true." |
| Status, ready | badge "Ready for auto-apply" · "Your required details are filled in." (L4) |
| Status, missing | badge "{n} details needed" ("1 detail needed") · "Auto-apply waits until these are filled: {labels}." · button "Fill in" |
| Status, waiting (appended) | "{n} applications are waiting for a detail below." ("1 application is …") |
| Status, `extra` error (M4) | "A saved answer needs attention. Open Settings → Apply → Answers you corrected." |
| No file | "Nothing saved yet. Your details stay on this computer." |
| Load error | "Couldn't load your details. {reason}" · "Try again" |
| Section row | "Complete" · "{n} to fill" · "Needed" · empty summary "Nothing filled yet"; entries "{n} entries · {first entry's title}" |
| Field badges | "Needed" · "Needed by {n} applications" · "From your resume, please check" |
| Section actions | "Save section" / "Saving…" / "Cancel"; toast "Saved." |
| Waiting notice (M6, inline, persistent) | "Saved. {n} applications were waiting for this." · "Apply again to {n} applications" · "Dismiss" ("1 application was …", "Apply again to 1 application") |
| Unsaved confirm | "Save your changes to {section}?" · "Save" / "Discard changes" |
| More about you note (Release 2) | "Details that many employers asked for. One is suggested only after more than {min_count − 1} different employers have asked." |
| Proposed field (Release 2) | title = topic title · badge "Suggested" · "Asked by {n} different employers, and your details don't cover it yet. Add it once and JobScraper uses it on every form that asks." (L1) · sensitive ones add "Stored on this computer only. The local AI reads it to fill forms." (M3, D-201) · "Add to details" / "Not needed"; toast "Removed. It won't be suggested again." + "Undo" |
| Pointer | "Answers you corrected for next time are in Settings → Apply." |
| What was sent: title | "What was sent" (submitted) / "What was filled" (dry run or stopped) |
| What was sent: sub | "Sent {when}. {n} answers were assumed." / "Nothing was sent. These are the answers filled before it stopped." |
| What was sent: filter / badges | "All {n}" · "Assumed {n}" · "Not answered {n}"; badges "Assumed" · "Not answered" · "Saved for next time" |
| What was sent: correction | "Use a different answer next time" / "Answer for next time"; checkbox "Only for applications to {employer}" (checked); "Save for next time"; helper (sent) "This form was already sent. Your answer is used from the next application on."; done (stopped) "Saved. Try this application again when you're ready." |
| What was sent: refusals | follows details (H3): "This answer follows your details. Change it in Your details." + link; shared (H2): "This question shares a saved answer with other questions. Change it in Settings → Apply → Answers you corrected."; too general: "This question is too general to save on its own (“{label}”). Change it in your details instead."; empty: "No answers were recorded for this attempt."; error "Couldn't load the answers. {reason}" · "Try again" |
| Row chips | "Needs one detail: {label}" + "Add it" · "Needs one file: {detail}" + "Add it" · "Ready to try again" + "Try again" · strict: "Stopped: {n} questions had no answer" + "See what was filled" · no-field fact: "Stopped: this form asks for your {fact}, which your details can't hold. Nothing was sent." |
| Settings row | "Answers you corrected" · "Answers you saved from an application. JobScraper uses them on every form with the same question." · value "{n} saved" / "None yet"; list item "{title}" over "{answer} · {Every application / Only {employer}}" + "Forget"; first 20, then "Show all {n}"; confirm "Forget this answer? JobScraper will answer this question from your details again." · "Forget" / "Keep"; empty "None yet. To save one, open an application and choose What was sent." |
| Settings, fill policy (D2) | "Always answer" as LFF §7.2; the other option is renamed "Stop when unsure": "It stops when your details don't cover a question. You answer them in that application's What was filled, then try again." |
| Overview "To do" | "{n} applications are waiting for a detail" + "Add details"; "{n} applications stopped: their forms ask for your {fact}" + "See applications" ({fact} from the four fixed `NO_FIELD_FACTS` titles only, review Q5); "{n} applications stopped on a question JobScraper can't answer" + "See applications"; Release 2: "A detail many employers ask for: {title}" + "Add it" |

### B.5 Data and API
**Store** (additive, guarded by `PRAGMA table_info` and `_add_column` like the existing steps, `store.py:490-540`).

**Release 1 = schema v9 on `int/Q-121`:** one column, filled by `audit_row` from the decided class (`class_string(klass, which)`, else the code key's; NULL under strict), so H3 can read it:
```sql
ALTER TABLE apply_answers ADD COLUMN field_class TEXT;
```

**Release 2 = schema v10:**
```sql
CREATE TABLE IF NOT EXISTS topics (
    key TEXT PRIMARY KEY,                    -- ^[a-z][a-z0-9_]{1,39}$, never a profile path
    title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,                      -- text | yes_no | number | date (the proposed field's)
    profile_path TEXT NOT NULL DEFAULT '',   -- set: the fact has a field; never proposed, feeds needed_by (M2)
    about_you INTEGER NOT NULL DEFAULT 1,    -- 0: depends on the employer or the job; never proposed
    sensitive INTEGER NOT NULL DEFAULT 0,
    named_by TEXT NOT NULL DEFAULT 'rule',   -- rule | model | class
    status TEXT NOT NULL DEFAULT 'counting', -- counting | proposed | added | remembered | dismissed | merged
    created_at TEXT NOT NULL, proposed_at TEXT, decided_at TEXT);
ALTER TABLE questions ADD COLUMN topic TEXT NOT NULL DEFAULT '';   -- '' = never counted (R3)
CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);
-- the counter (R5). :by_employer = (count_by == 'employer'), :min = min_count (16)
SELECT t.key, t.title, t.kind, t.named_by,
       COUNT(DISTINCT CASE WHEN :by_employer
             THEN COALESCE(NULLIF(s.employer_norm, ''), 'c:' || s.company_id, 'job:' || s.job_id)
             ELSE s.job_id END) AS n,
       COUNT(DISTINCT s.job_id) AS applications
  FROM topics t JOIN questions q ON q.topic = t.key
  JOIN question_sightings s ON s.question_id = q.id AND s.required = 1
 WHERE t.status = 'counting' AND t.about_you = 1 AND t.profile_path = ''
 GROUP BY t.key
HAVING n >= :min;
```
`propose_topics` also needs `named_by IN ('model','class')` and `key != 'owner_fact_national_id'`. Rows over the threshold that fail that filter are returned to the flow so it can name them once (R6).

**Store methods** (names fixed, SQL the engineer's):
- Release 1: `answer_row(answer_id)`, `attempt_field_question(attempt_id, field_key)`, `mark_answer_corrected(answer_id, value_json, now)`, `waiting_on_details()` → `[{job_id, attempt_id, paths}]`.
- Release 2: `set_question_topic`, `upsert_topic`, `merge_topic(src, dst)`, `topic_candidates(limit=50)`, `topic_counts(cfg)`, `propose_topics(cfg, now)`, `proposed_topics()`, `topic_needed_by()` → `{path: n}`, `set_topic_status`, `topic_report()` (for the CLI).

**Config (Release 2):** `apply.topics: {count_by: employer, min_count: 16, naming: true, naming_max_per_attempt: 5, naming_timeout_s: 15}`, a frozen `TopicsConfig`.

**Contract (WP-0, additive):**
- Release 1:
  - `Answer.field_class: str = ""`.
  - `REASON_TEXTS` hints:
    - `UNANSWERABLE_REQUIRED` → "Open What was filled for this application to answer it for next time, then click Try again."
    - `OWNER_FACT_MISSING` → "Add it in Profile → Your details, then click Try again." The text stays unchanged, because attempts.js parses it.
    - `DOCUMENT_MISSING` → "Add it in Profile → Your details → Files, then try again."
  - New `OWNER_FACT_NO_FIELD_HINT` "Your details have no place for it yet. Apply by hand, or skip this role."
  - `NO_FIELD_FACTS` (which → title), needed for the row text and the Overview line.
- Release 2: `TopicStatus`, `TOPIC_MIN_COUNT = 16`, `TOPIC_KINDS`.

**Routes** (Release 1 unless marked):
| Route | Change |
|---|---|
| `GET /api/applications/{job_id}/attempts/{attempt_id}/answers` (new) | `{attempt: {id, kind, state, finished_at, trial, entries_note}, employer, fields: [{id, step, label, type, required, value_text, basis_text, assumed, reason_text, status: sent\|not_answered\|not_sent, remembered_text, can_remember, refusal, options}]}`; 404 when the attempt is not this job's; no path, URL, log or password |
| `POST …/answers/{answer_id}/remember` (new) | `{value \| picks, only_employer: bool = true, etag}` → `{key, remembered_text, ready_to_retry, etag}`; 409 `shared_answer` or a stale etag; 422 `follows_your_details`, `too_general`, invalid. Runs under `PROFILE_WRITE_LOCK`. The `extra` writer moves from routers/questions.py `_apply_answer` into `web/remember.py` |
| `GET /api/applications` | additive `last_attempt.ready_to_retry`, `last_attempt.no_field` |
| `GET /api/apply/status` | additive `details_needed: [path]` |
| `GET /api/apply/remembered`, `DELETE /api/apply/remembered/{key}?etag=` (new) | non-promoted `extra` entries `[{key, title, value_text, scope_text}]`; DELETE removes one entry at the owner's click |
| `GET /api/applicant` / `PUT` | additive `sections`; `needed_by: {path: n}` (Release 1 from waiting roles, Release 2 plus mapped topics); `proposals: [{key, title, description, kind, sensitive, employers}]` (Release 2). PUT: the M4 `extra` rule |
| `POST /api/applicant/topics/{key}` / `…/{key}/dismiss` (Release 2) | add (`{value, etag}` → `extra`, `labels: []`, `promoted: true`) / Not needed |
| `GET /api/questions` (M5) | returns the full old-bundle shape for every `status`: `{mode, groups: [], counts: {open: 0, assumed: 0, answered: 0, dismissed: 0}, ready: [], waiting: [], busy, model_sees_private, retired: true}` |
| `POST /api/questions/answer`, `/{key}/dismiss`, `/retry`, `/{id}/keep`, `/{id}/change` (M5) | 410 `retired` now; the routes are removed in the release after |

The new SPA stops calling `getQuestions`, `answerQuestion`, `dismissQuestion`, `keepAssumed`, `changeAssumed` and `retryQuestions`, and `openAssumed` goes. `applicant.validate` accepts `extra.<k>.promoted` (bool), and `labels: []` only with `promoted: true` (today `applicant.py:1221-1223` requires a non-empty list). `promoted` joins `EXTRA_META_FIELDS` (`applicant.py:1154`), so an error about it stays log-safe like the other metadata.

**Contract v9 as built (WP-0; names beyond the list above, and the two ambiguities fixed):**
| Name in `apply/contracts.py` | What | Lane |
|---|---|---|
| `Answer.field_class: str = ""` | a `FIELD_CLASS_CHOICES` string or "" | F1 writes, S1 stores, W1 reads |
| hints of `UNANSWERABLE_REQUIRED`, `DOCUMENT_MISSING`, `OWNER_FACT_MISSING` | as listed above; every `text` unchanged | all renderers |
| `NO_FIELD_FACTS`, `NO_FIELD_FACT_TITLES`, `OWNER_FACT_NO_FIELD_HINT`, `OWNER_FACT_NO_FIELD_TEXT` | passport / bank / national_id / other_id → "passport number", "bank account details", "full NRIC or national ID number", "driving licence or other ID number". F1 writes `reason_detail` = the title for such a stop; W1 sets `no_field` when the detail is in `NO_FIELD_FACT_TITLES` and renders `OWNER_FACT_NO_FIELD_TEXT` | F1, W1, U2, U3 |
| `BASIS_TEXTS`, `FIELD_MAP_BASIS`, `BASIS_FROM_DETAILS(_BARE)`, `BASIS_ASSUMED(_NO_REASON)`, `BASIS_NOT_ANSWERED`, `basis_text(source, *, status, assumed, reason, form_label)` | the B.2b basis table as one pure function | W1 |
| `RememberRefusal` (`follows_your_details`, `shared_answer`, `too_general`), `REMEMBER_REFUSAL_TEXTS` | route codes and the B.4 refusal copy | W1, U2 |
| `REMEMBER_REFUSED_SOURCES`, `REMEMBER_REFUSED_CLASSES`, `field_class_of()`, `follows_your_details(source, field_class)` | the H3 rule; `web/remember.py` `remember_refusal(row)` calls it, then the H2 / too-general checks | W1 |
| `RememberScope` (`employer`, `every`), `REMEMBER_SCOPE_TEXTS`, `EXTRA_EMPLOYER_FIELD = "employer"`, `extra_entry_applies(entry, employer_name, employer_aliases)` | the scope of a remembered answer | W1 (writer, list, `EXTRA_META_FIELDS`), F1 (tier 3 + briefing) |
| `SentFieldStatus`, `ANSWERS_ATTEMPT_KEYS`, `ANSWERS_FIELD_KEYS` | the What was sent route's statuses and keys (the table above) | W1, U0, U2 |
| `QUESTIONS_RETIRED = "retired"`, `QUESTIONS_RETIRED_TEXT` | M5: the 410 code and text | W1 |
| `FILL_POLICY_LABELS` | "Always answer" / "Stop when unsure" (D2) | U3 |

- **Ambiguity 1 (layering).** B.2b's fallback "a row with no class … `declarations.classify_field` names a declaration" cannot run in `web/`: `tests/test_layering.py` `WEB_MAY_IMPORT` allows only the foundation and the contracts modules (B.9's "imports `apply.declarations`" was wrong). **Fixed:** the class is written at fill time instead. F1's `audit_row` sets `field_class` under `strict` to `declaration:<label>` when the code's declaration reader names one (else ""), so "NULL under strict" above becomes "" or that string. Rows written before v9 use the source rule alone: strict writes declarations, work rights and consents with a `declaration:` / `standing:` / `profile:` source, all refused.
- **Ambiguity 2 (scope storage).** B.2b gave the checkbox but no place for the scope. **Fixed:** an `extra` entry gains `employer` (the employer's display name; absent = every employer). One entry per exact label (H2): a new correction replaces the entry's value and scope. `extra_entry_applies` is the one rule; F1 must apply it in the tier-3 memory lookup (`apply/resolve.py`) and the briefing (`apply/briefing.py`) against `ResolveContext.employer_name` / `employer_aliases`, so a scoped answer never reaches another employer's form. Those two files join F1's lane (disjoint from W1).

### B.6 Removed or turned off (Release 1)
- **Vue:**
  - `QuestionsInbox.vue` and `QuestionCard.vue` are deleted, with int's "Answered for you" and their vitest pins (the tester lane classifies them first).
  - The `extra` group leaves the form (its list moves to Settings); "Other keys" becomes a muted disclosure at the bottom.
  - The App.vue / tabs.js badge stops counting questions, and the Overview questions row goes.
  - "Answer in Profile" becomes "Add it" (to the field) or "See what was filled"; "Review answers" becomes "See what was sent".
  - The ApplySettings fill-policy copy points to What was sent.
- **Flow:**
  - `capture_assumptions` and `capture_owner_fact` keep writing `questions` rows as **store records only**: the counter's input in Release 2, and `owner_fact_path`.
  - No naming runs inside the fill loop (already true on int, `apply_flow.py:771`).
  - The `assumed` status is never surfaced.
- **`strict` stays the code default through the squash and stays selectable as the rollback, shown as "Stop when unsure" (D2). It shows no cards either (R1):**
  - its capture writes `questions` byte for byte;
  - a stopped role recovers from its own "What was filled": "Answer for next time" on each unanswered field, then "Ready to try again", then Try again. For the 24-field stop that is 24 answers on the application page: the same work as the cards, in a place that does not grow the Profile (review Q8).
  - Rollback = revert the one `fill_policy` line (or switch in Settings); no data change.

### B.7 Risks and how each is watched
| Risk | Watch / answer |
|---|---|
| A blocking no-field fact (e.g. a passport number) stops applications before anything is proposed (D4: it waits for the threshold like any other topic) | It is never invisible. Each such row says why ("Stopped: this form asks for your passport number, which your details can't hold. Nothing was sent."). The Overview "To do" names the fact from the four fixed titles. The AQ same-fact ×3 pause names it in Runs. The Coordinator reads `jobscraper apply topics` (counts per topic, no values). Nothing appears on the Profile page until 16 employers have asked; a full NRIC is never proposed and such forms always stop |
| Wrong merge or split of topics | A wrong merge gives an odd proposal (Not needed) and never a wrong answer (H1: promoted entries have no labels). A split means it is never proposed; the model answers it anyway |
| Wrong assumed answers sent (D-203, D-216) | Marked in What was sent; the row chip "Submitted · {n} answers assumed" stays; the owner corrects it for next time. A form already sent cannot be recalled |
| A correction reaches the wrong question or overrides a declaration | H2: only the exact label, never another entry. H3: refused on standing, profile, declaration, consent (incl. certification and acknowledgement), work-rights, self-ID and owner-fact rows. Default scope is this employer |
| A company name or wording on the Profile page | No question list. `extra.*` errors are re-worded (M4). Proposals only from model- or class-named titles, checked for employer names, `?` and length (M1). Pins (6), (14), (18) render employer-named fixtures |
| "Apply again" sends real applications (D-203) | A persistent inline button only; a save never submits; never offered for a job with a submitted attempt (M6, pin 19) |
| Old bundle against the new backend | `GET /api/questions` keeps its full shape with nothing in it; the writers answer 410 |
| The live database | Additive DDL; the backfill in one transaction, idempotent; the B.8 copy check and a dated backup before the squash |

### B.8 Build plan (Coordinator D1: everything on `int/Q-121`, one visible go-live)
**Release 1 (built on `int/Q-121`, after the A1 lanes now in flight have merged there):**
| WP (lane) | Files (disjoint) | Verify (fakes only; never a real job id) | Pins |
|---|---|---|---|
| 0 architect | `apply/contracts.py` (Release 1 items). **Done (contract v9):** `Answer.field_class`, 3 hints, `FILL_POLICY_LABELS`, `NO_FIELD_FACTS` / `NO_FIELD_FACT_TITLES`, `OWNER_FACT_NO_FIELD_HINT` / `_TEXT`, `BASIS_*` + `basis_text()`, `RememberRefusal` + texts, `REMEMBER_REFUSED_SOURCES` / `_CLASSES`, `field_class_of()`, `follows_your_details()`, `RememberScope` + texts, `EXTRA_EMPLOYER_FIELD`, `extra_entry_applies()`, `SentFieldStatus`, `ANSWERS_ATTEMPT_KEYS` / `_FIELD_KEYS`, `QUESTIONS_RETIRED(_TEXT)` (table at the end of B.5) | `-k apply_contracts` | |
| S1 store | `store.py` (v9 `field_class`, 4 methods) | `-k store` | (20-a) v8→v9 |
| F1 flow | `apply_flow.py` (`audit_row` writes `field_class`), `apply/always.py` (only where a decision becomes an `Answer`: copy the class) | `-k apply_flow`, `-k apply_e2e`, `-k always` separately | (13) via audit |
| W1 web backend | `web/remember.py` (new: the writer, `remember_refusal`, the key rule), `web/routers/applications.py`, `web/routers/apply.py`, `web/routers/questions.py` (M5), `web/routers/applicant.py` (sections, the M4 rule), `applicant.py` (`SECTIONS`, `promoted`, `labels: []` rule) | `-k web_applications`, `-k web_apply`, `-k web_questions`, `-k web_applicant`, `-k applicant`, `-k layering` | (1)-(5), (13), (15), (21) |
| U0 | `web/src/api.js` | `npx vitest run` | |
| U1 Profile | `tabs/Profile.vue`, `components/ApplicationDetails.vue` (rebuilt), new `components/DetailSection.vue`, new `detailSections.js`, `applicantForm.js` (L5); deletes `QuestionsInbox.vue`, `QuestionCard.vue` | vitest | (6), (7), (14), (18), (19) |
| U2 Applications | `components/ApplicationRow.vue`, new `components/WhatWasSent.vue`, `attempts.js` (owner of the file; `answerTarget` / `openAnswer` / `FIELD_FOCUS_KEY` unchanged and read by U1) | vitest | (1-UI), (13-UI) |
| U3 Settings, Overview, shell | `components/ApplySettings.vue`, new `components/RememberedAnswers.vue`, `tabs/Overview.vue`, `overview.js`, `App.vue`, `tabs.js` (shell: tell the Q-100 owner) | vitest | (5-UI) |
| T0 tester, stale pins (a lane, not a line) | the `-k web_questions` / questions-store / vitest question and "Answered for you" suites | each red pin classified stale or defect, as the Q-121 lessons require; no bulk edit | |

- **Order:** 0 → S1 → F1 and W1 in parallel (disjoint) → U0 (the shapes are fixed here, so U0 may start with W1) → U1, U2, U3 in parallel. T0 runs beside each lane, then the pins. Everything merges into `int/Q-121`.
- **Go-live gate (Coordinator; the review's five conditions):**
  1. **Data safety on a copy.** Migrate a copy of the live DB from its schema (**v6**) to the final one (v9) with the new `store.py`, and check:
     - the row count per table is equal before and after;
     - `PRAGMA integrity_check` = ok;
     - `schema_version` = 9;
     - a second open changes nothing;
     - a dated backup of the live DB is kept beside it (the D-163 pattern).

     No agent reads `data/`.
  2. `strict` stays the code default through the squash. The `fill_policy: always` line is its own last commit, after a launch check on a dev copy. That check is not a trial (D-216).
  3. The `strict` rollback has been exercised once on the dev copy: set `strict`, open a stopped attempt's What was filled, Answer for next time, then Try again with a fixture job, never a real id.
  4. **Squash hygiene:** the scrubbed `git merge --squash` of `int/Q-121`, plus a deny-list scan of the whole squashed diff **and** the commit message. Then the full suite, `-k apply_e2e` and `-k apply_flow` run separately, vitest, and the bundle built only in the main checkout.
  5. B.2a's switch-on list is met; Release 2 is not on it.
- **Browser checks** at 1440 and 390 on dev port 8768, under `always` (on a copy with `apply.mode: dry_run` in the copy's settings table) and under `strict`.
  - Setup: `JOBSCRAPER_DB=<DB copy>`, `JOBSCRAPER_APPLY_QUEUE=0`, `JOBSCRAPER_MAIL_SYNC=0`, and **`JOBSCRAPER_CONFIG=<scratch>/config.dev.yaml`**, a copy of `config/config.yaml` whose `paths.applicant` (and `paths.resume_dir` if needed) is the absolute path of a copied applicant file.
  - The app has no environment variable for the applicant file. It is `paths.applicant` in the config file that `JOBSCRAPER_CONFIG` names (`config.py:638-641, 697-711`), and a relative path resolves against the checkout the code runs from (`config.py:25, 28-30, 486-487`).
  - Confirm before any click with the same environment: `python -c "from jobscraper.config import load_config; print(load_config().applicant_path)"`.
  - Check: the status line; open / save / cancel a section; Needed badges; the waiting notice; no "Questions from applications" and none of the copy's company names on the Profile page; What was filled on the copy's stopped attempt; Answer for next time and its refusals; Answers you corrected with Forget.

**Release 2 (invisible follow-up, on `int/Q-121` after the go-live, or on `personal` if `int/Q-121` is retired by then):**
| WP | Files | Verify | Pins |
|---|---|---|---|
| 0b architect | `apply/contracts.py` | `-k apply_contracts` | |
| S2 | `store.py` (v10, topic methods, backfill) | `-k store`, `-k questions_store` | (11), (20-b) v6→v10 |
| T | `apply/topics.py` (new, pure), `apply/questions.py` (`ask_topic`, `parse_topic_naming`, topic on capture) | `-k topics`, `-k questions` | (8), (17) |
| F2 | `apply_flow.py` (post-attempt naming with the L3 rules, `propose_topics`), `config.py`, `cli.py` (`apply topics`) | `-k apply_flow`, `-k apply_e2e`, `-k always` separately | (9), (10) |
| W2 | `web/routers/applicant.py` (proposals, add / dismiss) | `-k web_applicant` | (12), (16) |
| U4 | new `components/ProposedField.vue`, `DetailSection.vue` (More about you) | vitest | (6) extended |

Order: 0b → S2 → T → F2 and W2 in parallel → U4. The data check is condition 1 again, from the live schema to v10.

**Pins (tester, fakes):**
1. The answers route: every source gives its basis words; assumed and not-answered rows; `entries_note` and `trial` shown; 404 on a foreign attempt; no URL or log leak.
2. Remember for yes_no, choice (picks ⊆ seen from `options_json`), text, number and date, with `only_employer` true and false: the `extra` entry, `corrected_json`, the question rows answered, then `ready_to_retry`. 409 on a stale etag; 422 on a generic label.
3. A strict resolve of that label returns the remembered answer.
4. `GET /api/questions` keeps the full old shape with empty lists for every status; every writer answers 410.
5. `details_needed` = missing ∪ waiting.
6. The Profile DOM, rendered with employer-named fixtures, holds no employer name, no question label and no QuestionsInbox.
7. Section summaries and completeness (pure), including "{n} entries · {first title}".
8. `topic_of` exclusions and T1.
9. The counter, with `count_by` employer and job:
   - 16 employers → proposed; 30 sightings at 15 employers → not proposed;
   - the same job twice counts once; an optional sighting is not counted;
   - dismissed, added, remembered, path-mapped and rule-named topics are never proposed.
10. Naming:
    - 0 naming calls before the attempt is final, ≤ 5 after;
    - none while the queue is stopping; the pass stops at the first transport failure;
    - `same_as` merges and `profile_path` maps;
    - an unusable reply keeps the slug; a failure never changes the outcome.
11. The v10 backfill on a fixture with 24 open, 3 answered and 1 dismissed: no row lost in any table, the statuses as in B.3, a second open changes nothing.
12. Add to details → `extra` with `promoted` and `labels == []`, and the next briefing carries it.
13. Remember on each protected source and class is refused and writes nothing; the button is absent.
14. The strict twin of (6): open, answered and assumed rows from an employer-named fixture never reach the Profile DOM.
15. A model-named captured row whose key holds another entry: the other entry is byte-identical afterwards; a shared label → 409.
16. A resolve of a promoted topic's wording never returns `memory:`.
17. `owner_fact_national_id` is never proposed.
18. An invalid `extra` entry named after a fixture wording: neither its key nor its message appears in the Profile DOM, and the section save succeeds.
19. Saving a section issues no `POST /api/apply`; `ready_to_retry` is false for a job with a submitted attempt.
20. Migrations from a **v6** fixture: (a) to v9, (b) to v10.
21. Other keys never lists `extra.*`.

**What goes live when:**
- **One visible go-live:** at the next launch after the squash and the config line, the owner gets:
  - Your details rebuilt, with no cards and a badge of details only;
  - What was sent with corrections, Answers you corrected, and the waiting notice;
  - the model filling every field. The first Auto-apply click sends for real (D-216).
- **One invisible follow-up:** Release 2 starts counting, backfilled from the history. Nothing shows until a topic reaches 16 employers.

### B.9 Requirement map
| Requirement | Section |
|---|---|
| D-215 "never show specific questions asked by specific companies" | R1, B.4 (no list, no company, M4), B.6, pins (6), (14), (18) |
| D-215 "more than 15 times in different applications" + "a new section under user details" | R2-R6 (`count_by`, `min_count`), B.4 More about you |
| D-215 "answered from my resume and details" / "filled up completely by the LLM" | B.2a (switch-on), B.3, A.4 |
| D-215 "long and messy" | B.4 |
| D-208 / D-209 / D-213; D4 | B.2d (never invent; designed assumptions; a no-field fact waits) |
| D-87 and the standing truths | B.2b H3 refusals |
| D-203 / D-205 / D-216 | B.2a, B.2e (no confirmation; Apply again is the owner's click only) |
| PRD F-39 / principle 5 ("What I told this employer") | B.2b What was sent |
| NF-04 layering | `apply/topics.py` pure; SQL only in `store.py`; the model only through the backend object (as QD §5.3); `web/remember.py` imports `apply.declarations` like the other routers import `apply` |

### B.10 Decisions
- **Resolved:**
  - Employers vs job ids: the default is employer, and the owner can switch it with `apply.topics.count_by` (R2).
  - A blocking no-field fact waits for the threshold (D4).
  - One go-live from `int/Q-121` (D1).
  - The applicant-file copy is set through `JOBSCRAPER_CONFIG` + `paths.applicant` (D3, B.8).
  - `strict` keeps no cards and is shown as "Stop when unsure" (D2).
- **Open:**
  - **Shell owner (Q-100 session):** App.vue / tabs.js badge source and label (U3).
  - **Coordinator:** F1 edits `apply/always.py` at one point, the decision → `Answer` copy of the class. Schedule it after the in-flight A1 lanes (`tst/Q-121-A1-U9`, any fix round) merge, or give that one edit to the A1 engineer.

### B.11 Review changes: where each landed
- **Folded as written:**
  - H1 (R6, R4 last line, pins 12 and 16);
  - M3 (R6, copy), M4 (B.4, B.5 PUT), M5 (B.5), M6 (B.2e, copy, pin 19);
  - L1-L6 (R2, R4 T4 "when it runs", the copy, B.8 U1, B.4 accessibility);
  - pins 13-21; the T0 stale-pin lane; the Q2 cap of 20; the Q3 naming pass after migration; the Q5 Overview fact line; the Q8 Settings copy; the Q11 single checkbox.
- **Changed:**
  - **H1:** `applicant.validate` today requires non-empty `labels` (`applicant.py:1221-1223`), so it gains "`labels: []` only with `promoted: true`".
  - **H2:** the exact-label lookup runs first, over every `extra` entry, not only the slug's. Two entries holding one label would make tier 3 answer neither ("memory ambiguous", QD §6.2).
  - **H3:** the class test needs the class on the audit row, which int does not store. Release 1 therefore adds `apply_answers.field_class` (schema v9), and Release 2 moves to v10. Rows without a class fall back to the source plus `declarations.classify_field`.
  - **M1 / M2:** the reviewer's "named_by = class" for path-mapped topics would clash with T1 (also `class`, and proposable), so path mapping is its own column, `topics.profile_path`.
  - **Threshold:** `threshold: 15` becomes `count_by` + `min_count: 16` (Coordinator).
