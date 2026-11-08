# VERDICT: MERGE (Q-82 declarations: D-170 one status question per label)

Branch `eng/Q-82-declarations` @ 31e3f48, base `personal` c71de7e. Reviewer: independent, KA-2. Read: `apply_design.md` §7.5 (D-170 block and oracle table, D-164, D-166, D-169b), `docs/reviews/Q-80-declarations.md`, `git diff c71de7e..31e3f48 -- src/ tests/`. No CRITICAL or HIGH finding. All 20 Q-80 over-answers are now unknown. Four MEDIUM findings (one for over-answering location/state claims, one for under-answering, two smaller over-answer classes); none is a regression against `personal`, and every over-answer below pre-dates D-170. Replays used `declarations.classify` + `answer` (employer Acme, sample profile, every declaration false, `disability_status: no`, Yes/No dropdown unless stated) against a `git archive` of c71de7e ("base") and the branch ("new"). Scripts stayed in the session scratchpad.

## 1. Check 1: the Q-80 over-answers

All 20 are `unknown` now (19 labels, plus the checkbox "I am not bound by any non-compete and I can relocate" not ticked; "Important: Do you have a criminal record check?" as dropdown and as TEXT). The "keeps its answer" rows still answer: Please state your bankruptcy status / Non-compete status / Let us know if you were a politically exposed person / Specify if you have a criminal record and the offence / Criminal record, bankruptcy / Question: criminal record history / Self declaration: criminal record / Please confirm: Are you a PEP? / Can you confirm you are clear of any conflict of interest? (Yes). "Criminal record check", "PEP screening?", "Disability insurance?", "Bankruptcy court experience?" stay unknown. The spec's vocabulary counts match the code (72 shared; 10/11/25/13/20/47/12/9 per class = 147).

## 2. Check 2: under-answering (D-170 turned an answer into unknown; base answered No)

About 120 ordinary labels replayed (Greenhouse, Workday, Lever, bank and audit-firm styles). Most standard forms still answer No: convicted of a criminal offence/offense/felony, pending criminal charges, criminal conviction(s), declared bankrupt / bankrupt or insolvent, bound by or subject to a non-compete (about ten phrasings), relatives or family working at Acme, disability (with `disability_status: no`), employed by Acme, previously applied, PEP forms, government employee/official (most), regulatory or disciplinary action, conflict of interest. Labels that go unknown only through D-170 and that the owner would want answered (D-87):

| Label | New | Base | Correct? |
|---|---|---|---|
| Have you ever been convicted of a crime? If yes, please provide details. | unknown | No | NO, under-answered |
| Do you have a criminal record? If yes, please provide details. | unknown | No | NO |
| Have you ever been convicted of a felony? If yes, please explain | unknown | No | NO |
| Are you currently bound by a non-compete agreement? If yes, please specify. | unknown | No | NO |
| Have you ever been convicted of, or pleaded guilty to, any criminal offence? | unknown | No | NO ("pleaded") |
| Have you ever been convicted of a criminal offence or pleaded guilty to one? | unknown | No | NO |
| Have you ever been convicted of a crime (excluding minor traffic offences)? | unknown | No | NO ("excluding", "minor", "traffic") |
| Have you ever been convicted of a criminal offence (other than a minor traffic violation)? | unknown | No | NO |
| Have you ever been convicted of a criminal offence, other than a minor traffic offence? | unknown | No | NO |
| Have you ever been convicted of a criminal offence in the last 12 months? | unknown | No | NO ("months" is not filler, "years" is) |
| Are you, or have you been in the last 12 months, a politically exposed person? | unknown | No | NO |
| Are you a current or former government official? | unknown | No | NO ("current", "former" are non_compete filler only) |
| Have you ever filed for bankruptcy? / ...filed for personal bankruptcy? | unknown | No | NO ("filed") |
| Have you ever been adjudged bankrupt or entered into an individual voluntary arrangement? | unknown | No | NO |
| Do you have any unspent criminal convictions? | unknown | No | NO ("unspent") |
| Are you currently under investigation for any criminal offence? | unknown | No | NO |
| Has your professional licence ever been revoked or suspended? / Have you ever had a professional licence suspended or revoked? | unknown | No | NO ("licence", "suspended") |
| Have you ever been disciplined by any professional regulatory body? | unknown | No | NO ("disciplined") |
| Are you party to any agreement that restricts your ability to work for Acme? | unknown | No | NO ("ability", "work") |
| Are you aware of any conflict of interest that may arise from your employment at Acme? | unknown | No | arguable ("arise", "employment") |
| Have you ever been convicted of a crime involving dishonesty? / debarred by any government agency? / Do you have any financial or business relationship with a client of Acme that could affect your independence? / Are you a senior political figure? | unknown | No | acceptable (a second concept, or not the class) |

Counted: 25 labels newly unknown; about 20 of them should still answer, 5 are acceptable or arguable. Unknown at base too and unchanged (classification, not D-170): "Are you a politically exposed person or related to one?" and "...or a close family member or associate of one?" (two questions; unknown is right), "Do you have a disability or long-term health condition?", "Have you ever been employed by a public body or government agency?" (AMBIGUOUS), "Are any of your relatives currently employed by Acme?", "Do you or any of your family members own shares in Acme?". Six more ("found guilty of a crime", "court order or injunction", "refused entry or deported", "dismissed or asked to resign", "disqualified as a director", "outstanding legal proceedings") are not classified as declarations at all.

## 3. Checks 3 and 4: fresh adversarial labels and the vocabularies

About 55 fresh labels. Held (unknown): "Do you have a non-compete agreement and will you join Acme?" (AMBIGUOUS before D-170), "Are you a PEP and do you hold any position at Acme?", "Have you ever been convicted of a crime and are you currently in Singapore?", "Are you a government employee or a member of a union?", "Is any person you know a PEP?", "Does any person have a criminal record?", "Are you currently in a country where you are a PEP?", "Are you aware that you are a PEP?", checkboxes "I have never been declared bankrupt and I will join Acme" and "I confirm that I have no criminal record and am working in Singapore". The words you named ("and" alone, "check", "lawyer", "relocate", "screening", "right", "eligible", "visa", "able") are each excluded or caught by rules 1 and 3. D-170 also closed six of my probes that base answered. Wrong answers (all also answered at base; D-170 makes none worse):

| Label | Answer | Correct? |
|---|---|---|
| Are you a politically exposed person or currently in Singapore? | No | NO, second clause |
| Are you a politically exposed person or currently overseas? | No | NO |
| Have you been convicted of a crime or been in Singapore for the past year? | No | NO |
| Do you have a criminal record or any status in Singapore? | No | NO |
| Are you bound by a non-compete or working in Singapore? | No | NO |
| Do you have a non-compete agreement or a current role in Singapore? | No | NO |
| Are you a government employee or currently working in Singapore? | No | NO |
| Have you worked for the government or worked in Singapore? | No | NO |
| Do you have a disability or identify as living in Singapore? | No | NO |
| Checkbox "I confirm I am not a PEP and am currently in Singapore" | ticked | NO (a signed statement that covers a second claim) |
| Checkbox "I am not a PEP and I am aware of the status" | ticked | NO |
| Checkbox "I have no criminal record and I am in Singapore" | ticked | NO |
| Checkbox "I am not bound by a non-compete and I am currently in Singapore" | ticked | NO |
| Checkbox "I am not subject to any non-compete or working in Singapore" | ticked | NO |
| Are other people politically exposed persons? / Are any people politically exposed persons? | No | NO, subject is not the applicant |
| Is the person politically exposed? | No | NO, same |
| Are you aware of any politically exposed persons? | No | NO (the applicant's knowledge of others) |
| Are you aware of any criminal convictions against Acme? / ...bankruptcy proceedings against Acme? / ...the criminal record status of Acme? | No | NO (knowledge of others) |
| Is there a criminal record? | No | arguable |
| Do you hold shares in this company and a valid visa? / Do you have any relatives at Acme and a valid work permit? | No | NO (employer class; the D-170 block records this residual) |

Count: 21 wrong or arguable answers (14 from location/state words, 5 from subject or knowledge shifts, 2 recorded residuals), 17 right refusals.

## 4. Findings

### MEDIUM-1: location and state words in SHARED_FILLER let a second claim through (dropdown and checkbox)
- Where: `declarations.py` `_STATUS_FILLER` (singapore, country, countries, jurisdiction(s), elsewhere, overseas, anywhere, currently, now, still, aware, status, subject, i, you) with `_one_status_question` rules 1 and 3.
- Scenario: rule 1 sees only listed words, and rule 3 cuts only before `and`/`or` followed by a starter, so "or currently in Singapore" is not a cut at all. "Are you a politically exposed person or currently in Singapore?" → No. The checkbox "I am not bound by a non-compete and I am currently in Singapore" is ticked: a signed statement that asserts where the owner lives. Rule 3's "bare lead-in" exception (a piece made only of SHARED_FILLER) also lets "and I am in Singapore" through on a checkbox. This is Q-80 MEDIUM-1 narrowed, not closed: the spec says "a second clause about something else fails the same way", which holds only when the clause contains a word outside the vocabulary.
- Fix: location words are legitimate only as a qualifier after a class phrase ("convicted in Singapore or elsewhere"). After the first class span, require an `and`/`or` to be followed by another class span, a status run, or only a location tail (`in|within|of|from` + `any|the|other` + a location word). For a checkbox (rule 5), drop the all-SHARED piece exception or limit it to at most 4 tokens from {are, you, have, been, ever, i, am}. One pin per row above. Not blocking: no real form I know writes these labels, and base answered all of them.

### MEDIUM-2: under-answering on the commonest real suffixes (owner intent D-87)
- Where: the closed vocabulary. Missing: a trailing "If yes, please provide details / explain / specify" (the commonest suffix on Greenhouse and Workday dropdown labels), "pleaded", "excluding", "other than", "minor", "traffic", "months", "filed", "licence", "suspended", "disciplined", "current/former government official", "unspent", "under investigation".
- Scenario: each costs the owner one answer in the Questions inbox (tier 3 then reuses it). Not unsafe, and the spec accepts it ("an unseen word costs one answer"), but D-87 says declarations are answered, never asked. About 20 ordinary labels in section 2.
- Fix (follow-up; spec change and pins): (a) strip a trailing `if yes ...` / `if so ...` / `if applicable ...` tail in `question_frame` and `_one_status_question` like an ANSWER_HINT; this is the single largest gain. (b) Add to the class fillers: criminal_record: pleaded, unspent, minor, traffic, violation, violations, excluding, other, than; bankruptcy: filed, personal, insolvent, insolvency, voluntary, arrangement; regulatory_disciplinary: licence, license, suspended, disciplined; government_employment: current, former; shared: month, months. None opens a second clause.

### MEDIUM-3: subject shift and knowledge-of-others pass
- Where: shared "other", "any", "the", "aware", "against", pep filler "person(s)/people/individual"; shape A starts on `are/is`.
- Scenario: "Are other people politically exposed persons?" → No (a question about someone else). "Are you aware of any criminal convictions against Acme?" → No (D-90a keeps "aware" on purpose for "aware of any conflict of interest", but the employer span plus "against" extends it to knowledge of third parties).
- Fix: for `is/are/does/do` with a next token other than `you`, `i`, `there`, `any` + class span, fail rule 1; drop `against` when an employer span follows. Optional; pre-existing.

### MEDIUM-4: the employer-class compound residual still answers ("Do you hold shares in this company and a valid visa?" No)
- The D-170 block records it ("Residual (recorded, not fixed)"). Noted here because it breaks the one-answer-per-clause rule for five employer classes. A cheap close: run rules 1 and 3 for the employer classes with their phrase spans and the employer reference. Not blocking; contradicts nothing in the spec.

### LOW
- LOW-1: `answer(None, ...)` raises on a non-declaration label (replay harness only, as in Q-80; production callers classify first).
- LOW-2: `question_frame` gained `employer_names=()`; `locks._declaration_lock` reaches it through `answer()`, so there is still one implementation (grep over `src/`: no other caller).

## 5. Other review lines
- Fail closed: every new branch returns False on doubt; a failed helper falls to shape C and then "not a status question" (no new reason code). No new write without a matched class and the field gate. No CAPTCHA, secret or data handling touched. No personal data in the diff (labels generic, employer "Acme"; `tests/test_apply_declarations_d170.py` is generic too).
- Layering: no new import (`re` was already there); `test_layering` 13/13.
- Spec vs code: the oracle rows and vocabulary counts agree with the code; no disagreement found. The one wording that does not hold is in MEDIUM-1 above.

## 6. Test lines
- `python tests/run_tests.py -k declarations` → `87/87 passed  (-k 'declarations')` (one oracle test waits for WP-N6b, unrelated)
- `python tests/run_tests.py -k apply_contracts` → `66/66 passed  (-k 'apply_contracts')`
- `python tests/run_tests.py -k llm_fill` → `90/90 passed  (-k 'llm_fill')`
- `python tests/run_tests.py -k layering` → `13/13 passed  (-k 'layering')`
- No full suite (per delegation; it was 1487/1487).
