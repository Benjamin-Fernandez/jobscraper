"""Greenhouse SiteNavigator oracles (Q-35 WP-T4, lane N WP-N3; llm_fill_design §3.3, §9.2;
review M3; amendment: the pre_import snapshot).

  - `choose_entry` fills `ctx.pre_import` BEFORE `prefill` (the MyGreenhouse click) runs and
    returns what `prefill` returned. Review F5 (lane N 081b338+): the snapshot is read with lane
    R's reader (`page.read_page(..., options=False, step="form")`) and keyed with its
    `page.audit_keys(..., "form")`; text = the shown value (a list joined "; "), non-empty only;
    skipped when MyGreenhouse is off or has no button; a read error leaves it empty and
    `prefill` still runs. These oracles skip-clean (with a note) until the F5 code is on the
    branch; a non-ApplyFailure in `prefill` falls back to ""; an ApplyFailure propagates;
  - `step_id` is "form"; `scope` is the generic default "";
  - `precheck` re-raises only POSTING_CLOSED; any other schema failure is logged and the
    attempt goes on.
Fakes only (no browser, no network). Verify: python tests/run_tests.py -k greenhouse_nav
"""
from __future__ import annotations

import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
GH = "jobscraper.apply.ats.greenhouse"
NEEDS = (f"{GH}:GreenhouseAdapter.choose_entry", f"{GH}:GreenhouseAdapter.precheck",
         f"{GH}:GreenhouseAdapter.step_id")


def test_the_greenhouse_module_imports():
    from jobscraper.apply.ats import greenhouse
    assert greenhouse.GreenhouseAdapter.name == "greenhouse"


def _ctx(lines):
    from jobscraper.apply.contracts import AttemptContext, Tenant
    return AttemptContext(attempt_id=7, job={"url": "https://job-boards.greenhouse.io/exampleco/jobs/1"},
                          tenant=Tenant("greenhouse", "job-boards.greenhouse.io", "exampleco", posting_id="1"),
                          dry_run=True, email="alex.testcase@example.com", resume_path="",
                          log=lines.append, screenshot=lambda p, s: "", deadline=time.monotonic() + 600)


def _f5_landed() -> bool:
    import inspect
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    if "audit_keys" in inspect.getsource(GreenhouseAdapter._snapshot_pre_import):
        return True
    print("  note: the F5 pre_import snapshot (reader keys) is not on this branch yet; F5 oracles not run")
    return False


@contextlib.contextmanager
def _reader(order, fields, keys, *, boom=False):
    """Fake `jobscraper.apply.page.read_page` / `audit_keys` (looked up at call time)."""
    from jobscraper.apply import page as P
    saved = (P.read_page, P.audit_keys)

    def read_page(page, **kw):
        order.append(("read_page", kw))
        if boom:
            raise RuntimeError("the page went away")
        return list(fields)

    def audit_keys(page, fs, step):
        order.append(("audit_keys", step))
        return dict(keys)
    P.read_page, P.audit_keys = read_page, audit_keys
    try:
        yield
    finally:
        P.read_page, P.audit_keys = saved


def _fields():
    from jobscraper.apply.contracts import FieldType as FT, ValueOrigin as VO
    import llm_fill_t2 as T
    fields = [T.pf("r1", "First Name", shown="Alex", origin=VO.SITE_DEFAULT),
              T.pf("r2", "Phone", shown=""),
              T.pf("r3", "Skills", FT.MULTI_CHOICE, shown=["Python", "SQL"], origin=VO.SITE_DEFAULT),
              T.pf("r4", "I agree", FT.CHECKBOX, shown="true", origin=VO.SITE_DEFAULT)]
    keys = {"r1": "form:first_name", "r2": "form:phone", "r3": "form:skills", "r4": "form:consent_1"}
    return fields, keys


def _adapter(order, *, prefill=lambda: "mygreenhouse", button=True):
    """A GreenhouseAdapter with a faked MyGreenhouse button and prefill; `order` records calls."""
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    a = GreenhouseAdapter()
    a._autofill_button = lambda page: object() if button else None

    def run_prefill(page, ctx):
        order.append(("prefill", dict(ctx.pre_import)))
        return prefill()
    a.prefill = run_prefill
    return a


@needs(*NEEDS, "jobscraper.apply.page:audit_keys")
def test_choose_entry_snapshots_the_form_with_the_reader_keys_before_the_click():
    if not _f5_landed():
        return
    order, lines = [], []
    fields, keys = _fields()
    a, ctx = _adapter(order), _ctx(lines)
    with _reader(order, fields, keys):
        assert a.choose_entry(object(), ctx) == "mygreenhouse"
    assert [o[0] for o in order] == ["read_page", "audit_keys", "prefill"], "snapshot first, then the import"
    assert order[0][1].get("options") is False and order[0][1].get("step") == "form"
    assert order[1][1] == "form"
    want = {"form:first_name": "Alex", "form:skills": "Python; SQL", "form:consent_1": "true"}
    assert order[2][1] == want, "pre_import is complete when prefill runs (keys = the reader's audit keys)"
    assert ctx.pre_import == want
    assert not any("Alex" in line or "Python" in line for line in lines), "never logged"


@needs(*NEEDS, "jobscraper.apply.page:audit_keys")
def test_no_snapshot_without_an_import_and_a_read_error_leaves_it_empty():
    import dataclasses
    from jobscraper.apply import browser as B
    if not _f5_landed():
        return
    fields, keys = _fields()
    order: list = []
    a, ctx = _adapter(order, button=False), _ctx([])
    with _reader(order, fields, keys):
        assert a.choose_entry(object(), ctx) == "mygreenhouse"
    assert [o[0] for o in order] == ["prefill"] and ctx.pre_import == {}, "no MyGreenhouse button"
    saved = B.options_for
    B.options_for = lambda page: dataclasses.replace(saved(page), mygreenhouse=False)
    try:
        order = []
        a, ctx = _adapter(order), _ctx([])
        with _reader(order, fields, keys):
            a.choose_entry(object(), ctx)
        assert [o[0] for o in order] == ["prefill"] and ctx.pre_import == {}, "MyGreenhouse off"
    finally:
        B.options_for = saved
    order = []
    a, ctx = _adapter(order), _ctx([])
    with _reader(order, fields, keys, boom=True):
        assert a.choose_entry(object(), ctx) == "mygreenhouse"
    assert order[-1][0] == "prefill" and ctx.pre_import == {}, "best effort: prefill still runs"


@needs(*NEEDS)
def test_choose_entry_falls_back_on_a_prefill_crash_and_propagates_a_page_signal():
    from jobscraper.apply.contracts import ApplyFailure, ReasonCode

    def boom():
        raise RuntimeError("selector gone")
    lines: list[str] = []
    a = _adapter([], prefill=boom, button=False)
    assert a.choose_entry(object(), _ctx(lines)) == ""
    assert any("mygreenhouse: skipped" in line for line in lines)

    def captcha():
        raise ApplyFailure(ReasonCode.CAPTCHA, "")
    a = _adapter([], prefill=captcha, button=False)
    try:
        a.choose_entry(object(), _ctx([]))
    except ApplyFailure as e:
        assert e.reason is ReasonCode.CAPTCHA
    else:
        raise AssertionError("a page signal must stop the attempt")


@needs(*NEEDS)
def test_choose_entry_without_a_plan_still_runs_prefill():
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    a = GreenhouseAdapter()
    a.prefill = lambda page, ctx: ""
    ctx = _ctx([])
    assert a.choose_entry(object(), ctx) == "" and ctx.pre_import == {}


@needs(*NEEDS)
def test_step_id_is_form_and_scope_is_the_generic_default():
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    a = GreenhouseAdapter()
    assert a.step_id(object(), _ctx([])) == "form"
    assert a.scope(object(), _ctx([])) == ""


@needs(*NEEDS)
def test_precheck_reraises_only_posting_closed():
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    from jobscraper.apply.contracts import ApplyFailure, ReasonCode
    for exc, raises in ((ApplyFailure(ReasonCode.POSTING_CLOSED, "404"), True),
                        (ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "schema shape"), False),
                        (ApplyFailure(ReasonCode.ERROR, "http 500"), False),
                        (ValueError("bad json"), False)):
        a = GreenhouseAdapter()

        def plan(ctx, exc=exc):
            raise exc
        a.plan_from_schema = plan
        lines: list[str] = []
        try:
            a.precheck(_ctx(lines))
        except ApplyFailure as e:
            assert raises and e.reason is ReasonCode.POSTING_CLOSED, e
        else:
            assert not raises, f"{exc!r} must stop the attempt"
            assert any("reading the page instead" in line for line in lines), lines
    a = GreenhouseAdapter()
    a.plan_from_schema = lambda ctx: None
    assert a.precheck(_ctx([])) is None


if WAITING[_W0:]:
    print(f"[test_greenhouse_nav] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
