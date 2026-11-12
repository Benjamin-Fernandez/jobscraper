# Review: Q-120 auto-apply queue code (KA-1), `int/Q-120` @ 585ed8a

Reviewer, 2026-11-12. Scope: `git diff personal...int/Q-120` (store, worker, CLI, web, store and web pins, and the handler-rename fix 0481ab4), checked against `docs/architecture/apply_queue_design.md` (revised), the design review `Q-120-apply-queue-design.md` (H1 to H4, M1 to M6) and the engineers' and tester's handoffs.

**Verdict: FIX BEFORE MERGE.** The safety core is sound. Never twice still rests on the untouched `claim_click`, `apply_duplicate`, the reaper and the state machine, plus the new `UNIQUE(job_id)`, the live-attempt checks and `queue_take`'s single `BEGIN IMMEDIATE`. One in flight holds through the slot, `RunLock` and one loop. Consent holds through the fail-closed restart gate and pauses that need Resume. The dry-run rule holds through `pick_mode` plus a row that starts as `dry_run`. Two things must happen before this branch reaches `personal`:
1. **F1 (HIGH): pin the worker.** The design's §8 worker pins (P1, P6, P8, P9, P10/P10b, P14, P15, P20) are missing. So are the "pinned both ways" `pick_mode` pin (I5/H4) and any `pause_for` table pin. Nothing in `tests/` calls `run_queue`, `pick_mode` or `pause_for`.
2. **F2 (HIGH, merge order): the current bundle has no way to resume the queue.** Merge after WP-U1 and WP-U2, or at least after a Resume control and honest toasts land (Q9 below). Otherwise every pause is permanent in the owner's daily app, and the Inbox still says "Auto-apply started."

Evidence (export of int/Q-120 into a temp directory; no server, browser, worker or `data/` touched):
- `python tests/run_tests.py -k apply_queue` → `21/21 passed`
- `-k store` → `98/98 passed`
- `-k layering` → `13/13 passed`
- `-k web_` → `133/133 passed`; `-k test_web_mail` alone → `8/8 passed` (the `start_timer` collision is fixed by 0481ab4: handlers are now `pause_apply_queue_on_startup` and `start_apply_queue`).
- A probe script with the flow fakes on temp DBs (`FakeBrowserFactory`, `FakeAdapter`, rules fill):
  - P10b: auto click with `dry_run` at pick → `('dry_run', 'ready_to_submit', submit_clicked_at None)`, 0 submit calls.
  - P10: dry click with `auto` at pick → `dry_run` / `ready_to_submit`, 0 submits.
  - `--dry-run` → `dry_run`, 0 submits.
  - Auto twins (same `posting_key`) → first `submitted`, second `failed duplicate`, 1 submit call.
  - Paused queue → 0 rows, 0 browsers.
  - `pick_mode` gives `auto` only for `("auto", "auto", False)`; `AUTO`, `None` and `--dry-run` all give `dry_run`.

Not run: `-k apply_flow` and `-k apply_e2e` (the engineer reports 148/148 and 13/13), any real Edge (`alive()`), any live smoke.

## The ten questions

| # | Question | Result |
|---|---|---|
| 1 | Never twice | **PASS.** (a) A double click: `UNIQUE(job_id)` + `already_queued` inside `BEGIN IMMEDIATE` (`routers/apply.py:257-270`). (b) A click or retry while in flight: `live_attempt(job_id)` → `in_progress` (`apply.py:218`), plus the live-attempt guard inside `queue_add`'s INSERT (`store.py`, `queue_add`). (c) The worker dies after `queue_take`: the row is `queued`/`dry_run`; the next worker's reaper (under `RunLock`) makes it `failed(cancelled, interrupted)`, never returned automatically. An in-process cancel goes through `unstarted()` (back to the front, plus a pause). (d) The worker dies after the click: the stamp is committed before the click (`claim_click`, unchanged), the reaper gives `submitted_unconfirmed`, and `apply_duplicate` refuses it from then on. (e) A returned item: only when the store row is `failed` with `submit_clicked_at` null (`apply_flow.py` `run_queue`, M5), and every return comes with a pause. (f) Twins: `apply_duplicate` at the guards and again in `claim_click` (probe: the second twin ends `duplicate`). (g) The app is closed mid-attempt, then Resume: an orphan worker keeps `RunLock`, a new one exits 3 → `busy_elsewhere`, and the orphan stops at its loop top (`should_stop` → `app_closed`). (h) A hand-run `apply <id>`: `RunLock` serialises it. **`claim_click`, `mark_submit_clicked`, `reap_attempts`, `set_attempt_state`, `attempt_transition_allowed` and `apply/contracts.py` are not in the diff.** Residual: F5 (an untrack race of microseconds). |
| 2 | One in flight | **PASS.** Kicks come from enqueue (`/api/apply`, `/questions/retry`), Resume and the tick only. No GET kicks. `_kick` holds the runner lock, starts only when `slot_of(jobs)` is `free`, and `JobManager.start` raises `JobBusy` under its own lock. A search run or any other kind in the slot → no start. An orphan from an earlier web process stays `running` through `_recorded_process_alive`. A CLI run outside the slot → `RunLock` → exit 3 → `busy_elsewhere`. Two web processes: a dev instance with `JOBSCRAPER_DB` set is disabled (`applyqueue.py:53-62`). See F4 for dev copies started without it: `RunLock` sits under each DB's evidence root, so it does not serialise across copies. |
| 3 | Consent | **PASS.** The gate starts closed (`applyqueue.py:85`) and opens only after `queue_clear_yield` + `queue_pause_if_waiting(restarted)` succeed (`:98-113`); an exception leaves it closed and the view says `restarted`. The startup handler is registered before the tick (`api.py:284-285`). Every `queue_return` (RETURNS_ITEM, `unstarted`) is paired with a stored pause, so nothing restarts without Resume. The deferred run then auto-resume covers clicks from this session only (§6, as designed). Mode: `pick_mode` at the one place (`run_queue` → `set_mode` → `update_attempt(mode=)`, committed before `attempt()`), the row is created `dry_run` (`queue_take`), and the click is decided only by `_Run.dry_run` (`submit`, `pre_submit_scan`, the cap guard). No path skips `force_dry_run`. |
| 4 | Enqueue and untrack | **PASS with F5.** Each role gets one `BEGIN IMMEDIATE` covering the checks, `queue_add` and the `to_apply` row (`set_application_status` commits both). Refusal order: not_found, already_queued, in_progress, duplicate, cap (auto only), queue_full. The 100 bound is read inside the transaction. Untrack in flight → 409 `in_progress` (`applications.py:216`). Untrack while waiting deletes the queue row in the same commit (`delete_application`). `queue_take` drops a role with no row or one not `to_apply`. |
| 5 | Pause rules as built | **FINDING F3 (MEDIUM)** on the text markers. Model death mid-run is **PASS**: the cached `available` only gates the pre-take check, while `warm_up` runs per attempt (`apply_flow.py:1236`) and POSTs to Ollama. A dead model therefore ends the very first later item `model_unavailable` at `planning`, before Edge opens: paused and returned, nothing sent. A death during a fill → transport failure → `model_unavailable`. So the 1st item catches it, not the 2nd or 3rd. `alive()` not verified with a real Edge: F7 (LOW). |
| 6 | Web process | **PASS** (one MEDIUM, F6). Handlers and the tick are registered only with `apply_queue_worker=True`. The name collision is fixed (0481ab4, `test_web_mail` 8/8). Exit codes: only this runner's job id is judged; 0, 143 and reason `cancelled` → nothing; 3 → `busy_elsewhere`; anything else → `worker_failed`; the first pause wins. Cancel and Stop commit the pause before the signal, and `queue_take` refuses while paused (M3). `GET /apply/queue` and `GET /apply/status` only read. `CrossSiteWriteGuard` is ASGI middleware over every POST/PUT/PATCH/DELETE (`api.py:93,110-128`), and the tester pinned 9 write routes. |
| 7 | Can a test start a real worker? | **PASS.** `create_app` defaults to `apply_queue_worker=False`: no handler, no tick, and `kick()` returns at once. `cmd_web` is reached only from `test_web_mail.py:139-158` and `test_mail_d157_pins.py:144-170`, both with a temp `--config` and `uvicorn.run` stubbed, so startup handlers never run. (In `test_web_mail` the app *is* built with the queue on, because the test env has no `JOBSCRAPER_DB`; it is harmless while `uvicorn.run` stays stubbed.) `test_apply_queue_web` uses `worker=True`, a job command that raises, a fake manager swapped in, and `tick_s = 3600`. A tick on an empty temp DB: slot free → nothing waiting → returns False, no start. |
| 8 | Migration, live DB | **PASS.** v5 → v6 is a `CREATE TABLE IF NOT EXISTS` + index. `_migrate` only upserts `MAX(version)`, no row is rewritten, and an older build keeps 6 and ignores the table (its `delete_application` leaves a queue row, which `queue_take` later drops). Nothing touches `data/` at import. At start-up the live app writes only `DELETE settings apply_queue.yield`, plus the `restarted` pause when roles wait. |
| 9 | Today's bundle on the new backend | **FINDING F2 (HIGH for merge timing).** Mismatch list below. |
| 10 | Undisclosed departures, false docstrings, dead code | **F3, F6, F8.** The two pause-table overrides (a single `unanswerable_required` continues; content markers → `fill_failed`, not returned) are listed in the E2 handoff as Coordinator decisions, but design §4.1 still says otherwise: spec note. `CONTENT_FAILURE_MARKERS` has no emitter on this branch (dead until Q-121). `web/src/api.js:306,414-416` comments still promise 409 (UI lane). |

## Question 9: what today's UI does against the new backend

| # | File (web/src) | What happens | What the owner sees |
|---|---|---|---|
| a | (none) | No component calls `/api/apply/queue/resume`, `/pause`, `/stop` or `/clear`. | Every pause is permanent until U2 ships. That covers `restarted` (each app restart with roles waiting), `cancelled` (any Cancel of the apply job in Runs or the JobPill), `model_unavailable` (Ollama off at the first click), `app_closed`, `worker_failed`, `busy_elsewhere`, `daily_limit`, `bot_checks` and `repeated_*`. Clicks keep queueing behind the pause and nothing runs. When U2 lands, one Resume applies to everything clicked meanwhile; in `auto`, those are real submissions of days-old clicks, though the owner will see the list first. |
| b | `tabs/Inbox.vue:341-356` | Every 202 shows "Auto-apply started." It ignores `started`, `paused`, `disabled` and `queued[].position`. | It says "started" when the role only waits, or waits behind a pause that cannot be cleared (a). |
| c | `tabs/Inbox.vue:341` (no `emit('changed')`), `:262` | The click now writes `to_apply`, but the list isn't refreshed, so the role stays visible and selected. "Not interested" on it (dismiss) does not dequeue it. | The role still looks untouched in the Inbox. A second click gives the 422 text "already in the auto-apply queue. See it in Runs." (no queue in Runs yet). "Not interested" after the click still lets the worker apply. That is consistent with the click being consent, but the role leaving the list (design §7.1) is what makes this clear. |
| d | `tabs/Inbox.vue:320-321, 625` | Auto-apply is disabled while `status.busy` (the slot is held), and the status isn't polled. | While the worker runs, including a dry-run hold of up to 600 s, the owner cannot add roles. Same as today's Q-110 behaviour, not a regression, but it defeats the queue. |
| e | `components/QuestionsInbox.vue:151-161` | A 202 shows "Started. The applications are being filled in and sent in Edge." The 409 branch is dead. A 422 can now mean `profile_incomplete` or all refused (`already_queued` / `in_progress`), and gets the "can't go again yet" text. | A misleading "Started" when the roles only wait or are paused. |
| f | `tabs/Overview.vue:112-118` | While the worker holds the slot, `POST /jobs/run` answers 202 `{job, deferred: true}`. That is treated as a started run: toast "Run started.", and `job.value = {job, deferred, state: 'running'}`. | It says the run started when it starts only after the current application, which can be up to 10 min in a dry-run hold. |
| g | `tabs/Runs.vue:71-75` | Start is disabled while a job runs; only in the race window does the deferred body reach `track()`. It has no `id`, so `refresh()` then shows the apply job. | No message that the run is deferred. Minor. |
| h | `attempts.js:18-20` | `last_attempt.kind: "queued"`, `mode: null` → the pill reads "Auto-apply". Remove on an in-flight role gets the new 409 `in_progress`, shown as a generic error. | Cosmetic. |

None of these submits anything the owner did not click, and none breaks NF-05 or NF-06. (a) to (c) make the owner's daily Auto-apply silently stop after the first pause while the UI says "started". That matters most for the M20 gate dry runs, the next action in `handover.md`.

## Findings

### HIGH (binding)

**F1. The worker has no pins: `run_queue`, `pick_mode` and `pause_for` are unpinned (`apply_flow.py:1957-2075, 2078-2085, 2106-2146`).**
- **Scenario:** Q-121 is planned to rebase its reworked fill path over this code (design §9 merge order), and Q-113 also edits `apply_flow.py`. Picture a rebase that flips one condition. Say `set_mode` is moved below `attempt()`, `pick_mode` gets an `or`, or the `RETURNS_ITEM` gate loses `submit_clicked_at is None`. Every suite stays green, and the next queue run on the owner's `auto` install submits a role clicked in dry run, or re-queues a clicked one. The design makes I5 "pinned both ways" binding (H4, P10b). The tester's handoff says P1, P6, P8–P10b, P14, P15 and P20 were "left for the worker lane". None is on `int/Q-120`; `git grep pick_mode|run_queue|pause_for -- tests` returns nothing.
- **Fix (tester, `tests/test_apply_queue_flow.py`):**
  - `pick_mode`, all four combinations plus unknown values.
  - P10/P10b end to end (my probe above is a template: `fake_world` + `FakeBrowserFactory` + `registered` + `page_signals`, `fill="rules"`).
  - P1: the live count stays ≤ 1 at every state change.
  - P6: a launch error → returned + `browser_unavailable`; `available` False → no row.
  - P8: twins.
  - P9: tabs and hold.
  - P14: the parent is gone.
  - P15: a profile answer added mid-queue is seen by the next item.
  - P20: streaks across two `run_queue` calls; a Resume resets the window.
  - The Coordinator's three `pause_for` rows: content → `fill_failed`, not returned; transport → returned; a single fact → continues.
  - M3: a cancel while the row is `queued` → returned + paused.
  - Then gate on `-k apply_queue`, `-k apply_flow`, `-k apply_e2e` separately.

**F2. Merge order: the backend changes the meaning of today's buttons, and the current bundle cannot clear a pause (Q9 a to c).**
- **Scenario:** after the merge the owner restarts the app with one role still waiting (or presses Cancel on an apply job, or clicks while Ollama is off). The queue is paused, and no control in the bundle resumes it. Every later Auto-apply click toasts "Auto-apply started." and nothing happens. The M20 gate cannot run from the Inbox.
- **Fix (Coordinator's choice):** merge `int/Q-120` together with WP-U1 (Inbox / QuestionsInbox copy from `started`, `paused`, `disabled`; the role leaves the list) and WP-U2 (Runs panel with Resume, Pause, Stop, Clear; deferred start-run). Alternative: a stop-gap that ships a minimal Resume button and fixes the two toasts, built into the bundle in the main checkout. Merging the backend alone is safe for NF-05, NF-06 and D-200, but it is a functional regression in the daily app.

### MEDIUM

**F3. The content-failure classification is a substring match with no emitter (`apply_flow.py:2090, 2121`).**
- **Scenario A:** Q-121 words its stop as, say, "the model returned no answer the page accepts". `pause_for` misses it, and a content failure either continues (until `repeated_failures` after 3 roles) or, if the detail carries "(model unavailable)", is treated as transport. It is then *returned* and fails again after every Resume.
- **Scenario B:** an employer's validation text is copied into `reason_detail` (`validation_error` uses `res.errors`, page text) and contains "last resort". `fill_failed` pauses the queue for a per-role problem. That fails closed but isn't the right outcome.
- **Fix:** before Q-121 merges, carry the signal as data, not prose. Either use a contract constant that both sides import (e.g. `contracts.FILL_CONTENT_NOTES`, matched only against notes the flow itself writes), or use a distinct `ReasonCode` / `reason_detail` prefix. Add a pin that Q-121's real emitter is classified. Also update design §4.1 to the Coordinator's two overrides (spec note).

**F4. The dev-copy switch keys only on `JOBSCRAPER_DB` (`applyqueue.py:53-62`).**
- **Scenario:** an agent follows CLAUDE.md's "copy `data/jobscraper.db` into the worktree" but starts `JOBSCRAPER_PORT=8768 python -m jobscraper web` from the worktree without `JOBSCRAPER_DB`, or uses `--config` / `JOBSCRAPER_CONFIG` pointing at a copy. The relative `paths.db: data/jobscraper.db` resolves to the worktree copy, `apply_queue_wanted` → True, and the repository config is `apply.mode: auto`. An Auto-apply click in that UI runs a real worker on a stale never-twice history. `RunLock` sits under that copy's evidence root, so the live app's lock does not stop it, and only a held Edge profile might. This matches the design's rule (spec wins), but the rule the Coordinator set is "a development copy can never drain the queue".
- **Fix (cheap):** also turn it off when `JOBSCRAPER_PORT` is set to anything but the live port. Or, in the worker or `cmd_web`, refuse when the resolved DB path is not the main checkout's `data/jobscraper.db`, for example when it is under `.claude/worktrees/`. Add `JOBSCRAPER_APPLY_QUEUE=0` to CLAUDE.md's dev command, as H2 asked; CLAUDE.md:29 does not have it yet.

**F6. Stop cancels whatever holds the slot (`routers/apply.py:385-403`).**
- **Scenario:** the app restarted mid-attempt, so the live row shows `interrupted: true` (slot ≠ `apply`). Or a hand-run CLI `apply <id>` has a live attempt while a search run holds the slot. The owner (or U2's Stop button) posts `/queue/stop {attempt_id}`. `live.id == attempt_id`, so `jobs.cancel()` kills the **search run**, and the queue is paused `cancelled`. The attempt itself goes on (CLI) or was already dead.
- **Fix:** cancel only when `slot_of(jobs)[0] == "apply"`; otherwise 409 `already_finished` (or a `not_running` detail). U2 should not offer Stop on an `interrupted` row. Add a pin.

### LOW

- **F5.** Untrack race: `untrack` checks `live_attempt` and then calls `delete_application` in two statements, not one transaction (`applications.py:216-220`). If `queue_take` commits in between (microseconds), the role is applied to with no application row; `apply_duplicate` doesn't object to a missing row. Fix: do the check and the delete inside one `begin_immediate()` (a store method), or have `guards()` require a `to_apply` row for a taken item (`attempt_id` given).
- **F7.** `BrowserSession.alive()` (`apply/browser.py:133`) has not been run against a real Edge. If the context "close" event never fires and `pages` is empty after the owner closes Edge, `alive()` returns True. The next `new_page()` raises inside the attempt → `error` (not `browser_failed`), and after 3 roles → `repeated_errors`. Nothing is submitted, but three roles are burned. Check it on the first owner-watched dry run (close Edge during the hold, then click another role).
- **F8.** `queue_streak` counts every finished attempt in the window, CLI and batch runs included. Three CLI failures followed by one queue item can pause `repeated_failures`. That fails closed; document it or filter to queue-taken attempts.
- **F9.** `_judge` judges only when the next kick sees the worker's own record. If a deferred run started first (L4 path), the worker's exit is never judged. That's acceptable, since its own pauses are stored, but worth a line in the docstring.
- **F10.** Design §3.5's Stop says "one transaction" for the pause and the live read. The code makes two calls. It's functionally fine because the pause commits first; align the doc.

## Spec notes
- Design §4.1: replace the `unanswerable_required → fill_failed` row and the `model_unavailable` "no usable answers" row with the Coordinator's 2026-11-12 decisions as built (E2 handoff).
- Design §3.5: `POST /api/apply` takes an optional `source` (`inbox` | `applications`); a waiting role's `last_attempt` is synthetic `{kind: "queued", id: null}`; `/jobs/run` is deferred only when the runner is enabled. All three are listed in the W1 handoff; fold them into the design.
