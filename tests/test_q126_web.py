"""Q-126 lane W1 pins: the web half of "the app starts the local model" (D-214, D-217;
ollama_autostart_design.md §4.1-§4.5, §9 T13-T13f, T14, T16, T19, T20).

RED UNTIL eng/Q-126-W1 MERGES (the tests that touch only E1 code, or only the contract,
are already green: they are marked in their docstring). Written against the DESIGN, not
against W1's code. Do not weaken a pin to make it pass.

The rule these pin (mode is `auto`, so a lifted pause can mean a real submission):
  * no timer, tick, probe or page load lifts a model pause: only the owner's Resume or a
    new Inbox Auto-apply click does (R1);
  * the click lifts ONLY a model pause (the seven in MODEL_CLICK_RESUME), only when the
    runner is enabled and its restart gate is open, and never writes `resumed_at` (the
    bot-check streak survives); every other pause waits for Resume;
  * the web never waits for the model and never starts it: only the worker does;
  * `budget.ollama_path` cannot be set from the web (only the boolean switch can).

ASSUMED names (adapt the one helper if W1 differs and say so in the outbox): the click
lift goes through `Store.queue_resume_if`; `PUT /api/connections/model/autostart` stores the
settings row `budget.ollama_autostart` ("true"/"false"); the card facts are `autostart`,
`autostart_here`, `installed`; the web asks `backends.autostart_allowed_here` through the
module attribute (the card test patches it); `GET /api/apply/queue` gains a `model` key.

Fakes only: a temp DB, FakeJobs (no child process), an in-memory keyring, a fake probe. No
real job is started, no `data/`, no socket to Ollama, never port 8765.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_apply_queue_web import EVIL, WORKER, _db, _post, _world  # noqa: E402
from test_connections import ProbeStub, _wait_until, _web  # noqa: E402

from jobscraper import backends  # noqa: E402
from jobscraper.apply.contracts import (MODEL_PAUSE_VALUES, QUEUE_PAUSE_TEXTS,  # noqa: E402
                                        QueuePause)
from jobscraper.store import Store  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src" / "jobscraper"
NOW = "2026-11-15T08:00:00Z"
OLD = "2026-11-14T09:00:00Z"
MODEL = sorted(MODEL_PAUSE_VALUES)
NON_MODEL = ["owner", "cancelled", "bot_checks", "repeated_errors", "restarted",
             "app_closed", "daily_limit"]


def _pause(w, reason, detail=None, resumed=None):
    with _db(w) as st:
        if resumed:
            st.queue_resume(resumed)
        assert st.queue_pause(reason, detail, NOW) is True


def _snap(w):
    with _db(w) as st:
        return (st.queue_pause_state(), st.get_setting(Store.QUEUE_RESUMED_AT),
                st.queue_positions())


def _wait_role(w, job):
    """A waiting role put in by the store (not by a click, so nothing is lifted)."""
    with _db(w) as st:
        st.set_application_status(job, "to_apply")
        st.queue_add(job, w.cid, "dry_run", "inbox", NOW)
        st.commit()


# ------------------------------------------------------------------ the click (T13b, T13c)

def test_a_click_lifts_each_model_pause_and_never_writes_resumed_at():
    for reason in MODEL:
        with _world() as w:
            _pause(w, reason, "qwen3:14b", resumed=OLD)
            code, body = _post(w, w.jobs[0])
            assert code == 202 and body["paused"] is False and body["started"] is True, (reason, body)
            assert w.fake.started == [WORKER], reason                 # the worker starts: it ensures
            pause, resumed, pos = _snap(w)
            assert pause is None and resumed == OLD, (reason, pause, resumed)   # streak window kept
            assert pos == {w.jobs[0]: 1}


def test_a_click_never_lifts_any_other_pause():
    for reason in NON_MODEL:
        with _world() as w:
            _pause(w, reason, "d", resumed=OLD)
            code, body = _post(w, w.jobs[0])
            assert code == 202 and body["paused"] is True and body["started"] is False, (reason, body)
            pause, resumed, pos = _snap(w)
            assert pause["reason"] == reason and resumed == OLD, reason
            assert pos == {w.jobs[0]: 1}, "the role still queues"
            assert w.fake.started == [], reason


def test_a_click_lifts_nothing_when_the_runner_is_off_or_the_gate_is_closed():
    with _world(worker=False) as w:                                   # a dev copy
        _pause(w, "model_missing", "qwen3:14b")
        code, body = _post(w, w.jobs[0])
        assert code == 202 and body["disabled"] is True
        assert _snap(w)[0]["reason"] == "model_missing"
    with _world() as w:
        _pause(w, "model_missing", "qwen3:14b")
        w.runner.close_gate()                                         # the restart gate (M2)
        _post(w, w.jobs[0])
        assert _snap(w)[0]["reason"] == "model_missing" and w.fake.started == []


def test_the_questions_retry_route_does_not_lift_a_pause():
    src = (SRC / "web" / "routers" / "questions.py").read_text(encoding="utf-8")
    assert "lift_model_pause" not in src and "queue_resume" not in src
    apply_src = (SRC / "web" / "routers" / "apply.py").read_text(encoding="utf-8")
    assert apply_src.count("queue_resume_if(") >= 1 and "MODEL_PAUSE_VALUES" in apply_src


# ------------------------------------------------------------------ Resume (T13c)

def test_resume_lifts_a_model_pause_without_stamping_and_stamps_for_others():
    with _world() as w:
        _pause(w, "model_load_failed", "qwen3:14b", resumed=OLD)
        r = w.c.post("/api/apply/queue/resume")
        assert r.status_code == 200 and r.json()["paused"] is None, r.text
        assert _snap(w)[1] == OLD
    with _world() as w:
        _pause(w, "owner", resumed=OLD)
        assert w.c.post("/api/apply/queue/resume").status_code == 200
        pause, resumed, _ = _snap(w)
        assert pause is None and resumed not in (None, OLD)           # a new streak window


# ------------------------------------------------------------------ nothing lifts by itself (T13)

def test_no_tick_probe_or_page_load_lifts_a_model_pause():
    for reason in MODEL:
        with _world() as w:
            _pause(w, reason, "qwen3:14b", resumed=OLD)
            _wait_role(w, w.jobs[0])
            for _ in range(5):
                assert w.runner.kick() is False                       # the tick's own call
            for path in ("/api/apply/queue", "/api/apply/status", "/api/connections"):
                for _ in range(2):
                    w.c.get(path)
            pause, resumed, pos = _snap(w)
            assert pause["reason"] == reason and resumed == OLD, reason
            assert w.fake.started == [] and pos == {w.jobs[0]: 1}


def test_structurally_only_the_resume_route_and_the_click_helper_call_a_resume():
    """No scheduler, tick, mail timer or connection probe may reference a resume call."""
    call = re.compile(r"\.queue_resume(?:_if)?\(")
    found = {p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")
             if call.search(p.read_text(encoding="utf-8", errors="replace"))}
    assert found <= {"store.py", "web/routers/apply.py"}, found
    for name in ("applyqueue.py", "connections.py", "mailsync.py", "jobs.py", "control.py"):
        text = (SRC / "web" / name).read_text(encoding="utf-8")
        assert "queue_resume" not in text, name


def test_the_web_never_starts_or_waits_for_the_model():
    for p in (SRC / "web").rglob("*.py"):
        assert "ensure_model_running" not in p.read_text(encoding="utf-8"), p.name
    saved = backends.ensure_model_running
    def boom(*a, **k):
        raise AssertionError("a web route called the model service")
    backends.ensure_model_running = boom
    try:
        with _world() as w:
            _pause(w, "model_missing", "qwen3:14b")
            assert _post(w, w.jobs[0])[0] == 202
        with _world() as w:
            _pause(w, "model_unavailable")
            assert w.c.post("/api/apply/queue/resume").status_code == 200
    finally:
        backends.ensure_model_running = saved


# ------------------------------------------------------------------ the status payload (§4.1)

def test_the_queue_view_carries_the_model_state_only_while_the_apply_worker_holds_the_slot():
    with _world() as w:
        assert w.c.get("/api/apply/queue").json()["model"] is None
        with _db(w) as st:
            st.queue_model_state("starting", NOW)
        assert w.c.get("/api/apply/queue").json()["model"] is None   # slot is not `apply`
        w.fake.hold("apply")
        view = w.c.get("/api/apply/queue").json()
        assert view["slot"] == "apply" and view["model"] == {"state": "starting", "since": NOW}
        with _db(w) as st:
            st.queue_model_state("loading", NOW)
        assert w.c.get("/api/apply/queue").json()["model"]["state"] == "loading"
        with _db(w) as st:
            st.queue_model_state(None, NOW)
        assert w.c.get("/api/apply/queue").json()["model"] is None


# ------------------------------------------------------------------ the restart rule (T14)

def _seed_pause(reason):
    def before(app):
        st = app.state.store_factory()
        st.queue_pause(reason, "qwen3:14b", NOW)
        st.close()
    return before


def test_at_start_up_a_model_pause_with_waiting_roles_becomes_restarted_and_a_click_cannot_lift_it():
    with _world(seed_waiting=1, before_client=_seed_pause("model_missing")) as w:
        assert _snap(w)[0]["reason"] == "restarted"
        code, body = _post(w, w.jobs[1])
        assert code == 202 and body["paused"] is True and body["started"] is False, body
        assert _snap(w)[0]["reason"] == "restarted" and w.fake.started == []
        assert w.c.post("/api/apply/queue/resume").status_code == 200      # the owner's Resume
        assert w.fake.started == [WORKER]


def test_a_model_pause_with_no_waiting_roles_survives_start_up_and_the_next_click_lifts_it():
    with _world(before_client=_seed_pause("model_start_failed")) as w:
        assert _snap(w)[0]["reason"] == "model_start_failed"
        code, body = _post(w, w.jobs[0])
        assert code == 202 and body["paused"] is False and w.fake.started == [WORKER], body


# ------------------------------------------------------------------ the copy (T20)

def test_pause_copy_formats_the_detail_in_the_hint_and_no_brace_reaches_the_owner():
    from jobscraper.web.routers.apply import _pause_copy
    c = _pause_copy("model_missing", "qwen3:14b", NOW)
    assert "ollama pull qwen3:14b" in c["hint"] and "{" not in c["text"] + c["hint"]
    for reason in MODEL:
        for detail in ("x", None, ""):
            c = _pause_copy(reason, detail, NOW)
            assert "{" not in c["text"] + c["hint"] and "}" not in c["text"] + c["hint"], (reason, detail)
    assert "{" not in _pause_copy("model_port_taken", "11434", NOW)["text"]


# ------------------------------------------------------------------ the switch (T16)

def _store(w):
    return Store(w.cfg.db_path)


def test_the_autostart_switch_saves_only_a_boolean_and_round_trips():
    with _web() as w:
        r = w.client.put("/api/connections/model/autostart", json={"enabled": False})
        assert r.status_code == 200 and r.json() == {"enabled": False, "default": True}, r.text
        st = _store(w)
        try:
            assert st.get_setting("budget.ollama_autostart") == "false"
        finally:
            st.close()
        r = w.client.put("/api/connections/model/autostart", json={"enabled": True})
        assert r.status_code == 200 and r.json()["enabled"] is True
        for bad in ({"enabled": "yes"}, {"enabled": None}, {"enabled": []}, {}, {"on": True}):
            r = w.client.put("/api/connections/model/autostart", json=bad)
            assert r.status_code == 422, (bad, r.status_code)
        r = w.client.put("/api/connections/model/autostart", json={"enabled": "yes"})
        body = r.json()
        assert body["detail"] == "invalid" and body["errors"][0]["field"] == "enabled"
        st = _store(w)
        try:
            assert st.get_setting("budget.ollama_autostart") == "true"        # bad bodies changed nothing
        finally:
            st.close()


def test_the_switch_is_refused_cross_site_and_cannot_set_the_program_path():
    with _web() as w:
        r = w.client.put("/api/connections/model/autostart", json={"enabled": False}, headers=EVIL)
        assert r.status_code == 403
        w.client.put("/api/connections/model/autostart",
                     json={"enabled": True, "ollama_path": "C:/evil/ollama.exe",
                           "budget.ollama_path": "C:/evil/ollama.exe"})
        st = _store(w)
        try:
            assert st.get_setting("budget.ollama_path") is None
            assert st.get_setting("budget.ollama_autostart") in (None, "true")
        finally:
            st.close()
    for p in (SRC / "web").rglob("*.py"):                                     # structural: no web writer
        assert "ollama_path" not in p.read_text(encoding="utf-8"), p.name


# ------------------------------------------------------------------ the Local AI card (T19)

LOCAL = {"enable_llm": True, "backend": "ollama", "ollama_model": "example-model:8b",
         "ollama_url": "http://127.0.0.1:11434"}


class InstalledProbe(ProbeStub):
    def __init__(self, ok, code, installed):
        super().__init__(ok=ok, code=code)
        self.installed = installed

    def __call__(self, budget):
        with self._lock:
            self.calls += 1
        self.started.set()
        return backends.Probe(ok=self.ok, code=self.code, backend="ollama", model="example-model:8b",
                              local=True, installed=self.installed)


class _Busy:
    """A running search run: something is waiting on the model (need_now)."""
    def current(self, tail=0):
        return {"id": "r1", "kind": "run", "state": "running", "started_at": NOW,
                "finished_at": None, "exit_code": None}


def _card(w):
    w.client.get("/api/connections")
    assert _wait_until(lambda: not w.app.state.model_health.in_flight)
    items = w.client.get("/api/connections").json()["items"]
    return [i for i in items if i["id"] == "model"][0]


def _with_here(value):
    saved = backends.autostart_allowed_here
    backends.autostart_allowed_here = lambda **kw: value
    return saved


def test_unreachable_card_is_neutral_when_autostart_is_on_installed_here_and_no_model_pause():
    saved = _with_here(True)
    try:
        with _web(InstalledProbe(False, "unreachable", True), budget=LOCAL) as w:
            w.app.state.jobs = _Busy()
            m = _card(w)
            assert (m["state"], m["code"]) == ("neutral", "unreachable"), m
            f = m["facts"]
            assert f["autostart"] is True and f["installed"] is True and f["autostart_here"] is True
            blob = json.dumps(f)
            assert "\\" not in blob and ":/" not in blob and "ollama.exe" not in blob   # no path
    finally:
        backends.autostart_allowed_here = saved


def test_a_stored_model_pause_makes_the_card_attention_with_its_text():
    saved = _with_here(True)
    try:
        with _web(InstalledProbe(False, "unreachable", True), budget=LOCAL) as w:
            w.app.state.jobs = _Busy()
            st = _store(w)
            try:
                st.queue_pause("model_start_failed", "no answer after 60 seconds", NOW)
            finally:
                st.close()
            m = _card(w)
            assert m["state"] == "attention", m
            blob = json.dumps(m)
            assert "model_start_failed" in blob or "tried to start Ollama" in blob, blob
    finally:
        backends.autostart_allowed_here = saved


def test_the_card_stays_attention_when_not_installed_switched_off_or_not_here():
    saved = _with_here(True)
    try:
        with _web(InstalledProbe(False, "unreachable", False), budget=LOCAL) as w:      # not installed
            w.app.state.jobs = _Busy()
            assert _card(w)["state"] == "attention"
        with _web(InstalledProbe(False, "unreachable", True), budget=LOCAL) as w:       # switched off
            w.app.state.jobs = _Busy()
            assert w.client.put("/api/connections/model/autostart", json={"enabled": False}).status_code == 200
            m = _card(w)
            assert m["state"] == "attention" and m["facts"]["autostart"] is False, m
    finally:
        backends.autostart_allowed_here = saved
    saved = _with_here(False)                                                           # a copy
    try:
        with _web(InstalledProbe(False, "unreachable", True), budget=LOCAL) as w:
            w.app.state.jobs = _Busy()
            m = _card(w)
            assert m["state"] == "attention" and m["facts"]["autostart_here"] is False, m
    finally:
        backends.autostart_allowed_here = saved


def test_a_reachable_card_is_unchanged():
    saved = _with_here(True)
    try:
        with _web(InstalledProbe(True, "", True), budget=LOCAL) as w:
            m = _card(w)
            assert (m["state"], m["code"]) == ("connected", "ok")
    finally:
        backends.autostart_allowed_here = saved
