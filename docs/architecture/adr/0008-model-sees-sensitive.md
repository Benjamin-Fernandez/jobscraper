# ADR-0008: The local model may read sensitive profile fields (D-105)

**Status:** Accepted (owner decision 2026-11-07). Amended 2026-11-07 after review `docs/reviews/Q-74.md` (F1, F3/D-107, F5). **Amends:** apply_design §5.3, llm_fill_design §6.5 (H4). **Design:** `q74_model_sees_sensitive.md`.

## Context

Since M20, sensitive (S) profile values (date of birth, gender, residency, NS, race, religion, contact details, `us_self_id.*`, `declarations.*`) never reach a model prompt. They stay out through `applicant.llm_extract`'s allow-list, and llm_fill shows private facts only as "set/empty" and redacts the prompt. The cost is that some questions the model could settle from these facts end up as captured questions. The model runs locally (Ollama on 127.0.0.1). The owner: "the information can be sent to ai, it is not of concern".

## Decision

- A config switch, `apply.model_sees_sensitive` (owner: true), lets S values into prompts, but only when the backend is local. `backends.is_local` means Ollama on localhost, 127.0.0.1 or ::1, with a model tag that does not end in `-cloud` or `:cloud` (D-107: Ollama forwards those to ollama.com). `backends.is_local_config(budget)` applies the same rule to the config without building a backend.
- A remote backend keeps today's rule, whatever the switch says. One boolean on `ResolveContext` carries the effective value.
- **Reading, not deciding (Option C held).** The model reads every S value in its prompt, but the tier-5 grounding corpus gains the contact details only (`grounding_text(..., protected=False)`). A tier-5 value, option or evidence that contains a protected value (`applicant.protected_strings`: every S value except contact details, plus the year of a date) becomes UNGROUNDED with `sensitive=True`, and the question is captured as Private. Contact details may fill. With the flag on, tier-5 failure notes are scrubbed (`applicant.scrub`), and token violations keep only their kind. llm_fill follows the same rule: `facts_corpus` stays non-private, and G3 and the text guard reject protected values.
- Unchanged:
  - S values are never logged, and debug dumps stay redacted.
  - Code-decided answers stay code-decided (tier-1 sensitive canonicals, tier-2 sensitive stops, tier-4 declaration locks, EEO, LF locks, G7).
  - Sensitive questions are never sent for naming.

## Options considered

| Option | Verdict |
|---|---|
| A. Drop the S rule entirely | Rejected: a later remote backend (or a Docker service URL) would silently send S values off the machine. |
| B. Switch gated on a local backend (chosen) | Matches the owner's intent ("it's my machine") and fails safe on any other host. |
| C. Also let the model answer sensitive questions | Rejected: those answers are deterministic by design (ADR-0003 fail-closed, D-87). The owner asked about reading, not deciding. As first built, putting S values in the tier-5 corpus let tier 5 fill S answers the rules missed (review F1), so the corpus was cut back to contact details. |

## Consequences

- Better tier-5 and llm_fill answers on questions that need context like residency or contact details. A tier-5 answer that would repeat a protected value is captured for the owner instead of filled. Once answered, tier 3 decides it by code.
- The UI badge follows the effective value ("Private: local AI only").
- Prompt hashes change when the switch flips. The llm_fill fill-cache key (`job_id, field_sig, prompt_version, model, inputs_hash`) does not contain them, so the effective flag must be folded into `inputs_hash`. Only then do cached fills (llm_fill §13.3) re-run once after a flip (design §4 item 9).
- Exposing `singapore_status.nationality` (not S) to the local model with the whole block is accepted under D-105.
- The S definition (`is_sensitive`) still matters: it drives the audit, the tags, the redaction and the locks.
- Reversal is one config line.
