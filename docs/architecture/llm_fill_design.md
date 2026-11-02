# LLM-driven form filling (D-78; KA-1, KA-2)

**Stage B delta** for D-78 ("the LLM should be the one filling the information up"), queue Q-35 (+ Q-40: review Q-30 F1, F3, F4). Author: architect, 2026-11-03. **Status:** DRAFT for stage E cross-review.
**Decision record:** `adr/0006-llm-driven-form-filling.md`. **Contracts:** `src/jobscraper/apply/contracts.py` v5 (additive, plus superseded parts listed in the version comment). **Build plan:** `llm_fill_build_plan.md`.
**Inputs:** D-70, D-74, D-75, D-76, D-77, D-78, D-79 (`instructions/02_status.md` §4); `apply_design.md` (cited **AD §n**); `questions_design.md` (**QD §n**); ADR-0003, ADR-0004, ADR-0005; spikes `spikes/S-5_workday.md` and `spikes/S-5b_llm_workday.md` (the prototype `spikes/llm_fill/*.py` worked unchanged on two Workday tenants); `docs/reviews/Q-30.md`.

Reading guide: §1 is the whole design on one page. Engineers: §2 (where code goes), then the section your work package cites. Every "MUST" is a build rule.

---

## 1. Summary

```
apply_flow (orchestrator; state machine, caps, accounts, mail, submit: UNCHANGED)
   │  per wizard step / page, in state FILLING:
   ▼
apply/pagefill.fill_page(page, nav, ctx, services)            ── generic, the same for every ATS
   1 READ     apply/page.py      every visible control → PageField (label, kind, required, options,
                                 shown value + who put it there, preceding question, entry group)
   2 LOCK     apply/locks.py     deterministic answers the model never overrides: files, account email,
                                 declarations (tier 4), work rights (D-75), sensitive tier-2 keys,
                                 consents, the owner's own answers (extra, F1-guarded)
   3 ASK      apply/llm_fill.py  one model call per page chunk (an entry = one chunk): for each open
                                 field the model returns {source, ref, value, evidence}
   4 GUARD    apply/guards.py    refs → values by the program; grounding; choice-vs-source; entry scope;
                                 sensitive; prefill trust; second opinion on risky required answers
   5 FILL     apply/widgets.py   generic widget families fill and read back; one corrective pass on
                                 site errors
   6 STOP?    any required field still unknown → ApplyFailure(unanswerable_required) after capturing
                                 every such question for the Questions inbox (F-13)
   ▼
nav.next_step()  (apply/ats/<name>.py: navigation only)
```

- **The model decides, the program writes.** The model chooses *which source* answers each field. Whenever that source is a fact (profile path, the owner's `extra` answer, a standing fact), the program produces the value from the fact with the existing deterministic mappers (`resolve.fit_*`); the model's own text is used only for values that come from the resume or the job posting, and then only after the grounding guards. Sensitive values (AD §5.3) are never in a prompt: the model cites `profile:identity.gender`, the program fills it.
- **Site modules navigate, they don't fill.** `SiteNavigator` (contracts v5) opens, takes the resume import, handles the account wall, names the step, clicks Next and Submit, reads the confirmation. Reading and filling fields is generic; widget dialects (Workday prompts, react-select, segmented dates) are recognised by DOM pattern in one generic module, not per site.
- **Import from resume is always taken** (D-78 reverses D-70's Workday rule). The file the import reads is the tailored resume, so the import and the attachment are the same file (D-70 "tailored resume replaces the autofilled one" holds by construction, and is still checked).
- **Fail closed, unchanged.** A required field nothing can back up stops the attempt before anything is sent (ADR-0003) and becomes a question in the Profile tab (F-13), so the owner answers once and the retry proceeds. The state machine, submit-once, `submitted_unconfirmed` (ADR-0004), caps, CAPTCHA stop and NF-06 are untouched.

---

## 2. Components and boundaries

### 2.1 Files

```
src/jobscraper/apply/
  contracts.py   v5 (architect)
  page.py        NEW  generic page reader: PageField list, option collection (+ one-level category
                      expansion), per-field errors, value read-back, generic entry_sections()      (§3)
  widgets.py     NEW  widget families: detect + fill + read back (text, native select, ARIA listbox,
                      searchable combobox incl. Workday prompt and react-select, radio, checkbox,
                      segmented date, file). Supersedes ats/workday_widgets.py (WP-V6)               (§3.2)
  facts.py       NEW  fact catalogue (what the model may see) + fact_value(ref, field, ctx)          (§5)
  locks.py       NEW  deterministic pre-pass over PageFields (wraps resolve tiers 2-4)              (§4)
  llm_fill.py    NEW  prompt, JSON schema, call, reply parsing, pick_option, entry recheck,
                      second opinion, decision cache keys                                           (§6)
  guards.py      NEW  pure: ModelDecision + PageField + facts → Answer, stop list                     (§7)
  pagefill.py    NEW  fill_page(): read → lock → ask → guard → fill → read back → corrective pass   (§8)
  resolve.py     kept: fit_* mappers, load_rules, tiers 2-4 (used by locks/facts), grounded();
                      F1 and F4 fixes (§12). Tier 1 tagging and tier 5 retire (§4.1)
  plan.py        + qualified_label() (F1, §12.1)
  questions.py   capture from PageFields (context-qualified labels, F1)
  ats/workday.py NEW  SiteNavigator (navigation only)                                               (§9.1)
  ats/greenhouse.py   becomes a SiteNavigator: precheck, open, choose_entry = MyGreenhouse (§9.2)
apply_flow.py    FILLING loop calls pagefill per step; identity/mail (lane V V4) unchanged in substance
store.py         apply_answers columns + fill_cache table (§14)
backends.py      Backend.complete gains keep_alive (optional), warm() helper                       (§13)
```

### 2.2 Layering (NF-04, `tests/test_layering.py`)

- Only `backends.py` talks to the model: `llm_fill.py` receives a backend object and calls `backend.complete(...)`, exactly as `resolve.py` tier 5 did. No `/api/chat`, no HTTP in `apply/`.
- Only `store.py` has SQL: `fill_cache` reads/writes are store methods; `pagefill` gets them as injected callables (like `MemoryLookup`).
- `apply/` imports `apply.contracts`, foundation (`applicant`, `vault`, `config`, `models`), stdlib, Playwright. `facts.py` uses `applicant.llm_extract`, `applicant.computed_facts`, `applicant.is_sensitive`. Stages still don't import each other; the master resume entries reach `facts.py` through `ResolveContext` (filled by `apply_flow` from `tailor_flow`, D-68 pattern).
- No new layer; the tester's module classification needs no change (all new modules are inside the `apply` stage).

---

## 3. The page model (`apply/page.py`)

### 3.1 What the reader returns

`read_page(page, nav, ctx, *, scope: str = "") -> list[PageField]` (contracts v5 `PageField`), ported from the spike's `READER_JS` with these rules:

| Item | Rule |
|---|---|
| Which controls | visible, enabled `input`, `textarea`, `select`, `button[aria-haspopup="listbox"]`, `[role="combobox"]`, `[role="spinbutton"]` groups, inside `nav.scope()` (or the page minus `header, nav, footer, [role=banner|navigation|contentinfo]`) |
| Dropped | `type=hidden|submit|button|image|reset`, `password` (accounts are the navigator's), honeypots (`data-automation-id="beecatcher"`, name/label containing "for robots" / "honeypot"), read-only inputs |
| Label | `aria-labelledby` texts, else `label[for]`, else the field container's `legend`/`label`, else `aria-label`, else placeholder; trailing `*` removed |
| Required | `aria-required="true"`, `required`, a trailing `*`, or an `abbr` marker in the container |
| Description | the container's help text (`aria-describedby` non-error targets), ≤ 300 chars |
| Kind → `FieldType` | text-like inputs → TEXT / EMAIL / PHONE / URL / NUMBER by `type`; `textarea` → TEXTAREA; native `select` and listbox buttons → DROPDOWN; radios (grouped by `fieldset` / `radiogroup` / container) → RADIO; one checkbox → CHECKBOX; a checkbox group → MULTI_CHOICE; a combobox/prompt holding several pills → MULTI_CHOICE, else TYPEAHEAD (options known) or TYPEAHEAD with `options_complete=False` (search-driven); segmented date → DATE; `input[type=file]` → FILE |
| Options | native: `option` texts; listbox/prompt: open, read `[role="listbox"] [role="option"]` and `[data-automation-id="promptOption"]` (not chosen pills), Escape; ≤ 400. **Category expansion (L1):** options carrying a sub-list marker (right chevron) are opened one level and listed as `"Category > Leaf"`; leaves stay as they are |
| Shown value | text: `value`; select/listbox: the selected text ("" when it reads "Select One" or similar placeholder); radio: checked option's label; checkbox: `"true"`/`"false"`; prompt: pill texts; date: section **values** joined (never `aria-valuetext`, which holds the MM/DD/YYYY placeholder); file: the file name shown in the container (Workday empties `input.files` after upload) |
| Context | the label of the previous PageField in the same group/section (for generic labels, §12.1) |
| Group | when the control sits inside an `EntryGroup` from `nav.entry_sections()`: `group = "<section>#<index>"`, `group_title` = the heading |
| Error | the text of `[data-automation-id="inputAlert"]`, `[data-automation-id="errorMessage"]`, `[role="alert"]` linked by `aria-describedby`, or inside the container (S-5: `inputAlert` + `aria-invalid`) |
| Key | the reader's mark `data-llmfill="f<n>_<rand>"`, stable for this read; the audit key is `<step>:<automation id or html id or slug(label)>[#n]` (AD §6 key rules) |

### 3.2 Widget families (`apply/widgets.py`)

A family = `detect(el) -> bool`, `options(page, loc) -> list[str]`, `fill(page, loc, value) -> bool`, `read(page, loc) -> Value`. Families, in detection order: `segmented_date`, `file`, `native_select`, `aria_listbox` (button + listbox; Workday "Select One"), `prompt` (Workday `selectinput` / `promptOption` / `selectedItem` pills with `DELETE_charm`, search on Enter inside the search box), `react_select` (Greenhouse `.select__control`, AD §8.2 `choose_react_select`), `combobox` (any other ARIA combobox: type, pick), `radio`, `checkbox`, `text`. Reuse `browser.py` primitives (`fill_text`, `choose_native`, `choose_listbox`, `choose_radio`, `set_checkbox`, `upload`, `typeahead`, `settle`).

Rules that came out of S-5b and are MUST:
- **Strict listbox read-back:** a listbox counts as filled only when its button text equals the option **and** the field shows no error after blur. (S-5b: a listbox read back as filled while the site held no value.)
- **Dates by section role, not position;** a `YYYY-MM` value fills day `01` only if a Day section exists; equality check compares the numbers (`2026-03` = `3/2026`), so a correct prefilled date is not retyped.
- **Workday clicks:** when a click times out, click the preceding sibling `div[data-automation-id="click_filter"]`, then the following sibling, then the parent (S-5 item 2; spike `wd_click`). This lives in `widgets.click()` and is used by navigators too.
- **Multi-select:** remove wrong pills first, add each wanted item, read back as a set.
- **Upload:** success = the file name appears in the container within 30 s (Workday clears `input.files`).

### 3.3 Provenance of shown values (`ValueOrigin`)

On the **first read of a page in an attempt**, every non-empty shown value gets the attempt's import origin: `ctx.prefill` as returned by `nav.choose_entry` (`resume_import`, `mygreenhouse`), else `site_default`. Values JobScraper typed get `ours`; a re-read (corrective pass, §8 step 7) keeps the first-read origin for fields it did not touch.

**Only site values are shown to the model as `current`.** A value JobScraper typed earlier is never shown back as "current" (S-5b: our own earlier values biased the model into keeping them). On a corrective pass the model sees the site's error instead.

---

## 4. Locks: the deterministic pre-pass (`apply/locks.py`)

`lock_page(fields: list[PageField], ctx: ResolveContext, rules, *, today) -> dict[str, Answer]` runs before the model. A locked field is final: the model does not answer it (it is shown in the prompt as context only, `locked: true`, without its value when private). Locks reuse resolver code; no rule here is new except L6 and L7.

| # | Lock | Source and value | Answer |
|---|---|---|---|
| L1 | FILE whose label/section/automation id or page text matches `resume|résumé|cv|curriculum|drop (off )?your|autofill` | `ctx.resume_path` (the tailored file, else the original). Shown file name equal to ours → keep; another name → remove it, upload ours (D-70). A FILE whose label matches `transcript` → `documents.transcript` when set. Other required FILE → unknown (never guessed; not captured, QD §4.2); optional → blank | tier FIELD_MAP, `field_map:resume` |
| L2 | EMAIL kind, or a label phrase-matching `email` (AD §7.1, ≤ 4 tokens) | `ctx.account_email` or `contact.email` (private) | FIELD_MAP, `field_map:email` |
| L3 | Declarations (tier 4, AD §7.5): `declarations.classify(label_norm, description_norm)` | AD §7.5 rules, unchanged. `AMBIGUOUS` → unknown (reason `attestation_unclear`; never the model) | DECLARATION, `declaration:<label>` |
| L4 | Work rights (tier 2 `country_bool`, D-75, QD §8.2) | the profile map, then `default`, then the standing answer; a conflict → unknown (reason `conflict`) | PROFILE_RULE, `profile:singapore_status.<key>` |
| L5 | Tier-2 rows with `sensitive: true` (residency incl. `yes_if`, NS, race, gender, DOB, EEO) and the consent rows (`consents.privacy_consent`, `consents.certify_true`) | AD §7.3 mapping; sensitive no-fit → tier 3 (owner's answer) → else unknown (reason `no_option_fits`/`profile_gap`) | PROFILE_RULE |
| L6 | Tier 3 owner answers (`extra`, QD §6.2) **with the F1 guard** (§12.1) | the owner's own answer | MEMORY, `memory:extra.<key>` |
| L7 (new) | A declaration lock (L3) on a Yes/No **choice** whose label contains a negation marker (`not`, `never`, `no`, `none`, `neither`, `free of`, `without`) | the bool can't be mapped safely onto "Yes/No" (e.g. "Do you confirm you have no criminal record?") → unknown, reason `attestation_unclear` | — |

Non-sensitive tier-2 rows no longer answer on their own; their `kind`/`value_map`/`yes_if` are what `facts.fact_value` uses when the model cites that path (§5.3).

### 4.1 Resolver tiers 1–5 under D-78 (what is kept, what retires)

| Tier | Before (AD §7) | Under D-78 |
|---|---|---|
| 1 Field map | adapters tag `Canonical` from site ids/schema names; resolver maps to profile paths | **Retired as site tagging** (it is the "hardcoded manual entry" D-78 removes). Its value logic survives as facts: `standing:full_name`, `profile:contact.phone_number` (digits, the country part filled from `phone_country_code`), `profile:contact.country` (ISO → name table), `standing:account_email`, `standing:today` (Asia/Singapore), `standing:how_heard` (AD §7.2 HOW_HEARD fallback), L1 resume, L2 email |
| 2 Profile rules | label synonyms → profile path → `fit_*` | **Kept as locks** for sensitive keys, `country_bool`, consents (L4, L5). Non-sensitive rows become mapping metadata only |
| 3 Memory | `extra` by label, then `answer_memory` | **Kept as a lock** (L6) with the F1 guard; non-sensitive `extra` entries are also facts the model may cite (`extra:<key>`) for reworded questions |
| 4 Declarations | classifier + rules | **Kept as a lock** (L3) + L7 |
| 5 Per-field LLM | two runs, evidence, grounding | **Retired**; replaced by the page call. Its grounding check (AD §7.7) becomes guard G3 and its two-run agreement becomes G5 (second opinion) |

`resolve.resolve_all` stays callable until the cleanup WP (the `apply.fill: rules` path, §13.3).

---

## 5. Facts: what the model may see (`apply/facts.py`)

### 5.1 Catalogue

`fact_catalogue(profile, ctx, *, today) -> list[Fact]` (contracts `Fact`). Refs are exact strings; the model's `ref` is constrained to them by the JSON schema (enum).

| Namespace | Entries | Visible value? |
|---|---|---|
| `profile:<path>` | every leaf of `data/applicant.yaml` after D-79 normalisation, list entries indexed (`profile:experience[1].title`); template placeholder rows (employer starting "Example ") dropped | **Only for `applicant.llm_extract` allow-list paths** (AD §5.3) plus `identity.legal_first_name`, `legal_last_name`, `preferred_name` (names are not S). Every other path is **private**: all S paths (`contact.*` except city/country, `identity.date_of_birth`, `identity.gender`, `singapore_status.residency_status`, `declarations.*`, `us_self_id.*`, …) and the non-allow-listed ones such as `singapore_status.nationality`. The model sees `title` and `set`/`empty` only |
| `extra:<key>` | each `extra` entry (QD §6.1) usable for this employer (generic-label entries only when scoped to this employer, §12.1) | non-sensitive: `title` + value or picks; sensitive: private |
| `standing:<id>` | `today` (YYYY-MM-DD, Asia/Singapore), `full_name`, `experience_years`, `experience_months`, `graduation_year` (AD §5.1 `computed_facts`), `work_rights` (`applicant.work_rights_text`, D-75), `worked_here` and `current_employee_here` (AD §7.5 deduction for this employer), `previously_applied` (AD §12.3), `how_heard` (the profile default, "Company careers website" if empty), `account_email` (private) | yes, except `account_email` |

The prompt shows facts as one line each, `ref: value` or `ref: (private, set)` / `ref: (private, empty)`, in a fixed order (profile, extra, standing). Empty non-private facts are omitted (S-5b: blanks tempt the model), except entry facts.

### 5.2 Resume and job

- **RESUME** = `ctx.resume_text` (AD §7.7: the tailor master's text, else the extracted file), first 8000 chars. When the master's entries are available (`ResolveContext.resume_entries`, filled by `apply_flow` from `tailor_flow`, additive field; see §15 open item O-2), each entry is also a **block** with an id (`resume:experience[0]`…) used by entry calls (§6.4) and the entry-scope guard (G6).
- **JOB** = company, title, location (from the job row), the step title, first 3000 chars of the JD.

### 5.3 `fact_value(ref, field, ctx) -> Optional[Fit]`

The program's value for a cited fact, by the fact's kind: `fit_bool`, `fit_enum` (with the tier-2 row's `value_map` and `yes_if` when a row for that path exists and its synonyms match the label), `fit_text`, `fit_number`, `fit_salary`, `fit_country`, `fit_date`, decline mapping (AD §7.3.2), `extra` fit by kind (QD §6.2 step 4). Returns None when no option fits. For a private fact this is the **only** way a value reaches the page.

---

## 6. The model call (`apply/llm_fill.py`)

### 6.1 Chunks

One call per chunk: each entry group of the page is its own chunk (its fields + only its resume block); the remaining open fields go in chunks of ≤ `llm_fill.max_fields_per_call` (20). Locked fields of the chunk appear as context lines. FILE fields never reach the model.

### 6.2 Prompt

`SYSTEM` (constant, `FILL_PROMPT_VERSION = "fill:v1"`; ported from the spike's eight rules plus the fact-ref rules):

```
You fill in part of a job application form for ONE applicant. For every field id, say where the
answer comes from and give it. Sources:
- profile / extra / standing: a FACT. Give its exact ref. The program writes the value from the fact,
  so for a private fact leave value "" (never guess a private value).
- resume: the value comes from RESUME; copy into evidence a short exact quote (at most 25 words).
- job: the value comes from JOB; quote it the same way.
- keep: the field's current value (set by the site) is right; quote the source that shows it.
- unknown: the sources don't settle it.
Rules:
1. Never invent. If the sources don't contain the answer, source "unknown".
2. For a field with options, copy ONE option exactly (several only where the field allows several).
3. Dates as YYYY-MM-DD, YYYY-MM or YYYY to match the field's parts. Phone number without the
   country code when the form has a separate country-code field.
4. Prefer FACTS for contact details, address, work rights, salary, availability, consents and
   declarations; prefer RESUME for work history, education, skills and dates.
5. Put only the part that belongs in each field: a job title without the company or team, a company
   without the title.
6. A question about one entry (a job's location, a language's level) must use facts stated for THAT
   entry. The applicant's home city is not a job's location. A language level comes only from
   profile languages.
7. A field with a generic question (for example "Please specify") belongs to the question in its
   CONTEXT; answer it only if that question's answer needs it.
8. Optional fields you have no source for: unknown. Don't pad free text.
```

User prompt, **fixed order so the shared prefix is identical across calls of one attempt (§13.2):** `FACTS:` block → `RESUME:` (or, for an entry chunk, `RESUME ENTRY <id>:` only) → `JOB:` → `PAGE: <step title>` → `FIELDS (JSON):` → "Answer with one JSON object keyed by field id."

Field view (JSON per field): `id`, `question` (label), `kind`, `required`, `section`/`group_title` when set, `context` (generic labels), `help` (description), `options` (≤ `long_list`) or `options_note` (count + 5 examples, "answer in words; the program matches it"), `current` (only when `origin` is a site origin, §3.3), `parts` (date sections), `site_error` (corrective pass), `locked: true` (context only, no value when private).

### 6.3 Output schema (`format`)

One property per open field id, each:

```json
{"type":"object","properties":{
  "source":{"type":"string","enum":["profile","extra","standing","resume","job","keep","unknown"]},
  "ref":{"type":"string","enum":["<every catalogue ref>", ""]},
  "value": <see below>,
  "evidence":{"type":"string","maxLength":240}},
 "required":["source","ref","value","evidence"]}
```

`value`: CHECKBOX → enum `["true","false",""]`; DROPDOWN/RADIO/TYPEAHEAD with ≤ `long_list` options → enum of the options + `""`; MULTI_CHOICE with ≤ `long_list` options → array of that enum; long or search-driven lists → string; others → string (`maxLength` = the field's `max_length`, else 255 / TEXTAREA 2000). Parsed into `ModelDecision`s; a field missing from the reply → `unknown` (note `no reply`).

Call options: `temperature=0, seed=7`, `max_tokens = 120 × fields + 200` (≤ 8000), `timeout = llm_fill.page_timeout_s`, think off (backend default).

### 6.4 Follow-up calls (each a small, single-field or single-entry call)

| Call | When | What |
|---|---|---|
| `pick_option` (L2) | a long list (> `long_list`) or a search result list, and the words don't equal an option (exact, or the leaf of a `Category > Leaf` path) | "Pick the one option that means the same as the wanted answer" with an enum of the options + `""`; `""` → unknown |
| entry recheck (E4) | every TEXTAREA in an entry group whose shown value has origin `resume_import` | "This field belongs to entry <id>. Return the text from RESUME ENTRY <id> that belongs in it (or unknown)". The returned text replaces the shown one when it differs; grounded by G3/G6. (S-5b: the parser put a whole Projects section into one job's description.) |
| second opinion (G5) | a **required** choice, yes/no or number whose source is `resume` or `job` | the same field alone, `temperature=0.7, seed=7`, without the first answer; must give the same option/number (AD §7.6 two-run rule) |
| corrective (§8 step 7) | fields with a site error after Next or after fill | re-ask only those fields with `site_error`; our earlier value is not shown |

---

## 7. Guards (`apply/guards.py`; pure)

`decide(fields, locks, decisions, facts, ctx) -> tuple[dict[str, Answer], list[str]]`. Applied in this order per field; the first that rejects ends the field as **unknown** (status `UNKNOWN`, or `UNGROUNDED` for G3/G6) with a note naming the guard (no values in notes).

| # | Guard | Rule |
|---|---|---|
| G1 | Shape | decision parsed; choice value is one of the offered options (or a long-list match from L2); unknown ids ignored |
| G2 | Fact refs | `profile`/`extra`/`standing` need a ref of that namespace from the catalogue. The value is `fact_value(ref, field)`: an empty fact → unknown (reason `profile_gap`, `target_path` = the path when it is a FORM path); no fit → unknown (`no_option_fits`). For a non-private fact, when `fact_value` has a fit the **program's value wins** over the model's (note "fact mapping used" if they differed); when it has none (e.g. a hierarchical "How did you hear" list) the model's option is used if G4 passes against the fact's text |
| G3 | Grounding | `resume`/`job`/`keep` (unless G8 trusts the origin): `evidence` normalised ≥ 3 chars and a substring of the corpus (AD §7.7 corpus); free text passes `resolve.grounded` rules 1–5 (numbers, months/years, dictionary terms, capitalised words, length); a number occurs as a whole token; a URL occurs verbatim; a date's year (and month, when given) occurs in the evidence |
| G4 | Choice vs source | a chosen option not produced by `fact_value` must share a content token (stop words removed; level synonyms native/bilingual/mother tongue, fluent/advanced/proficient, basic/elementary/beginner) with the evidence or the cited fact's text. Yes/No options are exempt here and covered by G5 when required. (S-5b: an invented language level passed an enum-only check) |
| G5 | Second opinion | required choice / yes-no / number from `resume`/`job`: the §6.4 second call must agree, else unknown (`no_rule`) |
| G6 | Entry scope | a field in an entry group answered from `resume`/`keep`: the evidence must lie inside that entry's resume block (or its profile entry facts), never elsewhere (S-5b: a job's location taken from the resume header) |
| G7 | Sensitive | a field whose label matches the sensitive pattern (date of birth, gender, sex, race, ethnic, religion, NRIC / national id, disability, veteran, marital, pronoun) or whose tier-2 match is sensitive: only a lock or a private `profile` ref may answer; `resume`/`job`/`keep` → unknown. A `keep` is allowed only when the shown value equals `fact_value` of the private fact |
| G8 | Prefill trust | `keep` needs: origin in `TRUSTED_ORIGINS` (MyGreenhouse: the owner's own entries) and the field is not always-ours (resume, email), not an employer-specific declaration, not sensitive; **or** G3 (and G6 in an entry) passes. Otherwise: optional TEXT/TEXTAREA → **clear** it; optional choice → leave it, note "unsupported site value left" (status `PREFILLED`, confidence 0.5); required → unknown |
| G9 | Opt-ins | an optional checkbox may be ticked only from a fact ref (`consents.talent_pool_opt_in`, `consents.*`) or a lock |
| G10 | Required unknown | every required field ending unknown is listed in `PageOutcome.unknown_required` (all of them, not only the first, QD §4.1) |

**Answer mapping:**

| Outcome | tier | source | status | confidence |
|---|---|---|---|---|
| lock | per §4 | per §4 | FILLED / UNKNOWN | as before (1.0 / 0.95) |
| fact ref, program value | PROFILE_RULE (profile, standing) / MEMORY (extra) | `profile:<path>`, `standing:<id>`, `memory:extra.<key>` | FILLED | 0.95 |
| resume / job text or choice | LLM | `resume` / `job`; `rule_id = "fill:v1"`, `model`, `prompt_hash` | FILLED | 0.8 text, 0.9 choice with G5 |
| keep | NONE | the origin (`resume_import`, `mygreenhouse`, `site_default`) | PREFILLED | 0.95 trusted, 0.85 grounded |
| cleared (G8) | NONE | the origin | BLANK_OPTIONAL | 0 |
| unknown | NONE | `""` | UNKNOWN / UNGROUNDED | 0 |

`Answer.evidence`, `shown`, `origin`, `entry` are set on every row (contracts v5).

---

## 8. One page (`apply/pagefill.fill_page`)

```
fill_page(page, nav, ctx: AttemptContext, rctx: ResolveContext, services) -> PageOutcome
 1  step = nav.step_id(); sections = nav.entry_sections(); fields = page.read_page(scope=nav.scope())
 2  entries (§10): match groups to resume/profile entries; delete junk entries, add missing ones
    (then re-read once)
 3  locks = locks.lock_page(fields, rctx, rules)
 4  cached = services.cache_get(job_id, field signatures, facts_hash)        (§13.3)
 5  for each chunk of open, uncached fields: decisions += llm_fill.ask(chunk)
    then pick_option / entry recheck / second opinion as §6.4
 6  answers, unknown = guards.decide(...)
 7  if unknown_required: return PageOutcome(...) (the flow captures and stops; nothing on this page is
    typed: a stopped page is left as the site/import put it)
 8  fill every FILLED answer whose value differs from `shown` (dates and multi compared as in §3.2);
    clear the G8 clears; read back every field; fill_failed or a site error on a field → one
    corrective pass (§6.4 corrective call, guards again, fill again); still failing → fill_failed
 9  services.cache_put(...) for answers that passed the guards; return PageOutcome
```

The flow (`apply_flow`, FILLING state) per step: `outcome = fill_page(...)`; record audit rows (AD §7.8, all fields, every step); `unknown_required` → `_capture_questions` (QD §4.1, from the PageFields, §11) → `ApplyFailure(UNANSWERABLE_REQUIRED, first label)`; `fill_failed` on a required field → `ApplyFailure(VALIDATION_ERROR, labels)`; else `nav.next_step()`; a `StepResult.errors` after Next → `fill_page` again on the same step with those fields flagged (one retry per step, AD §9.4.9 rule kept), then `validation_error`. Loop guard: ≤ `max_wizard_steps` Next clicks; the same step id twice without errors → `page_unrecognised` ("stuck at <step>").

**Review page** (`step == "review"` or `StepResult.is_review`): generic check replacing AD §9.4.10's adapter parse: read the page text in the navigator's scope; every FILLED answer on a **required** field whose value is text (not a choice id) must appear in it (normalised AD §7.1; dates and phones compared as digit strings; the resume by file name); missing → note "not shown on review" (no failure: review pages omit fields); a text present in another form → no check. A required choice whose option label does not appear → note only. Mismatch detection stays deliberately weak: the strong checks are G1–G10 and the read-back; the review check catches only a lost resume (the file name must be shown when a resume was uploaded on a previous step → else `validation_error` "review: resume not shown").

Then, unchanged: dry run → `ready_to_submit`; auto → `submit_clicked_at` committed → `nav.submit()` once → confirmation wait → `submitted` / `submitted_unconfirmed` (ADR-0004).

---

## 9. Navigators (`SiteNavigator`, contracts v5): navigation only

Every method is navigation or site structure; none decides an answer. Everything a navigator returns is employer text or page state.

### 9.1 Workday (`apply/ats/workday.py`; replaces AD §9.4.5–§9.4.10)

| Method | Spec (S-5 / S-5b confirmed unless marked) |
|---|---|
| `match_url`, `tenant_from_company` | AD §9.4.1 unchanged |
| `precheck` | nothing |
| `open` | `goto(job_url)`, settle, decline a cookie banner (`legalNoticeDeclineButton`, else a button named Decline / Reject / Necessary only), classify (closed → `posting_closed`), click `adventureButton` (`a[role=button]`, href `<job_url>/apply`) |
| `choose_entry` | dialog `[data-automation-id="wd-popup-frame"]`: **`autofillWithResume` when offered** → return `resume_import`; else `applyManually` → `site_default`; no dialog → `direct` (`site_default`). `useMyLastApplication` is never chosen. `apply.workday_entry: manual` forces Apply Manually. The resume itself is uploaded by the generic page on the wizard's first step (S-5b: "Autofill with Resume" is wizard step 1 with one file input; L1 fills it) |
| `account_wall` | sign-in / create-account controls win over the progress bar (S-5: the account form is wizard step 1 with the progress bar visible) |
| `sign_in`, `sign_up`, `enter_code` | AD §9.4.3 with S-5 ids; submit buttons are clicked through the `click_filter` sibling (`widgets.click`); one sign-in per identity per attempt; vault entry written before the sign-up click (AD §10.2). Verification: AD §9.4.4 (S-5b: neither tenant asked; keep the path) |
| `step_id` | `progressBarActiveStep` text with the `(current )?step N of M` prefix removed, slugged: `my_information`, `my_experience`, `questions_<n>`, `voluntary_disclosures`, `self_identify`, `review`, `autofill_with_resume`, else `custom_<slug>` |
| `scope` | the step container (`applyFlowPage` / the page container), excluding the header and the bottom navigation |
| `entry_sections` | sections `workExperienceSection`, `educationSection`, `languageSection`, `websiteSection`, `certificationSection` (K; else headings "Work Experience", "Education", "Languages", "Websites", "Certifications"); entries = panels / `[role=group]` with a heading ending in a number; delete = `panel-set-delete-button` or a button named `/^delete/i` in the panel; add = `Add` / `/^add( another)?\b/i` |
| `next_step` | `bottom-navigation-next-button` / `pageFooterNextButton` / a button named Save and Continue / Next; if its text is Submit → `StepResult(step, is_review=True)` without clicking. Errors after Next: `inputAlert` texts (S-5), `errorMessage`, an error banner |
| `submit` | on review, the same button whose text is `/^submit$/i`, once |
| `after_submit` | text `/application submitted|thank you for (your )?appl/i`, URL containing `/jobTasks/completed/application` (S-5b) → `confirmed:text` / `confirmed:url`; `/userHome` listing the job → `confirmed:home` |

Retired from AD §9.4: the named-step field tables (§9.4.8), OVERWRITE prefill table (§9.4.6), `prompt_select`/`prompt_options`/`fill_date`/`panels` as Workday helpers (now generic widgets and `entry_sections`), the review parse (§9.4.10), the "never Autofill with Resume" rule (§9.4.2 step 3).

### 9.2 Greenhouse (`apply/ats/greenhouse.py`)

`precheck`: the board API schema request; 404/410 → `posting_closed` (the schema is no longer the fill plan). `open`: AD §9.1. `choose_entry`: the MyGreenhouse autofill of AD §9.1.1 steps 1–5 → `mygreenhouse` or `""` (behaviour and not-signed-in handling unchanged; S-6 still confirms the selectors). No account. `step_id` = `"form"`; `next_step` → `is_review=True`; `submit`/`after_submit`/security code: AD §9.1, §4.2 unchanged. `entry_sections`: the generic default.

The KEEP policy table (AD §9.1.1) is replaced by G8 with `TRUSTED_ORIGINS = {mygreenhouse}`: the owner's MyGreenhouse values are kept without grounding except the resume, the email, employer-specific declarations and sensitive fields, exactly the D-70 exceptions.

### 9.3 Lever, Ashby (M21)

Navigators only: AD §9.2/§9.3 open, submit and confirmation. Ashby's "autofill from resume" input is now **used** (D-78: always import), then every field is checked like any import.

### 9.4 Extension walkthrough: add a new ATS in 5 steps, no core edits

1. `apply/ats/<name>.py`: a class implementing `SiteNavigator`: `name` (= watchlist provider), `needs_account`, `password_rules`, `mail_domains`, `otp_pattern`, `match_url`, `tenant_from_company`.
2. `open` (posting → Apply), `choose_entry` (click the site's resume import if it has one and return `resume_import`), the account methods if it needs accounts.
3. `step_id`, `next_step`, `submit`, `after_submit`, `visible_errors` from the site's buttons and confirmation text; `scope`/`entry_sections` only if the generic defaults miss.
4. One line in `apply/ats/__init__.py` `REGISTRY`.
5. Tester: a recorded page per step in `tests/fixtures/apply/<ats>/` (scrubbed), a fake model reply file, a dry run to `ready_to_submit`.

A widget the generic families don't know is a `widgets.py` change (generic, reviewed once for all sites), not a navigator change.

---

## 10. Imported entries (work experience, education, languages, websites)

| # | Rule |
|---|---|
| E1 | **Import always.** `choose_entry` takes the site's import; the uploaded file is the tailored resume (else the original, AD §3). On any later step a resume attachment showing another file name is replaced (L1). Never submit another file (D-70) |
| E2 | **Match.** Each site entry is matched by the program to one source entry: profile `experience[]`/`education[]`/`languages[]` when non-empty (template rows dropped), else the master resume entries. Key: normalised employer/institution/language (AD §7.5 company match) plus title/degree tokens; best unique match by token overlap ≥ 0.5; ties → unmatched |
| E3 | **Junk.** An unmatched site entry (parser output with no source, e.g. a Projects section turned into a job) is deleted (`delete_locator`). No delete control and a required field in it can't be grounded → stop (unknown) |
| E4 | **Check every matched entry** in its own chunk (§6.1) with its source block only; every TEXTAREA from the import gets the entry recheck (§6.4); G6 holds for every sub-field |
| E5 | **Missing.** A source entry with no site entry: experience and education are added (section `add_locator`, re-read, then E4); languages and websites only from the profile (`languages[]`, `links.*`), never from resume text alone |
| E6 | **Ungroundable optional entry.** An entry whose required sub-field (e.g. a language's proficiency) ends unknown is deleted instead of guessed, when the section isn't required or other entries remain; otherwise the field stops the attempt and is captured |

---

## 11. Stops, capture, reason codes, degradation

- **Required unknown** (G10): before raising `unanswerable_required`, the flow captures every field in `unknown_required` that qualifies (QD §4.2, unchanged rules) — built from the PageField: `label` = verbatim, `label_norm` = `plan.qualified_label(...)` for generic labels (§12.1), `description`, options, `step`, `reason` from the guard (G2 `profile_gap`/`no_option_fits`, L3/L7 `attestation_unclear`, L4 `conflict`, G3/G6 `ungrounded`, else `no_rule`), `target_path` from G2. The owner answers once in the Profile tab; the retry's locks (L6) or facts pick it up. One capture point now (the page stop); the planning capture point disappears with the schema plan.
- **Not captured:** fields whose unknown came from the transport (no reply, timeout): `note` starts `transport:`; those end the attempt as `model_unavailable`.
- **Reason codes:** unchanged, plus **`model_unavailable`** (contracts v5; copy: "The local AI model wasn't available ({detail}), so JobScraper stopped before finishing the form. Nothing was sent." / "Start Ollama, check it with “python -m jobscraper doctor”, then try again."). Triggers: the warm-up call fails before Edge opens (detail "not running"); a page call raises `BackendError` or times out (detail "timed out on <step>"). Always before the click.
- **Degradation table:**

| Situation | Behaviour |
|---|---|
| Ollama not running | `model_unavailable` before the browser opens (warm-up, §13.1); nothing typed |
| A call cut by `done_reason == "length"` | the chunk is re-asked once split in half; fields still missing → transport unknown → `model_unavailable` if any is required |
| Malformed JSON | one retry of that chunk; then as above |
| The model says unknown on a required field | capture + `unanswerable_required` (G10) |
| A long list with no matching option | unknown; required → capture (`no_option_fits` when a fact was cited, else `no_rule`) |
| A searchable list returns nothing for the text | optional: left empty (count logged); required: unknown → capture |
| CAPTCHA / bot check at any point | AD §8.4 unchanged (classify after every navigation and before each fill) |
| Page reader finds no fields on a non-review step | `page_unrecognised` ("no fields on <step>") |

---

## 12. Review Q-30 findings resolved here

### 12.1 F1 (HIGH): generic labels

- **Definition** (`plan.is_generic(label_norm) -> bool`): `label_norm` ∈ `GENERIC_LABELS` (contracts v5), or fewer than 2 content tokens after the QD §5.2 stop words.
- **Qualified label** (`plan.qualified_label(label, description, context) -> str`): for a generic label, `norm_label(label) + " | " + norm_label(description or context)` (help text first, else the preceding question's label from the PageField); a non-generic label returns `norm_label(label)`. A generic label with neither description nor context is **unmatchable**: tier 3 never answers it and capture still records it (the owner sees it with the employer name).
- **Tier 3 / L6:** for a generic label, `extra` entries match only on the qualified label **and** only through `by_employer[<this employer>]`; the entry's base value is never used for a generic label (no reuse at another employer). Non-generic labels: QD §6.2 unchanged.
- **Capture:** `CapturedQuestion.label_norm` = the qualified label; QD §5.2 rule 3 (same `label_norm`) therefore groups only same-context questions; the answer is saved employer-scoped (`by_employer`) for generic labels — the web answer endpoint sets `employer` automatically for a generic key (QD §9.2 change, WP-Q5).
- **Model:** the field view carries `context`; rule 7 of the prompt; `extra` facts with generic labels are listed only when scoped to this employer.
- **Oracles (tester):** two fields "If yes, please specify" with different help texts at two employers → no reuse; same help text, other employer → no reuse; same employer and context → reuse.

### 12.2 F3 (MEDIUM): variant answers and clearing a pick

Adopt the reviewer's fix as the rule (QD §9.2 amended): (a) for `choice`/`multi`, the answer endpoint marks `answered` only the question rows (variants) that received a pick; for an employer-scoped answer, only rows whose sightings are from that employer; (b) the UI sends `[]` for a variant the owner cleared, and `_merge_picks` then drops that variant's option norms from `picks` (and keeps them in `seen`); (c) a group is `answered` only when all its rows are. Oracles: one variant answered → the other stays `open` and its jobs aren't "ready"; a cleared variant's old pick no longer resolves.

### 12.3 F4 (MEDIUM): an all-caps "US"

Decision (D-76 kept, pronoun case covered safely): in a label written entirely in capitals, a bare `US` token yields **both** `US` and `ctx.job_country`; equal work rights → answered; different → `conflict` (unknown, captured). In mixed-case labels D-76 is unchanged (`US` = United States, `us` = pronoun). `resolve.label_countries` changes accordingly; oracle: "ARE YOU AUTHORIZED TO WORK IN THE US?" with `US: false`, `SG: true` → conflict; with both true → Yes.

---

## 13. Latency budget, caching, config

### 13.1 Budget (qwen3:14b on the owner's GPU; S-5b measurements)

| Item | Measured | Budget |
|---|---|---|
| Cold model load (first call) | ~33 s for a 15-field page whose warm re-ask took 10 s | hidden behind Edge start-up by a **warm-up call** (`backends.warm(backend)`: one 1-token completion, `keep_alive = llm_fill.keep_alive`) at attempt start |
| Page, 1–15 fields | 2–10 s | `page_timeout_s` 120 per call |
| Page, 47–54 fields (imported experience) | 47–54 s, ~3.4–3.8k output tokens | chunked per entry (§6.1): ≈ the same total, but each call ≤ 20 s and scoped |
| Follow-ups (pick, recheck, second opinion) | ~1–2 s each | ≤ 15 per attempt (logged) |
| Whole Workday attempt (6–7 steps) | — | model ≤ ~150 s + browser ≤ ~180 s; `attempt_timeout_s` raised 420 → **900** (NF-07 "≤ 4 min typical" is exceeded on Workday; recorded as a deviation, §15) |

### 13.2 Prompt-prefix reuse

The `FACTS` + `RESUME` block is byte-identical across the calls of one attempt and comes first; per-call parts come last. Ollama keeps the KV state of a shared prefix while the model stays loaded (third-party documentation; unverified: WP-M4 measures `prompt_eval_ns` on the second call and records it). `keep_alive` keeps the model loaded between steps.

### 13.3 Decision cache (`fill_cache`, §14)

Key `(job_id, field_sig, facts_hash, prompt_version, model)`: `field_sig = sha256(kind + label_norm(qualified) + sorted option norms + group + origin + norm(shown))[:16]`; `facts_hash` = sha256 of the profile file bytes + resume text + JD text. Only guarded outcomes (FILLED/PREFILLED/BLANK_OPTIONAL answers with their `ModelDecision`) are cached; locks are never cached (cheap and they must see the latest profile). Use: a retry of the same job after the owner answers a question replays earlier steps without model calls. Scope is one job (never across employers). Rows older than 30 days are deleted at `apply_flow.run` start. Off with `llm_fill.cache: false`.

### 13.4 Config (`apply:` block additions; `ApplyConfig`)

```yaml
apply:
  fill: llm                  # llm (D-78) | rules (the pre-D-78 path; removed by WP-C1)
  attempt_timeout_s: 900     # was 420 (§13.1)
  workday_entry: auto        # auto = resume import when offered, else Apply Manually (D-78) | manual
  llm_fill:
    num_ctx: 32768
    page_timeout_s: 120
    max_fields_per_call: 20
    long_list: 15
    keep_alive: "15m"
    second_opinion: true
    cache: true
    max_followups: 15
    debug_dump: false        # true: data/apply/<id>/prompts/NN.json (local, gitignored; S values are never in prompts)
```

---

## 14. Store (DDL; additive, `SCHEMA_VERSION` + 1)

```sql
-- apply_answers: columns added in _migrate (PRAGMA table_info + ALTER TABLE ... ADD COLUMN)
--   evidence TEXT, shown_json TEXT, shown_origin TEXT, entry TEXT
CREATE TABLE IF NOT EXISTS fill_cache (
    job_id TEXT NOT NULL,
    field_sig TEXT NOT NULL,
    facts_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    decision_json TEXT NOT NULL,           -- the guarded ModelDecision + Answer fields (local only)
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, field_sig, facts_hash, prompt_version, model)
);
```

Methods: `fill_cache_get(job_id, sigs, facts_hash, prompt_version, model) -> dict[sig, dict]`, `fill_cache_put(job_id, rows, now)`, `fill_cache_purge(before) -> int`. `add_answers` writes the four new columns.

---

## 15. Deviations, open items

- **NF-07:** a Workday attempt may take ~5–6 min with the model (§13.1). The owner's goal (all forms filled) outranks the typical-time target; recorded here, planner folds into the PRD.
- **AD §5.3 rule kept, spike deviation closed:** the prototype sent `contact.*` and `nationality` values to the model; the design does not (§5.1). "Are you a Singapore Citizen?" is answered by the `yes_if` lock (L5), not from nationality.
- **O-1 (owner, optional):** D-78 says "the LLM should be the one filling". This design keeps deterministic locks for declarations, work rights, sensitive values, consents and the owner's own answers (the model still sees them as facts and context). If the owner wants even these decided by the model, that is a change to ADR-0003 (fail-closed) and needs the owner.
- **O-2 (additive contract, next version):** `ResolveContext.resume_entries` (the master resume's entries as `(id, kind, text)`) for E2 and G6. Until it lands, entry blocks are cut from `resume_text` by locating each profile entry's employer/institution line (heuristic, WP-F3).
- **Superseded in `apply_design.md`:** §6 (schema plan as fill source), §7.2 tagging, §7.6, §9.1.1 KEEP table (→ G8), §9.4.2 step 3, §9.4.5–§9.4.10, §15 walkthrough (→ §9.4 here). The planner/architect stage-E pass adds pointers there.

---

## 16. Test strategy (tester)

**Fixtures from the S-5b recordings, sanitised** (`tests/fixtures/apply/llm_fill/<tenant>/`, tenants `wd_a`, `wd_b`): for each step, `page.html` (scripts removed, every text value replaced by the synthetic profile's `tests/fixtures/apply/applicant.sample.yaml` values; employer names → "Example Employer"; requisition ids removed), `fields.json` (the reader's expected output on that page), and `reply.json` (a **fake model** reply: a JSON object per call, keyed by the prompt's chunk id). A fake backend returns the replies in order and records each prompt (so tests can assert what the model saw).

**Reply sets per guard** (each a small fixture; assert the resulting Answer status/source and the stop list):

| Oracle | Fixture reply | Expect |
|---|---|---|
| G2 private ref | gender field, reply `profile`/`profile:identity.gender`/value "" | program fills from the synthetic profile; the prompt contains no S value (assert on the recorded prompt for every S value of the sample profile) |
| G2 empty fact | required "Additional Address", reply ref `profile:contact.address_line2`, empty in the profile | unknown, captured with `profile_gap`, `target_path = contact.address_line2` (S-5b tenant B) |
| G1/L2 long hierarchical list | how-heard with 40 `Category > Leaf` options, reply words "Company careers site" | exact leaf match, else `pick_option` reply → the right path (S-5b failure 1) |
| G3 | free text with a number not in the corpus | UNGROUNDED |
| G4 | language level "Fluent" for a language not in profile `languages` | unknown → E6 deletes the optional entry (S-5b failure 4) |
| G5 | required yes/no from resume; second reply disagrees | unknown (`no_rule`) |
| G6 | job location answered from the resume header | UNGROUNDED (S-5b failure 3) |
| G7 | "Gender" answered `resume` | unknown |
| G8 | resume-import value in an optional text field with no support | cleared; MyGreenhouse value on a non-sensitive field → kept PREFILLED |
| E3 | an imported entry matching no source entry | deleted |
| E4 | an imported description with an extra section appended | recheck replaces it with the entry's text (S-5b failure 5) |
| Title rule | a title containing the employer name; reply keeps it | — prompt rule only; oracle asserts the system prompt holds rule 5 (S-5b failure 2) |
| Strict listbox | listbox reads back filled, field shows an error | corrective pass re-fills once; still error → fill_failed (S-5b failure 6) |
| L3 / L7 | negated declaration on a Yes/No choice | unknown, `attestation_unclear` |
| F1, F3, F4 | §12 | as §12 |
| Flow | full dry run over the `wd_a` pages served by `http.server`, fake model | `ready_to_submit`; audit rows for every field; one `model_unavailable` run with a failing backend; nothing typed after a stop |
| Privacy | every recorded prompt | no S value, no email; `debug_dump` off writes nothing |

Reader and widget oracles run on the HTML fixtures (Playwright, headless Edge or Chromium, skip-clean when unavailable): every field's label, kind, required flag, options (incl. category expansion on a hand-built prompt stub), shown value, date parts, honeypot dropped.

---

## 17. Requirement map

| Req / decision | Where |
|---|---|
| D-78 (model fills every form; import always; adapters navigation only) | §1, §3–§10, ADR-0006 |
| F-31 | §9 (navigators, extension walkthrough) |
| F-32 | §4 (locks), §5–§7 (facts, model, guards) |
| F-33 | §4 L3, L7 |
| F-34 | §3.2 widgets, §8, §10 E1 (tailored resume) |
| F-12, F-13 (D-74) | §4 L6, §11 capture, §12.1, §12.2 |
| F-37, F-38, NF-06 (ADR-0004) | §8 (state machine and submit unchanged), §11 |
| F-39 | §7 answer mapping, §14 columns |
| D-70 (tailored resume replaces the autofilled one; MyGreenhouse) | §9.2, §10 E1 |
| D-75 | §4 L4, §5.1 `standing:work_rights` |
| D-76, review F4 | §12.3 |
| D-77 | unchanged: real Workday submissions only when every required answer is backed (G10) |
| D-79 | §5.1 (facts after normalisation) |
| NF-02, NF-09 | §5.1 private facts, §13.4 `debug_dump`, logging as AD §17 (no values, no prompts) |
| NF-03 | §2.2 (Ollama only, through `backends.py`) |
| NF-04 | §2.2 |
| NF-07 | §13.1 (deviation, §15) |

---

## 18. Prior art (≤ 8 searches, 2026-11-03)

| Project | Licence | What we borrow | What we don't |
|---|---|---|---|
| browser-use (github.com/browser-use/browser-use) | MIT | the page as a numbered list of interactive elements the model refers to by id (our `data-llmfill` marks; the model never writes selectors) | the agent loop where the model also chooses clicks and navigation |
| Stagehand (Browserbase) | MIT | schema-constrained extraction; caching action results by their inputs (our §13.3 cache keyed by field signature + facts hash) | natural-language `act()` for navigation |
| Skyvern | AGPL-3.0 (core); its cloud adds CAPTCHA solving | the "validate after each step" loop (our read-back + corrective pass) — idea only; no code (copyleft, and CAPTCHA solving is against our rules) | everything else |
| AIHawk (Jobs_Applier_AI_Agent) | AGPL-3.0; its auto-apply part was removed from the open-source repo | a plain-text resume + profile YAML as the model's facts (we already have `applicant.yaml`) | LLM-generated answers without grounding |
| Small job-apply agents (e.g. torontodeveloper/job-application-agent, a local-LLM Workday extension, ApplyPilot) | mixed/unverified | confirms the shape: read fields → model maps each to an answer → pause before submit; persistent browser profile for Workday sign-in | code (licences not checked; nothing copied) |

Nothing is copied; ideas only. Sources are listed in ADR-0006.
