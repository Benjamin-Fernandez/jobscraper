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
