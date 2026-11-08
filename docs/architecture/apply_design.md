# Auto-apply design (KA-1, KA-2, KA-3)

**Stage B dossier** for PRD F-10–F-12, F-30–F-40, NF-01–NF-09 (`docs/prd.md` r1). Queue Q-04. Author: architect, 2026-11-01.
**Status:** DRAFT for stage E cross-review; **D-70 delta (Q-22, 2026-11-02): Workday first-class in M20 (§9.4), MyGreenhouse autofill (§9.1.1), Greenhouse label rule (§9.1.2), `yes_if` (§7.3.3), backup email (§10.5, §11.5), `apply open-profile` (§14.1)**. **D-74/D-75 delta (Q-30, 2026-11-03): the Profile → Application details form and the applicant API move into M20, plus "Questions from applications" (F-13): capture, `extra:` answers, tier 3 reads them; work-rights `default` keys and the tier-2 kind `country_bool`. All in `questions_design.md`; the sections below point there.** **D-164..D-166 delta (Q-81, 2026-11-07): §7.5 gate 2 STATUS frame as closed label shapes (D-164), `willing_to_sign_nda` unset = no answer and the consent-verb list (D-165, §5.4 template line too), the NDA closed-vocabulary compound rule (D-166); contracts unchanged.** **D-169b delta (Q-80, 2026-11-08): §7.5 D-164 step 2 drops a MODAL run (can/could/would/will you [please]) only right before a LEAD; three pin rows; contracts unchanged.** **D-170 delta (Q-82, 2026-11-08): §7.5 D-164 shapes A/B (and the freedom path) answer a status declaration only when the whole label is one status question: closed-span vocabulary per class, one-clause rule, `status` only at the end of a class noun phrase, the same check on a single checkbox; Q-80 review MEDIUM 1–3 closed; no pin-table row changes; contracts unchanged.** **D-171 delta (Q-83, 2026-11-08): §7.5 D-170 refined: a trailing "if yes/so, please provide details" tail is dropped on Yes/No choices, class filler for the common real suffixes (narrowing words only for a false value), place words only as a qualifier after a class noun, the lead-in piece only first, "aware" for conflict of interest only, the applicant as the subject; employer-class compound kept recorded; Q-82 review MEDIUM 1–3 closed; contracts unchanged.** Contracts: `src/jobscraper/apply/contracts.py` (CONTRACT_VERSION 4; v3 and v4 are additive, §20.2). ADRs: `adr/0001` (browser route), `adr/0002` (vault), `adr/0003` (automatic submission, fail-closed resolution), `adr/0005` (answers in the profile file).
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
    accounts.py         identity choice (primary / backup email), pure                           (§10.5, D-70)
    ats/__init__.py     REGISTRY = {name: adapter instance}
    ats/greenhouse.py   (M20, + MyGreenhouse §9.1.1)  ats/workday.py + ats/workday_widgets.py (M20, D-70)
    ats/lever.py  ats/ashby.py   (M21)
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
    identity (§10.5): primary or backup email ─► sign in / sign up (one backup retry on "already registered")
    prefill: adapter.prefill() ─► "" | mygreenhouse (KEEP) | workday_last_application / site_default (OVERWRITE)
    filling (per step): read_step ─► resolve (DOM adapters) ─► read_values + prefill policy (§9.1.1, §9.4.6)
                        ─► fill ─► read back ─► screenshot ─► classify ─► next_step (Workday: one corrective retry, §9.4.9)
    review (Workday): parse + cross-check the answers (§9.4.10)
    review page reached:
       dry_run ─► ready_to_submit (tab stays open)
       auto    ─► record submit_clicked_at ─► submitting ─► submit ─► wait ≤ 60 s for confirmation
                    ─► submitted (Applications: applied, tailored file: sent) | submitted_unconfirmed
    any ApplyFailure ─► stop input, screenshot + HTML, failed(reason)
  after the last job: if any tab is ready_to_submit, hold the browser for apply.dry_run_hold_s, then close
```

`apply_flow.run(cfg, store, job_ids: list[str], *, dry_run: bool, backend, http=None, browser_factory=None) -> list[AttemptResult]` is the orchestrator's only public function (D-69: `http` = an object with `get_json(url, **kw)`, default `net.HttpClient` from config, handed to adapters as `AttemptContext.http`; `browser_factory` = a callable returning the §8.1 session, default Playwright Edge; both exist so tests inject fakes, e.g. a schema with an unanswerable required field fails before any browser is created); `cmd_apply` calls it and exits 0 if every attempt ended `submitted` or `ready_to_submit`, else 1.

---

## 4. Attempt state machine

### 4.1 States and transitions

States and the allowed automatic transitions are `AttemptState` and `TRANSITIONS` in the contracts. Every non-terminal state **except `submitting`** may go to `failed` (D-69, ADR-0004). The store method `set_attempt_state` MUST refuse a transition for which `can_transition(src, dst, clicked=<submit_clicked_at is set>)` is false (raise `ValueError`); this is the guard against a coding error re-entering `submitting` or failing a clicked attempt. With `clicked=True` only `POST_CLICK_STATES` are reachable, so `verifying_email` after a click can go only to `submitting` or `submitted_unconfirmed`.

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
| signing_up | signing_up | `sign_up()` returned `already_registered` for the primary email and a backup email is set: the one retry with the backup (§10.5, D-70) |
| signing_in | verifying_email | after sign-in the site asks to verify the email (classify `verify_email`) |
| signing_in | filling | signed in, form visible |
| verifying_email | signing_in | link opened; the site now shows sign-in |
| verifying_email | filling | link opened or code entered; form visible |
| verifying_email | submitting | emailed security code entered after Submit (§4.2) |
| verifying_email | submitted_unconfirmed | after a click only: no code within the timeout, no mail set up, or any exception/challenge (§4.2) |
| filling | filling | `next_step()` moved to another step (step id changes; `step` column updated) |
| filling | ready_to_submit | review page reached and `mode = dry_run` |
| filling | submitting | review page reached and `mode = auto`; `submit_clicked_at` written and committed **before** the click |
| submitting | submitted | `after_submit()` → `confirmed:<signal>` within `confirm_timeout_s` (60) |
| submitting | submitted_unconfirmed | no confirmation within 60 s, or any exception, captcha, bot challenge or error page after the click (`reason_detail` = a note such as "captcha after submit"; never retried) |
| submitting | verifying_email | `after_submit()` → `code_required` (Greenhouse security code) |
| any non-terminal except submitting, before the click | failed(reason) | `ApplyFailure`, any other exception (`error`), deadline passed (`error`, detail "timed out"), cancel (`cancelled`) |

Rule NF-06 (wins over every reason code, D-69): once `submit_clicked_at` is set, the attempt can only end `submitted` or `submitted_unconfirmed` — never `failed`, never another automatic Submit (except the single code re-submit in §4.2). A challenge, error or exception after the click → `submitted_unconfirmed` with a note in `reason_detail` (e.g. "captcha after submit", "error page after submit", "timed out"); it is never retried. `apply_flow` enforces this by catching every exception after the click; the contract (`TRANSITIONS` without `submitting → failed`, `can_transition(..., clicked=True)`) and the store guard enforce it again. Only the owner's "It didn't go through" (§4.3, a dedicated store method outside `TRANSITIONS`) can turn such an attempt into `failed`.

### 4.2 The emailed security code at Submit (Greenhouse)

Greenhouse may answer Submit with "enter the security code we emailed you" when reCAPTCHA is unsure (brief §2.1). Then: `submitting → verifying_email` (mail §11, adapter `otp_pattern`) → `enter_code()` → `verifying_email → submitting` → `submit()` once more → wait for confirmation as before. This second click completes the same submission and is allowed once per attempt (`apply_attempts.code_resubmits` ≤ 1). With no mail set up: `submitted_unconfirmed` (Submit was already clicked), detail `security code needed; mailbox not set up`.

### 4.3 Owner actions and the reaper

| Action (web, M21) | Store effect |
|---|---|
| "It went through" on `submitted_unconfirmed` | state → `submitted`, `confirmation='owner'`; Applications → `applied` (event by `jobscraper`); tailored file → `sent` |
| "It didn't go through" on `submitted_unconfirmed` | state → `failed`, reason `error`, detail `owner: not submitted`; this frees the posting for a new attempt |
| Cancel the running apply job | JobManager kills the tree; the reaper below closes the row |

**Reaper** (`store.reap_attempts(now) -> int`, D-69: the caller decides whether a job is running, so there is no `job_running` argument), run at the start of `apply_flow.run` and by `GET /api/apply/attempts` when no `apply` job is running: every attempt in a non-terminal state becomes `submitted_unconfirmed` if `submit_clicked_at` is set, else `failed(cancelled)` (detail `interrupted`). Never resubmits.

### 4.4 Reason codes

Owner-facing copy lives in `REASON_TEXTS` (contracts) and is written in one voice: what happened, whether anything was sent, what to do. `{detail}` never holds a personal value.

| Code | Trigger (exact) | Owner text (summary) | Recovery hint |
|---|---|---|---|
| `captcha` | `classify` sees a visible challenge widget (§8.4) **before** the Submit click (after the click it is `submitted_unconfirmed` with the note "captcha after submit", §4.1, D-69) | CAPTCHA, stopped, nothing sent | Apply by hand. If `captcha_wait_s` > 0 the tab stays open that long and a confirmation seen meanwhile turns it into `submitted` |
| `bot_challenge` | Cloudflare/Akamai/PerimeterX interstitial or block page (§8.4), or HTTP 403/429 on the apply page | bot check blocked | Apply by hand |
| `sms_or_2fa` | classify `two_factor` (phone/SMS/authenticator prompt) | phone or two-step code | Apply by hand |
| `login_failed` | sign-in error shown (detail: rejected password / account locked); a `signin_failed` row for this tenant (no automatic retry); or sign-up says the email already has an account, the vault has no entry and no unused backup email is left (details: §10.5 rules 2–3) | can't sign in | Check by hand; add the password in Settings → Accounts → "Add an existing account" |
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
def computed_facts(profile, today: datetime.date) -> dict   # {"experience_months": int, "experience_years": int, "graduation_year": int|None}
def from_resume(profile_derived: dict, master: dict|None) -> dict   # M21 prefill (§5.5)
```

**`computed_facts` (D-68 A-4).** `experience_months` = the length of the **union** of the intervals of every `experience[]` entry (internships included; `education[]` never counts), whole months rounded down:
- Month position of a date: `YYYY-MM` → `12·Y + (M−1)` (start of that month); `YYYY-MM-DD` → `12·Y + (M−1) + (D−1)/days_in_month`.
- Interval of an entry = `[pos(start), pos_end)`, where `pos_end` = `pos(end) + 1` for a `YYYY-MM` end (the end month counts in full), `pos(end) + 1/days_in_month` for a `YYYY-MM-DD` end (the end day counts), and `pos(today) + 1/days_in_month(today)` when `end` is null (present); every `pos_end` is clipped to that "today" value. An entry with no `start`, or with `start` after today, contributes nothing.
- Overlapping or touching intervals are merged; `experience_months = floor(Σ merged lengths)`; `experience_years = experience_months // 12`. Example: 2024-05 → 2024-08 plus 2024-07 → 2024-12 = one interval 2024-05 → 2024-12 = 8 months.
- `graduation_year` = the year of the latest `education[].end`, else None.

Saving drops YAML comments; the Profile form is the editor (the template's comments exist for the first hand-fill in M20). Key order is kept (`sort_keys=False`). D-74: before the first save that drops comments, `save` keeps a copy as `data/applicant.commented-backup.yaml`. Saves from the web are guarded by an etag. The optional `extra:` block holds the owner's answers to questions from applications (`questions_design.md` §3.1, §6.1).

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

**REQUIRED_PATHS** (auto-apply refuses without them, F-11): `identity.legal_first_name`, `identity.legal_last_name`, `contact.email`, `contact.phone_country_code`, `contact.phone_number`, `contact.city`, `contact.country`, `singapore_status.residency_status`, ~~`singapore_status.authorised_to_work.SG`~~, ~~`singapore_status.requires_sponsorship.SG`~~ (removed by D-75: always answerable from the country key, then `default`, then the standing answer, `questions_design.md` §8.1), `availability.notice_period_days`, `availability.earliest_start_date`, `pay.expected_salary.amount`, `education` (≥ 1 entry with institution, degree, end), `consents.privacy_consent`, `consents.certify_true`. Plus a resume file (`documents.resume` or `profile.resume_ingest.find_resume`) — reported as `documents.resume`.

**RECOMMENDED_PATHS** (meter only): `contact.address_line1`, `contact.postal_code`, `singapore_status.ns_status`, `singapore_status.race`, `links.linkedin`, `experience`, `skills`, `languages`, `sourcing.how_heard_default`, `identity.date_of_birth`.

### 5.3 Sensitive fields (S)

S paths: `identity.date_of_birth`, `identity.gender`, `singapore_status.residency_status`, `singapore_status.ns_status`, `singapore_status.ord_date`, `singapore_status.race`, `singapore_status.race_other`, `singapore_status.religion`, `singapore_status.marital_status`, `singapore_status.nric_last4`, `us_self_id.*`, `declarations.*`, `contact.*` except `city`/`country`.

S values are never in an LLM prompt (`llm_extract` excludes them), never in a log line (redaction), and answers that use them carry `sensitive=True` (shown first in the audit view). They are stored in `apply_answers.value` (local DB; NF-02 covers passwords only).

`llm_extract` allow-list: `education[]`, `experience[]` (all keys), `skills`, `attested_skills`, `languages`, `links`, `availability.*`, `pay.expected_salary`, `sourcing.how_heard_default`, `contact.city`, `contact.country`, `singapore_status.work_pass`, `singapore_status.authorised_to_work`, `singapore_status.requires_sponsorship`.

**Amendment D-105 (Q-74, ADR-0008, `q74_model_sees_sensitive.md`):** when config `apply.model_sees_sensitive` is true **and** the model backend is local (`backends.is_local`: Ollama on localhost/127.0.0.1/::1), `ResolveContext.model_sees_sensitive` is true. Then `llm_extract(profile, sensitive=True)` and `grounding_text(..., sensitive=True)` add the S paths (not `extra`), so S values may be in the tier-5 prompt and its grounding corpus (and in llm_fill's FACTS, q74 §4). A tier-5 answer that contains an S value carries `sensitive=True`. With a remote backend, or the switch off, the rule above stands unchanged. In every case, S values are never logged. The fail-closed routing (tier-1 `SENSITIVE_CANONICALS`, tier-2 sensitive stops, tier-4 locks, EEO by code) and the refusal to send a sensitive question for naming don't change: the switch widens what the model reads, not what it decides.

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
  authorised_to_work: {SG: true, default: true}      # D-75. default: every country you don't list; add exceptions, e.g. US: false
  requires_sponsorship: {SG: false, default: false}  # D-75. default: every country you don't list
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
  non_compete: false                 # D-87: any agreement that limits the work you can do: non-compete, non-solicitation, NDA or confidentiality, stock option or restricted stock terms
  government_employment: false       # D-87: ever worked for the government, public sector, a statutory board or the military, not counting National Service
  willing_to_sign_nda: null          # D-91/D-165: true | false | null. Willing to sign an employer's NDA or confidentiality agreement? Unset (null) = you are asked. NDA willingness questions only, never a non-compete
  health_disclosure: decline         # decline only; a required health question fails the attempt
  # D-87: us_self_id.disability_status answers every disability question, in any country (no separate key)
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
2  replace ’ ‘ ʼ ` with ' (curly → straight first)
3  delete "(required)", "(optional)", "*"
4  replace every run of chars not in [a-z0-9+#'] with one space; keep "'" inside words (D-69:
   "don't" stays "don't"); drop a "'" at a token's start or end and a trailing "'s" ("company's" → "company")
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
| EMAIL | `ctx.account_email` when set (the account identity, §10.5), else `contact.email` |
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

Loader (D-69): `resolve.load_rules(path) -> QuestionRules` (raises `ValueError` naming the bad key on an invalid file; a missing file → empty rules).

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

An `enum` entry may also carry `yes_if` rules for Yes/No labels (§7.3.3).

Selection: for each entry, score = token count of its longest matching synonym, 0 if any `exclude` phrase matches. The highest score wins; a tie between different keys → tier 2 does not answer (note `ambiguous: k1, k2`).

**Minimum content** the researcher MUST provide (keys and kinds; synonyms are theirs): `singapore_status.authorised_to_work` and `singapore_status.requires_sponsorship` (kind `country_bool`, D-75: replace the former `.SG`/`.US` bool rows; rules and minimum synonyms in `questions_design.md` §8.2–§8.3), `singapore_status.residency_status` (enum, S; value_map for citizen/pr/foreigner incl. "Singapore Citizen or PR" style options), `singapore_status.nationality` (country), `singapore_status.work_pass` (enum), `singapore_status.ns_status` (enum, S), `singapore_status.race` (enum, S), `identity.gender` (enum, S), `identity.date_of_birth` (date, S), `availability.notice_period_days` (number), `availability.earliest_start_date` (date), `availability.willing_to_relocate` (bool), `availability.willing_to_travel_pct` (number), `pay.expected_salary` (salary), `pay.current_salary` (salary), `education[0].institution` / `.degree` / `.major` / `.end` / `.grade` (text/date), `computed.experience_years` (number), `computed.graduation_year` (number), `links.linkedin` / `links.github` / `links.portfolio` (url), `sourcing.how_heard_default` (text), `consents.certify_true` (bool; "information provided is true", "accurate and complete"), `consents.privacy_consent` (bool), `languages` (text: "English (native), …"), `identity.preferred_name` (text).

#### 7.3.2 Mapping a profile value onto offered options

Normalise every option label with §7.1.

- **bool:** yes-labels = label equals or starts with one of `yes`, `y`, `true`, `i am`, `i do`, `i have`, `i will`, `i can`, `authorised`, `authorized`; no-labels = equals or starts with `no`, `n`, `false`, `i am not`, `i do not`, `i don't`, `i dont`, `i have not`, `i will not`, `not`. No-prefixes are tested first (so "i am not" never counts as yes). Exactly one option of the right polarity → answer; else no answer. Text inputs get "Yes"/"No". Single checkbox: tick for true.
- **enum:** candidates = options whose label equals a `value_map` phrase, else whose label contains one as a phrase; then the enum value itself with `_`→space. Exactly one candidate → answer.
- **decline values:** an option whose label contains (phrase match, §7.1) any of: `decline`, `prefer not`, `choose not`, `not wish`, `don't wish`, `dont wish`, `do not wish`, `rather not`, `not to disclose`, `not to answer`, `not to say`, `don't want to answer`, `do not want to answer` (D-69; "I don't wish to answer" → `i don't wish to answer` matches `don't wish`). None offered and the field is required → `unknown`; optional → `blank_optional`.
- **number:** text inputs get the integer. Range options (`"0-1 years"`, `"S$3,000 - S$4,000"`, `"Below 3000"`, `"5000 and above"`, `"3k–4k"`): parse with `(\d[\d,]*(?:\.\d+)?)\s*(k)?` pairs; `below|under|less than` → (−∞, x); `above|over|more than|and above|\+` → (x, ∞). Pick the unique range containing the value (inclusive).
- **salary:** period from the label: `annual|annum|yearly|per year|p a` → annual; `month|monthly|per month` → monthly; else the profile's period. annual = monthly × `pay.months_per_year`. A currency named in the label or options that is not the profile's currency → no answer. Text input value: digits only (e.g. `5000`). `current_salary: null` → text "0" if the label says "current" and the field is required, else blank.
- **date:** ISO from the profile; the adapter formats it.
- **country:** ISO → name table; option equal to the name or containing it.
- **url / text:** the value as is; truncated never — over `max_length` → no answer.

#### 7.3.3 Yes/No labels answered from an enum key: `yes_if` (D-70; researcher's gap)

An enum key cannot answer a Yes/No question by §7.3.2 ("Are you a Singapore Citizen?" offers Yes/No, not citizen/pr/foreigner). An enum entry in `questions.yaml` may therefore carry `yes_if` rules:

```yaml
  - key: singapore_status.residency_status
    kind: enum
    sensitive: true
    synonyms: [...]
    value_map: {...}
    yes_if:                                   # optional; kind enum only
      - id: sg_citizen                        # [a-z0-9_]+, unique within the key
        values: [citizen]                     # enum values that mean Yes (a subset of value_map's keys)
        synonyms: [are you a singapore citizen, singapore citizen, singaporean]
        exclude: [or permanent resident, or pr]
      - id: sg_citizen_or_pr
        values: [citizen, pr]
        synonyms: [singapore citizen or permanent resident, singapore citizen or pr, citizen or pr]
      - id: sg_pr
        values: [pr]
        synonyms: [singapore permanent resident, singapore pr, permanent resident of singapore]
        exclude: [citizen]
```

**Loader** (`resolve.load_rules`): `yes_if` only on `kind: enum`; each rule needs `id`, non-empty `values` ⊆ the entry's `value_map` keys, non-empty `synonyms`; `exclude` optional. Anything else → `ValueError` naming `<key>#<id>`. Each rule becomes a **virtual entry** with key `<key>#<id>`, kind `bool`, `sensitive` inherited from its parent.

**Bool-shaped field:** a single CHECKBOX; or a DROPDOWN/RADIO whose options contain exactly one yes-polarity and exactly one no-polarity option by §7.3.2's bool rule, plus at most one decline option (§7.3.2 decline phrases) and nothing else.

**Candidate entries for a field** (then §7.3.1 scoring, unchanged: longest matching synonym, `exclude` → 0, a tie between different keys → no tier-2 answer):
- bool-shaped field → plain `bool` entries + virtual `yes_if` entries (plain `enum` entries are dropped: their values can't be offered as Yes/No);
- other choice fields (DROPDOWN, RADIO, MULTI_CHOICE) → plain entries only (virtual entries dropped);
- TEXT / TEXTAREA → plain entries, plus virtual entries only when the normalised label's first token is one of `are, is, do, does, have, has, will, would, can, were, was` (a question; the answer is the text "Yes"/"No").

**Value:** `v` = the profile value at the parent key. `v` empty → no answer (sensitive → `unknown`, never tier 5). `v == "decline"` → the decline option if offered, else no answer. Otherwise `answer = v in values`, mapped onto the options by §7.3.2 bool (single checkbox: tick for True). `source = "profile:<key>"`, `rule_id = "<key>#<id>"`, confidence 0.95, `sensitive` = the parent's.

**Worked examples** (residency `citizen`): "Are you a Singapore Citizen?" Yes/No → `sg_citizen` (5 tokens) → Yes. "Are you a Singapore Citizen or Permanent Resident?" Yes/No → `sg_citizen` is excluded ("or permanent resident"), `sg_citizen_or_pr` (5 tokens) → Yes; with residency `foreigner` → No. "Singapore Citizen / PR" with options "Singapore Citizen", "Singapore PR", "Foreigner" → not bool-shaped → the plain enum entry and its `value_map` (§7.3.2), unchanged. The researcher adds `yes_if` content to `config/questions.yaml` (WP-A03); `work_pass` and `ns_status` may get rules the same way (e.g. `ns_completed: values [completed]` for "Have you completed National Service?").

### 7.4 Tier 3: answer memory (confidence 0.95; F-12, M22 writes, M20 reads)

**D-74 (ADR-0005):** tier 3 first reads the profile's `extra:` answers (the owner's answers to questions from applications), matched by normalised label, then by option `picks`, with employer overrides (`questions_design.md` §6.2, `source = "memory:extra.<key>"`). It is also consulted when tier 2 stops on a sensitive no-fit. After that comes the lookup below, unchanged. The `answer_memory` table is frozen: M22's corrections write `extra` instead.

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
| `non_compete` (widened by D-87: any agreement that limits the work you can do) | non compete, non competes, noncompete, non competition, non solicitation, non solicit, nonsolicitation, non disclosure, nondisclosure, nda, ndas, confidentiality agreement, confidentiality agreements, confidentiality obligation, confidentiality obligations, restrictive covenant, restrictive covenants, restrictive agreement, restrictive agreements, restraint of trade, garden leave, bound by any agreement, agreement that restricts, agreements that restrict, agreement that would restrict, agreement restricting, agreements restricting, agreement that prevents, agreement that would prevent, agreement that prohibits, agreement that would prohibit, stock option agreement, stock option agreements, stock option or restricted stock, restricted stock grant, restricted stock agreement, restricted stock unit agreement, stock grant agreement, equity grant agreement (not "subject to any restrictions": work-rights questions use it) |
| `government_employment` (D-87) | civil service, civil servant, civil servants, public service, public servant, public sector, public officer, government service, government employee, government employees, government employment, government agency, government agencies, government ministry, government department, government body, government bodies, statutory board, statutory boards, government official, public official, worked for the government, worked for government, worked for a government, worked for any government, worked in the government, worked in government, work for the government, working for the government, employed by the government, employed by government, employed by a government, employed by any government, employed in the government, employed in government, have you worked in government, have you worked in the government, have you worked in the public sector, have you worked in the public service, have you worked in the civil service. Subject to the government/NS rule below |
| `health` | medical condition, health condition, mental health, medical history, illness |
| `disability` (D-87; **label only**, never the description: EEO preambles mention disability; **D-90 gate 5:** status frames only) | disability, disabilities, disabled, person with disability, persons with disabilities, people with disabilities, pwd, pwds, handicap, handicapped |
| `prior_employment_at_company` (**D-90 gate 4:** only when the label names this employer, else unsure) | previously worked, previously employed, previously been employed, worked for us, worked for, employed by, former employee, ex employee, have you worked, currently or previously employed |
| `current_employee_at_company` (D-69; **D-90 gate 4:** only when the label names this employer, else unsure) | currently an employee, current employee, currently employed, currently work for, currently working for, currently work at, currently working at, employee at, employee of |
| `previously_applied` | previously applied, applied before, have you applied, applied to this, applied for a position |

**Precedence (D-69):** when both `current_employee_at_company` and `prior_employment_at_company` match, the label is `prior_employment_at_company` if the text contains `previously`, `ever`, `before`, `former` or `ex` (as tokens), else `current_employee_at_company`; this pair alone never yields `AMBIGUOUS`. `AMBIGUOUS` is a module-level sentinel `declarations.AMBIGUOUS` (not a `DeclarationLabel` member).

**D-87 classifier additions (Q-48; the owner's rule: declaration-type questions default to No / none / not applicable).** `classify_all(label_norm, description_norm="") -> tuple[frozenset[DeclarationLabel], bool]` returns (classes, unsure). `classify()` is built on it and keeps its contract: unsure → `AMBIGUOUS`; one class → that class; two or more → `AMBIGUOUS`; none → the marker rule above. Steps:

1. Phrase hits (table; `disability` on the label only).
2. **Longest match (R1):** a class's hit is dropped when every span it matched lies inside a longer matched span of another class. This changes nothing on the pre-D-87 table. It lets "worked for the government" beat `prior_employment_at_company`'s "worked for", "employed by the government" beat "employed by", and `pep`'s "senior government official" beat "government official".
   - **D-89 (overlap, not only containment):** a `prior_employment_at_company` or `current_employee_at_company` span that overlaps a `government_employment` span (shares a token with it) is also dropped. So "Have you previously worked for the government?", "Are you currently employed by the government?" and "…by a government agency/body" are `government_employment`. Exceptions: the class survives through any span that touches no government span ("worked for us": F18 stays `AMBIGUOUS`), and the drop is skipped when the label names this employer (the token `us` or `our`, or a run that `company_match`es a name in `employer_names`; `classify_all(..., employer_names=())` is an additive keyword, and tier 4 and L3 pass `(ctx.employer_name, *ctx.employer_aliases)`). The government/NS rule (step 4) is unchanged.
3. The D-69 pair (above).
4. **Government/NS rule.** *gov* = a `government_employment` hit after R1. *mil* = a MILITARY term: military, armed forces, armed services, defence force, defence forces, defense force, army, navy, air force, national service, ns, nsf, nsman, saf, conscription, uniformed service, uniformed services. *excl* = an **NS exclusion**: an exclusion run (excluding, exclude, excludes, except, other than, apart from, aside from, besides, save for, not including, not counting, does not include, do not include) with an NS term starting within the next 4 tokens, or an NS term followed within 3 tokens by not included / excluded / not counted / does not count. NS terms: national service, full time national service, ns, nsf, mandatory military service, compulsory military service, mandatory national service, military service, mandatory service, compulsory service, conscription. *unsure* = government linked, glc, glcs, government owned, state owned, state enterprise.
   - (gov or mil) and excl, not unsure → `government_employment`.
   - gov, no mil, not unsure → `government_employment` (the owner's reading: NS is not government employment).
   - gov with (mil and no excl), or gov with unsure → unsure (`AMBIGUOUS`: unknown, never No).
   - mil without excl and no gov → not `government_employment`. An NS-inclusive question belongs to `ns_status` (tier-2 `yes_if`, LF L5); when no NS rule answers it, it is captured (LF G7, D-88).
5. A `disability` label that also has veteran, gender, race, ethnic, ethnicity, religion or marital → unsure.

`STANDING_DECLARATIONS` (employer-independent; a `declarations.py` constant): `pep`, `conflict_audit_independence`, `criminal_record`, `bankruptcy`, `regulatory_disciplinary`, `non_compete`, `government_employment`.

**Rules:**

- `AMBIGUOUS` → required: `unknown` (detail = label); optional: `blank_optional`. Never tier 5. **Except the agreement rule (D-87),** applied inside `answer()`: `classify_all` gives 2+ classes, not unsure, all in `STANDING_DECLARATIONS`, the field is not a single CHECKBOX, and every class has the same truth value → that bool by §7.3.2. `rule_id` and the source suffix = the sorted class values joined by `+` (e.g. `conflict_audit_independence+non_compete`), note `agreed: <classes>`. A set with an employer-specific class, `health` or `disability` stays `AMBIGUOUS`: D-70's prefill overwrite and the L6 skip key off a single class. A multi-class single checkbox stays `AMBIGUOUS` (ADR-0003: a tick is a signed statement, and token rules can't tell each class's polarity, e.g. "I have no conflict of interest and am bound by a non-compete").
- **D-90 gates (Q-48 review F1–F5; ADR-0003).** A declaration class (tier 4 and lock L3) answers only when all five gates hold; otherwise required → `unknown` (Questions inbox, `attestation_unclear`), optional → `blank_optional`. There is one implementation, in `declarations` (`answer()` runs it; `locks._declaration_lock` delegates to it and keeps no copy of the lists), plus one NS-exclusion helper `declarations.strip_ns_exclusions` that `locks` reuses (review F10).
  1. **Field type:** DROPDOWN/RADIO (Yes/No included) or a single CHECKBOX. TEXT/TYPEAHEAD only when the label's first token is a §5.4 question starter (are, is, do, does, have, has, will, would, can, were, was, did). Never a TEXTAREA or any other type. Note "not a yes/no question".
  2. **Status frame, never willingness:** the label has no WILLINGNESS entry (tokens willing, willingness, agree, agrees, consent, accept, acknowledge, acknowledgement, comply, abide, understand, read, prepared; runs able to sign, will you sign, would you sign, can you sign) **and** has a STATUS frame (runs have you, has, are you, is, were you, was, did you, do you have, do you hold, does, bound by, subject to, party to, signed, convicted, charged, i am, i have, i do not, i hold, there is, there are). "confirm" is neither: "I confirm I am not a PEP" is a real attestation. Note "not a status question".
     - **D-164 (Q-81; review F12, F13): the STATUS frame is a closed list of label shapes. It supersedes the run list in the line above** (the willingness test in that line is unchanged). One helper, `declarations.question_frame(label_toks, classes, f) -> bool`, replaces `_status_frame`. It runs for every bool answer on a non-checkbox field except `nda_willingness`, **including the D-91 freedom path** (F12), and for the agreement rule with the agreed class set. Single checkboxes keep the attestation rules of gate 3. On the `norm_label` tokens:
       1. Drop a trailing answer hint (`ANSWER_HINTS`). Then drop leading PREFIX runs, at most 3 tokens in total: please, kindly, declaration, declarations, self declaration, note, question, important.
       2. Drop an optional LEAD (confirm, indicate, state, specify, advise, tell us, let us know), then an optional if, whether or that.
          - **D-169b (Q-80):** a MODAL run (can you, could you, would you, will you), optionally followed by please, is dropped only when a LEAD comes immediately after it; the LEAD is then dropped as above, so shape B applies. A modal anywhere else is not dropped and gives no frame. It is not a PREFIX run and does not count toward the 3-token cap. Why: D-91 pins "Can you confirm you are clear of any conflict of interest?" → Yes, and a modal before a LEAD only rewords the LEAD request; it adds no new question shape.
       3. What is left has a frame when one shape holds:
          - **A, direct:** its first token is a status starter (are, is, do, does, did, have, has, had, was, were); or it starts with i am, i have, i hold, there is, there are; or it contains a status run anywhere (bound by, subject to, party to, signed, convicted, charged, hold, holds, held). **D-170:** `status` is no longer a run anywhere; it opens shape A only as the last token of a class noun phrase (D-170 rule 4).
          - **B, indirect (only after a LEAD):** it starts with you are, you're, you have, you've, you were, you had, you hold, you do, you did.
          - **D-170:** for a status class set (every class in `STANDING_DECLARATIONS` ∪ {disability}), A or B counts only when D-170 rules 1–3 also hold; otherwise shape C is tried next, as for any label.
          - **C, noun phrase:** the field is a DROPDOWN or RADIO and `bool_shaped`. Every class is in NOUN_CLASSES (pep, conflict_audit_independence, criminal_record, bankruptcy, regulatory_disciplinary, government_employment, disability). At most 6 tokens are left. Each of them lies inside a matched phrase span of those classes or is in NOUN_FILLER (a, an, the, any, of, or, person, persons, record, records, history, status, declaration, employment, action, actions, case, cases). The label has no NDA object. Excluded: `non_compete` and NDA objects (a bare "Non-compete agreement?" or "Confidentiality agreement" may mean "will you sign one"), the employer classes (gate 4) and `health`.
       4. Gate 1 for TEXT/TYPEAHEAD drops the step-1 PREFIX runs before it tests the first token. It never drops the MODAL run or the LEAD and never uses shape C.
       - Why: D-87 (the owner wants declarations answered, never asked) weighed against ADR-0003 (fail closed). A closed shape list answers the common forms and every shape can be pinned. The multi-word frames (are you, have you, do you have) were not accepted anywhere in the label: that would admit sentences whose main clause is not about the applicant's status. Willingness (gate 2), negation (gate 3), employer (gate 4) and disability (gate 5) still run first.
       - Oracles (a Yes/No dropdown unless stated; sample profile with every declaration false, `disability_status: no`):

         | Label | Result |
         |---|---|
         | Politically exposed person (PEP)? · Criminal record · Bankruptcy | No (C) |
         | Criminal record or bankruptcy | No (C, D-87 agreement rule) |
         | Disability (with `disability_status` no / yes / decline) | No / Yes / the decline option, else unknown (C) |
         | Declaration: Are you a politically exposed person? · Note: Do you have a non-compete? | No (PREFIX, A) |
         | Please confirm: Are you a PEP? | No (PREFIX, LEAD, A) |
         | Please indicate if you have ever been bankrupt | No (PREFIX, LEAD, B) |
         | Confirm you are free from any restrictive covenants | Yes (LEAD, B, freedom form) |
         | Can you confirm you are clear of any conflict of interest? | Yes (MODAL, LEAD, B, freedom form; `conflict_audit_independence: false`; D-91 pin, D-169b) |
         | Can you tell us whether you are a PEP? | No (MODAL, LEAD, B; D-169b) |
         | Can you sign a non-compete? | unknown (MODAL with no LEAD after it: no frame; gate 2 willingness also fails; D-169b) |
         | Free from any restrictive covenants? | unknown (no frame; F12) |
         | Non-compete agreement? · Confidentiality agreement · Criminal record check | unknown (C excludes the class or the token) |
         | Politically exposed person (PEP)? as TEXT · as a single checkbox | unknown (gate 1 · checkbox statement not recognised) |
         | Declaration: Are you a PEP? as TEXT · Please indicate if you have ever been bankrupt as TEXT | No · unknown (gate 1 drops PREFIX only) |
         | Former employee? | unknown (gate 4) |
     - **D-170 (Q-82; review `docs/reviews/Q-80-declarations.md` MEDIUM 1–3): a status declaration is answered only when the whole label is one status question about the applicant.** One helper, `declarations._one_status_question(toks, classes, employer_names, extra_runs=())`. It runs after shape A or B matches for a status class set (every class in STATUS_CLASSES = `STANDING_DECLARATIONS` ∪ {disability}), on the D-91 freedom path too (that path runs the frame). If it fails, shape C is tried next; if that fails too, the label ends as today: "not a status question", required `unknown`, optional `blank_optional`. No new reason code and no new note text. The employer classes (shareholding, relatives, prior and current employment, previously applied) keep D-164 unchanged: their phrases are relations whose object is the employer, which gate 4 and `company_match` already check, and their compounds are left to the F7 rule. `toks` = the tokens left after D-164 steps 1–2 (answer hint, PREFIX, MODAL + LEAD, link), with the NS-exclusion runs removed (`strip_ns_exclusions`).
       1. **Closed span (MEDIUM 1, 2).** Every token must be covered by one of these:
          - a class-phrase span of `classes` (the phrase table above; for `government_employment` the MILITARY terms count too, so the D-87 "(gov or mil) and excl" case keeps its answer);
          - a status run (bound by, subject to, party to, signed, convicted, charged, hold, holds, held);
          - a D-91 freedom run (free from/of, clear of/from, unrestricted by, unencumbered by, not bound by, not subject to, not party to);
          - an `extra_runs` span (rule 5 only);
          - a reference to this employer: THIS_EMPLOYER_RUNS, or a run whose `_company_tokens` are **equal** to those of the employer or an alias (equality, not the `company_match` prefix rule, so "acme and relocate" covers only "acme");
          - a number of 1–3 digits;
          - a token in SHARED_FILLER or in the CLASS_FILLER of one of the classes (below).
          Any other token ("check", "lawyer", "screening", "firm", "relocate", "eligible", "right", "valid") → rule fails. So a class phrase that only modifies another noun ("bankruptcy lawyer", "PEP screening officer", "criminal record check") fails, because the head noun is not filler: the class phrase must be the status complement (MEDIUM 2). A second clause about something else ("… and able to relocate") fails the same way (MEDIUM 1).
       2. **Every class is named in the label.** Each class has at least one span in `toks`. A class matched only through the field description gives no frame.
       3. **One question (MEDIUM 1).** Cut `toks` before each `and` / `or` that is followed by a status starter (are, is, do, does, did, have, has, had, was, were) or a subject (you, i, you're, you've, i'm). Each piece must hold a class span or a status run, or be made only of SHARED_FILLER (a bare lead-in, as in "Are you, or have you ever been, …"). Why: "Are you subject to a non-compete and are you working in Singapore?" uses only listed words but asks two questions.
       4. **`status` only at the end (MEDIUM 3).** `status` opens shape A only as the last token, after a noun phrase whose other tokens are class spans, NOUN_FILLER or "your": "Non-compete status" and "Please state your bankruptcy status" have a frame, but "Criminal record check status" does not ("check" breaks the noun phrase; shape C rejects it too). Rule 1 still runs after it.
       5. **Single checkbox (gate 3).** Once a polarity is found (attestation run or freedom run), rules 1–3 run on the statement left after its attestation lead (i confirm [that], i declare [that], i certify [that], i hereby …, i can confirm, i attest). The negative and positive attestation runs are passed as `extra_runs`. Otherwise the box is not ticked: required → `unknown`, note "checkbox statement not recognised". `nda_willingness` keeps D-166 and is out of scope here.
       - **Vocabulary** (closed: `declarations._STATUS_FILLER` and `_CLASS_FILLER`; 72 shared + 147 per class). Adding a word changes the spec and needs a pin.
         - SHARED (72): i, you, you're, you've, i'm, there, are, is, am, was, were, be, been, being, do, does, did, have, has, had; ever, currently, presently, now, previously, formerly, otherwise, still, past, last, year, years; a, an, the, any, such, other, your, all, either; or, and, as, of, in, to, for, from, by, with, at, under, within, during, since, against, including, e, g; country, countries, jurisdiction, jurisdictions, singapore, elsewhere, overseas, anywhere; aware, status, defined, subject.
         - `pep` (10): person, persons, people, individual, served, serving, senior, prominent, position, positions.
         - `conflict_audit_independence` (11): potential, actual, perceived, client, clients, auditor, auditors, issue, issues, government, rules.
         - `criminal_record` (25): crime, crimes, guilty, found, conviction, convictions, charge, charges, arrested, record, records, history, court, law, laws, case, cases, offences, offenses, felony, felonies, misdemeanor, misdemeanour, pending, proceedings.
         - `bankruptcy` (13): declared, adjudged, undischarged, discharged, debt, debts, petition, petitions, proceedings, order, orders, record, history.
         - `regulatory_disciplinary` (20): action, actions, proceedings, sanction, sanctions, sanctioned, investigation, investigations, body, bodies, authority, authorities, regulator, regulators, professional, revoked, penalty, penalties, record, history.
         - `non_compete` (47; sized by the live Q-48 F1 label, which must stay No): agreement, agreements, restriction, restrictions, restrict, restricts, restricted, obligation, obligations, clause, clauses, contract, contracts, contractual, accepted, entered, into, prohibit, prohibits, prevent, prevents, limit, limits, that, which, would, will, may, could, join, joining, job, role, responsibilities, duties, working, perform, current, former, previous, prior, employer, employers, pursuant, applicable, effect, active.
         - `government_employment` (12): worked, work, working, served, serving, employed, position, positions, role, roles, capacity, member.
         - `disability` (9): consider, yourself, identify, living, person, persons, people, record, history.
         - Left out on purpose: that (outside `non_compete`), check, certificate, lawyer, firm, holder, public, officer, screening, training, required, mandatory, right, valid, permit, eligible, able, relocate, like, buy, terms, and the negations (not, no, never are only covered inside a freedom or attestation run).
       - Why: D-166's closed vocabulary, applied to every status declaration. Token rules can't parse a sentence. An allow-list fails closed: an unseen word costs the owner one answer in the Questions inbox, which tier 3 then reuses. A wrong No on a form that submits itself is a false attestation (ADR-0003). The per-class filler keeps D-87: every D-164/D-169b row above and every Q-48, D-89, D-90a and D-91 pin keeps its result. Rejected:
         - (a) A coordinator-only test, as the review proposed. It misses "bankruptcy lawyer" and "PEP screening officer" (MEDIUM 2).
         - (b) A free prepositional tail after the class phrase. It reopens "… of a crime and able to relocate".
         - (c) A length cap. It breaks Q-48 F1, a real Workday label of about 70 tokens.
       - Residual (recorded, not fixed): an employer-class compound without a question starter after its `and` ("Do you hold shares in this company and a valid visa?") is still answered from the class; checkbox and dropdown labels outside the status classes are unchanged.
       - Oracles D-170 (a Yes/No dropdown unless stated; employer Acme; sample profile, every declaration false; `disability_status: no` where stated). The first 20 rows are the review's wrong answers and new probes, now unknown. The rest keep their results:

         | Label | Result |
         |---|---|
         | Do you have a criminal record check certificate? | unknown (1: check, certificate) |
         | Do you have a bankruptcy lawyer? | unknown (1: lawyer) |
         | Is a criminal record check required for your visa? | unknown (1) |
         | Are you aware that a criminal record check is mandatory? | unknown (1: that, check, mandatory) |
         | Is the criminal record check status satisfactory? | unknown (1) |
         | Criminal record check status | unknown (4: no frame; C rejects "check") |
         | Do you hold a valid work permit and have you been convicted of a crime? | unknown (1: valid, work, permit; 3) |
         | Are you currently a PEP screening officer? | unknown (1) |
         | Is your status as a criminal record holder public? | unknown (1: holder, public) |
         | Do you hold any regulatory disciplinary action training certificates? | unknown (1: training, certificates) |
         | Indicate whether you have worked in a bankruptcy law firm | unknown (1: worked, law, firm are not bankruptcy filler) |
         | Confirm you are a PEP screening analyst | unknown (1) |
         | Confirm you have the right to work and you are a PEP | unknown (1: right, work; 3: first piece has no class) |
         | Can you confirm you are free from any restrictive covenants and able to relocate? | unknown (1: able, relocate) |
         | Confirm you are free from any restrictive covenants and eligible to work in Singapore | unknown (1: eligible, work) |
         | Important: Do you have a criminal record check? (dropdown and TEXT) | unknown (1) |
         | Do you have a non-compete you'd like us to buy out? | unknown (1: you'd, like, buy, out; was No, "arguable" in the review) |
         | Are you subject to a non-compete and are you working in Singapore? | unknown (3: the second piece has no class) |
         | Single checkbox "I am not bound by any non-compete and I can relocate" (required) | not ticked → unknown (5) |
         | "Do you have any?" with description "Criminal record" | unknown (2: the class is named only in the description) |
         | Have you ever been convicted of a crime? · Have you ever been convicted of a criminal offence? (Yes/No) | No |
         | Have you been convicted of an offence or declared bankrupt? | No (agreement rule) |
         | Are you, or have you ever been, a senior government official? | No (3: "are you" is a lead-in) |
         | Have you held public office or worked in the civil service? | No (agreement rule; "worked" is `government_employment` filler) |
         | Have you ever worked for the Government (excluding mandatory military service)? | No (NS strip) |
         | Have you worked for any government body in the past? | No |
         | Are you aware of any conflict of interest with Acme? | No (employer span) |
         | Q-48 F1 label (`F1_LABEL`, `test_apply_declarations_q48.py`) | No (agreement: `conflict_audit_independence+non_compete`) |
         | Are you bound by any agreement such as a non-compete? · Are you bound by any non-compete? | No |
         | Have you been subject to any regulatory or disciplinary action? · Have you ever been declared bankrupt? | No |
         | Are you unrestricted by any non-compete or non-solicitation obligations? · Are you free from any restrictive covenants? | Yes (D-91) |
         | Non-compete status · Please state your bankruptcy status | No (4) |
         | Let us know if you were a politically exposed person · Specify if you have a criminal record and the offence | No · No (the review's "benign" row: "offence" is a class phrase) |
         | Are you a person with disability (PWD)? (`disability_status: no`) | No |
         | Single checkbox "I confirm I am not bound by any restrictive agreement" | ticked (5) |
         | Do you know anyone who works at Acme? | No (employer class: D-170 does not run) |
         | Every D-164 / D-169b row above | unchanged |
     - **D-171 (Q-83; review `docs/reviews/Q-82-declarations.md` MEDIUM 1–4): D-170 refined. No D-170 over-answer reopens.** Same helper, same notes, no new reason code. Owner intent D-87 (answer the standard declarations, never ask) weighed against ADR-0003 (fail closed).
       1. **Details tail (MEDIUM 2a).** D-164 step 1 becomes: drop a trailing answer hint; then, **only on a Yes/No DROPDOWN or RADIO** (`bool_shaped`), a trailing DETAILS TAIL; then a trailing answer hint again. DETAILS TAIL = `if yes` or `if so`, then optional please / kindly, then one VERB (provide, give, explain, specify, describe, elaborate, list, state), then 0–6 TAIL_OBJECT tokens (details, detail, further, more, full, brief, below, the, a, an, explanation, description, information, particulars, in, box, field, space, provided), running to the end of the label. Only the last `if yes` / `if so` is tried, and at least one token must stay before it. Any other tail ("If yes, please provide your position", "If so, when?") stays in and fails rule 1. On TEXT / TYPEAHEAD the tail is never dropped: that box asks for the details, so it ends `unknown`. `negated_question` and `_freedom_inverts` use the same strip. The tail has no negation in it, and the strip lets a mid-label "(Yes/No) If yes …" lose its hint too. Shape C sees the stripped tokens, so "Criminal record? If yes, please provide details." answers.
       2. **Vocabulary (MEDIUM 2b).** Every addition is class filler. None is a class phrase, because a phrase widens classification and D-171 changes only the frame test.
          - SHARED: + month, months (as year, years).
          - `conflict_audit_independence`: + aware (moved from SHARED, item 5).
          - `criminal_record`: + pleaded, plead (pleaded guilty), one ("… or pleaded guilty to one"), investigation (under investigation).
          - `bankruptcy`: + filed, personal (filed for personal bankruptcy), entered, into, individual, voluntary, arrangement, arrangements (an IVA is an insolvency procedure, the same class).
          - `regulatory_disciplinary`: + licence, license, licences, licenses ("suspended" is already a phrase, "revoked" already filler), disciplined.
          - `government_employment`: + current, former.
          - `non_compete`: + ability, work ("an agreement that restricts your ability to work for Acme"). "work" is not a PLACE_ANCHOR, so "… and work in Singapore" still fails.
          - **NARROWING** (`criminal_record`, 7): excluding, than, minor, traffic, violation, violations, unspent ("other" is already SHARED). These count only when the declaration value is **false** (taken before a D-91 inversion). A narrowed question keeps a true No. A Yes to "convicted, excluding minor traffic offences?" or "any unspent convictions?" may be false, so with a true value they are not covered and the field ends `unknown`.
          - Not added, recorded: "found guilty", "court order or injunction", "refused entry or deported", "dismissed or asked to resign", "disqualified as a director", "outstanding legal proceedings". These six labels are not declarations at all (classification, not D-170); they are a follow-up. Left unknown on purpose: "aware of any conflict of interest that may arise from your employment at Acme" (arguable), "crime involving dishonesty", "debarred by any government agency", "financial or business relationship … independence", "senior political figure" (each adds a second concept).
       3. **Places (MEDIUM 1).** singapore, country, countries, jurisdiction, jurisdictions, elsewhere, overseas and anywhere leave SHARED. They are covered only inside a PLACE QUALIFIER:
          - Form: one of in / within / of / from, then up to 2 of any / the / other / a / all, then a place noun (singapore, country, countries, jurisdiction, jurisdictions). Or a bare place adverb (elsewhere, overseas, anywhere).
          - Extension: repeated (or / and), optional preposition, up to 2 determiners, a place word ("in Singapore or any other country", "in Singapore or elsewhere").
          - Anchor: the qualifier counts only when the token right before it lies in a class-phrase span of a standing class, or is a PLACE_ANCHOR noun. PLACE_ANCHORS (56): crime(s), offences, offenses, felony, felonies, misdemeanor, misdemeanour, conviction(s), charge(s), charged, arrested, record(s), history, proceedings, case(s), court, order(s), petition(s), debt(s), action(s), sanction(s), sanctioned, investigation(s), body, bodies, authority, authorities, regulator(s), revoked, disciplined, licence, license, agreement(s), restriction(s), obligation(s), clause(s), contract(s), person(s).
          - Scope: only for a class set that holds a standing class, never for `disability` alone.
          - Result: a clause that names a place without a class ("… or currently in Singapore", "… or working in Singapore", "… a current role in Singapore", "… identify as living in Singapore") fails rule 1. The state words currently, now, still, status and subject stay SHARED: with places restricted and "aware" moved, no review probe passes through them.
       4. **Rule 3, the lead-in comes first (MEDIUM 1).** A piece with no class span and no status run passes only when no earlier piece has one: it is a lead-in ("Are you, or have you ever been, …"). A trailing all-filler piece ("I am not a PEP and I am aware of the status", "… and I am in Singapore") fails, on a dropdown and on a checkbox alike.
       5. **"aware" (MEDIUM 3).** Moves from SHARED to `conflict_audit_independence` filler. A conflict of interest is something the applicant knows of (D-90a keeps "Are you aware of any conflict of interest?" → No). For any other class, "aware of" asks what the applicant knows about other people ("Are you aware of any criminal convictions against Acme?"). "against" stays SHARED; with "aware" moved, the review's against-rows fail.
       6. **New rule 6, the applicant is the subject (MEDIUM 3).** At the start of `toks`, and right after each rule-3 cut, a status starter must be followed by `you` or `your`. These fail: "Are other people politically exposed persons?", "Is the person politically exposed?", "Is there a criminal record?", "Are you or is any other person a PEP?". "Has your professional licence ever been revoked?" passes. Relatives are exempt by design: D-170 does not run on the employer classes, so "Do any of your relatives work at Acme?" keeps D-164. The D-164 statement runs "there is" / "there are" stay, because the checkbox attestation "there is no …" uses them.
       7. **MEDIUM 4: kept recorded, not closed.** The employer-class compound ("Do you hold shares in this company and a valid visa?" → No; a single checkbox "I hold no shares in this company and have a valid visa" is ticked) stays the recorded D-170 residual. Why:
          - Those five classes answer only when the label names this employer (gate 4), and they answer from computed facts.
          - Closing it needs five new closed vocabularies with no label corpus behind them (the review replayed no employer-class variety). That trades one recorded shape for unmeasured under-answers on the commonest employer questions (relatives, previously applied).
          - D-83 reads every dry-run row before any real submit.
          - Revisit trigger: one such label in a dry-run audit or a live attempt. Then run rules 1, 3 and 6 on the employer classes with their own filler (queue it then).
       - Rejected:
         - (a) Strip any `if …` tail. It reopens "… ? If yes, are you also …".
         - (b) Pleaded guilty and IVA as class phrases. They widen classification beyond the frame fix.
         - (c) Cut before every and / or (the review's stronger rule 3). It breaks "suspended or revoked" and "adjudged bankrupt or entered into an IVA" without closing anything that items 3–6 leave open.
         - (d) Narrowing words for every value. A true value would give a Yes that may be false.
       - Vocabulary after D-171: SHARED 65 (72 − 8 places − aware + month, months); per class 169 (pep 10, conflict 12, criminal_record 29, bankruptcy 21, regulatory 25, non_compete 49, government 14, disability 9); NARROWING 7; PLACE_ANCHORS 56. Adding a word changes the spec and needs a pin.
       - Oracles D-171 (Yes/No dropdown unless stated; employer Acme; sample profile, every declaration false; `disability_status: no` where stated). The full 59-row pin list is in the Q-83 handoff (`comms/outbox/architect.md`, part D). Every D-164, D-169b and D-170 row keeps its result.

         | Label | Result |
         |---|---|
         | Have you ever been convicted of a crime? If yes, please provide details. · Do you have a criminal record? If yes, please provide details. · Are you currently bound by a non-compete agreement? If yes, please specify. · Have you ever been declared bankrupt? If so, please give details. | No (1) |
         | Criminal record? If yes, please provide details. | No (1, shape C after the strip) |
         | The first row above as TEXT · Are you a PEP? If yes, please provide your position. · Have you ever been declared bankrupt? If so, when? | unknown (1: tail kept on TEXT · object not in TAIL_OBJECT · no VERB) |
         | Have you ever been convicted of, or pleaded guilty to, any criminal offence? · …of a criminal offence or pleaded guilty to one? | No (2) |
         | Have you ever been convicted of a crime (excluding minor traffic offences)? · Do you have any unspent criminal convictions? | No (2, NARROWING); unknown with `criminal_record: true` |
         | Have you ever been convicted of a criminal offence in the last 12 months? · Are you, or have you been in the last 12 months, a politically exposed person? | No (2: months; 4: lead-in first) |
         | Are you a current or former government official? · Have you ever filed for (personal) bankruptcy? · Have you ever been adjudged bankrupt or entered into an individual voluntary arrangement? | No (2) |
         | Are you currently under investigation for any criminal offence? · Has your professional licence ever been revoked or suspended? · Have you ever been disciplined by any professional regulatory body? | No (2; 6: "your") |
         | Are you party to any agreement that restricts your ability to work for Acme? | No (2) |
         | Have you been convicted of a criminal offence in Singapore or any other country? · Have you ever been declared bankrupt in any jurisdiction? · Are you a politically exposed person in Singapore or elsewhere? | No (3: anchored place qualifier) |
         | Are you a politically exposed person or currently in Singapore? · …or currently overseas? · Have you been convicted of a crime or been in Singapore for the past year? · Do you have a criminal record or any status in Singapore? · Are you bound by a non-compete or working in Singapore? · Do you have a non-compete agreement or a current role in Singapore? · Are you a government employee or currently working in Singapore? · Have you worked for the government or worked in Singapore? · Do you have a disability or identify as living in Singapore? | unknown (3) |
         | Single checkboxes "I confirm I am not a PEP and am currently in Singapore" · "I am not a PEP and I am aware of the status" · "I have no criminal record and I am in Singapore" · "I am not bound by a non-compete and I am currently in Singapore" · "I am not subject to any non-compete or working in Singapore" | not ticked → unknown (3, 4, 5) |
         | Are other people politically exposed persons? · Are any people politically exposed persons? · Is the person politically exposed? · Is there a criminal record? · Are you or is any other person a PEP? | unknown (6) |
         | Are you aware of any politically exposed persons? · Are you aware of any criminal convictions against Acme? · …any bankruptcy proceedings against Acme? · …of the criminal record status of Acme? | unknown (5) |
         | Are you aware of any conflict of interest (with Acme)? · Do any of your relatives work at Acme? | No (5: conflict filler · relatives: D-170/171 do not run) |
         | Have you ever been convicted of a crime? with `criminal_record: true` | Yes (control) |
     - **D-90a:** WILLINGNESS also has sign, signing, object, objection, wish, want, prefer, familiar, comfortable, interested, keen, open to, happy to, knowledge, experience. So "I have no objection to signing the NDA" is never ticked, and "Are you familiar with MAS regulations?" / "Are you comfortable signing an NDA?" end unknown. "know" is left out because `relatives_at_company` uses "know anyone who works". "aware" is left out because "Are you aware of any conflict of interest?" is a status question that D-87 answers No.
     - D-90a also fixes: a decline-wording checkbox ("I do not wish to disclose a disability") is never ticked; "choice" in gate 1 means DROPDOWN/RADIO, so a MULTI_CHOICE declaration → unknown.
     - **D-91 `nda_willingness`** (the only exemption from gate 2). When the label has an NDA object (nda, ndas, non disclosure, nondisclosure, non disclosure agreement(s), confidentiality agreement(s), confidentiality obligation(s)) **and** a consent verb (willing, willingness, agree, agrees, consent, consents, accept, accepts, comply, abide, prepared; or the runs able to sign, will you sign, would you sign, can you sign; **D-165:** sign / signing may appear but are not a consent verb on their own, so "Signing an NDA?" → unknown; comfortable, happy to and open to are D-90a willingness words, not consent, so "Are you comfortable signing an NDA?" → unknown), the class is `nda_willingness` instead of `non_compete`. Its value is `declarations.willing_to_sign_nda` (true | false | null; **D-165: unset or null = no answer** → required `unknown`, optional `blank_optional`; never a false default), mapped by §7.3.2: "Are you willing to sign an NDA?", "Do you agree to sign our confidentiality agreement?" and "Will you comply with our confidentiality obligations?" all take it. A single consent checkbox ("I agree to sign the NDA") is ticked when the value is true, otherwise not (required → unknown).
     - **D-166 (Q-81; review F11): never answer one clause of a compound consent.** `nda_willingness` applies only when every label token outside the NDA object span(s) is in the closed vocabulary `declarations._NDA_LABEL_VOCAB`: i, you, we, are, is, am, do, does, will, would, can, able, to, willing, willingness, agree, agrees, consent, consents, accept, accepts, comply, abide, by, with, prepared, sign, signing, please, kindly, the, a, an, our, this, that, such, any, your, employer, company, agreement, agreements, obligation, obligations, confidentiality, if, asked. Any other token (and, or, terms, check, relocate, background, night, …) → not this class, the label is unsure → `unknown` / `blank_optional`, and a single checkbox is never ticked. Why: the F7 rule (no answer for one clause of a compound question) applied to consent; a tick is a signed statement (ADR-0003). The D-164 prefixes are deliberately not in this vocabulary. Built in the Q-48 fix round. Oracles with `willing_to_sign_nda: true`: "Are you willing to sign an NDA and relocate to Tokyo?" and "…and work night shifts?" → unknown; checkbox "I agree to sign the NDA and to a background check" → not ticked; "Are you willing to sign an NDA?", "Do you agree to sign our confidentiality agreement?", "Will you comply with our confidentiality obligations?", "Would you sign an NDA if asked?" → Yes; checkbox "I agree to sign the NDA" → ticked.
     - These stay unknown and are not this class: a label with any other restrictive-agreement object (non compete, non solicitation, restrictive covenant, stock or grant terms, garden leave); a label with read, understand, acknowledge, object or objection ("I have read … and have no questions", "Any objection to signing?"); a label with any negation (gate 3; the freedom forms don't apply).
     - `nda_willingness` is never in `STANDING_DECLARATIONS`: a willingness answer can't share one Yes/No with a status answer. Gates 1 and 3 and the S-free notes still apply.
  3. **Polarity known:** NEGATIONS = not, never, no, none, neither, nor, without, free of, free from, clear of, clear from, unrestricted, unencumbered, unrestrained, exempt, absence of, absent, lack, devoid, nothing, nobody, cannot, unable (matched after NS-exclusion runs are removed). A choice field whose label has a negation → unknown, never inverted (note "negated declaration question"). **The D-91 freedom forms are the exception:** free from, free of, clear of, clear from, unrestricted by, unencumbered by, not bound by, not subject to, not party to. Such a run must (i) be the only NEGATIONS hit in the label (after the NS-exclusion strip) and (ii) govern every matched class phrase: each phrase follows the run, with no second clause starter between them (a §5.4 question starter, "i am", "i have"). Then the field takes the **inverted** truth value: "Are you free from any restrictive covenants?" with `non_compete: false` → Yes. Any other negation, or a second one → unknown, as D-90. On a single checkbox the same governing run counts as a negative attestation ("I am free from any restrictive covenants" → ticked when the declaration is false). A single checkbox is ticked for a false declaration only through a recognised **negative attestation** run (i am not, i m not, i have not, i have never, i do not have, i don t have, i do not hold, i have no, i hold no, i am under no, there is no, there are no), never through a stray "no". It is ticked for a true declaration only through a positive attestation with no negation. A multi-class box stays `AMBIGUOUS` (agreement rule above).
  4. **Employer condition (review F4, live today, fixed now):** `prior_employment_at_company` and `current_employee_at_company` count only when the label names this employer. That means the token "us" (lower case in the raw label only; upper-case "US" is the country), "our", "we" or "here"; the runs this company, the company, this organisation, this organization, this firm, the employer; or a run that `company_match`es a name in `employer_names` (name plus aliases). Otherwise the hit makes the question unsure (`AMBIGUOUS`). One implementation, `declarations.names_this_employer(label_raw, employer_names)`, is shared with Q-46c (`facts` imports it from `declarations`, never the reverse). Without `label_raw`, "us" counts (the conservative side for the employer-specific checks). D-89 runs first.
     - **D-165 (Q-81; review F15 b), kept as built:** in an all-caps raw label "US" stays the country, so "HAVE YOU PREVIOUSLY WORKED FOR US?" → unknown. Why: the label cannot say which reading it means. The llm_fill F4 rule for work rights takes both readings; the country reading cannot answer an employer question, so that rule gives unknown here too. Any rule that picks one reading answers "…FOR US COMPANIES?" about this employer. The owner answers such a label once.
  5. **Disability, status frames only:** do you have, have you ever had, are you a person with, do you consider yourself, do you identify as, disability status. A label that also has accommodation(s), adjustment(s), arrangement(s), require(s), prevent, perform, performing, limit(s), affect(s), support, comfortable or working with → unknown, whatever the value.
  - Notes and rule ids carry class names, the public field label and constant reasons only, **never an S state** (e.g. "disability: no answer offered", not "declined").
  - **D-165 (Q-81; review F15, F16): settled as built, no code change.**
    - `willing_to_sign_nda` unset = no answer (D-91 bullet above; §5.4 template now shows `null`). Why: willingness is the owner's own answer. A silent false would turn down the employer's NDA for them. `applicant.py`, `config/applicant.example.yaml`, `truth()` and the tri-state Profile control already work this way. The owner's live value is true. The sample fixture's `false` is a test value and stays.
    - The D-91 consent verbs follow D-90a (D-91 bullet above). Why: "comfortable", "happy to" and "open to" ask about a feeling, not consent to sign. Pin: `test_d90a_pin_comfort_and_familiarity_questions_are_not_answered`.
    - F15 (a), grounding (`llm_fill` short-skill rule), is accepted: "Raised Series A, B, C" grounds a model-proposed "C". Why: it needs both a model proposal of "C" and a letter enumeration in the resume. A comma-list rule tight enough to reject it also rejects real lines like "Skills: R, C, Go". Revisit if a dry-run audit shows it.
    - F15 (b): gate 4 above.
- `pep`, `conflict_audit_independence`, `criminal_record`, `bankruptcy`, `regulatory_disciplinary`, `non_compete`, `government_employment` (D-87): the bool in `declarations.<label>` (default false).
- `disability` (D-87): `us_self_id.disability_status` is the disability answer for every country (no separate key). `no` → false, `yes` → true, `decline`/absent → no bool. A bool goes onto a bool-shaped field by §7.3.2, onto another choice by `fit_enum` with `DISABILITY_VALUE_MAP`, and onto a single checkbox by the negation rule below. `DISABILITY_VALUE_MAP` = the EEO disability phrases plus, for "no": no disability, i do not have a disability, i don't have a disability, i do not have any disability, not a person with disability, i am not a person with disability; for "yes": i am a person with disability, person with disability. With no bool: the decline option when offered, else required `unknown`, optional `blank_optional`. S, filled by the program, never tier 5.
- `shareholding_in_company`: true if `declarations.shareholding_in_company` or `company_match(employer, h)` for any `h` in `holdings`.
- `relatives_at_company`: true if `declarations.relatives_at_company` or any `relatives_employers` entry company-matches.
- `prior_employment_at_company`: true if any `experience[].employer` company-matches the employer or one of `ctx.employer_aliases` (internships count).
- `current_employee_at_company` (D-69): true only if an `experience[]` entry whose `employer` company-matches the employer or one of `ctx.employer_aliases` (the same matching as prior employment) has no end date (`end` null or absent); else false. ("Are you currently an employee at <company>?" in the Dataiku schema.)
- `previously_applied`: `ctx.previously_applied` (computed by apply_flow, §12.3).
- `health`: optional → `blank_optional`; required → decline option if offered, else `unknown`.
- **Company match** `company_match(a, b)`: normalise both: §7.1, then drop tokens `pte`, `ltd`, `limited`, `inc`, `llc`, `corp`, `corporation`, `co`, `plc`, `group`, `holdings`, `the`, `singapore`, `sg`, `bank` (only when other tokens remain); match if equal or one token list is a prefix of the other. ("DBS Bank Ltd" ~ "DBS"; "Grab" ~ "Grab Financial Group" → match: on a declaration, a truthful Yes beats a wrong No.)
- **Value onto the field:** bool → §7.3.2 bool mapping. **Single checkbox** declarations: a label with a recognised negative attestation (D-90 gate 3; formerly any of `not`, `never`, `no`, `none of`, `neither`) is a "tick = I am clear" box: tick when the declaration is false; otherwise ("I am a PEP"): tick when true. If the checkbox is required and the rule says "don't tick" → `unknown` (we will not tick a false statement to pass validation).
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

### 8.2 Fill primitives (all in `browser.py`, plus Workday's own widgets in `ats/workday_widgets.py` §9.4.7; adapters call these, never raw Playwright for input)

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

On `captcha`: if `captcha_wait_s` > 0 the tab is brought to front (`page.bring_to_front()`) and the flow polls `after_submit` every 2 s for that long; a confirmation turns the attempt `submitted`; otherwise `failed(captcha)` before the click, `submitted_unconfirmed` (note "captcha after submit") after it (§4.1). No input is sent meanwhile.

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
| Code after Submit | text matching `/security code/i` with a new text input → `code_required`; `mail_domains = ("greenhouse.io", "greenhouse-mail.io")`; `otp_pattern = r"\b([A-Za-z0-9]{8})\b"` superseded by **D-85**: the code is the only line (trimmed) of 6–12 letters/digits after the "security code" sentence (no digit required); zero or several candidate lines → fail closed (`llm_fill_design.md` §9.2). Revisit when S-4 or a real message shows the format |
| Errors | visible `[aria-invalid="true"]` field labels, `.helper-text--error`, text "This field is required" → `errors`; one re-fill of those fields, then `validation_error` |
| Account | none (`needs_account = False`) |

Recorded schemas for fixtures: the spike's `gh_vercel.json`, `gh_dataiku.json` (scratch; the tester copies them, scrubbed of nothing personal since they are public schemas, into `tests/fixtures/apply/greenhouse/` as `gh_vercel.json` and `gh_dataiku.json`, beside the recorded pages `form.html`, `form_challenge.html`, `bot_check.html`, `closed.html`, `confirm.html` and `recaptcha/`; sample inputs `tests/fixtures/apply/applicant.sample.yaml` and `questions.sample.yaml`).

#### 9.1.1 MyGreenhouse autofill, then fill the gaps (M20, D-70)

Owner (D-70): "if there is an option to 'autofill with Greenhouse' … it should, and then fill up the remaining empty areas." Greenhouse's Quick Apply puts an autofill button on Greenhouse-hosted applications when the employer has enabled it; the candidate's MyGreenhouse profile (name, contact, resume, employment, education, links, voluntary self-identification, saved answers to common questions) fills the form; sign-in is by a **code sent to the email**, no password (support.greenhouse.io "MyGreenhouse job alerts and quick apply", fetched 2026-11-02). The button copy differs between sources ("Autofill with Greenhouse", "Autofill my application"), so detection matches both. Selectors and the signed-in behaviour are confirmed by spike **S-6** (after owner task Q-24).

**Where the login lives (honest limit).** The owner's default Edge profile cannot be automated: Chromium-based browsers ignore remote debugging on the default user-data directory (brief §3.1, Chrome 136+; S-1 used a dedicated profile for this reason). So the MyGreenhouse session must live in the **JobScraper Edge profile** (`apply.profile_dir`). Owner step, once (Q-24): `python -m jobscraper apply open-profile https://my.greenhouse.io` (§14.1) → sign in with the emailed code → close the window. When the session lapses (length unknown; S-6 notes it), attempts fall back to the full fill below and the job log says "mygreenhouse: not signed in", and `apply show` shows it; the owner runs `open-profile` again. (Signing in automatically with the emailed code through IMAP is possible later; not in M20.)

**Planning change.** With `apply.mygreenhouse: true` (default) a required field that resolves `unknown`/`ungrounded` in `planning` does **not** fail the attempt before Edge opens; it is re-checked after the prefill (it may come from MyGreenhouse). With it false, or for every other ATS, §6's fail-before-the-browser rule is unchanged.

**`GreenhouseAdapter.prefill(page, ctx) -> str`** (after `open`, before the first fill):

1. `apply.mygreenhouse` false → `""`.
2. Button: the first visible `button`, `a` or `[role="button"]` whose accessible name matches `/autofill (with )?(my ?greenhouse|greenhouse)|autofill my application/i` (S-6). None → `""` (log "mygreenhouse: no button").
3. Snapshot `read_values` for every plan field (expected all empty). Click the button.
4. Within `apply.mygreenhouse_wait_s` (20), poll every 1 s:
   - **Not signed in** if any of: a new page opens in the context (popup); the tab navigates off `job-boards.greenhouse.io` / the employer page; a visible `[role="dialog"]` contains an `input[type="email"]` or text `/sign in|log in|create (an )?account|enter your email|verification code|continue with/i`. Then: close the popup (`popup.close()`), or `page.go_back()` and re-check `#first_name` (missing → re-`open`), or close the dialog (its `[aria-label="Close"]` / a button named `/^(close|cancel|not now|no thanks)$/i`, else Escape). Never type an email or request a code. Re-read values: unchanged → return `""` (log "mygreenhouse: not signed in"); changed → continue at "signed in".
   - **Signed in** when any plan field's value changed from the snapshot; then wait until two consecutive snapshots 1 s apart are equal (bounded by the same timeout) → return `"mygreenhouse"`.
   - Neither by the timeout → `""` (log "mygreenhouse: no effect").
   - Any other dialog (e.g. a consent "share your profile with <company>") → treated as not signed in in M20; S-6 records it and, if it is a plain consent, the design adds the click.
5. A screenshot `NN-mygreenhouse.png` in every case where the button was clicked.

**Fill with `PrefillPolicy.KEEP`** (the flow, after `prefill` returned `"mygreenhouse"`; `read_values` per field):

| Field | Shows a value | Action, audit row |
|---|---|---|
| RESUME (always ours, D-70) | any | remove an attached file (its remove control: a button named `/remove|delete/i` or `[aria-label*="remove" i]` inside the resume block, S-6), `upload` the tailored file, read back the shown name = the tailored file's name; else FILL_FAILED (required → `validation_error`; never submit MyGreenhouse's resume) |
| EMAIL (always ours) | different from `ctx.email` | overwrite (the security-code mail must reach the watched mailbox); equal → `filled`, note "already on page" |
| a single CHECKBOX (always ours) | any | our answer (an unticked box can't be told from "not answered") |
| a tier-4 answer whose label is in `EMPLOYER_SPECIFIC_DECLARATIONS` | different | overwrite with the resolver's deduction (a saved answer from another employer must not stand; deliberate exception to "only empty", recorded in §20.2) |
| any other field | non-empty | **keep**; status `prefilled`, tier NONE (0), `source = "mygreenhouse"`, confidence 0.95 (the owner's own saved data), value = the shown value, `sensitive` = the resolved answer's flag or section `compliance`/`demographic`; note "differs from profile (<source>)" when the resolver had a tier 1–4 answer that `fills` with a different value |
| any other field | empty | the planned answer as in §9.1 (fill; `blank_optional`; required + `unknown`/`ungrounded` → `unanswerable_required`, nothing sent) |

`read_values` for Greenhouse: text/textarea/phone: `input_value()`; react-select (DROPDOWN, LOCATION, `country`): the `.select__single-value` text inside the field's `.select__control` (K, S-6), "" when the placeholder shows; MULTI_CHOICE: `.select__multi-value__label` texts; CHECKBOX: "true"/"false"; FILE: the file name shown in the field's block (S-3 saw it appear), else "".

No MyGreenhouse (button absent, not signed in, no effect, or the flag off) → the full fill of §9.1 with every field; behaviour identical to the pre-D-70 design.

#### 9.1.2 Greenhouse canonical by label (tester Q-08 item 4, decided)

A schema question whose only field is `input_text` gets a link canonical by **phrase match** (§7.1), not exact label: LINKEDIN ← phrase `linkedin`; GITHUB ← `github`; WEBSITE ← `website`, `portfolio`, `personal site`. The §7.1 one-token rule applies (a one-token phrase matches only labels of ≤ 4 tokens), so "LinkedIn Profile", "LinkedIn URL", "Github URL", "Website", "Portfolio link" are tagged and "Please share your LinkedIn profile or another link to your work" is not (it falls to tier 2, `links.*` synonyms). Exactly one canonical must match; two ("LinkedIn or GitHub") → no canonical. `textarea`, select and file questions never get a link canonical. Tester oracle: the Dataiku schema's "LinkedIn URL" → LINKEDIN and "Github URL" → GITHUB.

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

### 9.4 Workday (M20, D-70)

Workday is first-class in M20 (D-70: "the largest of my problems and it should be solved"). This section is build-ready: every rule is fixed here; only the **selectors** marked **S-5** wait for spike S-5's recordings, with the best-known default given. Marks: **[pub]** = seen in two or more public automation projects (GitHub code search 2026-11-01, see Sources); **K** = one source or prior knowledge; **S-5** = confirm on the recordings. When a recording differs from a default, the recording wins and the engineer lists the difference in the WP handoff (a verification step, not a design choice).

**Spike S-5 (Q-23, software-engineer, owner-approved real accounts):** at 2 owner-chosen employers, with the owner's email: open a posting, record the Apply choice, create the account (or sign in), verify through IMAP, walk every wizard step filling the synthetic-safe owner data, **stop at Review** (no Submit). Output per tenant in `tests/fixtures/apply/workday/<tenant>/` (tester scrubs personal values to the synthetic profile's before commit):

| File | Content |
|---|---|
| `NN-<step>.html` | DOM after the step settled (scripts removed, every `data-automation-id`, `aria-*`, `role` kept), one per step incl. `00-posting`, `01-entry`, `02-signin`, `03-create_account`, `04-verify`, wizard steps, `NN-review` |
| `automation_ids.json` | per step: `[{automation_id, tag, role, type, label, required, in_section}]` for every element carrying a `data-automation-id` |
| `steps.json` | the progress-bar titles in order, and which container id each step had |
| `entry.json` | which Apply choices were offered (text + automation id) |
| `notes.md` | anything the defaults below got wrong; the "already registered" copy if met; date-section order; prompt behaviour on Enter; error-banner markup after a deliberate empty Next on one step |
| `verify_mail.txt` | the verification mail's sender domain, subject shape, link host and path shape (link token replaced by `TOKEN`) |

**S-5 checklist** (each item → `notes.md`, confirmed / differs):
1. Apply button id (`adventureButton` / `jobPostingApplyButton`) and the entry dialog ids (`applyManually`, `useMyLastApplication`, `autofillWithResume`); whether `<job_url>/apply/applyManually` opens the manual flow directly.
2. Sign-in / create-account ids (`email`, `password`, `verifyPassword`, `createAccountCheckbox`, `createAccountSubmitButton`, `signInSubmitButton`, `createAccountLink`, `signInLink`, `errorMessage`) and the click-overlay quirk.
3. The "already registered" message (exact copy, field error or banner) — provoke it at the 2nd tenant only if the owner already has an account there; else note "not met".
4. Verification: link or code; sender domain; does the link land on sign-in, on the wizard, or on candidate home.
5. Step containers (`contactInformationPage`, `myExperiencePage`, `primaryQuestionnairePage`, `secondaryQuestionnairePage`, `voluntaryDisclosuresPage`, `selfIdentificationPage`, `reviewJobApplicationPage`) vs progress-bar titles; any extra tenant step.
6. Generic field container (`formField-<name>`), label element, required marker.
7. Listbox (`aria-haspopup="listbox"` + `[role=option]`), radio, checkbox markup.
8. Multi-select prompt: `searchBox`, `promptOption`, `promptLeafNode`, `selectedItem`, `DELETE_charm`; whether Enter in the search box searches without advancing the step; category drill-down for "How did you hear about us".
9. Date widget: `dateSectionMonth-input` / `dateSectionDay-input` / `dateSectionYear-input` order and read-back attribute.
10. Repeating sections: section ids, Add button, panel ids (`workExperience-<n>`, `education-<n>`), delete button; resume upload id, attached-file chip and its delete; parse spinner.
11. Next button `bottom-navigation-next-button`; its text on Review ("Submit"); error banner/item markup after a deliberate empty Next.
12. Review page: label/value markup per item, section headings.
13. Session/candidate-home URLs (`/userHome`), "session expired" copy.
Confirmation (after Submit) is **not** recorded by S-5 (it stops at Review); the first real gate submission saves `confirm.html` and the fallback is `submitted_unconfirmed` (safe, NF-06).

#### 9.4.1 Tenant

| URL form | Regex (case-insensitive) |
|---|---|
| A `https://<tenant>.wd<N>.myworkdayjobs.com/[<locale>/]<site>/job/<location>/<slug>_<req>[/apply[/…]]` [pub] | `^https?://(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com(?:/[a-z]{2}[-_][a-z]{2})?/(?P<site>[^/?#]+)(?P<rest>/[^?#]*)?` |
| B `https://wd<N>.myworkdaysite.com/[<locale>/]recruiting/<tenant>/<site>/job/…` (K) | `^https?://(?P<wd>wd\d+)\.myworkdaysite\.com(?:/[a-z]{2}[-_][a-z]{2})?/recruiting/(?P<tenant>[\w-]+)/(?P<site>[^/?#]+)(?P<rest>/[^?#]*)?` |

- `Tenant(ats="workday", host=f"{tenant}.{wd}.myworkdayjobs.com".lower(), board=tenant.lower(), site=site, posting_id=…)`. Form B uses the **same canonical host** so one tenant has one vault service (`jobscraper:workday:<host>`) whichever URL form the posting used.
- `posting_id` = the job's `external_id` when set (the scraper stores the Workday req id there), else the `_(?P<req>[A-Za-z0-9-]+)$` suffix of the path segment after `/job/<location>/`, else "".
- `job_url` = the job URL with any `/apply…` suffix, query and fragment dropped (the posting page).
- `match_url(url)` applies A then B. `tenant_from_company(job)`: provider `workday` and `match_url(job["url"])` → that tenant; else None.
- Re-implemented in `ats/workday.py` (stages don't import `scrape/`); the tester asserts agreement with `scrape.adapters.parse_workday` on host/tenant/site for form A.

#### 9.4.2 Open and the Apply choice

1. `page.goto(job_url)`; `settle`; `classify` (closed → `posting_closed`). Apply button within `step_timeout_s`: `[data-automation-id="adventureButton"]` [pub], else `[data-automation-id="jobPostingApplyButton"]` (K), else a button or link named `/^apply( now)?$/i`. None → closed-text check → `posting_closed`, else `page_unrecognised` ("workday: no apply button").
2. Click it. Within 10 s the choice dialog shows some of (S-5): `[data-automation-id="applyManually"]` [pub] / text "Apply Manually"; `[data-automation-id="useMyLastApplication"]` (K) / "Use My Last Application"; `[data-automation-id="autofillWithResume"]` (K) / "Autofill with Resume". No dialog but a sign-in form or a wizard step → entry `direct`. Neither within 10 s → `page.goto(job_url + "/apply/applyManually")` (K) once, then re-check; still nothing → `page_unrecognised` ("workday: apply choice").
3. **Rule** (`WorkdayEntry`, recorded in the job log and `apply_attempts.step` history):
   - `ctx.applied_on_tenant` (§12.4: a Submit was already clicked on this tenant) **and** "Use My Last Application" is offered → click it; `ctx.prefill = "workday_last_application"`.
   - otherwise "Apply Manually" → `ctx.prefill = "site_default"`.
   - "Autofill with Resume" is **never** clicked: its resume parse is often wrong (brief §2.1, S23) and every parsed value would have to be undone.
   - only "Autofill with Resume" offered → `page_unrecognised` ("workday: only resume autofill offered").
   - `apply.workday_entry: manual` (config) forces "Apply Manually" whatever was offered.
   - In **every** case §9.4.6 applies: each field is checked against the resolver and overwritten when it differs. "Use My Last Application" saves typing; it never decides an answer.
4. The account wall follows the choice (Workday asks for an account after it). A still-valid session in the persistent profile shows the wizard directly.

#### 9.4.3 Account wall, sign in, create account

- `account_wall(page)`: `"sign_in"` when `[data-automation-id="signInSubmitButton"]` [pub] is visible; `"sign_up"` when `[data-automation-id="createAccountSubmitButton"]` [pub] (or `verifyPassword`) is visible; `None` when a step container or `[data-automation-id="progressBar"]` (K) is visible. **Which action runs is decided by the flow's identity rule (§10.5), not by which form happens to show:** the adapter switches forms with `[data-automation-id="createAccountLink"]` [pub] (sign-in → create) or `[data-automation-id="signInLink"]` (K) / a link named `/^sign in$/i` (create → sign-in).
- `sign_in(page, ctx, password)`: `fill_text` email `[data-automation-id="email"]` (or `signIn-email`) [pub] with `ctx.email` (read back), password `[data-automation-id="password"]` (or `signIn-password`) [pub] (no read-back of the value; check it is non-empty), click `signInSubmitButton` (if a `[data-automation-id="click_filter"]` (K) overlay intercepts, click its parent `div[role=button]` [pub]). Within `step_timeout_s`: wizard visible → return; classify `verify_email` → return (the flow moves to `verifying_email`); `[data-automation-id="errorMessage"]` or alert text `/wrong|incorrect|invalid|not match/i` → `ApplyFailure(LOGIN_FAILED, "The site rejected the saved password.")`; text `/locked|too many/i` → `ApplyFailure(LOGIN_FAILED, "The account is locked on this site.")`. **One sign-in submit per identity per attempt** (Workday tenants lock accounts after a few failures; Sources). Never "Forgot password" (F-35).
- `sign_up(page, ctx, password) -> SignUpOutcome`: `fill_text` `email` (= `ctx.email`), `password`, `verifyPassword`; tick `[data-automation-id="createAccountCheckbox"]` [pub] when present (terms: requires `consents.privacy_consent`, else `ApplyFailure(UNANSWERABLE_REQUIRED, "account terms")`); click `createAccountSubmitButton`. Within `step_timeout_s`, first match wins:
  1. text `/already (exists|in use|registered|been registered)|account (already )?exists|email address is already|an account with this email/i` (S-5 records the exact copy, field error or banner) → `already_registered`;
  2. an `errorMessage` beside the email or password field → `ApplyFailure(VALIDATION_ERROR, "account form: <field label>")` (§10.2 step 6 rollback);
  3. a step container / progress bar → `signed_in`;
  4. classify `verify_email` → `verify_email`;
  5. the sign-in form → `sign_in`.

#### 9.4.4 Email verification

`verifying_email` (from `verify_email`, or after sign-in when classify says `verify_email`): `MailWatcher.wait_for(since_utc=attempt.started_at, sender_domains=adapter.mail_domains + (employer domain,), link_domains=(tenant.host, "myworkdayjobs.com", "myworkday.com", "myworkdaysite.com", employer domain), otp_pattern=adapter.otp_pattern, want="either", to_addr=ctx.email)` on the mailbox of `ctx.email` (§11.5). Link → `page.goto(link)` in the attempt's tab; code → `enter_code`. Then: sign-in form → `signing_in` with the same identity's vault password; step container → `filling`; anything else (candidate home, a "verified" notice) → `page.goto(job_url)` and §9.4.2 steps 1–3 again (now signed in), then `filling`. On success the account row becomes `verified`.

#### 9.4.5 Wizard loop and step identification

`read_step(page, ctx)` returns `(step_id, fields)`:

1. **Container:** the visible page container's automation id → step id: `contactInformationPage`→`my_information`, `myExperiencePage`→`my_experience`, `primaryQuestionnairePage`→`questions_1`, `secondaryQuestionnairePage`→`questions_2`, `voluntaryDisclosuresPage`→`voluntary_disclosures`, `selfIdentificationPage`→`self_identify`, `reviewJobApplicationPage`→`review` [pub].
2. **Else the title:** `[data-automation-id="progressBarActiveStep"]` [pub] text, normalised (§7.1): `my information`→`my_information`; `my experience`→`my_experience`; `application questions`, `questions`, `additional questions`, `questionnaire` → `questions_<n>` (n = 1 + questions steps already seen in this attempt); `voluntary disclosures`→`voluntary_disclosures`; `self identify`, `self identification`, `disability` → `self_identify`; `review` → `review`; **any other title** → `custom_<slug>` (slug of the title, `[a-z0-9_]`, ≤ 30 chars), handled by the generic reader. Tenants add their own steps; a generic reader plus the fail-closed resolver is safer than refusing them.
3. Neither → `page_unrecognised` ("workday: no step").

`FormPlan.steps` = the progress-bar titles, slugged (`[data-automation-id="progressBar"]` items, S-5), logged once. Loop guards (in the adapter's `next_step`): at most 15 Next clicks per attempt; the same step id again after a Next with no visible errors → `page_unrecognised` ("stuck at <step>").

**Generic reader** (questions_*, custom_*, and any field on the named steps not in the tables below): every visible `[data-automation-id^="formField-"]` container (S-5; [pub] for the prefix) is one field. Label = its `label` or `legend` text without a trailing `*`; required = `*` in the label, `aria-required="true"`, or `required`. Type by control: `button[aria-haspopup="listbox"]` → DROPDOWN (options read by opening the list once: click, read `[role="option"]` texts in the open `[role="listbox"]`, press Escape); a prompt (`[data-automation-id="multiselectInputContainer"]` or a `searchBox` inside, K) → MULTI_CHOICE, or TYPEAHEAD when the field holds one value (options are searched at fill time, §9.4.7); a radio group → RADIO; several checkboxes → MULTI_CHOICE; one checkbox → CHECKBOX; `textarea` → TEXTAREA; `input[type=text|email|tel|url|number]` → TEXT; date sections → DATE. Key = `<step>:<container automation id>`, with `#<n>` appended when the id repeats on the step. Resolved by tiers 2–5 (questionnaires) or by the tables' canonicals.

#### 9.4.6 Prefill policy on Workday: OVERWRITE (`PrefillPolicy.OVERWRITE`)

Before filling a step the flow calls `adapter.read_values(page, ctx, fields)`. Per field:

| Resolver result | Field shows a value | Action, audit row |
|---|---|---|
| answer that `fills` | equal (normalised §7.1; dates as ISO; multi as sets; file by name) | no input; status `filled`, note "already on page" |
| answer that `fills` | different or empty | clear, then fill; status `filled` (note "replaced site value" when it was non-empty) |
| no answer, field **required** | anything | `unanswerable_required` (fail closed: a value we cannot back up is not kept, even our own from a last application) |
| no answer, optional | non-empty | keep; status `prefilled`, tier NONE (0), `source = ctx.prefill` (`workday_last_application` or `site_default`), confidence 0.9, value = the shown value |
| no answer, optional | empty | `blank_optional` |

Clearing: text → `fill("")`; prompt → remove every `selectedItem` pill; listbox/radio → choosing the new option replaces it; checkbox → `set_checkbox`; date → each section re-typed. Under "Use My Last Application" the repeating sections and the resume are still rebuilt exactly (§9.4.8).

#### 9.4.7 Widgets (`src/jobscraper/apply/ats/workday_widgets.py`, lane V)

Workday's own controls; adapters use these and `browser.py` (§8.2) only. Every helper returns True/False after a read-back.

| Helper | Behaviour |
|---|---|
| `choose_listbox(page, button, label)` | §8.2 (exists in `browser.py`) |
| `prompt_select(page, field, labels)` | Clear existing pills (`[data-automation-id="selectedItem"]`, remove control `[data-automation-id="DELETE_charm"]`, K). For each label: click the field's `[data-automation-id="searchBox"]` (K) input, `fill(label[:40])`, press **Enter** (this runs the prompt's search; it is the one allowed Enter, inside a search box that is not a form, S-5 item 8), wait ≤ 5 s for `[data-automation-id="promptOption"]` (K) items, click the one whose normalised text equals the label (else the only one containing it). If the clicked item is a category (it has a child-list chevron / is not `promptLeafNode`, K), match again among its children (≤ 3 levels). Read back: the pill texts contain every label |
| `prompt_options(page, field, search)` | For resolution: type `search` (or nothing, for a category list), Enter, read up to 50 `promptOption` texts (leaf and category), Escape. Used for HOW_HEARD (search "" then each category is a leaf list) and the school / field-of-study / skills prompts |
| `fill_date(field, iso)` | For each of `[data-automation-id="dateSectionMonth-input"]`, `dateSectionDay-input`, `dateSectionYear-input` (K, [pub] for month/year) present in the field, **by role, not position** (locale order differs): click it, `press_sequentially` MM / DD / YYYY. A `YYYY-MM` value with a Day section present → day `01`; a year-only field (first/last year attended) gets YYYY. Read back each section's value or `aria-valuetext` (S-5 item 9) |
| `panels(section)`, `add_panel(section)`, `delete_panel(panel)` | Sections: `[data-automation-id="workExperienceSection"]`, `educationSection`, `websiteSection`, `languageSection`, `certificationSection` (K, S-5). Add: `button[data-automation-id="Add"]` or a button named `/^add( another)?\b/i` inside the section. Panels: `[data-automation-id^="workExperience-"]` / `education-` / … (K) or `[role="group"]` children (S-5). Delete: `button[data-automation-id="panel-set-delete-button"]` (K) or a button named `/^delete/i` in the panel. After each add/delete wait ≤ 5 s for the panel count to change, else False |

#### 9.4.8 Named steps

| Step | Fields (all tier 1 unless said; ids [pub] unless marked) |
|---|---|
| my_information | `previousWorker` radio (PREVIOUS_WORKER, §7.5 prior employment); "How did you hear about us" `sourceDropdown`/`source--source` prompt (K; HOW_HEARD: `prompt_options` lists categories and leaves, §7.3.2 maps `sourcing.how_heard_default`, then `prompt_select`); `countryDropdown` / `addressSection_countryRegion` (COUNTRY, listbox); `legalNameSection_firstName`, `legalNameSection_lastName` (FIRST/LAST_NAME); `legalNameSection_preferredCheck` (K; tick only when `identity.preferred_name` set, then the preferred-name inputs); `addressSection_addressLine1`, `addressSection_city`, `addressSection_postalCode` (ADDRESS_LINE1, CITY, POSTAL_CODE); `phone-device-type` (PHONE_DEVICE_TYPE); `countryPhoneCode` (K; PHONE_COUNTRY_CODE, prompt or listbox); `phone-number` (PHONE); `email` (EMAIL: pre-filled with the account email; compared, never retyped unless different) |
| my_experience | **Resume first:** if a file is attached (`[data-automation-id="file-upload-successful"]` or a file chip with `[data-automation-id="delete-file"]`, K) delete it; `upload([data-automation-id="file-upload-input-ref"], ctx.resume_path)`; wait ≤ 20 s for the file name and for the parse spinner to go. Read back: the shown name equals the tailored file's name, else FILL_FAILED (required → `validation_error`; another resume is never submitted, D-70). **Then the sections, rebuilt to match the profile exactly:** delete every existing panel (last to first: the parse or a last application may have added some), then one `add_panel` per entry. Work experience per `experience[]` (profile order): `jobTitle`, `company`, `location`, `currentlyWorkHere` (checkbox, ticked iff `end` is null), `startDate` / `endDate` (`fill_date`, skipped when current), `roleDescription` (K; `description`). Education per `education[]`: `school` prompt (institution; no equal-or-unique match → required: `unanswerable_required` "school", optional: skipped), `degree` listbox (option containing the profile degree's level word: bachelor / master / doctor\|phd / diploma / associate, from `degree`; none or several → `unknown`), `fieldOfStudy` prompt (`major`; no match → skipped if optional), `gradeAverage` (K; `grade`), `firstYearAttended` / `lastYearAttended` (`fill_date` years from `start` / `end`). Websites: delete all, one panel per non-empty `links.linkedin`, `github`, `portfolio`, `other[]`; a separate `linkedinQuestion` (K) gets LINKEDIN. Skills prompt `formField-skills` (K): `prompt_select` once per profile skill ∪ attested skill; a skill with no equal suggestion is skipped (logged count only). Languages section when present: one panel per `languages[]`. Sources: `field_map:experience[i].<key>`, `field_map:education[i].<key>`, `field_map:links.<key>`, `field_map:skills` |
| questions_* / custom_* | generic reader (§9.4.5); tiers 2–5 |
| voluntary_disclosures | `gender` (EEO_GENDER), `ethnicityDropdown` (EEO_RACE), `hispanicOrLatino` (EEO_HISPANIC), `veteranStatus` (EEO_VETERAN), `agreementCheckbox` (TERMS_AGREEMENT); any other item via the generic reader (tiers 2–5; attestations tier 4). All from `us_self_id.*` / `consents.*` (§7.2) |
| self_identify | `name` (SELF_ID_NAME); date: `fill_date` with today (Asia/Singapore), else `dateIcon` → `datePickerSelectedToday` (SELF_ID_DATE); disability radio group (EEO_DISABILITY: `yes`/`no` by §7.3.2 bool polarity on options starting "Yes, I have" / "No, I don't have"; `decline` → the option containing "do not want to answer"); employee id (optional) blank |
| review | §9.4.10 |

#### 9.4.9 Next, and errors after Next (one corrective retry per step)

`next_step`: click `[data-automation-id="bottom-navigation-next-button"]` [pub] (text "Next"/"Save and Continue"); wait ≤ `step_timeout_s` for the step id to change **or** an error: `[data-automation-id="errorMessage"]` [pub], an error banner (`[data-automation-id="errorBanner"]` / `errorWidgetBar`, K, S-5 item 11) or text `/errors? (found|on this page)|is required|required field/i`. On error:

1. Flagged fields = the field containers holding an error message or `aria-invalid="true"`; their labels.
2. Per flagged field: an answer that `fills` → re-fill it once from a fresh locator; `blank_optional` / `prefilled` (the site wants it after all) → re-resolve that one field with `dataclasses.replace(field, required=True)` (tiers 1–5 as usual); answer → fill; none → `unanswerable_required` (label).
3. Click Next once more. Still errors → `validation_error` (up to 3 labels). `StepResult.errors` carries the labels only.

Split of work: the adapter's `next_step` does step 1 and returns `StepResult(step=<same step>, errors=<labels>)` instead of raising; `apply_flow` (generic, both ATSs; WP-B11) does steps 2–3 (it owns the resolver) and raises `validation_error` on the second failure. Greenhouse's "one re-fill, then `validation_error`" (§9.1 Errors) is the same machinery.

#### 9.4.10 Review page parse

On `review` (`is_review=True`): read every displayed item (S-5 item 12: label element + value element per `formField-*`, under section headings = step titles). Write `data/apply/<attempt_id>/review.json` = `[{section, label, value}]` (local, gitignored, never logged; deleted with the attempt). Cross-check each answer with status `filled` or `prefilled`: find the review item with the same normalised label under the same section; compare normalised values (§7.1 on text; dates and phones as digit strings; multi as sets; FILE by file name). Results:

- equal → nothing;
- item not found → note "not shown on review" (review pages omit some fields; no failure);
- different on an **optional** field → note "review shows a different value";
- different on a **required** field, or the resume file name differs → `ApplyFailure(VALIDATION_ERROR, "review page differs: <labels>")` **before** Submit (nothing sent).

`apply show` prints these notes with the answers.

Who: the Workday adapter, in the `next_step` call that lands on `review`, using the answers it was handed in its `fill` calls (the flow passes every answer of the step to `fill`, `prefilled` ones included; `fill` only types those that `fills`). It sets the notes on those `Answer` objects (`note` += "; review: …") and raises `validation_error` per the rules above; the flow, after that `next_step` (or on its failure), calls `store.annotate_answers(attempt_id, {(step, field_key): note})` to update the already-written rows (lane V store V-block, §13).

#### 9.4.11 Submit, confirmation

- `submit`: the review page's `bottom-navigation-next-button` whose text matches `/^submit$/i` [pub]; anything else on review → `page_unrecognised` ("workday: no submit").
- `after_submit` (polled): text `/application (has been )?submitted|thank you for applying|successfully submitted|congratulations/i` or `[data-automation-id="thankYouMessage"]` (K) → `confirmed:text`; URL containing `/userHome` (K) whose page lists the job title with a status matching `/submitted|under consideration|application received|in review/i` → `confirmed:home`. Errors visible → `errors`. Nothing by `confirm_timeout_s` → `submitted_unconfirmed` (NF-06). The first gate submission records `confirm.html` (owner-approved real submission, D-70).
- Dialogs: `page.on("dialog")` dismisses "leave this page?" prompts (stay on the page).
- "Your session has expired" (K) before the click → `ApplyFailure(ERROR, "workday session expired")`.

#### 9.4.12 Constants

| Item | Value |
|---|---|
| `needs_account` | True |
| `password_rules` | `PasswordRules(length=20, symbols="!@#$%^&*")` (Workday: upper, lower, digit, special; ≥ 8) |
| `mail_domains` | `("myworkday.com", "myworkdayjobs.com", "myworkdaysite.com", "workday.com")` + the employer's registrable domain (§11.3) |
| `otp_pattern` | `r"\b(\d{6})\b"` (verification is normally a link; a code variant, if S-5 meets one, sets this) |
| `prefill()` | returns `ctx.prefill` (set in §9.4.2); no action |
| `read_values()` | text: `input_value()`; listbox: the button text (empty when it shows "Select One", K); prompt: pill texts; radio: the checked option's label; checkbox: "true"/"false"; date: ISO from the sections; file: the attached file name |

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

Settings → Accounts → "Add an account you already have" (web, M21) and, from M20, the CLI `accounts add --url <tenant URL> --email <address>` (password by `getpass`): ATS (Workday), tenant URL, email, password → `vault.put` + account row status `created` (an existing `signin_failed` / `exists_no_password` row is reset to `created`). Fixes the `login_failed` "account exists" and "sign-in failed before" cases without a password reset.

### 10.5 Which email: identity choice and the backup email (D-70)

Profile: `contact.email` (primary, required) and `contact.backup_email` (optional, new: same validation as `contact.email`, must differ from it, sensitive like every `contact.*` path; template line `backup_email: ""   # used only when an ATS says your main email is already registered and JobScraper has no password for it`).

`apply/accounts.py` (stage, pure, no I/O; lane V):

```python
@dataclass(frozen=True)
class Identity:
    email: str
    action: str            # "sign_in" | "sign_up"

def choose_identity(primary: str, backup: str, rows: dict[str, str],
                    has_password: Callable[[str], bool]) -> Identity
    # rows: {email (lower): AccountStatus value} for this tenant; has_password(email) = vault.get(service, email) is not None
    # raises ApplyFailure(LOGIN_FAILED, detail) per rule 3/4
```

Rules, in order (emails compared lower-case; `backup` "" = none):

1. For `e` in (primary, backup), skipping "": if `has_password(e)` and `rows.get(e)` not in {`signin_failed`, `exists_no_password`} → `Identity(e, "sign_in")`.
2. If `rows.get(e) == "signin_failed"` for an `e` and rule 1 found nothing → `LOGIN_FAILED`, detail "Sign-in failed on this site before; JobScraper won't retry, to avoid locking the account." (The owner fixes it with `accounts add`, §14.1, which stores the password and resets the row to `created`.)
3. If `rows.get(primary) == "exists_no_password"`: backup set and `rows.get(backup)` is None → `Identity(backup, "sign_up")`; else `LOGIN_FAILED`, detail "An account exists for your email but JobScraper has no password for it. Add a backup email to your profile, or add the password with `accounts add`." (both emails used: "Accounts exist for both your emails, but JobScraper has no password for them.").
4. Else → `Identity(primary, "sign_up")`.

**The flow** (`apply_flow`, opening → signing_in | signing_up): `ctx.email = identity.email`; `ResolveContext.account_email = identity.email` (tier-1 EMAIL then answers with it, so the form's email matches the account). Sign-up follows §10.2 with `identity.email`. When `sign_up` returns `already_registered` for email `e`:

1. `vault.delete(service, e)` (the generated password was never accepted); row `e` → `exists_no_password`.
2. `e` is the primary, the backup is set and has no row → `signing_up → signing_up` (the one allowed self-transition, contract v3): generate, `vault.put(service, backup)`, row (backup, `creating`), the adapter re-fills the create-account form with the backup (`ctx.email = backup`), `sign_up` once more, outcomes as §10.2.
3. Otherwise → `failed(login_failed)` with the rule-3 detail. At most one backup retry per attempt.

Sign-in success: row `last_signin_at` = now, `last_signin_ok = 1`. Sign-in rejection: row → `signin_failed`, `last_signin_ok = 0`, `failed(login_failed)`. A later attempt never signs in automatically with a `signin_failed` row (rule 2). Mail for verification uses the identity's mailbox (§11.5).


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

### 11.5 Two mailboxes (D-70)

The mailbox for an address `a`:
- `a == contact.email` → the `apply.mail` mailbox (host, port, username; settings keys `apply.mail.*`);
- `a == contact.backup_email` → the `apply.mail_backup` mailbox when its host and username are set (settings keys `apply.mail_backup.host|port|username`), else the `apply.mail` mailbox (a backup address that forwards into, or is an alias of, the main inbox);
- password: `vault.get(IMAP_SERVICE.format(host=<host>), <username>)`, so two Gmail accounts on `imap.gmail.com` are two entries with different usernames;
- missing host, username or password → `mail_not_set_up` (before Submit; §4.2 after).

`MailWatcher.wait_for` gains `to_addr: Optional[str] = None`: when set, a message is kept only if one of its `To`, `Cc`, `Delivered-To`, `X-Original-To`, `X-Forwarded-To` headers contains `to_addr` (case-insensitive). The flow always passes the identity's address, so one inbox receiving both addresses never confuses the two accounts. CLI: `mail set-password [--backup]`, `mail test [--backup] [--find-from DOMAIN]` (§14.1).


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

### 12.4 `applied_on_tenant` for the Workday entry choice (D-70)

`store.applied_on_tenant(ats, tenant_host) -> bool`: an `apply_attempts` row with that `ats` and `tenant_host` and `submit_clicked_at` set exists. `apply_flow` puts it into `AttemptContext.applied_on_tenant`; Workday uses it to prefer "Use My Last Application" (§9.4.2).

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
    status TEXT NOT NULL,                  -- AccountStatus: creating | created | verified | signin_failed | unknown | exists_no_password (D-70)
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

Store methods (names fixed; SQL is the engineer's): `create_attempt(job_id, company_id, mode, now) -> int`, `set_attempt_state(id, state, *, step=None, reason=None, detail=None, **cols)` (validates `TRANSITIONS`), `mark_submit_clicked(id, now)`, `attempt(id)`, `attempts_for_job(job_id)`, `reap_attempts(now)`, `apply_duplicate(job_id)`, `apply_counts(company_id, day_start)`, `applied_to_company(company_id, exclude_job_id)`, `add_answers(attempt_id, rows)`, `answers(attempt_id)`, `answer_memory_get(label_norm, field_type, ats)`, `answer_memory_put(...)`, `upsert_account(...)`, `account(ats, host, email)`, `accounts()`, `set_account_status(id, status, **cols)`, `delete_account(id)`, `accounts_to_export()`, `mark_exported(ids, now)`; D-70 (lane V, a V-block, no DDL change): `accounts_for_tenant(ats, host) -> dict[email_lower, status]`, `applied_on_tenant(ats, host) -> bool`, `annotate_answers(attempt_id, notes: dict[tuple[step, field_key], str])` (sets `note` to the given text on the matching rows; §9.4.10). `apply_answers.tier` = 0 and `status = 'prefilled'` for kept site values (§9.1.1, §9.4.6).

Deleting: an application deleted via Undo does not delete attempts (the audit outlives the Undo); `answers` rows are deleted only with their attempt (no UI for it in M21).

D-74 (Q-block, no `SCHEMA_VERSION` change): tables `questions` and `question_sightings` and their methods, in `questions_design.md` §7. They hold employer text only, never an answer.

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
| `accounts add --url URL --email ADDRESS` (M20, D-70) | §10.4: `match_url` → tenant; `getpass` password; `vault.put` + row `created` (resets `signin_failed` / `exists_no_password`) | 0; 2 URL not a known ATS |
| `mail set-password [--backup]` | `getpass`, `vault.put(IMAP_SERVICE…)`; host/username from settings (`apply.mail` or, with `--backup`, `apply.mail_backup`) or `--host/--user` | 0 |
| `mail test [--backup] [--find-from DOMAIN]` | `test_connection` on that mailbox; with `--find-from`, reports the newest message from that domain (time only) | 0 ok / 1 |
| `apply open-profile [URL]` (M20, D-70) | Opens **headed** Edge on the JobScraper profile (`BrowserSession` with `headed=True` forced, same `profile_dir`) at URL (default `https://my.greenhouse.io/`); prints "Edge is open on the JobScraper profile. Sign in where you need to (MyGreenhouse, a Workday site), then close the window."; blocks in `hold(3600)` until the owner closes the window; nothing is filled, nothing logged beyond that line. The profile is locked while an `apply` job runs: a launch error naming the user-data directory → prints "An apply run is using the profile; try again when it ends." exit 1. `show` and `open-profile` are reserved first words of `apply` (job ids are hashes, never these words) | 0 / 1 |
| `apply show <job_id\|attempt_id>` (D-68 A-3; M20, lane B) | All digits → that attempt (`store.attempt`); otherwise the job's newest attempt (`store.attempts_for_job`, last). Prints a header (attempt id, job id, company — title, ATS, mode, state, reason code + detail, resume file + source, queued/started/submit-clicked/finished times), then one line per `store.answers(attempt_id)` row in id order: step, verbatim label, value (the exact value sent, **S-fields included**: this is the owner's own terminal; file fields as file name + SHA-256), tier, confidence, source (+ `rule_id`), status, and the note when present; then the evidence paths `data/apply/<attempt_id>/*.png` (and `failed.html`). This is how the owner reads the audit at the M20 gate. Nothing goes to a job log | 0; 1 unknown id / no attempt |

### 14.2 Job kinds (`web/jobs.py`)

`KINDS += ("apply", "tailor", "mailtest")`. argv: `apply` → `["apply", *job_ids] + (["--dry-run"] if opts.get("dry_run") else [])` (job ids validated against `^[A-Za-z0-9:_-]{1,80}$`, at most 20); `mailtest` → `["mail", "test"]`; `tailor` → tailor design. One job at a time stays the rule: an apply batch blocks a scrape run started from the web until it ends (consequence accepted; caps keep a batch ≤ 10 submissions).

### 14.3 Web API (M21; routers `web/routers/applicant.py`, `web/routers/apply.py`)

D-74: `GET/PUT /api/applicant` move into **M20** with the extended shape in `questions_design.md` §9.1 (`etag`, `form`, `file`; 409 on a stale etag or an unreadable file), and the new `/api/questions…` endpoints are in §9.2 there. The rows below for `/api/applicant` are superseded by that section.

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
- **Profile → Application details** (**M20 by D-74**; the full spec and copy are in `questions_design.md` §3, §10, which supersede this bullet): groups in §5.4 order, completeness meter "N of M needed details filled", "From resume, check" chips, sensitive groups marked "Never sent to the AI", Declarations as Yes/No switches with the plain question text, inline error per field from the 422 response.
- **Attempt panel, D-74 addition (M21, WP-W6):** on a `failed(unanswerable_required)` attempt, link "Answer it in Profile" and, once its questions are answered, **Retry** (the same `POST /api/questions/retry`).

---

## 15. Extension walkthrough: add a new ATS adapter in 6 steps (no core edits)

Example: SmartRecruiters (M22).

1. Create `src/jobscraper/apply/ats/smartrecruiters.py` with a class implementing `AtsAdapter` (contracts §"Adapter protocol"): `name = "smartrecruiters"` (equal to the watchlist provider), `needs_account`, `password_rules`, `mail_domains`, `otp_pattern`, and the methods. Use only `browser.py` primitives and `classify.py` for page states; raise `ApplyFailure` with a `ReasonCode` for every stop.
2. `match_url` / `tenant_from_company`: the URL regex and the board from the company slug.
3. `plan_from_schema` returns None unless the ATS publishes a form schema; `read_step` maps DOM controls to `FormField`s, tagging standard fields with `Canonical` values (add none: if a new standard field is needed, that is a contract change → architect).
4. `submit` / `after_submit`: the confirmation signal and the error markers; `prefill` (return "" unless the ATS has its own autofill the design adopts) and `read_values` (the shown value per field).
5. Register: one line in `apply/ats/__init__.py` `REGISTRY`.
6. Fixture + tests (tester): a recorded HTML page in `tests/fixtures/apply/<ats>/`, served by a local `http.server` in the test, filled in dry-run mode; assert the plan, the answers and `ready_to_submit`.

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
  mygreenhouse: true         # D-70: click "Autofill with (My)Greenhouse" when present, then fill only the gaps (§9.1.1)
  mygreenhouse_wait_s: 20
  workday_entry: auto        # auto = §9.4.2 rule (last application on a tenant applied to before, else Apply Manually) | manual
  max_wizard_steps: 15
  llm_text_temperature: 0.3
  mail:
    host: imap.gmail.com
    port: 993
    wait_s: 300              # F-36
    poll_s: 10
  mail_backup:               # mailbox for contact.backup_email; host "" = same mailbox as `mail` (§11.5)
    host: ""
    port: 993
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
| F-12 | §7.4, §13 `answer_memory`, §14.3 correct (M22); D-74: tier 3 reads `extra` (`questions_design.md` §6, ADR-0005) |
| F-13 (proposed, D-74) | `questions_design.md` §4–§10 |
| F-30 | §3, §12, §14.1, §14.2, §14.3 `POST /api/apply`, §14.4 Inbox |
| F-31 | §6, §9.0, §9.1 plan, §9.1.2, §9.4.1 |
| F-32 | §7 (tiers, schemas, grounding, recording), §7.3.3 `yes_if` |
| F-33 | §7.5 |
| F-34 | §8, §9 fill specs, §9.1.1 (MyGreenhouse, tailored resume replaces the autofilled one), §9.4.6–§9.4.10, §3 resume choice, §16 `resume_format` |
| F-35 | §10 (incl. §10.5 backup email), §9.4.3, §13 `ats_accounts`, §14.1 `accounts add`, `apply open-profile` |
| F-36 | §11 (incl. §11.5 two mailboxes), §9.4.4 |
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

### 19.1 M20 (re-scoped by D-70: Workday end to end + Greenhouse with MyGreenhouse) — lanes P, B, T, then V

**D-70:** lane V (vault, accounts, mail, Workday) moves from M21 into M20; it starts in the first freed engineer slot, its browser WPs after `browser.py` (WP-B4) and spike S-5's recordings. Lane V owns `vault.py`, `apply/mail.py`, `apply/accounts.py`, `apply/ats/workday.py`, `apply/ats/workday_widgets.py`, and after lane B merges a V-block in `apply_flow.py` (identity, mail, prefill policy OVERWRITE, review cross-check), `store.py` (V-block: `accounts_for_tenant`, `applied_on_tenant`), `cli.py` (V-block: `accounts`, `mail`). Lane B adds MyGreenhouse (`greenhouse.py` `prefill`/`read_values`, the KEEP policy in `apply_flow.py`) and `apply open-profile`. Lane P adds `yes_if` and `contact.backup_email`. The planner's `apply_build_plan.md` §2–§5 has the WPs.


| Lane | Branch | Files (only these) | Delivers |
|---|---|---|---|
| **P: profile + resolver** | `eng/M20-P-resolver` | `src/jobscraper/applicant.py`, `src/jobscraper/apply/resolve.py`, `src/jobscraper/apply/declarations.py`, `src/jobscraper/apply/__init__.py` (exact content §2.1), `src/jobscraper/backends.py`, `config/applicant.example.yaml`, `cli.py` (one new block: `applicant` verb) | §5.1–§5.4, §7 complete (tiers 1–5 incl. memory lookup through an injected callable), backend `format`/`temperature`/`seed`/`top_k` |
| **B: browser + Greenhouse + flow** | `eng/M20-B-greenhouse` | `src/jobscraper/apply/{__init__.py, detect.py, plan.py, classify.py, browser.py}`, `src/jobscraper/apply/ats/{__init__.py, greenhouse.py}`, `src/jobscraper/apply_flow.py`, `src/jobscraper/models.py` (+`posting_key`), `src/jobscraper/web/data.py` (import moved), `src/jobscraper/store.py` (one appended block: §13 tables + methods + `app_events.by`), `src/jobscraper/config.py` (ApplyConfig), `config/config.yaml` (`apply:` block), `requirements.txt` (`playwright`, `keyring`), `cli.py` (one new block: `apply` verb incl. `apply show`), `web/jobs.py` (kind `apply`) | §3, §4, §6, §7.7 context building (resume text, alias groups), §8, §9.0–§9.1, §12, §13, §14.1 `apply show`, §16, §17 |
| **T: deterministic tailor** | per `tailor_design.md` | per tailor design | the tailored DOCX/PDF for `tailor_for_apply` |

Disjointness: lanes P and B both create `apply/__init__.py` with the identical one-line content (git merges identical adds cleanly); `cli.py` gets one self-contained block per lane (Coordinator resolves the textual merge, `04_team.md` §2); `store.py` is touched by B and T, each appending its own block.

Integration order: P and T first (no browser); B builds against the contracts with a stub resolver (`resolve_all` returning tier-1 answers only) and a stub `tailor_for_apply` (returns the original resume), then a final B work package swaps in the real ones after P and T merge. Lane V follows (D-70). Lever/Ashby and the web/UI stay M21.

Dev rule (NF-08): every lane runs against a copied DB, web on port 8768; real Greenhouse pages only in `--dry-run` until the owner triggers the one M20 submission.

**D-74/D-75 (Q-30):** two more M20 lanes. **Q** (Python: D-75 work rights, applicant API, tier-3 `extra`, capture module, store Q-block, `/api/questions`, then the `apply_flow` Q-block after lane B merges) and **U** (Vue: Application details form, Questions from applications). Lane U runs in the slot lane V frees while V waits on S-5 and lane B. WPs are in `apply_build_plan.md` §2.5; the design is in `questions_design.md`.

### 19.2 M21 (preview; the planner splits it)

Lane V moved to M20 (D-70); M21 keeps only `apply/edge_save.ps1` (sync route) from it. Lane L: Lever + Ashby adapters. Lane W: web router `apply.py` + Vue (attempt panel, audit view, Settings → Apply/Accounts); the applicant router and the Profile form moved to M20 lanes Q and U (D-74, `apply_build_plan.md` §2.5); `applicant init` stays M21 (WP-W1b). The tailor LLM layer is its own lane per the tailor design.

---

## 20. Pending items, deviations, PRD conflicts, requests

### 20.1 Pending spikes (build with the default now)

| Item | Default until settled |
|---|---|
| S-1c Edge sync from the app profile (owner test) | `edge_sync: false`, CSV export route; UIA Save click off |
| S-1e Edge CSV columns | `name,url,username,password,note`; owner verifies with a one-row import (first-export note) |
| S-3 Submit-time reCAPTCHA behaviour (R-3) | classifier as §8.4; the M20 owner submission is the evidence |
| S-4 Gmail IMAP + Greenhouse security-code format | `otp_pattern = [A-Za-z0-9]{8}` for Greenhouse, `\d{6}` default |
| S-5 real Workday flow at 2 employers (Q-23, D-70) | §9.4 defaults; the 13-item checklist in §9.4; recordings in `tests/fixtures/apply/workday/<tenant>/` |
| S-6 MyGreenhouse in the JobScraper profile (after owner task Q-24) | §9.1.1 defaults: button regex, not-signed-in signals, `.select__single-value` read-back, resume remove control; dry run only, no Submit |
| Lever / Ashby ids marked K | confirm on a recorded fixture as the first step of each M21 adapter WP |

### 20.2 Additions and deviations (not conflicts)

- Reason codes `cancelled` and `mail_not_set_up` added to PRD §7.2's list (distinct owner actions).
- `vault.py` in the foundation instead of `apply/` (web needs it).
- `apply_flow` imports `tailor_flow` (one orchestrator→orchestrator edge).
- `app_events.by` column for "Applied by JobScraper".
- D-69 (tester testability items): no `submitting → failed` and no `failed` after the click (ADR-0004, contract v2: `POST_CLICK_STATES`, `can_transition(..., clicked=)`, `verifying_email → submitted_unconfirmed`); apostrophes kept in `norm_label`, wider decline phrases; declaration `current_employee_at_company`; signatures `resolve.load_rules(path)`, `declarations.AMBIGUOUS`, `store.reap_attempts(now)`, `apply_flow.run(..., http=None, browser_factory=None)`, `computed_facts(profile, today: date)`; fixture paths `tests/fixtures/apply/...`.
- D-68 (planner gaps A-1..A-4): alias groups in `ResolveContext` for grounding rule 3; resume-text source decided by `apply_flow`; CLI `apply show`; `experience_months` defined as a merged-interval union (§5.1). Contract change is additive (two new `ResolveContext` fields with defaults).
- D-70 (contract v3, additive: `AnswerSource`, `PrefillPolicy`, `PREFILL_POLICY`, `AnswerStatus.PREFILLED`, `AccountStatus`, `SignUpOutcome`, `WorkdayEntry`, `EMPLOYER_SPECIFIC_DECLARATIONS`, `ALWAYS_OURS`, `ResolveContext.account_email`, `AttemptContext.applied_on_tenant`/`prefill`, adapter methods `prefill` and `read_values`, transition `signing_up → signing_up`). No ADR: nothing existing changes meaning; the two new protocol methods are required of every adapter (Greenhouse implements them in WP-B11).
- D-74 (contract v4, additive: `QuestionKind`, `QuestionReason`, `QuestionStatus`, `CapturedQuestion`, `EXTRA_KEY_PATTERN`, `ResolveContext.job_country`; new `unanswerable_required` hint copy). Answers to captured questions live in `data/applicant.yaml` `extra:` (ADR-0005); tier 3 reads them and is now also consulted when tier 2 stops on a sensitive no-fit (the owner's explicit answer); unknown answers carry the matched tier-2 key in `rule_id`. The `answer_memory` table is frozen. Applicant API and Profile form moved M21 → M20. No new reason code: a stopped attempt keeps `unanswerable_required` and is retried as a new attempt.
- D-75: work-rights maps take a `default` key; the standing answer (authorised, no sponsorship) applies when absent; the two `.SG` paths leave `REQUIRED_PATHS`; tier-2 kind `country_bool` answers any country (no fall-through to tier 5); the tier-5 prompt and grounding corpus always carry `work_rights_text` (`questions_design.md` §8).
- D-70 deliberate exception to "fill only the empty fields" under MyGreenhouse: the resume, the email, single checkboxes and employer-specific declarations are always JobScraper's (§9.1.1) — a saved answer from another application must not stand in for "Have you worked for <this employer>?".
- D-70: on Workday a required field the resolver cannot answer fails the attempt even when the site (or our last application) shows a value (fail closed, ADR-0003).
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

D-70 delta lookups (2026-11-02, 5 of the 10 allowed):
- MyGreenhouse Quick Apply (button "Autofill my application"; sign-in "with a code sent to their email"; employer enables it under Configure → MyGreenhouse → Quick Apply; profile holds resume, contact, employment, education, links, self-identification): https://support.greenhouse.io/hc/en-us/articles/35746094035099-MyGreenhouse-job-alerts-and-quick-apply (fetched).
- MyGreenhouse candidate FAQ (account created with an email address; "common application questions" saved): https://my.greenhouse.com/faq (fetched). Search snippets of the same support article give the copy "Autofill with Greenhouse" (search only).
- Workday Apply choices ("Apply Manually" / "Autofill with Resume" / "Use My Last Application"): no official Workday page found; user and vendor reports only (e.g. https://www.teamblind.com/post/shyte-workday-k0fzthkq, https://intercom.help/earnbetter-83fd641ab32a/en/articles/10063750-how-to-autofill-job-applications-with-extension), search 2026-11-02. Ids stay K until S-5.
- Workday accounts are per tenant; "account already exists" after social sign-in; lock-out after repeated failed sign-ins (https://kb.wisconsin.edu/workday/152462, https://forums.developer.nvidia.com/t/nvidia-careers-workday-login-blocked/357855), search 2026-11-02. Basis for "one sign-in per identity per attempt" and no automatic retry after `signin_failed`.
