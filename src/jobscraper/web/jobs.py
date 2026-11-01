"""Runs and profile refreshes started from the browser, as child processes (M11-T3).

Why a child process and not a thread calling the pipeline. The web layer may
not import `pipeline.py` (PRD 8.2), and it should not want to: a run is minutes
of network and model calls, and a crash in one must not take the web app down.
So the web app does exactly what the user would type - `python -m jobscraper
run --batch-size N` or `profile --refresh` - and the CLI stays the one place
that says how a run behaves.

Why one job at a time. Two runs would plan the same due companies and write the
same rows. The lock lives here, in the web process, and is also written to
`data/jobs/current.json`, so a web app restarted mid-run still knows a job is
in flight: while the recorded process is alive the slot stays taken, and once it
is gone with no exit code captured the job reads `failed` - never `running`
forever. "The recorded process" is the PID plus its creation time (`pid_id`), so
a PID that Windows handed to another program after a reboot does not hold the
slot (C-5). This process only ever kills a process it started itself; a PID read
back from disk may by then belong to something else.

Cancel asks first and kills second (C-4). Each job runs in its own process
group; Cancel sends it CTRL_BREAK_EVENT on Windows (SIGTERM elsewhere), which
the CLI turns into `JobCancelled`, so the run row is marked `failed` with the
reason "cancelled" before the process exits 143. After the grace period (30 s
for a run, which may be inside a long model call; 5 s for the other kinds)
whatever is left is killed (`taskkill /T /F`, falling back to killing the child
itself). A run killed that way never reached its own `finally`, so this side
marks its run row `failed` with the reason "cancelled (killed)" through the
store (D-64): the Runs tab never shows a dead run as running. The job record
then says `reason: "cancelled"`.

Each job's stdout and stderr go to `data/jobs/<utc-stamp>-<kind>.log`, which is
what the Runs tab tails. `command` is injectable so tests run a stub instead of
the real CLI - no network, no model.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from jobscraper.store import utcnow

# `logger`, not `log`: start() already names each job's log file `log`.
logger = logging.getLogger(__name__)

# (kind, options) -> argv. `kind` is "run" or "profile".
CommandBuilder = Callable[[str, dict[str, Any]], list[str]]

KINDS = ("run", "profile", "titles", "companies", "tailor")
RECORD = "current.json"
EXIT_CANCELLED = 143           # the CLI's cancel handler (128 + 15)
KILLED_REASON = "cancelled (killed)"     # stats.reason of a run the web had to kill (D-64)
# src/jobscraper/web/jobs.py -> src
SRC_DIR = Path(__file__).resolve().parents[2]

IDLE = {"id": None, "kind": None, "state": "idle", "started_at": None,
        "finished_at": None, "exit_code": None}


class JobBusy(RuntimeError):
    """A job is already running."""


class JobIdle(RuntimeError):
    """There is no running job to cancel."""


class JobNotOurs(RuntimeError):
    """The running job was started by an earlier web process: no handle on it."""


class JobStuck(RuntimeError):
    """Cancel could not stop the job's process; it is still recorded as running."""


def cli_command(config_path: Optional[str | os.PathLike] = None) -> CommandBuilder:
    """The real command: this Python, the CLI, the app's own config.

    Without `config_path` the child resolves its config exactly as this process
    did - `JOBSCRAPER_CONFIG`, which it inherits, else `config/config.yaml`.
    """
    def build(kind: str, opts: dict[str, Any]) -> list[str]:
        argv = [sys.executable, "-m", "jobscraper"]
        if config_path:
            argv += ["--config", str(config_path)]
        if kind == "run":
            argv += ["run", "--batch-size", str(int(opts["batch_size"]))]
            if opts.get("dry_run"):
                argv.append("--dry-run")
        elif kind == "profile":
            argv += ["profile", "--refresh"]
        elif kind == "titles":
            argv += ["titles", "suggest"]
        elif kind == "companies":
            argv += ["companies", "search"]
        elif kind == "tailor":
            job_id = str(opts.get("job_id", ""))
            if not re.fullmatch(r"[A-Za-z0-9:_-]{1,80}", job_id):
                raise ValueError("tailor needs a job_id of letters, digits, : _ -")
            argv += ["tailor", job_id]
        else:
            raise ValueError(f"unknown job kind {kind!r}")
        return argv
    return build


def child_env() -> dict[str, str]:
    """This environment, plus what a child needs to import the package and to
    write a log the browser can read: UTF-8 (job titles are not cp1252) and
    unbuffered, so lines appear while the run is still going."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SRC_DIR), env.get("PYTHONPATH", "")) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def pid_alive(pid: Optional[int]) -> bool:
    """Whether a process with this PID is running. No third-party dependency."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(int(pid))
    try:
        os.kill(int(pid), 0)                    # signal 0: existence check only
    except ProcessLookupError:
        return False
    except PermissionError:                     # exists, owned by someone else
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    # os.kill(pid, 0) is not an existence check on Windows: signal 0 is
    # CTRL_C_EVENT. Ask the kernel for the process's exit code instead.
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    query_limited_information, still_active, access_denied = 0x1000, 259, 5
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _starttime_from_stat(stat: str) -> Optional[str]:
    """Field 22 (starttime, clock ticks after boot) of a /proc/<pid>/stat line.
    The command name (field 2) may hold spaces and parentheses, so the fields
    are counted from the last ')'."""
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[19] if len(fields) > 19 else None


def process_identity(pid: Optional[int]) -> Optional[str]:
    """Who a live PID is, beyond its number: the process creation time
    (`GetProcessTimes` on Windows, `<boot id>:<start time>` on Linux, `ps
    lstart` elsewhere), or None when it cannot be read.

    A PID alone is not an identity: after a reboot the PID a stale `running`
    record names may belong to another process, and the Runs tab would show the
    job running forever (C-5)."""
    if not pid or pid <= 0:
        return None
    if not sys.platform.startswith("linux"):
        return _identity_elsewhere(int(pid))
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        start = _starttime_from_stat(
            Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return f"{boot}:{start}" if boot and start else None


def _identity_elsewhere(pid: int) -> Optional[str]:
    """Windows: the process creation time (FILETIME); macOS/BSD: `ps -o lstart=`.
    Together with the PID this tells a reused PID from the original process."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)       # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kern, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                            ctypes.byref(kern), ctypes.byref(user)):
                return None
            return f"win:{(created.dwHighDateTime << 32) | created.dwLowDateTime}"
        finally:
            kernel32.CloseHandle(handle)
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"ps:{out}" if out else None


def _looks_like_jobscraper(pid: int) -> bool:
    """Best effort for a record with no identity (written before C-5): the
    process is `python -m jobscraper ...`, which is what `cli_command` starts.
    Unreadable counts as no."""
    try:
        if sys.platform.startswith("linux"):
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace")
        elif os.name == "nt":
            cmd = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                capture_output=True, text=True, timeout=20).stdout
        else:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "-m jobscraper" in " ".join(cmd.lower().split())


def _spawn_kwargs() -> dict[str, Any]:
    """A process group of the job's own, so Cancel can signal the job (and
    anything it started) without the signal reaching the web app's console."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _ask_to_stop(proc: subprocess.Popen) -> None:
    """The polite signal: CTRL_BREAK_EVENT to the job's process group on
    Windows, SIGTERM to its session elsewhere. Failing to send it is not an
    error - the kill after the grace period still follows."""
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        logger.warning("could not signal job pid %s: %s", proc.pid, type(exc).__name__)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the job and everything it started. Windows: `taskkill /T /F`,
    falling back to killing the child itself; POSIX: SIGKILL to its session."""
    if os.name == "nt":
        try:
            done = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                  capture_output=True, timeout=30)
            if done.returncode != 0:
                logger.warning("taskkill exited %s for pid %s", done.returncode, proc.pid)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("taskkill failed for pid %s: %s", proc.pid, type(exc).__name__)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            logger.warning("killpg failed for pid %s: %s", proc.pid, type(exc).__name__)
    try:
        proc.kill()                                  # at least the child itself
    except OSError:
        pass


def tail_lines(path: Path, n: int) -> list[str]:
    """The last `n` lines of a log, read from the end - logs can grow large."""
    if n <= 0 or not path.is_file():
        return []
    block = 64 * 1024
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n:
            step = min(block, pos)
            pos -= step
            fh.seek(pos)
            data = fh.read(step) + data
    return data.decode("utf-8", errors="replace").splitlines()[-n:]


class JobManager:
    """The one background job this web process is allowed at a time."""

    def __init__(self, jobs_dir: Path, command: CommandBuilder,
                 grace_seconds: float = 5.0, keep_logs: int = 50,
                 run_grace_seconds: float = 30.0,
                 store_factory: Optional[Callable[[], Any]] = None):
        self.jobs_dir = Path(jobs_dir)
        self.command = command
        self.grace_seconds = grace_seconds          # profile, titles, companies
        # A run may be inside a model call that answers only every few seconds;
        # its cancel handler runs at the next Python step, so it gets longer (D-64).
        self.run_grace_seconds = run_grace_seconds
        # Opens a store, for marking a killed run's row failed (D-64). None
        # (tests with no database) skips that step.
        self.store_factory = store_factory
        self.keep_logs = keep_logs          # newest N job logs kept on disk
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._record: Optional[dict[str, Any]] = self._load()

    # ---------------------------------------------------------------- public

    def current(self, tail: int = 200) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            return self._view(tail)

    def start(self, kind: str, opts: dict[str, Any],
              tail: int = 200) -> dict[str, Any]:
        """Launch a job. Raises `JobBusy` if one is running."""
        if kind not in KINDS:
            raise ValueError(f"unknown job kind {kind!r}")
        with self._lock:
            self._refresh()
            if self._running():
                raise JobBusy("a job is already running")
            argv = self.command(kind, opts)
            self.jobs_dir.mkdir(parents=True, exist_ok=True)
            job_id, log = self._new_log(kind)
            with open(log, "xb") as fh:
                # The header names the verb, not this machine's paths.
                shown = argv[argv.index("-m") + 1:] if "-m" in argv else [kind]
                fh.write(f"$ {' '.join(shown)}\n".encode("utf-8"))
                fh.flush()
                try:
                    self._proc = subprocess.Popen(
                        argv, stdout=fh, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, env=child_env(), close_fds=True,
                        **_spawn_kwargs())
                except OSError as exc:
                    reason = exc.strerror or type(exc).__name__   # no paths
                    fh.write(f"could not start: {reason}\n".encode("utf-8"))
                    self._record = self._new_record(job_id, kind, log, None)
                    self._finish(None)
                    logger.error("job %s (%s) could not start: %s", job_id, kind, reason)
                    raise
            self._record = self._new_record(job_id, kind, log, self._proc.pid)
            self._save()
            self._prune_logs()
            logger.info("job %s (%s) started, pid %s", job_id, kind, self._proc.pid)
            return self._view(tail)

    def cancel(self, tail: int = 200) -> dict[str, Any]:
        """Ask the running job to stop, then kill it after the grace period.
        `JobStuck` if the process will not die (it stays recorded as running).

        The signal and the waits happen outside the lock, so other requests
        (the Runs tab polling) are not held for the grace period."""
        with self._lock:
            self._refresh()
            if not self._running():
                raise JobIdle("no job is running")
            if self._proc is None:
                raise JobNotOurs(
                    f"the running job (PID {self._record['pid']}) was started by an "
                    "earlier web app process and cannot be cancelled from here")
            proc, job_id = self._proc, self._record.get("id")
            kind, since = self._record.get("kind"), self._record.get("started_at")
        grace = self.run_grace_seconds if kind == "run" else self.grace_seconds
        already = proc.poll()               # it may have ended since the refresh
        cancelled = already is None
        killed = False
        if already is not None:
            code = already
        else:
            code, killed = self._terminate(proc, grace)
        if killed and kind == "run":
            # The child died without its `finally`: its run row would read
            # `running` until per_run_timeout reaps it. Say what happened now.
            self._mark_killed_run(since)
        with self._lock:
            if self._record and self._record.get("id") == job_id and self._running():
                if killed:
                    self._append_log(f"[did not stop within {grace:g}s; killed]")
                self._append_log("[cancelled from the web app]" if cancelled else
                                 "[the job had already ended when cancel arrived]")
                self._finish(code, cancelled=cancelled)
            return self._view(tail)

    # ---------------------------------------------------------------- state

    def _running(self) -> bool:
        return bool(self._record) and self._record.get("state") == "running"

    def _refresh(self) -> None:
        """Settle a running job that has ended since the last request."""
        if not self._running():
            return
        if self._proc is not None:
            code = self._proc.poll()
            if code is not None:
                self._finish(code)
        elif not self._recorded_process_alive(self._record):
            self._finish(None)                  # gone, outcome unknown: failed

    def _recorded_process_alive(self, rec: dict[str, Any]) -> bool:
        """The recorded job's process still runs: its PID is alive and, where
        the record has an identity, it is the same process (not a PID reused
        after a reboot)."""
        pid = rec.get("pid")
        if not pid_alive(pid):
            return False
        recorded = rec.get("pid_id")
        if recorded:
            return process_identity(pid) == recorded    # unreadable or different: not it
        # A record from before C-5 has no identity: ask what the process is,
        # once - if it is ours, remember who it is so the next poll is cheap.
        if not _looks_like_jobscraper(int(pid)):
            return False
        rec["pid_id"] = process_identity(pid)
        self._save()
        return True

    def _finish(self, code: Optional[int], cancelled: bool = False) -> None:
        rec = self._record
        rec["state"] = "succeeded" if code == 0 and not cancelled else "failed"
        rec["exit_code"] = code
        if cancelled or code == EXIT_CANCELLED:
            rec["reason"] = "cancelled"          # the SPA can say "cancelled", not "failed"
        rec["finished_at"] = utcnow()
        self._proc = None
        self._save()
        # The job's own log file has the detail; this says which one to open.
        (logger.info if rec["state"] == "succeeded" else logger.warning)(
            "job %s (%s) %s, exit code %s", rec.get("id"), rec.get("kind"),
            rec.get("reason") or rec["state"], code)

    def _terminate(self, proc: subprocess.Popen,
                   grace: float) -> tuple[Optional[int], bool]:
        """Ask the job to stop; after `grace` seconds kill the whole tree (a
        run may have started a process of its own). Returns the exit code once
        it is dead, and whether it had to be killed; `JobStuck` if it is still
        alive after that."""
        _ask_to_stop(proc)
        try:
            return proc.wait(grace), False
        except subprocess.TimeoutExpired:
            pass
        logger.warning("job pid %s did not stop within %gs; killing it", proc.pid, grace)
        _kill_tree(proc)
        try:
            return proc.wait(self.grace_seconds), True
        except subprocess.TimeoutExpired:
            logger.error("pid %s did not exit after a kill", proc.pid)
            raise JobStuck("the job could not be stopped; it is still running") from None

    def _mark_killed_run(self, since: Optional[str]) -> None:
        """Mark the killed job's run row `failed`, reason "cancelled (killed)".

        The row is found as the run still `running` that started at or after
        the job did - one job at a time, so that is this job's run (a dry run
        has none, and then nothing changes). Never raises: the kill already
        happened, and the reaper is still the fallback."""
        if self.store_factory is None or not since:
            return
        store = None
        try:
            store = self.store_factory()
            n = store.fail_running_runs(since, KILLED_REASON)
            logger.warning("marked %s killed run(s) failed", n)
        except Exception:                   # noqa: BLE001 - see the docstring
            logger.exception("could not mark the killed run failed")
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()

    def _view(self, tail: int) -> dict[str, Any]:
        if not self._record:
            return {**IDLE, "log": []}
        rec = self._record
        view = {k: rec.get(k) for k in IDLE}
        if rec.get("reason"):
            view["reason"] = rec["reason"]          # "cancelled" (C-4)
        view["log"] = tail_lines(self.jobs_dir / Path(str(rec.get("log") or "")).name,
                                 tail) if rec.get("log") else []
        return view

    # ---------------------------------------------------------------- files

    def _new_log(self, kind: str) -> tuple[str, Path]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        job_id, n = f"{stamp}-{kind}", 1
        while (self.jobs_dir / f"{job_id}.log").exists():
            job_id, n = f"{stamp}-{kind}-{n}", n + 1
        return job_id, self.jobs_dir / f"{job_id}.log"

    @staticmethod
    def _new_record(job_id: str, kind: str, log: Path,
                    pid: Optional[int]) -> dict[str, Any]:
        return {"id": job_id, "kind": kind, "state": "running",
                "started_at": utcnow(), "finished_at": None, "exit_code": None,
                "pid": pid, "pid_id": process_identity(pid), "log": log.name}

    def _prune_logs(self) -> None:
        """Keep the newest `keep_logs` logs. Names start with a UTC stamp, so
        name order is age order; the current job's log is never removed."""
        current = self._record.get("log") if self._record else None
        logs = sorted(self.jobs_dir.glob("*.log"), key=lambda p: p.name)
        for old in logs[:max(0, len(logs) - self.keep_logs)]:
            if old.name != current:
                old.unlink(missing_ok=True)

    def _append_log(self, line: str) -> None:
        if self._record and self._record.get("log"):
            with open(self.jobs_dir / self._record["log"], "ab") as fh:
                fh.write(f"{line}\n".encode("utf-8"))

    def _load(self) -> Optional[dict[str, Any]]:
        try:
            rec = json.loads((self.jobs_dir / RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(rec, dict) or rec.get("kind") not in KINDS:
            return None
        return rec

    def _save(self) -> None:
        """Atomic: a crash mid-write must not leave a half record behind."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.jobs_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._record, fh)
            os.replace(tmp, self.jobs_dir / RECORD)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
