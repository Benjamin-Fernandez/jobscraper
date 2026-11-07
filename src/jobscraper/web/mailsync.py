"""Email updates while the web app runs (F-50d; mail_status_design §10.1).

Why a child process and not a thread. The sync reads IMAP and may call the
local model; `web/` may import neither `imapread` nor the orchestrator (MS §2.2
rule 4), and a hang or a crash in a sync must not take the web app down. So,
exactly like `web/jobs.py`, the web app runs what the owner would type:
`python -m jobscraper mail sync --trigger <t>`.

Why not the JobManager. A sync is short and frequent and must not take the run
/ apply slot (F-50d). It has its own single-flight lease in the database
(`store.mail_run_begin`, MS §10.2), which also guards the CLI and a second web
process; this runner only makes sure its own previous child has exited.

The password. `connect` and `set_password` run a short child whose stdin is the
app password plus a newline (MS §4): never argv, never env, never a file. The
password reaches this module wrapped in `Secret` and is revealed only into the
pipe. Its child's output is parsed as one JSON line and never logged.

`command` is injectable (`MailCommand`), so tests stub the children. The timer
starts only in `create_app(mail_timer=True)` (MS §10.1): tests and dev instances
default to off.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from jobscraper.web.jobs import child_env, _spawn_kwargs

logger = logging.getLogger(__name__)

# (kind, options) -> argv. Kinds: "sync" {trigger, account?, defer_model?},
# "add" {address?, use_application?, consent}, "set_password" {account_id}.
MailCommand = Callable[[str, dict[str, Any]], list[str]]

TRIGGERS = ("startup", "timer", "manual", "connect", "cli")
CHILD_TIMEOUT_S = 45            # the connect / set-password child (MS §4)
KEEP_LOGS = 20                  # newest sync logs kept in data/jobs/mail/ (MS §10.1)


def cli_mail_command(config_path: Optional[str] = None) -> MailCommand:
    """The real children: the CLI verbs of MS §10.3, run with this Python."""
    def build(kind: str, opts: dict[str, Any]) -> list[str]:
        argv = [sys.executable, "-m", "jobscraper"]
        if config_path:
            argv += ["--config", str(config_path)]
        if kind == "sync":
            trigger = str(opts.get("trigger") or "manual")
            if trigger not in TRIGGERS:
                raise ValueError(f"unknown mail sync trigger {trigger!r}")
            argv += ["mail", "sync", "--trigger", trigger]
            if opts.get("account") is not None:
                argv += ["--account", str(int(opts["account"]))]
            if opts.get("defer_model"):
                argv.append("--defer-model")
        elif kind == "add":
            argv += ["mail", "accounts", "add"]
            if opts.get("use_application"):
                argv.append("--use-application")
            else:
                argv += ["--address", str(opts["address"]), "--password-stdin"]
            argv += ["--consent", str(opts["consent"]), "--json"]
        elif kind == "set_password":
            argv += ["mail", "accounts", "set-password", "--id",
                     str(int(opts["account_id"])), "--password-stdin", "--json"]
        else:
            raise ValueError(f"unknown mail command {kind!r}")
        return argv
    return build


class MailSyncRunner:
    """The timer, "Check now" and the short connect children (MS §10.1)."""

    def __init__(self, cfg: Any, data_dir: Path, store_factory: Callable[[], Any],
                 job_manager: Any, command: MailCommand,
                 clock: Callable[[], float] = time.time, keep_logs: int = KEEP_LOGS):
        self.cfg = cfg
        self.log_dir = Path(data_dir) / "jobs" / "mail"
        self.store_factory = store_factory
        self.job_manager = job_manager
        self.command = command
        self.clock = clock
        self.keep_logs = keep_logs
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._started_at: Optional[str] = None
        self._next_at: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- timer

    def start_timer(self) -> None:
        """A daemon thread: first tick after `startup_delay_s`, then every
        `interval_min`, or `catchup_delay_s` after a `partial` run (MS §10.1)."""
        if self._thread is not None:
            return
        ms = self.cfg.mail_status
        self._next_at = self.clock() + ms.startup_delay_s
        self._thread = threading.Thread(target=self._loop, name="mail-sync-timer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the timer (the app's shutdown). A running child finishes on its own."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._next_at = None

    @property
    def timer_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        first = True
        while not self._stop.is_set():
            wait = max(0.0, (self._next_at or self.clock()) - self.clock())
            if self._stop.wait(min(wait, 5.0)):
                return
            if self.clock() < (self._next_at or 0):
                continue
            try:
                self.tick("startup" if first else "timer")
            except Exception:                       # noqa: BLE001 - the timer must survive
                logger.exception("mail sync tick failed")
            first = False
            self._next_at = self.clock() + self._next_delay()

    def _next_delay(self) -> float:
        ms = self.cfg.mail_status
        last = self._last_run()
        if last and last.get("state") == "partial":
            return float(ms.catchup_delay_s)
        return float(ms.interval_min) * 60.0

    def tick(self, trigger: str = "timer") -> bool:
        """One timer tick: spawn only if mail_status is enabled, some enabled
        account isn't paused, and our previous child has exited. PAUSED
        accounts are never retried by the timer (F-50p); the child skips them
        for `startup`/`timer` too."""
        if not self.cfg.mail_status.enabled or not self._has_live_account():
            return False
        try:
            self._spawn(trigger)
        except MailBusy:
            return False
        return True

    # ---------------------------------------------------------------- triggers

    def trigger(self, trigger: str = "manual", account: Optional[int] = None) -> dict[str, Any]:
        """"Check now" (or after a connect): spawn now. Raises `MailBusy` while
        our own child runs or another process holds a fresh lease."""
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger {trigger!r}")
        if self._lease_held():
            raise MailBusy("a check is already running")
        self._spawn(trigger, account)
        return self.status()

    def _spawn(self, trigger: str, account: Optional[int] = None) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise MailBusy("a check is already running")
            opts: dict[str, Any] = {"trigger": trigger}
            if account is not None:
                opts["account"] = int(account)
            if self._model_busy():
                opts["defer_model"] = True
            argv = self.command("sync", opts)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log = self._new_log()
            with open(log, "xb") as fh:
                shown = argv[argv.index("-m") + 1:] if "-m" in argv else ["mail", "sync"]
                fh.write(f"$ {' '.join(shown)}\n".encode("utf-8"))
                fh.flush()
                self._proc = subprocess.Popen(
                    argv, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    env=child_env(), close_fds=True, **_spawn_kwargs())
            self._started_at = _now()
            self._prune_logs(log.name)
            logger.info("mail sync started (%s), pid %s", trigger, self._proc.pid)

    def _model_busy(self) -> bool:
        """MS §10.1 model courtesy: a run or an apply attempt has the GPU."""
        if self.job_manager is None:
            return False
        try:
            return self.job_manager.current(tail=1).get("state") == "running"
        except Exception:                           # noqa: BLE001
            return False

    # ---------------------------------------------------------------- short children

    def connect(self, address: str, password: Any, consent_version: str) -> dict[str, Any]:
        """`mail accounts add --address A --password-stdin` (MS §4). `password` is
        a `Secret`. Returns the child's JSON result (`{"result": "ok",
        "account_id": N}` or `{"result": <code>}`); on ok a `connect` sync starts."""
        return self._short("add", {"address": address, "consent": consent_version}, password)

    def use_application(self, consent_version: str) -> dict[str, Any]:
        """`mail accounts add --use-application` (F-50b): no password needed."""
        return self._short("add", {"use_application": True, "consent": consent_version}, None)

    def set_password(self, account_id: int, password: Any) -> dict[str, Any]:
        """`mail accounts set-password --id N --password-stdin`; on ok a sync starts."""
        return self._short("set_password", {"account_id": int(account_id)}, password)

    def _short(self, kind: str, opts: dict[str, Any], password: Any) -> dict[str, Any]:
        argv = self.command(kind, opts)
        data = (password.reveal() + "\n") if password is not None else ""
        try:
            done = subprocess.run(argv, input=data.encode("utf-8"), capture_output=True,
                                  timeout=CHILD_TIMEOUT_S, env=child_env(), close_fds=True)
        except subprocess.TimeoutExpired:
            logger.warning("mail %s child timed out", kind)
            return {"result": "network"}
        except OSError as exc:
            logger.warning("mail %s child could not start: %s", kind, type(exc).__name__)
            return {"result": "internal"}
        result = _last_json(done.stdout)
        if not isinstance(result.get("result"), str):
            # The output is never logged: it could hold what the child echoed.
            logger.warning("mail %s child gave no result (exit %s)", kind, done.returncode)
            result = {"result": "internal"}
        logger.info("mail %s child: %s", kind, result["result"])
        if result["result"] == "ok":
            try:
                self.trigger("connect", result.get("account_id", opts.get("account_id")))
            except MailBusy:
                pass
        return result

    # ---------------------------------------------------------------- views

    def status(self) -> dict[str, Any]:
        """`{running, started_at, next_at}`: this runner's own child and timer;
        the rest of the state is read from the store (MS §10.1)."""
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
        next_at = None
        if self._next_at is not None and self.timer_running:
            next_at = datetime.fromtimestamp(self._next_at, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S")
        return {"running": running or self._lease_held(),
                "started_at": self._started_at if running else None, "next_at": next_at}

    def _with_store(self, fn: Callable[[Any], Any], default: Any) -> Any:
        store = None
        try:
            store = self.store_factory()
            return fn(store)
        except Exception:                           # noqa: BLE001 - a view, not a write
            logger.exception("mail runner could not read the store")
            return default
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()

    def _last_run(self) -> Optional[dict[str, Any]]:
        return self._with_store(lambda s: s.mail_last_run(), None)

    def _lease_held(self) -> bool:
        """Another process (the CLI, a second web app) holds a fresh lease."""
        ttl = float(self.cfg.mail_status.sync_timeout_s) + 60
        last = self._last_run()
        if not last or last.get("state") != "running":
            return False
        try:
            beat = datetime.strptime(str(last["heartbeat_at"]), "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc).timestamp()
        except (KeyError, ValueError):
            return False
        return beat > self.clock() - ttl

    def _has_live_account(self) -> bool:
        def live(store: Any) -> bool:
            return any(a.get("state") != "paused" for a in store.mail_accounts(enabled_only=True))
        return bool(self._with_store(live, False))

    # ---------------------------------------------------------------- logs

    def _new_log(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log, n = self.log_dir / f"{stamp}-mailsync.log", 1
        while log.exists():
            log, n = self.log_dir / f"{stamp}-mailsync-{n}.log", n + 1
        return log

    def _prune_logs(self, current: str) -> None:
        logs = sorted(self.log_dir.glob("*-mailsync*.log"), key=lambda p: p.name)
        for old in logs[:max(0, len(logs) - self.keep_logs)]:
            if old.name != current:
                old.unlink(missing_ok=True)


class MailBusy(RuntimeError):
    """A sync is already running (our child, or another process's lease)."""


def gmail_url(address: Optional[str], gm_msgid: Any) -> Optional[str]:
    """A link to the message in the owner's own Gmail (MS §11.1): built from the
    account address and X-GM-MSGID in hex (the web id), never taken from mail.
    None after a disconnect (no address) or for an unreadable id."""
    if not address:
        return None
    try:
        hexid = format(int(str(gm_msgid)), "x")
    except (TypeError, ValueError):
        return None
    from urllib.parse import quote
    return f"https://mail.google.com/mail/?authuser={quote(str(address), safe='@')}#all/{hexid}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _last_json(out: bytes) -> dict[str, Any]:
    """The last stdout line that is a JSON object, or {}."""
    for line in reversed((out or b"").decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                v = json.loads(line)
            except ValueError:
                continue
            if isinstance(v, dict):
                return v
    return {}
