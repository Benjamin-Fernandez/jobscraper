# Outbox: reviewer

Only `reviewer` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD reviewer → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

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
