"""Q-121 Amendment A1, closing pass: the three defects found while retargeting the old pins, the
Coordinator's departures R-f (1)-(5) and pin group 28 (the fill cache).

Fakes only (the scripted `ask` of tests/test_always_fill.py), sample profile, no model, no network,
no browser. Expected values come from llm_first_fill_design section 17 and the Coordinator's
rulings, never from what the code does today. A red pin in "DEFECTS" is a defect in the code.
Verify: python tests/run_tests.py -k always_a1_close
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    DELETE, NO_CLASS, YN, FakeAsk, attempt, code_key_of, is_empty, is_stop, is_ticked, is_unticked, labels,
    lie, page, pick_by, profile_with, report, say, shown, stop_is, what, _pf, _profile)

CONFLICT = "Do you declare any conflict of interest?"          # a tentative reader (the D-90 frame gate fails)
CONFIDENT = "Do you have any conflict of interest?"


# ================================================================== DEFECTS (red until fixed)

def test_defect_a_an_invented_grade_is_never_written_whatever_the_label_and_class():
    """Ruling R-d / design 17.2 owner_fact row: a value without a verified basis pointing at THAT fact is
    never written; with the fact in the profile, the profile value is. 'Class of degree' is vetoed today;
    'Grade' and 'Cumulative GPA' with the model's class `owner_fact:grade` write the invented value."""
    p = _profile()                                                   # the sample holds the grade "4.20 / 5.00"
    bad = []
    rows = [(lab, k) for lab in ("Grade", "Cumulative GPA", "Please indicate your grade point average")
            for k in ("owner_fact:grade",)]                          # the MODEL names the class: one key is enough (17.1, R-d)
    rows += [("Class of degree", k) for k in ("owner_fact:grade", "ordinary", NO_CLASS)]   # the code key names it too
    for label, klass in rows:
        for invented in ("First Class", "3.99"):
            res = attempt(_pf("g", label, "TEXT"), FakeAsk(lambda v, k=klass, x=invented: lie(x, k)), p)
            if is_stop(res) or invented in shown(res) or shown(res) != "4.20 / 5.00":
                bad.append((label, klass, invented, "want the profile grade 4.20 / 5.00", what(res)))
    assert not bad, report(bad)


def test_defect_b_a_retention_consent_with_its_key_unset_is_the_models_value_assumed():
    """Design 17.2 T column: 'Unset: ... retention -> the model decides, assumed.' Both keys name the
    class, the model's value is written, and it is flagged assumed (the owner never consented)."""
    label_q = "May we keep your details on file for future roles?"
    label_b = "I agree that you keep my details on file for future roles"
    p = profile_with(consents__data_retention_consent=DELETE)
    bad = []
    for tn, label, opts, said in (("RADIO", label_q, YN, "Yes"), ("RADIO", label_q, YN, "No"),
                                  ("CHECKBOX", label_b, (), "true"), ("CHECKBOX", label_b, (), "false")):
        if tn == "CHECKBOX" and said == "false":
            continue                                                  # a required box left unticked is no answer
        res = attempt(_pf("r", label, tn, options=opts), FakeAsk(lambda v, s=said: say(s, "resume", "", False, "stated")), p)
        if is_stop(res) or not res.assumed or (shown(res) if tn == "RADIO" else res.value) != said:
            bad.append((label, said, what(res)))
    assert not bad, report(bad)


def test_defect_c_a_silent_model_on_a_tentative_declaration_gets_the_confirm_call_then_the_protective_end():
    """Design 17.2, declaration row, protective end: 'the option stating none applies, when the gated
    reader is confident with H known (F0) OR TASK_CONFIRM PICKS IT; else unticked / empty for the site'.
    (17.1 describes the confirm call for a veto; the 17.2 wording is the only place a silent model is
    covered, so this pin follows it. LOW: today no confirm call is made and the field ends empty.)
    The unusable-pick halves are green; the usable-pick half is the one that is red."""
    bad = []
    # U8 + U9: "Do you declare any conflict of interest?" has no reading, so the confirmation's No (the owner's
    # truth) gets ONE meaning call ("no" = it does not state a conflict) before it is written: 2 calls, assumed.
    ask = FakeAsk(pick=pick_by("No", "no"))
    res = attempt(_pf("d", CONFLICT, options=YN), ask)
    if shown(res) != "No" or not res.assumed or len(ask.picks) != 2:
        bad.append(("confirm picks No", what(res), len(ask.picks)))
    ask = FakeAsk(pick=pick_by("No", "yes"))
    res = attempt(_pf("d", CONFLICT, options=YN), ask)
    if shown(res) != "" or len(ask.picks) != 2:
        bad.append(("confirm No, meaning yes: never written", what(res), len(ask.picks)))
    for pick in ("", "Yes"):
        res = attempt(_pf("d", CONFLICT, options=YN), FakeAsk(pick=lambda q, w, o, x=pick: x))
        if shown(res) == "Yes":
            bad.append((f"confirm {pick!r}", "the adverse value written", what(res)))
    assert not bad, report(bad)
