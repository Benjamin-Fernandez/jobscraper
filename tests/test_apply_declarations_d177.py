"""Q-90 review pins: D-177, the amendment of D-176 (review docs/reviews/Q-90-declarations.md MEDIUM-1 and
MEDIUM-2; the Coordinator's ruling). Written from the ruling text, independently of the code. Tier 4 through
`declarations.classify` / `classify_field` + `answer`, employer "Acme", the sample profile (every declaration
false), a Yes/No dropdown unless stated.

MEDIUM-1: "company"/"companies" leave the `regulatory_disciplinary` class filler, so "suspended by a company"
and "disciplinary action by a company" are no longer a plain No, while the director disqualification
phrases (which carry "company director" themselves) still answer No. A driving disqualification is not
`regulatory_disciplinary`.
MEDIUM-2: the UNCLASSED markers depend on the field type. A choice field (dropdown, radio, checkbox, multi
choice) that asks about an event stays AMBIGUOUS; a free-text field, or a choice field that only asks about
experience or availability ("experience with court orders"), is not AMBIGUOUS.

Gate: the D-177 symbol is not known to the tester when this is written, so the file waits on the one change
every D-177 build must make, `company` leaving `_CLASS_FILLER[REGULATORY]`. If the engineer's build keeps that
word out some other way, tell the tester: this gate is then the line to change.
Verify: python tests/run_tests.py -k declarations
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_apply_declarations_d170 as D170T  # noqa: E402
import test_apply_declarations_q48 as Q  # noqa: E402
from apply_support import WAITING  # noqa: E402
from questions_support import ctx_for, field  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus as AS, DeclarationLabel as DL, FieldType as FT  # noqa: E402

UNKNOWN = D170T.UNKNOWN
_run = D170T._run


def _landed() -> bool:
    try:
        from jobscraper.apply import declarations as D
        return "company" not in D._CLASS_FILLER[DL.REGULATORY]
    except Exception:
        return False


def gated(fn):
    if _landed():
        return fn
    WAITING.append((fn.__name__, "declarations:_CLASS_FILLER[REGULATORY] without 'company' (D-177)"))
    return None


YN = ("Yes", "No")


def _classify_field(label, ftype, description="", options=None):
    D = Q._D()
    opts = options or ()
    f = field("q", label, ftype, opts, True, description=description)
    ctx = ctx_for(Q._prof(), employer=Q.EMPLOYER)
    return D, f, ctx, D.classify_field(f, ctx)


# ------------------------------------------------------------ MEDIUM-1: "company" is not regulatory filler

@gated
def test_d177_m1_a_company_actor_makes_the_regulatory_question_unknown():
    _run([("Have you ever been suspended by a company?", UNKNOWN, {}),
          ("Have you ever been subject to disciplinary action by a company?", UNKNOWN, {})])


@gated
def test_d177_m1_a_company_director_disqualification_still_answers_no():
    _run([("Have you ever been disqualified as a company director?", "No", {}),
          ("Have you ever been disqualified from acting as a company director?", "No", {}),
          ("Are you a disqualified director?", "No", {})])    # reconstructed from the ruling's "disqualified director?"
    # D-176 row 32 ("... acting as a director of a company?") is pinned in the d176 file; see the report.


@gated
def test_d177_m1_a_driving_disqualification_is_not_regulatory_and_never_answers_no():
    label = "Have you ever been disqualified from driving?"
    D = Q._D()
    got = D.classify(Q._n(label), "")
    assert got is not DL.REGULATORY, got
    if got is not None and got is not D.AMBIGUOUS:
        _, a = Q._ans(label)
        assert a.status is not AS.FILLED, (got, a.status, a.value, a.note)


@gated
def test_d177_m1_the_regulatory_class_filler_no_longer_holds_company_or_companies():
    from jobscraper.apply import declarations as D
    assert not {"company", "companies"} & set(D._CLASS_FILLER[DL.REGULATORY]), D._CLASS_FILLER[DL.REGULATORY]


# ------------------------------------------------------------ MEDIUM-2: the field type decides

def _not_ambiguous_why(label, ftype):
    try:
        D, f, ctx, got = _classify_field(label, ftype, options=YN if ftype is FT.RADIO else ())
    except Exception as e:
        return f"{label!r} ({ftype.name}): raised {e!r}"
    return f"{label!r} ({ftype.name}): classify_field gave AMBIGUOUS, expected not" if got is D.AMBIGUOUS else ""


def _ambiguous_why(label, ftype):
    try:
        D, f, ctx, got = _classify_field(label, ftype, options=YN if ftype in (FT.RADIO, FT.DROPDOWN) else ())
    except Exception as e:
        return f"{label!r} ({ftype.name}): raised {e!r}"
    if got is not D.AMBIGUOUS:
        return f"{label!r} ({ftype.name}): classify_field gave {got!r}, expected AMBIGUOUS"
    a = D.answer(got, f, ctx)
    if a.status is not AS.UNKNOWN:
        return f"{label!r} ({ftype.name}): want unknown, got {a.status.name} {a.value!r} ({a.note})"
    return ""


@gated
def test_d177_m2_experience_or_availability_wording_is_not_ambiguous():
    bad = [m for m in (
        _not_ambiguous_why("Do you have experience with court orders?", FT.RADIO),
        _not_ambiguous_why("Are you available for litigation roles?", FT.RADIO),
        _not_ambiguous_why("Describe your experience with litigation support", FT.TEXTAREA),
        _not_ambiguous_why("Describe your experience with injunctions", FT.TEXT)) if m]
    assert not bad, "\n" + "\n".join(bad)


@gated
def test_d177_m2_a_choice_question_about_an_event_is_ambiguous_and_ends_unknown():
    bad = [m for m in (
        _ambiguous_why("Are you party to any litigation?", FT.RADIO),
        _ambiguous_why("Are there any outstanding legal proceedings against you?", FT.RADIO),
        _ambiguous_why("Have you been subject to a court order or injunction?", FT.RADIO)) if m]
    assert not bad, "\n" + "\n".join(bad)


@gated
def test_d177_m2_the_event_words_stay_ambiguous_on_choice_fields():
    labels = ("Have you ever been refused entry into or deported from any country?",
              "Have you ever been dismissed or asked to resign from any employment?",
              "Were you terminated for cause by a previous employer?")
    bad = [m for lab in labels for ft in (FT.RADIO, FT.DROPDOWN) if (m := _ambiguous_why(lab, ft))]
    assert not bad, "\n" + "\n".join(bad)


@gated
def test_d177_m2_rows_33_to_36_of_the_d176_table_still_hold_through_classify_field():
    labels = ("Are you subject to any court order or injunction?",
              "Have you ever been refused entry into or deported from any country?",
              "Have you ever been dismissed or asked to resign from any employment?",
              "Are there any outstanding legal proceedings against you?")
    bad = [m for lab in labels if (m := _ambiguous_why(lab, FT.DROPDOWN))]
    assert not bad, "\n" + "\n".join(bad)
