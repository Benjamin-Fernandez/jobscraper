"""Q-83 pins: D-171, the refinement of D-170 (apply_design §7.5 D-171 block and its oracle table; review
docs/reviews/Q-82-declarations.md MEDIUM 1-4; the 59-row list is part D of the Q-83 architect handoff).
Written from the spec, independently of the code. Tier 4 through `declarations.classify` + `answer`,
employer "Acme", the sample profile (every declaration false, `disability_status: no` where stated). A
Yes/No dropdown unless stated. Rows are numbered as in the handoff.

Gated on `declarations._strip_detail_tail`: the file skips until the D-171 code lands, then must pass.
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

from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT  # noqa: E402

D171 = ("jobscraper.apply.declarations:_strip_detail_tail",)
UNKNOWN = D170T.UNKNOWN
CHECKBOX = D170T.CHECKBOX
TEXT = dict(type=FT.TEXT, options=())
_run = D170T._run
_unknown_rows = D170T._unknown_rows


def _no_rows(*labels, **kw):
    return [(lab, "No", kw) for lab in labels]


def _checkbox_unticked(label, required=True):
    """'' when a single checkbox statement ends unknown (not ticked), else a one-line reason."""
    try:
        lab, a = Q._ans(label, required=required, **CHECKBOX)
    except Exception as e:
        return f"{label!r}: raised {e!r}"
    if lab is None:
        return f"{label!r}: classify() gave None, expected a declaration that stays unticked"
    if a.status is not AS.UNKNOWN:
        return f"{label!r}: want unknown, got {a.status.name} {a.value!r} ({a.note})"
    if a.value not in (None, "", "false"):
        return f"{label!r}: a value was set: {a.value!r}"
    return ""


def _assert_unticked(*labels):
    bad = [m for m in map(_checkbox_unticked, labels) if m]
    assert not bad, "\n" + "\n".join(bad)


# ------------------------------------------------------------ rows 1-7: the details tail (MEDIUM 2a)

@needs(*D171)
def test_d171_r01_to_r05_a_details_tail_is_dropped_on_a_yes_no_choice():
    _run(_no_rows(
        "Have you ever been convicted of a crime? If yes, please provide details.",            # 1
        "Do you have a criminal record? If yes, please provide details.",                      # 2
        "Have you ever been convicted of a felony? If yes, please explain",                    # 3
        "Are you currently bound by a non-compete agreement? If yes, please specify.",         # 4
        "Have you ever been declared bankrupt? If so, please give details.",                   # 5
    ))


@needs(*D171)
def test_d171_r01_the_tail_is_dropped_on_a_radio_too():
    _run(_no_rows("Have you ever been convicted of a crime? If yes, please provide details.", type=FT.RADIO))


@needs(*D171)
def test_d171_r06_agreement_plus_tail():
    _run(_no_rows("Have you ever been convicted of a criminal offence or declared bankrupt? "
                  "If yes, please provide details below."))


@needs(*D171)
def test_d171_r07_shape_c_sees_the_stripped_tokens():
    _run(_no_rows("Criminal record? If yes, please provide details."))


# ------------------------------------------------------------ rows 8-26: vocabulary, places, subject

@needs(*D171)
def test_d171_r08_r09_pleaded_guilty():
    _run(_no_rows(
        "Have you ever been convicted of, or pleaded guilty to, any criminal offence?",          # 8
        "Have you ever been convicted of a criminal offence or pleaded guilty to one?",          # 9
    ))


@needs(*D171)
def test_d171_r10_to_r12_narrowing_words_keep_a_false_no():
    _run(_no_rows(
        "Have you ever been convicted of a crime (excluding minor traffic offences)?",          # 10
        "Have you ever been convicted of a criminal offence (other than a minor traffic violation)?",  # 11
        "Have you ever been convicted of a criminal offence, other than a minor traffic offence?",     # 12
    ))


@needs(*D171)
def test_d171_r13_r14_months_are_filler():
    _run(_no_rows(
        "Have you ever been convicted of a criminal offence in the last 12 months?",            # 13
        "Are you, or have you been in the last 12 months, a politically exposed person?",       # 14
    ))


@needs(*D171)
def test_d171_r15_current_or_former_government_official():
    _run(_no_rows("Are you a current or former government official?"))


@needs(*D171)
def test_d171_r16_filed_for_bankruptcy():
    _run(_no_rows("Have you ever filed for bankruptcy?", "Have you ever filed for personal bankruptcy?"))


@needs(*D171)
def test_d171_r17_individual_voluntary_arrangement():
    _run(_no_rows("Have you ever been adjudged bankrupt or entered into an individual voluntary arrangement?"))


@needs(*D171)
def test_d171_r18_unspent_convictions_with_a_false_value():
    _run(_no_rows("Do you have any unspent criminal convictions?"))


@needs(*D171)
def test_d171_r19_under_investigation():
    _run(_no_rows("Are you currently under investigation for any criminal offence?"))


@needs(*D171)
def test_d171_r20_to_r22_licence_and_disciplined():
    _run(_no_rows(
        "Has your professional licence ever been revoked or suspended?",                         # 20 (subject: your)
        "Have you ever had a professional licence suspended or revoked?",                        # 21
        "Have you ever been disciplined by any professional regulatory body?",                   # 22
    ))


@needs(*D171)
def test_d171_r23_restricts_your_ability_to_work():
    _run(_no_rows("Are you party to any agreement that restricts your ability to work for Acme?"))


@needs(*D171)
def test_d171_r24_to_r26_a_place_qualifier_after_a_class_noun():
    _run(_no_rows(
        "Have you been convicted of a criminal offence in Singapore or any other country?",      # 24
        "Have you ever been declared bankrupt in any jurisdiction?",                             # 25
        "Are you a politically exposed person in Singapore or elsewhere?",                       # 26 (anchor "person")
    ))


# ------------------------------------------------------------ rows 27-31: the limits of the tail and of narrowing

@needs(*D171)
def test_d171_r27_a_text_field_keeps_the_tail_and_ends_unknown():
    """The box asks for the details, so the tail is never dropped on TEXT (row 1 as TEXT) nor TYPEAHEAD."""
    label = "Have you ever been convicted of a crime? If yes, please provide details."
    _run([(label, UNKNOWN, TEXT), (label, UNKNOWN, dict(type=FT.TYPEAHEAD, options=()))])


@needs(*D171)
def test_d171_r28_r29_a_tail_with_another_object_or_no_verb_stays_in():
    _run(_unknown_rows(
        "Are you a PEP? If yes, please provide your position.",                                   # 28 (object not closed)
        "Have you ever been declared bankrupt? If so, when?",                                     # 29 (no verb)
    ))


@needs(*D171)
def test_d171_r30_narrowing_words_count_only_for_a_false_value():
    prof = dict(prof=Q._prof(criminal_record=True))
    _run([("Have you ever been convicted of a crime (excluding minor traffic offences)?", UNKNOWN, prof),
          ("Do you have any unspent criminal convictions?", UNKNOWN, prof)])


@needs(*D171)
def test_d171_r31_control_a_true_value_without_narrowing_still_answers_yes():
    _run([("Have you ever been convicted of a crime?", "Yes", dict(prof=Q._prof(criminal_record=True)))])


# ------------------------------------------------------------ rows 32-51: location and subject probes, all unknown

@needs(*D171)
def test_d171_r32_to_r39_a_clause_naming_a_place_without_a_class_is_unknown():
    _run(_unknown_rows(
        "Are you a politically exposed person or currently in Singapore?",                        # 32
        "Are you a politically exposed person or currently overseas?",                            # 33
        "Have you been convicted of a crime or been in Singapore for the past year?",             # 34
        "Do you have a criminal record or any status in Singapore?",                              # 35
        "Are you bound by a non-compete or working in Singapore?",                                # 36
        "Do you have a non-compete agreement or a current role in Singapore?",                    # 37
        "Are you a government employee or currently working in Singapore?",                       # 38
        "Have you worked for the government or worked in Singapore?",                             # 39
    ))


@needs(*D171)
def test_d171_r40_disability_alone_gets_no_place_cover():
    _run(_unknown_rows("Do you have a disability or identify as living in Singapore?",
                       prof=Q._prof(disability="no")))


@needs(*D171)
def test_d171_r41_to_r45_a_checkbox_with_a_place_or_status_second_clause_is_not_ticked():
    _assert_unticked(
        "I confirm I am not a PEP and am currently in Singapore",                                 # 41
        "I am not a PEP and I am aware of the status",                                            # 42
        "I have no criminal record and I am in Singapore",                                        # 43
        "I am not bound by a non-compete and I am currently in Singapore",                        # 44
        "I am not subject to any non-compete or working in Singapore",                            # 45
    )


@needs(*D171)
def test_d171_r41_to_r45_an_optional_checkbox_of_that_kind_is_blank():
    bad = []
    for label in ("I confirm I am not a PEP and am currently in Singapore",
                  "I am not a PEP and I am aware of the status",
                  "I have no criminal record and I am in Singapore"):
        lab, a = Q._ans(label, required=False, **CHECKBOX)
        if a.status is not AS.BLANK_OPTIONAL:
            bad.append((label, a.status.name, a.value, a.note))
    assert not bad, bad


@needs(*D171)
def test_d171_r46_to_r48_the_applicant_must_be_the_subject():
    _run(_unknown_rows(
        "Are other people politically exposed persons?",                                          # 46
        "Are any people politically exposed persons?",                                            # 46
        "Are you aware of any politically exposed persons?",                                      # 48 ("aware" is conflict filler only)
    ))
    _run([("Is the person politically exposed?", UNKNOWN, {})], lenient=True)                    # 47


@needs(*D171)
def test_d171_r49_aware_of_a_record_against_the_employer_is_unknown():
    _run(_unknown_rows(
        "Are you aware of any criminal convictions against Acme?",
        "Are you aware of any bankruptcy proceedings against Acme?",
        "Are you aware of the criminal record status of Acme?",
    ))


@needs(*D171)
def test_d171_r50_r51_there_is_and_a_second_subject_are_unknown():
    _run(_unknown_rows(
        "Is there a criminal record?",                                                            # 50
        "Are you or is any other person a PEP?",                                                  # 51 (rule 6 after the cut)
    ))


# ------------------------------------------------------------ rows 52-59: controls and guards

@needs(*D171)
def test_d171_r52_relatives_are_exempt_from_d170_and_d171():
    _run(_no_rows("Do any of your relatives work at Acme?"))


@needs(*D171)
def test_d171_r53_aware_is_conflict_of_interest_filler():
    _run(_no_rows("Are you aware of any conflict of interest with Acme?",
                  "Are you aware of any conflict of interest?"))


@needs(*D171)
def test_d171_r54_left_unknown_on_purpose():
    _run(_unknown_rows("Are you a senior political figure?",
                       "Are you aware of any conflict of interest that may arise from your employment at Acme?"),
         lenient=True)


@needs(*D171)
def test_d171_r55_control_a_clean_attestation_checkbox_is_ticked():
    lab, a = Q._ans("I confirm I am not bound by any restrictive agreement", **CHECKBOX)
    assert a.status is AS.FILLED and a.value == "true", (a.status, a.value, a.note)


@needs(*D171)
def test_d171_r56_the_lead_in_piece_first_still_passes():
    _run(_no_rows("Are you, or have you ever been, a senior government official?"))


@needs(*D171)
def test_d171_r57_the_f1_label_keeps_its_rule_id():
    lab, a = Q._ans(Q.F1_LABEL, required=False)
    Q._filled(a, "No")
    assert a.rule_id == "conflict_audit_independence+non_compete", a.rule_id


@needs(*D171)
def test_d171_r58_guard_every_d164_d169b_d170_row_keeps_its_result():
    """The d170 file's GUARD_ROWS (which mirrors the d164 file) plus its kept rows, run again here."""
    _run(D170T.GUARD_ROWS, lenient=True)
    _run(_no_rows("Have you ever been convicted of a crime?", "Have you ever been convicted of a criminal offence?",
                  "Have you been convicted of an offence or declared bankrupt?",
                  "Have you held public office or worked in the civil service?",
                  "Have you ever worked for the Government (excluding mandatory military service)?",
                  "Have you worked for any government body in the past?",
                  "Are you bound by any agreement such as a non-compete?", "Are you bound by any non-compete?",
                  "Have you been subject to any regulatory or disciplinary action?",
                  "Have you ever been declared bankrupt?",
                  "Let us know if you were a politically exposed person",
                  "Specify if you have a criminal record and the offence",
                  "Do you know anyone who works at Acme?", "Non-compete status",
                  "Please state your bankruptcy status"))
    _run([("Are you unrestricted by any non-compete or non-solicitation obligations?", "Yes", {}),
          ("Are you free from any restrictive covenants?", "Yes", {}),
          ("Are you a person with disability (PWD)?", "No", dict(prof=Q._prof(disability="no")))])
    _run(_unknown_rows("Do you have a criminal record check certificate?", "Criminal record check status",
                       "Do you have a non-compete you'd like us to buy out?",
                       "Are you subject to a non-compete and are you working in Singapore?"))


@needs(*D171)
def test_d171_r59_a_clause_in_singapore_without_a_class_is_unknown():
    _run(_unknown_rows("Are you subject to a non-compete and are you in Singapore?"))


# ------------------------------------------------------------ vocabulary sizes ("adding a word needs a pin")

@needs("jobscraper.apply.declarations:_strip_detail_tail", "jobscraper.apply.declarations:_place_spans")
def test_d171_vocabulary_sizes_match_the_spec():
    from jobscraper.apply import declarations as D
    # D-176 moved the 7 time words out of SHARED (65 -> 58); they live in `_TIME_FILLER` (pinned in the d176 file)
    assert len(D._STATUS_FILLER) == 58, len(D._STATUS_FILLER)
    assert len(D._PLACE_ANCHORS) == 56, len(D._PLACE_ANCHORS)
    assert D._NARROWING_FILLER and sum(len(v) for v in D._NARROWING_FILLER.values()) == 7
    assert not {"singapore", "country", "countries", "jurisdiction", "jurisdictions", "elsewhere", "overseas",
                "anywhere", "aware"} & set(D._STATUS_FILLER)
    assert {"month", "months"} <= set(D._TIME_FILLER) and not {"month", "months"} & set(D._STATUS_FILLER)
