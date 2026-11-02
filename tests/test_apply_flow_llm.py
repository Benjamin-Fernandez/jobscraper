"""WP-T4 flow oracles for the LLM filling loop (LF §8 flow part, §11, §13.1; test plan §6). SKELETON.

Skip-clean until WP-N6a (lane N) lands: gated on `pagefill.fill_page` and the flow's FillServices
builder. The builder's name is ASSUMED (`apply_flow._fill_services`); confirm with lane N at N6a and
change GATE only. Each gated stub fails with "T4 stub" once the gate opens, so the missing bodies
are visible at N6a's Verify; the tester writes them against N6a's real names (the queue's T4 row).

Planned oracles (test plan §6):
  - stop: `wd_b` -> failed(unanswerable_required), detail = the first label, after one
    CapturedQuestion (profile_gap, target_path, verbatim label); no fill or clear after the stop;
    transport unknowns are never captured;
  - model_unavailable: the warm-up fails before `browser_factory` is called (count 0); a page call
    timeout gives "timed out on <step>";
  - flow: the same step twice, or no fields on a non-review step -> page_unrecognised; review
    without the resume's file name -> validation_error; caps and duplicate guards stay green;
  - replay smoke: the 7 `wd_a` steps over http.server + shim.js with the fake model ->
    ready_to_submit, one audit row per field per step, data-submit-count=0, prompts pass
    `assert_no_secrets`.
Verify: python tests/run_tests.py -k apply_flow_llm
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
GATE = ("jobscraper.apply.pagefill:fill_page", "jobscraper.apply_flow:_fill_services")


def test_the_flow_llm_fixtures_are_present():
    """Always runs, so `-k apply_flow_llm` is green before N6a."""
    from llm_fill_support import FIX
    for step in ("01-autofill_with_resume", "02-my_information", "03-my_experience", "04-questions_1",
                 "05-questions_2", "06-voluntary_disclosures", "07-review"):
        for name in ("page.html", "reply.json"):
            assert (FIX / "wd_a" / step / name).is_file(), (step, name)
    assert (FIX / "wd_b" / "02-my_information" / "reply.json").is_file()


def _stub(what: str):
    raise AssertionError(f"T4 stub: {what} (write against WP-N6a's names)")


@needs(*GATE)
def test_wd_b_stops_after_one_profile_gap_capture_and_touches_nothing():
    _stub("wd_b stop -> failed(unanswerable_required), one profile_gap capture, page untouched")


@needs(*GATE)
def test_a_failed_warm_up_is_model_unavailable_before_the_browser_opens():
    _stub("warm-up failure -> model_unavailable, browser_factory count 0")


@needs(*GATE)
def test_a_page_timeout_names_the_step():
    _stub('page call timeout -> "timed out on <step>"')


@needs(*GATE)
def test_a_repeated_step_or_an_empty_non_review_step_is_page_unrecognised():
    _stub("same step twice / no fields on a non-review step -> page_unrecognised")


@needs(*GATE)
def test_replay_wd_a_dry_run_reaches_ready_to_submit():
    _stub("wd_a 7-step replay -> ready_to_submit, audit rows, data-submit-count=0, no secrets in prompts")


if WAITING[_W0:]:
    print(f"[test_apply_flow_llm] {len(WAITING[_W0:])} oracle tests wait for WP-N6a: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
