"""Q-90/Q-91 pins: D-176, the refinement of D-171 plus six routed labels (apply_design §7.5 D-176 block and
its oracle table, rows 1-38; row 39 is the existing declaration suites, which run alongside). Written from
the spec, independently of the code. Tier 4 through `declarations.classify` + `answer`, employer "Acme", the
sample profile (every declaration false unless a row stores a value). A Yes/No dropdown unless stated.

Row 32 is written for the Coordinator ruling on Q1 (option A): "disqualified as a director" maps to
`regulatory_disciplinary`, so with the stored value false it answers No.

Gated on `declarations._TIME_FILLER`: the file skips until the D-176 code lands, then must pass.
Each group collects every failing row before it asserts, so one wrong row never hides the others.
Verify: python tests/run_tests.py -k declarations
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_apply_declarations_d170 as D170T  # noqa: E402
import test_apply_declarations_q48 as Q  # noqa: E402
from apply_support import needs  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus as AS, DeclarationLabel as DL, FieldType as FT  # noqa: E402

D176 = ("jobscraper.apply.declarations:_TIME_FILLER",)
UNKNOWN = D170T.UNKNOWN
CHECKBOX = D170T.CHECKBOX
_run = D170T._run


def _t(**decl):
    """kwargs for `_run`/`Q._ans`: a profile with these declaration values stored."""
    return dict(prof=Q._prof(**decl))


def _unknown_true(key_vals, *labels):
    return [(lab, UNKNOWN, _t(**key_vals)) for lab in labels]


def _ended_or_why(label, required, **kw):
    """'' when the field ends (unknown if required, blank_optional if not) and classify says AMBIGUOUS."""
    try:
        lab, a = Q._ans(label, required=required, **kw)
    except Exception as e:
        return f"{label!r}: raised {e!r}"
    D = Q._D()
    want = AS.UNKNOWN if required else AS.BLANK_OPTIONAL
    if a.status is not want or a.value not in (None, "", "false"):
        return f"{label!r} (required={required}): want {want.name}, got {a.status.name} {a.value!r} ({a.note})"
    return ""


def _ambiguous_why(label):
    got = Q._D().classify(Q._n(label), "")
    return "" if got is Q._D().AMBIGUOUS else f"{label!r}: classify() gave {got!r}, expected AMBIGUOUS"


def _checkbox_why(label, required, **kw):
    """Row 7/8: a single checkbox that must not be ticked."""
    try:
        lab, a = Q._ans(label, required=required, type=FT.CHECKBOX, options=(), **kw)
    except Exception as e:
        return f"{label!r}: raised {e!r}"
    want = AS.UNKNOWN if required else AS.BLANK_OPTIONAL
    if a.status is not want:
        return f"{label!r} (required={required}): want {want.name}, got {a.status.name} {a.value!r} ({a.note})"
    if a.value not in (None, "", "false"):
        return f"{label!r}: a value was set: {a.value!r}"
    if required and "checkbox statement not recognised" not in (a.note or ""):
        return f"{label!r}: note {a.note!r} lacks 'checkbox statement not recognised'"
    return ""


# ------------------------------------------------------------ rows 1-6, 10-12: a true value, place and time

PLACE_TIME_TRUE = (
    "Have you been convicted of a crime in Singapore?",                                       # 1
    "Have you been convicted of a crime in the last 12 months?",                              # 2
    "Have you been convicted of a crime in the last 5 years?",                                # 3
    "Have you been convicted of a crime in the past 5 years?",                                # 4
    "Have you been convicted of a crime since you were 18?",                                  # 5
    "Have you been convicted of a criminal offence in Singapore or any other country?",       # 6
)


@needs(*D176)
def test_d176_r01_to_r06_a_place_or_time_qualifier_with_a_true_value_is_unknown():
    _run(_unknown_true(dict(criminal_record=True), *PLACE_TIME_TRUE))


@needs(*D176)
def test_d176_r07_r08_a_single_checkbox_with_a_place_and_a_true_value_is_not_ticked():
    label = "I have been convicted of a crime in Singapore"
    bad = [m for m in (_checkbox_why(label, False, **_t(criminal_record=True)),      # 7
                       _checkbox_why(label, True, **_t(criminal_record=True))) if m]  # 8
    assert not bad, "\n" + "\n".join(bad)


@needs(*D176)
def test_d176_r09_the_flag_is_read_before_the_freedom_inversion():
    _run(_unknown_true(dict(non_compete=True), "Are you free from any non-compete agreement in Singapore?"))


@needs(*D176)
def test_d176_r10_a_time_word_inside_a_lead_in_with_a_true_value_is_unknown():
    _run(_unknown_true(dict(pep=True),
                       "Are you, or have you been in the last 12 months, a politically exposed person?"))


@needs(*D176)
def test_d176_r11_an_agreement_with_a_time_word_and_agreed_true_value_is_unknown():
    _run(_unknown_true(dict(criminal_record=True, bankruptcy=True),
                       "Have you been convicted of an offence or declared bankrupt in the last 5 years?"))


@needs(*D176)
def test_d176_r12_past_is_a_time_word_so_a_true_government_value_is_unknown():
    _run(_unknown_true(dict(government_employment=True),
                       "Have you worked for any government body in the past?"))


# ------------------------------------------------------------ rows 13-17: the false direction is unchanged

@needs(*D176)
def test_d176_r13_the_same_labels_with_every_value_false_answer_no():
    labels = PLACE_TIME_TRUE + ("Are you, or have you been in the last 12 months, a politically exposed person?",
                                "Have you worked for any government body in the past?")
    _run([(lab, "No", {}) for lab in labels])


@needs(*D176)
def test_d176_r14_the_agreement_row_with_every_value_false_answers_no():
    _run([("Have you been convicted of an offence or declared bankrupt in the last 5 years?", "No", {})])


@needs(*D176)
def test_d176_r15_the_freedom_form_with_a_place_and_a_false_value_answers_yes():
    _run([("Are you free from any non-compete agreement in Singapore?", "Yes", _t(non_compete=False))])


@needs(*D176)
def test_d176_r16_a_negative_attestation_checkbox_with_a_place_is_ticked():
    lab, a = Q._ans("I have never been convicted of a crime in Singapore", **CHECKBOX)
    assert lab is not None
    assert a.status is AS.FILLED and a.value == "true", (a.status, a.value, a.note)


@needs(*D176)
def test_d176_r17_control_the_bare_ever_convicted_question_with_a_true_value_answers_yes():
    _run([("Have you ever been convicted of a crime?", "Yes", _t(criminal_record=True))])


# ------------------------------------------------------------ rows 18-24: rule 6b, the possessed subject

@needs(*D176)
def test_d176_r18_to_r21_another_party_in_the_subject_zone_is_unknown():
    _run(_unknown_true(dict(non_compete=False),
                       "Is your previous employer bound by a non-compete?",                  # 18
                       "Are you or is your employer bound by a non-compete?",                # 19
                       "Are you or your employer bound by a non-compete?",                   # 20
                       "Are you or Acme party to any non-compete?"))                         # 21


@needs(*D176)
def test_d176_r22_a_possessed_licence_is_the_applicants_and_answers_no():
    _run([("Has your professional licence ever been revoked or suspended?", "No", {})])


@needs(*D176)
def test_d176_r23_the_q48_f1_label_still_answers_no_by_the_agreement_rule():
    _run([(Q.F1_LABEL, "No", {})])


@needs(*D176)
def test_d176_r24_an_employer_after_the_anchor_is_the_object_and_answers_no():
    _run([("Are you bound by any agreement with your current or former employer that restricts your work?",
           "No", _t(non_compete=False))])


# ------------------------------------------------------------ rows 25-28: LOW-2, tails on other shapes

@needs(*D176)
def test_d176_r25_a_negated_question_with_a_details_tail_is_unknown():
    _run([("Have you not been convicted of a crime? If yes, please provide details.", D170T.UNKNOWN, {})])


@needs(*D176)
def test_d176_r26_an_nda_willingness_question_with_a_tail_is_unknown():
    _run([("Are you willing to sign an NDA? If yes, please provide details.", UNKNOWN,
           _t(willing_to_sign_nda=True))])


@needs(*D176)
def test_d176_r27_an_nda_status_question_with_a_tail_answers_no():
    _run([("Do you have an NDA with a former employer? If yes, please provide details.", "No",
           _t(non_compete=False))])


@needs(*D176)
def test_d176_r28_a_non_yes_no_dropdown_with_a_tail_is_unknown():
    _run([("Have you ever been convicted of a crime? If yes, please provide details.", UNKNOWN,
           dict(options=("Never", "Once", "More than once")))])


# ------------------------------------------------------------ rows 29-32: found guilty, director disqualification

@needs(*D176)
def test_d176_r29_found_guilty_is_criminal_record_false_answers_no():
    _run([("Have you ever been found guilty of a crime?", "No", {})])


@needs(*D176)
def test_d176_r30_found_guilty_with_a_true_value_answers_yes():
    _run([("Have you ever been found guilty of a crime?", "Yes", _t(criminal_record=True))])


@needs(*D176)
def test_d176_r31_control_found_guilty_in_a_court_of_law_still_answers_no():
    _run([("Have you ever been found guilty of a criminal offence in a court of law?", "No", {})])


@needs(*D176)
def test_d176_r32_disqualified_as_a_director_is_regulatory_disciplinary_option_a_answers_no():
    """Coordinator ruling Q1, option A (proposed route), not the unknown fallback."""
    label = "Have you ever been disqualified from acting as a director of a company?"
    _run([(label, "No", {})])
    got = Q._D().classify(Q._n(label), "")
    assert got is DL.REGULATORY, got


# ------------------------------------------------------------ rows 33-36: unclassified on purpose, never tier 5

UNCLASSED = (
    "Are you subject to any court order or injunction?",                                      # 33
    "Have you ever been refused entry into or deported from any country?",                    # 34
    "Have you ever been dismissed or asked to resign from any employment?",                   # 35
    "Are there any outstanding legal proceedings against you?",                               # 36
)


@needs(*D176)
def test_d176_r33_to_r36_classify_is_ambiguous_so_neither_tier_5_nor_lf_l3_sees_it():
    bad = [m for m in map(_ambiguous_why, UNCLASSED) if m]
    assert not bad, "\n" + "\n".join(bad)


@needs(*D176)
def test_d176_r33_to_r36_required_ends_unknown():
    bad = [m for m in (_ended_or_why(lab, True) for lab in UNCLASSED) if m]
    assert not bad, "\n" + "\n".join(bad)


@needs(*D176)
def test_d176_r33_to_r36_optional_ends_blank_optional():
    bad = [m for m in (_ended_or_why(lab, False) for lab in UNCLASSED) if m]
    assert not bad, "\n" + "\n".join(bad)


# ------------------------------------------------------------ rows 37-38: the markers do not widen a compound

@needs(*D176)
def test_d176_r37_an_unclassed_marker_in_a_second_clause_makes_the_label_unsure():
    _run([("Have you previously worked for Acme, or have you ever been deported?", UNKNOWN, {})])


@needs(*D176)
def test_d176_r38_found_guilty_or_dismissed_is_a_compound_and_unknown():
    _run([("Have you ever been found guilty of an offence or dismissed from employment?", UNKNOWN, {})])


# ------------------------------------------------------------ vocabulary sizes ("adding a word needs a pin")

@needs(*D176, "jobscraper.apply.declarations:_OTHER_PARTY")
def test_d176_vocabulary_sizes_match_the_spec():
    from jobscraper.apply import declarations as D
    assert set(D._TIME_FILLER) == {"last", "past", "year", "years", "month", "months", "since"}, D._TIME_FILLER
    assert len(D._STATUS_FILLER) == 58 and not set(D._TIME_FILLER) & set(D._STATUS_FILLER), len(D._STATUS_FILLER)
    assert len(D._PLACE_ANCHORS) == 56, len(D._PLACE_ANCHORS)
    assert set(D._OTHER_PARTY) == {"employer", "employers", "company", "companies", "client", "clients",
                                   "auditor", "auditors", "regulator", "regulators", "authority",
                                   "authorities"}, D._OTHER_PARTY
