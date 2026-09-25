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
in flight: while the recorded PID is alive the slot stays taken, and once it is
gone with no exit code captured the job reads `failed` - never `running` forever.
This process only ever kills a process it started itself; a PID read back from
disk may by then belong to something else.

Each job's stdout and stderr go to `data/jobs/<utc-stamp>-<kind>.log`, which is
what the Runs tab tails. `command` is injectable so tests run a stub instead of
the real CLI - no network, no model.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from jobscraper.store import utcnow

# (kind, options) -> argv. `kind` is "run" or "profile".
CommandBuilder = Callable[[str, dict[str, Any]], list[str]]

KINDS = ("run", "profile")
RECORD = "current.json"
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
                 grace_seconds: float = 5.0, keep_logs: int = 50):
        self.jobs_dir = Path(jobs_dir)
        self.command = command
        self.grace_seconds = grace_seconds
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
                        stdin=subprocess.DEVNULL, env=child_env(), close_fds=True)
                except OSError as exc:
                    reason = exc.strerror or type(exc).__name__   # no paths
                    fh.write(f"could not start: {reason}\n".encode("utf-8"))
                    self._record = self._new_record(job_id, kind, log, None)
                    self._finish(None)
                    raise
            self._record = self._new_record(job_id, kind, log, self._proc.pid)
            self._save()
            self._prune_logs()
            return self._view(tail)

    def cancel(self, tail: int = 200) -> dict[str, Any]:
        """Terminate the running job, then kill it after the grace period."""
        with self._lock:
            self._refresh()
            if not self._running():
                raise JobIdle("no job is running")
            if self._proc is None:
                raise JobNotOurs(
                    f"the running job (PID {self._record['pid']}) was started by an "
                    "earlier web app process and cannot be cancelled from here")
            code = self._terminate(self._proc)
            self._append_log("[cancelled from the web app]")
            self._finish(code)
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
        elif not pid_alive(self._record.get("pid")):
            self._finish(None)                  # gone, outcome unknown: failed

    def _finish(self, code: Optional[int]) -> None:
        rec = self._record
        rec["state"] = "succeeded" if code == 0 else "failed"
        rec["exit_code"] = code
        rec["finished_at"] = utcnow()
        self._proc = None
        self._save()

    def _terminate(self, proc: subprocess.Popen) -> Optional[int]:
        if os.name == "nt":
            # The whole tree: a run may have started a model CLI of its own.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        else:
            proc.terminate()
        try:
            return proc.wait(self.grace_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait(self.grace_seconds)

    def _view(self, tail: int) -> dict[str, Any]:
        if not self._record:
            return {**IDLE, "log": []}
        rec = self._record
        view = {k: rec.get(k) for k in IDLE}
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
                "pid": pid, "log": log.name}

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
