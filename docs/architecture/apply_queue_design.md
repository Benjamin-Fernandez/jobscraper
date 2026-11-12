# Auto-apply queue design (KA-1, D-205)

Status: draft for review, 2026-11-12. ADR: `adr/0010-apply-queue.md`. Extends `apply_design.md` §3, §12, §14; changes none of its safety rules. The queue is fully deterministic: no model call decides anything here.

## 1. Goals, non-goals, requirement map

**Goals.** Clicking Auto-apply never fails because something is running: the role joins a durable queue and leaves the Inbox. One background worker applies to queued roles one at a time while the owner keeps clicking. Runs shows what is being applied now, what waits, why the queue is paused, and what just finished. Item-level failures don't stop the queue. System-level failures pause it with a reason.
**Non-goals.** Reordering beyond "returned items go to the front"; scheduling ("apply at 9 am"); more than one attempt at a time; a queue for other job kinds; multi-select in the Inbox (the API accepts up to 20 ids, so the Q-118 wave can add it later).

| Requirement | Where |
|---|---|
| F-30 queue one attempt per role, run one at a time, refuse with reasons, caps | §2, §3.2, §3.5 `POST /api/apply`, §4 |
| F-37 submit + confirm, dry run leaves the form open | §3.2 (attempt flow unchanged), §5 |
| F-38 fail properly, show the reason in the role's panel | §4.1, §7 Applications |
| NF-05 one attempt in flight, human pace | §2 I1, §3.2, §6 |
| NF-06 never submitted twice | §2 I2, §4.2 (reaper and `claim_click` unchanged) |
| D-200 only roles the owner clicked | §2 I4, §4.2 restart pause |
| D-203 auto = the click fills and submits; dry_run never submits | §2 I5 (mode never upgrades) |
| D-204 caps (0 = no limit, 10 per employer) | §4.1 (re-checked at pick; daily limit pauses) |
| D-205 queue + background worker + Runs section | the whole document |

## 2. Data model (SCHEMA_VERSION 5 → 6, additive)

Choice: a **separate `apply_queue` table** (ADR-0010). Waiting items are not `apply_attempts` rows, so the reaper, the attempt state machine and every NF-06 path stay exactly as they are.

```sql
CREATE TABLE IF NOT EXISTS apply_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,           -- I2: a job waits at most once
    company_id INTEGER,                    -- jobs.company_id at the click
    pos INTEGER NOT NULL,                  -- order: ORDER BY pos, id; new = MAX(pos)+1, returned = MIN(pos)-1
    mode TEXT NOT NULL CHECK (mode IN ('auto', 'dry_run')),   -- effective mode at the click: the most it may do (I5)
    source TEXT NOT NULL CHECK (source IN ('inbox', 'retry', 'applications', 'returned')),
    enqueued_at TEXT NOT NULL,
    note TEXT                              -- 'returned: <pause reason>' for an item put back by the worker
);
CREATE INDEX IF NOT EXISTS idx_apply_queue_pos ON apply_queue(pos, id);
```
Migration: the table comes from `SCHEMA`'s `CREATE TABLE IF NOT EXISTS`; `_migrate` only bumps `meta.schema_version` with the existing upsert. No existing row changes. An older build can still open the database: it ignores the table.
Queue state lives in the `settings` table (prefix `apply_queue.`, outside `ApplyConfig.with_settings`'s `apply.` keys): `apply_queue.paused` (a `QueuePause` value, or absent), `apply_queue.paused_detail`, `apply_queue.paused_at`, `apply_queue.yield` (`1` while a search run waits its turn, §6).
**Invariants.** I1: at most one attempt in flight. This is enforced as today by the JobManager slot, `RunLock`, and the `attempts_in_flight` guard, and only one worker process runs. I2: a job is never waiting twice (UNIQUE), never waiting while it has a live attempt (the enqueue check, §3.1), never in two places (`queue_take` deletes the row and creates the attempt in one transaction). I3: FIFO by `(pos, id)`; only the worker's "return" goes to the front. I4: rows are added only by an owner click (`POST /api/apply`, `POST /api/questions/retry`) or returned unchanged by the worker after a system pause, before any click. I5: attempt mode = `dry_run` if the item's mode or the effective mode at pick is `dry_run`, else `auto`. A dry-run click never submits later.

## 3. Components

### 3.1 Store (`store.py`, the only SQL), all commit unless noted
- `queue_add(job_id, company_id, mode, source, now) -> Optional[int]`: the new 1-based position, or None if already waiting (`INSERT … ON CONFLICT(job_id) DO NOTHING`).
- `queue_return(job_id, company_id, mode, note, now) -> None`: put back at the front (`pos = MIN(pos)-1`, source `returned`).
- `queue_items() -> list[dict]`: `{job_id, company, role, mode, position, enqueued_at, source, note}` in order (joins jobs and companies). `queue_positions() -> dict[job_id, int]`.
- `queue_remove(job_id) -> bool`; `queue_clear() -> int`.
- `queue_take(now, mode_cap: str) -> Optional[dict]`: in `BEGIN IMMEDIATE`, read the head, delete it, `create_attempt(job_id, company_id, mode=min(item.mode, mode_cap), now)`, commit. Returns `{job_id, attempt_id, mode, source}`.
- `queue_pause(reason, detail, now)`, `queue_resume()`, `queue_pause_state() -> Optional[{reason, detail, since}]`, `queue_pause_if_waiting(reason, now) -> bool` (pause only if items wait and the queue isn't already paused).
- `queue_request_yield()`, `queue_take_yield() -> bool` (read and clear), `queue_clear_yield()`.
- `live_attempt(job_id=None) -> Optional[dict]`: the newest non-terminal attempt (including `queued`), joined with company and role.
- `recent_attempts(limit=10) -> list[dict]`: finished attempts, newest first, with company and role.

### 3.2 Worker (`apply_flow.py`, orchestrator)
New public `run_queue(cfg, store, *, backend, apply_cfg_fn, http=None, browser_factory=None, say=print, evidence_dir=None, now=None, should_stop=None, force_dry_run=False) -> list[AttemptResult]`. `apply_cfg_fn()` returns the effective `ApplyConfig` (settings over config), read before every item so mode and limit changes apply to the next role. `_Run.run_queue()`:
```
RunLock (else log + return []) → reap_attempts → purge_fill_cache
loop:
  should_stop() (web parent gone)         → pause app_closed; break
  queue_take_yield()                      → log "a search run goes first"; break   (no pause)
  queue_pause_state()                     → break
  acfg = apply_cfg_fn(); begin_item()     (reload profile, reset per-job caches)
  profile missing                         → pause profile_incomplete (item stays); break
  acfg.fill == "llm" and not backend.available → pause model_unavailable (item stays); break
  item = queue_take(utcnow(), "dry_run" if force_dry_run else acfg.mode)
  none → dry-run hold (§5), which may return to the loop when a new item arrives; else break
  set_mode(item.mode); r = attempt(item.job_id, attempt_id=item.attempt_id)
  p = pause_for(r, history) (§4.1) → if p.returns and not r.clicked: queue_return(...); queue_pause(p); break
finally: close the session; release the lock
```
Changes to `_Run`: `attempt(job_id, *, attempt_id=None)` uses the given row instead of creating one. `run()` (the batch path) stays as it is for the CLI. `begin_item()` resets what the batch assumed fresh: `profile`/`profile_error`/log redaction values, `rules`, `_resume_text`, `_resume_entries`, `_aliases`, `reopened`, `compose_files`, `compose_meta`. In queue mode `seen` is cleared per item; I2 replaces the batch-duplicate check, so a retry clicked during the same worker isn't refused. `set_mode(mode)` sets `dry_run`/`mode`. `browser()` reopens the session if the owner closed the window (`session.alive()`). A launch error sets `self.browser_failed` with the detail "the JobScraper Edge profile is in use" (reuse `_names_profile_dir`) or "Edge could not start (<Type>)". One `BrowserSession` is reused across items, as in a batch. The guards, `claim_click`, the reaper and the state machine don't change.
`browser.py` (engine lane): `hold(seconds) -> bool` (True while the window is still open) and `alive() -> bool`.

### 3.3 CLI (`cli.py`)
`apply queue [--parent-pid N] [--dry-run]`: `queue` becomes a reserved first word, like `show` and `open-profile`. It boots, sets the backend `num_ctx` as `cmd_apply` does, and calls `run_queue` with `apply_cfg_fn=lambda: _effective_apply(cfg, store)`. `should_stop` = "the process `--parent-pid` with the identity recorded at start is gone" (lazy import of `web.jobs.pid_alive`/`process_identity`; cli is exempt from layering). It prints one line per item and a summary `queue: N finished, M waiting, paused: <reason>|no`. **Exit 0 on every orderly end** (drained, paused, yielded, item failures included); 2 bad arguments; 143 cancelled. Anything else is a crash (§4.2). `apply <ids>` (the batch) is unchanged; the web no longer uses it.

### 3.4 Web process: `web/jobs.py` and a new `web/applyqueue.py`
`jobs.py`: `apply` with `opts={"queue": True}` → argv `apply queue --parent-pid <os.getpid()>`; `queue` is added to the reserved ids. The slot rule is unchanged: one job at a time, and the worker is an ordinary `apply` job, so Cancel, the log, the JobPill and `current()` all work as they do now.
`applyqueue.py`: `ApplyQueueRunner(jobs, store_factory)`. It imports only the store, `web.jobs` and `apply.contracts`, and never Popens: it starts the worker only through `jobs.start`, so test fakes cover it. `kick() -> bool`, under a lock:
1. If the slot is busy, return.
2. If the last finished job is an `apply` this runner hasn't judged and it exited not in {0, 143}, call `queue_pause(worker_failed)`.
3. If `pending_run` is set, `jobs.start("run", pending_run)`, clear it, and return.
4. If paused or nothing is waiting, return.
5. Otherwise `jobs.start("apply", {"queue": True})`; `JobBusy` returns quietly.

`kick()` runs after every enqueue, resume and retry, on `GET /api/apply/queue`, and on a daemon tick every 5 s (`start_timer`/`stop`, the `MailSyncRunner` pattern). The tick is what starts the queue after a search run ends while nobody is watching. `create_app(apply_queue_timer=False)`; `cmd_web` passes True. Tests and the default stay off.
**Start-up hook** (always, in `create_app`'s startup): `queue_clear_yield()`, then `queue_pause_if_waiting(restarted)`. So no new attempt starts after a launch without a fresh Resume click (D-200 reading, §10).

### 3.5 Web API (`routers/apply.py` unless noted)
| Method, path | Request | Response |
|---|---|---|
| `POST /api/apply` (changed) | `{job_ids:[1..20]}` | **202** `{queued:[{job_id, position}], accepted:[job_id] (same ids, kept for compatibility), refused:[{job_id, reason_code, text, hint}], mode, paused: bool, started: bool, job: JobView or null}`. 422 `profile_incomplete` and 422 `refused` (all refused) as today. **No 409.** |
| `GET /api/apply/queue` (new) | | 200 `{paused: null or {reason, text, hint, since}, now: null or {attempt_id, job_id, company, role, mode, state, started_at}, slot: "free" or "apply" or "run" or "other", run_pending: bool, waiting:[{job_id, company, role, mode, position, enqueued_at, source}], recent:[{attempt_id, job_id, company, role, mode, kind, text, finished_at}]}`. Reaps first when the slot isn't `apply` (same rule as `/apply/attempts`), then kicks. |
| `DELETE /api/apply/queue/{job_id}` | | 204; 404 `{detail:"not_waiting"}` (already started or unknown) |
| `POST /api/apply/queue/pause` | | 200 queue view (idempotent; reason `owner`) |
| `POST /api/apply/queue/resume` | | 200 queue view, then kick; 422 `{detail:"profile_incomplete", missing}` (stays paused) |
| `POST /api/apply/queue/clear` | | 200 `{removed:n, queue: view}` (waiting rows only; the attempt in flight goes on) |
| `GET /api/apply/status` (additive) | | `{mode, missing, busy, queue:{waiting:int, applying:bool, paused: reason or null}}`. `mode`/`missing`/`busy` keep their meaning (`busy` = a job holds the slot). The Inbox stops reading `busy`; ModeChip is unaffected. |
| `POST /api/questions/retry` (changed, `routers/questions.py`) | as today | 202 `{queued, refused, job}` via the same enqueue helper (source `retry`); 422 `not_ready` as today; no 409 |
| `POST /api/jobs/run` (changed, `routers/jobs.py`) | as today | when `slot == "apply"`: 202 `{job:<apply view>, deferred:true}`. It sets `pending_run` and `queue_request_yield()`. Other busy kinds: 409 as today |
| `POST /api/jobs/cancel` (changed) | | when the running kind is `apply`, `queue_pause(cancelled)` **before** cancelling; the response is unchanged |
| `GET /api/applications` (additive, `routers/applications.py`) | | each row gains `queue: null or {position}`; `last_attempt.kind` gains `queued` (from the queue, when no live attempt) |

**Enqueue helper** (`routers/apply.py`, also used by questions):
1. Profile check (422).
2. Per id, in order: unknown → `not_found`; `queue_positions` has it → `already_queued`; `live_attempt(job_id)` → `in_progress`; `apply_duplicate` → `duplicate`; caps when mode is `auto` → `cap_reached`; queue at 100 → `queue_full`.
3. Then `queue_add(…, mode=effective mode, source)`, and if the role has no application row, `set_application_status(job_id, "to_apply")` (by the owner: it was their click).
4. One commit, then `kick()`.

The new refusal codes are API-only and their copy is in `QUEUE_REFUSAL_TEXTS` (§3.6). **Layering:** web imports only foundation + `apply.contracts`; the worker is an orchestrator; SQL only in `store.py`; no model call in web (`backend.available` is called by the worker).

### 3.6 Contract (additive; `apply/contracts.py`, CONTRACT_VERSION 5 → 6, written by the architect as WP-0 after review)
`class QueuePause(str, Enum)`: `owner, restarted, app_closed, cancelled, profile_incomplete, model_unavailable, browser_unavailable, bot_checks, repeated_errors, daily_limit, worker_failed`. `QUEUE_PAUSE_TEXTS: dict[QueuePause, ReasonText]` (copy in §7.2). `RETURNS_ITEM = {profile_incomplete, model_unavailable, browser_unavailable, daily_limit}`. `QUEUE_REFUSAL_TEXTS: dict[str, ReasonText]` for `not_found, already_queued, in_progress, queue_full`. Nothing existing changes, which is why no new ADR is needed beyond 0010.

## 4. Failure handling

### 4.1 After each item (`pause_for`, deterministic, in `apply_flow`)
| Outcome of the item | Queue | Item |
|---|---|---|
| Any per-role ending (submitted, ready_to_submit, unconfirmed, duplicate, closed, unsupported, validation, page_unrecognised, login, mail, unanswerable with the model up, per-employer cap, cancelled) | continues | stays in Applications with its reason and Try again |
| `profile_incomplete` (missed by the pre-check, e.g. the resume file vanished) | pauses `profile_incomplete` | returned to the front |
| `model_unavailable`, or detail containing "(model unavailable)" | pauses `model_unavailable` | returned |
| browser launch failed (`browser_failed`) | pauses `browser_unavailable` | returned |
| daily total cap refused at the guard (the flow knows which cap fired) | pauses `daily_limit` | returned |
| 2nd item in a row ending `captcha`/`bot_challenge` (or the note "captcha after submit") | pauses `bot_checks` | not returned (apply by hand) |
| 3rd item in a row ending `error` | pauses `repeated_errors` | not returned |
An item is returned only if `submit_clicked_at` is null (NF-06). Its failed attempt row stays as the audit. The pre-checks (profile, `backend.available`) pause **before** taking an item, so most system failures leave no failed attempt row.

### 4.2 Restart, crash, cancel
- App closed with roles waiting: at the next launch the queue is paused `restarted`; items are kept.
- App closed mid-attempt: the worker shares the console and usually dies with it. If it survives, it finishes the current role, sees the parent gone, pauses `app_closed`, and exits. In both cases the next reaper (worker start, or `GET /attempts|/queue` while no apply job runs) closes the row: clicked → `submitted_unconfirmed` "interrupted after submit" (the owner confirms, never resubmitted); not clicked → `failed(cancelled, interrupted)`, shown with Try again. It is never returned automatically.
- Worker crash (exit not 0/143): the kicker pauses `worker_failed`. No restart loop.
- Cancel from Runs or the JobPill pauses `cancelled` first, then the existing cancel runs; the attempt ends `failed(cancelled)` (or unconfirmed after a click).
- Retry: `POST /api/questions/retry` and Applications "Try again" (`POST /api/apply`) enqueue. A fresh click, so D-200 holds.

## 5. Dry-run behaviour
A filled tab (`ready_to_submit`) stays open and the worker moves on in a new tab. At most `DRY_RUN_TABS = 3` filled tabs are kept; a 4th closes the oldest (log line). When the queue is empty and a filled tab is open, the worker holds for up to `dry_run_hold_s` (600) in 5 s slices. It stops early when the owner closes the window, the queue is paused, a yield is requested, or a new item is waiting; a new item continues in the same session. Auto mode closes each tab as today and never holds. The ready text "The form stays open for 10 minutes" is unchanged; it's true for the last one.

## 6. Concurrency with search runs and other jobs
The worker and every other job kind share the single slot, so Edge, the GPU and the database writers never overlap. While another job runs, waiting items stay waiting; Runs shows "Waiting for the search run to finish", and the tick starts the worker when the slot frees. **Start run while the worker is active:** the button reads "Run after this application". The run goes ahead of the rest of the queue: the worker finishes the current role, yields (no pause), the kicker starts the run, and the queue resumes by itself afterwards. Profile, titles, companies, tailor and mail test still get 409 while the worker runs, with copy that points to Pause. The mail sync already defers the model while the slot is busy. Out of scope as before: a CLI `jobscraper run` started outside the web can overlap.

## 7. UI (what and copy; styling from the Q-118 wave)
**7.1 Surfaces**
- **Inbox** (reads `/api/apply/status` on mount and after each click). The Auto-apply button is disabled only when `missing` is non-empty or the status is unknown, never by `busy`. Hint: auto "Adds this role to the auto-apply queue. JobScraper fills the form and submits it."; dry "Adds this role to the auto-apply queue. Dry run: the form is filled, never submitted." Clicking takes the role out of the list (it becomes To apply). Toast: "Applying now." when position 1 and the worker starts; otherwise "Added to the auto-apply queue: {ordinal} in line."; paused: "Added to the auto-apply queue. The queue is paused; resume it in Runs." Toast actions: "See the queue" (#/runs) and "Undo" (DELETE + untrack if it had no status before; if it already started: "It has already started; stop it in Runs."). Refusals: the server's `text` + `hint`. The button can be clicked again at once.
- **Runs → section "Auto-apply queue"**, a new component `ApplyQueuePanel.vue` mounted above "Start a run". It polls `GET /api/apply/queue` every 3 s while visible and active (`now` or `waiting` non-empty and not paused), every 15 s otherwise, and stops while the tab is hidden.
  - Now applying: "{Company} · {Role}", the state word (tailoring "Preparing the resume", planning "Reading the form", opening "Opening the site", signing_in "Signing in", signing_up "Creating an account", verifying_email "Checking email", filling "Filling the form", submitting "Submitting"), elapsed time, a "Dry run" tag when the mode is dry_run, and the button "Stop this application" (after it: "Stopped. The queue is paused.").
  - `slot` run/other with items waiting: "Waiting for the search run to finish. Auto-apply starts right after." (other: "Waiting for the current job to finish.")
  - `run_pending`: "A search run starts when this application finishes. The queue continues after it."
  - Up next ({n}): an ordered list "{n}. {Company} · {Role}", "added {relative time}", a "Dry run" tag where it applies, "Back at the front: {note}" for returned items, and "Remove". Empty: "Nothing waiting. Choose Auto-apply on a role in the Inbox to add it here."
  - Controls: "Pause queue" (shown when not paused; note "The application in progress finishes first."), "Resume", "Clear queue" with the confirm "Remove all {n} waiting roles from the queue? They stay in Applications under To apply." and buttons "Clear queue" / "Keep them".
  - Paused banner: `paused.text`, `paused.hint`, "{n} waiting", and buttons Resume / Clear queue.
  - Recently finished (last 10): "{Company} · {Role}", the outcome chip (`attemptLabel(kind)`), the time, and "Open in Applications". Empty: "Finished applications show here."
  - Whole section empty: "No applications queued. Choose Auto-apply on roles in the Inbox; JobScraper applies to them one at a time in the background while you keep browsing."
- **JobPill** (ours): for kind `apply` it reads `/api/apply/queue` every 10 s while running and shows "Auto-apply · {n} waiting", or "Auto-apply running" when nothing waits. (A departure: "1 of 4" would mislead because the total keeps changing.)
- **Applications** (`attempts.js` + pill): new kind `queued` → "Queued · {ordinal}"; `running` → "Applying…". "Try again" on stopped/cancelled/needs-input-ready rows calls `POST /api/apply` (toast as in the Inbox). Applied only after `submitted`, unchanged. It refreshes on activation, on the window event `jobscraper:apply-queue` (sent by the Inbox and Runs after a change), and every 10 s while any row is queued or applying.
- **Start run** (Runs, while `slot == "apply"`): label "Run after this application". 409 for other kinds: "Auto-apply is busy. Pause the queue in Runs to free it after the current application."

**7.2 Pause copy (`QUEUE_PAUSE_TEXTS`, text / hint)**
owner "The queue is paused." / "Resume when you're ready." · restarted "Roles are waiting from your last session. Auto-apply doesn't start by itself after JobScraper restarts." / "Resume to continue, or clear the queue." · app_closed "JobScraper was closed, so the queue stopped after the application in progress." / "Resume to continue." · cancelled "You stopped the application in progress, so the queue is paused." / "Resume to go on with the next role." · profile_incomplete "Your application details are missing: {detail}." / "Fill them in under Profile → Application details, then resume." · model_unavailable "The local AI model isn't available, so the queue is paused. Nothing was sent." / "Start Ollama, then resume. The role it was on is back at the front." · browser_unavailable "Edge couldn't open for auto-apply: {detail}." / "Close any JobScraper Edge window (a sign-in window, for example), then resume. The role is back at the front." · bot_checks "Two sites in a row showed a CAPTCHA or bot check, so the queue is paused. Nothing was sent to them." / "Apply to those two by hand. Resume to go on with the rest." · repeated_errors "The last 3 applications stopped with an unexpected error, so the queue is paused." / "Check the Developer tab log, then resume." · daily_limit "Today's limit is reached ({detail})." / "Resume tomorrow, or raise the limit in Settings → Apply." · worker_failed "Auto-apply stopped unexpectedly, so the queue is paused." / "Check the Developer tab log, then resume."
Refusals: not_found "This role is no longer in the database." / "" · already_queued "This role is already in the auto-apply queue." / "See it in Runs." · in_progress "JobScraper is applying to this role right now." / "Follow it in Runs." · queue_full "The queue is full (100 roles)." / "Add more once some have finished."

**7.3 Accessibility.** Only the "Now applying" line is `aria-live="polite"`; lists are not live, to avoid chatter. Remove buttons are labelled "Remove {Company} {Role} from the queue". After a removal, focus moves to the next row's Remove, or to the "Up next" heading. Pause and Resume are separate buttons in tab order. The paused banner is `role="status"`. The pill keeps its hidden text on narrow screens.

## 8. Test plan (lean; the tester owns `tests/`)
Pins (fakes only: a fake JobManager, `browser_factory`, backend; **no test starts a real apply job**; the repo config is `auto`):
P1 never two in flight (the fake records the live attempt count at every state change; the kicker never starts while busy) · P2 never twice (already_queued, in_progress, duplicate; `queue_take` + `claim_click` unchanged) · P3 enqueue while a job runs → 202, a position, `started` false · P4 FIFO, and a returned item at the front · P5 remove a waiting item (204) vs a started one (404) · P6 system pauses: launch error → returned + `browser_unavailable` + the next item not taken; `available` False → `model_unavailable` with no attempt row · P7 start-up with waiting items → `restarted`, no start · P8 a refused item (applied twin) doesn't stop the next · P9 dry run: two items reach `ready_to_submit` before any hold; the 4th tab closes the oldest; an item added during the hold continues in the same session · P10 the mode never upgrades (dry-run click, auto at pick → dry_run) · P11 cancel of an apply job pauses `cancelled` · P12 worker exit 1 → `worker_failed`, no restart · P13 a run requested during the worker → deferred, yield, the run starts, then the worker · P14 parent gone → `app_closed` after the current item · P15 the per-item profile reload sees an answer added mid-queue · P16 layering stays green.
Fixtures: `questions_support.make_job`, the existing fake JobManager (`test_q114_caps._FakeJobs` gains `current()` idle/running), and the fake session with `hold() -> bool`/`alive()`.
Changed pins: `test_q114_caps.py` B (`fake.started[0]` opts become `{"queue": True}`; still one start). `test_web_questions.py` retry 409 pins → 202 `queued`. `test_web_apply_settings.py` preflight 202 shape (+`queued`). `test_web_control.py` run-busy pins: a run while a run holds the slot stays 409; add the apply case. Vitest: the Inbox `applyReady`/busy pins and the JobPill text. Gate each merge on `-k apply_flow` and `-k apply_e2e` run separately (handover).

## 9. Build plan (lanes with disjoint files)
| WP | Lane | Files | Inputs | Verify | Done when |
|---|---|---|---|---|---|
| WP-0 (≤30 min) | architect | `apply/contracts.py` | review of this doc | `python tests/run_tests.py -k apply_contracts` | §3.6 merged |
| WP-E1 (½ day) | E | `store.py` | WP-0 | `python tests/run_tests.py -k store` + `-k apply_queue_store` | §2, §3.1; P2/P4/P5 store parts green |
| WP-E2 (1 day) | E | `apply_flow.py`, `apply/browser.py`, `cli.py` | E1 | `-k apply_flow`, `-k apply_queue_flow`, `-k apply_e2e` (separately) | §3.2, §3.3, §4.1, §5; P1/P6/P8–P10/P14/P15 |
| WP-W1 (1 day) | W | `web/jobs.py`, `web/applyqueue.py` (new), `web/api.py`, `web/routers/apply.py`, `routers/questions.py`, `routers/jobs.py`, `routers/applications.py` | E1 (store), contract | `-k web_apply`, `-k q114`, `-k web_questions`, `-k web_control`, `-k layering` | §3.4, §3.5, §4.2; P3/P5/P7/P11–P13 |
| WP-U1 (½ day) | U | `web/src/api.js`, `tabs/Inbox.vue`, `components/JobPill.vue` | W1 shapes (this doc) | `cd web; npx vitest run` | §7 Inbox, JobPill |
| WP-U2 (1 day) | U2 | `components/ApplyQueuePanel.vue` (new), `tabs/Runs.vue` (mount + Start-run label only) | W1 shapes | vitest | §7 Runs |
| WP-U3 (½ day) | U3 | `web/src/attempts.js`, `tabs/Applications.vue` (pill + Try again only) | W1 shapes | vitest | §7 Applications |
| WP-T | tester | `tests/test_apply_queue_*.py` (new) + the changed pins above | each lane | as above | P1–P16 |
Merge order (Coordinator): WP-0 → E1 → E2 and W1 (parallel; W1 rebases on E1) → T pins per lane → U1/U2/U3 (parallel; U2/U3 coordinate with Q-118 on Runs.vue/Applications.vue: the queue lives in its own component so the overlap is one mount line) → one bundle build in the main checkout after messaging the live sessions. Smoke-check `personal`: `GET /api/apply/queue` on the dev instance (8768, DB copy, `JOBSCRAPER_MAIL_SYNC=0`); the start-up pause covers a copied DB with waiting rows.

## 10. Risks and open questions
- **D-200 reading (assumed, not blocking):** waiting roles are kept but paused after every restart, and Resume is the fresh click. If the owner wants the queue to continue by itself after a restart, that's a one-line change (skip `queue_pause_if_waiting` at start-up).
- Mode at the click is an upper bound (I5). Assumed from D-203; switching the setting to auto doesn't upgrade waiting dry-run items.
- The deferred search run is held in memory: a web restart forgets it (the owner clicks Start run again); the start-up clears the yield flag.
- An existing gap, not new: the web reaps when the JobManager sees no apply job, so a hand-started CLI `apply` could have a live row reaped. Unchanged; noted for a later Q.
- The worker surviving a closed window depends on how the desktop icon launches Python; the parent-PID check bounds it to the current role.
- Profile/titles/companies still get 409 while the worker runs (or holds a dry-run form for up to 10 minutes); Pause frees the slot after the current role.
READY TO BUILD: after review
