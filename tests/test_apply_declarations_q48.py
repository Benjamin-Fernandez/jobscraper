"""Q-48 / D-87 oracles F1-F20 (architect outbox 2026-11-02 "Q-48, D-87" section F; apply_design
§7.5, llm_fill_design §4 L3/L7). Tier 4 (declarations) with the sample profile (all declarations
false, `government_employment` absent = false, disability "decline") and employer "Acme".

Pins awaiting WP-Q48 (`eng/Q-48-declarations`): gated on `declarations.classify_all` and
`STANDING_DECLARATIONS`, so they skip cleanly until the lane merges and then must pass. F14 (health,
unchanged) and F19 (the pre-D-87 table, unchanged by R1) run now.
Verify: python tests/run_tests.py -k declarations
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402
from questions_support import REAL_RULES, StubBackend, chosen, ctx_for, field, profile, resolve_one, yes_no  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus as AS, AnswerTier, DeclarationLabel as DL, FieldType as FT  # noqa: E402

_W0 = len(WAITING)
Q48 = ("jobscraper.apply.declarations:classify_all", "jobscraper.apply.declarations:STANDING_DECLARATIONS")
YN = ("Yes", "No")
EMPLOYER = "Acme"

F1_LABEL = ("Have you signed or accepted any agreement, or are you otherwise subject to any restrictions, that "
            "1) will restrict the job responsibilities you may perform or 2) prohibit you from working for Acme, "
            "e.g. non-competition agreement, non-disclosure agreement, non-solicitation agreement, stock option or "
            "restricted stock grant agreement with your current or former employers or pursuant to applicable "
            "government conflict of interest restrictions?")


def _D():
    from jobscraper.apply import declarations
    return declarations


def _n(s: str) -> str:
    from jobscraper.apply.plan import norm_label
    return norm_label(s)


def _prof(disability=None, **decl):
    p = profile()
    p.setdefault("declarations", {}).update(decl)
    if disability is not None:
        p.setdefault("us_self_id", {})["disability_status"] = disability
    return p


def _ans(label, *, type=FT.DROPDOWN, options=YN, required=True, description="", prof=None):
    D = _D()
    f = field("q", label, type, options, required, description=description)
    lab = D.classify(_n(label), _n(description))
    return lab, D.answer(lab, f, ctx_for(prof if prof is not None else _prof(), employer=EMPLOYER))


def _filled(a, want):
    assert a.status is AS.FILLED and chosen(a) == (want,), (a.status, a.value, a.note)
    assert a.tier is AnswerTier.DECLARATION and a.sensitive, (a.tier, a.sensitive)


def _ended(a, required):
    assert a.status is (AS.UNKNOWN if required else AS.BLANK_OPTIONAL), (a.status, a.value, a.note)
    assert not a.fills if hasattr(a, "fills") else a.value is None


# ------------------------------------------------------------------ run now

def test_f14_a_health_question_is_unchanged():
    label = "Do you have any medical condition we should know about?"
    _lab, a = _ans(label, options=("Yes", "No", "Prefer not to say"))
    assert a.status is AS.FILLED and chosen(a) == ("Prefer not to say",), (a.status, a.note)
    _lab, a = _ans(label, options=("Yes", "No", "Prefer not to say"), required=False)
    _ended(a, False)


def test_f19_the_pre_d87_classifier_table_is_unchanged():
    D = _D()
    cases = {
        "Are you a politically exposed person (PEP)?": DL.PEP,
        "Do you hold shares in this company?": DL.SHAREHOLDING,
        "Do you have any relatives working at the company?": DL.RELATIVES,
        "Have you ever been convicted of a crime?": DL.CRIMINAL_RECORD,
        "Have you previously worked for us?": DL.PRIOR_EMPLOYMENT,
        "Have you previously applied to this company?": DL.PREVIOUSLY_APPLIED,
        "Are you bound by any agreement such as a non-compete?": DL.NON_COMPETE,
        "What is your favourite programming language?": None,
    }
    for label, want in cases.items():
        assert D.classify(_n(label), "") == want, label
    assert D.classify(_n("Please declare anything else we should know"), "") is D.AMBIGUOUS
    assert D.classify(_n("Have you been convicted of an offence or declared bankrupt?"), "") is D.AMBIGUOUS


# ------------------------------------------------------------------ agreement (A4), checkboxes (A5), L7 (A6)

@needs(*Q48)
def test_f1_two_standing_classes_that_agree_answer_no():
    D = _D()
    assert D.classify(_n(F1_LABEL), "") is D.AMBIGUOUS
    assert D.classify_all(_n(F1_LABEL), "") == (frozenset({DL.NON_COMPETE, DL.CONFLICT_AUDIT_INDEPENDENCE}), False)
    _lab, a = _ans(F1_LABEL, required=False)
    _filled(a, "No")
    assert a.rule_id == "conflict_audit_independence+non_compete", a.rule_id
    assert a.source.endswith("conflict_audit_independence+non_compete"), a.source


@needs(*Q48)
def test_f2_two_classes_that_disagree_end_the_field():
    prof = _prof(conflict_audit_independence=True)
    _lab, a = _ans(F1_LABEL, required=False, prof=prof)
    _ended(a, False)
    _lab, a = _ans(F1_LABEL, required=True, prof=prof)
    _ended(a, True)


@needs(*Q48)
def test_f15_f16_a_checkbox_is_single_class_only():
    _lab, a = _ans("I confirm I am not bound by any restrictive agreement", type=FT.CHECKBOX, options=())
    assert a.status is AS.FILLED and a.value == "true", (a.status, a.value, a.note)
    _lab, a = _ans("I confirm I have no conflict of interest and am not bound by any non-compete",
                   type=FT.CHECKBOX, options=())
    _ended(a, True)


@needs(*Q48)
def test_f17_a_negated_yes_no_is_unknown_on_both_paths():
    # D-91 (apply_design §7.5 gate 3): "free of/from" is now a freedom form that answers the inverted value;
    # "without" is still an unrecognised negation and ends unknown on both paths.
    label = "Are you without any non-compete agreement?"
    _lab, a = _ans(label)
    _ended(a, True)
    spy = StubBackend([{"choice": 0, "evidence": "x"}] * 4)
    a = resolve_one(yes_no("q", label), _prof(), REAL_RULES, backend=spy, employer=EMPLOYER)
    assert a.status is AS.UNKNOWN and spy.calls == [], (a.status, a.note, len(spy.calls))


# ------------------------------------------------------------------ government_employment (B2)

@needs(*Q48)
def test_f3_f4_government_service_excluding_ns_is_government_employment():
    D = _D()
    for label in ("Have you ever worked for the Government (excluding mandatory military service)?",
                  "Have you ever worked for the government, not including National Service?"):
        lab, a = _ans(label)
        assert lab is DL.GOVERNMENT_EMPLOYMENT, (label, lab)
        _filled(a, "No")
        assert a.rule_id == "government_employment", a.rule_id
    assert D.is_negated(_n("Have you ever worked for the government, not including National Service?")) is False


@needs(*Q48, "jobscraper.apply.locks:lock_page")
def test_f3_through_lock_l3_the_basis_is_government_employment():
    from jobscraper.apply import locks
    import llm_fill_t2 as T
    pf = T.pf("g", "Have you ever worked for the Government (excluding mandatory military service)?", FT.RADIO,
              options=YN)
    ctx = dataclasses.replace(T.rctx(), employer_name=EMPLOYER, employer_aliases=())
    a = locks.lock_page([pf], ctx, T.rules(), today=T.TODAY, uploaded={}).get("g")
    assert a is not None and a.status is AS.FILLED and a.value == "No", a
    assert "government_employment" in f"{a.source} {a.rule_id}" and "prior_employment" not in a.source


@needs(*Q48)
def test_f5_to_f7_military_and_government_linked_questions():
    D = _D()
    assert D.classify(_n("Have you served in the armed forces?"), "") is None, "not this lock (L5 / ns_status)"
    lab, a = _ans("Have you ever been employed by the government or served in the military?")
    assert lab is D.AMBIGUOUS
    _ended(a, True)
    assert D.classify(_n("Have you ever worked for a government-linked company?"), "") is D.AMBIGUOUS


@needs(*Q48)
def test_f8_f9_pep_and_civil_service():
    label = "Are you, or have you ever been, a senior government official?"
    for prof in (_prof(), _prof(government_employment=True)):
        lab, a = _ans(label, prof=prof)
        assert lab is DL.PEP, lab
        _filled(a, "No")
    both = "Have you held public office or worked in the civil service?"
    _lab, a = _ans(both)
    _filled(a, "No")
    _lab, a = _ans(both, prof=_prof(pep=True))
    _ended(a, True)


@needs(*Q48)
def test_f18_this_employer_or_the_government_stays_ambiguous():
    lab, a = _ans("Have you previously worked for us or any government agency?")
    assert lab is _D().AMBIGUOUS
    _ended(a, True)


D89_GOVERNMENT = (
    "Have you worked for the government?",
    "Have you previously worked for the government?",
    "Are you currently employed by the government?",
    "Do you currently work for the government?",
    "Have you previously been employed by a government agency?",
    "Have you worked for any government body in the past?",
)


@needs(*Q48)
def test_d89_plain_government_questions_are_government_employment_and_answer_no():
    D = _D()
    for label in D89_GOVERNMENT:
        lab, a = _ans(label)
        assert lab is DL.GOVERNMENT_EMPLOYMENT, (label, lab)
        _filled(a, "No")
        assert a.rule_id == "government_employment", (label, a.rule_id)
    assert D.classify(_n("Have you worked for Acme before?"), "") is DL.PRIOR_EMPLOYMENT
    assert D.classify(_n("Have you previously worked for us or any government agency?"), "") is D.AMBIGUOUS
    for label in ("Have you served in the armed forces or done national service?",
                  "Have you served in the military, including National Service?"):
        classes, _unsure = D.classify_all(_n(label), "")
        assert DL.GOVERNMENT_EMPLOYMENT not in classes, (label, classes)


# ------------------------------------------------------------------ disability (B3)

@needs(*Q48)
def test_f10_a_pwd_question_reads_disability_status():
    label = "Are you a person with disability (PWD)?"
    lab, a = _ans(label, prof=_prof(disability="no"))
    assert lab is DL.DISABILITY, lab
    _filled(a, "No")
    _lab, a = _ans(label, options=("Yes", "No", "Prefer not to say"))          # sample: decline
    assert a.status is AS.FILLED and chosen(a) == ("Prefer not to say",), (a.status, a.note)
    _lab, a = _ans(label)
    _ended(a, True)
    _lab, a = _ans(label, required=False)
    _ended(a, False)


@needs(*Q48)
def test_f11_an_eeo_disability_list_takes_the_no_option():
    opts = ("Yes, I have a disability (or previously had a disability)",
            "No, I do not have a disability and have not had one in the past", "I do not want to answer")
    lab, a = _ans("Disability status", options=opts, prof=_prof(disability="no"))
    assert lab is DL.DISABILITY, lab
    _filled(a, opts[1])


@needs(*Q48)
def test_f12_f13_disability_is_matched_on_the_label_only_and_never_mixed():
    D = _D()
    desc = "We are an equal opportunity employer and welcome applicants with a disability."
    classes, _unsure = D.classify_all(_n("Gender"), _n(desc))
    assert DL.DISABILITY not in classes
    assert D.classify(_n("Gender"), _n(desc)) is not DL.DISABILITY
    label = "Do you have any disability or medical condition that may affect your work?"
    lab, a = _ans(label, required=False, prof=_prof(disability="no"))
    assert lab is D.AMBIGUOUS
    _ended(a, False)
    _lab, a = _ans(label, prof=_prof(disability="no"))
    _ended(a, True)


# ------------------------------------------------------------------ D-79 synonyms (A8)

@needs(*Q48)
def test_f20_normalise_reads_na_and_nil_as_false_and_none_as_no_disability():
    from jobscraper import applicant as A
    D = _D()
    for raw in ("NA", "nil"):
        n = A.normalise(_prof(government_employment=raw))
        assert n["declarations"]["government_employment"] is False, raw
    missing = _prof()
    missing["declarations"].pop("government_employment", None)
    assert D.truth(DL.GOVERNMENT_EMPLOYMENT, A.normalise(missing), EMPLOYER) is False
    assert A.normalise(_prof(disability="none"))["us_self_id"]["disability_status"] == "no"


if WAITING[_W0:]:
    print(f"[test_apply_declarations_q48] {len(WAITING[_W0:])} oracle tests wait for WP-Q48: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
