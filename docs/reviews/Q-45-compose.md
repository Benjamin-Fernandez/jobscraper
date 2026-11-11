# Review: Q-45 composed texts (WP-K1/K2/K3/T7), branch `eng/Q-45-compose`

Reviewer, 2026-11-10. Diff `personal...HEAD` (head 83e8d7c). Spec: `llm_fill_design.md` §19, §8 step 7b, §13.4; build plan WP-K1/K2/K3/T7; D-179 and D-182 taken as ruled. Key areas KA-4 (tailor truthfulness) and KA-1 (auto-apply engine).

## Verdict: MERGE WITH FOLLOW-UPS

No CRITICAL and no HIGH finding. Everything that must fail closed does: a failing draft is never filled, compose off leaves the page untouched and captures the field, a second `compose_needed` ends the attempt, transport failure ends `model_unavailable`, a FILE upload takes its path from `composed_files` only. Four MEDIUM gaps (one is a truthfulness gap inherited from the spec's own C3/C2 design) and a few LOW items follow.

## Evidence

Run in the worktree (`PYTHONPATH=src python tests/run_tests.py -k <needle>`):
- `layering` 13/13; `tailor_compose` 24/24; `llm_fill_locks` 7/7; `apply_questions_page` 4/4; `apply_flow_compose` 8/8 (tester's path fix already in the tree); `llm_fill_model` 4/4; `q74_llm` 16/16.
- `apply_e2e` 13/13 (Edge available).
- `apply_flow`: see the addendum at the end.
- Not run: vitest (the worktree has no `web/node_modules`); the full suite; any live Ollama run.
- Adversarial probes against `tailor_flow.compose` with a scripted model and the case_a master (synthetic): results under M1/M2.

## Focus-by-focus

1. **Truthfulness (KA-4).** C1-C7 are implemented as specified and run on the returned text; a failing draft returns `ok=False, text=""` and `compose_step` has no path that fills it (`compose.py:246-272`, `apply_flow.py:1383-1395`). C5 blanks private spans before C2/C3/C4/C6, so no other issue detail can carry a piece of an S value into the FIX line (`compose.py:148`, `fix_line` drops PRIVATE_VALUE details). The whole user prompt, FIX line included, goes through `redact` on every attempt (`compose.py:259`); the contact block is excluded by `resume_text`. Probes: invented lowercase tools, a mid-sentence employer, upgraded verbs (`headed`), `Dear Hiring Manager`, `[Name]`-style placeholders, a long digit run (also Arabic-Indic digits), a bare URL, `{{name}}` all rejected. Gaps in M1, M2.
2. **Safety (KA-1).**
   - Compose off (default `enabled: false`): `_compose_split` lists nothing as pending unless the flag is on or a FILE target has an owner answer (`pagefill.py:766-782`), so the outcome is a plain `unknown_required` at step 7 with nothing typed, captured with `compose_needed: off`.
   - No loop: one `fill_page` after the texts; a second `compose_needed` raises `compose loop` before any capture or Next (`apply_flow.py:1305-1308`). The corrective pass (`:1208-1209`) goes through the same `page_result`, so it also cannot loop.
   - Transport: `res.error` starting `transport` -> `MODEL_UNAVAILABLE`, staged not applied, nothing captured (`apply_flow.py:1386-1392`); the type name only, no text.
   - Deadline: checked before each target (`:1376`); see M3 for the model call itself.
   - FILE path: `_composed_path` reads `ctx.composed_files` only, never `ans.value` (the text) (`pagefill.py:439-440`); an empty path makes `Path("").read_bytes()` raise `OSError`, counted as a failed upload, not an upload.
   - Owner first: TEXTAREA through L6 before L8 (`locks.py:297-304`); FILE through `owner_compose_text` before any model call (`apply_flow.py:1381`).
3. **Privacy.** No log line carries a text (`compose.py:264,269,271`; `apply_flow.py:1398,1439` log counts, a step id and a note). Letters go to `at.dir/cover_letter*.{docx,txt}` under `data/apply/<id>/`, which `.gitignore:66` covers (checked with `git check-ignore`). The diff has only synthetic fixtures (`example.*`, "Jane Tan"); no personal data, no secret. `ApplyFailure` carries the field label only. The decision cache holds model decisions only; locked composed text is not cached.
4. **Layering.** `tests/test_layering.py` 13/13. `apply_flow` is the one place that imports both `tailor.contracts` and `apply.*`; `tailor_flow.compose` takes `redact` as a parameter. `locks.py` copies `COMPOSE_VERSION` as `COMPOSE_RULE_ID` rather than importing it.
5. **Regressions.** G3 compose rule now skips compose targets (`guards.py:614-618`), `chunks()` never sends them or FILE fields to the model (`llm_fill.py:179`), so the model never sees a composed letter as context. Other free TEXTAREAs keep the G3 rule. Behaviour change worth knowing (spec-conformant, §19.1/19.2): an optional compose-target TEXTAREA is now left blank even with compose off; before, the page model could write it. `NOT_RESUME_RE`/`COVER_RE` now include "motivation letter", which stops such a FILE being taken for the resume slot (an improvement).

## Findings

### MEDIUM

**M1. A fabricated proper noun at a sentence or paragraph start passes C3.** `compose.py:156-158` turns paragraph breaks into ". " and `validate.facts` (`validate.py:85-88`) exempts a capitalised word at a sentence start. For a tailored bullet, tailor rule 5 limits that exemption to the source's own first word; a composed text has no source, so any capitalised sentence-start word is exempt. Probe: master text + `"\n\nStripe taught me how payments scale and Datadog showed me observability."` -> only `datadog` is flagged; `Stripe` passes. Failure scenario: a letter that opens a sentence with an employer, school or tool the resume lacks (not in the alias dictionary) is accepted and typed into a real application. Mitigations that exist: compose is off by default, and D-83 has the Coordinator read the audit row by row before a real submission. Fix (follow-up, small): in `compose.check`, flag a capitalised sentence-start word that is not a token of the master, of the allowed names or of a short function/common-word list; or accept only words in a lowercase-English stoplist. This goes beyond the spec's literal C3, so the spec text should say so.

**M2. C2 is digits only; spelled-out quantities pass.** `compose.py:150-154`. Probe: `"I have five years of experience and two internships."` and `"improved throughput by thirty percent"` are accepted against a master with no such numbers. The tailor design has `NUMBER_WORDS` for this (`tailor_design.md` §7.4); the spec's C2 says "digits", so this is a spec gap, not a code defect. Likewise "I built a recommendation engine" (an invented project in plain words) cannot be caught by any deterministic check here. Recommend: reuse `NUMBER_WORDS` in C2 when M22 lands it; note in the Q-45 record that C1-C7 bound facts, not stories, and that the D-83 read is the control for the rest.

**M3. The compose model call ignores the attempt deadline.** `compose.py:237` calls `backend.complete(system, user, max_tokens, **kw)` with no `timeout`; the Ollama backend then waits up to its own 600 s per call, two calls per target (`backends.py:109,199`). `compose_step` only checks `deadline_left() > 0` before each target (`apply_flow.py:1376`), as §19.3 says. Failure scenario: a hung or swapped-out model keeps the attempt alive for up to 20 minutes past `attempt_timeout`; the attempt ends afterwards as `timed out` (step 8 `_time_left`), so it fails closed but late, and holds the browser session open. Fix: pass `timeout=max(1.0, services.deadline_left())` through `tailor_flow.compose` into `_call` (the backend already accepts `timeout`).

**M4. The `off` hint points at a setting that doesn't exist.** `QuestionCard.vue:42`: "turn on “Write cover letters” in Settings → Apply." There is no such toggle (grep of `web/src` and `src/jobscraper/web` finds none); §19.5 says it is a config edit until lane W adds one. The owner is sent to a missing control. Spec §19.6 prescribes this text, so the spec wins for merge; fix the copy (or build the toggle) together with Q-96.

### LOW

- **L1. Owner text labelled as model output.** A FILE target with an owner answer is written as the letter and staged as source `composed`, tier LLM, confidence 0.9, rule `compose:v1`, model "" (`locks.py:_compose_lock`, `apply_flow.py:1381,1396-1397`). The audit view therefore shows an owner-written letter as an LLM composition. Suggest source/tier from the owner's answer when `meta == ("", "")`.
- **L2. `setup:` errors read as a failed fact check.** `tailor_flow.compose` returns `error="setup: <Type>"` for a broken aliases file; `apply_flow.py:1393-1394` maps everything except `no master` to `failed check`, and the card then says the draft failed its fact check. Add a note value or map it to the generic hint.
- **L3. Revealed compose target.** A required compose target that appears after an answer (reveal rounds, `pagefill.py` step 10) and the corrective pass (`apply_flow.py:1208`) get no compose step: step 10 stops with `unknown`, captured as `compose_needed: off` even when composing is on (misleading hint); the corrective pass raises `compose loop`. Both fail closed; the attempt just ends with a poor reason.
- **L4. `compose_needed` regex breadth.** `_MOTIVE` (`why ... work|want|apply`) also matches e.g. "Why are you leaving your current employer to work elsewhere?"; with composing on the model would answer that question from the resume under C1-C7. Truthful but off-topic; pre-existing regex, now acted on instead of only captured. Owner reads the audit.
- **L5. Name alone is not a private value.** `Jane is keen.` (first name only, sentence start) passes C3/C5 when the S value is the full name. The model never receives the name (redacted, contact block excluded), so this is theoretical.

## Disagreements with the spec

- C3 as written (`validate.facts(text)` subset check) is weaker for composed text than the tailor's rule 5 gives bullets (M1). The code follows the spec; I recommend amending §19.4 C3.
- §19.3 checks the deadline only between targets (M3); the code follows it.
- §19.6 `off` hint names a toggle that §19.5 says doesn't exist yet (M4).

## Not checked

Vitest for `QuestionCard` (no node_modules in the worktree); a live Ollama run of the letter quality; a real Greenhouse/Workday cover-letter upload (the D-83 gate); the full suite on the integration tree (run it after the merge, per the handover).

## Addendum: `-k apply_flow`
`145/145 passed  (-k 'apply_flow')` (with Edge; includes the tester's fixed path assertion). The evidence list above says "see the addendum": this is it.
