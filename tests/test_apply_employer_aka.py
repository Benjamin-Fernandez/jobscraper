"""Q-125 pins: `experience[].also_known_as`, the other names of a past employer.

Why it matters: the owner's install submits with no review step, so "Have you worked for us before?"
is a statement on a submitted application. D-210 (company_match: a name matches only when equal or
differing by generic words) stopped false Yes answers but left a real affiliate under another name
answered "No, never worked here", with no way to correct it. The owner can now list the other names
of an employer; the readers (`declarations.prior_employment` / `current_employment`, so `truth`,
`answer`, the `PREVIOUS_WORKER` canonical in the resolver and the standing facts worked_here /
current_employee_here) match a posting against the entry's employer AND each other name.

What is pinned (spec: comms/outbox/software-engineer.md, Q-125 entry):
  * the truth table, prior and current, with and without the field; no end date = current;
  * every other name goes through the SAME rule as the employer (an alias "Example" does not make
    "Example Logistics" match; generic words, "and" / "&" and accents fold), and the posting's own
    aliases still work alongside;
  * a wrong-typed value that skipped validation is ignored and never raises (a false Yes from
    reading a bare string letter by letter would be a false statement on a real form);
  * validation: one error per bad shape at `experience[i].also_known_as`, never repeating the value;
  * the end-to-end answers (tier-4 declaration, the resolver's canonical, the standing facts);
  * the form ships the sub-field (`list_text`, "Also known as") and a resume refresh keeps it.

Only made-up names (Northwind, NW Bank, Sample Analytics, Example Co). A dummy profile built in the
test; no network, no model, no server, no file under data/.
Verify: python tests/run_tests.py -k employer_aka
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import REAL_RULES, chosen, ctx_for, field, profile, resolve_one  # noqa: E402
from test_q44_refresh import (  # noqa: E402
    TEMPLATE, _exp, _plan, _prop_exp, _props,
)

from jobscraper import applicant as A  # noqa: E402
from jobscraper.apply import declarations as D, facts as F  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus as AS, Canonical, FieldType as FT,
)

T, X = True, False
L = D.DeclarationLabel


def _jobs(*entries):
    return {"experience": list(entries)}


def _entry(employer="Sample Analytics", aka="__absent__", end="2023-08", **kw):
    e = {"employer": employer, "title": "Analyst", "start": "2022-06", **kw}
    if end != "__absent__":
        e["end"] = end
    if aka != "__absent__":
        e["also_known_as"] = aka
    return e


def _both(employer, aliases, p):
    return D.prior_employment(p, employer, aliases), D.current_employment(p, employer, aliases)


# ------------------------------------------------------------------ the truth table

def test_the_truth_table_with_and_without_the_field():
    NP = "Northwind Platforms Inc"
    rows = [
        # entry employer, aka, end, posting, posting aliases, prior, current
        (NP, "__absent__", "2023-08", "Northwind", (), X, X),           # without the field: D-210 says No
        (NP, None, "2023-08", "Northwind", (), X, X),
        (NP, [], "2023-08", "Northwind", (), X, X),
        (NP, ["Northwind"], "2023-08", "Northwind", (), T, X),          # with it: Yes, but it ended
        (NP, ["Northwind"], None, "Northwind", (), T, T),               # no end date (null): current
        (NP, ["Northwind"], "__absent__", "Northwind", (), T, T),       # no end key: current
        (NP, ["Northwind"], "", "Northwind", (), T, T),                 # end "": current
        (NP, ["Northwind"], "2023-08", "Northwind Holdings Ltd", (), T, X),
        (NP, ["Northwind"], "2023-08", "Northwind Music", (), X, X),
        ("Sample Analytics", ["NW Bank"], "2023-08", "NW Bank Ltd", (), T, X),
        ("Sample Analytics", ["NW Bank"], None, "NW Bank Ltd", (), T, T),
        ("Sample Analytics", ["NW Bank"], None, "NW Logistics", (), X, X),
        ("Sample Analytics", ["NW Bank"], None, "Sample Analytics", (), T, T),   # the employer still matches
        ("Sample Analytics", ["NW Bank", "Northwind"], None, "Northwind", (), T, T),   # any of several
        ("Sample Analytics", ["NW Bank"], None, "Unrelated Co", (), X, X),
    ]
    bad = []
    for emp, aka, end, posting, aliases, prior, cur in rows:
        p = _jobs(_entry(emp, aka, end))
        got = _both(posting, aliases, p)
        if got != (prior, cur):
            bad.append(f"{emp!r} aka={aka!r} end={end!r} vs {posting!r}: got {got}, want {(prior, cur)}")
    assert not bad, "\n".join(bad)


def test_an_entry_names_only_count_for_that_entry_end_date():
    """The aka of an ENDED entry must not make a posting 'current' because another entry is open."""
    p = _jobs(_entry("Sample Analytics", ["Northwind"], end="2023-08"),
              _entry("Example Co", None, end=None))
    assert _both("Northwind", (), p) == (T, X)
    assert _both("Example Co", (), p) == (T, T)


# ------------------------------------------------------------------ every name goes through D-210

def test_an_other_name_is_matched_by_the_same_rule_not_by_prefix():
    """The old any-prefix rule made 'Example' match 'Example Logistics': a false 'worked here'."""
    p = _jobs(_entry("Sample Analytics", ["Example"]))
    assert _both("Example Logistics", (), p) == (X, X)
    assert _both("Example Foods", (), p) == (X, X)
    assert _both("Example", (), p) == (T, X)                     # equal: a match
    p2 = _jobs(_entry("Sample Analytics", ["Example Logistics"]))
    assert D.prior_employment(p2, "Example", ()) is False        # and the other direction
    assert D.prior_employment(p2, "Example Logistics Pte Ltd", ()) is True


def test_an_other_name_equal_or_differing_by_generic_words_matches():
    rows = [("Northwind", "Northwind", T), ("Northwind Holdings Ltd", "Northwind", T),
            ("Northwind", "Northwind Technologies Pte Ltd", T), ("northwind", "NORTHWIND", T),
            ("Northwind Financial", "Northwind", X),             # "financial" is not generic (F6)
            ("Northwind", "Northwind Music", X)]
    bad = []
    for aka, posting, want in rows:
        got = D.prior_employment(_jobs(_entry("Sample Analytics", [aka])), posting, ())
        if got is not want:
            bad.append(f"aka={aka!r} posting={posting!r}: got {got}, want {want}")
    assert not bad, "\n".join(bad)


def test_an_other_name_folds_and_ampersand_and_accents():
    p = _jobs(_entry("Sample Analytics", ["Smith & Wong", "Café Nord"]))
    assert D.prior_employment(p, "Smith and Wong Ltd", ()) is True
    assert D.prior_employment(p, "Smith & Wong", ()) is True
    assert D.prior_employment(p, "Cafe Nord", ()) is True
    p = _jobs(_entry("Sample Analytics", ["Smith and Wong", "Cafe Nord"]))
    assert D.prior_employment(p, "Smith & Wong Pte Ltd", ()) is True
    assert D.prior_employment(p, "Café Nord", ()) is True
    assert D.prior_employment(p, "Smith & Chan", ()) is False


def test_a_one_or_two_letter_other_name_matches_only_an_equal_name():
    p = _jobs(_entry("Sample Analytics", ["NW"], end=None))
    assert _both("NW", (), p) == (T, T)
    assert _both("NW Bank", (), p) == (X, X)                     # not a prefix licence (D-210)


def test_the_postings_own_aliases_work_with_the_entry_names():
    p = _jobs(_entry("Example Co", ["NW Bank"], end=None))
    assert _both("Zeta", ("NW Bank Ltd",), p) == (T, T)          # alias vs the other name
    assert _both("Zeta", ("Example Co",), p) == (T, T)           # alias vs the employer, as before
    assert _both("Zeta", ("Example Co Pte Ltd", "Other"), p) == (T, T)
    assert _both("Zeta", ("Example Music",), p) == (X, X)        # an alias goes through the rule too
    assert _both("Zeta", ("", "Unrelated"), p) == (X, X)


# ------------------------------------------------------------------ junk never raises, never matches

def test_a_wrong_typed_value_is_ignored_and_never_raises():
    junk = ["Northwind",                  # a bare string is not read as a name or letter by letter
            5, 1.5, True, {"a": "Northwind"}, {"Northwind": 1}, (),
            [None], [5], [None, 5, 2.5, ["Northwind"], {"x": "Northwind"}], [[]], [""], ["  "], {}]
    for v in junk:
        p = _jobs(_entry("Sample Analytics", v, end=None))
        for posting, aliases in (("Northwind", ()), ("N", ()), ("", ()), ("", ("",)), ("Sample Analytics", ())):
            got = _both(posting, aliases, p)               # must not raise
            want = (T, T) if posting == "Sample Analytics" else (X, X)
            assert got == want, (v, posting, got)
    # names() itself: only the employer, and only strings from a list
    assert D.entry_employer_names(_entry("Sample Analytics", "Northwind")) == ("Sample Analytics",)
    assert D.entry_employer_names(_entry("Sample Analytics", [None, 5, " Northwind ", ""])) == \
        ("Sample Analytics", "Northwind")
    assert D.entry_employer_names("not an entry") == () and D.entry_employer_names(None) == ()


def test_a_junk_item_among_good_names_does_not_hide_the_good_ones_or_match_everything():
    p = _jobs(_entry("Sample Analytics", [None, "", "Northwind"], end=None))
    assert _both("Northwind", (), p) == (T, T)
    assert _both("Anything Else", (), p) == (X, X)
    assert _both("", ("",), p) == (X, X)


# ------------------------------------------------------------------ validation

def _aka_errors(value, *, present=True):
    p = profile()
    e = copy.deepcopy(p["experience"][0])
    e.pop("also_known_as", None)
    if present:
        e["also_known_as"] = value
    p["experience"][0] = e
    base = {(x.path, x.message) for x in A.validate(profile())}
    return [x for x in A.validate(p) if (x.path, x.message) not in base]


def test_every_invalid_shape_gives_exactly_one_error_at_the_path_without_echoing_the_value():
    secret = "ZQX-Secret-Employer-7731"
    long_name = secret + "x" * 80
    bad = {
        "a string": secret,
        "a number": 42,
        "a mapping": {"name": secret},
        "a blank item": ["Northwind", "  "],
        "an empty-string item": [""],
        "a None item": [secret, None],
        "a number item": [secret, 5],
        "a nested list": [[secret]],
        "11 names": [f"{secret} {i}" for i in range(11)],
        "81 characters": [long_name],
    }
    for name, v in bad.items():
        errs = _aka_errors(v)
        assert len(errs) == 1, (name, errs)
        assert errs[0].path == "experience[0].also_known_as", (name, errs[0].path)
        assert errs[0].message and secret not in errs[0].message and "ZQX" not in errs[0].message, \
            (name, errs[0].message)


def test_the_error_messages_name_the_rule():
    assert "list of company names" in _aka_errors("Northwind")[0].message
    assert "non-empty" in _aka_errors(["Northwind", ""])[0].message
    assert "10" in _aka_errors([f"N{i}" for i in range(11)])[0].message
    assert "80" in _aka_errors(["x" * 81])[0].message
    # the second entry gets its own path
    p = profile()
    p["experience"] = [dict(p["experience"][0]), dict(p["experience"][0], also_known_as="bad")]
    assert [e.path for e in A.validate(p) if "also_known_as" in e.path] == ["experience[1].also_known_as"]


def test_the_valid_edge_cases_give_no_error():
    cases = {"absent": None, "null": None, "empty list": [], "one name": ["Northwind"],
             "ten names": [f"Name {i}" for i in range(10)], "80 characters": ["x" * 80],
             "80 characters with padding": ["  " + "x" * 80 + "  "]}
    assert _aka_errors(None, present=False) == []
    for name, v in cases.items():
        if name == "absent":
            continue
        assert _aka_errors(v) == [], name
    assert A.validate(profile()) == [], "the sample profile stays valid"


def test_an_also_known_as_check_does_not_disturb_the_other_entry_errors():
    p = profile()
    p["experience"][0]["also_known_as"] = ["Northwind"]
    p["experience"][0]["end"] = "not a date"
    paths = [e.path for e in A.validate(p)]
    assert "experience[0].end" in paths and "experience[0].also_known_as" not in paths


# ------------------------------------------------------------------ end to end

def _prof(aka, end="2023-08"):
    p = profile()
    p["experience"] = [_entry("Sample Analytics", aka, end)]
    return p


def _declare(p, label, employer, aliases=()):
    f = field("q", label, FT.DROPDOWN, ("Yes", "No"), True)
    return D.answer(D.classify(D.norm_label(label), ""), f, ctx_for(p, employer=employer, aliases=aliases))


def test_the_declaration_answer_flips_from_no_to_yes_when_the_name_is_added():
    q = "Have you previously worked for Northwind?"
    a = _declare(_prof(None), q, "Northwind")
    assert a.status is AS.FILLED and chosen(a) == ("No",), (a.status, chosen(a), a.note)
    a = _declare(_prof(["Northwind"]), q, "Northwind")
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, chosen(a), a.note)
    a = _declare(_prof(["Northwind"]), "Have you worked for us before?", "Northwind")
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, chosen(a), a.note)
    # an unrelated company stays No, with or without the field
    for aka in (None, ["Northwind"]):
        a = _declare(_prof(aka), "Have you previously worked for Example Co?", "Example Co")
        assert a.status is AS.FILLED and chosen(a) == ("No",), (aka, a.status, chosen(a), a.note)
    # a one-word posting that is only a prefix of the other name stays No (D-210)
    a = _declare(_prof(["Northwind Logistics"]), q, "Northwind")
    assert chosen(a) == ("No",), chosen(a)


def test_the_current_employee_answer_follows_the_end_date_and_the_name():
    q = "Are you currently employed by Northwind?"
    assert chosen(_declare(_prof(["Northwind"], end=None), q, "Northwind")) == ("Yes",)
    assert chosen(_declare(_prof(["Northwind"], end="2023-08"), q, "Northwind")) == ("No",)
    assert chosen(_declare(_prof(None, end=None), q, "Northwind")) == ("No",)
    assert D.truth(L.CURRENT_EMPLOYEE, _prof(["Northwind"], end=None), "Northwind") is True
    assert D.truth(L.PRIOR_EMPLOYMENT, _prof(["Northwind"]), "Northwind") is True
    assert D.truth(L.PRIOR_EMPLOYMENT, _prof(["Northwind"]), "Example Co") is False
    assert D.truth(L.PRIOR_EMPLOYMENT, _prof(["Northwind"]), "Zeta", ("Northwind",)) is True


def test_the_resolver_canonical_previous_worker_reads_the_other_names():
    f = field("pw", "Previous employee?", FT.DROPDOWN, ("Yes", "No"), True, canonical=Canonical.PREVIOUS_WORKER)
    assert chosen(resolve_one(f, _prof(None), REAL_RULES, employer="Northwind")) == ("No",)
    assert chosen(resolve_one(f, _prof(["Northwind"]), REAL_RULES, employer="Northwind")) == ("Yes",)
    assert chosen(resolve_one(f, _prof(["Northwind"]), REAL_RULES, employer="Example Co")) == ("No",)
    assert chosen(resolve_one(f, _prof(["Northwind"]), REAL_RULES, employer="Zeta",
                              aliases=("Northwind Pte Ltd",))) == ("Yes",)


def test_the_standing_facts_worked_here_and_current_employee_here_read_the_other_names():
    def standing(aka, end, employer="Northwind"):
        facts = F.by_ref(F.fact_catalogue(_prof(aka, end), ctx_for(_prof(aka, end), employer=employer),
                                          today="2026-11-14"))
        return facts["standing:worked_here"].value, facts["standing:current_employee_here"].value

    assert standing(None, None) == ("no", "no")
    assert standing(["Northwind"], None) == ("yes", "yes")
    assert standing(["Northwind"], "2023-08") == ("yes", "no")
    assert standing(["Northwind"], None, employer="Example Co") == ("no", "no")


# ------------------------------------------------------------------ the form and the refresh

def _experience_item():
    form = A.form_json()
    for g in form:
        for it in g["items"]:
            if it["path"] == "experience":
                return it
    raise AssertionError("no experience item in form_json()")


def test_the_profile_form_ships_the_sub_field_as_a_list_of_text():
    subs = {s["path"]: s for s in _experience_item()["sub"]}
    s = subs["also_known_as"]
    assert s["kind"] == "list_text" and s["label"] == "Also known as", s
    assert s["help"] and "worked for us" in s["help"]
    assert s["required"] is False and s["sensitive"] is False
    assert set(subs) >= {"employer", "title", "start", "end", "location", "description", "also_known_as"}
    assert A.ALSO_KNOWN_AS == "also_known_as" and (A.ALSO_KNOWN_AS_MAX_NAMES, A.ALSO_KNOWN_AS_MAX_LEN) == (10, 80)


def test_a_resume_refresh_keeps_the_owners_other_names():
    """A from_resume entry is updated from the resume; keys outside the proposal (the other names) stay."""
    mine = _exp(from_resume=True, also_known_as=["Northwind", "NW Bank"], description="old text")
    profile_ = {**copy.deepcopy(TEMPLATE), "experience": [mine]}
    props = _props(experience=[_prop_exp(description="new text from the resume")])
    plan = _plan(profile_, props)
    ups = [c for c in plan["changes"] if c["list"] == "experience" and c["op"] == "update"]
    assert len(ups) == 1, plan["changes"]
    new, ignored = A.apply_refresh(profile_, props, [ups[0]["id"]], TEMPLATE)
    assert not ignored
    entry = new["experience"][0]
    assert entry["description"] == "new text from the resume"
    assert entry["also_known_as"] == ["Northwind", "NW Bank"]
    assert entry["from_resume"] is True
    # an owner-edited entry (from_resume false) is kept whole, names included
    owner = _exp(from_resume=False, also_known_as=["Northwind"])
    plan = _plan({**copy.deepcopy(TEMPLATE), "experience": [owner]}, props)
    assert not [c for c in plan["changes"] if c["list"] == "experience" and c["op"] == "update"]
