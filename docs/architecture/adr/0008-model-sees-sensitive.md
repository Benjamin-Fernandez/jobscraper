# ADR-0008: The local model may read sensitive profile fields (D-105)

**Status:** Accepted (owner decision 2026-11-07). **Amends:** apply_design §5.3, llm_fill_design §6.5 (H4). **Design:** `q74_model_sees_sensitive.md`.

## Context

Since M20, sensitive (S) profile values (date of birth, gender, residency, NS, race, religion, contact details, `us_self_id.*`, `declarations.*`) never reach a model prompt. They stay out through `applicant.llm_extract`'s allow-list, and llm_fill shows private facts only as "set/empty" and redacts the prompt. The cost is that some questions the model could settle from these facts end up as captured questions. The model runs locally (Ollama on 127.0.0.1). The owner: "the information can be sent to ai, it is not of concern".

## Decision

- A config switch, `apply.model_sees_sensitive` (owner: true), lets S values into prompts, but only when the backend is local (`backends.is_local`: Ollama on localhost, 127.0.0.1 or ::1).
- A remote backend keeps today's rule, whatever the switch says. One boolean on `ResolveContext` carries the effective value.
- Unchanged:
  - S values are never logged, and debug dumps stay redacted.
  - Code-decided answers stay code-decided (tier-1 sensitive canonicals, tier-2 sensitive stops, tier-4 declaration locks, EEO, LF locks, G7).
  - Sensitive questions are never sent for naming.

## Options considered

| Option | Verdict |
|---|---|
| A. Drop the S rule entirely | Rejected: a later remote backend (or a Docker service URL) would silently send S values off the machine. |
| B. Switch gated on a local backend (chosen) | Matches the owner's intent ("it's my machine") and fails safe on any other host. |
| C. Also let the model answer sensitive questions | Rejected: those answers are deterministic by design (ADR-0003 fail-closed, D-87). The owner asked about reading, not deciding. |

## Consequences

- Better tier-5 and llm_fill answers on questions that need context like residency or contact details.
- The UI badge follows the effective value ("Private: local AI only").
- Prompt hashes change when the switch flips, so cached fills (llm_fill §13.3) re-run once.
- The S definition (`is_sensitive`) still matters: it drives the audit, the tags, the redaction and the locks.
- Reversal is one config line.
