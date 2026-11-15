# Code review 2: Q-121 Amendment A1 (the rebuilt answering rules), `int/Q-121` @ 743a06d

Reviewer, 2026-11-14. Scope: `git diff 4f9aac7..int/Q-121 -- src/jobscraper/apply/always.py briefing.py facts.py` (plus `pagefill.py` `always_row_decision`, the only `src` change after 301e908), read around the diff. Checked against `docs/architecture/llm_first_fill_design.md` §17, `docs/reviews/Q-121-always-code.md` (review 1), `docs/reviews/Q-121-A1-design.md`, the Coordinator's rulings and the engineers' handoffs (claims). Every finding below was reproduced with a stdin script on the tests' `FakeAsk`, `_pf` / `llm_fill_t2` builders and the dummy sample profile (employer "Example Employer"): no model, no network, no browser, no server, no apply job, no `data/`, no `.env`. The probe scripts are in the scratchpad, not in the repo. Notation: a probe cell writes the shown value; `~` = marked assumed; `!!` = the written value states an adverse declaration / opts in / is an unverified fact.

## Verdict

**NOT READY for the dress rehearsal as built.** The amendment does what it set out to do for the two review-1 problems: **H1 is closed** (no ordinary question gets a consent value, in all four model conditions), **H2 is closed** for every row of review 1 and for the design review's tick-if rows, **H3 and M1-M8 are closed** for the wordings of those reviews (tables in section 1). One key alone never writes code's value (section 3). But three HIGH findings remain, each with a small fix, and each is a place where the new rules still write the wrong thing with the model correct or with a single wrong key:

- **H1** a single stray negation word anywhere in a declaration question ("... Please do not include spent convictions", "(not including minor traffic offences)", "that is not yet spent") makes the reader invert the whole question; with both keys right, code overwrites the **correct** model "No" with **Yes** (an adverse declaration, assumed). "Is anything stopping you from declaring that you are not bankrupt?" does the same (the implicit-negator list has no inflections).
- **H2** with H unknown the confirmation pick is written when it differs from the model's first answer, **even when the model's first answer was right**: a flip writes the adverse option.
- **H3** the owner-fact code key for address / postal code / phone / age / salary / grade is far too wide and writes the applicant's own value over a **correct ordinary** answer, unmarked: the employer's address in a work-experience entry, "Company phone", "Age at graduation", "Pay grade of the role".

I do not count the rest (MEDIUM/LOW below) as blocking. Fix H1-H3, add pins for every table row, then the dress rehearsal is the right next step. All of this is a matter of the model doing something unlucky or of a particular wording; none is a case where a healthy model on an ordinary English form misbehaves, except H3 (code alone) and the over-protection in M1.

## Evidence run (this worktree, merged to 743a06d)

`python tests/run_tests.py -k always_a1` 119/119 (4 files). `-k facts` 19/19. `-k llm_fill` 100/100. `-k layering` 13/13 (all at 301e908; always.py, briefing.py, facts.py unchanged since). `-k always` at 301e908: 276/296, the 20 reds are the stale pins the tester has since retargeted (coordinator: 300/300 at 743a06d); the one red I saw in full, `plain consent` ("Yes ... assumed=True ... check: consent_privacy (a default, not set in your profile)") is the engineer's stated change (§17.2 acknowledgement of anything but a privacy notice follows `certify_true`, D5 default assumed); I judge it stale, not a regression. `-k declarations` at 301e908: 194/195, the one red is `Please be advised that we process your data. Do you acknowledge?` and `Do you confirm that you have read the above?` -> `'No' source=fallback:F2` (silent model). That one is a REAL (small) behaviour change, see L3. `-k pagefill` 22/22 at 301e908; the post-merge run of `-k always_a1`, `-k pagefill`, `-k declarations`, `-k layering` is quoted at the end if it finished before commit.

## Findings

### HIGH (block the dress rehearsal)

**H1. One negation word anywhere in the label inverts a declaration question; with both keys right code overwrites the correct "No" with "Yes".** `always.py:1771-1787` (`_as_asked`: `n == 1` -> `negated_question` -> `(not truth)`), used by `_decl_applies_yes` (2454-2458), `_declaration_rule` (2495-2498, T's option) and `_decl_in_h` (2534-2539, H). `IMPLICIT_NEGATORS` (1927-1929) is a literal word list without inflections and `implicit_negated` (2051-2055) counts "two negations" only. The reader's own docstring (`declarations.py:791-797`) says a negated Yes/No question "is not mapped to a bool (ends unknown, never inverted)"; `_as_asked` inverts instead. Same on `4f9aac7` (the S1 reader was kept by §4.2/§17.6), so review 1 and the design review missed it; it is exactly what A1's both-keys override makes dangerous.

Probe (radio Yes/No, sample profile, every declaration false; R = model right "No", class right; W = model "Yes", class right; O = class forced `ordinary`; M = class missing):

| Question | R | W | O | M |
|---|---|---|---|---|
| Have you been convicted of an offence that is not yet spent? | **Yes~** | Yes | **Yes~** | **Yes~** |
| Have you ever been convicted of a criminal offence? Please do not include spent convictions. | **Yes~** | Yes | **Yes~** | **Yes~** |
| Have you ever been convicted of a criminal offence (not including minor traffic offences)? | **Yes~** | Yes | **Yes~** | **Yes~** |
| Have you ever been convicted of a criminal offence? (Do not answer yes for traffic offences) | **Yes~** | Yes | **Yes~** | **Yes~** |
| Have you ever been declared bankrupt and not been discharged? | **Yes~** | Yes | **Yes~** | **Yes~** |
| Are you currently a politically exposed person? Note: do not answer for family members. | **Yes~** | Yes | **Yes~** | **Yes~** |
| Is there any reason you could not work for us, such as a criminal conviction? | **Yes~** | Yes | **Yes~** | **Yes~** |
| Is anything stopping you from declaring that you are not bankrupt? | **Yes~** | Yes | **Yes~** | **Yes~** |

In the R cells the model is right and code writes the adverse option; in the O/M cells the inverted H lets the model's wrong Yes through as "not adverse". Failure scenario: a UK-style "(do not include spent convictions)" tail on a criminal-record question; the owner's application states a conviction. "Do not include ..." tails and "not including / that is not ..." clauses are on a few percent of real criminal-record, bankruptcy and PEP questions. Unit coverage: none of the 119 pins has a negation word that is not a negation of the status.

**Smallest fix.** In `_as_asked(statement=True)`: invert only for a whitelist of subject-negation frames at the start of the question (`^(have|are|do|does|did|is|was|were) you (never|not|no)\b`, `^is it true that you (have )?(no|never|not)\b`); with any other negation run return `None` (H unknown, never inverted), as the reader's docstring already promises. Make `IMPLICIT_NEGATORS` inflection-proof (match stems: prevent*, stop(s|ping|ped) you, den(y|ies|ied|ying), fail*, unable). Pin the table above.

**H2. With H unknown the confirmation pick is written when it differs from the model's first answer, whether or not that answer was right.** `always.py:3688-3689` (`confirm_class`: `ok = h is False or (h is None and bool(refused) and _norm(pick) not in refused and not decline)`), `st.refused` is the model's value set at 3041 whenever the veto fires, adverse or not. Engineer's departure (2)/(3); §17.1 allows a confirm pick only "outside a **known** H". The Coordinator's ruling: an adverse declaration is never written, assumed or not. Probe (scripted pick that flips; a real model flips sometimes, the same 14B reading a label it already misread):

| Question (options) | Model (right) | Confirm pick | Written |
|---|---|---|---|
| Criminal record (Yes/No) | No | Yes | **Yes~** "the AI's answer was not used; the check picked Yes" |
| Bankruptcy (Yes/No) | No | Yes | **Yes~** |
| Politically exposed person (PEP) (Yes/No) | No | Yes | **Yes~** |
| Do you deny that you are a politically exposed person? | Yes | No | **No~** (claims PEP) |
| Es-tu une personne politiquement exposee ? (Oui/Non) | Non | Oui | **Oui~** |

H is unknown for exactly these (noun-phrase labels, implicit negator, non-English: see M1). With a truthful confirm pick equal to the model's answer the field ends empty (safe); only a flip writes, and a flip is as likely to be adverse as correct. **Smallest fix.** For `declaration`, `work_right`, `sponsorship`, `self_id` write a confirm pick only when `in_h(...) is False` (H known); with H unknown go to the protective end (the none-applies option when the reader is confident, else empty). Add the five rows as pins.

**H3. The owner-fact code key writes the applicant's own value over a correct ordinary answer, unmarked.** `always.py:2111-2148` (`fact_which`: address / postal code / phone, age 2135, salary 2133, grade 2131) and `protective_end` 3754-3770 (`code_key_fact` -> `_fact_fill` copies the profile value, `fallback=F1`, **not assumed**). C2 of the design review narrowed address / postal code / phone by field type and by a deny-list of words (email, url, country ...), but not by *whose* address it is. Probe, model right and class `ordinary` (correct ordinary answers shown as "model"):

| Field (TEXT unless noted) | Model | Written |
|---|---|---|
| Company address / Employer address | 1 Raffles Quay | **1 Example Road** (profile home address) |
| School address / Address of institution | 50 Nanyang Avenue | **1 Example Road** |
| Employer phone number / Company phone | 65551234 | **91234567** (profile phone) |
| School contact number | 67901234 | **91234567** |
| Employer postal code / Postal code of company | 048583 | **000001** |
| Age at graduation / Age of your oldest project / Age limit you are comfortable with | 23 / 3 / none | **24** (the applicant's age) |
| Mobile phone model / Phone brand you use | iPhone 13 / Apple | **91234567** |
| Street you grew up on | Orchard | **1 Example Road** |
| Pay grade of the role | E3 | **4.20 / 5.00** (the GPA) |
| Salary range of the role you applied for | 3000-4000 | **5000** (expected salary) |
| Salary of your last internship | 1200 | N/A~ |

Inside a work-experience entry group (`group="experience[0]"`, title "Work experience") the generic labels **"Address", "Phone number", "Postal code"** get the home values the same way (model correct, basis resume): `'1 Example Road' source=profile:contact.address_line1 note='F1 address'`, `91234567`, `000001`, not assumed, so the owner is never told. `facts.in_entry_section` (Q-46 a) already exists for exactly this and the strict `relevant` uses it. Failure scenario: an employment-history block with "Employer address" / "Employer phone" on a local corporate or public-sector form (about 1 in 8-10 of those; rare on Workday / Greenhouse) writes the applicant's home address and phone as the employer's. **Smallest fix.** In `fact_which`: return "" for address / postal code / phone / age / salary / grade when `facts.in_entry_section(pf.field)` or `pf.group` names an entry, and when the label holds an entity noun (company, employer, school, institution, university, previous, role, position, job, project, model, brand, grew, range, limit); require "age" to be the label's head word ("Age", "Your age", "Age range", "How old"); salary "current / last drawn" only with "your". Mark an F1 copy on a code key that the model contradicted `assumed` ("check: copied from your profile").

### MEDIUM

**M1. Over-protection: a short noun-phrase label has an unknown H, so a right model answer is vetoed and the required field ends empty.** `always.py:2058-2060` (`english`: needs a word from a 60-word stopword list) used at 2456 (`_decl_applies_yes`), 2500, 2522, 2599 (`_work_in_h`). Probe (R = model right, class right; all four conditions empty for the first group): required radios **"Criminal record", "Criminal convictions?", "Bankruptcy", "Politically exposed person (PEP)", "PEP status", "Non-compete agreement", "Regulatory disciplinary action"** -> `<empty>`; the work-rights dropdown **"Work authorization"** and **"Work authorisation status"** (three sentence options; `standing_answer` says `conflict`, H None) -> `<empty>` in R and W (the model's right "Authorized to work without sponsorship" is vetoed). "Conflict of interest" (has "of") works. With 12 such declaration radios and a silent confirm call, 9 required fields ended empty (12 calls). How common: bare-noun declaration labels are perhaps 1 in 10 declaration fields on ATS custom questions and bank / government forms; "Work authorization" as a dropdown is common on US-style Workday / Greenhouse. The failure is fail-closed (the site's validation, `validation_error`), but each is a field "a person would simply answer", and combined with H2 it is the route to a flipped confirm. **Fix.** Count a label as English when any token is in the code's own English lexicon (the class words `classify_all` matched, `_WORK_RIGHTS`, `_CITIZEN`, the declaration nouns), or invert the test: non-English only when it holds non-ASCII letters or a known foreign stopword (le, la, es, tu, une, ist, du, die, der, das, ja, nein, oui, non, ya, tidak ...).

**M2. The `other_person` key shadows the declaration key.** `always.py:2177` (`_key_on` returns `OTHER_PERSON` before the declaration branch). Questions that name a spouse, parent, partner, guardian or manager are declarations about the applicant's relatives, PEP status or shares: "Is your spouse, parent or sibling employed by Example Employer?", "Does your spouse or partner work for Example Employer?", "Do you or your spouse hold shares in Example Employer?", "Is your manager a relative?", "Do you have a parent or guardian who is a politically exposed person?", "Are you, your spouse or your partner a politically exposed person?": R `No~`, W (model Yes, class right) `<empty>`, **O `Yes~!!`, M `Yes~!!`**. The model's own class still vetoes (W), so this is a hole only when the model also misses the class. How common: "spouse / parent / sibling" is the usual wording of a relatives-in-the-company question. **Fix.** In `_key_on`, test `adverse_other` / `_declaration_classes` first when the field is a Yes/No, checkbox or statement list; `OTHER_PERSON` only wins for a text / email / phone field.

**M3. The marketing and retention frames are too narrow: seven common wordings have no code key, so a wrong model tick on them is written.** `always.py:1941-1974`, `2074-2090` (frames need an agreement / opt-in verb AND an object from a closed list). Probe (profile: marketing opt-in false, retention true or refused; model ticks "true" / "Yes" with class `ordinary` or missing; with the right class all are correctly refused or vetoed):

| Wording | Written with class ordinary / missing |
|---|---|
| Please keep my application on file for 12 months (retention refused) | **true~** |
| I wish to be considered for other suitable roles (retention refused) | **true~** |
| Yes, contact me about other positions that match my profile | **true~** |
| Keep me posted about new openings | **true~** |
| I would like to receive updates and offers from Example Employer | **true~** |
| I agree to be contacted by recruiters of Example Employer group companies | **true~** |
| May we contact you about other opportunities? / Would you like to be contacted about future roles? (sample profile, opt-in false, retention true) | **Yes~** |

The model labelling these `marketing` / `consent_retention` is the primary protection (right-class column is safe, `<empty>` when required, `false` when optional); the code key is the second key and is silent on all seven. These are standard talent-pool wordings. **Fix.** Add opt-in verbs "contact me", "keep me posted", "keep me in the loop", "be contacted", "notify me", "email me", "update me", "let me know" and objects "opportunities", "positions", "openings", "vacancies", "updates", "offers", "recruiters"; make "please keep / store / retain my ..." and "wish to be considered for" a retention frame without needing "agree".

**M4. The `declaration:other` key (C3) misses common adverse-history wordings.** `always.py:1977-1984` (`_OTHER_FRAMES`, `_ADVERSE_NOUNS`). With class `ordinary` / missing and the model's Yes: "Has your employment ever been terminated for cause?" -> **Yes~**, "Do you have any outstanding court judgments against you?" -> **Yes~**, "Do you or your spouse hold shares in Example Employer?" (M2) -> **Yes~**; "Have you ever been refused entry to any country?" is keyed. With the right class every one is vetoed and ends empty (W). **Fix.** Frames "has your employment", "has your contract", "did you ever", "do you have any outstanding", "have you ever had ... revoked"; nouns "judgment(s)", "judgement(s)", "terminated for cause", "struck off", "barred", "banned", "blacklisted", "insolvency", "garnish".

**M5. Grade and retention rows the tester flagged, both confirmed.** (a) CONFIRMED: `always.py:2739-2749` (`_fact_in_h` grade: `if not re.search(r"\d", text) and not class_word: return False`) lets a non-numeric value through on any label without a class-of-degree word. Probe, TEXT, profile grade `4.20`, model invents "First Class", class `owner_fact:grade` / ordinary / missing: **"Grade", "Cumulative GPA", "CGPA", "Final grade" -> `First Class~`** in all three classes (basis `resume` also), with and without a profile grade; "Class of degree" and "Degree classification" are vetoed and take the profile's `4.20 / 5.00` (or `N/A~` / the stop when none). It is marked assumed, so the owner can see it, but it is an invented personal fact on a field the design calls an owner fact. **Fix:** for the `grade` key treat any value that is not in the profile grade or the resume corpus as H (drop the digit test); keep "N/A". (b) CONFIRMED: with `consents.data_retention_consent` unset and the model's reply `basis default:consent, assumed false`, "May we keep your details on file for future roles?" -> `Yes` and "I agree to you keeping my CV for future vacancies" -> `true`, **not assumed** (`assumed=False`, source `default:consent`). §17.2 says retention unset -> "the model decides, assumed". `_consent_rule` (`always.py:2359-2361`) returns `t_kind "none"` and `decide` then adds nothing. **Fix:** in the undecided branch of `decide` set `assumed`, reason "check: consent_retention (not set in your profile)" when the class rule is retention with no key. A refusing answer ("false") on the checkbox ends empty (required) / `false~` (optional): fine.

**M6. `facts.py` (A1-P) blocks the applicant's own details after a field about another person, and misses other persons the P2 lock writes into.** Own-detail label test `_own_detail_label` (`facts.py` new, ~600-612) ignores "your / my": **"Your email address" after "Referrer's name"**, "Email" after "Name of friend or colleague who referred you", "Phone" after "Mentor name", "Your name" after "Agency recruiter" -> `about_other_person` True -> the applicant's own required email / phone left empty ("left empty for the site's validation: F4: never the applicant's own contact"). And the opposite gap (R5, accepted in the design but wider than the word list): **Guarantor email, Employer's contact email (for verification), Previous employer HR email, Professor's email, Email of recommender, and "Email address" under "Who referred you? Name"** -> `alex.testcase@example.com [src=field_map:email]` in every model condition (the P2 lock never asks the model). Scope for strict (item 7): see section 7. **Fix:** an own-detail label that starts with "your" / "my" is never about another person; add guarantor, recommender, referee's, professor, HR, verification, "previous employer", "former employer" to the other-person words for EMAIL / PHONE fields.

**M7. R0 collapses every option to the first one when the option text has no ASCII letters (pre-existing, reached through the new ladder).** `always.py:822-824` (`norm_label(o) == norm_label(w)`; both are "" for CJK, Thai, Arabic, Hindi). Probe: options (是, 否), model "否" (No) -> **是** written (`coerce ... rung='R0'`); same on `4f9aac7`. Singapore forms are almost all English; a bilingual yes/no list is the case. **Fix:** require `norm_label(w)` non-empty for the R0 comparison and fall back to casefolded exact string equality.

**M8. Non-English labels (accepted R2, with two sharpenings).** With class right the field ends empty (H unknown, confirm silent): Malay, German, Chinese, French rows. With class `ordinary` / missing the model's adverse value is written: "Pernah disabitkan atas kesalahan jenayah?" `Ya~`, "Haben Sie eine Vorstrafe?" `Ja~`, "你是否有犯罪记录？" `是~`, "Avez-vous déjà été condamné pour un délit ?" `Oui~`, "Es-tu une personne politiquement exposee ?" `Oui~`. This is the design's accepted R2; the sharpenings: H2 above makes the *right-class* path unsafe on a flip, and M7 breaks CJK option matching before any class applies.

### LOW

**L1.** `hints` (`always.py:304-326`) tells the model the code's own classification ("declaration: criminal_record (D1)", "about another person ..."), so the two keys are not independent: a code misclassification is echoed by the model and both keys agree on the wrong class (R6, not adverse). Acceptable; the rehearsal's blind-class run still isolates the code key.

**L2.** `== PAGE ==` prints `step_title` raw (`always.py:444`); a title holding a newline and "== FIELDS (JSON) ==" forges a heading (probe on `messages`: the forged lines appear verbatim). The title is a single reader-normalised line in practice; fence or `json.dumps` it.

**L3.** (declarations red) A silent model on an unframed required acknowledgement: "Do you acknowledge?" -> `No~` (F2 generic No, `fallback:F2`), "I have read and understood the above", "I agree", "I accept", "I confirm", "I understand and agree" (required checkboxes) -> `<empty>` (unticked). Pre-A1 they were `Yes` (D5 default). With a model that answers (A5 forces it) all of them are ticked / Yes (`true~`), so this needs a silent model. **Fix:** add "the above", "this notice", "the following", "this declaration" to `_ACK_OBJ` and let a bare "I agree / I accept / I acknowledge" on a required checkbox be an acknowledgement.

**L4.** (c) CONFIRMED: a silent model never gets the confirmation call on a tentative reader: "Have you ever been convicted of a criminal offence? Please do not include spent convictions." (standing `tentative`), "Is it true that you have no criminal record?" -> `''`, picks=0; on a confident reader with noun-phrase / spouse wording ("Criminal record", "Is your spouse, parent or sibling employed ...") also `''`. Only the plain "Have you ever been convicted of a criminal offence?" gives `No` (`default:no_declaration`). Fail-closed; rare because A5 re-asks until the model answers. After H1/M1 are fixed this largely disappears.

**L5.** Required gender / race list with the profile on `decline` and no decline option ("Man / Woman / Non-binary", "Male / Female / Other") ends `validation_error "no gender option matches your profile (prefer not to say)"` (design C6b, intended). Common on Singapore forms (required Male / Female). Owner-visible; the owner can set `identity.gender`.

**L6.** Required "Address Line 2" with an empty profile `address_line2` -> `owner_fact_missing` ("Address Line 2"). Line 2 is usually optional; when required a person would write "N/A". Required "Current salary" NUMBER with `pay.current_salary` null -> `owner_fact_missing` (a new graduate would write 0): by design (§17.4 M8), the capture asks the owner once. A required combined "Privacy Policy and receive marketing" box with the opt-in unset or false -> `consent_refused "receiving marketing messages"` (design C5, intended).

**L7.** "Class of degree" writes the numeric `4.20 / 5.00` (truthful, a poor fit for a field expecting "First Class Honours"); a typed class comes only from the resume.

## 1. Review 1 and design-review inputs under the four model conditions

R = model right + right class; W = model wrong + right class; O = wrong value, class `ordinary`; M = wrong value, class missing. Sample profile unless stated. "OK" = nothing adverse written and no correct ordinary answer overwritten.

| Input | R | W | O | M | Verdict |
|---|---|---|---|---|---|
| H1 ×7 ordinary questions (confirm 2y experience, data structures, similar roles, other roles, promotions, marketing newsletters, licence on file), profiles sample and all-consents-false | model's value | model's value | model's value | model's value | OK: never a `consents.*` source |
| H1 two required lists, retention false | model's pick | model's pick | model's pick | model's pick | OK, no stop |
| H2 4 checkboxes (tick if PEP, check if convicted, I have a relative, I am a PEP), required / optional | empty / `false` | empty / `false` | empty / `false` | empty / `false` | OK (required: empty for the site; optional: unticked) |
| H2 "I am not a politically exposed person" ticked | kept `true` | `true` | `true` | `true` | OK |
| H2 4 lists (multi PEP, multi bankrupt, radio Bankruptcy, radio conflict of interest) | none option | none option | none option | none option (radio conflict: empty for O/M) | OK |
| H3 DOB, year / month / day / D.O.B. / Born on / Geburtsdatum / Tarikh lahir / Date de naissance / Age / How old / "Date of birth - Year" list, invented 1999-05-17 | profile value | profile | profile | profile | OK; no DOB in profile -> `owner_fact_missing` in all four |
| SSN, Tax ID, driver licence, employee ID, passport, bank, NRIC / FIN invented | stop | stop | stop | stop | OK (`owner_fact_missing`) |
| Class of degree / Honours / Classification | profile `4.20 / 5.00` | same | same | same | OK; but see M5 (a) for "Grade", "CGPA" |
| M1 address, postal, mobile, Phone, Contact number invented | profile | profile | profile | profile | OK; but H3 for the generic over-reach |
| M3 pairs (No / "No, but ..."; Female / Non-female; Singapore / Singapore PR; Not Hispanic / Hispanic; ...) | R1 refuses all | | | | OK (ladder returns None, R2 decides); "Bachelor's degree" vs "Bachelors Degree" now costs an R2 call |
| M4 gender, race, religion, marital (profile decline or male) | decline / profile | same | same | same | OK; "Man" for male OK; never "Other"; disability / veteran -> PNTS |
| M5 "Have you ever been dismissed ...", litigation, visa refused, under investigation | No | No | empty | empty | OK (not adverse); M4 for the unkeyed wordings |
| M5b "Visa status" (3 options) | authorised, no sponsorship | same | same | same | OK; "Work authorization" empty (M1) |
| M6 20 fields, reply "not json" | content failure after 6 calls, before A5 | | | | OK |
| M7 referee, emergency, supervisor, mentor, referral email / phone | empty / "Available on request" | same | same | same | OK for the listed words; M6 gaps |
| M8 "Last drawn salary" / "Current salary" | `N/A~` / stop | same | same | same | OK, never the expected figure |
| L1 "prevents you", "NOT free of", "unable to confirm", "fail to meet" | empty | empty | empty | empty | OK; "stopping you" is not covered: H1 |
| L3 KEEP of a site-restored phone / address / DOB | profile value | | | | OK |
| L5 "accept that the above is complete and correct" | certification frame | | | | OK |
| C1 "untrue / false that / deny / incorrect" ×4, tick-if ×2 | empty | empty | empty | empty | OK, never adverse; over-protected but rare wording |
| C2 nine non-fact labels (Email, Confirm email, Home page URL, Home country, IP, Phone Device Type, Country Phone Code, Phone Extension, "Do you have a mobile phone?") | model's value / profile email | | same | same | OK; but with the model's class forced to `owner_fact:phone`, "Do you have a mobile phone?" -> **No** (F2 generic No) and "Home page URL" -> the profile's LinkedIn (a wrong model class can overwrite a correct ordinary answer; rare) |
| C3 dismissed, litigation, visa refusal, investigation | No | No | empty | empty | OK |
| C4 NDA willingness (profile willing) with model `declaration:non_compete`; Expected salary with `owner_fact:salary_current` | Yes~ / 5000 | | | | OK |
| C5 combined privacy + marketing / privacy + retention, required, opt-in false or unset | `consent_refused` (marketing / retention part) | same | same | same | OK; optional -> unticked |
| C6 Man / Woman, hispanic / latino, decline profile, no decline option | `Man` / PNTS / `validation_error` | | | | OK (L5) |
| C7 "Not Hispanic or Latino" vs "Hispanic or Latino" | None | | | | OK |
| C9 How old, SSN, tax ID, driver licence, employee ID | owner facts | | | | OK |

## 2. New wordings (about 70 inputs)

Below only the outcomes that are unsafe or empty. All declaration paraphrases not listed ("convicted of an offence or declared bankrupt", ALL CAPS, inverted No / Yes order, "Yes / No / Prefer not to say", sentence options "I have / do not have a criminal record", "Criminal history" None / Minor / Serious, "free from any criminal convictions", "Is there any reason ... such as a criminal conviction" (H1), tick-style "I declare that I am not a PEP" / "I confirm that I have never been convicted", the PEP, relatives, shares, non-compete, restrictive covenants, prior employment, previously applied, government, regulatory, conflict, insolvent, health rows) ended safe: the model's right answer, or none-applies, in R and W.

**Unsafe** (all in sections H1, H2, H3, M2, M3, M4 above): the negation-tail family (H1, 8 wordings); the flipped confirm (H2, 5); the over-wide fact key (H3, 21 labels); spouse / parent declarations (M2, 6); seven talent-pool wordings (M3); three adverse-history wordings (M4); "Grade / CGPA" (M5); Guarantor / HR / Professor / Recommender email (M6); non-English (M8).

**Empty or stopped where a person would simply answer (over-protection), with how common the wording is:**

| Wording (required) | Outcome | How common |
|---|---|---|
| Criminal record / Bankruptcy / PEP status / Non-compete agreement ... (noun-phrase radio) | empty (M1) | ~1 in 10 declaration fields |
| Work authorization / Work authorisation status (dropdown, no country) | empty (M1) | common on US-style forms |
| Do you deny / Is it untrue / Is it false that / Would it be incorrect (C1) | empty | very rare |
| tick-if PEP / convicted checkbox, required | empty | rare (usually optional) |
| Es-tu / Pernah / Haben Sie / 你是否 (non-English) | empty | rare in Singapore |
| Gender required, profile decline, options without decline | `validation_error` stop | common (Male / Female forms) |
| Address Line 2 required, empty profile line 2 | `owner_fact_missing` | rare required |
| Current salary NUMBER required, null profile | `owner_fact_missing` | common on local corporate forms; capture asks once |
| Privacy + marketing combined box required | `consent_refused` stop | uncommon, intended |
| Your email / Phone after a referrer / mentor / recruiter field | applicant's own required email left empty (M6; also strict) | uncommon |
| Required acknowledgement with a silent model (I agree / I accept / Do you acknowledge?) | unticked / No | needs a silent model |
| Consent-style checkboxes on a page where the model answered "assumed" | ticked, assumed (fine) | n/a |

Real label counts per page: not measured (no live model, no real forms).

## 3. The two-key `decide` against §17.1 (`always.py:2974-3089`)

Read row by row:
- **Code writes its own value only on `both`:** `write_truth` is reached at 3028-3031 (needs `both and rule.has_t`) and 3047-3049 (needs `both`, and then the value equals T's). `both = ck is not None and mk is not None and _same_key(...)` (3018). So no path writes code's value with one key. (The protective end is a different mechanism: a veto followed by A6; it can write T on the code key alone, §17.2 col. "protective end", and that is where H3 bites.)
- **Model value after a veto:** `st.vetoed` (3040) -> `problem` -> A5 re-ask goes back through `decide` (a new model value outside H is written; correct) -> `confirm_class` (H2) -> `protective_end`. A vetoed value is not written by any path; H2 is about the confirm pick, not the veto.
- **Contradicting keys (C4):** `rules` gets the model's class rule as a second rule (3020-3022) and `hs` covers both; verified: PEP question with model class `owner_fact:date_of_birth`, `sponsorship`, `marketing`, `consent_privacy`, `self_id:gender`, `other_person` and value Yes -> `No` in every case; "Date of birth" with model class `declaration:pep` or `consent_privacy` -> the profile DOB; "Gender" (decline) with model `marketing` / `self_id:race` / `declaration:pep` -> PNTS; "Are you willing to sign an NDA?" with model `declaration:non_compete` -> the model's Yes, assumed. `which` mismatch (model `salary_current`, label "Expected salary") -> 5000 in all conditions.
- **D1b** (3023-3027) only for both keys, H known, a cited `default:` rule; fine.
- **Cached / replayed decision:** `always_row_decision` (pagefill.py, post-301e908) returns None (a miss) for a row without a readable class or another prompt version, and rebuilds `klass` / `which` otherwise, so a replay goes through `decide` with both keys, not code-only. Replay under `always` is still off (`_always_steps` never reads the cache), so this is unexercised in a run; the cache write stores `a.source` (the answer's source) and the redacted value, so a replayed decision's basis is the written answer's. Sound as built.
- **A5 ordering:** a vetoed field enters A5 unless `protect_now` (3044); the A5 result replaces a vetoed state only when usable or the previous was unusable (`fill_page_always` 4070-4078), so a vetoed state is never overwritten by an unusable one without keeping `vetoed` / `rule`. Sound.
- **Departure (1)** (a required box the model leaves unticked = no answer): safe, fail-closed; routes to A5/A6 and ends as before. **(3)** M3 also on the yes/no mapping and F2 fit: safe; ordinary sentence options still resolve ("Yes, I do" / "No, I do not", "Yes - up to 25%", "I am over 18": R2 picks, 0-1 calls). **(4)** "add me / include me / have you read": harmless additions, but too few (M3). **(5)** call cap stops the page when spent with required fields open: safe; see section 6. **(2)** the confirmation replacement: finding H2.

## 4. Code keys: wide enough and narrow enough

Keys (class:which) the detector gives with the sample profile:

| Label | Key |
|---|---|
| I consent to the processing of my personal data | consent_privacy |
| I have read and agree to the Privacy Policy | acknowledgement |
| Subscribe to our newsletter | marketing |
| I certify that the information given is true | certification |
| By submitting you confirm you have read our Terms of Use | acknowledgement |
| Are you a PEP? / Criminal record / Are you subject to any restrictive covenant? | declaration:pep / criminal_record / non_compete |
| Is any of your relatives a director of Example Employer? | declaration:relatives_at_company |
| Have you ever been refused entry to any country? | declaration:other |
| National Registration Identity Card (NRIC) number / Date of birth (dd/mm/yyyy) / CGPA / Residential address / Postal code / Contact number | owner_fact:national_id / date_of_birth / grade / address / postal_code / phone |
| Race / Sex / Religion | self_id:race / gender / religion |
| Do you require a work pass? / Right to work in Singapore | sponsorship / work_right |
| Referee 1 - email / Emergency contact number | other_person |
| **Silent (should be keyed):** Please keep my application on file for 12 months; May we contact you about other opportunities?; Keep me posted about new openings; I would like to receive updates and offers from Example Employer; I understand that false statements may lead to dismissal; Has your employment ever been terminated for cause?; Do you have any outstanding court judgments against you?; Are you an ex-serviceman? (ordinary, fine); Citizenship status dropdown (ordinary: a wrong nationality dropdown pick is written, assumed; model-only protection) | ordinary |

Narrow enough: 28 ordinary questions (2y Python, onsite days, relocation assistance, available immediately, privacy-regulation experience, email-marketing tools, mailing address in Singapore, background-check comfort, driving licence, studied in Singapore, startup, studying, referred by employee, know anyone, club, Home country, Years of experience, Phone type, code of conduct of the programme, assessment in 7 days, availability for interview, Expected graduation date, English first language) get `ordinary`. Over-matches (a protected key on an ordinary field): "Do you accept the salary range stated in the job post?" -> owner_fact:salary_expected (harmless: H false without a digit); "Age of your oldest project", "Age at graduation" -> owner_fact:age and "What is your current address situation?" -> owner_fact:address (H3); "Do you hold shares in a company?" -> declaration:shareholding_in_company (reader, shared with strict); "Have you been convicted in debate competitions?" -> criminal_record (silly); "Do you agree to the code of conduct of the programme?" -> acknowledgement (right).

## 5. Prompt `always:v2`

Rules 11 and 12 as built match §17.3 (`always.py:94-119`): rule 11 names JOB DESCRIPTION, PAGE and FIELDS as the employer's text, help / context never ask for more; rule 12 gives the class before the value with the negative examples (2y Python, promotions, NDA / relocate, refer, privacy / marketing tools) and `ordinary` last in the enum. Nothing outside the briefing's groups reaches a prompt: the diff to `briefing.py` adds class tags on rule lines, the D1 "other adverse history" sentence, `standing:age` (computed from a DOB already in PROFILE) and the fence. The JD is fenced and labelled; a JD line starting `==` becomes `--` (A1-B pins; I re-read `fence_job_description`). The R2 / confirm question is `QUESTION (JSON): "<label>"`. Help text steering a class: M2a works (an 80-character injection sentence under "Additional information" gives no key; the model's DOB is dropped by the identity-class check and F4 `N/A` / F6 today are written); a short help "Enter your date of birth" under "Other" / "Comments" / "Additional information" gets the DOB into a TEXT field (the accepted M2 residual: indistinguishable from a real field). Gaps: L1 (hints echo the code key), L2 (page title unfenced).

## 6. Budget

Calls (counted on the fake): 22 fields, no near-miss dropdown: 1 call; 28 fields with 6 near-miss dropdowns: 8 calls (2 main + 6 R2); 32 fields / 10 near-miss: 12; 38 fields / 10 near-miss: 12; cap = 3 × chunks + 20 (23 for one chunk, 29 for three). A page of 12 bare-noun declaration radios + 8 text with a silent confirm: 12 calls (3 main + 9 confirms), 9 fields empty. Unparseable replies on 20 fields: 6 calls, content failure before A5. A normal 30-field page does not reach the cap (about 8-14 calls); a degenerate page (20 near-miss dropdowns, or 12+ vetoed declarations plus R2) can: 20 R2 + 3 main + 3 A5 + 5 confirms = 31 > 29, ending `unanswerable_required: too many model calls`. M3's strictness adds an R2 call for decorated options ("Bachelor's degree" vs "Bachelors Degree"). The rehearsal should print the maximum observed.

## 7. `strict`

`always.py` and `briefing.py`: the only entry points are `fill_page_always`, `pick_call`, `ladder`, `decision`, `always_services` / `at.always`. Guards: `pagefill.fill_page` dispatches on `_policy(rctx) is FillPolicy.ALWAYS` (pagefill.py:143-145, unknown values fall back to strict); `apply_flow` sets `at.always = self.policy is FillPolicy.ALWAYS` (apply_flow.py:1139) and every `always_services`, `AL.AlwaysStop`, refill and trial branch is under `at.always`; `pagefill.always_row_decision` is not called anywhere yet. Module-level code in always.py is constants, regexes and imports (import-time cost only; `-k layering` 13/13, `-k pagefill` 22/22). `briefing.py` is reached only through `always`.

`facts.py` is shared. Strict callers: `locks.py:182` (L2 email lock: skip when about another person), `guards.py:661` (G13), `facts.py:773` (`relevant`), `facts.py:1124` (`label_runs` heads). What changes for strict, exactly: (1) `about_other_person` is True for more fields, so strict writes **less**, never something new: text / email / phone / number / URL / typeahead fields whose label, section, group title or (generic labels only) help / context holds referrer(s), referral, referred, mentor(s), recruiter(s), colleague(s) / friend(s) / relative(s) (only with a detail word: name, email, phone ...), "contact person(s)" no longer receive the applicant's own contact or identity (previously `field_map:email` / profile phone were written); never when the label holds hear / heard / source or the field is a yes/no or list. (2) the preceding-field rule (TEXT / EMAIL / PHONE own-detail label right after a field about another person, `pf.context` not a question): the applicant's own "Your email address" after "Referrer's name" is now treated as the referrer's and left empty (probe above, M6): in strict a required own email left unfilled ends the page as an unanswered required field (a captured question), where before the applicant's email was written. That is the only way strict newly leaves a field empty that a person would fill. (3) `label_runs` heads exclude more fields (a field already other-person); no effect unless two runs of the same section label exist. No new write. Fix: M6 (own-detail labels starting "your / my").

## Residuals I accept (with who sees them)

R1, R3-R9 of the design review as written. R2 (non-English) with the M7 sharpening in a fix list; R3 (confirm is the same model): accepted only once H2 is fixed, because today a flip is written for H-unknown fields. R6 (both keys wrong the same way writes the owner's "No" to a non-declaration), which L1 makes slightly more likely. A model that labels a country / citizenship dropdown ordinary and picks a wrong nationality ("Malaysia" for a Singapore citizen, assumed): no code key reads a nationality list (`Citizenship` -> `ordinary` above); model-only protection, flagged assumed.

## What I checked and found sound

Review 1 H1 (all rows, four conditions), H2 (all rows), H3 and the C-list labels; two-key `decide` structure, contradiction rule, which-mismatch, D1b, A5 ordering, cache row class; implicit-negator wordings that are in the list; consent frames with the right class (refused -> `consent_refused` required / unticked optional / refusing option on Yes/No, in all four conditions for the keyed wordings, including combined boxes); unset privacy / certification -> agree assumed; owner-fact stops (DOB parts, ID words, passport, bank, NRIC, SSN, tax ID, licence, employee ID, current salary, grade class words) in all four conditions; identity-class and "applicant's contact in another person's field" for the listed words; M3 option rule; M6 content failure; prompt fence and JSON question; call budget on normal pages; strict isolation (section 7).

## What the dress rehearsal must watch for

1. After the H1 fix: every declaration wording with a "not" in an instruction tail or a relative clause, run in all four conditions; the owner-visible row must be "No / none applies".
2. Per class recall on the **noun-phrase** and **spouse / parent** declaration labels (M1, M2) and on the seven talent-pool wordings (M3): the blind-class run is the proof the code key is wide enough; today it is not.
3. Employer address / phone / postal code and "Age at ..." fields inside a work-experience entry: the value written must be the page's own entity, never the profile's (H3).
4. A confirm pick that differs from the model's right answer on an H-unknown label (H2): script the pick to flip.
5. Calls per page with many R2 picks plus vetoed declarations; first-call grammar-compile time.
6. CJK / non-English yes/no lists (M7, M8).
7. A "Grade" / "CGPA" text field with the profile grade present (M5 a).

## Not reached

No real model (class recall, flip rate, latency); no browser, so the reader, entry groups and typeahead were not run (entry binding checked only through `pf.group`); the Vue / flow / store / web changes (`apply_flow.py`, `store.py`, routers: out of scope here); `widgets.py`; the 20 retargeted pins individually (I judged `plain consent` and the two silent-acknowledgement rows only); month / year dropdown coercion; the `compose` path; the full `-k always` at 743a06d (the Coordinator reports 300/300). The post-merge numbers for `-k always_a1`, `-k pagefill`, `-k declarations`, `-k layering` at 743a06d follow in the outbox entry if they finished before commit.
