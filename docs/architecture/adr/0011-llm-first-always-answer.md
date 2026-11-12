# ADR-0011: The local model answers every field; code keeps only the mechanics (always answer)

**Status:** Proposed · **Date:** 2026-11-12 · **Deciders:** owner (D-208), architect · **Design:** `../llm_first_fill_design.md` (Q-121)
**Supersedes for the default policy:** ADR-0003 §1–§3 (deterministic first, fail closed, two agreeing runs), ADR-0006's "the model chooses the source, the program checks and writes" and its locks (D-82), ADR-0008 Option C ("the model reads, code decides") and the private/sensitive split for a local model (D-105, D-201). All of them stay in force under `apply.fill_policy: strict`.

## Context
The owner's first live attempt (Greenhouse, 43 fields) filled nothing and ended `unanswerable_required`: 28 required fields unknown although the profile and resume held the answers. Causes: the relevance guard G2b rejected correct education facts (no entry group, no synonym), phantom react-select inputs (fixed in Q-119), and fail-closed stops on declarations, another country's visa question, a disabled composer and rule misses. The owner (D-208): the model reads everything, derives sensibly, must fill every field, declarations default to No, no string matching. The constitution changed principles 1 and 3 accordingly. Fixed constraints: local model only, no secret in a prompt, files and identity by code, offered options only, bot-check stops, never twice, pre-Submit scan, full audit.

## Options considered
| Option | Assessment |
|---|---|
| A. Keep fail-closed; loosen guards one by one (wider synonyms, more tier-2 rows, relaxed G2b/G7) | Low risk per step, but every new form finds the next miss: the failure class is structural (a veto per guard). Contradicts D-208 ("not string matching"). Rejected |
| B. Strict path first, then an always-answer pass for whatever it left unknown | Reuses all code, but runs two pipelines per page (G5 second runs, rechecks, then a model pass with a different prompt), doubles latency, and the strict pass's rejections (e.g. G2b on the education entry) still decide what the second pass must guess. Two sources of truth in the audit. Rejected |
| C. Model-first: one briefing (whole profile, earlier answers, computed facts, standing rules, resume) and the model answers every field; code does mechanics, hard limits, and a deterministic last resort marked as an assumption (chosen) | One prompt path, fewer calls (no G5/recheck), the briefing fits in 1/3 of the context, wrong answers are visible (basis + assumed flag + "Answered for you"). Risk: plausible wrong answers on real applications |

## Decision
Option C as `apply.fill_policy: always` (the owner's shipped config); `strict` kept as a selectable policy and as the code default so existing behaviour and pins are unchanged. Under `always`:
- The model gets the briefing as a stable, cached prompt prefix and answers every field with `{value, basis, assumed, reason}`; required fields always get an answer (must-answer pass, then a per-type deterministic last resort, marked assumed).
- Locks, tier-2 rows, declaration classes and relevance become hints; G1 (offered options), G12 (other employers in free text) and G13 (applicant's details in another person's field) stay hard; G3 becomes an audit flag; G2/G4/G5/G7/G8 are removed.
- Code keeps: file uploads, the identity email, the owner's exact earlier answer (P3), secrets refused at `backends.py`, local-only (a remote backend falls back to `strict`), format coercion, read-back, bot-check stops, never twice, the pre-Submit scan.
- A page that would need more than `last_resort_max` last resorts, or gets no usable reply, is a system failure (`model_unavailable`, the queue pauses), never a page of guesses.

## Consequences
- Easier: forms whose wording differs from the profile get filled; one prompt path; ~2–3 calls per page; the audit says per row where each answer came from.
- Harder: an answer can now be plausible and wrong. Mitigated by code-built standing rules, code-computed facts, the assumed mark, "Answered for you" with Keep/Change (the correction wins next time), and the M20 gate run under `always` before auto.
- Additive contract v7 (`FillPolicy`, `Answer.assumed`, new sources, `document_missing`, `QuestionStatus.ASSUMED`), schema +1 (`apply_answers.assumed`).
- Revisit if gate audits show wrong values with a cited fact (then code writes the cited fact's value), or if the briefing passes 18k tokens (then retrieval of earlier answers, design §3.2).
