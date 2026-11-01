# Auto-apply design (KA-1, KA-2, KA-3)

**Stage B dossier** for PRD F-10–F-12, F-30–F-40, NF-01–NF-09 (`docs/prd.md` r1). Queue Q-04. Author: architect, 2026-11-01.
**Status:** DRAFT for stage E cross-review. Contracts: `src/jobscraper/apply/contracts.py` (CONTRACT_VERSION 1). ADRs: `adr/0001` (browser route), `adr/0002` (vault), `adr/0003` (automatic submission, fail-closed resolution).
**Inputs:** `docs/research/auto_apply_brief.md` §2, §4–§6, §8; spike report `docs/architecture/spikes/S-1_S-3_browser.md` (folded in below, marked **[S-1]** / **[S-3]**).

Decisions D-50…D-63 are not reopened here. Where this design adds something the PRD does not name, it says so in §20.

Reading guide for engineers: §2 (where code goes), §4 (state machine), then the section your work package cites. Every "MUST" is a build rule; nothing below is left for the engineer to choose. Items that depend on a spike not yet run say **pending S-n** and give the default to build now.

---

## 1. Responsibilities and boundaries

**The apply feature does:** take an Inbox role, check it may be applied to (duplicates, caps, profile), make sure a resume file exists (tailor or original), find the employer's ATS, build the list of fields, answer every field from deterministic sources first and the local model last, drive Microsoft Edge to fill and submit, create and sign in to ATS accounts with passwords kept in Windows Credential Manager, read verification mail read-only, detect the confirmation, and record every answer, screenshot and outcome.

**It does not:** solve or wait out a CAPTCHA automatically, evade bot checks, reset passwords, handle SMS/2FA, apply through job boards, write Edge's password database, send or delete mail, invent facts, call a cloud model.

**Boundaries (who owns what):**

| Concern | Owner module | Never in |
|---|---|---|
| SQL | `store.py` | anything else |
| Model calls | `backends.py` | apply/, applicant.py |
| Profile file (load/validate/save) | `applicant.py` (foundation) | web routers (they call it) |
| Passwords (keyring) | `vault.py` (foundation) | SQLite, YAML, logs, prompts |
| Browser | `apply/browser.py` + adapters | web/ |
| Composition | `apply_flow.py` | stages |

---

## 2. Components and module map

### 2.1 Files

```
src/jobscraper/
  applicant.py          FOUNDATION  profile schema, load/save/validate, completeness, LLM extract, grounding text, redaction list
  vault.py              FOUNDATION  keyring wrapper, password generator, Edge CSV export          (§10)
  apply_flow.py         ORCHESTRATOR  queue → guards → tailor → detect → plan → resolve → browser → submit → record
  apply/                STAGE
    __init__.py         engineer creates; exact content: """Auto-apply stage package (docs/architecture/apply_design.md)."""
    contracts.py        architect (done)
    detect.py           pick adapter + Tenant                                                      (§9.0)
    plan.py             FormPlan from schema or DOM step; label normalisation (norm_label)         (§6, §7.1)
    resolve.py          tiers 1–5, option mapping, LLM prompt builder, grounding check             (§7)
    declarations.py     attestation classifier + rules (tier 4) + prior-employment deduction      (§7.5)
    classify.py         page-state classifier: challenge, 2FA, closed, verify-email, errors       (§8.4)
    browser.py          Playwright session, fill primitives, screenshots, HTML dump               (§8)
    mail.py             IMAP fetcher (read-only)                                                  (§11)
    ats/__init__.py     REGISTRY = {name: adapter instance}
    ats/greenhouse.py   (M20)  ats/lever.py  ats/ashby.py  ats/workday.py   (M21)
  web/routers/applicant.py, web/routers/apply.py   (M21)
config/
  questions.yaml        researcher-owned data (format §7.3)
  applicant.example.yaml  public template (§5.4)
data/ (gitignored)      applicant.yaml · apply/<attempt_id>/ · edge_passwords_<stamp>.csv
```

`vault.py` sits in the foundation, not in `apply/` as PRD §7.2's sketch shows, because the web app needs it directly (Copy password, set the IMAP password, Edge export) and web/ may not import a stage. This is a placement change, not a requirement change (§20).

### 2.2 Dependency graph

```
cli.py ──► apply_flow.py ──► tailor_flow.py (only for tailor_for_apply)
              │
              ├──► apply/{detect, plan, resolve, declarations, classify, browser, mail, ats/*}
              │        (apply/ imports only: apply.contracts, foundation, stdlib, playwright, imaplib)
              └──► store, config, net, backends, applicant, vault, models
web/routers/{applicant, apply}.py ──► store, config, applicant, vault, apply.contracts (only)
```

### 2.3 Layering test changes (tester, `tests/test_layering.py`)

1. `STAGES += {"apply", "tailor"}`; `ORCHESTRATOR += {"apply_flow", "tailor_flow"}`; `FOUNDATION += {"applicant", "vault"}`.
2. One allowed orchestrator→orchestrator edge: `apply_flow` may import `tailor_flow`. `test_nothing_imports_the_orchestrator` exempts exactly that pair.
3. web/ may import `jobscraper.apply.contracts` and `jobscraper.tailor.contracts` and nothing else from those packages. `_local_imports` must report dotted names for these two (e.g. `apply.contracts`) so the check can allow them precisely.
4. Stage `apply` may import `apply.contracts`; it may not import `tailor` (and vice versa).
5. The existing SQL-token and `/api/chat` checks apply to all new files unchanged (the contracts avoid the bare token, see `FieldType.DROPDOWN`).

---

## 3. End-to-end flow

```
web "Auto-apply" ──POST /api/apply──► preflight (store + applicant) ──► JobManager.start("apply", job_ids)
                                                                         │ child process
python -m jobscraper apply <job_id>... [--dry-run]                       ▼
apply_flow.run():
  reap stale attempts (§4.3) ─► for each job_id, in order:
    create attempt (queued) ─► guards: duplicate · caps · profile (§12) ─► fail early or continue
    tailoring: tailor_flow.tailor_for_apply()  (no current file) ─► resume path (tailored PDF/DOCX or original)
    planning: detect adapter + tenant ─► build ResolveContext (resume text + alias groups, §7.7) ─► plan_from_schema (Greenhouse) ─► resolve all ─► fail before the browser if a required field is unknown
    opening: browser session (one per job run) ─► new tab ─► adapter.open ─► classify page
    [signing_in | signing_up ─► verifying_email]           (Workday; §10, §11)
    filling (per step): read_step ─► resolve (DOM adapters) ─► fill ─► read back ─► screenshot ─► classify ─► next_step
    review page reached:
       dry_run ─► ready_to_submit (tab stays open)
       auto    ─► record submit_clicked_at ─► submitting ─► submit ─► wait ≤ 60 s for confirmation
                    ─► submitted (Applications: applied, tailored file: sent) | submitted_unconfirmed
    any ApplyFailure ─► stop input, screenshot + HTML, failed(reason)
  after the last job: if any tab is ready_to_submit, hold the browser for apply.dry_run_hold_s, then close
```

`apply_flow.run(cfg, store, job_ids: list[str], *, dry_run: bool, backend) -> list[AttemptResult]` is the orchestrator's only public function; `cmd_apply` calls it and exits 0 if every attempt ended `submitted` or `ready_to_submit`, else 1.

---

## 4. Attempt state machine

### 4.1 States and transitions

States and the allowed automatic transitions are `AttemptState` and `TRANSITIONS` in the contracts. Every non-terminal state may go to `failed`. The store method `set_attempt_state` MUST refuse a transition not in `TRANSITIONS` (raise `ValueError`); this is the guard against a coding error re-entering `submitting`.

| From | To | Trigger |
|---|---|---|
| (new) | queued | `apply_flow` creates the row for a job id |
| queued | tailoring | guards passed and no current tailored file for the job (tailor design §11.2) |
| queued | planning | guards passed and a current tailored file exists, or `tailor.enabled: false` |
| tailoring | planning | tailor returned (success → tailored file; failure → original resume, `resume_source='original'`, note logged) |
| planning | opening | adapter found; schema plan (if any) fully resolved with no required field `unknown`/`ungrounded` |
| opening | signing_in | `account_wall()` = `sign_in`, or the ATS needs an account and the vault has one |
| opening | signing_up | the ATS needs an account and the vault has none |
| opening | filling | the form is visible (no account wall) |
| signing_up | verifying_email | `sign_up()` returned `verify_email` |
| signing_up | signing_in | `sign_up()` returned `sign_in` (site sends you to sign in) |
| signing_up | filling | `sign_up()` returned `signed_in` |
| signing_in | verifying_email | after sign-in the site asks to verify the email (classify `verify_email`) |
| signing_in | filling | signed in, form visible |
| verifying_email | signing_in | link opened; the site now shows sign-in |
| verifying_email | filling | link opened or code entered; form visible |
| verifying_email | submitting | emailed security code entered after Submit (§4.2) |
| filling | filling | `next_step()` moved to another step (step id changes; `step` column updated) |
| filling | ready_to_submit | review page reached and `mode = dry_run` |
| filling | submitting | review page reached and `mode = auto`; `submit_clicked_at` written and committed **before** the click |
| submitting | submitted | `after_submit()` → `confirmed:<signal>` within `confirm_timeout_s` (60) |
| submitting | submitted_unconfirmed | no confirmation within 60 s, or any exception after the click |
| submitting | verifying_email | `after_submit()` → `code_required` (Greenhouse security code) |
| any non-terminal | failed(reason) | `ApplyFailure`, any other exception (`error`), deadline passed (`error`, detail "timed out"), cancel (`cancelled`) |

Rule NF-06: once `submit_clicked_at` is set, the attempt can only end `submitted` or `submitted_unconfirmed` — never `failed`, never another automatic Submit (except the single code re-submit in §4.2). `apply_flow` enforces this by catching every exception after the click and mapping it to `submitted_unconfirmed`.

### 4.2 The emailed security code at Submit (Greenhouse)

Greenhouse may answer Submit with "enter the security code we emailed you" when reCAPTCHA is unsure (brief §2.1). Then: `submitting → verifying_email` (mail §11, adapter `otp_pattern`) → `enter_code()` → `verifying_email → submitting` → `submit()` once more → wait for confirmation as before. This second click completes the same submission and is allowed once per attempt (`apply_attempts.code_resubmits` ≤ 1). With no mail set up: `submitted_unconfirmed` (Submit was already clicked), detail `security code needed; mailbox not set up`.

### 4.3 Owner actions and the reaper

| Action (web, M21) | Store effect |
|---|---|
| "It went through" on `submitted_unconfirmed` | state → `submitted`, `confirmation='owner'`; Applications → `applied` (event by `jobscraper`); tailored file → `sent` |
| "It didn't go through" on `submitted_unconfirmed` | state → `failed`, reason `error`, detail `owner: not submitted`; this frees the posting for a new attempt |
| Cancel the running apply job | JobManager kills the tree; the reaper below closes the row |

**Reaper** (`store.reap_attempts(now, job_running: bool)`), run at the start of `apply_flow.run` and by `GET /api/apply/attempts` when no `apply` job is running: every attempt in a non-terminal state becomes `submitted_unconfirmed` if `submit_clicked_at` is set, else `failed(cancelled)` (detail `interrupted`). Never resubmits.

### 4.4 Reason codes

Owner-facing copy lives in `REASON_TEXTS` (contracts) and is written in one voice: what happened, whether anything was sent, what to do. `{detail}` never holds a personal value.

| Code | Trigger (exact) | Owner text (summary) | Recovery hint |
|---|---|---|---|
| `captcha` | `classify` sees a visible challenge widget (§8.4) at any point, including after Submit before a confirmation | CAPTCHA, stopped, nothing sent | Apply by hand. If `captcha_wait_s` > 0 the tab stays open that long and a confirmation seen meanwhile turns it into `submitted` |
| `bot_challenge` | Cloudflare/Akamai/PerimeterX interstitial or block page (§8.4), or HTTP 403/429 on the apply page | bot check blocked | Apply by hand |
| `sms_or_2fa` | classify `two_factor` (phone/SMS/authenticator prompt) | phone or two-step code | Apply by hand |
| `login_failed` | sign-in error shown; or sign-up says the email already has an account and the vault has no entry (detail: "An account exists for your email but JobScraper has no password for it.") | can't sign in | Check by hand; add the password in Settings → Accounts → "Add an existing account" |
| `email_verification_timeout` | no matching mail within `mail.wait_s` (300) | no email in 5 min | Click the link by hand, retry |
| `mail_not_set_up` | verification needed before Submit and IMAP host/user/password not configured | mailbox not set up | Settings → Apply → Mailbox |
| `unanswerable_required` | a required field ends `unknown`, `ungrounded`, or an attestation the classifier can't label; detail = verbatim label (first 120 chars) | no backed-up answer to "…" | Add it to Application details, or apply by hand |
| `validation_error` | visible field errors after one re-fill retry, or `fill_failed` on a required field; detail = up to 3 field labels | site rejected the form | Open the posting; fix profile data if it's yours |
| `page_unrecognised` | `open`/`read_step` finds none of the adapter's expected markers, or an unknown wizard step; detail = ATS + step | page not a known form | Apply by hand; see screenshot |
| `posting_closed` | schema 404/410; apply page 404/410; closed-posting text (§8.4) | posting closed | Nothing to do |
| `unsupported_ats` | `detect` finds no adapter | can't apply here yet | Apply by hand |
| `cap_reached` | daily or per-employer cap hit (§12); detail e.g. "10 of 10 today" | limit reached | Tomorrow, or Settings → Apply |
| `duplicate` | §12 duplicate rules; detail e.g. "applied 2026-10-30" / "same posting as <company> · <role>" | already applied | See Applications |
| `profile_incomplete` | `applicant.missing_for_apply()` non-empty, or no resume file at all; detail = field names, comma-separated | details missing | Profile → Application details |
| `cancelled` | owner cancel, or the reaper closing an interrupted attempt before Submit | cancelled | Start again |
| `error` | any other exception before Submit; deadline exceeded; Ollama needed for a required field but unavailable is **not** this (it is `unanswerable_required`, detail "<label> (model unavailable)") | unexpected, stopped before sending | Retry; Developer tab log |

Non-failure terminal copy: `STATE_TEXTS` for `submitted_unconfirmed` and `ready_to_submit`.

---

## 5. Applicant profile (F-10, F-11)

### 5.1 File and module

`data/applicant.yaml` (gitignored by `data/applicant*.yaml`). `applicant.py` (foundation) owns it:

```python
APPLICANT_PATH_DEFAULT = "data/applicant.yaml"          # config paths.applicant overrides
SCHEMA_VERSION = 1

@dataclass(frozen=True)
class FieldError:
    path: str          # dotted, list index in brackets: "education[0].end"
    message: str       # plain English, names the rule

def load(path) -> dict                 # {} if absent; raises ApplicantError on unreadable YAML
def save(path, profile: dict) -> None  # validate first; atomic (tempfile + os.replace); yaml.safe_dump(sort_keys=False, allow_unicode=True)
def validate(profile) -> list[FieldError]
def missing_for_apply(profile) -> list[str]        # REQUIRED_PATHS that are empty, as dotted paths
def completeness(profile) -> tuple[int, int]       # (filled, needed) over REQUIRED_PATHS + RECOMMENDED_PATHS
def llm_extract(profile) -> dict                   # non-sensitive allow-list only (§5.3)
def grounding_text(profile) -> str                 # flattened non-sensitive values + computed facts (§7.7)
def redaction_values(profile) -> list[str]         # every string value ≥ 3 chars + digits-only phone/postal, for log scrubbing
def computed_facts(profile, today) -> dict         # {"experience_months": int, "experience_years": int, "graduation_year": int|None}
def from_resume(profile_derived: dict, master: dict|None) -> dict   # M21 prefill (§5.5)
```

**`computed_facts` (D-68 A-4).** `experience_months` = the length of the **union** of the intervals of every `experience[]` entry (internships included; `education[]` never counts), whole months rounded down:
- Month position of a date: `YYYY-MM` → `12·Y + (M−1)` (start of that month); `YYYY-MM-DD` → `12·Y + (M−1) + (D−1)/days_in_month`.
- Interval of an entry = `[pos(start), pos_end)`, where `pos_end` = `pos(end) + 1` for a `YYYY-MM` end (the end month counts in full), `pos(end) + 1/days_in_month` for a `YYYY-MM-DD` end (the end day counts), and `pos(today) + 1/days_in_month(today)` when `end` is null (present); every `pos_end` is clipped to that "today" value. An entry with no `start`, or with `start` after today, contributes nothing.
- Overlapping or touching intervals are merged; `experience_months = floor(Σ merged lengths)`; `experience_years = experience_months // 12`. Example: 2024-05 → 2024-08 plus 2024-07 → 2024-12 = one interval 2024-05 → 2024-12 = 8 months.
- `graduation_year` = the year of the latest `education[].end`, else None.

Saving drops YAML comments; the Profile form is the editor (the template's comments exist for the first hand-fill in M20).

### 5.2 Validation rules (F-11)

| Path | Rule (message names it) |
|---|---|
| `contact.email` | `^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$` |
| `contact.postal_code` | when `contact.country == "SG"`: exactly 6 digits |
| `contact.phone_country_code` | `^\+\d{1,3}$` |
| `contact.phone_number` | digits and spaces only; for `+65`: 8 digits starting 3, 6, 8 or 9 |
| `pay.expected_salary.amount` | positive integer |
| `pay.expected_salary.currency` | 3 uppercase letters |
| `pay.expected_salary.period` | `monthly` \| `annual` |
| `pay.months_per_year` | integer 12–14 |
| every date | `YYYY-MM-DD` or `YYYY-MM` (as declared per field below); `start` ≤ `end` |
| enums | exactly the listed values |
| `links.*`, `links.other[]` | `http://` or `https://` URL |
| `availability.notice_period_days` | integer ≥ 0 |
| `availability.willing_to_travel_pct` | integer 0–100 |
| `singapore_status.nric_last4` | empty or `^\d{3}[A-Z]$` (never a full NRIC: any 9-char NRIC-shaped string anywhere in the file is an error) |
| `education[]`, `experience[]` | `institution`/`employer` and `title`/`degree` non-empty |

**REQUIRED_PATHS** (auto-apply refuses without them, F-11): `identity.legal_first_name`, `identity.legal_last_name`, `contact.email`, `contact.phone_country_code`, `contact.phone_number`, `contact.city`, `contact.country`, `singapore_status.residency_status`, `singapore_status.authorised_to_work.SG`, `singapore_status.requires_sponsorship.SG`, `availability.notice_period_days`, `availability.earliest_start_date`, `pay.expected_salary.amount`, `education` (≥ 1 entry with institution, degree, end), `consents.privacy_consent`, `consents.certify_true`. Plus a resume file (`documents.resume` or `profile.resume_ingest.find_resume`) — reported as `documents.resume`.

**RECOMMENDED_PATHS** (meter only): `contact.address_line1`, `contact.postal_code`, `singapore_status.ns_status`, `singapore_status.race`, `links.linkedin`, `experience`, `skills`, `languages`, `sourcing.how_heard_default`, `identity.date_of_birth`.

### 5.3 Sensitive fields (S)

S paths: `identity.date_of_birth`, `identity.gender`, `singapore_status.residency_status`, `singapore_status.ns_status`, `singapore_status.ord_date`, `singapore_status.race`, `singapore_status.race_other`, `singapore_status.religion`, `singapore_status.marital_status`, `singapore_status.nric_last4`, `us_self_id.*`, `declarations.*`, `contact.*` except `city`/`country`.

S values are never in an LLM prompt (`llm_extract` excludes them), never in a log line (redaction), and answers that use them carry `sensitive=True` (shown first in the audit view). They are stored in `apply_answers.value` (local DB; NF-02 covers passwords only).

`llm_extract` allow-list: `education[]`, `experience[]` (all keys), `skills`, `attested_skills`, `languages`, `links`, `availability.*`, `pay.expected_salary`, `sourcing.how_heard_default`, `contact.city`, `contact.country`, `singapore_status.work_pass`, `singapore_status.authorised_to_work`, `singapore_status.requires_sponsorship`.

### 5.4 Template: `config/applicant.example.yaml` (public; placeholders only)

The engineer creates this file verbatim (scope request §20, R-1). The owner copies it to `data/applicant.yaml` (Q-13).

```yaml
# JobScraper applicant profile: TEMPLATE. Copy to data/applicant.yaml and fill it in.
# data/applicant.yaml is gitignored. Never put real values in THIS file (the repo is public).
# S = sensitive: never sent to the AI model, never written to logs.
# "decline" means "prefer not to say" wherever a form offers it.
version: 1

identity:
  legal_first_name: "Firstname"
  legal_last_name: "Lastname"
  preferred_name: ""                 # optional
  name_order: western                # western | surname_first
  pronouns: ""
  date_of_birth: null                # S. YYYY-MM-DD. Left empty, a form that requires it fails with a reason
  gender: decline                    # S. male | female | non_binary | decline

contact:
  email: "applicant@example.com"     # the one address used for every application and account
  phone_country_code: "+65"
  phone_number: "90000000"
  address_line1: "1 Example Road"
  address_line2: ""
  postal_code: "000000"              # 6 digits in Singapore
  city: "Singapore"
  country: SG                        # ISO 3166-1 alpha-2

singapore_status:
  nationality: SG                    # ISO country code
  residency_status: citizen          # S. citizen | pr | foreigner
  work_pass: none_required           # none_required | ep | s_pass | dp | ltvp_loc | student_pass | other
  authorised_to_work: {SG: true}     # add other countries a form may ask about, e.g. US: false
  requires_sponsorship: {SG: false}
  ns_status: not_applicable          # S. completed | serving | exempted | not_applicable
  ord_date: null                     # S. YYYY-MM, when ns_status is completed or serving
  race: decline                      # S. chinese | malay | indian | eurasian | other | decline
  race_other: ""                     # S
  religion: decline                  # S. free text or decline
  marital_status: decline            # S. single | married | decline
  nric_last4: ""                     # S. optional, e.g. "123A". NEVER the full NRIC

us_self_id:                          # S. US equal-employment questions on global forms
  eeo_gender: decline                # male | female | non_binary | decline
  eeo_race_ethnicity: decline        # asian | black | hispanic_latino | white | two_or_more | native_american | pacific_islander | decline
  veteran_status: decline            # not_a_veteran | veteran | decline
  disability_status: decline         # no | yes | decline

availability:
  notice_period_days: 0
  earliest_start_date: "2026-01-05"  # YYYY-MM-DD
  willing_to_relocate: false
  willing_to_travel_pct: 0

pay:
  expected_salary: {amount: 0, currency: SGD, period: monthly, negotiable: true}
  current_salary: null               # or {amount: 0, currency: SGD, period: monthly}
  months_per_year: 12                # 13 if you count the AWS bonus when converting to annual

education:                           # newest first. from_resume: true = filled from your resume, please check
  - institution: "Example University"
    degree: "Bachelor of Engineering"
    major: "Computer Engineering"
    minor: ""
    start: "2021-08"                 # YYYY-MM
    end: "2025-06"                   # YYYY-MM (expected date if still studying)
    grade_type: cap                  # gpa | cap | honours_class
    grade: "4.00"
    grade_scale: "5.00"
    from_resume: false

experience:                          # internships count: prior employment is deduced from this list
  - employer: "Example Pte Ltd"
    title: "Software Engineering Intern"
    start: "2024-05"
    end: "2024-08"                   # null = present
    location: "Singapore"
    description: "One or two lines, copied from your resume."
    from_resume: false

skills: ["Python", "SQL"]
attested_skills: []                  # skills you confirmed with "I have this" in the resume tailor
languages:
  - {language: English, spoken: native, written: native}   # native | fluent | professional | basic

links:
  linkedin: ""
  github: ""
  portfolio: ""
  other: []

documents:
  resume: ""                         # empty = data/resume.pdf or data/resume.docx
  transcript: ""

sourcing:
  how_heard_default: "Company careers website"

consents:
  privacy_consent: true              # consent to the employer processing your application data
  data_retention_consent: true       # consent to keep your data for future roles
  talent_pool_opt_in: false
  certify_true: true                 # "I certify the information I gave is true and complete"

declarations:                        # D-55 standing answers. S. Change any that stop being true.
  pep: false                         # politically exposed person (self, family, close associate)
  conflict_audit_independence: false
  shareholding_in_company: false
  holdings: []                       # names of companies you hold shares in; a match with the employer answers Yes
  relatives_at_company: false
  relatives_employers: []            # employers where a relative works; a match answers Yes
  criminal_record: false
  bankruptcy: false
  regulatory_disciplinary: false
  non_compete: false
  health_disclosure: decline         # decline only; a required health question fails the attempt
```

### 5.5 Pre-fill from the resume (M21, F-10 bullet 2)

`python -m jobscraper applicant init` (CLI; refuses if the file exists) writes the template with: `skills` from `profile.derived.yaml` merged skills; `education[]`/`experience[]` from the master resume (tailor design: entries with `kind` education/experience; employer, title, dates, institution, degree copied verbatim), each with `from_resume: true`; `links` from the master's contact block. The Profile form shows a "From resume, check" chip on every entry with `from_resume: true`; saving an entry from the form sets it `false`. In M20 the owner hand-fills from the template (no init needed).

---

## 6. Forms and plans

- A **FormPlan** (contracts) holds the fields. Schema adapters (Greenhouse) return the whole plan from `plan_from_schema`; DOM adapters return `None` and the flow builds the plan one step at a time from `read_step`.
- **Field keys:** Greenhouse = schema field `name`; Lever = input `name` (custom cards: `cards[<uuid>][field<N>]`); Ashby = input `id` (`_systemfield_*` or the field UUID); Workday = `<automation-id>` or `<automation-id>#<n>` for repeated groups, prefixed by step id for questionnaire items (`primaryQuestionnaire:<n>`).
- **Required:** the schema's `required`; on DOM forms, a label ending `*`, `aria-required="true"`, or a `required` attribute.
- **Hidden** fields are recorded (status `skipped`) and never filled. An alternative input (`alt_of`, e.g. Greenhouse `resume_text` beside `resume`) is skipped when its primary is answered.
- **Resolution timing:** schema plans are resolved in full in `planning`; a required `unknown` fails the attempt before Edge opens. DOM steps are resolved in full before the first keystroke on that step.

---

## 7. Answer resolution (KA-2, F-32, F-33)

`resolve.resolve_all(fields, ctx: ResolveContext, *, backend, rules: QuestionRules, memory: MemoryLookup) -> dict[str, Answer]` resolves each field independently with the tiers below, in order, first answer wins. `MemoryLookup = Callable[[str, str, str], Optional[str]]` (label_norm, field_type, ats → stored value JSON) is `store.answer_memory_get` bound by `apply_flow`.

A tier "answers" only when it produces a value that is valid for the field: for choice fields, one of the offered options (mapped by §7.3.2); for text, a non-empty string within `max_length`. If a tier has a value but it maps to no offered option, that tier does not answer and the next tier is tried — except tiers 2 and 4 on **sensitive** or **attestation** fields, which stop resolution with `unknown` (no LLM guess on a fact the profile owns).

After the tiers: required + no answer → `unknown` (attempt fails, §4.4); optional + no answer → `blank_optional`.

### 7.1 Label normalisation (`plan.norm_label`)

```
1  text = html_to_text(label) (strip tags), unicodedata NFKC, lowercase
2  replace ’ ‘ with '
3  delete "(required)", "(optional)", "*"
4  replace every run of chars not in [a-z0-9+#'] with one space; then delete "'" 
5  drop a leading list number ("1 ", "12 ")
6  collapse spaces, strip
```
A **phrase match** of phrase P in label L: `norm_label(P)` split into tokens occurs as a contiguous token run in `norm_label(L)`. A one-token phrase matches only if L has ≤ 4 tokens (so "email" does not match "may we email you about other roles").

### 7.2 Tier 1: field map (confidence 1.0)

Adapters tag fields with a `Canonical`. The resolver maps them:

| Canonical | Value |
|---|---|
| FIRST_NAME / LAST_NAME | `identity.legal_first_name` / `legal_last_name` |
| FULL_NAME | first + " " + last (`surname_first`: last + " " + first) |
| PREFERRED_NAME | `identity.preferred_name` or blank |
| EMAIL | `contact.email` |
| PHONE | `contact.phone_number` (digits only); the adapter fills the country part |
| PHONE_COUNTRY_CODE | `contact.phone_country_code` → option whose label contains it (e.g. "Singapore +65") |
| PHONE_DEVICE_TYPE | option "Mobile" |
| ADDRESS_LINE1/2, CITY, POSTAL_CODE | `contact.*` |
| COUNTRY | option whose label equals the country name for `contact.country` (fixed ISO→name table in resolve.py; SG → "Singapore") |
| LOCATION | `contact.city` (typeahead: first suggestion whose label starts with it) |
| CURRENT_COMPANY | employer of the `experience[]` entry with `end: null`, else blank |
| LINKEDIN / GITHUB / PORTFOLIO / WEBSITE | `links.*` (WEBSITE = portfolio, else github) |
| RESUME | `ctx.resume_path` |
| COVER_LETTER | optional → `blank_optional`; required → tier 5 free text (§7.6) saved to `data/apply/<id>/cover_letter.txt` and uploaded |
| EEO_* | `us_self_id.*` → option via §7.3.2 (decline set when `decline`) |
| CONSENT_PRIVACY / RETENTION / TALENT_POOL | `consents.*` (checkbox true/false; Greenhouse GDPR fields) |
| TERMS_AGREEMENT | `consents.privacy_consent` |
| SELF_ID_NAME / SELF_ID_DATE | full name / today (Asia/Singapore) |
| HOW_HEARD | `sourcing.how_heard_default` → option by §7.3.2; no option matches → the option containing "career" or "website", else `unknown` |
| PREVIOUS_WORKER | `declarations.prior_employment()` (§7.5) |

`source = "field_map:<canonical>"`, `rule_id = canonical`.

### 7.3 Tier 2: profile rules (confidence 0.95)

#### 7.3.1 `config/questions.yaml` format (researcher fills the content)

```yaml
version: 1
questions:
  - key: singapore_status.requires_sponsorship.SG   # a profile path, or computed.<name> (§5.1 computed_facts)
    kind: bool             # bool | enum | text | number | salary | date | url | country
    sensitive: false       # true for S paths: a miss stops at `unknown`, never tier 5
    synonyms:              # phrases; matched by §7.1 phrase match
      - require sponsorship
      - need sponsorship
      - visa sponsorship
      - require an employment pass
    exclude: [united states, u s]   # optional phrases; a label containing any is not this key
    value_map:             # enum only: profile value -> option-label phrases
      citizen: [singapore citizen, citizen]
```

Selection: for each entry, score = token count of its longest matching synonym, 0 if any `exclude` phrase matches. The highest score wins; a tie between different keys → tier 2 does not answer (note `ambiguous: k1, k2`).

**Minimum content** the researcher MUST provide (keys and kinds; synonyms are theirs): `singapore_status.authorised_to_work.SG` (bool), `singapore_status.requires_sponsorship.SG` (bool), `singapore_status.residency_status` (enum, S; value_map for citizen/pr/foreigner incl. "Singapore Citizen or PR" style options), `singapore_status.nationality` (country), `singapore_status.work_pass` (enum), `singapore_status.ns_status` (enum, S), `singapore_status.race` (enum, S), `identity.gender` (enum, S), `identity.date_of_birth` (date, S), `availability.notice_period_days` (number), `availability.earliest_start_date` (date), `availability.willing_to_relocate` (bool), `availability.willing_to_travel_pct` (number), `pay.expected_salary` (salary), `pay.current_salary` (salary), `education[0].institution` / `.degree` / `.major` / `.end` / `.grade` (text/date), `computed.experience_years` (number), `computed.graduation_year` (number), `links.linkedin` / `links.github` / `links.portfolio` (url), `sourcing.how_heard_default` (text), `consents.certify_true` (bool; "information provided is true", "accurate and complete"), `consents.privacy_consent` (bool), `languages` (text: "English (native), …"), `identity.preferred_name` (text).

#### 7.3.2 Mapping a profile value onto offered options

Normalise every option label with §7.1.

- **bool:** yes-labels = label equals or starts with one of `yes`, `y`, `true`, `i am`, `i do`, `i have`, `i will`, `i can`, `authorised`, `authorized`; no-labels = equals or starts with `no`, `n`, `false`, `i am not`, `i do not`, `i don t`, `i have not`, `i will not`, `not`. No-prefixes are tested first (so "i am not" never counts as yes). Exactly one option of the right polarity → answer; else no answer. Text inputs get "Yes"/"No". Single checkbox: tick for true.
- **enum:** candidates = options whose label equals a `value_map` phrase, else whose label contains one as a phrase; then the enum value itself with `_`→space. Exactly one candidate → answer.
- **decline values:** an option whose label contains any of: `decline`, `prefer not`, `not wish`, `don t wish`, `do not wish`, `rather not`, `not to disclose`, `not to answer`, `not to say`, `i don t want to answer`. None offered and the field is required → `unknown`; optional → `blank_optional`.
- **number:** text inputs get the integer. Range options (`"0-1 years"`, `"S$3,000 - S$4,000"`, `"Below 3000"`, `"5000 and above"`, `"3k–4k"`): parse with `(\d[\d,]*(?:\.\d+)?)\s*(k)?` pairs; `below|under|less than` → (−∞, x); `above|over|more than|and above|\+` → (x, ∞). Pick the unique range containing the value (inclusive).
- **salary:** period from the label: `annual|annum|yearly|per year|p a` → annual; `month|monthly|per month` → monthly; else the profile's period. annual = monthly × `pay.months_per_year`. A currency named in the label or options that is not the profile's currency → no answer. Text input value: digits only (e.g. `5000`). `current_salary: null` → text "0" if the label says "current" and the field is required, else blank.
- **date:** ISO from the profile; the adapter formats it.
- **country:** ISO → name table; option equal to the name or containing it.
- **url / text:** the value as is; truncated never — over `max_length` → no answer.

### 7.4 Tier 3: answer memory (confidence 0.95; F-12, M22 writes, M20 reads)

Lookup `(label_norm, field_type, ats)` then `(label_norm, field_type, '*')`. The stored value is JSON: a string, a list (multi), or for choice fields the option label(s); a choice value applies only if an offered option has the same normalised label. `source = "memory:<label_norm>"`. In M20/M21 the table is empty until M22's correction UI writes it; the lookup is built in M20 so the tier order is fixed from the start.

### 7.5 Tier 4: declarations (`declarations.py`, F-33; confidence 0.95)

**Classifier** `classify(label_norm, description_norm) -> DeclarationLabel | AMBIGUOUS | None`: a label matches a class when any of its phrases phrase-matches label + " " + description. Exactly one class → that class; two or more → `AMBIGUOUS`; none → `None`, unless the label contains an **attestation marker** (`declare`, `declaration`, `attest`, `politically`, `convicted`, `bankrupt`, `conflict`, `disciplinary`, `charged`) → `AMBIGUOUS`.

| Label | Phrases |
|---|---|
| `pep` | politically exposed, pep, prominent public function, public office, senior government official, senior political |
| `conflict_audit_independence` | audit client, independence, conflict of interest, conflicts of interest |
| `shareholding_in_company` | shares in, shareholding, shareholder, financial interest, equity interest, own securities, stock in |
| `relatives_at_company` | relative, relatives, related to, family member, family members, friends or family, know anyone who works, close personal relationship |
| `criminal_record` | convicted, criminal, offence, offense, pending charges, court proceedings |
| `bankruptcy` | bankrupt, bankruptcy, insolvency, insolvent, judgment debt |
| `regulatory_disciplinary` | regulatory, disciplinary, mas, licence revoked, license revoked, suspended, censured, investigated by |
| `non_compete` | non compete, restrictive covenant, non solicitation, bound by any agreement, restraint of trade |
| `health` | medical condition, health condition, mental health, medical history, illness |
| `prior_employment_at_company` | previously worked, previously employed, previously been employed, worked for us, worked for, employed by, former employee, ex employee, have you worked, currently or previously employed |
| `previously_applied` | previously applied, applied before, have you applied, applied to this, applied for a position |

**Rules:**

- `AMBIGUOUS` → required: `unknown` (detail = label); optional: `blank_optional`. Never tier 5.
- `pep`, `conflict_audit_independence`, `criminal_record`, `bankruptcy`, `regulatory_disciplinary`, `non_compete`: the bool in `declarations.<label>` (default false).
- `shareholding_in_company`: true if `declarations.shareholding_in_company` or `company_match(employer, h)` for any `h` in `holdings`.
- `relatives_at_company`: true if `declarations.relatives_at_company` or any `relatives_employers` entry company-matches.
- `prior_employment_at_company`: true if any `experience[].employer` company-matches the employer or one of `ctx.employer_aliases` (internships count).
- `previously_applied`: `ctx.previously_applied` (computed by apply_flow, §12.3).
- `health`: optional → `blank_optional`; required → decline option if offered, else `unknown`.
- **Company match** `company_match(a, b)`: normalise both: §7.1, then drop tokens `pte`, `ltd`, `limited`, `inc`, `llc`, `corp`, `corporation`, `co`, `plc`, `group`, `holdings`, `the`, `singapore`, `sg`, `bank` (only when other tokens remain); match if equal or one token list is a prefix of the other. ("DBS Bank Ltd" ~ "DBS"; "Grab" ~ "Grab Financial Group" → match: on a declaration, a truthful Yes beats a wrong No.)
- **Value onto the field:** bool → §7.3.2 bool mapping. **Single checkbox** declarations: a label with a negation (`not`, `never`, `no`, `none of`, `neither`) is a "tick = I am clear" box: tick when the declaration is false; otherwise ("I am a PEP"): tick when true. If the checkbox is required and the rule says "don't tick" → `unknown` (we will not tick a false statement to pass validation).
- `source = "declaration:<label>"`, `rule_id = <label>`, `sensitive = True`.

Status questions (work authorisation, sponsorship, citizenship/PR, race, NS, US self-ID) are tier 1 (canonical EEO fields) or tier 2 (questions.yaml, `sensitive: true`); "decline" profile values map to the decline option set.

### 7.6 Tier 5: local LLM (F-32 bullets 1–3)

**Eligible fields:** not hidden, not FILE (except a required cover letter), not sensitive (no tier-2 sensitive key matched), not an attestation (classifier `None`). Others end `unknown`/`blank_optional` at tier 4.

**Backend change (engineer, `backends.py`):** `Backend.complete(system, user, max_tokens=4096, *, format=None, temperature=None, seed=None, top_k=None)`. `format=None` sends `"json"` (unchanged behaviour); a dict is sent as the JSON schema. `temperature=None` sends 0; `seed`/`top_k` are added to `options` only when given. `OffBackend` unchanged. Existing callers are untouched.

**System prompt** (constant `resolve.SYSTEM_PROMPT`):
```
You answer one question on a job application for the applicant described below.
Rules:
1. Use only facts in APPLICANT, RESUME or JOB. Never invent an employer, title, date, degree,
   number, skill or tool.
2. If the facts do not settle the answer, answer unknown (choice -1, or unknown true).
3. For a choice question, pick the option the facts support, and copy into "evidence" a short
   exact quote (3-200 characters) from APPLICANT, RESUME or JOB that supports it.
4. For free text, write plain first-person sentences, no greeting or sign-off, within the
   character limit. Mention only skills and experience present in APPLICANT or RESUME.
Return JSON only, matching the schema.
```
**User prompt:** `QUESTION: <label>\nHELP: <description>\nTYPE: <choice|multi|text|number>\nREQUIRED: yes|no\nLIMIT: <n> characters\nOPTIONS:\n0. <label>\n1. <label>…\n\nAPPLICANT (JSON):\n<llm_extract + computed_facts>\n\nRESUME:\n<ctx.resume_text, first 6000 chars>\n\nJOB: <company> — <title>\n<jd_text, first 6000 chars>`.

**Schemas (`format`):**
- choice: `{"type":"object","properties":{"choice":{"type":"integer","minimum":-1,"maximum":N-1},"evidence":{"type":"string","maxLength":200}},"required":["choice","evidence"]}`
- multi: `{"type":"object","properties":{"choices":{"type":"array","items":{"type":"integer","minimum":0,"maximum":N-1},"uniqueItems":true,"maxItems":N},"unknown":{"type":"boolean"},"evidence":{"type":"string","maxLength":200}},"required":["choices","unknown","evidence"]}`
- text: `{"type":"object","properties":{"unknown":{"type":"boolean"},"text":{"type":"string","maxLength":L}},"required":["unknown","text"]}` with L = `max_length` or 255 (TEXT) / 1500 (TEXTAREA) / 2500 (cover letter)
- number: `{"type":"object","properties":{"unknown":{"type":"boolean"},"value":{"type":"number"}},"required":["unknown","value"]}`

**Calls:** choice/multi/number: two calls, `temperature=0, seed=7` and `temperature=0.7, seed=7`; answered only if both agree (same index set / value) and both pass grounding; confidence 0.9. Text: one call, `temperature=0.3, seed=7`; one retry if grounding fails, with the user prompt extended by `PREVIOUS ANSWER WAS REJECTED BECAUSE: <violations>`; confidence 0.8. `max_tokens`: 200 (choice/number), L/2+100 (text). `BackendError` → no answer, note `model unavailable`.

**Recorded:** `model = backend.model_id`, `prompt_hash = sha256(system + "\n\n" + user)[:16]`, `source = "llm"`, `rule_id = "llm:v1"`.

### 7.7 Grounding check (`resolve.grounded`)

**Corpus** = `applicant.grounding_text(profile)` (non-sensitive values, one per line, plus computed facts as sentences, e.g. "Total professional experience: 14 months (1 years).") + `ctx.resume_text` + JD text + employer name.

**Resume text (D-68 A-2).** `apply_flow` (the orchestrator; stages never import each other) fills `ResolveContext.resume_text` once per attempt: the tailor master's text from `tailor_flow.master_text(cfg)` when a master cache valid for the current resume hash exists (tailor design §2), else `resume_ingest.extract_text(find_resume(<resume dir>))` (the profile stage's existing functions; the same file that is uploaded on the original-resume path). Either fails or no resume → `""` and the job-log line "resume text unavailable" (grounding then relies on profile + JD only, which only makes it stricter). `resume_text` never reaches a log.

**Alias groups (D-68 A-1).** `apply_flow` also fills `ResolveContext.alias_groups` and `alias_ambiguous` from `config/aliases.yaml` through `tailor_flow.alias_groups(cfg) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]` (the tailor's loader, tailor design §6.1; `apply/` does not import `tailor/`). One group per aliases entry = `(canonical, *variants)`; `instances` are not included (an instance is a one-way claim, not a synonym). A missing or invalid `aliases.yaml` → empty groups and the log line "aliases unavailable" (rule 3 then uses profile and attested skills only). `corpus_norm` = lowercase, whitespace collapsed, `,` removed inside digit groups.

- **choice / multi:** chosen index in range (schema); `evidence` normalised has ≥ 3 chars and is a substring of `corpus_norm`.
- **number:** the value formatted as an integer (or as given if fractional) occurs as a whole number in `corpus_norm`.
- **text:** fails on any of:
  1. a number token (`\d[\d,.]*%?`, normalised) not occurring as a whole token in the corpus;
  2. a month-name or year (`19xx|20xx`) not in the corpus;
  3. a dictionary term (every string in `ctx.alias_groups` ∪ profile skills ∪ attested skills) present in the text but **not grounded**: a term is grounded when it, or any other member of its alias group, occurs in the corpus (so "Postgres" in the text is grounded by a profile skill "PostgreSQL", and "k8s" by "Kubernetes"). Matching is case-insensitive on whole tokens, except tokens in `ctx.alias_ambiguous` (`go`, `c`, `r`), which match only when not all-lowercase (tailor design §4.1);
  4. a capitalised word not at sentence start, not in the allow-list (`I`, `I'm`, `I've`, `Singapore`, weekday and month names, `English`) and not occurring (case-insensitive) in the corpus;
  5. length > L, or empty when `unknown` is false.
  The violations list (no values beyond the offending tokens) goes into `Answer.note` and the retry prompt.

### 7.8 Audit (F-39)

Every field of every step gets one `apply_answers` row (§13), written when its step is filled (or when the attempt fails before filling, with the resolved status). Values are the exact value sent (file fields: the file name and SHA-256, not the path). `fill_failed` is set by `fill()`'s return.

---

## 8. Browser layer (KA-1, F-34)

### 8.1 Session (`browser.py`)

```python
class BrowserSession:                                  # one per `apply` job run
    def __init__(self, cfg: ApplyConfig): ...
    def __enter__(self) -> "BrowserSession"            # starts sync_playwright, launch_persistent_context
    def new_page(self) -> Page                         # a new tab per attempt
    def hold(self, seconds: float) -> None             # keep open; returns early when the owner closes the window
    def __exit__(...)                                  # closes the context and Playwright
```

Launch (**[S-1]**): `chromium.launch_persistent_context(user_data_dir=expandvars(cfg.profile_dir), channel="msedge", headless=not cfg.headed, ignore_default_args=["--disable-sync"] if cfg.edge_sync else None, viewport=None, locale="en-SG", timezone_id="Asia/Singapore", accept_downloads=False)`. All other Playwright defaults stay (`--enable-automation` is not passed by Playwright 1.64; password-store flags have no effect on Windows). No stealth, no user-agent change, no fingerprint flags (PRD §4.3). `profile_dir` default `%LOCALAPPDATA%\JobScraper\apply-profile`; it is outside the repo (NF-01 satisfied by location; the NF-01 test checks `data/` paths only). Edge shows a "--no-sandbox unsupported flag" bar; harmless.

The persistent profile can be open in only one process: a second `apply` job would fail to launch, which the JobManager's single slot already prevents.

### 8.2 Fill primitives (all in `browser.py`; adapters call these, never raw Playwright for input)

| Primitive | Behaviour |
|---|---|
| `fill_text(loc, value)` | `loc.fill(value)`; read back `loc.input_value()`; mismatch (ignoring spaces, for reformatting widgets like intl-tel-input) → one retry with `press_sequentially(value, delay=type_delay_ms)`; still wrong → returns False |
| `choose_react_select(page, loc, label)` | **[S-3]** click `loc`; `press_sequentially(prefix, delay=60)` where prefix = the first 30 chars of `label`; wait ≤ 5 s for `.select__menu [role="option"]` whose normalised text equals the normalised label (else contains it, if exactly one); click it; read back the nearest `.select__control` text. **Never press Enter.** Scope option search to `.select__menu` (bare `[role=option]` matches hidden intl-tel-input items) |
| `choose_native(loc, label)` | `loc.select_option(label=label)`; read back |
| `choose_listbox(page, button, label)` | Workday dropdowns: click the button (`aria-haspopup="listbox"`), click `[role="option"]` with exact text inside the open `[role="listbox"]`, read back the button text |
| `choose_radio(container, label)` | click the `label` element with exact normalised text (or its input); verify `checked` |
| `set_checkbox(loc, on)` | `loc.check()` / `loc.uncheck()`; verify |
| `typeahead(page, loc, text, pick)` | type text, wait for suggestions, click the one `pick(labels)` selects; none → False |
| `upload(loc, path)` | `loc.set_input_files(path)` on the (possibly hidden) file input; wait ≤ 15 s for the file name to appear on the page |
| `settle(page)` | `wait_for_load_state("domcontentloaded")`, then `wait_for_load_state("networkidle", timeout=5000)` ignoring timeout, then `apply.action_pause_ms` |

Pace (NF-05): a fixed `action_pause_ms` (250) after each field; no random jitter.

### 8.3 Evidence (F-34, F-38)

- Directory `data/apply/<attempt_id>/` (gitignored by `data/apply/`).
- Screenshots: `NN-<step>.png` full page, `NN` = two-digit sequence; step ids are `[a-z0-9_-]` (adapters slug them). Taken after `open`, after each step is filled, on the review page, after Submit, and on every failure (`NN-failed.png`). File names never contain personal values.
- On failure also `failed.html` (`page.content()`); and on `captcha`/`bot_challenge` a screenshot before any wait.
- Retention: kept as long as the attempt row (deleted with it; no automatic purge in M20/M21).

### 8.4 Page classifier (`classify.py`)

`classify(page) -> PageSignal` where `PageSignal ∈ {ok, captcha, bot_challenge, two_factor, verify_email, closed, error_page}`; called after every navigation, before each step's fill, after each Next, and while waiting for confirmation. Order of checks:

1. **captcha** (visible = `is_visible()` and bounding box height > 30): `iframe[src*="recaptcha"][src*="bframe"]`, `iframe[title*="recaptcha challenge" i]`, `iframe[src*="recaptcha"][src*="anchor"]:not([src*="size=invisible"])` (v2 checkbox), `iframe[src*="hcaptcha.com"]` whose src contains `frame=challenge` or `frame=checkbox`, `iframe[src*="challenges.cloudflare.com"]`, `.cf-turnstile`. **[S-3]** The invisible Enterprise anchor (`size=invisible`) and `.grecaptcha-badge` are on every Greenhouse board and are **not** a challenge.
2. **bot_challenge:** title `Just a moment...`; `#challenge-form`, `#cf-challenge-running`, `#px-captcha`; body text matching `/verify you are human|checking your browser|access denied.*reference #|unusual traffic/is`; HTTP status 403 or 429 on the main document.
3. **two_factor:** an `input[autocomplete="one-time-code"]` or a label/text matching `/verification code|one-time (pass)?code|authenticator|two-step|2-step|two-factor/i` **and** the page text mentions `sms|text message|phone|mobile|authenticator app`. (The same pattern mentioning `email` is `verify_email`.)
4. **verify_email:** text matching `/verify your email|check your (email|inbox)|we('ve| have) sent (you )?an? (email|link|code)|confirm your email|security code/i` and no visible form fields of the application.
5. **closed:** HTTP 404/410 on the main document; text matching `/no longer (accepting applications|available|open)|position has been filled|job (is )?not found|this job has expired|posting (has )?closed/i`.
6. **error_page:** HTTP ≥ 500.

Adapters may add markers (Workday `errorMessage`, Greenhouse `?error=true` redirect).

On `captcha`: if `captcha_wait_s` > 0 the tab is brought to front (`page.bring_to_front()`) and the flow polls `after_submit` every 2 s for that long; a confirmation turns the attempt `submitted`; otherwise `failed(captcha)`. No input is sent meanwhile.

---

## 9. ATS adapters

### 9.0 Detection (`detect.py`, F-31)

`detect(job: dict) -> tuple[AtsAdapter, Tenant]` or raises `ApplyFailure(UNSUPPORTED_ATS)`:
1. `job["provider"]` (the company's watchlist provider) in `REGISTRY` → `adapter.tenant_from_company(job)`; a `None` tenant falls through.
2. Each adapter's `match_url(job["url"])` in registry order.
3. Neither → `unsupported_ats` (detail = provider or URL host).

### 9.1 Greenhouse (M20)

| Item | Spec |
|---|---|
| Tenant | `board` = company `slug` (board token); `posting_id` = job `external_id`; `host = "job-boards.greenhouse.io"`. URL patterns: `(job-boards|boards)(\.eu)?\.greenhouse\.io/(embed/job_app\?for=)?(?P<board>[\w.-]+)(/jobs/\|&token=)(?P<id>\d+)`, and any URL with `gh_jid=<id>` when the company provider is greenhouse |
| Plan | `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?questions=true` with the app's `net.HttpClient` (ctx.http). 404 → `posting_closed`. [docs.greenhouse.io/job-board.html, fetched 2026-11-01] |
| Mapping | `questions[]`: one FormField per `fields[]` entry; key = field `name`, label = question `label`, required = question `required`, description = question `description` (HTML→text). Types: `input_text`→TEXT, `textarea`→TEXTAREA, `input_file`→FILE, `input_hidden`→HIDDEN, `multi_value_single_select`→DROPDOWN, `multi_value_multi_select`→MULTI_CHOICE; options from `values[{label,value}]`. When a question has a FILE and a TEXTAREA field (resume/cover letter), the textarea gets `alt_of` the file. Canonical by name: `first_name`, `last_name`, `email`, `phone`, `resume`→RESUME, `cover_letter`→COVER_LETTER; `preferred_name`; questions labelled "LinkedIn Profile"/"Website"/"GitHub" get LINKEDIN/WEBSITE/GITHUB. `location_questions` → one LOCATION field, key `candidate-location` (**[S-3]**). `compliance[]` (EEOC) → section `compliance`, canonical by name (`gender`→EEO_GENDER, `race`→EEO_RACE, `hispanic_ethnicity`→EEO_HISPANIC, `veteran_status`→EEO_VETERAN, `disability_status`→EEO_DISABILITY). `demographic_questions.questions[]` → section `demographic`, key = `str(id)`, options from `answer_options[{id,label}]`, resolved by EEO canonical when the label matches gender/race/ethnicity/veteran/disability, else decline set. `data_compliance[]` → CHECKBOX fields keyed `gdpr_processing_consent_given`, `gdpr_retention_consent_given` (canonical CONSENT_PRIVACY / CONSENT_RETENTION), present only when the flags are true. Plus one non-schema field: `country` (phone country react-select) → PHONE_COUNTRY_CODE |
| Open | `https://job-boards.greenhouse.io/{board}/jobs/{id}` (**[S-3]**: the form is on the posting page). If the final URL leaves `greenhouse.io`, open `https://job-boards.greenhouse.io/embed/job_app?for={board}&token={id}`. Expect `#first_name` within `step_timeout_s`; else `page_unrecognised` |
| Locators | **[S-3]** `[id="<name>"]` for every schema field (ids can be numeric, hence the attribute form); checkboxes `[id="<name>_1"]` (GDPR: `gdpr_processing_consent_given_1`); resume `#resume`, cover letter `#cover_letter` (hidden file inputs). Ignore the unnamed `remix-css-…-requiredInput` beside required react-selects |
| Fill | TEXT/TEXTAREA → `fill_text`; DROPDOWN (react-select) → `choose_react_select`; MULTI_CHOICE → `choose_react_select` once per option; LOCATION → `choose_react_select` on `#candidate-location` (async options; same helper); PHONE → `fill_text(#phone)` after `country` is chosen; CHECKBOX → `set_checkbox`; FILE → `upload` |
| Next | single page: `next_step` returns `is_review=True` |
| Submit | `button[type="submit"]` whose text matches `/submit/i` |
| Confirmation | URL contains `/confirmation`, or text matching `/thank you for applying|application (has been )?(received|submitted)|we('ve| have) received your application/i` → `confirmed:url` / `confirmed:text` |
| Code after Submit | text matching `/security code/i` with a new text input → `code_required`; `mail_domains = ("greenhouse.io", "greenhouse-mail.io")`; `otp_pattern = r"\b([A-Za-z0-9]{8})\b"` (**pending S-4**: confirm the code format on a real message) |
| Errors | visible `[aria-invalid="true"]` field labels, `.helper-text--error`, text "This field is required" → `errors`; one re-fill of those fields, then `validation_error` |
| Account | none (`needs_account = False`) |

Recorded schemas for fixtures: the spike's `gh_vercel.json`, `gh_dataiku.json` (scratch; the tester copies them, scrubbed of nothing personal since they are public schemas, into `tests/fixtures/greenhouse/`).

### 9.2 Lever (M21)

Selectors below are from prior knowledge and public automation code (marked **K**); the M21 Lever WP starts by recording one real apply page as a fixture and confirming them (a verification step, not a design choice: if a selector differs, the fixture wins and the engineer notes it in the handoff).

| Item | Spec |
|---|---|
| Tenant | `jobs.lever.co/{slug}/{uuid}` (also `jobs.eu.lever.co`); board = slug, posting_id = uuid; host = `jobs.lever.co` |
| Plan | DOM (`plan_from_schema` → None) |
| Open | `https://jobs.lever.co/{slug}/{uuid}/apply`; expect `form` with `input[name="email"]` |
| Fields (K) | `name` (FULL_NAME), `email`, `phone`, `org` (CURRENT_COMPANY), `location` (LOCATION typeahead, `#location-input`), `urls[LinkedIn]`, `urls[GitHub]`, `urls[Portfolio]`, `urls[Other]`, resume `input[type=file][name="resume"]` (RESUME), `comments` (optional; left blank). Custom cards: for each hidden `input[name$="[baseTemplate]"]` parse its JSON value `{text, fields:[{type, text, required, options:[{text}]}]}`; field N's input is `[name="cards[<uuid>][field<N>]"]`; types `text`→TEXT, `textarea`→TEXTAREA, `multiple-choice`→RADIO, `multiple-select`→MULTI_CHOICE (checkboxes), `dropdown`→DROPDOWN (native select). EEO: `select[name^="eeo["]` → EEO canonicals. Consent checkboxes `input[name^="consent["]` → CONSENT_* |
| Fill | text → `fill_text`; native selects → `choose_native`; radios/checkboxes → `choose_radio`/`set_checkbox` (brief: programmatic clicks may trigger hCaptcha; the classifier then ends the attempt `captcha`, by design) |
| Submit | `#btn-submit` or `button[data-qa="btn-submit"]` (K) |
| Confirmation | URL ends `/thanks`, or text `/application submitted|thanks for applying/i` |
| Errors | `.error-message:visible`, `.application-error` |
| Account | none; `mail_domains = ("lever.co", "hire.lever.co")` |

### 9.3 Ashby (M21)

| Item | Spec |
|---|---|
| Tenant | `jobs.ashbyhq.com/{slug}/{uuid}`; host `jobs.ashbyhq.com`. An employer page with `#ashby_embed` maps to the same URL from the job's `external_id` |
| Plan | DOM. (Ashby's non-public form API is not used.) |
| Open | `https://jobs.ashbyhq.com/{slug}/{uuid}/application`; wait until the text "Fetching application form" is gone and `#_systemfield_email` is visible (≤ `step_timeout_s`) |
| Fields | `#_systemfield_name` (FULL_NAME), `#_systemfield_email` (EMAIL), `#_systemfield_resume` (RESUME, file; **not** the separate autofill-from-resume input at the top, which is never used), phone `input[type=tel]` (PHONE). Custom fields: every field entry container with a `label[for]`; type from the control: `input[type=text|email|url|number]`, `textarea`, `[role=combobox]` (react-select → DROPDOWN), radios `#<uuid>-labeled-radio-<n>` (RADIO), checkbox groups (MULTI_CHOICE), Yes/No button pairs (RADIO with options Yes/No, clicked as buttons). Required = asterisk in the label or `aria-required` |
| Submit | `button[type="submit"]` with text `/submit application/i` |
| Confirmation | text `/successfully submitted|application submitted|thanks for applying/i`, or URL ending `/submitted` |
| Errors | text `/missing entry for required field|required/i` beside fields, `[class*="error"]:visible` |
| Account | none; `mail_domains = ("ashbyhq.com",)`. Ashby merges candidates by email (brief §1.2): the per-employer cap (2/day) and the duplicate guard are the protection; no plus-addressing (PRD assumption) |

Sources for Ashby selectors: public automation references (github.com/galiprandi/job-seeker `.agents/skills/browser-automation/references/ats-patterns.md`, read 2026-11-01). Confirm with a fixture in the WP, as for Lever.

### 9.4 Workday (M21)

Automation ids below were confirmed in several independent public automation projects (GitHub code search 2026-11-01: `ubangura/Workday-Application-Automator/apply.js`, `AbhishekMandapmalvi/AutoApply/bot/apply/workday.py`, `ChrisMBarr/UserScripts`, `Tran-Steven/jobpipe`, `girijesh18/HireOS`). Ids marked **K** were seen in only one source or come from prior knowledge; the Workday WP confirms them on a recorded tenant fixture first.

| Item | Spec |
|---|---|
| Tenant | `parse_workday(url)` (existing in `scrape/adapters.py`; `detect` receives it via the orchestrator, or the adapter re-implements the same regex in `ats/workday.py` — chosen: re-implement, stages don't import each other): host `<tenant>.wd<n>.myworkdayjobs.com`, board = tenant, site. `vault_service = jobscraper:workday:<host>`. One account per tenant (brief S23) |
| Open | job URL; click `[data-automation-id="adventureButton"]` or `[data-automation-id="jobPostingApplyButton"]`; then `[data-automation-id="applyManually"]` when offered (never "Autofill with resume", never "Use my last application") |
| Account wall | sign-in form visible (`signIn-email`/`email` + `password` inputs) or `[data-automation-id="createAccountLink"]` / `utilityButtonSignIn` |
| Sign in | email `[data-automation-id="email"]` (or `signIn-email`), password `[data-automation-id="password"]` (or `signIn-password`), click `[data-automation-id="signInSubmitButton"]` (if covered by an overlay, click its parent `div[role=button]`). `[data-automation-id="errorMessage"]` visible → `login_failed` |
| Sign up | `createAccountLink` → `email`, `password`, `verifyPassword`, tick `createAccountCheckbox` (terms; `consents.privacy_consent` must be true, else `unanswerable_required` "account terms") → **vault write first (§10.2)** → `createAccountSubmitButton`. Result: signed in (wizard visible) → `signed_in`; verify-email text → `verify_email`; sign-in form → `sign_in`; "already exists"/"already in use" text → `login_failed` (detail as §4.4) |
| Steps | step id from the visible page container: `contactInformationPage`→`my_information`, `myExperiencePage`→`my_experience`, `primaryQuestionnairePage`/`secondaryQuestionnairePage`→`questions_1`/`questions_2`, `voluntaryDisclosuresPage`→`voluntary_disclosures`, `selfIdentificationPage`→`self_identify`, `reviewJobApplicationPage`→`review` (`is_review=True`). Active step label `[data-automation-id="progressBarActiveStep"]` is logged. An unknown container → `page_unrecognised` |
| my_information | `previousWorker` radio (PREVIOUS_WORKER), how-heard source (HOW_HEARD; K: `sourceDropdown`, a two-level listbox — pick category then source), `countryDropdown`/`addressSection_countryRegion` (COUNTRY), `legalNameSection_firstName`, `legalNameSection_lastName`, `addressSection_addressLine1`, `addressSection_city`, `addressSection_postalCode`, `phone-device-type` (PHONE_DEVICE_TYPE), `countryPhoneCode` (K, PHONE_COUNTRY_CODE), `phone-number` (PHONE), `email` (pre-filled; verify only) |
| my_experience | upload `[data-automation-id="file-upload-input-ref"]` (RESUME); wait for the parse (≤ 20 s: spinner gone). Then make the sections match the profile exactly: delete every pre-filled `workExperience-<n>` and education panel (their Delete buttons), and add one panel per profile entry via the section's `Add` button: experience `jobTitle`, `company`, `location`, `currentlyWorkHere` checkbox, `formField-startDate`/`formField-endDate` → `dateSectionMonth-input` + `dateSectionYear-input`, `description`; education `formField-schoolItem` (typeahead; no matching school → required: `unanswerable_required` "school"), `degree` (listbox), `formField-field-of-study` (typeahead), `gpa`, `formField-firstYearAttended`, `formField-lastYearAttended`; websites `websiteSection` Add + url; `linkedinQuestion`; skills `formField-skillsPrompt` (type a skill, choose the exact suggestion; skills without a suggestion are skipped). These are tier-1 answers with `source = "field_map:experience[i].<key>"` |
| questions_* | every `[data-automation-id^="formField-"]` item: label = its `legend`/`label` text; control = listbox button → DROPDOWN, radio group → RADIO, `textarea` → TEXTAREA, `input` → TEXT, checkbox group → MULTI_CHOICE, date → DATE. Key `questions_<n>:<index>`. Resolved by tiers 2–5 |
| voluntary_disclosures | `gender` (EEO_GENDER), `ethnicityDropdown` (EEO_RACE), `hispanicOrLatino` (EEO_HISPANIC), `veteranStatus` (EEO_VETERAN), `agreementCheckbox` (TERMS_AGREEMENT). Other items via tiers |
| self_identify | `name` (SELF_ID_NAME), date via `dateIcon` → `datePickerSelectedToday` (SELF_ID_DATE), disability choice (EEO_DISABILITY: decline option "I do not want to answer") |
| Next / Submit | `[data-automation-id="bottom-navigation-next-button"]`; on `review` its text is "Submit" → that click is `submit()` |
| Confirmation | `[data-automation-id="thankYouMessage"]` visible (K), or text `/application (has been )?submitted|thank you for applying|congratulations/i`; fallback: candidate home lists the job title with status "Submitted" (K) |
| Errors | `[data-automation-id="errorMessage"]`, error banner text `/errors? found|required/i` after Next → one re-fill of the flagged fields, then `validation_error` |
| Password rules | `PasswordRules(length=20, symbols="!@#$%^&*")` (Workday requires upper, lower, digit, special; ≥ 8) |
| Mail | `mail_domains = ("myworkday.com", "myworkdayjobs.com", "workday.com")` + the employer's registrable domain (§11.3) |

Workday's site terms (brief §7, D-54, R-6) are accepted by the owner; caps and the no-evasion rules apply unchanged.

---

## 10. Accounts, vault and Edge (KA-3, F-35, NF-02)

### 10.1 `vault.py` (foundation)

```python
SERVICE_PREFIX = "jobscraper"
def service_for(ats: str, host: str) -> str               # "jobscraper:<ats>:<host lower>"
IMAP_SERVICE = "jobscraper:imap:{host}"                    # username = the IMAP login
def get(service, username) -> Optional[Secret]             # keyring.get_password
def put(service, username, secret: Secret) -> None        # keyring.set_password; read back and compare, else VaultError
def delete(service, username) -> None
def generate(rules: PasswordRules) -> Secret               # secrets.SystemRandom
def export_edge_csv(rows, out_dir) -> Path                 # §10.3
```
**[S-1]** keyring 25.7 uses `WinVaultKeyring`; entries appear in Credential Manager as `LegacyGeneric:target=jobscraper:<…>`, user = email. Store only passwords (blob limit ~2.5 KB).

**Generator:** length = `rules.length` clamped to `[min_length, max_length]`; draw one char from each required class (A–Z, a–z, 0–9, `rules.symbols`), fill the rest from the union, shuffle with `SystemRandom().shuffle`. Never logged.

### 10.2 Account creation order (stored before sign-up submit)

1. `secret = vault.generate(adapter.password_rules)`
2. `vault.put(service, email, secret)` (read-back verified; failure → `error`, nothing submitted)
3. `store.upsert_account(ats, host, email, status='creating', attempt_id)`
4. `adapter.sign_up(page, ctx, secret)` (clicks submit)
5. outcome `signed_in`/`verify_email`/`sign_in` → status `created`; after a successful verification → `verified` (`verified_at`)
6. the site shows a field error before accepting (password rule, invalid email): `vault.delete`, delete the account row, → `validation_error`
7. any exception after the click: keep both (status `unknown`); the next attempt signs in with the stored password

Sign-in failure (`login_failed`) sets status `signin_failed` and `last_signin_ok=0`; the password is never reset or regenerated (F-35).

### 10.3 Into Edge

- **Default route (CSV, F-35 fallback):** Settings → Accounts → "Export new passwords for Edge" writes `data/edge_passwords_<UTC stamp>.csv` (covered by `data/*.csv`), UTF-8, header `name,url,username,password,note`, one row per account with `exported_to_edge_at IS NULL`: name = `<ATS> <tenant host>`, url = `https://<tenant host>/`, username = email, note = `JobScraper`. **[S-1]** Edge requires `url,username,password`; the Chromium export format adds `name,note`. The UI shows the import path (Edge → Settings → Profiles → Import browser data → Import from other password managers → Passwords CSV). "I've imported it" deletes the file (overwrite with zeros, then unlink) and stamps the rows. The web app also deletes any `data/edge_passwords_*.csv` older than 1 hour at startup and on every Accounts page load. The first export carries a one-time note: "Check with one account first: import, then look for it in Edge's passwords."
- **Sync route (pending owner test, S-1c):** `apply.edge_sync: true` drops `--disable-sync`; the owner signs the JobScraper Edge profile into their Microsoft account once with password sync on. Privacy cost (spike): the owner's synced passwords then also live in `apply-profile`. Edge only saves a password when its "Save your password?" bubble is accepted; Playwright cannot click it. With `apply.edge_save_bubble: true` (only honoured when `edge_sync` is true), after `sign_up` the flow runs a best-effort Windows UI Automation click (PowerShell helper shipped as `src/jobscraper/apply/edge_save.ps1`, scoped to `msedge` processes whose command line contains the profile path, button name "Save", 5 s timeout). Failure is logged and ignored: keyring stays the source of truth and the CSV route stays available.
- **Copy password:** `POST /api/apply/accounts/{id}/password` returns the password once (`Cache-Control: no-store`), the UI copies it to the clipboard and never renders it.

### 10.4 Add an existing account

Settings → Accounts → "Add an account you already have": ATS (Workday only in M21), tenant URL, email, password → `vault.put` + account row status `created`. Fixes the `login_failed` "account exists" case without a password reset.

---

## 11. Mail: IMAP verification (F-36, D-52)

### 11.1 Fetcher (`apply/mail.py`)

```python
class MailWatcher:
    def __init__(self, host: str, port: int, username: str, password: Secret, timeout_s: float = 20): ...
    def wait_for(self, *, since_utc: datetime, sender_domains: Sequence[str], link_domains: Sequence[str],
                 otp_pattern: Optional[str], want: str, wait_s: int = 300, poll_s: int = 10) -> Verification
        # want: "link" | "code" | "either". Raises ApplyFailure(EMAIL_VERIFICATION_TIMEOUT).
def test_connection(host, port, username, password) -> str       # "ok: N messages in INBOX" or raises MailError
```

- `imaplib.IMAP4_SSL(host, port, timeout=…)`, `login`, then for each folder in (`INBOX`, `[Gmail]/Spam`): `conn.select(folder, readonly=True)` (issues **EXAMINE**). Never `STORE`, `COPY`, `MOVE`, `EXPUNGE`, `APPEND`, or SMTP (F-36). A folder that doesn't exist is skipped.
- Search: `SEARCH SINCE <dd-Mon-yyyy of since_utc − 1 day>`; for each id, `FETCH (INTERNALDATE BODY.PEEK[])` (PEEK: never sets \Seen). Keep messages with INTERNALDATE ≥ `since_utc − 60 s` (since = attempt `started_at`).
- Sender match: the From address domain `d` matches when `d == s` or `d.endswith("." + s)` for any `s` in `sender_domains` (adapter `mail_domains` + employer registrable domain).
- Newest matching message first. Body: `text/plain` part, else `text/html` → text; links from `href` attributes and bare URLs.
- **Link:** first URL whose host matches `link_domains` (the tenant host, the ATS domains, the employer domain; same suffix rule) and whose URL or anchor text matches `/verify|verification|activate|confirm|validate/i`. Only such a link is opened (F-36), in the attempt's tab (`page.goto`).
- **Code:** the first line containing `/code/i`, then that line and the next; first match of `otp_pattern` (adapter; default `r"\b(\d{6})\b"`).
- Poll every `poll_s` until `wait_s`; reconnect on a dropped connection; logout at the end. Logged: "verification mail found (link|code) from <sender domain>" — never the URL, code or subject.

### 11.2 When mail is used

`verifying_email` in Workday sign-up/sign-in, and Greenhouse's code after Submit (§4.2). Not configured (no host, username or vault entry) → `mail_not_set_up` before Submit (after Submit: §4.2).

### 11.3 Employer registrable domain

From the company's `careers_url` host: the last two labels, or the last three when the second-to-last is one of `com, co, edu, gov, org, net, ac` and the last is a 2-letter country code (`dbs.com.sg` → `dbs.com.sg`; `careers.dbs.com` → `dbs.com`). ATS hosts (`*.myworkdayjobs.com`, `greenhouse.io`, `lever.co`, `ashbyhq.com`) are not employer domains.

### 11.4 Owner setup: Gmail app password (Q-14)

1. Google Account → Security → turn on **2-Step Verification** (app passwords need it; not available with Advanced Protection or security-key-only 2SV).
2. Open `https://myaccount.google.com/apppasswords`, create one named `JobScraper`, copy the 16 characters (spaces don't matter).
3. In Gmail → Settings → Forwarding and POP/IMAP, make sure IMAP access is on if the option is shown.
4. JobScraper → Settings → Apply → Mailbox: host `imap.gmail.com`, port `993`, username = your Gmail address, paste the app password → Save (stored in Credential Manager as `jobscraper:imap:imap.gmail.com`; never in a file). Or CLI: `python -m jobscraper mail set-password` (prompts with `getpass`).
5. Click **Test connection** (or `python -m jobscraper mail test`): expect "Connected, read-only: N messages in INBOX".
6. To revoke: delete the app password at the same Google page; changing the Google password also revokes it.

Spike S-4 = step 5 plus one real verification-style message found by `mail test --find-from <domain>` (prints only "found from <domain> at <time>").

---

## 12. Caps and duplicate guards (F-30, D-61, NF-05, NF-06)

### 12.1 Order of checks per job (in `apply_flow`, after creating the `queued` row)

1. **Profile** (`applicant.missing_for_apply` + resume exists) → `profile_incomplete`.
2. **Duplicate** (`store.apply_duplicate(job_id) -> Optional[str]` returns a detail or None):
   - `applications` row for `job_id` with status ≠ `to_apply` → "applied <applied_at>"
   - a **twin**: an application with status ≠ `to_apply` whose `posting_key(url)` equals this job's (M17 rule; `posting_key` moves from `web/data.py` to `models.py`, engineer) → "same posting as <company> · <role>"
   - an attempt for this `job_id` or a twin in `submitted`/`submitted_unconfirmed`, or with `submit_clicked_at` set → "already submitted by JobScraper"
   - the same `job_id` appearing twice in one batch → the second is `duplicate`.
3. **Caps** (`store.apply_counts(company_id, day_start_utc) -> (today_total, today_employer)`, counting attempts with `submit_clicked_at ≥ day_start` where day = the local calendar day, Asia/Singapore): `today_total ≥ daily_cap` → `cap_reached` ("10 of 10 today"); `today_employer ≥ per_employer_daily_cap` → `cap_reached` ("2 of 2 today at <company>"). Dry runs never count (no click). In `dry_run` mode caps are not checked.
4. **One in flight:** the JobManager runs one job at a time; inside a job attempts run sequentially. `apply_flow` additionally refuses to start if another attempt row is in a non-terminal state other than `queued` after reaping (detail "another application is in progress").

### 12.2 Web preflight

`POST /api/apply` runs checks 1–3 with the same foundation calls (no stage import) and returns refusals immediately; only eligible job ids are passed to the job. `apply_flow` re-checks (authoritative; state may change between).

### 12.3 `previously_applied` for the resolver

True if any `applications` row (status ≠ `to_apply`) or any attempt with `submit_clicked_at` exists for a job of the same `company_id`, excluding the current job. (`store.applied_to_company(company_id, exclude_job_id) -> bool`.)

---

## 13. Store (DDL)

`SCHEMA_VERSION` 2 → 3. The new tables are appended to `SCHEMA` (created by the existing `executescript` on any DB); `_migrate` gains the column additions below (PRAGMA table_info + `ALTER TABLE … ADD COLUMN`, the existing pattern) and sets `meta.schema_version` to 3 with an upsert. The tailor design's `tailored` table joins in the same version; the two lanes each append their own block and the Coordinator merges (`04_team.md` §2).

```sql
CREATE TABLE IF NOT EXISTS apply_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    company_id INTEGER,                    -- jobs.company_id at queue time (per-employer cap)
    ats TEXT, tenant_host TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('auto', 'dry_run')),
    state TEXT NOT NULL,                   -- AttemptState values
    step TEXT,                             -- current or last step id
    reason_code TEXT, reason_detail TEXT,  -- ReasonCode value; detail has no personal values
    end_url TEXT,                          -- page URL at the end, query string dropped
    plan_source TEXT,                      -- schema | dom
    resume_file TEXT, resume_sha256 TEXT,  -- file name only, and its hash
    resume_source TEXT,                    -- tailored | original
    tailored_id INTEGER,                   -- tailored.id when resume_source = tailored
    confirmation TEXT,                     -- signal that matched, or 'owner'
    code_resubmits INTEGER NOT NULL DEFAULT 0,
    queued_at TEXT NOT NULL, started_at TEXT, submit_clicked_at TEXT, finished_at TEXT,
    job_log TEXT                           -- the web job id (data/jobs/<id>.log), if started from the web
);
CREATE INDEX IF NOT EXISTS idx_attempts_job ON apply_attempts(job_id, id);
CREATE INDEX IF NOT EXISTS idx_attempts_clicked ON apply_attempts(submit_clicked_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_one_success
    ON apply_attempts(job_id) WHERE state IN ('submitted', 'submitted_unconfirmed');

CREATE TABLE IF NOT EXISTS apply_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    step TEXT NOT NULL DEFAULT '',
    field_key TEXT NOT NULL,
    label TEXT NOT NULL, label_norm TEXT NOT NULL,
    field_type TEXT NOT NULL, required INTEGER NOT NULL,
    section TEXT,
    options_json TEXT,                     -- [{"label":..,"value":..}] as offered
    value_json TEXT,                       -- exact value sent (JSON); NULL when blank
    tier INTEGER NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
    status TEXT NOT NULL,                  -- AnswerStatus values
    rule_id TEXT, model TEXT, prompt_hash TEXT, note TEXT,
    sensitive INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL,
    corrected_json TEXT, corrected_at TEXT -- M22 (F-12): the owner's correction
);
CREATE INDEX IF NOT EXISTS idx_answers_attempt ON apply_answers(attempt_id, id);

CREATE TABLE IF NOT EXISTS ats_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ats TEXT NOT NULL, tenant_host TEXT NOT NULL, email TEXT NOT NULL,
    vault_service TEXT NOT NULL,           -- the Credential Manager target; never the password
    status TEXT NOT NULL,                  -- creating | created | verified | signin_failed | unknown
    created_at TEXT NOT NULL, verified_at TEXT,
    last_signin_at TEXT, last_signin_ok INTEGER,
    exported_to_edge_at TEXT,
    created_by_attempt INTEGER,
    UNIQUE (ats, tenant_host, email)
);

CREATE TABLE IF NOT EXISTS answer_memory (
    label_norm TEXT NOT NULL,
    field_type TEXT NOT NULL,
    ats TEXT NOT NULL DEFAULT '*',
    value_json TEXT NOT NULL,              -- choice fields: option label(s)
    source_answer_id INTEGER,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (label_norm, field_type, ats)
);
```

Column addition in `_migrate`: `app_events.by TEXT` (NULL = the owner; `'jobscraper'` = written by auto-apply; the UI renders "Applied by JobScraper", F-37). `set_application_status` gains `by: Optional[str] = None`.

Store methods (names fixed; SQL is the engineer's): `create_attempt(job_id, company_id, mode, now) -> int`, `set_attempt_state(id, state, *, step=None, reason=None, detail=None, **cols)` (validates `TRANSITIONS`), `mark_submit_clicked(id, now)`, `attempt(id)`, `attempts_for_job(job_id)`, `reap_attempts(now)`, `apply_duplicate(job_id)`, `apply_counts(company_id, day_start)`, `applied_to_company(company_id, exclude_job_id)`, `add_answers(attempt_id, rows)`, `answers(attempt_id)`, `answer_memory_get(label_norm, field_type, ats)`, `answer_memory_put(...)`, `upsert_account(...)`, `account(ats, host, email)`, `accounts()`, `set_account_status(id, status, **cols)`, `delete_account(id)`, `accounts_to_export()`, `mark_exported(ids, now)`.

Deleting: an application deleted via Undo does not delete attempts (the audit outlives the Undo); `answers` rows are deleted only with their attempt (no UI for it in M21).

---

## 14. Interfaces

### 14.1 CLI verbs (`cli.py`, one function per verb)

| Verb | Behaviour | Exit |
|---|---|---|
| `apply <job_id>... [--dry-run]` | `apply_flow.run`. Mode = `--dry-run` → dry_run; else the effective `apply.mode` (settings > config). Prints one line per state change and a final table: job id, state, reason | 0 all ok; 1 any failed/unconfirmed; 2 bad arguments |
| `applicant check` | load + validate + missing; prints each error `path: message`, the missing list, completeness `filled/needed`, and "Resume: <file name> ok" | 0 when no errors and nothing missing |
| `applicant init` | §5.5 (M21); refuses if the file exists | 0 / 1 |
| `accounts list` | ATS, tenant, email, status, created, verified, exported (no passwords) | 0 |
| `accounts export-edge` | §10.3; prints the CSV path and the import steps; `--confirm` deletes the newest export and stamps rows | 0 |
| `mail set-password` | `getpass`, `vault.put(IMAP_SERVICE…)`; host/username from settings or `--host/--user` | 0 |
| `mail test [--find-from DOMAIN]` | `test_connection`; with `--find-from`, reports the newest message from that domain (time only) | 0 ok / 1 |
| `apply show <job_id\|attempt_id>` (D-68 A-3; M20, lane B) | All digits → that attempt (`store.attempt`); otherwise the job's newest attempt (`store.attempts_for_job`, last). Prints a header (attempt id, job id, company — title, ATS, mode, state, reason code + detail, resume file + source, queued/started/submit-clicked/finished times), then one line per `store.answers(attempt_id)` row in id order: step, verbatim label, value (the exact value sent, **S-fields included**: this is the owner's own terminal; file fields as file name + SHA-256), tier, confidence, source (+ `rule_id`), status, and the note when present; then the evidence paths `data/apply/<attempt_id>/*.png` (and `failed.html`). This is how the owner reads the audit at the M20 gate. Nothing goes to a job log | 0; 1 unknown id / no attempt |

### 14.2 Job kinds (`web/jobs.py`)

`KINDS += ("apply", "tailor", "mailtest")`. argv: `apply` → `["apply", *job_ids] + (["--dry-run"] if opts.get("dry_run") else [])` (job ids validated against `^[A-Za-z0-9:_-]{1,80}$`, at most 20); `mailtest` → `["mail", "test"]`; `tailor` → tailor design. One job at a time stays the rule: an apply batch blocks a scrape run started from the web until it ends (consequence accepted; caps keep a batch ≤ 10 submissions).

### 14.3 Web API (M21; routers `web/routers/applicant.py`, `web/routers/apply.py`)

| Method, path | Request | Response |
|---|---|---|
| `GET /api/applicant` | | `{profile, errors:[{path,message}], missing:[path], completeness:{filled,needed}, from_resume:[path], sensitive:[path]}` (`profile` = `{}` if no file) |
| `PUT /api/applicant` | `{profile}` | 200 same shape as GET; 422 `{detail:"invalid", errors:[{path,message}]}` (nothing saved) |
| `POST /api/apply` | `{job_ids:[str], dry_run?:bool}` | 202 `{job: <JobView>, accepted:[job_id], refused:[{job_id, reason_code, text, hint, detail}]}`; 409 `{detail:"busy"}` if a job runs; 422 `{detail:"profile_incomplete", missing:[path]}` |
| `GET /api/apply/attempts?job_id=` | | `[{id, job_id, mode, state, step, reason_code, text, hint, detail, queued_at, finished_at, confirmation, resume_file, resume_source}]` newest first (reaps first when no apply job runs) |
| `GET /api/apply/attempts/{id}` | | the row + `answers:[{label, field_type, required, options, value, tier, source, confidence, status, sensitive, note}]` + `screenshots:[name]` |
| `GET /api/apply/attempts/{id}/screenshots/{name}` | | PNG; `name` must match `^\d{2}-[a-z0-9_-]+\.png$` and exist in that attempt's directory |
| `POST /api/apply/attempts/{id}/outcome` | `{went_through: bool}` | §4.3; only on `submitted_unconfirmed` (409 otherwise) |
| `GET /api/apply/settings` | | `{mode, daily_cap, per_employer_daily_cap, headed, captcha_wait_s, mail:{host, port, username, password_set}}` |
| `PUT /api/apply/settings` | same minus `password_set` | 200 same; 422 on bad values (caps 1–50, wait 0–600, port 1–65535) |
| `PUT /api/apply/mail-password` | `{password}` | 204; stored via `vault.put` |
| `POST /api/apply/mail-test` | | 202 `{job}` (kind `mailtest`) |
| `GET /api/apply/accounts` | | `[{id, ats, tenant_host, email, status, created_at, verified_at, exported_to_edge_at}]` |
| `POST /api/apply/accounts` | `{ats, tenant_url, email, password}` | 201 (§10.4) |
| `POST /api/apply/accounts/{id}/password` | | `{password}` with `Cache-Control: no-store` |
| `POST /api/apply/accounts/export-edge` | | `{file:"data/edge_passwords_<stamp>.csv", count}`; 204 when none to export |
| `POST /api/apply/accounts/export-edge/confirm` | | 204; deletes the file, stamps rows |
| `POST /api/apply/answers/{id}/correct` (M22) | `{value, remember:bool}` | 200 |

`text`/`hint` come from `REASON_TEXTS` with `{detail}` filled (web imports `apply.contracts`). Settings are stored in the `settings` table under keys `apply.mode`, `apply.daily_cap`, `apply.per_employer_daily_cap`, `apply.headed`, `apply.captcha_wait_s`, `apply.mail.host`, `apply.mail.port`, `apply.mail.username`; each falls back to `config.yaml`'s `apply:` block. The mail username is never written to config (the repo is public).

### 14.4 UI (M21; fast-track spec, Vue)

- **Inbox detail actions:** "Auto-apply" (primary) beside "Apply on company site"; in multi-select mode "Auto-apply to selected (N)". While the profile is incomplete the button is disabled with "Finish your application details first" linking to Profile. Clicking shows a confirm only in `auto` mode: "Send applications to N employers now? JobScraper fills and submits them in Edge." [Send applications] [Cancel]. Refusals from the response show as a toast list.
- **Attempt panel** (Inbox and Applications detail, when the job has attempts): state chip (Queued, Tailoring, Filling (step), Submitted, Needs your check, Dry run ready, Failed), the reason `text` + `hint`, "Open the posting" link on any failure, "It went through" / "It didn't go through" on `submitted_unconfirmed`, link "What I told this employer".
- **What I told this employer** (Applications detail, F-39): outcome line; resume file sent (name, tailored or original, link to the tailor diff); table Question · Answer · Source (badge: Form field / Your profile / Remembered / Declaration / AI) · Confidence; sensitive answers first under "Personal declarations"; AI answers flagged "written by AI"; screenshots as a thumbnail strip (click to enlarge).
- **Settings → Apply:** Mode (Automatic submit / Dry run), daily limit, per-employer limit, Show the browser window (headed), CAPTCHA wait seconds, Mailbox (host, port, username, app password field showing "Saved" when set, Test connection).
- **Settings → Accounts:** table ATS · Site · Email · Created · Verified · In Edge (exported date) · [Copy password]; buttons "Export new passwords for Edge", "I've imported it", "Add an account you already have".
- **Profile → Application details:** groups in §5.4 order, completeness meter "N of M needed details filled", "From resume, check" chips, sensitive groups marked "Never sent to the AI", Declarations as Yes/No switches with the plain question text, inline error per field from the 422 response.

---

## 15. Extension walkthrough: add a new ATS adapter in 6 steps (no core edits)

Example: SmartRecruiters (M22).

1. Create `src/jobscraper/apply/ats/smartrecruiters.py` with a class implementing `AtsAdapter` (contracts §"Adapter protocol"): `name = "smartrecruiters"` (equal to the watchlist provider), `needs_account`, `password_rules`, `mail_domains`, `otp_pattern`, and the methods. Use only `browser.py` primitives and `classify.py` for page states; raise `ApplyFailure` with a `ReasonCode` for every stop.
2. `match_url` / `tenant_from_company`: the URL regex and the board from the company slug.
3. `plan_from_schema` returns None unless the ATS publishes a form schema; `read_step` maps DOM controls to `FormField`s, tagging standard fields with `Canonical` values (add none: if a new standard field is needed, that is a contract change → architect).
4. `submit` / `after_submit`: the confirmation signal and the error markers.
5. Register: one line in `apply/ats/__init__.py` `REGISTRY`.
6. Fixture + tests (tester): a recorded HTML page in `tests/fixtures/<ats>/`, served by a local `http.server` in the test, filled in dry-run mode; assert the plan, the answers and `ready_to_submit`.

Nothing in `apply_flow.py`, `resolve.py`, `store.py` or the web layer changes. Questions specific to the ATS go into `config/questions.yaml` (researcher).

---

## 16. Config: the `apply:` block (engineer adds to `config/config.yaml`)

```yaml
apply:
  mode: dry_run              # auto | dry_run. Settings → Apply overrides. M20 ships dry_run; the owner switches to auto after the M20 gate
  daily_cap: 10              # D-61
  per_employer_daily_cap: 2  # D-61
  headed: true               # D-53; Settings overrides
  captcha_wait_s: 0          # F-38
  profile_dir: "%LOCALAPPDATA%\\JobScraper\\apply-profile"
  edge_sync: false           # S-1: true drops --disable-sync (only after the owner's sync test)
  edge_save_bubble: false    # best-effort UIA click on Edge's Save prompt; needs edge_sync
  type_delay_ms: 60          # press_sequentially delay (react-select search, retries)
  action_pause_ms: 250       # fixed pause after each field (NF-05)
  step_timeout_s: 45         # waiting for a page or step to appear
  confirm_timeout_s: 60      # F-37
  attempt_timeout_s: 420     # whole attempt, excluding the mail wait (NF-07: ≤ 4 min typical)
  dry_run_hold_s: 600        # F-37 dry run: keep the filled form open
  resume_format: pdf         # pdf | docx: which tailored file to upload when both exist (falls back to the other)
  llm_text_temperature: 0.3
  mail:
    host: imap.gmail.com
    port: 993
    wait_s: 300              # F-36
    poll_s: 10
paths:
  applicant: data/applicant.yaml
  questions: config/questions.yaml
```

`config.py` gains `Config.apply` (a frozen `ApplyConfig` dataclass with these fields and defaults) and `applicant_path`, `questions_path`.

---

## 17. Logging rules (NF-09, NF-02)

- `apply_flow` writes to stdout (the job log the Developer tab tails) one line per event: `[attempt 12] <state> step=<step> ats=<ats> fields=<n> filled=<n> blank=<n> unknown=<n> tier5=<n>`; on failure `[attempt 12] failed reason=<code> step=<step> detail=<detail>` plus the rendered owner text.
- Never logged: any answer value, any profile value, the email, passwords, verification URLs or codes, mail subjects, resume text, LLM prompts or outputs. URLs are logged as host + path with the query string dropped.
- Every line passes through `redact(line, applicant.redaction_values(profile))`, which replaces each value (case-insensitive, longest first) with `[redacted]`. Exceptions are logged as `type(exc).__name__` + the redacted first line, truncated to 200 chars; full tracebacks only for `error`, also redacted.
- Labels (question text) may be logged; they are the employer's text.

---

## 18. Requirement map

| Req | Where |
|---|---|
| F-10 | §5.1, §5.3, §5.4 (incl. D-55 declarations), §5.5 |
| F-11 | §5.2, §12.1 (1), §14.3 `/api/applicant`, §14.4 Profile |
| F-12 | §7.4, §13 `answer_memory`, §14.3 correct (M22) |
| F-30 | §3, §12, §14.1, §14.2, §14.3 `POST /api/apply`, §14.4 Inbox |
| F-31 | §6, §9.0, §9.1 plan |
| F-32 | §7 (tiers, schemas, grounding, recording) |
| F-33 | §7.5 |
| F-34 | §8, §9 fill specs, §3 resume choice, §16 `resume_format` |
| F-35 | §10, §9.4 sign-up/in, §13 `ats_accounts` |
| F-36 | §11 |
| F-37 | §4.1, §4.2, §4.3, §9 confirmation rows |
| F-38 | §4.4, §8.3, §8.4 |
| F-39 | §7.8, §13 `apply_answers`, §14.4 |
| F-40 | §14.3 settings/accounts, §14.4, §16 |
| NF-01 | §8.1 (profile dir outside repo), §8.3, §10.3 CSV path, §5.1; the test is the tester's (paths: `data/applicant.yaml`, `data/apply/`, `data/edge_passwords_x.csv`) |
| NF-02 | §10, §11.1, §17, §5.3 |
| NF-03 | §7.6 (Ollama only), §14.3 (web unchanged: loopback) |
| NF-04 | §2 |
| NF-05 | §8.2 pace, §12 |
| NF-06 | §4.1 rule, §4.3 reaper, §12.1 (2), §13 unique index |
| NF-07 | §16 timeouts; §3 (schema plan before the browser) |
| NF-08 | §19 (lanes test on port 8768 with a copied DB; no live DB) |
| NF-09 | §17 |

---

## 19. Lanes

### 19.1 M20 (walking skeleton: Greenhouse dry run + one owner-triggered submission) — 3 lanes

| Lane | Branch | Files (only these) | Delivers |
|---|---|---|---|
| **P: profile + resolver** | `eng/M20-P-resolver` | `src/jobscraper/applicant.py`, `src/jobscraper/apply/resolve.py`, `src/jobscraper/apply/declarations.py`, `src/jobscraper/apply/__init__.py` (exact content §2.1), `src/jobscraper/backends.py`, `config/applicant.example.yaml`, `cli.py` (one new block: `applicant` verb) | §5.1–§5.4, §7 complete (tiers 1–5 incl. memory lookup through an injected callable), backend `format`/`temperature`/`seed`/`top_k` |
| **B: browser + Greenhouse + flow** | `eng/M20-B-greenhouse` | `src/jobscraper/apply/{__init__.py, detect.py, plan.py, classify.py, browser.py}`, `src/jobscraper/apply/ats/{__init__.py, greenhouse.py}`, `src/jobscraper/apply_flow.py`, `src/jobscraper/models.py` (+`posting_key`), `src/jobscraper/web/data.py` (import moved), `src/jobscraper/store.py` (one appended block: §13 tables + methods + `app_events.by`), `src/jobscraper/config.py` (ApplyConfig), `config/config.yaml` (`apply:` block), `requirements.txt` (`playwright`, `keyring`), `cli.py` (one new block: `apply` verb incl. `apply show`), `web/jobs.py` (kind `apply`) | §3, §4, §6, §7.7 context building (resume text, alias groups), §8, §9.0–§9.1, §12, §13, §14.1 `apply show`, §16, §17 |
| **T: deterministic tailor** | per `tailor_design.md` | per tailor design | the tailored DOCX/PDF for `tailor_for_apply` |

Disjointness: lanes P and B both create `apply/__init__.py` with the identical one-line content (git merges identical adds cleanly); `cli.py` gets one self-contained block per lane (Coordinator resolves the textual merge, `04_team.md` §2); `store.py` is touched by B and T, each appending its own block.

Integration order: P and T first (no browser); B builds against the contracts with a stub resolver (`resolve_all` returning tier-1 answers only) and a stub `tailor_for_apply` (returns the original resume), then a final B work package swaps in the real ones after P and T merge. `vault.py`, `mail.py`, Lever/Ashby/Workday and the web/UI are M21.

Dev rule (NF-08): every lane runs against a copied DB, web on port 8768; real Greenhouse pages only in `--dry-run` until the owner triggers the one M20 submission.

### 19.2 M21 (preview; the planner splits it)

Lane V: `vault.py`, `apply/mail.py`, `apply/edge_save.ps1`, CLI `accounts`/`mail`, Workday adapter. Lane L: Lever + Ashby adapters. Lane W: web routers `applicant.py`/`apply.py` + Vue (Profile form, attempt panel, audit view, Settings → Apply/Accounts). The tailor LLM layer is its own lane per the tailor design.

---

## 20. Pending items, deviations, PRD conflicts, requests

### 20.1 Pending spikes (build with the default now)

| Item | Default until settled |
|---|---|
| S-1c Edge sync from the app profile (owner test) | `edge_sync: false`, CSV export route; UIA Save click off |
| S-1e Edge CSV columns | `name,url,username,password,note`; owner verifies with a one-row import (first-export note) |
| S-3 Submit-time reCAPTCHA behaviour (R-3) | classifier as §8.4; the M20 owner submission is the evidence |
| S-4 Gmail IMAP + Greenhouse security-code format | `otp_pattern = [A-Za-z0-9]{8}` for Greenhouse, `\d{6}` default |
| Lever / Ashby / Workday ids marked K | confirm on a recorded fixture as the first step of each M21 adapter WP |

### 20.2 Additions and deviations (not conflicts)

- Reason codes `cancelled` and `mail_not_set_up` added to PRD §7.2's list (distinct owner actions).
- `vault.py` in the foundation instead of `apply/` (web needs it).
- `apply_flow` imports `tailor_flow` (one orchestrator→orchestrator edge).
- `app_events.by` column for "Applied by JobScraper".
- D-68 (planner gaps A-1..A-4): alias groups in `ResolveContext` for grounding rule 3; resume-text source decided by `apply_flow`; CLI `apply show`; `experience_months` defined as a merged-interval union (§5.1). Contract change is additive (two new `ResolveContext` fields with defaults).
- Tier-5 choice answers need two agreeing runs and a verbatim evidence quote (stricter than F-32's "one of the offered options").
- Attestation-like questions the classifier can't label never reach the LLM (fail closed).

### 20.3 PRD conflicts raised (not resolved here)

1. **F-12 says answer memory is "resolver tier 2"; F-32 lists it third** (after profile rules). This design follows F-32's order (memory = tier 3). Coordinator to confirm.
2. **F-22 stores "I have this" attested skills in "profile overrides"** (`config/profile.overrides.yaml`, an owner-protected, hand-edited, comment-bearing file under the read-only-in-Docker `config/`). The tailor design writes them to `data/applicant.yaml` → `attested_skills` instead. Coordinator to confirm (details in `tailor_design.md` §20).
3. **Scope:** `config/applicant.example.yaml` (PRD/Q-13 "template") is in no role's write scope (the engineer may write `config/config.yaml`, `config/rules.yaml` only). Request: add it to the software-engineer scope (lane P creates it from §5.4).
4. **Brief vs PRD path:** the brief proposed `config/applicant.yaml`; the PRD's `data/applicant.yaml` is used (PRD wins; recorded for the reader).

### 20.4 Requests to other roles

- **Tester (blocking the merge of this branch):** with only the contracts present, `test_every_v2_module_is_classified` fails ("modules ['apply'] belong to no layer"; and `tailor` once its contracts land). The §2.3 classification must be merged together with or before this branch. Also: `tests/test_layering.py` changes in §2.3; NF-01 `git check-ignore` test for `data/applicant.yaml`, `data/master_resume.json`, `data/tailored/x`, `data/apply/x`, `data/edge_passwords_x.csv`; Greenhouse fixtures from the spike's recorded schemas.
- **Researcher:** `config/questions.yaml` per §7.3.1 minimum content.
- **Planner:** OVERVIEW/README "never logs in anywhere" no longer true (Q-15).

## Sources (lookups this design made, 2026-11-01)

- Greenhouse Job Board API, `?questions=true` shapes and field types: https://docs.greenhouse.io/job-board.html (fetched).
- Workday `data-automation-id` values: GitHub code search for `legalNameSection_firstName`, `bottom-navigation-next-button`, `primaryQuestionnairePage`, `reviewJobApplicationPage`, `progressBarActiveStep`; files read: `ubangura/Workday-Application-Automator/apply.js`, `AbhishekMandapmalvi/AutoApply/bot/apply/workday.py` (read for selector facts only; neither is reused).
- Ashby form selectors: `galiprandi/job-seeker` `.agents/skills/browser-automation/references/ats-patterns.md`; GitHub code search `_systemfield_resume`.
- Spike S-1/S-3 report (local, merged on `personal`).
