"""Q-94 / Q-46 e, browser half: Workday's Save and Continue that does nothing (tester).

Queue row Q-46 (e): "Workday's first Save and Continue showed no error and did not advance; the second
click landed on an empty next step and raised required errors: the navigator waits for the step id to
change before reading the page and never clicks Next twice on one read".

The page `flow_llm/stay_counted.html` is the real Workday wizard markup whose Next does nothing and
shows no error, and which counts each press in `body.dataset.nextClicks`. Two pins:

  - the real `WorkdayNavigator.next_step`, called once on that page, presses Next exactly once, waits
    out `step_timeout_s` (patched to 1 s) and returns the same step with no errors and no review flag;
  - the real `apply_flow.run` (real navigator, real `fill_page`, scripted model) over the same page
    presses Next exactly once in the whole attempt and ends FAILED(page_unrecognised, "... shown
    again"); nothing is submitted.

Headless Edge on 127.0.0.1, no network, no real model, temp DB, synthetic applicant. A machine without
Edge says so and the pins pass vacuously (the repo's habit). Run on its own when verifying:
`python tests/run_tests.py -k q94_gate_prep_edge` (the full suite skips the Edge tests, see the handover).
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402

GATE = ("jobscraper.apply.pagefill:fill_page", "jobscraper.apply_flow:_fill_services")
NAV = ("jobscraper.apply.ats.workday:NAVIGATOR",)


def test_q94_fixture_is_present_and_counts_next():
    p = Path(__file__).resolve().parent / "fixtures" / "apply" / "flow_llm" / "stay_counted.html"
    text = p.read_text(encoding="utf-8")
    assert "pageFooterNextButton" in text and "nextClicks" in text and "applyFlowPage" in text


@needs(*NAV)
def test_q94_q46e_workday_next_step_presses_next_once_per_call_when_nothing_changes():
    import test_workday_nav as WN
    from jobscraper.apply import browser as B
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    from jobscraper.config import ApplyConfig
    with WN._browser() as (pg, fx):
        if pg is None:
            return
        ctx = WN._ctx(fx.url("workday_nav/job"))
        pg.goto(fx.url("flow_llm/stay_counted.html"))
        assert WN._data(pg, "nextClicks") == "0"
        saved = B.options_for
        B.options_for = lambda page: dataclasses.replace(ApplyConfig(), step_timeout_s=1)
        try:
            res = N.next_step(pg, ctx)
        finally:
            B.options_for = saved
        assert WN._data(pg, "nextClicks") == "1", f"Next pressed {WN._data(pg, 'nextClicks')} times in one call"
        assert res.step == "my_information" and not res.errors and not res.is_review, res
        assert WN._data(pg, "submitCount") in ("", "0")


@needs(*GATE)
def test_q94_q46e_a_silent_next_is_pressed_once_in_the_whole_attempt_and_ends_shown_again():
    import test_apply_flow_llm as L
    from llm_fill_support import FakeFillBackend
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    fname = {"|Given Name(s)": {"source": "profile", "ref": "profile:identity.legal_first_name",
                                "value": "Alex", "evidence": ""}}
    fb = FakeFillBackend(replies=[{"kind": "page", "repeat": True, "reply": fname}], strict=True)
    out = L._run_fixture("flow_llm/stay_counted.html", fb)       # step_timeout_s is 3 s there
    if out is None:
        return
    try:
        r = out.r
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED, (r.state, r.reason, r.reason_detail)
        assert "shown again" in r.reason_detail and "my_information" in r.reason_detail, r.reason_detail
        assert out.final["next"] == "1", f"Next pressed {out.final['next']} times on one unchanged page"
        assert out.final["submit"] == "0"
        assert out.w.store.attempt(r.attempt_id)["submit_clicked_at"] is None
    finally:
        out.w.close()
