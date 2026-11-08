"""Unit tests of the two N6a review fixes (docs/reviews/Q-35-N6a.md F1, F2). No Edge, no Ollama.

F1: an auto-mode (not dry-run) attempt on the llm path never reaches Submit before the pre-Submit
    scan exists (WP-N6b); it ends READY_TO_SUBMIT with a note.
F2: the warm-up request carries the same `options.num_ctx` and `keep_alive` as the fill calls.
Verify: python tests/run_tests.py -k apply_n6a_review_fixes
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_apply_flow_n6a import FakeNav, scripted, two_steps, world, run  # noqa: E402

from jobscraper import apply_flow, backends  # noqa: E402
from jobscraper.apply.contracts import AttemptState as S  # noqa: E402


def test_f1_an_auto_mode_llm_attempt_stops_at_review_and_never_presses_submit():
    w, jid = world()
    try:
        nav = FakeNav()

        def boom(page, ctx):
            raise AssertionError("auto mode must not press Submit before the pre-Submit scan (N6b)")
        nav.submit = boom
        with scripted(nav, two_steps):
            r, factory, say, model = run(w, jid, nav, dry_run=False)
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail == apply_flow.AUTO_SUBMIT_BLOCKED == "auto submit needs the pre-Submit scan (N6b)"
        assert apply_flow.AUTO_SUBMIT_BLOCKED in say.text
        row = w.store.conn.execute("SELECT state, submit_clicked_at FROM apply_attempts").fetchone()
        assert row[0] == "ready_to_submit" and row[1] is None, tuple(row)
    finally:
        w.close()


def test_f1_a_dry_run_is_unchanged_and_carries_no_note():
    w, jid = world()
    try:
        nav = FakeNav()
        with scripted(nav, two_steps):
            r, *_ = run(w, jid, nav, dry_run=True)
        assert r.state is S.READY_TO_SUBMIT and not r.reason_detail, (r.state, r.reason_detail)
    finally:
        w.close()


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._p, self.text = status, payload or {}, ""

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Client:
    """Records every POST; answers /api/tags with the model pulled."""

    def __init__(self):
        self.posts = []

    def get(self, url, **kw):
        return _Resp(200, {"models": [{"name": "qwen3:14b"}]})

    def post(self, url, json=None, **kw):
        self.posts.append((url, json))
        if url.endswith("/api/show"):
            return _Resp(200, {"capabilities": ["thinking"]})
        if url.endswith("/api/chat"):
            return _Resp(200, {"message": {"content": "{}"}})
        return _Resp(200, {})


def test_f2_warm_up_sends_the_same_num_ctx_and_keep_alive_as_the_fill_calls():
    c = _Client()
    b = backends.OllamaBackend(model="qwen3:14b", num_ctx=16384, client=c)
    b.num_ctx = 32768                    # what cli.cmd_apply sets from apply.llm_fill.num_ctx
    backends.warm(b, "30m")
    b.complete("s", "u", keep_alive="30m")
    warm = next(j for u, j in c.posts if u.endswith("/api/generate"))
    chat = next(j for u, j in c.posts if u.endswith("/api/chat"))
    assert warm["options"]["num_ctx"] == chat["options"]["num_ctx"] == 32768, (warm, chat["options"])
    assert warm["keep_alive"] == chat["keep_alive"] == "30m"
    assert "prompt" not in warm and warm["model"] == "qwen3:14b"


def test_f2_warm_up_without_keep_alive_sends_none():
    c = _Client()
    b = backends.OllamaBackend(model="qwen3:14b", num_ctx=8192, client=c)
    backends.warm(b)
    (_, body), = [p for p in c.posts if p[0].endswith("/api/generate")]
    assert "keep_alive" not in body and body["options"] == {"num_ctx": 8192}
