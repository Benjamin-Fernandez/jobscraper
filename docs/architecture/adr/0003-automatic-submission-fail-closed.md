# ADR-0003: Fully automatic submission, with fail-closed answer resolution

**Status:** Accepted (implements D-51, D-55, D-57, D-58)
**Date:** 2026-11-01
**Deciders:** owner (D-51); architect (the guard design recorded here)
**Relates to:** PRD F-32, F-33, F-37, F-38, F-39, NF-06, R-5; `apply_design.md` §4, §7, §12

## Context

The owner decided that the app clicks Submit itself (D-51), against the research recommendation of a human final review (brief §7: at 90% per-field accuracy a 30-field form is fully right about 4% of the time; declarations are legal attestations; small models invent metrics). The owner's mitigation is "fail properly": stop on anything uncertain rather than guess. This ADR fixes how the design turns that into rules a coder cannot weaken by accident.

## Decision

1. **Deterministic first, model last.** Tiers in F-32 order: field map → profile rules (`questions.yaml`) → answer memory → declarations → local LLM. The first tier that yields a valid value wins.
2. **Fail closed on facts the profile owns.** Sensitive fields and anything that looks like an attestation never reach the model. A declaration-like question the classifier cannot label uniquely ends a required field `unknown` (the attempt fails `unanswerable_required`) and leaves an optional one blank.
3. **The model only chooses or rewords grounded facts.** Choice answers need two agreeing runs (temperature 0 and 0.7) and a verbatim evidence quote found in the profile, resume or JD. Free text passes a code grounding check (numbers, dates, dictionary terms, proper nouns must occur in the corpus), with one checked retry.
4. **Resolve before typing.** Greenhouse plans are resolved in full before Edge opens; DOM steps are resolved in full before the first keystroke on that step.
5. **Submit is a one-way door.** `submit_clicked_at` is committed before the click. After it, an attempt ends `submitted` or `submitted_unconfirmed` only; nothing resubmits automatically except the single re-click after an emailed security code. A partial unique index allows one successful attempt per posting; twins (same posting URL) are refused.
6. **Every answer is audited** with its tier, source, confidence and, for the model, the prompt hash; the owner can read "What I told this employer".
7. **M20 gate before `auto`.** The app ships with `apply.mode: dry_run`; the owner switches to `auto` after reviewing 5 dry runs (PRD M20 gate).

## Options Considered

### Option A: automatic submit with fail-closed resolution (chosen)
**Pros:** meets the owner's goal (no typing); wrong-answer risk concentrated in tier 5, which is boxed in by agreement, evidence and grounding; failures are visible and recoverable by hand.
**Cons:** more attempts fail `unanswerable_required` than a permissive resolver would; a grounded but poorly judged choice can still go out (mitigated by audit and caps).

### Option B: automatic submit with a confidence threshold only (brief §8.3 style, ≥ 0.9)
**Cons:** confidence from a 14B model is not calibrated; a threshold without evidence checks lets confident inventions through. Rejected.

### Option C: human final review (research recommendation)
**Cons:** contradicts D-51. Kept as `dry_run` mode, which the owner can choose at any time.

## Trade-off Analysis

The owner trades some completion rate for a lower chance of a wrong attestation. G1's targets (≥ 70% / ≥ 50% submitted) are measured at M21; if `unanswerable_required` dominates the failures, the fix is more profile rules and answer memory (deterministic tiers), not a looser model tier.

## Consequences

- Easier: reasoning about safety: every path to a submitted value is enumerable from the audit row's tier.
- Harder: forms with many open-ended required questions will fail until the owner adds answers (profile or memory).
- Revisit if: G1 is missed mainly because of tier-5 refusals on harmless questions; then widen evidence rules with an ADR, never by disabling grounding.

## Action Items

1. [ ] Lane P implements `apply_design.md` §7 exactly, including the refusal paths.
2. [ ] Tester: oracle tests for each refusal path (ambiguous attestation, sensitive miss, disagreeing runs, ungrounded text).
3. [ ] Owner reviews 5 dry-run audits at the M20 gate before setting `auto`.
