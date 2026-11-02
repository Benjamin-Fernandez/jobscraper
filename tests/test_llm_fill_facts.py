"""T2 facts oracles (Q-35 WP-T2, lane M WP-M1; llm_fill_design §5, TR-1, TR-5).

  - `today_sg`: 16:30Z on 2 Nov is 3 Nov in Singapore (TR-5);
  - the catalogue never shows an S value: private facts carry no value and `facts_text` holds
    none of the sample S values (TR-1); every ref is unique;
  - `s_values` covers the account email and the phone; `facts_used_hash`-style privacy is the
    store's (test_store_fill_cache).
Skip-clean until `jobscraper.apply.facts` exists. Verify: python tests/run_tests.py -k llm_fill_facts
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.facts:fact_catalogue", "jobscraper.apply.facts:facts_text",
         "jobscraper.apply.facts:s_values", "jobscraper.apply.facts:today_sg")


def test_the_t2_builders_import():
    import llm_fill_t2 as T
    assert T.TODAY == "2026-11-03"


@needs(*NEEDS)
def test_today_is_the_singapore_date_of_an_injected_utc_instant():
    from jobscraper.apply import facts as F
    import llm_fill_t2 as T
    assert F.today_sg(T.NOW) == "2026-11-03"
    assert F.today_sg(T.NOW - 3600) == "2026-11-02", "15:30Z is still the 2nd in Singapore"


@needs(*NEEDS)
def test_the_fact_catalogue_never_shows_an_s_value():
    from jobscraper.apply import facts as F
    from llm_fill_support import find_secrets
    import llm_fill_t2 as T
    ctx = T.rctx()
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    assert cat, "a catalogue for the sample profile"
    refs = [f.ref for f in cat]
    assert len(refs) == len(set(refs)), "refs are unique"
    for f in cat:
        if f.private:
            assert f.value == "", f.ref
    text = F.facts_text(cat)
    assert not find_secrets(text, T.secrets()), "an S value reached FACTS"    # never print values
    assert any(f.ref == "standing:today" and T.TODAY in f.value for f in cat), "standing:today"


@needs(*NEEDS)
def test_s_values_cover_the_account_email_and_the_phone():
    from jobscraper.apply import facts as F
    from apply_flow_support import sample_profile
    p = sample_profile()
    got = {v.lower() for v in F.s_values(p, "alex.backup@example.net")}
    assert "alex.backup@example.net" in got and p["contact"]["email"].lower() in got
    assert any(p["contact"]["phone_number"] in v for v in got)


if WAITING[_W0:]:
    print(f"[test_llm_fill_facts] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
