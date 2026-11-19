# Q-121 unlock review S2: consents, declarations, class stamp

**Verdict: NOT READY for an unlock that sends for real, FOR THIS PART (consents).** Two HIGH findings, both in the same family: code decides consents from word lists, and the lists are short. H1: a marketing / contact consent worded in a way the frames do not read is ticked against `talent_pool_opt_in = false`; in a box that bundles it with a privacy consent, **code itself writes the tick over a model that refused** (45 of 66 bundles). H2: a third-party sharing box naming a recipient outside the closed list ("sister companies", "subsidiaries", "customers", "parent company", "background-check vendors", ...) is ticked as the privacy consent (D-224 5a says: stop). Declarations (question 4) and the class stamp (question 6) have no HIGH. Everything the earlier reviews closed for consents (H3, N2 as written, R, M8, G1 / closure H1) still holds for the wordings those reviews named. The fixes are the same inversion D-220 already applied to retention: allow-list the pure privacy form, give everything else the strict path.

Branch `rev/Q-121-S2` (from `tst/Q-121-G2` 5f1b215). Range read: `git diff 599fd44..HEAD -- always.py facts.py` plus `apply_flow.stored_class`, `web/remember.remember_refusal`. All probes are in `docs/reviews/Q-121-unlock-S2-probes/` (fake models only; `g.py` helpers; run from the worktree root with `JOBSCRAPER_OLLAMA_AUTOSTART=0`). Fakes: the confirmation / meaning replies are FAITHFUL unless a row says otherwise (`c1.py` `faithful`); `S2_PICK=yes` gives the adversarial confirmer.

**Counts.** Wordings of my own: 105 in the consent grid (`wordings.py`: W 75 + W_UNKEYED 16 + W_STATUS 14) as optional box, required box, required and optional yes/no, under 6 model classes (consent_privacy, consent_retention, marketing, ordinary, declaration:other, none), 3 consent profiles (all false, sample, all true), 3 model behaviours (agrees, refuses, basis none) = about 22,000 cells; plus 88 bundles (`b1.py`), 225 sharing-recipient wordings (`sh1.py`), 37 unkeyed-wording probes (`k1.py`), 30 + 9 required-privacy wordings (`q5.py`, `q5b.py`), 9 drop-down consents (`m2.py`), 8 owner-consented cases (`m1.py`), 41 declaration labels / 1,824 cells (`d1.py`), 22 stamp paths (`s1.py`): about 550 wordings. Misbehaved (at least one HIGH cell, any profile / class): 42 of 89 grid wordings; under the sample profile: 33; under the sample profile AND the model's right class: 26 (21 after removing five opt-out wordings whose yes/no meaning the fake cannot settle). Also run: `-k layering` 13/13, `-k q127` 96/96, `-k declarations` 202/202; `-k always`: see the last line of this file.

## HIGH

### H1. Marketing / contact consents the frames do not read are ticked; in a bundle with a privacy consent, code writes the tick itself
- **Trigger.** An optional or required box (or a Yes/No, or a drop-down whose OPTIONS carry the consent) that asks for contact or messages in words `consent_frames` / `consent_key` do not know: "I agree to receive emails from Example Employer", "I consent to receive communications from Example Employer", "Opt in to SMS notifications", "Yes, send me updates", "I agree to be contacted by Example Employer's recruitment team", "I consent to Example Employer contacting me about opportunities", "I agree to be added to the Example Employer talent network", "I would like to receive emails with career tips", "Keep in touch", "I would like to stay connected", "Text me about new roles", "I'd like to hear about career opportunities". `probes/k1.py`: 28 of 37 consent-like wordings have no code key. The vocabulary is `_MKT_VERBS` always.py:2410, `_MKT_OBJ` :2413, `_MKT_CONTACT` :2416, `_MKT_CONTACT_OBJ` :2419 ("be contacted" but not "being contacted" / "contacting me"; "receive" + "job alerts" but not "receive emails / communications / SMS"; "add me" but not "be added").
- **Done, alone (the model decides, L7-like).** `c1.py` (unkeyed list, faithful confirmer): ticked / Yes with `talent_pool_opt_in = false` under EVERY model class, including the right one (`marketing`): `decide` always.py:5705 (`class_correctable`, :2580) sees a consent / marketing class that code's frames do not find in an English label and asks once more with "This question is class ordinary ... not about <marketing>. Answer it from the resume and the profile." (`class_correct_problem`, always.py:186), and the reply is taken as an ordinary answer "whatever class it names" (always.py:5661). So a model that is RIGHT is told by code to stop being right. A required box with a refusing or silent model is ticked by the last resort (`box-req` + refuse / none = true). A drop-down whose consent sits in its options ("Talent community": "Yes, add me ..." / "No thanks"; "Receive emails from Example Employer": "Subscribe" / "Do not subscribe") is not read at all: `m2.py` picks the agreeing option under ordinary / no class, and "Receive emails ..." even under `marketing`.
- **Done, bundled (code writes it, no model mistake needed).** `probes/b1.py`, sample profile, the model says the right class `consent_privacy` and REFUSES: "I agree to the processing of my personal data and to being contacted about other vacancies", "... and to receive emails from Example Employer", "... and to stay in touch", "I consent to the collection and use of my data by Example Employer, and to be added to your talent community" are ticked / answered Yes (optional and required): the label is read as privacy only (classes `['consent_privacy']`), T = `privacy_consent` = true, `write_truth` overwrites the model's refusal (`decide` always.py:5756, both keys agree). 45 of 66 bundles (3 well-formed leads x 22 contact phrases) tick; only 7 phrases per lead are caught ("to receive job alerts", "to be contacted about other vacancies", "to receive updates", "newsletter", "marketing communications", "by recruiters", "for Example Employer to contact me"). The same bundle with the caught phrase stops `consent_refused` (required) or stays unticked (optional): correct.
- **Should be done.** Invert, as D-220 did for retention: a consent-shaped label (box, Yes/No, list) is the pure privacy form only when nothing is left after the privacy frame words and a closed neutral list; any contact / communication word (contact*, email*, sms, text, whatsapp, call, receive, send, update*, news*, alert*, recommend*, event*, notif*, in touch, hear, talent, network, community, alumni, subscribe) adds MARKETING (truth `talent_pool_opt_in`). Read the OPTIONS of a drop-down / radio list. Take the model's marketing / consent class as binding when code has no key (never run the forced "ordinary" correction on a consent or marketing class; at most one neutral class check).
- **Rule check.** D-221 L7 accepted "a consent the model calls ordinary, with no code key for its wording" as a residual. The wordings above are ordinary application-system wordings (the rehearsal page only holds wordings the frames already read: "updates and offers", "marketing communications"), the bundled case needs no model mistake, and the correction rule undoes a CORRECT model class. I rank by the bar, not by L7; the Coordinator may re-rule L7.

### H2. A third-party sharing consent is ticked when the recipient is not in the closed list, and the employer's own name turns any recipient "internal"
- **Trigger.** A tick box or Yes/No about sharing the applicant's details with: sister companies, subsidiaries, parent company, customers, portfolio companies, franchisees, background-check / screening vendors, the government, regulators, referees, recruiters / headhunters / job boards, advertisers, data brokers, investors, "our network", "our vendors", "service providers", "professional advisers". `_SHARE_TO` (always.py:2861) lists third parties, affiliates, partner organisations, group companies, other companies / employers, clients, sponsors, agencies, external recruiters, "recruiters from"; `share_frame` (:2982) needs a verb from `_SHARE_VERB_RE` (not "having access", "use by") AND such a recipient.
- **Done.** `probes/sh1.py` (45 recipients x 5 frames = 225 wordings): 165 are NOT caught as third-party sharing; each ends as the privacy consent (sample profile: `privacy_consent` true) = ticked / Yes, where D-224 5a (truth false; a required tick box stops `consent_refused`, a Yes/No answers No) applies to a third party. Three mechanisms: (1) closed recipient list (above); (2) `internal_share_frame` (:2963) matches `theemployer` in `_INTERNAL_TO_RE` (:2923) wherever the employer's name stands, including as the SHARER: "I consent to Example Employer sharing my details with data brokers / sister companies / background screening providers / advertisers" is classed INTERNAL (the privacy consent) and ticked; (3) "parent" in `_RELATED` (:2825) turns "... sharing with its / our parent company" into a relatives declaration (`['declaration']`, required box ends empty `-`) and "referees" into `other_person`. Consistency: "affiliates", "third parties", "clients", "recruitment agencies", "group companies" stop; "sister companies", "subsidiaries", "customers" tick. `m2.py`: a drop-down "Sharing" with the option "Yes, share my profile with our partner companies" is ticked (options are not read).
- **Q5 table (below)** has the realistic required-box wordings: 8 of 30 stop, 5 that D-224 would stop are ticked.
- **Should be done.** Same inversion: in a consent-shaped label with a sharing verb, every recipient is third-party unless it is in a closed INTERNAL list (hiring team / manager / interviewers / HR / the employer's recruitment team) or the on-behalf sense (D-225). `theemployer` counts as recipient only after "with / to / by", never as subject. Add the missing sharing verbs ("use by", "having access", "available to").
- **Note.** D-224 is the Coordinator's ruling, not the owner's; the owner question on affiliates is open (not ruled here). Whatever the owner answers, the code is inconsistent today: the same kind of recipient stops or ticks depending on its noun.

## MEDIUM

- **M1. A required privacy box that says "collect, use and STORE my personal data" stops the application.** `probes/q5b.py`: "I consent to Example Employer collecting, using and storing my personal data for the purpose of processing my application" -> classes {consent_privacy, consent_retention} (`_RETAIN_RE` always.py:2377 reads "storing my personal data" as keep-on-file); `retention_pure` (:3291) finds residue (collecting, using, purpose, processing, application); `_consent_rule` (:3330) adds MARKETING; `talent_pool_opt_in` false -> `consent_refused` with the detail "receiving marketing messages" (wrong: nothing about messages). 4 of 9 such wordings stop ("storing", "holding", "store ... securely"). Fix: when the privacy frame is among the classes and the retention frame has no future / other / on-file / talent word, it is part of the privacy consent; add collect / use / purpose / recruitment / process / application / securely to the neutral list when CONSENT_PRIVACY is present.
- **M2. "I have read and agree to the Privacy Policy" (the commonest privacy box) is keyed ACKNOWLEDGEMENT; a model that refuses or is silent on it is not repaired.** `probes/m1.py`, sample profile (privacy true): optional box + model refuses -> `false`; basis none -> unticked; optional Yes/No -> "No"; REQUIRED Yes/No + refuse -> "No". `_same_key` does not pair an acknowledgement key with the model's `consent_privacy`, and H is false when T agrees (`in_h` always.py:4976), so nothing writes the owner's true. Every exact-class case (privacy "processing", retention "keep ... on file", certification, "accept the terms") is repaired. Needs one model mistake; MEDIUM by the bar (optional consent the owner HAS given left unticked / a required Yes/No answered No). Fix: `_consent_key_of(ACKNOWLEDGEMENT)` already maps to `privacy_consent` when a privacy notice is named; treat that pair as the same key in `_same_key`.
- **M3. Declaration-like wordings the reader does not class are decided by the model alone.** `probes/d1.py`: "Are you a director of any company?" and "Do you have any outside business interests?" with the model answering Yes under class ordinary / none and a faithful vote: Yes is written (8 cells; with class `declaration:other` they are vetoed). D-55 / D-87 say affiliations are No. One wrong value plus an ordinary class; for a new graduate a "Yes" is improbable (the resume says none). Fix: add directorship, outside business interest, second job, board seat to the declaration reader (`declarations.py`, out of this scope) or to `_OTHER_FRAMES` / `_ADVERSE_NOUNS`.

## LOW

- **L1. Class stamp gaps** (question 6): the early exit for an optional field with model basis none (`decide` always.py:5591) returns before `ctx.decided` is set (:5666), so a BLANK optional consent or declaration carries no class (`field_class` empty, source empty) and "Answer for next time" is offered (`remember_refusal` -> None) on it; `REMEMBER_REFUSED_CLASSES` (contracts.py:1348) lacks CERTIFICATION and ACKNOWLEDGEMENT, so a model-written (source `assumption`) certification is offered too. Owner-initiated and the owner sees the field; but the D-215 / H3 promise ("refused on consents and declarations") has these two holes. Fix: set `ctx.decided` before the early return from `class_string(ck or mk)`; add the two classes.
- **L2.** "parent company" in a consent box makes it a relatives declaration, the required box then ends empty (`-`), the site validation fails (no submit). Part of H2.
- **L3.** NDA willingness is ordinary (D9): a model "No" to "Are you willing to sign a non-disclosure agreement?" stays "No" (truth true; `d1.py` control). A restrictive covenant ("Are you bound by a non-compete?") is read as a declaration and answered No in every cell.
- **L4.** Opt-out wordings ("Tick if you do NOT want to be contacted", "Untick to opt out", "I do not consent to ...", "I opt out of the talent community") have no code reading (`_as_asked` returns None for a negated consent); the model and one confirmation decide. A model that leaves an opt-out box unticked leaves the owner's refusal unexpressed (the site default applies). Known limit; 366 cells. Accepted unless the owner wants opt-outs ticked by code.
- **L5.** A status word inside a consent wording: 14 wordings x 216 cells (`c1.py` S2_LIST=status): no consent / marketing / certification box was ticked from the nationality fact (closure H1 closed). The only HIGH cells are one certification wording that names a spouse's citizenship with `certify_true = false` (all-false profile; the real profile has certify true): the spouse word hides the certification key. A retention box that adds "I am a Singapore citizen" has residue and stops (`consent_refused`): correct by the R rule, rare.
- **L6.** The stop detail for M1 says "receiving marketing messages" for a privacy box; the owner reads a wrong reason.
- **L7 (accepted residual, listed).** Wrong outcome needing a wrong class AND a wrong value, or two wrong calls: ordinary / none class on a consent with a code key (vetoed), double-fault declaration cells (78 cells over 11 labels in `d1.py`: needs a wrong model value plus a wrong confirmation or meaning reply).

## Answers to the seven questions

1. **Closure H1, p21 / p23:** closed in every row (p21: no TICKED anywhere; p23: all "No"). New wordings: see H1, H2, M1, M2. Bundles that tick two consents, opt-out boxes, pre-ticked boxes, drop-downs, long legal text, certifications, acknowledgement vs consent: table 1 below.
2. **Sharing consent:** yes, ticked by many paths (H2). Availability side: 8 of 30 required privacy wordings stop (Q5 table); one of them (M1) stops for a wrong reason; 7 for a recipient word ("affiliates", "subsidiaries", "group", "third parties", "agencies", "partners", "clients"). I did not rule on the affiliates question.
3. **`consent_both_known` and class disagreement:** where code has a key, a disagreeing model class cannot tick against the truth (each key vetoes in its own H, `decide` :5715-5722): no HIGH cell in a wording code reads, for any model class. The optional early exit leaves the box blank when the keys disagree (no tick; an owner consent can stay unticked: M2 and 25 wordings with a MISS cell when the model refuses or is silent under a class that does not match, all with a model mistake). The "class corrected" rule (D-213) today does the opposite of its aim on any consent / marketing wording code does not read: it overrules a right model class (H1). **L7 is NOT the only way** a consent is decided by the model alone: (a) the corrected-ordinary route above with the model's class RIGHT, (b) a drop-down's options, (c) the bundle where code reads only the privacy half and writes it. Likelihood: an optional marketing / "stay in touch" / "emails from X" box is on a large share of application forms; I estimate more than one in three of them are worded outside the frames; the bundled privacy + contact box is the commonest way to ask.
4. **Declarations:** 41 labels (34 yes/no and box wordings, 4 negated forms, 3 NDA controls) x model value (adverse / not) x class (declaration, ordinary, none) x vote reply (faithful, confirm flipped, meaning flipped, both) x required / optional = 1,824 cells. Zero adverse values written for a false truth from a read wording; 8 single-fault cells on two unread wordings (M3); 78 double-fault cells on 11 labels (residual). NDA willingness "Yes" stays Yes; "Are you bound by a non-compete agreement?" and the restrictive-covenant and NDA-signed wordings answer No. The "partner" change did not touch the relatives declaration: "Do you have a spouse, partner or relative working at Example Employer?", "Is your partner employed by ...?", "Do you have a family member or partner who works at ...?", "Do you have any personal relationship with an employee ...?" are answered No in every cell ("Are you a partner in any law firm or business?" too).
5. **Q5 table:** below. 8 of 30 stop.
6. **Class stamp:** table 2 below; the gaps are L1.
7. **Loosened since the last reviews?** H3 (keep-on-file plus contact needs both consents): holds for keep-on-file labels; the same residue idea was never applied to the privacy frame, which is H1's bundle. N2 / M8: held for retention labels. U, U8b, U9-U12, D-87, R: no loosening found on declarations (105-cell grid rebuilt as 1,824 cells). G1 (status word in a consent label): held. D-224 / D-225 are new and are where H2 sits.

## Table 1: consent kinds (sample profile: privacy, retention, certify true; talent pool false). Outcome of the filler when the model agrees / refuses

| Wording kind | Optional box | Required box | Yes/No | Note |
|---|---|---|---|---|
| Privacy "processing of my personal data" (exact frame) | ticked | ticked | Yes | refusing model repaired |
| "I have read and agree to the Privacy Policy" | ticked if model agrees; model refusal stays | ticked (last resort) | model's answer | M2 |
| Retention "keep on file for future roles" | ticked | ticked | Yes | all-false profile: unticked / stop / No |
| Certification "I certify ... true" | ticked | ticked | Yes | all-false: stop |
| Marketing in the frame ("job alerts", "newsletter", "marketing communications") | unticked | left to the site | No | right |
| Marketing outside the frame ("emails from X", "SMS", "stay in touch", "talent network") | **ticked** | **ticked** | **Yes** | H1 |
| Privacy + contact bundle, contact in the frame | unticked | stop | No | right |
| Privacy + contact bundle, contact outside the frame | **ticked** | **ticked** | **Yes** | H1, code writes it |
| Third-party sharing, recipient in `_SHARE_TO` | unticked | stop | No | D-224 |
| Third-party sharing, any other recipient | **ticked** | **ticked** | **Yes** | H2 |
| Privacy "collect, use and store" | ticked | **stop** | Yes | M1 |
| Opt-out ("do NOT want to be contacted") | model decides | model decides | model decides | L4 |
| Pre-ticked box (site default), keyed marketing | unticked (cleared) | n/a | n/a | right (s1 row 7); an unkeyed one stays ticked |
| Drop-down, consent in the options | model decides | model decides | n/a | H1 / H2 |

## Table 2: the class stamp ("Answer for next time" refused?) `probes/s1.py`

| Exit path | `field_class` | source | `remember_refusal` |
|---|---|---|---|
| Profile-set consent box, first pass / must-answer round / last resort | consent_privacy / marketing / certification / acknowledgement | `profile:consents.*` | refused (source and class) |
| Internal and third-party sharing (`share_end`) | consent_privacy | `profile:` or `default:no_third_party_sharing` | refused |
| Declaration, first pass / vote / protective end / last resort | `declaration:<which>` | `default:no_declaration` | refused |
| Pre-selected adverse declaration, vote fails | n/a | stop `validation_error` | n/a |
| Blank OPTIONAL consent or declaration (model basis none, early exit) | **(none)** | "" | **offered** (L1) |
| Unkeyed consent decided by the model (H1 route) | ordinary | assumption | offered (the class it really is is lost) |
| Model-written certification / acknowledgement | certification / acknowledgement | assumption | **offered** (classes missing from `REMEMBER_REFUSED_CLASSES`) |
| NDA willingness, unread declaration wording | ordinary | assumption | offered (ordinary by design) |
| STRICT policy (what runs today) | "" or `declaration:<label>` by `stored_class` | `profile:` / `declaration:` / `field_map:` / `standing:` / `memory:` | refused by source for all but `memory:` (the owner's own saved answer) |

## Table 3 (Q5): 30 realistic REQUIRED privacy / data-processing tick boxes, sample profile, model agrees (`probes/q5.py`). **8 stop `consent_refused`.**

| # | Wording (shortened; Example Employer) | Result | Why |
|---|---|---|---|
| 1 | read and agree to the Candidate Privacy Notice | ticked | acknowledgement / privacy |
| 2 | consent to collecting, using and **storing** my personal data for processing my application | **STOP** | retention frame + residue -> needs talent pool (M1) |
| 3 | processed by Example Employer and its service providers per the Privacy Policy | ticked | on-behalf sense |
| 4 | shared with Example Employer's **affiliates and subsidiaries** | **STOP** | `affiliat` (third party) |
| 5 | transfer to Example Employer **group companies** outside my country | **STOP** | `group companies` |
| 6 | disclose to **third parties** who provide services to it | **STOP** | `third parties` |
| 7 | processed by Example Employer and its recruitment partners | ticked | on-behalf sense (partners that "process") |
| 8 | collection, use and disclosure ... by Example Employer and its **related corporations** | ticked | not in the list (D-224 would stop) |
| 9 | share my application with the hiring manager and interview panel | ticked | internal |
| 10 | applicant tracking provider processing on its behalf | ticked | on-behalf |
| 11 | processed by vendors engaged by Example Employer | ticked | on-behalf |
| 12 | stored on servers operated by our cloud service provider | ticked | model decides (no key) |
| 13 | shared with Example Employer's **recruitment agencies** | **STOP** | `agencies` |
| 14 | forwarded to relevant hiring teams within Example Employer | ticked | internal |
| 15 | Example Employer sharing my data with **background screening providers** | ticked | classed internal because the employer is the sharer (H2) |
| 16 | shared with **other members of the group** | **STOP** | `members of the group` |
| 17 | processed by Example Employer and its third-party processors | ticked | on-behalf |
| 18 | Terms of Use and Privacy Policy | ticked | |
| 19 | privacy policy, **including sharing with its parent company** | ticked (Yes/No empty) | keyed as relatives declaration (H2) |
| 20 | Data Protection Notice and details shared with the group HR department | ticked | internal |
| 21 | shared with its **partners** who help with recruitment | **STOP** | partner organisation |
| 22 | shared with our service providers and professional advisers | ticked | model decides |
| 23 | sensitive data processed by Example Employer and companies acting on its instructions | ticked | on-behalf |
| 24 | passed to our recruitment process outsourcing provider | ticked | model decides |
| 25 | shared with regulators and government authorities where required by law | ticked | classed internal |
| 26 | used by Example Employer and its **sister companies** | ticked | not in the list (H2) |
| 27 | reviewed by HR team and relevant business units | ticked | internal |
| 28 | disclosed to its **clients** for placing me | **STOP** | `clients` |
| 29 | shared with companies within the Example Employer **network** | ticked | employer name -> internal (H2) |
| 30 | processed by Example Employer and external service providers on its behalf | ticked | on-behalf |

Stops 8 (7 by a recipient word, 1 by M1). Ticked although D-224 would stop: 8, 15, 19, 26, 29 (and 25 by design).

## What held

Closure H1 and p21 / p23; G1 across 14 status-in-consent wordings; D-224 5a for the closed recipient list (a Yes/No answers No, a required box stops, never ticked); D-225 internal and on-behalf wordings follow the privacy consent (ticked, refusal when `privacy_consent` is false); R for keep-on-file labels (contact residue needs both consents); `consent_both_known` and the optional early exit (a known pair of keys writes the truth; disagreeing keys never tick against it); the site-prefilled rule (pre-ticked keyed marketing box cleared; pre-selected adverse declaration cleared or stopped); every consent / declaration exit stamps a class except the blank optional exit (L1); declarations as above; layering test 13/13.

## Plain-words residual list for the owner

1. The filler reads consent wordings from word lists. A marketing or "stay in touch" box phrased in a way the lists do not know can be ticked even though your details say no to the talent pool; a privacy box that also asks to be contacted can be ticked as a whole. Until fixed, expect to see "Assumed" consent boxes in "What was sent" and check them.
2. A required box that mentions sharing with an unusual recipient (sister companies, customers, a parent company) is ticked today; the common ones (affiliates, third parties, clients, agencies) stop the application.
3. A privacy box that says "store my personal data" stops the application for the wrong reason.
4. A consent worded as "I do NOT want ...", or as a drop-down whose options carry the consent, is left to the model.
5. Open owner question, quantified: with the sample profile, 3 of the 8 stops among the 30 realistic required privacy wordings are affiliate / group wordings (4, 5, 16); a ruling that the privacy consent covers affiliates would remove those 3 stops (and leave 5).

## Fix list (all in `always.py`, small)

1. H1: widen / invert the marketing frame for consent-shaped labels (contact verbs and objects above), read options, never run the forced "ordinary" correction on a consent or marketing class code has no key for (:5705), take the model's marketing class as binding.
2. H2: closed internal list, everything else third-party; `theemployer` only after "with / to / by"; more sharing verbs.
3. M1: privacy frame absorbs a store / hold phrase with no future / other word.
4. M2: `_same_key` pairs ACKNOWLEDGEMENT(privacy notice) with CONSENT_PRIVACY.
5. M3 and L1 as written.
6. Then re-run `probes/c1.py` (S2_LIST=all / unkeyed), `b1.py`, `sh1.py`, `q5.py`, `m2.py`, `d1.py`, `s1.py`; the new fixture rows should be bundles, "emails from X", "SMS", drop-downs with the consent in the options, and the 45 recipients.

`-k always`: 642/643 passed (the one red is the known r10 DEFECT pin about a status wording, not this part); `-k layering` 13/13; `-k q127` 96/96; `-k declarations` 202/202 (`probes/k_always.log`).
