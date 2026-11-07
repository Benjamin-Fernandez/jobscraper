"""M5 oracles: `questions.capture_page` (Q-35 WP-M5; llm_fill_design §11, §12.1; questions_design
§4.2; D-86 interim).

  - only required fields left UNKNOWN / UNGROUNDED are captured: not optional ones, not FILLED,
    not FILE/HIDDEN (a cover letter is the compose exception, test_llm_fill_probes F9), not
    a transport failure ("transport", "model: unavailable");
  - the reason comes from the guard or lock tag (§11): L4 / work-rights conflict -> conflict;
    G2d/G2e -> no_option_fits; G2 profile_gap with a form path -> profile_gap + target;
    G3/G6/G11 -> ungrounded; L3/L7 -> attestation_unclear (sensitive); other G/E -> no_rule;
    a G7 note makes the row sensitive;
  - a generic label is qualified by its context, so two "Please specify" are two questions;
  - notes and labels never carry a value.
Answers are built directly (the guard behaviour is test_llm_fill_guard_table). Verify:
python tests/run_tests.py -k questions_capture_page
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.questions:capture_page", "jobscraper.apply.questions:page_reason",
         "jobscraper.apply.questions:TRANSPORT_NOTES")


def test_the_capture_oracles_load():
    import llm_fill_t2 as T
    assert T.TODAY


def _ans(key, note, *, status=None, rule_id="", sensitive=False):
    from jobscraper.apply.contracts import Answer, AnswerStatus as AS, AnswerTier
    return Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="", confidence=0.0,
                  status=status or AS.UNKNOWN, rule_id=rule_id, note=note, sensitive=sensitive)


def _capture(fields, answers):
    from jobscraper.apply import questions as Q
    import llm_fill_t2 as T
    return {c.field_key: c for c in Q.capture_page(fields, answers, T.rctx(), T.rules())}


@needs(*NEEDS)
def test_only_required_unanswered_fields_are_captured():
    from jobscraper.apply.contracts import Answer, AnswerStatus as AS, AnswerTier, FieldType as FT
    import test_llm_fill_probes as P
    fields = [P._pf("a", "Describe your final-year project", FT.TEXTAREA),
              P._pf("b", "Describe a hobby", FT.TEXTAREA, required=False),
              P._pf("c", "Portfolio", FT.FILE),
              P._pf("d", "Describe your internship", FT.TEXTAREA),
              P._pf("e", "Describe a challenge", FT.TEXTAREA),
              P._pf("f", "Describe a team you led", FT.TEXTAREA)]
    answers = {"a": _ans("a", "G3: quote not in the source", status=AS.UNGROUNDED),
               "b": _ans("b", "G3: quote not in the source", status=AS.BLANK_OPTIONAL),
               "c": _ans("c", "L1: no file"),
               "d": Answer("d", "Built tools.", AnswerTier.LLM, "llm", 0.8),
               "e": _ans("e", "transport: the model did not answer"),
               "f": _ans("f", "model: unavailable")}
    got = _capture(fields, answers)
    assert set(got) == {"a"}, set(got)
    assert got["a"].reason.value == "ungrounded" and got["a"].required is True


@needs(*NEEDS)
def test_the_reason_follows_the_guard_or_lock_tag():
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import test_llm_fill_probes as P
    cases = {
        "g2d": ("Which office do you prefer?", "G2d: model value differs from the fact", "no_option_fits"),
        "g2e": ("Which campus do you prefer?", "G2e: no_option_fits", "no_option_fits"),
        "g6": ("Describe your internship tasks", "G6: quote outside the entry", "ungrounded"),
        "g12": ("Describe a past team project", "G12: names another employer", "no_rule"),
        "l4": ("Are you authorised to work in Malaysia?", "L4: work rights differ", "conflict"),
        "l7": ("I have never been declared bankrupt", "L7: negated declaration", "attestation_unclear"),
    }
    fields = [P._pf(k, label, FT.TEXTAREA if k in ("g6", "g12") else FT.TEXT) for k, (label, _n, _r) in cases.items()]
    answers = {k: _ans(k, note, status=AS.UNGROUNDED if k == "g6" else AS.UNKNOWN)
               for k, (_l, note, _r) in cases.items()}
    got = _capture(fields, answers)
    for k, (_l, note, reason) in cases.items():
        assert k in got, k
        assert got[k].reason.value == reason, (k, got[k].reason)
        assert got[k].note == note
    assert got["l7"].sensitive is True, "attestation rows are sensitive"


@needs(*NEEDS)
def test_a_g7_row_is_sensitive_and_generic_labels_are_qualified_by_context():
    import test_llm_fill_probes as P
    f1 = P._pf("s1", "Please specify", context="Race")
    f2 = P._pf("s2", "Please specify", context="Do you hold other offers?")
    got = _capture([f1, f2], {"s1": _ans("s1", "G7: sensitive question", sensitive=True),
                              "s2": _ans("s2", "model: unknown")})
    assert got["s1"].sensitive is True and got["s2"].sensitive is False
    assert got["s1"].label_norm != got["s2"].label_norm, "two different questions"
    assert got["s1"].label == got["s2"].label == "Please specify"


@needs(*NEEDS)
def test_a_profile_gap_names_its_form_path():
    from jobscraper.apply import questions as Q
    from jobscraper.apply.contracts import FieldType as FT
    import test_llm_fill_probes as P
    f = P._pf("g", "Address Line 2", FT.TEXT)
    got = _capture([f], {"g": _ans("g", "G2c: profile_gap", rule_id="contact.address_line2")})
    assert got["g"].reason.value == "profile_gap" and got["g"].target_path == "contact.address_line2", \
        (got["g"].reason, got["g"].target_path)
    got = _capture([f], {"g": _ans("g", "G2c: profile_gap", rule_id="profile:not.a.form.path")})
    assert got["g"].reason.value == "no_rule" and got["g"].target_path == ""
    assert Q.TRANSPORT_NOTES and all(isinstance(t, str) for t in Q.TRANSPORT_NOTES)


if WAITING[_W0:]:
    print(f"[test_questions_capture_page] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
