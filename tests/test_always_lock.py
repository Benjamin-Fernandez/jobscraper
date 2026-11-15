"""Q-121 release lock pins (D-223): the "always answer" fill policy can take effect ONLY when the
config FILE says `apply.always_available: true` (code default false; never settable from the web,
the settings table, the CLI or the environment). The branch ships to the owner's daily app, where an
Auto-apply click sends a REAL application, so the lock is pinned from every side:

  A. config   the key's type rules, not a setting, no settings row unlocks it, and the repository's own
              config/config.yaml is locked and has no `fill_policy: always` line (the pin that keeps
              the release locked until the owner's go-live edit);
  B. flow     every way of asking for `always` (config, stored settings row, both, CLI path, apply
              queue path) runs the STRICT path: `effective_policy` says why, the log says it once per
              attempt, `pagefill._fill_page_always` and `always.fill_page_always` are never entered
              (both are patched to RAISE), no trial run is consumed, no briefing is sent to the model,
              and compose's "a required cover letter is written under always" rule does not apply;
  C. web      GET shows locked + strict + the sentence, PUT always is 422 and stores nothing, no PUT /
              POST / PATCH route that takes a JSON body can change the key, an old stored `always`
              row reads as strict;
  D. static   the source files that mention the key, and none of them writes it anywhere.
  E. control  with the lock open (the config object's field true) `always` is effective as before.

Fakes only: the harness of tests/always_flow_support.py (a mock Ollama transport, FakeNav that only
counts submits, a temp DB), the web world of tests/test_web_always.py with a fake job manager. No real
model, no port, no process. Nothing here can send an application. Example Co is a made-up employer.
Verify: python tests/run_tests.py -k always_lock
"""
from __future__ import annotations

import contextlib
import dataclasses
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import (  # noqa: E402
    NOW, Net, backend, make, nav_class, page, ready_ensurer,
)
from apply_flow_support import FakeBrowserFactory, Say, page_signals, registered  # noqa: E402
from test_web_always import ENV_KEYS, EVIL, _world  # noqa: E402,F401

from jobscraper import apply_flow, backends, cli  # noqa: E402
from jobscraper import store as store_mod  # noqa: E402
from jobscraper.apply import always as AL, pagefill  # noqa: E402
from jobscraper.apply.contracts import AttemptState as ST, FillPolicy, ReasonCode as RC  # noqa: E402
from jobscraper.config import ApplyConfig, ComposeConfig, Config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = "Always answer isn't available yet: it is still being checked."
NOT_RELEASED = apply_flow.POLICY_NOT_RELEASED
BASE = dict(dry_run_hold_s=0, confirm_timeout_s=0, daily_cap=0, per_employer_daily_cap=0, fill="llm")
KEY_ROW = "apply.always_available"


# ================================================================== A. config

def test_lock_config_is_false_by_default_and_when_the_key_is_absent():
    assert ApplyConfig().always_available is False
    for raw in (None, {}, {"mode": "auto"}, {"fill_policy": "always"}, "not a dict", [], 5):
        assert ApplyConfig.from_raw(raw).always_available is False, raw
    assert Config({}).apply.always_available is False
    assert Config({"apply": {"fill_policy": "always", "fill": "llm"}}).apply.always_available is False


def test_lock_config_only_a_real_yaml_true_unlocks():
    """A real boolean true only. Strings (any case), numbers, null, lists and maps stay locked
    (PyYAML reads an UNQUOTED yes / on as a real boolean, so those are a file edit like `true`)."""
    assert ApplyConfig.from_raw({"always_available": True}).always_available is True
    assert ApplyConfig.from_raw(yaml.safe_load("always_available: true")).always_available is True
    for bad in ("true", "True", "TRUE", "yes", "on", "1", " true ", 1, 2, 1.0, "", None, [], [True], {}, {"a": 1}, "false",
                False, 0, "always"):
        assert ApplyConfig.from_raw({"always_available": bad}).always_available is False, repr(bad)
    # the same through the whole config object and through quoted YAML text
    for text in ('"true"', "'yes'", '"on"', "1", "null", "~", "[true]"):
        raw = yaml.safe_load(f"apply:\n  always_available: {text}\n")
        assert Config(raw).apply.always_available is False, text


def test_lock_config_is_not_a_setting_and_no_settings_row_unlocks_it():
    assert "always_available" not in ApplyConfig.SETTING_KEYS
    assert "always_available" not in ApplyConfig.MAIL_SETTING_KEYS
    from jobscraper.config import POLICY_KEYS
    assert "always_available" not in POLICY_KEYS
    from jobscraper.web.routers import apply as router
    assert "always_available" not in router._SETTING_RULES and "always_available" not in router._SETTING_KEYS
    assert KEY_ROW not in router._SETTING_KEYS.values()
    locked = ApplyConfig.from_raw({"fill_policy": "always", "fill": "llm"})
    for stored in ("true", "True", "1", "yes", "on", True, 1):
        got = locked.with_settings(lambda k, v=stored: v if k == KEY_ROW else None)
        assert got.always_available is False, stored
    # a row alone moves nothing else either, and a "false" row does not LOCK a released install
    both = locked.with_settings(lambda k: {KEY_ROW: "true", "apply.fill_policy": "always"}.get(k))
    assert both.always_available is False and both.fill_policy == "always"
    open_ = dataclasses.replace(locked, always_available=True)
    assert open_.with_settings(lambda k: "false" if k == KEY_ROW else None).always_available is True
    # a real settings table
    w, _cid, _jobs = make(1)
    try:
        w.store.set_setting(KEY_ROW, "true")
        w.store.commit()
        assert w.cfg.apply.with_settings(w.store.get_setting).always_available is False
        assert cli._effective_apply(w.cfg, w.store).always_available is False
    finally:
        w.close()


def test_lock_the_repository_config_is_locked_and_has_no_fill_policy_always_line():
    """The release gate itself: read config/config.yaml as TEXT. The owner's go-live edit (a later
    commit) flips the key and may add the policy line; until then this fails the build if either was
    done early. Also covers the other YAML files in the repository root and config/."""
    text = (ROOT / "config" / "config.yaml").read_text(encoding="utf-8")
    lines = [ln.split("#", 1)[0] for ln in text.splitlines()]
    values = [m.group(1) for m in (re.match(r"\s*always_available:\s*(.*?)\s*$", ln) for ln in lines) if m]
    assert values == ["false"], f"config/config.yaml must say `always_available: false` once, under apply: {values}"
    assert not any(re.match(r"\s*fill_policy:\s*[\"']?always\b", ln, re.I) for ln in lines), \
        "config/config.yaml must not set fill_policy: always while the release is locked"
    raw = yaml.safe_load(text)
    assert raw["apply"].get("always_available") is False
    assert str(raw["apply"].get("fill_policy", "strict")).lower() != "always"
    assert Config(raw).apply.always_available is False
    for p in [*(ROOT / "config").glob("*.y*ml"), *ROOT.glob("*.y*ml")]:
        if p.name == "config.yaml" and p.parent.name == "config":
            continue
        body = [ln.split("#", 1)[0] for ln in p.read_text(encoding="utf-8").splitlines()]
        assert not any(re.match(r"\s*always_available:\s*true", ln, re.I) for ln in body), p
        assert not any(re.match(r"\s*fill_policy:\s*[\"']?always\b", ln, re.I) for ln in body), p


# ================================================================== B. flow: every way of asking for always

class Entered(AssertionError):
    """Raised by the patched always-filler entry points: entering one fails the test."""


@contextlib.contextmanager
def always_entry_guard(*, raising=True):
    """Patch `pagefill._fill_page_always` and `always.fill_page_always`. `raising`: both raise (and
    record) so the attempt fails loudly if the always path starts; not raising (the control case): the
    pagefill one records and answers an ordinary page, so a test can see the path WAS taken."""
    entered: list[str] = []

    def boom_always(*a, **k):
        entered.append("always.fill_page_always")
        raise Entered("always.fill_page_always was entered")

    def page_entry(pg, nav, ctx, rctx, services):
        entered.append("pagefill._fill_page_always")
        if raising:
            raise Entered("pagefill._fill_page_always was entered")
        return page()

    saved = (pagefill._fill_page_always, AL.fill_page_always)
    pagefill._fill_page_always, AL.fill_page_always = page_entry, boom_always
    try:
        yield entered
    finally:
        pagefill._fill_page_always, AL.fill_page_always = saved


def _dispatch(nav, services, ctx, rctx):
    """What `pagefill.fill_page` does first, with a page that is always the same: the policy picks the
    path; the always path goes through the (patched) entry; the strict path answers an ordinary page."""
    if pagefill._policy(rctx) is FillPolicy.ALWAYS:
        return pagefill._fill_page_always(None, nav, ctx, rctx, services)
    return page()


def _eff(w, **over):
    """The ApplyConfig the CLI and the queue build: config.yaml's block with the settings table over it
    (`cli._effective_apply`), the way the real entry points build it, plus the harness' quick timings."""
    return dataclasses.replace(cli._effective_apply(w.cfg, w.store), **{**BASE, **over})


def _run(w, jobs, nav, be, acfg, *, dry_run=True, via_queue=False, cid=None):
    """apply_flow.run (the CLI / web job path) or apply_flow.run_queue (the Auto-apply queue path) over
    the fakes, with `acfg` as the effective settings. Returns (factory, say)."""
    from jobscraper.store import utcnow
    factory, say = FakeBrowserFactory(), Say()
    with registered(nav), page_signals(), S.scripted(_dispatch) as calls, S.scan(()):
        if not via_queue:
            apply_flow.run(w.cfg, w.store, list(jobs), dry_run=dry_run, backend=be, http=object(),
                           browser_factory=factory, apply_cfg=acfg, say=say, evidence_dir=w.tmp / "evidence",
                           now=lambda: NOW)
        else:
            for j in jobs:
                assert w.store.queue_add(j, cid, "dry_run" if dry_run else "auto", "inbox", utcnow()) is not None
            w.store.commit()
            apply_flow.run_queue(w.cfg, w.store, backend=be, apply_cfg_fn=lambda: acfg, http=object(),
                                 browser_factory=factory, say=say, evidence_dir=w.tmp / "evidence",
                                 model_ensurer=ready_ensurer())
    say.calls = calls
    return factory, say


def _assert_strict_run(w, jobs, nav, net, say, entered, *, dry_run):
    rows = w.attempt_rows()
    assert len(rows) == len(jobs), [r["state"] for r in rows]
    if dry_run:
        assert [r["state"] for r in rows] == [ST.READY_TO_SUBMIT.value] * len(jobs),             [(r["state"], r.get("reason_code"), r.get("reason_detail")) for r in rows]
    else:
        assert all(r["state"] in (ST.SUBMITTED.value, ST.SUBMITTED_UNCONFIRMED.value) for r in rows),             [(r["state"], r.get("reason_code"), r.get("reason_detail")) for r in rows]
    assert entered == [], f"the always filler was entered: {entered}"
    assert [c["rctx"].fill_policy for c in say.calls] and \
        all(c["rctx"].fill_policy is FillPolicy.STRICT for c in say.calls)
    assert all(c["rctx"].model_sees_sensitive is False for c in say.calls), "the strict context is unchanged"
    # the reason is logged ONCE per attempt, and "fill policy: always" never is
    assert say.text.count(NOT_RELEASED) == len(jobs), say.text
    assert "fill policy: always" not in say.text and "Trial:" not in say.text
    assert not any(r.get("trial") for r in rows)
    assert w.store.always_trial_used() == 0, "no trial run is consumed while locked"
    assert not any(p == "/api/chat" for _m, p, _b in net.log), "no briefing was sent to the model"
    if not dry_run:
        assert nav.submits == len(jobs), "the strict path submits as it always did"
    else:
        assert nav.submits == 0


ASKS = [
    ("config fill_policy always", {"fill_policy": "always"}, None),
    ("stored settings row always", {}, "always"),
    ("config always and a stored row always", {"fill_policy": "always"}, "always"),
    ("config strict, stored row always", {"fill_policy": "strict"}, "always"),
    ("config always, trial runs set", {"fill_policy": "always", "always_trial_runs": 3}, "always"),
]


def _locked_world(config_apply):
    """A world whose config.yaml `apply:` block is `config_apply` and never sets always_available."""
    from apply_flow_support import make_world
    from always_flow_support import add_job
    w = make_world(apply_block=dict(config_apply))
    cid, j1 = add_job(w.store, key="exampleco", name="Example Co", provider="fakenav", slug="exampleco",
                      external_id="1", url="https://fake.example.com/jobs/1")
    j2 = add_job(w.store, key="exampleco", name="Example Co", provider="fakenav", slug="exampleco",
                 external_id="2", company_id=cid, url="https://fake.example.com/jobs/2")[1]
    for j in (j1, j2):
        w.store.set_application_status(j, "to_apply")
    w.store.commit()
    return w, cid, [j1, j2]


def test_lock_effective_policy_is_strict_with_the_reason_for_every_way_of_asking():
    local = backend(Net())
    assert backends.is_local(local)
    asked = [ApplyConfig.from_raw({"fill_policy": "always", "fill": "llm"}),
             ApplyConfig.from_raw({"fill_policy": "always", "fill": "llm", "always_available": False}),
             ApplyConfig.from_raw({"fill_policy": "always", "fill": "llm", "always_available": "true"}),
             ApplyConfig(fill_policy="always", fill="llm"),
             SimpleNamespace(fill_policy="always", fill="llm"),                          # no such attribute
             SimpleNamespace(fill_policy="always", fill="llm", always_available="true"),  # not a real True
             SimpleNamespace(fill_policy="always", fill="llm", always_available=1),
             SimpleNamespace(fill_policy="always", fill="llm", always_available=None)]
    for acfg in asked:
        assert apply_flow.effective_policy(acfg, local) == (FillPolicy.STRICT, NOT_RELEASED), acfg
    # the lock is checked FIRST: it is the reason even when the model is remote or the filler is rules
    remote = backend(Net(), url="http://ollama:11434")
    rules = ApplyConfig.from_raw({"fill_policy": "always", "fill": "rules"})
    assert apply_flow.effective_policy(ApplyConfig.from_raw({"fill_policy": "always"}), remote) \
        == (FillPolicy.STRICT, NOT_RELEASED)
    assert apply_flow.effective_policy(rules, local) == (FillPolicy.STRICT, NOT_RELEASED)
    # asking for nothing is silent: strict, no reason
    assert apply_flow.effective_policy(ApplyConfig.from_raw({"fill_policy": "strict"}), local) == (FillPolicy.STRICT, "")
    assert apply_flow.effective_policy(ApplyConfig(), local) == (FillPolicy.STRICT, "")


def test_lock_every_way_of_asking_runs_the_strict_path_in_a_dry_run_and_a_real_click_on_the_cli_path():
    for label, config_apply, stored in ASKS:
        for dry_run in (True, False):
            w, _cid, jobs = _locked_world(config_apply)
            try:
                if stored is not None:
                    w.store.set_setting("apply.fill_policy", stored)
                    w.store.commit()
                acfg = _eff(w)
                if stored is not None or "fill_policy" in config_apply:
                    assert acfg.fill_policy in ("always", "strict"), label
                assert acfg.always_available is False, label
                if stored == "always" or config_apply.get("fill_policy") == "always":
                    assert acfg.fill_policy == "always", f"setup: {label} must really ask for always"
                nav, net = nav_class()(), Net()
                with always_entry_guard() as entered:
                    _f, say = _run(w, jobs, nav, backend(net), acfg, dry_run=dry_run)
                _assert_strict_run(w, jobs, nav, net, say, entered, dry_run=dry_run)
            finally:
                w.close()


def test_lock_every_way_of_asking_runs_the_strict_path_on_the_apply_queue_path():
    for label, config_apply, stored in ASKS:
        for dry_run in (True, False):
            w, cid, jobs = _locked_world(config_apply)
            try:
                if stored is not None:
                    w.store.set_setting("apply.fill_policy", stored)
                    w.store.commit()
                acfg = _eff(w, mode="dry_run" if dry_run else "auto")      # a queue item's mode must be allowed
                nav, net = nav_class()(), Net()
                with always_entry_guard() as entered:
                    _f, say = _run(w, jobs, nav, backend(net), acfg, dry_run=dry_run, via_queue=True, cid=cid)
                _assert_strict_run(w, jobs, nav, net, say, entered, dry_run=dry_run)
            finally:
                w.close()


def test_lock_a_real_click_with_a_trial_count_is_not_turned_into_a_trial_run():
    """While locked the first-use trial does not exist: `always_trial_runs: 3` must not make a click a
    dry run (it would hide that the policy is off) and the counter must not move."""
    w, _cid, jobs = _locked_world({"fill_policy": "always", "always_trial_runs": 3})
    try:
        nav, net = nav_class()(), Net()
        with always_entry_guard() as entered:
            _f, say = _run(w, jobs, nav, backend(net), _eff(w), dry_run=False)
        rows = w.attempt_rows()
        assert [r["mode"] for r in rows] == ["auto", "auto"] and nav.submits == 2
        assert w.store.always_trial_used() == 0 and entered == []
        assert "Trial" not in say.text and not any(r.get("trial") for r in rows)
        assert w.store.get_setting(w.store.ALWAYS_TRIAL_USED) in (None, "", "0", 0)
    finally:
        w.close()


def test_lock_the_cli_apply_path_builds_the_same_locked_settings():
    """`jobscraper apply` and `apply queue` build their settings with `cli._effective_apply`: it must
    never carry the key from the table, and the doctor says the policy is not released."""
    from test_always_flow_trial import _doctor
    for apply_block in ({"fill_policy": "always"}, {"fill_policy": "always", "fill": "llm"},
                        {"always_available": False, "fill_policy": "always", "always_trial_runs": 2}):
        out = _doctor(apply_block={"always_available": False, **apply_block}, be=backend(Net()))
        assert "always answer is not released on this install" in out, out
        assert "fill policy    Always answer" not in out and "trial" not in out.lower(), out
    # and the doctor with the lock open still shows always (the control)
    on = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()))
    assert "fill policy    Always answer" in on and "not released" not in on, on


def test_lock_a_required_cover_letter_is_not_composed_under_a_locked_always():
    """compose's `forced = at.always and f.required` follows `self.policy`: locked, `always` is strict,
    so with compose off the attempt stops exactly as strict does and the tailor is never asked."""
    U = S._u()

    def cover_run(*, always_available):
        w, _cid, jobs = make(1)
        try:
            calls = []

            def script(nav, services, ctx, rctx):
                f = U.pf("cover", "Cover letter", required=True)
                if ctx.composed:
                    return U.outcome("one", [f], {"cover": U.ans("cover", next(iter(ctx.composed.values())))})
                return U.outcome("one", [f], {"cover": U.ans("cover", None, status=S.AnswerStatus.UNKNOWN,
                                                              note="compose needed")},
                                 compose_needed=("cover",))

            def fake_compose(*a, **kw):
                calls.append(kw)
                return SimpleNamespace(ok=True, error="", text="Composed text.", model="fake-model:1b",
                                       prompt_hash="h" * 16)
            real = apply_flow.tailor_flow.compose
            apply_flow.tailor_flow.compose = fake_compose
            try:
                res, _f, say = S.run_batch(w, jobs, nav_class()(), backend(Net()), script, fill_policy="always",
                                           always_available=always_available, compose=ComposeConfig(enabled=False))
            finally:
                apply_flow.tailor_flow.compose = real
            return res[0], calls, say
        finally:
            w.close()

    r, calls, say = cover_run(always_available=False)
    assert r.state is ST.FAILED and r.reason is RC.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
    assert r.reason_detail == "Cover letter" and calls == [], "locked: strict stops, the tailor is not asked"
    assert NOT_RELEASED in say.text
    # control: released, the same page IS composed (test_q127_close pins the rest)
    r2, calls2, _s = cover_run(always_available=True)
    assert r2.state is ST.READY_TO_SUBMIT and len(calls2) == 1 and calls2[0].get("policy") == "always"


# ================================================================== E. control: the lock open

def test_lock_open_always_is_effective_exactly_as_before():
    local = backend(Net())
    acfg = ApplyConfig.from_raw({"fill_policy": "always", "fill": "llm", "always_available": True})
    assert apply_flow.effective_policy(acfg, local) == (FillPolicy.ALWAYS, "")
    # and the other two reasons still apply, after the lock
    assert apply_flow.effective_policy(dataclasses.replace(acfg, fill="rules"), local) == (FillPolicy.STRICT, apply_flow.POLICY_NOT_LLM)
    assert apply_flow.effective_policy(acfg, backend(Net(), url="http://ollama:11434")) \
        == (FillPolicy.STRICT, apply_flow.POLICY_NOT_LOCAL)
    # the detector is not vacuous: with the lock open an attempt DOES reach the always entry point
    w, _cid, jobs = _locked_world({"fill_policy": "always", "always_available": True})
    try:
        nav, net = nav_class()(), Net()
        with always_entry_guard(raising=False) as entered:
            _f, say = _run(w, jobs, nav, backend(net), _eff(w), dry_run=True)
        assert entered == ["pagefill._fill_page_always"] * len(jobs), entered
        assert all(c["rctx"].fill_policy is FillPolicy.ALWAYS for c in say.calls)
        assert NOT_RELEASED not in say.text and "fill policy: always" in say.text
    finally:
        w.close()


# ================================================================== C. web

def _table(cfg):
    st = store_mod.Store(cfg.db_path)
    try:
        return st.conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    finally:
        st.close()


def _table_bytes(cfg):
    return repr([(str(k), repr(v)) for k, v in _table(cfg)])


def _set_row(cfg, key, value):
    st = store_mod.Store(cfg.db_path)
    st.set_setting(key, value)
    st.commit()
    st.close()


LOCKED_WEB = {"always_available": False}


def test_lock_web_get_reports_locked_strict_and_the_sentence():
    # (the helper unlocks by default: the lock is set here by the file value)
    for apply_block in ({"always_available": False, "fill_policy": "always"}, {"always_available": False}):
        with _world(apply_block=apply_block) as (client, _cfg, _i, _f):
            body = client.get("/api/apply/settings").json()
            assert body["always_available"] is False
            assert body["fill_policy_effective"] == "strict"
            if apply_block.get("fill_policy") == "always":
                assert body["fill_policy_inactive"] == SENTENCE
            fill = client.get("/api/apply/status").json()["fill"]
            assert fill["fill_policy_effective"] == "strict"
            assert fill["fill_policy_inactive"] == (SENTENCE if apply_block.get("fill_policy") == "always" else None)


def test_lock_web_put_always_is_422_with_the_sentence_and_the_table_is_untouched():
    with _world(apply_block=dict(LOCKED_WEB)) as (client, cfg, _i, fake):
        before_table, before_get = _table_bytes(cfg), client.get("/api/apply/settings").json()
        for body in ({"fill_policy": "always"},
                     {"fill_policy": "always", "always_trial_runs": 3},       # all-or-nothing
                     {"daily_cap": 9, "fill_policy": "always"},
                     {"fill_policy": "always", "mode": "auto"}):
            r = client.put("/api/apply/settings", json=body)
            assert r.status_code == 422, (body, r.status_code, r.text)
            j = r.json()
            assert j["detail"] == "invalid"
            assert j["errors"] == [{"field": "fill_policy", "message": SENTENCE}], j
            assert _table_bytes(cfg) == before_table, body
            assert client.get("/api/apply/settings").json() == before_get, body
        assert fake.started == []
        # an apply setting that is not "always" still saves (the lock is not a general read-only)
        ok = client.put("/api/apply/settings", json={"fill_policy": "strict"})
        assert ok.status_code == 200 and ok.json()["fill_policy"] == "strict"
        assert ok.json()["always_available"] is False and ok.json()["fill_policy_effective"] == "strict"
        assert dict(_table(cfg)).get("apply.fill_policy") == "strict"
        again = client.put("/api/apply/settings", json={"daily_cap": 11})
        assert again.status_code == 200 and again.json()["daily_cap"] == 11
        # after the saves: still locked, and a foreign origin never reaches the lock check
        assert client.get("/api/apply/settings").json()["always_available"] is False
        assert client.put("/api/apply/settings", headers=EVIL, json={"fill_policy": "always"}).status_code == 403


def test_lock_web_the_key_is_not_an_apply_setting_and_no_row_unlocks_it():
    with _world(apply_block=dict(LOCKED_WEB)) as (client, cfg, _i, _f):
        before = _table_bytes(cfg)
        for body in ({"always_available": True}, {"always_available": "true"},
                     {"apply": {"always_available": True}}, {"fill_policy": "strict", "always_available": True}):
            r = client.put("/api/apply/settings", json=body)
            assert r.status_code == 422, (body, r.text)
            assert any(e["field"] in ("always_available", "apply") for e in r.json()["errors"]), r.json()
            assert _table_bytes(cfg) == before
        # a settings-table row named apply.always_available does nothing to the reads
        _set_row(cfg, KEY_ROW, "true")
        _set_row(cfg, "apply.fill_policy", "always")
        body = client.get("/api/apply/settings").json()
        assert body["always_available"] is False and body["fill_policy_effective"] == "strict"
        assert body["fill_policy_inactive"] == SENTENCE
        assert client.put("/api/apply/settings", json={"fill_policy": "always"}).status_code == 422
        fill = client.get("/api/apply/status").json()["fill"]
        assert fill["fill_policy_effective"] == "strict" and fill["fill_policy_inactive"] == SENTENCE


def test_lock_web_an_old_stored_always_row_reads_as_strict_while_locked():
    """A row saved before the lock (or by hand): the reads show the EFFECTIVE policy, strict. KNOWN
    LIMIT, pinned: the payload's `fill_policy` field still echoes the stored value, `always`."""
    with _world(apply_block=dict(LOCKED_WEB)) as (client, cfg, _i, _f):
        _set_row(cfg, "apply.fill_policy", "always")
        _set_row(cfg, "apply.always_trial_runs", 3)
        body = client.get("/api/apply/settings").json()
        assert body["fill_policy_effective"] == "strict" and body["fill_policy_inactive"] == SENTENCE
        assert body["always_available"] is False
        assert body["fill_policy"] == "always", "pinned: the stored value is echoed (the Vue shows Stop when unsure)"
        fill = client.get("/api/apply/status").json()["fill"]
        assert (fill["fill_policy_effective"], fill["fill_policy_inactive"]) == ("strict", SENTENCE)
        # going back to strict rewrites the row
        assert client.put("/api/apply/settings", json={"fill_policy": "strict"}).status_code == 200
        body = client.get("/api/apply/settings").json()
        assert body["fill_policy"] == "strict" and body["fill_policy_inactive"] is None


def test_lock_web_an_old_stored_always_row_runs_strict_in_an_attempt():
    """The same stored row, through the flow: the attempt runs strict (the engine reads the settings
    table with `cli._effective_apply`, the lock comes from the file)."""
    w, _cid, jobs = _locked_world({"fill_policy": "strict"})
    try:
        w.store.set_setting("apply.fill_policy", "always")
        w.store.commit()
        acfg = _eff(w)
        assert acfg.fill_policy == "always" and acfg.always_available is False
        nav, net = nav_class()(), Net()
        with always_entry_guard() as entered:
            _f, say = _run(w, jobs, nav, backend(net), acfg, dry_run=True)
        _assert_strict_run(w, jobs, nav, net, say, entered, dry_run=True)
    finally:
        w.close()


# every unsafe route that declares a JSON body, as of this lock. A new one must be added here after
# someone read it (the sweep below sends it the key). A body-less route cannot carry the key.
SWEPT = {
    ("PUT", "/api/applicant"), ("POST", "/api/applicant/check"), ("POST", "/api/applicant/refresh"),
    ("POST", "/api/applications/{job_id}"),
    ("POST", "/api/applications/{job_id}/attempts/{attempt_id}/answers/{answer_id}/remember"),
    ("POST", "/api/apply"), ("POST", "/api/apply/queue/stop"), ("PUT", "/api/apply/settings"),
    ("PUT", "/api/connections/model/autostart"), ("POST", "/api/jobs/run"), ("PUT", "/api/settings"),
    ("PUT", "/api/titles"),
}
UNSAFE = {"PUT", "POST", "PATCH", "DELETE"}


def _body_routes(app):
    out = set()
    for path, ops in app.openapi()["paths"].items():
        for method, op in ops.items():
            if method.upper() in UNSAFE and op.get("requestBody"):
                out.add((method.upper(), path))
    return out


def test_lock_web_no_route_that_takes_a_json_body_can_change_the_key():
    with _world(apply_block=dict(LOCKED_WEB)) as (client, cfg, _i, fake):
        found = _body_routes(client.app)
        assert found == SWEPT, ("a route with a JSON body appeared or went: read it, then update SWEPT",
                                sorted(found - SWEPT), sorted(SWEPT - found))
        assert ("PUT", "/api/apply/settings") in found
        before_cfg = cfg.apply.always_available
        bodies = ({"always_available": True}, {"apply": {"always_available": True}},
                  {"fill_policy": "always", "always_available": True})
        for method, path in sorted(found):
            url = re.sub(r"\{[^}]+\}", "1", path)
            for body in bodies:
                r = client.request(method, url, json=body)
                assert r.status_code < 500, (method, url, body, r.status_code, r.text[:200])
                rows = dict((str(k), v) for k, v in _table(cfg))
                assert not any("always_available" in k for k in rows), (method, url, body, rows)
                assert not any(str(v).lower() == "true" and k.endswith("always_available") for k, v in rows.items())
                got = client.get("/api/apply/settings").json()
                assert got["always_available"] is False and got["fill_policy_effective"] == "strict", (method, url, body, got)
                assert client.get("/api/apply/status").json()["fill"]["fill_policy_effective"] == "strict", (method, url)
        # the app's own view of the file never moved either (no route rewrites config.yaml)
        assert cfg.apply.always_available is before_cfg is False


# ================================================================== D. static: where the key appears

def test_lock_source_files_that_mention_the_key_never_write_it_or_take_it_from_a_flag_or_env():
    allowed = {"config.py", "apply_flow.py", "cli.py", str(Path("web") / "routers" / "apply.py")}
    base = ROOT / "src" / "jobscraper"
    seen = set()
    for p in base.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if "always_available" not in text:
            continue
        rel = str(p.relative_to(base))
        seen.add(rel)
        for n, ln in enumerate(text.splitlines(), 1):
            if "always_available" not in ln:
                continue
            code = ln.split("#", 1)[0]
            if "always_available" not in code:
                continue
            assert not re.search(r"set_setting|environ|getenv|add_argument|setattr|__setitem__|\.update\(", code), \
                f"{rel}:{n}: {ln.strip()}"
    assert seen <= allowed, f"new source files mention always_available: {sorted(seen - allowed)} (read them, then update this pin)"
    assert {"config.py", "apply_flow.py"} <= seen
