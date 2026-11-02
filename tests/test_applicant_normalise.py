"""Q-36 (owner decision D-78: no rigid manual entry) oracles for `applicant.normalise`.

`normalise(profile)` canonicalises every enum, plain boolean and date field; `load`, `validate`
and `save` all call it. These tests pin what the docstrings of `normalise`, `_canon_enum`,
`_canon_bool` and `_canon_date` promise, from the outside (the public `normalise`, `validate`,
`load`, `save`), and the limits: what must NOT be rewritten, so a typo still gets reported.

Synthetic data only (the sample profile is an invented person). No network; every file lives in
a temp folder; nothing under `data/`.
"""
from __future__ import annotations

import calendar
import copy
import datetime as dt
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT, profile  # noqa: E402

from jobscraper import applicant as A  # noqa: E402

TEMPLATE = ROOT / "config" / "applicant.example.yaml"


# ------------------------------------------------------------------ helpers

def _put(p: dict, path: str, value) -> dict:
    """Set a dotted path on `p`, creating the mappings on the way (no list indices)."""
    *parents, leaf = path.split(".")
    cur = p
    for part in parents:
        if not isinstance(cur.get(part), dict):      # absent, or null in the sample (current_salary)
            cur[part] = {}
        cur = cur[part]
    cur[leaf] = value
    return p


def _got(p: dict, path: str):
    cur = p
    for part in path.split("."):
        cur = cur[part]
    return cur


def _norm_at(path: str, value):
    """`normalise` of the sample profile with `path` set to `value`; the value at `path` after."""
    return _got(A.normalise(_put(profile(), path, value)), path)


def _errs_at(path: str, value) -> list:
    return A.validate(_put(profile(), path, value))


def _paths(errs) -> set[str]:
    return {e.path for e in errs}


def _entry(lst: str, key: str, value) -> dict:
    p = profile()
    p[lst][0][key] = value
    return p


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="jobscraper-normalise-"))


# Every enum path and each of its allowed values ("decline" only for health_disclosure).
def _enum_cases():
    for path, allowed in A.ENUMS.items():
        for value in allowed:
            yield path, value


# ------------------------------------------------------------------ enums

def test_every_enum_value_reads_back_from_any_case_spaces_and_hyphens():
    """Any case, surrounding spaces, and spaces or hyphens for underscores: for EVERY enum path
    and EVERY allowed value, so a value added to ENUMS later is covered without an edit here."""
    n = 0
    for path, value in _enum_cases():
        variants = {value.upper(), value.title(), f"  {value}  ", value.replace("_", " "),
                    value.replace("_", "-"), value.replace("_", " ").upper(),
                    value.replace("_", "-").title()}
        for typed in variants:
            assert _norm_at(path, typed) == value, (path, typed)
            n += 1
        # the canonical spelling is a fixed point, and validates
        assert _norm_at(path, value) == value
    assert n > 50


def test_the_named_spellings_the_owner_will_actually_type():
    for typed, want in (("Male ", "male"), ("FEMALE", "female"), ("Non-Binary", "non_binary"),
                        ("non binary", "non_binary"), ("Non_binary", "non_binary")):
        assert _norm_at("identity.gender", typed) == want, typed
        assert _norm_at("us_self_id.eeo_gender", typed) == want, typed
    assert _norm_at("identity.name_order", "Surname First") == "surname_first"
    assert _norm_at("singapore_status.residency_status", "Citizen") == "citizen"
    assert _norm_at("singapore_status.residency_status", "PR") == "pr"
    assert _norm_at("singapore_status.work_pass", "S-Pass") == "s_pass"
    assert _norm_at("singapore_status.work_pass", "none required") == "none_required"
    assert _norm_at("singapore_status.ns_status", "Not Applicable") == "not_applicable"
    assert _norm_at("singapore_status.ns_status", "not-applicable") == "not_applicable"
    assert _norm_at("us_self_id.eeo_race_ethnicity", "Two or more") == "two_or_more"
    assert _norm_at("us_self_id.veteran_status", "Not a veteran") == "not_a_veteran"


def test_a_mappable_enum_validates_clean_after_the_read():
    p = profile()
    for path, typed in (("identity.gender", "Non-Binary"), ("singapore_status.race", " CHINESE "),
                        ("singapore_status.ns_status", "Completed"),
                        ("pay.expected_salary.period", "Per Month"),
                        ("us_self_id.disability_status", "NO")):
        _put(p, path, typed)
    assert A.validate(p) == []


def test_pay_period_synonyms_for_both_salaries():
    monthly = ("month", "Per Month", "per-month", "MONTHLY", "mth", "monthly", " Month ")
    annual = ("year", "yearly", "Yearly", "annual", "Annual", "per annum", "Per Annum",
              "pa", "PA", "p.a.", "P.A.")
    for path in ("pay.expected_salary.period", "pay.current_salary.period"):
        for typed in monthly:
            assert _norm_at(path, typed) == "monthly", (path, typed)
        for typed in annual:
            assert _norm_at(path, typed) == "annual", (path, typed)


def test_a_pay_period_synonym_works_when_the_salary_block_is_the_owners_own():
    p = profile()
    p["pay"]["expected_salary"]["period"] = "p.a."
    p["pay"]["current_salary"] = {"amount": 4000, "currency": "SGD", "period": "per month"}
    out = A.normalise(p)
    assert out["pay"]["expected_salary"]["period"] == "annual"
    assert out["pay"]["current_salary"]["period"] == "monthly"
    assert A.validate(p) == []


def test_pay_synonyms_do_not_leak_into_other_enums():
    """`month` / `year` / `pa` mean something only for a pay period."""
    for path in ("identity.gender", "singapore_status.marital_status",
                 "singapore_status.work_pass"):
        for typed in ("monthly", "annual", "p.a."):
            assert _norm_at(path, typed) == typed, (path, typed)
            assert path in _paths(_errs_at(path, typed)), (path, typed)


def test_prefer_not_to_say_and_rather_not_say_read_as_decline_where_decline_is_allowed():
    declinable = [p for p, allowed in A.ENUMS.items() if "decline" in allowed]
    assert "identity.gender" in declinable and "us_self_id.disability_status" in declinable
    assert "declarations.health_disclosure" in declinable
    for path in declinable:
        for typed in ("prefer not to say", "Prefer Not To Say", "prefer-not-to-say",
                      "PREFER_NOT_TO_SAY", "rather not say", "Rather Not Say", "  rather not say "):
            assert _norm_at(path, typed) == "decline", (path, typed)


def test_decline_synonyms_stay_as_typed_where_decline_is_not_allowed():
    for path, allowed in A.ENUMS.items():
        if "decline" in allowed:
            continue
        for typed in ("prefer not to say", "rather not say"):
            assert _norm_at(path, typed) == typed, (path, typed)
            assert path in _paths(_errs_at(path, typed)), (path, typed)
    # the list enums have no decline either
    p = profile()
    p["languages"][0]["spoken"] = "prefer not to say"
    assert "languages[0].spoken" in _paths(A.validate(p))


def test_a_yaml_boolean_is_yes_or_no_only_for_a_yes_no_enum():
    """`disability_status: no` is read by YAML as False; that is the owner's "no"."""
    doc = yaml.safe_load("us_self_id:\n  disability_status: no\n")
    assert doc["us_self_id"]["disability_status"] is False          # the YAML trap itself
    assert A.normalise(doc)["us_self_id"]["disability_status"] == "no"
    assert _norm_at("us_self_id.disability_status", True) == "yes"
    assert _norm_at("us_self_id.disability_status", False) == "no"
    assert _norm_at("us_self_id.disability_status", "Yes") == "yes"
    assert _norm_at("us_self_id.disability_status", "NO") == "no"
    # an enum without both yes and no keeps the bool, and validate reports it
    for path, allowed in A.ENUMS.items():
        if {"yes", "no"} <= set(allowed):
            continue
        for b in (True, False):
            got = _norm_at(path, b)
            assert got is b, (path, b, got)
            assert path in _paths(_errs_at(path, b)), (path, b)
    # list enums too
    p = profile()
    p["languages"][0]["spoken"] = True
    assert A.normalise(p)["languages"][0]["spoken"] is True
    assert "languages[0].spoken" in _paths(A.validate(p))


def test_an_enum_value_that_maps_to_nothing_stays_as_typed_and_validate_reports_it():
    for path, allowed in A.ENUMS.items():
        for typed in ("zzz-not-a-value", "maybe", 3, 2.5, ["male"], {"a": 1}):
            assert _norm_at(path, typed) == typed, (path, typed)
            errs = [e for e in _errs_at(path, typed) if e.path == path]
            assert len(errs) == 1, (path, typed, errs)
            assert errs[0].message == "must be one of: " + ", ".join(allowed), errs[0]
    # None and "" are "empty", not errors (a required one shows up in missing_for_apply)
    for empty in (None, "", "   "):
        assert A.validate(_put(profile(), "identity.gender", empty)) == []


def test_list_enums_education_grade_type_and_languages():
    p = profile()
    p["education"][0]["grade_type"] = "Honours Class"
    p["languages"][0].update(spoken=" Fluent ", written="NATIVE")
    p["languages"][1].update(spoken="professional", written="Basic")
    out = A.normalise(p)
    assert out["education"][0]["grade_type"] == "honours_class"
    assert [(x["spoken"], x["written"]) for x in out["languages"]] == \
        [("fluent", "native"), ("professional", "basic")]
    assert A.validate(p) == []
    for typed, want in (("GPA", "gpa"), ("Cap", "cap"), ("honours-class", "honours_class")):
        p["education"][0]["grade_type"] = typed
        assert A.normalise(p)["education"][0]["grade_type"] == want, typed
    p["education"][0]["grade_type"] = "first class"
    assert "education[0].grade_type" in _paths(A.validate(p))


def test_free_text_numbers_and_urls_are_never_rewritten():
    p = profile()
    p["identity"]["preferred_name"] = "No"
    p["identity"]["pronouns"] = "She/Her"
    p["singapore_status"]["religion"] = "Prefer not to say"
    p["singapore_status"]["race_other"] = "Yes"
    p["contact"]["address_line1"] = "12 Mar 2020 Road"
    p["education"][0]["major"] = "Mar 2020"
    p["education"][0]["grade"] = "4.20"
    p["experience"][0]["description"] = "True. Male. 03/2020."
    p["experience"][0]["location"] = "Per Month"
    p["links"]["github"] = "https://github.com/Example"
    p["sourcing"]["how_heard_default"] = "Yes"
    p["pay"]["expected_salary"]["amount"] = 5000
    p["pay"]["months_per_year"] = 13
    p["availability"]["notice_period_days"] = 30
    p["skills"] = ["Yes", "Mar 2020", "Per Month"]
    assert A.normalise(p) == p


# ------------------------------------------------------------------ booleans

def test_every_plain_bool_reads_a_quoted_yes_no_true_false_in_any_case():
    for path in A.BOOLS:
        for typed in ("yes", "Yes", "YES", " true ", "True", "TRUE"):
            assert _norm_at(path, typed) is True, (path, typed)
        for typed in ("no", "No", "NO", " false ", "False", "FALSE"):
            assert _norm_at(path, typed) is False, (path, typed)
        for b in (True, False):
            assert _norm_at(path, b) is b
    p = profile()
    for path in A.BOOLS:
        _put(p, path, "Yes")
    assert A.validate(p) == []


def test_a_word_that_is_not_yes_no_true_false_stays_and_validate_reports_a_bool_error():
    for path in A.BOOLS:
        for typed in ("maybe", "y", "n", "1", "0", 1, 0, 2, "", "yes please", [True]):
            assert _norm_at(path, typed) == typed, (path, typed)
            errs = [e for e in _errs_at(path, typed) if e.path == path]
            assert len(errs) == 1 and errs[0].message == "must be true or false", (path, typed, errs)


def test_both_work_rights_maps_read_quoted_words_and_keep_their_keys():
    for block in ("authorised_to_work", "requires_sponsorship"):
        p = profile()
        p["singapore_status"][block] = {"SG": "yes", "US": "No", "default": " TRUE ", "FR": "false",
                                        "JP": None, "DE": True}
        m = A.normalise(p)["singapore_status"][block]
        assert m == {"SG": True, "US": False, "default": True, "FR": False, "JP": None, "DE": True}, m
        assert all(m[k] is v for k, v in (("SG", True), ("US", False), ("default", True),
                                          ("FR", False), ("DE", True)))
        assert A.validate(p) == []
        # a word that is not a boolean is reported at the key, nothing about the rest
        p["singapore_status"][block] = {"SG": "yes", "US": "maybe", "FR": 3}
        got = A.normalise(p)["singapore_status"][block]
        assert got == {"SG": True, "US": "maybe", "FR": 3}, got
        assert _paths(A.validate(p)) == {f"singapore_status.{block}.US",
                                         f"singapore_status.{block}.FR"}


def test_work_rights_map_keys_are_not_rewritten_so_a_lowercase_key_is_still_an_error():
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"sg": "yes"}
    m = A.normalise(p)["singapore_status"]["authorised_to_work"]
    assert m == {"sg": True}, "the value is read, the key is not touched"
    assert "singapore_status.authorised_to_work" in _paths(A.validate(p))


def test_a_work_rights_value_that_is_not_a_map_is_left_for_validate():
    p = profile()
    p["singapore_status"]["authorised_to_work"] = "yes"
    p["singapore_status"]["requires_sponsorship"] = [True]
    out = A.normalise(p)["singapore_status"]
    assert out["authorised_to_work"] == "yes" and out["requires_sponsorship"] == [True]
    assert _paths(A.validate(p)) == {"singapore_status.authorised_to_work",
                                     "singapore_status.requires_sponsorship"}


def test_a_quoted_word_drives_work_rights_end_to_end():
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"SG": "yes", "default": "no"}
    p["singapore_status"]["requires_sponsorship"] = {"SG": "no", "default": "yes"}
    n = A.normalise(p)
    assert A.work_rights(n, "SG") == (True, False)
    assert A.work_rights(n, "FR") == (False, True)


# ------------------------------------------------------------------ month-only date: ord_date

ORD = "singapore_status.ord_date"


def test_ord_date_reads_date_objects_and_the_documented_text_forms_as_year_month():
    table = [
        (dt.date(2020, 3, 15), "2020-03"),
        (dt.datetime(2020, 3, 15, 9, 30), "2020-03"),
        (dt.date(2020, 12, 1), "2020-12"),
        ("2020-03", "2020-03"),
        ("  2020-03  ", "2020-03"),
        ("2020-03-15", "2020-03"),                 # a day given to a month-only field is cut
        ("2020/03", "2020-03"), ("2020/3", "2020-03"),
        ("03/2020", "2020-03"), ("3/2020", "2020-03"),
        ("Mar 2020", "2020-03"), ("March 2020", "2020-03"), ("mar 2020", "2020-03"),
        ("MARCH 2020", "2020-03"), ("Mar. 2020", "2020-03"), ("March, 2020", "2020-03"),
        ("Mar-2020", "2020-03"), ("  March   2020 ", "2020-03"),
        ("Sept 2020", "2020-09"), ("Sep 2020", "2020-09"), ("September 2020", "2020-09"),
    ]
    for typed, want in table:
        assert _norm_at(ORD, typed) == want, (typed, want)
        assert _errs_at(ORD, typed) == [], typed
    # every month, long and short name
    for i in range(1, 13):
        for name in (calendar.month_name[i], calendar.month_abbr[i]):
            assert _norm_at(ORD, f"{name} 2021") == f"2021-{i:02d}", (name, i)


def test_ord_date_that_maps_to_no_month_stays_as_typed_and_validate_reports_it():
    for typed in ("2020-13", "2020/13", "13/2020", "2020/00", "00/2020", "Foo 2020", "Marc 2020",
                  "March", "2020", "2020-02-30", "31/02/2001", "15/03/2020", "03/04/01",
                  "next year", "soon", 202006, 3.5, True):
        assert _norm_at(ORD, typed) == typed, typed
        errs = [e for e in _errs_at(ORD, typed) if e.path == ORD]
        assert len(errs) == 1 and errs[0].message == "must be a date as YYYY-MM", (typed, errs)


# ------------------------------------------------------------------ day dates

DAY_PATHS = ("identity.date_of_birth", "availability.earliest_start_date")


def test_day_fields_read_date_objects_and_day_month_year_as_iso_day():
    table = [
        (dt.date(2000, 3, 15), "2000-03-15"),
        (dt.datetime(2000, 3, 15, 23, 59), "2000-03-15"),
        ("2000-03-15", "2000-03-15"), ("  2000-03-15 ", "2000-03-15"),
        ("15/03/2000", "2000-03-15"), (" 15/03/2000 ", "2000-03-15"),
        ("1/3/2000", "2000-03-01"),
        ("03/04/2001", "2001-04-03"),              # Singapore order: day first
        ("29/02/2000", "2000-02-29"),              # a real leap day
        ("31/12/1999", "1999-12-31"),
    ]
    for path in DAY_PATHS:
        for typed, want in table:
            assert _norm_at(path, typed) == want, (path, typed, want)
            assert _errs_at(path, typed) == [], (path, typed)


def test_ambiguous_or_invalid_day_dates_stay_as_typed_and_validate_reports_them():
    for path in DAY_PATHS:
        for typed in ("12/31/2000",     # month 31: looks American, not a day/month/year
                      "03/04/01",       # two-digit year: ambiguous
                      "2001/07/04",     # year first with slashes: ambiguous
                      "31/02/2001",     # not a real date
                      "29/02/2001",     # not a leap year
                      "00/03/2000", "15/00/2000", "32/01/2000",
                      "2000-03",        # a month is not a day
                      "2000/03", "Mar 2000", "15 March 2000", "tomorrow", "2000-02-30", 20000315):
            assert _norm_at(path, typed) == typed, (path, typed)
            errs = [e for e in _errs_at(path, typed) if e.path == path]
            assert len(errs) == 1 and errs[0].message == "must be a date as YYYY-MM-DD", \
                (path, typed, errs)


def test_a_yaml_date_typed_without_quotes_is_read_like_the_quoted_text():
    doc = yaml.safe_load("identity:\n  date_of_birth: 2000-03-15\n"
                         "singapore_status:\n  ord_date: 2022-06-30\n"
                         "availability:\n  earliest_start_date: 2026-01-05\n")
    assert isinstance(doc["identity"]["date_of_birth"], dt.date)           # the YAML trap itself
    out = A.normalise(doc)
    assert out["identity"]["date_of_birth"] == "2000-03-15"
    assert out["singapore_status"]["ord_date"] == "2022-06"
    assert out["availability"]["earliest_start_date"] == "2026-01-05"
    assert all(isinstance(v, str) for v in (out["identity"]["date_of_birth"],
                                            out["singapore_status"]["ord_date"],
                                            out["availability"]["earliest_start_date"]))


# ------------------------------------------------------------------ entry dates

def test_entry_dates_keep_a_full_day_but_read_month_names_as_year_month():
    """Deliberate (D-68 A-4, apply_design 5.2): computed_facts counts a day when one is given, so
    `education[]` / `experience[]` start and end are NOT cut to the month; only a form that is not
    already canonical is rewritten (to YYYY-MM)."""
    table = [
        ("2024-05-15", "2024-05-15"), ("2024-05", "2024-05"), ("  2024-05 ", "2024-05"),
        (dt.date(2024, 5, 15), "2024-05-15"), (dt.datetime(2024, 5, 15, 8, 0), "2024-05-15"),
        ("Mar 2020", "2020-03"), ("March 2020", "2020-03"), ("mar 2020", "2020-03"),
        ("03/2020", "2020-03"), ("2020/03", "2020-03"), ("Sept 2020", "2020-09"),
        ("15/03/2020", "2020-03-15"),     # follows from entries accepting a day (Singapore order)
    ]
    for lst in ("education", "experience"):
        for key in ("start", "end"):
            for typed, want in table:
                got = A.normalise(_entry(lst, key, typed))[lst][0][key]
                assert got == want, (lst, key, typed, got, want)
    # None ("present") and "" are left alone
    for empty in (None, ""):
        assert A.normalise(_entry("experience", "end", empty))["experience"][0]["end"] == empty
        assert A.validate(_entry("experience", "end", empty)) == []


def test_entry_dates_that_map_to_nothing_stay_as_typed_and_validate_reports_them():
    for typed in ("2024-13", "13/2024", "Foo 2024", "2024-02-30", "12/31/2000", "31/02/2001",
                  "03/04/01", "2001/07/04", 2024):
        p = _entry("education", "start", typed)
        assert A.normalise(p)["education"][0]["start"] == typed, typed
        errs = [e for e in A.validate(p) if e.path == "education[0].start"]
        assert len(errs) == 1 and errs[0].message == "must be a date as YYYY-MM or YYYY-MM-DD", \
            (typed, errs)


def test_validate_compares_entry_dates_after_they_are_read():
    p = profile()
    p["education"][0].update(start="Mar 2020", end="Jun 2020")
    assert A.validate(p) == []
    p["education"][0].update(start="Jun 2020", end="Mar 2020")
    errs = A.validate(p)
    assert [(e.path, e.message) for e in errs] == [("education[0].end", "must not be before start")]
    p["education"][0].update(start="2020-06-15", end="03/2020")
    assert [e.path for e in A.validate(p)] == ["education[0].end"]


# ------------------------------------------------------------------ normalise itself

def _messy() -> dict:
    """A profile typed the way a person would: every field in a non-canonical spelling that
    normalise promises to read."""
    p = profile()
    p["identity"].update(gender="Non-Binary", name_order="Surname First",
                         date_of_birth="15/03/2000")
    p["singapore_status"].update(residency_status="Citizen", work_pass="none required",
                                 ns_status="Completed", race="Prefer not to say",
                                 marital_status=" SINGLE ", ord_date="Mar 2022",
                                 authorised_to_work={"SG": "yes", "US": "no"},
                                 requires_sponsorship={"SG": "No", "default": "TRUE"})
    p["us_self_id"].update(eeo_gender="Rather not say", eeo_race_ethnicity="Asian",
                           veteran_status="Not a Veteran", disability_status=False)
    p["availability"].update(earliest_start_date=dt.date(2026, 1, 5), willing_to_relocate="no")
    p["pay"]["expected_salary"].update(period="per annum", negotiable="Yes")
    p["pay"]["current_salary"] = {"amount": 4000, "currency": "SGD", "period": "Month"}
    p["education"][0].update(start="Aug 2021", end="06/2025", grade_type="CAP")
    p["experience"][0].update(start="2024-05-15", end="August 2024")
    p["languages"][0].update(spoken="Native", written="FLUENT")
    p["consents"].update(privacy_consent="yes", certify_true=" True ")
    p["declarations"].update(pep="no", bankruptcy="False", health_disclosure="prefer not to say")
    return p


def test_normalise_of_a_messy_profile_is_canonical_and_validates_clean():
    p = _messy()
    assert A.validate(p) == []
    out = A.normalise(p)
    assert out["identity"] == {**p["identity"], "gender": "non_binary", "name_order": "surname_first",
                               "date_of_birth": "2000-03-15"}
    s = out["singapore_status"]
    assert (s["residency_status"], s["work_pass"], s["ns_status"], s["race"], s["marital_status"],
            s["ord_date"]) == ("citizen", "none_required", "completed", "decline", "single", "2022-03")
    assert s["authorised_to_work"] == {"SG": True, "US": False}
    assert s["requires_sponsorship"] == {"SG": False, "default": True}
    u = out["us_self_id"]
    assert (u["eeo_gender"], u["eeo_race_ethnicity"], u["veteran_status"], u["disability_status"]) \
        == ("decline", "asian", "not_a_veteran", "no")
    assert out["availability"]["earliest_start_date"] == "2026-01-05"
    assert out["availability"]["willing_to_relocate"] is False
    assert out["pay"]["expected_salary"]["period"] == "annual"
    assert out["pay"]["expected_salary"]["negotiable"] is True
    assert out["pay"]["current_salary"]["period"] == "monthly"
    assert (out["education"][0]["start"], out["education"][0]["end"],
            out["education"][0]["grade_type"]) == ("2021-08", "2025-06", "cap")
    assert (out["experience"][0]["start"], out["experience"][0]["end"]) == ("2024-05-15", "2024-08")
    assert (out["languages"][0]["spoken"], out["languages"][0]["written"]) == ("native", "fluent")
    assert out["consents"]["privacy_consent"] is True and out["consents"]["certify_true"] is True
    d = out["declarations"]
    assert d["pep"] is False and d["bankruptcy"] is False and d["health_disclosure"] == "decline"


def test_normalise_is_idempotent():
    for p in (_messy(), profile(), {}, {"identity": {"gender": "zzz"}}, {"education": "x"}):
        once = A.normalise(p)
        assert A.normalise(once) == once
        assert A.validate(once) == A.validate(A.normalise(once))
    # and the canonical forms are fixed points: sample profile and the shipped template
    assert A.normalise(profile()) == profile()
    tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert A.normalise(tpl) == tpl
    assert A.validate(tpl) == []


def test_normalise_does_not_change_its_argument_and_returns_a_deep_copy():
    p = _messy()
    before = copy.deepcopy(p)
    out = A.normalise(p)
    assert p == before, "the argument is untouched"
    assert out is not p
    for path in ("identity", "singapore_status", "pay", "pay.expected_salary",
                 "singapore_status.authorised_to_work"):
        assert _got(out, path) is not _got(p, path), path
    assert out["education"] is not p["education"] and out["education"][0] is not p["education"][0]
    out["education"][0]["institution"] = "changed"
    out["singapore_status"]["authorised_to_work"]["SG"] = None
    assert p == before, "writing to the copy does not reach the original"
    A.validate(p)
    assert p == before, "validate does not change its argument either"


def test_normalise_never_adds_or_removes_a_key():
    p = {"identity": {"gender": "Male"}, "pay": {"expected_salary": {"period": "Month"}},
         "education": [{"institution": "X", "grade_type": "GPA"}]}
    out = A.normalise(p)
    assert out == {"identity": {"gender": "male"}, "pay": {"expected_salary": {"period": "monthly"}},
                   "education": [{"institution": "X", "grade_type": "gpa"}]}
    assert A.normalise({}) == {}
    assert A.normalise(profile()).keys() == profile().keys()


def test_normalise_tolerates_odd_shapes_without_raising_and_leaves_them_for_validate():
    for odd in (None, [], "text", 3, ("a",)):
        assert A.normalise(odd) == odd
    p = {"identity": "text", "singapore_status": [], "pay": {"expected_salary": "monthly",
         "current_salary": None}, "education": "x", "experience": [None, 3, "y", {"start": "Mar 2020"}],
         "languages": ["English"], "availability": 5, "us_self_id": None, "consents": [True]}
    out = A.normalise(p)
    assert out["experience"][3] == {"start": "2020-03"}
    out["experience"][3] = p["experience"][3]
    assert out == p
    assert A.validate(p), "and validate still has things to say about it"
    assert A.validate("not a mapping") == [A.FieldError("", "the profile must be a mapping")]


# ------------------------------------------------------------------ validate messages

def test_validate_messages_never_echo_the_value():
    """§5.2: a message names the rule, never the value (a typed value can be personal data)."""
    secret = "S3CRET-zq9"
    cases = {
        "identity.gender": secret,
        "singapore_status.residency_status": secret,
        "pay.expected_salary.period": secret,
        "us_self_id.disability_status": secret,
        "consents.privacy_consent": secret,
        "declarations.pep": secret,
        "availability.willing_to_relocate": secret,
        "identity.date_of_birth": f"31/02/{secret}",
        "availability.earliest_start_date": f"12/31/{secret}",
        ORD: f"{secret} 2020",
        "singapore_status.authorised_to_work.default": secret,
        "singapore_status.requires_sponsorship.US": secret,
    }
    for path, bad in cases.items():
        errs = _errs_at(path, bad)
        assert errs, (path, "must be reported")
        for e in errs:
            assert secret not in e.message and secret not in e.path, (path, e)
    p = profile()
    p["education"][0]["start"] = f"{secret} 2020"
    p["education"][0]["grade_type"] = secret
    p["languages"][0]["spoken"] = secret
    errs = A.validate(p)
    assert {"education[0].start", "education[0].grade_type", "languages[0].spoken"} <= _paths(errs)
    for e in errs:
        assert secret not in e.message and secret not in e.path, e


# ------------------------------------------------------------------ load and save

def test_load_returns_the_normalised_profile_of_a_hand_typed_file():
    d = _tmp()
    f = d / "applicant.yaml"
    f.write_text(
        "version: 1\n"
        "identity:\n  gender: Non-Binary\n  date_of_birth: 2000-03-15\n"
        "singapore_status:\n  ord_date: Mar 2022\n  authorised_to_work: {SG: 'yes', default: 'no'}\n"
        "us_self_id:\n  disability_status: no\n  eeo_gender: prefer not to say\n"
        "availability:\n  earliest_start_date: 05/01/2026\n  willing_to_relocate: 'No'\n"
        "pay:\n  expected_salary: {amount: 5000, currency: SGD, period: p.a., negotiable: yes}\n"
        "education:\n  - {institution: X, degree: Y, start: 'Aug 2021', end: 2025-06-30}\n",
        encoding="utf-8")
    got = A.load(f)
    assert got["identity"] == {"gender": "non_binary", "date_of_birth": "2000-03-15"}
    assert got["singapore_status"] == {"ord_date": "2022-03",
                                       "authorised_to_work": {"SG": True, "default": False}}
    assert got["us_self_id"] == {"disability_status": "no", "eeo_gender": "decline"}
    assert got["availability"] == {"earliest_start_date": "2026-01-05", "willing_to_relocate": False}
    assert got["pay"]["expected_salary"] == {"amount": 5000, "currency": "SGD", "period": "annual",
                                             "negotiable": True}
    assert (got["education"][0]["start"], got["education"][0]["end"]) == ("2021-08", "2025-06-30")
    assert A.validate(got) == []
    assert f.read_text(encoding="utf-8").count("Non-Binary") == 1, "load never rewrites the file"
    assert A.load(d / "missing.yaml") == {}
    (d / "empty.yaml").write_text("", encoding="utf-8")
    assert A.load(d / "empty.yaml") == {}


def test_save_then_load_round_trips_the_canonical_values():
    d = _tmp()
    f = d / "applicant.yaml"
    messy = _messy()
    before = copy.deepcopy(messy)
    A.save(f, messy)
    assert messy == before, "save does not change the dict it was given"
    on_disk = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert on_disk == A.normalise(messy), "the file holds the canonical spellings"
    assert A.load(f) == A.normalise(messy)
    text = f.read_text(encoding="utf-8")
    for typed in ("Non-Binary", "Surname First", "Prefer not to say", "per annum", "Mar 2022",
                  "15/03/2000"):
        assert typed not in text, typed
    assert isinstance(A.load(f)["identity"]["date_of_birth"], str), "dates are saved as text"
    # a second save of what was loaded is byte-for-byte the same file
    first = f.read_bytes()
    A.save(f, A.load(f))
    assert f.read_bytes() == first
    # the folder holds the profile and nothing else (no temp file left behind)
    assert sorted(x.name for x in d.iterdir()) == ["applicant.yaml"]


def test_save_refuses_a_value_that_still_maps_to_nothing_and_writes_nothing():
    d = _tmp()
    f = d / "applicant.yaml"
    p = _messy()
    p["identity"]["gender"] = "zzz-secret"
    p["singapore_status"]["ord_date"] = "someday"
    try:
        A.save(f, p)
    except A.ApplicantError as e:
        assert {x.path for x in e.errors} == {"identity.gender", "singapore_status.ord_date"}
        assert "zzz-secret" not in str(e) and "someday" not in str(e)
    else:
        raise AssertionError("save accepted an invalid profile")
    assert not f.exists() and list(d.iterdir()) == []
    # an existing file is left as it was
    A.save(f, profile())
    good = f.read_bytes()
    try:
        A.save(f, p)
    except A.ApplicantError:
        pass
    assert f.read_bytes() == good


def test_the_shipped_template_saves_and_loads_unchanged():
    d = _tmp()
    f = d / "applicant.yaml"
    tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    A.save(f, tpl)
    assert A.load(f) == tpl
