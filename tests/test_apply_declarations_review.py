"""Q-48 review pins (docs/reviews/Q-48-and-lane-M-fixes.md F1-F5, F7, F8, F10; rule of record D-90,
02_status §4). Tier 4 through `declarations.classify` + `answer` (and lock L3 for F2), employer
"Acme", the sample profile. F6 and F9 live in test_llm_fill_guard_table.

PINS: every test marked "pin" fails until the WP-Q48 fix round (eng/Q-48-declarations) lands;
the positives ("still ticked", "still No", "filled by data") pass now and must keep passing.
Verify: python tests/run_tests.py -k declarations
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_apply_declarations_q48 as Q  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus as AS, DeclarationLabel as DL, FieldType as FT  # noqa: E402

YN = ("Yes", "No")


def _not_answered(label, *, type=FT.DROPDOWN, options=YN, required=True, prof=None):
    """Unknown (required) / blank (optional), or not a declaration at all; never a filled value."""
    D = Q._D()
    lab = D.classify(Q._n(label), "")
    if lab is None:
        return None
    _lab, a = Q._ans(label, type=type, options=options, required=required, prof=prof)
    assert a.status is (AS.UNKNOWN if required else AS.BLANK_OPTIONAL), (label, a.status, a.value, a.rule_id)
    return a


def _ticked(label, prof=None):
    _lab, a = Q._ans(label, type=FT.CHECKBOX, options=(), prof=prof)
    return a.status is AS.FILLED and a.value == "true"


# ------------------------------------------------------------------ F1 willingness / consent

WILLING = ("Are you willing to sign a non-disclosure agreement?",
           "Do you agree to sign our confidentiality agreement?",
           "Will you be able to comply with our confidentiality obligations?")


def test_f1_pin_willingness_to_sign_an_nda_is_never_answered_from_non_compete():
    for nc in (False, True):
        prof = Q._prof(non_compete=nc)
        for label in WILLING:
            _not_answered(label, prof=prof)
            _not_answered(label, required=False, prof=prof)


def test_f1_pin_an_acknowledgement_checkbox_is_never_ticked_on_a_stray_no():
    for label in ("I have read the confidentiality agreement and have no questions",
                  "I have no objection to signing the NDA"):
        assert not _ticked(label), label


def test_f1_a_recognised_negative_attestation_is_still_ticked():
    assert _ticked("I am not bound by any non-compete")


# ------------------------------------------------------------------ F2 field type gate

ESSAYS = ("Why do you want to join the public service?", "What draws you to public sector work?",
          "Describe your interest in the civil service", "Describe your experience with public sector agencies",
          "Describe how you handle confidentiality obligations in prior roles")


def test_f2_pin_a_declaration_class_never_types_no_into_an_essay_box():
    for label in ESSAYS:
        _not_answered(label, type=FT.TEXTAREA, options=())
        _not_answered(label, type=FT.TEXTAREA, options=(), required=False)


def test_f2_pin_lock_l3_leaves_an_essay_box_alone():
    import dataclasses
    from jobscraper.apply import locks
    import llm_fill_t2 as T
    ctx = dataclasses.replace(T.rctx(), employer_name=Q.EMPLOYER, employer_aliases=())
    fields = [T.pf(f"e{i}", label, FT.TEXTAREA) for i, label in enumerate(ESSAYS)]
    got = locks.lock_page(fields, ctx, T.rules(), today=T.TODAY, uploaded={})
    filled = {k: a.value for k, a in got.items() if a.status is AS.FILLED}
    assert not filled, filled


def test_f2_a_status_question_in_a_text_box_is_still_no():
    _lab, a = Q._ans("Are you a politically exposed person?", type=FT.TEXT, options=())
    assert a.status is AS.FILLED and a.value == "No", (a.status, a.value)


# ------------------------------------------------------------------ F3 negations the list missed

INVERTED = ("Are you free from any restrictive covenants?",
            "Can you confirm you are clear of any conflict of interest?",
            "Are you unrestricted by any non-compete or non-solicitation obligations?",
            "Are you unencumbered by any NDA?")


def test_f3_pin_an_unlisted_negation_is_unknown_never_inverted():
    for label in INVERTED:
        _not_answered(label)


def test_f3_a_plain_status_question_is_still_no():
    _lab, a = Q._ans("Are you bound by any non-compete?")
    Q._filled(a, "No")


# ------------------------------------------------------------------ F4 this employer only

OTHER_EMPLOYERS = ("Have you worked with government clients?", "Have you worked for a startup before?",
                   "Have you worked in a bank?", "Are you a current employee of a government-linked company?",
                   "Have you worked for the US government?")


def test_f4_pin_employment_questions_that_do_not_name_this_employer_are_not_answered():
    for label in OTHER_EMPLOYERS:
        _not_answered(label)
        _not_answered(label, required=False)


def test_f4_questions_about_this_employer_are_filled_by_data():
    for label in ("Have you previously worked for Acme?", "Have you ever worked for us?"):
        lab, a = Q._ans(label)
        assert lab is DL.PRIOR_EMPLOYMENT, (label, lab)
        Q._filled(a, "No")


# ------------------------------------------------------------------ F5 disability frames

def test_f5_pin_accommodation_and_ability_frames_are_not_the_disability_class():
    D = Q._D()
    for label in ("Do you have a disability that would prevent you from performing the job?",
                  "Do you require any accommodation for a disability during the interview?"):
        assert D.classify(Q._n(label), "") is not DL.DISABILITY, label
        if D.classify(Q._n(label), "") is not None:
            _lab, a = Q._ans(label, prof=Q._prof(disability="yes"))
            assert not (a.status is AS.FILLED and a.value == "Yes"), (label, a.rule_id)


def test_f5_pin_a_decline_to_disclose_checkbox_is_not_ticked_from_a_no():
    assert not _ticked("I do not wish to disclose a disability", prof=Q._prof(disability="no"))


# ------------------------------------------------------------------ F7, F8, F10

def test_f7_pin_a_compound_question_with_an_unclassified_clause_is_unknown():
    _not_answered("Have you been convicted of an offence, or are you able to work night shifts?")


def test_f8_pin_a_note_never_states_the_disability_choice():
    _lab, a = Q._ans("Are you a person with disability (PWD)?")          # sample: decline, no decline option
    assert a.status is AS.UNKNOWN
    assert "declin" not in (a.note or "").lower() and "declin" not in (a.rule_id or "").lower(), a.note


def test_f10_pin_the_ns_exclusion_rule_is_one_implementation():
    from jobscraper.apply import declarations as D, locks
    for label in ("Have you ever worked for the Government (excluding mandatory military service)?",
                  "Have you worked for the government, not including National Service?",
                  "Have you served in the armed forces?"):
        toks = Q._n(label).split()
        assert locks.strip_ns_exclusion(list(toks)) == D._strip_ns_exclusions(list(toks)), label
    own = getattr(locks, "NS_TERMS", None)
    assert own is None or own is getattr(D, "NS_TERMS", object()), "locks keeps its own NS term list"


# ------------------------------------------------------------------ D-90a additions (02_status §4)

def test_d90a_pin_comfort_and_familiarity_questions_are_not_answered():
    for label in ("Are you comfortable signing an NDA?", "Are you familiar with MAS regulations?"):
        _not_answered(label)
        _not_answered(label, required=False)


def test_d90a_pin_objection_and_disclosure_checkboxes_are_never_ticked():
    assert not _ticked("I have no objection to signing the NDA")
    for prof in (Q._prof(), Q._prof(disability="no")):
        assert not _ticked("I do not wish to disclose a disability", prof=prof)


def test_d90a_pin_a_multi_select_declaration_is_unknown():
    _not_answered("Have you been convicted of a crime?", type=FT.MULTI_CHOICE,
                  options=("Yes, a criminal offence", "Yes, a traffic offence", "None of the above"))


def test_d90a_negative_controls_still_answer_from_data():
    lab, a = Q._ans("Do you know anyone who works at Acme?")
    assert lab is DL.RELATIVES, lab
    Q._filled(a, "No")
    _lab, a = Q._ans("Are you aware of any conflict of interest with Acme?")
    Q._filled(a, "No")
