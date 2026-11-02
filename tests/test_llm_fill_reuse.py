"""T5 oracles for review Q-30 F1 and F4 under D-78 (llm_fill_design §12.1, §12.3; test plan §6 T5).

F1 reuse matrix (lock L6 through `locks.lock_page`, an `extra` answer to a generic label):
  - same employer and same context -> reused (L6 FILLED, `memory:extra.<key>`);
  - same context at another employer -> not reused; another context at the same employer -> not;
  - the entry's base value is never used for a generic label;
  - a context-less generic label at the same employer, step and position -> reused on the retry.
F4: in an all-caps label a bare "US" yields both US and the job's country: equal work rights ->
answered, different -> conflict (no model). Mixed case: "us" stays the pronoun.
Verify: python tests/run_tests.py -k llm_fill_reuse
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.locks:lock_page", "jobscraper.apply.locks:qualified_labels",
         "jobscraper.apply.plan:qualified_label")
F4_NEEDS = ("jobscraper.apply.resolve:label_countries", "jobscraper.applicant:work_rights")

EX, SC = "Example Employer", "Sample Corp"
ANSWER = "One pending offer"


def test_the_reuse_oracles_load():
    import llm_fill_t2 as T
    assert T.TODAY


def _qualified(label, context, *, step="", ordinal=0):
    from jobscraper.apply.plan import qualified_label
    return qualified_label(label, "", context, step=step, ordinal=ordinal)


def _locked(fields, extra: dict, employer: str):
    import dataclasses
    from jobscraper.apply import locks
    import llm_fill_t2 as T
    ctx = T.rctx()
    prof = dict(ctx.profile)
    prof["extra"] = extra
    ctx = dataclasses.replace(ctx, profile=prof, employer_name=employer, employer_aliases=())
    return locks.lock_page(fields, ctx, T.rules(), today=T.TODAY, uploaded={})


def _entry(label_norm, *, base=None, by_employer=None):
    e = {"title": "Please specify", "description": "", "kind": "text", "sensitive": False,
         "labels": [label_norm], "value": base}
    if by_employer is not None:
        e["by_employer"] = by_employer
    return {"offers_detail": e}


def _filled(locked, key):
    from jobscraper.apply.contracts import AnswerStatus as AS
    a = locked.get(key)
    return a is not None and a.status is AS.FILLED and a.value == ANSWER


@needs(*NEEDS)
def test_f1_a_generic_answer_is_reused_only_at_its_employer_with_its_context():
    import test_llm_fill_probes as P
    ctx_text = "Do you hold other offers?"
    q = _qualified("Please specify", ctx_text)
    assert " | " in q, q
    extra = _entry(q, by_employer={"example employer": {"value": ANSWER}})
    same = P._pf("s", "Please specify", context=ctx_text)
    got = _locked([same], extra, EX)
    assert _filled(got, "s"), got.get("s")
    assert got["s"].source == "memory:extra.offers_detail", got["s"].source
    assert not _filled(_locked([same], extra, SC), "s"), "another employer: no reuse"
    other_ctx = P._pf("s", "Please specify", context="Notice period")
    assert not _filled(_locked([other_ctx], extra, EX), "s"), "another context: no reuse"


@needs(*NEEDS)
def test_f1_the_base_value_of_a_generic_entry_is_never_used():
    import test_llm_fill_probes as P
    ctx_text = "Do you hold other offers?"
    extra = _entry(_qualified("Please specify", ctx_text), base=ANSWER)
    got = _locked([P._pf("s", "Please specify", context=ctx_text)], extra, EX)
    assert not _filled(got, "s"), got.get("s")


@needs(*NEEDS)
def test_f1_a_context_less_generic_label_is_reused_at_the_same_step_and_position():
    import dataclasses
    from jobscraper.apply import locks
    import test_llm_fill_probes as P
    a = P._pf("a", "Please specify")
    b = P._pf("b", "Please specify")
    a = dataclasses.replace(a, field=dataclasses.replace(a.field, step="Questions"))
    b = dataclasses.replace(b, field=dataclasses.replace(b.field, step="Questions"))
    quals = locks.qualified_labels([a, b])
    assert quals["a"] != quals["b"], "two context-less generic labels on one step are two questions"
    extra = _entry(quals["b"], by_employer={"example employer": {"value": ANSWER}})
    got = _locked([a, b], extra, EX)                          # the retry: same step, same order
    assert _filled(got, "b") and not _filled(got, "a"), (got.get("a"), got.get("b"))
    assert not _filled(_locked([a, b], extra, SC), "b")


@needs(*F4_NEEDS)
def test_f4_an_all_caps_us_reads_as_both_the_us_and_the_jobs_country():
    from jobscraper.apply import resolve as R
    up = "ARE YOU AUTHORIZED TO WORK IN THE US?"
    assert R.label_countries("are you authorized to work in the us", up, "SG") == {"US", "SG"}
    mixed = "Are you authorised to work for us?"
    assert "US" not in R.label_countries("are you authorised to work for us", mixed, "SG"), \
        "mixed case: 'us' stays the pronoun"


@needs(*F4_NEEDS)
def test_f4_all_caps_us_answers_when_rights_agree_and_is_a_conflict_when_they_differ():
    from jobscraper.apply.contracts import AnswerStatus as AS
    from questions_support import D75_RULES, StubBackend, chosen, resolve_one, with_work_rights, yes_no
    label = "ARE YOU AUTHORIZED TO WORK IN THE US?"
    be = StubBackend([{"choice": 0, "evidence": "x"}] * 4)
    agree = with_work_rights({"SG": True, "US": True}, {"SG": False, "US": False})
    a = resolve_one(yes_no("q", label), agree, D75_RULES, backend=be, job_country="SG")
    assert a.status is AS.FILLED and chosen(a) == ("Yes",), (a.status, a.note)
    differ = with_work_rights({"SG": True, "US": False}, {"SG": False})
    a = resolve_one(yes_no("q", label), differ, D75_RULES, backend=be, job_country="SG")
    assert a.status is AS.UNKNOWN and "work rights differ" in a.note, (a.status, a.note)
    assert be.calls == [], "D-75: never the model"


if WAITING[_W0:]:
    print(f"[test_llm_fill_reuse] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
