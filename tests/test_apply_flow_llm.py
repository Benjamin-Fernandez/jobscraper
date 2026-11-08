"""WP-T4 flow oracles for the LLM filling loop (LF §8 flow part, §11, §13.1; test plan §6).

Written at WP-N6a against the spec (llm_fill_design §8 "The flow per step", §11 "Stops, capture,
reason codes", §13.1 budget; build plan WP-N6a "Do / Done when"), not against the code. They run
the real `apply_flow.run` with the real `pagefill.fill_page`, the real Workday navigator
(subclassed only to open a local fixture URL instead of a posting), the scripted
`FakeFillBackend` and headless Edge on 127.0.0.1 (http.server + shim.js). No network, no real
model, temp DB, synthetic applicant. The scripted-`fill_page` unit tests of the same loop are in
test_apply_flow_n6a.py.

  - stop: `wd_b` -> failed(unanswerable_required), detail = the first label, after one
    CapturedQuestion (profile_gap, target_path, verbatim label); the page is left as the site put
    it (no input event, no changed value, no Next click); transport unknowns are never captured;
  - model_unavailable: a failed warm-up ends the attempt before `browser_factory` is called
    (count 0) and passes `llm_fill.keep_alive`; a page call that times out gives "timed out on
    <step>", nothing captured, nothing typed;
  - flow: the same step twice, or no fields on a non-review step -> page_unrecognised;
  - replay smoke: the 7 `wd_a` steps -> ready_to_submit, one audit row per field per step,
    data-submit-count=0, prompts pass `assert_no_secrets`.

Still gated for WP-N6b (the cache and the pre-Submit scan are stubs/absent in N6a; build plan
N6b "Done when: all T4 flow oracles pass (cache replay, pre-Submit scan)"):
  - cache replay: zero model calls on a retry, a changed cited fact -> a miss (LF §13.3, TR-2);
  - Greenhouse/review pre-Submit scan stops an empty required field (`validation_error`, no click)
    and the review text check (resume file name must appear).
Verify: python tests/run_tests.py -k apply_flow_llm
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
GATE = ("jobscraper.apply.pagefill:fill_page", "jobscraper.apply_flow:_fill_services")
# N6b: `cache_get`/`cache_put` are stubs in N6a and the flow has no pre-Submit scan. The name is
# ASSUMED (engineer's handoff names none); confirm with lane N at WP-N6b and change GATE only.
N6B_GATE = ("jobscraper.apply_flow:_Run.pre_submit_scan",)

ROOT = Path(__file__).resolve().parents[1]
APPLY_FIX = ROOT / "tests" / "fixtures" / "apply"
NOW = 1_793_700_000.0                      # 2026-11-03 (the day the fixtures were recorded for)

# What a page looks like to a person: values, ticks, pills, listbox texts, entry panels, files, plus
# the counters the shim and the session keep. Compared before the flow and at the end of a stop.
SNAP_JS = """() => JSON.stringify({
  v: [...document.querySelectorAll('input,textarea')].map(e => [e.value, e.checked]),
  b: [...document.querySelectorAll('button[aria-haspopup="listbox"]')].map(e => e.textContent.trim()),
  p: [...document.querySelectorAll('[data-automation-id="selectedItem"]')].map(e => e.title),
  g: document.querySelectorAll('[role="group"][data-entry]').length,
  f: [...document.querySelectorAll('[data-automation-id="file-upload-item-name"]')].map(e => e.textContent)})"""
FINAL_JS = f"""() => ({{page: ({SNAP_JS})(), submit: document.body.dataset.submitCount || '0',
  next: document.body.dataset.nextClicks || '0', inputs: (window.__inputs || []).length,
  path: location.pathname}})"""


def test_the_flow_llm_fixtures_are_present():
    """Always runs, so `-k apply_flow_llm` is green before N6a."""
    from llm_fill_support import FIX
    for step in ("01-autofill_with_resume", "02-my_information", "03-my_experience", "04-questions_1",
                 "05-questions_2", "06-voluntary_disclosures", "07-review"):
        for name in ("page.html", "reply.json"):
            assert (FIX / "wd_a" / step / name).is_file(), (step, name)
    assert (FIX / "wd_b" / "02-my_information" / "reply.json").is_file()
    for name in ("stay.html", "empty.html"):
        assert (APPLY_FIX / "flow_llm" / name).is_file(), name


# ------------------------------------------------------------------ harness

class _Recorder:
    """A backend that is not there, or one that is: records warm-ups, never answers."""
    name, model_id, available = "rec", "rec-model:1b", True

    def __init__(self, warm_error: str = ""):
        self.warm_error, self.warms, self.completes = warm_error, [], 0

    def warm(self, keep_alive=None):
        from jobscraper.backends import BackendError
        self.warms.append(keep_alive)
        if self.warm_error:
            raise BackendError(self.warm_error)

    def complete(self, *a, **k):
        self.completes += 1
        raise AssertionError("no model call expected")


def _fixture_nav(start_rel: str):
    """The real Workday navigator, except that `open` goes to a local fixture page (there is no
    posting to click Apply on) and the tenant is synthetic. Everything the flow later does
    (`choose_entry` aside, which has no dialog to find here) is the real navigator's code."""
    from jobscraper.apply.ats.workday import WorkdayNavigator
    from jobscraper.apply.contracts import Tenant, ValueOrigin

    class FixtureWorkday(WorkdayNavigator):
        name = "wdfixture"
        base = ""
        start = start_rel
        before: dict = {}

        def tenant_from_company(self, job):
            return Tenant("wdfixture", "fixture.example.test", "exampleco", posting_id="REQ-0000")

        def open(self, page, ctx):
            page.goto(f"{self.base}/{self.start}", wait_until="domcontentloaded")
            self.before = page.evaluate(FINAL_JS)
            ctx.log("fixture: opened " + self.start)

        def choose_entry(self, page, ctx):
            return ValueOrigin.RESUME_IMPORT.value

    return FixtureWorkday()


@contextlib.contextmanager
def _registered(nav):
    from jobscraper.apply.ats import REGISTRY
    REGISTRY[nav.name] = nav
    try:
        yield nav
    finally:
        REGISTRY.pop(nav.name, None)


def _session_class():
    """The test Edge session (profile in a temp dir), snapshotting FINAL_JS when a page closes."""
    from apply_flow_support import edge_session_class
    base = edge_session_class()

    class Snapping(base):
        def _snap(self, page):
            if id(page) in self._snapped:
                return
            self._snapped.add(id(page))
            try:
                self.snapshots.append(page.evaluate(FINAL_JS))
            except Exception as exc:
                self.snapshots.append({"error": type(exc).__name__})
    return Snapping


class _Result:
    def __init__(self, w, r, say, nav, sessions, backend):
        self.w, self.r, self.say, self.nav, self.sessions, self.backend = w, r, say, nav, sessions, backend

    @property
    def final(self) -> dict:
        snaps = [s for sess in self.sessions for s in sess.snapshots]
        assert snaps, "no page was snapshotted"
        return snaps[-1]


def _run_fixture(start_rel, backend, *, dry_run=True, resume_text=None, acfg_over=None, jd_text=""):
    """One apply attempt over a local fixture page. None when headless Edge is not available."""
    from apply_flow_support import (Say, add_job, edge_acfg, edge_available, make_world)
    from llm_fill_support import FixtureDir
    from jobscraper import apply_flow
    if not edge_available():
        return None
    w = make_world()
    try:
        _cid, jid = add_job(w.store, key="exampleco", name="Example Employer", provider="wdfixture",
                            slug="exampleco", external_id="REQ-0000", description=jd_text,
                            url="https://fixture.example.test/job/REQ-0000")
        edge_dir = str(w.tmp / "edge-profile")
        cls, sessions, say = _session_class(), [], Say()

        def factory(acfg):
            s = cls(acfg, profile_dir=edge_dir).start()
            sessions.append(s)
            return s
        acfg = dataclasses.replace(edge_acfg(w.cfg.apply, edge_dir, fill="llm", **(acfg_over or {})), step_timeout_s=3)
        nav = _fixture_nav(start_rel)
        orig_text = apply_flow._Run.resume_text
        if resume_text is not None:                 # the grounding corpus (the fake PDF has no text)
            apply_flow._Run.resume_text = lambda self, path: resume_text
        try:
            with FixtureDir(APPLY_FIX) as fx, _registered(nav):
                nav.base = fx.url("").rstrip("/")
                res = apply_flow.run(w.cfg, w.store, [jid], dry_run=dry_run, backend=backend, http=object(),
                                     browser_factory=factory, apply_cfg=acfg, say=say,
                                     evidence_dir=w.tmp / "evidence", now=lambda: NOW)
        finally:
            apply_flow._Run.resume_text = orig_text
        return _Result(w, res[0], say, nav, sessions, backend)
    except BaseException:
        w.close()
        raise


# ------------------------------------------------------------------ stop

@needs(*GATE)
def test_wd_b_stops_after_one_profile_gap_capture_and_touches_nothing():
    """LF §8 step 7 + §11 "Required unknown": the Address Line 2 the profile does not have ->
    one capture (`profile_gap`, target `contact.address_line2`, the page's own label), then
    `failed(unanswerable_required)` with that label; M9/TR-7: the page is exactly as the site put
    it (no input event, same values), Next was never pressed, nothing submitted."""
    from llm_fill_support import FIX, FakeFillBackend
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    fb = FakeFillBackend.from_file(FIX / "wd_b" / "02-my_information" / "reply.json")
    out = _run_fixture("llm_fill/wd_b/02-my_information/page.html", fb,
                       resume_text=(FIX / "resume_sample.txt").read_text(encoding="utf-8"))
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail == "Address Line 2"
        groups = w.store.question_groups()
        assert len(groups) == 1, [g["labels"] for g in groups]
        g = groups[0]
        assert g["labels"] == ["Address Line 2"], "the verbatim label"
        assert g["reason"] == "profile_gap" and g["target_path"] == "contact.address_line2", \
            (g["reason"], g["target_path"])
        assert out.say.text.count("question captured") == 1
        # the page was not touched
        end = out.final
        assert end["inputs"] == 0 and end["next"] == "0" and end["submit"] == "0", end
        assert end["page"] == out.nav.before["page"], "values, ticks, pills and entries unchanged"
        # nothing was decided-and-applied: the decided rows say so, none claims to be on the page
        rows = w.store.answers(r.attempt_id)
        assert rows, "the page's rows are kept for the audit"
        assert not [x for x in rows if x["status"] == "filled"], \
            [(x["field_key"], x["status"]) for x in rows if x["status"] == "filled"]
        assert [x["note"] for x in rows if x["status"] == "skipped"] and \
            all("not applied" in x["note"] for x in rows if x["status"] == "skipped")
        row = w.store.attempt(r.attempt_id)
        assert row["submit_clicked_at"] is None
        fb.assert_no_secrets(_secrets())
    finally:
        w.close()


def _secrets():
    from llm_fill_support import sample_secrets
    return sample_secrets()


# ------------------------------------------------------------------ model_unavailable

@needs(*GATE)
def test_a_failed_warm_up_is_model_unavailable_before_the_browser_opens():
    """LF §13.1 + §11 table: "Ollama not running -> warm-up fails before Edge opens ->
    model_unavailable". `browser_factory` is never called; the posting is never opened; no vault,
    account or answer row; `llm_fill.keep_alive` reaches the warm-up when set (and is None when not)."""
    from apply_flow_support import FakeBrowserFactory, Say, add_job, make_world, page_signals
    from jobscraper import apply_flow
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    from vault_support import memory_keyring
    for keep, seen in (("", None), ("30m", "30m")):
        w = make_world()
        try:
            add_job(w.store, key="exampleco", name="Example Employer", provider="wdfixture",
                    slug="exampleco", external_id="REQ-0000", url="https://fixture.example.test/job/REQ-0000")
            jid = w.store.conn.execute("SELECT job_id FROM jobs").fetchone()[0]
            be, factory, say, nav = _Recorder("Ollama is not running"), FakeBrowserFactory(), Say(), _fixture_nav("x")
            llm = dataclasses.replace(w.cfg.apply.llm_fill, keep_alive=keep)
            acfg = dataclasses.replace(w.cfg.apply, fill="llm", llm_fill=llm, dry_run_hold_s=0, confirm_timeout_s=0)
            opened = []
            nav.open = lambda page, ctx: opened.append(1)
            with _registered(nav), page_signals(), memory_keyring() as mem:
                r = apply_flow.run(w.cfg, w.store, [jid], dry_run=True, backend=be, http=object(),
                                   browser_factory=factory, apply_cfg=acfg, say=say,
                                   evidence_dir=w.tmp / "evidence", now=lambda: NOW)[0]
                assert mem.calls == [], "no vault read or write"
            assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (r.state, r.reason)
            assert "not running" in r.reason_detail
            assert factory.started == 0 and opened == [], "the browser never starts"
            assert be.warms == [seen], (keep, be.warms)
            assert be.completes == 0
            row = w.store.attempt(r.attempt_id)
            assert row["step"] == "planning" and row["submit_clicked_at"] is None
            assert w.store.answers(r.attempt_id) == [] and w.store.accounts() == []
        finally:
            w.close()


@needs(*GATE)
def test_a_page_timeout_names_the_step():
    """LF §11 "Not captured: transport failures": a model call that times out on a page ->
    `failed(model_unavailable)` "timed out on <step>", always before the click; nothing captured
    (the timed-out answers were never decided), nothing typed, Next never pressed."""
    from llm_fill_support import FIX, FakeFillBackend
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    fb = FakeFillBackend(replies=[{"kind": "page", "repeat": True, "raise": "timeout", "match": "FIELDS"}], strict=True)
    out = _run_fixture("llm_fill/wd_a/02-my_information/page.html", fb,
                       resume_text=(FIX / "resume_sample.txt").read_text(encoding="utf-8"))
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail == "timed out on my_information"
        assert w.store.question_groups("all") == [], "transport unknowns are never captured"
        assert "question captured" not in out.say.text
        end = out.final
        assert end["inputs"] == 0 and end["next"] == "0" and end["submit"] == "0", end
        assert end["page"] == out.nav.before["page"]
        assert fb.calls, "the model was asked"
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None
    finally:
        w.close()


# ------------------------------------------------------------------ the loop guard

@needs(*GATE)
def test_a_repeated_step_or_an_empty_non_review_step_is_page_unrecognised():
    """LF §8 "Loop guard": the same step id AND the same field signatures twice without errors ->
    `page_unrecognised`; §11 table: "No fields on a non-review step -> page_unrecognised ("no
    fields on <step>")". Real pages: `stay.html` (Next does nothing, no error shown) and
    `empty.html` (no fields). Neither ends in a click on anything but Next."""
    from llm_fill_support import FakeFillBackend
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    fname = {"|Given Name(s)": {"source": "profile", "ref": "profile:identity.legal_first_name",
                                "value": "Alex", "evidence": ""}}
    fb = FakeFillBackend(replies=[{"kind": "page", "repeat": True, "reply": fname}], strict=True)
    out = _run_fixture("flow_llm/stay.html", fb)
    if out is None:
        return
    try:
        r = out.r
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED, (r.state, r.reason, r.reason_detail)
        assert "shown again" in r.reason_detail and "my_information" in r.reason_detail
        assert out.final["submit"] == "0"
    finally:
        out.w.close()

    fb = FakeFillBackend(replies=[], strict=True)
    out = _run_fixture("flow_llm/empty.html", fb)
    try:
        r = out.r
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail == "no fields on my_information"
        assert fb.calls == [] and out.final["next"] == "0", "nothing asked, Next never pressed"
    finally:
        out.w.close()


# ------------------------------------------------------------------ replay smoke

@needs(*GATE)
def test_replay_wd_a_dry_run_reaches_ready_to_submit():
    """LF §16 Flow: "dry run wd_a -> ready_to_submit". The 7 recorded steps over http.server +
    shim.js, the scripted model (each step's reply.json), the real navigator and pagefill:
    `ready_to_submit` on the Review page, Submit never pressed (data-submit-count=0), one audit
    row per field per step under its page, every prompt free of S values (NF-02)."""
    from llm_fill_support import FIX, FakeFillBackend, steps
    from jobscraper.apply.contracts import AttemptState as S
    calls = []
    for d in steps("wd_a"):
        calls += json.loads((d / "reply.json").read_text(encoding="utf-8"))["calls"]
    fb = FakeFillBackend(replies=calls, strict=True)
    out = _run_fixture("llm_fill/wd_a/01-autofill_with_resume/page.html", fb, dry_run=True,
                       resume_text=(FIX / "resume_sample.txt").read_text(encoding="utf-8"),
                       jd_text=(FIX / "jd_sample.txt").read_text(encoding="utf-8"))
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail, out.say.text[-1200:])
        row = w.store.attempt(r.attempt_id)
        assert row["mode"] == "dry_run" and row["submit_clicked_at"] is None and row["plan_source"] == "page"
        end = out.final
        assert end["submit"] == "0", "a dry run never presses Submit"
        assert end["path"].endswith("/07-review/page.html"), end["path"]
        rows = w.store.answers(r.attempt_id)
        by_step: dict[str, list[dict]] = {}
        for x in rows:
            by_step.setdefault(x["step"], []).append(x)
        # step ids: the progress-bar title slugged, question pages keep their position (M7)
        assert {"my_information", "my_experience", "voluntary_disclosures"} <= set(by_step), sorted(by_step)
        assert len([s for s in by_step if s.startswith("questions_")]) == 2, sorted(by_step)
        keys = [(x["step"], x["field_key"]) for x in rows]
        assert len(keys) == len(set(keys)), "one audit row per field per step"
        assert not [x for x in rows if x["status"] in ("unknown", "ungrounded", "fill_failed")], \
            [(x["field_key"], x["status"], x["note"]) for x in rows if x["status"] in ("unknown", "ungrounded", "fill_failed")]
        assert w.store.question_groups("all") == [], "a clean replay captures nothing"
        fb.assert_no_secrets(_secrets())
    finally:
        w.close()


# ------------------------------------------------------------------ N6b (gated)

@needs(*N6B_GATE)
def test_n6b_the_pre_submit_scan_stops_an_empty_required_field():
    """LF §8 "Before Submit (H7)": `page.scan_required` over the whole form -> any hit ->
    `validation_error`, nothing sent. Written with WP-N6b."""
    raise AssertionError("WP-N6b landed: write the pre-Submit scan oracle (validation_error, no click)")


if WAITING[_W0:]:
    print(f"[test_apply_flow_llm] {len(WAITING[_W0:])} oracle tests wait for WP-N6b: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
