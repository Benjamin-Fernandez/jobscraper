"""Q-121 WP-F1 flow oracles (D-208; llm_first_fill_design §2 K1/K2/K8, §6, §9, §12, §13 oracles
8, 9, 10, 18, 20 plus the flow side of 6 and the strict-unchanged checks).

Why these pins matter: with `apply.fill_policy: always` and `apply.mode: auto` every Auto-apply
click fills AND SUBMITS a real application through this code, with no review step. So the pins
fail when: a secret reaches a prompt; a stop is mapped to the wrong outcome (a wrong pause, a
role returned that must not be, a role lost that must be); the strict path changes; a trial
attempt submits; the policy switch takes effect where it must not.

The seam is tests/always_flow_support.py: a real `OllamaBackend` on 127.0.0.1:11434 over an
`httpx.MockTransport` (every request recorded), the real flow (`apply_flow.run` / `run_queue`),
a counting fake navigator and fake browser, a scripted page (`fill_page` replaced; the
model-facing pages run the REAL `always.fill_page_always`). Temp DB and the test config only.
No model, no network, no real application, dummy data, employer "Example Co".
Verify: python tests/run_tests.py -k always_flow
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import Net, backend, forms, make, nav_class, page, run_batch, run_q  # noqa: E402
from vault_support import memory_keyring  # noqa: E402

from jobscraper import apply_flow, backends  # noqa: E402
from jobscraper.apply import always as AL  # noqa: E402
from jobscraper.apply.classify import PageSignal  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AttemptState as ST, FillPolicy, QueuePause, ReasonCode as R,
)
from jobscraper.config import ApplyConfig  # noqa: E402

SECRET = 'Pw"Dummy\\Zq7 x9!'          # a quote, a backslash and a space: raw and JSON forms differ
ALWAYS = {"fill_policy": "always"}


def _extra_note(value: str) -> dict:
    return {"portal_note": {"title": "Portal note", "description": "", "kind": "text", "sensitive": False,
                            "labels": ["dummy portal note"], "value": value}}


def _profile_with_extra(value: str) -> dict:
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["extra"] = _extra_note(value)
    return p


def _row(w, job_id):
    rows = [r for r in w.attempt_rows() if r["job_id"] == job_id]
    return rows[-1] if rows else None


# ================================================================== policy (K2, oracle 9)

def test_the_default_policy_is_strict_and_a_plain_run_is_a_strict_run():
    assert ApplyConfig().fill_policy == "strict" and ApplyConfig().always_trial_runs == 0
    assert ApplyConfig.from_raw({}).fill_policy == "strict"
    w, _cid, jobs = make(1)
    try:
        net = Net()
        res, _f, say = run_batch(w, jobs, nav_class()(), backend(net))      # no fill_policy given
        assert res[0].state is ST.READY_TO_SUBMIT
        rctx = say.calls[0]["rctx"]
        assert rctx.fill_policy is FillPolicy.STRICT and rctx.model_sees_sensitive is False
        assert "fill policy" not in say.text and "fill_policy" not in say.text, "strict says nothing"
        assert [p for _m, p, _b in net.log if p == "/api/chat"] == [], \
            "strict warms with a bare generate, never the briefing prefix"
        assert all(not x["assumed"] for x in w.store.answers(res[0].attempt_id))
    finally:
        w.close()


def test_always_is_effective_only_with_a_local_model_and_the_llm_filler():
    acfg = ApplyConfig.from_raw({"fill_policy": "always", "fill": "llm", "always_available": True})
    local = backend(Net())
    assert apply_flow.effective_policy(acfg, local) == (FillPolicy.ALWAYS, "")
    for be, why in ((backend(Net(), url="http://ollama:11434"), apply_flow.POLICY_NOT_LOCAL),
                    (backend(Net(), model="qwen3:cloud"), apply_flow.POLICY_NOT_LOCAL),
                    (backend(Net(), model="gpt-oss:120b-cloud"), apply_flow.POLICY_NOT_LOCAL),
                    (backends.OffBackend(), apply_flow.POLICY_NOT_LOCAL)):
        assert apply_flow.effective_policy(acfg, be) == (FillPolicy.STRICT, why), why
    rules = ApplyConfig.from_raw({"fill_policy": "always", "fill": "rules", "always_available": True})
    assert apply_flow.effective_policy(rules, local) == (FillPolicy.STRICT, apply_flow.POLICY_NOT_LLM)
    strict = ApplyConfig.from_raw({"fill_policy": "strict"})
    assert apply_flow.effective_policy(strict, local) == (FillPolicy.STRICT, "")
    assert apply_flow.effective_policy(ApplyConfig(), local) == (FillPolicy.STRICT, "")


def test_a_non_local_model_runs_the_attempt_strict_and_the_log_says_why():
    w, _cid, jobs = make(1)
    try:
        for be_kw in ({"url": "http://ollama:11434"}, {"model": "qwen3:cloud"}):
            net = Net()
            res, _f, say = run_batch(w, [jobs[0]], nav_class()(), backend(net, **be_kw), **ALWAYS)
            w.store.conn.execute("DELETE FROM apply_attempts")
            w.store.commit()
            assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason_detail)
            assert apply_flow.POLICY_NOT_LOCAL in say.text, say.text
            rctx = say.calls[0]["rctx"]
            assert rctx.fill_policy is FillPolicy.STRICT and rctx.model_sees_sensitive is False
            assert not any(p == "/api/chat" for _m, p, _b in net.log), "no briefing prefix was sent"
            assert "assumed=" not in say.text, "no assumption counters under strict"
    finally:
        w.close()


def test_a_bad_stored_policy_is_strict_and_never_a_start_up_error():
    import logging
    from jobscraper.config import Config
    from apply_flow_support import make_world
    for bad in ("sometimes", "", "ALWAYS?", 7, ["always"], {"a": 1}):
        a = ApplyConfig.from_raw({"fill_policy": bad, "always_trial_runs": "many"})
        assert (a.fill_policy, a.always_trial_runs) == ("strict", 0), bad
    assert ApplyConfig.from_raw({"always_trial_runs": -3}).always_trial_runs == 0
    w = make_world()
    try:
        logging.disable(logging.CRITICAL)
        base = ApplyConfig.from_raw({"fill_policy": "strict"})
        for stored, want in (("bogus", "strict"), ("always", "always"), ("strict", "strict"), ("", "strict")):
            w.store.set_setting("apply.fill_policy", stored)
            assert base.with_settings(w.store.get_setting).fill_policy == want, stored
        w.store.set_setting("apply.always_trial_runs", "x")
        assert base.with_settings(w.store.get_setting).always_trial_runs == 0
        w.store.set_setting("apply.always_trial_runs", "-2")
        assert base.with_settings(w.store.get_setting).always_trial_runs == 0
        w.store.set_setting("apply.always_trial_runs", "3")
        assert base.with_settings(w.store.get_setting).always_trial_runs == 3
        raw = dict(w.cfg.raw if hasattr(w.cfg, "raw") else {})
        for bad in ("sometimes", 7):
            Config({**raw, "apply": {"fill_policy": bad, "always_trial_runs": "x"}})      # must not raise
    finally:
        logging.disable(logging.NOTSET)
        w.close()


def test_always_in_the_flow_warms_the_model_with_the_briefing_and_widens_what_the_model_may_read():
    w, _cid, jobs = make(1)
    try:
        net = Net()
        res, _f, say = run_batch(w, jobs, nav_class()(), backend(net), **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT
        assert "fill policy: always (local model)" in say.text
        rctx = say.calls[0]["rctx"]
        assert rctx.fill_policy is FillPolicy.ALWAYS and rctx.model_sees_sensitive is True
        warm = net.chats[0]
        assert [m["role"] for m in warm["messages"]] == ["system", "user"] and warm["options"]["num_predict"] == 1
        assert "briefing ready" in say.text
    finally:
        w.close()


def test_the_settings_inactive_text_follows_is_local_config():
    base = {"enable_llm": True, "backend": "ollama", "ollama_model": "qwen3:14b"}
    assert backends.is_local_config({**base, "ollama_url": "http://127.0.0.1:11434"}) is True
    assert backends.is_local_config({**base, "ollama_url": "http://ollama:11434"}) is False
    assert backends.is_local_config({**base, "ollama_model": "x:cloud"}) is False
    assert backends.is_local_config({**base, "enable_llm": False}) is False
    assert backends.is_local_config({**base, "backend": "off"}) is False


# ================================================================== oracle 8: K1 secrets

def _vault_world(*, wall=(), password=SECRET, extra_value=None, profile=None):
    w, cid, jobs = make(1, profile=profile if profile is not None else
                        (_profile_with_extra(extra_value) if extra_value is not None else None))
    nav = nav_class()(wall=wall)
    return w, cid, jobs, nav


def test_a_vault_password_planted_in_the_profile_is_refused_before_any_request_or_browser():
    from apply_flow_support import EMAIL
    for planted in forms(SECRET):                       # raw, then JSON-escaped
        with memory_keyring():
            w, _cid, jobs, nav = _vault_world(extra_value=f"note: {planted} end")
            try:
                S.put_account(w, nav, EMAIL, SECRET)
                net = Net()
                res, fac, say = run_batch(w, jobs, nav, backend(net), **ALWAYS)
                r = res[0]
                assert r.state is ST.FAILED and r.reason is R.ERROR and r.reason_detail == "prompt check", \
                    (r.state, r.reason, r.reason_detail)
                assert w.store.attempt(r.attempt_id)["step"] == "planning"
                assert net.model_requests == [], "a refused prompt costs no request"
                assert not net.carries(*forms(SECRET)), "no request body holds the secret"
                assert not any(x in say.text for x in forms(SECRET)), "the log never holds it"
                assert fac.started == 0 and "open" not in nav.calls, "no browser, no site touched"
                assert nav.submits == 0
            finally:
                w.close()


def test_registered_secrets_refuse_nothing_ordinary_and_no_request_ever_carries_them():
    from apply_flow_support import EMAIL
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world()
        try:
            S.put_account(w, nav, EMAIL, SECRET)
            net = Net(S.answering())
            res, _f, say = run_batch(w, jobs, nav, backend(net), **ALWAYS)
            assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason_detail)
            assert "prompt check: 1 secret(s) registered" in say.text
            assert net.chats, "the warm-up went through"
            assert not net.carries(*forms(SECRET))
        finally:
            w.close()


def test_a_password_generated_at_sign_up_is_registered_at_once_under_both_policies():
    for policy in ("always", "strict"):
        with memory_keyring():
            w, _cid, jobs, nav = _vault_world(wall=("sign_up",))
            try:
                seen: dict = {}

                def script(n, services, ctx, rctx):
                    pw = nav.signed_up[0]
                    for leak in (pw, f"x {json.dumps(pw)[1:-1]} y"):
                        try:
                            services.backend.complete("system", f"fill the form with {leak}")
                            seen.setdefault("sent", []).append(leak)
                        except backends.PromptRefused:
                            seen.setdefault("refused", []).append(leak)
                    return page()
                net = Net()
                res, _f, _s = run_batch(w, jobs, nav, backend(net), script, fill_policy=policy)
                assert res[0].state is ST.READY_TO_SUBMIT, (policy, res[0].state, res[0].reason_detail)
                assert len(nav.signed_up) == 1 and "sent" not in seen and len(seen["refused"]) == 2, (policy, seen)
                assert not net.carries(*forms(nav.signed_up[0])), policy
            finally:
                w.close()


def test_a_secret_too_short_to_guard_stops_always_and_is_only_logged_under_strict():
    from apply_flow_support import EMAIL
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world()
        try:
            S.put_account(w, nav, EMAIL, "abc12")                       # 5 characters
            net = Net()
            res, fac, _say = run_batch(w, jobs, nav, backend(net), **ALWAYS)
            r = res[0]
            assert r.state is ST.FAILED and r.reason is R.ERROR and r.reason_detail == "prompt check"
            assert fac.started == 0 and net.model_requests == []
        finally:
            w.close()
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world(wall=("sign_in",))
        try:
            S.put_account(w, nav, EMAIL, "abc12")
            res, _f, say = run_batch(w, jobs, nav, backend(Net()))
            assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason, res[0].reason_detail)
            assert nav.signed_in == ["abc12"] and "too short for the prompt check" in say.text
        finally:
            w.close()


def test_a_prompt_the_check_refuses_on_a_page_ends_error_prompt_check_not_model_unavailable():
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world(wall=("sign_up",))
        try:
            def wrap(real):
                def ask(messages, schema, **kw):
                    msgs = [dict(m) for m in messages]
                    msgs[0]["content"] += " " + nav.signed_up[0]            # a secret in the page prompt
                    return real(msgs, schema, **kw)
                return ask
            fields = S.req_numbers("q", 1)
            net = Net()
            res, _f, say = run_batch(w, jobs, nav, backend(net),
                                     S.real_page(fields, "one", ask_wrap=wrap), **ALWAYS)
            r = res[0]
            assert r.state is ST.FAILED and r.reason is R.ERROR and r.reason_detail == "prompt check", \
                (r.state, r.reason, r.reason_detail)
            assert not net.carries(*forms(nav.signed_up[0])), "the refused prompt never left"
            assert nav.submits == 0
        finally:
            w.close()


def test_strict_ends_a_refused_page_prompt_as_error_prompt_check_too():
    """K1 has no policy qualifier: "the flow ends failed(error, 'prompt check') before any
    keystroke on that page". Under strict pagefill reports a refusal as a transport failure and
    the flow's refusal watch is `always`-only (engineer departure 2)."""
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world(wall=("sign_up",))
        try:
            def script(n, services, ctx, rctx):
                try:
                    services.backend.complete("system", f"fill with {nav.signed_up[0]}")
                except backends.BackendError:                  # what pagefill does with any BackendError
                    return S._u().outcome("one", [S._u().pf("a", "Field")],
                                          {"a": S._u().ans("a", None, status=S.AnswerStatus.UNKNOWN,
                                                            note="transport: model unavailable")},
                                          transport_failed=True)
                raise AssertionError("the registered password was not refused")
            res, _f, _s = run_batch(w, jobs, nav, backend(Net()), script)
            r = res[0]
            assert r.state is ST.FAILED and r.reason is R.ERROR and r.reason_detail == "prompt check", \
                (r.state, r.reason, r.reason_detail)
        finally:
            w.close()


def test_the_registry_is_cleared_when_an_attempt_ends_however_it_ends():
    from apply_flow_support import EMAIL
    # (a) an attempt that ended with a refusal does not leave its secret behind
    be_net = Net()
    be = backend(be_net)
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world(extra_value=SECRET)
        try:
            S.put_account(w, nav, EMAIL, SECRET)
            res, _f, _s = run_batch(w, jobs, nav, be, **ALWAYS)
            assert res[0].reason_detail == "prompt check"
            w.store.conn.execute("DELETE FROM ats_accounts")             # the next attempt knows no secret
            w.store.commit()
            w.store.conn.execute("DELETE FROM apply_attempts")
            w.store.commit()
            res2, _f2, _s2 = run_batch(w, jobs, nav_class()(), be, **ALWAYS)
            assert res2[0].state is ST.READY_TO_SUBMIT, \
                "the second attempt inherited the first one's secret: " + str(res2[0].reason_detail)
        finally:
            w.close()
    # (b) a successful attempt does not either
    be = backend(Net())
    with memory_keyring():
        w, _cid, jobs, nav = _vault_world(wall=("sign_up",))
        try:
            res, _f, _s = run_batch(w, jobs, nav, be, **ALWAYS)
            assert res[0].state is ST.READY_TO_SUBMIT
            pw = nav.signed_up[0]
            be.complete("system", f"an ordinary prompt that mentions {pw}")      # must not raise
        finally:
            w.close()
