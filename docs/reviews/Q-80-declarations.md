# VERDICT: MERGE (Q-80 declarations: D-164 question_frame, D-169b, F12/F14)

Branch `eng/Q-80-declarations` @ 08ff630, base `personal` 2045f06. Reviewer: independent, KA-2. Files read: `src/jobscraper/apply/declarations.py`, `locks.py` (diff), `tests/test_apply_declarations_d164.py`, `docs/architecture/apply_design.md` §7.5 (D-164 block, D-165, D-166, D-169b, D-91, gates 1-4). No CRITICAL or HIGH finding. Three MEDIUM findings; they are spec-shaped and the same weakness already existed on `personal` for the old frame, so they do not block.

## 1. Pin table replayed through `declarations.classify` + `answer` (employer Acme, sample profile, required Yes/No dropdown)

| Label | Result | Spec |
|---|---|---|
| Politically exposed person (PEP)? / Criminal record / Bankruptcy / Criminal record or bankruptcy | No | No |
| Disability (status no / yes) | No / Yes (replayed, and the d164 tests) | match |
| Declaration: Are you a politically exposed person? / Note: Do you have a non-compete? | No | No |
| Please confirm: Are you a PEP? / Please indicate if you have ever been bankrupt | No | No |
| Confirm you are free from any restrictive covenants | Yes | Yes |
| Can you confirm you are clear of any conflict of interest? | Yes | Yes |
| Can you tell us whether you are a PEP? | No | No |
| Can you sign a non-compete? | unknown | unknown |
| Free from any restrictive covenants? | unknown (not a status question) | unknown |
| Non-compete agreement? / Confidentiality agreement / Criminal record check | unknown | unknown |
| PEP? as TEXT / as single checkbox | unknown / unknown | unknown |
| Declaration: Are you a PEP? as TEXT | No | No |
| Please indicate if you have ever been bankrupt as TEXT | unknown | unknown |
| Former employee? | unknown (gate 4) | unknown |

All rows of the spec table hold.

## 2. Adversarial labels (Yes/No dropdown unless stated; every declaration false, `disability_status: no` where relevant)

"Base" = `personal` 2045f06, replayed from a `git archive` copy. "New" = answered at 08ff630 but not at base.

| Label | Answer | Correct? |
|---|---|---|
| Please confirm the criminal record check consent | unknown | yes |
| Disability insurance? | unknown | yes |
| Do you have a non-compete you'd like us to buy out? | No | arguable (the status clause is real; base same) |
| Bankruptcy court experience? | unknown | yes |
| Can you confirm you will sign the NDA and relocate? | unknown | yes |
| Note: are you comfortable with a background check? | not a declaration | yes |
| PEP screening? | unknown | yes |
| Please confirm you consent to a criminal record check | unknown | yes |
| Are you willing to undergo a criminal record check? | unknown | yes |
| Do you have a criminal record check certificate? | No | NO, over-answered (base same) |
| Do you have a bankruptcy lawyer? | No | NO, over-answered (base same) |
| Is a criminal record check required for your visa? | No | NO, over-answered (base same) |
| Are you aware that a criminal record check is mandatory? | No | NO, over-answered (base same; D-90a keeps "aware" on purpose) |
| Is the criminal record check status satisfactory? | No | NO, over-answered (base same: "status" run) |
| Criminal record check status | No | NO, over-answered (base same: "status" run) |
| Do you hold a valid work permit and have you been convicted of a crime? | No | NO, compound answered by one clause (base same) |
| Are you currently a PEP screening officer? | No | NO, over-answered (base same) |
| Is your status as a criminal record holder public? | No | NO, over-answered (base same) |
| Do you hold any regulatory disciplinary action training certificates? | No | NO, over-answered (base same) |
| Have you ever been bankrupt or do you have a visa that restricts work? | unknown | yes |
| Have you been convicted of a crime or do you need sponsorship? | unknown | yes |
| Are you a PEP or do you require relocation assistance? | unknown | yes |
| Please tell us about your criminal record | unknown | yes |
| Can you tell us about your bankruptcy? | unknown | yes |
| Please state your bankruptcy status | No | yes (base same) |
| Let us know if you were a politically exposed person | No | yes (new) |
| Indicate whether you have worked in a bankruptcy law firm | No | NO, over-answered (new, shape B) |
| Confirm you are a PEP screening analyst | No | NO, over-answered (new, shape B) |
| Confirm you have the right to work and you are a PEP | No | NO, compound (new, shape B) |
| Can you confirm you are free from any restrictive covenants and able to relocate? | Yes | NO, compound: Yes also covers "able to relocate" (base same, the freedom path had no frame) |
| Confirm you are free from any restrictive covenants and eligible to work in Singapore | Yes | NO, compound (base same) |
| Specify if you have a criminal record and the offence | No | benign (new; "No record" makes the second clause moot) |
| Can you please confirm you have no criminal record / Could you confirm you have not been convicted of a crime | unknown (negation) | yes |
| Please confirm you are free from any criminal record or bankruptcy | unknown (negation) | yes |
| Bankruptcy or criminal record or visa sponsorship | unknown | yes |
| Criminal record, bankruptcy / Criminal Record (Yes/No) / Criminal history / Bankruptcy record / Conflict of interest / Regulatory disciplinary action / Government employment (history) | No | yes (new, shape C) |
| Question: criminal record history / Self declaration: criminal record / Declaration: Note: criminal record | No | yes (new, PREFIX + C) |
| Person with criminal record / Criminal record disclosure | unknown | yes (conservative) |
| Non-compete / Non-compete agreement? | unknown | yes |
| Non-compete status | No | yes (status run) |
| Can you tell us whether you will sign an NDA? / Can you confirm you are willing to sign an NDA? / Confirm you agree to sign an NDA | unknown | yes (D-166 vocabulary excludes modal and lead) |
| Are you willing to sign an NDA? | the `willing_to_sign_nda` value | yes, path unchanged |
| Disability with `decline` and no decline option | unknown | yes |
| Please indicate if you have ever been bankrupt / Are you a PEP? / Criminal record as TEXTAREA; Are you a PEP? as MULTI_CHOICE | unknown | yes (gate 1) |
| Important: Do you have a criminal record check? | No (TEXT too) | NO, over-answered (new only through the PREFIX; the same shape without the prefix was answered at base) |

## 3. Checks asked for

1. Pin table: holds (section 1). `tests/test_apply_declarations_d164.py` 19/19.
2. Over-answering: 19 of about 48 probes are answered when they should not be; 13 of those were already answered at base. The ones new at 08ff630 come through PREFIX, LEAD shape B, or shape A reached through a prefix. Shape C is tight (noun classes only, at most 6 tokens, filler list, NDA objects excluded); I found no shape-C over-answer. The wrong answers cluster in shape A (any status starter plus a class phrase anywhere) and the new shape B (any "you have/you are" after a LEAD).
3. F12: the freedom path now runs the frame (`_bool_answer` runs `question_frame` after the inversion; "Free from any restrictive covenants?" is unknown). NDA willingness: `cls is not L.NDA_WILLINGNESS` skips the frame, the NDA classifier is untouched, and the D-166 vocabulary still blocks the modal/lead forms. TEXTAREA and MULTI_CHOICE never answer (gate 1 runs first).
4. F14: `NEGATIONS` exists only in `declarations.py:181`; `locks.NEGATIONS` is gone and nothing imports it (grep over `src/` and `tests/`: a comment and the pin test only). No `_status_frame` reference is left.

## 4. Findings

### MEDIUM-1: a compound label gets one answer for one clause
- Where: `declarations.py` `question_frame`, shape B and the freedom path (the frame tests only the start of the label).
- Scenario: "Can you confirm you are free from any restrictive covenants and able to relocate?" with `non_compete: false` fills Yes, which also attests "able to relocate". "Confirm you have the right to work and you are a PEP" fills No. A false attestation on a form that auto-submits (ADR-0003).
- Pre-existing at base for the freedom form (it had no frame) and for shape A ("Do you hold a valid work permit and have you been convicted of a crime?" → No). Not a regression, but D-164 was the place to close it; D-166 already applies the rule to NDAs.
- Fix (propose as a Q-81 decision, not a blocker): in `question_frame`, return False when the tokens after the strip contain `and` / `or` / `as well as` followed by tokens outside the matched class phrase spans and filler (the D-166 test applied to the whole label). The agreement rule ("Criminal record or bankruptcy") still passes through the covered-span test.

### MEDIUM-2: shape B (and shape A) accept any "you have / you are / do you have" whose object merely contains a class phrase
- Scenario: "Indicate whether you have worked in a bankruptcy law firm" → No; "Confirm you are a PEP screening analyst" → No; "Do you have a bankruptcy lawyer?" → No. If the owner has worked at such a firm, the filled No is false.
- Pre-existing for A (13 labels answered at base); shape B adds a few. Spec-consistent (D-87: answer, do not ask).
- Fix: none needed to merge. Optional: require that nothing follows the class phrase span except filler, an answer hint or "ever".

### MEDIUM-3: the status runs ("status", "hold") fire anywhere in the label
- Where: `_STATUS_RUNS` in shape A. Scenario: "Criminal record check status" and "Is the criminal record check status satisfactory?" → No. Pre-existing; the D-164 text lists them "anywhere". Fix: anchor `status` to the end of the noun phrase. Low value; record only.

### LOW
- LOW-1: `answer(None, ...)` raises on a non-declaration label (replay harness only; every production caller classifies first through `classify_field`).

## 5. Other review lines
- Fail closed: every new branch returns False (no frame) on doubt. No new path writes a value without a matched class and the field gate. No CAPTCHA, secret or data handling touched. No personal data in the diff (labels are generic, employer "Acme").
- Layering: `declarations` imports `resolve.bool_shaped` lazily inside `_noun_phrase`, the same pattern as `fit_bool`; `test_layering` 13/13.
- Spec: the diff matches §7.5 D-164 steps 1-4, shapes A/B/C and D-169b; no disagreement with the spec found.

## 6. Test lines
- `python tests/run_tests.py -k declarations` → `62/62 passed` (d164 19/19, q48 16/16, review 24/24)
- `python tests/run_tests.py -k apply_contracts` → `66/66 passed`
- `python tests/run_tests.py -k llm_fill` → `90/90 passed`
- `python tests/run_tests.py -k layering` → `13/13 passed`
- No full suite (per delegation). Replay scripts stayed in the session scratchpad.
