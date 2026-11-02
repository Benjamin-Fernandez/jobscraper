"""T2 guard table, part 2 (Q-35 WP-T2; llm_fill_design §7 G8, G9, G11, §10 E2, E5, E6; test plan
§4). Scripted decisions through `locks.lock_page` + `guards.decide`; sample profile only.

  G8  a MyGreenhouse `keep` on a TEXT field is trusted; the same `keep` of a resume-import value
      on a required field needs G3; a TEXTAREA keep always needs G3;
  G9  optional leftovers from the site: TEXT cleared ("G9: clear"), a pre-ticked box unticked;
  G11 an entry title holding the employer is a recheck target and not filled as is;
  E2/E5 a source entry with no site entry is added; E6 an unmatched optional entry is deleted.
Verify: python tests/run_tests.py -k guard_table
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.guards:decide", "jobscraper.apply.guards:recheck_targets",
         "jobscraper.apply.guards:G9_NOTES", "jobscraper.apply.facts:entry_blocks")


def test_the_entry_guard_table_loads():
    import llm_fill_t2 as T
    assert T.TODAY


def _P():
    import test_llm_fill_probes as P
    return P


def _run(fields, decisions, *, matches=None, sections=(), ctx=None):
    from jobscraper.apply import facts as F, guards as G, locks
    import llm_fill_t2 as T
    ctx = ctx or T.rctx()
    rules = T.rules()
    lk = locks.lock_page(fields, ctx, rules, today=T.TODAY, uploaded={})
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    return G.decide(fields, lk, decisions, cat, ctx, matches=matches or {}, second=lambda pf: None,
                    today=T.TODAY, rules=rules, sections=list(sections), blocks=F.entry_blocks(ctx))


@needs(*NEEDS)
def test_g8_trusted_prefill_is_kept_and_an_untrusted_one_needs_grounding():
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT, ValueOrigin as VO
    P = _P()
    mg = P._pf("t", "Preferred first name", shown="Alex", origin=VO.MYGREENHOUSE)
    d = _run([mg], [P._md("t", "keep", "Alex")])
    assert d.answers["t"].status in (AS.FILLED, AS.PREFILLED), (d.answers["t"].status, d.answers["t"].note)
    ri = P._pf("c", "Current company", shown="Nowhere Holdings", origin=VO.RESUME_IMPORT)
    d = _run([ri], [P._md("c", "keep", "Nowhere Holdings")])
    assert d.answers["c"].status not in (AS.FILLED, AS.PREFILLED), "D-83: a required import kept only after G3"
    ta = P._pf("w", "Tell us about yourself", FT.TEXTAREA, shown="I founded Nowhere Holdings.", origin=VO.MYGREENHOUSE)
    d = _run([ta], [P._md("w", "keep", "I founded Nowhere Holdings.")])
    assert d.answers["w"].status not in (AS.FILLED, AS.PREFILLED), "a TEXTAREA keep needs G3"


@needs(*NEEDS)
def test_g9_optional_site_leftovers_are_cleared_or_unticked():
    from jobscraper.apply import guards as G
    from jobscraper.apply.contracts import FieldType as FT, ValueOrigin as VO
    P = _P()
    web = P._pf("w", "Website", required=False, shown="https://junk.example", origin=VO.RESUME_IMPORT)
    box = P._pf("b", "Send me marketing emails", FT.CHECKBOX, required=False, shown="true", origin=VO.SITE_DEFAULT)
    d = _run([web, box], [P._md("w", "unknown", ""), P._md("b", "unknown", "")])
    assert "w" in d.resets and G.reset_action(d.answers["w"]) == "clear", (d.resets, d.answers["w"].note)
    assert "b" in d.resets and G.reset_action(d.answers["b"]) == "untick", (d.resets, d.answers["b"].note)


@needs(*NEEDS)
def test_g11_an_entry_title_holding_the_employer_is_rechecked_not_filled():
    from jobscraper.apply import facts as F, guards as G
    from jobscraper.apply.contracts import AnswerStatus as AS
    import llm_fill_t2 as T
    P = _P()
    gid = F.group_id("work_experience", 1)
    title = P._pf("t", "Job Title", group=gid, group_title="Work Experience 1")
    bad = "Software Engineering Intern, Example Logistics Pte Ltd"
    decs = [P._md("t", "resume", bad, evidence=bad)]
    ctx = T.rctx()
    targets = G.recheck_targets([title], decs, {gid: "experience[0]"}, ctx, blocks=F.entry_blocks(ctx))
    assert "t" in list(targets), targets
    d = _run([title], decs, matches={gid: "experience[0]"})
    assert not (d.answers["t"].status is AS.FILLED and d.answers["t"].value == bad), d.answers["t"].note


@needs(*NEEDS, "jobscraper.apply.contracts:EntrySection")
def test_e5_a_missing_entry_is_added_and_e6_an_unmatched_optional_entry_is_deleted():
    from jobscraper.apply import facts as F
    from jobscraper.apply.contracts import EntryGroup, EntrySection
    P = _P()
    g1 = F.group_id("work_experience", 1)
    t1 = P._pf("t1", "Job Title", group=g1, group_title="Work Experience 1", shown="Software Engineering Intern")
    sec = EntrySection(section="work_experience", title="Work Experience", add_locator="[data-add]",
                       entries=(EntryGroup("work_experience", 1, "Work Experience 1", "[data-e1]", "[data-d1]"),))
    d = _run([t1], [], matches={g1: "experience[0]"}, sections=[sec])
    assert any(s == "work_experience" and e == "experience[1]" for s, e in d.adds), d.adds
    g2 = F.group_id("work_experience", 2)
    t2 = P._pf("t2", "Job Title", required=False, group=g2, group_title="Work Experience 2", shown="Juggler")
    sec2 = EntrySection(section="work_experience", title="Work Experience", add_locator="[data-add]",
                        entries=(EntryGroup("work_experience", 1, "Work Experience 1", "[data-e1]", "[data-d1]"),
                                 EntryGroup("work_experience", 2, "Work Experience 2", "[data-e2]", "[data-d2]")))
    ok = P._md("t1", "profile", "Software Engineering Intern", ref="profile:experience[0].title")
    d = _run([t1, t2], [ok], matches={g1: "experience[0]", g2: None}, sections=[sec2])
    assert g2 in d.deletes and g1 not in d.deletes, d.deletes


if WAITING[_W0:]:
    print(f"[test_llm_fill_guard_table_entries] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
