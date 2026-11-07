# Q-74 / D-105: the local model may read private profile fields

Fast track (`instructions/05_workflow.md` §3.2). ADR: `adr/0008-model-sees-sensitive.md`. Amends `apply_design.md` §5.3 and, when it merges, `llm_fill_design.md` §6.5.

Owner, 2026-11-07: "the information can be sent to ai, it is not of concern".

## 1. Rule

- New config key **`apply.model_sees_sensitive: bool`** (code default `false`; `config/config.yaml` sets **`true`** for the owner).
- **Effective value** = the key is true **and** the backend is local. Only the effective value counts anywhere. Computed once per attempt in `apply_flow`, and once per GET in the web routers.
- **Local** = `backends.is_local(backend)`: the backend is an `OllamaBackend` and the hostname of its `url` (after the `JOBSCRAPER_OLLAMA_URL` override, which `build` already applies) is in `LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}`. A Docker service name (`http://ollama:11434`), a LAN IP or any other host counts as remote, and so does `OffBackend`. Remote means today's rule.
- **What widens:** what a model prompt may *read*. With the effective value on, S values (§5.3 S paths) may be in the tier-5 prompt and the tier-5 grounding corpus, and (after Q-35 merges) in the llm_fill FACTS catalogue and the unredacted user prompt.
- **What does not change:**
  - Never logged: `redaction_values`, the job log scrubber, prompt hashes only, `debug_dump` still redacted.
  - Who decides an answer: tier 1 `SENSITIVE_CANONICALS`, tier-2 sensitive no-fit stops (ADR-0003), tier-4 declaration locks (D-87..D-91), EEO/`us_self_id` answers made by code, LF locks L1–L7, guard G7.
  - Question naming: a sensitive question still never goes to the model. Its label is employer text, the slug works, and sending it would only add test surface.
  - `Answer.sensitive` / `CapturedQuestion.sensitive` / `Fact.private` keep their meaning ("S data": shown first in the audit, tagged Private, kept out of logs).
- **Degradation:** key on + remote backend → effective off. The attempt log gets one line, `model_sees_sensitive ignored: model backend is not on this computer` (no URL, no values), and `doctor` shows it (§5 step 8). No reason code: nothing fails.

## 2. Contract (done, `src/jobscraper/apply/contracts.py`)

`ResolveContext.model_sees_sensitive: bool = False` (additive, last field). The field docs of `Answer.sensitive`, `CapturedQuestion.sensitive` and `Fact.private` now mention D-105. No other contract changes.

## 3. Map of every sensitivity filter

| Place | What it does today | D-105 |
|---|---|---|
| `applicant.SENSITIVE_PATHS / SENSITIVE_PREFIXES / is_sensitive` | defines S | unchanged |
| `applicant.LLM_ALLOW`, `llm_extract(profile)` | allow-list for prompts | **gains `*, sensitive=False`**; True adds `LLM_ALLOW_SENSITIVE = ("identity.date_of_birth", "identity.gender", "singapore_status", "us_self_id", "declarations", "contact")`. `extra` is never included (tier 3 reads it by code) |
| `applicant.grounding_text` | non-sensitive corpus | **gains `*, sensitive=False`**, passed to `llm_extract` |
| `applicant.redaction_values` | every profile string → log scrub | unchanged |
| new `applicant.sensitive_strings(profile)` | — | string leaves (≥ 3 chars, dates as ISO) of S paths, for step 4 |
| `resolve.user_prompt` | `llm_extract(profile)` | `llm_extract(profile, sensitive=ctx.model_sees_sensitive)` |
| `resolve.corpus_text` | `grounding_text(profile)` | same flag (the corpus = what the model saw) |
| `resolve._tier5` result | `sensitive=False` | `sensitive=True` when the flag is on and the value contains a `sensitive_strings` item (case-insensitive, whole word) |
| `resolve._tier1` `SENSITIVE_CANONICALS`, `_tier2_one` sensitive stop, `t2.sensitive` gate before tier 5, `_tier4` attestation gate | fail-closed routing | **unchanged** |
| `apply/declarations.py` (`sensitive=True` locks) | code-decided | unchanged |
| `apply/questions.py` capture `sensitive=` (l.192), `ask_model` / `assign_key` refusal, `naming_existing` | Private tag; no naming | unchanged |
| `apply_flow.audit_row` / `_prefilled` `sensitive` | audit order | unchanged |
| `contracts.ALWAYS_OURS`, `keep_decision` | prefill (resume, email) | unrelated, unchanged |
| `apply_flow.resolve_ctx` | builds ctx | **sets the flag** (`cfg.apply.model_sees_sensitive and backends.is_local(self.backend)`), and logs the §1 line when the key is on but the value is not |
| `web/routers/applicant.py sensitive_paths` | which fields are tagged | unchanged; payload **gains `model_sees_private: bool`** |
| `web/routers/questions.py` group `sensitive` | tag | unchanged; payload **gains `model_sees_private`** |
| `cli.py` apply audit print (l.1120) | the owner's own view | unchanged |
| `config.LlmFillConfig` docstring "prompts never hold S values" | doc | reword: "…unless D-105 is in effect" |
| `config/applicant.example.yaml` header "S = sensitive: never sent to the AI model" | doc | "S = sensitive: never written to logs; the AI reads it only when it runs on this computer and `apply.model_sees_sensitive` is on" |

## 4. Rule for the paused llm_fill branch (`int/Q-35-M`) when it merges

llm_fill must read `rctx.model_sees_sensitive`, and only that, to decide what the prompt shows. `Fact.private` keeps marking S facts and keeps driving G2d, G7, `facts_corpus` (G3 grounds resume/job values against non-private facts only) and audit `sensitive`. With the flag on, `facts.build` fills `Fact.value` for private facts too, and `facts_text` prints `ref | title | private: <value>` instead of `private, set`. The model still cites the ref with value "" and the program writes the value (SYSTEM text unchanged). `llm_fill.redact` is applied to the user prompt with `s_values` when the flag is off and with `[]` when it is on. The §6.5 `current` withholding is lifted for site-origin values when the flag is on; values JobScraper typed are never shown back. `debug_dump` always writes the prompt redacted with the full `s_values`. `facts_used_hash` and `prompt_hashes` don't change. With the flag off, every llm_fill pin passes unchanged. The merge adds two pins (flag on: a private value is in the prompt; flag on: the dump has no S value).

## 5. UI copy (`design:ux-copy`)

The badge follows the **effective** value from the payload, never the config key.

| State | Badge | Full sentence (title / screen reader) |
|---|---|---|
| off (today) | `Private: never sent to the AI` | unchanged |
| on | **`Private: local AI only`** | `Private. Only the AI on this computer reads it, and it's never written to logs.` |
| header, mostly private | `Private: local AI only, except City and Country` | same sentence |

Why this copy: the badge exists to say where a value goes. That still matters, because the owner chose a local-only exposure and a remote backend turns it back off. Dropping the badge would hide that the fields are still treated specially (never logged, answered by rules). "Stays on this computer" was rejected because it is false: employers receive these values when their form asks. "Local AI only" is short enough for the header variant and matches the term "AI" already used in the UI. Store the strings in one module, `web/src/privacy.js` (`privateBadge(on)`, `privateSentence(on)`), used by `ApplicationDetails.vue`, `QuestionCard.vue` and `QuestionsInbox.vue`. The "•••" mask under "Other keys in your file" stays: it is about the screen, not the AI.

## 6. Build steps (one lane, `eng/Q-74-model-sees-sensitive`)

1. `backends.py`: `LOCAL_HOSTS`, `is_local(backend) -> bool` (urllib.parse; no network). Verify: `python tests/run_tests.py -k test_backends`.
2. `config.py`: `ApplyConfig.model_sees_sensitive: bool = False`. `config/config.yaml`: `apply.model_sees_sensitive: true` with a one-line comment. Reword the `LlmFillConfig` docstring. Verify: `-k test_config`.
3. `applicant.py`: `LLM_ALLOW_SENSITIVE`, the `sensitive=` keyword on `llm_extract` / `grounding_text`, `sensitive_strings`. Update the `config/applicant.example.yaml` header comment. Verify: `-k test_applicant`.
4. `apply/resolve.py`: pass the flag in `user_prompt` / `corpus_text`; set tier-5 `sensitive` as in §3. Touch no routing. Verify: `-k test_resolve`.
5. `apply_flow.py`: set the flag in `resolve_ctx`; log the ignored line. Verify: `-k test_apply_flow`.
6. `web/routers/applicant.py`, `web/routers/questions.py`: `model_sees_private` (`cfg.apply.model_sees_sensitive and backends.is_local(backends.build(cfg.budget))`; `build` makes no network call). Verify: `-k test_web`.
7. `web/src/privacy.js` plus the three components (§5). Verify: `cd web; npx vitest run`.
8. `cli.py doctor`: one line, `Private fields: the local AI may read them` / `Private fields: kept from the AI (model backend is not on this computer)` / `Private fields: kept from the AI`. Verify: `-k test_cli`.
9. Full suite: `python tests/run_tests.py`. Then commit.

**Files:** `src/jobscraper/{backends,config,applicant,apply_flow,cli}.py`, `src/jobscraper/apply/resolve.py`, `src/jobscraper/web/routers/{applicant,questions}.py`, `config/config.yaml`, `config/applicant.example.yaml`, `web/src/privacy.js`, `web/src/components/{ApplicationDetails,QuestionCard,QuestionsInbox}.vue`, tests. **Overlap:** `QuestionCard.vue` is also changed on `int/Q-35-M` (merge note only: different lines). `ApplicationDetails.vue` is not in Q-75 lane I.

**Tests (tester pins):**
- T1 `is_local`: true for `http://127.0.0.1:11434`, `http://localhost:11434`, `http://[::1]:11434`; false for `http://ollama:11434`, `http://192.168.1.5:11434` and `OffBackend`; the env override wins.
- T2 `llm_extract` / `grounding_text`: the default output has no S value (regression pin); `sensitive=True` includes `identity.date_of_birth`, `declarations.*` and `contact.phone_number`; `extra` is never included.
- T3 flag on + fake local backend: the tier-5 user prompt contains an S value. Flag off: it doesn't.
- T4 flag on: a sensitive no-fit (tier 2), a tier-4 declaration, a tier-1 SENSITIVE_CANONICAL stop and an attestation all make **zero** model calls (the fake backend records the calls).
- T5 flag on: a tier-5 answer whose value contains an S value has `sensitive=True`, and it grounds when the value is only in the S facts.
- T6 apply_flow: key on + local → `rctx.model_sees_sensitive`; key on + remote → False plus the one log line; the job log of a flag-on dry run contains no S value.
- T7 naming: `ask_model` returns None for a sensitive question with the flag on.
- T8 web: both GET payloads carry `model_sees_private`. Vitest: the badge text for each flag value in the three components; the header variant.

READY TO BUILD: yes
