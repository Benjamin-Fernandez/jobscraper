# Review: Q-90 / Q-91 (D-176, KA-2) on `eng/Q-90-declarations`

Reviewer, 2026-11-10. Change set: spec 0d5e6d5 (apply_design §7.5 D-176), code 84f39d8 (`src/jobscraper/apply/declarations.py` only), pins ca728e0 (`tests/test_apply_declarations_d176.py` + one size pin in d171), spec notes 68764d1 (`llm_fill_design.md` G12 and §13.3). The merge of personal 944257b (1e0a907) is ignored. Rulings applied: Q1 = option A, Q2 = G12 amended to match the code.

## Verdict: MERGE WITH FOLLOW-UPS

No CRITICAL or HIGH finding. Every D-176 rule is implemented as specified, and no label I tried is answered Yes/No when it should be unknown, except one MEDIUM loosening (M1) that the spec itself introduced. Two MEDIUMs and two LOWs below; M1 is a three-line fix I would take before the merge if the lane is still open, but it does not block.

Evidence (last lines):
- `PYTHONPATH=src python tests/run_tests.py -k declarations` -> `151/151 passed  (-k 'declarations')`
- `-k llm_fill` -> `90/90 passed  (-k 'llm_fill')`
- `-k layering` -> `13/13 passed  (-k 'layering')`
- Privacy: the diff against `0d5e6d5~1..ca728e0` touches six files (outbox, two design docs, `declarations.py`, two tests). No e-mail, real name, employer name from mail or secret in added lines (only "Acme"). Layering: `declarations.py` imports only `re`, `typing`, `.contracts`, `.plan`; no SQL, no backend, no stage import.

## 1. Rule-by-rule against D-176

| Rule | Code | Result |
|---|---|---|
| 1 Time words only for a false value | `_TIME_FILLER` (7), `_STATUS_FILLER` now 58; `shared = _STATUS_FILLER \| _TIME_FILLER if narrowing_ok` (declarations.py:866); rule-3 lead-in test uses `shared` | OK. `narrowing_ok = value is False` at :1159, taken before the D-91 inversion; an unset value (None) counts as "not false", the safe side |
| 1 Place spans only for a false value | `places = _place_spans(...) if narrowing_ok else []` (:862) | OK |
| 6b No other party in the subject zone | :876-880: zone = tokens from piece start to the first anchor; fails on an `_OTHER_PARTY` token or an `_employer_spans` start inside it | OK. `_OTHER_PARTY` has 12 words as specified |
| "found guilty" -> criminal_record | PHRASES[CRIMINAL_RECORD] (:110) | OK ("academic/professional misconduct" labels still end unknown by the status frame, see table) |
| Five director runs -> REGULATORY | PHRASES[REGULATORY] + filler `company companies` (:112-119, :356) | Runs OK. The class-wide filler has a side effect: M1 |
| `UNCLASSED_MARKERS` -> AMBIGUOUS, not in `ATTESTATION_MARKERS` | 14 runs (:431-438); checked in `classify()` only after "no class matched" and the attestation check (:677-682) | OK, and kept apart: "Have you previously worked for Acme, or have you ever been deported?" -> AMBIGUOUS, unknown |
| Q1 option A | the five runs are in REGULATORY | OK, matches the ruling |
| G12 / §13.3 notes (Q-92 F3, F5, Q2) | `facts.other_employers(rctx, composed=...)` (facts.py:247-268): own employers = `experience[].employer`, `education[].institution`, resume entries, subtracted only when `composed`; guards.py:420-421 builds `others` and `others_composed`; kept MyGreenhouse text uses `c.others` (guards.py:776, 781). `pagefill._cache_put` (:701-733) and `_cached` (:694) never store/replay a required unknown, drop stop keys, corrected fields, empty picks, and store an optional unknown | Notes match the built code |

## 2. Findings

### MEDIUM-1: `company`/`companies` as REGULATORY class filler loosens non-director questions (declarations.py:356)
Added so "disqualified as a director of a company?" passes, but the filler is class-wide. Before D-176 these ended unknown ("not a status question"); now they are filled **No** from `regulatory_disciplinary: false`:
- "Have you ever been suspended by a company?" -> No (old: unknown)
- "Have you ever been subject to disciplinary action by a company?" -> No (old: unknown)

An employer's suspension or HR discipline is not a regulator's action; D-87 (NDAs, restrictive agreements, government work, disability, affiliations) does not cover it, so the owner's `false` does not state it. This is the same direction the architect flagged for the director phrase ("widens what `false` states") but here it was not weighed, and the Coordinator's Q1 ruling covered only the director runs. Failure scenario: a form asks "Have you ever been suspended by a company?" and an applicant who was once suspended from an internship is answered No by a signed submission.
Fix (small): remove `company companies` from `_CLASS_FILLER[REGULATORY]` and put the tail in the phrases instead ("disqualified as a director of a company", "...of any company", "...of a company", plus the same for the other four), or cover it as an `extra_run` only after a director phrase. Re-run row 32 and the d176 size pins (169 per class). The spec's "171 with company, companies" line then changes; the spec wins, so ask the architect for a one-line amendment.

### MEDIUM-2: `UNCLASSED_MARKERS` also fires on non-declaration questions and takes them away from tier 5
`classify()` returns AMBIGUOUS for any label that holds a marker run and no class. Downstream (`resolve._tier4` -> `declarations.answer`, AMBIGUOUS branch): `_agreed` finds no classes, so the answer is `_ended` = UNKNOWN (required) or BLANK_OPTIONAL (optional), final, never tier 5. `questions.py:187/338` then captures a required one as a Questions-inbox item (reason `attestation_unclear`, sensitive = true); `locks`/`guards` also treat the field as a declaration. Observed:
- "Can you work with litigation teams?" -> AMBIGUOUS, UNKNOWN
- "Do you have experience with court orders?" -> AMBIGUOUS, UNKNOWN
- "Describe your experience with litigation support" (TEXTAREA) -> AMBIGUOUS, UNKNOWN (an essay question the model would have answered)
- "Are you available for litigation roles?" / "How did you hear about our litigation practice?" -> AMBIGUOUS, UNKNOWN
- "Please describe your experience with injunctions" -> AMBIGUOUS, UNKNOWN

This is fail-closed, so it is not a safety defect; the cost is that a law-, compliance- or legal-ops employer's form turns into Questions-inbox items and blank optionals, and the essay answer disappears. The existing `conflict` attestation marker has the same shape ("conflict resolution skills"), so this is a known pattern, not a new class of problem. The spec does not mention this cost. Scope is small for the owner's target (new-grad roles), hence MEDIUM.
Fix options: (a) narrow the bare words to declaration-shaped runs ("involved in litigation", "pending litigation", "subject to an injunction", "any court order", "been dismissed"); (b) skip the markers in `classify_field` for TEXTAREA / non-choice fields (the field is available there, `classify` has no type); (c) accept and record. I would do (a) with the existing pins as the oracle (rows 33-37 must stay AMBIGUOUS).

### LOW-1: natural wordings of the director family are still unclassified -> tier 5
Only the five specified runs match. "Have you ever been disqualified from acting as a company director?", "...disqualified from holding office?" and "disqualified director" give `classify -> None`, so tier 5 (the model) can answer them: the exact Q-91 hazard for a slightly different wording. Fix: add "disqualified as a company director", "disqualified from acting as a company director", "company director disqualification" to the REGULATORY phrases (or a fallback UNCLASSED run "disqualified director").

### LOW-2: "disqualified from driving" and similar stay None (tier 5)
Correct as not a declaration; noted so the fix to LOW-1 does not widen to a bare "disqualified" run.

## 3. Question 2 checks (answers)

- **AMBIGUOUS for a skills question:** answered above (MEDIUM-2): unknown / blank_optional, final, no model; captured as `attestation_unclear` when required.
- **Rule 6b on a normal "you" label:** "Do you have a non-compete with any client?" -> `non_compete`, UNKNOWN "not a status question", with value false or true. This is **not** 6b: "client" is not NON_COMPETE filler, so rule 1 refuses it. Running the pre-D-176 module (copy at the scratchpad `oldsrc`) gives the same result. "Do you have a non-compete with any employer?" -> No/Yes (employer is non-compete filler and sits after the anchor), "Do you have any conflict of interest with a client?" -> No. 6b changes only labels where the other party sits before the first anchor, as the pins say. Right: unknown is the safe result, and that label is not answerable from a bool.

## 4. Adversarial labels (employer Acme, sample profile; YN dropdown, required, unless noted; F = value false, T = value true). "Pin" = covered by the D-176 table; "out" = outside it

| # | Label | Result | Right? |
|---|---|---|---|
| 1 | Can you work with litigation teams? (out) | AMBIGUOUS, UNKNOWN | safe; over-reach, see M2 |
| 2 | Do you have experience with court orders? (out) | AMBIGUOUS, UNKNOWN | safe; M2 |
| 3 | Describe your experience with litigation support, TEXTAREA (out) | AMBIGUOUS, UNKNOWN | safe; M2 (the model is blocked) |
| 4 | Have you ever been suspended by a company? (out) | regulatory_disciplinary, F: **No** (old: unknown) | **wrong direction**, M1 |
| 5 | Have you ever been subject to disciplinary action by a company? (out) | F: **No** (old: unknown) | **wrong direction**, M1 |
| 6 | Have you ever been disqualified as a director of a company? (out) | F: No | right (the Q1 ruling) |
| 7 | Have you been disqualified as a director in the past 5 years? (out) | regulatory F: No; T: unknown | right |
| 8 | Have you ever been disqualified from acting as a company director? (out) | classify None -> tier 5 | gap, LOW-1 |
| 9 | Have you ever been found guilty of academic misconduct? (out) | criminal_record, UNKNOWN "not a status question" | right |
| 10 | Have you ever been found guilty of a crime outside Singapore? (out) | T: unknown; F: unknown ("outside" is not a closed place) | safe |
| 11 | Have you been convicted of a crime or deported from any country? (out) | criminal_record, UNKNOWN | right (the frame refuses the second clause) |
| 12 | Have you ever been convicted of a crime or dismissed from employment? (out) | criminal_record, UNKNOWN | right |
| 13 | Have you or your client been convicted of a crime? (out) | UNKNOWN | right (6b, `client` in the zone) |
| 14 | Have you been convicted of a crime or has your employer been convicted? (out) | UNKNOWN | right (6b, second piece) |
| 15 | In the last 5 years, have you been convicted of a crime? (out, lead-in) | T: UNKNOWN; F: No | right (rule 3 uses `shared`) |
| 16 | Have you been convicted of a crime within 7 years? (out) | T: UNKNOWN; F: No | right |
| 17 | Have you been convicted of a crime in the previous 10 years? / during the last decade? / ever since 2019? (out) | UNKNOWN for T and F | safe under-answer (not closed words) |
| 18 | Have you been convicted of a crime in Singapore or elsewhere? / in any country? (out) | T: UNKNOWN; F: No | right; matches the rejected-(a) note |
| 19 | I have been convicted of a crime in the last 5 years, checkbox (out) | T: UNKNOWN; F: UNKNOWN | right (a false statement is never ticked; F is unknown because ticking would claim it) |
| 20 | I have not been convicted of a crime in the last 5 years, checkbox (out) | F: ticked; T: UNKNOWN "checkbox statement not recognised" | right |
| 21 | Are you free from any non-compete in the past? (out, freedom + time) | T: UNKNOWN; F: Yes | right (flag read before the inversion) |
| 22 | Are you willing to sign an NDA in Singapore? with `willing_to_sign_nda: true` (out) | AMBIGUOUS, UNKNOWN | right (D-166 vocabulary) |
| 23 | Have you been convicted of a crime or declared bankrupt in the last 5 years? with criminal F, bankruptcy T (out) | AMBIGUOUS, UNKNOWN | right (agreement rule) |
| 24 | Have you ever been disqualified as a director or been convicted of a crime? (out) | AMBIGUOUS, FILLED No (agreed criminal_record+regulatory_disciplinary) | right (both false; the agreement rule) |
| 25 | Have you ever worked for Acme or been dismissed from Acme? (out) | prior_employment_at_company, No | right (dismissal implies employment) |
| 26 | Are you or your regulator subject to disciplinary action? (out) | UNKNOWN | right (6b); same as before |
| 27 | Have you ever been convicted of a crime in the past? (out) | T: UNKNOWN; F: No | right ("past" is a time word) |
| 28 | Pins checked once for sanity: rows 1-6, 9, 18-21, 25-28, 33-37 of the table | as the table | right (suite is green) |

Not a defect, my script: `declarations.answer(None, ...)` raises AttributeError, which the resolver never reaches (`_tier4` returns early on None).

## 5. Pins
The pin file asserts the table oracles and sizes (the d171 pin moved 65 -> 58, `_TIME_FILLER` pinned in the d176 file). It does not cover M1 or M2; if M1 and M2 are fixed, add: "suspended by a company" (F -> unknown) and "litigation support" TEXTAREA (not AMBIGUOUS).

## 6. Disagreement with the spec
M1 comes from the spec's own vocabulary line ("169 -> 171 with company, companies"). Per the rules the spec wins, so I do not block on it; I recommend the architect amends it.
