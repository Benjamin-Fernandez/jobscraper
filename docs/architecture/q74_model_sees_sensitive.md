# Q-74 / D-105: the local model may read private profile fields

**Changelog:** 2026-11-07, amended after review `docs/reviews/Q-74.md` (fix round f716e3e, 2e5a232). F1: the tier-5 grounding corpus gets contact details only, and protected values make an answer UNGROUNDED (§1, §3). F2: notes are scrubbed (§1, §3). F3/D-107: cloud model tags are not local (§1). F5: llm_fill hooks and the fill-cache key (§4). F8: nationality exposure accepted (§3). T5 superseded (§6).

Fast track (`instructions/05_workflow.md` §3.2). ADR: `adr/0008-model-sees-sensitive.md`. Amends `apply_design.md` §5.3 and, when it merges, `llm_fill_design.md` §6.5. Decisions: D-105, D-107.

Owner, 2026-11-07: "the information can be sent to ai, it is not of concern".

## 1. Rule

- New config key **`apply.model_sees_sensitive: bool`** (code default `false`; `config/config.yaml` sets **`true`** for the owner).
- **Effective value** = the key is true **and** the backend is local. Only the effective value counts anywhere. Computed once per attempt in `apply_flow`, and once per GET in the web routers.
- **Local** = `backends.is_local(backend)`: the backend is an `OllamaBackend`, the hostname of its `url` (after the `JOBSCRAPER_OLLAMA_URL` override, which `build` already applies) is in `LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}`, **and** the model tag does not end in `-cloud` or `:cloud` (case-insensitive; **D-107**: Ollama forwards those tags to ollama.com). A Docker service name (`http://ollama:11434`), a LAN IP or any other host counts as remote, and so does `OffBackend`. Remote means today's rule. Both checks live in `backends._target_is_local(url, model)`. **`backends.is_local_config(budget)`** applies the same rule to the budget config: it resolves the URL and model as `build` does (env first, then config) without building a backend. The web routers use it (review F7).
- **What widens:** what a model prompt may *read*. With the effective value on, S values (§5.3 S paths) may be in the tier-5 prompt, and (after Q-35 merges) in the llm_fill FACTS catalogue and the unredacted user prompt. The tier-5 **grounding corpus** gains the **contact details only** (`contact.*`).
- **Reading, not deciding** (ADR-0008 Option C, review F1). Every S value except contact details is **protected**: `applicant.protected_strings(profile)` covers date of birth and its year, gender, residency/NS, race, religion, `us_self_id` and `declarations`. With the flag on, tier 5 (`_tier5`, `_tier5_text`) runs `_protected_hit` on the chosen option labels, the evidence, the number and the text. The match is whole-word and case-insensitive. A hit adds the violation `private value`, and the answer is UNGROUNDED with `sensitive=True`, so it is captured as a Private question. Once the owner answers, tier 3 decides it by code. A text answer gets its one retry with the reason `private value`, never with the value itself. Evidence that only a protected value supports gives "evidence not found". Contact details may fill, and `_shows_s_value` tags them Private.
- **Notes** (review F2). With the flag on, `_llm_failed` scrubs the note with `applicant.scrub(note, sensitive_strings + protected_strings, "[private]")`. `_note_for` cuts token violations (`number N`, `year Y`, `month M`, `word W`, `evidence not found: <quote>`, `number not found: N`) down to their kind. With the flag off, notes are unchanged.
- **What does not change:**
  - Never logged: `redaction_values`, the job log scrubber, prompt hashes only, `debug_dump` still redacted.
  - Who decides an answer: tier 1 `SENSITIVE_CANONICALS`, tier-2 sensitive no-fit stops (ADR-0003), tier-4 declaration locks (D-87..D-91), EEO/`us_self_id` answers made by code, LF locks L1–L7, guard G7.
  - Question naming: a sensitive question still never goes to the model. Its label is employer text, the slug works, and sending it would only add test surface.
  - `Answer.sensitive` / `CapturedQuestion.sensitive` / `Fact.private` keep their meaning ("S data": shown first in the audit, tagged Private, kept out of logs).
- **Degradation:** key on + remote backend (or a cloud model tag) → effective off. The attempt log gets one line, `model_sees_sensitive ignored: model backend is not on this computer` (no URL, no values), and `doctor` shows it (§6 step 8). No reason code: nothing fails.

## 2. Contract (done, `src/jobscraper/apply/contracts.py`)

`ResolveContext.model_sees_sensitive: bool = False` (additive, last field). The field docs of `Answer.sensitive`, `CapturedQuestion.sensitive` and `Fact.private` now mention D-105. No other contract changes. The F1/F2/F3 fixes need none either.

## 3. Map of every sensitivity filter

| Place | What it does today | D-105 |
|---|---|---|
| `applicant.SENSITIVE_PATHS / SENSITIVE_PREFIXES / is_sensitive` | defines S | unchanged |
| `applicant.LLM_ALLOW`, `llm_extract(profile)` | allow-list for prompts | **gains `*, sensitive=False, protected=True`**. `sensitive=True` adds `LLM_ALLOW_SENSITIVE = ("identity.date_of_birth", "identity.gender", "singapore_status", "us_self_id", "declarations", "contact")`. `protected=False` keeps only the `contact` part of that addition. `extra` is never included (tier 3 reads it by code). The whole `singapore_status` block also brings in the non-S `nationality`; showing it to the local model is accepted under D-105 (review F8) |
| `applicant.grounding_text` | non-sensitive corpus | **gains `*, sensitive=False, protected=True`**, passed to `llm_extract` |
| `applicant.redaction_values` | every profile string → log scrub | unchanged |
| new `applicant.sensitive_strings(profile)` | — | string leaves (≥ 3 chars, dates as ISO) of S paths, for tagging |
| new `applicant.protected_strings(profile)` | — | `sensitive_strings` without `contact.*`; a date also yields its year. For matching only, never logged (F1) |
| `applicant.scrub(line, values, mark)` | was the `apply_flow.redact` body | moved here; `apply_flow.redact` delegates to it; also scrubs tier-5 notes (F2) |
| `backends.is_local`, `is_local_config`, `_target_is_local` | — | §1 local rule, including the cloud-tag check (D-107) |
| `resolve.user_prompt` | `llm_extract(profile)` | `llm_extract(profile, sensitive=ctx.model_sees_sensitive)` (every S value: the model reads) |
| `resolve.corpus_text` | `grounding_text(profile)` | `grounding_text(profile, sensitive=ctx.model_sees_sensitive, protected=False)`: with the flag on, contact details only. **Supersedes** "same flag (the corpus = what the model saw)" (F1) |
| `resolve._tier5` / `_tier5_text` result | `sensitive=False` | flag on: `sensitive=True` when the value contains a `sensitive_strings` item (whole word, case-insensitive); a `_protected_hit` → violation `private value`, UNGROUNDED, `sensitive=True` (§1) |
| `resolve._llm_failed`, `_note_for` | note may quote the reply | flag on: scrubbed with `[private]`; token violations reduced to their kind (F2) |
| `resolve._tier1` `SENSITIVE_CANONICALS`, `_tier2_one` sensitive stop, `t2.sensitive` gate before tier 5, `_tier4` attestation gate | fail-closed routing | **unchanged** |
| `apply/declarations.py` (`sensitive=True` locks) | code-decided | unchanged |
| `apply/questions.py` capture `sensitive=` (l.192), `ask_model` / `assign_key` refusal, `naming_existing` | Private tag; no naming | unchanged |
| `apply_flow.audit_row` / `_prefilled` `sensitive` | audit order | unchanged |
| `contracts.ALWAYS_OURS`, `keep_decision` | prefill (resume, email) | unrelated, unchanged |
| `apply_flow.resolve_ctx` | builds ctx | **sets the flag** (`cfg.apply.model_sees_sensitive and backends.is_local(self.backend)`), and logs the §1 line when the key is on but the value is not |
| `web/routers/applicant.py sensitive_paths` | which fields are tagged | unchanged; payload **gains `model_sees_private: bool`** (`backends.is_local_config`, F7) |
| `web/routers/questions.py` group `sensitive` | tag | unchanged; payload **gains `model_sees_private`** |
| `cli.py` apply audit print (l.1120) | the owner's own view | unchanged |
| `config.LlmFillConfig` docstring "prompts never hold S values" | doc | reword: "…unless D-105 is in effect" |
| `config/applicant.example.yaml` header (line 3) "S = sensitive: never sent to the AI model" | doc | `# S = sensitive: never written to logs. The AI reads S values only when apply.model_sees_sensitive is on and the model runs on this computer; except contact details, they never ground an AI-written answer (those questions wait for you).` |

## 4. Rule for the paused llm_fill branch (`int/Q-35-M`) when it merges

llm_fill must read `rctx.model_sees_sensitive`, and only that, to decide what the prompt shows. `Fact.private` keeps marking S facts and keeps driving G2d, G7, `facts_corpus` (G3 grounds resume/job values against non-private facts only; Option C, the same rule as the tier-5 corpus) and audit `sensitive`. With the flag on, `facts.build` fills `Fact.value` for private facts too, and `facts_text` prints `ref | title | private: <value>` instead of `private, set`. The model still cites the ref with value "" and the program writes the value (SYSTEM text unchanged). With the flag off, every llm_fill pin passes unchanged.

Hook points (line numbers ≈, `int/Q-35-M` ae45cc7; review F5):

1. `facts.fact_catalogue` (≈351-376): fill the value for private facts when the flag is on.
2. `facts.facts_text` (≈385-393): `private: <value>` line when on.
3. `pagefill.py` ≈134 `run.sv`: keep the full `s_values` for G7, `pick_refused` and debug. Pass `s_values=[]` to the `llm_fill.user_prompt` / `schema` redaction when on.
4. `llm_fill.field_view` ≈268 `_withhold`: when on, lifted for site-origin values. Values JobScraper typed are never shown back.
5. `llm_fill.recheck_entry` (≈612-625): same decision as the user prompt (redact with `[]` when on, with `s_values` when off).
6. `llm_fill.pick_option` (≈569-576): **keep** the redaction of the prompt and `fmt` with the full `s_values`, whatever the flag. It picks among site options, so showing S values there would let the model decide an S choice (Option C), and it gains nothing. `pick_refused` unchanged.
7. `guards.py` ≈421 (G3 quote invariant): the comment "the model saw the redacted resume, so a quote can't carry an S value" no longer holds when the flag is on. New rule: G3 grounds quotes only against the resume, the job and the non-private `facts_corpus`. A quote holding an `applicant.protected_strings` item gives unknown, whatever the flag. Update the comment.
8. `guards.py` ≈691 (text guard): besides `[private]` echoes, with the flag on a model-written text value that holds a protected string not in the resume gives unknown. This is the llm_fill side of F1.
9. **Fill cache.** The key `(job_id, field_sig, prompt_version, model, inputs_hash)` (`store.py` ≈315, `pagefill.py` ≈649) must change with the flag. Today `inputs_hash` (`pagefill.py` ≈138) hashes the redacted resume, so a flip would reuse stale fills. Fold the effective flag into `inputs_hash`, so cached fills re-run once after a flip. `facts_used_hash` and `prompt_hashes` change with the prompt text but are not cache keys. **Supersedes** "`facts_used_hash` and `prompt_hashes` don't change".
10. `debug_dump`: no writer yet; when added, it always writes the prompt redacted with the full `s_values`.

The merge adds four pins: (a) flag on, a private value is in the prompt; (b) flag on, the dump has no S value; (c) flag on, a text value with a protected value not in the resume gives unknown; (d) flipping the flag changes `inputs_hash`.

## 5. UI copy (`design:ux-copy`)

The badge follows the **effective** value from the payload, never the config key.

| State | Badge | Full sentence (title / screen reader) |
|---|---|---|
| off (today) | `Private: never sent to the AI` | unchanged |
| on | **`Private: local AI only`** | `Private. Only the AI on this computer reads it, and it's never written to logs.` |
| header, mostly private | `Private: local AI only, except City and Country` | same sentence |

Why this copy: the badge exists to say where a value goes. That still matters, because the owner chose a local-only exposure and a remote backend turns it back off. Dropping the badge would hide that the fields are still treated specially (never logged, answered by rules). "Stays on this computer" was rejected because it is false: employers receive these values when their form asks. "Local AI only" is short enough for the header variant and matches the term "AI" already used in the UI. Store the strings in one module, `web/src/privacy.js` (`privateBadge(on)`, `privateSentence(on)`), used by `ApplicationDetails.vue`, `QuestionCard.vue` and `QuestionsInbox.vue`. The "•••" mask under "Other keys in your file" stays: it is about the screen, not the AI.

## 6. Build steps (one lane, `eng/Q-74-model-sees-sensitive`)

1. `backends.py`: `LOCAL_HOSTS`, `is_local(backend) -> bool` (urllib.parse; no network). Amended: cloud tags (D-107) and `is_local_config(budget)`. Verify: `python tests/run_tests.py -k test_backends`.
2. `config.py`: `ApplyConfig.model_sees_sensitive: bool = False`. `config/config.yaml`: `apply.model_sees_sensitive: true` with a one-line comment. Reword the `LlmFillConfig` docstring. Verify: `-k test_config`.
3. `applicant.py`: `LLM_ALLOW_SENSITIVE`, the `sensitive=` / `protected=` keywords on `llm_extract` / `grounding_text`, `sensitive_strings`, `protected_strings`, `scrub`. Update the `config/applicant.example.yaml` header comment (§3 last row; outside the engineer scope, the Coordinator applies it). Verify: `-k test_applicant`.
4. `apply/resolve.py`: pass the flag in `user_prompt` / `corpus_text` (`protected=False` there); tier-5 `sensitive`, `_protected_hit` and note scrubbing as in §1/§3. Touch no routing. Verify: `-k test_resolve`.
5. `apply_flow.py`: set the flag in `resolve_ctx`; log the ignored line. Verify: `-k test_apply_flow`.
6. `web/routers/applicant.py`, `web/routers/questions.py`: `model_sees_private` (`cfg.apply.model_sees_sensitive and backends.is_local_config(cfg.budget)`; amended F7: no backend built per GET). Verify: `-k test_web`.
7. `web/src/privacy.js` plus the three components (§5). Verify: `cd web; npx vitest run`.
8. `cli.py doctor`: one line, `Private fields: the local AI may read them` / `Private fields: kept from the AI (model backend is not on this computer)` / `Private fields: kept from the AI`. Verify: `-k test_cli`.
9. Full suite: `python tests/run_tests.py`. Then commit.

**Files:** `src/jobscraper/{backends,config,applicant,apply_flow,cli}.py`, `src/jobscraper/apply/resolve.py`, `src/jobscraper/web/routers/{applicant,questions}.py`, `config/config.yaml`, `config/applicant.example.yaml`, `web/src/privacy.js`, `web/src/components/{ApplicationDetails,QuestionCard,QuestionsInbox}.vue`, tests. **Overlap:** `QuestionCard.vue` is also changed on `int/Q-35-M` (merge note only: different lines). `ApplicationDetails.vue` is not in Q-75 lane I.

**Tests (tester pins):**
- T1 `is_local`: true for `http://127.0.0.1:11434`, `http://localhost:11434`, `http://[::1]:11434`; false for `http://ollama:11434`, `http://192.168.1.5:11434` and `OffBackend`; the env override wins. Amended (D-107): false for a local URL with the model `x:cloud`, `x-cloud`, `X:Cloud`; true for `cloudy:7b`; `is_local_config` follows the same rule.
- T2 `llm_extract` / `grounding_text`: the default output has no S value (regression pin); `sensitive=True` includes `identity.date_of_birth`, `declarations.*` and `contact.phone_number`; `sensitive=True, protected=False` has contact details and no protected value; `extra` is never included.
- T3 flag on + fake local backend: the tier-5 user prompt contains an S value. Flag off: it doesn't.
- T4 flag on: a sensitive no-fit (tier 2), a tier-4 declaration, a tier-1 SENSITIVE_CANONICAL stop and an attestation all make **zero** model calls (the fake backend records the calls).
- T5 **superseded** (review F1). It said: "a tier-5 answer whose value contains an S value has `sensitive=True`, and it grounds when the value is only in the S facts". Replacement: with the flag on, a tier-5 choice or text answer whose value, option label or evidence holds a protected value is UNGROUNDED with `sensitive=True`, and its note holds no S fragment. A text answer gets one retry with the reason `private value`. A resume-grounded answer still fills with `sensitive=False`. A contact value fills with `sensitive=True`. Pins F1a–F1d, F2a–F2b and F3 are in `comms/outbox/software-engineer.md` (Q-74 fix round).
- T6 apply_flow: key on + local → `rctx.model_sees_sensitive`; key on + remote → False plus the one log line; the job log of a flag-on dry run contains no S value.
- T7 naming: `ask_model` returns None for a sensitive question with the flag on.
- T8 web: both GET payloads carry `model_sees_private`. Vitest: the badge text for each flag value in the three components; the header variant.

READY TO BUILD: yes

## D-201 (2026-11-11): the whole profile is readable

Owner, 2026-11-11: "the AI filling in the auto-apply information can access all inputted information about the user; it is not sensitive in any way". Fast-track delta on D-105; KA-2, so an independent review before merge. No contract change, no ADR (ADR-0008's decision holds; this widens one list it already names).

**(a) Paths.** `applicant.LLM_ALLOW_SENSITIVE` becomes `("identity", "pay", "consents", "singapore_status", "us_self_id", "declarations", "contact")`: the two `identity.*` leaves give way to the whole `identity` block, plus `pay` and `consents`. That adds the leaves still hidden under D-105: `identity.legal_first_name`, `legal_last_name`, `preferred_name`, `name_order`, `pronouns`, `pay.current_salary`, `pay.months_per_year`, `consents.privacy_consent`, `data_retention_consent`, `talent_pool_opt_in`, `certify_true`. Never `documents` (local file paths; the resume upload is lock L1) and never `version` (not about the applicant). `LLM_ALLOW_CONTACT` is unchanged, so the tier-5 grounding corpus is unchanged. Both users of the list widen with no edit of their own: tier 5 (`resolve.user_prompt` → `llm_extract(sensitive=True)`) and llm_fill FACTS (`facts._model_may_read`). Note: in FACTS the three `facts.NAME_PATHS` are already non-private and shown; for them only tier 5 widens.

**(b) `extra` and the standing `account_email`.** With the effective switch on, `facts.fact_catalogue` gives a sensitive `extra` answer and the private standing fact `standing:account_email` their value, so `facts_text(show_private=True)` prints `private: <value>`. `Fact.private` stays `True`, so G2d (never a restated private fact), G7 (a private `extra` or standing fact on an S-labelled question gives unknown), `pick_refused`, the audit `sensitive` order and redaction keep their meaning. The model still cites the ref with value "" and the program writes the value (SYSTEM text unchanged). `llm_extract` and `grounding_text` still never include `extra` (tier 3 reads it by code).

**(c) Unchanged.**
- ADR-0008 Option C: the model reads, code decides. Tier-1 `SENSITIVE_CANONICALS`, tier-2 sensitive stops, tier-4 declaration and attestation locks, EEO by code, LF locks L1–L7 (L5 keeps `consents.privacy_consent` / `certify_true` lock-decided), G7, `pick_option` redaction with the full `facts.s_values` (which still lists `account_email`), the `_withhold` rule for values JobScraper typed.
- Grounding: `protected_strings`, the tier-5 corpus (contact only), the llm_fill `facts_corpus` (non-private facts only) and G3 / the text guard. A value the model repeats from a newly readable leaf (say the current salary) grounds only where it already did; otherwise the field ends unknown or captured. That is fail-closed.
- S values are never logged (`redaction_values`, job-log scrubber, prompt hashes only, `debug_dump` redacted). `inputs_hash` still folds the effective switch. A remote backend or cloud tag ignores the switch (D-107). `extra` values and sensitive questions are still never sent for question naming (`questions.ask_model`, `naming_existing`).

**(d) Risks, accepted.** (1) More personal data in local prompts: accepted on the owner's statement, and it stays on this computer (principle 6: the backend must be local, else the switch is off). (2) The model could write a name, salary or consent into a free-text answer: grounding and the guards are unchanged, so it cannot invent or decide one (principle 1); the value goes to the employer anyway when its form asks. (3) Stale cache: a flag-on fill cached under D-105 saw less. The `inputs_hash` marker is versioned (f) so those fills re-run once.

**(e) Opt-in.** No new switch. The existing `apply.model_sees_sensitive: true` (owner config) plus a local backend turns D-201 on. The UI line stays: Profile tab / `doctor` "Private fields: the local AI may read them", badge "Private: local AI only". Same meaning, wider set.

**(f) Code delta (engineer, one small lane).**
1. `applicant.py`: `LLM_ALLOW_SENSITIVE` as in (a). Comment above it: "D-201: every profile group except `documents` and `version`; `extra` never". `llm_extract` docstring: "adds LLM_ALLOW_SENSITIVE (D-105, widened by D-201)". `LLM_ALLOW_CONTACT` unchanged.
2. `apply/facts.py` `fact_catalogue`: the `extra` loop `value=words if (not private or reads) else ""`, and the standing loop `value="" if not is_set or (private and not reads) else _text(v)`. Docstrings of `fact_catalogue`, `_model_may_read` ("Never `extra` or a standing private fact" becomes "the `extra` and standing private facts are handled in `fact_catalogue`") and `facts_text`.
3. `apply/facts.py` `inputs_hash`: the marker `"\n\x1e\x1dprivate-visible"` becomes `"\n\x1e\x1dprivate-visible:d201"`.
4. Nothing in `guards.py`, `locks.py`, `llm_fill.py`, `pagefill.py`, `resolve.py`, contracts or the web. Verify: `python tests/run_tests.py -k q74`, `-k q79`, `-k llm_fill`, `-k guards`, `-k applicant`, then the full suite plus `-k apply_flow` and `-k apply_e2e` (Edge).

**(g) Pins (tester).** Rule: a pin that asserts a formerly hidden leaf stays hidden with the switch effective becomes a pin that it is shown, and gets a flag-off twin that it is hidden. Flag-off pins don't change.
- `tests/test_q74_llm_fill_hooks.py::test_hook_a_extra_answers_never_reach_the_prompt_even_with_the_flag_on` → flag on, a usable sensitive `extra` value is in FACTS as `private: <value>`; flag off it is not. Use an entry that `facts._extra_usable` accepts, so the pin cannot pass empty.
- `test_hook_a_show_private_without_a_value_keeps_the_set_marker` stays (an unset `identity.pronouns` still prints `private, empty`).
- `tests/test_q74_model_sees_sensitive.py::test_t2_sensitive_true_adds_every_s_block_but_never_extra` stays. Add: `llm_extract(p, sensitive=True)` holds the legal name, `pay.current_salary` and `consents`, and no `documents` or `version`; `protected=False` still gives contact only.
- New: flag on, `standing:account_email` prints its value, and `pick_option` still redacts it; G7 still gives unknown for a private `extra` fact on an S-labelled field; a flag-on/flag-off `inputs_hash` pair differs and the flag-on one differs from the D-105 marker. G3 pins: none expected to change, since `facts_corpus` is unchanged.

READY TO BUILD: yes (after the KA-2 review of this delta)
