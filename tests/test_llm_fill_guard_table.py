"""T2 guard table (Q-35 WP-T2; llm_fill_design §7, §10; test plan §4). Each case runs one page
through `locks.lock_page` + `guards.decide` with scripted ModelDecisions (no model, no browser).

  G1  a value that is no option -> unknown "G1"; a required field with no decision -> unknown;
      a decision for an id not on the page is ignored;
  G2  a ref outside the catalogue -> unknown "G2"; a cited fact whose model value is empty or
      equal -> the program's value (CONF_FACT); a different model value -> unknown "G2d";
  G3  a resume value not in the resume -> UNGROUNDED "G3"; a grounded one -> FILLED, LLM,
      rule_id RULE_ID, evidence kept;
  G4  an option with no token in common with its quote -> not written "G4";
  G5  a Yes/No from the resume (required or optional, LF §7): a disagreeing second opinion ->
      unknown; an agreeing one -> FILLED CONF_MODEL_CHECKED;
  G7  `sensitive_label` whole words ("Religion" yes, "Sussex" / "embrace" no);
  G10 required unknowns listed in page order;
  E3  an entry group with no source entry (junk) is deleted, its fields SKIPPED, not unknown.
Verify: python tests/run_tests.py -k llm_fill_guard_table
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.guards:decide", "jobscraper.apply.guards:RULE_ID",
         "jobscraper.apply.facts:hash_key")


def test_the_guard_table_loads():
    import llm_fill_t2 as T
    assert T.TODAY


def _h():
    import test_llm_fill_probes as P
    return P


@needs(*NEEDS)
def test_g1_non_option_no_reply_and_stray_ids():
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    P = _h()
    office = P._pf("o", "Preferred office", FT.DROPDOWN, options=("North", "South"))
    langs = P._pf("l", "Which programming languages do you know?", FT.TEXTAREA)
    d, _ = P._decide([office, langs], [P._md("o", "job", "East", evidence="Python"),
                                       P._md("zz", "job", "x", evidence="Python")])
    assert d.answers["o"].status is AS.UNKNOWN and d.answers["o"].note.startswith("G1"), d.answers["o"].note
    assert d.answers["l"].status is AS.UNKNOWN, "no decision for a required field"
    assert "zz" not in d.answers
    assert list(d.unknown_required) == ["o", "l"], "G10: page order"


@needs(*NEEDS)
def test_g2_refs_outside_the_catalogue_fail_and_a_fact_takes_the_programs_value():
    from jobscraper.apply import guards as G
    from jobscraper.apply.contracts import AnswerStatus as AS
    P = _h()
    city = P._pf("c", "City")
    d, lk = P._decide([city], [P._md("c", "profile", "Singapore", ref="profile:nope.path")])
    assert "c" not in lk
    assert d.answers["c"].status is AS.UNKNOWN and d.answers["c"].note.startswith("G2"), d.answers["c"].note
    for model_value in ("", "singapore"):                   # empty or equal (normalised): the program's value
        d, _ = P._decide([city], [P._md("c", "profile", model_value, ref="profile:contact.city")])
        a = d.answers["c"]
        assert a.status is AS.FILLED and a.value == "Singapore" and a.confidence == G.CONF_FACT, (a.value, a.note)
    d, _ = P._decide([city], [P._md("c", "profile", "Atlantis", ref="profile:contact.city")])
    a = d.answers["c"]                                       # LF §7 G2(d): a disagreement is unknown, never "program wins"
    assert a.status is AS.UNKNOWN and a.note.startswith("G2d"), (a.status, a.note)


@needs(*NEEDS)
def test_g2d_a_model_value_naming_the_fitted_option_by_its_leaf_is_the_programs_value():
    """Failing pin (MEDIUM, fails closed): G1's `option_for` reads "Company careers website" as
    the option "Online > Company careers website" (its leaf), and that is also the fact's own
    value, but G2(d)'s non-enum branch compares the raw model value with the program's option
    (`same_value(mv, pv)`, no `option_for`), so the how-heard question stops the application as
    unknown "G2d". The enum branch already normalises with `option_for`."""
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    P = _h()
    opts = ("Online > Company careers website", "Online > LinkedIn", "Referral > Employee")
    hh = P._pf("h", "How did you hear about us?", FT.DROPDOWN, options=opts)
    for mv in ("", "Online > Company careers website", "Company careers website"):
        d, _ = P._decide([hh], [P._md("h", "standing", mv, ref="standing:how_heard")])
        a = d.answers["h"]
        assert a.status is AS.FILLED and a.value == opts[0], (mv, a.status, a.note)
    d, _ = P._decide([hh], [P._md("h", "standing", "LinkedIn", ref="standing:how_heard")])
    assert d.answers["h"].status is AS.UNKNOWN, "another option is still a disagreement"


@needs(*NEEDS)
def test_g3_grounding():
    from jobscraper.apply import guards as G
    from jobscraper.apply.contracts import AnswerStatus as AS, AnswerTier, FieldType as FT
    P = _h()
    q = P._pf("q", "Describe a project you built", FT.TEXTAREA)
    d, _ = P._decide([q], [P._md("q", "resume", "Built a Rust compiler.", evidence="Built a Rust compiler.")])
    assert d.answers["q"].status is AS.UNGROUNDED and d.answers["q"].note.startswith("G3"), d.answers["q"].note
    line = "Automated weekly reports with SQL and Python."
    d, _ = P._decide([q], [P._md("q", "resume", line, evidence=line)])
    a = d.answers["q"]
    assert a.status is AS.FILLED and a.tier is AnswerTier.LLM and a.rule_id == G.RULE_ID, (a.status, a.note)
    assert a.value == line and a.evidence


@needs(*NEEDS)
def test_g3_compose_accepts_a_verbatim_resume_line_that_names_c_plus_plus():
    """Failing pin (LOW, fails closed; `resolve.grounded` text rules, used by G3's compose
    rule): a verbatim resume line containing "C++" is rejected with "word C", so a "why"
    answer naming C++ / C# goes to the Questions inbox although it is grounded."""
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    P = _h()
    q = P._pf("q", "Describe a project you built", FT.TEXTAREA)
    line = "Campus Robot League - built a line-following robot in C++ for the university league."
    d, _ = P._decide([q], [P._md("q", "resume", line, evidence=line)])
    assert d.answers["q"].status is AS.FILLED, d.answers["q"].note


@needs(*NEEDS)
def test_g4_an_option_needs_a_token_in_its_quote():
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    P = _h()
    lvl = P._pf("v", "Python proficiency", FT.DROPDOWN, required=False, options=("Beginner", "Advanced"))
    d, _ = P._decide([lvl], [P._md("v", "resume", "Advanced", evidence="Python, SQL, PostgreSQL, Git")])
    a = d.answers["v"]
    assert a.status is not AS.FILLED and a.note.startswith("G4"), (a.status, a.note)


@needs(*NEEDS)
def test_g5_a_required_yes_no_from_the_resume_needs_an_agreeing_second_opinion():
    from jobscraper.apply import guards as G
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    P = _h()
    yn = P._pf("y", "Do you have experience with SQL?", FT.RADIO, options=("Yes", "No"))
    quote = "Automated weekly reports with SQL and Python."
    asked: list[str] = []

    def second(answer):
        def f(pf):
            asked.append(pf.field.key)
            return P._md(pf.field.key, "resume", answer, evidence=quote)
        return f
    d, _ = P._decide([yn], [P._md("y", "resume", "Yes", evidence=quote)], second=second("No"))
    assert d.answers["y"].status is not AS.FILLED and asked == ["y"], (d.answers["y"].status, d.answers["y"].note)
    asked.clear()
    d, _ = P._decide([yn], [P._md("y", "resume", "Yes", evidence=quote)], second=second("Yes"))
    a = d.answers["y"]
    assert a.status is AS.FILLED and a.value == "Yes" and a.confidence == G.CONF_MODEL_CHECKED, (a.status, a.note)
    asked.clear()
    opt = P._pf("y2", "Do you have experience with SQL?", FT.RADIO, required=False, options=("Yes", "No"))
    d, _ = P._decide([opt], [P._md("y2", "resume", "Yes", evidence=quote)], second=second("No"))
    assert asked == ["y2"], "LF §7 G5: every model-chosen Yes/No, optional too"
    assert d.answers["y2"].status is not AS.FILLED


@needs(*NEEDS)
def test_g7_sensitive_labels_match_whole_words():
    from jobscraper.apply import guards as G
    P = _h()
    assert G.sensitive_label(P._pf("a", "Religion")) is True
    assert G.sensitive_label(P._pf("b", "What is your gender?")) is True
    assert G.sensitive_label(P._pf("c", "Preferred office: Sussex or London?")) is False
    assert G.sensitive_label(P._pf("d", "How do you embrace change?")) is False


@needs(*NEEDS, "jobscraper.apply.contracts:EntrySection")
def test_e3_a_junk_entry_is_deleted_and_its_fields_are_skipped():
    from jobscraper.apply import facts as F, guards as G, locks
    from jobscraper.apply.contracts import AnswerStatus as AS, EntryGroup, EntrySection
    import llm_fill_t2 as T
    P = _h()
    gid = F.group_id("work_experience", 3)
    t = P._pf("t", "Job Title", group=gid, group_title="Work Experience 3")
    c = P._pf("co", "Company", group=gid, group_title="Work Experience 3")
    sec = EntrySection(section="work_experience", title="Work Experience", add_locator="[data-add]",
                       entries=(EntryGroup("work_experience", 3, "Work Experience 3", "[data-e3]", "[data-d3]"),))
    ctx = T.rctx()
    rules = T.rules()
    fields = [t, c]
    lk = locks.lock_page(fields, ctx, rules, today=T.TODAY, uploaded={})
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    d = G.decide(fields, lk, [], cat, ctx, matches={gid: None}, second=lambda pf: None, today=T.TODAY,
                 rules=rules, sections=[sec])
    assert gid in d.deletes, d.deletes
    assert d.answers["t"].status is AS.SKIPPED and d.answers["t"].note.startswith("E3"), d.answers["t"].note
    assert not set(d.unknown_required) & {"t", "co"}


if WAITING[_W0:]:
    print(f"[test_llm_fill_guard_table] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
