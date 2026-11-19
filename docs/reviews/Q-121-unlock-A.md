**Estimate: about one application in three (4 of 12 corpus forms, 33%; plausible range 25 to 45%) would reach "ready to submit" under always today, with a competent model AND with a realistic one (same 4 forms both runs). Basis: 12 made-up Singapore new-grad forms (490 fields, 375 required) run through `always.fill_page_always` with scripted models and the sample applicant; the profile-gap forms (NRIC, binary gender lists, referees) are over-represented in my corpus, ordinary Greenhouse / Lever forms pass more often (4 of 6). Fixing five specific over-protections (below) takes it to 7 of 12 (58%); the owner's affiliates answer adds a form (67%); adding honours class, transcript and a zero current salary to the profile reaches 10 of 12.**

# Q-121 unlock review A: will real applications get through?

Branch `rev/Q-121-A` (from `tst/Q-121-G2` 5f1b215; never push). Reviewer, 2026-11-19. Corpus `docs/reviews/Q-121-unlock-A-corpus/` (12 forms), probes `docs/reviews/Q-121-unlock-A-probes/` (`run_corpus.py`, `probe_cases.py`, `probe_codekey.py`, `run_strict.py`, `results_*.json`). No real model, no port 11434, no `data/`, no `.env`.

## 0. Method and what the numbers are worth

- **Corpus:** 3 forms in each of Workday, Greenhouse, Lever and SuccessFactors / Taleo style (Workday and SF are 4 to 5 pages each, one `fill_page_always` call per page). Employers are made up (Northwind Bank, Acme Trading, Contoso Logistics, Kestrel Labs, Fabrikam Games, Initech Analytics, Blue Heron Studios, Tidewater Ventures, Lumen Payments, Meridian Bank, Harbour Shipping Group, Pinnacle Insurance). Wordings are my recollection of what such forms ask, not scraped.
- **Applicant:** `tests/fixtures/apply/applicant.sample.yaml` (Singapore citizen, NS completed, CAP 4.20 / 5.00, expected SGD 5,000, no current salary, no referees, no transcript, gender / race "decline", `consents.talent_pool_opt_in: false`, no `authorised_to_work.default`). A real owner profile with a transcript or honours class would pass more.
- **Competent fake:** names the right class and gives the true answer for every field, and gives the confirmation / meaning / own-fact / experience answers a competent model would. Where the profile has no fact it is silent (or says "assumed" for odd custom questions). What is left empty is code's own doing.
- **Realistic fake:** same, plus the place call answered as `place_replies_qwen3_14b.json` does (NONE for "citizen / PR / work pass" and for US / United States, the country for plain Singapore wordings), class `ordinary` on every fifth protected field, one wrong answer per form on a protected yes/no, silent on two optional fields.
- **Diagnosis mode:** after a page stop the offending field is dropped and the page re-run, so every stop reason of a form is listed. "Ready" = no stop and no required field left empty. Required "why us / cover letter" free text is a compose target (written by the tailor round trip in `apply_flow`, step 7b); it is counted apart as "composed" and not tested here, so a form's readiness also assumes the tailor works.
- **Place-call assumption (mine):** a status wording that names Singapore only as an adjective ("Singapore citizen") or names no place gets NONE; "... in Singapore" gets "Singapore". The Coordinator's real-model run will show how far this holds.

## 1. Results per form (c = competent, r = realistic)

| form | fields | req | answered c/r | composed | optional left empty c/r | req empty c/r | page stops c/r | max calls per page c/r (base cap) | ready c/r |
|---|---|---|---|---|---|---|---|---|---|
| 01 workday Northwind Bank | 56 | 40 | 49/47 | 1 | 5/7 | 1/1 | 1/1 | 12/14 (26) | N/N |
| 02 workday Acme Trading | 59 | 42 | 52/50 | 1 | 4/6 | 2/2 | 1/1 | 9/10 (26) | N/N |
| 03 workday Contoso Logistics | 54 | 39 | 47/45 | 0 | 5/7 | 2/2 | 1/1 | 9/6 (26) | N/N |
| 04 greenhouse Kestrel Labs | 37 | 25 | 33/31 | 0 | 3/5 | 1/1 | 0/0 | 8/8 (29) | N/N |
| 05 greenhouse Fabrikam Games | 37 | 26 | 33/32 | 0 | 3/4 | 0/0 | 0/0 | 10/9 (29) | Y/Y |
| 06 greenhouse Initech Analytics | 36 | 28 | 32/32 | 1 | 1/1 | 2/2 | 1/1 | 12/12 (29) | N/N |
| 07 lever Blue Heron Studios | 30 | 18 | 22/20 | 0 | 7/9 | 1/1 | 1/1 | 8/10 (29) | N/N |
| 08 lever Tidewater Ventures | 32 | 23 | 30/28 | 0 | 2/4 | 0/0 | 0/0 | 14/11 (29) | Y/Y |
| 09 lever Lumen Payments | 32 | 27 | 30/28 | 1 | 1/3 | 0/0 | 0/0 | 9/10 (29) | Y/Y |
| 10 SF Meridian Bank | 43 | 39 | 33/31 | 0 | 0/2 | 10/10 | 7/7 | 19/19 (23) | N/N |
| 11 SF Harbour Shipping | 38 | 34 | 36/36 | 0 | 2/2 | 0/0 | 0/0 | 5/5 (26) | Y/Y |
| 12 SF Pinnacle Insurance | 36 | 34 | 32/30 | 1 | 0/2 | 3/3 | 2/2 | 4/5 (26) | N/N |
| **total** | 490 | 375 | 429/410 | 6 | | **22/22** | 14/14 | 163 / 166 calls over 33 pages | **4/4 of 12** |

Overall: 22 of 375 required fields (6%) end empty or stopped; 33 (competent) / 52 (realistic) optional fields are left empty by choice or silence; 163 calls (competent) / 166 (realistic) over 33 pages = about 5 per page, 14 per form. No page hit the cap (`CallCapReached` never raised). The tightest page is form 10 page 1 (14 fields, 19 calls against a base cap of 23, which the vote budget raises by 3 per voting field); a longer SF personal-details page with more protected fields could reach it. The realistic run changes only counts of answered fields: the filler corrected 7 of the 12 injected wrong answers by the standing-answer check, left 2 empty (US / other-country place), wrote the true value on 2 (no row to contradict) and **wrote the wrong one on 1 (see section 7)**.

## 2. Required fields left empty, and why (identical in both runs unless stated)

| form | required field | note on the field | right stop? |
|---|---|---|---|
| 01 | "Do you have any outside business interests or shareholdings ... at Northwind Bank?" | STOP owner_fact_missing: bank details | NO: the label only holds the employer's name |
| 02 | "Are you legally authorized to work in the United States?" | work rights: place not recognised | over-protection (profile holds US: false) |
| 02 | "I consent to my personal data being shared with Acme Trading's affiliates and group companies ..." | STOP consent_refused: sharing your details with other companies | the owner's open question |
| 03 | "Class of Degree" (honours list) | STOP owner_fact_missing: grade | right (profile holds a CAP, not a class) |
| 03 | "What is your current immigration status in Singapore?" (Citizen / PR / EP ...) | work rights: place not recognised | over-protection |
| 04 | "Are you legally authorized to work in the United States?" | place not recognised | over-protection |
| 06 | "I understand that Initech will share my personal data with its group companies and service providers ..." | consent_refused: sharing | the owner's open question |
| 06 | "Are you legally authorised to work in any country other than Singapore?" | place not recognised | right-ish (no `default` row in the profile; the stop note is misleading) |
| 07 | "I consent to Blue Heron Studios storing my personal data for 12 months for the purposes of this recruitment process." | STOP consent_refused: receiving marketing messages | NO: a plain retention consent for this recruitment |
| 10 | NRIC / FIN | owner_fact_missing: national ID | right (never stored) |
| 10 | Gender, Race, Marital Status (lists with no decline option, required) | validation_error: no ... option matches your profile (prefer not to say) | right (profile says decline) |
| 10 | Title (Mr / Ms / Mrs ...) | F2: not classed: left for the site | right (profile holds no title) |
| 10 | Class of Honours | owner_fact_missing: grade | right |
| 10 | Last drawn monthly salary (NUMBER) | owner_fact_missing: current salary | right by the profile, but see rank 6 |
| 10 | Referee 1 email, Referee 1 phone | F4: never the applicant's own contact | right (no referees) |
| 10 | "I consent to Meridian Bank and its related corporations, affiliates and service providers ..." | consent_refused: sharing | owner's question |
| 12 | Academic transcript (FILE, required) | STOP document_missing | right (profile has no transcript) |
| 12 | "I consent to Pinnacle Insurance collecting, using and disclosing my personal data ..., including to its parent company, subsidiaries and affiliates." | consent_refused: sharing | owner's question |
| 12 | "I authorise Pinnacle Insurance to verify my education, employment history and criminal record." | declaration:criminal_record: the check did not agree | NO: an authorisation box, not a declaration |

Written without a stop on the same forms (checked): the privacy, certification, acknowledgement boxes, every declaration (No), sponsorship (No), citizenship / PR (Yes), NS (Yes / Completed), notice, salary expected, start date, "how did you hear", self-ID (decline wording or option), phone, address, school, degree, GPA, dates.

## 3. Why real applications would stop, ranked

Frequency is my judgement for Singapore new-grad postings. "Right stop" = the profile truly lacks the fact or the consent is truly refused.

| # | stop reason and exact wording(s) | frequency | verdict | smallest safe change (and what it risks) |
|---|---|---|---|---|
| 1 **HIGH** | **The employer's name contains "Bank".** `always.py:5946` `_BANK = ("bank", ...)` is matched by `fact_which` (`:2727`) on any non-checkbox, non-free-text field, so "Do you have any outside business interests ... at Northwind Bank?", "Are you currently employed by Northwind Bank?", "Have you ever been employed by Northwind Bank or any of its subsidiaries?", "Why do you want to join Northwind Bank?" (single line), "How did you hear about Northwind Bank?" all stop with `owner_fact_missing: bank details`. Probe: 5 of 9 labels naming the bank stop (`probe_cases.py bank`; the same question without the word "Bank" passes). Corpus: 1 of 12 forms stops (form 01); form 10 names Meridian Bank in two questions and neither stopped (their wordings are keyed first), so the rate per form is lower than per label. | very common for bank employers (the largest group of Singapore graduate programmes: DBS-, OCBC-, UOB-, Standard-Chartered-style names); any form that names the employer in a yes/no or a dropdown | **over-protection, and the message is false.** The row reads "Stopped: this form asks for your bank account details, which your details can't hold ... Apply by hand, or skip" with no Try again (`NO_FIELD_FACTS`, contracts.py:1265, `attempts.js` `noRetry`). | Match "bank" only with its companions: `("bank account", "bank details", "bank name", "account number", "iban", "swift")`, or strip `declarations.employer_names_of(rctx)` before the match. Risk: a field that really asks "Bank" alone reaches the model, which has no bank fact, so it answers none; the identity-class rule already blocks a value there. |
| 2 **HIGH** | **A required consent box that shares data with affiliates / group companies / third parties (the owner question).** "... shared with Acme Trading's affiliates and group companies", "its related corporations, affiliates and service providers", "share my personal data with its group companies and service providers", "including to its parent company, subsidiaries and affiliates", "shared with third parties". | common: 7 of 12 corpus forms hold one (all required) | **right by the current ruling (D-224: third-party sharing is its own consent, truth False) but a dead end and inconsistent.** See sections 5 and 6. | (a) Owner's decision. If "yes": add `consents.third_party_sharing` to the Profile form (`applicant.FORM`, one `_I(...)` bool; today the key exists only in `always.py:3375`, so the owner cannot set it) and keep unset = refused; or rule that sharing inside the employer's own group for recruitment rides on the privacy consent (as D-225 (3) already does for "on its behalf"). (b) Either way make the recogniser consistent: "affiliated funds and portfolio companies", "studios in other countries", "Harbour Shipping Group companies and its service providers in other countries" are ticked today (forms 05, 08, 11). |
| 3 **MEDIUM** | **Work rights for the US / another named country.** "Are you legally authorized to work in the United States?", "Are you eligible to work in the US?", "Do you require sponsorship to work in the United States?" (all end empty in the probe whatever the class; Malaysia is answered "No" from the profile). "Are you legally authorised to work in any country other than Singapore?" | occasional to common on forms copied from a multinational (3 of 12 here) | **over-protection for the US wordings:** `authorised_to_work.US: false` is in the profile; the real model quotes NONE for US wordings (fixture) so the place check never agrees. The "any other country" one is a right stop (no `default` row). | Accept code's own reading when the label is a pure work-rights frame naming exactly one of US / U.S. / USA / United States (the resolver already reads it, D-219) even when the model's quote is NONE, provided the model class agrees and the answer comes from the profile row; or ask the place question as a yes/no ("does QUESTION name the United States?"), which a 14B model answers better than a quote. Risk: a place the resolver mis-reads; keep the case-sensitive "US" token and the pure-frame test. For "any other country": add `authorised_to_work.default` to the profile. |
| 4 **MEDIUM** | **Retention consent that ends "for recruitment".** "I consent to Blue Heron Studios storing my personal data for 12 months for the purposes of this recruitment process.", "... storing my personal data for the purposes of this recruitment process.", "... storing my personal data for 12 months.", "I consent to Kestrel Labs storing my personal data for 12 months for recruitment purposes". Fail with `consent_refused: receiving marketing messages`. Passing variants: "retained for 12 months for the purposes of this recruitment process", "... stored for up to 2 years for this application", "kept on file for future opportunities". | common (GDPR-style retention boxes on Lever / Greenhouse; "for recruitment purposes" is the usual tail) | **over-protection and a misleading message.** `retention_pure` (always.py:3291) treats "recruitment", "process", "purposes" as residue, so the box needs the talent-pool consent too (false in the sample profile). The owner is told to agree to "receiving marketing messages". | Add `recruitment recruiting hiring selection process purpose purposes` to `_R_NEUTRAL` (always.py:3276). Risk: tiny; "for marketing purposes" still has the residue word "marketing". |
| 5 **MEDIUM** | **Consent to checks that names a criminal record.** "I authorise Pinnacle Insurance to verify my education, employment history and criminal record." (left empty: `declaration:criminal_record: the check did not agree`). Passing: "I consent to Lumen carrying out background, reference and criminal record checks before I am hired.", "I authorise the company to conduct background checks." | common on bank / insurer / government-linked forms | **over-protection.** The first-person "I authorise X to verify ..." is permission, not a statement about the applicant. | In the declaration detector, treat a CHECKBOX that starts "I authorise / consent to / allow X to verify / check / screen / obtain" as an acknowledgement. Keep "I confirm I have no criminal record" a declaration. Risk: low if the rule needs the authorise verb and the checking verb. |
| 6 **MEDIUM** | **Facts the profile does not hold that local forms require.** Class of honours (list: First / Second Upper ...): owner_fact grade; last drawn salary (NUMBER, "Last drawn monthly salary (SGD)"): owner_fact current salary, while the TEXT variants "Current / last drawn monthly salary" are written "N/A" by F4 (inconsistent); Title / Salutation; referee email and phone; transcript file; NRIC (never stored: apply by hand, correct). | common on SF / Taleo and bank forms (3 of 12 corpus forms, 10, 03, 12) | **right stops** (the profile lacks the fact), except the salary inconsistency. | Profile additions, not code: `education[].honours` (class text), a "no current salary" choice that writes 0 / Nil for a new graduate, `identity.title`, a referees list, `documents.transcript`. Today "Add it" for honours points at `education[0].grade`, which holds the CAP other forms need: overwriting it breaks them. |
| 7 **LOW** | **Status wording "immigration status in Singapore".** "What is your current immigration status in Singapore?" with Citizen / PR / EP / S Pass ends empty (`place not recognised`) even when the place reply is "Singapore"; "Your work authorisation status in Singapore" and "Citizenship / immigration status" pass. | occasional | over-protection | Add "immigration status" to `status_phrases()`. Risk: low. |
| not a stop | **Required free text** ("Why X?", "tell us about a project"): 6 compose targets in 5 forms, written by the tailor round trip; this review did not test it. Under strict the same fields stop (`compose_needed: off`). | very common | n/a | Make sure the tailor path is on whenever fill_policy is always (design: required targets bypass `COMPOSE_OFF`). |

## 4. Strict comparison (what is live today)

`run_strict.py` replays `pagefill._decide` (locks, then a competent scripted model that cites a profile fact or a verbatim resume line and says unknown otherwise, then `guards.decide`) with no browser, on all 12 forms. It is generous to strict: it gives the model `model_sees_sensitive` and counts the 73 required fields that failed only because the harness has no entry sections as answered.

| form | required | strict unanswered | always unanswered (c) |
|---|---|---|---|
| 01 Northwind Bank (Workday) | 40 | 12 | 1 |
| 04 Kestrel Labs (Greenhouse) | 25 | 8 | 1 |
| 10 Meridian Bank (SF) | 39 | 20 | 10 |
| all 12 | 375 | **125 (33%)** | **22 (6%)** |

Strict stops every one of the 12 forms (at least 7 required fields unanswered each: declarations "attestation not recognised", NS and consent boxes "profile rule ... no offered option fits", how-heard, notice, dates, free text); always stops 8 and passes 4. **Yes, the always filler is the improvement the owner asked for in kind**: unanswered required fields fall from a third to 6%, and the stops that remain are mostly specific, fixable, or true profile gaps. **It is not yet "filled completely" in practice**: two of three applications still stop, mainly on items 1 to 5 above, four of which are over-protection that the profile already answers.

## 5. The owner's open question, in numbers

Required privacy boxes that share with affiliates, group companies, related corporations, a parent / subsidiaries or "third parties": **4 of 12 forms** stop on them today (02 Acme, 06 Initech, 10 Meridian, 12 Pinnacle). Three more hold a sharing or transfer wording that the recogniser does not see and are **ticked**: 05 ("transfer to ... studios in other countries"), 08 ("disclosure to our affiliated funds and portfolio companies"), 11 ("transferred to and processed by Harbour Shipping Group companies and its service providers in other countries"). So **7 of 12** forms ask it, 4 stop, 3 pass inconsistently. **Forms that stop for that reason alone: 0** (each of the 4 has another stop). Form 02 would stop for it alone once the US wording (rank 3) is fixed; 06, 10, 12 carry real profile gaps as well. If the owner agrees, one more form (02) is ready after the US fix, and the other three still need the profile data of rank 6.

## 6. What the owner sees when a page stops, and the dead ends

Read from `contracts.py` (`REASON_TEXTS`, `basis_text`, `REMEMBER_REFUSED_*`), `web/src/attempts.js`, `WhatWasSent.vue`; I did not run the web app.

- `owner_fact_missing` with a profile field (grade, current salary, date of birth): chip "Needs one detail: <fact>", "Add it" opens that field, Try again: **workable** (honours caveat in rank 6).
- `document_missing`: chip "Needs one file: Academic transcript", Add opens Files: **workable**.
- `consent_refused` retention / marketing: chip "Needs your agreement: ..." and the Consents group has those toggles: workable, but for rank 4 the sentence names the wrong consent ("receiving marketing messages") for a plain retention box.
- Row "What was filled": an unanswered field shows only **"Not answered"** (`BASIS_NOT_ANSWERED`, contracts.py:1311); the reason in the note ("place not recognised", "F2: not classed", "F4: never the applicant's own contact") is **not shown there**. "Answer for next time" works for ordinary and other-person fields (Title, referee: workable) and is **refused** for declarations, consents, work rights, sponsorship, self-ID and owner facts ("This answer follows your details. Change it in Your details.").

**Dead ends:**
1. **Sharing consent (rank 2).** Chip: "Needs your agreement: sharing your details with other companies" / hint "To agree, change it in Profile → Consents". The Profile form has no such field (`consents.third_party_sharing` is in `always.py:3375` only; `grep` finds it nowhere in `applicant.py` or `web/src`). The box's own "Answer for next time" is refused. The owner cannot agree even if they want to. **HIGH.**
2. **False "bank details" (rank 1).** "Stopped ... your bank account details, which your details can't hold ... Apply by hand, or skip", no Try again, for a question that never asked for bank details. **HIGH.**
3. **US work rights (rank 3).** The row says "Not answered"; the owner opens it, "Answer for next time" says "follows your details, change it in Your details", but Your details already say No for the US. A loop with no exit. **HIGH** by the bar (no way forward).
4. Gender / race / marital with no decline option (form 10): the stop text names the profile ("no gender option matches your profile (prefer not to say)") and the owner can set a value in the profile; workable, but the owner has to decide to put a real gender into the profile to apply to such forms.

## 7. For the other two reviewers: a WRONG protected answer written

`probe_cases.py sponsor sponsor2` (scripted model that labels class `ordinary` and answers the opposite of the truth): the filler **wrote "Yes" to a sponsorship question** (the applicant "requires sponsorship") on:
- "Will you require us to sponsor you for a work visa?"
- "Would you need Example Co to sponsor you?"
- "Will you require Contoso Logistics to sponsor you for a work visa or employment pass now or in the future?" (form 03, realistic run)

`probe_codekey.py`: `always.code_key` returns `(None, '')` for these three wordings (the verb frame "sponsor you" is not keyed), so with the model's class also wrong nothing protects the field. Wordings with "sponsorship", "visa sponsorship" or "sponsor your work pass" are keyed and corrected ("votes: the check and code agree (No); the AI answered Yes"). Needs the model to be wrong on both class and value; the verb-frame wording is common ("Will you require us to sponsor you ..."). Also noted, not a defect: an optional "keep my details on file ... and contact me about other opportunities" box is left unticked (talent-pool consent false), which is the protective end.

## 8. Plain-words summary for the owner

With the sample profile and a well-behaved model, about a third of ordinary Singapore new-grad applications would now go through to "ready to submit"; the other two thirds stop on one to ten fields. The old (strict) behaviour stopped every form I tried and left a third of the required fields blank; the new one leaves 6% blank, so it is clearly the better product. Most stops are not mysterious: five of them are the filler being too careful about something your profile already answers (a bank's name in a question, a consent that says "for recruitment", a "US work rights" question, an "I authorise background checks" box, an "immigration status" list). Fixing those would take it to about 7 of 12, and your decision on "may my details be shared with the employer's affiliates" adds one more. The rest are real gaps (honours class, transcript, no previous salary, referees, NRIC, a gender list with no decline option), and you can close most by adding them to your profile. Today three stops leave you with no way forward on screen (the affiliates box has no switch in Profile, the "bank details" message is false, the US question says "see your details" when your details already answer it). That is what I would fix before turning it on, together with one safety hole: three "sponsor you" wordings can still get a wrong "Yes".

## 9. Findings by bar

- **HIGH (over-protection, product would not work):** rank 1 (bank), rank 2 (sharing: no field; inconsistent recogniser), dead end 3 (US place, loop).
- **HIGH (for the other reviewers, wrong protected answer):** section 7, "sponsor you" wordings.
- **MEDIUM:** ranks 3, 4, 5, 6.
- **LOW:** rank 7; the misleading stop notes ("F2: not classed ...") that are not shown to the owner anyway.

## 10. Reproduce

`JOBSCRAPER_OLLAMA_AUTOSTART=0 PYTHONPATH=src python docs/reviews/Q-121-unlock-A-probes/run_corpus.py both` (about 3 min), `.../probe_cases.py [bank|privacy|privacy2|authorise|sharing|sponsor|sponsor2|status|status2|salary]`, `.../probe_codekey.py`, `.../run_strict.py`. `python tests/run_tests.py -k always` was not re-run (no code changed).
