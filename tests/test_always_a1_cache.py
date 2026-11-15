"""Q-121 Amendment A1, pin group 28 (design 17.3, 17.7 (28); R10): the fill cache under `always`.

A cached row stores the field's class and `always:v2`; a row with no class, a bad class or another
prompt version is a MISS (the field is asked again), never a code-only replay; replay under
`always` is still OFF (`_always_steps` never reads the cache), so the replay is pinned through the
miss cases and through the two-key rule applied to a restored decision. No model, no network, no
browser: `fill_page_always(classes=...)` with the scripted fake, `_always_cache_put` on a stub run.
Verify: python tests/run_tests.py -k always_a1_cache
"""
from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, TODAY, YN, FakeAsk, lie, pick_by, report, say, _pf, _profile, _run)

CONFLICT = "Do you declare any conflict of interest?"


def _page():
    return [_pf("pep", "Are you a politically exposed person?", options=YN),
            _pf("city", "Location (City)", "TEXT"),
            _pf("conf", CONFLICT, options=YN)]


def _classes_run(ask):
    classes: dict = {}
    out = _run(_page(), ask, classes=classes)
    return out, classes


def test_g28_fill_page_always_reports_the_models_class_else_the_code_key_for_every_answered_field():
    ask = FakeAsk(lambda v: {"pep": say("No", "default", "default:no_declaration", klass="declaration:pep"),
                             "city": say("Singapore", "profile", "profile:contact.city", klass="ordinary"),
                             "conf": say("No", "default", "default:no_declaration", klass=NO_CLASS)}[v["id"]])
    _out, classes = _classes_run(ask)
    assert classes.get("pep") == "declaration:pep", classes            # the model's own class
    assert classes.get("city") == "ordinary", classes
    # no class in the reply (a cut schema): the code key's, never a missing entry
    assert classes.get("conf") == "declaration:conflict_audit_independence", classes


def _rows_of(out, classes):
    """The rows `pagefill._always_cache_put` writes for this page (a stub run, no browser)."""
    import llm_fill_t2 as T
    from jobscraper.apply import always as AL, briefing as BR, pagefill as P
    p = _profile()
    r = T.rctx(p)
    fields = _page()
    run = types.SimpleNamespace(
        al=types.SimpleNamespace(brief=BR.build(p, r, today=TODAY), model_keys={pf.field.key for pf in fields},
                                 corrected=set(), fb={}, classes=dict(classes)),
        cfg={}, rctx=r, fields={pf.field.key: pf for pf in fields}, order=[pf.field.key for pf in fields],
        answers=dict(out.answers), failed={}, today=TODAY, qv=[], ctx=types.SimpleNamespace(job={"job_id": "job-1"}),
        services=types.SimpleNamespace(model="m-test", cache_put=lambda job_id, rows: captured.append((job_id, rows))))
    captured: list = []
    P._always_cache_put(run)
    return [row for _jid, rows in captured for row in rows]


def _good_ask():
    # U9: "Do you declare any conflict of interest?" is no canonical frame (no reading), so even the right "No" is
    # written only after the confirmation (the owner's truth: No) and ONE meaning call that says "no"
    return FakeAsk(pick=pick_by("No", "no"), answer=lambda v: {"pep": say("No", "default", "default:no_declaration", klass="declaration:pep"),
                              "city": say("Singapore", "profile", "profile:contact.city", klass="ordinary"),
                              "conf": say("No", "default", "default:no_declaration", klass="declaration:conflict_audit_independence")}[v["id"]])


def test_g28_a_cached_row_stores_the_class_and_the_v2_prompt_version():
    from jobscraper.apply import always as AL
    out, classes = _classes_run(_good_ask())
    rows = _rows_of(out, classes)
    assert len(rows) == 3, rows
    bad = []
    for row in rows:
        d = row["decision"]
        if row["prompt_version"] != AL.PROMPT_VERSION or AL.PROMPT_VERSION != "always:v2" or not d.get("class"):
            bad.append(("version/class", row["prompt_version"], d.get("class")))
    assert sorted(r["decision"]["class"] for r in rows) == sorted(classes.values()), (rows, classes)
    assert not bad, report(bad)


def test_g28_a_field_the_model_answered_with_no_class_gets_no_row_never_a_class_less_row():
    out, classes = _classes_run(_good_ask())
    classes.pop("city")                                                 # as if the class were lost
    rows = _rows_of(out, classes)
    assert len(rows) == 2 and all(r["decision"].get("class") for r in rows), rows


def test_g28_a_restored_row_carries_the_class_and_the_which():
    from jobscraper.apply import pagefill as P
    out, classes = _classes_run(_good_ask())
    by_class = {r["decision"]["class"]: r for r in _rows_of(out, classes)}
    d = P.always_row_decision("pep", by_class["declaration:pep"])
    assert d is not None and d.klass.value == "declaration" and d.which == "pep", d
    assert d.via.startswith("cache:") and str(d.value) == "No", d
    d2 = P.always_row_decision("city", by_class["ordinary"])
    assert d2 is not None and d2.klass.value == "ordinary" and d2.which == "", d2


def test_g28_a_row_with_no_class_a_bad_class_or_another_prompt_version_is_a_miss_never_a_replay():
    import copy
    from jobscraper.apply import pagefill as P
    out, classes = _classes_run(_good_ask())
    row = _rows_of(out, classes)[0]
    assert P.always_row_decision("pep", row) is not None                # the control: the row itself replays
    bad = []
    nocls = copy.deepcopy(row)
    nocls["decision"].pop("class")
    bad_cls = copy.deepcopy(row)
    bad_cls["decision"]["class"] = "nonsense"
    empty_cls = copy.deepcopy(row)
    empty_cls["decision"]["class"] = ""
    v1 = copy.deepcopy(row)
    v1["prompt_version"] = "always:v1"
    odd_src = copy.deepcopy(row)
    odd_src["decision"]["source"] = "weird:x"
    for name, r in (("no class", nocls), ("bad class", bad_cls), ("empty class", empty_cls),
                    ("always:v1", v1), ("unreadable source", odd_src)):
        if P.always_row_decision("pep", r) is not None:
            bad.append(name)
    assert not bad, f"these rows must be a MISS (None): {bad}"


def test_g28_a_replayed_decision_still_goes_through_the_two_key_rule_it_is_not_code_only():
    """A restored class goes through the same rule as a live answer. D-212 U (replaces "a restored declaration
    class is both keys: not vetoed"): a declaration's wrong Yes is put to the vote whatever the class, with one
    key (`ordinary`) or both: `vetoed`, never written as is."""
    import llm_fill_t2 as T
    from jobscraper import applicant
    from jobscraper.apply import always as AL, briefing as BR, pagefill as P
    p = _profile()
    r = T.rctx(p)
    ctx = AL.PageCtx(brief=BR.build(p, r, today=TODAY), rctx=r, profile=applicant.normalise(dict(p)),
                     ask=FakeAsk(), rules=T.rules(), today=TODAY, step_title="Application")
    pf = _pf("conf", CONFLICT, options=YN)
    for klass, vetoed in (("ordinary", True), ("declaration:conflict_audit_independence", True)):
        row = {"prompt_version": AL.PROMPT_VERSION,
               "decision": {"source": "assumption", "ref": "", "value": "Yes", "evidence": "x", "assumed": True,
                            "via": "always", "class": klass}}
        d = P.always_row_decision("conf", row)
        assert d is not None, klass
        st = AL.decide(pf, d, ctx)
        shown = ", ".join(st.labels) if st.labels else str(st.value or "")
        assert shown != "Yes", (klass, "the adverse Yes must never be replayed", shown, st.vetoed)
        assert st.vetoed is vetoed, (klass, "vetoed" if st.vetoed else "not vetoed", shown)


def test_g28_replay_under_always_is_still_off_the_always_steps_never_read_the_cache():
    from jobscraper.apply import pagefill as P
    for fn in (P._always_steps, P._always_prepare, P._always_round):
        assert "cache_get" not in inspect.getsource(fn), f"{fn.__name__} reads the cache: replay is switched on; add replay pins"
