"""Prefilter behaviour: location, titles, experience ceiling (PRD 8.3[3]).

The first four tests are v1's, ported onto the v2 engine at M9-T1 when v1's
matching.py retired. Every case that still holds under v2's decisions is kept.
The ones that changed did so deliberately: D-7 rejects *every* Remote not
naming Singapore (v1 sent "Remote (Worldwide)" to the model), and D-10's
title allow-list rejects titles like "Quantitative Developer" that are not
among the resume's target titles (v1 kept them).

`test_min_years_takes_the_lowest_stated` is load-bearing: section 8.3[3] adopts
its "lowest stated requirement wins" semantics, so a 2-5 year range passes the
3-year cap while "4+ years" rejects.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tempfile

import yaml

from jobscraper import filter as F
from jobscraper.models import RawJob


def _location(loc: str) -> str:
    """'pass' or 'reject' from the location rule alone, on a clean posting."""
    r = judge("Software Engineer", location=loc)
    if r.reject_rule == "location_explicit":
        return "reject"
    assert r.passed, (loc, r.reject_rule)
    return "pass"


def test_location_is_default_deny():
    for sg in ("Singapore", "Singapore, Hong Kong"):
        assert _location(sg) == "pass", sg
    for elsewhere in ("Zug, Switzerland", "Aarhus, Central Denmark Region",
                      "Europe", "New York", "London, UK", "Bengaluru"):
        assert _location(elsewhere) == "reject", elsewhere
    # Vague or blank goes to the model (D-2) ...
    for vague in ("", "APAC", "All Offices", "Multiple Locations"):
        assert _location(vague) == "pass", vague
    # ... but bare "Remote" no longer does (D-7).
    assert _location("Remote") == "reject"


def test_remote_pinned_to_a_region_is_elsewhere():
    """A region-locked remote desk is out of reach, like any foreign location.

    "Remote - Munich" names a city on no deny list: the rule has to fail closed
    on residue, not on enumeration, or the next unlisted city leaks through.
    """
    for pinned in ("US Remote", "US-Remote", "US - Remote", "US Remote National",
                   "Remote (US)", "Remote-Canada", "EMEA Remote",
                   "SF, NY, Remote", "NYC, SF, Chi, Remote",
                   "Chicago, Atlanta, Remote", "Toronto, Remote-Canada",
                   "Remote - Munich"):
        assert _location(pinned) == "reject", pinned
    # D-7: borderless remote is rejected too - v1 sent these to the model.
    for open_ended in ("Remote (Worldwide)", "Work from anywhere",
                       "Fully Remote", "Remote - APAC"):
        assert _location(open_ended) == "reject", open_ended
    # A Singapore desk is not collateral damage when remote is also offered.
    assert _location("Singapore / Remote") == "pass"
    assert _location("Remote - Singapore") == "pass"


def test_stage_a_rejects_and_keeps_the_right_things():
    """v1's stage_a cases, as the v2 rule chain."""
    assert judge("Software Engineer").passed
    assert not judge("Senior Software Engineer").passed
    assert not judge("Software Engineer Intern").passed
    assert not judge("HR Generalist").passed
    assert not judge("Software Engineer", location="New York").passed
    assert not judge("Software Engineer",
                     desc="Requires 7+ years experience with Python on Kubernetes").passed
    # A vague location survives rather than being guessed away.
    assert judge("Software Engineer", location="APAC").passed
    # D-10: not a target title, so no longer kept (v1 kept both).
    assert judge("Graduate Technology Analyst").reject_rule == "title_allow"
    assert judge("Quantitative Developer").reject_rule == "title_allow"


def test_min_years_takes_the_lowest_stated():
    assert F.min_years_required("2+ years preferred, 5 years ideal") == 2
    assert F.min_years_required("no numbers here") is None


# ==========================================================================
# M4-T1 - the v2 rules engine (filter.py + config/rules.yaml, PRD 8.3[3])
#
# Everything below runs against the real config/rules.yaml, a hand-written
# profile dict of the shape in PRD 0.6 contract 1, and a stub overlap scorer
# (contract 2). filter.py never imports profile/ - the scorer is injected.
# ==========================================================================

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
    """The v2 port must agree with v1's min_years_required (PRD 8.3[3]).

    v1's function retired with matching.py at M9-T1; these are its answers,
    captured from it on 2026-09-24 just before it was archived.
    """
    v1_answers = {"2+ years preferred, 5 years ideal": 2, "no numbers here": None,
                  "2-5 years": 2, "4+ years": 4, "3 years": 3,
                  "founded 150 years ago": None,
                  "1 year of Go, 3+ years of Python": 1}
    for text, expected in v1_answers.items():
        assert F.min_years_required(text) == expected, text


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


# --------------------------------------------------------------------------
# M4-T1b - `filter test`: a dry run with no scrape and no database
# --------------------------------------------------------------------------

def _cli(*argv):
    import contextlib
    import io

    from jobscraper import cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_filter_cli_test_names_the_deciding_rule_and_token():
    code, out, _err = _cli("filter", "test", "--title", "Senior Backend Engineer",
                           "--location", "Singapore")
    assert code == 0, out
    assert "REJECT by title_deny: senior" in out, out
    assert "deciding rule" in out, out


def test_filter_cli_test_runs_against_a_draft_rules_file():
    rules = _rules(lambda d: _rule(d, "title_deny").update(enabled=False))
    code, out, _err = _cli("filter", "test", "--title", "Senior Backend Engineer",
                           "--location", "Remote, Global",
                           "--rules", str(rules.path))
    assert code == 0 and "REJECT by location_explicit: remote" in out, out


def _explain_env():
    """A throwaway v2 database, derived profile and config, wired together."""
    from jobscraper.store import Store as StoreV2

    tmp = Path(tempfile.mkdtemp())
    (tmp / "profile.derived.yaml").write_text(
        yaml.safe_dump(PROFILE), encoding="utf-8")
    cfg = tmp / "config.yaml"
    cfg.write_text(yaml.safe_dump({"paths": {
        "db": str(tmp / "v2.db"), "rules": str(RULES_PATH),
        "profile": str(tmp / "profile.derived.yaml")}}), encoding="utf-8")

    st = StoreV2(tmp / "v2.db")
    cid = st.insert_company("acme", "Acme", "https://acme/careers")
    raw = RawJob("7", "Senior Site Reliability Engineer", "https://acme/jobs/7",
                 "Remote (APAC)", description="Needs 5+ years with Kubernetes.")
    st.upsert_job("job7", cid, raw, 1, True)
    st.commit()
    rules = _rules()
    st.save_prefilter("job7", 1, rules.hash, False, "title_deny", "senior")
    st.close()
    return cfg


def test_filter_cli_explain_shows_every_rule_for_a_stored_posting():
    cfg = _explain_env()
    code, out, _err = _cli("--config", str(cfg), "filter", "explain", "job7")
    assert code == 0, out
    assert "Senior Site Reliability Engineer" in out and "Acme" in out, out
    assert "stored    REJECT by title_deny: senior" in out, out
    # The live trace names every rule, not just the one that decided.
    for rule_id, token in (("title_deny", "senior"),
                           ("location_explicit", "remote"),
                           ("experience_ceiling", "5+ years")):
        line = next(ln for ln in out.splitlines() if ln.strip().startswith(rule_id))
        assert "REJECT" in line and token in line, line
    # A posting URL works as well as its id.
    code, out, _err = _cli("--config", str(cfg), "filter", "explain",
                           "https://acme/jobs/7")
    assert code == 0 and "job7  Acme" in out, out


def test_filter_cli_explain_unknown_job_is_a_clear_error():
    cfg = _explain_env()
    code, _out, err = _cli("--config", str(cfg), "filter", "explain", "nope")
    assert code == 1 and "no posting" in err, err
