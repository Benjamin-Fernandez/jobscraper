# VERDICT: MERGE WITH FOLLOW-UPS (Q-83 declarations: D-171 details tail, place qualifiers, applicant subject, narrowing words)

Branch `eng/Q-83-declarations` @ cc53f68 (code 6bc59da, pins 5f4bb30, spec 629990f), base `personal`. Reviewer: independent, KA-2. Read: `apply_design.md` §7.5 D-171 block and oracle table, `docs/reviews/Q-82-declarations.md`, `git diff personal...HEAD -- src/`, the pin file's test list. No CRITICAL or HIGH finding. One MEDIUM and three LOW items, all safety-direction notes on value-true answers or pin gaps; none is a regression against `personal`, and none blocks. Adversarial replays used `declarations.classify` + `answer` through `test_apply_declarations_q48._ans/_prof` (employer Acme, sample profile, every declaration false unless stated, Yes/No dropdown unless stated). Scripts stayed in the session scratchpad.

## 1. Spec vs code, rule by rule
- **Details tail (spec item 1).** `_strip_detail_tail` and `_strip_trailers` match the spec: answer hint, then (only when `yes_no = fit_type in (DROPDOWN, RADIO) and bool_shaped(f)`) the tail, then a hint again; last "if yes/so" only; at least one token before it; optional please/kindly; one verb; at most 6 TAIL_OBJECT tokens to the end. `negated_question` and `_freedom_inverts` call `_strip_trailers(..., True)` as specified. Replays: "...crime? If yes, please provide details." No (dropdown and radio); the same as TEXT unknown; "...provide details and any other information about your visa", "...provide your trustee's name below", "If yes, please provide details. If yes, please list the offences", "...further information in the space provided below" (7 object tokens, over the cap of 6) all unknown. "If yes, please provide details. Have you ever been convicted of a crime?" (tail first) unknown. "Have you not been convicted of a crime? If yes, please provide details." unknown (negated). "Are you free from any criminal convictions? If yes, ..." Yes (correct inversion). "Are you willing to sign an NDA? If yes, please provide details." unknown (AMBIGUOUS before the frame).
- **Narrowing (item 2).** `narrowing_ok = value is False`, taken before the D-91 inversion, threaded to `question_frame` and to the checkbox `_one_status_question`. With `criminal_record: true`, "...convicted of a crime (excluding minor traffic offences)?" is unknown; with false, No; "Are you free of any criminal convictions other than minor traffic violations?" Yes (correct: false means none at all). "I have no criminal record excluding minor traffic violations" ticked. Matches the spec.
- **Places (item 3).** `_place_spans` needs a standing class in the set and an anchor right before the qualifier. Replays: "criminal record in Singapore or elsewhere" No; "...in Singapore or currently work in Singapore", "...in Singapore and a valid visa", "non-compete agreement with a company in Singapore", "disability in Singapore" (with `disability_status: no`) all unknown. Matches.
- **Rule 3 lead-in first, rule 5 "aware", rule 6.** Match. "Are you a PEP in Singapore or are you aware of any PEP?", "Is your spouse a politically exposed person?", "Are you aware of any criminal record against Acme employees?", "Do you know anyone with a criminal record?", "Has anyone in your family been convicted of a crime?" all unknown.
- **Vocabulary counts** read from the code: SHARED 65, per class 169 (10/12/29/21/25/49/14/9), NARROWING 7, PLACE_ANCHORS 56. Equal to the spec line.
- No disagreement between spec and code found.

## 2. Adversarial labels (72 replayed in two batches; the rows that matter, 14 not covered by a pin marked +)

| # | Label (type, profile) | Result | Right? |
|---|---|---|---|
| 1+ | Have you been convicted of a crime? If yes, provide details. (no "please") | No | yes |
| 2+ | Do you have a criminal record? If yes provide details (no comma) | No | yes |
| 3+ | Have you ever been convicted of a crime? (Yes/No) If yes, please provide details. | No | yes (mid-label hint dropped as specced) |
| 4+ | Have you been declared bankrupt in any jurisdiction? If so, please provide a brief description below. | No | yes |
| 5+ | Are you a politically exposed person? If yes, please provide details (options Yes / No / Prefer not to say) | No | yes |
| 6+ | I confirm I have no criminal record. If yes, please provide details. (checkbox) | unknown | yes (the tail never strips on a checkbox; safe) |
| 7+ | Do you have a non-compete agreement? If yes, please provide details. Will you join Acme? | unknown | yes |
| 8+ | Have you been convicted of a crime? If yes, please provide details. (`criminal_record: true`) | Yes | yes (the tail adds no narrowing) |
| 9+ | Are you free from any non-compete agreement in Singapore? | Yes | yes |
| 10+ | Do you have a criminal record excluding minor traffic violations? If yes please provide details (`criminal_record: true`) | unknown | yes |
| 11+ | Have you been convicted of a crime in Singapore? (`criminal_record: true`) | Yes | NO, see MEDIUM-1 |
| 12+ | Have you been convicted of a crime in the last 12 months? and "...in the last 5 years?" (`criminal_record: true`) | Yes | NO, see MEDIUM-1 |
| 13+ | I have been convicted of a crime in Singapore (optional checkbox, `criminal_record: true`) | ticked | NO, see MEDIUM-1 |
| 14+ | Is your previous employer bound by a non-compete? and "Are you or is your employer bound by a non-compete?" | No and No | arguable, see LOW-1 |

Also held as expected (unknown): the tail on a TEXT field; "...If yes, please provide details and any other information about your visa"; "If yes, please provide details. Have you ever been convicted..."; "Have you been declared bankrupt? If yes, please provide your trustee's name below."; "Have you not been convicted of a crime? If yes..."; "Are you currently in Singapore? If yes, please provide details about your PEP status"; "Do you know anyone with a criminal record?"; "Has anyone in your family been convicted of a crime?"; "Do you have a disability in Singapore?"; "Are you bound by a non-compete agreement with a company in Singapore?".

## 3. Findings

### MEDIUM-1: a place or time qualifier is covered for a TRUE value (the hazard D-171 closed for narrowing words)
- Where: `declarations.py` `_place_spans` (place qualifiers), `_STATUS_FILLER` (`last year years month months`), and `_bool_answer` (`narrowing_ok = value is False` is the only value-sensitive gate).
- Scenario: the owner sets `criminal_record: true` (a conviction overseas in 2015). "Have you been convicted of a crime in Singapore?" answers Yes; "...in the last 12 months?" and "...in the last 5 years?" answer Yes; the optional checkbox "I have been convicted of a crime in Singapore" is ticked. Each is a statement the profile does not support (the declaration is a bare boolean with no place or date). The spec's own rejected option (d) says "a true value would give a Yes that may be false"; that reasoning applies to place and time qualifiers equally. Time words (`year(s)`, `last`) pre-date D-171; D-171 adds `month(s)` and makes places a qualifier, so it widens the same class a little.
- Not a regression for the owner today: every declaration in the profile is false, where "No" to a narrowed question is true.
- Fix (follow-up, spec change plus pins): treat place-qualifier spans and the `year/years/month/months/last` words like NARROWING: covered only when `value is False`; with a true value the field ends `unknown`. One pin per row 11-13. Alternative: record it as a residual in D-171 with the revisit trigger "any declaration set true".

### LOW-1: rule 6 accepts "your <other party>" as an applicant subject
- Where: `_APPLICANT_SUBJECT = {you, your}`.
- Scenario: "Is your previous employer bound by a non-compete?" and "Are you or is your employer bound by a non-compete?" answer No (`employer`, `previous` are non_compete filler by design, for the live F1 label). The first asks about the previous employer's own agreement. With a false value, No is the owner's own state and mostly harmless; with a true value it would be Yes about a third party. Narrow, and "your" is a spec decision (rule 6 text; "Has your professional licence ever been revoked?" passes).
- Fix: optional; or add a pin that records it as acceptable.

### LOW-2: pin gaps (none changes the verdict)
- No pin for the true-value rows in MEDIUM-1 (they would document current behaviour), for `negated_question` with a tail ("Have you not been convicted of a crime? If yes, ..." unknown; spec item 1 names it), for an NDA label with a tail, or for a tail on a dropdown that is not `bool_shaped`. The code is right in each replayed case; add rows so a later change cannot drift.

### LOW-3: hard edges, no defect
- A 7-token tail object ("further information in the space provided below") stays unknown: an under-answer, safe, spec-consistent.
- `question_frame` imports `resolve.bool_shaped` inside the function (resolve imports this module). `test_layering` passes; the lazy import is the way round the cycle and is cheap.

## 4. Safety-direction checks
- **Over-answering from stripped tails:** none found. The tail is closed (verbs, objects), only the last "if yes/so", never on TEXT, TYPEAHEAD or CHECKBOX, and what remains must still pass the full D-164/D-170 frame. A tail that mentions anything else stays in and fails rule 1.
- **Negation:** `negated_question` and `_freedom_inverts` see the stripped tokens; the tail holds no negation word, so nothing is hidden. "Have you not been convicted of a crime? If yes, ..." unknown; "free from ... If yes" Yes.
- **NDA willingness:** unchanged (`cls is not L.NDA_WILLINGNESS` guards both paths; D-165 unset-is-no-answer untouched).
- **D-87 defaults and D-90 gates:** untouched in the diff (gate order, employer-name gate and D-91 inversion call sites kept; `narrowing_ok` is read before the inversion as specced). Employer classes still answer through D-164 with a tail ("Do you hold any shares in Acme? If yes, please provide details." No; "Have you ever worked for Acme? If yes, ..." No); the recorded MEDIUM-4 residual is kept, not changed.
- **Fail closed:** every new branch returns False or unknown on doubt; no new reason code or write.

## 5. Layering, privacy, CAPTCHA
- Layering: no new module import beyond the existing lazy `.resolve` import; `test_layering` 13/13.
- Privacy: no profile values in notes, logs or the diff (the added lines hold no log or print call; notes are fixed strings; pin labels are generic, employer "Acme"). No `data/` path touched.
- No CAPTCHA or bot-check handling touched.

## 6. Test lines
- `PYTHONPATH=src python tests/run_tests.py -k declarations` gives `122/122 passed  (-k 'declarations')`
- `PYTHONPATH=src python tests/run_tests.py -k layering` gives `13/13 passed  (-k 'layering')`
- No full suite (per delegation). Pending: the tester's docstring-only edit to `tests/test_apply_declarations_d170.py` (requested in the software-engineer outbox); not reviewed, as instructed.

## 7. Follow-ups to queue
1. MEDIUM-1: value-sensitive place and time words (or a recorded residual), plus pins.
2. LOW-2: pins for negated + tail, NDA + tail, non-bool-shaped dropdown + tail.
3. LOW-1: optional rule 6 tightening.

VERDICT: MERGE WITH FOLLOW-UPS.
