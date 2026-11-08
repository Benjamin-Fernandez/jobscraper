"""Q-82 pins: D-170, one status question per declaration label (apply_design §7.5 D-170 block, its
oracle table and rules 1-5; review docs/reviews/Q-80-declarations.md MEDIUM 1-3). Written from the spec,
independently of the code. Tier 4 through `declarations.classify` + `answer`, employer "Acme", the sample
profile (every declaration false, `disability_status: no` where stated). A Yes/No dropdown unless stated.

Gated on `declarations._one_status_question`: the file skips until the D-170 code lands, then must pass.
Each group collects every failing row before it asserts, so one wrong row never hides the others.
Verify: python tests/run_tests.py -k declarations
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_apply_declarations_q48 as Q  # noqa: E402
from apply_support import needs  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT  # noqa: E402

D170 = ("jobscraper.apply.declarations:_one_status_question",)
UNKNOWN = "unknown"
DECLINE = ("Yes", "No", "I prefer not to say")


def _check(label, want, lenient=False, **kw):
    """'' when the row holds, else a one-line reason. `want` is an option label, or UNKNOWN (required field
    ends `unknown`, never a filled value; the label is still a declaration, so the frame is what refuses)."""
    description = kw.get("description", "")
    try:
        lab, a = Q._ans(label, **kw)
    except Exception as e:  # a crash is a failure of the row, not of the group
        return f"{label!r}: raised {e!r}"
    if want == UNKNOWN:
        if Q._D().classify(Q._n(label), Q._n(description)) is None:
            if lenient:
                return ""
            return f"{label!r}: classify() gave None, expected a declaration that ends unknown"
        if a.status is not AS.UNKNOWN:
            return f"{label!r}: want unknown, got {a.status.name} {a.value!r} ({a.note})"
        return ""
    try:
        Q._filled(a, want)
    except AssertionError as e:
        return f"{label!r}: want {want!r}, got {e}"
    return ""


def _run(rows, lenient=False):
    """rows: (label, want, kwargs). One assertion listing every failing row."""
    bad = [m for m in (_check(lab, want, lenient, **kw) for lab, want, kw in rows) if m]
    assert not bad, "\n" + "\n".join(bad)


def _unknown_rows(*labels, **kw):
    return [(lab, UNKNOWN, kw) for lab in labels]


# ------------------------------------------------------------ rule 1: the modifier rows (MEDIUM 2)

@needs(*D170)
def test_d170_rule1_a_class_phrase_that_only_modifies_another_noun_is_unknown():
    _run(_unknown_rows(
        "Do you have a criminal record check certificate?",
        "Do you have a bankruptcy lawyer?",
        "Is a criminal record check required for your visa?",
        "Are you aware that a criminal record check is mandatory?",
        "Is the criminal record check status satisfactory?",
        "Are you currently a PEP screening officer?",
        "Is your status as a criminal record holder public?",
        "Do you hold any regulatory disciplinary action training certificates?",
        "Indicate whether you have worked in a bankruptcy law firm",
        "Confirm you are a PEP screening analyst",
    ))


@needs(*D170)
def test_d170_rule1_the_prefix_does_not_reopen_the_modifier_rows():
    """"Important:" is a PREFIX; the label left is still not one status question (dropdown and TEXT)."""
    label = "Important: Do you have a criminal record check?"
    _run([(label, UNKNOWN, {}), (label, UNKNOWN, dict(type=FT.TEXT, options=()))])


@needs(*D170)
def test_d170_rule1_a_status_clause_with_extra_words_is_unknown():
    """Was No, "arguable" in the review: "you'd, like, buy, out" are not filler."""
    _run(_unknown_rows("Do you have a non-compete you'd like us to buy out?"))


# ------------------------------------------------------------ rules 1 and 3: the compounds (MEDIUM 1)

@needs(*D170)
def test_d170_rules_1_and_3_compounds_are_unknown():
    _run(_unknown_rows(
        "Do you hold a valid work permit and have you been convicted of a crime?",
        "Confirm you have the right to work and you are a PEP",
        "Can you confirm you are free from any restrictive covenants and able to relocate?",
        "Confirm you are free from any restrictive covenants and eligible to work in Singapore",
        "Are you subject to a non-compete and are you working in Singapore?",
    ))


@needs(*D170)
def test_d170_rule3_a_piece_without_a_class_or_status_run_fails_even_with_listed_words():
    """The second clause holds no class span and no status run, and after D-171 'Singapore' is not filler either, so rules 1 and 3 both refuse it."""
    _run(_unknown_rows("Are you subject to a non-compete and are you in Singapore?"))


# ------------------------------------------------------------ rule 2: the class must be in the label

@needs(*D170)
def test_d170_rule2_a_class_named_only_in_the_description_gives_no_frame():
    """Every token of "Do you have any?" is filler, so only rule 2 stops it (it filled No before D-170)."""
    _run([("Do you have any?", UNKNOWN, dict(description="Criminal record"))])


@needs(*D170)
def test_d170_rule2_control_a_class_named_in_the_label_ignores_the_description():
    _run([("Do you have a criminal record?", "No", dict(description="Criminal record")),
          ("Do you have a criminal record?", "No", {})])


# ------------------------------------------------------------ rule 4: "status" only at the end (MEDIUM 3)

@needs(*D170)
def test_d170_rule4_status_after_a_modifier_noun_has_no_frame():
    _run(_unknown_rows("Criminal record check status"))


@needs(*D170)
def test_d170_rule4_status_ending_a_class_noun_phrase_keeps_its_frame():
    _run([("Non-compete status", "No", {}),
          ("Please state your bankruptcy status", "No", {})])


# ------------------------------------------------------------ rule 5: the single checkbox

CHECKBOX = dict(type=FT.CHECKBOX, options=())


@needs(*D170)
def test_d170_rule5_a_checkbox_with_a_second_clause_is_not_ticked():
    label = "I am not bound by any non-compete and I can relocate"
    lab, a = Q._ans(label, **CHECKBOX)
    assert lab is not None
    assert a.status is AS.UNKNOWN, (a.status, a.value, a.note)
    assert a.value in (None, "", "false"), a.value
    assert "checkbox statement not recognised" in (a.note or ""), a.note


@needs(*D170)
def test_d170_rule5_a_checkbox_with_a_second_clause_is_blank_when_optional():
    lab, a = Q._ans("I am not bound by any non-compete and I can relocate", required=False, **CHECKBOX)
    assert a.status is AS.BLANK_OPTIONAL, (a.status, a.value, a.note)


@needs(*D170)
def test_d170_rule5_a_clean_attestation_checkbox_is_still_ticked():
    lab, a = Q._ans("I confirm I am not bound by any restrictive agreement", **CHECKBOX)
    assert a.status is AS.FILLED and a.value == "true", (a.status, a.value, a.note)


# ------------------------------------------------------------ the kept rows (D-170 oracle, second half)

@needs(*D170)
def test_d170_kept_convicted_questions_answer_no():
    _run([("Have you ever been convicted of a crime?", "No", {}),
          ("Have you ever been convicted of a criminal offence?", "No", {}),
          ("Have you been convicted of an offence or declared bankrupt?", "No", {})])


@needs(*D170)
def test_d170_kept_are_you_or_have_you_ever_been_is_a_lead_in():
    _run([("Are you, or have you ever been, a senior government official?", "No", {})])


@needs(*D170)
def test_d170_kept_government_rows_answer_no():
    _run([("Have you held public office or worked in the civil service?", "No", {}),
          ("Have you ever worked for the Government (excluding mandatory military service)?", "No", {}),
          ("Have you worked for any government body in the past?", "No", {})])


@needs(*D170)
def test_d170_kept_an_employer_reference_covers_the_employer_span():
    _run([("Are you aware of any conflict of interest with Acme?", "No", {})])


@needs(*D170)
def test_d170_kept_the_f1_label_still_answers_no_by_the_agreement_rule():
    lab, a = Q._ans(Q.F1_LABEL, required=False)
    Q._filled(a, "No")
    assert a.rule_id == "conflict_audit_independence+non_compete", a.rule_id


@needs(*D170)
def test_d170_kept_bound_by_and_regulatory_and_bankrupt_rows():
    _run([("Are you bound by any agreement such as a non-compete?", "No", {}),
          ("Are you bound by any non-compete?", "No", {}),
          ("Have you been subject to any regulatory or disciplinary action?", "No", {}),
          ("Have you ever been declared bankrupt?", "No", {})])


@needs(*D170)
def test_d170_kept_freedom_forms_answer_yes():
    _run([("Are you unrestricted by any non-compete or non-solicitation obligations?", "Yes", {}),
          ("Are you free from any restrictive covenants?", "Yes", {})])


@needs(*D170)
def test_d170_kept_lead_rows_with_a_benign_tail_answer_no():
    _run([("Let us know if you were a politically exposed person", "No", {}),
          ("Specify if you have a criminal record and the offence", "No", {})])


@needs(*D170)
def test_d170_kept_person_with_disability_answers_from_disability_status():
    _run([("Are you a person with disability (PWD)?", "No", dict(prof=Q._prof(disability="no")))])


@needs(*D170)
def test_d170_kept_checkbox_attestation_is_ticked():
    lab, a = Q._ans("I confirm I am not bound by any restrictive agreement", **CHECKBOX)
    assert a.status is AS.FILLED and a.value == "true", (a.status, a.value, a.note)


@needs(*D170)
def test_d170_kept_employer_classes_do_not_run_d170():
    """Employer class (relatives): the phrase's object is the employer, D-164 behaviour is unchanged."""
    _run([("Do you know anyone who works at Acme?", "No", {})])


# ------------------------------------------------------------ guard: every D-164 / D-169b row keeps its result

GUARD_ROWS = [
    # the 8 labels, noun phrases (shape C)
    ("Politically exposed person (PEP)?", "No", {}),
    ("Politically exposed person (PEP)?", "No", dict(type=FT.RADIO)),
    ("Criminal record", "No", {}),
    ("Bankruptcy", "No", {}),
    ("Criminal record or bankruptcy", "No", {}),
    ("Disability", "No", dict(prof=Q._prof(disability="no"))),
    ("Disability", "Yes", dict(prof=Q._prof(disability="yes"))),
    ("Disability", "I prefer not to say", dict(options=DECLINE, prof=Q._prof(disability="decline"))),
    ("Disability", UNKNOWN, dict(prof=Q._prof(disability="decline"))),
    # PREFIX, LEAD, MODAL
    ("Declaration: Are you a politically exposed person?", "No", {}),
    ("Note: Do you have a non-compete?", "No", {}),
    ("Please confirm: Are you a PEP?", "No", {}),
    ("Please indicate if you have ever been bankrupt", "No", {}),
    ("Confirm you are free from any restrictive covenants", "Yes", {}),
    ("Can you confirm you are clear of any conflict of interest?", "Yes", {}),
    ("Can you tell us whether you are a PEP?", "No", {}),
    ("Would you please indicate if you have ever been bankrupt", "No", {}),
    ("Please kindly note can you confirm you are a PEP?", "No", {}),
    ("Please kindly note are you a PEP?", "No", {}),
    ("Please kindly note important are you a PEP?", UNKNOWN, {}),
    # no frame / excluded
    ("Can you sign a non-compete?", UNKNOWN, {}),
    ("Free from any restrictive covenants?", UNKNOWN, {}),
    ("Non-compete agreement?", UNKNOWN, {}),
    ("Confidentiality agreement", UNKNOWN, {}),
    ("Criminal record check", UNKNOWN, {}),
    ("Former employee?", UNKNOWN, {}),
    # gate 1 / single checkbox
    ("Politically exposed person (PEP)?", UNKNOWN, dict(type=FT.TEXT, options=())),
    ("Politically exposed person (PEP)?", UNKNOWN, dict(type=FT.TYPEAHEAD, options=())),
    ("Politically exposed person (PEP)?", UNKNOWN, CHECKBOX),
    ("Declaration: Are you a PEP?", "No", dict(type=FT.TEXT, options=())),
    ("Please indicate if you have ever been bankrupt", UNKNOWN, dict(type=FT.TEXT, options=())),
]


@needs(*D170)
def test_d170_guard_every_d164_d169b_row_keeps_its_result():
    # As in the d164 file, an `unknown` row passes when the label is not a declaration at all.
    _run(GUARD_ROWS, lenient=True)


@needs(*D170)
def test_d170_guard_the_d164_pin_file_rows_are_a_subset_of_this_table():
    """A new D-164 pin must be mirrored here: the d164 file's label constants appear in GUARD_ROWS."""
    import test_apply_declarations_d164 as D164
    have = {lab for lab, _w, _k in GUARD_ROWS}
    missing = [lab for lab in (*D164.LISTED_SHAPES, *D164.SHAPE_C_EXCLUDED) if lab not in have]
    assert not missing, missing
