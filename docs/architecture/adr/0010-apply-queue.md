# ADR-0010: A durable auto-apply queue drained by one looping worker job

**Status:** Proposed · **Date:** 2026-11-12 · **Deciders:** Coordinator, owner (D-205) · **Design:** `../apply_queue_design.md`

## Context
Today `POST /api/apply` starts one `apply` job for the clicked ids and answers 409 while any job runs, so the owner can't add a second role. D-205 asks for a queue that a background worker drains while the owner keeps clicking. The constraints stay: one attempt in flight (NF-05), never submitted twice (NF-06; the reaper and the pre-click compare-and-set), only roles the owner clicked (D-200), the click is the consent and the mode decides submit (D-203), and one GPU and one Edge profile shared with search runs. `web/` may not import `apply_flow`.

## Options considered
**Where waiting items live**
- A. `apply_attempts` rows in state `queued`. No new table. But the reaper closes every non-terminal row today, so it would have to skip `queued`, and `queued` would change from "a moment before the guards" to "durable waiting". Removing an item needs a delete or a `failed(cancelled)` row (audit noise). The safety-critical NF-06 code gets edited for a UI feature.
- B. **A separate `apply_queue` table** (job_id UNIQUE, pos, mode at the click, source). The reaper, the state machine and `claim_click` stay untouched. Remove = delete a row. `queue_take` moves the head into a new `queued` attempt in one transaction, so an item is never in two places or lost.

**Who drains it**
- 1. A thread in the web process. This is rejected: web may not import the orchestrator (layering), a browser or model hang would hang the web app, and Cancel would need a second mechanism.
- 2. One `apply` job per item, chained by the JobManager. The worker is simplest, and search runs could slot in between items. But Edge relaunches and the profile lock churns per item, dry-run filled tabs can't outlive their process, and the chaining logic moves into the web layer anyway.
- 3. **One looping worker job** `jobscraper apply queue`: an ordinary `apply` job in the single slot. It takes the next item, runs the unchanged attempt flow, and looks again; it exits when the queue is empty, paused, or asked to yield to a search run. A small web-side kicker (`web/applyqueue.py`, a 5 s tick plus kicks on enqueue and resume) starts it through `JobManager.start` when the slot is free.

## Decision
B + 3.
- Pause state lives in `settings` (`apply_queue.*`). System failures (profile, model, browser launch, daily limit) pause the queue and put the item back at the front, only if Submit was never clicked. Repeated CAPTCHAs or errors pause without putting it back.
- Every web start-up pauses a non-empty queue: Resume is the fresh click.
- An attempt runs in `auto` only when both the item's mode at the click and the effective mode at pick are exactly `auto`, never via a string comparison (review H4).
- A search run requested while the worker is active waits for the current role, then goes before the rest of the queue.

## Consequences
- Clicking never fails for "busy": `POST /api/apply` and `POST /api/questions/retry` answer 202 with positions, and the 409 pins change.
- NF-05 and NF-06 machinery is reused as is. The worker is the only path that takes items and re-runs every guard at pick time. Only the worker reaps (at its start, under `RunLock`); the queue GET has no side effects (review M1).
- Additive only: schema v6 (a new table), contract v6 (`QueuePause`, texts), `GET /api/apply/status` gains `queue`. `AttemptResult` is unchanged.
- **New risk, fenced (review H1, H2):** a worker started by the web is a real `apply` process, and the repository config is `auto`.
  - `create_app` defaults to no worker.
  - The runner looks up `app.state.jobs` at each kick.
  - `cmd_web` starts the 5 s tick only when `JOBSCRAPER_APPLY_QUEUE` allows it: unset is off on a dev instance (`JOBSCRAPER_DB` set).
  - A copied DB must never drain the queue: its never-twice history is stale and the Edge profile is shared.
- **Unattended sequences** are now possible in `auto` mode. That raises the stakes of D-208's always-answer filler. The pause rules carry it: system failures, `fill_failed`, 2 bot checks, 3 errors, 3 identical failures (streaks from the DB). So does the fail-closed restart gate.
- **Smaller costs:**
  - A paused or yielded worker exits 0, so its job record reads "succeeded"; the banner carries the reason.
  - Other short jobs (profile, titles) still get 409 while the worker runs, or for up to 10 minutes while it holds a dry-run form; Pause frees the slot.
  - The deferred search run lives in memory only.
- Revisit if the owner wants the queue to continue by itself after a restart (one line), or wants a priority order.
