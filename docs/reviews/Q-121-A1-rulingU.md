# Code review 4: Q-121 ruling U (D-212) as built, `int/Q-121` @ e676c3c

Reviewer, 2026-11-14. Scope: `git diff 7b4b428..e676c3c -- src/jobscraper/apply/always.py src/jobscraper/apply/facts.py` (fix2 A-E, fix3 / U1-U7 / N1-N11, U8, U8b), read against D-212 (U1-U5, U8b, W) as given in the delegation, the third review (`docs/reviews/Q-121-A1-fix1.md`) and the engineer's claims in `comms/outbox/software-engineer.md` ("Q-121 A1 fix2 and fix3" onward): checked, not trusted. Every cell below was produced by a stdin script on the tests' `FakeAsk` / `_pf` builders and the dummy sample profile (employer "Example Employer", past employers "Example Logistics Pte Ltd" / "Sample Analytics"): no model, no network, no browser, no server, no apply job, no `data/`, no `.env`. Probe scripts are in the session scratchpad, not in the repo. About 6,000 grid cells and 300 single probes.

Notation. `X~/n` = the field ends with X, `~` = marked assumed, `n` = model calls after the fill call (pick / confirmation / meaning calls). Conditions: model R / W / S = right / wrong / silent; class = right / `ordinary` / missing; confirmation c = R right / F flipped / U unusable; meaning m = faithful ("no" for the right value, "yes" for the wrong one) / "no" / "yes" / inverted / unusable.

## Verdict

**NOT READY for the owner's switch-on. Ruling U is implemented as stated and the third review's N1-N6 are closed, but two HIGH findings remain, both in the one place ruling U still trusts: code's own reading of a question's direction (F1) and the truth the vote is built on (F2).** No cell writes a contradiction from a RIGHT model plus a right confirmation. No path writes code's reading without at least one model answer agreeing with it. Where a class is named by either key, a contradicting value needs three wrong model answers (model, confirmation, meaning) in every cell I ran **except** the F1 family, where code's reader is wrong and counts as the second vote.

- **F1 (HIGH, safety).** The reader still decides "which option is the owner's truth" by a deny-list of negation / polarity words. A wording that inverts the question with a word not on the list gets a confident, WRONG reader option. Then U1 writes a lazy wrong "No" with **no call**, unmarked; and a right model's "Yes" followed by ONE flipped confirmation writes the reader's wrong option (U3). Declarations ("Is your criminal record satisfactory?", "Are you a fit and proper person?", "Are you independent of ...?") and, worse, work rights ("Do you have any restrictions on your right to work in the United States?" -> "No", an over-claim) are affected. The third review's N1 / N2 closed the words it listed; the class of defect is the same.
- **F2 (HIGH, availability, fail-closed).** A profile with any declaration true, OR an application to an employer the owner has already applied to / worked for, makes the owner's truth for `declaration:other` unknown, so **every** adverse-history question ("Have you ever been dismissed ...?") ends EMPTY with a right model and no confirmation call: 32 of 49 wordings in my set. Every second application to the same company stops at the first such required question. Introduced by U (before U the model's answer stood).

Blocking: F1, F2. Everything else is MEDIUM / LOW. Smallest fixes are at the end of each finding. The rehearsal should run after F1 / F2, not before.

## 1. Ruling U, clause by clause (implemented as stated?)

| Clause | As stated? | Where | Evidence |
|---|---|---|---|
| U1 model = reader's option -> written, no call | **yes** | `always.py:3540-3542` (`_u_decide`), `write_truth` 3477-3502; box left unticked counts (`c_raw`, 3539) | declarations, work rights, boxes: 0 picks on agreement in every grid |
| U2 differ / no reading / silent -> ONE confirmation, no A5 round | **yes** | `3543-3549` (`vetoed`, `protect_now`, `vote = "U"`), A5 `need` excludes `protect_now` (5084-5086), call `4567` -> `_u_confirm` 4509-4528 (tick box: 4516-4524 "Should the box «...» be ticked?") | silent model: 1 confirmation (grid rows S) |
| U3 confirmation = reader -> written; = model's first -> ONE meaning call | **yes** (one carve-out, see below) | `4572-4577`, `4578-4598`, meaning `4592-4595` | right model + agreeing confirmation + meaning "no" writes with 2 calls, "yes" / unusable -> empty, in all class conditions |
| U4 protective end never writes code's reading | **yes** | `protective_end` 4667-4672 returns `u_vote_end` or `_blank_end` for every U class; none-applies only when the confirmation named it 4599-4602; `last_resort` always has a rule for a U field (4838-4847) | no cell with a failed vote ends on the reader's option (grid, 6,000 cells) |
| U5 the negation list gates nothing | **yes, as stated** | `decl_mode` (3505-3522) is not reached for a U class (3659-3660); the list only decides whether the reader HAS a reading (`_as_asked` 1860-1895, `no_reading` 1935-1938, `_declaration_rule` 2905 / 2933-2935) | see F1: that is exactly why an unlisted word is a hole |
| U8 silent model: confirmation's value after its meaning call | **yes** | `4624-4632` | S rows: `value~/2` only when the meaning says "no" |
| U8b no reading, two differing answers: meaning on BOTH | **yes** | `4603-4623`; second call skipped when the first is unusable (4609-4610) | R/F/inv and W/R/inv rows write the "own says no, other says yes" value |
| W firm truth vetoed in both directions, then U2-U4 | **yes** | `_work_truths_firm` 3019-3036, `_work_under_claim` 3039-3054, `_work_in_h` 3110-3141, `_work_rule` 3057-3107 | US (firm No), Germany (derived), SG: only the 3-wrong cells contradict. The veto itself is subsumed by U2 (any difference votes); H only decides whether the meaning call runs (4590) |
| U6 page cap `3 x chunks + 20 + 3 per voted field` | **yes** | `CALLS_PER_VOTE = 3` (233), `_vote_budget` 4994-4999, `5063` | 16 bare nouns, right model: 27 calls vs cap 71 |
| fix2 A own contact in an employer / school / referee entry | yes | `entity_contact` 2383-2399, `hard_checks` 1218-1220, prefill 4939-4942 | own phone / postal / address / email in an entry -> N/A or empty (probe table section 6) |
| fix2 B grade list only from profile / resume | yes | `_fact_in_h` 3261-3276, `protective_end` 4769-4781 | `First Class / Second Upper / Other` + required -> owner-fact stop; `4.0 - 4.5` -> that band |
| fix2 C "Your / My" labels are the applicant's own | yes | `facts.py:662-669` | "Your phone number" in a referee group -> the applicant's value |
| fix2 D protected class only the model names, default cite -> one re-check | yes | `3630-3638` | one extra fill call, then the table; see section 5 on the in-flight fix |
| fix2 E keep-on-file frame is retention | yes | `3617-3618` | marketing class + "keep my application on file" -> ticked as retention |
| N3 a mapping note is part of the question; a narrowing note is not | yes | `_core_question` 1898-1915, `_SCOPE_NOTE_RE` 1921-1924 | N3 rows: "Select Yes to confirm you have none", "(Yes = none)", "Answer Yes if you have never been bankrupt" have no reading; "(Do not answer yes for traffic offences)" keeps `No` |
| N4 / N5 / N6 | yes | `entry_pay_unbacked` 2419-2426, `_OTHER_PERSON_FACT` 2375-2378 / `fact_which` 2456-2457, `protective_end` 4680-4685 | education GPA with "First Class" -> the profile grade; experience Salary 3200 / 5000 -> "N/A"; Age with unusable check -> required stop / optional empty |

U3 carve-out (not a finding): when the confirmation repeats the model's first answer and the reader says that value is NOT the contradicting one (`in_h` False), no meaning call runs (4590-4592). This only happens for decline-type values ("Prefer not to say", "N/A"); the ruling's "whether the reader takes that value as contradicting or has no reading" does not cover it. Accept.

The third review's tables: N1 (clean / spotless / clear: 5 wordings x R/W/O/M x cR/cW/cU): closed, the only contradictions are the 3-wrong cells (model wrong + confirmation wrong + meaning wrong, or the U8b mirror). N2 (5 negated work-rights wordings): closed, same. N3 (5 wordings): closed. N4 / N5 / N6: closed (N5: code never writes the owner's date of birth into a dependant's field; a MODEL that copies it there still stands, LOW 6.3). Over-protection items 1-3 of that review: closed, the three "Tick if ... not" boxes end ticked with a right model (U8 / U7), the `rf1` box too.

## 2. Findings

### HIGH

**F1. A wrong reader option is a vote.** `always.py:1929-1938` (`_POLARITY_WORDS`, `no_reading`), `1880-1895` (`_as_asked`), `2851-2855` (`_decl_applies_yes`), `3083-3093` (`_work_rule`: for a yes/no, `want = need if sponsorship else auth`, no other reading), `3540-3542` (U1), `4572-4577` (U3).

Reader is read off a deny-list: any wording with no listed negation / polarity word is read as "Yes = the adverse thing applies" (declarations) or "Yes = authorised" (work rights). A question whose Yes means the opposite, with a word not on the list, gets a confident wrong option.

Declarations. Truth: all false (sample profile), so the right answer to a positive-polarity question is Yes. Class right = `declaration:<class>` (code's own key finds the class on the criminal-record ones, so class `ordinary` / missing behaves the same). Model "No" is the lazy default.

| Wording (Yes/No, required) | reader option | model W "No" (class right) | model R "Yes" + flipped confirmation "No" |
|---|---|---|---|
| Is your criminal record satisfactory? / acceptable? / Do you have a satisfactory criminal record? | No (wrong) | **`No/0` unmarked, no call** | **`No~/1`** |
| Is your disciplinary record satisfactory? | No | `No/0` | `No~/1` |
| Can you pass a criminal background check? / Are you able to pass ...? | No | `No/0` | `No~/1` |
| Are you in compliance with all non-compete obligations? | No | `No/0` | `No~/1` |
| Are you fully compliant with the conflict of interest policy? / Do you satisfy the independence requirements? | No | `No/0` | `No~/1` |
| Are you eligible to work for the government? | No | `No/0` | `No~/1` |
| Are your relatives independent of Example Employer? | No | `No/0` | `No~/1` |
| Are you independent of Example Employer? / at liberty to work for us? / fit and proper? / financially solvent? / in good financial standing? / Is your financial standing sound? / of good character? / beyond reproach? | No (model class named, code key silent) | `No/0` | `No~/1` |

Work rights. SG citizen sample profile: Singapore authorised, United States firm "not authorised" (`authorised_to_work: {SG: true, US: false}`). Right answer "Yes" to a restriction question for the US, "No" for Singapore.

| Wording | right | model W (lazy) | model R + flipped confirmation |
|---|---|---|---|
| Do you have any restrictions on your right to work in the United States? | Yes | **`No/0` unmarked**: an OVER-claim of work authorisation | `No~/1` |
| Are you restricted from working in the United States? / prohibited? / barred from employment? / Is your right to work ... limited in any way? / Are you subject to immigration restrictions on working ...? | Yes | `No/0` (all five) | `No~/1` |
| Would you be working in the United States on a temporary visa? / Do you require your employer to apply for a work permit for you in the United States? | Yes | `No/0` | `No~/1` |
| Is there any restriction on your right to work in Singapore? / Are you restricted from working in Singapore? | No | `Yes/0`: an under-claim | `Yes~/1` |
| Are you currently on a student visa? / Are you a foreigner? / Are you a foreign national requiring a work pass? | No | `Yes/0` | `Yes~/1` |

Failure scenario (the owner's install, auto mode, no review step). A Singapore posting asks "Do you have any restrictions on your right to work in Singapore?" The briefing tells the model the owner is a citizen. The model's habit, seen in every rehearsal, is a lazy "Yes" or "No" on a yes/no it classes as a declaration; one in ten wrong is enough. The reader says Yes (wrongly), the model says Yes, U1 writes it with no call, no mark. The form is submitted claiming a work restriction the owner does not have. For the over-claim row (a US posting) the same path submits "No restriction" for a country where the profile says the owner is not authorised. With a RIGHT model the exposure is one flipped confirmation (the confirmation is one more model call, on a different prompt).

Why not already caught by U: ruling U's premise is that the reader is a trustworthy vote. For direction, it is only trustworthy for a closed set of frames. This is the same family as reviews 1-3 (code judging a question simple enough to count as a vote); each time the list was extended and each time another word was found.

Smallest fix (design change, ~40 lines): make the reader an ALLOW-list. A yes/no declaration has a reading only when the core question starts with a recognised adverse frame (`have you ever (been|had|...)`, `do you (currently )?have (any|a)`, `are you (currently )?(a|an|subject to|bound by|under|...)`, `has any`, `were you`, `is any member`) AND contains no word from a short positive list ("satisfactory", "acceptable", "solvent", "sound", "fit", "proper", "character", "independent", "compliant", "comply", "pass", "eligible", "reproach", "liberty", "satisfy", "meet"). A yes/no work-rights question has a reading only when it matches one of the closed affirmative frames (`authorised|authorized|eligible|legally|right to work`, `require|need sponsorship|visa|work pass|permit`) and holds none of: restriction(s), restricted, limited, prohibited, barred, foreign(er), temporary, student, non-citizen, unrestricted, "apply for". Everything else is "no reading": confirmation + meaning call (U6), 3 model answers, which is exactly what the ruling wants for a question code cannot read. Cost: extra calls on unusual wordings only. Pin: the two tables above; and for the allow-list, one pin per frame.

**F2. The owner's truth for `declaration:other` (and any classless declaration) becomes unknown for a returning applicant, and U turns "unknown" into "empty".** `always.py:2805-2825` (`_decl_truth`: for `other` or no class the pool is `set(DeclarationLabel) - _NOT_TENTATIVE`, which includes `prior_employment`, `current_employee`, `previously_applied`; any True makes the result None), `2907-2908` (`if t is None: return rule`, so no `truth_text` and no reader option), `4514` (`_u_confirm`: no `truth_text` -> None), `4671-4672` (blank end).

Probe: sample profile, model right ("No", class `declaration:other`, which is also what code's own key says for these wordings), confirmation right, meaning faithful.

| Context | wordings (49: `declaration:*` adverse-history and class-less) | end not-"No" |
|---|---|---|
| base (first application to a company) | 49 | **0** |
| `rctx.previously_applied = True` (a second application at the same company, `store.applied_to_company`) | 49 | **32**, all `-` (empty for the site), **0 confirmation calls** |
| employer = a past employer in the profile ("Sample Analytics") | 49 | 34 empty (3 of them correctly true) |

The 32: "Have you ever been dismissed / fired / asked to resign / refused a visa / deported / under investigation / sanctioned / a party to a lawsuit / cautioned by the police / barred from working with children / denied a security clearance", "Do you have any pending legal proceedings / outstanding judgments / outside business interests / other employment / gifts to declare", "Is there any reason you could not work for us" and the rest. Of the 32, 14 carry code's own key `declaration:other` (a frame plus an adverse noun: dismissed, fired, asked to resign, terminated for cause, legal proceedings, investigation, refused a visa, deported, sanctioned, judgments, barred, lawsuit, contract terminated, security clearance) and end empty whatever class the model names; the other 18 have no code key and end empty only when the model names `declaration:other` (under `ordinary` or no class the model's answer stands), so naming the class makes it worse. The same happens with a profile that sets ONE declaration true (pep=True: "Have you ever been dismissed from a job?" -> empty, 0 calls).

Failure scenario. The owner clicks Auto-apply on a second role at the same company. Page 2 of the form has "Have you ever been dismissed or asked to resign?" (required). The field is left empty for the site's validation, the page ends `fill_failed` / validation error, the attempt fails. Nothing wrong is submitted; the filler simply cannot do the product's core repeat case, and the failure is silent until the owner reads the attempt. Before U (7b4b428) the model's answer stood when T was unknown; U made it fail closed. The same gap hides a smaller one: for a TRUE employer-history declaration the `truth_text` is also empty (`yes` map at 2913 lacks the `_YES_TEXT_EXTRA` classes), so a wrong "No" to "Have you previously applied to us?" with `previously_applied` True ends empty with no call (safe, 0 contradictions).

Smallest fix (3 lines + a pin): in `_decl_truth`, build the `other` / classless pool from the plain adverse-history classes only (the `_PLAIN_BOOLS`: pep, conflict, shareholding, relatives, criminal, bankruptcy, regulatory, non-compete, government) and leave the three employer-specific classes out; when T is still None and the model gave a usable answer, treat it as "no reading" (the confirmation text may be generic: "the applicant has no adverse history unless PROFILE says so") instead of ending empty. Pin: `previously_applied=True` + `Have you ever been dismissed from a job?` + right model -> `No`, `-k` same for the pep=True profile.

### MEDIUM

**F3. A model-named `government_employment` on a military / National Service question: the reader says "No" and the confirmation text does not handle it.** `always.py:2900-2955` (`_declaration_rule` has no NS / military check; `declarations` 501-520 marks such questions unsure for its own key), `1386-1394` (`owner_truth_text` carries the NS sentence only as a parenthesis). Probe, sample profile (`ns_status: completed`), "Have you served in the military, including National Service?", model class `declaration:government_employment`: model R "Yes" + confirmation "No" -> **`No~/1`** (a false claim of no military service); confirmation "Yes" + meaning "yes" -> empty/2; confirmation "Yes" + meaning "no" -> `Yes~/2`. With model class `ordinary` the model's "Yes" stands (`Yes~/0`). A careful model follows the parenthesis ("a question that counts National Service uses the National Service status in PROFILE"), a lazy one echoes the headline. Fix: when the label holds an NS / military term with no exclusion, the reader has no reading and the confirmation text states the NS status ("has completed National Service (ns_status)"); the code has the term list at `declarations.py:505-516`. Not HIGH only because it needs a model-named class and a model flip on the confirmation.

**F4. Two meaning sentences can be read "no" for a truly contradicting value.** `always.py:4537-4555` (`contradiction_text`), `4420-4424`.
- Unauthorised truth (`not auth`): the sentence is only "the applicant is authorised to work there". "Do you require visa sponsorship to work in the United States?" answered "No" (a false "needs no sponsorship") asks "does that state that the applicant is authorised to work there?"; a literal reader answers "no", so three agreeing answers (model "No", confirmation "No", meaning "no") write the over-claim. Fix: "...is authorised to work there, or needs no visa sponsorship there" (the other two branches already name both).
- Class `other`: the sentence is a five-way list ("dismissed or asked to resign, is in litigation, under investigation or sanction, or refused a visa or deported"), but the model names `other` for ANY unrecognised adverse question ("Do you have any outside business interests?", "other employment", "gifts to declare"). A "Yes" to those is not literally one of the five, so a literal meaning reply is "no". Fix: for `other` use the generic sentence "the applicant reports an adverse event or an interest that PROFILE does not state".
Both only matter after two wrong answers (model, confirmation).

**F5. A transport failure inside a vote is swallowed as "the check did not agree".** `always.py:4371-4372` (`_confirm_pick`), `4461-4462` (`verify_meaning`), `4522-4523` (`_u_confirm`), `4415-4416` (`own_fact_check`): `except (BackendError, TimeoutError): return None`. Probe: an `ask` that raises `BackendError` on every pick call. Page outcome `transport_failed=False`; each voted field ends `unknown`, note `left empty for the site's validation: declaration:criminal_record: the check did not agree: left for the ...`. It fails closed and names the field, but (a) the audit says "did not agree" for a model that was down, (b) the flow never retries the page (`transport_failed` is what makes the attempt retryable), so a 10-second Ollama blip in the middle of a declarations page becomes a permanent validation failure. Fix: let the `BackendError` / `TimeoutError` out of these four helpers; `fill_page_always` already turns it into `transport_failed` (`5121-5126`). The third review noted the same (section 3); ruled "not a retry"; I think the ruling should change now that every declaration costs a confirmation.

**F6. Protective "empty" is not empty on a required field the site pre-filled.** `pagefill.py:1135` (`_always_apply_one`: `if ans.status is not FILLED: return`), `always.py:4294-4299` (`_blank_end`). Probe: a required radio with `shown="Yes"`, origin `site_default`, the model keeps it, class `declaration:criminal_record` or `pep`, confirmation "Yes" and meaning "yes" (or unusable): the answer is `unknown`, value None, and the page leaves the site's "Yes" in place; the empty-required scan does not see it (the field is not empty). U4 promises empty / unticked. An optional field is cleared (`BLANK_OPTIONAL` -> `reset_field`). Rare (sites seldom pre-select an adverse option) but this is the one place the protective end does not protect. Fix: for a required vetoed declaration with a site-supplied value, `_blank_end` returns `BLANK_OPTIONAL`-style "clear it" or the flow stops `profile_gap`.

### LOW

- **F7.** `declaration:other` / class-less adverse wordings outside the frame list have no code key at all, so a model that names no class, or `ordinary`, and answers wrong is written with no call (accepted R2 / M8). Measured on my 58 wordings: no key for "Have you served in the military?", "Have you been involved in any fraud?", "Has any regulator ever taken action against you?", "Are you a director of any other company?", "Do you have any outside business interests?", "Have you ever been cautioned by the police?", "Do you have a spent conviction?", "Have you had any adverse findings by a tribunal?", "Have you ever resigned in lieu of termination?", "Is there any reason why you could not work for us?", "Is it true that you have never been dismissed from a job?", "Are you in good standing with all professional regulators?", "Are you a Singapore citizen?" (work rights by citizenship). Their wrong answers end `W/ordinary` -> written, unmarked or assumed, 0 calls. A silent model on the same wordings ends F2's generic "No" (assumed, counted against `last_resort_max`). First-person statement boxes ("I agree that I have been dismissed from a previous employer", "I acknowledge that I have a conflict of interest with Example Employer", "I accept that I have a relative working at Example Employer") have no key: a model that ticks them with no class (or `ordinary`) is written `T/0`, and for the first one a SILENT model ticks it too through the last-resort ladder (`SR=T/0`). Fix: broaden `_OTHER_FRAMES` / `_ADVERSE_NOUNS` (fraud, cautioned, tribunal, adverse finding, resigned in lieu, "reason ... could not") and add "is it true that you have (never)" to the frames; a silent model on an unkeyed required box should stay unticked.
- **F8.** Mis-key: "Are you registered on any sex offender register?" keys `self_id:gender` ("sex"), so the field stops (`validation_error`, "no gender option matches your profile") with a right model under every model class, `ordinary` and none included (probe: 3 of 3 conditions). "I confirm that none of the following apply" etc. are fine.
- **6.3** (owner-fact / other-person regressions, ten-plus labels of mine, section 6): a model that copies the owner's date of birth into "Date of birth of dependant" or the owner's address into a stand-alone "Hospital address" (outside an entry group) is written, assumed; code never writes it. An unusable own-fact check on "Home address" / "Postal code" keeps the model's invented value, assumed (the ruling the third review disagreed with, N6 shared facts).
- **F9.** `pick_call` retries an unparsable reply once (N11): one vote can cost 4-6 page calls; the cap `3 per voted field` can be hit only by a stuck model (intended: content failure).
- **F10.** Health declaration (`declaration:health`): a RIGHT "Prefer not to say" (the owner's `health_disclosure: decline`) and a "Yes" end empty with 0 calls (no truth text, no reader for a three-option list): the known gap being fixed by the tester. Compound work rights ("authorised to work in Singapore and the United States?") has no single truth: empty with a right model.

## 3. The meaning call and the confirmation's "truth in plain words"

Sentences as built (`4439-4463`, `4537-4555`; one line, label capped at 200, value at 80, no newline):

| Class | Statement (meaning call) | Verdict |
|---|---|---|
| criminal_record, bankruptcy, pep, conflict, shareholding, regulatory, non_compete | the class's `HAS ...` sentence, lowercased | unambiguous, both polarities (a "No" to "Is your record clean?" -> does that state the applicant HAS a criminal record -> yes). I could not get a literal reader to answer "no" for a truly contradicting value in either polarity |
| relatives_at_company | "has relatives working at the employers applied to" | ambiguous only for "Is your manager a relative?" (a manager is not "relatives working at") |
| government_employment | the military sentence with the NS parenthesis | F3 |
| prior_employment / current_employee / previously_applied | `_YES_TEXT_EXTRA` | fine; but `truth_text` for the TRUE case is empty (F2) |
| other | five-way list | too narrow for what the model labels `other` (F4) |
| health / disability / nda_willingness | no statement -> meaning call returns None -> protective end | by design (empty); F10 |
| work rights, authorised and no sponsorship needed | "is not authorised ..., or needs visa sponsorship" | fine |
| work rights, authorised and needs sponsorship | "is not authorised ..., or needs no visa sponsorship" | fine |
| work rights, NOT authorised | "is authorised to work there" only | F4: misses "needs no sponsorship" |
| tick box | "does ticking it / leaving it unticked state that ..." | fine; a box ticked "I am not a PEP" asks what ticking states |

The confirmation's plain-words truth (`truth_text`): correct for every false-declaration class; for a profile with a TRUE declaration it states the profile row ("The applicant has a criminal record, charge or proceeding.", source `profile:declarations.<class>`) and is correct, except (a) a compound question naming two classes where only one is true states BOTH as true ("has a criminal record; and has been bankrupt"), a right answer (Yes) but a false sentence, (b) `government_employment` (F3), (c) the five employer-history classes with a TRUE value have none (F2).

## 4. Cost

Measured with the fake, one page of 20 `RADIO` Yes/No declarations (count = fill calls + pick calls):

| Page | calls | cap (3 x 1 + 20 + 3 per voted field) | wrong values written |
|---|---|---|---|
| 20 plain wordings, model right | 3 (1 + 2: two wordings have no reading) | 29 | 0 |
| the same, model wrong on 5, confirmation right | 8 | 38 | 0 |
| the same, model wrong on all 20, confirmation right | 23 | 83 | 0 |
| 16 bare-noun labels ("Criminal record", "Bankruptcy", ...), model right | 27 | 71 | 0 |
| same, model wrong on 5 | 32 | 71 | 0 |
| same, model wrong on all 16 (the one written "Yes" is "Pending litigation": no key at all, F7) | 42 | 71 | 1 |
| 24 mixed (16 bare + 8 plain), model right | 28 | 2 chunks | 0 |

The cap cannot end a correct page except through repeated unparsable replies (F9). A transport failure mid-vote fails closed (empty) but is not retried and the audit says "did not agree" (F5).

## 5. Over-protection, counted

Right model on every field, right confirmation, faithful meaning. Counted over my wordings (49 adverse-history / declaration + 19 declaration yes/no and list + 12 statement boxes + 19 work-rights + the 4 true-declaration rows):

| Context | ends empty or stopped | List |
|---|---|---|
| first application, all declarations false (the owner today) | **0** of about 100, apart from the rows below | |
| a second application at the same company (`previously_applied`), or a past employer | **32 of 49** adverse-history wordings (F2) | dismissed / fired / asked to resign / deported / refused a visa / under investigation / lawsuit / judgments / regulator action / fraud / police caution / tribunal / outside interests / other employment / gifts / "any reason you could not work for us" / spent conviction ... |
| any profile with ONE declaration true | every `other` and class-less wording | same list |
| `declaration:health` with a right "Prefer not to say" | 1 (F10) | "medical condition that may affect your work" |
| the statement "sex offender register" | 1 stop (F8) | |
| compound work rights across two countries | 1 | "authorised to work in Singapore and the United States?" |
| `First Class / Second Upper / Other` grade list with only a numeric grade in the profile | 1 stop (fix2 B, correct fail-closed) | |

Frequency on real forms: the 32 are the most common adverse-history questions on corporate forms (dismissal and legal-proceedings questions appear on nearly every large-employer form); F2 makes the whole group unavailable on every re-application. The other four are rare.

## 6. Regressions outside the vote (fix2 A-C, N4-N6; ten-plus labels of mine, class `ordinary`)

Own contact in another party's field: "Phone number" (employer entry) with the applicant's phone -> "N/A" (the filler's own F4 last resort); "Postal code" (employer entry) own -> "N/A"; "Address" (school entry) own -> "N/A"; "Contact email of previous employer" own email -> "Available on request"; "Referee email" (reference group) own email -> empty (required stays for the site); "Previous employer phone" / "Reference phone" own phone -> "Available on request". Own detail where it is the applicant's: "Your email address" after "Referrer details" -> the applicant's email; "Your phone number" in a referee group -> the model's own number (assumed) -- that is the intended fix2 C. Grade: education "Grade / GPA" "First Class" -> `4.20 / 5.00` from the profile (1 call 0); "4.20/5.00" -> kept. Salary in an experience entry 5000 / 3200 -> "N/A". Age 1999 + unusable check -> required stop `owner_fact_missing` / optional empty; "Home address" / "Postal code" 88 Orchard Road / 123456 + unusable check -> the model's value, assumed (ruled). Dependant date of birth: the model's value even when it is the owner's own date of birth (assumed, not code's write). Standalone "Hospital address" with the owner's own address from the model -> written, assumed (fix2 A only checks entry groups). None of these is reachable under `strict` except `facts.py` (the six-word other-person list and the "Your" rule), which only writes LESS (other-person labels) or the same as before A1-P ("Your ..." labels), as the third review found.

## 7. Evidence run (this worktree = int/Q-121 e676c3c + the review)

`python tests/run_tests.py -k always_a1` -> `205/205 passed`; `-k facts` -> `22/22 passed`; `-k pagefill` -> `22/22 passed`; `-k llm_fill` -> `100/100 passed`; `-k layering` -> `13/13 passed` (my worktree only; no browser, server or apply job started). The tester's pins (`tests/test_always_a1_u.py`) pass because they use the wordings of the third review; none of F1-F6 is in them.

## 8. Residuals I accept, and who sees each

| Residual | Who sees it | Mark |
|---|---|---|
| Model wrong AND confirmation wrong AND meaning wrong writes the contradiction (the ruled three-vote residual); confirmation independence is unmeasured | owner reads `~` (assumed) and the note "votes: the AI's answer, the check and a meaning check agree" in the Applications audit | assumed, `check: <class>` |
| Both keys silent (no code key and the model names no class / `ordinary`) on an adverse wording code does not list (F7): the model's answer stands | nobody (no mark unless the model marks it) | none; this is the largest unmeasured exposure |
| U8b writes a value contradicted by TWO of the three first answers only when three answers (confirmation + both meanings) say so | owner (`~`, note names both answers) | assumed |
| N6 shared facts keep the model's value on an unusable check | owner (`~`) | assumed |
| Model labels a true declaration ordinary and the owner's profile has a true one (the owner's profile today is all false) | n/a today | |
| "Have you worked on similar roles before?" labelled `non_compete` and answered "No" (rehearsal): the in-flight class-correction re-ask is a sound extra signal, but another call to the same model; a deterministic anchor (the label must hold at least one word of the class definition or the class is dropped) is cheaper and does not depend on the model's agreement with itself. Do both; keep the re-ask for labels that pass the anchor. It must never run for a class code's own key names |

## 9. What the final rehearsal must watch

1. F1 wordings in all four model conditions, with the reader's option, the confirmation, both meaning replies and the written value logged: the satisfactory / acceptable / independent / compliant / pass-a-check / restriction / limited / prohibited / barred / temporary / student / foreigner set (tables above), and the owner's real work-rights profile for US / UK rows.
2. F2: `previously_applied` True and an employer the owner worked for, on a page with five adverse-history questions; also a profile with one true declaration. Count empties.
3. Confirmation independence: how often the confirmation repeats a wrong first answer, how often a right first answer gets a flipped confirmation, and how often the meaning call is "no" for a contradicting value (F3, F4). The whole residual rests on these rates.
4. Required statement boxes with "not" / "none apply" (ticked now); first-person adverse boxes with no key (F7); a silent model on an unkeyed required box.
5. Military / National Service wordings under class `government_employment` and `ordinary` (F3).
6. A page with the model unreachable for the confirmation calls only (F5).
7. A required declaration pre-selected by the site (F6).
8. Calls per page on the heaviest real page (the cap formula holds; the number to record is calls per voted field).

## 10. What can still go wrong after switch-on, for the owner (plain words)

Each Auto-apply click fills the form and submits it with nobody checking. The filler is now much safer than before: for the sensitive questions (criminal record, bankruptcy, being a political figure, relatives or conflicts at the company, non-compete, whether you may work in the country) the program no longer puts its own answer over the model's answer on its own, it asks the model a second and sometimes a third time and writes a sensitive answer only when the answers agree, and it marks such answers as assumed so you can see them in the attempt record. What can still go wrong: (1) a question worded with an unusual word (for example "Is your criminal record satisfactory?" or "Do you have any restrictions on your right to work in ...?") can make the program misread which answer is the true one; then a lazy or mistaken "No" from the model is written straight in with no second look, and that can be a wrong statement about your record or your right to work, shown as if it came from your profile. (2) If you have already applied to a company, or worked there, nearly every adverse-history question on its form (dismissed, legal proceedings, investigation) is left blank, and the application stops at the first required one; that does not put a wrong answer in but you will see repeat applications fail. (3) On a question the program does not recognise as sensitive and the model does not flag either, the model's answer stands unchecked. (4) If your local model is switched off or crashes in the middle of a page, the sensitive questions are left blank and the application fails instead of waiting and trying again. Fix (1) and (2) before the switch-on; read the first attempts' sensitive answers row by row.
