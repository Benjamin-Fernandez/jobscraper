# Auto-apply queue design (KA-1, D-205)

Status: revised 2026-11-12 after the independent review `docs/reviews/Q-120-apply-queue-design.md` (H1–H4, M1–M6 folded in; L1–L7 resolved or accepted in §10). ADR: `adr/0010-apply-queue.md`. Extends `apply_design.md` §3, §12, §14; changes none of its safety rules. The queue is deterministic: no model call decides anything here. Aligned with D-208 / `llm_first_fill_design.md` (Q-121).

## 1. Goals, non-goals, requirement map

**Goals.** Clicking Auto-apply never fails because something is running: the role joins a durable queue and leaves the Inbox. One background worker applies to queued roles one at a time while the owner keeps clicking. Runs shows now / next / paused / recently finished. Per-role failures don't stop the queue; system failures and repeated identical failures pause it with a reason.
**Non-goals.** Reordering beyond "returned items go to the front"; scheduling; more than one attempt at a time; a queue for other job kinds; Inbox multi-select (the API takes up to 20 ids).

| Requirement | Where |
|---|---|
| F-30 queue one attempt per role, one at a time, refuse with reasons, caps | §2, §3.2, §3.5 `POST /api/apply`, §4 |
| F-37 submit + confirm; dry run leaves the form open | §3.2 (attempt flow unchanged), §5 |
| F-38 fail properly, reason in the role's panel | §4.1, §7 Applications |
| NF-05 one attempt in flight, human pace | §2 I1, §3.2, §3.4, §6 |
| NF-06 never submitted twice | §2 I2, §4.2 (reaper, `claim_click` unchanged), §3.4 H2 switch |
| D-200 only roles the owner clicked | §2 I4, §3.4 restart gate, §3.5 untrack |
| D-203 auto = click fills and submits; dry_run never submits | §2 I5 |
| D-204 caps (0 = no limit, 10 per employer) | §4.1 (re-checked at pick; daily limit pauses) |
| D-205 queue + background worker + Runs section | the whole document |
| D-208 always answer; `unanswerable_required` = system failure | §4.1 |

## 2. Data model (SCHEMA_VERSION 5 → 6, additive)

A **separate `apply_queue` table** (ADR-0010): waiting items are not `apply_attempts` rows, so the reaper, the state machine and every NF-06 path stay as they are.
```sql
CREATE TABLE IF NOT EXISTS apply_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,           -- I2: a job waits at most once
    company_id INTEGER,                    -- jobs.company_id at the click
    pos INTEGER NOT NULL,                  -- ORDER BY pos, id; new = MAX(pos)+1, returned = MIN(pos)-1
    mode TEXT NOT NULL CHECK (mode IN ('auto', 'dry_run')),   -- effective mode at the click (I5)
    source TEXT NOT NULL CHECK (source IN ('inbox', 'retry', 'applications', 'returned')),
    enqueued_at TEXT NOT NULL,
    note TEXT                              -- 'returned: <pause reason>' for an item put back by the worker
);
CREATE INDEX IF NOT EXISTS idx_apply_queue_pos ON apply_queue(pos, id);
```
Migration: the table comes from `SCHEMA`'s `CREATE TABLE IF NOT EXISTS`; `_migrate` only bumps `meta.schema_version` (existing upsert). No existing row changes; an older build ignores the table.
Queue state in `settings` (prefix `apply_queue.`, outside `ApplyConfig.with_settings`'s `apply.` keys): `paused` (a `QueuePause` value or absent), `paused_detail`, `paused_at`, `resumed_at` (the streak window, §4.1), `yield` (`1` while a search run waits its turn, §6).
**Invariants.** I1 at most one attempt in flight: the JobManager slot, `RunLock`, the `attempts_in_flight` guard, one worker process. I2 a job is never waiting twice (UNIQUE), never waiting while it has a live attempt (enqueue check), never in two places (`queue_take` deletes the row and creates the attempt in one transaction). I3 FIFO by `(pos, id)`; only a worker return goes to the front. I4 rows are added only by an owner click (`POST /api/apply`, `POST /api/questions/retry`) or returned unchanged by the worker before any click; a role whose application row is gone or no longer `to_apply` is never taken (H3). **I5 (H4) the attempt mode is `auto` only when the item's `mode` is exactly `"auto"` AND the effective mode at pick is exactly `"auto"` AND no `--dry-run`; anything else, including an unknown or empty value, is `dry_run`.** Never a string `min`/`max`; one helper `pick_mode(item_mode, effective_mode, force_dry_run) -> str` in `apply_flow`, pinned both ways.

## 3. Components

### 3.1 Store (`store.py`, the only SQL). "No commit" methods are committed by the caller.
- `queue_add(job_id, company_id, mode, source, now) -> Optional[int]` (no commit): new 1-based position, or None if already waiting (`ON CONFLICT(job_id) DO NOTHING`).
- `queue_return(job_id, company_id, mode, note, now) -> None` (commits): put back at the front (`pos = MIN(pos)-1`, source `returned`); `ON CONFLICT(job_id) DO NOTHING` (a fresh click in between wins, L6).
- `queue_items() -> list[dict]` (`{job_id, company, role, mode, position, enqueued_at, source, note}` in order); `queue_positions() -> dict[job_id, int]`; `queue_remove(job_id) -> bool`; `queue_clear() -> int` (commit).
- `queue_take(now) -> tuple[Optional[dict], list[str]]` (commits): in one `BEGIN IMMEDIATE`: (1) **if `apply_queue.paused` or `apply_queue.yield` is set, return (None, [])** (M3); (2) walk the head: an item whose `applications` row is missing or not `to_apply` is deleted and its job id added to the dropped list (H3), the next one is tried; (3) delete the head and `create_attempt(job_id, company_id, mode="dry_run", now)`. The row starts fail-safe; the worker sets the `pick_mode` result with `update_attempt(mode=…)` before the row leaves `queued`, and only `_Run.dry_run` (set from the same value) decides the click. Returns `({job_id, attempt_id, item_mode, source}, dropped)`.
- `delete_application(job_id)` (existing, H3): also `DELETE FROM apply_queue WHERE job_id = ?` in the same transaction.
- `queue_pause(reason, detail, now) -> bool` (commits): writes only if not already paused (first reason wins, L3). `queue_resume(now)` (clears the pause, sets `resumed_at`). `queue_pause_state() -> Optional[{reason, detail, since}]`. `queue_pause_if_waiting(reason, now) -> bool`.
- `queue_request_yield()`, `queue_take_yield() -> bool` (read and clear), `queue_clear_yield()`.
- `live_attempt(job_id=None) -> Optional[dict]`: newest non-terminal attempt (incl. `queued`) with company and role.
- `recent_attempts(limit=10) -> list[dict]`; `queue_streak(since, limit=3) -> list[dict]`: the newest finished attempts started at or after `since`, fields `state, reason_code, reason_detail, submit_clicked_at` (M4).

### 3.2 Worker (`apply_flow.py`, orchestrator)
New public `run_queue(cfg, store, *, backend, apply_cfg_fn, http=None, browser_factory=None, say=print, evidence_dir=None, now=None, should_stop=None, force_dry_run=False) -> QueueOutcome` (`QueueOutcome` = results + `lock_refused: bool`, internal to the flow). `_Run.run_queue()`:
```
RunLock, else return lock_refused (cli exits 3) → reap_attempts (THE reaper for the web path, M1) → purge_fill_cache
loop:
  should_stop() (web parent gone)          → queue_pause(app_closed); break
  queue_take_yield()                       → log "a search run goes first"; break      (no pause)
  self.acfg = apply_cfg_fn(); begin_item()  (L1: caps, timeouts, fill, compose per item)
  profile missing                          → queue_pause(profile_incomplete); break     (item untouched)
  acfg.fill == "llm" and not backend.available → queue_pause(model_unavailable); break
  item, dropped = queue_take(utcnow()); log one line per dropped id ("no longer To apply; skipped")
  none → dry-run hold (§5; may loop back on a new item), else break
  mode = pick_mode(item.item_mode, acfg.mode, force_dry_run); set_mode(mode); update_attempt(mode=mode)
  r = attempt(item.job_id, attempt_id=item.attempt_id)
  row = store.attempt(r.attempt_id)        (M5: state and submit_clicked_at come from the store)
  p = pause_for(row, self.last_cap, store.queue_streak(window_start))   (§4.1)
  if p: if p.returns and row.state == "failed" and row.submit_clicked_at is None: queue_return(...)
        queue_pause(p); break
finally: close the session; release the lock
```
`window_start` = the later of `apply_queue.resumed_at` and now − 24 h.
Changes to `_Run`, confined to new methods plus three small edits:
- `attempt(job_id, *, attempt_id=None)` uses the given row. Its `BaseException` handler gains one case: a row still `queued` (never started) is failed `cancelled` "interrupted before start" and returned to the front (M3).
- `cap_refusal` sets `self.last_cap = "daily" | "employer"` (reset per item) (M5). This is internal; no contract change.
- `browser()` reopens a session the owner closed (`session.alive()`). A launch error sets `self.browser_failed` with the detail "the JobScraper Edge profile is in use" (`_names_profile_dir`) or "Edge could not start (<Type>)".

New methods:
- `begin_item()` resets the profile, `profile_error`, log redaction values, `rules`, `_resume_text`, `_resume_entries`, `_aliases`, `reopened`, `compose_files`, `compose_meta`, `last_cap`, `browser_failed` and `seen` (I2 replaces the batch-duplicate check).
- `set_mode(mode)`, `pick_mode`, `pause_for`.

`run()` (the CLI batch) is unchanged. The guards, `claim_click`, the reaper and the state machine are unchanged. `browser.py`: `hold(seconds) -> bool` (True while the window is open) and `alive() -> bool`.

### 3.3 CLI (`cli.py`)
`apply queue [--parent-pid N] [--dry-run]`: `queue` becomes a reserved first word (like `show`, `open-profile`). It sets the backend `num_ctx` as `cmd_apply` does and calls `run_queue` with `apply_cfg_fn=lambda: _effective_apply(cfg, store)`. `should_stop` = the `--parent-pid` process, with the identity recorded at start, is gone (lazy `web.jobs.pid_alive`/`process_identity`; cli is exempt from layering). It prints one line per item and `queue: N finished, M waiting, paused: <reason>|no`. **Exit codes: 0 on every orderly end** (drained, paused, yielded, item failures included); 3 = `RunLock` held by another apply run (L2); 2 bad arguments; 143 cancelled; anything else is a crash. `apply <ids>` is unchanged; the web no longer uses it. `cmd_web` reads `apply_queue_wanted(env)` (§3.4, H2).

### 3.4 Web process: `web/jobs.py` and a new `web/applyqueue.py`
`jobs.py`: `apply` with `opts={"queue": True}` → argv `apply queue --parent-pid <os.getpid()>`; `queue` joins the reserved ids. The slot rule is unchanged: the worker is an ordinary `apply` job, so Cancel, the log, the JobPill and `current()` work as now.

`applyqueue.py`: `ApplyQueueRunner(app_state, *, enabled: bool)`. It reads `app_state.jobs` and `app_state.store_factory` **at every kick, never at construction (H1)**, so a fake swapped in after `create_app` is the only manager it can reach. It imports only the store, `web.jobs` and `apply.contracts`, and never Popens.

`kick() -> bool`, under a lock: (1) not `enabled` or `restart_gate` closed → return; (2) slot busy → return; (3) the last finished job is one this runner started (its recorded id, L3): exit 3 → `queue_pause(busy_elsewhere)`, any other exit not in {0, 143} → `queue_pause(worker_failed)`; (4) `pending_run` set → `queue_clear_yield()` (L4), `jobs.start("run", pending_run)`, clear it, return; (5) paused or nothing waiting → return; (6) `jobs.start("apply", {"queue": True})`, record the job id; `JobBusy` returns quietly. Kicks come from the write routes only: enqueue, retry, resume, and the end of a deferred run. Plus a daemon tick every 5 s while `enabled` (the `MailSyncRunner` pattern). **No GET kicks (M1).**

**Switches (H1, H2).** `create_app(apply_queue_worker: bool = False)`: tests and the default never start a worker. `cmd_web` passes `apply_queue_wanted(os.environ)`, which follows the `mail_timer_wanted` rule: `JOBSCRAPER_APPLY_QUEUE=1` on, `=0` off; unset → on, unless `JOBSCRAPER_DB` is set (a dev instance on a copied DB). The reason: a copied DB has its own never-twice history while the Edge profile is shared. When disabled there is no tick and no start. Enqueue still records (UI work), `GET /api/apply/queue` reports `paused: {reason: "disabled"}` (view only, never stored), and Resume answers 409 `disabled`.

**Start-up gate (M2).** The runner is built with `restart_gate = True`, held in memory. The startup handler (registered **before** `start_timer`) runs `queue_clear_yield()` and `queue_pause_if_waiting(restarted)`. Only when that write succeeded does the gate open (the stored pause now protects). If it fails, the gate stays closed for this process: no worker starts, and the GET view reports `restarted`. A successful Resume (its write committed) opens the gate.

### 3.5 Web API (`routers/apply.py` unless noted)
| Method, path | Request | Response |
|---|---|---|
| `POST /api/apply` (changed) | `{job_ids:[1..20]}` | **202** `{queued:[{job_id, position}], accepted:[job_id] (kept for compatibility), refused:[{job_id, reason_code, text, hint}], mode, paused: bool, started: bool, disabled: bool, job: JobView or null}`. 422 `profile_incomplete` and 422 `refused` (all refused) as today. **No 409.** |
| `GET /api/apply/queue` (new; **no side effects**, M1) | | 200 `{paused: null or {reason, text, hint, since}, now: null or {attempt_id, job_id, company, role, mode, state, started_at, interrupted: bool}, slot: "free" or "apply" or "run" or "other", run_pending: bool, waiting:[{job_id, company, role, mode, position, enqueued_at, source, note}], recent:[{attempt_id, job_id, company, role, mode, kind, text, finished_at}]}`. `interrupted` = a live row while the slot isn't `apply` (it is closed by the next worker's reaper). Goes on the GET sweep allowlist. |
| `DELETE /api/apply/queue/{job_id}` | | 204; 404 `{detail:"not_waiting"}` |
| `POST /api/apply/queue/pause` | | 200 view (reason `owner`; idempotent) |
| `POST /api/apply/queue/stop` (new, M3) | `{attempt_id}` | One transaction: `queue_pause(cancelled)` and read `live_attempt()`. If it's still `attempt_id`, `jobs.cancel()` → 200 view; else 409 `{detail:"already_finished"}` (the queue is paused anyway and nothing else is cancelled). |
| `POST /api/apply/queue/resume` | | 200 view, then kick; 422 `{detail:"profile_incomplete", missing}`; 409 `{detail:"disabled"}` (H2) |
| `POST /api/apply/queue/clear` | | 200 `{removed:n, queue: view}` (waiting rows only) |
| `GET /api/apply/status` (additive) | | `{mode, missing, busy, queue:{waiting:int, applying:bool, paused: reason or null}}`. `mode`/`missing`/`busy` keep their meaning (`busy` = a job holds the slot). The Inbox stops reading `busy`; ModeChip, SetupChecklist and ApplySettings are unaffected. |
| `POST /api/questions/retry` (changed, `routers/questions.py`) | as today | 202 `{queued, refused, job, started, disabled}` via the enqueue helper (source `retry`); 422 `not_ready` as today; no 409 |
| `POST /api/jobs/run` (changed, `routers/jobs.py`) | as today | `slot == "apply"`: 202 `{job:<apply view>, deferred:true}`; sets `pending_run` + `queue_request_yield()`. Other busy kinds: 409 as today |
| `POST /api/jobs/cancel` (changed) | | running kind `apply`: `queue_pause(cancelled)` committed **before** the cancel (the take honours it, M3); response unchanged |
| `DELETE /api/applications/{job_id}` (changed, `routers/applications.py`, H3) | | `live_attempt(job_id)` → 409 `{detail:"in_progress", text, hint}` and nothing is deleted. Otherwise as today, with the queue row deleted in the same transaction. |
| `GET /api/applications` (additive) | | each row gains `queue: null or {position}`; `last_attempt.kind` gains `queued` |

**H3 decision.** Removing a role that is being applied to right now is **refused** (not cancelled). A cancel may land after the Submit click, and the attempt's audit should keep its application row. The copy points to Stop in Runs.
**Enqueue helper** (shared with questions; one transaction, L6): profile check (422); per id: unknown → `not_found`, waiting → `already_queued`, `live_attempt(job_id)` → `in_progress`, `apply_duplicate` → `duplicate`, caps when the mode is `auto` → `cap_reached`, 100 waiting → `queue_full`; then `queue_add(…, mode=effective mode, source)` + `set_application_status(job_id, "to_apply")` when the role has no row (the owner's click); one commit, then `kick()`. The refusal codes are API-only (`QUEUE_REFUSAL_TEXTS`). **Layering:** web imports only foundation + `apply.contracts`; SQL only in `store.py`; `backend.available` is called by the worker, never by web.

### 3.6 Contract (additive; `apply/contracts.py`, CONTRACT_VERSION 5 → 6; the architect writes it as WP-0)
`class QueuePause(str, Enum)`: `owner, restarted, app_closed, cancelled, profile_incomplete, model_unavailable, browser_unavailable, fill_failed, bot_checks, repeated_errors, repeated_failures, daily_limit, worker_failed, busy_elsewhere, disabled` (`disabled` is view-only, never stored). `QUEUE_PAUSE_TEXTS: dict[QueuePause, ReasonText]` (§7.2). `RETURNS_ITEM = {profile_incomplete, model_unavailable, browser_unavailable, daily_limit}`. `QUEUE_REFUSAL_TEXTS: dict[str, ReasonText]` for `not_found, already_queued, in_progress, queue_full, disabled`. `AttemptResult` is **not** changed: `clicked` and the state come from the store row, and the cap from `_Run.last_cap` (M5). Purely additive, so ADR-0010 covers it.

## 4. Failure handling

### 4.1 After each item (`pause_for(row, last_cap, streak)`, deterministic; checked top to bottom)
| Outcome (row from the store) | Queue | Item |
|---|---|---|
| `profile_incomplete` (missed by the pre-check, e.g. the resume vanished) | pause `profile_incomplete` | returned |
| `model_unavailable`, or a detail with "model unavailable" / "no usable answers" (Q-121 A6) | pause `model_unavailable` | returned |
| `browser_failed` set | pause `browser_unavailable` | returned |
| `cap_reached` with `last_cap == "daily"` | pause `daily_limit` | returned |
| `unanswerable_required` (under D-208 `always` only a system failure; under the old policy it also waits in Questions) | pause `fill_failed` | not returned (Applications "Needs your input"; retry = a click) |
| streak: the last 2 both `captcha`/`bot_challenge` (incl. the notes "captcha/bot check after submit") | pause `bot_checks` | not returned |
| streak: the last 3 `error` | pause `repeated_errors` | not returned |
| streak: the last 3 `failed` with the **same** reason, except `duplicate`, `posting_closed`, `cap_reached` (employer), `cancelled`, `unsupported_ats` (these end before any form or account) | pause `repeated_failures` (detail = the reason text) | not returned |
| Anything else: `submitted`, `ready_to_submit`, `submitted_unconfirmed`, `duplicate`, `posting_closed`, `unsupported_ats`, `validation_error`, `page_unrecognised`, `login_failed`, mail reasons, `document_missing` (Q-121), the employer cap, `cancelled` | continues | stays in Applications with Try again |
An item is returned only when the row is `failed` with `submit_clicked_at` null (NF-06, read from the store). The streak comes from the DB (`queue_streak`), so it survives worker restarts. It starts at the later of the last Resume and 24 h ago, so an old CAPTCHA doesn't count. The pre-checks (profile, `backend.available`) pause **before** a take, which leaves no failed row.

### 4.2 Restart, crash, cancel, untrack
- **Restart:** app closed with roles waiting → the next launch pauses `restarted` (fail-closed gate, §3.4); items kept.
- **Closed mid-attempt:** the worker usually dies with the console; if it survives, it finishes the current role, then `app_closed`. The next worker's reaper (at its start, under `RunLock`; the web never reaps) closes the row: clicked → `submitted_unconfirmed` "interrupted after submit" (the owner confirms; never resubmitted); not clicked → `failed(cancelled, interrupted)` with Try again. Never returned automatically.
- **Crash and lock:** exit not 0/3/143 → `worker_failed`, no restart loop; exit 3 (a CLI run holds the lock) → `busy_elsewhere`.
- **Cancel and Stop** commit the pause before the signal, and `queue_take` refuses inside its transaction while paused, so a cancel can only hit the role in flight when the pause committed; Stop also checks that role's id (§3.5).
- **Untrack:** while waiting, the queue row is deleted; in flight, refused (H3); `queue_take` skips roles no longer `to_apply`. **Retry** (`/questions/retry`, Applications "Try again") enqueues: a fresh click.

## 5. Dry-run behaviour
A filled tab (`ready_to_submit`) stays open and the worker moves on in a new tab. At most `DRY_RUN_TABS = 3` are kept; a 4th closes the oldest (log line). With the queue empty and a filled tab open, the worker holds for up to `dry_run_hold_s` (600) in 5 s slices. It stops early when the window is closed, the queue is paused, a yield is requested, or an item is waiting (it continues in the same session). Auto mode closes each tab as today and never holds.

## 6. Concurrency with search runs and other jobs
The worker and every other job kind share the single slot, so Edge, the GPU and database writers never overlap. While another job runs, items wait; Runs shows "Waiting for the search run to finish", and the tick starts the worker when the slot frees. **Start run while the worker is active:** the label is "Run after this application". The worker finishes the current role and yields (no pause), the kicker clears the yield and starts the run, and the queue resumes by itself afterwards. Profile, titles, companies, tailor and mail test still get 409 while the worker runs, including during a dry-run hold of up to 10 minutes. Pause ends the hold (L5, accepted, §10). The mail sync already defers the model while the slot is busy.

## 7. UI (what and copy; styling from Q-118 §1/§4)
**7.1 Surfaces**
- **Inbox** (`/api/apply/status` on mount and after each click). Auto-apply is disabled only when `missing` is non-empty or the status is unknown, never by `busy`. Hints: auto "Adds this role to the auto-apply queue. JobScraper fills the form and submits it."; dry "Adds this role to the auto-apply queue. Dry run: the form is filled, never submitted." The click takes the role out of the list (it becomes To apply). Toasts: "Applying now." (position 1 and `started`) · "Added to the auto-apply queue: {ordinal} in line." · paused: "Added to the auto-apply queue. The queue is paused; resume it in Runs." · `disabled`: "Added to the queue. Auto-apply is switched off in this copy of JobScraper, so nothing will be sent from here." Toast actions: "See the queue" (#/runs) and "Undo". Undo = `DELETE /api/applications/{id}` when the role had no status before, else `DELETE /api/apply/queue/{id}`; on 409: "It has already started; stop it in Runs."
- **QuestionsInbox** (retry): "Added {n} to the auto-apply queue." plus the paused/disabled variants above. The 409 "Another job is running" copy goes.
- **Runs → "Auto-apply queue"** (`ApplyQueuePanel.vue`, the Q-118 §4 contract: `section.ui-card.runs-queue`, `.ui-card-head` + `.ui-count` + `.ui-card-actions`, mounted in LC's `.runs-top` slot). It polls `GET /api/apply/queue` every 3 s while visible and active, every 15 s otherwise, and never while the tab is hidden.
  - **Now applying** (`.ui-list-row`, `StateChip`): "{Company} · {Role}", the state word, the elapsed time, a "Dry run" badge, and "Stop this application" (→ `/queue/stop`; then "Stopped. The queue is paused."; 409 → "That application had already finished. The queue is paused."). State words: tailoring "Preparing the resume", planning "Reading the form", opening "Opening the site", signing_in "Signing in", signing_up "Creating an account", verifying_email "Checking email", filling "Filling the form", submitting "Submitting". `interrupted`: "Interrupted. JobScraper closes it when auto-apply next starts."
  - **Slot held by something else:** run: "Waiting for the search run to finish. Auto-apply starts right after."; other: "Waiting for the current job to finish." When `run_pending`: "A search run starts when this application finishes. The queue continues after it."
  - **Up next ({n})** (`ol.ui-list`): "{n}. {Company} · {Role}", "added {relative}", a "Dry run" badge, "Back at the front: {note}", and `button.ghost` "Remove". Empty: "Nothing waiting. Choose Auto-apply on a role in the Inbox to add it here."
  - **Actions:** "Pause queue" (note "The application in progress finishes first."), "Resume", "Clear queue" (confirm "Remove all {n} waiting roles from the queue? They stay in Applications under To apply." with the buttons "Clear queue" / "Keep them").
  - **Paused banner** (`.notice.warn[role=status]`): text, hint, "{n} waiting", and Resume / Clear queue. Resume 409 `disabled`: "Auto-apply is switched off in this copy of JobScraper (JOBSCRAPER_APPLY_QUEUE=0)."
  - **Recently finished** (10, `ul.ui-list`): "{Company} · {Role}", an outcome `.ui-badge`, the time, and `a.text-link` "Open in Applications" (`#/applications/all/<job_id>`). Empty: "Finished applications show here."
  - **Whole panel empty:** "No applications queued. Choose Auto-apply on roles in the Inbox; JobScraper applies to them one at a time in the background while you keep browsing."
- **Start run** (Runs `startLabel`, Overview): while `slot == "apply"` the label is "Run after this application". A `deferred` 202 shows "The search run starts when the current application finishes." and tracks no job as "run". Other 409s: "Auto-apply is busy (it may be keeping a dry-run form open). Pause the queue in Runs to free it."
- **JobPill** (ours): kind `apply` reads `/api/apply/queue` every 10 s while running and shows "Auto-apply · {n} waiting", or "Auto-apply running" when nothing waits. Not "1 of 4", because the total keeps changing.
- **Applications** (`ApplicationRow.vue` `.app-state` slot + `attempts.js`): new kind `queued` → "Queued · {ordinal}"; `running` → "Applying…"; "Try again" on stopped, cancelled and ready needs-input rows → `POST /api/apply`. Remove on a role in flight shows the 409 text. A role becomes Applied only after `submitted`. It refreshes on activation, on `jobscraper:apply-queue` (sent by the Inbox and Runs), and every 10 s while a row is queued or applying.

**7.2 Pause copy (`QUEUE_PAUSE_TEXTS`, text / hint)**
owner "The queue is paused." / "Resume when you're ready." · restarted "Roles are waiting from your last session. Auto-apply doesn't start by itself after JobScraper restarts." / "Resume to continue, or clear the queue." · app_closed "JobScraper was closed, so the queue stopped after the application in progress." / "Resume to continue." · cancelled "You stopped an application, so the queue is paused." / "Resume to go on with the next role." · profile_incomplete "Your application details are missing: {detail}." / "Fill them in under Profile → Application details, then resume." · model_unavailable "The local AI model isn't answering, so the queue is paused. Nothing was sent." / "Start Ollama, then resume. The role it was on is back at the front." · browser_unavailable "Edge couldn't open for auto-apply: {detail}." / "Close any JobScraper Edge window (a sign-in window, for example), then resume. The role is back at the front." · fill_failed "The form filler couldn't answer a required question, so the queue is paused. Nothing was sent." / "See the role in Applications. Resume to go on with the next one." · bot_checks "Two sites in a row showed a CAPTCHA or bot check, so the queue is paused." / "Apply to those two by hand. Resume to go on with the rest." · repeated_errors "The last 3 applications stopped with an unexpected error, so the queue is paused." / "Check the Developer tab log, then resume." · repeated_failures "The last 3 applications stopped the same way ({detail}), so the queue is paused." / "Fix the cause shown in Applications, then resume." · daily_limit "Today's limit is reached ({detail})." / "Resume tomorrow, or raise the limit in Settings → Apply." · worker_failed "Auto-apply stopped unexpectedly, so the queue is paused." / "Check the Developer tab log, then resume." · busy_elsewhere "Another auto-apply run (started from the command line) is using the browser." / "Resume when it has finished." · disabled "Auto-apply is switched off in this copy of JobScraper." / "Roles can be queued here, but nothing is applied."

Refusals (text / hint): not_found "This role is no longer in the database." · already_queued "This role is already in the auto-apply queue." / "See it in Runs." · in_progress "JobScraper is applying to this role right now." / "Stop it in Runs first if you want to remove it." · queue_full "The queue is full (100 roles)." / "Add more once some have finished."

**7.3 Accessibility.** Only "Now applying" is `aria-live="polite"`. Remove buttons are labelled "Remove {Company} {Role} from the queue"; after a removal focus moves to the next Remove, else to the "Up next" heading. Pause and Resume are separate buttons; the banner is `role="status"`; the JobPill keeps its hidden text when narrow.

## 8. Test plan (lean; the tester owns `tests/`)
Fakes only: a fake JobManager, `browser_factory` and backend. **No test starts a real apply job** (the repository config is `auto`).

**Pins.** P1 never two in flight (live count checked at every state change; the kicker never starts while busy) · P2 never twice (`already_queued`, `in_progress`, `duplicate`) · P3 enqueue while a job runs → 202 + position, `started` false · P4 FIFO; a returned item goes to the front; `queue_return` after a fresh click does nothing · P5 remove waiting (204) vs started (404) · P6 launch error → returned + `browser_unavailable`, next not taken; `available` False → `model_unavailable`, no attempt row · P7 start-up with waiting items → `restarted`, no start · P7b (M2) store failing at start-up → no start even after it recovers; Resume opens the gate · P8 a refused item (applied twin) doesn't stop the next · P9 dry run: two `ready_to_submit` before any hold; the 4th tab closes the oldest; an item added during the hold continues · P10/P10b (H4) dry-run click + auto at pick → `dry_run`; auto click + mode switched to dry_run → `ready_to_submit`, `submit_clicked_at` null; unknown value → `dry_run` · P11 (M3) the pause commits before the cancel; paused → `queue_take` None; Stop with a stale `attempt_id` → 409, no cancel · P12 exit 1 → `worker_failed`, exit 3 → `busy_elsewhere`; stale or pre-upgrade records not judged; an existing pause not overwritten · P13 run during the worker → deferred, yield, run starts with the yield cleared, then the worker · P14 parent gone → `app_closed` after the current item · P15 a profile answer added mid-queue is seen by the next item · P16 layering · P17 (H1) default `create_app()` + waiting item + POST → the `job_command` stub (raises if called) is never called; with `apply_queue_worker=True` and a fake swapped in after `create_app` → the fake gets the start, the stub is never called · P18 (H2) `apply_queue_wanted`: `=0` off, `=1` on, unset + `JOBSCRAPER_DB` off; disabled → enqueue 202 `disabled`, Resume 409, no tick · P19 (H3) untrack while waiting → no queue row and no attempt after a worker pass; untrack in flight → 409; a role set to `applied` while waiting is dropped by `queue_take` · P20 (M4) streaks across two worker processes: 3 × same reason → `repeated_failures`; `unanswerable_required` → `fill_failed`; Resume resets the window · P21 (M1) `GET /api/apply/queue` writes and starts nothing; it joins the GET-sweep allowlist.
**Fixtures:** `questions_support.make_job`; `_FakeJobs` gains `current()` (idle / running / ended with an exit code); a fake session with `hold() -> bool` and `alive()`.
**Changed pins:** `test_q114_caps.py` B (default app: no start, `fake.started == []`, one in `queued`; a variant with `apply_queue_worker=True` expects `("apply", {"queue": True})`) · `test_web_questions.py` retry 409 → 202 `queued` · `test_web_apply_settings.py` the 202 shape · `test_web_control.py` add the deferred case · `test_connections.py` the allowlist · vitest: Inbox `applyReady`/busy, JobPill, QuestionsInbox retry, Runs/Overview start-run. Gate merges on separate `-k apply_flow` and `-k apply_e2e` runs.

## 9. Build plan (lanes with disjoint files)
| WP | Lane | Files | After | Verify | Done when |
|---|---|---|---|---|---|
| WP-0 (≤30 min) | architect | `apply/contracts.py` | this review | `python tests/run_tests.py -k apply_contracts` | §3.6 merged |
| WP-E1 (½ day) | E | `store.py` | WP-0 | `-k store` + `-k apply_queue_store` | §2, §3.1; store parts of P2/P4/P5/P11/P19/P20 |
| WP-E2 (1 day) | E | `apply_flow.py` (new functions + the 3 edits of §3.2), `apply/browser.py`, `cli.py` | E1, Q-119 | `-k apply_flow`, `-k apply_queue_flow`, `-k apply_e2e` (separately) | §3.2, §3.3, §4, §5; P1/P6/P8–P10b/P14/P15/P20 |
| WP-W1 (1 day) | W | `web/jobs.py`, `web/applyqueue.py` (new), `web/api.py`, `routers/apply.py`, `routers/questions.py`, `routers/jobs.py`, `routers/applications.py` | E1 | `-k web_apply`, `-k q114`, `-k web_questions`, `-k web_control`, `-k connections`, `-k layering` | §3.4, §3.5; P3/P5/P7/P7b/P11–P13/P17–P19/P21 |
| WP-U1 (½ day) | U | `web/src/api.js`, `tabs/Inbox.vue`, `components/JobPill.vue`, `components/QuestionsInbox.vue` | W1 | `cd web; npx vitest run` | §7 Inbox, JobPill, QuestionsInbox |
| WP-U2 (1 day) | U2 | `components/ApplyQueuePanel.vue` (new), `tabs/Runs.vue` (mount in LC's slot + `startLabel` + deferred), `tabs/Overview.vue` (deferred start-run only) | W1, Q-118 LC + LA | vitest | §7 Runs, Start run |
| WP-U3 (½ day) | U3 | `web/src/attempts.js`, `components/ApplicationRow.vue` (`.app-state` slot, Try again, Remove 409) | W1, Q-118 LB | vitest | §7 Applications |
| WP-T | tester | `tests/test_apply_queue_*.py` (new) + the changed pins | each lane | as above | P1–P21 |

**Merge order (Coordinator):** Q-119 (reader fix, `apply/page.py`) → WP-0 → E1 → E2 ∥ W1 → T pins per lane → Q-121's flow changes rebased on top. E2 goes first because its `apply_flow.py` change is small and additive (new functions plus three local edits), while Q-121 reworks the fill path; rebasing the large change over the small one is cheaper and safer. The queue's pauses (`model_unavailable`, `fill_failed`, `repeated_failures`) should also exist before D-208's filler runs unattended sequences. Q-113 also touches `apply_flow.py`: whichever lands second rebases. U1 after W1; U2 after W1 + Q-118 LC/LA; U3 after W1 + LB. Then one bundle build in the main checkout (message the live sessions first).
**Smoke (H2):** run the dev instance as `JOBSCRAPER_DB=<copy> JOBSCRAPER_PORT=8768 JOBSCRAPER_MAIL_SYNC=0 JOBSCRAPER_APPLY_QUEUE=0 python -m jobscraper web`. Check that `GET /api/apply/queue` shows `paused.reason == "disabled"` and that an enqueue answers 202 with `disabled: true`. Never run the worker against a copied DB: the Edge profile is shared and the copy's never-twice history is stale.

## 10. Risks, accepted LOWs, open questions
- **Assumed, not blocking:** waiting roles are kept but paused after every restart, and Resume is the fresh click (D-200; undoing it is one line). The mode at the click is an upper bound (I5, from D-203).
- **LOWs resolved:** L1 (`acfg` re-read per item; `headed` keeps its launch value until the session reopens, accepted) · L2 (exit 3 → `busy_elsewhere`) · L3 (only this runner's jobs are judged; first pause wins) · L4 (the yield is cleared when the run starts) · L6 (one transaction per enqueue; `queue_return` does nothing on conflict) · L7 (ADR updated).
- **L5 accepted:** other job kinds get 409 for up to 10 minutes during a dry-run hold. The copy says so and Pause ends the hold; a generic yield would race the tick.
- **Also accepted:** a paused or yielded worker exits 0, so its job record reads "succeeded" (the banner carries the reason). The deferred run lives in memory, so a restart forgets it. Whether the worker outlives a closed window depends on how the desktop icon launches Python; the parent-PID check bounds it to the current role. A hand-started CLI `apply` stays outside the queue; `RunLock` serialises it with the worker.
READY TO BUILD (independent review 2026-11-12: ready with changes, all folded in)
