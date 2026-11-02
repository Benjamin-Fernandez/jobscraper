"""T2 guard oracles (Q-35 WP-T2, lane M WP-M3; llm_fill_design §7, §10; lane M/R Decision shape).

  - `guards.Decision(answers, unknown_required, deletes, adds, resets)`, defaults empty;
  - G9 notes and `reset_action` round-trip; `UNVERIFIED_NOTE`;
  - a lock is final: `decide` keeps the lock answer although the model replied otherwise;
  - G1/G10: a required field with no decision is unknown and listed in `unknown_required`.
Skip-clean until `jobscraper.apply.guards` exists. Verify: -k llm_fill_guards
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.guards:decide", "jobscraper.apply.guards:Decision",
         "jobscraper.apply.guards:G9_NOTES", "jobscraper.apply.guards:reset_action",
         "jobscraper.apply.locks:lock_page", "jobscraper.apply.facts:fact_catalogue")


def test_the_guards_oracles_file_loads():
    import llm_fill_t2 as T
    assert T.TODAY


@needs(*NEEDS)
def test_the_decision_shape_and_the_g9_notes():
    import dataclasses
    from jobscraper.apply import guards as G
    from jobscraper.apply.contracts import Answer, AnswerTier
    assert [f.name for f in dataclasses.fields(G.Decision)] == [
        "answers", "unknown_required", "deletes", "adds", "resets"]
    d = G.Decision()
    assert d.answers == {} and d.unknown_required == d.deletes == d.adds == d.resets == ()
    assert set(G.G9_NOTES) == {"clear", "reset", "untick"}
    for action, note in G.G9_NOTES.items():
        assert G.reset_action(Answer("k", None, AnswerTier.LLM, "llm", 0.0, note=note)) == action
    assert G.reset_action(Answer("k", "x", AnswerTier.LLM, "llm", 0.9)) == ""
    assert G.UNVERIFIED_NOTE == "unverified site value"


@needs(*NEEDS)
def test_a_lock_is_final_and_a_required_field_without_a_decision_stops_the_page():
    from jobscraper.apply import facts as F, guards as G, locks
    from jobscraper.apply.contracts import FieldType as FT, FillSource, ModelDecision
    import llm_fill_t2 as T
    ctx = T.rctx()
    fields = [T.pf("k-email", "Email Address", FT.EMAIL, required=True),
              T.pf("k-why", "Why do you want to work here?", FT.TEXTAREA, required=True)]
    rules = T.rules()
    lk = locks.lock_page(fields, ctx, rules, today=T.TODAY, uploaded={})
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    wrong = [ModelDecision(field_key="k-email", source=FillSource.JOB, value="someone@else.example", evidence="x")]
    d = G.decide(fields, lk, wrong, cat, ctx, matches={}, second=lambda pf: None, today=T.TODAY,
                 rules=rules)
    assert d.answers["k-email"].value == T.EMAIL, "the model can't override a lock"
    assert "k-why" in d.unknown_required, "G1/G10: no decision for a required field"
    assert "k-email" not in d.unknown_required


if WAITING[_W0:]:
    print(f"[test_llm_fill_guards] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
