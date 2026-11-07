"""Q-46 oracles (P0, found live in Q-41 phase 1 on a Workday tenant; queue 06 Q-46 a-c). Scripted
model decisions through `locks.lock_page` + `guards.decide` (no model, no browser); the sample
profile only.

  (a) a work-experience Location never comes from contact/address facts: only that entry's facts
      or its resume entry; with none, the required field ends unknown and the page stops (M9);
  (b) a skill the model lists or a widget picks must match a resume/profile skill (whole word or
      alias) or `attested_skills`, else it is dropped; a duplicate of a kept skill is dropped too;
  (c) "Have you ever worked for the Government ..." is not about this employer: neither the
      prior-employment declaration nor `standing:worked_here` may answer it.
Failing pins name their owner in the docstring (lane M: guards / facts / locks / llm_fill).
Verify: python tests/run_tests.py -k llm_fill_q46
"""
from __future__ import annotations

import copy
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.guards:decide", "jobscraper.apply.facts:entry_blocks",
         "jobscraper.apply.llm_fill:pick_option")

SKILLS_LIST = ["Python", "SQL", "PyTorch", "Raven DB", "HTML Design"]
RESUME_SKILLS = "Python, SQL, PostgreSQL, Git"


def test_the_q46_oracles_load():
    import llm_fill_t2 as T
    assert T.TODAY


def _entry_decide(field, decisions, ctx, gid, entry):
    from jobscraper.apply import facts as F, guards as G, locks
    import llm_fill_t2 as T
    rules = T.rules()
    lk = locks.lock_page([field], ctx, rules, today=T.TODAY, uploaded={})
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    return G.decide([field], lk, decisions, cat, ctx, matches={gid: entry}, second=lambda pf: None,
                    today=T.TODAY, rules=rules, blocks=F.entry_blocks(ctx))


# ------------------------------------------------------------------ (a) entry Location

@needs(*NEEDS)
def test_q46a_an_entry_location_takes_only_its_entrys_facts():
    from jobscraper.apply import facts as F
    from jobscraper.apply.contracts import AnswerStatus as AS
    import llm_fill_t2 as T
    import test_llm_fill_probes as P
    gid = F.group_id("work_experience", 2)
    loc = P._pf("loc", "Location", group=gid, group_title="Work Experience 2")
    ctx = T.rctx()
    d = _entry_decide(loc, [P._md("loc", "profile", "Singapore", ref="profile:contact.city")], ctx, gid, "experience[1]")
    assert d.answers["loc"].status is not AS.FILLED and "loc" in d.unknown_required, d.answers["loc"].note
    d = _entry_decide(loc, [P._md("loc", "profile", "Singapore", ref="profile:experience[1].location")],
                      ctx, gid, "experience[1]")
    assert d.answers["loc"].status is AS.FILLED, "the entry's own location is the source"
    prof = copy.deepcopy(ctx.profile)
    prof["experience"][1]["location"] = ""                     # the entry has no location
    empty = T.rctx(profile=prof)
    for dec in (P._md("loc", "profile", "Singapore", ref="profile:contact.city"),
                P._md("loc", "resume", "Singapore", evidence="Alex Testcase | Singapore"),   # the resume header
                P._md("loc", "job", "Singapore", evidence="Singapore"),
                P._md("loc", "keep", "Singapore", evidence="Singapore")):
        d = _entry_decide(loc, [dec], empty, gid, "experience[1]")
        assert d.answers["loc"].status is not AS.FILLED, (dec.source, d.answers["loc"].note)
        assert "loc" in d.unknown_required, "M9: a required entry field with no source stops the page"


@needs(*NEEDS)
def test_q46a_a_location_in_a_work_experience_section_never_takes_the_home_city():
    """Failing pin (HIGH, fails open: lane M, `guards` G2(a)/(b) + `facts.relevant`). A Location
    the reader did not put in an entry group (no `group`, section "Work Experience", context
    "Company") is filled from `profile:contact.city`: the applicant's home city submitted as a
    past job's location (what Q-41 phase 1 saw live). A field whose section, group title or
    context names a work/education entry must not cite contact/address facts."""
    from jobscraper.apply.contracts import AnswerStatus as AS
    import test_llm_fill_probes as P
    loc = P._pf("loc", "Location", context="Company")
    loc = dataclasses.replace(loc, field=dataclasses.replace(loc.field, section="Work Experience"))
    d, _ = P._decide([loc], [P._md("loc", "profile", "Singapore", ref="profile:contact.city")])
    assert d.answers["loc"].status is not AS.FILLED, (d.answers["loc"].value, d.answers["loc"].note)


# ------------------------------------------------------------------ (b) skills

def _skills_field():
    from jobscraper.apply.contracts import FieldType as FT
    import test_llm_fill_probes as P
    sk = P._pf("s", "Type to Add Skills", FT.MULTI_CHOICE)
    return dataclasses.replace(sk, options_complete=False)        # Workday: a search-driven multiselect


@needs(*NEEDS)
def test_q46b_no_skill_off_the_resume_or_profile_is_ever_filled():
    """Failing pin (HIGH, fails open: lane M, `guards` G3 for MULTI values). A list quoted from
    the resume is grounded as a whole by its evidence, so "PyTorch", "Raven DB" and "HTML Design"
    are filled although no resume line, profile skill or attested skill names them."""
    from jobscraper.apply.contracts import AnswerStatus as AS
    import test_llm_fill_probes as P
    sk = _skills_field()
    for ev in (RESUME_SKILLS, "Python, SQL"):
        dec = P._md("s", "resume", SKILLS_LIST, evidence=ev)
        d, _ = P._decide([sk], [dec], second=lambda pf, dec=dec: dec)    # G5: the second opinion agrees
        a = d.answers["s"]
        if a.status is AS.FILLED:
            bad = {v for v in a.value} - {"Python", "SQL", "PostgreSQL", "Git"}
            assert not bad, f"ungrounded skills filled: {sorted(bad)}"


@needs(*NEEDS)
def test_q46b_ungrounded_and_duplicate_skills_are_dropped_and_the_rest_kept():
    """Failing pin (lane M, guards; queue Q-46 b): the rule is "drop", not "reject the field":
    the grounded skills stay, an unknown one and a near-duplicate of a kept one ("HTML Design"
    after "HTML") go."""
    from jobscraper.apply.contracts import AnswerStatus as AS
    import llm_fill_t2 as T
    import test_llm_fill_probes as P
    prof = copy.deepcopy(T.rctx().profile)
    prof["skills"] = ["Python", "SQL", "PostgreSQL", "Git", "HTML"]
    ctx = T.rctx(profile=prof)
    dec = P._md("s", "resume", ["Python", "HTML", "HTML Design", "PyTorch"], evidence="Python, SQL, PostgreSQL, Git")
    d, _ = P._decide([_skills_field()], [dec], ctx, second=lambda pf: dec)
    a = d.answers["s"]
    assert a.status is AS.FILLED and list(a.value) == ["Python", "HTML"], (a.status, a.value, a.note)


@needs(*NEEDS)
def test_q46b_a_skill_suggestion_must_name_the_wanted_skill():
    """Failing pin (lane M `llm_fill.pick_option`, or lane R's multiselect fill that calls it):
    the model may map "Python" to "Python (Programming Language)", never to "PyTorch"."""
    from jobscraper.apply import llm_fill as L
    import llm_fill_t2 as T
    from llm_fill_support import FakeFillBackend
    opts = ["PyTorch", "Python (Programming Language)"]
    fb = FakeFillBackend(replies=[{"kind": "pick", "repeat": True, "raw": {"choice": "Python (Programming Language)"}}])
    assert L.pick_option(fb, _skills_field(), "Python", opts, s_values=T.secrets()) == opts[1]
    fb = FakeFillBackend(replies=[{"kind": "pick", "repeat": True, "raw": {"choice": "PyTorch"}}])
    assert L.pick_option(fb, _skills_field(), "Python", opts, s_values=T.secrets()) is None, \
        "a suggestion that does not name the skill is no pick"


# ------------------------------------------------------------------ (c) relevance

GOV = "Have you ever worked for the Government (excluding mandatory military service)?"


@needs(*NEEDS)
def test_q46c_worked_here_does_not_answer_a_government_service_question():
    """Failing pin (MEDIUM, right answer on the wrong basis: lane M, `locks` L3 declaration
    match + `facts.relevant`). The prior-employment declaration locks "No" on this label and
    `relevant("standing:worked_here")` is True; neither is about the Government. Expected: the
    field ends unknown (captured) or is answered from a relevant source."""
    from jobscraper.apply import facts as F
    from jobscraper.apply.contracts import FieldType as FT
    import llm_fill_t2 as T
    import test_llm_fill_probes as P
    gov = P._pf("g", GOV, FT.RADIO, options=("Yes", "No"))
    ctx = T.rctx()
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    assert F.relevant("standing:worked_here", gov, T.rules(), facts=cat, rctx=ctx) is False
    d, lk = P._decide([gov], [P._md("g", "standing", "No", ref="standing:worked_here")],
                      second=lambda pf: P._md(pf.field.key, "standing", "No", ref="standing:worked_here"))
    a = d.answers["g"]
    basis = f"{a.source} {a.rule_id}".lower()
    assert "prior_employment" not in basis and "worked_here" not in basis, (a.status, a.source, a.rule_id)


if WAITING[_W0:]:
    print(f"[test_llm_fill_q46] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
