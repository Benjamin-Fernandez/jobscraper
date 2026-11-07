# Review: Q-48 declarations (WP-Q48 + D-89) and the lane M defect fixes, `eng/Q-48-declarations`

- **Reviewer:** reviewer agent, 2026-11-02
- **Target:** `eng/Q-48-declarations` at `5964504` (read with `git show`, run from a detached scratch worktree that is now removed).
- **Diffs:**
  - (A) lane M fixes: `git diff 1b58acb...19495da -- src/` (7 files, +232/-16): `guards.py`, `facts.py`, `resolve.py`, `locks.py`, `llm_fill.py`, `questions.py`, `contracts.py`.
  - (B) WP-Q48 + D-89: `git diff 90daf5c...eng/Q-48-declarations -- src/ config/` (9 files, +636/-71): `declarations.py` +413, `applicant.py`, `applicant.example.yaml`, `resolve._tier4`, `locks._declaration_lock`.
- **Checked against:** `apply_design.md` §7.5 and §5.4 (D-87, D-89), `llm_fill_design.md` §4 (L3, L7), §7 (G2, G5, G7, G9), ADR-0003 (fail-closed), decisions D-55, D-82, D-86, D-87, D-88, D-89.
- **Method:** read the code, then ran about 60 adversarial labels through the real resolver (`resolve_one` with `config/questions.yaml` and the sample profile, employer "Acme") and through `guards.ground_items`, `llm_fill.deterministic_pick` and `names_wanted`.
- **Not covered:** `pagefill` callers of `deterministic_pick` (R3 is not on this branch); `QuestionCard.vue` and the web labels for `compose_needed`; the full 920-test suite (I ran only the subsets below).

## VERDICT: NEEDS FIXES (part B); part A is fine to merge on its own

**(A) Lane M fixes: MERGE.** No HIGH. One MEDIUM (F6) and one LOW (F9) in this part. The privacy, fail-closed and no-model-call properties hold (section "What holds").

**(B) WP-Q48: do not merge before F1-F3.** The classifier is frame-blind. D-87 makes "No" the default for declaration classes, and the new phrase lists (NDA, confidentiality, public sector, public service, government agency, disability) match those words in questions that are not asking "are you bound by / have you ever". The result is a wrong "No" on a signed answer, a "No" typed into an essay box, or an unbacked tick. The oracles F1-F20 are green (16/16) because none of them uses these frames. A green suite does not contradict this.

Recommended split: the Coordinator can merge `19495da` (lane M) into `int/Q-35-M` now and hold the Q-48 declarations commit until F1-F4 are fixed.

**Counts: 4 HIGH, 2 MEDIUM, 4 LOW.**

### Evidence

| Command (scratch worktree at `5964504`) | Result |
|---|---|
| `python tests/run_tests.py -k declarations` | 16/16 passed |
| `python tests/run_tests.py -k q46` | 7/7 passed |
| `python tests/run_tests.py -k layering` | 10/10 passed |
| `python tests/run_tests.py -k llm_fill` | 71/72 passed; the one failure is `test_g7_d88_military_and_national_service_labels_are_sensitive` (last line: `pick_option(fb, q, "Yes", ["Yes","No"]) is None`). It fails because `deterministic_pick` now returns the exact option with no model call. This is the known oracle the tester is updating; `fb.calls == []` still holds |
| PII scan of the added lines (emails, names, `+65` numbers, password assignments) | no hits |

### What holds (read in the code and probed)

- **Examples from the brief, as built:**

| Label (dropdown Yes/No, required) | Class | Result |
|---|---|---|
| "Do you have a non-compete you'd like us to know about?" | `non_compete` | No (correct: D-87) |
| "Have you worked with government clients?" | `prior_employment_at_company` | No (wrong class, see F4) |
| "Are you a current employee of a government-linked company?" | `current_employee_at_company` | No (wrong class, see F4) |
| "Do you require any accommodation for a disability during the interview?" | `disability` | unknown with decline; "No" when the owner's answer is No; "Yes" when it is Yes (see F5) |
| "Have you worked with a government agency?" | prior + government | unknown (D-89 fail-closed) |
| "Do you hold any shares in a government agency?" | government + shareholding | unknown |
| "Do you have family members employed by the government?" | government + relatives | unknown |

- **Agreement rule (`_agreed`, `declarations.py:488`):** it refuses a single checkbox, an unsure question, any set outside `STANDING_DECLARATIONS`, and any set with mixed or `None` values. "PEP and non-compete" gives No; "disability or health condition" gives unknown. The note and rule_id are `agreed: <class values joined by +>` only. No S value is in them.
- **D-89 overlap drop and `employer_names`:** fail-closed in every mix I tried. A label that names "us"/"our" or the employer keeps the employer classes, and a disagreeing mix stays AMBIGUOUS.
- **Government/NS rule:** matches §7.5 rule 4 (gov + mil without NS exclusion, or gov + govlike, is unsure; mil + exclusion without gov adds the class). "Have you ever served in the military? (excluding National Service)" gives No; "...including National Service" is not filled by this tier.
- **`deterministic_pick` (`llm_fill.py:590`), item 3:** it runs before `pick_refused`, `redact` and the backend call (`:564`), so it cannot put anything into a prompt. It matches only a normalised exact option or a `Category > Leaf` leaf, or one phone-code option, and returns None on more than one hit. "No" never matches "No, I am not a veteran" (the leaf split is on " > " only). A "No" leaf shared by two categories returns None. Skipping the deny list is safe here because the deny list exists to keep S values out of prompts, and this path sends none. This depends on the caller's G7 still judging model-sourced values on sensitive labels, which is true in `guards.py` and which I could not re-check in `pagefill`.
- **Q-46b (item 5):** `norm_label` keeps "c++" and "c#" distinct from "c"; `names_wanted` rejects PyTorch for Python, Java for JavaScript and C++ for C. The alias groups in `config/aliases.yaml` do not conflate distinct skills (SQL and SQL Server are separate groups). The remaining gap is F6.
- **Q-46a/c, G2d leaf, G2(d) restated fact, G2e, C++ grounding, D-88 labels, COMPOSE_NEEDED:** read; no defect found. `_restates_fact` excludes private facts and Yes/No; the program's own fit is still what gets written. G2e returns unknown when the program's value is no offered option on a complete list. `questions.COMPOSE_NEEDED` is the enum member (no `try/except` fallback left).
- **`applicant.py`:** "nil/none/na/n_a/not_applicable" read as false only for `declarations.*` booleans (`DECLARATION_BOOLS`); `consents.*` and the others keep the old canon. The disability synonyms map to "no" only.
- **Layering and submission:** `test_layering` 10/10. The diff touches no click, submit, upload or CAPTCHA code, so ADR-0004 and the no-evasion rule are not in play.

## Findings

### F1 HIGH: willingness, consent and acknowledgement questions about an NDA or confidentiality are swept into `non_compete` and answered "No" (or ticked)
`declarations.py:115-132` (the new `NON_COMPETE` phrases "nda", "non disclosure", "confidentiality agreement(s)", "confidentiality obligation(s)", "garden leave", ...); `:172` and `:520` (`is_negated` flips the tick); `:513-530` (`_bool_answer`).

- **Why:** D-87(1) says a restrictive agreement the owner is *bound by* is No. The phrases match the noun anywhere, so any question that merely mentions the agreement gets the "bound by" answer. A consent question needs the owner's willingness, which the profile does not hold.
- **Failure scenarios (all run, default profile):**
  - "Are you willing to sign a non-disclosure agreement?" gives **No** (filled, tier 4). "Do you agree to sign our confidentiality agreement?" gives **No**. "Will you be able to comply with our confidentiality obligations?" gives **No**. The employer reads the candidate as refusing a standard NDA.
  - The same dropdown with `declarations.non_compete: true` gives **Yes**, for an unrelated reason.
  - Single checkbox "I have read the confidentiality agreement and have no questions": `is_negated` sees the token "no", so `tick = not False = True` and the box is **ticked** (rule_id `non_compete`). The program has signed "I have read the agreement". ADR-0003 allows a tick only when the profile value makes the statement true; here the value says nothing about the statement. "I have no objection to signing the NDA" is ticked the same way.
  - Pre-existing instances of the same pattern: "mas" (any MAS mention gives `regulatory_disciplinary`: No), "independence", "pep".
- **Fix (in `declarations`, one place):**
  - Add a consent/willingness frame set (tokens `willing, willingness, agree, agrees, consent, accept, acknowledge, acknowledgement, comply, abide, understand, read, prepared`; runs `able to sign, will you sign, would you sign, can you sign`). When a frame token is present and the class is `non_compete` (and, safest, any class), `classify` returns AMBIGUOUS. Do not add "confirm": "I confirm I am not a PEP" is a real attestation.
  - For a single checkbox, any frame token ends `unknown` (required) or blank (optional); never tick on a polarity token alone.
  - Optionally require a status frame before a Yes/No answer: have/has, bound by, subject to, party to, signed, hold, been convicted/charged, is anyone.
  - This is a spec gap, not a spec violation: the §7.5 table lists the phrases without a frame. Amend §7.5 (architect) with the code.
- **Tester pins:** the three willingness labels above on a dropdown → unknown (required) / blank (optional) for both `non_compete` true and false; the two checkbox labels → not ticked; "I am not bound by any non-compete" → still ticked.

### F2 HIGH: a declaration class is answered in an essay box: "No" is typed into a TEXTAREA
`declarations.py:527` (`fit_bool(f, value)` for non-choice fields) with `resolve.py:497` (`fit_bool` returns "Yes"/"No" for TEXT/TEXTAREA/TYPEAHEAD); `locks.py:_declaration_lock` (same call; no field-type gate); `declarations.py:347` (`classify` has no question-starter gate).

- **Why:** the §7.5 phrases `public service`, `public sector`, `civil service`, `confidentiality obligations`, `statutory board`, etc. occur in motivation and experience prompts. `classify` has no gate, and `fit_bool` writes the bool into any text field. §5.4 (line 519 of `apply_design.md`) already gates tier 2 virtual entries on a question starter (are, is, do, does, have, has, will, would, can, were, was); tier 4 has no such gate.
- **Failure scenarios (run, TEXTAREA, required):**
  - "Why do you want to join the public service?" gives the answer **"No"**, rule_id `government_employment`. A GovTech or statutory-board application is the likely place for this label.
  - "What draws you to public sector work?" and "Describe your interest in the civil service" give **"No"**.
  - "Describe your experience with public sector agencies" and "Describe how you handle confidentiality obligations in prior roles" give **"No"**.
  - The L3 lock in the LLM-fill flow takes the same path, so the model never sees these fields.
- **Fix:**
  - In `_bool_answer` (and `_disability_answer`), for TEXT/TYPEAHEAD require the normalised label's first token to be in the §5.4 starter set, and never fill a TEXTAREA; otherwise `_ended(... "not a yes/no question")`. A required one stops as unknown and goes to the inbox.
  - Mirror it in `locks._declaration_lock` by delegating to the same helper rather than a second copy.
- **Tester pins:** the five labels above as TEXTAREA → unknown/blank, not "No"; "Are you a politically exposed person?" as TEXT → still "No".

### F3 HIGH: a negation the closed list does not know gives an inverted answer: "Are you free from any restrictive covenants?" is answered "No"
`declarations.py:176` (`_QUESTION_NEGATIONS`), `:172` (`_NEGATIONS`); the same list is mirrored in `locks._negated`.

- **Why:** LF L7 and §7.5 list exactly: not, never, no, none, neither, free of, without. Other common phrasings flip the meaning and are not on it, so the bool is mapped the wrong way round.
- **Failure scenarios (run, dropdown Yes/No):**

| Label | Answer | Correct |
|---|---|---|
| "Are you free from any restrictive covenants?" | No | Yes |
| "Can you confirm you are clear of any conflict of interest?" | No | Yes |
| "Are you unrestricted by any non-compete or non-solicitation obligations?" | No | Yes |
| "Are you unencumbered by any NDA?" | No | Yes |

  Each one tells the employer the candidate is bound or conflicted. D-87 adds the `non_compete` class, so this phrasing becomes live on Workday and Greenhouse forms.
- **Fix:** add to both lists (and to `locks.NEGATIONS`): `free from`, `clear of`, `clear from`, `unrestricted`, `unencumbered`, `unrestrained`, `exempt`, `absence of`, `absent`, `lack`, `devoid`, `nothing`, `nobody`, `nor`, `cannot`, `unable`. A closed list will always have gaps, so also take the status-frame whitelist from F1: a Yes/No bool is answered only when the label matches a positive status frame; any other shape is unknown. This is a spec gap (the list is the spec's); amend L7 and §7.5 together.
- **Tester pins:** the four labels above → unknown; "Are you bound by any non-compete?" → No.

### F4 HIGH (pre-existing; spec-listed phrases): prior and current employment answer questions that do not name this employer
`declarations.py:156-157` (`"have you worked"`, `"worked for"`, `"employed by"`, and the current-employee phrases); `:270` (`_names_employer` is used only for the D-89 overlap exception); `:347` (`classify`).

- **Why:** `truth()` evaluates these two classes against `ctx.employer_name`, so the answer is only valid for a question about this employer. `facts.names_this_employer` (Q-46c) already enforces that for the standing facts in the LLM path; the declarations tier does not.
- **Failure scenarios (run, default profile, employer Acme):**
  - "Have you worked with government clients?" gives **No** (`prior_employment_at_company`). "Have you worked for a startup before?" and "Have you worked in a bank?" give **No**. The owner has internships; the real answer may be Yes.
  - "Are you a current employee of a government-linked company?" gives **No** via `current_employment(profile, "Acme")`. §7.5 rule 4 says government-linked is unsure, but that check runs only when a government phrase also hit, so it is bypassed here.
  - In a textarea the same labels get "No" (F2).
- **Spec note:** the §7.5 table lists these phrases with no employer condition. I think the table is wrong for this case (ADR-0003: a question about something else must not be answered). Recommend an amendment: the two employer classes apply only when the label names this employer (us, our, we, here, this/the company, the employer or an alias); otherwise AMBIGUOUS.
- **Fix:** move `THIS_EMPLOYER_RUNS` into `declarations` (it must not import `facts`, which imports it) and have `facts` import it from there. Use it in `classify_all`: a hit on `prior_employment_at_company` or `current_employee_at_company` counts only with an employer reference. Caution for the fix: the token "us" also matches the country, so "Have you worked for the US government?" and "worked with US clients" count as naming the employer in both `_names_employer` (`:270`) and `facts.THIS_EMPLOYER_RUNS` (`facts.py:591`). Match the lower-case word "us" against the raw label (`f.label`), not the lower-cased tokens.
- **Tester pins:** the four labels above → unknown/blank; "Have you previously worked for Acme?" and "Have you ever worked for us?" → filled by data.
- Not blocking by itself if the Coordinator records it as accepted risk (it is live today and not caused by this change), but it is the same class of defect as F1-F3 and the same function.

### F5 MEDIUM: the disability class answers questions that are not "do you have a disability", and a decline checkbox gets ticked
`declarations.py:544-560` (`_disability_answer`), `:520` (checkbox tick); phrases at `:152`.

- **Why:** the class is label-only but matches the word anywhere. The profile value `yes` is then written to any frame.
- **Failure scenarios (run):**
  - `us_self_id.disability_status: yes`: "Do you have a disability that would prevent you from performing the job?" gives **Yes**, which is not what the owner's answer means. "Do you require any accommodation for a disability during the interview?" gives Yes. With `no` both give No (benign), and with `decline` both end unknown.
  - `disability_status: no`: the single checkbox "I do not wish to disclose a disability" is **ticked** (`is_negated` flips "not"), declaring "I do not wish to disclose" when the owner's profile says No.
  - "Are you comfortable working with people with disabilities?" is a class hit (unknown only because the default is decline).
- **Fix:** for the "yes" value answer only a have-a-disability frame (see F1's status frame); for accommodation, prevent, limit, affect, perform and comfortable-working frames answer only when the value is "no", else unknown. A checkbox whose label has decline wording (do not wish, prefer not, rather not, decline, do not want) is ticked only when the value is None, and never from a polarity flip.

### F6 MEDIUM: the "whole words in the quote" path admits short and common-word skills from prose
`guards.py:658` (`ok = bool(names & known) or any(n and contains_run(ev, n.split()) ...)`).

- **Why:** `ground_items` keeps an item that is a whole word in the model's own quote. For names that are also ordinary words or letters, the quote can contain them without the skill.
- **Failure scenario (run, profile skills `C++, Python, .NET, Java`):** quote "Led the R&D team; go-to-market; Series C; excel in teamwork; Swift delivery of word-of-mouth" keeps items `R`, `Go`, `C`, `Word`, `Excel`, `Swift`. All six go onto a skills multi-select; none is a skill on the resume. G3 afterwards confirms the quote is in the resume, which it is.
- **Fix:** for items of two characters or fewer, or in a short stoplist (`go, r, c, word, excel, swift, spark, rust, scala, office, ruby, flask, dash, pandas`), accept only `names & known` (profile or attested skills), not the quote path. Optional: compare case-sensitively for single-token names.
- **Tester pin:** the quote above with items R, Go, C, Word, Excel, Swift → `[]`; "Built services in C++ and Python" with C, C#, Objective-C → `[]`; with Python → `[Python]`.

### F7 LOW: a compound question with an unclassified clause is answered for the classified clause only
`declarations.py:347` (`classify`).

- "Have you been convicted of an offence, or are you able to work night shifts?" gives **No** (`criminal_record`). The second clause is ignored. Rare label. Fix: with two or more question starters (or "and"/"or" joining a clause that has its own starter) and one class, return AMBIGUOUS.

### F8 LOW: an Answer note states the owner's disability choice
`declarations.py:556` note "disability: declined, no decline option".

- The note is stored with the attempt. "declined" is the S value of `disability_status`. Reword to "disability: no answer offered" (it needs no value). The other `_ended` notes are constants or the form label, which is public.

### F9 LOW: `deterministic_pick` accepts bare digits as a phone code
`llm_fill.py:587` (`_PHONE_CODE = ^\+?\s*(\d{1,4})$`), `:590-604`.

- With the `+` optional, wanted "65" and a lone option "Level +65 items" returns that option (run). Only a field with no exact option and a `+NN` in its text is exposed, so rare. Fix: require the `+` in `wanted`, or let the caller say the field is a phone-code field.

### F10 LOW: NS-exclusion logic exists twice with separate term lists
`declarations._ns_exclusion_spans` (`:241`) and `locks.strip_ns_exclusion` (`locks.py` +40 lines, `NS_TERMS`, `NS_EXCLUSION_LEADS`, `NS_EXCLUSION_TAILS`).

- Today the lists are equal. A future edit to one makes the resolver and the lock disagree on a question (one fails closed, the other answers). `locks` already imports `declarations`; reuse `declarations._strip_ns_exclusions` (make it public). No change in behaviour.

## Notes

- **Agreement with the architect's design:** D-87(4) and D-89 are built as written. F1-F5 are not deviations from §7.5 but gaps in it. The disagreement to log: the spec's phrase table has no frame, no employer condition and no field-type gate for tier 4, and its negation list is closed. The spec wins until amended, so the code fixes need a §7.5 / L7 amendment from the architect first (or in the same pass).
- **Suggested order:** F2 (small, central), F3 (list), F1 (frame set), F4 (employer reference, touches `facts` import direction), then F5, F6.
- **Open question for the Coordinator:** whether F4 is fixed with Q-48 or recorded as a known risk. It is live for Greenhouse today.

---

## Re-review (fix round, 2026-11-07)

VERDICT: MERGE (no CRITICAL or HIGH open; F1-F10 closed; D-90, D-90a and D-91 are built as specified, with the notes below; one MEDIUM and five LOW are non-blocking).

- **Target:** `eng/Q-48-declarations` at `1004247`. The fix round is `git log 3aadc13..1004247` (production: `2b43299`, `3d2eaf7`, `70eef15`, `8393f98`; test-only: `9adf10d`, `0c58ca2`, `76bcf13`; spec: `388e768`..`549e511`).
- **Method:** read `declarations.py` in full and the diffs of `locks`, `facts`, `guards`, `llm_fill`, `resolve`, `questions`, `applicant`, `contracts`. Then ran about 120 labels through the real resolver (`questions_support.resolve_one` with `config/questions.yaml`, the sample profile, employer "Acme", a `StubBackend` that recorded zero model calls on every one), plus direct calls to `ground_items`, `deterministic_pick`, `classify`, `names_this_employer` and `applicant.normalise`. The probe scripts are in the session scratchpad only.
- **Note on the file:** `docs/reviews/Q-48-and-lane-M-fixes.md` is not on this branch (it was committed on `personal` as `a856254`). Everything above this section is that commit verbatim, so the Coordinator can resolve the add/add by taking either side.

### Findings F1-F10

| Finding | Fix commit(s) | Closed? | Evidence (replayed on 1004247) |
|---|---|---|---|
| F1 HIGH willingness / consent questions answered "No" or ticked | `2b43299`, `70eef15` | **Closed** (gap: F11) | "Are you willing to sign a non-compete agreement?" -> unknown. Checkbox "I have read the confidentiality agreement and have no questions" and "I have no objection to signing the NDA" -> unknown, not ticked. Checkbox "I am not bound by any non-compete" -> still ticked. NDA labels are now class `nda_willingness` (D-91) and read only `declarations.willing_to_sign_nda`: true -> Yes, false -> No, unset -> unknown (required) / blank (optional), never from `non_compete`. "Are you comfortable signing an NDA?" and "Any objection to signing an NDA?" -> unknown under all three values. |
| F2 HIGH declaration "No" typed into an essay box | `2b43299` | **Closed** | All five review labels as TEXTAREA (required and optional) -> unknown / blank, note "not a yes/no question". "Why do you want to join the public service?" as TEXT -> unknown (willingness `want`). "Are you a politically exposed person?" as TEXT -> still "No"; as TEXTAREA -> unknown. Lock L3 runs the same `answer()` (pin `test_f2_pin_lock_l3_leaves_an_essay_box_alone`). MULTI_CHOICE -> unknown. |
| F3 HIGH unlisted negation inverts the answer | `2b43299`, `3d2eaf7` | **Closed** | One list (`declarations.NEGATIONS`) holds all the review's additions plus contractions. The four review labels now answer **Yes** (non_compete / conflict false) through the D-91 freedom forms, which is the review's "Correct" column. "Are you without any non-compete agreement?" -> unknown. "Are you bound by any non-compete?" -> No. `locks` keeps no working copy (stale constant: F14). |
| F4 HIGH employer classes answer questions that name another company | `2b43299`, `70eef15` | **Closed** | "Have you worked with government clients?", "...for a startup before?", "...in a bank?", "Are you a current employee of a government-linked company?", "Have you previously worked for Globex?" -> unknown. "Have you previously worked for Acme?", "...for us?", "Have You Worked For Us Before?", "Have you worked here before?", "...for Acme Pte Ltd?" -> filled by data. **US rule:** "Have you worked for the US government?" and "...for US companies?" -> unknown (`names_employer` tests the raw label for `\b[Uu]s\b`, so upper-case "US" is the country); `classify` without a raw label counts "us" (the conservative side) and `answer()` re-checks with the real label. The check runs in `classify_all` (callers with names) and again in `answer()` (callers without), so no path skips it. |
| F5 MEDIUM disability frames and decline checkbox | `2b43299` | **Closed** | With `disability_status: yes`: "...disability that would prevent you from performing the job?" and "...accommodation for a disability during the interview?" -> unknown (were Yes). "Are you comfortable working with people with disabilities?" -> unknown. Checkbox "I do not wish to disclose a disability" -> unknown under yes, no and decline (never ticked). "Do you have a disability?" -> Yes / No / decline option as before. Disability in TEXTAREA or MULTI_CHOICE -> unknown. |
| F6 MEDIUM short / common-word skills grounded from prose | `2b43299` | **Closed** (edge: F15) | `ground_items(["R","Go","C","Word","Excel","Swift"], <review prose>)` -> `[]`; `["C","C#","Objective-C"]` on "Built services in C++ and Python" -> `[]`; `["Python"]` -> `["Python"]`; a real skills line "Skills: Python, R, Go, Excel" keeps R, Go and Excel. |
| F7 LOW compound question | `70eef15` | **Closed** | "Have you been convicted of an offence, or are you able to work night shifts?" -> AMBIGUOUS (unknown). Two-class compounds stay AMBIGUOUS. (The first handoff said F7 was backlog; `70eef15` built it.) |
| F8 LOW note stated "declined" | `2b43299` | **Closed** | Note is now `disability: no answer offered`. Every `_ended` note is a constant, a class name or the public label; the agreed note is `agreed: <class names>`. |
| F9 LOW bare digits as a phone code | `2b43299` | **Closed** | `_PHONE_CODE = ^\+\s*(\d{1,4})$`. `deterministic_pick("65", ["Level +65 items","Other"])` -> `None`; `("+65", ["Singapore (+65)","Other"])` -> `Singapore (+65)`; `("65", ["+65","+1"])` -> `None`. |
| F10 LOW NS-exclusion logic twice | `2b43299` | **Closed** (stale constant: F14) | `locks.strip_ns_exclusion = declarations.strip_ns_exclusions`; the `NS_*`, `ANSWER_HINTS` and `_negated` copies are deleted from `locks`. |

### D-90 / D-90a / D-91 against the spec

- **Gate 1 (field type):** DROPDOWN/RADIO/single CHECKBOX; TEXT/TYPEAHEAD only with a question-starter first token; TEXTAREA, MULTI_CHOICE and every other type end unknown / blank with note "not a yes/no question". Matches §7.5 gate 1 and D-90a.
- **Gate 2 (willingness / status):** matches the spec lists, with two deviations on the safe side (F12, F13). `know` and `aware` are correctly absent. A decline-wording checkbox is never ticked.
- **Gate 3 and the D-91 freedom forms:** condition (i) (the run is the only NEGATIONS hit, after the NS strip and the answer-hint strip) and condition (ii) (every matched phrase follows the run with no second clause starter or "i am" / "i have" between) are implemented in `_freedom_inverts`. Verified: "free from X and not bound by Y" -> unknown (two negations); "Are you free from restrictions? Do you have a non-compete?" -> unknown (second clause); "Have you ever not been bound by..." -> unknown; "Is there anything free from conflict of interest, and are you a politically exposed person?" -> unknown. Inversion is right for `non_compete` and `government_employment` (owner `government_employment: false`: "Are you free from any government employment?" -> Yes; with true -> No). Single checkbox: "I am free from any restrictive covenants" is ticked only when the declaration is false; required with value true -> unknown. A multi-class freedom question is unknown (the agreement path passes no class), the safe reading.
- **Gate 4 (employer):** see F4. D-89 runs first (the government overlap drop is skipped only when the label names the employer); "Have you ever worked for the government?" -> No.
- **Gate 5 (disability frames):** see F5. Deviation: a bare "Disability" label on a Yes/No passes `classify_all` (3 tokens or fewer) but fails the bool frame check, so it ends unknown (F13).
- **D-91 with the owner values to come** (`government_employment: false`, `willing_to_sign_nda: true`): "Are you willing to sign an NDA?", "Do you agree to sign our confidentiality agreement?", "Will you comply with our confidentiality obligations?" -> Yes; checkbox "I agree to sign the NDA" -> ticked; "Are you bound by an NDA?" -> No (non_compete false); non-compete willingness -> unknown. `applicant.normalise`: true / "yes" -> True, "no" -> False, "nil" / "NA" / "n/a" / "Not applicable" -> None (unset), absent -> key not created; `""` and `"maybe"` stay strings and `truth()` reads any non-bool as unset (unknown), so a typo fails closed. `non_compete` still reads "nil" as false.
- **No path types a declaration into a textarea or ticks a decline checkbox:** probed disability, health, NDA and class labels on TEXTAREA and CHECKBOX under every profile value. A checkbox is ticked only through `attestation_polarity`, a freedom run, or the D-91 consent box.
- **Privacy and safety:** no model call on any probe (`StubBackend.calls == 0`); notes carry no S value; a scan of the added lines (emails, `+65` numbers, password assignments, captcha terms) found nothing; the diff touches no click, submit, upload or captcha code; `tests/test_layering.py` 10/10.

### Test-only commits

- **`9adf10d` (prior-employment pin): follows the spec and strengthens the test.** The old line asked "Have you previously worked for Example Logistics?" with employer Dataiku and expected "No", which is exactly review F4's failure. The new pin asks a label that names Dataiku -> "No", asserts the other-company label is **not FILLED**, and keeps the alias and internship assertions. No weakening.
- **`0c58ca2` (sample fixture gains `willing_to_sign_nda: false`): follows the spec text; the spec itself is inconsistent here (F16).** It satisfies `test_sample_applicant_has_exactly_the_design_template_keys` against the AD §5.4 template, which has `false`. No pin depends on the key being absent (the review tests `pop` it explicitly for the unset cases). With the fixture at `false`, default-sample NDA willingness labels answer "No" rather than unknown, which is what `false` means.
- **`76bcf13` (F17 pin uses "without"): follows the spec and does not weaken.** "free of" is now a D-91 freedom form, so the old label must answer Yes. The pin keeps its both-paths-unknown intent with "without", and the freedom behaviour is pinned separately (`test_d91_pin_a_freedom_form_answers_the_inverted_value`, `test_d91_pin_a_double_or_other_negation_stays_unknown`, `test_f3_a_plain_status_question_is_still_no`). I confirmed the same behaviour by replay above.

### New findings

**F11 MEDIUM (non-blocking; fix before the owner's `willing_to_sign_nda: true` is used on a real submit, or accept the risk): `nda_willingness` answers a compound consent question for the NDA part only.**
- `declarations._nda_consent` (`:508`); `_compound_unclassified` (`:490`) cuts only on "and/or + starter + pronoun".
- Scenario with the owner value true: "Are you willing to sign an NDA and relocate to Tokyo?" -> **Yes**; "Are you willing to sign an NDA and work night shifts?" -> **Yes**; checkbox "I agree to sign the NDA and to a background check" -> **ticked**. The program claims a willingness it does not hold. With the sample value (false) the dropdowns answer No and the box stays unticked, so the exposure begins when the owner's `true` is written.
- Fix: in `_nda_consent`, return False (-> unknown) when "and" / "or" / a comma after the NDA object or consent verb joins anything outside a small closed vocabulary (agreement, obligations, confidentiality, our, the, a, this, employer, company, terms). Equivalent: require every label token to be in {frame words, NDA object words, filler}. Pins: the three labels above -> unknown / not ticked for `true`; the three D-91 examples still Yes.
- Spec: D-91 says nothing on compounds; the F7 rationale (do not answer one clause of a compound question) covers it. Add one line to §7.5.

**F12 LOW: the freedom path skips the status-frame gate.** `_bool_answer` (`:822-825`): a negated label that `_freedom_inverts` goes straight to `fit_bool` without `_status_frame`. "Confirm you are free from any restrictive covenants" and "Free from any restrictive covenants?" -> Yes. The answers are true, but §7.5 gate 2 says "confirm" is neither willingness nor status, so the spec would give unknown. Apply `_status_frame` there, or amend gate 2 to exempt freedom forms.

**F13 LOW (spec-conformant regression; disclosed by the engineer): noun-phrase and prefixed labels that used to answer "No" now go to the inbox.** `_status_frame` (`:602`) checks the first token (after "please" / "kindly") plus a short run list. So "Politically exposed person (PEP)?", "Criminal record", "Non-compete agreement?", "Please indicate if you have ever been bankrupt", "Declaration: Are you a politically exposed person?", "Note: Do you have a non-compete?", "Please confirm: Are you a PEP?" and a bare "Disability" on Yes/No all end unknown ("not a status question"). A required one stops the attempt once; the owner answers it and tier 3 `extra` remembers. The spec wins (gate 2 requires a frame), but the spec's frame runs (`are you`, `have you`, `do you have`, `i am`, `i have`) read as "anywhere in the label" and the code anchors at the start. Suggest the architect confirm; if wanted, accept those runs anywhere (the willingness exclusion still applies) and decide whether a Yes/No label that is only a class phrase (4 tokens or fewer, no willingness word) may answer. Fail-closed, so not blocking.

**F14 LOW: dead copy `locks.NEGATIONS`** (`locks.py:54`, the old 7-entry list, referenced nowhere). §7.5 says `locks` keeps no copy of the lists. Delete it so nobody reuses the short list.

**F15 LOW: two residual edges.** (a) A comma list in prose still passes the short-skill rule: `ground_items(["C"], "Raised Series A, B, C")` -> `["C"]` (the list test sees three parts). (b) All-caps labels ("HAVE YOU PREVIOUSLY WORKED FOR US?") read "US" as the country -> unknown (fail-closed; "Us" and "us" work).

**F16 LOW (spec inconsistency; the architect to amend): `willing_to_sign_nda` default and the consent-verb list.** AD §5.4 template (line 377) says `willing_to_sign_nda: false` and §7.5 (line 578) says "(bool, default false)". `config/applicant.example.yaml`, `applicant.py` ("never defaults to false"), `truth()` and the tester's pins treat **unset as unknown**, the safer reading, which I reviewed against. Also D-91's verb list names `comfortable`, `happy to`, `open to`, while D-90a (and the pin `test_d90a_pin_comfort_and_familiarity_questions_are_not_answered`) says "Are you comfortable signing an NDA?" ends unknown; the code follows D-90a. The software-engineer's 2026-11-02 handoff reads D-91's list the other way; the code does not. The spec wins until amended, and both code behaviours are fail-closed, so I did not count them against the build.

### Regressions checked

- Still correct: every pre-D-87 class on a status question ("Have you ever been convicted...?", "Are you a politically exposed person?", relatives, shareholding and previously-applied labels that name Acme), the NS-excluded military question, the long F1 non-compete label, and the checkbox attestations "I declare that I am not a politically exposed person", "I confirm I have no conflict of interest", "I have never been convicted of a criminal offence".
- Moved to unknown (all fail-closed): noun-phrase and prefixed labels (F13); employer-class questions that name no employer ("Are you a former employee?").
- One behaviour change outside the tier: `guards._keep_field` and the capture checks now see AMBIGUOUS (not PRIOR_EMPLOYMENT) for a prior-employment question that names another company, so a MyGreenhouse prefill for it is no longer discarded as "employer-specific". That value is the owner's own stored answer to a question that is not about this employer, so I treat it as acceptable.

### Tests (run from this worktree at 1004247; the full suite was not run, per the brief)

| Command | Result |
|---|---|
| `python tests/run_tests.py -k declarations` | `40/40 passed  (-k 'declarations')` (q48 16/16, review 22/22, contracts 2/2) |
| `python tests/run_tests.py -k apply_contracts` | `66/66 passed  (-k 'apply_contracts')` |
| `python tests/run_tests.py -k llm_fill` | `74/74 passed  (-k 'llm_fill')` (includes the F6 and F9 pins) |
| `python tests/run_tests.py -k layering` | `10/10 passed  (-k 'layering')` |

### Next steps

1. Merge into `int/Q-35-M` as is. After the merge to `personal`, smoke the Profile "Application details" tab: `willing_to_sign_nda` must show as a tri-state (unset / Yes / No) before the owner edits that tab, or the SPA could save "unset" as false (engineer request (2) in `comms/outbox/software-engineer.md`). I did not check the web code or run the SPA. Write the owner's two values by the surgical replace.
2. Queue F11 (engineer plus a tester pin), with F12 and F14, before the first real submit on a form with an NDA question. F13, F15 and F16 go to the architect (compound NDA rule; frame runs anywhere or noun-phrase labels; `willing_to_sign_nda` unset semantics; D-91 vs D-90a verb list).
