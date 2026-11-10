"""Q-93 pins (KA-1): three follow-ups of docs/reviews/Q-80-flow-fixes.md, each red on personal
b8329a5 and green once fixed.

  M3  (D-174)  a failed E5 Add stops the attempt `validation_error` even when the section has no
               required field: any `fill_failed` row carrying the E5 "could not be added" note
  L1  (D-175)  a hidden file input is read only if a visible button beside it (or in its
               container) names a picker (attach / upload / browse / choose / select / file /
               resume / CV, text or aria-label) or references the input (aria-controls = its id),
               or a visible label[for] points at it
  P   (pick path) a model that refuses a pick call is reported "model unavailable", a timeout
               "timed out": the real cause reaches the outcome and the attempt's detail

Headless Edge on local pages (an all-optional section stub, inline L1 pages); the model is
scripted. Controls (the behaviour that must NOT change) sit next to each pin so a fix that
just drops the check stays red. Skip-clean without Edge. Verify: python tests/run_tests.py -k apply_q93
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import edge_available  # noqa: E402
from apply_support import needs  # noqa: E402
import test_apply_pagefill as P  # noqa: E402
from test_apply_pagefill_review import ENTRY_REPLY, OPTIONAL_REPLY, SWALLOW, _reply_file, _run  # noqa: E402
from test_apply_flow_n6a import FakeNav, ans, outcome, pf, run, scripted, world  # noqa: E402
from test_apply_q80_review_pins import _CV, _FIELD, ATTACH, SUBMIT, _file_fields  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus, AttemptState as S, ReasonCode as R  # noqa: E402
from jobscraper.apply.pagefill import ENTRY_NOTE_PREFIX, ENTRY_NOTE_TAIL  # noqa: E402

ADD_SEL = '[data-automation-id="add-button"]'


def _through_the_flow(real):
    """`real` (a PageOutcome) goes through the real `apply_flow.page_result` as the first page; a
    clean second page follows, so an attempt that goes on ends in the second step and a missing
    stop shows as "not failed" (not as the "shown again" of a page repeated)."""
    then = outcome("two", [pf("c", "Nationality")])
    w, jid = world()
    try:
        nav = FakeNav()

        def script(n, s):
            if n.step_id(None, None) != "one":
                return then
            return dataclasses.replace(real, step="one")
        with scripted(nav, script):
            r, _f, _s, _m = run(w, jid, nav)
    finally:
        w.close()
    return r


# ------------------------------------------------------------------ M3 (D-174)

E5_NOTE = f"{ENTRY_NOTE_PREFIX}education entry could not be added (no add control){ENTRY_NOTE_TAIL}"


def _optional_row_outcome(note: str):
    """One page with a single OPTIONAL field whose row failed to fill, carrying `note`."""
    a = ans("a", "v", status=AnswerStatus.FILLED, note=note)
    return outcome("one", [pf("a", "School", required=False)], {"a": a}, fill_failed=["a"])


def test_m3_an_optional_row_with_the_e5_note_ends_the_attempt_validation_error():
    """Flow level, no browser: the swallowed Add put the section note on an optional row. The
    attempt must stop `validation_error` and say an entry could not be added (D-174)."""
    r = _through_the_flow(_optional_row_outcome(E5_NOTE))
    assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR, (r.state, r.reason, r.reason_detail)
    assert "could not be added" in r.reason_detail, r.reason_detail


def test_m3_control_an_optional_fill_failed_row_without_the_e5_note_does_not_stop_the_attempt():
    """Today's behaviour for an ordinary optional failure stays: the attempt goes on."""
    r = _through_the_flow(_optional_row_outcome("value not accepted by the page"))
    assert r.reason is not R.VALIDATION_ERROR, (r.state, r.reason, r.reason_detail)
    assert r.state is not S.FAILED, (r.state, r.reason, r.reason_detail)


@needs(*P.FILL)
def test_m3_a_swallowed_add_in_a_section_with_no_required_field_ends_the_attempt():
    """The real outcome of a swallowed Add on an all-optional section (stub q93_entries_optional)
    goes through the real `page_result`."""
    with P._open("stubs/q93_entries_optional.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(SWALLOW, ADD_SEL)
        real, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
    assert real.fields and not any(x.field.required for x in real.fields), "the stub must have no required field"
    section = {x.field.key for x in real.fields}
    noted = {k for k, a in real.answers.items() if "could not be added" in (a.note or "")}
    assert noted & set(real.fill_failed) & section, ("precondition: the E5 note rides on fill_failed rows",
                                                      real.fill_failed, sorted(noted))
    assert not real.unknown_required, real.unknown_required
    r = _through_the_flow(real)
    assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR, (r.state, r.reason, r.reason_detail)
    assert "could not be added" in r.reason_detail, r.reason_detail


# ------------------------------------------------------------------ L1 (D-175)

_NAME = "Resume"
_SIB = f'<form>{_FIELD}<div class="field">%s</div></form>'


def _cases(*bodies: str) -> list[bool]:
    """For each page body: whether a FILE field was read."""
    return [bool(g) for g in _file_fields(*bodies)]


def test_l1_a_cancel_button_or_a_help_button_beside_a_hidden_file_input_is_not_a_file_field():
    """The reviewer's probes: (1) the form holds only the hidden input, a `type=button` Cancel and
    Submit; (2) a `.field` div with the input and a `type=button` Help. Neither button picks a file."""
    if not edge_available():
        return
    cancel_in_form, help_in_field, cancel_in_field, aria_help, in_div, in_nested = _cases(
        f'<form>{_CV}<button type="button">Cancel</button>{SUBMIT}</form>',
        _SIB % f'{_CV}<button type="button">Help</button>',
        _SIB % f'<label>{_NAME}</label>{_CV}<button type="button">Cancel</button>',
        _SIB % f'{_CV}<button type="button" aria-label="Help">?</button>',
        f'<form>{_FIELD}<div>{_CV}<button type="button">Cancel</button></div>{SUBMIT}</form>',
        _SIB % f'<div>{_CV}</div><button type="button">Help</button>')
    assert not cancel_in_form, "L1: a Cancel button in the form exposes the hidden file input"
    assert not help_in_field, "L1: a Help button in a .field div exposes the hidden file input"
    assert not cancel_in_field, "L1: a labelled .field with only a Cancel button exposes the input"
    assert not aria_help, "L1: an aria-label=Help button exposes the hidden file input"
    assert not in_div, "L1: a Cancel button in a plain div exposes the hidden file input"
    assert not in_nested, "L1: a Help button in the container of a wrapped input exposes it"


def test_l1_control_a_button_that_names_a_picker_or_points_at_the_input_is_still_read():
    """Must stay read: the Greenhouse Attach shape, "Select files", "Upload resume", an
    aria-label that says upload, aria-controls = the input id (a bare "Go"), and a visible label[for]."""
    if not edge_available():
        return
    names = ["attach", "select files", "upload resume", "aria-label upload", "aria-controls", "label[for]"]
    got = _cases(
        _SIB % f'<label>{_NAME}</label>{_CV}{ATTACH}',
        _SIB % f'<label>{_NAME}</label>{_CV}<button type="button">Select files</button>',
        _SIB % f'<label>{_NAME}</label>{_CV}<button type="button">Upload resume</button>',
        _SIB % f'<label>{_NAME}</label>{_CV}<button type="button" aria-label="Upload CV">+</button>',
        _SIB % f'<label>{_NAME}</label>{_CV}<button type="button" aria-controls="cv">Go</button>',
        _SIB % f'<label for="cv">Upload resume</label>{_CV}')
    missing = [n for n, ok in zip(names, got) if not ok]
    assert not missing, f"D-175 controls no longer read: {missing}"


# ------------------------------------------------------------------ pick-path cause

def _pick_outcome(raiser: str):
    """`fill_page` on the optional-prompt stub; the page call answers, every pick call raises."""
    calls = [c if c.get("kind") != "pick" else {"kind": "pick", "repeat": True, "match": "", "raise": raiser}
             for c in OPTIONAL_REPLY]
    with P._open("stubs/review_optional_prompt.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return None
        out, _r, _sv, _fb = _run(pg, "questions", _reply_file(Path(tmp), calls))
        return out


@needs(*P.FILL)
def test_pick_the_attempt_detail_for_a_failed_pick_says_model_unavailable_not_timed_out():
    """Through the real `page_result`: the attempt ends `model_unavailable`; a refusing model is
    not reported "timed out", a real timeout still is."""
    for raiser, want, other in (("BackendError", "model unavailable", "timed out"),
                                ("timeout", "timed out", "model unavailable")):
        out = _pick_outcome(raiser)
        if out is None:
            return
        r = _through_the_flow(out)
        assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (raiser, r.state, r.reason, r.reason_detail)
        assert want in r.reason_detail and other not in r.reason_detail, (raiser, r.reason_detail)
