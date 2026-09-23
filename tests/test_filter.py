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
