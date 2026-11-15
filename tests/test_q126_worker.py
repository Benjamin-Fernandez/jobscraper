"""Q-126 lane E2 pins: the worker, CLI, pipeline and config half (D-214, D-217;
ollama_autostart_design.md §3, §4.3, §6 rule 7, §9 T11-T12c, T18, doctor line, config).

RED UNTIL eng/Q-126-E2 MERGES (the config pin too: E2 owns config/config.yaml).
Written against the DESIGN, not E2's code; do not weaken a pin to make it pass.

ASSUMED names (adapt `_run` / `Ensurer` if E2 differs; say so in the outbox):
  * `apply_flow.run_queue(..., model_ensurer=<callable>, model_autostart=<bool>)`: the
    callable replaces `backends.ensure_model_running` and is called as
    `model_ensurer(budget, **kw)` with the keywords `autostart`, `backend`, `load`,
    `keep_alive`, `on_state`, `should_stop`; it returns a `backends.ModelReady`;
  * the worker calls it only when `acfg.fill == "llm"` and the backend is a real
    `OllamaBackend` (here a subclass with no network); a fake backend keeps the old rule;
  * `on_state` writes `store.queue_model_state(...)`, cleared when the worker ends;
  * the retry note is exactly "the local AI model restarted";
  * the log line contains "goes again (once)".

Fakes only: the apply_flow fake world (temp DB, fake adapter and browser), a scripted
ensurer, `_Run.attempt` replaced as in tests/test_apply_queue_flow.py. Mode `dry_run`
throughout; no process, no socket, no real job, no `data/`.
"""
from __future__ import annotations

import dataclasses
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import FakeBrowserFactory, Say, page_signals, registered  # noqa: E402
from test_apply_queue_flow import _enqueue, _pause, _rows, _world  # noqa: E402

from jobscraper import apply_flow, backends  # noqa: E402
from jobscraper.apply.contracts import MODEL_PAUSE_BY_CODE, AttemptState  # noqa: E402
from jobscraper.store import utcnow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class FakeOllama(backends.OllamaBackend):
    """A real OllamaBackend by type (so the worker treats it as one), with no network."""
    available = True
    unavailable_code = ""

    def __init__(self):
        super().__init__(url="http://127.0.0.1:11434", model="qwen3:14b", client=object())

    def warm(self, keep_alive=None, *, timeout=None):
        pass

    def reset_probe(self):
        pass


class Ensurer:
    """Scripted model service: one ModelReady code per call, the last one repeats."""
    def __init__(self, store, *script, on_call=None):
        self.store, self.script, self.on_call = store, list(script or ["ready"]), on_call
        self.calls: list[dict] = []
        self.state_seen: list = []

    def __call__(self, budget, **kw):
        n = len(self.calls)
        self.calls.append(kw)
        code = self.script[min(n, len(self.script) - 1)]
        on_state = kw.get("on_state")
        if on_state:
            on_state("starting")
            self.state_seen.append(self.store.queue_model_view())
        if self.on_call:
            self.on_call(n)
        return backends.ModelReady(code, started=code == "ready", detail="d" if code != "ready" else "")


def _run(w, ad, ens, *, autostart=True, should_stop=None, fill="llm", backend=None):
    acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0, fill=fill,
                               mode="dry_run", daily_cap=0, per_employer_daily_cap=0)
    factory, say = FakeBrowserFactory(), Say()
    with registered(ad), page_signals(when=None):
        out = apply_flow.run_queue(
            w.cfg, w.store, backend=backend or FakeOllama(), apply_cfg_fn=lambda: acfg,
            http=object(), browser_factory=factory, say=say, evidence_dir=w.tmp / "evidence",
            should_stop=should_stop, model_ensurer=ens, model_autostart=autostart)
    return out, factory, say


@contextmanager
def _attempts(plan):
    """Replace `_Run.attempt`: plan(job_id, n) -> "down" | "down_clicked" | "other" | "ok"."""
    orig, counts = apply_flow._Run.attempt, {}

    def fake(self, job_id, *, attempt_id=None):
        n = counts[job_id] = counts.get(job_id, 0) + 1
        kind = plan(job_id, n)
        state, reason, detail, click = {
            "down": ("failed", "model_unavailable", "model unavailable (timeout)", None),
            "down_clicked": ("failed", "model_unavailable", "model unavailable", utcnow()),
            "other": ("failed", "unanswerable_required", "one question", None),
            "ok": ("ready_to_submit", None, None, None)}[kind]
        self.store.conn.execute(
            "UPDATE apply_attempts SET state=?, reason_code=?, reason_detail=?, submit_clicked_at=?"
            " WHERE id=?", (state, reason, detail, click, attempt_id))
        self.store.commit()
        return SimpleNamespace(attempt_id=attempt_id, state=AttemptState(state))
    apply_flow._Run.attempt = fake
    try:
        yield counts
    finally:
        apply_flow._Run.attempt = orig


def _notes(w):
    """Record the note of every queue_return."""
    notes, orig = [], w.store.queue_return

    def rec(*a, **k):
        notes.append(k.get("note", a[3] if len(a) > 3 else None))
        return orig(*a, **k)
    w.store.queue_return = rec
    return notes


# ------------------------------------------------------------------ T11: before each take

def test_each_not_ready_code_stores_the_mapped_pause_with_detail_takes_nothing_and_clears_state():
    for code, pause in MODEL_PAUSE_BY_CODE.items():
        w, ad, cid, (j1,) = _world(1)
        _enqueue(w, cid, [j1], "dry_run")
        ens = Ensurer(w.store, code)
        out, factory, _say = _run(w, ad, ens)
        st = _pause(w)
        assert st["reason"] == pause.value and st["detail"] == "d", (code, st)
        assert _rows(w) == [] and factory.started == 0, code            # no attempt row, no browser
        assert w.store.queue_positions() == {j1: 1}, code                # the role stays first
        assert w.store.queue_model_view() is None, code                  # worker state cleared
        assert ens.state_seen and ens.state_seen[0]["state"] == "starting"
        w.close()


def test_ready_lets_the_take_go_ahead_and_the_service_is_asked_to_load_and_to_stop_on_close():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    with _attempts(lambda j, n: "ok"):
        ens = Ensurer(w.store, "ready")
        out, _f, _s = _run(w, ad, ens)
    assert [r["job_id"] for r in _rows(w)] == [j1, j2] and _pause(w) is None
    assert len(ens.calls) >= 2                                           # before each take
    k = ens.calls[0]
    assert k["autostart"] is True and k["load"] is True and callable(k["should_stop"])
    assert isinstance(k["backend"], backends.OllamaBackend)
    w.close()


def test_the_run_queue_default_is_autostart_off_and_rules_fill_never_calls_the_service():
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    ens = Ensurer(w.store, "not_running")
    with _attempts(lambda j, n: "ok"):
        acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0, fill="llm",
                                   mode="dry_run", daily_cap=0, per_employer_daily_cap=0)
        with registered(ad), page_signals(when=None):
            apply_flow.run_queue(w.cfg, w.store, backend=FakeOllama(), apply_cfg_fn=lambda: acfg,
                                 http=object(), browser_factory=FakeBrowserFactory(), say=Say(),
                                 evidence_dir=w.tmp / "evidence", model_ensurer=ens)
    assert ens.calls and ens.calls[0]["autostart"] is False              # library default: no start
    assert _pause(w)["reason"] == "model_unavailable"
    w.close()
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    ens = Ensurer(w.store, "ready")
    with _attempts(lambda j, n: "ok"):
        _run(w, ad, ens, fill="rules")
    assert ens.calls == []                                               # fill != llm: no model needed
    w.close()


# ------------------------------------------------------------------ T11b, T11c: the stop checks

def test_a_close_during_the_model_wait_takes_nothing_and_pauses_app_closed():
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    stop = {"v": False}
    ens = Ensurer(w.store, "cancelled", on_call=lambda n: stop.update(v=True))
    _run(w, ad, ens, should_stop=lambda: stop["v"])
    assert _pause(w)["reason"] == "app_closed"
    assert _rows(w) == [] and w.store.queue_positions() == {j1: 1}
    w.close()


def test_a_close_right_after_a_ready_precheck_takes_nothing():
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    stop = {"v": False}
    ens = Ensurer(w.store, "ready", on_call=lambda n: stop.update(v=True))
    _run(w, ad, ens, should_stop=lambda: stop["v"])
    assert _pause(w)["reason"] == "app_closed"
    assert _rows(w) == [] and w.store.queue_positions() == {j1: 1}       # T11c
    w.close()


# ------------------------------------------------------------------ T12: the one retry

def test_a_model_failure_after_a_take_restarts_the_model_and_the_role_goes_again_once():
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    notes = _notes(w)
    with _attempts(lambda j, n: "down" if n == 1 else "ok"):
        ens = Ensurer(w.store, "ready")
        out, _f, say = _run(w, ad, ens)
    rows = _rows(w)
    assert [(r["state"], r["reason_code"]) for r in rows] == [
        ("failed", "model_unavailable"), ("ready_to_submit", None)], rows
    assert notes == ["the local AI model restarted"], notes              # exactly these words (C11)
    assert _pause(w) is None and w.store.queue_positions() == {}
    assert any("goes again (once)" in str(line) for line in say.lines), say.lines
    w.close()


def test_the_same_role_failing_again_pauses_model_not_answering_and_is_returned():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    with _attempts(lambda j, n: "down"):
        _run(w, ad, Ensurer(w.store, "ready"))
    st = _pause(w)
    assert st["reason"] == "model_not_answering", st
    assert [r["job_id"] for r in _rows(w)] == [j1, j1]                   # one retry, then stop
    assert w.store.queue_positions() == {j1: 1, j2: 2}
    w.close()


def test_the_retry_cap_is_two_per_worker_run():
    w, ad, cid, (j1, j2, j3) = _world(3)
    _enqueue(w, cid, [j1, j2, j3], "dry_run")
    with _attempts(lambda j, n: "down" if n == 1 else "ok") as counts:
        _run(w, ad, Ensurer(w.store, "ready"))
    assert counts == {j1: 2, j2: 2, j3: 1}, counts                       # j3 got no retry
    assert _pause(w)["reason"] == "model_not_answering"
    assert w.store.queue_positions() == {j3: 1}
    w.close()


def test_a_close_after_the_post_item_wait_returns_the_role_and_takes_no_other():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    stop = {"v": False}
    ens = Ensurer(w.store, "ready", on_call=lambda n: stop.update(v=(n >= 1)))   # 2nd call = post-item
    with _attempts(lambda j, n: "down"):
        _run(w, ad, ens, should_stop=lambda: stop["v"])
    assert _pause(w)["reason"] == "app_closed"
    assert [r["job_id"] for r in _rows(w)] == [j1]
    assert w.store.queue_positions() == {j1: 1, j2: 2}
    w.close()


def test_a_post_item_wait_that_does_not_end_ready_returns_the_role_with_the_mapped_pause():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    with _attempts(lambda j, n: "down"):
        _run(w, ad, Ensurer(w.store, "ready", "load_failed"))
    st = _pause(w)
    assert st["reason"] == "model_load_failed" and st["detail"] == "d", st
    assert [r["job_id"] for r in _rows(w)] == [j1]
    assert w.store.queue_positions() == {j1: 1, j2: 2}
    w.close()


def test_no_retry_for_another_outcome_or_after_the_submit_click():
    w, ad, cid, (j1,) = _world(1)                                        # another failure reason
    _enqueue(w, cid, [j1], "dry_run")
    notes = _notes(w)
    with _attempts(lambda j, n: "other") as counts:
        _run(w, ad, Ensurer(w.store, "ready"))
    assert counts == {j1: 1} and notes == []
    w.close()
    w, ad, cid, (j1, j2) = _world(2)                                     # Submit was clicked (NF-06)
    _enqueue(w, cid, [j1, j2], "dry_run")
    notes = _notes(w)
    with _attempts(lambda j, n: "down_clicked" if j == j1 else "ok") as counts:
        _run(w, ad, Ensurer(w.store, "ready"))
    assert counts.get(j1) == 1 and notes == [], (counts, notes)
    assert j1 not in w.store.queue_positions(), "a role with Submit clicked is never returned"
    w.close()


# ------------------------------------------------------------------ T18, doctor, config

def test_the_pipeline_default_never_starts_the_model():
    import inspect
    from jobscraper import pipeline
    p = inspect.signature(pipeline.run).parameters.get("model_autostart")
    assert p is not None and p.default is False


def test_the_doctor_line_says_autostart_state_and_never_a_path():
    from jobscraper import cli
    from jobscraper.config import Config
    line = cli._doctor_autostart_line(Config({"budget": {"enable_llm": True, "backend": "ollama"}}))
    assert isinstance(line, str) and line.lstrip().lower().startswith("autostart")
    assert "off in this copy" in line                                    # the suite sets the variable to 0
    assert "\\" not in line and ":/" not in line and "ollama.exe" not in line.lower()


def test_the_repository_config_turns_autostart_on_and_leaves_the_program_path_commented():
    text = (ROOT / "config" / "config.yaml").read_text(encoding="utf-8")
    budget = yaml.safe_load(text)["budget"]
    assert budget.get("ollama_autostart") is True
    assert "ollama_path" not in budget                                   # never set in the repository
    assert "# ollama_path:" in text or "#ollama_path:" in text


# ------------------------------------------------------------------ T13e

def test_after_a_click_lift_a_failing_model_check_stores_the_precise_pause_again_and_takes_nothing():
    from jobscraper.apply.contracts import MODEL_PAUSE_VALUES
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    w.store.queue_resume(utcnow())                                       # an earlier Resume: window start
    resumed = w.store.get_setting("apply_queue.resumed_at")
    w.store.queue_pause("model_unavailable", None, utcnow())
    assert w.store.queue_resume_if(set(MODEL_PAUSE_VALUES), utcnow(),
                                   keep_window=MODEL_PAUSE_VALUES) == "model_unavailable"
    assert _pause(w) is None                                             # the click lifted it
    _run(w, ad, Ensurer(w.store, "not_installed"))
    st = _pause(w)
    assert st["reason"] == "model_not_installed" and st["detail"] == "d", st
    assert _rows(w) == [] and w.store.queue_positions() == {j1: 1}
    assert w.store.get_setting("apply_queue.resumed_at") == resumed      # the streak window kept
    w.close()
