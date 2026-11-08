"""Q-79: `apply.model_sees_sensitive` (D-105, D-107) through N6a's `_Run.body_llm`.

Q-74 pinned the flag in the resolver, the llm_fill hooks and `fill_page` called by hand. This file
pins the join: the `ResolveContext` that `body_llm` builds with `resolve_ctx(..., attempt_id=at.id)`
carries the effective flag into `fill_page`, and the "ignored" log line names the attempt.

  (a) flag on + a local (Ollama on 127.0.0.1) fake backend: the llm_fill prompt holds a synthetic
      private value (`facts_text` prints `private: <value>`) and the fill-cache `inputs_hash` differs
      from the flag-off run;
  (b) flag on + a non-local backend (a Docker host name, or an Ollama `x:cloud` tag, D-107): the flag
      is ignored (prompt and hash equal the flag-off run) and the log line
      `[attempt N] model_sees_sensitive ignored: ...` carries the attempt prefix, once per attempt;
  (c) in every case no S value is in a log line, an audit note/evidence or a cache row.

Two tiers. The scripted tier replaces `fill_page` (the n6a harness) and needs no browser. The Edge
tier runs the real `fill_page` over a recorded Workday page (skipped cleanly without headless Edge,
like the other browser oracles). Synthetic values only; scripted fake backends; no network, no Ollama,
temp DB, no data/.
Verify: python tests/run_tests.py -k q79
"""
from __future__ import annotations

import contextlib
import dataclasses
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_fill_t2 as T  # noqa: E402
import test_apply_flow_llm as LLM  # noqa: E402
import test_apply_flow_n6a as N  # noqa: E402
import test_q74_model_sees_sensitive as base  # noqa: E402
from apply_flow_support import sample_profile  # noqa: E402

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply import facts as F, llm_fill as L  # noqa: E402
from jobscraper.apply.contracts import AttemptState as S, FieldType as FT  # noqa: E402
from jobscraper.backends import Completion, OllamaBackend  # noqa: E402

LOCAL = "http://127.0.0.1:11434"
IGNORED = "model_sees_sensitive ignored: model backend is not on this computer"
PROTECTED = (base.RACE, base.FAITH, base.RESIDENCY, base.GENDER, base.DOB)


def synthetic_profile() -> dict:
    """The synthetic sample applicant with marker values on the S paths (never real data)."""
    p = sample_profile()
    p["identity"]["date_of_birth"] = base.DOB
    p["identity"]["gender"] = base.GENDER
    p["singapore_status"].update(race=base.RACE, religion=base.FAITH, residency_status=base.RESIDENCY)
    return p


class LocalFill(OllamaBackend):
    """An OllamaBackend with a scripted `complete` (never the network), whose url and model tag
    decide `backends.is_local` exactly as in production. `inner` is the scripted backend."""

    def __init__(self, url: str = LOCAL, model: str = "qwen3:14b", inner=None):
        super().__init__(url=url, model=model)
        self.inner = inner

    @property
    def available(self) -> bool:
        return True

    def warm(self, keep_alive=None):
        return None

    @property
    def calls(self):
        return getattr(self.inner, "calls", [])

    def complete(self, system, user, max_tokens=4096, **kw):
        if self.inner is None:
            raise AssertionError("no model call expected")
        return self.inner.complete(system, user, max_tokens, **kw)


def user_text(backend) -> str:
    return "\n".join(getattr(c, "user", "") for c in backend.calls)


# ------------------------------------------------------------------ tier 1: scripted fill_page

@contextlib.contextmanager
def capturing(nav):
    """Replace `fill_page` with a one-field script that records the rctx body_llm built."""
    got: list = []

    def fake(page, nav_, ctx, rctx, services):
        got.append(rctx)
        step = nav_.step_id(page, ctx)
        if step == "review":
            return N.outcome(step, [])
        return N.outcome(step, [N.pf("a", "First name")])
    saved = apply_flow.fill_page
    apply_flow.fill_page = fake
    try:
        yield got
    finally:
        apply_flow.fill_page = saved


def scripted_run(backend, *, flag: bool):
    w, jid = N.world(profile=synthetic_profile())
    try:
        nav = N.FakeNav(("one", "review"))
        with capturing(nav) as got:
            r, _factory, say, _m = N.run(w, jid, nav, backend, apply_over={"model_sees_sensitive": flag})
        rows = w.store.answers(r.attempt_id)
        return r, got, say, rows
    finally:
        w.close()


def llm_prompt(rctx) -> str:
    """The llm_fill user prompt for the facts and ctx body_llm handed to fill_page, built the way
    pagefill builds it (nothing redacted when the flag is on, the full S list when off)."""
    facts = F.fact_catalogue(rctx.profile, rctx, today=T.TODAY)
    sv = [] if rctx.model_sees_sensitive else F.s_values(rctx.profile, rctx.account_email)
    pf = T.pf("k", "Why do you want to work here?", FT.TEXTAREA, required=True)
    return L.user_prompt(L.Chunk("one:k", None, (pf,)), facts, rctx, step_title="Step", s_values=sv, cfg={})


def key(rctx) -> str:
    return F.inputs_hash(L.redact(rctx.resume_text or "", [] if rctx.model_sees_sensitive else
                                  F.s_values(rctx.profile, rctx.account_email)),
                         rctx.jd_text or "", sees_private=rctx.model_sees_sensitive)


def ignored_lines(say) -> list[str]:
    return [ln for ln in say.lines if "model_sees_sensitive ignored" in ln]


def test_a_flag_on_local_backend_body_llm_hands_fill_page_the_flag():
    be = LocalFill()
    r, got, say, _rows = scripted_run(be, flag=True)
    assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
    assert got and all(c.model_sees_sensitive is True for c in got), [c.model_sees_sensitive for c in got]
    assert not ignored_lines(say), "a local backend: nothing is ignored, so nothing is logged"
    up = llm_prompt(got[0])
    assert f"| private: {base.DOB}" in up, "facts_text prints the private value"
    for m in (base.GENDER, base.RACE, base.FAITH, base.RESIDENCY):
        assert m in up, m


def test_a_flag_off_local_backend_the_prompt_holds_no_private_value_and_the_key_differs():
    on = scripted_run(LocalFill(), flag=True)[1][0]
    off_r, off_got, off_say, _ = scripted_run(LocalFill(), flag=False)
    assert off_r.state is S.READY_TO_SUBMIT and off_got[0].model_sees_sensitive is False
    base.assert_no_s(llm_prompt(off_got[0]), "flag-off llm_fill prompt", PROTECTED)
    assert "| private, set" in llm_prompt(off_got[0])
    assert key(on) != key(off_got[0]), "the flag is part of the fill-cache key"
    assert not ignored_lines(off_say), "flag off: nothing to ignore, no line"


def _remote_cases():
    return (("a Docker/LAN host", dict(url="http://ollama:11434")),
            ("a cloud tag x:cloud (D-107)", dict(model="x:cloud")),
            ("a cloud tag -cloud", dict(model="gpt-oss:120b-cloud")))


def test_b_flag_on_non_local_backend_is_ignored_and_the_log_line_names_the_attempt():
    for what, kw in _remote_cases():
        r, got, say, _rows = scripted_run(LocalFill(**kw), flag=True)
        assert r.state is S.READY_TO_SUBMIT, (what, r.state, r.reason, r.reason_detail)
        assert got and all(c.model_sees_sensitive is False for c in got), (what, "flag must be off")
        lines = ignored_lines(say)
        assert lines, (what, "the 'ignored' line is missing")
        for ln in lines:
            assert re.search(rf"\[attempt {r.attempt_id}\] {re.escape(IGNORED)}$", ln), (what, ln)
        base.assert_no_s(llm_prompt(got[0]), f"llm_fill prompt via {what}", PROTECTED)
        assert key(got[0]) == key(scripted_run(LocalFill(), flag=False)[1][0]), \
            (what, "an ignored flag leaves the cache key as flag-off")
        base.assert_no_s(say.text, f"log via {what}", PROTECTED)
        assert "ollama:11434" not in say.text and "x:cloud" not in say.text, "no URL or model tag in the log"


def test_b_flag_off_remote_backend_logs_no_ignored_line():
    r, got, say, _ = scripted_run(LocalFill(url="http://ollama:11434"), flag=False)
    assert r.state is S.READY_TO_SUBMIT and got[0].model_sees_sensitive is False
    assert not ignored_lines(say)


def test_c_no_s_value_in_any_log_line_or_audit_row():
    for what, be, flag in (("local on", LocalFill(), True), ("local off", LocalFill(), False),
                           ("remote on", LocalFill(url="http://ollama:11434"), True),
                           ("cloud on", LocalFill(model="x:cloud"), True)):
        r, _got, say, rows = scripted_run(be, flag=flag)
        base.assert_no_s(say.text, f"log ({what})", PROTECTED)
        assert rows, "the page's audit rows exist"
        for x in rows:
            base.assert_no_s(" ".join(str(x.get(k) or "") for k in ("note", "evidence", "detail")),
                             f"audit row ({what})", PROTECTED)
        base.assert_no_s(str(r.reason_detail or ""), f"result detail ({what})", PROTECTED)


# ------------------------------------------------------------------ tier 2: the real fill_page over a recorded page

@contextlib.contextmanager
def cache_spy():
    """Record what the flow's FillServices is asked to read and write (a stub in N6a, so the
    rows stay empty; the point is that nothing S could be written, and the key is what pagefill built)."""
    gets, puts = [], []
    og, op = apply_flow._FillServices.cache_get, apply_flow._FillServices.cache_put

    def cache_get(self, job_id, sigs, prompt_version, model, inputs_hash):
        gets.append(inputs_hash)
        return og(self, job_id, sigs, prompt_version, model, inputs_hash)

    def cache_put(self, job_id, rows):
        puts.append(rows)
        return op(self, job_id, rows)
    apply_flow._FillServices.cache_get, apply_flow._FillServices.cache_put = cache_get, cache_put
    try:
        yield gets, puts
    finally:
        apply_flow._FillServices.cache_get, apply_flow._FillServices.cache_put = og, op


def edge_run(backend_kw: dict, *, flag: bool):
    """body_llm with the real fill_page over the recorded wd_b page. None without headless Edge."""
    from llm_fill_support import FIX, FakeFillBackend
    inner = FakeFillBackend.from_file(FIX / "wd_b" / "02-my_information" / "reply.json")
    be = LocalFill(inner=inner, **backend_kw)
    with cache_spy() as (gets, puts):
        out = LLM._run_fixture("llm_fill/wd_b/02-my_information/page.html", be,
                               resume_text=(FIX / "resume_sample.txt").read_text(encoding="utf-8"),
                               acfg_over={"model_sees_sensitive": flag})
    if out is None:
        return None
    # A run that never reached the model proves nothing: say what happened instead of passing vacuously.
    assert inner.calls, ("the attempt never called the model", out.r.state, out.r.reason, out.r.reason_detail,
                         out.say.lines[-6:])
    return out, inner, gets, puts


def sample_dob() -> str:
    return sample_profile()["identity"]["date_of_birth"]


def test_edge_a_real_fill_page_flag_on_local_prompt_holds_the_private_value_and_the_key_differs():
    on = edge_run({}, flag=True)
    off = edge_run({}, flag=False)
    if on is None or off is None:
        return
    dob = sample_dob()
    try:
        assert dob in user_text(on[1]), "flag on + local: the model reads the date of birth"
        assert f"| private: {dob}" in user_text(on[1])
        assert dob not in user_text(off[1]), "flag off: unchanged"
        assert on[2] and off[2] and set(on[2]).isdisjoint(off[2]), "inputs_hash differs between flag on and off"
        assert not ignored_lines(on[0].say)
        _c_edge(on, dob)
        _c_edge(off, dob)
    finally:
        on[0].w.close()
        off[0].w.close()


def test_edge_b_real_fill_page_flag_on_non_local_is_ignored_with_the_attempt_prefix():
    off = edge_run({}, flag=False)
    if off is None:
        return
    dob = sample_dob()
    try:
        for what, kw in (("host", dict(url="http://ollama:11434")), ("cloud tag", dict(model="x:cloud"))):
            on = edge_run(kw, flag=True)
            try:
                assert dob not in user_text(on[1]), (what, "the flag is ignored: no private value in the prompt")
                assert on[2] and set(on[2]) == set(off[2]), (what, "inputs_hash equals the flag-off key")
                lines = ignored_lines(on[0].say)
                assert lines, what
                assert all(re.search(rf"\[attempt {on[0].r.attempt_id}\] {re.escape(IGNORED)}$", ln) for ln in lines), lines
                _c_edge(on, dob)
            finally:
                on[0].w.close()
    finally:
        off[0].w.close()


def _c_edge(run, dob: str) -> None:
    out, _inner, _gets, puts = run
    assert dob not in out.say.text, "the log"
    assert dob not in repr(puts), "the cache rows"
    store = out.w.store
    for x in store.answers(out.r.attempt_id):
        assert dob not in " ".join(str(x.get(k) or "") for k in ("note", "evidence", "detail")), "the audit row"
    assert dob not in str(out.r.reason_detail or "")
