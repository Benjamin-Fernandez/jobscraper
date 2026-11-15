"""Q-126 round 3 pins (code review M1, M2 follow-ups; design §3, §6, §9 T13d, T13e, T18, T19).

Green on int/Q-126 (320cfeb and later). What they pin:
  * M1: `applicant refresh-resume` (and `tailor`, `titles suggest`, `profile`) reach their
    model-start check with every name defined. `_applicant_refresh` hid a NameError behind a
    broad `except Exception`, so the pin runs the REAL `_ensure_model` (autostart is off:
    the suite sets JOBSCRAPER_OLLAMA_AUTOSTART=0) and makes the next stage raise a marker;
    the marker, not NameError, must come out. For the other verbs `_ensure_model` is replaced
    by a recorder that raises a BaseException: reaching it proves the call's own names exist.
  * `cmd_web` sets JOBSCRAPER_CONFIG only when `--config` is given, before the app is created.
  * T18: the pipeline starts the model only when postings wait, the model is on and the probe
    says down; a failed start never raises and only changes the skip line.
  * T13d: a click's lift never takes away a pause that changed under it. T13e: a lifted
    model pause that still cannot be cleared is stored again by the worker (in
    tests/test_q126_worker.py). T19: a recovered `model_unavailable` attempt stops counting.

Fakes only: temp config and DB, patched downstream stages, no process, no socket, no real
model, no `data/`, never `jobscraper apply`, `apply queue` or `web` for real.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import profile  # noqa: E402
from mail_flow_support import config, tmpdir  # noqa: E402

from jobscraper import backends, cli, decide, pipeline  # noqa: E402
from jobscraper.store import Store  # noqa: E402


class _Reached(BaseException):
    """Raised by a recorder: the verb got as far as the model-start check."""


class _Marker(Exception):
    pass


def _cfg_file():
    tmp = tmpdir("q126cli_")
    cfg, path = config(tmp, write=True)
    return tmp, cfg, str(path)


def _cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except _Reached:
            code = "reached"
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def _patched(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def _recorder(calls):
    def rec(cfg, store, args, **kw):
        calls.append(kw)
        raise _Reached()
    return rec


# ------------------------------------------------------------------ M1

def test_applicant_refresh_resume_reaches_its_next_stage_with_no_name_error():
    from jobscraper import tailor_flow
    tmp, cfg, path = _cfg_file()
    app = tmp / "applicant.yaml"
    app.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8")
    cfg.raw["paths"]["applicant"] = str(app)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg.raw, fh)
    assert os.environ.get("JOBSCRAPER_OLLAMA_AUTOSTART") == "0"       # the real _ensure_model is inert
    reached = []

    def next_stage(c, backend):
        reached.append(type(backend).__name__)
        raise _Marker("sentinel")
    with _patched(tailor_flow, profile_proposals=next_stage):
        code, out, err = _cli(["--config", path, "applicant", "refresh-resume"])
    assert reached, (code, out, err)                                  # the stage after the check ran
    assert "NameError" not in err + out, err
    assert "_Marker" in err                                           # the broad except saw our marker


def test_applicant_refresh_passes_args_to_the_check():
    tmp, cfg, path = _cfg_file()
    app = tmp / "applicant.yaml"
    app.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8")
    seen = []
    args = SimpleNamespace(config=None, yes=False)
    with _patched(cli, _ensure_model=lambda c, s, a, **kw: seen.append(a)):
        cfg.raw["paths"]["applicant"] = str(app)
        from jobscraper import tailor_flow
        with _patched(tailor_flow, profile_proposals=lambda c, b: (_ for _ in ()).throw(_Marker("x"))):
            with contextlib.redirect_stderr(io.StringIO()):
                cli._applicant_refresh(cfg, False, args)
    assert seen == [args]


def test_tailor_profile_and_titles_suggest_reach_the_model_check_with_no_name_error():
    from jobscraper.profile import resume_ingest as ri
    from jobscraper import filter as filter_mod
    _tmp, _cfg, path = _cfg_file()
    calls = []
    with _patched(cli, _ensure_model=_recorder(calls)):
        assert _cli(["--config", path, "tailor", "no-such-job"])[0] == "reached"
        assert _cli(["--config", path, "profile"])[0] == "reached"
        with _patched(ri, load_derived_profile=lambda c: {"target_titles": []},
                      load_resume=lambda d, force=False: "resume text"):
            assert _cli(["--config", path, "titles", "suggest"])[0] == "reached"
    assert len(calls) == 3


def test_the_real_check_never_fails_a_command_and_does_nothing_here():
    _tmp, cfg, _path = _cfg_file()
    out = io.StringIO()
    assert cli._ensure_model(cfg, None, SimpleNamespace(config=None), say=out.write) is None
    assert out.getvalue() == ""                                       # autostart is off in a test


# ------------------------------------------------------------------ M2 and --config

@contextlib.contextmanager
def _web_env():
    import uvicorn
    from jobscraper.web import api as web_api
    seen = []
    saved = (uvicorn.run, web_api.create_app, os.environ.get("JOBSCRAPER_CONFIG"))
    uvicorn.run = lambda app, **kw: None
    web_api.create_app = lambda cfg, **kw: seen.append(os.environ.get("JOBSCRAPER_CONFIG")) or object()
    try:
        yield seen
    finally:
        uvicorn.run, web_api.create_app = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop("JOBSCRAPER_CONFIG", None)
        else:
            os.environ["JOBSCRAPER_CONFIG"] = saved[2]


def test_cmd_web_sets_jobscraper_config_only_with_dash_dash_config_and_before_the_app():
    _tmp, _cfg, path = _cfg_file()
    with _web_env() as seen:
        os.environ.pop("JOBSCRAPER_CONFIG", None)
        assert _cli(["--config", path, "web"])[0] == 0
        assert seen == [path], seen                                   # set when create_app ran
        with tempfile.TemporaryDirectory() as t:
            main = Path(t) / "main"
            (main / ".git").mkdir(parents=True)
            (main / "data").mkdir()
            db = main / "data" / "jobscraper.db"
            db.write_bytes(b"")
            assert backends.autostart_allowed_here(
                db_path=db, env={}, source_dir=main) is True          # control: allowed on its own DB
            assert backends.autostart_allowed_here(
                db_path=db, env={"JOBSCRAPER_CONFIG": seen[0]}, source_dir=main) is False
    # (without `--config` nothing sets it: tests/test_apply_queue_cli.py runs that path and its
    # `_web_run` restores the variable, so this file never starts `web` on the default config)


# ------------------------------------------------------------------ T18

class _Down(backends.OllamaBackend):
    available = False
    unavailable_reason = "down"
    unavailable_code = "unreachable"

    def __init__(self, model="qwen3:14b"):
        super().__init__(url="http://127.0.0.1:11434", model=model, client=object())


class _Store:
    def __init__(self, cached_model=None, failures=0):
        self.cached_model, self.failures = cached_model, failures

    def get_decision(self, job_id, pv, h):
        return {"model": self.cached_model} if self.cached_model else None

    def decision_failures(self, job_id, pv, h, model):
        return self.failures


def _bring(store, backend, budget=None, ensure=None, postings=None):
    calls = []
    real = backends.ensure_model_running

    def spy(b, **kw):
        calls.append(kw)
        return ensure(b, **kw) if ensure else backends.ModelReady("ready")
    backends.ensure_model_running = spy
    try:
        posts = postings if postings is not None else [decide.Posting("j1", "Analyst", "Entry level")]
        words = pipeline._bring_model_up(budget or {"enable_llm": True}, store, backend, posts, 1,
                                         lambda s: None, None)
    finally:
        backends.ensure_model_running = real
    return calls, words


def test_the_pipeline_starts_the_model_only_when_a_posting_waits_and_the_probe_says_down():
    calls, words = _bring(_Store(), _Down())
    assert len(calls) == 1 and calls[0]["autostart"] is True and words == ""
    assert _bring(_Store(cached_model="qwen3:14b"), _Down())[0] == []        # every posting cached
    assert _bring(_Store(failures=99), _Down())[0] == []                     # parked postings
    assert _bring(_Store(), _Down(), postings=[])[0] == []                   # nothing waits
    assert _bring(_Store(), _Down(), budget={"enable_llm": False})[0] == []  # the model is off

    class Up(_Down):
        available = True
    assert _bring(_Store(), Up())[0] == []                                   # already answering
    assert _bring(_Store(), backends.OffBackend("tests"))[0] == []           # not an Ollama backend


def test_a_failed_start_only_changes_the_skip_words_and_never_raises():
    calls, words = _bring(_Store(), _Down(), ensure=lambda b, **kw: backends.ModelReady("not_installed"))
    assert words == "Ollama isn't installed"
    _, words = _bring(_Store(), _Down(), ensure=lambda b, **kw: backends.ModelReady(
        "model_missing", detail="qwen3:14b"))
    assert "qwen3:14b" in words

    def boom(b, **kw):
        raise RuntimeError("the service broke")
    calls, words = _bring(_Store(), _Down(), ensure=boom)
    assert len(calls) == 1 and words == ""                                   # swallowed


def test_a_run_without_the_switch_never_asks_the_service():
    from test_pipeline import _run, _world
    cfg, st = _world(3)
    real = backends.ensure_model_running

    def boom(*a, **k):
        raise AssertionError("the pipeline started the model without model_autostart")
    backends.ensure_model_running = boom
    try:
        rep = _run(cfg, st, backend=_Down())
    finally:
        backends.ensure_model_running = real
    assert rep.status in ("ok", "partial", "failed")


# ------------------------------------------------------------------ T13d, T19

def test_a_click_cannot_lift_a_pause_that_changed_under_it():
    from test_apply_queue_web import _db, _post, _world
    real = Store.queue_resume_if

    def racing(self, reasons, now, **kw):
        # the owner pressed Pause (and the model pause went) between the click's read and its clear
        self.queue_resume(now)
        self.queue_pause("owner", None, now)
        return real(self, reasons, now, **kw)
    with _world() as w:
        with _db(w) as st:
            st.queue_pause("model_missing", "qwen3:14b", "2026-11-15T08:00:00Z")
        Store.queue_resume_if = racing
        try:
            code, body = _post(w, w.jobs[0])
        finally:
            Store.queue_resume_if = real
        assert code == 202 and body["paused"] is True and w.fake.started == [], body
        with _db(w) as st:
            assert st.queue_pause_state()["reason"] == "owner"


def test_a_recovered_model_unavailable_attempt_stops_counting_as_need():
    from jobscraper.web.connections import need_reason
    down = {"reason_code": "model_unavailable", "state": "failed", "finished_at": "2026-11-15T08:00:00"}
    ok = {"reason_code": None, "state": "ready_to_submit", "finished_at": "2026-11-15T09:00:00"}
    older_ok = dict(ok, finished_at="2026-11-15T07:00:00")
    recent = "2026-11-14T00:00:00"
    assert need_reason({}, [], {"a": down}, [], recent) == "application"
    assert need_reason({}, [], {"a": down, "b": ok}, [], recent) is None
    assert need_reason({}, [], {"a": down, "b": older_ok}, [], recent) == "application"
