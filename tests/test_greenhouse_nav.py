"""Greenhouse SiteNavigator oracles (Q-35 WP-T4, lane N WP-N3; llm_fill_design §3.3, §9.2;
review M3; amendment: the pre_import snapshot).

  - `choose_entry` fills `ctx.pre_import` (key `form:<html id>`, text per LF §3.1, non-empty
    only) BEFORE `prefill` (the MyGreenhouse click) runs, and returns what `prefill` returned;
    a non-ApplyFailure in `prefill` falls back to "" (the generic fill does everything); an
    ApplyFailure (a page signal) propagates;
  - `step_id` is "form"; `scope` is the generic default "";
  - `precheck` re-raises only POSTING_CLOSED; any other schema failure is logged and the
    attempt goes on.
Fakes only (no browser, no network). Verify: python tests/run_tests.py -k greenhouse_nav
"""
from __future__ import annotations

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


class _Loc:
    def __init__(self, html_id):
        self.html_id = html_id

    def get_attribute(self, name):
        return self.html_id if name == "id" else None


def _adapter(order, shown, *, prefill=lambda: "mygreenhouse"):
    """A GreenhouseAdapter whose page reads are faked; `order` records the calls."""
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    from jobscraper.apply.contracts import FieldType, FormField, FormPlan
    a = GreenhouseAdapter()
    fields = [FormField(key="first_name", label="First Name", type=FieldType.TEXT, required=True),
              FormField(key="phone", label="Phone", type=FieldType.TEXT, required=False),
              FormField(key="skills", label="Skills", type=FieldType.MULTI_CHOICE, required=False),
              FormField(key="consent", label="I agree", type=FieldType.CHECKBOX, required=False),
              FormField(key="token", label="", type=FieldType.HIDDEN, required=False)]
    a._plans[7] = FormPlan(ats="greenhouse", job_id="1", apply_url="https://job-boards.greenhouse.io/x",
                           source="schema", fields=fields)
    ids = {"first_name": "first_name", "phone": "phone", "skills": "", "consent": "consent_1"}

    def read_values(page, ctx, fs):
        order.append(("read_values", [f.key for f in fs]))
        return {f.key: shown.get(f.key, "") for f in fs}

    def run_prefill(page, ctx):
        order.append(("prefill", dict(ctx.pre_import)))
        return prefill()
    a.read_values = read_values
    a.prefill = run_prefill
    a.locator = lambda page, f: _Loc(ids.get(f.key, ""))
    return a


@needs(*NEEDS)
def test_choose_entry_snapshots_the_form_before_the_mygreenhouse_click():
    order, lines = [], []
    shown = {"first_name": "Alex", "phone": "", "skills": ["Python", "SQL"], "consent": "true",
             "token": "abc"}
    a = _adapter(order, shown)
    ctx = _ctx(lines)
    assert a.choose_entry(object(), ctx) == "mygreenhouse"
    assert [o[0] for o in order] == ["read_values", "prefill"], "snapshot first, then the import"
    assert "token" not in order[0][1], "hidden fields are not read"
    want = {"form:first_name": "Alex", "form:skills": "Python, SQL", "form:consent_1": "true"}
    assert order[1][1] == want, "pre_import is complete when prefill runs"
    assert ctx.pre_import == want
    assert not any("Alex" in line or "Python" in line for line in lines), "never logged"


@needs(*NEEDS)
def test_choose_entry_falls_back_on_a_prefill_crash_and_propagates_a_page_signal():
    from jobscraper.apply.contracts import ApplyFailure, ReasonCode

    def boom():
        raise RuntimeError("selector gone")
    order, lines = [], []
    a = _adapter(order, {"first_name": "Alex"}, prefill=boom)
    ctx = _ctx(lines)
    assert a.choose_entry(object(), ctx) == ""
    assert ctx.pre_import == {"form:first_name": "Alex"}
    assert any("mygreenhouse: skipped" in line for line in lines)

    def captcha():
        raise ApplyFailure(ReasonCode.CAPTCHA, "")
    a = _adapter([], {}, prefill=captcha)
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
