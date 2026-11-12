"""Q-121 review F6 pins: the company-name matching rule (`declarations.company_match`, apply_design
§7.5 as narrowed by F6) and every place that decides "same company" or "another company".

Why it matters: the owner's install submits with no review step, so "Have you worked here? Yes" is
a statement on a submitted application. Before F6 the rule was "one name is a prefix of the other",
so applying to "Example" with "Example Logistics" in the profile's experience answered Yes (false).
The opposite error, No for the same firm ("Northwind" vs "Northwind Holdings Ltd"), is equally
false. The rule now: both names tokenised (case, punctuation, a leading "the", the trailing legal
form / group / holdings / branch / Singapore words dropped); equal, or one a prefix of the other with
EVERY extra word generic (legal form, place, entity word such as bank or technologies) and none right
after "of"; a one-word name under 3 characters matches only an equal name.

Coordinator decisions (2026-11-12): the rule stays as built. "financial" is NOT generic ("Grab" vs
"Grab Financial Group" is False: Prudential plc is not Prudential Financial); a true affiliate is
matched through the employer's aliases, which use the same rule. "Shell" vs "Shell Eastern
Petroleum" is False for the same reason.

Written from the spec in comms/outbox/software-engineer.md (F6 entry) and the Coordinator's
decisions, with synthetic and public company names. No network, no model, no server, no browser.
Truth tables are checked in BOTH argument orders. A pair is red only when the built rule gives
an answer that is false for a pair an owner would meet; those pins are kept together at the end
(`test_defect_*`) and stay red until the defect is fixed.
Verify: python tests/run_tests.py -k declarations_f6
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import chosen, ctx_for, field, profile  # noqa: E402

from jobscraper.apply import declarations as D, facts as F  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus as AS, EntryGroup, EntrySection, FieldType as FT, PageField, ResolveContext,
)

T, X = True, False          # expected: the same company / not the same company


def _both(table):
    """Every (a, b, want) checked in both orders; ONE failure message listing all wrong rows."""
    bad = []
    for a, b, want in table:
        for x, y in ((a, b), (b, a)):
            got = D.company_match(x, y)
            if got is not want:
                bad.append(f"company_match({x!r}, {y!r}) = {got}, want {want}")
    assert not bad, "\n".join(bad)


# ------------------------------------------------------------------ the rule, table-driven

def test_equal_names_and_spelling_only_differences_match():
    _both([
        ("Example", "Example", T),
        ("Example Pte Ltd", "example pte. ltd.", T),            # case and punctuation
        ("EXAMPLE", "example", T),
        ("Ex-ample", "Ex ample", T),                            # a hyphen is a space
        ("Example, Inc.", "example inc", T),
        ("AT&T", "AT & T", T),                                  # "&" is a separator
        ("Johnson & Johnson", "Johnson&Johnson", T),
        ("The Example Company", "Example", T),                  # a leading "the"
        ("The Example Group", "Example", T),
        ("The Hongkong and Shanghai Banking Corporation", "Hongkong and Shanghai Banking Corporation", T),
        ("Nestlé", "Nestlé SA", T),                   # accents kept the same on both sides
        ("The Example", "The Sample", X),
        ("Example", "Sample", X),
    ])


def test_legal_forms_and_group_or_holdings_words_never_make_a_different_company():
    _both([
        ("Example Pte Ltd", "Example", T),
        ("Example Private Limited", "Example", T),
        ("Example Pvt. Ltd.", "Example", T),
        ("Example LLC", "Example Corp", T),
        ("Example Co., Ltd.", "Example", T),
        ("Example GmbH", "Example", T),
        ("Example PLC", "Example", T),
        ("Northwind", "Northwind Holdings Ltd", T),                 # the F6 example of the same firm
        ("Grab", "Grab Holdings Inc.", T),
        ("Example Group", "Example", T),
        ("Example Holdings Group Ltd", "Example", T),
        ("Example", "Example Pte Ltd (Singapore Branch)", T),
        ("Example Co", "Example Logistics", X),                 # "Co" is dropped; "logistics" is not
    ])


def test_a_place_after_the_name_is_the_same_company():
    _both([
        ("Google", "Google Asia Pacific Pte. Ltd.", T),
        ("Example", "Example Singapore", T),
        ("Example Pte Ltd", "Example Singapore", T),
        ("Example", "Example (Singapore) Pte Ltd", T),
        ("Example", "Example APAC", T),
        ("Example", "Example India Pvt Ltd", T),
        ("Example", "Example Hong Kong", T),
        ("Example", "Example Asia Pacific", T),
        ("DBS Bank Ltd", "DBS Bank (Hong Kong) Limited", T),
        ("Microsoft", "Microsoft Singapore Pte Ltd", T),
        ("Standard Chartered", "Standard Chartered Bank (Singapore) Limited", T),
        ("Standard Chartered Bank", "Standard Chartered Singapore", T),
        # a place INSIDE a name is part of the name: only the shared first word is left
        ("Air China", "Air India", X),
        ("China Airlines", "India Airlines", X),
    ])


def test_an_entity_word_after_the_name_is_the_same_company():
    _both([
        ("DBS", "DBS Bank Ltd", T),
        ("DBS Bank", "DBS", T),
        ("Example", "Example Technologies", T),
        ("Example", "Example Technology Pte Ltd", T),
        ("Example", "Example Labs", T),
        ("Example", "Example Capital Partners", T),
        ("Example", "Example Software Solutions", T),
        ("Example", "Example Securities", T),
        ("Example", "Example Digital Services", T),
        ("Example", "Example Asset Management", T),
        ("Example Bank", "Example Capital", X),                 # two different entity words: not a prefix
        ("Example Tech", "Example Technology", X),              # tokens differ ("tech" vs "technology")
    ])


def test_one_extra_word_that_is_not_generic_names_another_business():
    for word in ("Logistics", "Foods", "Motors", "Airlines", "Insurance", "Pharma", "Energy", "Financial",
                 "Finance", "Petroleum", "Robotics", "Media", "Properties", "Analytics"):
        _both([("Example", f"Example {word}", X),
               ("Example Pte Ltd", f"Example {word} Pte Ltd", X),
               ("Example Singapore", f"Example {word} Singapore", X)])
    _both([
        ("Grab", "Grab Financial Group", X),                    # Coordinator: financial is not generic
        ("Grab", "Grab Financial", X),
        ("Shell", "Shell Eastern Petroleum", X),                # Coordinator: the affiliate is an alias
        ("Morgan Stanley", "Morgan Advanced Materials", X),
        ("Prudential", "Prudential Financial", X),              # the classic pair of unrelated firms
        ("Example Logistics", "Sample Analytics", X),
        ("Acme", "Apex Acme", X),
        ("Example", "Example Logistics Pte Ltd (Singapore Branch)", X),
    ])
    # one generic word does not rescue a second, non-generic one
    _both([("Example", "Example Technologies Logistics", X),
           ("Example", "Example Singapore Logistics", X)])


def test_the_of_guard_a_word_after_of_is_the_name_not_a_location_or_entity_word():
    _both([
        ("Bank of America", "Bank of Singapore", X),
        ("Bank of Singapore", "Bank of Singapore Limited", T),
        ("Bank of America", "Bank of America Singapore Limited", T),
        ("Bank of America", "Bank of America Technologies", T),
        ("Development Bank of Singapore", "Development Bank of Japan", X),
        ("Development Bank of Singapore", "Development Bank of Singapore Ltd", T),
        # the bare guard: the place right after "of" is never an extra generic word, and the
        # trailing-place strip never takes it off (each guard alone is needed for this pair)
        ("Bank of", "Bank of Singapore", X),
        ("Bank of", "Bank of America", X),
    ])


def test_a_name_under_three_characters_matches_only_an_equal_name():
    _both([
        ("GS", "GS", T),
        ("GS", "gs", T),
        ("GS", "GS Pte Ltd", T),                                # only legal forms are stripped first
        ("GS", "GS Singapore", T),
        ("EY", "EY Singapore", T),
        ("GS", "GS Yuasa", X),
        ("GS", "GS Technologies", X),                           # the under-3 rule is stricter than the entity list
        ("EY", "EY Consulting", X),
        ("3M", "3M Company", T),
        ("Ab", "Ab Foods", X),
        ("Abc", "Abc Technologies", T),                         # 3 characters is enough
    ])


def test_an_empty_or_missing_name_matches_nothing_not_even_another_empty_name():
    for a, b in [("", "Example"), (None, "Example"), ("   ", "Example"), ("", ""), (None, None),
                 ("", None), ("(Singapore)", ""), ("...", "Example"), ("&", "&")]:
        assert D.company_match(a, b) is False, (a, b)
        assert D.company_match(b, a) is False, (b, a)


def test_a_name_of_only_filler_words_still_compares_as_itself():
    # "Group" / "Holdings" alone are not erased to nothing: the last token always stays
    assert D.company_match("Holdings", "Holdings Ltd") is True
    assert D.company_match("Holdings", "Example Holdings") is False


# ------------------------------------------------------------------ prior and current employment

def _profile_with(*entries):
    return {"experience": list(entries)}


JOBS = _profile_with(
    {"employer": "Example Logistics", "title": "Analyst", "start": "2024-01"},                  # no end: current
    {"employer": "DBS Bank Ltd", "title": "Intern", "start": "2023-06", "end": "2023-08"},       # an internship
    {"employer": "Google Asia Pacific Pte. Ltd.", "title": "SWE", "start": "2022-01", "end": ""},  # "" = current
    {"employer": "Northwind Holdings Ltd", "title": "Engineer", "start": "2020-01", "end": "2021-12"},
)


def test_prior_and_current_employment_on_a_dummy_profile():
    cases = [
        # employer, aliases, prior, current
        ("Example", (), X, X),                                  # the F6 case: only "Example Logistics" is in the profile
        ("Example Logistics", (), T, T),
        ("Example Logistics Pte Ltd", (), T, T),
        ("Example Foods", (), X, X),
        ("DBS", (), T, X),                                      # an internship counts (D-55); it ended
        ("DBS Group Holdings", (), T, X),
        ("Google", (), T, T),                                   # end "" = no end date
        ("Northwind", (), T, X),                                  # the other error: No for the same firm
        ("Northwind Holdings", (), T, X),
        ("Northwind Music", (), X, X),
        ("Sample", (), X, X),
        ("Sample", ("Example",), X, X),                         # an alias goes through the same rule
        ("Sample", ("Example Logistics",), T, T),
        ("ELX", ("Example Logistics",), T, T),
        ("Sample", ("", "Example"), X, X),                      # an empty alias is skipped
    ]
    bad = []
    for employer, aliases, prior, cur in cases:
        got = (D.prior_employment(JOBS, employer, aliases), D.current_employment(JOBS, employer, aliases))
        if got != (prior, cur):
            bad.append(f"{employer!r} aliases={aliases}: got prior/current {got}, want {(prior, cur)}")
    assert not bad, "\n".join(bad)


def test_an_entry_with_no_end_date_key_or_a_null_end_is_current():
    for entry in ({"employer": "Acme Robotics"}, {"employer": "Acme Robotics", "end": None},
                  {"employer": "Acme Robotics", "end": ""}):
        p = _profile_with(entry)
        assert D.current_employment(p, "Acme Robotics") is True, entry
        assert D.current_employment(p, "Acme") is False, entry
        assert D.prior_employment(p, "Acme") is False, entry
    p = _profile_with({"employer": "Acme Robotics", "end": "2024-05"})
    assert D.prior_employment(p, "Acme Robotics") is True and D.current_employment(p, "Acme Robotics") is False


def test_the_employment_helpers_ignore_junk_and_empty_names():
    for p in (None, {}, {"experience": None}, {"experience": []}, {"experience": ["x", 3, None]},
              {"experience": [{"employer": ""}, {"employer": None}, {"title": "no employer"}]}):
        for employer, aliases in (("Example", ()), ("", ()), ("", ("",)), ("Example", ("Acme",))):
            assert D.prior_employment(p, employer, aliases) is False, (p, employer)
            assert D.current_employment(p, employer, aliases) is False, (p, employer)


def test_an_alias_names_the_affiliate_the_word_lists_cannot_tell():
    """Coordinator: 'financial' is not generic, so a real affiliate is joined through the alias."""
    p = _profile_with({"employer": "Grab Financial Group", "start": "2023-01", "end": "2024-01"},
                      {"employer": "Shell Eastern Petroleum (Pte) Ltd", "start": "2022-01", "end": "2022-08"})
    assert D.prior_employment(p, "Grab") is False
    assert D.prior_employment(p, "Grab", ("Grab Financial Group",)) is True
    assert D.prior_employment(p, "Grab", ("Grab Financial Group Pte Ltd",)) is True
    assert D.current_employment(p, "Grab", ("Grab Financial Group",)) is False
    assert D.prior_employment(p, "Shell") is False
    assert D.prior_employment(p, "Shell", ("Shell Eastern Petroleum",)) is True
    # the alias is a name, not a licence: an unrelated alias does not match
    assert D.prior_employment(p, "Grab", ("Grab Taxi",)) is False


def test_the_declaration_answers_no_for_a_company_that_only_shares_a_first_word():
    """End to end through tier 4 (`declarations.answer`): the false 'Yes, I have worked here' that
    F6 closed. The question names the employer being applied to (D-90 gate 4)."""
    prof = profile()
    prof["experience"] = [dict(e) for e in JOBS["experience"]]

    def ans(label, employer, aliases=()):
        f = field("q", label, FT.DROPDOWN, ("Yes", "No"), True)
        lab = D.classify(D.norm_label(label), "")
        return D.answer(lab, f, ctx_for(prof, employer=employer, aliases=aliases))

    a = ans("Have you previously worked for Example?", "Example")
    assert a.status is AS.FILLED and chosen(a) == ("No",), (a.status, chosen(a), a.note)
    a = ans("Have you previously worked for Example Logistics?", "Example Logistics")
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, chosen(a), a.note)
    a = ans("Have you previously worked for Northwind?", "Northwind")
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, chosen(a), a.note)
    a = ans("Are you currently employed by Example?", "Example")
    assert a.status is AS.FILLED and chosen(a) == ("No",), (a.status, chosen(a), a.note)
    a = ans("Are you currently employed by Example Logistics?", "Example Logistics")
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, chosen(a), a.note)
    a = ans("Have you previously worked for Dbs?", "DBS")      # an internship counts
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, chosen(a), a.note)
    a = ans("Are you currently employed by DBS?", "DBS")       # ... but it ended
    assert a.status is AS.FILLED and chosen(a) == ("No",), (a.status, chosen(a), a.note)


# ------------------------------------------------------------------ names_this_employer

def test_a_label_names_this_employer_only_when_the_extra_word_is_generic():
    N = D.names_this_employer
    assert N("Have you worked at Example before?", ["Example Logistics"]) is False   # shorter, non-generic extra
    assert N("Have you worked at DBS before?", ["DBS Bank Ltd"]) is True
    assert N("Have you worked at DBS Bank before?", ["DBS"]) is True
    assert N("Did you work at Example Foods?", ["Example Logistics"]) is False
    assert N("Did you work at Example Logistics Pte Ltd?", ["Example Logistics"]) is True
    assert N("Have you worked for Northwind?", ["Northwind Holdings Ltd"]) is True
    assert N("Have you worked for Grab?", ["Grab Financial Group"]) is False         # Coordinator decision
    assert N("Have you worked for Grab?", ["Grab Financial Group", "Grab"]) is True  # via an alias
    assert N("Have you ever worked at Bank of America?", ["Bank of Singapore"]) is False
    assert N("Have you ever worked at Bank of Singapore?", ["Bank of Singapore Limited"]) is True
    assert N("Have you worked for us before?", []) is True                           # "us" needs no name
    assert N("Have you worked for Example?", []) is False
    assert N("Have you worked for Example?", ["", None]) is False                     # empty names name nobody
    assert N("", ["Example"]) is False


# ------------------------------------------------------------------ the callers that changed

def _rctx(employer, others, *, aliases=(), experience=(), education=(), resume_entries=()):
    return ResolveContext(profile={"experience": list(experience), "education": list(education)},
                          employer_name=employer, employer_aliases=tuple(aliases),
                          other_employers=tuple(others), resume_entries=tuple(resume_entries))


def test_facts_other_employers_no_longer_exempts_a_name_that_only_shares_a_first_word():
    """G12 guard list. This employer "Example": a watchlist company "Example Logistics" is ANOTHER
    company now (guarded), "Example Pte Ltd" is this one (exempt)."""
    r = _rctx("Example", ["Example Logistics", "Example Pte Ltd", "Sample Analytics", "DBS"])
    got = F.other_employers(r)
    assert got == [["example", "logistics"], ["sample", "analytics"], ["dbs"]], got
    # the other direction: this employer is the longer name
    r = _rctx("Example Logistics", ["Example", "Example Logistics Singapore", "Example Foods"])
    assert F.other_employers(r) == [["example"], ["example", "foods"]]
    # an alias exempts a spelling of this employer (same rule)
    r = _rctx("Grab", ["Grab Financial Group", "Grab Holdings"], aliases=("Grab Financial Group",))
    assert F.other_employers(r) == []
    r = _rctx("Grab", ["Grab Financial Group", "Grab Holdings"])
    assert F.other_employers(r) == [["grab", "financial"]], F.other_employers(r)   # employer_norm drops "group"


def test_facts_other_employers_for_a_composed_text_exempts_the_applicants_own_employers_by_the_same_rule():
    mine = [{"employer": "Example Logistics", "title": "Analyst"}]
    # own employer "Example Logistics": a watchlist "Example Logistics Pte Ltd" is the same company: exempt
    r = _rctx("Other Co", ["Example Logistics Pte Ltd"], experience=mine)
    assert F.other_employers(r, composed=True) == []
    assert F.other_employers(r, composed=False) == [["example", "logistics"]]
    # a watchlist "Example" is NOT the own employer "Example Logistics" any more, so it stays guarded
    # (fail-closed): a composed text naming "Example Logistics" can fail G12 on the token "example" ...
    r = _rctx("Other Co", ["Example"], experience=mine)
    assert F.other_employers(r, composed=True) == [["example"]]
    assert F.names_other_employer("I worked at Example Logistics.", F.other_employers(r, composed=True)) is True
    # ... unless the resume entries name it (the existing exemption)
    r = _rctx("Other Co", ["Example"], experience=mine,
              resume_entries=[("experience[0]", "experience", "Analyst, Example Logistics, 2024")])
    assert F.other_employers(r, composed=True) == []
    # education counts as the applicant's own too
    r = _rctx("Other Co", ["Sample University Singapore"], education=[{"institution": "Sample University"}])
    assert F.other_employers(r, composed=True) == []


def test_apply_flow_other_employers_follows_the_same_rule_and_joins_alias_groups():
    from jobscraper import apply_flow as AF
    store = SimpleNamespace(companies=lambda: [SimpleNamespace(name=n) for n in
                                               ("Example Logistics", "Example Pte Ltd", "Sample Analytics", "Northwind")],
                            sighting_employers=lambda: ["Example Foods", "Example Singapore", "Northwind Holdings Ltd"])
    me = SimpleNamespace(store=store)

    def run(company, aliases=(), groups=()):
        return AF._Run.other_employers(me, {"company": company}, tuple(aliases), tuple(groups))

    got = run("Example")
    assert got == ("Example Logistics", "Sample Analytics", "Northwind", "Example Foods", "Northwind Holdings Ltd"), got
    # an aliases.yaml group joins its spellings with the same rule: "Example Logistics" is this employer
    got = run("Example", groups=[("Example", "Example Logistics")])
    assert "Example Logistics" not in got and "Example Foods" in got, got
    # a group that does not hold this employer's name changes nothing
    assert run("Example", groups=[("Sample Analytics", "Sample Analytics Asia")]) == run("Example")
    # an alias name from the job (company_key, board) is a name of this employer, by the same rule
    got = run("Ex", aliases=("Example Logistics",))
    assert "Example Logistics" not in got and "Example Pte Ltd" in got, got   # alias is not a prefix licence


def _site_entry(kind_fields, rctx, section="work_experience"):
    """F.match_entries over one site entry whose fields are (key, label, shown)."""
    pfs = [PageField(field=field(k, label, FT.TEXT), widget="text", shown=shown, group=f"{section}#1")
           for k, label, shown in kind_fields]
    sec = EntrySection(section=section, title="Work Experience",
                       entries=(EntryGroup(section, 1, "Work Experience 1", "#e1"),))
    return F.match_entries([sec], pfs, rctx)


def test_entry_matching_leaves_a_site_entry_unmatched_when_the_employer_differs_by_a_real_word():
    exp = [{"employer": "Acme Logistics", "title": "Software Engineer", "start": "2023-01"}]
    r = _rctx("Other Co", [], experience=exp)
    shown = lambda emp: [("c", "Company", emp), ("t", "Job title", "Software Engineer")]  # noqa: E731
    assert _site_entry(shown("Acme Logistics Pte Ltd"), r) == {"work_experience#1": "experience[0]"}
    assert _site_entry(shown("Acme Logistics"), r) == {"work_experience#1": "experience[0]"}
    assert _site_entry(shown("Acme"), r) == {"work_experience#1": None}             # shares only a first word
    assert _site_entry(shown("Acme Foods"), r) == {"work_experience#1": None}
    exp = [{"employer": "Acme", "title": "Software Engineer", "start": "2023-01"}]
    r = _rctx("Other Co", [], experience=exp)
    assert _site_entry(shown("Acme Technologies"), r) == {"work_experience#1": "experience[0]"}
    assert _site_entry(shown("Acme Logistics"), r) == {"work_experience#1": None}


def test_the_entry_score_is_zero_for_a_different_employer_and_positive_for_the_same_one():
    src = ("experience[0]", "Acme Logistics", "Software Engineer", "")
    assert F._score("experience", "Acme", "Software Engineer", src) == 0.0
    assert F._score("experience", "Acme Logistics Singapore", "Software Engineer", src) >= F.MATCH_MIN
    assert F._score("experience", "Acme Logistics Pte Ltd", "", src) == F.MATCH_MIN   # employer alone
    assert F._score("experience", "", "Software Engineer", src) >= F.MATCH_MIN_NO_NAME  # no employer shown: title only


# ------------------------------------------------------------------ the stored key must not move

# `employer_norm` is the stored key of saved per-employer answers (`by_employer`) and of question
# sightings. F6 left `_COMPANY_NOISE` and `_company_tokens` alone. The expected values below are
# HARD-CODED, taken from `git show e1ea40d:src/jobscraper/apply/declarations.py` (the commit before
# F6) by running that version's `employer_norm` on each name in a scratch process; the same ten
# names give the same ten strings on the F6 version (checked at write time).
EMPLOYER_NORM_BEFORE_F6 = [
    ("Shopee Pte Ltd", "shopee"),
    ("Bank of Singapore", "of"),                  # odd but stored: bank and singapore are noise
    ("DBS Bank Ltd", "dbs"),
    ("Google Asia Pacific Pte. Ltd.", "google asia pacific"),
    ("The Example Group", "example"),
    ("Grab Holdings Inc.", "grab"),
    ("Standard Chartered Bank (Singapore) Limited", "standard chartered"),
    ("Pte Ltd", "pte ltd"),                       # all noise: keeps the tokens rather than ""
    ("AT&T Corp.", "at t"),
    ("", ""),
]
NOISE_BEFORE_F6 = frozenset({"pte", "ltd", "limited", "inc", "llc", "corp", "corporation", "co", "plc",
                             "group", "holdings", "the", "singapore", "sg", "bank"})


def test_employer_norm_is_exactly_what_it_was_before_f6():
    bad = [f"employer_norm({n!r}) = {D.employer_norm(n)!r}, want {want!r}"
           for n, want in EMPLOYER_NORM_BEFORE_F6 if D.employer_norm(n) != want]
    assert not bad, "\n".join(bad)
    assert D.employer_norm(None) == ""
    assert D._COMPANY_NOISE == NOISE_BEFORE_F6, "the stored-key word list changed: saved answers would orphan"


def test_every_old_noise_word_is_still_generic_for_the_match():
    assert NOISE_BEFORE_F6 <= D._COMPANY_GENERIC, sorted(NOISE_BEFORE_F6 - D._COMPANY_GENERIC)
    # and "financial"/"finance" are deliberately not generic (Coordinator decision)
    assert not ({"financial", "finance", "logistics", "foods", "motors", "airlines", "insurance",
                 "pharma", "energy", "petroleum"} & D._COMPANY_GENERIC)


# ------------------------------------------------------------------ the existing helper still exists

def test_the_signatures_callers_use_are_unchanged():
    assert callable(D.company_match) and callable(D.prior_employment) and callable(D.current_employment)
    assert callable(D.names_this_employer) and callable(D.names_employer) and callable(D.employer_norm)
    assert D.company_match("a", "b") is False and isinstance(D.company_match("a", "a"), bool)


# ------------------------------------------------------------------ DEFECT pins: red on purpose
# Each is a normalisation failure (not a word-list decision): the same company, written two ways
# the owner meets, is reported as another company, so a declaration says "No" for a real former
# employer (a false statement). They stay red until the matcher is fixed. Both existed before F6
# (the old rule normalised the same way); F6 did not cause them.

def test_defect_ampersand_and_the_word_and_are_the_same_company():
    _both([
        ("Procter & Gamble", "Procter and Gamble", T),
        ("Johnson & Johnson", "Johnson and Johnson", T),
        ("Marks & Spencer", "Marks and Spencer Group plc", T),
    ])


def test_defect_an_accented_letter_and_its_plain_form_are_the_same_company():
    _both([
        ("Nestlé", "Nestle", T),
        ("Société Générale", "Societe Generale", T),
        ("Crédit Agricole", "Credit Agricole Singapore Branch", T),
    ])
