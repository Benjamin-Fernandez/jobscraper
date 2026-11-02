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
