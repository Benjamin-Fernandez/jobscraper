# Review: Q-60 / F-50, lane F (store, sync flow, CLI, web timer) (KA-3)

**Scope:** `git diff 5409278 136d44c` plus `771c12d`, head `2662865`, on `int/Q-60-mail-status` (worktree `feat-Q-60`): `store.py` (DDL, `mail_*`
methods, `_write_status`), `mailstatus_flow.py`, `config.py` (`MailStatusConfig`, `as_bool`), `config/config.yaml`, `cli.py` (`mail sync`, `mail accounts`,
`cmd_web`), `web/mailsync.py`, `web/routers/mail.py`, `web/routers/applications.py`, `web/api.py`.
**Spec:** MS §4, §5, §8, §9, §10, §12, §13; ADR-0007; D-150..D-156.
**Reviewer:** reviewer agent, 2026-11-07. Read-only on code. Reproductions ran in a scratch interpreter (stdin, no repo files) against temp DBs under a temp dir,
`tests/mail_support.FakeMailServer`, an in-memory keyring and a fake backend with `available = False`. No real mailbox, no keyring, no `data/`, no port 8765.

## Verdict: APPROVE WITH FIXES

The design points I was asked to check hold. The mailbox stays read-only in a real flow run (only `CAPABILITY LIST LOGIN EXAMINE UID SEARCH UID FETCH LOGOUT` reached the
fake server, `violations == []`). The password reaches only Credential Manager and the child's stdin: not the DB (byte scan of file and WAL), not the logs, not argv,
not the child environment. The cursor, message row, event, evidence and status move in one transaction (a forced failure left nothing behind). Forward-only,
owner-newer-wins, the Spam rule and "model never AUTO" are enforced in the flow as the spec says. Schema 4 to 5 migrates cleanly and an older build still opens the result.

**One MAJOR defect needs a fix before the owner connects a real mailbox (FL-1):** one email with a raw-UTF-8 sender domain wedges the mailbox for good, silently. A
second MAJOR (FL-2) is that lane F has no committed tests at all. Neither blocks merging the code into `personal`, because no mailbox is connected until the owner does it
and the sync only reads: merge, then fix FL-1 and write the oracles before the M-gate (the first real connection).

## Tests

- `python tests/run_tests.py -k mail` → `126/126 passed  (-k 'mail')`
- `python tests/run_tests.py -k layering` → `13/13 passed  (-k 'layering')` (no SQL outside `store.py`; web does not import `imapread`; flow and stage edges fine)
- Full suite: see the last line of this section.
- No test in `tests/` imports `mailstatus_flow`, `mail_record`, `MailSyncRunner` or the `/api/mail` routes (grep). The engineer's e2e scripts live in the session scratchpad only.
- Vitest was not run: the worktree has no `node_modules`.
- Full suite result: `python tests/run_tests.py` → `1041/1041 passed` (browser tests skipped: no browser available).

## Findings

### FL-1 MAJOR: one email can wedge a mailbox permanently (poison message; reproduced)
- **Where:** `mailstatus_flow.py:274-277` (`process` then `mail_record` for each header) and `:239-245` (any non-`_Stop` exception ends the account as `internal`; the cursor
  stays before the message); `store.py:2247-2257` (binds `sender_domain`); the bad value comes from `imapread.parse_header` (header bytes decoded with
  surrogate escapes: `From: a@bücher.example` as raw UTF-8 gives `from_domain == 'b\udcc3\udcbccher.example'`).
- **Scenario (reproduced):** the tracked application is Acme. The mailbox holds (1) an auto-reply (`Auto-Submitted: auto-replied`) from a raw-UTF-8 domain, then (2) a real
  rejection from `recruiting@acme.example`. Runs 1, 2 and 3 all end `internal` (`UnicodeEncodeError` inside `mail_record`: sqlite refuses a lone surrogate), 0 message rows,
  application still `applied`; `fail_count` 1, 2, 3 and `retry_after` grows 10, 20, 40 minutes (cap 60). The rejection is never processed; the UI says only "internal error".
  The `auto_reply` gate precedes `not_job_mail` and only `too_old`/`own_mail`/`not_job_mail` blank the domain (`_NO_TRACE_REASONS`, `:54`, `:405`), so any auto-reply or
  other gated mail carries the raw `from_domain` to the INSERT. Anyone who can email the owner can trigger it (a spam message with the right header), and the same shape applies to any
  future bug in `process` or the store for one message. (A raw-UTF-8 display name also leaves surrogates in `from_name`; that one is never stored, so it doesn't fail.)
- **Fix (three layers, do at least the first two):** (a) lane I, `imapread.parse_header`: make `from_domain`/`from_reg` ASCII (punycode via `idna`, else `""`) and strip surrogates from every str field of `MailHeader`;
  (b) lane F, `store.py`: one `_text()` helper (`s.encode("utf-8","replace").decode()`) on every string bound in `mail_*`; (c) lane F, flow: isolate the message. Wrap `process` + `mail_record` in `try/except Exception`
  (not `_Stop`, not `MailFailure`); on failure store a minimal `skipped / internal` row (`gm_msgid`, role, uid, received_at, no text) with the cursor in the same transaction, count it
  (`counts.errors`), and stop the account only after N consecutive failures. **Spec disagreement:** MS §12 row "Unexpected exception" says stop the account. The spec stands until the architect amends it;
  I recommend the amendment because the current rule turns any single-message bug into a silent permanent stall. **Tester:** pin "auto-reply from a surrogate domain, then a real rejection: the rejection is applied".

### FL-2 MAJOR: lane F has no committed tests
- **Where:** `tests/` (grep above). The store transaction methods, the lease, the migration, the flow, the CLI verbs, the runner and 11 routes carry the status changes of the owner's real
  applications, and nothing pins them.
- **Fix (tester, before the M-gate):** oracles for at least these, each of which I ran by hand: (1) `mail_record` rolls back message, event, evidence and cursor when the
  cursor write fails; (2) the AUTO re-check gives `no_change/owner_newer` when the status moved between decide and record; (3) accept: no job_id or a foreign job_id on an ambiguous suggestion is `not_found`, a replay is `not_open`,
  dismiss after accept is `not_open`; (4) undo restores status and `applied_at`, a second undo is `not_open`, a re-sync and a disconnect-then-reconnect never re-apply an undone mail; (5) lease: a second `mail_run_begin` returns None,
  a stale one is `abandoned`, the old run's heartbeat is False; (6) migration 4 to 5 (build a v4 DB with the old `Store`); (7) FL-1 and FL-3; (8) the runner: password only on stdin (argv and `child_env()` checked), the timer skips PAUSED,
  `JOBSCRAPER_MAIL_SYNC=0` gives no timer; (9) a UIDVALIDITY change: no second event, cursor re-based.

### FL-3 MINOR: a sync that is running when the mailbox is disconnected re-creates its rows (reproduced)
- **Where:** `store.py:2212-2264` (`mail_record` never checks that the account still exists), `web/routers/mail.py:225-244` (`delete_account` doesn't look at the lease), `cli.py` `remove`.
- **Scenario:** the owner disconnects during a sync. `mail_account_delete` clears the rows; the child's next `mail_record` for that account id inserts a message row and a cursor (reproduced: `orphan msgs 1, orphan cursors 1`),
  and evidence rows for a suggestion would point at an account that is gone. Ids are AUTOINCREMENT, so a reconnect gets a new id and the orphans stay forever (matched ones are never purged). It breaks F-50c ("delete its cursor, log, suggestions") for the window of one sync.
- **Fix:** inside the `mail_record`/`mail_resolve_pending` transaction `SELECT 1 FROM mail_accounts WHERE id = ?` and return `{outcome: "gone"}` (the flow then raises `_Stop`); or refuse the disconnect with 409 while a lease is held.

### FL-4 MINOR: dev instances still read the real mailbox by default
- **Where:** `cli.py` `cmd_web` (`JOBSCRAPER_MAIL_SYNC` defaults to on); the `CLAUDE.md` dev-instance command has no `JOBSCRAPER_MAIL_SYNC=0` (the architect's request and ADR-0007 item 3 are still open).
- **Scenario:** after the owner connects a mailbox, the documented dev command (copy `data/jobscraper.db`, port 8768) starts a timer that reads the real Gmail from the copy with its own lease and its own cursors: duplicate Gmail logins, suggestions in a throw-away DB, and the vault password used by two apps.
- **Fix:** Coordinator updates `CLAUDE.md`; better, `cmd_web` turns the timer off by default when `JOBSCRAPER_DB` is set (an explicit `JOBSCRAPER_MAIL_SYNC=1` turns it on).

### FL-5 MINOR: pending-model retries burn once per tick, so "3 days" is 30 minutes (reasoned; matches MS §5.5 literally)
- **Where:** `mailstatus_flow.py:419-427`, `store.py:2364-2369` (retries + 1 on every sync where the model is unavailable), `MAIL_MODEL_RETRIES = 3`.
- **Scenario:** the owner has Ollama off when the app opens. Three timer ticks (about 30 minutes) later every `pending_model` row is `expired` and becomes an "unclear" suggestion with no target, although the window is 3 days.
- **Fix:** count a retry only when a model call was made and gave no usable answer; an unavailable model should leave `retries` alone (age still expires the row). Needs an architect word on §5.5.

### FL-6 MINOR: "Check now" does nothing on an account in backoff, and says so nowhere (reasoned; the engineer raised it as Q1)
- **Where:** `mailstatus_flow.py:497` (`retry_after` applies to every trigger), `web/routers/mail.py:249-263`.
- **Scenario:** after a network error the account has `retry_after = now + 10..60 min`. The owner clicks Check now: the run is `ok` with zero accounts and the UI shows a normal result. Same for `mail sync` on the CLI ("no mailbox to read now").
- **Fix:** owner triggers (`OWNER_TRIGGERS`) ignore `retry_after`, as they already ignore PAUSED.

### FL-7 MINOR: read routes write, and wait for the write lock (reasoned)
- **Where:** `store.py:2399-2444` (`mail_suggestions` marks stale rows `superseded` and commits; N+1 `_mail_app_brief`), called from `GET /api/mail` (`routers/mail.py:145`, polled every 5 s by the card) and `GET /api/mail/suggestions`.
- **Scenario:** a poll that finds a stale suggestion needs the write lock while a sync's `mail_record` holds it (or the reverse): "database is locked" after 5 s becomes a 500 on a GET.
- **Fix:** compute `live` in the read without writing and let the sync, accept and dismiss paths do the `superseded` update; or catch the locked DB and return the rows unchanged.

### FL-8 MINOR: `async def` routes do blocking SQLite on the event loop (reasoned)
- **Where:** `routers/mail.py:170, 189, 199, 213, 300` (`add_account`, `add_application_account`, `set_account_password`, `switch_account`, `accept_suggestion`): `open_store` and `mail_accept` (`BEGIN IMMEDIATE`, waits up to the 5 s busy timeout) run on the loop. The child processes are correctly pushed to `run_in_threadpool`.
- **Scenario:** an Accept while a sync holds the write lock freezes the whole web app (every tab) for up to 5 s.
- **Fix:** read the body in the async part, then do the store work inside `run_in_threadpool`.

### FL-9 MINOR: an owner who backfills applications gets no updates, and nothing says why (reasoned)
- **Where:** `store.py:2165-2166` (`owner_changed_at` = latest owner event `at`, the time of the click), `transition` row 6.
- **Scenario:** the owner enters last month's applications today. Every email older than the entry time is `no_change / owner_newer` (right per MS §8), but there is no UI for that outcome, so acknowledgements, rejections and offers for those applications are never even suggested.
- **Fix:** none needed for the merge. Suggest that an `owner_newer` result for a forward verdict yields a suggestion (the owner still decides) instead of silence, or that the first-sync note says it. Architect's call.

### FL-10 NIT (all reasoned unless marked)
- `web/mailsync.py:136-143`: `_next_delay()` reads the *previous* run's state right after spawning the new child, so the 60 s catch-up after a `partial` run starts one cycle late (10 minutes first).
- `mailstatus_flow.py:149-156`: `first_sync_from` parses `applied_at` with `TIME_FMT`; a value with an offset or microseconds raises `ValueError` and the connect child reports `internal`. `applied_at` from the web may be free-form (not checked).
- `config.py` `MailStatusConfig.from_raw`: `int(float(v))` raises `OverflowError` for `.inf`, which isn't caught, so `cfg.mail_status` and `GET /api/mail` fail on such a config.
- `store.py:2281`: a `to_apply` application moved straight to `rejected` by mail gets `applied_at` = the rejection date. Undo restores NULL (the undo restore itself was reproduced on an applied → rejected change).
- `web/mailsync.py:111-117`: `stop()` doesn't end a running child, so a sync can outlive the app and keep the DB open; it ends at its own deadline.
- Public repo: real employer names in code and tests (`imapread.py:223-239` docstrings use `dbs.com`; `tests/fixtures/mail/rules_min.yaml:16` and `tests/test_mail_review_pins.py` use Grab/Sea as the common-word examples; `store.py:537`, older). Not personal data; the handover asks for "Acme". No other personal data, e-mail addresses or secrets in the diff (grep of the range).

## Verified OK (reproduced unless marked "read")

- **Read-only:** a full first sync, a UIDVALIDITY change, a re-sync, an undo and a reconnect sync against `FakeMailServer`: commands used `CAPABILITY CONNECT EXAMINE LIST LOGIN LOGOUT UID FETCH UID SEARCH`; `violations == []`. The flow reaches IMAP only through `ImapTransport`. `retry_pending` and `refind` use the same wrapper (read).
- **Password:** the web route wraps it in `Secret` at once and never builds a pydantic model (read); `_short` sends `password + "\n"` as `input=` to `subprocess.run` with `env=child_env()` (a copy of `os.environ` plus path and encoding, no secret) and an argv that has `--password-stdin` only (read, `web/mailsync.py:48-76, 218-241`); `cmd_mail_status._read_password` reads one stdin line. After the e2e run: password not in the DB file or WAL; none of the canary subject, the address, the password, "Acme" or the domain in the log output; the canary subject is not in `mail_messages` (it can be in `mail_evidence.subject`, by design, capped at 120). `_log_crash` logs class and frames only.
- **One transaction:** `mail_record` (BEGIN IMMEDIATE; message, status, event, evidence, cursor; commit; rollback on any error). Forced `RuntimeError` in the cursor write: status unchanged, 0 message rows, 0 `by='mail'` events, 0 evidence, no cursor. `mail_resolve_pending` has the same shape (read).
- **No gap, no double processing:** a crash between messages resumes at the stored uid (read; per-message `cursor_after`); `seen` dedupe by X-GM-MSGID; UIDVALIDITY change: 0 scanned (nothing after `last_scan_at`), events unchanged (3 before, 3 after), cursors re-based with the new validity. `last_scan_at` rides unchanged on per-message cursors and moves only on a complete scan, so a capped scan plus a validity change can't skip a backlog (read, `imapread.py:998-1000`).
- **Forward-only, owner-newer, Spam, model:** an acknowledgement for an `applied` application gave `no_change/same_status`; the rejection gave AUTO `forward`; an interview invitation found in Spam gave a `from_spam` suggestion (not AUTO); the AUTO re-check with a moved status gave `no_change/owner_newer` and left the owner's `interviewing` alone; undo wrote an owner event, so the same mail does not re-apply after a re-sync **or after disconnect plus reconnect** (the rebuilt message rows come back as `owner_newer`). A model verdict can't be AUTO (`transition` model_tier, first review; the flow passes the verdict tier through unchanged, read).
- **Accept / dismiss / undo (store level):** accept without job_id on an ambiguous suggestion `not_found`; with a foreign job_id `not_found`; with a candidate `ok` and the status moved; replay `not_open`; dismiss after accept `not_open`; undo of the accepted change `ok` with status and `applied_at` back; undo of an open suggestion `not_found`; accept of a dismissed one `not_open`. Quotes are cut to 200 and subjects to 120 in the INSERT. Route inputs: ids `ge=1`, body size capped at 4096 B, errors are fixed text, writes sit behind `CrossSiteWriteGuard` (read).
- **Lease:** a second `mail_run_begin` while a fresh run exists gives None, also from a second `Store` on the same file; after the TTL the old row is `abandoned`, its heartbeat returns False and the new run's True. The runner checks the lease and its own child before spawning; the timer is a daemon thread that only reads the store and calls `Popen` (never blocks the server); PAUSED accounts are skipped by `tick`; `JOBSCRAPER_MAIL_SYNC=0` gives `mail_timer=False` (read, `cli.py` `cmd_web`).
- **Migration 4 to 5:** a DB made by the old `Store` (5409278) with two events opens with the new `Store` in 7 ms; the five `mail_*` tables appear, `schema_version` becomes 5, data and `by=NULL` events intact, a second open is clean. **Rollback:** the old build opens the v5 DB, sees all events (including `by='mail'`), writes, and leaves the new tables alone. No `ALTER` is involved (`by` already exists), so there is nothing to undo; caveats: the old build's `delete_application` doesn't remove `mail_evidence` rows, and an old UI knows no `assessment` status. Neither loses data.
- **Layering:** `-k layering` 13/13; no `execute(` in `mailstatus_flow.py`, `web/mailsync.py`, `routers/mail.py`; `store.py` imports no `mailstatus` module (read).
- **Privacy of stored text (MS §13):** `mail_messages` holds no subject, address or text (`row()`); evidence holds subject ≤ 120 and quote ≤ 200 from the link-scrubbed text; the Gmail link is built from the account address and X-GM-MSGID, never from mail. API responses expose them only on localhost behind the trusted-host check.
- **Config:** `as_bool` truth table equals `transition.as_bool` (read); `mail_status.enabled` defaults on but nothing is read until a mailbox is connected with consent (`_has_live_account`, `_eligible`).

## Requests

- **Software engineer (lanes F and I):** FL-1 (a, b, c), FL-3, FL-6, FL-7, FL-8; FL-10 items at leisure.
- **Tester:** FL-2 oracles (the list is the hand-run set above), including the FL-1 surrogate pin.
- **Architect:** amend MS §12 (per-message isolation, FL-1) and §5.5 (what counts as a retry, FL-5); decide FL-9 and the 5-plus-character name residual from the first review (F3).
- **Coordinator:** FL-4 (`CLAUDE.md` dev command; the `cmd_web` default), and the scratchpad write block (my Write tool was refused there; I used stdin scripts only, so nothing was written outside `docs/reviews/` and the outbox).
