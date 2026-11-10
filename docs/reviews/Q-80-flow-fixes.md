# Review: Q-80 flow fixes (KA-1) on `eng/Q-80-flow-fixes`

Reviewer, 2026-11-08. Diff `personal...HEAD` (7e3e535): code 366c098, 1bc591f, ce8f0e4 in `src/jobscraper/apply/pagefill.py`, `apply_flow.py`, `apply/page.py`; pins 48bdc98, 5a1d4e0 (`tests/test_apply_q80_review_pins.py`, `tests/llm_fill_pages.py`, one assertion in `tests/test_apply_flow_n6a.py`). Findings fixed: R3 re-review F12, F14 (D-173 wording ruling); N6a F3, F4 (D-172), F5, F6.

## Verdict: MERGE WITH FOLLOW-UPS

No CRITICAL or HIGH finding. Every fix matches its finding, no fail-closed path is weakened in a way that reaches Submit, and the diff adds no applicant values, no new SQL and no import across layers. Three MEDIUM items (one weakened defence, one over-claiming docstring, two unpinned halves of a fix) and two LOW items go to a follow-up.

## Evidence

| Command | Last line |
|---|---|
| `PYTHONPATH=src python tests/run_tests.py -k apply_q80` | `11/11 passed  (-k 'apply_q80')` |
| `... -k pagefill` | `19/19 passed  (-k 'pagefill')` |
| `... -k apply_e2e` | `13/13 passed  (-k 'apply_e2e')` |
| `... -k layering` | `13/13 passed  (-k 'layering')` |

Revert experiments (throwaway `git worktree add --detach` under the scratchpad, removed afterwards):
- All three source files restored from `personal`, new pins kept: `4/11 passed`. Red: F12, F14, F3 (slow warm-up), both F4 pins, F5 "model gone", F6 "typed before stop". Green on old code, as controls should be: F3 deadline-still-runs-out, F4 Attach/label control, F5 real timeout, F6 stop-before-typing.
- Only `_backend_note` (pagefill) forced to "model unavailable" and only `_entry_problem` (apply_flow) forced to "": `apply_q80` 11/11, `pagefill_review` 11/11, `apply_flow_n6a` 12/12 all stay green. See M2.

## Checks asked for

1. **F12** (`pagefill.py` `_delete_entries`). Confirmed = clicked and no member key still located on the page (`_present` returns True when it cannot tell). A group whose controls remain is still "E3: delete not confirmed" and its required fields stop the page; the pin keeps that as a control (entry 2 in `unknown_required`) and the old swallowed-delete pin in `test_apply_pagefill_review` stays green. The reviewer's earlier fix text is followed except that the section-count cross-check only logs (M1).
2. **F6** (`_note_typed`). `run.known` is created per `_Run` (per `fill_page`), so a key is OURS only after `_apply_one` typed it on this page (`_mark` after `r.ok`; a file only after a readable upload). The note is added only to rows with status FILLED and origin OURS, so a step-7 stop (nothing typed) keeps "not applied" (control pin passes), and rows that failed, were cleared (G9) or only prefilled are not promoted. `stage` keeps FILLED only when the note is present, and only on `applied=False` paths, which all end the attempt; the pre-Submit scan is not reached from them.
3. **F3** (`body_llm`). `ctx.deadline += monotonic() - t_warm` after a successful `warm_up`. The added time is the measured warm-up, itself capped by the Ollama transport timeout (`ollama_timeout`, default 600 s) and executed once per attempt. A failed warm-up raises before the line. `services.deadline_left()` reads `ctx.deadline` live, so pages see the extension (pin asserts about the whole 420 s left after a 500 s warm-up; control shows later slowness still ends the attempt `error`).
4. **F5.** `_backend_note` returns one of two constants; `_transport_cause` returns text taken from a row note that starts `transport:` (constants from pagefill). The exception text is only inspected, never copied, so no profile value reaches `reason_detail` or the DB. Classification is by substring of the exception text ("timed out"/"timeout"), which matches this codebase's two producers (`llm_fill` "model call timed out", httpx `ReadTimeout` via `Ollama request failed: ...`).
5. **Auto mode.** The diff does not touch `pre_submit_scan`, `submit` or the `dry_run` branch (`apply_flow.py` ~1219-1226: scan, then dry-run stop, else `submit`). Every changed `page_result` branch still raises `ApplyFailure` before the next step. Nothing lets the llm path reach Submit without the scan.
6. **Notes and logs.** New log lines carry only a section name and a constant reason (`E3: <section> has more entries...`, `E5: add failed in <section>: <why>`; `<why>` is one of four literals). Row notes and `reason_detail` carry the section name from the page, no applicant value. No SQL added; `tests/test_layering.py` 13/13.

## Findings

### M1 MEDIUM: the section-count cross-check no longer protects anything (F12)
`pagefill.py` `_delete_entries`, the `for section, n in confirmed.items()` loop at the end (diff hunk `@@ -390,6 +395,9 @@`).
- **What changed.** Before, a delete counted only when the group's keys were gone AND the section shrank. Now the keys alone decide; a section that did not shrink as far as the confirmed deletes explain only writes a log line.
- **Why it matters.** The key check is `page.locator(pf.field.locator).count() > 0`, i.e. the reader's `data-llmfill` mark. The count was the only independent signal that a delete really happened. If a site re-creates a list item without the mark while the click was in fact swallowed (a React list re-render triggered by another group's successful delete), the junk entry looks "gone", the page does not stop, and in auto mode it is submitted with the junk entry (the required scan only flags empty required controls, and the junk entry's fields hold values, or are no longer read at all).
- **Not demonstrated.** I could not reproduce mark loss with the local stubs; Workday's DOM may never do it. The first live Workday dry run (D-83) is where it would show. Noted as MEDIUM because the loss of the second signal is certain and the effect is a silent junk row in a submitted application.
- **Spec note.** My F12 text said to use the section count "as a cross-check on the whole section ... never to demote a group whose own controls are gone". The engineer read that as log-only. Both readings satisfy the finding; I prefer the stricter one.
- **Fix.** When `left > initial - confirmed`, stop the section (keys of its confirmed groups to `unknown_required`, "E3: delete not confirmed" note) instead of only logging. The F12 scenario is unaffected (3 entries, delete of 3 works, delete of 2 swallowed: `left` 2 = 3 - 1). Add a pin: all deletes "confirmed" by keys but the section still has the old count.

### M2 MEDIUM: two halves of the fixes are not pinned (verified by reverting them)
- **F5, pagefill half.** `_backend_note` and the `except BackendError as exc` edits in `fill_page` and `_picker` (`pagefill.py` ~175, ~473, ~778) are not exercised: both F5 pins script the outcome (`transport_failed=True` with a ready-made `transport: ...` note) and never run `fill_page`. Forcing `_backend_note` to always return "model unavailable" leaves every test green (11/11 `apply_q80`, 11/11 `pagefill_review`, 12/12 `apply_flow_n6a`). A regression to "a timeout reads as model unavailable" (or the reverse) would not be caught.
  Fix: a `pagefill` test with a scripted backend that raises `BackendError("model call timed out (TimeoutError)")` once and `BackendError("Ollama request failed: ConnectError: ...")` once, asserting the rows' notes `transport: timed out` / `transport: model unavailable`.
- **F14 / D-173, flow half.** `_entry_problem` and the new `bad`/`added` split in `page_result` are not covered: the F14 pin stops at `PageOutcome` row notes. Forcing `_entry_problem` to return "" keeps all three suites green; the flow would then report the field labels again ("Job Title, Company, ...") instead of "another work experience entry could not be added (...)". Fix: a `FakeNav`-style test (like the F5 pins) whose outcome has a required `fill_failed` row carrying the E5 note, asserting `r.reason is VALIDATION_ERROR` and `"could not be added" in r.reason_detail` and that the field labels are not listed.

### M3 MEDIUM: a failed Add in a section with no required field does not stop the attempt (D-173 as written)
`pagefill.py` `_add_failed` docstring ("auto mode must not submit with fewer entries than the profile has") against `apply_flow.py` `page_result` (`req = [k for k in outcome.fill_failed if ... required]`).
- **Scenario.** A section whose fields are all optional (a Workday Education or Languages entry, or a Greenhouse employment block with optional fields): E5 asks for a second entry, Add is swallowed, `_add_failed` lists the section's keys in `fill_failed`, but `req` is empty, so no `ApplyFailure`. The page is submitted with fewer entries than the source has. Nothing false is typed and the E5 note is on the audit rows, so this is an omission, not a wrong answer. It is the same behaviour as before this branch (the filter on `required` is old), so it is not a regression; D-173's text says the attempt "still stops", and that holds only when a required field exists.
- **Fix.** Either say so in D-173 and the docstring (accepted limit until the contracts entry channel exists), or make `page_result` stop on any `fill_failed` row that carries the E5 section note, required or not. The second is one line next to `_entry_problem` and matches the docstring.

### L1 LOW: a visible non-picker button still exposes a hidden file input (D-172, F4)
`page.py` `pickerButton` (diff `@@ -352,12`) and the container path at `@@ -384,8`.
- **Probe (headless Edge on local pages, `PG.read_page`):** a form holding only the hidden `<input type=file>`, a `type=button` "Cancel" and a Submit yields a FILE field; a `.field` div with the input and a `type=button` "Help" next to it yields a FILE field. A `type=reset` sibling yields none (the D-172 case, fixed).
- **Effect.** Bounded: an optional one is left blank, a required one stops `unanswerable_required`, and the only upload is the resume into a hidden input. D-172 says "or any button that isn't a picker"; a code-only test cannot tell a picker from another button, so this is a heuristic limit, not an oversight.
- **Fix (optional).** Require the button's text/aria-label to match attach/upload/browse/choose/select/resume/CV, or its `onclick`/`for` to reference the input; keep the Greenhouse Attach fixture as a control.

### L2 LOW: timeout classification is by substring of an upstream message
`pagefill.py` `_backend_note`. "Ollama returned HTTP 500: ... timed out waiting for llama runner to start" and `ConnectTimeout` are both reported "timed out", which is arguably right for the owner (retry later) but may blur a missing model from a slow one. No safety effect; the note and detail are constants. Revisit if the first live runs show a misleading detail.

## Notes (no action)
- `_note_typed` also runs on a transport failure, so a model that dies after step 9 leaves FILLED rows with "typed before the page stopped" and no "transport:" note on them; the cause note sits on the unanswered rows (`_transport`). `_transport_cause` takes the first such row, so the detail is right unless every row had an answer, in which case it falls back to "timed out" (cosmetic).
- The 48 fixture files shown as modified in `git status` are line-ending noise and are not in the diff (`git diff personal...HEAD --stat` lists none).
- Test files sit in the Tester's scope; this review changed nothing outside `docs/reviews/`.
