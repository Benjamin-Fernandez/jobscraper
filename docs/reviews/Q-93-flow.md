# Review Q-93 (KA-1): D-174 E5 stop, D-175 file-input trigger, pick-path cause

Reviewer: independent. Branch `eng/Q-93-flow`. Change set `git diff 43be498^..006f8f3` (code 43be498, pins 006f8f3); the personal merge 72aa339 is ignored.
Sources: `docs/reviews/Q-80-flow-fixes.md` (M3, L1, M2/L2), engineer handoff (newest Q-93 entry, `comms/outbox/software-engineer.md`).

## Verdict: MERGE WITH FOLLOW-UPS

No CRITICAL or HIGH finding. Each change matches its ruling, no fail-closed path is weakened (D-174 adds a stop), and every pin goes red when its fix is reverted. Two MEDIUM follow-ups (D-175 recall and visibility) and three LOW notes.

## Verify (last lines)
- `-k apply_q93`: `6/6 passed  (-k 'apply_q93')`
- `-k apply_q80`: `15/15 passed  (-k 'apply_q80')`
- `-k pagefill`: `19/19 passed  (-k 'pagefill')`
- `-k apply_n6a_defect_pins`: `2/2 passed  (-k 'apply_n6a_defect_pins')`
- `-k layering`: `13/13 passed  (-k 'layering')`

## Pins kill the fixes
Throwaway worktree on 006f8f3 (in the scratch area), one source file reverted to 43be498^ at a time, then the worktree was removed.

| Reverted file | Result | Red test |
|---|---|---|
| `apply_flow.py` (D-174) | `-k apply_q93` 4/6 | `test_m3_an_optional_row_with_the_e5_note...` (state READY_TO_SUBMIT, no stop) and the browser M3 test; the control stays green |
| `apply/page.py` (D-175) | `-k apply_q93` 5/6 | `test_l1_a_cancel_button_or_a_help_button...` ("a Cancel button in the form exposes the hidden file input"); the L1 control stays green |
| `apply/pagefill.py` (cause) | `apply_q93` 5/6, `apply_q80` 14/15 | `test_pick_the_attempt_detail...` ("timed out on one" for BackendError) and the tightened q80 pin (`set()` != `{want}`) |

The tightened q80 pin is a strict improvement (exact match). Controls sit beside each pin, so "just delete the check" stays red. Caveat: the Edge-based pins return early when Edge is unavailable (known Q-84 issue); the kill runs above prove they executed here.

## 1. Rulings and fail-closed

**D-174 (apply_flow.py:1307-1315).** Matches the ruling. `added` is now computed over all `fill_failed` rows (required or not); `bad` stays required-only and excludes E5-noted rows. Other optional `fill_failed` rows still do not stop (control pin). The stop raises before Next/Submit, so it can only turn a would-be proceed into `validation_error`. Fail-closed strengthened.

**D-175 (page.py:358-370).** Matches the ruling: text or aria-label word match, or `aria-controls == el.id`; visible `label[for]` and the submit/reset/CTRL exclusions are unchanged. Dropping a button can only make the reader skip a file field, never fill a wrong one, so the direction is fail-closed. The cost is recall, see below.

**Pick-path cause (pagefill.py:798-804).** Matches the ruling. Guarded by `note.lower().startswith("transport:")` and applied only when no row has one. `_transport_cause` splits on ":" then ";", so "transport: model unavailable; <old note>" reads as "model unavailable". The deadline branch in `page_result` (`deadline_left() <= 0` gives "timed out") is checked first and is unchanged.

### D-175 recall: probe results
Edge, a `display:none` file input plus one sibling control inside `.field`, no label[for] (probe script in the scratch area, not committed).
- READ: `Attach`, `Select Files`, `Browse...`, `Choose from computer`, `Add attachment`, role=button `Drop file here`, `<span>Attach</span>`, aria-label `Upload` / `Attach` on an icon, `Resume later` (the known bounded residual).
- DROPPED: `Add`, `Replace`, `Change`, `Résumé` (accented: ASCII `\b` and `resume` do not match `résumé`), `Curriculum Vitae`, `From my device`, `Add document`, an icon-only button without aria-label, `Cancel`.

The main providers' controls are safe: Greenhouse `Attach`, Workday `Select Files` / drop zone `Drop file here`, Lever/Ashby `Upload`/`Attach` styles. The Greenhouse siblings Dropbox / Google Drive / `Enter manually` are not triggers by themselves, but `Attach` always sits beside them.

## Findings

### MEDIUM-1 (recall, D-175): accented and synonym button texts no longer expose a required resume
page.py:361 `PICK_WORDS`. Scenario: a custom ATS shows a hidden `<input type=file>` whose only trigger is a button reading `Résumé`, `Add`, `Replace`, `Change` (shown after a file is already attached), `Curriculum Vitae`, or `Add document`, with no `label[for]` and no `aria-controls`. Before Q-93 the input was read and the resume uploaded; now the field is not read at all. For a required resume the site's own validation then blocks Next and the attempt ends `validation_error` (it stops where it used to succeed; fail-closed). For an optional resume the application proceeds without it; the N6b review check (resume name on the page) is the backstop, and I did not verify that it covers the optional case.
Suggested fix (cheap, still bounded): accept `r[eé]sum[eé]`, `curriculum`, `document`, and `replace`/`change` only together with a file word. Spec disagreement: none; the ruling listed the exact word set and the engineer followed it. A follow-up, not a blocker.

### MEDIUM-2 (visibility): a dropped hidden file input is invisible in the audit
page.py:396-400. When `trigger` is false the input is silently skipped. With D-175 this happens more often and nothing records it. A one-line log ("hidden file input skipped: no picker button") would turn MEDIUM-1 from a silent resume omission into a diagnosable one. Same follow-up.

### LOW-1: a FILLED row can carry a leading "transport:" note
pagefill.py:798-804. I traced every reader of notes:
- `_transport` always returns `transport_failed=True`; `page_result` raises `ApplyFailure` for it and never calls `capture` (apply_flow.py:1291-1296). The Questions-card path (`questions.capture_page`, questions.py:325) is not reached for that outcome, and it skips `transport`-prefixed rows anyway.
- `_cache_put` is called only from `_outcome` (pagefill.py:750), not from `_transport`, so no cache row is written from a transport-failed page.
- `stage(applied=False)` (apply_flow.py:1336) flips a FILLED row to SKIPPED + "not applied" unless it carries the typed-before-stop note; a typed first row stays FILLED/applied with a note that leads with "transport: ...". Audit display only. No behaviour change found. If a later reader treats a leading "transport" as "row unanswered", the first row would be misclassified; today none does.

### LOW-2: `attach\w*` / `upload\w*` match derived forms
The handoff states it. Harmless (attachment, uploaded). `Resume later` stays a residual as ruled; L2 (substring classification) is untouched.

### LOW-3: Edge pins skip silently without Edge
The tests return early when `edge_available()` is false. This is the project-wide issue in the handover "Watch out"; keep gating the apply merge on separate `-k apply_q93` / `apply_e2e` / `apply_flow` runs.

## 2. Auto mode
The diff does not touch `submit`, `pre_submit_scan` or the mode logic. Auto mode still reaches Submit only through `pre_submit_scan` (apply_flow.py:1215-1221, 1228-1267, fail-closed when the scan cannot run). D-174 only adds a pre-Next stop. No path added that skips the scan.

## 3. Personal data, logs, layering
- Added lines scanned for emails, phone prefixes, passwords/keys and owner names: nothing. Stub content uses fictional "Example Logistics Pte Ltd" / "Campus Robot League".
- No new log lines. The existing E5 log carries section names and a reason, not applicant values. The notes added are fixed strings ("transport: model unavailable" or "transport: timed out").
- No SQL, no model calls, no new cross-stage imports. `-k layering` 13/13. No CAPTCHA or bot-check handling touched.

## Follow-ups to queue
1. D-175 recall words (MEDIUM-1) and a skip log line (MEDIUM-2).
2. On the first real Workday/Greenhouse dry run (M20 gate): confirm the resume field is still read (`Select Files` / `Attach`), and that a Workday page with a file already attached (button text may be `Replace`/`Delete`) behaves as before.
3. L2 substring classification stays a residual as ruled.
