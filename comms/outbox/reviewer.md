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
