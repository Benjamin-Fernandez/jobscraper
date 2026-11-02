# Review: M20 lane B (KA-1 auto-apply engine), `eng/M20-B-browser-greenhouse`

- **Reviewer:** reviewer agent, 2026-11-02
- **Diff:** `git diff personal...eng/M20-B-browser-greenhouse`, merge base `318c8b9`, head `30b6d1d`. 15 files, +3012/-22.
- **Checked against:** `docs/prd.md` F-30..F-40, NF-01..NF-09; `docs/architecture/apply_design.md` §3, §4 (ADR-0004 / D-69), §8, §9.1, §9.1.1, §12, §13, §17; the engineer's handoff (`comms/outbox/software-engineer.md`, 2026-11-02).
- **Evidence:** `python tests/run_tests.py` in the lane worktree printed `500/500 passed`. `-k layering` printed `10/10 passed`. `-k apply` printed `68/68 passed`. The worktree was clean at `30b6d1d`.

## VERDICT: APPROVE WITH FIXES

F1 (HIGH) blocks the merge. It is a 2 to 3 line fix plus one oracle. F2 to F14 do not block the merge. F2, F4 and F10 must be closed before the first `apply.mode: auto` run (the M20 gate).

What holds, checked by reading the code:
- **Dry run never submits.** `cli.py:738` uses `dry_run = args.dry_run or mode != "auto"`, so anything other than the exact value `auto` means a dry run. The config ships `mode: dry_run`. `apply_flow.py:777-781` returns before `submit()`. No `Enter` key is pressed anywhere in `browser.py` or `greenhouse.py`. The only clicks before Submit are the MyGreenhouse autofill button, a dialog close button and a file-remove button.
- **NF-06.** `submit_clicked_at` is committed before the click (`apply_flow.py:831-833`). Every exception after the click is caught (`:835-839`). The store refuses `failed` once a click is recorded (`store.py:1580`). The reaper turns a clicked attempt into `submitted_unconfirmed`. The partial unique index enforces one success per job. Confirmation is never retried.
- **Duplicates and caps** follow the §12.1 order: profile, then the same job twice in a batch, then the applied application or a twin (`posting_key`), then a clicked or succeeded attempt, then the caps on clicks since midnight Asia/Singapore, then one attempt in flight. A dry run skips the caps. A cap of 0 or below refuses every attempt, so 0 never means unlimited.
- **CAPTCHA and bot checks are a stop, never solved.** `classify` only reads the page. A challenge before the click ends `failed(captcha|bot_challenge)` with a screenshot and HTML. After the click it ends `submitted_unconfirmed` with a note. The Edge launch matches §8.1 exactly: no stealth flags, no user-agent change.
- **Migration (live DB).** The change is additive: four `CREATE TABLE IF NOT EXISTS`, one nullable `app_events.by` column added only if absent, and a `schema_version` upsert. It is idempotent. If the old build opens the database afterwards it is unaffected: no code reads `schema_version`, the old `INSERT INTO app_events` names its four columns explicitly, and the new tables are ignored.
- **Layering.** No SQL outside `store.py` and no model call outside `backends`. The store does not import `apply/`: it keeps a string copy of the transition table, and `check_attempt_table()` checks that copy against the contract at import.
- **Privacy in the diff.** There is no personal data. The config has placeholders only, and a grep for emails, phone numbers and the owner's name found nothing. Evidence and the HTML dump go to `data/apply/<id>/` (gitignored, `.gitignore:66`), and screenshot file names are step slugs only.

## Findings

### F1 HIGH: under MyGreenhouse, our resume is not uploaded when the attached file has the same name
`src/jobscraper/apply_flow.py:427-429` (with `keep_decision` at `:346-347` and `same_value` at `:382-383`).

- **Why:** for an always-ours field that shows a value, `keep_decision` returns OVERWRITE. Then `apply_prefill_policy` skips the input when `same_value()` is true, and for a FILE field that test is a **file name** comparison. Every tailored file has the same name, `First_Last_Resume.pdf` (`tailor/storage.py:36-43`), whatever the job. The original is usually `resume.pdf`.
- **Failure scenario:** MyGreenhouse holds a resume named `First_Last_Resume.pdf`. That happens if the owner saved one there, or if MyGreenhouse keeps the last uploaded file. Autofill attaches it, and the flow records "already on page" and never uploads this job's tailored file. In auto mode the employer gets a different resume: the previous job's tailored version, or an old one.
- **The audit is also wrong.** The row is `filled` with **our** file's SHA-256 (`_sent_value`, `:278-283`), and `mark_tailored_sent` marks our file `sent`.
- **Spec:** this breaks D-70 and §9.1.1 (RESUME row: "any → remove an attached file, upload the tailored file … never submit MyGreenhouse's resume"). It is the engineer's decision (4) in the handoff. Accept that decision for EMAIL, reject it for files.
- **Fix:** never take the "already on page" shortcut for `FieldType.FILE`, or at least not for `Canonical.RESUME`. Always route the field to `to_fill` so that `_replace_file` removes the attached file and uploads ours. Tester: add an oracle in which the shown file name equals ours, and assert the field is in `to_fill`.

### F2 MEDIUM: the store guard is weaker than the contract; the reaper can free an attempt that may have been clicked
`src/jobscraper/store.py:1568-1582` (`attempt_transition_allowed`) and `:1242` (`reap_attempts`).

- **Why:** the contract's `can_transition(..., clicked=False)` refuses SUBMITTING, SUBMITTED and SUBMITTED_UNCONFIRMED without a recorded click (`contracts.py:100`). The store copy drops that half, so a tester oracle can enter `submitting` without a click (the engineer disclosed this). §4.1 says the store MUST refuse.
- **Failure scenario:** a later code path (lane V's `verifying_email → submitting`, or a refactor) enters `submitting` and clicks without `mark_submit_clicked`. The process dies. The reaper sees `submit_clicked_at IS NULL` and writes `failed(cancelled)`, which frees the posting, and the next run submits a second time.
- **Fix:**
  - Enforce the contract's rule in the store, and have the tester call `mark_submit_clicked` in `test_a_posting_can_succeed_only_once` before entering SUBMITTING.
  - Make the reaper treat `state IN ('submitting','submitted_unconfirmed')`, or any post-click state, as clicked even when `submit_clicked_at` is NULL.
- **Spec:** the spec wins here.

### F3 MEDIUM: the `ApplyFailure` handler ignores `at.clicked`; a missing Submit button counts as submitted
`src/jobscraper/apply_flow.py:637-639`, `:827-839`; `greenhouse.py:562-566`.

- **Why:** the `except ApplyFailure` branch calls `fail()` unconditionally. No `ApplyFailure` can reach it after the click today, because `submit()` catches everything. A future one would make `set_attempt_state` raise `ValueError` inside the handler. That ends the batch with a traceback and leaves the row for the reaper. It is safe, but a crash.
- **Missing button:** `adapter.submit()` raises "submit button" not found **after** the click has been recorded. The attempt ends `submitted_unconfirmed`, and the job is blocked as "already submitted by JobScraper" with nothing sent. In M20 nothing can clear that state, because "It didn't go through" is M21.
- **Fix:**
  - Mirror the `except Exception` branch: `if at.clicked: self.unconfirmed(...)`.
  - Find the Submit button (count > 0, visible) before `mark_submit_clicked`, and fail `page_unrecognised` before the click if it is absent.

### F4 MEDIUM: the reaper runs without a "no apply job running" check; `mark_submit_clicked` is not a compare-and-set
`src/jobscraper/apply_flow.py:879-882`, `store.py:1215` and `:1242`.

- **Why:** §4.3 and §12.1(4) rely on the JobManager's single slot, but the CLI `apply` bypasses the JobManager.
- **Failure scenario:** the owner runs `python -m jobscraper apply X` while a web apply job is live. The second run's reaper rewrites the first run's live attempt. Before the click it becomes `failed(cancelled)`, and the first run then crashes on its next transition. After the click it becomes `submitted_unconfirmed`, and the first run's real confirmation then raises `ValueError`, so Applications is never set to `applied`.
- **Why no double submission today:** the Edge profile lock, the transition table and the clicked-attempt duplicate rule together prevent one. The protection is accidental, though.
- **Second problem:** `mark_submit_clicked` stamps any row, including a reaped `failed` one. That leaves a `failed` row with a click, which blocks the job for good and which no owner action can clear.
- **Fix:**
  - Use a run lock: a PID file in `<db dir>/apply/`, or reap only attempts whose `started_at` is older than `attempt_timeout_s + confirm_timeout_s + mail.wait_s`.
  - Make the pre-click write a compare-and-set: `UPDATE … SET submit_clicked_at=? WHERE id=? AND state='filling' AND submit_clicked_at IS NULL`, require `rowcount == 1`, and re-run `apply_duplicate` and `apply_counts` in the same transaction before clicking.

### F5 MEDIUM: the CLI summary bypasses redaction (NF-09)
`src/jobscraper/cli.py:744-745`.

- **Why:** the result table prints `reason_detail` to stdout without going through `redact()`, and for a web job stdout is the Developer-tab log. A `validation_error` detail can include the site's own error text (`greenhouse.visible_errors` takes `.helper-text--error` text verbatim), which may repeat a typed value. The per-state log line for the same failure *is* redacted.
- **Fix:** print the table through `apply_flow.redact(line, applicant.redaction_values(profile))`, or return redacted details in `AttemptResult`.

### F6 MEDIUM (decision 5, accepted with a limit): whole-word redaction misses values next to a digit
`src/jobscraper/apply_flow.py:75-84`.

- The lookarounds `(?<![0-9A-Za-z])…(?![0-9A-Za-z])` fix the "cap" → "[redacted]tcha" problem. They also mean a profile phone `91234567` is **not** redacted inside `+6591234567`.
- **Suggestion:** apply the word boundary only to purely alphabetic values, and keep substring matching for values that contain a digit or `@`.

### F7 MEDIUM: `captcha_wait_s` is not built, though F-38 (P0) and §8.4 define it
`config/config.yaml` (`captcha_wait_s: 0`) and `ApplyConfig.SETTING_KEYS`.

- The default of 0 behaves correctly. A value above 0, from config or Settings, is silently ignored.
- **Accept the deferral,** but log "captcha_wait_s is not supported yet" when it is above 0, or reject it.
- **Design gap for the architect:** "a confirmation seen meanwhile turns it into `submitted`" needs `filling → submitted`. TRANSITIONS does not have that edge, and the click rule would refuse it, because the owner's own click is never recorded.

### F8 MEDIUM (decision: phone country left blank): risk of a wrongly formatted phone
`greenhouse.py:216-219` and `:528-532`.

- The `country` react-select gets no answer: it has no schema options, so the resolver returns nothing. intl-tel-input then uses its default country.
- A profile phone without `+65` may be read as another country's number or rejected. A rejection means `validation_error`, which fails closed. A silent misformat sends a wrong number.
- **Suggestion:** for `PHONE_COUNTRY_CODE` with no options, answer from `contact.phone_country` (for example "Singapore") through the existing typeahead path, or require an E.164 `contact.phone` in `applicant check`. Check this in the Greenhouse dry-run screenshots at the gate.

### F9 MEDIUM: MyGreenhouse KEEP may keep employer-specific free text (design, for the architect)
§9.1.1 table, `contracts.py:433`.

- `ALWAYS_OURS = {RESUME, EMAIL}`. The design states MyGreenhouse stores "saved answers to common questions". A cover-letter textarea or a "Why <company>?" answer saved for another employer is **kept**.
- The implementation follows the spec, so the spec wins here. Raise it for S-6: consider adding COVER_LETTER, and TEXTAREA fields whose label names the company, to the always-ours set.

### F10 MEDIUM: the orchestrator has no automated tests
- The suite never calls `apply_flow.run`. The WP Verify files `test_apply_flow.py`, `test_apply_cli.py`, `test_apply_e2e.py` and `test_greenhouse_fill.py` do not exist. The engineer quotes scratch runs only.
- **Required before any `mode: auto` run** (tester): a fake browser and adapter proving each of these:
  - (a) a dry run never calls `submit`;
  - (b) an exception after the click ends `submitted_unconfirmed` and never `failed`;
  - (c) duplicate, twin and cap refusals through the flow;
  - (d) log lines are redacted;
  - (e) F1's resume rule.

### F11 LOW: reserved words pass the job-id check
`web/jobs.py:110-115`, `cli.py` `cmd_apply`.
- `show` and `open-profile` match `[A-Za-z0-9:_-]{1,80}`, so a web `apply` job with `job_ids=["show","<id>"]` runs `apply show <id>`. That prints every answer, sensitive ones included, into the Developer-tab job log.
- It is reachable only by a crafted local request. **Fix:** the builder refuses those two words.

### F12 LOW (decision 1, accepted): evidence beside the DB
`apply_flow.py:145-147`.
- With the default `paths.db` the evidence lands in `data/apply/`, which is gitignored. A dev DB copied anywhere in a worktree other than `data/` would put screenshots and `failed.html` (personal data) in a path that is **not** ignored.
- **Suggestion:** warn when `evidence_root` is inside the repo but not under `data/`, or document "copy the DB to `<worktree>/data/`".

### F13 LOW: the `schema_version` upsert downgrades
`store.py:339-342`. An older build opening a future v4 database would write `3`. Nothing reads the value today. Use `MAX(CAST(value AS INTEGER), ?)`.

### F14 LOW: the orchestrator reaches into `store.conn.commit()`
`apply_flow.py` (4 places). This is the first module other than `store.py` to touch the connection. It is not SQL and the layering test passes. Add `Store.commit()`.

## Engineer decisions (handoff list)
| # | Decision | Verdict |
|---|---|---|
| 1 | evidence in `<db dir>/apply/<id>/` | Accept (F12 note) |
| 2 | in-flight refusal reason `error`, detail "another application is in progress" | Accept (§12.1(4) names the detail, not the code) |
| 3 | audit rows written after Next; an early end writes all | Accept |
| 4 | an always-ours field equal to ours is recorded "already on page" with no input | Accept for EMAIL; **reject for FILE/RESUME (F1)** |
| 5 | whole-word redaction | Accept with the F6 limit |
| 6 | a tailor failure is logged and the original is used | Accept (F-34 bullet 3) |
| — | phone country left blank | Accept for now (F8) |
| — | `captcha_wait_s` not built | Accept the deferral (F7) |

## Open issues for the Coordinator
- In M20 nothing can clear a `submitted_unconfirmed` attempt ("It didn't go through" is M21). Any false `submitted_unconfirmed` blocks that posting until the database is edited by hand. Plan the store method before the gate's real submissions.
- Back up `data/jobscraper.db` before the first launch after the merge. The migration is safe, but this is the live database.
