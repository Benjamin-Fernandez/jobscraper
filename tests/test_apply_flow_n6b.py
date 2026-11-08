"""WP-N6b oracles (Q-35; llm_fill_design §5.2, §7 G12, §8 "Before Submit", §13.3, §14).

Written from the spec, before and independent of the code (build plan WP-N6b "Done when: all T4
flow oracles pass (cache replay, pre-Submit scan)"). Each test cites its spec line. They skip
cleanly (the `needs` gate, `N6B_GATE` of test_apply_flow_llm.py: change it there only) until
`apply_flow._Run.pre_submit_scan` / `tailor_flow.resume_entries` exist.

  (a) cache replay (LF §13.3, §14):
      retry of the same job -> earlier pages replayed, 0 model calls; a changed cited fact or a
      changed resume text (inputs_hash) -> a miss; an unrelated fact change -> still a hit; two
      jobs never share an entry (job key); rows older than 30 days are purged at run start (the
      `now` seam); a model `unknown` is never replayed as an answer (R3 re-review F13, pinned
      for Q-80 too); `llm_fill.cache: false` writes nothing.
  (b) pre-Submit scan + review check (LF §8 "Before Submit (H7)"):
      a hit of `page.scan_required` -> validation_error, nothing sent (auto AND dry run); a clean
      page reaches Submit only in auto mode, exactly once, after the last fill and the scan; the
      review text check: the uploaded resume's file name must appear ("review: resume not shown");
      a required text value not shown is a note only.
  (c) `tailor_flow.resume_entries(cfg)` (LF §5.2): cached master only, `()` on any miss, never
      raises, never parses, contact excluded; `rctx.resume_entries` / `rctx.other_employers`
      (LF §7 G12): watchlist names + sighting employers minus this employer and its aliases.

Edge-level tests run headless Edge on 127.0.0.1 against the recorded-structure fixtures (no
network, scripted `FakeFillBackend`, temp DB, synthetic applicant) and return early when Edge is
not installed. Unit-level tests use the FakeNav of test_apply_flow_n6a.py (no Edge, no model).
Verify: python tests/run_tests.py -k apply_flow_n6b
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402
from test_apply_flow_llm import (  # noqa: E402
    APPLY_FIX, N6B_GATE, NOW, _Result, _fixture_nav, _registered, _session_class,
)

_W0 = len(WAITING)
ENTRIES_GATE = ("jobscraper.tailor_flow:resume_entries",)
CLOCK = 1_700_000_000.0                    # 2023-11-14T22:13:20Z: the unit-level clock
DAY = 86400.0
WD_A_05 = "llm_fill/wd_a/05-questions_2/page.html"          # one model-decided field (start date)
WD_A_04 = "llm_fill/wd_a/04-questions_1/page.html"          # salary + one optional unknown
START_KEY = "|What is your earliest available start date?"
UNKNOWN_OPTIONAL_KEY = "|If yes, please specify"
ADDRESS2_KEY = "|Address Line 2"


# ------------------------------------------------------------------ helpers (always defined)

def _fx():
    import llm_fill_support as L
    return L


def _calls(*steps: str, tenant: str = "wd_a") -> list[dict]:
    out: list[dict] = []
    for s in steps:
        out += json.loads((_fx().FIX / tenant / s / "reply.json").read_text(encoding="utf-8"))["calls"]
    return out


def _backend(*steps: str, tenant: str = "wd_a", strict: bool = True):
    return _fx().FakeFillBackend(replies=_calls(*steps, tenant=tenant), strict=strict)


def _silent():
    """A backend that fails the test loudly on any call (strict, no replies)."""
    return _fx().FakeFillBackend(replies=[], strict=True)


def _text(name: str) -> str:
    return (_fx().FIX / name).read_text(encoding="utf-8")


def _job(w, external_id: str, *, company_id=None, jd: str = ""):
    from apply_flow_support import add_job
    return add_job(w.store, key="exampleco", name="Example Employer", provider="wdfixture",
                   slug="exampleco", external_id=external_id, description=jd,
                   url=f"https://fixture.example.test/job/{external_id}", company_id=company_id)


def _attempt(w, jid, backend, start_rel, *, dry_run=True, resume_text=None, acfg_over=None,
             root: Path = APPLY_FIX, now: float = NOW):
    """One apply attempt over a fixture page in an EXISTING world (so a second attempt can see
    the first one's cache). None when headless Edge is not available. Never closes `w`."""
    from apply_flow_support import Say, edge_acfg, edge_available
    from llm_fill_support import FixtureDir
    from jobscraper import apply_flow
    if not edge_available():
        return None
    edge_dir = str(w.tmp / "edge-profile")
    cls, sessions, say = _session_class(), [], Say()

    def factory(acfg):
        s = cls(acfg, profile_dir=edge_dir).start()
        sessions.append(s)
        return s
    acfg = dataclasses.replace(edge_acfg(w.cfg.apply, edge_dir, fill="llm", **(acfg_over or {})),
                               step_timeout_s=3)
    nav = _fixture_nav(start_rel)
    orig = apply_flow._Run.resume_text
    if resume_text is not None:
        apply_flow._Run.resume_text = lambda self, path: resume_text
    try:
        with FixtureDir(root) as fx, _registered(nav):
            nav.base = fx.url("").rstrip("/")
            res = apply_flow.run(w.cfg, w.store, [jid], dry_run=dry_run, backend=backend, http=object(),
                                 browser_factory=factory, apply_cfg=acfg, say=say,
                                 evidence_dir=w.tmp / "evidence", now=lambda: now)
    finally:
        apply_flow._Run.resume_text = orig
    return _Result(w, res[0], say, nav, sessions, backend)


def _audit(w, attempt_id: int) -> list[tuple]:
    return sorted((x["step"], x["field_key"], x["status"]) for x in w.store.answers(attempt_id))


def _cache_jobs(w) -> list[str]:
    return sorted(r[0] for r in w.store.conn.execute("SELECT DISTINCT job_id FROM fill_cache"))


def _cache_count(w) -> int:
    return w.store.conn.execute("SELECT COUNT(*) FROM fill_cache").fetchone()[0]


def _asked(backend) -> set[str]:
    return {k for c in backend.calls for k in c.keys}


def _edit_profile(w, edit) -> None:
    import yaml
    p = w.cfg.applicant_path
    data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    edit(data)
    Path(p).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@contextlib.contextmanager
def _world(**kw):
    from apply_flow_support import make_world
    w = make_world(**kw)
    try:
        yield w
    finally:
        w.close()


def _stamp(epoch: float) -> str:
    from jobscraper.store import TIME_FMT
    return datetime.fromtimestamp(epoch, timezone.utc).strftime(TIME_FMT)


# ------------------------------------------------------------------ (a) cache replay, Edge level

@needs(*N6B_GATE)
def test_a_retry_of_the_same_job_replays_the_page_with_no_model_call():
    """LF §13.3 "a retry of the same job replays earlier pages" and the build plan T4 row "fill_cache
    replay with zero model calls on retry". Page 05 holds one model-decided field (the start date,
    a profile fact). Attempt 1 asks the model once; attempt 2 (same job, same resume text, same
    model) makes NO call (a strict backend with no replies), reaches the same state, and writes the
    same audit rows (a hit still goes through locks and G1-G12, so the field is filled again)."""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A1")
        text = _text("resume_sample.txt")
        fb1 = _backend("05-questions_2")
        a1 = _attempt(w, jid, fb1, WD_A_05, resume_text=text)
        if a1 is None:
            return
        from jobscraper.apply.contracts import AttemptState as S
        assert a1.r.state is S.READY_TO_SUBMIT, (a1.r.state, a1.r.reason, a1.r.reason_detail)
        assert len(fb1.calls) == 1 and _asked(fb1) == {START_KEY}, [c.keys for c in fb1.calls]
        fb2 = _silent()
        a2 = _attempt(w, jid, fb2, WD_A_05, resume_text=text)
        assert a2.r.state is S.READY_TO_SUBMIT, (a2.r.state, a2.r.reason, a2.r.reason_detail)
        assert fb2.calls == [], f"a retry must replay from fill_cache; asked {[c.keys for c in fb2.calls]}"
        assert _audit(w, a2.r.attempt_id) == _audit(w, a1.r.attempt_id)
        rows2 = {x["field_key"]: x["status"] for x in w.store.answers(a2.r.attempt_id)}
        assert "filled" in rows2.values(), rows2        # the replayed decision still went through the guards and was typed


@needs(*N6B_GATE)
def test_a_retry_never_asks_again_for_a_cached_field_only_for_a_model_unknown():
    """LF §13.3 + F13 together, on page 04 (salary = a fact decision, "If yes, please specify" =
    the model's `unknown`): attempt 2 may ask about the unknown field at most, never about the
    salary. (No assertion on whether the unknown is re-asked: F13 says it must be, the next test.)"""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A2")
        text = _text("resume_sample.txt")
        a1 = _attempt(w, jid, _backend("04-questions_1", "05-questions_2"), WD_A_04, resume_text=text)
        if a1 is None:
            return
        from jobscraper.apply.contracts import AttemptState as S
        assert a1.r.state is S.READY_TO_SUBMIT, (a1.r.state, a1.r.reason, a1.r.reason_detail)
        reply = {UNKNOWN_OPTIONAL_KEY: {"source": "unknown", "ref": "", "value": "", "evidence": ""}}
        fb2 = _fx().FakeFillBackend(replies=[{"kind": "page", "repeat": True, "reply": reply}], strict=True)
        a2 = _attempt(w, jid, fb2, WD_A_04, resume_text=text)
        assert a2.r.state is S.READY_TO_SUBMIT, (a2.r.state, a2.r.reason, a2.r.reason_detail)
        assert _asked(fb2) <= {UNKNOWN_OPTIONAL_KEY}, sorted(_asked(fb2))
        assert _audit(w, a2.r.attempt_id) == _audit(w, a1.r.attempt_id)


@needs(*N6B_GATE)
def test_a_changed_cited_fact_is_a_miss_and_an_unrelated_change_is_not():
    """LF §13.3 "a row whose `facts_used_hash` no longer matches is a miss ... answering a question
    in the Profile tab leaves every other decision cached" (build plan T4 "a changed cited fact ->
    a miss"). The start-date decision cites `profile:availability.earliest_start_date`. Changing
    an UNCITED leaf (`pay.current_salary`) -> still 0 calls; changing the cited one -> the model is
    asked for that field again."""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A3")
        text = _text("resume_sample.txt")
        a1 = _attempt(w, jid, _backend("05-questions_2"), WD_A_05, resume_text=text)
        if a1 is None:
            return
        _edit_profile(w, lambda d: d["pay"].__setitem__("current_salary", 4200))
        fb2 = _silent()
        a2 = _attempt(w, jid, fb2, WD_A_05, resume_text=text)
        assert fb2.calls == [], "an uncited fact changed: every decision stays cached"
        _edit_profile(w, lambda d: d["availability"].__setitem__("earliest_start_date", "2026-12-01"))
        fb3 = _fx().FakeFillBackend(replies=_calls("05-questions_2"), strict=True)
        a3 = _attempt(w, jid, fb3, WD_A_05, resume_text=text)
        pages = [c for c in fb3.calls if c.kind == "page" and c.keys]     # (keyless "name a question" calls are not fills)
        assert len(pages) == 1 and set(pages[0].keys) == {START_KEY}, \
            f"the cited fact changed: one fresh page call for that field; asked {[(c.kind, c.keys) for c in fb3.calls]}"
        assert {c.kind for c in fb3.calls} <= {"page", "second", "corrective", "recheck"}, [c.kind for c in fb3.calls]
        # (the end state of attempt 3 is not asserted: the new date may be refused by a date guard)


@needs(*N6B_GATE)
def test_a_changed_resume_text_is_a_miss():
    """LF §13.3 key: `inputs_hash = sha256(redacted resume text + JD text)[:16]` is part of the key,
    so a different resume text (or JD) hits nothing: the model is asked again (build plan T4)."""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A4")
        text = _text("resume_sample.txt")
        a1 = _attempt(w, jid, _backend("05-questions_2"), WD_A_05, resume_text=text)
        if a1 is None:
            return
        fb2 = _backend("05-questions_2")
        a2 = _attempt(w, jid, fb2, WD_A_05, resume_text=text + "\nCertified Example Practitioner, 2026.")
        assert _asked(fb2) == {START_KEY}, f"inputs_hash changed: expected a fresh call, asked {sorted(_asked(fb2))}"
        assert a2.r.state is a1.r.state, (a2.r.state, a2.r.reason, a2.r.reason_detail)


@needs(*N6B_GATE)
def test_a_changed_job_description_is_a_miss():
    """LF §13.3 key (`inputs_hash` covers the JD text): the same job re-scraped with a new JD does
    not replay the decisions made on the old one."""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A5", jd=_text("jd_sample.txt"))
        text = _text("resume_sample.txt")
        a1 = _attempt(w, jid, _backend("05-questions_2"), WD_A_05, resume_text=text)
        if a1 is None:
            return
        cols = [r[1] for r in w.store.conn.execute("PRAGMA table_info(jobs)")]
        col = "description" if "description" in cols else "jd_text"
        w.store.conn.execute(f"UPDATE jobs SET {col} = ? WHERE job_id = ?",
                             (_text("jd_sample.txt") + "\nNow also: stakeholder reporting.", jid))
        w.store.commit()
        fb2 = _backend("05-questions_2")
        _attempt(w, jid, fb2, WD_A_05, resume_text=text)
        assert _asked(fb2) == {START_KEY}, sorted(_asked(fb2))


@needs(*N6B_GATE)
def test_a_two_jobs_never_share_a_cache_entry():
    """LF §13.3 key starts with `job_id`; §14 PRIMARY KEY (job_id, ...). Defect class: pagefill read
    `ctx.job.get("id", "")` while the job dict's key is `job_id`, so every job wrote under "" and
    job B replayed job A's decisions. Two jobs, same company, same JD, same resume text: B asks the
    model although A is cached; each job's own retry is then silent; the cache holds one distinct
    non-empty job_id per job."""
    with _world() as w:
        cid, ja = _job(w, "REQ-A6")
        _c, jb = _job(w, "REQ-A7", company_id=cid)
        assert ja != jb
        text = _text("resume_sample.txt")
        a = _attempt(w, ja, _backend("05-questions_2"), WD_A_05, resume_text=text)
        if a is None:
            return
        fb_b = _backend("05-questions_2")
        _attempt(w, jb, fb_b, WD_A_05, resume_text=text)
        assert _asked(fb_b) == {START_KEY}, \
            f"job B must not replay job A's decision; asked {sorted(_asked(fb_b))}"
        assert _cache_jobs(w) == sorted([ja, jb]), _cache_jobs(w)
        for jid in (ja, jb):
            fb = _silent()
            r = _attempt(w, jid, fb, WD_A_05, resume_text=text)
            assert fb.calls == [], f"{jid}: its own retry replays from its own rows"
            assert r.r.state.value == "ready_to_submit", r.r.state


@needs(*N6B_GATE)
def test_a_model_unknown_is_never_replayed_as_an_answer():
    """R3 re-review F13 (docs/reviews/Q-35-R3-rereview.md; pin for Q-80, "Tester pin"): a page that
    stops on a required `unknown` (wd_b: Address Line 2) must not store that unknown as a decision
    to replay. The retry (the owner added the fact, here: same everything) asks the model about
    that field AGAIN, while the page's other decisions are replayed (LF §8 step 13, "the retry
    after the owner answers replays the rest"): "Given Name(s)" is not asked again.
    Either fix is accepted (`_cache_put` skips UNKNOWN, or `_cached` treats it as a miss). If the
    engineer defers F13 to Q-80 this test is the expected red one: say so in the handoff."""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A8")
        text = _text("resume_sample.txt")
        start = "llm_fill/wd_b/02-my_information/page.html"
        fb1 = _backend("02-my_information", tenant="wd_b")
        a1 = _attempt(w, jid, fb1, start, resume_text=text)
        if a1 is None:
            return
        from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
        assert a1.r.state is S.FAILED and a1.r.reason is R.UNANSWERABLE_REQUIRED, \
            (a1.r.state, a1.r.reason, a1.r.reason_detail)
        assert ADDRESS2_KEY in _asked(fb1)
        fb2 = _backend("02-my_information", tenant="wd_b", strict=False)
        _attempt(w, jid, fb2, start, resume_text=text)
        asked = _asked(fb2)
        assert ADDRESS2_KEY in asked, "the stored `unknown` was replayed: the model was not asked again (F13)"
        assert "|Given Name(s)" not in asked, "the page's other decisions must replay from the cache"


@needs(*N6B_GATE)
def test_a_cache_disabled_in_config_writes_and_replays_nothing():
    """LF §13.3 last line: `llm_fill.cache: false` disables it. No rows after a finished page; the
    retry asks the model again."""
    with _world() as w:
        _cid, jid = _job(w, "REQ-A9")
        text = _text("resume_sample.txt")
        over = {"llm_fill": dataclasses.replace(w.cfg.apply.llm_fill, cache=False)}
        a1 = _attempt(w, jid, _backend("05-questions_2"), WD_A_05, resume_text=text, acfg_over=over)
        if a1 is None:
            return
        assert _cache_count(w) == 0, "cache: false must write no row"
        fb2 = _backend("05-questions_2")
        _attempt(w, jid, fb2, WD_A_05, resume_text=text, acfg_over=over)
        assert _asked(fb2) == {START_KEY}


# ------------------------------------------------------------------ unit harness (FakeNav)

def _unit():
    """The FakeNav world of test_apply_flow_n6a.py (imported lazily: it needs the N6a code)."""
    import test_apply_flow_n6a as U
    return U


def _run_unit(w, jid, nav, model=None, *, dry_run=True, now=CLOCK):
    from apply_flow_support import FakeBrowserFactory, Say, page_signals
    from jobscraper import apply_flow
    U = _unit()
    factory, say = FakeBrowserFactory(), Say()
    acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0)
    model = model or U.FakeModel()
    with _registered(nav), page_signals():
        res = apply_flow.run(w.cfg, w.store, [jid], dry_run=dry_run, backend=model, http=object(),
                             browser_factory=factory, apply_cfg=acfg, say=say,
                             evidence_dir=w.tmp / "evidence", now=lambda: now)
    return res[0], say


@contextlib.contextmanager
def _script(nav, script, events=None):
    """Replace `apply_flow.fill_page`: `script(nav, services, ctx, rctx)` -> PageOutcome."""
    from jobscraper import apply_flow
    saved = apply_flow.fill_page

    def fake(page, nav_, ctx, rctx, services):
        if events is not None:
            events.append(f"fill:{nav_.step_id(page, ctx)}")
        return script(nav_, services, ctx, rctx)
    apply_flow.fill_page = fake
    try:
        yield
    finally:
        apply_flow.fill_page = saved


def _two_steps(nav, services, ctx, rctx):
    U = _unit()
    if nav.step_id(None, None) == "one":
        return U.outcome("one", [U.pf("a", "First name"), U.pf("b", "Last name")])
    return U.outcome("two", [U.pf("c", "Nationality")])


def _row(sig, *, model="fake-model:1b", inputs="i" * 16, facts="f" * 16, source="profile", ref="profile:x.y"):
    return {"field_sig": sig, "prompt_version": "fill:v2", "model": model, "inputs_hash": inputs,
            "facts_used_hash": facts,
            "decision": {"source": source, "ref": ref, "evidence": "", "value": None, "via": "page"}}


@contextlib.contextmanager
def _scan(hits=(), events=None, calls=None):
    """Stand in for `page.scan_required(page, scope)` (the reader needs a real DOM)."""
    from jobscraper.apply import page as P
    saved = P.scan_required

    def fake(page, scope=""):
        if events is not None:
            events.append("scan")
        if calls is not None:
            calls.append(scope)
        return tuple(hits)
    P.scan_required = fake
    try:
        yield
    finally:
        P.scan_required = saved


# ------------------------------------------------------------------ (a) purge and wiring, unit level

@needs(*N6B_GATE)
def test_a_rows_older_than_30_days_are_purged_at_run_start_on_the_attempt_clock():
    """LF §13.3 "Purge rows older than 30 days at `apply_flow.run` start (`now` seam, TR-5)"; §14
    `fill_cache_purge(before)`. Rows stamped 31 and 29 days before the injected clock: after the
    run starts only the 29-day row is left. The clock is 2023, far from the wall clock, so a purge
    on `utcnow()` would delete the 29-day row too (and keep neither)."""
    U = _unit()
    w, jid = U.world()
    try:
        w.store.fill_cache_put(jid, [_row("old" + "0" * 13)], now=_stamp(CLOCK - 31 * DAY))
        w.store.fill_cache_put(jid, [_row("new" + "0" * 13)], now=_stamp(CLOCK - 29 * DAY))
        assert _cache_count(w) == 2
        nav = U.FakeNav()
        seen = {}

        def script(n, services, ctx, rctx):
            seen.setdefault("sigs", sorted(r[0] for r in w.store.conn.execute("SELECT field_sig FROM fill_cache")))
            return _two_steps(n, services, ctx, rctx)
        with _script(nav, script):
            r, _say = _run_unit(w, jid, nav)
        assert seen["sigs"] == ["new" + "0" * 13], seen
    finally:
        w.close()


@needs(*N6B_GATE)
def test_a_the_services_cache_round_trips_per_job_model_and_inputs_and_stamps_with_the_clock():
    """LF §13.3 / §14 wiring of `FillServices.cache_put` / `cache_get` onto `fill_cache`
    (contracts v5 shapes: rows with field_sig, prompt_version, model, inputs_hash, facts_used_hash,
    decision). Round trip returns {sig: {"decision": ..., "facts_used_hash": ...}}; another job,
    another model or another inputs_hash gets {}; a row put on the attempt clock C is kept by a run
    at C+29d and purged by a run at C+31d (rows are stamped with the injected clock, not the wall
    clock)."""
    U = _unit()
    w, jid = U.world()
    try:
        nav = U.FakeNav()
        sig = "s" * 16
        probes = {}

        def script(n, services, ctx, rctx):
            services.cache_put(jid, [_row(sig)])
            probes["same"] = services.cache_get(jid, [sig, "zz"], "fill:v2", services.model, "i" * 16)
            probes["other_job"] = services.cache_get("other-job", [sig], "fill:v2", services.model, "i" * 16)
            probes["other_model"] = services.cache_get(jid, [sig], "fill:v2", "another-model:7b", "i" * 16)
            probes["other_inputs"] = services.cache_get(jid, [sig], "fill:v2", services.model, "j" * 16)
            probes["other_prompt"] = services.cache_get(jid, [sig], "fill:v1", services.model, "i" * 16)
            return _two_steps(n, services, ctx, rctx)
        with _script(nav, script):
            _run_unit(w, jid, nav)
        assert list(probes["same"]) == [sig], probes["same"]
        got = probes["same"][sig]
        assert got["facts_used_hash"] == "f" * 16 and got["decision"]["source"] == "profile" \
            and got["decision"]["ref"] == "profile:x.y", got
        assert probes["other_job"] == {} and probes["other_model"] == {} \
            and probes["other_inputs"] == {} and probes["other_prompt"] == {}, probes
        for days, expect in ((29, [sig]), (31, [])):
            nav2, seen = U.FakeNav(), {}

            def look(n, services, ctx, rctx, _seen=seen):
                _seen["sigs"] = sorted(r[0] for r in w.store.conn.execute("SELECT field_sig FROM fill_cache"))
                return _two_steps(n, services, ctx, rctx)
            with _script(nav2, look):
                _run_unit(w, jid, nav2, now=CLOCK + days * DAY)
            assert seen["sigs"] == expect, (days, seen)
    finally:
        w.close()


# ------------------------------------------------------------------ (b) pre-Submit scan, unit level

def _submit_nav(events):
    U = _unit()
    nav = U.FakeNav()

    def submit(page, ctx):
        events.append("submit")
    nav.submit = submit
    return nav


@needs(*N6B_GATE)
def test_b_a_required_field_left_empty_at_review_stops_before_submit_in_both_modes():
    """LF §8 "Before Submit (H7)": `page.scan_required` over the whole form, any hit ->
    `validation_error`, nothing sent. The scan comes BEFORE the dry-run split, so a dry run fails
    the same way. Submit is never called, `submit_clicked_at` stays empty, the attempt is FAILED
    (not ready_to_submit) and says why."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    U = _unit()
    for dry in (False, True):
        w, jid = U.world()
        try:
            events: list[str] = []
            nav = _submit_nav(events)
            with _script(nav, _two_steps, events), _scan(("two:nationality",), events):
                r, say = _run_unit(w, jid, nav, dry_run=dry)
            assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR, (dry, r.state, r.reason, r.reason_detail)
            assert r.reason_detail, "the owner must be told what was empty"
            assert "submit" not in events and events.count("scan") >= 1, events
            row = w.store.attempt(r.attempt_id)
            assert row["submit_clicked_at"] is None
            assert w.store.attempt(r.attempt_id)["state"] == "failed"
        finally:
            w.close()


@needs(*N6B_GATE)
def test_b_a_clean_page_reaches_submit_only_in_auto_mode_once_after_the_scan():
    """LF §8 "Before Submit": clean scan, then "unchanged: dry run -> ready_to_submit; auto ->
    submit_clicked_at committed -> nav.submit() once". (N6a's AUTO_SUBMIT_BLOCKED stop is gone.)
    Order: the last fill, then the scan, then Submit. A dry run scans too and never submits."""
    from jobscraper.apply.contracts import AttemptState as S
    U = _unit()
    # auto mode
    w, jid = U.world()
    try:
        events: list[str] = []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan((), events):
            r, say = _run_unit(w, jid, nav, dry_run=False)
        assert events.count("submit") == 1, events
        last_fill = max(i for i, e in enumerate(events) if e.startswith("fill:"))
        assert last_fill < events.index("scan") < events.index("submit"), events
        assert r.state in (S.SUBMITTED, S.SUBMITTED_UNCONFIRMED), (r.state, r.reason, r.reason_detail)
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"], "committed before the click"
        assert "needs the pre-Submit scan" not in say.text
    finally:
        w.close()
    # dry run
    w, jid = U.world()
    try:
        events = []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan((), events):
            r, say = _run_unit(w, jid, nav, dry_run=True)
        assert r.state is S.READY_TO_SUBMIT and not r.reason_detail, (r.state, r.reason, r.reason_detail)
        assert "submit" not in events and events.count("scan") == 1, events
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None
    finally:
        w.close()


@needs(*N6B_GATE)
def test_b_the_scan_covers_the_form_scope_after_the_last_fill_and_never_on_a_transport_stop():
    """LF §8 "Before Submit" (whole form) and §11 (a stop never reaches review): `scan_required` is
    called with the navigator's scope string (positional or keyword, here ""), only once the
    steps are done; a page that stops (required unknown) never runs the pre-Submit scan or Submit."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    U = _unit()
    w, jid = U.world()
    try:
        events, scopes = [], []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan((), events, scopes):
            _run_unit(w, jid, nav, dry_run=False)
        assert scopes and all(s == "" for s in scopes), scopes
    finally:
        w.close()
    w, jid = U.world()
    try:
        events = []
        nav = _submit_nav(events)

        def stop(n, s, ctx, rctx):
            return U.outcome("one", [U.pf("q", "Describe your weekend.")],
                             {"q": U.ans("q", None, status=U.AnswerStatus.UNKNOWN, note="model: unknown")},
                             unknown_required=("q",))
        # steps before review may scan (the page-level scan is fill_page's); the PRE-SUBMIT one must not run
        with _script(nav, stop, events), _scan((), events):
            r, _say = _run_unit(w, jid, nav, dry_run=False)
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason)
        assert "submit" not in events and "scan" not in events, events
    finally:
        w.close()


# ------------------------------------------------------------------ (b) review text check, Edge level

def _variant_root(tmp: Path, review_edit) -> Path:
    """A copy of the llm_fill fixtures whose wd_a review page is edited by `review_edit(html)`."""
    root = tmp / "variant"
    shutil.copytree(APPLY_FIX / "llm_fill", root / "llm_fill")
    page = root / "llm_fill" / "wd_a" / "07-review" / "page.html"
    html = page.read_text(encoding="utf-8")
    new = review_edit(html)
    assert new != html, "the variant must differ from the recorded review page"
    page.write_text(new, encoding="utf-8")
    return root


def _full_wd_a(w, jid, root, *, dry_run):
    return _attempt(w, jid, _backend("01-autofill_with_resume", "02-my_information", "03-my_experience",
                                     "04-questions_1", "05-questions_2", "06-voluntary_disclosures",
                                     "07-review"),
                    "llm_fill/wd_a/01-autofill_with_resume/page.html", dry_run=dry_run, root=root,
                    resume_text=_text("resume_sample.txt"), acfg_over={})


_NAME = "Alex_Testcase_Resume.pdf"          # the recorded review page's file name text


@needs(*N6B_GATE)
def test_b_the_review_must_show_the_uploaded_resume_file_name():
    """LF §8 "Before Submit": "the review text check: the resume file name must appear when a
    resume was uploaded (else `validation_error` "review: resume not shown")". wd_a uploads
    `resume.pdf` on step 1; the review page is edited to show a different document. The attempt
    fails closed (in a dry run too: the check precedes the dry-run split), Submit never pressed."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    with _world() as w:
        _cid, jid = _job(w, "REQ-B1", jd=_text("jd_sample.txt"))
        root = _variant_root(w.tmp, lambda h: h.replace(_NAME, "Some_Other_Document.docx"))
        out = _full_wd_a(w, jid, root, dry_run=True)
        if out is None:
            return
        r = out.r
        assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR, (r.state, r.reason, r.reason_detail, out.say.text[-800:])
        assert "resume not shown" in r.reason_detail, r.reason_detail
        assert out.final["submit"] == "0"
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None


@needs(*N6B_GATE)
def test_b_a_review_that_shows_the_resume_name_passes_and_a_missing_text_value_is_a_note_only():
    """LF §8 "Before Submit": the file name present -> the check passes; "text values of required
    fields not shown -> note only". The review page shows the exact uploaded name and no longer
    shows the salary text: a dry run still ends `ready_to_submit`. In auto mode the same page then
    presses Submit exactly once (shim `data-submit-count` = 1, `submit_clicked_at` set)."""
    from jobscraper.apply.contracts import AttemptState as S
    with _world() as w:
        _cid, jid = _job(w, "REQ-B2", jd=_text("jd_sample.txt"))

        def edit(html: str) -> str:
            html = html.replace(_NAME, "resume.pdf")
            return re.sub(r'<div data-automation-id="reviewItem"><h4>What is your expected monthly salary'
                          r'[^<]*</h4><p>[^<]*</p></div>', "", html)
        root = _variant_root(w.tmp, edit)
        out = _full_wd_a(w, jid, root, dry_run=True)
        if out is None:
            return
        assert out.r.state is S.READY_TO_SUBMIT, (out.r.state, out.r.reason, out.r.reason_detail, out.say.text[-800:])
        assert out.final["submit"] == "0"
        out2 = _full_wd_a(w, jid, root, dry_run=False)
        assert out2.final["submit"] == "1", out2.final
        row = w.store.attempt(out2.r.attempt_id)
        assert row["submit_clicked_at"], "committed before the click"
        assert out2.r.state in (S.SUBMITTED, S.SUBMITTED_UNCONFIRMED), (out2.r.state, out2.r.reason, out2.r.reason_detail)


# ------------------------------------------------------------------ (c) resume entries

def _master_world(w, *, resume_hash="sha256:n6b", text_override=None, write_master=True):
    """A cached master (tests/fixtures/tailor/case_a) for `w.cfg`; the resume-file layer is stubbed
    on `tailor_flow.resume_ingest` so no PDF is parsed. Returns (master, restore)."""
    from jobscraper import tailor_flow
    from jobscraper.tailor import master as master_mod
    from jobscraper.profile import resume_ingest
    data = json.loads((Path(__file__).resolve().parent / "fixtures" / "tailor" / "case_a" / "master.json")
                      .read_text(encoding="utf-8"))
    m = master_mod.from_dict(data)
    m.resume_hash = "sha256:n6b"
    if write_master:
        master_mod.save(w.cfg.master_resume_path, m)
    text = "\n".join(master_mod._leaves(m)) if text_override is None else text_override
    assert text_override is not None or not master_mod.leaf_check(m, text)
    saved = (resume_ingest.find_resume, resume_ingest.extract_text, resume_ingest.file_hash)
    resume_ingest.find_resume = lambda d: Path(d) / "resume.pdf"
    resume_ingest.extract_text = lambda p: text
    resume_ingest.file_hash = lambda p: resume_hash

    def restore():
        resume_ingest.find_resume, resume_ingest.extract_text, resume_ingest.file_hash = saved
    return m, restore, tailor_flow


@needs(*ENTRIES_GATE)
def test_c_resume_entries_come_from_the_cached_master_only():
    """LF §5.2 / build plan WP-N6b: `resume_entries(cfg) -> tuple[tuple[str, str, str], ...]`
    = `(id, kind, text)` per master entry, ids like `experience[0]` (contracts v5), the `master_text`
    pattern (cached master only; contact excluded). Each entry's text carries its title,
    organisation and bullets so E2 matching and G3/G6 grounding can use it."""
    with _world() as w:
        m, restore, tf = _master_world(w)
        try:
            got = tf.resume_entries(w.cfg)
        finally:
            restore()
        assert isinstance(got, tuple) and len(got) == 2, got
        assert all(isinstance(e, tuple) and len(e) == 3 and all(isinstance(x, str) for x in e) for e in got), got
        kinds = {k for _i, k, _t in got}
        assert kinds == {"experience", "education"}, kinds
        ids = [i for i, _k, _t in got]
        assert len(set(ids)) == 2 and all(re.fullmatch(r"(experience|education)\[\d+\]", i) for i in ids), ids
        assert all(i.startswith(k + "[") for i, k, _t in got), got
        exp = next(e for e in got if e[1] == "experience")
        assert exp[0] in ("experience[0]", "experience[1]"), exp[0]          # per-kind or running index (spec reads either way)
        for must in ("Software Engineering Intern", "Acme Logistics Pte Ltd",
                     "Built REST APIs in Python and Postgres for shipment tracking."):
            assert must in exp[2], (must, exp[2][:200])
        assert [k for _i, k, _t in got] == [s.kind.value for s, _e in m.entries()], \
            "master reading order (education comes first in this master)"
        assert m.contact.name not in "\n".join(t for _i, _k, t in got), "contact is excluded"


@needs(*ENTRIES_GATE)
def test_c_resume_entries_is_empty_on_any_miss_and_never_raises():
    """LF §5.2 + build plan: "cached master only, never parses, never raises, `()` on a miss":
    no cache file; a cache for another resume hash; a corrupt cache file; a master whose text no
    longer occurs in the resume (leaf check); a resume file that cannot be read."""
    with _world() as w:
        # (1) no master cache at all
        _m, restore, tf = _master_world(w, write_master=False)
        try:
            assert tf.resume_entries(w.cfg) == ()
        finally:
            restore()
        # (2) the cache belongs to another resume
        _m, restore, tf = _master_world(w, resume_hash="sha256:someone-else")
        try:
            assert tf.resume_entries(w.cfg) == ()
        finally:
            restore()
        # (3) corrupt cache file
        _m, restore, tf = _master_world(w)
        try:
            Path(w.cfg.master_resume_path).write_text("{not json", encoding="utf-8")
            assert tf.resume_entries(w.cfg) == ()
        finally:
            restore()
        # (4) the resume's text no longer contains the master's fields (a hand edit gone wrong)
        _m, restore, tf = _master_world(w, text_override="completely different words")
        try:
            assert tf.resume_entries(w.cfg) == ()
        finally:
            restore()
        # (5) the resume file cannot be read
        _m, restore, tf = _master_world(w)
        from jobscraper.profile import resume_ingest

        def boom(p):
            raise OSError("unreadable")
        resume_ingest.extract_text = boom
        try:
            assert tf.resume_entries(w.cfg) == ()
        finally:
            restore()


@needs(*N6B_GATE, *ENTRIES_GATE)
def test_c_rctx_gets_the_resume_entries_and_a_miss_gives_the_empty_tuple():
    """LF §5.2 (owner WP-N6b): `apply_flow` fills `ResolveContext.resume_entries` from
    `tailor_flow.resume_entries(cfg)`; with no cached master the context carries `()` and the
    attempt still runs (the profile's own entries are then the only blocks)."""
    from jobscraper import tailor_flow
    U = _unit()
    sentinel = (("experience[0]", "experience", "Example Intern at Example Employer\n- Did a thing."),)
    for patch, expect in ((sentinel, sentinel), (None, ())):
        w, jid = U.world()
        saved = tailor_flow.resume_entries
        if patch is not None:
            tailor_flow.resume_entries = lambda cfg, _v=patch: _v
        seen = {}
        try:
            nav = U.FakeNav()

            def script(n, s, ctx, rctx):
                seen["r"] = rctx.resume_entries
                return _two_steps(n, s, ctx, rctx)
            with _script(nav, script):
                r, _say = _run_unit(w, jid, nav)
            assert seen["r"] == expect, seen
            assert r.state.value == "ready_to_submit", (r.state, r.reason, r.reason_detail)
        finally:
            tailor_flow.resume_entries = saved
            w.close()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


@needs(*N6B_GATE)
def test_c_other_employers_are_watchlist_and_sighting_names_minus_this_employer_and_aliases():
    """LF §7 G12 (build plan WP-N6b "fill `rctx.other_employers`: watchlist names + sighting
    employers, this employer and its aliases removed"). World: this job at "Fake Co" (company
    key `fakeco`, board `co`); watchlist/companies: Other Corp One, Other Corp Two, and "FakeCo"
    (an alias spelling of this employer); a captured question's sighting at "Third Corp" and one at
    "fakeco". Expect {other corp one, other corp two, third corp}; none of this employer's forms;
    names only (strings)."""
    import yaml
    from questions_support import seed_question
    U = _unit()
    w, jid = U.world()
    try:
        names = ["Other Corp One", "Other Corp Two", "FakeCo"]
        for i, n in enumerate(names):
            w.store.insert_company(f"other{i}", n, f"https://other{i}.example/careers", provider="greenhouse",
                                   slug=f"other{i}")
        (w.tmp / "watchlist.yaml").write_text(yaml.safe_dump({"version": 1, "companies": [
            {"name": n, "careers_url": f"https://other{i}.example/careers"} for i, n in enumerate(names)]}),
            encoding="utf-8")
        w.store.commit()
        nav0 = U.FakeNav()                                  # a first attempt: sightings need an attempt id
        with _script(nav0, _two_steps):
            r0, _s = _run_unit(w, jid, nav0)
        # sightings whose job is no longer in `jobs` (company_id None): only `employer_norm` names them
        seed_question(w.store, attempt_id=r0.attempt_id, job_id="gone-job-1", company_id=None,
                      employer_norm="third corp", key="q_a", label="Why Third Corp?", kind="text",
                      field_key="qa")
        seed_question(w.store, attempt_id=r0.attempt_id, job_id="gone-job-2", company_id=None,
                      employer_norm="fakeco", key="q_b", label="Why us?", kind="text", field_key="qb")
        seen = {}
        nav = U.FakeNav()

        def script(n, s, ctx, rctx):
            seen["o"] = rctx.other_employers
            return _two_steps(n, s, ctx, rctx)
        with _script(nav, script):
            _run_unit(w, jid, nav)
        got = seen["o"]
        assert isinstance(got, tuple) and all(isinstance(x, str) and x.strip() for x in got), got
        forms = {_norm(x) for x in got}
        assert {"other corp one", "other corp two", "third corp"} <= forms, forms
        assert not [x for x in forms if x in ("fake co", "fakeco", "co")], f"this employer or an alias leaked: {sorted(forms)}"
    finally:
        w.close()


@needs(*N6B_GATE)
def test_c_other_employers_is_empty_when_there_is_nobody_else():
    """LF §7 G12: a world with only this employer (empty watchlist, no sightings) -> `()`; the
    employer itself is never its own "other employer"."""
    U = _unit()
    w, jid = U.world()
    try:
        seen = {}
        nav = U.FakeNav()

        def script(n, s, ctx, rctx):
            seen["o"] = rctx.other_employers
            return _two_steps(n, s, ctx, rctx)
        with _script(nav, script):
            _run_unit(w, jid, nav)
        assert [x for x in seen["o"] if _norm(x) in ("fake co", "fakeco")] == [], seen
        assert seen["o"] == (), seen
    finally:
        w.close()


if WAITING[_W0:]:
    print(f"[test_apply_flow_n6b] {len(WAITING[_W0:])} oracle tests wait for WP-N6b: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
