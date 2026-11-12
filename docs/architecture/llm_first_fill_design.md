# LLM-first form filling: always answer (D-208; KA-2, touches KA-1/KA-4)

**Stage B**, queue Q-121. Author: architect, 2026-11-12. **Status:** draft for review. **Decision record:** `adr/0011-llm-first-always-answer.md`. **Builds on:** `llm_fill_design.md` (**LF §n**), `apply_design.md` (**AD §n**), `questions_design.md` (**QD §n**), `apply_queue_design.md` (**AQ §n**), `q116_settings_design.md`. **Inputs:** D-208 (owner, verbatim in `instructions/02_status.md` §4); `01_scope_and_goals.md` §3/§5 principles 1 and 3 as amended; the owner's first live attempt (Greenhouse embedded form, 43 fields read, 0 filled, `unanswerable_required`); the Q-119 engineer's reproduction (Coordinator message, 2026-11-12).
Rule ids: **H1–H10** hard constraints (§2), **D1–D10** standing rules (§3.4), **A1–A9** page steps and **P1–P3** code pre-fill (§4.1), **R0–R5** option ladder (§4.3), **X1–X9** last resort (§4.5). Every "MUST" is a build rule.

## 1. Summary
```
apply_flow (state machine, claim, queue, accounts, mail, submit: UNCHANGED)
 pagefill.fill_page ─ policy strict → today's path, unchanged (LF §8)
                    └ policy always (local model only) → always.fill_page_always:
  A1 read + settle   A2 code pre-fill (P1 files, P2 identity email, P3 owner's exact earlier answer)
  A3 main pass       BRIEFING (cached prefix) + JOB + ≤20 FIELDS → {value, basis, ref, assumed, reason}
  A4 mechanics       coerce formats, map onto options (R0-R5), hard checks
  A5 must-answer     required fields still unusable: focused calls, "none" not allowed
  A6 last resort     X1-X9 by field type, marked assumed; > last_resort_max → system failure
  A7 apply           bot check, entries, fill + read-back, verification read, revealed fields
  A8 corrective      site errors / required scan → one A5 round → else validation_error
```
- **The model answers every field from one briefing**: the whole profile, every earlier owner answer, code-computed facts, the owner's standing rules, the full resume, then the job. Tier-2 rows, declaration classes, locks and relevance become **hints in the field view**, never a reason to leave a field empty (principle 3).
- **Code keeps the mechanics and the hard limits** (§2): the file, the identity email, secrets out of every prompt, offered options only, format coercion, read-back, bot-check stops, never twice, the pre-Submit scan, the audit.
- **Nothing ends `unknown` under `always`.** A required field with no basis gets the model's most neutral truthful answer, marked **assumed** and offered to the owner as "Answered for you". Only a system failure (model down, no usable replies) stops, and that pauses the queue (AQ §4.1).
- **`strict` stays** selectable and is the code default, so the ~600 existing apply pins keep their meaning with no edit (§13).

## 2. Hard constraints and where each lives
| # | Constraint | Home |
|---|---|---|
| H1 | Passwords, app passwords, vault secrets never in a prompt (NF-02) | (a) `briefing.build` reads profile + `extra` only, never the vault, and drops `documents`, `version`, `contact.backup_email`; the reader already drops `type=password`. (b) **Choke point** in `backends.py`: `forbid(values)` / `allow_all()`; `apply_flow` registers the account password and the IMAP app password when it loads them; `complete()` refuses any prompt containing one (`PromptRefused(BackendError)`), covering tailor and compose too. The flow ends `failed(error, "prompt check")` before any keystroke on that page |
| H2 | Local model only | `apply_flow.resolve_ctx`: effective policy `always` only when `backends.is_local(backend)` (D-107 rule); else `strict` (today's redaction) + log line "fill_policy always ignored: model not on this computer". Fall back, don't refuse: strict is safe and works |
| H3, H4 | One in flight, never twice; CAPTCHA / bot / SMS / 2FA stop | unchanged: `claim_click`, the queue worker (ADR-0010), `submit_clicked_at` (ADR-0004); `services.classify` before the first keystroke (A7) and before A8 |
| H5, H6 | Files chosen by code; the identity email is the vault's | P1 and P2 (`ctx.email`); FILE and EMAIL fields never enter FIELDS |
| H7 | A choice takes an offered option only | A4 + ladder §4.3 + widget strict read-back (LF §3.2) |
| H8 | Pre-Submit scan | kept; under `always` a hit gets one A8 round, then a rescan; still a hit → `validation_error`, nothing sent |
| H9 | Every answer audited with its basis | §6 |
| H10 | No personal values in the job log; tests never apply | log lines carry counts only ("page application: 28 answered, 3 assumed, 0 last resort, 2 calls, 21 s"); `debug_dump` keeps redacting S values; tests use fake backends and fixture pages |

## 3. The briefing ("pre-prompting")
### 3.1 Module and shape
New pure module `apply/briefing.py`: `build(profile, rctx, *, extra_filter) -> Briefing(text, hash, tokens)` and `job_block(rctx, *, today) -> str`. Built once per attempt; deterministic (fixed order, no timestamps), so byte-identical across attempts until the profile, `extra`, the master resume or a rule changes. `hash` = sha256(text)[:16]. Prompt version `always:v1`. Sections, in order:
1. **PROFILE**: every group, labelled with the Profile form's labels (`applicant.FORM`): identity, contact (no backup email), work rights and status, availability, pay (monthly and annual), skills and attested skills, languages, links, consents, declarations, US self-identification, then `Education 1 (newest)` … and `Experience 1 (most recent)` … one line per entry field.
2. **ANSWERS YOU GAVE BEFORE**: every usable `extra` entry (title, the labels it answers, the answer; `by_employer` only for this employer; the G12 filter on other employers' answers kept). Cap 40 entries.
3. **COMPUTED FACTS** (§3.3). 4. **STANDING RULES** D1–D10 (§3.4). 5. **RESUME**: the master text in full (`tailor_flow.master_text`, else the extracted file).
Outside the cached part: **JOB** (company, title, location, today, the this-employer facts of §3.3, the JD's first 6000 characters), then per call **PAGE**, **FIELDS (JSON)** and the **TASK** line (§5.1).
### 3.2 Token budget (num_ctx 32768) and RAG verdict
| Part | Tokens (~3.6 chars/token) |
|---|---|
| SYSTEM_ALWAYS ~600 · PROFILE (4.3 KB YAML → labelled lines) ~1,400 · ANSWERS ≤ 1,000 · COMPUTED + RULES ~700 · RESUME (6.8k chars) ~1,900 | **stable prefix ~5,600** |
| JOB (JD ≤ 6000 chars) | ≤ 1,800 |
| FIELDS: 20 fields × ~90 (options ≤ `long_list` inline) | ~1,800 |
| Output: `max_tokens = 60 × fields + 200` | ≤ 1,400 |
| **One call** | **~10,600 (32% of num_ctx)** |

**RAG: not built.** The whole briefing fits three times over. Retrieval is needed only when the stable prefix passes `llm_fill.briefing_max_tokens` = 18,000 (32,768 minus JOB, 20 fields, output and a 4k margin): about 65k characters, i.e. hundreds of `extra` answers. The design then: PROFILE, COMPUTED, RULES and RESUME stay whole; ANSWERS is replaced per call by the 15 entries whose labels share the most tokens with the call's field labels (deterministic, `plan.tokens`, no embeddings), placed **after** JOB so the cached prefix survives. Until then `briefing.build` logs "briefing large: N tokens" and `doctor` warns above the threshold.
### 3.3 Computed facts (code; never the model's arithmetic)
Today (Asia/Singapore); full name and name order; experience in years and months (`applicant.computed_facts`); highest qualification, graduation date and year (newest education `end`, "expected" when future); currently a student; current or most recent employer and title; currently employed (`end: null`); notice period and earliest start (`max(earliest_start_date, today + notice)`); aged 18+/21+ (only when `date_of_birth` is set); work rights for SG, each listed country and "any other country" (`applicant.work_rights`), plus "holds citizenship or residence only in <nationality>, and no visa or residence permit elsewhere"; expected pay monthly and annual (`months_per_year`). **JOB block:** worked here before, employed here now (`declarations.prior_employment` / `current_employment`), applied here before (`rctx.previously_applied`), a relative works here (`relatives_employers` match), holds shares here (`holdings` match).
### 3.4 Standing rules (code-built from the profile; a profile value always beats a default)
| Id | Rule given to the model |
|---|---|
| D1 `no_declaration` | from `declarations.*`, each false key stated as a status: not a politically exposed person nor family or close associate of one; no relatives or close relationships with this employer's staff or public officials; no conflict of interest, audit-independence issue or shareholding here; no criminal record, charges or proceedings; never bankrupt; no regulatory or disciplinary action; no non-compete, non-solicitation, NDA or other restrictive agreement; never employed by a government, public body or statutory board (NS not counted). "Answer so the answer states this, whichever way the question is worded (Yes when a negative wording makes Yes state it)." A true key is stated as true |
| D2 `employer_history` | the JOB block's facts answer worked / employed / applied here, relative here, shares here |
| D3 `work_rights` | §3.3's per-country lines; another territory's citizenship, residence or visa → none held; sponsorship or authorisation elsewhere → the "any other country" line |
| D4 `self_id` | gender, race, ethnicity, veteran, disability, pronouns, religion, marital status: the profile value; "decline" → the "prefer not to say / decline" option |
| D5 `consent` | consents, acknowledgements ("I have read / understood / been advised"), certification of truth, privacy and data processing needed to apply → agree, unless `consents.*` says false |
| D6 `talent_pool` | marketing, future roles → `consents.talent_pool_opt_in`, else No |
| D7 `availability` | start date, notice, "can you start by <date>" from the computed availability |
| D8 `how_heard` | `sourcing.how_heard_default` → the closest option, else "Company website / Careers site", else "Other" |
| D9 `willing` | relocate, travel, sign an NDA, background check, on-site: the profile value when set; otherwise Yes, **assumed** |
| D10 `health` | a health condition affecting work → No; with `health_disclosure: decline` and a "prefer not to say" option, that option |
### 3.5 Prefix reuse (Ollama)
Ollama's runner reuses the KV cache for the longest token prefix shared with the previous request on the loaded model. MUST: (1) one `SYSTEM_ALWAYS` for every call type under `always` (main, must-answer, pick, corrective); the instruction is the final TASK line; (2) the user message starts BRIEFING, then JOB; (3) the same `num_ctx` for every apply call, compose included (a change reloads the model); (4) `keep_alive` 15m as today; (5) `backends.warm(backend, keep_alive, prefix=...)` sends system + briefing + JOB with `num_predict: 1` while Edge opens. Verify at the gate with `CallLog.prompt_eval_ns`: from the second call, prompt evaluation ≤ 25% of the first. Without reuse a call costs ~2 s more (~7k tokens), so reuse is an optimisation, not a dependency.

## 4. The always-answer algorithm (one page; new `apply/always.py`)
### 4.1 Steps
- **A1 Read and settle.** `page.read_page` (with Q-119); wait `settle_ms` (1500); read again. A value that appeared between the reads (the site restores earlier input) is a site value with the import origin (LF §3.3): the model sees it as `current` and answers `keep` when it matches the briefing, a new value otherwise. Values JobScraper typed are never shown back (S-5b). A field with **no label and no options** is skipped (`SKIPPED`, "no label") unless the page marks it invalid; then its context or placeholder is its question.
- **A2 Code pre-fill.** **P1** files: the resume slot (L1 rules); `documents.transcript` for a transcript; the composed letter for a cover-letter FILE (§4.6); another **required** FILE (portfolio, "additional documents") → the resume, assumed; a required transcript with none set → `failed(document_missing, "transcript")`, per role; optional others skipped. **P2** EMAIL fields and email labels ≤ 4 tokens → `ctx.email`. **P3** the owner's own answer to the **exact qualified label** (L6 with the F1 generic-label guard) when it fits: the owner's correction must win (§6.3). P-fields are context lines (`locked: true`).
- **A3 Main pass.** All other fields, required and optional: entry chunks (§4.4), the rest ≤ `max_fields_per_call` (20) per call.
- **A4 Mechanics.** Coerce (§4.2); choices and typeaheads through the ladder (§4.3); hard checks: H7; another person's field must not carry the applicant's own name or contact (G13); a free text must not name another watchlist employer as the target (G12, own employers excepted); no placeholder (`[…]`, "lorem", "your name"). A failed check → unusable → A5.
- **A5 Must-answer.** Each **required** field with a missing, `none`, empty, unparseable or unusable value: batches of `must_answer_batch` (8) on the same prefix, `TASK_MUST`, schema without `none`, the A4 problem in the field view (`problem`, no values).
- **A6 Last resort.** Still unusable → X1–X9 (§4.5), assumed, source `last_resort:<X>`. More than `last_resort_max` (5) on one page, or a call unusable for every field after its one retry → **system failure**: `transport_failed`, note "no usable answers" → `model_unavailable` → queue pause. Never a page of guesses.
- **A7 Apply.** `services.classify`, deadline; entry deletes (E3 junk only) and adds (§4.4); fill values that differ from the shown one; an optional field left `none` that shows a site value is cleared/reset (G9 mechanics); strict read-back; then a **verification read** of every decided field: a value the site reverted is filled once more, else `fill_failed`. Revealed fields: A1–A7 (≤ `max_reveal_rounds`).
- **A8 Corrective.** Site errors after fill or Next, a required `fill_failed`, the required scan: one A5 round with `site_error`, then A6, fill once; still failing → `validation_error` (the site's rejection, not a guess).
- **A9 Outcome.** `PageOutcome` with `answers`, `assumed`, `last_resort`; `unknown_required` always empty; cache put (§8).
### 4.2 Coercion (code)
Dates: the model gives `YYYY-MM-DD`/`YYYY-MM`/`YYYY`; code writes segmented dates by role, `MM/YYYY` text, a month dropdown ("June"/"Jun"/"06"/"6" via R0) and a year dropdown; an open end ticks a "current/present" box when one exists, else the current month, assumed. Numbers: digits, the field's decimal separator, within `min`/`max`; salary converted to the field's period. Phone: digits without the code when a code control exists; the code control gets "+65" via `deterministic_pick`. Text: trimmed to `maxlength`; an entry title loses its employer (" at X", " - X": old G11 as a fix). URLs verbatim.
### 4.3 Option ladder (choices, typeaheads, long lists)
| Rung | Rule | Mark |
|---|---|---|
| R0 | `deterministic_pick`: equal (normalised), a `Category > Leaf` leaf, a phone code | basis kept |
| R1 | the single option with the highest token overlap ≥ 0.6 with the wanted words (`facts.overlap`), no tie | basis kept |
| R2 | one `TASK_PICK` call on the shared prefix (question, wanted words, options) → an option or "" | basis kept |
| R3 | neutral, in order: "Prefer not to say"/"Decline…" (D4/D10 only), "Other", "Not listed", "None of the above", "Not applicable"/"N/A" | assumed |
| R4 | required only: the first option that isn't a placeholder ("Select…", "--") | assumed |
| R5 | optional: leave empty | — |

**Remote typeahead** (location, school): queries in order: the model's words (≤ 40 chars) → their first word of ≥ 3 letters → a family fallback from the briefing (city → `contact.city`, then the country; school → the institution without "The"/"University of"; else "Other") → R1–R4 on the last list shown. No query ever shows an option → empty → A8 → `validation_error`. `pick_option`'s deterministic first step is kept; `pick_refused` is not called under `always`.
### 4.4 Repeating entries (education, experience)
- **Detection is a hint.** When `nav.entry_sections` finds groups, an entry chunk carries its source entry's block. When it doesn't (Greenhouse education today: a `<p>` title, no numbered heading, the section named after "Phone"), the fields go in the main pass under rule 8: an education or experience field outside a numbered entry is about the newest entry. Failed detection never prevents filling.
- **Binding.** A slot that shows a school/employer binds by E2 as today; a **blank** slot binds to the first unbound source entry in profile order (newest first). Source = the profile's entries, else `rctx.resume_entries`.
- **Adding.** With an "Add another" control, add until bound slots = min(source entries, `max_entries.<section>`: education 2, experience 3); a one-slot form gets the newest entry. A failed Add is an attempt note ("1 of 2 education entries added"), not a stop (D-174 stays for `strict`). E3 (delete imported junk) stays; E6 is dropped.
- **Dates:** Start month/year and End month/year are four fields answered from one entry via §4.2.
### 4.5 Last resort (deterministic, `always.last_resort`)
| Id | Field | Value |
|---|---|---|
| X1 | yes/no or one checkbox, declaration-like (`declarations.classify` hit or marker) | the option stating "none applies": No; Yes/ticked when `declarations` polarity finds a negated wording |
| X2 | yes/no with consent words (agree, acknowledge, confirm, consent, understand, certify, advised) | Yes / ticked |
| X3, X4 | yes/no with willingness words (willing, able to, open to, prepared to); any other yes/no | Yes; No |
| X5 | choice, multi, typeahead | ladder R3, then R4 (multi: one item) |
| X6 | required text | about another person → "Available on request"; else "N/A" |
| X7 | required free text | "Please see my attached resume for details." |
| X8 | required number | the field's `min` when set, else 0 |
| X9 | required date | start/availability → the computed earliest start; else today |
### 4.6 Free text and composed texts
Free text is written by the model in A3/A5 from the briefing and JD. `resolve.grounded` (old G3 compose rule) runs as an **audit check**: words it can't find in the briefing or JD set `assumed` ("words not in your profile or resume"); the value is sent. **Compose targets** (cover letter, "why join", LF §19.1): every **required** target is composed by `tailor_flow.compose` whatever `apply.compose.enabled` says; optional ones only when it is on. C1–C7 keep one retry; a second failure **prunes** (new `compose.prune(text, issues)`: drop each sentence holding a C2/C3/C4/C6 token, a C5 value or a C7 placeholder) and uses the rest when ≥ 2 sentences remain, else a code-built neutral text ("I am applying for the <title> role at <employer>. My resume, attached, sets out my education and experience."), assumed. No `compose_needed` capture under `always`.

## 5. Prompts and schema (`always.py` builds them; only `backends.py` calls the model)
### 5.1 SYSTEM_ALWAYS (`always:v1`) and TASK lines
```
You fill in a job application form for the applicant described in BRIEFING. You answer for them.
1. Use BRIEFING: PROFILE, ANSWERS YOU GAVE BEFORE, COMPUTED FACTS, STANDING RULES, RESUME. Copy facts
   exactly: names, schools, employers, dates, grades, numbers, links.
2. Derive when a question is worded differently: a degree gives the discipline, citizenship and the
   work-rights lines give visa and sponsorship answers, dates give durations, the newest entry gives
   "current" answers.
3. STANDING RULES are the applicant's own answers. Follow them whichever way a question is worded.
4. Every REQUIRED field gets an answer. If nothing in BRIEFING bears on it, give the most neutral truthful
   answer (an option such as "Prefer not to say", "Other" or "Not applicable" when offered) and set
   "assumed": true. Never invent what BRIEFING does not give: no grade, salary figure, employer,
   school, date, number or name.
5. An OPTIONAL field: answer it when BRIEFING covers it; otherwise basis "none" and value "".
6. Options: copy one exactly (several only where allowed). A "search" field: the words to type, ≤ 40 characters.
7. Dates as YYYY-MM-DD or YYYY-MM; numbers as digits; a phone number without its country code when the
   form has a separate country-code field.
8. A field inside an ENTRY uses that entry's facts. An education or experience field outside a numbered
   entry is about the newest entry. A field about another person (referee, emergency contact) never
   takes the applicant's own name or contact details.
9. Free text: first person, plain, from BRIEFING and JOB, within the limit; no placeholders; name only
   this employer as the one applied to.
10. basis: profile:<path> | extra:<key> | standing:<id> | resume | job | default:<rule id> | keep (the
   current value is right) | assumption | none. reason: ≤ 12 words; required when assumed is true.
```
`TASK_MAIN` "Answer every field in FIELDS. Reply with one JSON object keyed by field id." · `TASK_MUST` "These REQUIRED fields still need an answer; each shows its problem. Basis none and empty values are not allowed. If BRIEFING does not settle one, give the most neutral truthful answer and set assumed: true." · `TASK_PICK` "Pick the one option that best means WANTED for QUESTION. Copy it exactly, or answer \"\"." · `TASK_CORRECT` = TASK_MUST + "The site rejected the value: see site_error."
**Field view:** `id`, `question`, `kind`, `required`, `section`/`entry`, `context`, `help`, `options` (≤ `long_list`) or `options_note` (count + 5 examples, "search"), `current` (site values only), `parts`, `maxlength`, `site_error`, `problem`, and **`hints`**: the old mechanisms' findings as words ("declaration: pep (D1)", "negated wording", "profile rule: singapore_status.requires_sponsorship", "earlier answer: extra.visa_status", "names country: HK", "generic label; see context").
### 5.2 Output schema (`format`)
Per field id: `value` (choice ≤ `long_list` → enum + ""; multi → array of enum; checkbox `["true","false"]`; else string with `maxLength`), `basis` (enum; **without `none` for required fields**), `ref` (≤ 80), `assumed` (bool), `reason` (≤ 100). `temperature=0`, `seed=7`, think off, timeout `page_timeout_s`; a cut or malformed reply is split and retried once (LF §11).

## 6. Audit, assumptions and the owner's control
**6.1 Rows.** `Answer.source` = the basis (`profile:<path>`, `memory:extra.<key>`, `standing:<id>`, `resume`, `job`, `default:<D>`, keep → the origin, `assumption`, `last_resort:<X>`, `field_map:resume|email` for P1/P2, `composed`); tier `LLM` for model answers; `rule_id = always:v1`; `evidence` = the model's reason (local DB only, never logged; Q-113's stored-quote redaction is `strict`-only). **`assumed`** for basis `assumption`, every `last_resort:*`, R3/R4, a free text failing the grounded check, D9 uncovered willingness, a value differing from the fact it cites ("differs from <ref>"). Confidence: fact/default 0.9, resume/job 0.85, assumed 0.5.
**6.2 Attempt.** `apply_answers.assumed`; the attempt summary and Applications pill read **"Submitted · 3 answers assumed"** / **"Ready to submit · 3 answers assumed"**; "What I told this employer" highlights assumed rows with their reason.
**6.3 "Answered for you"** (reuses questions + `extra`). `questions.capture_assumptions(fields, answers, rctx, rules)`: every filled `assumed` row except FILE and P-rows, `reason = assumed`, grouped and keyed as QD §5; called after every page through `_capture_questions` (never changes an outcome). `store.upsert_question`: new rows `status = assumed`; a seen-again `answered` row whose saved answer wasn't used becomes `assumed`; `dismissed` stays. No value goes into `questions` (QD §7 kept): the card reads it from `apply_answers` by the latest sighting's (attempt_id, field_key). Card: chip **"Answered for you"**; body **"JobScraper answered “{answer}”: {reason}. Keep it for next time, or change it."**; buttons **Keep** / **Change**. Keep saves the sent value to `extra` (labels, kind, picks/seen) and marks the row `answered`; Change saves the owner's value. From then on P3 or ANSWERS YOU GAVE BEFORE carries it. `retry_candidates` unchanged.

## 7. Contracts, config, store
### 7.1 Contract additions (additive; `apply/contracts.py`; the architect writes them after review as WP-0; v6 → **v7**, or folded into Q-120's v6 if it hasn't merged)
- `class FillPolicy(str, Enum): STRICT = "strict"; ALWAYS = "always"`; `ResolveContext.fill_policy: FillPolicy = FillPolicy.STRICT`.
- `Answer.assumed: bool = False`; `ModelDecision.assumed: bool = False` (`evidence` doc: "under always, the model's reason").
- `FillSource`: `DEFAULT`, `ASSUMPTION`, `NONE` ("none"). `AnswerSource`: `DEFAULT`, `ASSUMPTION`, `LAST_RESORT` ("last_resort").
- `DEFAULT_RULES = ("no_declaration", "employer_history", "work_rights", "self_id", "consent", "talent_pool", "availability", "how_heard", "willing", "health")`; `LAST_RESORT_RULES = ("X1", …, "X9")`.
- `ReasonCode.DOCUMENT_MISSING = "document_missing"`; `REASON_TEXTS`: **"This form needs a {detail}, and your profile has none. Nothing was sent."** / hint **"Add it in Profile, then try again."** `QuestionStatus.ASSUMED`, `QuestionReason.ASSUMED` ("assumed"). `PageOutcome.assumed`, `PageOutcome.last_resort: tuple[str, ...] = ()`. `FillServices.briefing() -> Briefing`.
### 7.2 Config and Settings
```yaml
apply:
  fill_policy: always          # always (D-208): the local AI answers every field | strict: stop and ask (ADR-0003)
  llm_fill: {must_answer_batch: 8, last_resort_max: 5, settle_ms: 1500, briefing_max_tokens: 18000,
             max_entries: {education: 2, experience: 3}}   # added to the existing block
```
`ApplyConfig.fill_policy` defaults to `"strict"`; the shipped `config/config.yaml` (the owner's install) says `always`. Read in `apply_flow.resolve_ctx` (with H2) into `ResolveContext.fill_policy`; under `always` the effective `model_sees_sensitive` is true. Settings → Apply row (q116 table format):

| Group | Row label (`id`) | Description line | Value shown | Control | Saves to | v1 |
|---|---|---|---|---|---|---|
| How applying works | How forms are answered (`fill-policy`) | Always answer: the local AI fills every field from your profile and resume and marks anything it had to assume. Ask me first: it stops and asks when your profile doesn't cover a question. | Always answer / Ask me first | edit: 2 radios | `fill_policy` (`always` \| `strict`) | v1 |

The "Write cover letters" description gains "Required ones are always written when forms are answered automatically." Q-111 exposes `fill_policy` in `GET/PUT /api/apply/settings` as writable.
### 7.3 Store (additive; `SCHEMA_VERSION` + 1 after Q-120's v6)
`ALTER TABLE apply_answers ADD COLUMN assumed INTEGER NOT NULL DEFAULT 0;` and `questions.status` gains `'assumed'` (TEXT, no DDL). No value column in `questions`.

## 8. What each mechanism becomes under `always` (under `strict` everything stays as built)
| Mechanism | Under `always` |
|---|---|
| Tier 1 field map; L1, L1b files; L2 email | **hard mechanics**: P1, P2; other tier-1 values are briefing facts + coercion |
| Tier 2 profile rules | **hint**; their `value_map`/`yes_if`/`fit_*` are **mechanics** in R0/R1 when the basis cites that path |
| Tier 3 memory (`extra`); L6 owner answers | **briefing** + **hard** P3 on the exact qualified label only |
| Tier 4 declarations; L3 + D-90 gates; L7 negated declaration | **briefing** D1/D2 + **hint** ("declaration: pep", "negated wording"); the polarity gate lives on in X1; never a stop |
| Tier 5 per-field LLM | **removed** (main pass) |
| L4 work rights | **briefing** (§3.3) + **hint** "names country"; `conflict` no longer stops |
| L5 sensitive rows, consents | **briefing** + D4/D5 |
| L8 composed text | **hard**; composing forced for required targets (§4.6) |
| G1 shape | **hard** (H7, ladder) |
| G2 (a) scope, (b) relevance, (c)–(f) | **removed** as vetoes; (b) **advisory only** (a shared token like "i" from "i.e." made `consents.certify_true` "relevant" to a GPA question; a missing synonym rejected the education entry); a value differing from its cited fact → **audit flag** + assumed |
| G3 grounding | **audit flag** (free text → assumed) |
| G4 choice vs source; G5 second opinion; G7 sensitive | **removed** (G5: no extra calls, D1 makes declarations rule-driven; G7: everything is readable locally) |
| G6 entry scope | **hint** (entry chunk + rule 8) |
| G8 prefill trust | **removed**: the model sees `current` and answers `keep` or a value |
| G9 leftovers; G11 entry titles | **mechanics**: clear/reset what the model left `none` ("unverified site value" stays an audit note); strip the employer from a title (§4.2) |
| G10 required unknown | **replaced** by A5 + A6; only a system failure stops |
| G12 other employers; G13 own detail on another person's field | **hard** in A4 (+ the `extra` filter for G12); one A5 retry, then X7 / X6 |
| `pick_refused`; `quote_checked`, D-202 stored quotes | `strict` only; under `always` not called, and the reason is stored as is (local DB) |
| `Fact.private`, `sensitive`, `s_values` | badge, audit flag, **log and debug-dump redaction** only; prompts unredacted (`sv_prompt = []`) |
| Question capture | not a stop; **assumptions** captured (§6.3) |
| Fill cache | same key shape; `prompt_version = always:v1`; `inputs_hash = sha(briefing.hash + JD + "always")` (any profile/`extra`/resume edit misses); values stored; not stored: corrective, last resort, pick replies |

## 9. Stops and reason codes under `always`
Kept unchanged: `captcha`, `bot_challenge`, `sms_or_2fa`, `login_failed`, `email_verification_timeout`, `mail_not_set_up`, `validation_error` (site rejection after A8, or the pre-Submit scan), `page_unrecognised`, `posting_closed`, `unsupported_ats`, `cap_reached`, `duplicate`, `profile_incomplete` (pre-check), `cancelled`, `error` (+ "prompt check", H1). **New:** `document_missing` (per role; the queue continues). **`model_unavailable`** also covers "no usable answers on <step>" (A6): a system failure; the queue pauses and returns the item (AQ §4.1 already maps it). **`unanswerable_required`** is not produced by the filler under `always`; it remains for `strict` and for sign-up with `consents.privacy_consent: false` (the owner's explicit refusal, "account terms").

## 10. Worked example: the owner's Greenhouse form (after Q-119: 30 labelled fields + resume; placeholder values)
| Field family (Q-119 keys) | By | Value (placeholder) | Basis / mark |
|---|---|---|---|
| First / last / preferred name | A3 | Firstname / Lastname | `profile:identity.*` |
| Email · Resume | P2 · P1 | identity email · data/resume.pdf | `field_map:email` · `field_map:resume` |
| Phone · country code (react-select) | A3 + §4.2 · R0 | 90000000 · "Singapore (+65)" | `profile:contact.*` |
| Location (city), remote typeahead | A3 + query ladder | "Singapore" | `profile:contact.city` |
| LinkedIn / website (optional) | A3 | the link, or empty | `profile:links.*` / `none` |
| Education: School, Degree, Discipline (no entry group detected) | A3 rule 8 + R0–R2 | Example University / Bachelor's / Computer Engineering | `profile:education[0].*` |
| Education: Start month/year, End month/year | A3 + §4.2 | August / 2021 / June / 2025 | `profile:education[0].start/end` |
| `indicate_grade_point_average` | A3 | "4.00 / 5.00" when profile or resume has a grade; else "N/A" | `profile:education[0].grade` / **assumed** |
| `how_did_hear_about` | A3 + R1 | "Company Website" | `default:how_heard` |
| Sponsorship now or in future (SG role) | A3 | No | `standing:work_rights` |
| `immigration_status` (another territory) | A3 | "No" / "None" | `default:work_rights` |
| `region_currently_located` | A3 + R1 | "Asia Pacific" / "Singapore" | `profile:contact.country` |
| `preferred_office_location` | A3 + R1 | the JD's office when listed, else the option nearest Singapore | `job` / **assumed** |
| `if_last_professional_experience` (free text) | A3 | two sentences on Experience 1 | `resume` (grounded check) |
| `if_currently_employed_reasons` | A3 | not employed: "Not applicable: I am not currently employed."; employed: a short reason | `standing:current_employment` / **assumed** |
| `if_currently_employed_length` (notice) | A3 | "Immediately" | `profile:availability.notice_period_days` |
| `specifically_be_advised_that` (acknowledgement) | A3 | "I acknowledge" / "Yes" | `default:consent` |
| Declarations if shown (PEP, relatives, worked here) | A3 | No (Yes on a negated wording) | `default:no_declaration` / `standing:worked_here` |
| EEO / self-ID · privacy consent checkbox | A3 + R0/R3 | "Decline to self-identify" · ticked | `default:self_id` · `profile:consents.privacy_consent` |
| Optional "anything else" / optional cover letter | A3 / §4.6 | empty | `none` |

Expected: no required field empty, 2–4 assumed, 2–3 calls, ~25 s.

## 11. Latency and cost
| | `strict` today (live: 2 calls, 24 s, then stopped) | `always` |
|---|---|---|
| Calls per page; prompt eval | 1 per chunk + pick + recheck + G5 (≤ 25 follow-ups); ~3k tokens per call | 1 per chunk (2 for 30 fields) + ≤ 1 must-answer + R2 picks only without an R0/R1 match (0–2) + corrective; ~7k prefix once (hidden by `warm`), then the suffix only |
| Output, 30 fields | ~35 tokens/field | ~45 tokens/field ≈ 1.3k tokens ≈ 20 s at ~60 tok/s (Qwen3 14B, RTX 5080) |
| Page | — | **~22–30 s**; a Greenhouse attempt ≤ 2 min, inside `attempt_timeout_s` 420 |

Cache: a retry of the same job with an unchanged profile replays every decision; any profile/`extra` edit invalidates that job's rows (needed so Keep/Change takes effect).

## 12. Q-119 and Q-120
- **Q-119 merges first (precondition):** the hidden react-select helper inputs (`input[required][tabindex=-1][aria-hidden=true]` in `.select__container`) are skipped and the real combobox is marked required; otherwise every phantom would be "answered". A1's no-label rule is the backstop. Entry detection for the Greenhouse education panel is **not** a precondition (§4.4).
- **Q-120:** no design change. `model_unavailable` (incl. "no usable answers") pauses and returns the item; please add `document_missing` to AQ §4.1's per-role row. The briefing is rebuilt per item (pure, cheap); its cached prefix survives between items while the model stays loaded.

## 13. Test plan (tester; fakes only, never a real apply job)
**New oracles** (`tests/test_always_*.py`; fixture `tests/fixtures/greenhouse_live_anon.html` = the Q-119 saved page anonymised: employer "Example Co", no personal data, deny-list scanned):
1. Live form: `fill_page` under `always` with a scripted fake model → no required field unknown or empty; `unknown_required == ()`. 2. Declarations → No: PEP, relatives, a compound ("criminal record or bankruptcy"); a negated wording ("I confirm I am not…") → Yes; basis `default:no_declaration`; X1 gives the same with a model returning nothing usable. 3. Education with no entry group: School/Degree/Discipline and the four date parts fill from `education[0]`.
4. A visa question about another country → No (`default:work_rights`); sponsorship elsewhere follows the profile's `default` row (two fixture profiles).
5. Typeahead ladder: one pin per rung R0–R4; a remote list that never shows options → `validation_error`. 6. A required number with no basis → X8, `assumed`, source `last_resort:X8`.
7. H1: registered account and app passwords, the same strings planted in `extra`: no prompt of any call contains them; `PromptRefused` → `error` "prompt check", nothing typed. 8. H2: a remote backend → effective `strict` + the log line.
9. Model down (BackendError) and a model returning garbage for every field → `model_unavailable`, queue pause; 6 required last resorts on one page → the same. 10. Optional free text with nothing to say stays empty; an optional field the briefing covers is filled.
11. Briefing: same bytes for the same inputs; every profile group except `documents`/`version`/`backup_email`; the hash changes on an `extra` edit; SYSTEM → BRIEFING → JOB identical across main, must-answer and pick calls.
12. Assumptions: an assumed row makes an `assumed` question; Keep writes `extra`; the next attempt answers it by P3 without an assumption. 13. Site-restored value (fixture JS sets a value after load): kept when it matches, overwritten otherwise; a reverted value is re-filled once.
**Existing pins:** `ResolveContext` and `ApplyConfig` default to `strict`, and `tests/apply_flow_support.py` replaces the whole `apply:` block (line 113), so guard, lock, declarations, pagefill, apply_flow and Edge e2e pins keep their meaning **with no edit**. Check only pins that compare the shipped `config/config.yaml` with defaults: `test_q114_caps.py`, `test_settings.py`, `test_web_apply_settings.py`, `test_web.py`. Gate each always-lane merge on `-k always`, `-k apply_flow`, `-k apply_e2e` run separately (the Edge-skip trap).

## 14. Build plan (lanes with disjoint files)
| WP | Lane | Files | Inputs | Verify | Done when |
|---|---|---|---|---|---|
| WP-0 (≤ 30 min) | architect | `apply/contracts.py` | review | `python tests/run_tests.py -k apply_contracts` | §7.1 merged |
| WP-T0 (½ day) | tester | `tests/test_always_*.py`, fixture | WP-0 | new files collect; strict suite green | oracles 1–13 written, red |
| WP-B1 (1 day) | B | `apply/briefing.py` (new) | WP-0 | `-k always_briefing` | §3; oracle 11 |
| WP-B2 (1 day) | B | `apply/always.py` (new) | B1 | `-k always_fill` | §4.2–§4.5, §5; oracles 2, 5, 6, 10 |
| WP-K1 (½ day) | K | `tailor/compose.py`, `tailor_flow.py` | WP-0 | `-k compose` | §4.6 prune + neutral text |
| WP-H1 (½ day) | H | `backends.py` | WP-0 | `-k backends`, `-k ollama` | H1 choke point, `warm(prefix=)` |
| WP-C1 (1 day) | C | `apply/pagefill.py` (branch, A1 settle, A7 verification read), `apply/facts.py` (blank-slot binding), `apply/widgets.py` (query ladder) | B2, **Q-119 merged** | `-k pagefill`, `-k always`, `-k apply_e2e` | §4.1, §4.4; oracles 1, 3, 13 |
| WP-F1 (1 day) | F | `apply_flow.py`, `apply/questions.py`, `config.py`, `config/config.yaml` | C1, H1, K1, **Q-120 E2 merged** | `-k apply_flow`, `-k apply_e2e`, `-k always_flow` separately | §6, §7.2, §9; oracles 4, 7–9, 12 |
| WP-S1 (½ day) | F, after F1 | `store.py` | **Q-120 E1 merged** | `-k store`, `-k questions_store` | §7.3 |
| WP-W1 (½ day) | W | `web/routers/questions.py`, `web/routers/apply.py` (after Q-111) | S1 | `-k web_questions`, `-k web_apply`, `-k layering` | §6.3, §7.2 API |
| WP-U1 (1 day) | U | `web/src/components/QuestionCard.vue`, the Questions group, the Applications pill text, the Settings row | W1; Q-118 and Q-120 U lanes merged | `cd web; npx vitest run` | §6–§7 copy |

**Merge order:** Q-119 → WP-0 → B1, K1, H1 (parallel) → B2 → C1 → (Q-120 E1/E2 merged) → F1 → S1 → W1 → U1, tester pins per lane → one bundle build in the main checkout after messaging the live sessions. B, K, H, C touch no Q-119/Q-120 file; F1/S1 wait for Q-120's `apply_flow.py`/`store.py`; nothing here edits `page.py` or `guards.py` (guards stays strict-only).

## 15. Risks and open questions
| Risk | Mitigation |
|---|---|
| Wrong answers sent on real applications | D1–D10 code-built from the profile; facts computed by code (§3.3); hard checks H7/G12/G13; assumed rows listed after every attempt with Keep/Change; the owner's corrections win (P3); the M20 gate (5 dry runs read row by row) runs under `always` before auto |
| A confident wrong derivation (cites a fact, writes another value) | audit flag + assumed; pin; revisit: write the fact's coerced value if the gate shows it |
| Over-eager optional fills | rule 5 + `none`; optional free text never gets X7, optional choices never R4 |
| Latency; a misbehaving model | prefix reuse + `warm(prefix)`; no G5/recheck calls; must-answer only for gaps; cache on retries; `last_resort_max` turns a page of last resorts into a system failure (queue pause) |
| Prompts carry everything | local only (H2); secrets refused at the backend (H1); log redaction unchanged |

**Open (none blocking; my assumptions, owner may redirect):** (a) code default `strict`, shipped config `always`; (b) a failed "Add another" is a note, not a stop, under `always`; (c) a willingness the profile doesn't cover → Yes, assumed; (d) a required "other" FILE gets the resume, a required transcript ends `document_missing`; (e) `max_entries` education 2, experience 3.

READY TO BUILD: after review
