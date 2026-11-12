# Review: Q-120 auto-apply queue design (KA-1)

Reviewer, 2026-11-12. Inputs: `docs/architecture/apply_queue_design.md` (192 lines, commit 3dfef38) and `docs/architecture/adr/0010-apply-queue.md`, checked against the code on `personal` @ 56e4c3d. Only reading; no tests run, no apply job started.

**Verdict: READY WITH CHANGES.** Four HIGH findings must change the design before WP-0: H1 (the kicker's JobManager handle), H2 (a dev instance must not drain the queue), H3 (untrack must dequeue), H4 (the `min()` mode rule). The MEDIUMs should go into the same edit. They don't block, but M1 to M3 are cheap now and expensive after W1.

The core choice holds up: a separate `apply_queue` table, one looping worker, the reaper, `claim_click` and the state machine unchanged. I found no path that submits one posting twice inside one database. The CAS at `store.py:1407-1410` inside `claim_click`'s `BEGIN IMMEDIATE` (`apply_flow.py:806-819`) is still the last line of defence, and every scenario below ends on it or before it.

## The ten questions

| # | Question | Result |
|---|---|---|
| 1 | NF-06 never twice | **PASS within one DB**, with H3, M1 and H2 (cross-DB). (a) Double-click: `UNIQUE(job_id)` plus `already_queued`. (b) Retry while in flight: `live_attempt` includes `queued`, so `in_progress`. `queue_take` deletes the row and inserts the attempt in one transaction, so a reader sees one or the other and there is no gap. (c) A crash after take leaves a `queued` row, which the next worker's reaper closes as `failed(cancelled, interrupted)`. It shows in Applications with Try again and the kicker pauses `worker_failed`. Not lost silently. (d) A crash after the click becomes `submitted_unconfirmed` at reap, and `apply_duplicate` (`store.py:1500-1506`) refuses every later enqueue. (e) A returned item can't have been clicked, provided the return reads `submit_clicked_at` from the row (M5: `AttemptResult` has no `clicked`). Every RETURNS_ITEM reason is raised before `mark_submit_clicked`. (f) Twin ids can both wait. The second one is refused at its guard or at `claim_click` because the first one's `submit_clicked_at` matches on `posting_key` (`store.py:1500-1505`). (g) Closed and reopened: the reaper settles the row and Resume never re-adds it. (h) CLI `apply <id>` while the worker runs: `RunLock` refuses it (`apply_flow.py:1788-1791`); the reverse case is L2. |
| 2 | NF-05 one in flight | **PASS.** `kick()` is serialised by the runner lock. `JobManager.start` re-checks the slot under its own lock (`jobs.py:357-360`). A search run in the slot gives `JobBusy`, which is swallowed. The pseudo-code takes `RunLock` before the loop, so a worker that loses the lock has taken nothing. `attempts_in_flight` (`store.py:1443-1450`) still guards each attempt. L2 covers the respawn loop when the lock is held elsewhere. |
| 3 | D-200 consent | **FINDING: H4, H3, M2, H2.** These are fine: returned items (they need Resume), the deferred run (a yield, not a pause, and clicked in the same session), `clear`, retry (a click), and a dry-run click never upgrading. The reverse case (an auto click, then the owner switches to dry run) is correct under §2 I5 but contradicted by §3.1's `min()` (H4). An untracked role is still applied to (H3). A start-up pause that fails to write opens the gate (M2). |
| 4 | `apply_queue` vs `to_apply` | **FINDING: H3.** A row that is applied or rejected is refused as `duplicate`, which is correct and fail-closed. An existing `to_apply` row is allowed and correct. A status changed while the role waits is refused at the guard (correct; the copy says "applied", LOW). Untrack while the role waits is H3. Remove and Clear leave `to_apply`, which matches the copy "They stay in Applications under To apply" (§7.1). |
| 5 | Pause rules | **FINDING: M4, M5.** "Which cap fired" isn't exposed. `r.clicked` doesn't exist. The "in a row" history is per worker process and resets whenever the queue drains. Identical per-role endings (today's `unanswerable_required`) burn through the queue. |
| 6 | Worker vs web | **FINDING: M3, L2, L3.** The parent-PID stop is sound. Exit 0 on a pause makes the JobManager record read "succeeded" (`jobs.py:460`); that's acceptable because the pause banner carries the reason (record it, L7). Cancel pauses first, then cancels, but the worker can take the next item in between (M3). The "unjudged last job" rule misfires on stale records (L3). The 5 s tick runs in every `cmd_web`, including dev instances (H2). |
| 7 | Dry run, tabs | **PASS.** Each attempt opens its own tab (`apply_flow.py:1081,1208`) and Submit acts on that attempt's `page` object (`:1266`), never on "the active tab". A held dry-run tab is never addressed again. The pre-Submit scan and `claim_click` are unchanged. A `ready_to_submit` page is kept open by the existing rule (`:1007`). |
| 8 | Search runs and other jobs | **PASS** with L4 and L5. §5 says a yield ends the hold, so the run doesn't deadlock waiting on the worker. Profile, titles and companies get 409 for up to 10 minutes while the worker sits idle in the hold (L5). |
| 9 | API and compatibility | **FINDING: H1, M1, M6.** `/apply/status` is additive and stays compatible: ModeChip, SetupChecklist and `ApplySettings.vue:71,344` read `mode`, `missing` and `busy`, whose meanings are unchanged. The "no 409" change has callers outside the lanes (M6). `GET /api/apply/queue` with a reaper and a kick is unsafe for the GET sweep and has no web precedent (M1). |
| 10 | Layering, migration, build plan | **PASS on layering and migration.** `SCHEMA_VERSION = 5` (`store.py:27`) and `CONTRACT_VERSION = 5` (`contracts.py:23`) are confirmed. `_migrate`'s upsert (`store.py:494-499`) fits. Web may import foundation plus `apply.contracts` (`test_layering.py:79`). **FINDING on the plan:** H1 (test harness). The pins for H3, H4 (reverse), M2 and M3 are missing. Lane conflicts: WP-E2 `apply_flow.py` against Q-121 (D-208, queued) and Q-113. Q-118 §9 asks to change U3's file list to `ApplicationRow.vue`. |

## Findings

### HIGH (binding)

**H1. The kicker captures the JobManager at construction, so tests would spawn a real `apply queue` against the live config.**
- §3.4 builds `ApplyQueueRunner(jobs, store_factory)` "on the MailSyncRunner pattern", and that pattern captures `app.state.jobs` when `create_app` runs (`api.py:262-263`).
- The existing web tests replace the manager after `create_app`: `test_q114_caps.py:144-146`, `test_web_questions.py:118-120`, `test_web_apply_settings.py:85-87`. `routers` see the fake through `get_jobs` (`deps.py:26-28`), but a runner built at construction would still hold the real `JobManager` with `cli_command(None)`.
- **Scenario:** the tester's changed pin for `POST /api/apply` enqueues a role in the temp DB. `kick()` sees one waiting item and runs the real `jobs.start("apply", {"queue": True})`, which Popens `python -m jobscraper apply queue`. With no `--config`, the child resolves `config/config.yaml` (`jobs.py:85-90`): the live DB with `mode: auto`. If the live queue has waiting, unpaused items (for example, waiting behind a live search run), that child applies to them outside the live app's slot. That breaks NF-05 and causes a real submission started by a test run. §8's "no test starts a real apply job" can't hold with this construction.
- **Change:** the runner resolves the manager at kick time (`ApplyQueueRunner(get_jobs=lambda: app.state.jobs, …)`), and the timer stays off in tests. Add a pin: with the real manager left in place and a waiting item in the temp DB, a POST never Popens. A stub `job_command` that fails the test if it's called would do.

**H2. A dev instance on a copied DB can drain the queue in `auto` and submit again what the live app already sent.**
- `cmd_web` always passes `apply_queue_timer=True` (§3.4).
- `RunLock` and the NF-06 history are per database: `evidence_root = db_path.parent / "apply"` (`apply_flow.py:151-153`). The Edge profile is shared (`config.py:115`), and the repository config is `mode: auto`.
- **Scenario:** a Q-118 or U2 tester smoke-tests `ApplyQueuePanel` on 8768 with a DB copied this morning and presses Resume, or clicks Auto-apply. The dev worker submits a posting that the live DB has submitted since the copy was taken; the copy's `apply_duplicate` can't know. Even in dry run it may create Workday accounts. The design's own smoke step (§9) runs the GET on the dev instance, and that GET kicks.
- **Change:** add `JOBSCRAPER_APPLY_QUEUE=0`, read like `JOBSCRAPER_MAIL_SYNC` (`api.py:241-243`, `cli.py:288`). When it's 0, no tick runs, `kick()` never starts a worker (it can still enqueue for UI tests), and `/apply/queue` reports a `dev_disabled` pause. Add it to CLAUDE.md's dev command and to §9's smoke step.

**H3. Untracking a waiting role doesn't dequeue it, so the worker applies to a role the owner removed.**
- `DELETE /api/applications/{job_id}` (`applications.py:182-193`, `store.delete_application` at `store.py:1104-1116`) deletes only the application and history rows.
- With no application row, `apply_duplicate` returns None (`store.py:1484-1486`) and the guards pass.
- **Scenario:** the owner clicks Auto-apply on a role (position 4), changes their mind, and removes it in Applications. Q-118 LB puts Remove in the row's ⋯ menu. The role goes back to the Inbox, and minutes later it's submitted in `auto`. The Inbox Undo toast (DELETE plus untrack) is safe; Applications' Remove isn't.
- **Change:** `delete_application` also deletes the `apply_queue` row in the same transaction (it's the one SQL module). For a role in flight, the router answers that it's in progress and points to Stop. As defence in depth, `queue_take` drops an item whose application row is missing or isn't `to_apply`, with a log line, and takes the next. Pin: untrack while waiting leaves nothing queued and no attempt.

**H4. §3.1's `mode=min(item.mode, mode_cap)` is wrong as written.**
- In Python, `min("dry_run", "auto") == "auto"`, so a literal implementation turns every mix of modes into `auto`. A dry-run click with auto at pick would submit, and so would an auto click after the owner switches to dry run.
- §2 I5 states the right rule, so the document contradicts itself on the one decision that separates "fill" from "submit". P10 pins only one direction.
- **Change:** replace `min()` with "`auto` only if the item's mode, the cap and `force_dry_run` all allow it: both values exactly `"auto"` and no `--dry-run`; anything else, including an unknown value, means `dry_run`". Add P10b: an auto click, then the mode set to `dry_run` before pick, gives `ready_to_submit` and `submit_clicked_at` stays null.

### MEDIUM

**M1. The design adds a reaper on a polled GET, though no web reaper exists and the lock rule forbids one.**
- §3.5 says "Reaps first … (same rule as `/apply/attempts`)" and §10 calls it "an existing gap". It isn't existing behaviour: `reap_attempts` has one caller (`apply_flow.py:1794`, under `RunLock`), and there's no `/api/apply/attempts` route. Applications uses `/applications/{id}/attempts`, which doesn't reap (`applications.py:144-150`). `apply_design.md:163,1504` specified one, but the later `RunLock` rule says "only the lock holder may reap" (`apply_flow.py:521-525`).
- **Scenario:** the Runs panel polls every 3 s. A CLI `apply` run, or a worker the JobManager has lost track of (`process_identity` unreadable, so `_recorded_process_alive` is False at `jobs.py:445-449`), has its live row marked `failed(cancelled)` while it's still filling. The role becomes re-queueable while its tab is open. The CAS still prevents a second click, so this is audit corruption, not a double send.
- The GET also kicks, so it can Popen. The Q-104 sweep (`test_connections.py:698-764`) would call it with the real JobManager.
- **Change:** no writes on this GET. Show a live row as "interrupted" (read-only) when the slot isn't `apply`, and let the worker reap at start. Drop the kick from the GET (the tick and the POSTs cover it). List the route in `SWEEP_GET_ALLOWLIST` as side-effect free.

**M2. The start-up pause fails open, and its order relative to the timer isn't stated.**
- The hook writes through a store at startup, against the principle "nothing is opened at startup" (`api.py:65`).
- **Scenario:** the DB is locked by a surviving worker, or is unreadable. The hook's error is swallowed (or it isn't, and the app won't serve `/`). Then the tick starts the worker on the previous session's items with no fresh click.
- **Change:** the runner keeps an in-memory `restart_gate = True`. `kick()` starts no worker until the pause row is written or the owner resumes. Register the pause before `start_timer`. Pin: a failing store at startup leads to no start.

**M3. Cancel and Pause race with `queue_take`.**
- §3.5 has the cancel route pause the queue, then call `jobs.cancel()`. A worker that has just passed `queue_pause_state()` takes the next item, and CTRL_BREAK then ends a role the owner didn't stop as `failed(cancelled)`. The owner's "Pause queue" has the same window.
- **Change:** `queue_take` reads the pause and yield flags inside its `BEGIN IMMEDIATE` and returns None when either is set. An attempt interrupted while still `queued` (never started) goes back to the front.

**M4. The pause history is per process, and repeated identical failures don't pause.**
- (a) In auto the worker exits whenever the queue drains (§5: it never holds). With the owner adding roles one at a time, "2nd CAPTCHA in a row" and "3rd error in a row" never accumulate.
- (b) Every role ending the same way: `unanswerable_required` (Q-119's first live attempt today), `mail_not_set_up`, `login`, `page_unrecognised`. Each one continues, so a queue of 20 turns into 20 failed attempts, possibly creating Workday accounts along the way. With D-208 (always answer) the remaining stop signals become the main safety net.
- **Change:** compute "in a row" from the database (the last N finished queue attempts, whatever the worker process). Add "3 in a row with the same per-role reason (except duplicate, closed and the per-employer cap)", which pauses with a new reason `repeated_failures`, without returning the item.

**M5. "The flow knows which cap fired" and `r.clicked` aren't true of the code.**
- Both caps raise `CAP_REACHED` and differ only in the detail text (`apply_flow.py:788-798`); `claim_click` raises the same thing (`:810`).
- If the per-employer cap is read as the daily one, the head item is returned and every Resume pauses again: a stuck queue. If the daily cap is read as the per-employer one, the queue burns through.
- `AttemptResult` has no `clicked` field (`contracts.py:1047-1058`).
- **Change:** `cap_refusal` tags which cap fired (an internal attribute; no contract change). `pause_for` returns an item only when the row's state is `failed` and `submit_clicked_at` is null, both read from the store.

**M6. The UI callers of the changed responses are outside the lanes.**
- `QuestionsInbox.vue:150-161`: the retry toast says "Started … being filled in and sent in Edge", and there's 409 copy. With the queue the item may only be queued or paused.
- `Overview.vue:110-121`: Start run gets a deferred 202 that carries the apply job's view. It shows "Run started" and tracks the apply job.
- `Runs.vue:77`: Start run (U2 lists only the mount and the label).
- **Change:** add these to the U1/U2 file lists and their vitest files.

### LOW

- **L1.** `begin_item()` doesn't refresh `self.acfg`, but caps, timeouts, `fill` and `compose` all read `self.acfg` (`apply_flow.py:792-794, 954-962, 603-604`). State `self.acfg = apply_cfg_fn()` per item. Note that `headed` keeps its launch value until the session reopens.
- **L2.** A worker refused by `RunLock` exits 0, so the tick respawns it every 5 s for the whole CLI run. `keep_logs=50` (`jobs.py:328`) then prunes the owner's search-run logs. Use a distinct exit code and back off (or pause with `busy_elsewhere`).
- **L3.** The "unjudged last finished apply" rule also judges a record from before the upgrade (a batch `apply` exits 1 whenever an attempt fails, `cli.py:1261`) and `_finish(None)` after a restart (`jobs.py:437-438`). Either sets `worker_failed` and may overwrite `restarted` or `app_closed`. Judge only jobs this runner started, and never overwrite an existing pause.
- **L4.** If the worker had already exited when the run was requested, the yield flag stays set after the kicker starts the pending run, and the next worker exits at once. The kicker should clear the yield flag when it starts the run.
- **L5.** While the worker idles in the dry-run hold, only a search run can end it. Have any `POST /api/jobs/*` set the yield flag, or state the 10-minute 409 in the copy.
- **L6.** `queue_return` against `UNIQUE(job_id)` has no conflict rule (the role may have been clicked again in between). §3.1 says "all commit" but §3.5 says "one commit". Put `queue_add` and `set_application_status` in one transaction.
- **L7. ADR-0010:** the rejected options are described fairly. The consequences omit the always-on timer in `cmd_web` (H2), the GET with side effects (M1), "succeeded" on a paused worker, the test-harness exposure (H1), and that the queue makes unattended `auto` sequences possible, which raises the stakes of D-208.

## Spec notes
- Q-118 §9 (56e4c3d) asks AQ §9 to move U3 from `Applications.vue` to `ApplicationRow.vue` and to merge LB/LC before U2/U3. Adopt it.
- Q-121 (D-208) will rework `apply_flow.py`, which is also WP-E2's file. Sequence the two, or confine E2 to new functions (`run_queue`, `begin_item`, `set_mode`) to keep conflicts small. Q-119's lane touches only `apply/page.py` so far.
