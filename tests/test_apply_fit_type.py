"""D-167 pins: `FormField.fit_type` (Q-35 WP-N6a defect D1; architect entry "N6a defect D1, D-167";
llm_fill_design §3.1 "Fit type", §15 D-167).

A TYPEAHEAD that has an offered list (non-empty `options`: a react-select, a combobox, a Workday
prompt) is fitted exactly like a DROPDOWN with those options. A search typeahead (`options == ()`)
stays free text. `CHOICE_TYPES` is unchanged; `fit_type` is a derived property, not a dataclass
field; the memory key stays `f.type.value`.

Groups (the architect's 1-6; the two mutation checks of group 7 were run by hand, see the outbox):
  1 parity with DROPDOWN across every site the delta touched; 2 search typeaheads unchanged;
  3 declaration gate and disability; 4 the Workday "Category > Leaf" fit; 5 memory key;
  6 contract.
Verify: python tests/run_tests.py -k apply_fit_type
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import profile  # noqa: E402

from jobscraper.apply import declarations, facts, questions, resolve  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    CHOICE_TYPES, FieldType, FormField, Option, ResolveContext,
)

DD, TA = FieldType.DROPDOWN, FieldType.TYPEAHEAD
GENDER = ("Male", "Female", "Non-Binary", "I don't wish to answer")
YESNO = ("Yes", "No")
COUNTRIES = ("Singapore", "Malaysia")
YEARS = ("0-1 years", "2-3 years", "4-5 years")
YESNODECLINE = ("Yes", "No", "I don't wish to answer")
DISABILITY = ("Yes, I have a disability", "No, I don't have a disability", "I don't wish to answer")
KINDS = ("Citizen", "PR", "Others")
LEAVES = ("Job Board > LinkedIn", "Job Board > JobStreet", "Company Website > Careers Page",
          "Referral > Employee Referral", "Other")


def _f(ftype: FieldType, label: str, options=(), *, required: bool = True) -> FormField:
    return FormField("f", label, ftype, required, options=tuple(Option(o) for o in options))


def _both(label: str, options):
    return _f(DD, label, options), _f(TA, label, options)


def _rctx(**kw) -> ResolveContext:
    return ResolveContext(profile=profile(), employer_name="Example Employer", ats="greenhouse", **kw)


# ------------------------------------------------------------------ 1 parity with DROPDOWN

def _parity(call, label, options, *, want_fit: bool = True):
    dd, ta = _both(label, options)
    want, got = call(dd), call(ta)
    if want_fit:
        assert want is not None, f"{label}: the DROPDOWN reference must fit"
    assert got == want, f"{label}: TYPEAHEAD with options gives {got!r}, DROPDOWN {want!r}"


def test_g1_fit_decline_enum_bool_text_country_number_and_bool_shaped_match_a_dropdown():
    _parity(resolve.fit_decline, "Gender", GENDER)
    _parity(lambda f: resolve.fit_enum(f, "decline", {}), "Gender", GENDER)
    _parity(lambda f: resolve.fit_enum(f, "male", {}), "Gender", GENDER)
    _parity(lambda f: resolve.fit_bool(f, True), "Do you need sponsorship?", YESNO)
    _parity(lambda f: resolve.fit_bool(f, False), "Do you need sponsorship?", YESNO)
    _parity(lambda f: resolve.fit_text(f, "Singapore"), "Where are you based?", COUNTRIES)
    _parity(lambda f: resolve.fit_country(f, "SG"), "Country", COUNTRIES)
    _parity(lambda f: resolve.fit_number(f, 2), "Years of experience", YEARS)
    _parity(resolve.bool_shaped, "Are you a student?", YESNODECLINE, want_fit=False)
    dd, ta = _both("Are you a student?", YESNODECLINE)
    assert resolve.bool_shaped(dd) and resolve.bool_shaped(ta)


def test_g1_the_saved_answer_kind_choice_and_the_question_kind_match_a_dropdown():
    ans = {"value": None, "picks": ["citizen"], "seen": ["citizen", "pr", "others"]}
    _parity(lambda f: resolve._extra_fit(f, "choice", ans), "What is your visa status?", KINDS)
    dd, ta = _both("What is your visa status?", KINDS)
    assert questions.kind_for(dd) == questions.kind_for(ta) == questions.QuestionKind.CHOICE
    dd, ta = _both("Are you eligible to work here?", YESNO)
    assert questions.kind_for(dd) == questions.kind_for(ta) == questions.QuestionKind.YES_NO


def test_g1_the_memory_tier_answers_a_listed_typeahead_like_a_dropdown():
    def call(f):
        seen = []

        def memory(label_norm, ftype, ats):
            seen.append(ftype)
            return json.dumps("Female")
        a = resolve._memory_answer(f, "gender", _rctx(), memory)
        return (a.value if a else None), a is not None
    dd, ta = _both("Gender", GENDER)
    assert call(dd) == call(ta) == ("Female", True)


# ------------------------------------------------------------------ 2 search typeahead unchanged

def test_g2_a_search_typeahead_without_options_stays_free_text():
    s = _f(TA, "Location (City)")
    assert s.fit_type is TA
    assert resolve.fit_text(s, "Singapore") == ("Singapore", ())
    assert resolve.fit_country(s, "SG") is not None and "Singapore" in resolve.fit_country(s, "SG")[0]
    assert resolve.fit_bool(s, True) == ("Yes", ())
    assert resolve.fit_decline(s) is None
    assert questions.kind_for(s) == questions.QuestionKind.TEXT


# ------------------------------------------------------------------ 3 declarations

def test_g3_the_declaration_gate_accepts_a_listed_typeahead_and_refuses_a_search_one():
    label = "Prior employment with Acme"
    dd, ta = _both(label, YESNO)
    assert declarations._field_gate(dd) == "" and declarations._field_gate(ta) == ""
    search = _f(TA, label)
    assert declarations._field_gate(search) == "not a yes/no question"
    assert declarations._field_gate(_f(FieldType.TEXT, label)) == "not a yes/no question"


def test_g3_the_disability_answer_on_a_listed_typeahead_matches_a_dropdown():
    dd, ta = _both("Do you have a disability?", DISABILITY)
    for value in (True, False, None):
        a, b = declarations._disability_answer(dd, value), declarations._disability_answer(ta, value)
        assert (b.status, b.value) == (a.status, a.value), (value, a, b)
    yes = declarations._disability_answer(ta, True)
    assert yes.value == "Yes, I have a disability" and declarations._disability_answer(ta, None).value == \
        "I don't wish to answer"


# ------------------------------------------------------------------ 4 the Workday leaf fit

def test_g4_the_category_leaf_fit_on_a_prompt_typeahead_matches_a_dropdown():
    from jobscraper.apply import resolve as R
    rules = R.load_rules(Path(__file__).resolve().parents[1] / "config" / "questions.yaml")
    rctx = _rctx()
    dd, ta = _both("How Did You Hear About Us?", LEAVES)
    want = facts._leaf_fit("standing:how_heard", dd, rctx, rules, today="2026-11-03")
    got = facts._leaf_fit("standing:how_heard", ta, rctx, rules, today="2026-11-03")
    assert want is not None, "the DROPDOWN reference must fit a leaf"
    assert got == want, (got, want)


# ------------------------------------------------------------------ 5 memory key

def test_g5_the_memory_key_is_still_the_field_type_not_the_fit_type():
    keys = []

    def memory(label_norm, ftype, ats):
        keys.append(ftype)
        return None
    resolve._memory_answer(_f(TA, "Gender", GENDER), "gender", _rctx(), memory)
    assert keys and set(keys) == {"typeahead"}, keys      # stored rows keep their key


# ------------------------------------------------------------------ 6 contract

def test_g6_fit_type_is_a_derived_property_and_follows_the_options():
    names = [x.name for x in dataclasses.fields(FormField)]
    assert "fit_type" not in names and isinstance(FormField.fit_type, property)
    assert FieldType.TYPEAHEAD not in CHOICE_TYPES, "CHOICE_TYPES is unchanged"
    f = _f(TA, "Gender", GENDER)
    assert f.fit_type is DD and f.type is TA
    assert dataclasses.replace(f, options=()).fit_type is TA
    for t in FieldType:
        if t is not TA:
            assert _f(t, "x", GENDER).fit_type is t, t
