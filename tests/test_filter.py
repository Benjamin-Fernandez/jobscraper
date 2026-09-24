"""Prefilter behaviour: location, titles, experience ceiling.

These carried over from v1's test_core.py unchanged. They guard rules that v2
keeps (PRD section 8.3[3]) and are the regression net for M4-T1, which rewrites
the implementation underneath them.

`test_min_years_takes_the_lowest_stated` is load-bearing: section 8.3[3] adopts
its "lowest stated requirement wins" semantics, so a 2-5 year range passes the
3-year cap while "4+ years" rejects.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import re  # noqa: F401
import tempfile

from jobscraper.config import load_profile
from jobscraper.matching import (location_verdict, min_years_required, stage_a)
from jobscraper.models import Candidate, Company, RawJob, ScoreBreakdown
from jobscraper.store import Store

def _store(n=25):
    db = Path(tempfile.mkdtemp()) / "t.db"
    st = Store(db)
    st.sync_companies([{"ordinal": i, "name": f"C{i}", "tier": "T3",
                        "category": "Fintech", "careers_url": "https://x/careers",
                        "role_type_hint": "SWE"} for i in range(1, n + 1)])
    return st


def test_location_is_default_deny():
    p = load_profile()
    assert location_verdict("Singapore", p) == "singapore"
    assert location_verdict("Singapore, Hong Kong", p) == "singapore"
    for elsewhere in ("Zug, Switzerland", "Aarhus, Central Denmark Region",
                      "Europe", "New York", "London, UK", "Bengaluru"):
        assert location_verdict(elsewhere, p) == "elsewhere", elsewhere
    for vague in ("", "APAC", "Remote", "All Offices", "Multiple Locations"):
        assert location_verdict(vague, p) == "ambiguous", vague

def test_remote_pinned_to_a_region_is_elsewhere():
    """Remote is only vague while it is unqualified.

    A desk we cannot legally occupy is out of reach however remote it is, so a
    region-locked remote posting is rejected like any other foreign location.
    The last case names a city on no deny list: the rule has to fail closed on
    residue, not on enumeration, or the next unlisted city leaks through again.
    """
    p = load_profile()
    for pinned in ("US Remote", "US-Remote", "US - Remote", "US Remote National",
                   "Remote (US)", "Remote-Canada", "EMEA Remote",
                   "SF, NY, Remote", "NYC, SF, Chi, Remote",
                   "Chicago, Atlanta, Remote", "Toronto, Remote-Canada",
                   "Remote - Munich"):
        assert location_verdict(pinned, p) == "elsewhere", pinned

    # Genuinely borderless remote still reaches the model.
    for open_ended in ("Remote (Worldwide)", "Work from anywhere",
                       "Fully Remote", "Remote - APAC"):
        assert location_verdict(open_ended, p) == "ambiguous", open_ended

    # A Singapore desk is not collateral damage when remote is also offered.
    assert location_verdict("Singapore / Remote", p) == "singapore"
    assert location_verdict("Remote - Singapore", p) == "singapore"

def test_stage_a_rejects_and_keeps_the_right_things():
    p = load_profile()
    st = _store(1)
    co = st.all_companies()[0]

    def judge(title, loc="Singapore", desc=""):
        c = Candidate(job_id="x", company=co,
                      raw=RawJob("1", title, "https://x", loc, description=desc))
        return stage_a(c, p), c.filter_reason

    assert judge("Software Engineer")[0]
    assert judge("Graduate Technology Analyst")[0]
    assert judge("Quantitative Developer")[0]
    assert not judge("Senior Software Engineer")[0]
    assert not judge("Software Engineer Intern")[0]
    assert not judge("HR Generalist")[0]
    assert not judge("Software Engineer", loc="New York")[0]
    assert not judge("Software Engineer", desc="Requires 7+ years experience")[0]
    # A vague location survives rather than being guessed away.
    assert judge("Software Engineer", loc="APAC")[0]

def test_min_years_takes_the_lowest_stated():
    assert min_years_required("2+ years preferred, 5 years ideal") == 2
    assert min_years_required("no numbers here") is None


# ==========================================================================
# M4-T1 - the v2 rules engine (filter.py + config/rules.yaml, PRD 8.3[3])
#
# Everything below runs against the real config/rules.yaml, a hand-written
# profile dict of the shape in PRD 0.6 contract 1, and a stub overlap scorer
# (contract 2). filter.py never imports profile/ - the scorer is injected.
# ==========================================================================

import yaml

from jobscraper import filter as F

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"

PROFILE = {
    "profile_version": 1,
    "summary": "New-grad backend engineer.",
    "skills": ["python", "kubernetes", "postgresql", "kafka", "go"],
    "target_titles": ["software engineer", "backend engineer",
                      "site reliability engineer", "platform engineer"],
    "title_aliases": {"sre": "site reliability engineer",
                      "swe": "software engineer"},
    "years_experience": 0,
}

# Enough skills to clear keyword_floor, and no years, so each test isolates the
# one rule it is about.
GOOD_DESC = "You will build Python services on Kubernetes."


def stub_scorer(text, skills):
    low = text.lower()
    hits = [s for s in skills if s in low]
    return len(hits), hits


def _rules(mutate=None):
    """The real rules, optionally edited in memory and re-loaded from a temp file."""
    if mutate is None:
        return F.load_rules(RULES_PATH)
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    mutate(data)
    tmp = Path(tempfile.mkdtemp()) / "rules.yaml"
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return F.load_rules(tmp)


def _rule(data, rule_id):
    return next(r for r in data["rules"] if r["id"] == rule_id)


def judge(title, location="Singapore", desc=GOOD_DESC, rules=None,
          profile=PROFILE, scorer=stub_scorer):
    posting = {"title": title, "location": location, "description": desc}
    return F.evaluate(posting, rules or _rules(), profile, scorer)


def test_filter_location_precedence_d7():
    for loc in ("Remote, Global", "Remote (APAC)", "Hybrid — Austin, US",
                "Work from anywhere", "Zug, Switzerland", "Remote - Bulgaria",
                "Kuala Lumpur, Malaysia"):
        r = judge("Software Engineer", loc)
        assert not r.passed and r.reject_rule == "location_explicit", (loc, r)

    # An allow token wins outright, even against remote (precedence row 1).
    for loc in ("Singapore", "Singapore, Singapore", "SG - Singapore",
                "Remote — Singapore", ""):
        r = judge("Software Engineer", loc)
        assert r.passed, (loc, r)

    # Vague-only strings pass through for the model to read (row 3, D-2).
    for loc in ("APAC", "Global", "Multiple Locations", "All Offices", "Various"):
        assert judge("Software Engineer", loc).passed, loc

    # Remote is checked before the vague list, so APAC cannot rescue it (row 2).
    r = judge("Software Engineer", "Remote (APAC)")
    assert r.reject_detail == "remote", r


def test_filter_title_allow_d10():
    assert judge("Site Reliability Engineer").passed
    assert judge("SRE").passed, "aliases are folded before matching"
    assert judge("Engineer, Software").passed, "token subset, any order"
    assert judge("DevOps / SRE (Platform)").passed
    assert judge("Back-end Engineer").passed, "hyphenated words match joined"

    r = judge("Technical Writer")
    assert not r.passed and r.reject_rule == "title_allow", r


def test_filter_deny_runs_before_allow():
    r = judge("Senior Software Engineer")
    assert not r.passed
    assert r.reject_rule == "title_deny" and r.reject_detail == "senior", r
    # The trace still shows title_allow would have matched: the order decided.
    verdicts = {t.rule_id: t.verdict for t in r.trace}
    assert verdicts["title_allow"] == "pass", r.trace


def test_filter_experience_ceiling_d12_lowest_stated_wins():
    def yrs(text):
        return judge("Software Engineer", desc=f"{GOOD_DESC} {text}")

    r = yrs("Requires 4+ years of experience.")
    assert not r.passed and r.reject_rule == "experience_ceiling", r
    assert "4+ years" in r.reject_detail, r
    assert yrs("Requires 3+ years of experience.").passed
    assert yrs("2-5 years of backend experience.").passed      # floor is 2
    assert yrs("2 to 5 yrs experience.").passed
    assert yrs("2+ years preferred, 5 years ideal.").passed    # v1's own case
    assert not yrs("Minimum 7 years in fintech.").passed
    # The title is read too.
    r = judge("Software Engineer (5+ years)")
    assert r.reject_rule == "experience_ceiling", r


def test_filter_min_years_agrees_with_the_carried_over_semantics():
    """The v2 port and v1's min_years_required must never disagree (PRD 8.3[3])."""
    for text in ("2+ years preferred, 5 years ideal", "no numbers here",
                 "2-5 years", "4+ years", "3 years", "founded 150 years ago",
                 "1 year of Go, 3+ years of Python"):
        assert F.min_years_required(text) == min_years_required(text), text


def test_filter_keyword_floor_uses_the_injected_scorer():
    seen = {}

    def spy(text, skills):
        seen["skills"] = list(skills)
        return stub_scorer(text, skills)

    r = judge("Software Engineer", desc="We use Python.", scorer=spy)
    assert not r.passed and r.reject_rule == "keyword_floor", r
    assert r.overlap_score == 1, r
    assert seen["skills"][:5] == PROFILE["skills"], seen

    r = judge("Software Engineer", desc="Python, Kafka and PostgreSQL.")
    assert r.passed and r.overlap_score == 3, r

    # No description at all is not evidence of a mismatch: leave it to the model.
    r = judge("Software Engineer", desc="")
    assert r.passed and r.overlap_score is None, r


def test_filter_enabled_false_disables_a_rule():
    rules = _rules(lambda d: _rule(d, "title_deny").update(enabled=False))
    r = judge("Senior Software Engineer", rules=rules)
    assert r.passed, r
    assert {t.rule_id: t.verdict for t in r.trace}["title_deny"] == "disabled"


def test_filter_extra_entries_take_effect_without_code():
    assert judge("Solutions Engineer").reject_rule == "title_allow"
    rules = _rules(lambda d: _rule(d, "title_allow").update(
        extra=["solutions engineer"]))
    assert judge("Solutions Engineer", rules=rules).passed

    rules = _rules(lambda d: _rule(d, "title_deny").update(
        extra=[r"\bquant\w*"]))
    r = judge("Quantitative Software Engineer", rules=rules)
    assert r.reject_rule == "title_deny" and r.reject_detail == "quantitative", r

    rules = _rules(lambda d: _rule(d, "keyword_floor").update(extra=["rust"]))
    assert judge("Software Engineer", desc="Rust and Python.", rules=rules).passed


def test_filter_declaration_order_is_evaluation_order():
    def location_first(d):
        loc = _rule(d, "location_explicit")
        d["rules"].remove(loc)
        d["rules"].insert(0, loc)

    r = judge("Senior Software Engineer", "London, UK")
    assert r.reject_rule == "title_deny", r
    r = judge("Senior Software Engineer", "London, UK",
              rules=_rules(location_first))
    assert r.reject_rule == "location_explicit", r
    assert [t.rule_id for t in r.trace][0] == "location_explicit"


def test_filter_trace_covers_every_rule_in_order():
    r = judge("Software Engineer")
    assert r.passed and r.reject_rule is None and r.reject_detail is None
    assert [t.rule_id for t in r.trace] == [x.id for x in _rules().rules]
    assert all(t.verdict == "pass" for t in r.trace), r.trace
    assert "title_deny" in F.render(r) and "PASS" in F.render(r)


def test_filter_rules_hash_is_canonical():
    a = F.load_rules(RULES_PATH)
    assert len(a.hash) == 64 and a.hash == F.load_rules(RULES_PATH).hash

    # Comments and formatting do not change what the rules mean, nor the hash.
    tmp = Path(tempfile.mkdtemp()) / "rules.yaml"
    tmp.write_text("# a comment\n" + RULES_PATH.read_text(encoding="utf-8")
                   + "\n\n# trailing\n", encoding="utf-8")
    assert F.load_rules(tmp).hash == a.hash

    b = _rules(lambda d: _rule(d, "keyword_floor").update(min_overlap=3))
    assert b.hash != a.hash, "a rule edit must invalidate cached verdicts (8.4)"


def test_filter_bad_rules_fail_loudly_at_load():
    def boom(mutate, needle):
        try:
            _rules(mutate)
        except ValueError as exc:
            assert needle in str(exc), (needle, exc)
        else:
            raise AssertionError(f"expected a load error mentioning {needle!r}")

    boom(lambda d: _rule(d, "title_deny").update(kind="nonsense"), "nonsense")
    boom(lambda d: d["rules"].append(dict(_rule(d, "title_deny"))), "duplicate")
    boom(lambda d: _rule(d, "title_deny").update(extra=["(unclosed"]),
         "title_deny")


def test_filter_a_new_rule_kind_is_one_function():
    @F.rule_kind("title_length")
    def _title_length(rule, ctx):
        too_long = len(ctx.title) > rule.spec["max_chars"]
        return F.Outcome("reject" if too_long else "pass", str(len(ctx.title)))

    try:
        rules = _rules(lambda d: d["rules"].append(
            {"id": "short_titles", "kind": "title_length", "max_chars": 20}))
        assert judge("Software Engineer", rules=rules).passed
        r = judge("Software Engineer, Payments Infrastructure", rules=rules)
        assert r.reject_rule == "short_titles", r
    finally:
        F.KINDS.pop("title_length", None)


def test_filter_accepts_objects_as_well_as_dicts():
    raw = RawJob("1", "Backend Engineer", "https://x", "Singapore",
                 description=GOOD_DESC)
    assert F.evaluate(raw, _rules(), PROFILE, stub_scorer).passed
