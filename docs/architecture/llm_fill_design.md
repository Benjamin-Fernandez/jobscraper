# LLM-driven form filling (D-78; KA-1, KA-2)

**Stage B delta** for D-78 ("the LLM should be the one filling the information up"), queue Q-35 (+ Q-40: review Q-30 F1, F3, F4). Author: architect, 2026-11-03. **Status:** amended after stage E (review `docs/reviews/Q-35-design.md` H1–H7, M1–M14; tester TR-1–TR-13; decisions D-81, D-82, D-83). Change log: `comms/outbox/architect.md` (2026-11-03, "Q-35 amendment").
**Decision record:** `adr/0006-llm-driven-form-filling.md`. **Contracts:** `src/jobscraper/apply/contracts.py` v5 (additive; amended additively after stage E). **Build plan:** `llm_fill_build_plan.md`.
**Inputs:** D-70, D-74–D-79, D-81–D-83 (`instructions/02_status.md` §4); `apply_design.md` (cited **AD §n**); `questions_design.md` (**QD §n**); ADR-0003, ADR-0004, ADR-0005; spikes `spikes/S-5_workday.md`, `spikes/S-5b_llm_workday.md` (prototype `spikes/llm_fill/*.py`); `docs/reviews/Q-30.md`.

Reading guide: §1 is the whole design on one page. Engineers: §2 (where code goes), then the section your work package cites. Every "MUST" is a build rule. Rule ids: **L1–L7** locks (§4), **LL1–LL4** list handling (§3.1, §6.4), **G1–G12** guards (§7), **E1–E7** entries (§10).

---

## 1. Summary

```
apply_flow (orchestrator; state machine, caps, accounts, mail, submit: UNCHANGED)
   │  per wizard step / page, in state FILLING:
   ▼
apply/pagefill.fill_page(page, nav, ctx, rctx, services)       ── generic, the same for every ATS
   1 READ     page.py      every visible control → PageField (label, kind, required, options,
                           shown value + who put it there, preceding question, entry group)
   2 LOCK     locks.py     deterministic answers the model never overrides (D-82): files, account
                           email, work rights, sensitive tier-2 keys, consents, the owner's own
                           answers (extra, F1-guarded), declarations
   3 ASK      llm_fill.py  one call per chunk (an entry = one chunk): for each open field the model
                           returns {source, ref, value, evidence}; the whole prompt is redacted
   4 GUARD    guards.py    fact refs must be relevant and in scope; values tied to their evidence and
                           entry; second opinion on model-chosen Yes/No and required choices;
                           untrusted site values cleared or flagged
   5 STOP?    any required field unknown → nothing on the page is changed; capture → stop
   6 APPLY    entries deleted/added, widgets fill + strict read-back, revealed fields get another
                           round, one corrective pass; required scan before Next and before Submit
   ▼
nav.next_step()  (apply/ats/<name>.py: navigation only)
```

- **The model chooses the source, the program checks and writes.** For a fact (profile path, the owner's `extra` answer, a standing fact) the program produces the value with the deterministic mappers (`resolve.fit_*`), but only when the fact is relevant to the question and in the field's entry (G2). The model's own text is used only for resume/job values whose words all come from the quoted evidence (G3). Sensitive values (AD §5.3) are never in a prompt (§6.5).
- **Site modules navigate, they don't fill.** `SiteNavigator` opens, takes the resume import, handles the account wall, names the step, clicks Next and Submit, reads the confirmation.
- **Import from resume is always taken** (D-78), and every imported value is checked; an attachment JobScraper didn't upload in this attempt is always replaced by ours (D-70, L1).
- **Fail closed, unchanged.** A required field nothing can back up stops the attempt before anything is sent (ADR-0003) and becomes a question in the Profile tab (F-13). The state machine, submit-once, `submitted_unconfirmed` (ADR-0004), caps, CAPTCHA stop and NF-06 are untouched. Locks stay deterministic (D-82).

---

## 2. Components and boundaries

### 2.1 Files

```
src/jobscraper/apply/
  contracts.py   v5 (architect)
  page.py        NEW  generic page reader: PageField list, options (+ LL1 category expansion),
                      per-field errors, read-back, generic entry_sections(), scan_required()      (§3, §8)
  widgets.py     NEW  widget families: detect, options, fill, read, reset; click fallbacks; the one
                      allowed Enter (§3.2). Supersedes ats/workday_widgets.py (WP-V6)
  facts.py       NEW  fact catalogue, fact_value, relevance (G2), entry matching (E2), s_values,
                      today_sg, cache hashes                                                      (§5)
  locks.py       NEW  deterministic pre-pass (wraps resolve tiers 2-4)                             (§4)
  llm_fill.py    NEW  prompt constants, redact(), chunks, schema, ask, pick_option, recheck_entry,
                      second_opinion                                                              (§6)
  guards.py      NEW  pure: decisions + PageFields + facts → Answers, entry actions, stop list     (§7)
  pagefill.py    NEW  fill_page(): §8                                                             (§8)
  resolve.py     kept: fit_*, load_rules, tiers 2-4, grounded(); F1 and F4 fixes (§12)
  plan.py        + is_generic(), qualified_label() (F1, §12.1)
  questions.py   + capture_page() from PageFields (§11)
  ats/workday.py NEW  SiteNavigator (§9.1)        ats/greenhouse.py  + SiteNavigator methods (§9.2)
apply_flow.py    FILLING loop calls pagefill per step; identity/mail (WP-N4) unchanged in substance
tailor_flow.py   + resume_entries(cfg) (M5/O-2 owner: WP-N6b)
store.py         apply_answers columns + fill_cache table (§14)
backends.py      keep_alive keyword (sent only when given), warm() helper (§13)
```

### 2.2 Layering (NF-04, `tests/test_layering.py`)

- Only `backends.py` talks to the model: `llm_fill.py` receives a backend object and calls `backend.complete(...)` (as `resolve.py` tier 5 did). No HTTP in `apply/`.
- Only `store.py` has SQL: `fill_cache` reads/writes reach `pagefill` as `FillServices` methods (contracts v5).
- `apply/` imports `apply.contracts`, foundation, stdlib, Playwright. The master resume's entries reach `facts.py` through `ResolveContext.resume_entries` (filled by `apply_flow` from `tailor_flow.resume_entries`, D-68 pattern). No new layer.

---

## 3. The page model (`apply/page.py`)

### 3.1 What the reader returns

`read_page(page, *, scope: str, sections: list[EntrySection], origin: ValueOrigin, rng=None) -> list[PageField]` (TR-4: `rng` seeds the mark suffix in tests), ported from the spike's `READER_JS`:

| Item | Rule |
|---|---|
| Which controls | visible, enabled `input`, `textarea`, `select`, `button[aria-haspopup="listbox"]`, `[role="combobox"]`, `[role="spinbutton"]` groups, inside `scope` (or the page minus `header, nav, footer, [role=banner|navigation|contentinfo]`); returned **in document order** |
| Dropped | `type=hidden|submit|button|image|reset`, `password`, honeypots (`data-automation-id="beecatcher"`, name/label containing "for robots" / "honeypot"), read-only inputs |
| Label | `aria-labelledby` texts, else `label[for]`, else the container's `legend`/`label`, else `aria-label`, else placeholder; trailing `*` removed |
| Required | `aria-required="true"`, `required`, a trailing `*`, or an `abbr` marker in the container |
| Description | the container's help text (`aria-describedby` non-error targets), ≤ 300 chars |
| Kind → `FieldType` | text-like inputs → TEXT / EMAIL / PHONE / URL / NUMBER by `type`; `textarea` → TEXTAREA; native `select` and listbox buttons → DROPDOWN; radios → RADIO; one checkbox → CHECKBOX; a checkbox group → MULTI_CHOICE; a combobox/prompt with several pills → MULTI_CHOICE, else TYPEAHEAD (`options_complete=False` when search-driven); segmented date → DATE; `input[type=file]` → FILE |
| Options | native `option` texts; listbox/prompt: open, read `[role="listbox"] [role="option"]` and `[data-automation-id="promptOption"]` (not chosen pills), Escape; ≤ 400. **LL1 category expansion:** options with a sub-list marker are opened one level and listed as `"Category > Leaf"` |
| Shown value | text: `value`; select/listbox: selected text ("" for a "Select One"-style placeholder); radio: checked label; checkbox: `"true"`/`"false"`; prompt: pill texts; date: section **values** joined (never `aria-valuetext`); file: the file name shown in the container |
| Context | the label of the previous PageField in the same group/section (generic labels, §12.1) |
| Group | inside an `EntryGroup`: `group = "<section>#<index>"`, `group_title` = heading |
| Error | `[data-automation-id="inputAlert"]`, `errorMessage`, `[role="alert"]` linked by `aria-describedby` or inside the container |
| Key | the mark `data-llmfill="f<n>_<rand>"` (stable for one read); the audit key is `<step>:<automation id or html id or slug(label)>[#n]` |

### 3.2 Widget families (`apply/widgets.py`)

A family = `detect(el)`, `options(page, loc)`, `fill(page, loc, value) -> bool`, `read(page, loc) -> Value`, `reset(page, loc) -> bool` (back to empty/placeholder; False when the widget can't be emptied, e.g. a radio group). Families in detection order: `segmented_date`, `file`, `native_select`, `aria_listbox`, `prompt` (Workday `selectinput` / `promptOption` / `selectedItem` + `DELETE_charm`), `react_select` (Greenhouse), `combobox`, `radio`, `checkbox`, `text`. Reuse `browser.py` primitives.

MUST rules:
- **Strict read-back for every family (M14):** `fill` returns True only when `read` equals the intended value (normalised AD §7.1; dates by numbers; multi as sets; file by name) **and** the field shows no error after blur. A typeahead/combobox that selected another suggestion is `fill_failed`. A search miss on an optional field clears the typed text.
- **Dates by section role, not position;** `2026-03` equals `3/2026`.
- **Clicks:** `widgets.click(page, loc)`: plain click; on timeout the preceding sibling `div[data-automation-id="click_filter"]`, then the following sibling, then the parent (S-5 item 2). Navigators use it too.
- **Enter (M8):** `browser.py`'s "never press Enter" rule stands with one exception: Enter may be sent only to a `prompt`-family search input, and only when that input is not inside a `<form>` that has a submit control (`el.form` with a `[type=submit]` or a button named Submit). Every other family never sends Enter.
- **Multi-select:** remove wrong pills first, add each item, read back as a set. **Upload:** success = the file name appears in the container within 30 s.

### 3.3 Provenance of shown values (`ValueOrigin`)

- Before the import, `choose_entry` stores what the form already showed in `ctx.pre_import` (key = audit key, value = shown text) (M3; Greenhouse snapshots before clicking MyGreenhouse, AD §9.1.1 step 3; Workday's import runs on an earlier step, so nothing to snapshot).
- On the **first read of a page**, a non-empty shown value gets `site_default` when it equals `ctx.pre_import[key]`, else the attempt's import origin (`ctx.prefill`: `resume_import`, `mygreenhouse`), else `site_default`. A value JobScraper typed gets `ours`; re-reads keep the first-read origin for untouched fields.
- **What the model sees of a shown value:** `current` only when the origin is a site origin **and** none of the withholding rules of §6.5 hits; otherwise `current_set: true`. Values JobScraper typed are never shown back (S-5b: they bias the model).

---

## 4. Locks: the deterministic pre-pass (`apply/locks.py`; D-82)

`lock_page(fields, rctx, rules, *, today, uploaded) -> dict[str, Answer]` runs before the model. A field with a FILLED lock is final: it is not in the output schema; it appears in the prompt as context (`locked: true`, no value when private). **Order (M1, F-32):** L1, L2, L4/L5, L6, L3/L7. An UNKNOWN from L4/L5 or L3/L7 consults L6 for the same qualified label; if L6 has nothing, the field stays UNKNOWN (captured) and **never** goes to the model.

| # | Lock | Rule | Answer |
|---|---|---|---|
| L1 | Resume FILE (H6) | A FILE input is the resume slot when its label/section/automation id matches `resume|résumé|cv|curriculum`, or — **only when the step has exactly one FILE input** — the page text matches `resume|cv|drop (off )?your|autofill`. A FILE labelled cover letter, transcript, portfolio or anything else is never the resume slot. Value `ctx.resume_path`. Keep the shown attachment **only if this attempt uploaded it** (`ctx.uploaded` holds name → SHA-256 of our uploads, kept across steps); any other attachment, even with our file name, is removed and ours uploaded (D-70; lane B review F1) | FIELD_MAP, `field_map:resume` |
| L1b | Other FILEs | label `transcript` → `documents.transcript` when set; required cover letter → the model composes a letter (one call, G3 compose rule, G12), saved to `data/apply/<id>/cover_letter.txt` and uploaded; any other required FILE → unknown (not captured, QD §4.2); optional → blank | FIELD_MAP / LLM |
| L2 | Email | EMAIL kind, or a label phrase-matching `email` (≤ 4 tokens) → `ctx.account_email` or `contact.email` | FIELD_MAP, `field_map:email` |
| L4 | Work rights (D-75) | tier-2 `country_bool` (QD §8.2); conflict → unknown (`conflict`) | PROFILE_RULE |
| L5 | Sensitive tier-2 rows and consents | tier-2 rows with `sensitive: true` (residency incl. `yes_if`, NS, race, gender, DOB, EEO) and `consents.privacy_consent`, `consents.certify_true` (AD §7.3); a no-fit → L6 → else unknown (`no_option_fits` / `profile_gap`) | PROFILE_RULE |
| L6 | Owner answers (`extra`, QD §6.2) | with the F1 guard (§12.1); skipped for employer-specific declarations (QD §6.2 step 1) | MEMORY, `memory:extra.<key>` |
| L3 | Declarations (tier 4, AD §7.5) | unchanged; `AMBIGUOUS` → unknown (`attestation_unclear`) | DECLARATION |
| L7 | Negated declaration on a Yes/No choice | label contains `not`, `never`, `no`, `none`, `neither`, `free of`, `without` → unknown (`attestation_unclear`) | — |

Non-sensitive tier-2 rows don't answer on their own; their `kind`/`value_map`/`yes_if`/synonyms are what G2 uses (relevance and mapping).

### 4.1 Resolver tiers 1–5 under D-78

| Tier | Under D-78 |
|---|---|
| 1 Field map | **Retired as site tagging.** Value logic survives as facts (`standing:full_name`, `profile:contact.phone_number` digits, `profile:contact.country` ISO → name, `standing:account_email`, `standing:today`, `standing:how_heard`) and as L1/L2 |
| 2 Profile rules | **Locks** for sensitive keys, `country_bool`, consents (L4, L5); other rows = relevance + mapping metadata for G2 |
| 3 Memory | **Lock** L6 (F1 guard); non-sensitive, non-generic `extra` entries are also citable facts (G2, G12) |
| 4 Declarations | **Lock** L3 + L7 |
| 5 Per-field LLM | **Retired**; its grounding check becomes G3 and its two-run agreement G5 (ADR-0003 §3 kept: every model-chosen Yes/No and required choice needs two agreeing runs) |

`resolve.resolve_all` stays callable until WP-C1 (`apply.fill: rules`).

---

## 5. Facts (`apply/facts.py`)

### 5.1 Catalogue

`fact_catalogue(profile, rctx, *, today) -> list[Fact]`. Refs are exact strings; an entry chunk's schema allows only that entry's refs (G2 scope).

| Namespace | Entries | Visible value? |
|---|---|---|
| `profile:<path>` | every leaf of `data/applicant.yaml` after D-79 normalisation, list entries indexed; template rows (employer starting "Example ") dropped. `Fact.entry` = `experience[i]` / `education[i]` / `languages[i]` / `links.<k>` for entry facts | only `applicant.llm_extract` allow-list paths plus the legal/preferred names; every other path (all S paths, `singapore_status.nationality`, …) is **private** (`set`/`empty` only) |
| `extra:<key>` | each `extra` entry usable here: not generic-label unless scoped to this employer (§12.1); not naming another employer (G12) | non-sensitive: title + value/picks; sensitive: private |
| `standing:<id>` | `today` (`today_sg(now_utc)`, Asia/Singapore, TR-5), `full_name`, `experience_years`, `experience_months`, `graduation_year`, `work_rights` (D-75 text), `worked_here`, `current_employee_here`, `previously_applied`, `how_heard`, `account_email` (private) | yes, except `account_email` |

Each fact also carries its **title words** (from the FORM label of the path, the `extra` title, or the standing id's description) used by G2 relevance. Shown one per line, fixed order (profile, extra, standing); empty non-private facts omitted.

### 5.2 Resume and job

- **RESUME** = the tailor master's text (`tailor_flow.master_text`, which excludes the contact header); else `resume_ingest.extract_text` of the file. Either way the prompt is redacted (§6.5). First 8000 chars.
- **Entry blocks (M5, O-2 closed):** `ResolveContext.resume_entries` (contracts v5) = `(id, kind, text)` per master entry (`experience[0]`, `education[1]`, …), filled by `apply_flow` from `tailor_flow.resume_entries(cfg)` (owner: WP-N6b). When it is empty, blocks come from the profile entries' own facts only. **No block → G3/G6 reject every `resume`/`keep` answer in that group** (fail closed). A page with imported entries, an empty `resume_entries` **and** no profile entries for that section → `ApplyFailure(PROFILE_INCOMPLETE, "<section>")` (the owner fills experience/education in Profile) before anything is changed.
- **JOB** = company, title, location, the step title, first 3000 chars of the JD.

### 5.3 `fact_value(ref, field, rctx, rules) -> Optional[Fit]` and `relevant(ref, field, rules) -> bool`

`fact_value`: by the fact's kind with `fit_bool`, `fit_enum` (+ the tier-2 row's `value_map`/`yes_if`), `fit_text`, `fit_number`, `fit_salary`, `fit_country`, `fit_date`, decline mapping, `extra` fit by kind (QD §6.2 step 4). None = no fit. For a private fact this is the only way its value reaches the page.

`relevant` (used by G2): True when a tier-2 row for that path (or the `extra` entry's `labels`) matches the field's label by AD §7.3.1 scoring (synonyms, `exclude`), **or** the field's label shares a content token with the fact's title words or a `FACT_TITLE_SYNONYMS` entry (module constant: phone/mobile/contact number; postal/zip/postcode; address/street/unit; birth/dob; city/town; school/university/institution; degree/qualification; …). Stop words as QD §5.2; whole words only.

---

## 6. The model call (`apply/llm_fill.py`)

### 6.1 Chunks

`chunks(fields, groups, max_fields) -> list[Chunk]`: each entry group is one chunk (its fields + its block); the remaining open fields in chunks of ≤ `llm_fill.max_fields_per_call` (20). Locked fields of the chunk are context lines. FILE fields never reach the model (except L1b's cover-letter call).

### 6.2 Prompt (constants exported: `SYSTEM`, `SECOND_SYSTEM`, `PICK_SYSTEM`, `RECHECK_SYSTEM`; `FILL_PROMPT_VERSION = "fill:v2"`)

`SYSTEM`:

```
You fill in part of a job application form for ONE applicant. For every field id, say where the
answer comes from and give it. Sources:
- profile / extra / standing: a FACT. Give its exact ref. The program writes the value from the fact,
  so for a private fact leave value "" (never guess a private value).
- resume: the value comes from RESUME; copy into evidence the exact words it comes from (at most
  25 words). Every word of the value must appear in the evidence.
- job: the same, from JOB.
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

`SECOND_SYSTEM` = `SYSTEM` + "\nThis is a check of a single field." `PICK_SYSTEM` = "Pick the one option that means the same as the wanted answer for the question. Copy it exactly. If none means the same, answer \"\"." `RECHECK_SYSTEM` = "Copy, from RESUME ENTRY only, the lines that belong in this field for this entry. Copy them exactly; never add words. If none belong, answer unknown."

User prompt, fixed order (TR-4, TR-11): `FACTS:` → `RESUME:` (entry chunks: `RESUME ENTRY <id>:` only) → `JOB:` → `PAGE: <step title>` → `FIELDS (JSON):` + one valid JSON array on its own → the fixed final line "Answer with one JSON object keyed by field id." FACTS is byte-identical across every call of an attempt; FACTS + RESUME across all non-entry chunks.

Field view: `id`, `question`, `kind`, `required`, `section`/`group_title`, `context` (generic labels), `help`, `options` (≤ `long_list`) or `options_note` (count + 5 examples), `current` or `current_set` (§3.3, §6.5), `parts`, `site_error` (corrective pass), `locked: true`.

### 6.3 Output schema (`format`)

Per open field: `source` enum `["profile","extra","standing","resume","job","keep","unknown"]`; `ref` enum = the chunk's allowed refs + `""` (entry chunk: that entry's refs only, plus `standing:today`; other chunks: refs with no entry); `value` (CHECKBOX `["true","false",""]`; short lists → enum; short multi → array of enum; long/search lists and text → string with `maxLength`); `evidence` string ≤ 240. A missing field → unknown, note `no reply`. Options: `temperature=0, seed=7`, `max_tokens = 120 × fields + 200` (≤ 8000), `timeout = llm_fill.page_timeout_s`, think off; `keep_alive` only when configured (TR-6).

### 6.4 Follow-up calls (each sets `ModelDecision.via`)

| Call (`via`) | When | Rule |
|---|---|---|
| `pick` (LL2) | a long list (> `long_list`) or a search result list (LL3), and the words don't equal an option or the leaf of a `Category > Leaf` path | enum of the options + `""`; `""` → unknown |
| `recheck` (E4) | every TEXTAREA in an entry group whose shown value has origin `resume_import`; every entry TEXT that fails G11 | a copy task (`RECHECK_SYSTEM`): every returned line must occur (normalised) in the entry's block (G3 copy rule), else rejected. Unknown or rejected → the imported value is **unsupported**: optional → cleared, required → unknown. Never kept (H1c) |
| `second` (G5) | every model-chosen Yes/No answer (required or optional) and every required choice or number whose value is the model's (source `resume`/`job`, or a fact with no fit) | the same field alone, `SECOND_SYSTEM`, `temperature=0.7, seed=7`, without the first answer; must give the same option/number |
| `corrective` | fields with a site error after fill or after Next | re-ask only those, with `site_error`; our earlier value not shown |

LL3 searchable lists: the filler types the model's words (≤ 40 chars), picks an exact match, else `pick`; nothing → required unknown, optional cleared. LL4 multi-select: each item separately, read back as a set.

### 6.5 Privacy: what can never be in a prompt (H4, TR-1)

- `facts.s_values(profile, account_email) -> list[str]`: the free-text values of S paths: `contact.*` except city/country (email, phone as digits with and without the country code and with common spacing, address lines, postal code), `contact.backup_email`, `identity.date_of_birth` (ISO, DD/MM/YYYY, D Month YYYY, Month D, YYYY), `singapore_status.nric_last4`, `ord_date`, `race_other`, free-text `religion`, plus the account email. **Enum S values** (gender, race, residency, NS status, marital status) are not redacted: they are ordinary words ("Chinese" is also a language) and the model never receives them as fact values; L5/G7 keep the model off those questions.
- `llm_fill.redact(text, s_values) -> str`: replaces each value (case-insensitive; the phone also as digit runs) by `[private]`, longest first. Applied to the **whole user prompt** of every call, after it is built (covers RESUME from the extracted file, current values, JOB).
- `current` is withheld (`current_set: true` instead) when: the kind is EMAIL or PHONE; the label matches G7's pattern or a contact word (`address`, `street`, `unit`, `postal`, `zip`, `postcode`, `phone`, `mobile`, `email`, `nric`, `passport`, `id number`); or the shown value contains an `s_values` item.
- `debug_dump` writes only the redacted prompt.

---

## 7. Guards (`apply/guards.py`; pure)

`decide(fields, locks, decisions, facts, rctx, *, second, today) -> Decision` where `Decision` = answers, the stop list, and entry actions (deletes, adds). Applied in order per field; the first rejection ends the field **unknown** (status `UNKNOWN`, or `UNGROUNDED` for G3/G6/G11) with a note naming the guard (no values). Module constants (TR-10): `STOP_WORDS`, `LEVEL_SYNONYMS`, `SENSITIVE_LABEL`, `CONTACT_WORDS`, `FACT_TITLE_SYNONYMS`, all matched on whole words.

| # | Guard | Rule |
|---|---|---|
| G1 | Shape | decision parsed; a choice value is an offered option (or an LL2/LL3 match); unknown ids ignored |
| G2 | Fact refs (H2, TR-3) | (a) **scope**: the ref is in the chunk's allowed set (entry chunk: refs whose `Fact.entry` is the group's matched entry, plus `standing:today`; an unmatched group allows none; other chunks: refs with no entry). (b) **relevance**: `facts.relevant(ref, field)` (§5.3), else unknown. (c) **value**: `fact_value(ref, field)`; empty fact → unknown (`profile_gap`, `target_path`); no fit → see (e). (d) **bool/enum facts on a choice field**: the program's option is used only when a tier-2 row for that path (or the `extra` labels) matches the label, **or** the model's own option equals the program's; a disagreement → unknown (captured), never "program wins". For other kinds, a non-private fact's model value must equal the program value (normalised; dates by numbers) or be empty, else unknown. (e) **no fit** (e.g. a hierarchical how-heard list): the model's option is used only if G4 passes against the fact's text and, for Yes/No or required choices, G5 agrees |
| G3 | Grounding (H1) | `resume`/`job`/`keep` (except G8's trusted keep): evidence normalised ≥ 3 chars and a substring of the corpus. **Copy rule** (TEXT anywhere; TEXTAREA in an entry group; every `keep` of text): every content token of the normalised value occurs in the evidence; numbers and dates as tokens; a URL verbatim. **Compose rule** (TEXTAREA outside entry groups, e.g. "Why do you want to join?", cover letter): `resolve.grounded` rules 1–5 against the corpus. In an entry group the corpus is that entry's block + its entry facts only (no block → reject) |
| G4 | Choice vs source | an option not produced by `fact_value` shares a content token (minus `STOP_WORDS`, with `LEVEL_SYNONYMS`) with the evidence or the fact's text. Yes/No options are exempt here (G5 covers them) |
| G5 | Second opinion (ADR-0003 §3) | the §6.4 `second` call agrees, else unknown (`no_rule`). Applies to every model-chosen Yes/No (required or optional) and every required choice/number whose value is the model's. `llm_fill.second_opinion: false` → those answers end unknown (fail closed; TR-10) |
| G6 | Entry scope | a field in an entry group answered from `resume`/`keep`: the evidence lies inside that entry's block (no block, or an unmatched group → reject); fact refs are scoped by G2(a) |
| G7 | Sensitive (M2) | `SENSITIVE_LABEL` = date of birth, birth date, dob, gender, sex, race, ethnic(ity), religion, nric, national id, identity card/number, passport, disability, veteran, marital, pronoun, **citizen(ship), permanent resident, pr, residen(t\|cy) status, nationality, national service, ns, ord** (whole words). Such a field may be answered only by a lock or a private `profile` ref that passes G2; `resume`/`job`/`keep` → unknown; a `keep` only when the shown value equals the program's value of that private fact |
| G8 | Prefill trust (H3, H5c, D-83) | `keep` is trusted without G3 only when the origin is in `TRUSTED_ORIGINS` (MyGreenhouse), the field is not TEXTAREA and not a cover letter, not always-ours, not an employer-specific declaration, not sensitive, and passes G12. Every other `keep` needs G3 (+ G6 in an entry). A **required** `resume_import` value is kept only if G3 passed (D-83) |
| G9 | Untrusted leftovers (H3) | every field with a non-empty shown value from a site origin whose final answer is not FILLED or a G8-passed PREFILLED: optional TEXT/TEXTAREA → **clear**; optional choice → `reset` to the placeholder, and when the widget can't be reset → status PREFILLED, confidence 0.5, note "unverified site value" (in an entry group: E6 instead); an optional checkbox the site ticked → **untick** unless a fact or lock backs it; required → unknown. The audit value is the read-back after these actions |
| G10 | Required unknown | every required field ending unknown → `PageOutcome.unknown_required` (all, QD §4.1) |
| G11 | Entry titles (M12) | in an entry group, a TEXT value for a title/position/role field must not contain the matched entry's employer tokens unless that entry's title line in the block does; otherwise one `recheck`; still failing → unknown |
| G12 | Other employers (H5) | an `extra` value, a MyGreenhouse kept text, or a composed text that phrase-matches an employer in `rctx.other_employers` (watchlist names and the employers in captured questions' sightings, minus this employer and its aliases) and not this employer or its aliases → not listed as a fact / not kept / rejected → unknown (captured). A generic-label field may cite only `extra` entries scoped to this employer |

**Answer mapping (H2d):**

| Outcome | tier | source | status | confidence | rule_id / model / prompt_hash |
|---|---|---|---|---|---|
| lock | per §4 | per §4 | FILLED / UNKNOWN | 1.0 / 0.95 | as before |
| fact chosen by the model, value written by the program | **LLM** | `profile:<path>`, `standing:<id>`, `memory:extra.<key>` | FILLED | 0.9 | `fill:v2`, model, hash |
| resume / job value | LLM | `resume` / `job` | FILLED | 0.9 with G5, else 0.8 | `fill:v2`, model, hash |
| keep | NONE | the origin | PREFILLED | 0.95 trusted, 0.85 grounded | `fill:v2` |
| unverified leftover (G9) | NONE | the origin | PREFILLED | 0.5 | note "unverified site value" |
| cleared / reset / unticked (G9) | NONE | the origin | BLANK_OPTIONAL | 0 | note names the action |
| unknown | NONE | `""` | UNKNOWN / UNGROUNDED | 0 | the guard in `note` |

`Answer.evidence`, `shown`, `origin`, `entry` are set on every row.

---

## 8. One page (`apply/pagefill.fill_page`)

```
fill_page(page, nav, ctx, rctx, services: FillServices) -> PageOutcome
 1  step = nav.step_id(); sections = nav.entry_sections(); fields = page.read_page(...)  (§3; origin §3.3)
 2  facts = facts.fact_catalogue(..., today=services.today()); matches = facts.match_entries(...) (E2);
    the PROFILE_INCOMPLETE check (§5.2); nothing is changed yet
 3  locked = locks.lock_page(fields, rctx, services.rules, today=..., uploaded=ctx.uploaded)
 4  cached = services.cache_get(...) (§13.3); replayed decisions (via "cache") go through 6 like fresh ones
 5  for each chunk of open, uncached fields: services.deadline_left() > 0 else stop "timed out";
        decisions += llm_fill.ask(services.backend, chunk, ...); then pick / recheck / second (§6.4)
        (BackendError, timeout, a cut/malformed reply after one retry → transport_failed, return)
 6  decision = guards.decide(fields, locked, decisions, facts, rctx, matches=..., second=..., today=...)
    (G1-G12; entry actions E3, E5, E6)
 7  if decision.unknown_required: return PageOutcome(..., unknown_required)  — NOTHING on the page has
    been changed: no fill, clear, reset, delete or add (M9, TR-7)
 8  services.classify(page) (captcha/bot → raise, AD §8.4); services.deadline_left() > 0
 9  apply: entry deletes (E3, E6), then entry adds (E5) → re-read the added entries → steps 3-7 for
    them; fills (only values that differ from shown; FILE uploads record ctx.uploaded); G9
    clears/resets/unticks; strict read-back (§3.2)
10  revealed fields (H7): re-read the scope; fields not seen in step 1 → steps 3-9 for them
    (at most `max_reveal_rounds` = 2); a required field unknown in such a round → stop (unknown_required)
11  corrective pass: fill_failed or a site error → services.classify(page), `corrective` call, decide,
    fill once; still failing → fill_failed
12  required scan (H7): page.scan_required(page, scope) → keys of visible required controls that are
    empty or show an error → handled as 10 once; still → stop: unknown → unknown_required,
    else fill_failed
13  services.cache_put(...); return PageOutcome
```

A stop after step 9 (an added entry or a revealed field) leaves the page partly changed; nothing is submitted and the flow stops the attempt.

**Pinned signatures (M6; lanes M and R build against these):**

| Function | Signature |
|---|---|
| `llm_fill.chunks` | `(fields: list[PageField], matches: dict[str, Optional[str]], max_fields: int) -> list[Chunk]` (`Chunk` = `NamedTuple(id: str, entry: Optional[str], fields: tuple[PageField, ...])`) |
| `llm_fill.ask` | `(backend, chunk: Chunk, facts: list[Fact], rctx: ResolveContext, *, step_title: str, s_values: list[str], cfg) -> list[ModelDecision]` (raises `BackendError` on transport failure) |
| `llm_fill.pick_option` | `(backend, field: PageField, wanted: str, options: list[str], *, s_values) -> Optional[str]` |
| `llm_fill.recheck_entry` | `(backend, field: PageField, block: str, *, s_values) -> ModelDecision` |
| `llm_fill.second_opinion` | `(backend, field: PageField, chunk: Chunk, facts, rctx, *, step_title, s_values) -> ModelDecision` |
| `facts.match_entries` | `(sections: list[EntrySection], fields: list[PageField], rctx: ResolveContext) -> dict[str, Optional[str]]` (group id → source entry id) |
| `guards.decide` | `(fields, locks, decisions, facts, rctx, *, matches, second: Callable[[PageField], ModelDecision], today: str) -> Decision` |
| `locks.lock_page` | `(fields: list[PageField], rctx: ResolveContext, rules, *, today: str, uploaded: dict[str, str]) -> dict[str, Answer]` |
| `facts.fact_catalogue` | `(profile: dict, rctx: ResolveContext, *, today: str) -> list[Fact]` |
| `facts.s_values` / `llm_fill.redact` | `(profile: dict, account_email: str) -> list[str]` / `(text: str, s_values: list[str]) -> str` |
| `facts.today_sg` | `(now_utc: float) -> str` |
| `page.read_page` / `page.scan_required` | `(page, *, scope: str, sections: list[EntrySection], origin: ValueOrigin, rng=None) -> list[PageField]` / `(page, scope: str) -> tuple[str, ...]` |
| `pagefill.fill_page` | `(page, nav: SiteNavigator, ctx: AttemptContext, rctx: ResolveContext, services: FillServices) -> PageOutcome` |
| services | `FillServices` Protocol in contracts v5: `backend`, `model`, `rules`, `cfg`, `today()`, `now()`, `deadline_left()`, `classify(page)`, `cache_get(...)`, `cache_put(...)`, `log(line)` |

**The flow per step (`apply_flow`, FILLING):** `apply_flow.run(..., now=None)` builds one `FillServices` per attempt with that clock (`None` = `time.time`; TR-5); `outcome = fill_page(...)`; audit rows for all fields; `outcome.transport_failed` → `failed(model_unavailable)`; `unknown_required` → `_capture_questions` (from `capture_page`, §11) → `ApplyFailure(UNANSWERABLE_REQUIRED, first label)`; `fill_failed` on a required field → `validation_error`; else `nav.next_step()`; `StepResult.errors` → `fill_page` again on the same step with those fields flagged (once), then `validation_error`. Loop guard: ≤ `max_wizard_steps` Next clicks; the same step id **and** the same set of field signatures twice without errors → `page_unrecognised`.

**Before Submit (H7):** on the review page, `page.scan_required` over the whole form (Greenhouse: the one page; Workday: the review page shows no inputs, so the last step's scan before Next stands) → any hit → `validation_error`, nothing sent. Then the review text check: the resume file name must appear when a resume was uploaded (else `validation_error` "review: resume not shown"); text values of required fields not shown → note only. Then, unchanged: dry run → `ready_to_submit`; auto → `submit_clicked_at` committed → `nav.submit()` once → `submitted` / `submitted_unconfirmed` (ADR-0004).

---

## 9. Navigators (`SiteNavigator`): navigation only

### 9.1 Workday (`apply/ats/workday.py`)

| Method | Spec |
|---|---|
| `match_url`, `tenant_from_company` | AD §9.4.1 |
| `precheck` | nothing |
| `open` | `goto(job_url)`, settle, decline a cookie banner (`legalNoticeDeclineButton`, else Decline / Reject / Necessary only), classify, click `adventureButton` |
| `choose_entry` | dialog `wd-popup-frame`: `autofillWithResume` when offered → `resume_import`; else `applyManually` → `site_default`; no dialog → `site_default`. Never `useMyLastApplication`. `apply.workday_entry: manual` forces Apply Manually. The resume is uploaded on the wizard's first step by L1 |
| `account_wall` | sign-in/create controls win over the progress bar (S-5) |
| `sign_in`, `sign_up`, `enter_code` | AD §9.4.3 with S-5 ids; `widgets.click`; one sign-in per identity per attempt; vault entry before the sign-up click |
| `step_id` (M7) | `progressBarActiveStep` text with the `(current )?step N of M` prefix removed, slugged; **when another progress item has the same title, `_<N>` is appended** (two "Application Questions" pages → `application_questions_4`, `application_questions_5`); `review` for the review page |
| `scope` | the step container, excluding header and bottom navigation |
| `entry_sections` | sections `workExperienceSection`, `educationSection`, `languageSection`, `websiteSection`, `certificationSection` (else headings); entries = panels / `[role=group]` with a numbered heading; delete = `panel-set-delete-button` or `/^delete/i`; add = `Add` / `/^add( another)?\b/i` |
| `next_step` | `bottom-navigation-next-button` / `pageFooterNextButton` / Save and Continue / Next; text Submit → `StepResult(is_review=True)` without clicking; errors from `inputAlert`, `errorMessage`, banners |
| `submit` | the same button with text `/^submit$/i`, once |
| `after_submit` | `/application submitted|thank you for (your )?appl/i`, URL `/jobTasks/completed/application` → confirmed; `/userHome` listing → `confirmed:home` |

Retired from AD §9.4: named-step tables (§9.4.8), OVERWRITE table (§9.4.6), Workday helper module, review parse (§9.4.10), "never Autofill with Resume" (§9.4.2 step 3).

### 9.2 Greenhouse (`apply/ats/greenhouse.py`)

`precheck`: the schema request (404/410 → `posting_closed`). `open`: AD §9.1. `choose_entry`: AD §9.1.1 steps 1–5 with the pre-click snapshot stored in `ctx.pre_import` (M3) → `mygreenhouse` or `""`. No account. `step_id` = `"form"`; `next_step` → `is_review=True` (the pre-Submit `scan_required` of §8 is the deterministic check before the click). `submit`/`after_submit`/security code: AD §9.1, §4.2. `entry_sections`: generic default.

### 9.3 Lever, Ashby (M21)

Navigators only (AD §9.2/§9.3 open, submit, confirmation). Ashby's "autofill from resume" is now used (D-78).

### 9.4 Extension walkthrough: a new ATS in 5 steps, no core edits

1. `apply/ats/<name>.py`: a `SiteNavigator` with `name`, `needs_account`, `password_rules`, `mail_domains`, `otp_pattern`, `match_url`, `tenant_from_company`.
2. `open`, `choose_entry` (click the site's resume import if any, return `resume_import`; snapshot `ctx.pre_import` first), the account methods if needed.
3. `step_id` (unique per page), `next_step` (never clicks Submit), `submit`, `after_submit`, `visible_errors`; `scope`/`entry_sections` only if the defaults miss.
4. One line in `apply/ats/__init__.py` `REGISTRY`.
5. Tester: recorded pages, fake replies, a dry run to `ready_to_submit`.

A widget the families don't know is a `widgets.py` change (generic), not a navigator change.

---

## 10. Imported entries

| # | Rule |
|---|---|
| E1 | **Import always** (`choose_entry`), with the tailored resume (else the original); L1 replaces any attachment this attempt didn't upload |
| E2 | **Match** (`facts.match_entries`; TR-10): a site entry matches source entry X when the shown employer/institution/language company-matches X's (AD §7.5) **and** the overlap coefficient `|A∩B| / min(|A|,|B|)` of the content tokens of title/degree is ≥ 0.5; with no employer shown, title overlap ≥ 0.8. The unique best match wins; ties → unmatched. Sources: profile entries when non-empty, else `rctx.resume_entries` |
| E3 | **Junk:** an unmatched site entry is deleted (applied in §8 step 9). No delete control and a required field in it → unknown (stop) |
| E4 | **Check every matched entry** in its own chunk with its block; imported TEXTAREAs get `recheck` (copy rule); G6 and G2(a) hold |
| E5 | **Missing:** a source entry with no site entry: experience and education are added (step 9, then a round for the new entry); languages and websites only from the profile |
| E6 | **Ungroundable optional entry:** an entry with a required sub-field unknown, or an unverified leftover (G9), is deleted when the section isn't required or other entries remain; otherwise the field stops the attempt and is captured |
| E7 | Entry actions are decided in step 6 and applied only in step 9 (nothing changes on a page that stops in step 7) |

---

## 11. Stops, capture, reason codes, degradation

- **Required unknown** (G10): `questions.capture_page(fields, answers, ctx, rules)` builds the questions (QD §4.2 rules): `label_norm` = `plan.qualified_label(...)` (§12.1), `reason` from the guard (G2 `profile_gap`/`no_option_fits`; L3/L7 `attestation_unclear`; L4 `conflict`; G3/G6/G11 `ungrounded`; else `no_rule`), `target_path` from G2. One capture point (the page stop).
- **Not captured:** transport failures. `PageOutcome.transport_failed` = True when any call raised `BackendError`, timed out, or a reply stayed cut/malformed after its one retry; the flow ends `failed(model_unavailable)` (detail "timed out on <step>" / "not running"), always before the click.
- **Reason codes:** unchanged, plus `model_unavailable` (contracts v5).
- **Deadline (D-81):** `attempt_timeout_s` (420) for Greenhouse and `attempt_timeout_workday_s` (900) for Workday, both **excluding** the IMAP wait (the mail wait has its own `mail.wait_s`). `services.deadline_left()` is checked before every model call and before step 9; exceeded → `failed(error)` "timed out" before typing on that page.

| Situation | Behaviour |
|---|---|
| Ollama not running | warm-up fails before Edge opens → `model_unavailable` |
| Reply cut (`done_reason == "length"`) or malformed | the chunk is split in half / re-asked once; still → `transport_failed` |
| Model says unknown on a required field | capture + `unanswerable_required` |
| Long list, no matching option | unknown; required → capture |
| Search returns nothing | optional: text cleared; required: unknown → capture |
| CAPTCHA / bot check | AD §8.4 (classify after navigation, before step 9, before the corrective pass) |
| No fields on a non-review step | `page_unrecognised` ("no fields on <step>") |
| Imported entries but no source entries | `profile_incomplete` (§5.2) |

---

## 12. Review Q-30 findings

### 12.1 F1 (HIGH): generic labels

- `plan.is_generic(label_norm)`: in `GENERIC_LABELS`, or fewer than 2 content tokens after the QD §5.2 stop words.
- `plan.qualified_label(label, description, context, *, step="", ordinal=0) -> str`: generic → `norm(label) + " | " + norm(description or context)`; **with neither (M1)** → `norm(label) + " | @" + step + "#" + str(ordinal)` (ordinal = the field's position among the step's generic fields); non-generic → `norm(label)`.
- **L6:** a generic label matches `extra` only on the qualified label **and** only through `by_employer[<this employer>]`; the base value is never used. Non-generic: QD §6.2.
- **Model (H5a):** a generic-label field may cite only `extra` entries scoped to this employer (G12); facts from other employers' generic answers are not listed.
- **Capture:** `label_norm` = the qualified label; answers to generic keys are saved employer-scoped (WP-Q5 sets `employer` automatically).
- **Oracles:** different help texts at two employers → no reuse; same help text, other employer → no reuse; same employer and context → reuse; a context-less generic label at the same employer, step and position → reuse on retry.

### 12.2 F3 (MEDIUM): variant answers and clearing a pick

(a) For `choice`/`multi`, only rows that received a pick become `answered`; for an employer-scoped answer, only rows with sightings from that employer. (b) The UI sends `[]` for a cleared variant; `_merge_picks` drops its norms from `picks` (kept in `seen`). (c) A group is `answered` only when all its rows are.

### 12.3 F4 (MEDIUM): an all-caps "US"

In a label written entirely in capitals, a bare `US` yields both `US` and `ctx.job_country`; equal → answered, different → `conflict`. Mixed-case labels: D-76 unchanged.

---

## 13. Latency, caching, config

### 13.1 Budget (D-81)

| Item | Measured (S-5b) | Budget |
|---|---|---|
| Cold model load | ~33 s first call | hidden by `backends.warm(backend, keep_alive)` at attempt start |
| Page, 1–15 fields | 2–10 s | `page_timeout_s` 120 per call |
| Page, 47–54 fields | 47–54 s | chunked per entry (each ≤ ~20 s) |
| Follow-ups | ~1–2 s each | ≤ `max_followups` (25) per attempt; beyond → unknown |
| Greenhouse attempt | — | ≤ 4 min typical (NF-07 kept), `attempt_timeout_s` 420 |
| Workday attempt | — | ~5–6 min, `attempt_timeout_workday_s` 900 (D-81); both measured at the gate |

### 13.2 Prompt-prefix reuse

FACTS (+ RESUME on non-entry chunks) first and byte-identical within an attempt; `keep_alive` keeps the model loaded. Unverified for Ollama; WP-M4 records `prompt_eval_ns` of a repeated prefix.

### 13.3 Decision cache (`fill_cache`; M4, TR-2)

- Key `(job_id, field_sig, prompt_version, model, inputs_hash)`: `field_sig = sha256(kind + qualified label_norm + sorted option norms + group + origin + norm(shown))[:16]` (shown values are hashed, never stored); `inputs_hash = sha256(redacted resume text + JD text)[:16]`.
- Row: the `ModelDecision` only (`source`, `ref`, `evidence`, and `value` only for `resume`/`job`/`keep`; a fact decision stores no value) + `facts_used_hash` = sha256 of the cited facts' current values (profile leaves or the `extra` entry).
- Replay: a row whose `facts_used_hash` no longer matches is a miss; a hit goes through locks and G1–G12 again and the program recomputes fact values. So answering a question in the Profile tab (which rewrites `applicant.yaml`) leaves every other decision cached.
- Purge rows older than 30 days at `apply_flow.run` start (`now` seam, TR-5). `llm_fill.cache: false` disables it.

### 13.4 Config

```yaml
apply:
  fill: llm                      # llm (D-78) | rules (old path; removed by WP-C1)
  attempt_timeout_s: 420         # Greenhouse and others; excludes the IMAP wait (D-81)
  attempt_timeout_workday_s: 900 # Workday (D-81); excludes the IMAP wait
  workday_entry: auto            # auto = resume import when offered, else Apply Manually | manual
  llm_fill:
    num_ctx: 32768
    page_timeout_s: 120
    max_fields_per_call: 20
    long_list: 15
    keep_alive: "15m"            # sent only when set
    second_opinion: true         # false: answers that need G5 end unknown
    cache: true
    max_followups: 25
    max_reveal_rounds: 2
    debug_dump: false            # redacted prompts only, data/apply/<id>/prompts/
```

---

## 14. Store (DDL; additive, `SCHEMA_VERSION` + 1)

```sql
-- apply_answers: columns added in _migrate: evidence TEXT, shown_json TEXT, shown_origin TEXT, entry TEXT
CREATE TABLE IF NOT EXISTS fill_cache (
    job_id TEXT NOT NULL,
    field_sig TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    facts_used_hash TEXT NOT NULL,
    decision_json TEXT NOT NULL,           -- ModelDecision only; never a private fact value
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, field_sig, prompt_version, model, inputs_hash)
);
```

Methods: `fill_cache_get(job_id, sigs, prompt_version, model, inputs_hash) -> dict[sig, dict]`, `fill_cache_put(job_id, rows, now)`, `fill_cache_purge(before) -> int`.

---

## 15. Deviations, decisions, open items

- **NF-07 (D-81):** Workday may take ~5–6 min; Greenhouse stays ≤ 4 min; both measured at the gate.
- **Locks (D-82):** O-1 answered: locks stay deterministic; the owner may revisit (an ADR-0003 change).
- **Gate (D-83):** 5 Greenhouse dry runs; the Coordinator reads each dry-run audit row by row before a real submission; a required `resume_import` value is kept only when G3 passed (G8); gate Workday postings need fresh owner approval.
- **AD §5.3 held:** the prototype sent contact values and nationality to the model; this design redacts them (§6.5) and answers citizenship questions by L5.
- **O-2 closed:** `ResolveContext.resume_entries` is in v5; `tailor_flow.resume_entries(cfg)` and the fill in `apply_flow` belong to WP-N6b.
- **Superseded in `apply_design.md`:** §6 (schema plan as fill source), §7.2 tagging, §7.6, §9.1.1 KEEP table (→ G8), §9.4.2 step 3, §9.4.5–§9.4.10, §15 (→ §9.4). Planner adds pointers.

---

## 16. Test strategy (tester)

Fixtures (`tests/fixtures/apply/llm_fill/<tenant>/`, `wd_a`, `wd_b`): `page.html` (scrubbed to `applicant.sample.yaml` values, "Example Employer", no requisition ids; My Information **pre-filled with the sample's phone and address** for the privacy oracle), `fields.json`, `reply.json`. The fake backend routes on the exported system constants, keys replies on `group|question` parsed from the FIELDS JSON block, and records every prompt.

| Oracle | Expect |
|---|---|
| Privacy (H4, TR-1) | no `s_values` item, no email, in any recorded prompt; pre-filled phone/address fields carry `current_set` |
| G2 scope (TR-3) | a job's Location citing `profile:contact.city` → unknown |
| G2 relevance/polarity (H2) | "able to work without sponsorship" citing `requires_sponsorship` with no tier-2 match → unknown unless the model's option equals the program's; citizenship Yes from `standing:work_rights` → unknown |
| G2 entry facts (H2) | a "Malay" language entry citing `profile:languages[0].level` (English) → unknown |
| G2 empty fact | required address field, empty in the sample → `profile_gap` capture |
| G3 copy (H1) | Location "Singapore" with an in-block quote that lacks it → UNGROUNDED |
| Recheck (H1c) | a reply with an extra line → rejected; unknown → optional cleared / required unknown |
| G5 | a Yes/No (optional too) whose second reply disagrees → unknown |
| G7 (M2) | "Are you a Singapore PR?" from `resume` → unknown |
| G8/G9 (H3) | an optional imported "Website" the model calls unknown → cleared; a pre-ticked opt-in → unticked; a non-resettable radio → PREFILLED "unverified" |
| G11 (M12) | a title containing the employer → recheck → stripped or unknown |
| G12 (H5) | an `extra` text naming another employer is not listed; a MyGreenhouse textarea needs G3 |
| L1 (H6, TR-8) | an attachment with our name not uploaded in this attempt → replaced; a cover-letter input never gets the resume |
| K order (M1) | an `attestation_unclear` answered by the owner resolves on retry through L6 |
| Revealed field (H7) | a stub where "Yes" reveals a required textarea → second round; unanswerable → stop; Greenhouse pre-Submit scan stops an empty required field |
| Step id (M7) | two "Application Questions" pages → different ids, no `page_unrecognised` |
| Enter (M8) | no Enter sent outside a prompt search box or inside a form with a submit control |
| Nothing changed (M9, TR-7) | zero fill/clear/reset/delete/add calls when step 7 stops |
| Cache (M4, TR-2) | after an `extra` answer, uncited decisions replay with zero model calls; a cited changed fact → miss |
| Clock (TR-5) | `today_sg(16:30Z)` → the next day |
| Flow | dry run `wd_a` → `ready_to_submit`; `transport_failed` → `model_unavailable`; deadline between chunks |

An optional eval `tests/evals/llm_fill.py` (TR-12; real model over the sanitised fixtures, not in the suite): thresholds 0 S leaks, 0 ungrounded fills.

---

## 17. Requirement map

| Req / decision | Where |
|---|---|
| D-78 | §1, §3–§10, ADR-0006 |
| D-81, D-82, D-83 | §11 deadline, §13.1, §4, §15, G8 |
| F-31 | §9 |
| F-32 | §4–§7 |
| F-33 | §4 L3, L7 |
| F-34 | §3.2, §8, §10, L1 |
| F-12, F-13 | L6, §11, §12 |
| F-30, F-37, F-38, NF-06 | §8 (pre-Submit scan, state machine unchanged), §11 |
| F-39 | §7 answer mapping, §14 |
| D-70 | L1, §9.2, §10 E1 |
| D-75 | L4, `standing:work_rights` |
| D-76, review F4 | §12.3 |
| D-77 | D-83 reading (§15) |
| D-79 | §5.1 |
| NF-02, NF-09 | §6.5, §13.3, §13.4 |
| NF-03, NF-04 | §2.2 |
| NF-07 | §13.1 (D-81) |

---

## 18. Prior art (≤ 8 searches, 2026-11-03)

| Project | Licence | Borrowed | Not borrowed |
|---|---|---|---|
| browser-use | MIT | the page as a numbered list of elements the model refers to by id | the agent loop that also navigates |
| Stagehand (Browserbase) | MIT | schema-constrained extraction; caching results keyed by inputs (§13.3) | natural-language `act()` |
| Skyvern | AGPL-3.0 core; its cloud solves CAPTCHAs | idea only: validate after each step | code; CAPTCHA solving |
| AIHawk | AGPL-3.0; auto-apply removed from the repo | resume + profile YAML as facts | ungrounded answers |
| Small job-apply agents | mixed / unverified | the shape: read fields → model maps → pause before submit | code |

Nothing is copied; sources are in ADR-0006.
