"""The auto-apply queue's starter in the web process (Q-120, D-205;
apply_queue_design §3.4, §4.2, §6).

Clicking Auto-apply only records the role in the `apply_queue` table. This
runner is what turns waiting roles into work: when the JobManager's one slot is
free and the queue is not paused, it starts the worker, an ordinary `apply` job
(`jobscraper apply queue --parent-pid <this pid>`), so Cancel, the log, the
JobPill and `current()` work as for every other job. The worker applies to the
roles one at a time and exits; the runner never applies to anything itself and
never Popens.

Why it looks the JobManager and the store factory up on `app_state` at every
kick, never at construction (review H1). Tests build the app, then swap a fake
JobManager in; a runner holding the manager from `create_app` would start the
real CLI past the fake, against the repository config (`apply.mode: auto`).

Why it is off unless `cmd_web` turns it on (H1, H2). `create_app` defaults to
`enabled=False`: tests and the default never start a worker, and no tick runs.
`cmd_web` passes `apply_queue_wanted(os.environ)`: a dev instance on a copied
database (`JOBSCRAPER_DB` set) has its own never-twice history while the Edge
profile is shared, so it must not apply from that copy. Disabled, clicks still
record (UI work) and the queue view says `disabled`.

Why a restart gate (M2, D-200). Roles left waiting from the last session were
clicked then, not now. The start-up hook pauses the queue (`restarted`) when
roles wait; only once that write has committed does the in-memory gate open, so
a store that is locked or unreadable at start-up can never let the tick start
the worker on old clicks. A committed Resume opens the gate too.

Exit codes of a worker this runner started (§3.3, L2, L3): 0 every orderly end,
143 cancelled, 3 another apply run holds `RunLock` (pause `busy_elsewhere`),
anything else a crash (pause `worker_failed`, no restart loop). Only the job id
this runner recorded is judged, so a record from an earlier web process or a
pre-upgrade job is never read as a crash. The first pause wins (the store).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Mapping, Optional

from jobscraper.apply.contracts import QueuePause
from jobscraper.store import utcnow
from jobscraper.web.jobs import EXIT_CANCELLED, JobBusy

logger = logging.getLogger(__name__)

TICK_S = 5.0                       # the daemon tick while enabled (§3.4)
EXIT_LOCK_HELD = 3                 # `apply queue`: RunLock held by another apply run (L2)
ENV_SWITCH = "JOBSCRAPER_APPLY_QUEUE"


def apply_queue_wanted(env: Mapping[str, str]) -> bool:
    """Does `web` start the auto-apply worker? (§3.4, H2; the `mail_timer_wanted` rule.)

    `JOBSCRAPER_APPLY_QUEUE=1` on, `=0` off. Unset: on for the real app, off when
    `JOBSCRAPER_DB` is set - that marks a dev instance on a copied database, whose
    never-twice history is stale while the Edge profile is shared."""
    flag = str(env.get(ENV_SWITCH, "")).strip()
    if flag in ("0", "1"):
        return flag == "1"
    return not str(env.get("JOBSCRAPER_DB", "")).strip()


def slot_of(jobs: Any) -> tuple[str, dict[str, Any]]:
    """("free" | "apply" | "run" | "other", the current job view without its log)."""
    try:
        cur = jobs.current(tail=0)
    except TypeError:                        # a manager whose current() takes no tail
        cur = jobs.current()
    cur = dict(cur or {})
    if cur.get("state") != "running":
        return "free", cur
    kind = cur.get("kind")
    return (kind if kind in ("apply", "run") else "other"), cur


class ApplyQueueRunner:
    """Starts the worker when the slot is free (§3.4). See the module docstring."""

    def __init__(self, app_state: Any, *, enabled: bool, tick_s: float = TICK_S):
        self._state = app_state            # read at every kick (H1); never jobs or a store
        self.enabled = bool(enabled)
        self.tick_s = tick_s
        self._gate_closed = True           # M2: opens only after the start-up pause committed
        self._lock = threading.Lock()
        self._started_job: Optional[str] = None     # the worker job this runner started (L3)
        self.pending_run: Optional[dict[str, Any]] = None   # a search run deferred (§6)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- the gate

    @property
    def gate_closed(self) -> bool:
        return self._gate_closed

    # The handler names are distinct from MailSyncRunner's (`start_timer`, `stop`):
    # pins find the mail timer among the start-up handlers by `__name__`.
    def pause_apply_queue_on_startup(self) -> None:
        """The start-up hook, registered before `start_apply_queue` (M2): drop a stale
        yield (L4) and pause `restarted` when roles wait. The gate opens only when
        both writes went through; on any error it stays closed for this process."""
        store = None
        try:
            store = self._state.store_factory()
            store.queue_clear_yield()
            if store.queue_pause_if_waiting(QueuePause.RESTARTED, utcnow()):
                logger.info("auto-apply queue paused: roles were waiting from the last session")
        except Exception:                   # noqa: BLE001 - fail closed, never block start-up
            logger.exception("auto-apply queue start-up pause failed; the queue stays stopped")
            return
        finally:
            _close(store)
        self._gate_closed = False

    def open_gate(self) -> None:
        """A committed Resume (the owner's fresh click) opens the gate."""
        self._gate_closed = False

    def close_gate(self) -> None:
        """Fail closed for this process (a cancel whose pause could not be written)."""
        self._gate_closed = True

    # ---------------------------------------------------------------- deferred run

    def defer_run(self, opts: dict[str, Any]) -> None:
        """`POST /api/jobs/run` while the worker holds the slot (§6): remember the run;
        the caller has asked the worker to yield (`queue_request_yield`)."""
        with self._lock:
            self.pending_run = dict(opts)

    # ---------------------------------------------------------------- kick

    def kick(self) -> bool:
        """Start the worker if it may run now; True when this call started a job
        (the worker, or a deferred run). Never raises: the caller's write has
        committed already, and the tick retries."""
        if not self.enabled or self._gate_closed:
            return False
        with self._lock:
            try:
                return self._kick()
            except Exception:               # noqa: BLE001 - see the docstring
                logger.exception("auto-apply queue kick failed")
                return False

    def _kick(self) -> bool:
        jobs = self._state.jobs                          # H1: looked up now
        slot, cur = slot_of(jobs)
        if slot != "free":
            return False
        store = self._state.store_factory()
        try:
            self._judge(cur, store)
            if self.pending_run is not None:             # (4) the deferred search run
                opts, self.pending_run = self.pending_run, None
                store.queue_clear_yield()                # L4
                try:
                    jobs.start("run", opts)
                except JobBusy:
                    self.pending_run = opts
                    return False
                logger.info("auto-apply queue: the deferred search run started")
                return True
            if store.queue_pause_state() is not None or not store.queue_positions():
                return False                             # (5)
        finally:
            _close(store)
        try:                                             # (6)
            view = jobs.start("apply", {"queue": True})
        except JobBusy:
            return False
        self._started_job = (view or {}).get("id")
        logger.info("auto-apply worker started (job %s)", self._started_job)
        return True

    def _judge(self, cur: dict[str, Any], store: Any) -> None:
        """(3) How the worker this runner started ended (L2, L3)."""
        if not self._started_job or cur.get("id") != self._started_job:
            return
        self._started_job = None
        code = cur.get("exit_code")
        if code == 0 or code == EXIT_CANCELLED or cur.get("reason") == "cancelled":
            return
        reason = QueuePause.BUSY_ELSEWHERE if code == EXIT_LOCK_HELD else QueuePause.WORKER_FAILED
        store.queue_pause(reason, None, utcnow())
        logger.warning("auto-apply worker ended with exit code %s; queue paused (%s)",
                       code, reason.value)

    # ---------------------------------------------------------------- tick

    def start_apply_queue(self) -> None:
        """A daemon thread kicking every `tick_s` while enabled (the MailSyncRunner
        pattern): the worker starts once the slot frees, a deferred run after it."""
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="apply-queue-tick", daemon=True)
        self._thread.start()

    def stop_apply_queue(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    @property
    def timer_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.wait(self.tick_s):
            self.kick()


def _close(store: Any) -> None:
    close = getattr(store, "close", None)
    if callable(close):
        close()


