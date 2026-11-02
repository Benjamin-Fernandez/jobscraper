# Application details form, questions from applications, work-rights defaults (D-74, D-75)

**Stage B** for queue Q-30. Author: architect, 2026-11-03. Status: DRAFT for stage E. Extends `apply_design.md` (cited as **AD §n**); contracts `src/jobscraper/apply/contracts.py` **CONTRACT_VERSION 4** (additive, §12). ADR: `adr/0005-answer-memory-in-profile.md`.

**Owner requests.** D-74 (2026-11-03): "These fields should have a tab to input from the web app, and any fields that the application realises it requires in the future should be dynamically added to the web app if possible, e.g. while applying the LLM realises there should be a field for 'visa status'." D-75 (2026-11-03): "the LLM should always assume I have working rights etc."

**What this adds**
1. **Profile → Application details** (WP-W1, WP-W5 pulled from M21 into M20): every key of `data/applicant.yaml` editable in the web app, with what auto-apply still needs shown at the top.
2. **Questions from applications** (new **F-13**, WP-Q1…Q4): a required question that no tier can answer is captured, grouped with equivalent questions and shown as a new field. The owner answers it once, the answer is saved in `data/applicant.yaml` under `extra:`, and resolver tier 3 reuses it on every later form (F-12's answer memory, brought forward from M22). Attempts that stopped on it can be retried.
3. **Work-rights defaults** (D-75, WP-P9 + WP-A04): a right-to-work or sponsorship question about any country is answered from that country's key, else from a `default` key, and never falls through to the model. The model is always told the applicant's standing work rights.

Prior art: Simplify Copilot lists the questions its autofill cannot answer and stores the owner's answers to custom questions. It reuses them only on an exact wording match ([help.simplify.jobs](https://help.simplify.jobs/article/18-saving-custom-questions)). This design keeps the "list the unanswered questions, store the owner's answer" shape. It matches on the normalised label (AD §7.1) plus the synonyms the owner has confirmed. Answers stay in a local file instead of the browser.

---

## 1. Boundaries

| Concern | Owner module | Never in |
|---|---|---|
| Owner answers (values) | `data/applicant.yaml` → `extra:` through `applicant.save` | SQLite, logs, prompts |
| Pending-question queue (employer text only) | `store.py` tables `questions`, `question_sightings` | applicant.yaml |
| Capture, grouping, key naming (pure) | `apply/questions.py` (stage, new) | web/ |
| Store writes and the model call for naming | `apply_flow.py` (orchestrator; model via the injected `backend`) | stages |
| Reusing answers (tier 3) | `apply/resolve.py` | — |
| Form schema, validation, save | `applicant.py` (foundation) | web routers (they call it) |
| HTTP | `web/routers/applicant.py`, `web/routers/questions.py` | — |

The model **names and groups** questions. It never answers one, never sees a profile value or an answer, and never sees a sensitive question (§5.3).

## 2. Components and files

```
src/jobscraper/
  applicant.py           FOUNDATION  + FORM schema (§3.2), etag, commented backup, `extra` + D-75 validation,
                                       work_rights / work_rights_text (§8), redaction skips extra metadata (§11)
  apply/questions.py     STAGE (new)  kind_for, capture, signature, slug_key, naming prompt/schema/parse, assign_key (§4, §5)
  apply/resolve.py       STAGE        tier 3 reads `extra` (§6); tier-2 kind `country_bool` (§8); work_rights in the tier-5 prompt
  apply_flow.py          ORCHESTRATOR Q-block: capture at the two unanswerable_required points (§4.1)
  store.py               Q-block: DDL §7, methods §7.1
  config.py              Q-block: QuestionCaptureConfig + Config.question_capture (§7.2)
  web/routers/applicant.py   GET/PUT /api/applicant (§9.1)
  web/routers/questions.py   /api/questions… (§9.2)
web/src/
  tabs/Profile.vue                  sub-views "Resume and titles" | "Application details" (§10)
  components/ApplicationDetails.vue  Missing + the full form (WP-W5)
  components/QuestionsInbox.vue      Questions from applications (WP-Q4)
  components/FieldInput.vue          one widget per FORM kind / QuestionKind (shared by both)
config/questions.yaml    researcher: two `country_bool` rows replace the four authorised/sponsorship rows (§8.3)
config/applicant.example.yaml   `default:` keys (§8.1). No `extra:` key: it is optional and the Profile tab creates it
                                 (so the tester's template-keys oracle is unchanged)
```

Dependency check (NF-04, `tests/test_layering.py` unchanged): `apply/questions.py` imports `apply.contracts`, `apply.plan`, `apply.resolve`, `apply.declarations` and `applicant`, which are its own stage plus foundation. The web routers import `store`, `config`, `applicant`, `web.jobs` and `apply.contracts` only. `/api/questions` therefore never computes a normalised label itself: the stage stores `label_norm`, option norms and `employer_norm` in the rows (§7).

## 3. Profile → Application details (F-10, F-11; WP-W1, WP-W5)

### 3.1 Load and save behaviour (decided)

- **Key order is kept.** `applicant.save` uses `yaml.safe_dump(sort_keys=False)`, so existing keys keep their order and new keys are appended at the end of their mapping.
- **Comments are not kept** (AD §5.1, unchanged; no new YAML library). When the first web save would drop comments, `save` first copies the file to **`data/applicant.commented-backup.yaml`**. A file "would drop comments" if any line's first non-blank character is `#`. The copy is made only if it doesn't exist yet. The name matches the existing `data/applicant*.yaml` ignore rule, which the tester asserts (§13).
  New signature: `save(path, profile, *, keep_commented_copy: bool = True) -> None`.
- **Lost-update guard.** `applicant.etag(path) -> str` is the first 16 hex characters of the SHA-256 of the file bytes (`""` if the file is absent). GET returns it, and PUT and the answer endpoint must send it back. If it doesn't match, the server returns 409 and saves nothing. This protects the form, a second tab, the Questions card (which also writes the file) and a hand edit from overwriting each other.
- **Keys the form doesn't know** (anything not in FORM and not `extra`) go round-trip untouched. The UI edits a deep copy of the whole `profile` and PUTs it back. They are listed read-only in the last group (§3.3, group 16).
- **Unreadable file** (`ApplicantError`): GET returns 200 with `profile: {}` and `file.error` set to the error text. PUT returns 409 `{detail:"unreadable"}`, so a broken file is never overwritten.

### 3.2 FORM: the schema the UI renders (in `applicant.py`, one source of truth)

```python
@dataclass(frozen=True)
class FormItem:
    path: str                 # dotted; for kind "entries", the list path
    label: str
    kind: str                 # text | email | phone_cc | digits | int | date | month | bool | enum | country
                              # | url | list_text | list_url | entries | salary | country_bool_map | fixed
    options: tuple[tuple[str, str], ...] = ()   # (value, label) for enum
    help: str = ""
    sub: tuple["FormItem", ...] = ()           # entries: the fields of one entry (paths relative)
@dataclass(frozen=True)
class FormGroup:
    id: str; title: str; items: tuple[FormItem, ...]; note: str = ""
FORM: tuple[FormGroup, ...]
def form_json() -> list[dict]      # FORM + required / recommended / sensitive flags computed from
                                   # REQUIRED_PATHS, RECOMMENDED_PATHS, is_sensitive (never duplicated by hand)
```

Groups in AD §5.4 order. Each group title is shown, and "Private" marks a group or item whose paths are sensitive (AD §5.3). The label is the exact UI text.

| # | Group (title) | Items: path → label (kind; enum labels; help) |
|---|---|---|
| 1 | `identity` "Name" | `legal_first_name` → "Legal first name" (text) · `legal_last_name` → "Legal last name" (text) · `preferred_name` → "Preferred name" (text) · `name_order` → "Name order" (enum: western "First name first", surname_first "Surname first") · `pronouns` → "Pronouns" (text) · `date_of_birth` → "Date of birth" (date) · `gender` → "Gender" (enum: male "Male", female "Female", non_binary "Non-binary", decline "Prefer not to say") |
| 2 | `contact` "Contact" | `email` → "Email for applications" (email; help "Used for every application and site account.") · `backup_email` → "Backup email" (email; help "Used only when a site says the main address already has an account.") · `phone_country_code` → "Phone country code" (phone_cc) · `phone_number` → "Phone number" (digits) · `address_line1` → "Address line 1" · `address_line2` → "Address line 2" · `postal_code` → "Postal code" (digits) · `city` → "City" · `country` → "Country" (country) |
| 3 | `singapore_status` "Work status" | `nationality` → "Nationality" (country) · `residency_status` → "Residency status" (enum: citizen "Singapore Citizen", pr "Singapore Permanent Resident", foreigner "Foreigner") · `work_pass` → "Work pass" (enum: none_required "None needed", ep "Employment Pass", s_pass "S Pass", dp "Dependant's Pass", ltvp_loc "LTVP with Letter of Consent", student_pass "Student's Pass", other "Other") · `authorised_to_work` → "Right to work" (country_bool_map; help "Your answer for every country. Add a country only if it's different there.") · `requires_sponsorship` → "Needs visa sponsorship" (country_bool_map; same help) · `ns_status` → "National Service" (enum: completed "Completed", serving "Serving", exempted "Exempted", not_applicable "Not applicable") · `ord_date` → "ORD date" (month) · `race` → "Race" (enum: chinese "Chinese", malay "Malay", indian "Indian", eurasian "Eurasian", other "Other", decline "Prefer not to say") · `race_other` → "Race, if other" · `religion` → "Religion" (text; help "Or leave it as decline.") · `marital_status` → "Marital status" (enum: single "Single", married "Married", decline "Prefer not to say") · `nric_last4` → "NRIC, last 4 characters" (text; help "Only the last 4, such as 123A. Never the full NRIC.") |
| 4 | `us_self_id` "US equal-employment questions" | `eeo_gender` → "Gender" · `eeo_race_ethnicity` → "Race or ethnicity" · `veteran_status` → "Veteran status" · `disability_status` → "Disability status" (all enum; values from `applicant.ENUMS`, `decline` = "Prefer not to say", others capitalised with `_`→space) |
| 5 | `availability` "Availability" | `notice_period_days` → "Notice period, in days" (int) · `earliest_start_date` → "Earliest start date" (date) · `willing_to_relocate` → "Willing to relocate" (bool) · `willing_to_travel_pct` → "Willing to travel, % of the time" (int) |
| 6 | `pay` "Pay" | `expected_salary` → "Expected salary" (salary: amount int, currency 3 letters, period enum monthly "per month"/annual "per year", negotiable bool) · `current_salary` → "Current salary" (salary; a "I don't have one" switch writes `null`) · `months_per_year` → "Months of pay per year" (int; help "13 if you count the AWS bonus.") |
| 7 | `education` "Education" | entries: `institution` "School", `degree` "Degree", `major` "Major", `minor` "Minor", `start` "Start" (month), `end` "End, or expected end" (month), `grade_type` "Grade type" (enum: gpa "GPA", cap "CAP", honours_class "Honours class"), `grade` "Grade", `grade_scale` "Out of" |
| 8 | `experience` "Experience" | entries: `employer` "Employer", `title` "Job title", `start` "Start" (month), `end` "End" (month; empty = "I still work here"), `location` "Location", `description` "What you did" (text, multi-line) |
| 9 | `skills_languages` "Skills and languages" | `skills` → "Skills" (list_text) · `attested_skills` → "Skills you confirmed" (list_text; help "Added when you click “I have this” in the resume tailor.") · `languages` → entries: `language` "Language", `spoken` "Spoken", `written` "Written" (enum: native "Native", fluent "Fluent", professional "Professional", basic "Basic") |
| 10 | `links` "Links" | `linkedin` "LinkedIn" · `github` "GitHub" · `portfolio` "Portfolio" (url) · `other` → "Other links" (list_url) |
| 11 | `documents` "Files" | `resume` → "Resume file" (text; help "Leave empty to use data/resume.pdf or data/resume.docx.") · `transcript` → "Transcript file" (text) |
| 12 | `sourcing` "Sourcing" | `how_heard_default` → "How you heard about a job" (text) |
| 13 | `consents` "Consents" | `privacy_consent` → "I consent to employers processing my application data" · `data_retention_consent` → "Employers may keep my data for future roles" · `talent_pool_opt_in` → "Add me to talent pools" · `certify_true` → "I certify the information I give is true and complete" (all bool) |
| 14 | `declarations` "Declarations" (note: "Your standing answers. Change any that stop being true.") | `pep` → "Are you a politically exposed person, or a family member or close associate of one?" · `conflict_audit_independence` → "Do you have an audit or independence conflict with an employer?" · `shareholding_in_company` → "Do you hold shares or a financial interest in the employers you apply to?" · `holdings` → "Companies you hold shares in" (list_text) · `relatives_at_company` → "Do relatives of yours work at the employers you apply to?" · `relatives_employers` → "Employers where a relative works" (list_text) · `criminal_record` → "Have you ever been convicted of a criminal offence?" · `bankruptcy` → "Have you ever been bankrupt?" · `regulatory_disciplinary` → "Have you ever faced regulatory or disciplinary action?" · `non_compete` → "Are you bound by a non-compete or similar agreement?" (bools as Yes/No switches) · `health_disclosure` → "Health questions" (fixed: "Always “Prefer not to say”") |
| 15 | `extra` "Answers you gave to application questions" | one row per `extra` entry: title, the answer widget for its kind (§6.1), "Only for <employer>" rows from `by_employer`, button "Remove" (confirm §10.3). Hidden when `extra` is empty |
| 16 | (no path) "Other keys in your file" | read-only `path: value` for every leaf not covered above (sensitive paths are shown as "•••"). Note: "These keys aren't in the form. They're kept as they are. Edit them in data/applicant.yaml." Hidden when there are none |

`version` is not shown. It is always written as 1.

### 3.3 Required and missing

- `missing` (from `applicant.missing_for_apply`) feeds the **"Needed before auto-apply"** section at the top (§10.2). Each field in the form whose path is required shows a "Needed" tag while it is empty.
- After D-75 (§8.1), `REQUIRED_PATHS` no longer lists `singapore_status.authorised_to_work.SG` and `requires_sponsorship.SG`: they always have an answer (the country key, else `default`, else the standing answer). With today's owner file the list is `singapore_status.residency_status`, `availability.earliest_start_date` and `pay.expected_salary.amount`.

## 4. Capture: questions from applications (F-13; WP-Q1)

### 4.1 When (apply_flow Q-block)

`apply_flow` captures at the two places where it ends an attempt `failed(unanswerable_required)` (AD §4.4):
1. **planning**: a schema plan resolved with a required field `unknown`/`ungrounded` (after the B11 MyGreenhouse deferral, i.e. at the moment the flow actually fails);
2. **filling**: a DOM step resolved with such a field.

At that point it captures **every** required field in the resolved set that qualifies (§4.2), not only the first. That way the owner answers them all before a retry. On wizards (Workday) later steps aren't known yet: a retry can surface the next step's questions, and each retry gets further. Capture runs in dry-run and auto mode alike.

It is called as `_capture_questions(store, cfg, backend, attempt_row, job, fields, answers, ctx, rules)`. That helper calls `questions.capture(...)`, then for each captured question it assigns a key (§5), runs `store.upsert_question` and `store.add_sighting`, and logs one line per question: `[attempt 12] question captured key=<key> kind=<kind> reason=<reason>` (no values; labels are employer text, AD §17). **Any exception inside capture is caught and logged** as `question capture failed: <ExcType>`. The attempt still ends `unanswerable_required` exactly as before, so capture can never change an outcome.

Optional fields that end `blank_optional` are **not** captured in M20 (a later `question_capture.optional` switch could add them, M21). With `question_capture.enabled: false`, nothing is captured.

### 4.2 Which fields (`questions.capture(fields, answers, ctx, rules) -> list[CapturedQuestion]`, pure)

A field qualifies when all of these hold: `required`; its Answer status is `UNKNOWN` or `UNGROUNDED`; its type is not `FILE`/`HIDDEN`; it is not an employer-specific declaration (`declarations.classify(...)` ∈ `EMPLOYER_SPECIFIC_DECLARATIONS`; tier 4 owns those, and an `unknown` there is a real stop).

| `reason` (`QuestionReason`) | Condition (first that holds) | `target_path` |
|---|---|---|
| `profile_gap` | tier-1 canonical with a profile path in `CANONICAL_PATHS` whose value is empty; or `Answer.rule_id` names a tier-2 profile key (virtual `k#id` → `k`; not `computed.*`) whose value is empty, and that path is a FORM path (list index `[0]` allowed) | that path |
| `no_option_fits` | `rule_id` names a profile key with a value, or a canonical with a value, but no offered option fits | "" |
| `attestation_unclear` | tier 4 returned `unknown` (AMBIGUOUS, a required "don't tick" box, a required health question) | "" |
| `conflict` | D-75: work rights differ between the countries a label names (§8.2) | "" |
| `ungrounded` | status `UNGROUNDED` | "" |
| `no_rule` | anything else (no tier answered; model unknown, unavailable or disagreeing) | "" |

`CANONICAL_PATHS` (in `questions.py`): FIRST_NAME/LAST_NAME/PREFERRED_NAME → `identity.*`; ADDRESS_LINE1/2, CITY, POSTAL_CODE, PHONE, PHONE_COUNTRY_CODE, COUNTRY → `contact.*`; LOCATION → `contact.city`; LINKEDIN/GITHUB/PORTFOLIO → `links.*`; HOW_HEARD → `sourcing.how_heard_default`; EEO_GENDER/EEO_RACE/EEO_VETERAN/EEO_DISABILITY → `us_self_id.*`. Others have no path.

**Kind** (`kind_for(field) -> QuestionKind`): single CHECKBOX or `resolve.bool_shaped` → `yes_no`; DROPDOWN/RADIO → `choice`; MULTI_CHOICE → `multi`; DATE → `date`; NUMBER → `number`; everything else (TEXT, TEXTAREA, EMAIL, PHONE, URL, TYPEAHEAD) → `text`.

**Sensitive** = `answer.sensitive` or the tier-2 rule matched is sensitive, or `reason` is `attestation_unclear`, or the canonical is in `resolve.SENSITIVE_CANONICALS`, or `target_path` is an S path (`applicant.is_sensitive`).

`CapturedQuestion` (contracts) holds: `label` (verbatim, ≤ 300 chars), `label_norm`, `description` (≤ 300), `kind`, `options` (verbatim, ≤ 50), `option_norms`, `required`, `sensitive`, `reason`, `target_path`, `field_key`, `field_type`, `step`, `ats`, `employer_norm` (§6.2 normalisation of `ctx.employer_name`) and `note` (the resolver's note; it never holds a value).

## 5. Grouping and naming

### 5.1 Equivalent questions

- **Signature** `sig = sha256(kind + "\n" + label_norm + "\n" + "\n".join(sorted(option_norms)))[:16]`. The same `sig` is the same `questions` row; each new appearance adds a sighting.
- **Group** = all rows sharing a `key`. The UI shows one card per key, and a choice group has one picker per distinct option set (a "variant" = one row).

### 5.2 Key assignment (`questions.assign_key`, deterministic first; for a new `sig` only)

1. `target_path` set → `key = target_path`, `named_by = "profile"`, title = the FORM label of that path.
2. An `extra` entry already lists `label_norm` in `labels` → that key (e.g. a new option set for a question already answered).
3. A `questions` row with the same `label_norm` and a compatible kind (same `QuestionKind`) → its key.
4. Not sensitive, `question_capture.llm_naming` on and a backend that isn't `OffBackend` → the model's suggestion (§5.3). `same_as` joins an existing non-sensitive key of the same kind; otherwise `key` is used if free (or held by the same kind). `named_by = "model"`.
5. Otherwise **slug**: tokens of `label_norm` minus the stop words `a an the of in on for to and or your you are is do does have has what which please select enter provide` → the first 4 → joined with `_`, keeping only `[a-z0-9_]`, ≤ 40 characters, a letter first (prefix `q_` otherwise). If that's empty, the slug is `question`. A clash with a key of a different label or kind gets `_2`, `_3`, and so on. `named_by = "rule"`, title = the verbatim label (≤ 60 chars, cut at a word).

Keys match `EXTRA_KEY_PATTERN = ^[a-z][a-z0-9_]{1,39}$` (contracts) except `profile` keys, which are dotted profile paths.

### 5.3 Model naming (optional; never answers)

- Call: `backend.complete(NAMING_SYSTEM, user, max_tokens=200, format=NAMING_SCHEMA, temperature=0, seed=7)`, made by `apply_flow` with the attempt's backend. Timeout = `question_capture.naming_timeout_s` (20). One call per new non-sensitive `sig`, at most `question_capture.naming_max_per_attempt` (10) per attempt; the rest get slugs.
- `NAMING_SYSTEM` (constant in `questions.py`):
  ```
  You name a question from a job application form so it can be saved as a field in the applicant's profile.
  You never answer the question. Reply with JSON only.
  key: a short snake_case name for what is asked (for example visa_status, notice_period, gpa).
  title: a short label a person would read (at most 6 words).
  description: one sentence saying what the field holds (at most 25 words).
  same_as: the key of an EXISTING FIELD that asks for the same fact, or "" if none does.
  ```
- User prompt: `QUESTION: <label>\nHELP: <description>\nTYPE: <kind>\nOPTIONS:\n- <option>…(≤ 20)\n\nEXISTING FIELDS:\n- <key>: <title> (<kind>)…` listing **non-sensitive** keys only (≤ 50, newest first) from `extra` and open `questions` rows. Nothing from the profile, no answer and no employer name is included.
- `NAMING_SCHEMA`: `{"type":"object","properties":{"key":{"type":"string","pattern":"^[a-z][a-z0-9_]{1,39}$"},"title":{"type":"string","maxLength":60},"description":{"type":"string","maxLength":160},"same_as":{"type":"string","maxLength":40}},"required":["key","title","description","same_as"]}`.
- `questions.parse_naming(reply, existing, q)` re-checks everything: the key pattern, a non-empty title (otherwise the label is used), `same_as` ∈ the listed keys with the same kind (otherwise it's ignored), and no clash with a key of another kind (otherwise slug). `BackendError`, timeout or an invalid reply → slug, plus one log line `question naming unavailable`.
- **Wrong merges are visible.** A card lists every verbatim label in its group ("Also asked as …"), so the owner sees what they're answering. Splitting a wrong merge is M21 (until then the owner edits `extra` labels in the file).

## 6. Storage of answers and tier 3 (F-12 brought forward; WP-Q2). Decision: ADR-0005

### 6.1 `data/applicant.yaml` → `extra:`

```yaml
extra:                                   # answers to questions employers asked (F-13); written by the Profile tab
  visa_status:                           # key: ^[a-z][a-z0-9_]{1,39}$
    title: Visa status                   # what the owner reads
    description: ""                      # optional (model's sentence)
    kind: choice                         # yes_no | choice | multi | text | date | number
    sensitive: false                     # true: shown as Private, never sent to the model, redacted in logs
    labels:                              # normalised labels (AD §7.1) that mean this question; ≥ 1
      - what is your visa status
      - current work pass type
    value: null                          # yes_no: true|false · text: str ≤ 2000 · date: YYYY-MM-DD|YYYY-MM · number: int|float · choice/multi: null
    picks: [singapore citizen]           # choice/multi: normalised option labels the owner chose (⊆ seen)
    seen: [singapore citizen, permanent resident, employment pass]   # choice/multi: every normalised option the owner decided on
    by_employer:                         # optional overrides; key = normalised employer (§6.2)
      shopee: {value: null, picks: [citizen], seen: [citizen, pr, others]}
```

`picks`/`seen` are the "options → value map": across all the option sets seen, `picks` are the options that mean the owner's answer. Matching is by equality of normalised option labels, never by substring.

`applicant.validate` rules for `extra` (errors at `extra.<key>.<field>`): key pattern; `kind` in the enum; `labels` a non-empty list of strings; `value` type per kind (date per `DATE` formats; text ≤ 2000); `picks` ⊆ `seen` and both lists of strings for choice/multi, with `picks` non-empty for choice; `sensitive` bool; `by_employer` a mapping of non-empty keys to `{value, picks, seen}` checked the same way. The NRIC rule already walks the whole file.

### 6.2 Tier 3 lookup (`resolve._tier3`, extended; confidence 0.95)

`_extra_answer(f, label_norm, ctx)` runs first, then the existing `answer_memory` lookup (unchanged; the table stays empty, see ADR-0005):

1. Skip if `declarations.classify(label_norm, norm(description))` ∈ `EMPLOYER_SPECIFIC_DECLARATIONS` (tier 4 owns them).
2. Entries whose `labels` contain `label_norm` exactly. None → no answer. Two or more → no answer (note `memory ambiguous: k1, k2`).
3. Scope: `by_employer[e]` for the first `e` in [employer_norm(`ctx.employer_name`), employer_norm(each alias)] that is present; else the entry itself. `employer_norm` = AD §7.5 company normalisation, tokens joined by a space.
4. Fit by kind and field: `yes_no` → `fit_bool(f, value)` (checkbox: tick for true; text: "Yes"/"No"). `choice` on DROPDOWN/RADIO → the offered options whose norm ∈ `picks`, exactly one. `multi` on MULTI_CHOICE → only when every offered option's norm ∈ `seen`, then offered ∩ `picks`, non-empty. `text` → `fit_text`. `date` → `fit_date`. `number` → `fit_number`. A kind that doesn't suit the field type → no answer.
5. Answer: tier `MEMORY`, `source = "memory:extra.<key>"`, `rule_id = "extra.<key>"` (+ `"@<employer_norm>"` when scoped), `sensitive = entry.sensitive`.

**Order change in `resolve_field`** (fail-closed is kept, because the owner's own explicit answer is a fact they gave):

```
t2 answer        → return it
t3 (extra, then answer_memory) → return it   # now also consulted when tier 2 stopped on a sensitive no-fit
t2 stop          → unknown (rule_id = the tier-2 key)
t4, t5           → unchanged
```

On every final `unknown` whose tier-2 selection found exactly one key, `rule_id` is set to that key (it was ""). Capture reads it (§4.2). The answer status and the attempt outcome are unchanged.

Audit (F-39): rows carry `source = memory:extra.<key>`. The M21 audit view's "Remembered" badge covers them.

### 6.3 Promotion of an `extra` key (documented, not built)

When an `extra` key proves general (e.g. `visa_status` on many forms), the architect adds a first-class profile path plus a `questions.yaml` row. A one-off migration then moves the value, and the `extra` entry is deleted. Until then `extra` works without code changes.

## 7. Store (DDL; Q-block, no `SCHEMA_VERSION` change: `CREATE TABLE IF NOT EXISTS` runs on every open, like the tailor block)

```sql
-- M20 questions (questions_design §7)
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sig TEXT NOT NULL UNIQUE,               -- §5.1
    key TEXT NOT NULL,                      -- extra key, or a profile path when target_path is set
    target_path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,                     -- QuestionKind
    label TEXT NOT NULL,                    -- verbatim, first seen (employer text)
    label_norm TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',-- [{"label": verbatim, "norm": normalised}] as first seen
    sensitive INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,                   -- QuestionReason, latest sighting
    named_by TEXT NOT NULL DEFAULT 'rule',  -- rule | model | profile
    status TEXT NOT NULL DEFAULT 'open',    -- QuestionStatus
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, answered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_questions_key ON questions(key);
CREATE TABLE IF NOT EXISTS question_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    attempt_id INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    company_id INTEGER,
    employer_norm TEXT NOT NULL DEFAULT '',
    ats TEXT NOT NULL DEFAULT '',
    step TEXT NOT NULL DEFAULT '',
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,                    -- verbatim as seen here
    required INTEGER NOT NULL,
    seen_at TEXT NOT NULL,
    UNIQUE (question_id, attempt_id, field_key)
);
CREATE INDEX IF NOT EXISTS idx_sightings_attempt ON question_sightings(attempt_id);
CREATE INDEX IF NOT EXISTS idx_sightings_question ON question_sightings(question_id);
```

No answer value is ever stored in these tables.

### 7.1 Store methods (names fixed; SQL is the engineer's)

- `upsert_question(q: dict, now) -> int`: insert by `sig`, or update `last_seen_at`, `reason`. A seen-again `answered` row goes back to `open` (the saved answer didn't fit this time). A `dismissed` row stays dismissed.
- `add_sighting(question_id, attempt_id, job_id, company_id, employer_norm, ats, step, field_key, label, required, now)`: ignore on the UNIQUE conflict.
- `question_groups(status: str = "open") -> list[dict]`: one dict per key, holding `{key, title, description, kind, sensitive, target_path, status, named_by, labels[verbatim, distinct], variants[{question_id, label, options}], employers[company names, distinct, by first sighting], waiting:int, first_seen_at, last_seen_at}`. `status` is `"open"`, `"answered"` or `"all"`. A group's status is `open` if any of its rows is open. `waiting` = the distinct jobs in `retry_candidates()` that have a sighting in the group.
- `question_keys() -> list[tuple[key, title, kind, sensitive]]`: for naming and §5.2 rule 3.
- `questions_by_key(key) -> list[dict]`
- `set_questions_status(key, status, now) -> int`
- `retry_candidates() -> list[dict]`: jobs whose **newest** attempt is `failed` with reason `unanswerable_required` and has ≥ 1 sighting. Each dict is `{job_id, attempt_id, company, title, open:int, dismissed:int}`, where `open`/`dismissed` count that attempt's sightings by question status. **Ready** = `open == 0 and dismissed == 0`.

### 7.2 Config (Q-block; `config.py` + `config/config.yaml`)

```yaml
question_capture:              # questions_design.md (D-74)
  enabled: true                # capture required questions no tier answered
  llm_naming: true             # let the local model name and group non-sensitive questions (never answer)
  naming_timeout_s: 20
  naming_max_per_attempt: 10
```

A frozen `QuestionCaptureConfig` with these fields and defaults is defined above `Config`, and the property `question_capture` goes at the end of `Config`. Lane B's `ApplyConfig` is not touched.

## 8. Work-rights defaults (D-75; WP-P9, WP-A04)

### 8.1 Profile

```yaml
singapore_status:
  authorised_to_work: {SG: true, default: true}     # default: every country you don't list
  requires_sponsorship: {SG: false, default: false}
```

- `validate`: keys are 2-letter ISO codes **or `default`**. Values are bool or null. The message for a bad key becomes "keys must be 2-letter ISO country codes or default".
- `applicant.work_rights(profile, country: str) -> tuple[bool, bool]` returns (authorised, needs_sponsorship). For each map: the country's own bool, else `default`'s bool, else the **standing answer** (authorised `True`, sponsorship `False`). An absent or empty map therefore always has an answer.
- `REQUIRED_PATHS` loses `singapore_status.authorised_to_work.SG` and `singapore_status.requires_sponsorship.SG` (always answerable); the meter's `needed` drops by 2.
- Template (AD §5.4): the two lines above, with the comment `# default: every country you don't list`.
- `applicant.work_rights_text(profile) -> str`. With the defaults (true, false) it returns exactly **"The applicant has the right to work and needs no visa sponsorship."** Otherwise it returns "The applicant {has|does not have} the right to work and {needs no|needs} visa sponsorship." After that comes one sentence per country key whose value differs from its map's effective default, for example "For US: does not have the right to work." / "For US: needs visa sponsorship." (ISO code, so the foundation needs no country table.)
- `grounding_text` appends `work_rights_text(profile)` as its last line, and the tier-5 user prompt's APPLICANT JSON gains `"work_rights": work_rights_text(profile)` (`resolve.user_prompt`). The model is therefore always told, and a choice answer can quote it as evidence (AD §7.7).

### 8.2 Tier 2 kind `country_bool` (resolve.py)

`questions.yaml` entries with `kind: country_bool` have `key` = `singapore_status.authorised_to_work` or `singapore_status.requires_sponsorship` (the loader refuses other keys and `value_map`/`yes_if` on this kind). Selection and scoring are unchanged (AD §7.3.1). On a match:

1. **Countries named** (`resolve.label_countries(label_norm) -> set[str]`): phrase match (contiguous tokens, **without** the one-token ≤ 4-token rule) of each `COUNTRIES` name plus these aliases: US `united states`, `united states of america`, `u s`, `u s a`, `usa`, `america`; GB `uk`, `u k`, `britain`, `great britain`, `england`; EU `european union`, `eu`, `eea`, `europe` (key `EU`); AE `uae`, `united arab emirates`. The token `us` alone is **never** a country ("work for us"). ISO codes are never aliases except those listed. Demonyms are not used.
2. **No country named** → `{contact.country}` if the label contains `where you live`, `where you reside`, `country of residence` or `where you currently live`; else `{ctx.job_country}`. That covers "the country where this job is located", "this country" and no country at all. `ResolveContext.job_country` is new, defaults to `"SG"` and is left at the default by `apply_flow`, because JobScraper's roles are Singapore roles.
3. **Value**: for `authorised_to_work`, `a(c)`; for `requires_sponsorship`, `s(c)` (from `work_rights`). Exception: on `authorised_to_work`, a label with the token `without` and any of `sponsor`, `sponsorship`, `visa` → `a(c) and not s(c)` ("Can you work in the US without sponsorship?").
4. Several countries: if all values are equal, use that value. If they differ → stop: `unknown`, note `work rights differ: <c1>, <c2>`, captured with reason `conflict`. Not sensitive, but tier 5 is **not** tried: D-75 means these never reach the model.
5. Fit: `fit_bool` (bool-shaped choice, checkbox, or "Yes"/"No" text). If the options aren't bool-shaped, that tier does not answer (it is not sensitive), and t3/t4/t5 follow as usual. The model sees `work_rights` (§8.1).
6. `source = "profile:singapore_status.<map>.<C or default or standing>"`, `rule_id = <key>`, confidence 0.95, `sensitive = False`.

Not covered by D-75: residency or citizenship questions stay on `singapore_status.residency_status` (enum + `yes_if`), and work-pass type stays on `singapore_status.work_pass`. "Do you hold a (valid) work permit?" is deliberately in neither list (for a citizen the literal answer is No). It falls to tier 5, which sees `work_rights`, or to capture.

### 8.3 `config/questions.yaml` rows (researcher, WP-A04)

Replace the four rows `singapore_status.authorised_to_work.SG`, `.US`, `requires_sponsorship.SG`, `.US` with two `country_bool` rows. Drop every country `exclude` (the country is detected now, not excluded). The minimum synonyms are below; the researcher may add more from real forms.

| Row | Minimum synonyms (normalised) |
|---|---|
| `singapore_status.authorised_to_work` | authorised to work · authorized to work · legally authorised to work · legally authorized to work · legally entitled to work · legally allowed to work · legally eligible to work · legally able to work · eligible to work · eligible for employment · right to work · work authorisation · work authorization · authorisation to work · authorization to work · permitted to work · allowed to work · entitled to work · work rights · working rights · without sponsorship · without visa sponsorship · without requiring sponsorship |
| `singapore_status.requires_sponsorship` | require sponsorship · require visa sponsorship · need sponsorship · need visa sponsorship · visa sponsorship · work visa sponsorship · immigration sponsorship · sponsorship to work · sponsorship for employment · sponsorship now or in the future · now or in the future require · require a work permit · need a work permit · work permit required · require a work visa · need a work visa · work visa required · visa required · require a visa · need a visa · require visa support · visa transfer · require an employment pass · need an employment pass · require a work pass · need a work pass · work pass sponsorship |

Rule for the researcher: the `without …` phrases belong **only** to the authorised row, and the sponsorship row gets `exclude: [without]`. The `work_pass` `yes_if` excludes (`require an`, `need a`, …) stay as they are, so "Will you require an Employment Pass?" scores on the sponsorship row.

## 9. Web API

### 9.1 `web/routers/applicant.py` (WP-W1)

| Method, path | Request | Response |
|---|---|---|
| `GET /api/applicant` | | `{profile, etag, errors:[{path,message}], missing:[path], completeness:{filled,needed}, from_resume:[path], sensitive:[path], form: applicant.form_json(), file:{exists, has_comments, error}}` |
| `PUT /api/applicant` | `{profile, etag}` | 200 same shape as GET (new etag) · 409 `{detail:"changed"}` (etag mismatch) or `{detail:"unreadable"}` · 422 `{detail:"invalid", errors:[{path,message}]}`. Nothing is saved on 409/422 |

`sensitive` = every leaf path in `profile` for which `applicant.is_sensitive` is true, plus `extra.<key>` for entries with `sensitive: true`. `applicant init` / `from_resume` stay in M21 (WP-W1b).

### 9.2 `web/routers/questions.py` (WP-Q3)

| Method, path | Request | Response |
|---|---|---|
| `GET /api/questions?status=open\|answered\|all` | | `{mode:"auto"\|"dry_run", groups:[store.question_groups + current], ready:[{job_id, attempt_id, company, title}], waiting:[{job_id, company, title, open}], busy:bool}`. `current` = for answered groups, `{value, picks, by_employer}` from `extra[key]` (or the profile value at `target_path`) |
| `POST /api/questions/answer` | `{key, etag, employer?: str\|null, value?: any, picks?: {"<question_id>": ["<verbatim option label>", …]}}` | 200 `{answered:[question_id], ready:[…], etag}` · 404 unknown key · 409 changed/unreadable · 422 `{detail:"invalid", errors}` |
| `POST /api/questions/{key}/dismiss` | | 204; status `dismissed` |
| `POST /api/questions/retry` | `{job_ids:[str]}` (≤ 20; each must be in `ready`) | 202 `{job}` (kind `apply`; `opts` without `dry_run`, so `cmd_apply` uses the effective mode, AD §14.1) · 409 `{detail:"busy"}` · 422 `{detail:"not_ready", job_ids:[…]}` |

**Answer algorithm** (server, all in the router through foundation calls):
1. Load the profile, then compare etags. Get the rows with `store.questions_by_key(key)`; none → 404.
2. `target_path` set: write `value` at that path (list index `[0]` creates the first entry if the list is empty) and skip to step 4. `picks` are not accepted here, because the card shows the profile field's own widget.
3. Otherwise merge into `extra[key]`, creating it with `title`, `description`, `kind` and `sensitive` from the rows. `labels` ∪= every row's `label_norm`. For `yes_no`/`text`/`date`/`number`, set `value`. For `choice`/`multi`, `seen` ∪= every option norm of each row in `picks`, and `picks` ∪= the norms of the chosen labels (looked up in that row's `options_json`; an unknown label → 422). With `employer`, write into `by_employer[<the sightings' employer_norm for that company>]` instead of the base. `employer` must be one of the group's employers, else 422.
4. `applicant.save(path, profile)`: on `ApplicantError`, 422 with its errors (nothing saved). Then `set_questions_status(key, "answered")`.

`mode` = settings `apply.mode` else `cfg.apply.mode`. `busy` = `JobManager` has a running job.

## 10. UI (fast-track spec; WP-W5, WP-Q4)

### 10.1 Placement

The Profile tab gets two sub-views behind a segmented control (`role="tablist"`): **"Resume and titles"** (today's content, unchanged) and **"Application details"**. The chosen view is remembered in `localStorage["profile.view"]`. The first visit opens "Application details" when `missing` or open questions exist. The control's second label shows a count when that is above zero: "Application details (4)" = missing + open groups.

"Application details" shows, in order:
1. **Needed before auto-apply** (hidden when `missing` is empty)
2. **Questions from applications** (always shown; empty state when none)
3. **The full form** (§3.2 groups 1–16) with the meter and a sticky "Save details" bar.

### 10.2 Copy (owner-facing; one voice: what, why, what to do)

| Element | Copy |
|---|---|
| Missing heading / intro | **Needed before auto-apply** · "Auto-apply won't start until these are filled in." |
| Missing item | "<field label>" + link **Fill in** (scrolls to and focuses the field) |
| Meter | "<filled> of <needed> details filled" |
| Field tags | "Needed" (required and empty) · "Private: never sent to the AI" (sensitive) · "From your resume, please check" (`from_resume`) |
| Questions heading / intro | **Questions from applications** · "Employers asked these, and JobScraper had no answer it could back up. Answer once and it's used on every application that asks." |
| Questions empty state | "No questions waiting. When an application asks something JobScraper can't answer, it shows up here." |
| Card meta | "Asked by Shopee, Grab · 2 applications waiting" (1: "1 application waiting"; 0: omit the second part) |
| Card, several labels | "Also asked as: “What is your visa status?”, “Current work pass type”" |
| Card reason chip | `no_rule` "Not in your profile" · `ungrounded` "The AI's answer couldn't be checked against your details" · `profile_gap` "Missing from your profile" · `no_option_fits` "Your saved answer isn't one of this form's options" · `attestation_unclear` "A declaration JobScraper couldn't classify" · `conflict` "Your work rights differ between the countries asked" |
| Profile-gap card | "This is your profile's <field label>. Your answer is saved there." |
| Choice variant label | "<Employer>'s options" (one picker per option set) |
| Scope control | "Use this answer for: **All employers** ▾" (options: All employers, then each employer in the group) |
| Primary / secondary | **Save answer** · **I'll answer this one by hand** |
| Saved toast | "Saved. JobScraper will use this answer from now on." |
| Dismiss toast | "Okay. Applications that ask this will stop there, so you can finish them by hand." |
| Ready banner | "<n> application(s) can go again now." **Retry <n> applications** |
| Retry confirm (auto mode only) | Title "Send <n> applications now?" · body "JobScraper fills them in and submits them in Edge." · **Send applications** / **Not now** |
| Retry started (dry run) | "Started. Dry run: everything is filled in and nothing is sent." |
| Busy | "Another job is running. Retry when it finishes." |
| Answered list | collapsible "Answered questions (<n>)", each with **Change answer** |
| Form save | **Save details** → "Saved." |
| 422 | "Some details need fixing. They're marked below." (+ the inline message per path) |
| 409 changed | "This file changed since you opened it, in another tab or by hand. Reload to get the latest, then make your change again." **Reload** |
| 409 unreadable / GET `file.error` | "JobScraper can't read data/applicant.yaml (<error>). Fix the file by hand. Nothing will be saved over it until then." |
| Comments note (when `file.has_comments`) | "Saving rewrites applicant.yaml without its comments. A copy with the comments is kept as applicant.commented-backup.yaml." |
| Remove an answer (group 15) | "Remove this answer? Applications that ask it will stop and ask you again." **Remove answer** / **Keep it** |
| `unanswerable_required` hint (contracts) | "Answer it under Profile → Application details, then retry." |

### 10.3 Widgets (`FieldInput.vue`, shared)

`yes_no` = two radio buttons, Yes / No · `choice` = `<select>` of the variant's verbatim options · `multi` = checkboxes · `text` = textarea (≤ 2000) · `date` = date input (stored `YYYY-MM-DD`) · `number` = number input · FORM kinds per §3.2 (`country_bool_map` = a "Default" Yes/No plus "Add a country" rows of ISO code + Yes/No; `entries` = repeatable fieldsets with Add/Remove; `list_text` = chips with an add box; `salary` = amount + currency + period + negotiable). All inputs have visible labels, errors are linked via `aria-describedby`, and the sensitive tag is plain text, not colour alone.

## 11. Privacy, logging, degradation

- **NF-01**: answers live only in `data/applicant.yaml` (gitignored, like the commented backup). The DB (`data/jobscraper.db`, gitignored) holds employer text only (labels, options, employer names). Fixtures use synthetic values.
- **NF-02/NF-09**: `redaction_values` keeps walking `extra` values, `picks` and `by_employer`, so answers are redacted from logs. It **skips** `extra.*.labels`, `title`, `description`, `seen`, `kind`, `sensitive`, so question text stays readable in the job log (it is employer text, AD §17). Capture and naming log keys, kinds and reasons only.
- **NF-03**: naming uses the local backend only; with `OffBackend` keys are slugs.
- **Model boundary**: naming prompts carry the employer's question text of non-sensitive questions and the titles of non-sensitive keys. They never carry a profile value, an answer or an employer name. Tier 5 is unchanged except for the `work_rights` sentence (non-sensitive: it is the D-75 standing answer).

| Failure | Behaviour |
|---|---|
| Ollama down or invalid naming reply | slug key; log `question naming unavailable` |
| Store error during capture | log `question capture failed: <type>`; attempt still `failed(unanswerable_required)` |
| applicant.yaml unreadable | GET shows the error; PUT/answer 409 `unreadable`; nothing is overwritten |
| Concurrent edit | 409 `changed`; the UI offers Reload |
| Saved answer doesn't fit on the next form | not answered at tier 3 → captured again → the row reopens (`no_option_fits` or a new variant) |
| Malformed `extra` entry (hand edit) | `validate` names it; tier 3 skips that entry (no answer, note `memory entry invalid: <key>`) |
| Answer saved while an apply job runs | the running job already loaded the profile; the next attempt uses it. Retry is refused while busy |
| Two entries list the same label (hand edit) | tier 3 doesn't answer (`memory ambiguous`); capture reassigns per §5.2 |

## 12. Contracts v4 (additive; no ADR needed for the contract, ADR-0005 for the storage choice)

`QuestionKind`, `QuestionReason`, `QuestionStatus`, `CapturedQuestion`, `EXTRA_KEY_PATTERN`, `ResolveContext.job_country = "SG"`, and the `UNANSWERABLE_REQUIRED` hint copy. Nothing existing changes meaning. Reason codes: **none added**. A stopped attempt keeps `unanswerable_required`, and "Retry" is a new attempt through the normal `apply` job (the failed one is terminal; duplicate rules don't count `failed`).

## 13. Tests the tester writes (WP-Q0)

| File (needle) | Oracles |
|---|---|
| `tests/test_applicant_form.py` (`applicant_form`) | every leaf of `config/applicant.example.yaml` is a FORM path or inside an `entries`/map item; `form_json` flags match `REQUIRED_PATHS`/`is_sensitive`; `save` keeps key order and writes `applicant.commented-backup.yaml` once when the file had comments (not on the second save, not when there were none); `etag` changes with the bytes; `extra` validation cases (§6.1: bad key, picks ⊄ seen, wrong value type, empty labels, bad `by_employer`); D-75 validation (`default` accepted; `{sg: true}` error; `default: "yes"` error) |
| `tests/test_web_applicant.py` (`web_applicant`) | GET shape incl. `form`, `etag`, `file`; PUT bad postal code → 422 naming `contact.postal_code`, file unchanged; stale etag → 409 `changed`; unreadable file → GET 200 with `file.error`, PUT 409 `unreadable`; unknown keys round-trip |
| `tests/test_apply_resolve_rules.py` (`apply_resolve_rules`), D-75 cases with `tests/fixtures/apply/questions_d75.yaml` (the two `country_bool` rows) and, after WP-A04, the real file | (1) "Are you legally authorized to work in the United States?" Yes/No, `{SG: true, default: true}` → Yes, source `…authorised_to_work.default` · (2) same with `US: false` → No, source `….US` · (3) "Will you now or in the future require sponsorship for employment visa status (e.g. H-1B)?" → No · (4) "Do you require visa sponsorship to work in the UK?" with the map absent → No (standing) · (5) "Are you authorised to work in the country where this job is located?" → `SG` key · (6) "Work permit required?" → No · (7) "Are you eligible to work in Canada?" maps absent → Yes · (8) "Can you work in the US without sponsorship?" `a(US)=true, s(US)=true` → No; defaults → Yes · (9) "Are you authorised to work in the US or Canada?" with US false, default true → `unknown`, note `work rights differ`, and no backend call · (10) "Are you authorised to work for us?" → SG, not US · (11) "Are you a Singapore Citizen?" still answered by `residency_status#sg_citizen` · (12) "Do you hold an Employment Pass?" still `work_pass#holds_ep` · (13) `missing_for_apply` no longer lists the two `.SG` paths · (14) `grounding_text` ends with "The applicant has the right to work and needs no visa sponsorship."; `user_prompt` APPLICANT JSON has `work_rights` · (15) loader refuses `country_bool` on another key |
| `tests/test_apply_resolve_memory.py` (`apply_resolve_memory`) | yes_no/choice/multi/text/date/number fits from `extra`; choice needs exactly one pick offered; multi needs all offered ∈ `seen`; `by_employer` beats the base for that employer only (alias too); employer-specific declaration labels never answered from `extra`; a sensitive tier-2 no-fit stop is answered by a matching `extra` entry; two entries with one label → no answer; malformed entry skipped; source/rule_id/sensitive per §6.2; unknown answers carry the tier-2 key in `rule_id` |
| `tests/test_apply_questions.py` (`apply_questions`) | `kind_for` table; reasons and `target_path` per §4.2 (canonical gap, tier-2 gap, no fit, attestation, ungrounded, conflict); FILE/optional/employer-specific not captured; `sig` stable under option order; key rules 1–5 in order; slug rules (stop words, clash suffix); naming with a scripted fake backend: prompt has no profile value and no employer name, a sensitive question makes **no** call, invalid key / unknown `same_as` / kind clash / `BackendError` → slug; store: upsert reopens `answered` but not `dismissed`, sightings unique, `question_groups` waiting counts, `retry_candidates` readiness |
| `tests/test_web_questions.py` (`web_questions`) | GET groups/ready/mode; answer for each kind writes `extra` as §6.1 (labels, picks, seen merged across two variants); profile-gap answer writes the path; employer scope writes `by_employer`; bad option label → 422; stale etag → 409; dismiss → 204; retry only ready ids (422 otherwise), 409 busy, argv has no `--dry-run` |
| `tests/test_apply_flow_questions.py` (`apply_flow_questions`) | with a fake adapter: a schema plan with two required unknowns fails `unanswerable_required` and captures **both** with sightings; dry run captures too; a store exception in capture leaves the outcome unchanged; captured stdout holds no profile value and no `extra` value; after the answer is saved in `extra`, a second run answers at tier 3 (`memory:extra.<key>`) |
| `tests/test_privacy.py` (`privacy`) | `git check-ignore` also passes for `data/applicant.commented-backup.yaml` |
| `tests/test_apply_d70.py` (**blocking the merge of `arch/Q-30-dynamic-fields`**) | `test_contract_version_is_3` → assert `CONTRACT_VERSION >= 3` (v4 is additive) |
| `tests/test_apply_contracts.py` | `test_sample_profile_validates_clean…` keeps passing (the sample's maps have no `default`; absent = standing answer); add: a sample with `default` keys validates clean |
| `web/tests/ApplicationDetails.test.js` | the Missing list from `missing`; required/sensitive tags; meter; inline 422 error; the 409 Reload message; the comments note when `file.has_comments` |
| `web/tests/QuestionsInbox.test.js` | card meta ("Asked by A, B · 2 applications waiting"); one picker per variant; private tag; profile-gap card copy; Save posts the §9.2 shape; retry confirm only in auto mode; empty state |

## 14. Requirement map

| Req | Where |
|---|---|
| F-10 (profile; D-75 defaults) | §3.2, §6.1, §8.1 |
| F-11 (Profile form, validation, missing first) | §3, §9.1, §10 |
| F-12 (answer memory; read from `extra`, M22 corrections write `extra`) | §6, ADR-0005 |
| **F-13 (new, proposed below)** | §4, §5, §7, §9.2, §10 |
| F-32 (tier 2 `country_bool`, tier 3 order, tier 5 `work_rights`) | §6.2, §8.2, §8.1 |
| F-33 (status questions: residency/work pass unchanged) | §8.2 last paragraph |
| F-38 (stopped attempt → answer → retry) | §4.1, §7.1 `retry_candidates`, §9.2 retry |
| F-39 (audit source `memory:extra.<key>`) | §6.2 |
| NF-01, NF-02, NF-03, NF-09 | §11 |
| NF-04 | §2 |

**Proposed PRD text** (planner adds it; I don't write `docs/prd.md`): *F-13 (P1) Questions to answer.* WHEN an attempt stops on a required question that no tier answers THE SYSTEM SHALL record the question with its verbatim label, options, ATS, employer and attempt, group it with equivalent questions, and show it under Profile → Application details → "Questions from applications". WHEN the owner answers it THE SYSTEM SHALL save the answer in `data/applicant.yaml` and use it at resolver tier 3 on every later form that asks it, and SHALL offer to retry the applications that stopped on it. The model MAY name and group questions but SHALL NOT answer them, and SHALL NOT see a sensitive question or any answer. *F-33 addition (D-75):* work authorisation and sponsorship for any country SHALL come from that country's profile value, else the profile default, else "authorised, no sponsorship needed"; the model SHALL always be given that standing answer.

## 15. Build split (WPs in `questions_build_plan.md`, to be pasted into `docs/planning/apply_build_plan.md` §2.5)

Lane **Q** (Python, `eng/M20-Q-questions`): P9 → W1 → Q2 → Q1a → Q3 → (after lane B merges) Q1b. Lane **U** (web, `eng/M20-U-profile-ui`, in the slot lane V frees while it waits on S-5/lane B): W5 → Q4. Researcher: A04. Tester: Q0. Lane B and V files are untouched, except for appended Q-blocks in `store.py`, `apply_flow.py`, `config.py` and `config/config.yaml`, which the Coordinator merges.

## Sources

- Simplify Copilot, saving custom questions (answers stored per exact question wording; unanswered questions listed for the owner): https://help.simplify.jobs/article/18-saving-custom-questions (search result, 2026-11-03).
