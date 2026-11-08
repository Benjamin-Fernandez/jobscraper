"""Q-80 pins: D-164 declaration question shapes (`declarations.question_frame`), D-169b, Q-48 F12/F14
(apply_design §7.5 D-164 oracle table). Tier 4 through `declarations.classify` + `answer`, employer
"Acme", the sample profile (every declaration false, `disability_status: no`). A Yes/No dropdown unless stated.

Verify: python tests/run_tests.py -k declarations
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_apply_declarations_q48 as Q  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT  # noqa: E402

DECLINE = ("Yes", "No", "I prefer not to say")


def _unknown(label, *, type=FT.DROPDOWN, options=Q.YN, prof=None):
    """Required field ends `unknown` (or the label is not a declaration at all); never a filled value."""
    D = Q._D()
    if D.classify(Q._n(label), "") is None:
        return
    _lab, a = Q._ans(label, type=type, options=options, prof=prof)
    assert a.status is AS.UNKNOWN, (label, a.status, a.value, a.note)


# ------------------------------------------------------------ the 8 labels: unknown -> No

LISTED_SHAPES = [
    "Politically exposed person (PEP)?",
    "Criminal record",
    "Bankruptcy",
    "Declaration: Are you a politically exposed person?",
    "Note: Do you have a non-compete?",
    "Please confirm: Are you a PEP?",
    "Please indicate if you have ever been bankrupt",
]


def test_d164_the_listed_shapes_answer_no():
    for label in LISTED_SHAPES:
        _lab, a = Q._ans(label)
        Q._filled(a, "No")


def test_d164_a_noun_phrase_dropdown_works_as_a_radio_too():
    _lab, a = Q._ans("Politically exposed person (PEP)?", type=FT.RADIO)
    Q._filled(a, "No")


def test_d164_criminal_record_or_bankruptcy_is_no_by_the_agreement_rule():
    _lab, a = Q._ans("Criminal record or bankruptcy")
    Q._filled(a, "No")


def test_d164_bare_disability_reads_disability_status():
    for status, want in (("no", "No"), ("yes", "Yes")):
        _lab, a = Q._ans("Disability", prof=Q._prof(disability=status))
        Q._filled(a, want)


def test_d164_bare_disability_decline_takes_the_decline_option():
    _lab, a = Q._ans("Disability", options=DECLINE, prof=Q._prof(disability="decline"))
    Q._filled(a, "I prefer not to say")


def test_d164_bare_disability_decline_without_a_decline_option_is_unknown():
    _unknown("Disability", prof=Q._prof(disability="decline"))


# ------------------------------------------------------------ freedom forms (F12)

def test_d164_free_from_restrictive_covenants_without_a_frame_is_unknown():
    """F12: the D-91 freedom path runs the frame; a bare noun-led label has none."""
    _unknown("Free from any restrictive covenants?")


def test_d164_confirm_you_are_free_from_restrictive_covenants_is_yes():
    _lab, a = Q._ans("Confirm you are free from any restrictive covenants")
    Q._filled(a, "Yes")


# ------------------------------------------------------------ classes C excludes

SHAPE_C_EXCLUDED = [
    "Non-compete agreement?",
    "Confidentiality agreement",
    "Criminal record check",
]


def test_d164_shape_c_excludes_non_compete_nda_objects_and_stray_tokens():
    for label in SHAPE_C_EXCLUDED:
        _unknown(label)


def test_d164_a_noun_phrase_is_not_a_frame_on_text():
    """Gate 1 (TEXT/TYPEAHEAD) drops PREFIX only and never uses shape C."""
    _unknown("Politically exposed person (PEP)?", type=FT.TEXT, options=())
    _unknown("Politically exposed person (PEP)?", type=FT.TYPEAHEAD, options=())


def test_d164_a_noun_phrase_is_not_a_frame_on_a_single_checkbox():
    _unknown("Politically exposed person (PEP)?", type=FT.CHECKBOX, options=())


def test_d164_gate_1_on_text_drops_prefix_but_not_the_lead():
    _lab, a = Q._ans("Declaration: Are you a PEP?", type=FT.TEXT, options=())
    Q._filled(a, "No")
    _unknown("Please indicate if you have ever been bankrupt", type=FT.TEXT, options=())


# ------------------------------------------------------------ PREFIX cap, gate 4

def test_d164_prefix_run_is_capped_at_three_tokens():
    _lab, a = Q._ans("Please kindly note are you a PEP?")
    Q._filled(a, "No")
    _unknown("Please kindly note important are you a PEP?")


def test_d164_the_employer_classes_stay_unknown_whatever_the_shape():
    _unknown("Former employee?")


# ------------------------------------------------------------ D-169b

def test_d169b_a_modal_before_the_lead_still_has_the_freedom_frame():
    _lab, a = Q._ans("Can you confirm you are clear of any conflict of interest?")
    Q._filled(a, "Yes")


def test_d169b_a_modal_before_the_lead_applies_to_status_questions():
    _lab, a = Q._ans("Can you tell us whether you are a PEP?")
    Q._filled(a, "No")


def test_d169b_modal_run_may_carry_please_and_does_not_count_toward_the_prefix_cap():
    _lab, a = Q._ans("Would you please indicate if you have ever been bankrupt")
    Q._filled(a, "No")
    _lab, a = Q._ans("Please kindly note can you confirm you are a PEP?")
    Q._filled(a, "No")


def test_d169b_a_modal_without_a_lead_stays_unknown():
    _unknown("Can you sign a non-compete?")


# ------------------------------------------------------------ F14

def test_f14_locks_has_no_dead_negations_list():
    from jobscraper.apply import declarations, locks
    assert not hasattr(locks, "NEGATIONS")
    assert declarations.NEGATIONS, "declarations.NEGATIONS is the one list"
