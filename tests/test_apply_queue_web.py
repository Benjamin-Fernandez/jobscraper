"""Q-120 (D-205) web oracles for the auto-apply queue (apply_queue_design §3.4, §3.5, §4.2, §6,
§8 P2-P5, P7, P7b, P11-P13, P17-P19, P21; review H1, H2, H3, M1, M2, M3).

In mode `auto` a queued role becomes a REAL submission. What these pin:
  * a click only queues: 202 with a position, never 409, never twice (P2, P3);
  * nothing starts without a click or after a restart (P7, P7b: the gate fails closed);
  * the default `create_app()` never starts a worker, and the runner reaches only the job
    manager on `app.state` at kick time (P17, H1);
  * a dev copy never drains the queue (P18, H2);
  * a removed role is never applied to, a role in flight can't be removed (P5, P19, H3);
  * GETs write and start nothing (P21, M1); Stop/Cancel pause first (P11, M3);
  * a search run during the worker is deferred, not refused (P13); exit codes judged (P12).

Every test builds the real app over a temp config and DB with a dummy resume. The real
JobManager's command builder RAISES if it is ever called (and records the call); a FAKE job
manager is swapped in after `create_app`, so no child process, browser, server or network
is ever used, and never data/ or port 8765. The background tick is set to an hour, so every
kick in a test is one the test made (or a route made).
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import profile  # noqa: E402
from questions_support import make_job  # noqa: E402

from jobscraper.store import Store, utcnow  # noqa: E402

NOW = "2026-11-12T08:00:00Z"
EVIL = {"Origin": "https://evil.example"}
WORKER = ("apply", {"queue": True})


class FakeJobs:
    """The JobManager seam: records start/cancel, holds one slot, never runs anything."""

    def __init__(self):
        from jobscraper.web.jobs import IDLE
        self.started: list[tuple[str, dict]] = []
        self.cancels: list = []
        self.on_cancel = None             # called at cancel time; its value is recorded
        self.cur = dict(IDLE)
        self.n = 0

    def current(self, tail: int = 200) -> dict:
        return dict(self.cur, log=[])

    def _run(self, job_id: str, kind: str) -> None:
        self.cur = {"id": job_id, "kind": kind, "state": "running", "started_at": NOW,
                    "finished_at": None, "exit_code": None}

    def start(self, kind: str, opts: dict, tail: int = 200) -> dict:
        from jobscraper.web.jobs import JobBusy
        if self.cur.get("state") == "running":
            raise JobBusy("a job is already running")
        self.n += 1
        self.started.append((kind, dict(opts)))
        self._run(f"fake-{self.n}", kind)
        return self.current()

    def cancel(self, tail: int = 200) -> dict:
        from jobscraper.web.jobs import JobIdle
        if self.cur.get("state") != "running":
            raise JobIdle("nothing is running")
        self.cancels.append(self.on_cancel() if self.on_cancel else True)
        self.finish(143, reason="cancelled")
        return self.current()

    def hold(self, kind: str) -> None:
        """Another job (started elsewhere) holds the slot."""
        self._run(f"other-{kind}", kind)

    def finish(self, code: int, reason=None) -> None:
        self.cur = dict(self.cur, state="done" if code == 0 else "failed", exit_code=code,
                        finished_at=NOW, reason=reason)

    def release(self) -> None:
        from jobscraper.web.jobs import IDLE
        self.cur = dict(IDLE)


@contextmanager
def _world(*, worker: bool = True, swap: bool = True, seed_waiting: int = 0, n_jobs: int = 5,
           before_client=None):
    """SimpleNamespace(c, app, cfg, cid, jobs, fake, calls): the real app on a temp DB.
    `seed_waiting` roles wait in the queue (with `to_apply` rows) before the app starts."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        path.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8", newline="\n")
        (data / "resume.pdf").write_bytes(b"%PDF-1.4 dummy resume for the queue pins")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765},
                      "apply": {"mode": "dry_run"}})
        st = Store(cfg.db_path)
        cid = st.insert_company("fakeco", "Fake Co", "https://fakeco.example")
        jobs = [make_job(st, cid, n) for n in range(1, n_jobs + 1)]
        for j in jobs[:seed_waiting]:
            st.set_application_status(j, "to_apply")
            st.queue_add(j, cid, "dry_run", "inbox", NOW)
        st.commit()
        st.close()
        calls: list = []

        def real_command(kind, opts):           # the real JobManager's builder: never reached
            calls.append((kind, dict(opts)))
            raise RuntimeError("a test reached the real job command")

        app = create_app(cfg, job_command=real_command, apply_queue_worker=worker)
        app.state.apply_queue.tick_s = 3600
        fake = FakeJobs()
        if swap:
            app.state.jobs = fake
        if before_client:
            before_client(app)
        with TestClient(app, base_url="http://localhost") as client:
            yield SimpleNamespace(c=client, app=app, cfg=cfg, cid=cid, jobs=jobs, fake=fake,
                                  calls=calls, runner=app.state.apply_queue)


@contextmanager
def _db(w):
    st = Store(w.cfg.db_path)
    try:
        yield st
    finally:
        st.close()


def _post(w, *ids, **extra):
    r = w.c.post("/api/apply", json={"job_ids": list(ids), **extra})
    return r.status_code, r.json()


def _snapshot(w) -> tuple:
    """Every row a queue route could write: queue, attempts, applications, queue settings."""
    con = sqlite3.connect(str(w.cfg.db_path))
    try:
        return tuple(tuple(map(tuple, con.execute(sql).fetchall())) for sql in (
            "SELECT * FROM apply_queue ORDER BY id",
            "SELECT * FROM apply_attempts ORDER BY id",
            "SELECT job_id, status FROM applications ORDER BY job_id",
            "SELECT key, value FROM settings WHERE key LIKE 'apply_queue.%' ORDER BY key"))
    finally:
        con.close()


def _take(w) -> dict:
    """What the worker's first step does: take the head (a `queued` attempt)."""
    with _db(w) as st:
        item, _ = st.queue_take(utcnow())
    return item


# ------------------------------------------------------------------ H1 / P17


def test_p17_h1_default_app_starts_nothing_and_a_fake_swapped_in_after_create_app_gets_the_start():
    # the default create_app(): the REAL JobManager stays in place, a role waits, a click comes
    with _world(worker=False, swap=False, seed_waiting=1) as w:
        assert w.runner.enabled is False and w.runner.timer_running is False
        code, body = _post(w, w.jobs[1])
        assert code == 202 and body["started"] is False and body["disabled"] is True, body
        assert body["queued"] == [{"job_id": w.jobs[1], "position": 2}], body
        assert w.runner.kick() is False
        with _db(w) as st:
            assert st.queue_pause_state() is None             # no start-up hook ran either
        assert w.calls == [], "the default app reached the real job command"

    # the worker switched on, a fake swapped in AFTER create_app: the fake gets the start
    with _world(worker=True) as w:
        code, body = _post(w, w.jobs[0])
        assert code == 202 and body["started"] is True and body["paused"] is False, body
        assert body["queued"] == [{"job_id": w.jobs[0], "position": 1}]
        assert body["job"]["kind"] == "apply" and body["job"]["id"] == "fake-1", body
        assert w.fake.started == [WORKER]
        assert w.calls == [], "the runner reached a job manager other than app.state.jobs"


# ------------------------------------------------------------------ P2 / P3


def test_p3_p2_clicks_while_a_job_runs_wait_with_positions_and_a_role_never_waits_twice():
    with _world(n_jobs=6) as w:
        j1, j2, j3, j4, j5, _ = w.jobs
        w.fake.hold("run")                                    # a search run holds the slot
        for job, pos in ((j1, 1), (j2, 2)):
            code, body = _post(w, job)
            assert code == 202, (code, body)
            assert body["queued"] == [{"job_id": job, "position": pos}] and body["refused"] == []
            assert body["started"] is False and body["job"] is None, body
        # the same role again: refused, still one row
        code, body = _post(w, j1)
        assert code == 422 and body["detail"] == "refused", (code, body)
        assert [(x["job_id"], x["reason_code"]) for x in body["refused"]] == [(j1, "already_queued")]
        assert body["refused"][0]["text"] and body["refused"][0]["hint"]
        # a role in flight (a live attempt) and one already applied are refused; a mix still queues
        with _db(w) as st:
            st.create_attempt(j4, w.cid, "dry_run", utcnow())
            st.set_application_status(j5, "applied")
            st.commit()
        code, body = _post(w, j1, j3, j4, j5)
        assert code == 202, (code, body)
        assert body["queued"] == [{"job_id": j3, "position": 3}], body
        assert [(x["job_id"], x["reason_code"]) for x in body["refused"]] == [
            (j1, "already_queued"), (j4, "in_progress"), (j5, "duplicate")], body
        with _db(w) as st:
            assert st.queue_positions() == {j1: 1, j2: 2, j3: 3}
        assert w.fake.started == [] and w.calls == []


# ------------------------------------------------------------------ P5 + pause / resume / clear


def test_p5_remove_waiting_204_started_or_unknown_404_and_the_pause_resume_clear_shapes():
    with _world() as w:
        j1, j2, j3, j4, _ = w.jobs
        w.fake.hold("run")
        for j in (j1, j2):
            assert _post(w, j)[0] == 202
        assert w.c.delete(f"/api/apply/queue/{j1}").status_code == 204
        for gone in (j1, "nosuchjob"):
            r = w.c.delete(f"/api/apply/queue/{gone}")
            assert r.status_code == 404 and r.json() == {"detail": "not_waiting"}, (gone, r.text)
        live = _take(w)                                        # j2 has started
        assert live["job_id"] == j2
        r = w.c.delete(f"/api/apply/queue/{j2}")
        assert r.status_code == 404 and r.json()["detail"] == "not_waiting"
        with _db(w) as st:
            assert [a["state"] for a in st.attempts_for_job(j2)] == ["queued"]    # untouched

        view = w.c.post("/api/apply/queue/pause").json()
        assert set(view) == {"paused", "now", "slot", "run_pending", "waiting", "recent"}, view
        assert view["paused"]["reason"] == "owner" and view["paused"]["text"], view
        assert view["slot"] == "run" and view["run_pending"] is False
        assert view["now"]["job_id"] == j2 and view["now"]["attempt_id"] == live["attempt_id"]
        assert view["now"]["interrupted"] is True              # live row, slot not `apply`
        assert w.c.post("/api/apply/queue/pause").json()["paused"]["reason"] == "owner"

        r = w.c.post("/api/apply/queue/resume")
        assert r.status_code == 200 and r.json()["paused"] is None, r.text
        for j in (j3, j4):
            assert _post(w, j)[0] == 202
        r = w.c.post("/api/apply/queue/clear")
        assert r.status_code == 200 and r.json()["removed"] == 2, r.text
        assert r.json()["queue"]["waiting"] == []
        with _db(w) as st:                                     # the roles stay in Applications
            assert st.application(j3)["status"] == "to_apply"
        assert w.fake.started == []                            # the run held the slot throughout


# ------------------------------------------------------------------ P7 / P7b (M2)


def test_p7_roles_waiting_at_start_up_pause_restarted_and_nothing_starts_until_resume():
    with _world(seed_waiting=1) as w:
        with _db(w) as st:
            assert st.queue_pause_state()["reason"] == "restarted"       # stored, not view-only
        assert w.c.get("/api/apply/queue").json()["paused"]["reason"] == "restarted"
        code, body = _post(w, w.jobs[1])                       # a new click doesn't restart it
        assert code == 202 and body["paused"] is True and body["started"] is False, body
        assert w.runner.kick() is False
        assert w.fake.started == []
        r = w.c.post("/api/apply/queue/resume")
        assert r.status_code == 200 and r.json()["paused"] is None
        assert w.fake.started == [WORKER] and w.calls == []


def test_p7b_a_start_up_pause_that_cannot_be_written_keeps_the_gate_closed_until_resume():
    def flaky_store_at_start_up(app):
        real, seen = app.state.store_factory, []

        def factory():
            st = real()
            if not seen:                                       # only the start-up hook's store
                seen.append(1)

                def locked(*_a, **_k):
                    raise sqlite3.OperationalError("database is locked")
                st.queue_clear_yield = locked
            return st
        app.state.store_factory = factory

    with _world(seed_waiting=1, before_client=flaky_store_at_start_up) as w:
        assert w.runner.gate_closed is True
        with _db(w) as st:
            assert st.queue_pause_state() is None              # the write did fail
        # the store works again now: still nothing starts on old clicks
        assert w.c.get("/api/apply/queue").json()["paused"]["reason"] == "restarted"
        code, body = _post(w, w.jobs[1])
        assert code == 202 and body["paused"] is True and body["started"] is False, body
        assert w.runner.kick() is False and w.fake.started == []
        assert w.c.post("/api/apply/queue/resume").status_code == 200   # the owner's click
        assert w.fake.started == [WORKER] and w.calls == []


# ------------------------------------------------------------------ P18 (H2)


def _source_dirs(base: Path):
    """(a main-checkout-like dir: `.git` is a DIRECTORY, a worktree-like dir: `.git` is a FILE)."""
    main_like, worktree_like = base / "main_like", base / "worktree_like"
    (main_like / ".git").mkdir(parents=True)
    worktree_like.mkdir()
    (worktree_like / ".git").write_text("gitdir: ../elsewhere/.git/worktrees/x", encoding="utf-8")
    return main_like, worktree_like


def test_p18_h2_a_dev_copy_or_the_switch_off_records_clicks_but_never_starts_the_worker():
    from jobscraper.web.applyqueue import apply_queue_wanted
    with tempfile.TemporaryDirectory() as t:
        main_like, worktree_like = _source_dirs(Path(t))     # same answer wherever the suite runs
        assert apply_queue_wanted({}, source_dir=main_like) is True
        assert apply_queue_wanted({}, source_dir=worktree_like) is False
        assert apply_queue_wanted({"JOBSCRAPER_APPLY_QUEUE": "0"}, source_dir=main_like) is False
        assert apply_queue_wanted({"JOBSCRAPER_DB": "C:/copy/jobscraper.db"},
                                  source_dir=main_like) is False
        assert apply_queue_wanted({"JOBSCRAPER_DB": "C:/copy/jobscraper.db",
                                   "JOBSCRAPER_APPLY_QUEUE": "1"}, source_dir=main_like) is True

    for env in ({"JOBSCRAPER_APPLY_QUEUE": "0"}, {"JOBSCRAPER_DB": "C:/copy/jobscraper.db"}):
        with _world(worker=apply_queue_wanted(env)) as w:     # slot free: a start would happen
            assert w.runner.timer_running is False
            code, body = _post(w, w.jobs[0])
            assert code == 202 and body["disabled"] is True and body["started"] is False, (env, body)
            assert body["queued"] == [{"job_id": w.jobs[0], "position": 1}]
            assert w.c.get("/api/apply/queue").json()["paused"]["reason"] == "disabled"
            assert w.c.get("/api/apply/status").json()["queue"]["paused"] == "disabled"
            r = w.c.post("/api/apply/queue/resume")
            assert r.status_code == 409 and r.json() == {"detail": "disabled"}, r.text
            assert w.runner.kick() is False
            with _db(w) as st:
                assert st.queue_pause_state() is None          # `disabled` is never stored
            w.fake.hold("apply")                               # no deferral without a runner
            assert w.c.post("/api/jobs/run").status_code == 409
            assert [k for k, _ in w.fake.started] == [] and w.calls == [], env


def test_f4_dev_copy_switch_truth_table_one_deviation_from_the_live_app_turns_it_off():
    """Review F4: unset, the worker is ON only for the owner's live app = no JOBSCRAPER_DB,
    no JOBSCRAPER_CONFIG, no --config, port 8765, code not from a worktree. Any single
    deviation is OFF; `=1` forces on (even on 8768 or from a worktree), `=0` forces off."""
    from jobscraper.web.applyqueue import apply_queue_wanted as wanted, running_from_worktree
    with tempfile.TemporaryDirectory() as t:
        main_like, worktree_like = _source_dirs(Path(t))
        assert running_from_worktree(main_like) is False
        assert running_from_worktree(worktree_like) is True
        live = dict(source_dir=main_like)
        assert wanted({}, **live) is True
        assert wanted({}, port=8765, **live) is True
        assert wanted({"JOBSCRAPER_PORT": "8765"}, **live) is True
        # forced
        for extra in ({}, {"port": 8768}, {"config_path": "x.yaml"}):
            assert wanted({"JOBSCRAPER_APPLY_QUEUE": "1", "JOBSCRAPER_PORT": "8768",
                           "JOBSCRAPER_DB": "c.db"}, source_dir=worktree_like, **extra) is True
        assert wanted({"JOBSCRAPER_APPLY_QUEUE": "0"}, **live) is False
        assert wanted({"JOBSCRAPER_APPLY_QUEUE": "0"}, port=8765, **live) is False
        # one deviation at a time, all OFF
        assert wanted({"JOBSCRAPER_PORT": "8768"}, **live) is False       # the review scenario
        assert wanted({"JOBSCRAPER_PORT": "abc"}, **live) is False        # not a number
        assert wanted({}, port=8769, **live) is False
        assert wanted({"JOBSCRAPER_PORT": "8765"}, port=8769, **live) is False   # `port` wins
        assert wanted({}, config_path="other.yaml", **live) is False
        assert wanted({"JOBSCRAPER_DB": "C:/copy/jobscraper.db"}, **live) is False
        assert wanted({"JOBSCRAPER_CONFIG": "other.yaml"}, **live) is False
        assert wanted({}, source_dir=worktree_like) is False
        assert wanted({}, port=8765, source_dir=worktree_like) is False


# ------------------------------------------------------------------ P21 (M1)


def test_p21_m1_get_queue_status_and_applications_write_nothing_and_start_nothing():
    with _world() as w:
        j1, j2, j3, *_ = w.jobs
        w.fake.hold("run")
        assert _post(w, j1)[0] == 202 and _post(w, j2)[0] == 202
        with _db(w) as st:                                     # an interrupted attempt (no worker)
            aid = st.create_attempt(j3, w.cid, "dry_run", utcnow())
            st.set_attempt_state(aid, "planning")
            st.commit()
        w.fake.release()                                       # a kick now WOULD start the worker
        before = _snapshot(w)
        first = w.c.get("/api/apply/queue").json()
        second = w.c.get("/api/apply/queue").json()
        assert first == second
        assert first["now"]["attempt_id"] == aid and first["now"]["state"] == "planning"
        assert first["now"]["interrupted"] is True             # shown, not reaped
        assert [x["job_id"] for x in first["waiting"]] == [j1, j2] and first["slot"] == "free"
        for path in ("/api/apply/status", "/api/applications"):
            assert w.c.get(path).status_code == 200
        assert _snapshot(w) == before and w.fake.started == []
        assert w.runner.kick() is True and w.fake.started == [WORKER]   # (the kick would have)


# ------------------------------------------------------------------ P19 (H3)


def test_p19_h3_untrack_removes_a_waiting_role_and_refuses_the_role_in_flight():
    with _world() as w:
        j1, j2, *_ = w.jobs
        w.fake.hold("run")
        assert _post(w, j1)[0] == 202 and _post(w, j2)[0] == 202
        assert w.c.delete(f"/api/applications/{j1}").status_code == 200
        with _db(w) as st:
            assert st.queue_positions() == {j2: 1}
        live = _take(w)                                        # the worker took j2
        assert live["job_id"] == j2
        r = w.c.delete(f"/api/applications/{j2}")
        assert r.status_code == 409 and r.json()["detail"] == "in_progress", r.text
        assert r.json()["text"] and r.json()["hint"]
        with _db(w) as st:
            assert st.application(j2)["status"] == "to_apply"  # nothing deleted
            assert st.attempts_for_job(j1) == [] and st.queue_take(utcnow()) == (None, [])


def test_f5_untrack_refuses_a_live_role_and_removes_a_waiting_role_with_its_queue_row():
    with _world() as w:
        j1, j2, *_ = w.jobs
        w.fake.hold("run")
        assert _post(w, j1, j2)[0] == 202
        live = _take(w)                                        # j1 is now in flight
        assert live["job_id"] == j1
        r = w.c.delete(f"/api/applications/{j1}")
        assert r.status_code == 409 and r.json()["detail"] == "in_progress", r.text
        with _db(w) as st:
            assert st.application(j1)["status"] == "to_apply"            # the row remains
            assert [a["id"] for a in st.attempts_for_job(j1)] == [live["attempt_id"]]
            assert st.live_attempt(j1) is not None                       # and the attempt
            assert st.queue_positions() == {j2: 1}
        assert w.c.delete(f"/api/applications/{j2}").status_code == 200   # waiting: both go together
        with _db(w) as st:
            assert st.application(j2) is None
            assert st.queue_positions() == {} and st.queue_items() == []
        assert w.c.delete(f"/api/applications/{j2}").status_code == 404


def test_f5_a_take_attempted_while_the_untrack_transaction_holds_the_lock_cannot_take_the_role():
    """The check and the delete are one BEGIN IMMEDIATE transaction: a worker `queue_take` that
    arrives between the live-attempt check and the delete waits, then finds the role gone."""
    with _world() as w:
        j1, *_ = w.jobs
        w.fake.hold("run")
        assert _post(w, j1)[0] == 202
        assert w.c.get("/api/apply/queue").json()["paused"] is None
        inside, release = threading.Event(), threading.Event()
        real = w.app.state.store_factory

        def factory():
            st = real()
            check = st.live_attempt

            def gated(*a, **k):                                # the untrack has taken its lock
                out = check(*a, **k)
                inside.set()
                release.wait(15)
                return out
            st.live_attempt = gated
            return st
        w.app.state.store_factory = factory
        out: dict = {}
        untrack = threading.Thread(target=lambda: out.update(r=w.c.delete(f"/api/applications/{j1}")))
        untrack.start()
        assert inside.wait(10), "the untrack never reached its check"

        def taker():
            with _db(w) as st:
                out["take"] = st.queue_take(utcnow())
        take = threading.Thread(target=taker)
        take.start()
        time.sleep(0.4)
        still_waiting = take.is_alive()
        release.set()
        untrack.join(15)
        take.join(15)
        assert still_waiting, "queue_take ran while the untrack transaction was open"
        assert out["r"].status_code == 200, out["r"].text
        assert out["take"] == (None, []), out["take"]
        with _db(w) as st:
            assert st.attempts_for_job(j1) == [] and st.application(j1) is None


def test_f6_stop_cancels_only_an_apply_job_holding_the_slot_and_the_live_attempt_id():
    """Review F6: the live attempt may be a leftover while a search run holds the slot;
    cancelling then would kill the run. Every refusal is 409 with nothing cancelled."""
    with _world() as w:
        j1, *_ = w.jobs
        assert _post(w, j1)[1]["started"] is True              # the worker holds the slot
        live = _take(w)
        stop = lambda attempt_id: w.c.post("/api/apply/queue/stop", json={"attempt_id": attempt_id})
        w.fake.hold("run")                                     # a search run holds the slot
        r = stop(live["attempt_id"])
        assert r.status_code == 409 and r.json() == {"detail": "already_finished"}, r.text
        assert w.fake.cancels == [] and w.fake.cur["kind"] == "run" and w.fake.cur["state"] == "running"
        w.fake.hold("apply")                                   # an apply job, but a wrong attempt id
        r = stop(live["attempt_id"] + 100)
        assert r.status_code == 409 and r.json() == {"detail": "already_finished"}, r.text
        assert w.fake.cancels == []
        r = stop(live["attempt_id"])                           # apply job + the live attempt
        assert r.status_code == 200, r.text
        assert len(w.fake.cancels) == 1 and w.fake.cur["state"] != "running"


# ------------------------------------------------------------------ P11 (M3)


def test_p11_m3_stop_checks_the_attempt_id_and_every_cancel_commits_the_pause_first():
    with _world() as w:
        j1, j2, *_ = w.jobs

        def pause_now():
            with _db(w) as st:
                state = st.queue_pause_state()
            return state and state["reason"]
        w.fake.on_cancel = pause_now

        assert _post(w, j1)[1]["started"] is True              # the worker runs (fake-1)
        live = _take(w)
        r = w.c.post("/api/apply/queue/stop", json={"attempt_id": live["attempt_id"] + 100})
        assert r.status_code == 409 and r.json() == {"detail": "already_finished"}, r.text
        assert w.fake.cancels == []                            # nothing else is cancelled
        assert pause_now() == "cancelled"                      # but the queue is paused
        r = w.c.post("/api/apply/queue/stop", json={"attempt_id": live["attempt_id"]})
        assert r.status_code == 200 and r.json()["paused"]["reason"] == "cancelled", r.text
        assert w.fake.cancels == ["cancelled"]                 # the pause was there at the signal

        # Cancel in the job pill on the worker: the pause is committed before the cancel too
        assert w.c.post("/api/apply/queue/resume").status_code == 200
        assert _post(w, j2)[1]["started"] is True              # fake-2
        assert pause_now() is None
        r = w.c.post("/api/jobs/cancel")
        assert r.status_code == 200, r.text
        assert w.fake.cancels == ["cancelled", "cancelled"]
        assert w.fake.started == [WORKER, WORKER] and w.calls == []


# ------------------------------------------------------------------ P13 (§6)


def test_p13_a_search_run_during_the_worker_is_deferred_then_runs_then_the_worker_again():
    with _world() as w:
        j1, j2, *_ = w.jobs
        assert _post(w, j1)[1]["started"] is True
        r = w.c.post("/api/jobs/run")
        assert r.status_code == 202 and r.json()["deferred"] is True, r.text
        assert r.json()["job"]["kind"] == "apply"
        with _db(w) as st:
            assert st.get_setting(Store.QUEUE_YIELD) == "1"
        assert w.c.get("/api/apply/queue").json()["run_pending"] is True
        assert [k for k, _ in w.fake.started] == ["apply"]

        w.fake.finish(0)                                       # the worker yielded
        assert w.runner.kick() is True
        assert [k for k, _ in w.fake.started] == ["apply", "run"]
        with _db(w) as st:
            assert not st.get_setting(Store.QUEUE_YIELD)       # cleared before the run (L4)
            assert st.queue_pause_state() is None              # a yield is not a pause
        assert w.c.get("/api/apply/queue").json()["run_pending"] is False

        assert _post(w, j2)[0] == 202                          # waits behind the run
        r = w.c.post("/api/jobs/run")
        assert r.status_code == 409, r.text                    # a run during a run: as before
        w.fake.finish(0)
        assert w.runner.kick() is True and w.fake.started[-1] == WORKER
        assert w.calls == []


# ------------------------------------------------------------------ P12 (exit codes)


def test_p12_worker_exit_codes_pause_once_and_only_for_the_worker_this_runner_started():
    from jobscraper.web.applyqueue import ApplyQueueRunner
    with _world() as w:
        w.fake.hold("run")
        for j in w.jobs[:3]:
            assert _post(w, j)[0] == 202
        w.fake.release()

        def pause():
            with _db(w) as st:
                state = st.queue_pause_state()
            return state and state["reason"]

        assert w.runner.kick() is True                         # fake-1
        w.fake.finish(1)
        assert w.runner.kick() is False and pause() == "worker_failed"
        assert len(w.fake.started) == 1                        # no restart loop

        assert w.c.post("/api/apply/queue/resume").status_code == 200    # fake-2
        w.fake.finish(3)
        assert w.runner.kick() is False and pause() == "busy_elsewhere"

        assert w.c.post("/api/apply/queue/resume").status_code == 200    # fake-3
        assert w.c.post("/api/apply/queue/pause").status_code == 200
        w.fake.finish(1)
        assert w.runner.kick() is False and pause() == "owner"           # first pause wins

        assert w.c.post("/api/apply/queue/resume").status_code == 200    # fake-4
        w.fake.finish(1)
        # a record this runner did not start (an earlier web process) is never judged
        fresh = ApplyQueueRunner(w.app.state, enabled=True)
        fresh.open_gate()
        assert fresh.kick() is True and pause() is None
        assert w.fake.started == [WORKER] * 5 and w.calls == []


# ------------------------------------------------------------------ status + Applications


def test_status_keeps_its_keys_and_applications_rows_carry_the_queue_position():
    with _world() as w:
        j1, j2, j3, *_ = w.jobs
        with _db(w) as st:                                     # j3 failed once before (Try again)
            aid = st.create_attempt(j3, w.cid, "dry_run", utcnow())
            st.set_attempt_state(aid, "failed", reason="cancelled", detail="test")
            st.set_application_status(j3, "to_apply")
            st.commit()
        w.fake.hold("run")
        for j in (j1, j2, j3):
            assert _post(w, j)[0] == 202
        status = w.c.get("/api/apply/status").json()
        assert {"mode", "missing", "busy", "queue"} <= set(status), status
        assert status["mode"] == "dry_run" and status["missing"] == [] and status["busy"] is True
        assert status["queue"] == {"waiting": 3, "applying": False, "paused": None}, status
        rows = {r["job_id"]: r for r in w.c.get("/api/applications").json()}
        for pos, j in enumerate((j1, j2, j3), start=1):
            assert rows[j]["queue"] == {"position": pos}, rows[j]
            assert rows[j]["last_attempt"]["kind"] == "queued", rows[j]["last_attempt"]
            assert rows[j]["last_attempt"]["state"] == "queued"
            assert rows[j]["last_attempt"]["id"] is None
        w.fake.hold("apply")
        assert w.c.get("/api/apply/status").json()["queue"]["applying"] is True


# ------------------------------------------------------------------ cross-site writes


def test_a_foreign_origin_write_to_every_queue_route_is_403_and_changes_nothing():
    with _world() as w:
        j1, j2, *_ = w.jobs
        w.fake.hold("run")
        assert _post(w, j1)[0] == 202
        w.fake.release()                                       # a kick could start the worker
        before = _snapshot(w)
        writes = (("POST", "/api/apply", {"job_ids": [j2]}),
                  ("DELETE", f"/api/apply/queue/{j1}", None),
                  ("POST", "/api/apply/queue/pause", None),
                  ("POST", "/api/apply/queue/stop", {"attempt_id": 1}),
                  ("POST", "/api/apply/queue/resume", None),
                  ("POST", "/api/apply/queue/clear", None),
                  ("POST", "/api/questions/retry", {"job_ids": [j1]}),
                  ("DELETE", f"/api/applications/{j1}", None),
                  ("POST", "/api/jobs/run", None))
        for method, path, body in writes:
            kw = {"json": body} if body is not None else {}
            r = w.c.request(method, path, headers=EVIL, **kw)
            assert r.status_code == 403, (method, path, r.status_code, r.text)
        assert _snapshot(w) == before
        assert w.fake.started == [] and w.fake.cancels == [] and w.calls == []
