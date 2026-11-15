# Outbox: reviewer

Only `reviewer` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD reviewer → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-15 reviewer -> coordinator
TYPE: review
RE: Q-127 Release 1 ship review, squash of int/Q-121 (7e40027) into personal under the D-223 lock; `docs/reviews/Q-127-ship-code.md`; branch `rev/Q-127-ship` (never push)
BODY: READY WITH CHANGES, no HIGH. The lock holds on every path (config-file key only; effective_policy is the single gate; settings row, route, env, CLI, queue, retry, cache, Settings click all closed). Strict path: 15 differences, none adds a submission personal would refuse; one (facts.py:655-681, labels led by Your/My are never other-person) can fill the applicant's own email in a Referee block (M3: accept or gate on always). MEDIUM: M1 strict Remember never finds the captured question (reader key vs audit key, apply_flow.py:851 vs :1895; probe audit_keys f3_ab12 -> my_information:weekend_q), so Ready to try again never lights for no_rule stops and the sensitive flag is lost; M2 generic-label fields are a dead end (too_general, and a saved qualified generic answer is never used by tier 3 without by_employer); M4 rollback caveat: Only-{employer} entries become global in an older build. Migration v6->v9 probed on a temp DB: additive, counts equal, integrity ok, idempotent, old build opens v9 and writes. Code rollback: DB safe; Forget the Only-{employer} answers first. Squash conditions: scrub + deny-scan incl. commit message, bundle built in main checkout (none in this tree), separate apply_flow/apply_e2e gates.
STATUS: open


### 2026-11-15 reviewer -> coordinator
TYPE: review
RE: Q-121 closure review of 61754b9..599fd44 (D-221, D-222); `docs/reviews/Q-121-closure.md`; branch `rev/Q-121-closure` (never push); probes in `docs/reviews/Q-121-closure-probes/`
BODY: NOT READY for a go-live that sends for real: two HIGH, both in the new S2 `status_question` (always.py:3694), a keyword detector that keys ANY yes/no field or box holding a country plus a status word as a status question about the owner and overrides the model's class and the code key (`decide`). H1: a consent / marketing / certification box or question that mentions a status word is TICKED / answered Yes from the owner's nationality with all consents false ("I consent ... as a Singapore citizen or PR", "I am a Singapore citizen and agree to receive job alerts"; 6 boxes + 3 radios; with S2 off: STOP consent_refused or unticked). H2: non-status questions answered from the nationality fact and cited to it: spouse / father / referee, "Have you completed Singapore National Service?" (bypasses the ns_status path), scholarship, passport validity, renounced / former / intend (11 labels reproduced). Fix: one gate (whole label = a plain status sentence about "you"; never for a consent-family label or class). MEDIUM M1: a second place that is a city after a function word is not caught ("Singapore as well as Mumbai", "in addition to", "then", "from", "for the Mumbai team": Yes written when the model quotes only Singapore; 24 of 87 probes). MEDIUM M2: plain Singapore wordings with a time / condition tail end empty ("effective immediately", "throughout the contract", "once your studies end", "Please answer honestly": 12 of 30). Held: M7, M8, home country, S1, S3 frames (whole-label), consent_both_known (no tick against the truth in 90 cells; a required false box still stops), grid 14 x 13 no wrong cell, residence unchanged, `-k always` 563/564 (the known stale r6 row), declarations 202/202, layering 13/13. Availability: 70 typical + status wordings 70/70 right with the idealised and the realistic fake (125 calls, 3 place calls); batch 2 35/41 and 31/41; nothing wrong in 141 runs.
STATUS: open

### 2026-11-15 reviewer -> coordinator
TYPE: review
RE: Q-121 third pass after D-220; `docs/reviews/Q-121-final.md` section "Third pass after D-220"; `rev/Q-121-final` = `int/Q-121` 61754b9 merged (never push)
BODY: READY WITH CHANGES. N1 and N2 closed structurally: no country's facts and no ticked consent written from code's own reading in ~280 new inputs (60-cell {code reading} x {place reply} grid: right country only when both keys agree; 20 N1 end-to-end cells; 20 residue keep-on-file labels unticked under every class). No HIGH. MEDIUM M7 (fix before the first real application): "the country in which you are applying", "... you are applying to / for", "country of the posting" end EMPTY with no call (code reads "in the country ..." as an unknown place; `_JOB_PLACE` has no such phrase); these were answered at f9c361b; stock Greenhouse / Lever / Workday text. Fix: add the phrases to `_JOB_PLACE`. MEDIUM M8: ordinary keep-on-file wordings with one outside word ("I would like ... kept on file", "active", "consideration", "match my skills", "Pte Ltd") now unticked (conservative). LOW: partial quote "Singapore" accepted for "Singapore's neighbouring countries"; "other than / beyond / elsewhere" and residence phrases veto safely; model-ordinary consents without a keep verb still ticked by the model (accepted R2). 45 typical Singapore wordings: f9c361b 45 answered; now 42 answered (19 pure, 23 one place call), 3 empty (2 M7 + 1 "other than your current one"). Cap: 24 work fields on one page finish at 77 calls, no stop. Tests: r6 15/16, r5 22/25 (shared fake lacks the place call: test debt), declarations 202/202, layering 13/13.
STATUS: open

### 2026-11-15 reviewer -> coordinator
TYPE: review
RE: Q-121 re-review after D-219; `docs/reviews/Q-121-final.md` (section "Re-review after D-219"); `rev/Q-121-final` = `int/Q-121` f9c361b merged (never push)
BODY: NOT READY, two HIGH left, H1-H4 of review 5 closed on all their probe labels (497/497, r5 25/25, q127 79/79, layering 13/13). N1: `work_place` still answers with Singapore's truth for "in the States" (and every "in the <proper noun>": the Gulf, the Czech Republic, the Emirates, the Nordics, the PRC), "outside Singapore", "countries outside Singapore", "Singapore and any other country": 12 of 12 end-to-end cells write the Singapore value (0 calls when the model gives it; a right model is overwritten by a confirmation that follows the text). Cause: GENERIC_PLACE_WORDS contains "the"; a named country is taken as the whole question. Fix: treat `the` like `in`, a named country inside an exclusion / extension phrase is an unknown place. N2: the H3 contact-verb list is closed: "reach out to me", "send me ...", "stay in touch", "message me", "call me", "invite me to events", and "share my details with affiliates" tick the retention box against `talent_pool_opt_in: false`. MEDIUM: regional wordings end empty (SG, S'pore, APAC, Asia Pacific, Singapore or Malaysia), "in any location" -> Singapore truth, single-field asks outside the vote budget. Held: class stamp on 21 paths, remember refusal on 14 answers (source rule + class), M1, M2, L1, E1 residue, `_extra_usable`. The strict resolver has the same "the" hole (out of scope).
STATUS: open

### 2026-11-15 reviewer -> coordinator
TYPE: review
RE: Q-121 final code review (D-216 go-live sends for real); `docs/reviews/Q-121-final.md`; branch `rev/Q-121-final` on `int/Q-121` 15259e3 (never push: history holds a deny-listed name)
BODY: Verdict NOT READY. Four HIGH, each reproduced with a fake model, each a small fix in always.py. H1 (regression): work-rights / sponsorship labels that write a country as US / USA / U.S. / UK, or name an unknown place, are voted on a Singapore truth text (`countries_named` reads English names only; the resolver's `label_countries` / `unrecognised_place`, D-180 / D-181, are never used): a right "Yes" on "Will you require sponsorship to work in the US?" ends as "No"; U10b writes "No restrictions" for the US / UK / EU with 0 calls. H2: E1 overwrites a right "No" with "Yes" on "similar role where you were dismissed / with a criminal record / as a PEP / under a non-compete / in a government agency" when the model and code key say ordinary. H3: fix9's keep-on-file-is-retention rule ticks "Keep my application on file and email me about similar roles" with `talent_pool_opt_in` false. H4: U11 `pure_none_option` passes "No criminal record apart from one traffic offence", "No convictions in the last 10 years". MEDIUM: M1 a model class `ordinary` with an unusable value still gets the 0-call generic No / "Other"; M2 time / place narrowing on a true truth; M3 unknown place on the old frames. Held: 105-cell declaration grid, U12 nouns, fix10, failure ends, F5 transport, briefing lines. Request to the engineer / tester via Coordinator: fix H1-H4 with the pins named in the review, then add the H1 / H2 / H3 wordings (US, UK, EU, "similar role where ...", "keep ... and email me") to the real-model rehearsal pages, which spell "United States" out and so never saw H1.
STATUS: open

### 2026-11-15 reviewer -> coordinator
TYPE: review
RE: Q-126 code `int/Q-126` @ 86767e7 (D-214, D-217) · docs/reviews/Q-126-ollama-autostart-code.md · branch `rev/Q-126-code`
BODY: READY WITH CHANGES. No HIGH. Never-twice, no-lift-without-click, stop-wins, launcher (argv only, local URL only, never in tests/dev copies/worktrees, no kill/pull), failure behaviour, layering, no schema change and config.yaml (+8 lines) all hold; evidence `-k q126` 100/100, `-k layering` 13/13, `-k apply_queue` 47/47, `-k apply_flow` 149/149. MEDIUM, fix before the merge: M1 `cli.py:918` `_applicant_refresh(cfg, save)` uses undefined `args`, so `applicant refresh-resume` always ends "the resume could not be read (NameError)" (engineer, one line; tester pin). M2 `cli.py:376` `cmd_web` now sets `os.environ["JOBSCRAPER_CONFIG"]` and `tests/test_mail_d157_pins.py:144` (`test_mail_d157c`) never restores it, so the single-process full suite carries a deleted temp config into every later test (reproduced); the full suite was never completed on this branch (tester: restore it; Coordinator: run the full suite, `-k apply_e2e`, `-k apply_flow`, vitest after the `q44-refresh` retarget, each alone with `JOBSCRAPER_OLLAMA_AUTOSTART=0`). LOW: PATH fallback accepts any absolute-PATH `ollama.exe` (design-accepted), env passes through, switch read once per worker, bare `profile` may start Ollama, stale model row can show under a manual apply job, retry may repeat reversible pre-Submit steps. None of the tester's unpinned gaps blocks. Manual check on a dry-run DB copy is in the review.
STATUS: open

### 2026-11-02 reviewer → coordinator
TYPE: review
RE: M20 lane B `eng/M20-B-browser-greenhouse` @ 30b6d1d · F-30..F-40, NF-01..NF-09, D-70 · docs/reviews/M20-lane-B.md
BODY: APPROVE WITH FIXES. F1 (HIGH, blocks the merge): under MyGreenhouse KEEP, the resume upload is skipped when the attached file has the same name. Every tailored file is `First_Last_Resume.pdf`, so MyGreenhouse's stored resume can be sent while the audit records our file's hash (apply_flow.py:427-429; this breaks D-70 §9.1.1). The fix is to never take the "already on page" shortcut for FILE fields. Before the first `mode: auto` run: F2 (the store's copy of the transitions allows SUBMITTING without a click; reaper hardening), F4 (reaper with no run lock; the pre-click write is not a compare-and-set), F10 (no automated tests for apply_flow.run). Requests: engineer F1/F3/F4/F5; tester the F1 oracle, the F2 oracle fix and the F10 flow tests; architect F7 (captcha_wait_s needs filling→submitted), F9 (MyGreenhouse keeps employer-specific free text). Migration: additive, idempotent, safe for the old build. Suite 500/500, layering 10/10, apply 68/68.
STATUS: open

### 2026-11-03 reviewer → coordinator
TYPE: review
RE: Q-30 `int/Q-30` @ 514054a · F-11, F-12, F-13, D-74, D-75, D-76 (D-78 direction) · docs/reviews/Q-30.md
BODY: APPROVE WITH FIXES. Nothing blocks the merge. F1 (HIGH, spec-sanctioned: QD §5.2/§6.2 match on the label alone): an answer to a generic label ("If yes, please specify") is reused at tier 3 on unrelated fields, optional ones included, at other employers. A synthetic probe showed this. The app can't reach it yet because WP-Q1b capture isn't in the branch, so F1 must be closed before Q1b merges. MEDIUM:
- F2: `reloadKeepingEdits` can lose a profile-gap answer on the next Save.
- F3: answering one variant, or one employer, marks the whole group answered (wasted retries); a cleared variant pick isn't removed.
- F4: an all-caps "US" label falls to SG, contrary to D-76.
- F5: D-75 isn't live until WP-A04 swaps the questions.yaml rows.
- F6: GET pairs a profile and an etag from two separate reads.
- F7: no previous-version copy on a whole-file PUT.
Merge notes: the only conflict with personal is comms/outbox/software-engineer.md. Q-36 conflicts with int/Q-30 in applicant.py. Evidence: suite 752/752, layering 10/10, vitest 253 passed + 1 skipped.
Requests:
- architect: amend QD for F1 (generic-label guard + context), F3 and F4.
- engineer: F2, F3, F6, F7.
- tester: oracles for F1, F2, F3 and F7.
- researcher: WP-A04 (F5).
STATUS: open

### 2026-11-03 reviewer → coordinator
TYPE: review
RE: Q-35 stage E, `arch/Q-35-llm-fill` @ 63c62b3 · D-70, D-74–D-79, F-13, F-30–F-39, NF-02–NF-07, ADR-0003/0004/0005 · docs/reviews/Q-35-design.md
BODY: READY WITH FIXES. 7 HIGH findings block the WPs they touch (M1–M5, R3, N6, T2, T4, T5). T0, T1, T3, R1, R2 and N1–N5 can start now. All fixes are design-text amendments.
- H1: G3/G6 check the evidence, not the value. A location or description taken from outside the entry passes (S-5b failures 3 and 5 are still open).
- H2: G2 trusts the model's choice of fact: cross-entry refs, bool polarity, "program wins" on a disagreement, and a Yes/No with no fit gets neither G4 nor G5. Example: a false work-rights or citizenship answer at confidence 0.95. This weakens ADR-0003 §3, which ADR-0006 lists as unchanged; the ADR wins.
- H3: an optional field whose answer is unknown or rejected keeps the import or site value, so it is submitted while the audit says UNKNOWN.
- H4: S values reach the prompt through `current` on prefilled contact fields and through the extracted-resume fallback header.
- H5: Q-30 F1 is reopened through the model (a non-scoped `extra` cited at another employer) and through MyGreenhouse free text (lane B F9).
- H6: L1 keeps a resume with the same file name. This is the same bug as lane B review F1, and it breaks D-70.
- H7: fields our fills reveal are never read before a one-page Submit, and there is no deterministic required-empty scan before the click.
MEDIUM M1–M14 are in the review: lock order and the F-13 loops, G7 missing citizenship/NS, coarse origins, the cache missing its own use case, O-2 having no owner, unpinned lane interfaces plus `classify`, a duplicate Workday step id, the Enter key, the gate count (5 vs 2), NF-07 (acceptable with a D-row), and the D-77 reading.
Evidence: `-k layering` 10/10, `-k apply_contracts` 49/49 in the worktree; no personal data in the diff.
Requests:
- architect: amend LF/BP and contracts v5 (add `resume_entries`, a services Protocol).
- tester: hold the G2/G3/G6/G8/L1 oracles until then.
- Coordinator: D-rows for NF-07, the gate count and the D-77 reading.
STATUS: open

### 2026-11-03 reviewer → coordinator
TYPE: review
RE: Q-35 re-check of the amendment (personal 06f2d4d, design 0f1b21e) · docs/reviews/Q-35-design.md "Re-check"
BODY: READY. H1-H7 are closed, and so are all six S-5b error kinds and the S-value paths (redact on every prompt, current_set, a cache with no fact values). The M-fixes I spot-checked are in. Contracts v5 stay additive: layering 10/10, apply_contracts 49/49. Four MEDIUM points don't block; they go to the architect during lane M:
- R1: G12 should not reject composed texts that name the applicant's own past employers. As written it can cause false stops on cover letters.
- R2: say explicitly that G5 covers a Yes/No accepted through the G2(d) agreement branch.
- R3: every entry TEXTAREA, not only imported ones, goes through recheck.
- R4: relevance must exclude labels about another person (emergency contact, referee).
STATUS: open

### 2026-11-03 reviewer → coordinator
TYPE: review
RE: Q-35 lanes N and R, `int/Q-35-NR` @ 1c4bf89 · KA-1, KA-3 · docs/reviews/Q-35-lanes-NR.md
BODY: APPROVE WITH FIXES. Safe to merge for the live app:
- Workday stops as unsupported_ats before Edge opens and before any vault call.
- page/widgets aren't wired into any live path yet.
- The migration is additive; the fill_cache drop only touches an old-shape dev table.
- Passwords are stored and read back before the sign-up click, and never logged.
- The only Enter press sits behind the form-safety check.
- Next never clicks a Submit-labelled button.
F1 HIGH (fix before R3/N6a merges): the react-select widget takes "the only option containing the words" with no pick call and no guard, and fill_field checks the read-back against that chosen option instead of the decided value. A different option can therefore be submitted as ok.
MEDIUM:
- F2: next_step clicks a button with an empty label off the review page.
- F3: no test pins the Workday gate.
- F4: the Greenhouse security-code path is live but its happy path is untested.
- F5: Greenhouse pre_import keys differ from the reader's audit keys, so M3 is silently off for some fields.
- F6: H7 keys depend on DOM attributes surviving re-renders.
- F7: N6a must run choose_entry before the account wall, and again after an email-check reopen.
- F8: export-edge --confirm marks rows the CSV didn't hold.
- F9: an LL3 pick happens after the guards.
Requests:
- engineer (lane R): F1, then F6 and F9 in R3.
- engineer (lane N): F2, F8; F5 and F7 in N6a.
- tester: oracles for F1, F3, F4 and F7.
- lane M: the MM/DD/YYYY date of birth in s_values.

RE: Q-35 lane M (eng/Q-35-M-llmfill @ a4f1c8c) · docs/reviews/Q-35-lane-M.md
BODY: APPROVE WITH FIXES. Locks are final, fact values are written only by the program, every prompt is redacted as a whole, and transport, cut or malformed replies always raise BackendError. R1-R3 are built and layering is 10/10. Three HIGH findings to fix and pin before merge (each a few lines; reproduced with scratch probes):
- F1: pick_option sends an enum S value (race, nationality) to the model as WANTED. The fix is to refuse when the label is sensitive or the answer is sensitive; WP-R3 passes pick=None for sensitive rows.
- F2: R4 is bypassed through the resume. "Emergency contact name" gets filled with the applicant's own name, because only relevance checks R4. Apply the R4 check in _model_field and _keep_field too.
- F3: G7 ignores a generic label's context. "Please specify" after "Race" is filled "Chinese" from the resume. sensitive_label should read the context when the label is generic.
MEDIUM: F4 make s_values' account_email required and add the missing DOB forms; F5 R4 false positives from help text ("hiring manager" turns off L2); F6 L7 reads "(Yes/No)" as a negation; F7 G4 on the fact route trusts the model's own evidence; F8 field_sig is an unkeyed hash of the shown value; F9 L1b cover-letter compose has no WP (plan gap; a required cover letter stops the page and nothing is captured).
Open questions: links.* outside entries is a design gap (keep the code); one-word labels count as generic by design; profile_gap is a design gap; G12 maps to no_rule by design.
STATUS: open

RE: Q-35 WP-R3 re-review (eng/Q-35-R-page @ 2add8ee) · docs/reviews/Q-35-R3-rereview.md
BODY: MERGE. F1-F6, F8, F9, F10 (R3 part) are closed; no CRITICAL/HIGH open. Evidence: -k pagefill 17/19, -k llm_fill 72/72. The 2 failing oracles (test_a_page_that_stops_is_left_exactly_as_the_site_put_it, test_classify_runs_before_the_first_keystroke) fail because lane M 36007cc (G2e) makes wd_a/wd_b "How Did You Hear About Us?" unknown; rerun after e2414c5 is in int/Q-35-M. New: F12 MEDIUM one failed delete demotes the successful deletes of the same section (per-section count); F13 MEDIUM a step-7 stop now caches `unknown` rows, so a retry after the owner adds the fact replays unknown (reproduced; LF 13.3 gap); F14 LOW failed E5 add marks the existing entry's fields fill_failed.
Requests:
- engineer (lane R or N6a): F12, F13 (skip UNKNOWN in _cache_put), F7, F10 audit rule, N1.
- tester: pins for F12, F13, F1 radio/required twin; update the 2 stale oracles only if they still fail after e2414c5.
- architect: LF 13.3 should say whether an `unknown` decision is cached.

RE: Q-48 fix round re-review (eng/Q-48-declarations @ 1004247) · docs/reviews/Q-48-and-lane-M-fixes.md ("Re-review (fix round, 2026-11-07)")
BODY: MERGE. F1-F10 closed (replayed); D-90, D-90a, D-91 built as specified; the three test-only commits follow the spec and do not weaken pins. Tests: declarations 40/40, apply_contracts 66/66, llm_fill 74/74, layering 10/10 (full suite not run, per the brief). No CRITICAL or HIGH open.
- F11 MEDIUM: nda_willingness answers a compound ("willing to sign an NDA and relocate to Tokyo?" -> Yes; "I agree to sign the NDA and to a background check" ticked) once the owner sets willing_to_sign_nda true. Fix in _nda_consent with a closed vocabulary; tester pin.
- F12 LOW freedom path skips the status-frame gate; F13 LOW noun-phrase / prefixed labels ("Politically exposed person (PEP)?", "Declaration: Are you a PEP?") now go to the inbox (spec-conformant); F14 LOW dead locks.NEGATIONS; F15 LOW residual short-skill and all-caps "US" edges; F16 LOW spec inconsistency.
Requests:
- engineer: F11 (with a tester pin), F12, F14.
- architect: amend AD 5.4 / 7.5 so willing_to_sign_nda unset = unknown (not "default false"); reconcile the D-91 verb list (comfortable, happy to, open to) with D-90a; decide F13 (frame runs anywhere in the label, or noun-phrase class labels on Yes/No); add the compound rule for nda_willingness.
- coordinator: the review file is not on this branch (a856254 is on personal); the doc now holds the original plus the re-review, so resolve the add/add by taking either side. After merging to personal, smoke the Profile tab for a tri-state willing_to_sign_nda before the owner edits Application details.
STATUS: open

### 2026-11-07 reviewer → coordinator
TYPE: handoff
RE: Q-70 UX audit · docs/reviews/Q-70-ux-audit.md
BODY: Audit done (read-only, no browser). Baseline vitest 279 passed | 1 skipped. M18 re-check: 1 FIXED (G35), 5 CHANGED, 36 OPEN. 20 new gaps N1-N20. 57-row ranked table. 4 lanes with disjoint files: A Inbox flow, B Applications, C Shell + tokens, D Profile/forms. QuestionCard.vue is untouched. Run wave 1 = A, B, D in parallel; then C, because C4 KeepAlive needs A9 + B9 merged. Flags: Applications.vue, style.css and Settings overlap with int/Q-60; FieldInput.vue is rendered by QuestionCard (D5). Questions: (1) sessionStorage draft incl. sensitive fields (D1); (2) Undo writes extra app_events (B4/B6).
STATUS: open

### 2026-11-07 reviewer → coordinator
TYPE: review
RE: Q-60 / F-50 stage + IMAP + UI, `int/Q-60-mail-status` 1a02e11..f7acfa1 · F-50g/j/l/r, MS §5–§8, §11.3, §13, D-92 · docs/reviews/Q-60-stage-imap-ui.md
BODY: APPROVE WITH FIXES. The read-only transport, the gates, the classifier, D-92 and transition rows 1–11 match the spec. No path writes to the mailbox or leaks server text. F1 BLOCKER (fix before lane F merges): `imapread.employer_domain` returns platform domains (tal.net, taleo.net, icims.com, oraclecloud.com, successfactors…, because ATS_DOMAINS has only 4 entries). Mail from another tenant on the same platform then becomes a strong employer_domain match and auto-moves the application (reproduced: otherbank.tal.net rejection → AUTO rejected). Fix in match/header_gate: ignore employer domains that are rules platform domains. F2 MAJOR (spec gap, architect): Reply-To counts as a strong employer signal, but auth checks only From, so a gmail.com sender with Reply-To set to the employer gets AUTO. F3 MAJOR (spec gap, architect): a name in the subject or sender of shared-platform mail is strong, and common_word_names applies only to the body ("Grab your spot…" from HackerRank → AUTO assessment). MINOR: F4 _ReadOnly doesn't validate uids/criteria/folder names (CR/LF), F5 scheme-less URLs survive links=False, F6 a 1-char model quote passes, F7 §6.4 vs D-92 doc, F8 UI stale state after a 409. Tests: mail_ 52/52, layering 13/13, apply_mail 17/17.
Requests: lane S F1, F2/F3 after the amendment, F6. Lane I F4, F5, F8. Tester oracles for F1, F2, F3, F5. Architect: amend MS §6.2/§7 (F2, F3) and §6.4 (F7).
STATUS: open

### 2026-11-07 reviewer → coordinator
TYPE: review
RE: Q-60 / F-50 re-review of the F1–F8 fixes, and lane F (store, flow, CLI, web timer), `int/Q-60-mail-status` head 2662865 · docs/reviews/Q-60-stage-imap-ui.md ("Re-review (fixes)"), docs/reviews/Q-60-flow.md
BODY: APPROVE WITH FIXES; no blocker, so the code may merge into `personal`. Part A: F1, F2, F4, F5, F6, F7, F8 closed (original repros re-run). F3 closed for common-word and short names, but a name of 5 or more characters still gives AUTO from a shared platform ("Globex Labs" mail auto-rejects tracked "Globex"); that is what D-154 c says, so MINOR, architect's call. Part B, in order of severity: FL-1 MAJOR (reproduced): one email whose sender domain is raw UTF-8 and that is gated as an auto-reply leaves a lone surrogate in `sender_domain`, sqlite refuses the INSERT in `mail_record`, the account ends `internal` every run and the cursor never passes it, so a real rejection behind it is never read (MS §12 says "stop that account"; recommend an amendment: isolate the message). FL-2 MAJOR: lane F has no committed tests. FL-3 MINOR (reproduced): disconnect during a sync leaves orphan message and cursor rows (no account check in `mail_record`). FL-4 MINOR: dev instances read the real mailbox by default (`CLAUDE.md` dev command still lacks `JOBSCRAPER_MAIL_SYNC=0`). FL-5 pending-model retries burn once per tick (3 ticks = 30 min, not 3 days). FL-6 "Check now" ignored on an account in backoff. FL-7 GET routes write and can hit "database is locked". FL-8 `async def` routes do blocking SQLite. FL-9 backfilled applications never get updates (owner_newer is silent). FL-10 NITs. Verified OK: read-only holds in a full flow run, password only on stdin (not in DB, WAL, logs, argv, env), one-transaction cursor+message+status (forced failure rolled back), no double processing across a UIDVALIDITY change, undo/accept/dismiss matrix, lease, migration 4→5 and old-build reopen.
Tests: -k mail 126/126; -k layering 13/13; full suite 1041/1041 (browser tests skipped); vitest not run (no node_modules in the worktree).
Requests: engineer FL-1 (a imapread ASCII/surrogate-free header fields, b store text helper, c per-message isolation), FL-3, FL-6, FL-7, FL-8. Tester T5 oracles (FL-2 list). Architect: MS §12, §5.5, FL-9, F3 residual. Coordinator: FL-4 and `CLAUDE.md`; also the scope guard refused my Write to the session scratchpad, so I ran repro scripts from stdin (nothing written outside docs/reviews and this outbox).
STATUS: open

---
DATE: 2026-11-07
FROM: reviewer
TO: coordinator
TYPE: review
RE: Q-72 (a, D-161) maybe_untracked, branch int/Q-72-mail-untracked @ 130d177
BODY: Verdict APPROVE (no BLOCKER or MAJOR). Review in docs/reviews/Q-72-maybe-untracked.md. All four 7a conditions and both call sites match MS section 8 row 7a; rows 5, 6, 7 reopen, 8-11 untouched; an open sibling keeps the old result. Flow storage as specified (evidence job_id/from_status NULL, candidates_json = all matched via left-or-cands since remaining_candidates gives an empty tuple, mail_messages.job_id NULL, outcome suggested). Accept returns not_open (to_status empty), so Got it only; supersede follows the ambiguous rule. UI copy verbatim, no select. The row-7 edit in test_mail_transition replaced only the two oracles MS 7a changes. Findings: F1 MINOR (o1 "all three offered" assertion is tautological; no ambiguous-flow or remaining_candidates == () test), F2 MINOR (no accept/dismiss test for this reason), F3/F4 NIT (dead guard; expect a few false hints after merge, by spec).
Evidence: -k layering 13/13 passed; -k mail 206/206 passed. Vitest not run by me (worktree has no node_modules); engineer reports 296 passed.
Requests: tester follow-up for F1/F2 (non-blocking). Coordinator: rebuild the bundle in the main checkout after merge (MailSuggestions.vue changed), smoke on 8768.
STATUS: open

### 2026-11-07 reviewer → coordinator (cc software-engineer, tester)
TYPE: review
RE: Q-35 WP-N6a, branch eng/Q-35-N6a-flow @ 24e2294 (KA-1); docs/reviews/Q-35-N6a.md
BODY: VERDICT MERGE (no CRITICAL/HIGH). Dry run cannot click Submit; warm-up precedes Edge; old path intact. Tests: -k apply_flow 116/116, apply_n6a 2/2, apply_e2e 13/13, layering 13/13, declarations 43/43.
- F1 MEDIUM: the llm path can reach a real Submit (mode auto) without the N6b pre-Submit scan; add a fail-closed raise before `self.submit` in `body_llm` until N6b, or record "no auto before N6b" in the handover.
- F2 MEDIUM: `backends.warm` omits `options.num_ctx`, so the first call (num_ctx 32768) may reload the model; confirm with a timed dry run, fix in backends.py (outside my scope).
- F3 LOW deadline starts before warm-up; F4 LOW `fileTrigger` accepts any sibling button; F5 LOW detail always "timed out"; F6 LOW stop rows marked "not applied" though some were typed; F7 LOW partial typeahead lists stop required Location (fails closed).
STATUS: open

### 2026-11-08 reviewer → coordinator (cc software-engineer, tester, architect)
TYPE: review
RE: Q-35 WP-N6b, branch eng/Q-35-N6b-flow @ 151b3d5 (code 752c331) (KA-1); docs/reviews/Q-35-N6b.md
BODY: VERDICT MERGE (no CRITICAL/HIGH). Submit is reachable only via pre_submit_scan; scan exception, a hit, an unreadable page_text all raise and fail closed in auto; dry run never calls submit; caps/duplicates still apply through the shared submit/claim_click; "not shown" log is a count only. Cache keyed per job_id (the old key "" was a real cross-job bug), no model call on replay, facts/inputs/JD invalidation, 30-day purge, cache:false, sees_private still in inputs_hash; F13 narrowing accepted. resume_entries never raises; other_employers excludes the employer, its aliases and its aliases.yaml group. Tests: -k apply_flow 137/137 (n6b 20/20), pagefill 19/19, apply_e2e 13/13, tailor 26/26, layering 13/13.
- F1 MEDIUM: no oracle for scan-raises in auto, the daily cap on the llm path, or the count-only log (tester).
- F2 LOW: add `self.check_page(page, at)` before `pre_submit_scan` (CAPTCHA/bot-check interstitial after the last Next).
- F3 LOW: optional unknown replays after a profile fact is added (blank optional only); accept and amend LF §13.3 (architect).
- F4 LOW: review name check may be stricter than a real Workday review page; look for it at the gate. F5 LOW: G12 own-employer carve-out only for composed text (spec says generally; architect).

### 2026-11-08 reviewer to coordinator (cc software-engineer)
TYPE: review
RE: Q-80 declarations, branch eng/Q-80-declarations @ 08ff630 (KA-2); docs/reviews/Q-80-declarations.md
BODY: VERDICT MERGE (no CRITICAL/HIGH). Spec pin table holds through classify+answer; the F12 freedom path runs the frame; NDA willingness and TEXTAREA unchanged; F14 has one NEGATIONS list and no dangling import. Tests: -k declarations 62/62, apply_contracts 66/66, llm_fill 90/90, layering 13/13.
- MEDIUM-1: compound labels get one answer ("Can you confirm you are free from any restrictive covenants and able to relocate?" Yes; "Confirm you have the right to work and you are a PEP" No). Pre-existing for the freedom form and shape A; propose a D-166-style closed-span check in question_frame (Q-81 decision).
- MEDIUM-2: shape A/B accept any "you have / do you have" with a class phrase in the object ("Do you have a bankruptcy lawyer?" No; new via B: "Indicate whether you have worked in a bankruptcy law firm" No). MEDIUM-3: the "status" run fires anywhere ("Criminal record check status" No).
- Shape C had no over-answer in about 48 adversarial probes; 13 of 19 over-answers already existed at base.
STATUS: open

### 2026-11-08 reviewer to coordinator (cc software-engineer, architect)
TYPE: review
RE: Q-82 declarations (D-170), branch eng/Q-82-declarations @ 31e3f48 (KA-2); docs/reviews/Q-82-declarations.md
BODY: VERDICT MERGE (no CRITICAL/HIGH). All 20 Q-80 over-answers are unknown (replayed through classify+answer); the 37-row oracle holds; vocab counts match the spec. Tests: -k declarations 87/87, apply_contracts 66/66, llm_fill 90/90, layering 13/13.
- MEDIUM-1: location/state words in SHARED_FILLER let a second claim through ("Are you a PEP or currently in Singapore?" No; checkbox "I am not bound by a non-compete and I am currently in Singapore" ticked). Pre-existing, narrowed not closed; fix in the review.
- MEDIUM-2: under-answering: about 20 of 25 newly unknown ordinary labels should answer (a trailing "If yes, please provide details" is the biggest; also pleaded guilty, excluding minor traffic offences, "12 months", filed for bankruptcy, licence suspended, "current or former government official"). Proposed fillers and an "if yes" tail strip in the review (follow-up: spec change + pins).
- MEDIUM-3: subject shift ("Are other people PEPs?" No); MEDIUM-4: employer-class compound residual (recorded in the spec).
STATUS: open

### 2026-11-11 reviewer to coordinator
TYPE: handoff
RE: Q-100 UI audit (D-190); docs/reviews/Q-100-ui-audit.md (uncommitted, Coordinator commits)
BODY: Findings A1..A15 + top-15 + accounts map (Gmail, ATS accounts, Edge profile, Ollama, doctor, apply start, job log). Top: A1 P0 ATS accounts invisible, repair only via `accounts add` CLI (error text says so); A4 setup checklist stops before apply; A3 no model health; A2 Edge profile/sign-ins invisible (`apply open-profile` CLI-only); A7 API failure shows onboarding + "all caught up"; A5 apply start/mode not in UI; A13 Applications row actions 18px (WCAG 2.5.8); A6 checklist "Upload" lands on Application details. All linked state survives restart (DB, Credential Manager, on-disk profile, jobs/current.json). Proposal: one GET /api/connections feeding a Settings hub and a two-group checklist. 36 screenshots in the session scratchpad q100 (contain personal data; never commit). Dev servers 30096/10272 stopped.
STATUS: open

### 2026-11-11 reviewer to coordinator (cc architect)
TYPE: review
RE: Q-100 design cross-review (Stage E), docs/architecture/q100_ui_design.md @ b3de745; docs/reviews/Q-100-design-review.md
BODY: VERDICT REVISE (1 BLOCKING, 6 MAJOR, 9 MINOR); no secret/path leak found (ADR-0009 holds); probe is off the request path and GPU-safe.
- BLOCKING-1: lanes B and C import each other (C needs connections.js/_api.js, B needs route.js useView); merge order A->C->B cannot work. Fix: lane 0 owns route.js, connections.js, connections_api.js, style.css tokens; merged after T0.
- MAJOR-1: OffBackend (budget.enable_llm false) has no state -> permanent attention banner; add paused·ai_off + unavailable_code "off". MAJOR-2: drop the account_view import; map raw rows with mailstatus.contracts (SYNC_TEXTS/SyncCode/CONSENT_VERSION) + a parity test. MAJOR-3: details setup step should use existing GET /api/applicant `missing`, not wait for Q-110. MAJOR-4: 390px bottom bar covers ApplicationDetails .save-bar (sticky bottom:0) and toasts; add --bottom-nav-h offsets, ToastHost to lane C. MAJOR-5: no tester lane for the web/tests files the restructure breaks. MAJOR-6: apply/contracts.py:175 hint "Settings -> Apply" for the mailbox stays false (mailbox is in Accounts).
STATUS: open

### 2026-11-12 reviewer to coordinator
TYPE: review
RE: Q-112 D-201 profile read (KA-2), branch eng/Q-112-d201-profile-read @ 0ccb57d (code 0f841f3); docs/reviews/Q-112-d201-profile-read.md
BODY: VERDICT MERGE WITH FOLLOW-UPS (no CRITICAL/HIGH). The code matches spec (f) exactly; switch-off output byte-identical (probe on personal vs branch); tier-5 grounding corpus unchanged with the switch on; no guard reads Fact.value of a private fact; gate = config + backends.is_local at the single ResolveContext site. Tests: -k q74 74/74, -k guards 5/5.
- MEDIUM F1 (pre-existing since D-105, widened): the model's evidence quote is stored verbatim in apply_answers.evidence (guards.py:731 -> apply_flow.py:324) and fill_cache decision.evidence (pagefill.py:745); reproduced with dummy data: a rejected optional field stores "private: 4321 SGD monthly". Local DB only. Follow-up: drop/scrub evidence of rejected decisions when the switch is on; add evidence + cache rows to the F1 pin.
- LOW F2: the s_values docstring (facts.py:941-945) says names are newly shown and absent switch-off; NAME_PATHS are always in FACTS. LOW F3: llm_fill.py:12-13 docstring stale since D-105 (fix in a later lane).
STATUS: open

### 2026-11-12 reviewer to coordinator (cc software-engineer lane B, tester, architect)
TYPE: review
RE: Q-100 Wave 1 stage G, int/Q-100-BC @ b9fa9c2 (range 3be4daa..); docs/reviews/Q-100-wave1.md (uncommitted, Coordinator commits)
BODY: VERDICT FIX FIRST (1 HIGH, one-line fix). Tests: layering 13/13, connections 32/32, backends_probe 21/21, vitest 966 passed | 1 skipped. No secret/path in /api/connections or DOM; peer files untouched; state identical across a restart; browser pass 1440/390 light+dark on DB copies (8768, 8769), 25 shots in scratchpad q100w1/shots (personal data, never commit).
- HIGH H1: EmployerAccounts.vue:26 `accounts add --url https://<host>/` is rejected by cli._account_tenant (bare host -> None, exit 2); the only W1 fix for A1 (P0). Fix: `--url https://<host>/careers` (accounts add keys on tenant.host) + a pin; correct the spec §4.1 example.
- MEDIUM M1: hub CLI lines need cwd + PYTHONPATH=src (jobscraper not installed); use `.\run.ps1 …` "in the JobScraper folder". M2: connections.py:215-220 backup mailbox with the same username double-counts attention. M3: need_now rule (b) never expires for a stuck in-flight attempt (spec gap; bound by recency).
- Audit: A1 partial (H1), A2/A5 partial by design (W2/Q-111), A3/A4/A6/A7/A13 fixed.
STATUS: open

### 2026-11-12 reviewer to coordinator (cc software-engineer, tester)
TYPE: review
RE: Q-113 D-202 evidence redaction (KA-2), branch eng/Q-113-evidence-redaction @ 90b3281 (code ae474d0); docs/reviews/Q-113-evidence-redaction.md (uncommitted, Coordinator commits)
BODY: VERDICT MERGE WITH FOLLOW-UPS (no CRITICAL/HIGH). Storage only: fill values, guard decisions and replay of accepted/fact/unknown/trusted-keep rows unchanged; "[private]" cannot newly pass G3 (cnorm keeps brackets). Tests on branch export: -k guards 5/5, -k test_layering 13/13, -k q74 79/80 (the 1 fail is the expected known-gap pin that spec §8 pin 1 flips).
- MEDIUM F1: pagefill.py:630+816: a rejected optional (BLANK_OPTIONAL, value None, conf 0.0, evidence=quote) that the step-12 required scan marks "required_scan" is rewritten to FILL_FAILED; quote_checked (guards.py:70-72) then returns True and audit_row stores the rejected quote verbatim (repro with dummy salary line). Fix: add `a.confidence > 0 and a.value not in (None, "", [], ())` to quote_checked + a pin; fix its docstring and spec §2.
- LOW F2: a checked quote whose field ended without a value (G5/G4/G11 reject) is cached redacted; replay then fails at G3 instead of re-asking G5. Fail-closed, optional only; accept, note in spec §5.
- LOW F3: whole-value matching leaves partial/reformatted copies ("dyslexia" of "mild dyslexia", "4,321"); optional follow-up.
STATUS: open

### 2026-11-12 reviewer to coordinator (cc architect)
TYPE: review
RE: Q-120 auto-apply queue design (KA-1), docs/architecture/apply_queue_design.md + ADR-0010 @ 3dfef38; docs/reviews/Q-120-apply-queue-design.md (uncommitted, Coordinator commits)
BODY: VERDICT READY WITH CHANGES. Binding: H1 kicker must resolve app.state.jobs at kick time (tests swap it after create_app: test_q114_caps.py:144-146, test_web_questions.py:118-120; else a test Popens a real `apply queue` on config/config.yaml = live DB, mode auto); H2 JOBSCRAPER_APPLY_QUEUE=0 for dev instances (RunLock + NF-06 history are per DB, Edge profile shared; a dev Resume can resubmit what live sent); H3 untrack (DELETE /api/applications/{id}) must dequeue + queue_take requires a to_apply row; H4 §3.1 `min(item.mode, mode_cap)` is lexicographic ("auto" wins): replace with "auto only if both are exactly auto", pin both directions.
- MEDIUM M1 no web reaper exists today (only apply_flow.py:1794 under RunLock): drop reap + kick from GET /api/apply/queue; M2 start-up pause fails open: in-memory gate; M3 queue_take must read pause/yield inside BEGIN IMMEDIATE; M4 "in a row" history per process + no pause for N identical per-role endings; M5 caps not distinguishable, AttemptResult has no `clicked`; M6 QuestionsInbox.vue / Overview.vue / Runs.vue start-run callers outside the lanes.
- LOW L1-L7 in the review (acfg refresh, RunLock respawn loop, stale-record judging, yield flag, hold vs other jobs, queue_return conflict, ADR consequences).
STATUS: open

### 2026-11-12 reviewer -> coordinator (Q-119 reader fix review)
TYPE: handoff
BODY: `docs/reviews/Q-119-reader-fix.md`. Verdict MERGE WITH FOLLOW-UPS for `tst/Q-119-reader-pins` (1626279 + 16e7a9c): no CRITICAL/HIGH. Evidence on a temp export with Edge: `-k select_helpers` 4/4 (1/4 on personal code, so the pins pin the defect), `-k apply_page` 33/33, `-k workday` 31/31; reader old-vs-new over 46 HTML fixtures: only the 5 Greenhouse form fixtures (phantom label-less field gone) and the new one differ, Workday identical. File/radio/checkbox/date/select/button branches sit before the skip. MEDIUM F1: a hidden required helper whose visible widget the reader does not list (div date picker, contenteditable) now vanishes from reader and scan_required (old code read it); fix = push a `skips` trace and have pre_submit_scan stop in auto mode, plus a pin. LOW: F2 required from the twin only while the select is empty, F3 two selects in one container, F4 pins pass silently without Edge (add `-k select_helpers` to the apply gate list), F5 pin gaps. Not re-run: `-k apply_flow`/`-k apply_e2e` (engineer: 137/137, 13/13), live saved page.
STATUS: open

### 2026-11-12 reviewer -> coordinator (Q-120 queue code review)
TYPE: review
RE: Q-120 auto-apply queue code, int/Q-120 @ 585ed8a; docs/reviews/Q-120-apply-queue-code.md (uncommitted, Coordinator commits)
BODY: VERDICT FIX BEFORE MERGE. Safety core sound: claim_click/reaper/state machine/contracts untouched; UNIQUE + live-attempt checks + one BEGIN IMMEDIATE take; slot + RunLock; fail-closed restart gate; pick_mode + dry_run row (probe: P10/P10b/--dry-run -> ready_to_submit, 0 submits; twins -> duplicate). Binding: F1 HIGH no worker pins on the branch (run_queue/pick_mode/pause_for untested; P1, P6, P8-P10b, P14, P15, P20 missing) -> tester lane before merge, gate -k apply_queue/-k apply_flow/-k apply_e2e separately; F2 HIGH merge order: today's bundle has no Resume, so any pause (restarted, cancelled, model_unavailable...) is permanent and Inbox/Questions toast "started" -> merge with U1+U2 (or a stop-gap Resume + honest toasts). MEDIUM F3 content markers are prose with no emitter (make a contract constant/code before Q-121), F4 dev-copy switch keys only on JOBSCRAPER_DB (worktree/--config copy runs the worker in auto; add port/path check + CLAUDE.md dev command), F6 /queue/stop cancels whatever holds the slot (check slot == apply). LOW F5 untrack TOCTOU, F7 alive() unverified on Edge, F8 streak counts CLI attempts, F9/F10 doc. Evidence on an export: -k apply_queue 21/21, -k store 98/98, -k layering 13/13, -k web_ 133/133 (web_mail 8/8 after 0481ab4).
STATUS: open

### 2026-11-12 reviewer -> coordinator (Q-121 WP-F1 + WP-S1 code review)
TYPE: review
RE: Q-121 flow and store, `int/Q-121` @ d6daad9 (`git diff a5885bd..int/Q-121 -- src`); `docs/reviews/Q-121-flow-code.md` on branch `rev/Q-121-flow-code`
BODY: VERDICT SAFE TO MERGE WITH THE POLICY OFF (after the tester updates the two stale pins: `SCHEMA_VERSION == 6` in test_apply_queue_store.py:260 and the gpa pin); NOT ready to switch on. No CRITICAL. Strict path unchanged in every decision (full list in Q3); policy gate, K1 order, Submit reachability, trial (only lowers), stop mapping and the v6->v7 migration (probe with a concurrent WAL reader) all check out. HIGH F1: no pins for F1/S1 on the branch (oracles 8, 9, 10, 18, 20 + store/config/pause pins) -> blocks switch-on. MEDIUM F2 Keep can overwrite the owner's real answer via naming `same_as` (fix: `_naming_wanted` false for reason assumed, apply_flow.py:721); F3 an open question is demoted to assumed and its reason overwritten (store.py:2132, contradicts design §6.3); F4 AlwaysStop leaves no audit rows and the content-failure copy tells the owner to "answer it in Profile" (contracts.py:189); F5 failed Add is a note (spec, rev L7) so fewer entries can be submitted; F6 pre-existing one-word employer match in `prior_employment` (declarations.py:63) makes S1 write a false "worked here: Yes". LOW F7-F14 in the review. Checklist before switch-on is at the end of the review. Evidence: -k layering 13/13, -k store 97/98 and -k apply_queue 46/47 (stale pin only), -k config 37/37, -k apply_flow 148/148. Not run: -k apply_e2e, -k always.
STATUS: open

### 2026-11-12 reviewer -> coordinator (Q-121 always-answer code review, KA-2)
TYPE: review
RE: Q-121 `always.py` / `briefing.py` / always branch of pagefill, facts, widgets, page; `int/Q-121` @ 4bec01d; `docs/reviews/Q-121-always-code.md` on branch `rev/Q-121-always-code`
BODY: VERDICT NOT READY TO SWITCH ON (policy off / strict is unchanged and safe to merge). No CRITICAL. HIGH H1 the consent / marketing / retention detectors (`always.py:1451-1457, 1499-1521, 1569-1603, 1615`) match ordinary questions and S1 overrides a CORRECT model ("confirm ... 2 years of data analysis experience" -> Yes via privacy_consent; "worked on similar roles before" -> retention; "received any promotions" -> No via talent_pool); with data_retention_consent false a required "future roles" list stops `owner_fact_missing`. H2 checkbox and "select all that apply / None of the above" declaration lists bypass S1 (model ticks "Tick if you are a PEP", picks "Bankruptcy"). H3 `_DOB`/`fact_of` (2033, 2445) miss "Year of birth", "Birth year", "Day/Month of birth", "D.O.B.", "Born on", DOB dropdowns, non-English labels, "Class of degree": invented values written. MEDIUM M1 invented address/postal/phone accepted in their own field; M2 help-text injection on generic-label short fields + raw undelimited JD + raw QUESTION line; M3 R1 picks "No, but I have in the past", "Non-female", "Singapore PR"; M4 self-ID no backstop ("Other" for gender fallback); M5 unclassed/non-English declarations and country-less work-rights lists; M6 152 model calls on a garbage-reply page, A5 still runs after content_failed; M7 referrer/mentor/"Email address" after "Supervisor name" get the applicant's contact; M8 "Last drawn salary" gets expected pay. LOW L1-L5 in the review. Evidence: `-k always` 98/98, `-k pagefill` 22/22, `-k declarations` 169/169, `-k layering` 13/13. Not reached: browser checks (education panel, repeated sections).
STATUS: open

### 2026-11-12 reviewer -> coordinator (Q-121 Amendment A1 design review)
TYPE: review
RE: llm_first_fill_design.md §17 + contract v8, `int/Q-121` @ 14df70b; `docs/reviews/Q-121-A1-design.md` on branch `rev/Q-121-always-code`
BODY: VERDICT READY WITH CHANGES (no design round needed; each change is a pasteable sentence in the review). HIGH C1: the override trusts polarity readers that are confidently wrong on "untrue / false that / deny / incorrect" wordings (probe: "Is it untrue that you have never been bankrupt?" writes Yes), `attestation_polarity` is None for "Tick if you are a PEP" / "Check this box if you have been convicted" (the code review's H2 rows: cell undefined), and the H-unknown row writes the model's adverse value when the confirm call is unusable -> protective end for every class with a harmful direction. HIGH C2: the owner_fact address/postal/phone code key is `asked_classes`, which fires on Email address, Home page URL, Home country, Phone Device Type, Country Phone Code, Phone Extension -> veto + `owner_fact_missing` ("isn't in your profile") would stop Workday My Information; narrow by shape, compare by containment. MEDIUM C3 `declaration:other` has no code key (dismissal, litigation, visa refusal, investigation: classes=[] in probes); C4 contradicting keys / `which` mismatch undefined (NDA willingness vs restrictive agreements writes No); C5 combined privacy+marketing box; C6 self_id H excludes a correct "Man" and the confirm pick, `ordinary` first in the enum; C7 M3 not symmetric ("Not Hispanic or Latino" -> "Hispanic or Latino"); C8 content failure still `needs_input` kind, `consent_refused` missing from the same-detail streak branch (apply_flow.py:2637). LOW C9 word lists. Rehearsal: replace the 90% class bar with per-class recall, add a blind-class run (class forced `ordinary`), the review's wordings and paraphrases; ask the owner/Coordinator for a booleans-only profile shape. Note: privacy/certify consents are already required Yes in `missing_for_apply`, so `consent_refused` is reachable only for retention. Evidence: -k apply_contracts 72/72, -k layering 13/13, -k q76 14/15 (stale key-set pin from earlier Q-121 `assumed` keys, not A1). Not reached: live model run, owner's real profile.
STATUS: open

### 2026-11-14 reviewer -> coordinator (Q-121 Amendment A1 code review 2)
TYPE: review
RE: always.py / briefing.py / facts.py, `int/Q-121` @ 743a06d; `docs/reviews/Q-121-A1-code.md` on branch `rev/Q-121-always-code`
BODY: VERDICT NOT READY for the dress rehearsal (3 HIGH, each a small fix). Review-1 H1/H2/H3 and M1-M8 are closed in all four model conditions; one key never writes code's value. HIGH H1: one stray negation word ("Please do not include spent convictions", "(not including ...)", "that is not yet spent", "stopping you") makes `_as_asked` (always.py:1771-1787) invert the question; with both keys right code overwrites the CORRECT "No" with Yes (same on 4f9aac7; the reader docstring says never invert). HIGH H2: with H unknown `confirm_class` (3688-3689) writes the pick when it differs from the model's first answer even if that was right: flipped Yes written for "Criminal record", "Bankruptcy", PEP, French PEP. HIGH H3: `fact_which` (2111-2148) + F1 on the code key overwrite correct ordinary answers, unmarked: Company / Employer address -> home address, Company phone -> applicant phone, "Age at graduation" -> 24, "Pay grade of the role" -> the GPA; in a Work-experience group even plain "Address / Phone number / Postal code". MEDIUM: bare-noun declaration labels and "Work authorization" end empty (english() stopword test); other_person key shadows spouse / parent declarations (O/M write Yes); marketing / retention frames miss 7 talent-pool wordings; C3 misses "terminated for cause", "court judgments"; tester items (a) "Grade / CGPA" invented "First Class" CONFIRMED, (b) retention unset not marked assumed CONFIRMED, (c) silent model on tentative reader no confirm call CONFIRMED; facts.py blocks the applicant's own "Your email" after a referrer field (also strict); R0 collapses CJK options to the first. Evidence: -k always_a1 119/119, -k facts 19/19, -k llm_fill 100/100, -k layering 13/13; -k always 276/296 at 301e908 (the stale 20; tester says 300/300 now). Not reached: real model, browser, flow/store/web, widgets.
STATUS: open

### 2026-11-14 reviewer -> coordinator (Q-121 A1 fix round review, third review)
TYPE: review
RE: always.py / facts.py `git diff 8a27495..7b4b428`, `int/Q-121` @ 7b4b428; `docs/reviews/Q-121-A1-fix1.md` on branch `rev/Q-121-always-code`
BODY: VERDICT READY WITH CHANGES: the dress rehearsal can run; fix N1 + N2 before the owner's switch-on. Review-2 H1, H2, H3 CLOSED (tables re-run in all four model conditions, three confirmations, three meaning replies; model right never ends adverse, flipped confirmation ends empty); M1, M2, M3, M4, M7 CLOSED; M6 partly (your / my and the listed words closed; "Employer's contact email (for verification)", "Contact email of previous employer" still get the applicant's email). NEW HIGH N1: positive-polarity words ("clean", "clear of", "spotless", "exempt", "lack") are invisible to the negation test, so "Is your criminal record clean?" gets a confident WRONG reader: right model + right confirm = EMPTY, flipped confirm = `No~` written, wrong model = `No` unmarked with no call (fix: add to NEGATION_WORDS / PHRASES). NEW HIGH N2: negated work-rights / sponsorship questions ("Do you not require a visa...", "Are you not authorised...", "anything that prevents you...") have no negation test; with the model right and the confirmation flipped, unusable or a transport failure, `protective_end` writes code's inverted reading unmarked (fix: no T option when the label has a negation; blank end). MEDIUM N3 a trailing note that maps Yes / No ("Select Yes to confirm you have none") inverts the question and `_core_question` ignores it (introduced by the note rule); N4 entry-group guard only covers address / phone / postal: an invented "First Class" grade is written in an education entry, the expected salary is written as a past job's pay; N5 "Date of birth of dependant / child" gets the applicant's DOB; N6 an unusable F2 check keeps the model's invented own detail (Age "1999"). LOW N7-N11 and the over-protection list (required "Tick if you are not a PEP" boxes end empty with a right model) in the review. Meaning call: wording unambiguous except `relatives_at_company` / `other` (statement table), unreachable off declarations, transport failure empty, notes hold option labels only. Budget: 20 negated P2 fields = 1 call; 20 P3 = 21 (cap 23); only a page of 20 wrong-and-agreeing declarations hits the cap. strict: only facts.py is shared (strict writes less for guarantor / professor / tutor / HR words, more for "your / my" own details). Evidence: -k always_a1 145/157 (the 12 reds: 9 superseded or ruling-bound, 3 close to N6 / over-protection; none a regression), -k facts 20/20, -k pagefill 22/22, -k llm_fill 100/100, -k layering 13/13. Not reached: real model (confirmation independence), browser, flow / store / web, cache replay.
STATUS: open

### 2026-11-14 reviewer -> coordinator (Q-121 ruling U review, fourth review)
TYPE: review
RE: always.py / facts.py `git diff 7b4b428..e676c3c`, `int/Q-121` @ e676c3c (fix2 A-E, fix3, U1-U8b, W); `docs/reviews/Q-121-A1-rulingU.md` on branch `rev/Q-121-always-code`
BODY: VERDICT NOT READY for the owner's switch-on; the rehearsal should run after F1 / F2. Ruling U is implemented as stated, clause by clause (U1-U5, U8, U8b, W, U6 budget, fix2 A-E, N3-N6 all "yes", file:line in the review); third-review N1-N6 and the over-protection items are CLOSED; no cell writes a contradiction from a right model plus a right confirmation; no path writes code's reading without a model answer agreeing; cache replay is off, D1b `default:` cites and the F0 ladder do not write declarations (58 wordings probed). In every cell with a class named by either key a contradiction needs three wrong model answers EXCEPT F1. HIGH F1: the reader is a deny-list, so an unlisted inverting word gives a confident WRONG option that counts as a vote: "Is your criminal record satisfactory? / Can you pass a criminal background check? / Are you independent of ...? / fit and proper? / solvent?" -> a lazy "No" is written unmarked with NO call, and a right "Yes" + one flipped confirmation writes `No~`; for work rights "Do you have any restrictions on your right to work in the United States?" -> `No/0` (an over-claim of work authorisation), also restricted / limited / prohibited / barred / temporary visa / student visa / foreigner (fix: an allow-list of adverse and affirmative frames; anything else = no reading, so confirmation + meaning, three answers). HIGH F2 (fail-closed, introduced by U): `_decl_truth` puts prior_employment / current_employee / previously_applied in the `other` pool, so for a second application at the same company, a past employer, or a profile with one true declaration, every `declaration:other` / class-less question ends EMPTY with a right model and 0 calls: 32 of 49 wordings (dismissed, asked to resign, legal proceedings, investigation, refused a visa ...); the attempt then fails at the site's validation (fix: leave the three employer classes out of the pool; T unknown -> no reading, not empty). MEDIUM F3 model-named government_employment on "military, including National Service" -> right "Yes" + flipped confirmation writes `No~` (NS status ignored by the reader and the truth text); F4 meaning sentence for a NOT-authorised truth omits "needs no sponsorship", and class `other`'s five-way sentence is too narrow; F5 BackendError inside a vote is swallowed ("the check did not agree", page not retried); F6 a required declaration the site pre-filled with an adverse option keeps it after a failed vote (`_always_apply_one` leaves UNKNOWN alone). LOW F7-F10 (adverse wordings no key covers, "sex offender register" stops as self_id gender, entity facts copied by the model, health decline). Over-protection counted: 0 of about 100 on a first application; 32 of 49 adverse-history wordings on a repeat application (F2); 3 rare others. Cost: 20 plain declarations 3 calls (cap 29), wrong on 5: 8, all wrong: 23 (cap 83), 16 bare nouns 27 (cap 71). In-flight class-correction re-ask: sound as an extra signal, but add a deterministic anchor (a model-only class needs a word of the class definition in the label) and never run it for a class code's own key names. Evidence: `-k always_a1` 205/205, `-k facts` 22/22, `-k pagefill` 22/22, `-k llm_fill` 100/100, `-k layering` 13/13. Not reached: real model (confirmation independence, the rate the residual rests on), browser, flow / store / web, cache replay (off), the in-flight fix.
STATUS: open

### 2026-11-15 reviewer → coordinator, architect
TYPE: review
RE: Q-127 (D-215) · docs/architecture/q127_profile_questions_design.md · docs/reviews/Q-127-profile-questions-design.md
BODY: READY WITH CHANGES. Diagnosis right; design meets D-215 once the text changes land (no second design round). HIGH: H1 a promoted topic must carry no exact labels (a wrong merge would answer other wordings silently via L6); H2 "Use a different answer next time" must never reuse a captured row's key (model-named, F2 again), key = slug of the exact label with collision rule; H3 remember refused on answers that follow declarations/consents/standing rows, default scope = this employer. MEDIUM: M1 propose only named topics; M2 topics for fields the profile already has go to "Needed by n applications", count required fields only; M3 never propose national_id; M4 no `extra.*` validation text on Profile; M5 full old-bundle shape, 410 the old writers; M6 "Apply again to n" is an inline notice, not a toast. Threshold: employers, keep, make it a config value. Build order: the Coordinator's (single go-live from int/Q-121), with five conditions in the review §9 (v6 copy migration, strict stays code default, config flip as its own last commit, rollback exercised once, squash + commit message deny-list scan). Request to architect: fold H1-H3, M1-M6 into the design text and add pins 13-21 and a stale-pin tester WP.
STATUS: open

### 2026-11-15 reviewer → coordinator, architect
TYPE: review
RE: Q-126, D-214 · docs/architecture/ollama_autostart_design.md + contracts.py WP-0 @ arch/Q-126-ollama-autostart 175af9e · docs/reviews/Q-126-ollama-autostart-design.md
BODY: READY WITH CHANGES. Two HIGH, each with paste-ready text. C1: the worker can wait up to 390 s for the model and then `queue_take` without re-checking `should_stop`, so it can apply after the app was closed; re-check after `precheck` and pass `should_stop` into the wait. C2: the tick auto-resume goes beyond D-214 and D-200 (a pause hours old lifts and real applications start with no click), `queue_resume_if` stamps `resumed_at` (which erases the bot-check streak), and `port_taken` can loop; bound it (30 min, three reasons, probe checked after the pause, 2 lifts/hour, no `resumed_at`) or drop the tick and keep Resume. MEDIUM: C3 `find_ollama` must not use `shutil.which` (cwd first on Windows; known locations before PATH); C4 test guard (assign the env var, refuse in `_spawn_detached`, positive "own DB" condition); C5 cap retries per worker run; C6 the pin `test_apply_contracts_v5.py:40` fails (`-k apply_contracts` 71/72): change the pin, not the hint; the "no test pins these strings" claim is wrong; C7 ping tries and `other`/`timeout` during the start wait; C8 lock holds PID, a dead creator's lock is stale; C9 Local AI card state must be neutral too. LOW: C10 diagnosis (cache is not why the worker is blind), C11 Up-next note text, C12 `[::1]` and no-port URLs, C13/C14 merge order and manual-check additions. Merge order: land `int/Q-121` first (squash + scrub), then rebase WP-0 and build Q-126 on the new `personal`; `warm()` signature is the hard conflict (`int/Q-121` has `messages`); never base Q-126 on `int/Q-121`. Within Q-126: WP-0, E1, W1 (before or with E2), E2, U1.
STATUS: open
