"""`apply queue` and `cmd_web`'s queue switch (Q-120, apply_queue_design §3.3, §3.4; review
H2, L2). `apply_flow.run_queue` is replaced by a recorder in every test but the lock one,
which runs the real worker on a temp config with an EMPTY queue and the RunLock held, so
nothing can be taken. uvicorn.run and create_app are replaced: no server, no port.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import make_world  # noqa: E402

from jobscraper import apply_flow, cli  # noqa: E402
from jobscraper.web import jobs as web_jobs  # noqa: E402


def _run(cfg_path, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--config", str(cfg_path), *argv])
    return code, out.getvalue(), err.getvalue()


def _world():
    w = make_world()
    w.close()                          # the CLI opens its own connection
    return w


@contextlib.contextmanager
def _fake_queue(outcome=None, refuse=False):
    calls = []

    def fake(cfg, store, *, backend, apply_cfg_fn, should_stop=None, force_dry_run=False, **kw):
        if refuse:
            raise AssertionError("the worker must not start")
        calls.append({"force_dry_run": force_dry_run, "mode": apply_cfg_fn().mode,
                      "should_stop": should_stop})
        return outcome if outcome is not None else apply_flow.QueueOutcome()
    saved = apply_flow.run_queue
    apply_flow.run_queue = fake
    try:
        yield calls
    finally:
        apply_flow.run_queue = saved


def test_queue_is_a_reserved_word_and_bad_arguments_exit_2_without_a_worker():
    w = _world()
    with _fake_queue(refuse=True):
        for argv in (["apply", "queue", "abc123"], ["apply", "queue", "--parent-pid", "0"],
                     ["apply", "queue", "--parent-pid", "-4"], ["apply", "abc123", "--parent-pid", "7"]):
            code, out, err = _run(w.cfg_path, *argv)
            assert code == 2, (argv, code, out, err)
    build = web_jobs.cli_command()
    for ids in (["queue"], ["abc123", "queue"]):
        try:
            build("apply", {"job_ids": ids})
        except ValueError:
            continue
        raise AssertionError(f"job id(s) {ids} would run the queue worker from a web job")
    assert build("apply", {"queue": True})[3:5] == ["apply", "queue"]


def test_exit_0_on_drained_paused_and_yielded_and_the_dry_run_flag_forces_dry_run():
    w = _world()
    cases = ((apply_flow.QueueOutcome(), "paused: no"),
             (apply_flow.QueueOutcome(paused="fill_failed", waiting=2), "paused: fill_failed"),
             (apply_flow.QueueOutcome(yielded=True, waiting=1), "1 waiting"))
    for outcome, line in cases:
        with _fake_queue(outcome) as calls:
            code, out, err = _run(w.cfg_path, "apply", "queue")
        assert code == 0 and line in out, (outcome, code, out, err)
        assert calls[0]["force_dry_run"] is False and calls[0]["should_stop"] is None
    with _fake_queue() as calls:
        code, out, _ = _run(w.cfg_path, "apply", "queue", "--dry-run")
    assert code == 0 and calls[0]["force_dry_run"] is True
    with _fake_queue(apply_flow.QueueOutcome(lock_refused=True)):
        code, out, _ = _run(w.cfg_path, "apply", "queue")
    assert code == 3 and "nothing was taken" in out


def test_exit_3_when_another_apply_run_holds_the_lock_with_the_real_worker():
    w = _world()
    lock = apply_flow.RunLock(apply_flow.evidence_root(w.cfg) / "run.lock")
    assert lock.acquire(), "the test could not take the lock"
    try:
        code, out, err = _run(w.cfg_path, "apply", "queue")
    finally:
        lock.release()
    assert code == 3, (code, out, err)
    assert "another apply run" in out


@contextlib.contextmanager
def _web_run(repo_root, env):
    """`cmd_web` with uvicorn and create_app replaced (no server, no port), the env set to
    exactly `env` for the switch's keys, and the code's repo root pointed at `repo_root`
    (a temp dir whose `.git` is a directory = the main checkout, or a file = a worktree), so
    the answer is the same wherever the suite runs. Yields the recorded create_app kwargs."""
    import uvicorn
    from jobscraper.web import api as web_api, applyqueue
    seen = []
    saved = (uvicorn.run, web_api.create_app, applyqueue._REPO_ROOT)
    keys = ("JOBSCRAPER_DB", "JOBSCRAPER_CONFIG", "JOBSCRAPER_PORT", "JOBSCRAPER_APPLY_QUEUE",
            "JOBSCRAPER_MAIL_SYNC")
    old = {k: os.environ.get(k) for k in keys}
    uvicorn.run = lambda app, **kw: None
    web_api.create_app = lambda cfg, **kw: seen.append(kw) or object()
    applyqueue._REPO_ROOT = Path(repo_root)
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        yield seen
    finally:
        uvicorn.run, web_api.create_app, applyqueue._REPO_ROOT = saved
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _git_dir_like(base):
    d = Path(base) / "main_like"
    (d / ".git").mkdir(parents=True)
    return d


def test_cmd_web_passes_the_queue_switch_to_create_app():
    import tempfile
    w = _world()
    with tempfile.TemporaryDirectory() as t:
        main_like = _git_dir_like(t)
        cfg = ["--config", str(w.cfg_path)]
        # (env, extra argv before `web`, wanted): `--config` alone now turns the worker OFF
        # (review F4); the live app is `web` with no --config, from the main checkout.
        cases = (({"JOBSCRAPER_APPLY_QUEUE": "0"}, [], False),
                 ({"JOBSCRAPER_DB": str(w.tmp / "copy.db")}, [], False),
                 ({}, cfg, False),
                 ({"JOBSCRAPER_APPLY_QUEUE": "1"}, cfg, True),
                 ({}, [], True))
        for env, pre, want in cases:
            with _web_run(main_like, env) as seen:
                with contextlib.redirect_stdout(io.StringIO()):
                    assert cli.main([*pre, "web"]) == 0
                assert seen[-1].get("apply_queue_worker") is want, (env, pre, seen[-1])


def test_cmd_web_hands_the_resolved_port_and_config_path_to_the_switch():
    """F4: the switch is asked about the port `web` binds (config `web.port` with
    JOBSCRAPER_PORT applied) and the `--config` it was given, not only the env."""
    import tempfile
    from jobscraper.web import applyqueue
    w = _world()
    calls = []
    real = applyqueue.apply_queue_wanted

    def spy(env, **kw):
        calls.append(kw)
        return real(env, **kw)
    with tempfile.TemporaryDirectory() as t:
        main_like = _git_dir_like(t)
        applyqueue.apply_queue_wanted = spy
        try:
            for env, pre, port, path, want in (
                    ({}, [], 8765, None, True),
                    ({"JOBSCRAPER_PORT": "8769"}, [], 8769, None, False),
                    ({}, ["--config", str(w.cfg_path)], None, str(w.cfg_path), False)):
                with _web_run(main_like, env) as seen:
                    with contextlib.redirect_stdout(io.StringIO()):
                        assert cli.main([*pre, "web"]) == 0
                kw = calls[-1]
                assert kw["config_path"] == path, (env, kw)
                if port is not None:
                    assert kw["port"] == port, (env, kw)
                assert isinstance(kw["port"], int)
                assert seen[-1]["apply_queue_worker"] is want, (env, seen[-1])
        finally:
            applyqueue.apply_queue_wanted = real
