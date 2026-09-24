"""ATS discovery: does this board really belong to this company?

Carried over from v1 unchanged. Discovery is REUSE in PRD section 9 - these are
the tests that let M3-T2 move the module without fear.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper.scrape import discovery as D

def test_aggregator_urls_never_yield_a_slug():
    """Mathrix once became LinkedIn because its careers URL was a LinkedIn page."""
    agg = "https://www.linkedin.com/company/mathrix/jobs/"
    assert D.is_aggregator(agg)
    assert D.domain_slug(agg) is None
    assert D.domain_slug("https://www.hudsonrivertrading.com/careers/") ==         "hudsonrivertrading"

def test_board_must_corroborate_the_company_name():
    # anyone can register google.recruitee.com
    assert not D.corroborates("Meta", "Facebook Data", "meta")
    assert not D.corroborates("Mathrix", "LinkedIn", "linkedin")
    assert D.corroborates("Jane Street", "Jane Street", "janestreet")
    assert D.corroborates("IMC Trading", "IMC", "imc")

def test_slug_alone_corroborates_when_the_ats_reports_no_name():
    assert D.corroborates("Virtu Financial", None, "virtu")
    assert not D.corroborates("Mathrix", None, "linkedin")

def test_demo_boards_are_rejected():
    assert D._all_samples(["Senior Marketer (Sample)"])
    assert D._all_samples(["Test Job", "Your first job"])
    assert not D._all_samples(["Software Engineer", "Sample Analyst"])
    assert not D._all_samples([])
