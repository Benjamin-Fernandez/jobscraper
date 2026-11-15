"""Q-126 lane E1 pins: the model service in `backends.py` (D-214, D-217;
docs/architecture/ollama_autostart_design.md §2, §6, §9 T1-T10, T15).

RED UNTIL eng/Q-126-E1 MERGES. Written against the design's names and seams, not
against code: every test reaches `backends.<name>` at call time, so before E1 each
one fails on a missing attribute (a per-test count, not an import error). Do not
weaken a pin to make it pass; if the engineer names a seam differently, fix the one
helper that adapts it (`Rig`, `_ensure`, `_spawn_detached` call) and say so in the
outbox. ASSUMED seam shapes (the design names the seams but not their signatures):

  http   an httpx.Client-like object: `get(url, **kw)` / `post(url, **kw)` returning a
         response with `.status_code`, `.json()`, `.raise_for_status()`. A refused port
         raises httpx.ConnectError, a slow one httpx.TimeoutException.
  spawn  `spawn(argv, env)`; argv and env may also arrive as keywords (the fake takes
         both). The env dict is the full environment plus OLLAMA_HOST.
  find   `find(budget)` -> a path string or None.
  clock/sleep   `clock()` is monotonic seconds; `sleep(s)` advances it (the fake).
  lock age   judged by the lock file's mtime against `time.time()` (a file's age cannot
         come from a fake monotonic clock).

Nothing here starts a process, opens a socket or touches port 11434: every transport
is a fake, the executable path is made up, and `_spawn_detached` is called only with
`subprocess.Popen` replaced by a recorder (and only for its REFUSALS).
"""
from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from contextlib import contextmanager
from pathlib import Path

import httpx

from jobscraper import backends as B

URL = "http://127.0.0.1:11434"
TAG = "qwen3:14b"
IS_WIN = os.name == "nt"
EXE_NAME = "ollama.exe" if IS_WIN else "ollama"


def _resp(status=200, body=None, bad_json=False):
    r = types.SimpleNamespace(status_code=status)
    def _json():
        if bad_json:
            raise ValueError("not json")
        return body
    r.json = _json
    def _raise():
        if status >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=r)
    r.raise_for_status = _raise
    return r


def _answer(kind):
    if kind == "ollama":
        return _resp(200, {"version": "0.5.1"})
    if kind == "refused":
        raise httpx.ConnectError("refused")
    if kind == "timeout":
        raise httpx.ReadTimeout("slow")
    if kind == "other":
        return _resp(404, {"error": "not ollama"})
    if kind == "other_nojson":
        return _resp(200, None, bad_json=True)
    if kind == "other_noversion":
        return _resp(200, {"hello": "world"})
    raise AssertionError(kind)


class Clock:
    """Fake monotonic clock. `sleep` advances it and yields the real CPU for a moment
    so a helper thread (a warm call, a second caller) can make progress."""
    def __init__(self):
        self.now = 0.0
        self.sleeps = 0
        self.hook = None
        self._mu = threading.Lock()

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        with self._mu:
            self.now += float(seconds)
            self.sleeps += 1
            n = self.sleeps
        if self.hook:
            self.hook(n)
        time.sleep(0.004)


class FakeHttp:
    def __init__(self, rig):
        self.rig = rig
        self.calls = []                       # (method, url)

    def _record(self, method, url, kw):
        with self.rig.mu:
            self.calls.append((method, url))
            self.rig.last_kw = dict(kw)

    def get(self, url, *a, **kw):
        self._record("GET", url, kw)
        if url.endswith("/api/version"):
            return _answer(self.rig.next_version())
        if url.endswith("/api/tags"):
            return _resp(200, {"models": [{"name": n} for n in self.rig.tags]})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, *a, **kw):
        self._record("POST", url, kw)
        return _resp(200, {})

    def close(self):
        pass


class Rig:
    """Everything `ensure_model_running` is allowed to touch, faked."""
    def __init__(self, before=("ollama",), after=("ollama",), tags=(TAG,), exe="auto",
                 alive=True, spawn_error=None, spawn_delay=0.0):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        self.lock_dir = self.dir / "locks"
        self.lock_dir.mkdir()
        self.before, self.after = list(before), list(after)
        self.tags = list(tags)
        self.exe = str(self.dir / "Ollama" / EXE_NAME) if exe == "auto" else exe
        self.alive = alive
        self.spawn_error = spawn_error
        self.spawn_delay = spawn_delay
        self.mu = threading.Lock()
        self.clock = Clock()
        self.http = FakeHttp(self)
        self.spawns = []                      # dicts: argv, env, kw, lock_pid, version_gets
        self.find_calls = 0
        self.alive_calls = []
        self.states = []
        self.last_kw = {}
        self._i_before = self._i_after = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    # -- the seams ---------------------------------------------------------
    def next_version(self):
        with self.mu:
            if self.spawns:
                s, i = self.after, self._i_after
                self._i_after += 1
            else:
                s, i = self.before, self._i_before
                self._i_before += 1
        return s[min(i, len(s) - 1)]

    def spawn(self, *args, **kw):
        argv = args[0] if args else kw.get("argv") or kw.get("args") or kw.get("cmd")
        env = args[1] if len(args) > 1 else next((v for k, v in kw.items() if isinstance(v, dict)), None)
        if self.spawn_error:
            raise self.spawn_error
        locks = list(self.lock_dir.glob("jobscraper-ollama-*.lock"))
        lock_pid = locks[0].read_text().strip() if locks else None
        time.sleep(self.spawn_delay)
        with self.mu:
            self.spawns.append({"argv": list(argv), "env": dict(env or {}), "kw": kw,
                                "lock_pid": lock_pid,
                                "version_gets": sum(1 for m, u in self.http.calls
                                                    if u.endswith("/api/version"))})

    def find(self, *a, **kw):
        self.find_calls += 1
        return self.exe

    def pid_alive(self, pid):
        self.alive_calls.append(pid)
        return self.alive(pid) if callable(self.alive) else bool(self.alive)

    # -- helpers -----------------------------------------------------------
    def backend(self, url=URL, model=TAG, cls=None):
        return (cls or B.OllamaBackend)(url=url, model=model, client=self.http)

    def lock_path(self, port=11434):
        return self.lock_dir / f"jobscraper-ollama-{port}.lock"

    def plant_lock(self, text, age=0.0, port=11434):
        p = self.lock_path(port)
        p.write_text(text, encoding="utf-8")
        if age:
            t = time.time() - age
            os.utime(p, (t, t))
        return p

    def ensure(self, *, autostart=True, backend="default", **kw):
        be = self.backend() if backend == "default" else backend
        kw.setdefault("on_state", self.states.append)
        return B.ensure_model_running(
            {"ollama_url": URL, "ollama_model": TAG}, autostart=autostart, backend=be,
            spawn=self.spawn, find=self.find, http=self.http, pid_alive=self.pid_alive,
            clock=self.clock, sleep=self.clock.sleep, lock_dir=self.lock_dir, **kw)

    def gets(self, suffix):
        return [u for m, u in self.http.calls if m == "GET" and u.endswith(suffix)]

    def locks_left(self):
        return list(self.lock_dir.glob("jobscraper-ollama-*.lock"))


# --------------------------------------------------------------------------
# T1, T2: already answering, or nothing listening
# --------------------------------------------------------------------------

def test_an_answering_ollama_is_ready_and_nothing_is_spawned():
    with Rig(before=["ollama"]) as rig:
        r = rig.ensure()
        assert r.code == "ready" and r.ok and r.started is False
        assert rig.spawns == [] and rig.find_calls == 0
        assert len(rig.gets("/api/version")) == 1              # the first answer wins at once
        assert rig.locks_left() == [] and rig.states == []
        assert not any(m == "POST" for m, _ in rig.http.calls)  # load=False: no generate


def test_model_ready_is_a_frozen_dataclass_with_ok():
    import dataclasses
    r = B.ModelReady("ready")
    assert dataclasses.is_dataclass(r) and r.ok and r.started is False and r.detail == ""
    assert not B.ModelReady("not_installed").ok
    try:
        r.code = "x"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ModelReady must be frozen")


def test_nothing_listening_spawns_exactly_once_with_fixed_argv_and_the_lock_pid():
    with Rig(before=["refused"], after=["ollama"]) as rig:
        r = rig.ensure()
        assert r.ok and r.started is True
        assert len(rig.spawns) == 1
        s = rig.spawns[0]
        assert s["argv"] == [rig.exe, "serve"]                     # fixed argv, no shell string
        assert s["env"].get("OLLAMA_HOST") == "127.0.0.1:11434"
        assert not s["kw"].get("shell")
        assert s["version_gets"] >= 3                              # three refused tries first
        assert s["lock_pid"] == str(os.getpid())                   # the creator's PID, one line
        assert rig.locks_left() == []                              # released afterwards
        assert "starting" in rig.states


def test_a_start_has_no_pull_and_no_unexpected_request():
    with Rig(before=["refused"]) as rig:
        rig.ensure()
        assert all("/api/pull" not in u for _, u in rig.http.calls)


# --------------------------------------------------------------------------
# T3: finding the program
# --------------------------------------------------------------------------

def test_program_not_found_is_not_installed_with_the_tag_and_no_spawn():
    with Rig(before=["refused"], exe=None) as rig:
        r = rig.ensure()
        assert r.code == "not_installed" and not r.ok and r.detail == TAG
        assert rig.spawns == [] and rig.locks_left() == []


def _mkexe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    return path


def _env(tmp: Path, *path_dirs, **extra):
    env = {"PATH": os.pathsep.join(str(d) for d in path_dirs),
           "LOCALAPPDATA": str(tmp / "localappdata"), "ProgramFiles": str(tmp / "programfiles"),
           "HOME": str(tmp / "home")}
    env.update(extra)
    return env


def _same(found, expected: Path) -> bool:
    return found is not None and Path(found).resolve() == Path(expected).resolve()


@contextmanager
def _which_forbidden():
    real = shutil.which
    def boom(*a, **k):
        raise AssertionError("find_ollama must never call shutil.which (C3)")
    shutil.which = boom
    try:
        yield
    finally:
        shutil.which = real


def test_find_ollama_ignores_the_cwd_the_checkout_and_relative_path_entries():
    if not IS_WIN:
        return      # the default-location table differs; the rule under test is the same
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t, _which_forbidden():
        tmp = Path(t)
        cwd, checkout = tmp / "cwd", tmp / "checkout"
        _mkexe(cwd / EXE_NAME)
        _mkexe(checkout / "tools" / EXE_NAME)
        _mkexe(tmp / "rel" / EXE_NAME)
        env = _env(tmp, ".", "rel", cwd, checkout / "tools")
        found = B.find_ollama({}, env, cwd=cwd, checkout=checkout)
        assert found is None, found


def test_find_ollama_prefers_default_install_over_path_and_skips_shims():
    if not IS_WIN:
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t, _which_forbidden():
        tmp = Path(t)
        on_path = _mkexe(tmp / "bin" / EXE_NAME)
        (tmp / "shim").mkdir()
        (tmp / "shim" / "ollama.cmd").write_text("@echo hi")
        (tmp / "shim" / "ollama.bat").write_text("@echo hi")
        env = _env(tmp, tmp / "shim", tmp / "bin")
        cwd, checkout = tmp / "cwd", tmp / "checkout"
        assert _same(B.find_ollama({}, env, cwd=cwd, checkout=checkout), on_path)
        default = _mkexe(tmp / "localappdata" / "Programs" / "Ollama" / EXE_NAME)
        assert _same(B.find_ollama({}, env, cwd=cwd, checkout=checkout), default)
        # no program at all: only a shim on PATH
        env2 = _env(tmp / "nowhere", tmp / "shim")
        assert B.find_ollama({}, env2, cwd=cwd, checkout=checkout) is None


def test_a_configured_path_must_be_the_real_program_and_is_fatal_when_wrong():
    if not IS_WIN:
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t, _which_forbidden():
        tmp = Path(t)
        good = _mkexe(tmp / "mine" / EXE_NAME)
        on_path = _mkexe(tmp / "bin" / EXE_NAME)                 # a valid fall-through target
        env = _env(tmp, tmp / "bin")
        cwd, checkout = tmp / "cwd", tmp / "checkout"
        assert _same(B.find_ollama({"ollama_path": str(good)}, env, cwd=cwd, checkout=checkout), good)
        for bad in (tmp / "mine" / "ollama.bat", tmp / "mine" / "cmd.exe",
                    tmp / "mine" / "ollama app.exe", Path("relative") / EXE_NAME,
                    tmp / "mine" / "missing" / EXE_NAME):
            if bad.suffix and bad.parent.exists() and not bad.exists():
                bad.write_bytes(b"MZ")
            got = B.find_ollama({"ollama_path": str(bad)}, env, cwd=cwd, checkout=checkout)
            assert got is None, (str(bad), got)                  # never falls through to PATH
        assert on_path.exists()


# --------------------------------------------------------------------------
# T4: when a start is not allowed
# --------------------------------------------------------------------------

def test_autostart_off_never_spawns_and_reports_not_running():
    with Rig(before=["refused"]) as rig:
        r = rig.ensure(autostart=False)
        assert r.code == "not_running" and rig.spawns == [] and rig.find_calls == 0


def test_a_non_local_url_or_cloud_tag_never_spawns():
    for url, model in (("http://ollama:11434", TAG), ("http://192.168.1.20:11434", TAG),
                       ("https://api.example.com", TAG), (URL, "qwen3:cloud"),
                       (URL, "gpt-oss:120b-cloud")):
        with Rig(before=["refused"]) as rig:
            r = rig.ensure(backend=rig.backend(url=url, model=model))
            assert r.code == "not_running", (url, model, r)
            assert rig.spawns == [] and rig.locks_left() == [], (url, model)


def test_ipv6_loopback_gets_bracketed_host_port_and_a_url_without_a_port_is_not_started():
    with Rig(before=["refused"], after=["ollama"]) as rig:
        r = rig.ensure(backend=rig.backend(url="http://[::1]:11500"))
        assert r.started and rig.spawns[0]["env"]["OLLAMA_HOST"] == "[::1]:11500"
    with Rig(before=["refused"]) as rig:
        r = rig.ensure(backend=rig.backend(url="http://127.0.0.1"))
        assert r.code == "not_running" and rig.spawns == []


def test_a_non_default_port_names_the_lock_and_the_host():
    with Rig(before=["refused"], after=["ollama"]) as rig:
        seen = []
        orig = rig.spawn
        def spy(*a, **k):
            seen.append(sorted(p.name for p in rig.lock_dir.glob("*.lock")))
            return orig(*a, **k)
        rig.spawn = spy
        r = rig.ensure(backend=rig.backend(url="http://localhost:12000"))
        assert r.ok and seen == [["jobscraper-ollama-12000.lock"]]
        assert rig.spawns[0]["env"]["OLLAMA_HOST"].endswith(":12000")


# --------------------------------------------------------------------------
# T5, T6, T6b: failures and the ping's three tries
# --------------------------------------------------------------------------

def test_spawn_that_raises_oserror_is_start_failed_the_program_wouldnt_start():
    with Rig(before=["refused"], spawn_error=OSError("no")) as rig:
        r = rig.ensure()
        assert r.code == "start_failed" and "wouldn't start" in r.detail
        assert rig.locks_left() == []


def test_no_answer_within_the_start_wait_is_start_failed_after_sixty_seconds():
    with Rig(before=["refused"], after=["refused"]) as rig:
        r = rig.ensure()
        assert r.code == "start_failed" and "60 seconds" in r.detail
        assert 60 <= rig.clock.now < 80                          # the deadline, not far past it
        assert len(rig.spawns) == 1 and rig.locks_left() == []


def test_ping_decisions_outside_a_start_never_spawn():
    table = [
        (["other"], "port_taken"), (["other_nojson"], "port_taken"),
        (["other_noversion"], "port_taken"),
        (["timeout"], "not_answering"),
        (["timeout", "other", "timeout"], "not_answering"),     # any mix is a timeout
        (["refused", "other", "refused"], "not_answering"),
    ]
    for script, code in table:
        with Rig(before=script) as rig:
            r = rig.ensure()
            assert r.code == code, (script, r)
            assert rig.spawns == [] and rig.find_calls == 0, script
            assert len(rig.gets("/api/version")) == 3, script    # three tries
            assert 1.5 <= rig.clock.now < 20, (script, rig.clock.now)   # 1 s apart, bounded
    with Rig(before=["other"]) as rig:
        assert rig.ensure().detail == "11434"                   # port_taken names the port


def test_the_first_ollama_answer_wins_even_after_refusals():
    with Rig(before=["refused", "refused", "ollama"]) as rig:
        r = rig.ensure()
        assert r.ok and r.started is False and rig.spawns == []
        assert len(rig.gets("/api/version")) == 3


def test_during_the_start_wait_other_and_timeout_continue_the_poll():
    with Rig(before=["refused"], after=["other", "timeout", "other", "refused", "ollama"]) as rig:
        r = rig.ensure()
        assert r.ok and r.started is True and len(rig.spawns) == 1


def test_at_the_deadline_the_last_answer_decides():
    for after, code in (("refused", "start_failed"), ("other", "port_taken"),
                        ("timeout", "not_answering")):
        with Rig(before=["refused"], after=[after]) as rig:
            r = rig.ensure()
            assert r.code == code, (after, r)
            assert len(rig.spawns) == 1


# --------------------------------------------------------------------------
# T7, T8, T10: model check, load, probe reset
# --------------------------------------------------------------------------

def test_a_missing_model_is_model_missing_and_never_pulled():
    with Rig(tags=["llama3:8b"]) as rig:
        r = rig.ensure()
        assert r.code == "model_missing" and r.detail == TAG
        assert all("/api/pull" not in u for _, u in rig.http.calls)
        assert not any(m == "POST" for m, _ in rig.http.calls)


def test_a_tag_without_a_colon_matches_latest():
    with Rig(tags=["qwen3:latest"]) as rig:
        assert rig.ensure(backend=rig.backend(model="qwen3")).ok


class _RecordingBackend(B.OllamaBackend):
    fail = False
    hang = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.warm_calls, self.resets = [], 0

    def reset_probe(self):
        self.resets += 1
        super().reset_probe()

    def warm(self, keep_alive=None, *, timeout=None):
        self.warm_calls.append({"keep_alive": keep_alive, "timeout": timeout, "resets": self.resets})
        if self.hang is not None:
            self.hang.wait(8)
            return
        if self.fail:
            raise B.BackendError("could not load")


def test_load_calls_warm_by_keyword_with_the_cap_and_resets_the_probe_first():
    with Rig() as rig:
        be = rig.backend(cls=_RecordingBackend)
        r = rig.ensure(backend=be, load=True, keep_alive="30m")
        assert r.ok
        assert len(be.warm_calls) == 1
        c = be.warm_calls[0]
        assert c["timeout"] is not None and c["timeout"] <= 330 and c["keep_alive"] == "30m"
        assert c["resets"] >= 1                                  # step 6 before step 7
        assert rig.states[-1:] == ["loading"]


def test_a_failed_load_is_load_failed_with_the_tag():
    with Rig() as rig:
        be = rig.backend(cls=_RecordingBackend)
        be.fail = True
        r = rig.ensure(backend=be, load=True)
        assert r.code == "load_failed" and r.detail == TAG


def test_a_load_that_never_returns_hits_the_cap_as_load_failed():
    with Rig() as rig:
        be = rig.backend(cls=_RecordingBackend)
        be.hang = threading.Event()
        try:
            r = rig.ensure(backend=be, load=True, load_wait_s=12.0)
        finally:
            be.hang.set()
        assert r.code == "load_failed", r
        assert 12 <= rig.clock.now < 40


def test_load_false_never_posts():
    with Rig() as rig:
        be = rig.backend(cls=_RecordingBackend)
        assert rig.ensure(backend=be, load=False).ok and be.warm_calls == []


def test_warm_timeout_is_keyword_only_everywhere():
    for fn in (B.Backend.warm, B.OllamaBackend.warm, B.warm):
        p = inspect.signature(fn).parameters.get("timeout")
        assert p is not None, fn
        assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is None, fn


def test_reset_probe_makes_a_failed_backend_available_again():
    with Rig(before=["ollama"]) as rig:
        be = rig.backend()
        rig.tags = []
        assert be.available is False and be.unavailable_code == "model_missing"
        rig.tags = [TAG]
        assert be.available is False                             # the cache holds
        be.reset_probe()
        assert be.available is True and be.unavailable_code == ""


# --------------------------------------------------------------------------
# T9: the start lock (C8)
# --------------------------------------------------------------------------

def test_a_live_creators_fresh_lock_means_wait_and_never_spawn():
    with Rig(before=["refused"] * 7 + ["ollama"]) as rig:
        lock = rig.plant_lock("4242\n")
        r = rig.ensure()
        assert r.ok and r.started is False and rig.spawns == []
        assert 4242 in rig.alive_calls
        assert "starting" in rig.states
        assert lock.exists()                                     # not ours to delete


def test_a_lock_older_than_ninety_seconds_is_stale_even_if_its_pid_looks_alive():
    with Rig(before=["refused"], after=["ollama"]) as rig:
        rig.plant_lock("4242\n", age=200)
        r = rig.ensure()
        assert r.ok and r.started and len(rig.spawns) == 1


def test_a_dead_creators_lock_is_stale_at_once_not_after_sixty_seconds():
    with Rig(before=["refused"], after=["ollama"], alive=False) as rig:
        rig.plant_lock("4242\n")
        r = rig.ensure()
        assert r.ok and r.started and len(rig.spawns) == 1
        assert rig.clock.now < 15, rig.clock.now                  # no 60 s wait, no start_failed
        assert rig.locks_left() == []


def test_a_lock_with_no_readable_pid_goes_stale_within_a_few_seconds():
    with Rig(before=["refused"], after=["ollama"]) as rig:
        rig.plant_lock("")
        r = rig.ensure()
        assert r.ok and len(rig.spawns) == 1 and rig.clock.now < 30


def test_a_lock_that_vanishes_during_the_wait_lets_the_waiter_spawn_once():
    with Rig(before=["refused"], after=["ollama"]) as rig:
        lock = rig.plant_lock("4242\n")
        def vanish(n):
            if n == 8 and lock.exists():
                lock.unlink()
        rig.clock.hook = vanish
        r = rig.ensure()
        assert r.ok and r.started is True and len(rig.spawns) == 1
        assert rig.locks_left() == []


def test_two_callers_at_once_spawn_exactly_once():
    with Rig(before=["refused"], after=["ollama"], spawn_delay=0.02) as rig:
        out, bar = [], threading.Barrier(2)
        def go():
            bar.wait()
            out.append(rig.ensure())
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        assert len(out) == 2 and all(r.ok for r in out), out
        assert len(rig.spawns) == 1
        assert sum(1 for r in out if r.started) == 1
        assert rig.locks_left() == []


# --------------------------------------------------------------------------
# T11 (service half): should_stop ends every wait early (C1)
# --------------------------------------------------------------------------

def test_should_stop_ends_the_start_wait_with_cancelled_and_releases_the_lock():
    with Rig(before=["refused"], after=["refused"]) as rig:
        r = rig.ensure(should_stop=lambda: rig.clock.now > 6)
        assert r.code == "cancelled" and not r.ok
        assert rig.clock.now < 15                                # nowhere near 60 s
        assert rig.locks_left() == []


def test_should_stop_ends_a_wait_behind_another_callers_lock():
    with Rig(before=["refused"]) as rig:
        lock = rig.plant_lock("4242\n")
        r = rig.ensure(should_stop=lambda: rig.clock.now > 6)
        assert r.code == "cancelled" and rig.spawns == [] and lock.exists()


def test_should_stop_ends_a_long_load_with_cancelled():
    with Rig() as rig:
        be = rig.backend(cls=_RecordingBackend)
        be.hang = threading.Event()
        try:
            r = rig.ensure(backend=be, load=True, should_stop=lambda: rig.clock.now > 5)
        finally:
            be.hang.set()
        assert r.code == "cancelled" and rig.clock.now < 20


# --------------------------------------------------------------------------
# T15, T15b, T15c: where a start is allowed, and the spawner's own refusals
# --------------------------------------------------------------------------

def _checkouts(tmp: Path):
    main = tmp / "main"
    (main / ".git").mkdir(parents=True)
    (main / "data").mkdir()
    db = main / "data" / "jobscraper.db"
    db.write_bytes(b"")
    wt = tmp / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: ../main/.git/worktrees/wt\n")
    (wt / "data").mkdir()
    return main, db, wt


def test_autostart_allowed_here_only_on_the_checkouts_own_database():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        main, db, wt = _checkouts(tmp)
        other = tmp / "copy.db"
        other.write_bytes(b"")
        f = B.autostart_allowed_here
        assert f(db_path=db, env={}, source_dir=main) is True                    # T15b
        assert f(db_path=other, env={}, source_dir=main) is False                # a copy
        assert f(db_path=wt / "data" / "jobscraper.db", env={}, source_dir=wt) is False   # worktree
        assert f(db_path=db, env={"JOBSCRAPER_CONFIG": "x.yaml"}, source_dir=main) is False
        assert f(db_path=db, env={}, config_given=True, source_dir=main) is False
        assert f(db_path=db, env={"JOBSCRAPER_OLLAMA_AUTOSTART": "0"}, source_dir=main) is False
        # "1" is the explicit one-command override and allows even a copy
        assert f(db_path=other, env={"JOBSCRAPER_OLLAMA_AUTOSTART": "1"}, source_dir=main) is True


def test_running_from_worktree_moved_to_backends_and_unchanged():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        main, _db, wt = _checkouts(Path(t))
        plain = Path(t) / "plain"
        plain.mkdir()
        assert B.running_from_worktree(wt) is True
        assert B.running_from_worktree(main) is False
        assert B.running_from_worktree(plain) is False


def test_autostart_switch_is_a_settings_row_over_config_over_true():
    f = B.autostart_switch
    assert f({}) is True and f({"ollama_autostart": False}) is False
    assert f({"ollama_autostart": False}, get=lambda k: "true") is True      # settings win
    assert f({}, get=lambda k: "false") is False
    asked = []
    f({}, get=lambda k: asked.append(k))
    assert asked == ["budget.ollama_autostart"]


@contextmanager
def _popen_recorder():
    calls = []
    class Rec:
        def __init__(self, *a, **k):
            calls.append((a, k))
            raise AssertionError("a test must never start a process")
    real = subprocess.Popen
    subprocess.Popen = Rec
    saved = {n: getattr(B, n) for n in ("Popen",) if hasattr(B, n)}
    for n in saved:
        setattr(B, n, Rec)
    try:
        yield calls
    finally:
        subprocess.Popen = real
        for n, v in saved.items():
            setattr(B, n, v)


def test_the_spawner_refuses_when_autostart_is_off_in_the_environment():
    ghost = str(Path(tempfile.gettempdir()) / "no-such-dir" / EXE_NAME)         # never a real file
    prev = os.environ.get("JOBSCRAPER_OLLAMA_AUTOSTART")
    os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"
    try:
        with _popen_recorder() as calls:
            try:
                B._spawn_detached([ghost, "serve"], {"OLLAMA_HOST": "127.0.0.1:11434"})
            except OSError:
                pass
            else:
                raise AssertionError("_spawn_detached must raise OSError when the variable is 0")
            assert calls == []
    finally:
        if prev is None:
            os.environ.pop("JOBSCRAPER_OLLAMA_AUTOSTART", None)
        else:
            os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = prev


def test_the_spawner_refuses_when_a_test_runner_module_is_loaded_even_without_the_variable():
    ghost = str(Path(tempfile.gettempdir()) / "no-such-dir" / EXE_NAME)
    prev = os.environ.pop("JOBSCRAPER_OLLAMA_AUTOSTART", None)
    had = "run_tests" in sys.modules
    sys.modules.setdefault("run_tests", types.ModuleType("run_tests"))
    try:
        with _popen_recorder() as calls:
            try:
                B._spawn_detached([ghost, "serve"], {"OLLAMA_HOST": "127.0.0.1:11434"})
            except OSError:
                pass
            else:
                raise AssertionError("_spawn_detached must raise OSError under a test runner")
            assert calls == []
    finally:
        if not had:
            sys.modules.pop("run_tests", None)
        if prev is not None:
            os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = prev


def test_a_refusing_spawner_means_start_failed_through_the_default_seam():
    """No `spawn=` injected: the default `_spawn_detached` is used and, under the suite's
    guard, refuses; the service reports start_failed and never launches anything."""
    with Rig(before=["refused"]) as rig:
        with _popen_recorder() as calls:
            r = B.ensure_model_running(
                {"ollama_url": URL, "ollama_model": TAG}, autostart=True, backend=rig.backend(),
                find=rig.find, http=rig.http, pid_alive=rig.pid_alive, clock=rig.clock,
                sleep=rig.clock.sleep, lock_dir=rig.lock_dir)
            assert r.code == "start_failed", r
            assert calls == []
