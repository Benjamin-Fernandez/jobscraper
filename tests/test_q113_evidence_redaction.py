"""Q-113 / D-202 pins (docs/architecture/q113_evidence_redaction.md section 8): the model's evidence quote is
stored verbatim in `apply_answers.evidence` and in `fill_cache` only when the guards checked it and the field took
a value; every other quote is stored with private values as "[private]".

The flipped known-gap pin (rejected quote, audit row) stays in tests/test_q74_llm_fill_hooks.py. Here: the
fill_cache row, cache-hit replay, the `quote_checked` routes, non-model rows, the corrective pass and the account
swap, whole-token matching.

No Edge, no model, no network: the real `pagefill.fill_page` setup and `_decide` (locks, cache replay, `llm_fill.ask`,
`guards.decide`) run on a stand-in page and the scripted FakeFillBackend; the flow cases use the N6a harness
(`fill_page` scripted, fake browser). Dummy data only. Verify: python tests/run_tests.py -k q113
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_fill_t2 as T  # noqa: E402
import test_apply_flow_n6a as N  # noqa: E402
import test_apply_pagefill as TP  # noqa: E402
import test_q74_llm_fill_hooks as H  # noqa: E402
from llm_fill_support import FakeFillBackend  # noqa: E402

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply import facts as F, guards as G, llm_fill as L, locks, pagefill as PF  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerStatus as AS, AnswerTier, FieldType as FT, FillSource, ModelDecision, PageField, ValueOrigin,
)

PRIVATE = "[private]"
WHY = "Tell us about yourself"                                            # an optional TEXTAREA
SKILLS_Q = "Which skills do you use at work?"


# ------------------------------------------------------------------ a stand-in page for the real fill_page setup

class _Page:
    url = "https://fake.example.test/apply"

    def evaluate(self, *_a, **_k):
        return ""


class _Halt(Exception):
    pass


class _CacheSvc(TP.FakeServices):
    """pagefill's recording services with a fill_cache that replays stored rows (by field_sig)."""

    def __init__(self, backend, rows=()):
        super().__init__(backend, None, 600.0)
        self.rows = {r["field_sig"]: r for r in rows}

    def cache_get(self, job_id, sigs, prompt_version, model, inputs_hash) -> dict:
        return {s: self.rows[s] for s in sigs if s in self.rows}


def _decide_page(rctx, fields, replies, rows=()):
    """Run the real `fill_page` up to and including `_decide` (steps 1-6), then `_cache_put`, and stop before
    anything is typed. Returns (run, decision, services, backend); `services.puts` holds the cache rows."""
    box = {}
    real_decide = PF._decide

    def decide_then_halt(run, flds, sections, forced):
        d = real_decide(run, flds, sections, forced)
        box["run"], box["d"] = run, d
        raise _Halt

    class Nav:
        name = "fakewd"

        def step_id(self, page, ctx):
            return "questions"

        def scope(self, page, ctx):
            return ""

        def entry_sections(self, page, ctx):
            return []

    fb = FakeFillBackend(replies=list(replies))
    svc = _CacheSvc(fb, rows)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ctx, _unused = TP._world(Path(tmp))
    saved = PF.P.read_page, PF.P.audit_keys, PF._decide
    PF.P.read_page = lambda *a, **k: list(fields)
    PF.P.audit_keys = lambda *a, **k: {}
    PF._decide = decide_then_halt
    try:
        try:
            PF.fill_page(_Page(), Nav(), ctx, rctx, svc)
        except _Halt:
            pass
    finally:
        PF.P.read_page, PF.P.audit_keys, PF._decide = saved
    run = box["run"]
    PF._cache_put(run)
    return run, box["d"], svc, fb


def _page_reply(*decisions):
    """One scripted page reply. Each decision: (label, source, value, evidence)."""
    return {"kind": "page", "repeat": True, "reply": {
        f"|{label}": {"source": source, "ref": "", "value": value, "evidence": evidence}
        for label, source, value, evidence in decisions}}


def _audit(run, key, values=None):
    """The audit row of one field as the flow would write it (same `quote_values` set)."""
    a = run.answers[key]
    return apply_flow.audit_row("questions", run.fields[key].field, a, tuple(run.qv if values is None else values))


# ------------------------------------------------------------------ pin 2 (fill_cache half): rejected quote, cache row

def test_d202_b_a_rejected_quote_is_stored_redacted_in_the_fill_cache_row_and_the_audit_row():
    """The review scenario (D-201 profile; the model quotes the pronouns, the sensitive extra answer and the salary
    amount, which G3 rejects) through the real pagefill: the fill_cache `decision.evidence` holds "[private]" and
    none of the private values; the legal and preferred names stay (not private by design, spec section 3)."""
    rctx = dataclasses.replace(T.rctx(H._d201_profile()), model_sees_sensitive=True)
    quote = "Zyxquill Vandermoot Quillo xe/xem Plumbago-7731 " + H.SALARY
    pf = T.pf("k", WHY, FT.TEXTAREA, required=False)
    run, _d, svc, fb = _decide_page(rctx, [pf], [_page_reply((WHY, "resume", "I built a tool", quote))])
    assert fb.calls and all(m in fb.calls[0].user for m in ("xe/xem", "Plumbago-7731", H.SALARY)),         "precondition: the model reads every value it then quotes"
    a = run.answers["k"]
    assert a.status is AS.BLANK_OPTIONAL and a.note.startswith("G3"), (a.status, a.note)
    rows = [r for put in svc.puts for r in put]
    assert len(rows) == 1, "the rejected optional is cached (redact, don't drop)"
    for what, ev in (("fill_cache", rows[0]["decision"]["evidence"]), ("audit row", _audit(run, "k")["evidence"])):
        assert PRIVATE in ev, (what, ev)
        for m in ("xe/xem", "Plumbago-7731", H.SALARY):
            assert m not in ev, f"{what} evidence still holds {m[:3]!r}..."
        for name in ("Zyxquill", "Vandermoot", "Quillo"):
            assert name in ev, f"{what}: the legal/preferred name is not private by design ({name[:3]}...)"


# ------------------------------------------------------------------ pin 3: replay

def test_d202_c_cache_replay_a_checked_quote_verbatim_to_the_same_value_a_rejected_one_to_the_same_blank():
    """Run 1 stores a checked resume quote verbatim and a rejected optional's quote redacted; run 2 replays both from
    fill_cache (`via == "cache:page"`) with no model call: the same FILLED value, and the same BLANK_OPTIONAL + note."""
    resume = ("Alex Testcase\nSingapore Citizen. Built REST APIs in Python and Postgres for shipment tracking.\n"
              "SKILLS\nPython, SQL, PostgreSQL, Git\n")
    # switch off: with it on, G3 rejects a quote holding a protected word that only the resume holds
    rctx = dataclasses.replace(T.rctx(H._d201_profile(), resume_text=resume), model_sees_sensitive=False)
    assert "singapore citizen" in F.enum_s_values(rctx.profile), "precondition: the checked quote holds a private word"
    ok_q = "Singapore Citizen. Built REST APIs in Python"
    bad_q = "Plumbago-7731 " + H.SALARY
    fa = T.pf("a", "Describe your background", FT.TEXT, required=False)
    fb_ = T.pf("b", WHY, FT.TEXTAREA, required=False)
    replies = [_page_reply(("Describe your background", "resume", "Built REST APIs in Python", ok_q),
                           (WHY, "resume", "I built a tool", bad_q))]
    run1, _d, svc1, fake1 = _decide_page(rctx, [fa, fb_], replies)
    a1, b1 = run1.answers["a"], run1.answers["b"]
    assert a1.status is AS.FILLED and a1.value == "Built REST APIs in Python", (a1.status, a1.note)
    assert b1.status is AS.BLANK_OPTIONAL and b1.note.startswith("G3"), (b1.status, b1.note)
    rows = {r["decision"]["evidence"]: r for put in svc1.puts for r in put}
    assert ok_q in rows, "the checked quote is stored verbatim in fill_cache"
    assert _audit(run1, "a")["evidence"] == ok_q, "and verbatim in the audit row"
    red = [e for e in rows if e != ok_q]
    assert len(red) == 1 and PRIVATE in red[0] and "Plumbago-7731" not in red[0] and H.SALARY not in red[0], red
    assert PRIVATE in _audit(run1, "b")["evidence"]
    calls1 = len(fake1.calls)
    run2, _d2, svc2, fake2 = _decide_page(rctx, [fa, fb_], [], rows=list(rows.values()))
    assert not fake2.calls and calls1 >= 1, "run 2 made no model call (strict backend, no replies)"
    assert {run2.decisions[k].via for k in ("a", "b")} == {"cache:page"}
    a2, b2 = run2.answers["a"], run2.answers["b"]
    assert (a2.status, a2.value) == (a1.status, a1.value), "the checked quote replays to the same value"
    assert (b2.status, b2.note) == (b1.status, b1.note), "the redacted rejected quote replays to the same blank + note"


# ------------------------------------------------------------------ pin 4: quote_checked routes (review F1)

def test_d202_d_quote_checked_is_true_only_for_the_resume_job_route_and_the_grounded_keep():
    """Every guard route that gives an Answer a non-empty `evidence`. True: resume after G3, job after G3, grounded
    keep. False: trusted keep (CONF_KEEP_TRUSTED) and each rejecting `_answer_unknown` route."""
    p = T.rctx().profile
    rctx = dataclasses.replace(T.rctx(p, resume_text="Singapore Citizen. Python, SQL, PostgreSQL, Git\n",
                                      jd_text="We build logistics software in Python.\n"), model_sees_sensitive=False)

    def route(pf, d):
        rules = T.rules()
        lk = locks.lock_page([pf], rctx, rules, today=T.TODAY, uploaded={})
        facts = F.fact_catalogue(rctx.profile, rctx, today=T.TODAY)
        out = G.decide([pf], lk, [d], facts, rctx, matches={}, second=lambda x: None, today=T.TODAY, rules=rules)
        return out.answers[pf.field.key]

    txt = T.pf("t", "Describe your background", FT.TEXT)
    opt = lambda key, label, ftype, **kw: T.pf(key, label, ftype, options=("Oracle", "Cassandra"), **kw)
    site = lambda **kw: dict(shown="Some site value", origin=ValueOrigin.RESUME_IMPORT, **kw)
    md = lambda key, src, value, ev, **kw: ModelDecision(key, src, "", value, ev, **kw)
    cases = [
        # (name, answer, expected quote_checked, expected status set)
        ("resume after G3", route(txt, md("t", FillSource.RESUME, "Python and SQL", "Python, SQL, PostgreSQL")),
         True, {AS.FILLED}),
        ("job after G3", route(txt, md("t", FillSource.JOB, "Logistics software", "build logistics software in Python")),
         True, {AS.FILLED}),
        ("grounded keep", route(T.pf("g", "Describe your background", FT.TEXT, shown="Python, SQL",
                                      origin=ValueOrigin.RESUME_IMPORT), md("g", FillSource.KEEP, "", "Python, SQL")),
         True, {AS.PREFILLED}),
        ("trusted keep", route(T.pf("m", "Describe your background", FT.TEXT, shown="Some value",
                                    origin=ValueOrigin.MYGREENHOUSE), md("m", FillSource.KEEP, "", "private quote here")),
         False, {AS.PREFILLED}),
        ("G3 reject (quote not in the source)", route(txt, md("t", FillSource.RESUME, "a tool", "Plumbago-7731 987654")),
         False, {AS.BLANK_OPTIONAL}),
        ("G3 reject, required", route(T.pf("r", "Describe your background", FT.TEXT, required=True),
                                      md("r", FillSource.RESUME, "a tool", "Plumbago-7731 987654")),
         False, {AS.UNGROUNDED}),
        ("G4 reject (option not backed by the quote)", route(opt("c", "Favourite database", FT.DROPDOWN),
                                                             md("c", FillSource.RESUME, "Oracle", "Python, SQL")),
         False, {AS.BLANK_OPTIONAL}),
        ("skill list, no item grounded", route(opt("s", SKILLS_Q, FT.MULTI_CHOICE),
                                               md("s", FillSource.RESUME, ["Oracle"], "Python, SQL")),
         False, {AS.BLANK_OPTIONAL}),
        ("keep, G3 reject", route(T.pf("k1", "Describe your background", FT.TEXT, shown="Some site value", required=True,
                                       origin=ValueOrigin.RESUME_IMPORT), md("k1", FillSource.KEEP, "", "Plumbago-7731 987654")),
         False, {AS.UNGROUNDED}),
        ("keep, G4 reject", route(opt("k2", "Favourite database", FT.DROPDOWN, shown="Oracle", required=True,
                                      origin=ValueOrigin.RESUME_IMPORT), md("k2", FillSource.KEEP, "", "Python, SQL")),
         False, {AS.UNKNOWN}),
    ]
    for name, a, want, statuses in cases:
        assert a.evidence, f"{name}: precondition, the Answer carries a quote ({a.status}, {a.note})"
        assert a.status in statuses, (name, a.status, a.note)
        assert G.quote_checked(a) is want, (name, a.status, a.confidence, a.note)
    assert cases[3][1].confidence == G.CONF_KEEP_TRUSTED, "precondition: the trusted keep route"


# ------------------------------------------------------------------ fix round: rows pagefill rewrites keep their quote

def _assert_redacted(what, ev):
    assert PRIVATE in ev, (what, ev)
    for m in ("xe/xem", "Plumbago-7731", H.SALARY):
        assert m not in ev, f"{what}: evidence still holds {m[:3]!r}..."


def test_d202_h_rows_pagefill_rewrites_are_not_checked_and_keep_their_quote_redacted():
    """Review F1. A rejected optional that the step-12 required scan rewrites to FILL_FAILED (real `_outcome`, with
    `run.failed` set as `_required_scan` sets it), and a rejected or trusted-keep row rewritten to PREFILLED at
    CONF_UNVERIFIED (real `_clear_failed_optional`; the widget's reset is stubbed to fail, as a site that ignores it)
    keep their evidence but are NOT `quote_checked`: the audit row and the cache row hold it redacted."""
    from types import SimpleNamespace
    quote = "xe/xem Plumbago-7731 " + H.SALARY
    rctx = dataclasses.replace(T.rctx(H._d201_profile()), model_sees_sensitive=True)
    # (a) FILL_FAILED by the required scan
    f1 = T.pf("f1", WHY, FT.TEXTAREA, required=False)
    run, _d, _svc, _fb = _decide_page(rctx, [f1], [_page_reply((WHY, "resume", "I built a tool", quote))])
    assert run.answers["f1"].status is AS.BLANK_OPTIONAL and run.answers["f1"].evidence, "precondition: a rejected quote"
    run.failed["f1"] = "required_scan"
    out = PF._outcome(run)
    a = out.answers["f1"]
    assert a.status is AS.FILL_FAILED and a.evidence, (a.status, a.note)
    assert G.quote_checked(a) is False, "a rejected quote made FILL_FAILED is not checked"
    _assert_redacted("FILL_FAILED row", apply_flow.audit_row("questions", f1.field, a, tuple(run.qv))["evidence"])
    # (b) PREFILLED at CONF_UNVERIFIED: a rejected row and a trusted keep
    f2 = T.pf("f2", "Describe your hobbies", FT.TEXT, required=False)
    f3 = T.pf("f3", "Describe your background", FT.TEXT, required=False, shown="Typed site text",
              origin=ValueOrigin.MYGREENHOUSE)
    run, _d, svc, _fb = _decide_page(rctx, [f2, f3], [_page_reply(
        ("Describe your hobbies", "resume", "a hobby", quote),
        ("Describe your background", "keep", "", quote))])
    assert run.answers["f2"].status is AS.BLANK_OPTIONAL and run.answers["f2"].evidence, "precondition: rejected"
    assert run.answers["f3"].confidence == G.CONF_KEEP_TRUSTED and run.answers["f3"].evidence,         "precondition: a trusted keep with a quote"
    run.failed.update(f2="readback", f3="readback")
    saved = PF.W.reset_field
    PF.W.reset_field = lambda page, pf: SimpleNamespace(ok=False, shown="Typed site text")
    try:
        PF._clear_failed_optional(run)
    finally:
        PF.W.reset_field = saved
    svc.puts.clear()
    PF._cache_put(run)
    cache = {r["field_sig"]: r["decision"]["evidence"] for put in svc.puts for r in put}
    assert len(cache) == 2, "both rewritten rows are cached"
    for key, f in (("f2", f2), ("f3", f3)):
        a = run.answers[key]
        assert a.status is AS.PREFILLED and a.confidence == G.CONF_UNVERIFIED and a.evidence, (key, a.status)
        assert G.quote_checked(a) is False, f"{key}: a PREFILLED row at CONF_UNVERIFIED is not checked"
        _assert_redacted(f"{key} audit row", apply_flow.audit_row("questions", f.field, a, tuple(run.qv))["evidence"])
        _assert_redacted(f"{key} fill_cache row", cache[run.sigs[key]])


def test_d202_i_a_rejected_decisions_cached_value_is_redacted_a_checked_ones_replays_verbatim():
    """Tester O1. fill_cache keeps the model's `value` for resume/job/keep decisions. A decision G3 rejected has its
    value stored with private values as "[private]" (the legal name stays); an accepted, checked decision's value is
    stored verbatim, and a second run replays it to the same FILLED value with no model call."""
    resume = "Alex Testcase\nSingapore Citizen building REST APIs in Python and Postgres.\n"
    jd = "We build logistics software in Python.\n"
    rctx = dataclasses.replace(T.rctx(H._d201_profile(), resume_text=resume, jd_text=jd), model_sees_sensitive=False)
    assert "singapore citizen" in F.enum_s_values(rctx.profile), "precondition: the value holds a private word"
    fa, fb_, fc = (T.pf("a", "Describe your background", FT.TEXT), T.pf("b", WHY, FT.TEXTAREA),
                   T.pf("c", "Describe the employer", FT.TEXT))
    good_v = "Singapore Citizen building REST APIs"
    bad_v = "Zyxquill built a Plumbago-7731 tool earning " + H.SALARY
    replies = [_page_reply(("Describe your background", "resume", good_v, "Singapore Citizen building REST APIs"),
                           (WHY, "resume", bad_v, "Plumbago-7731 " + H.SALARY),
                           ("Describe the employer", "job", bad_v, "Plumbago-7731 " + H.SALARY))]
    run1, _d, svc1, _f1 = _decide_page(rctx, [fa, fb_, fc], replies)
    assert run1.answers["a"].status is AS.FILLED, (run1.answers["a"].status, run1.answers["a"].note)
    for k in ("b", "c"):
        assert run1.answers[k].status is AS.BLANK_OPTIONAL and run1.answers[k].note.startswith("G3"),             (k, run1.answers[k].note)
    vals = {r["field_sig"]: r["decision"]["value"] for put in svc1.puts for r in put}
    assert vals[run1.sigs["a"]] == good_v, "a checked decision's value is stored verbatim"
    for k in ("b", "c"):
        v = vals[run1.sigs[k]]
        assert PRIVATE in v and "Plumbago-7731" not in v and H.SALARY not in v and "Zyxquill" in v, (k, v)
    rows = [r for put in svc1.puts for r in put]
    run2, _d2, _svc2, fake2 = _decide_page(rctx, [fa, fb_, fc], [], rows=rows)
    assert not fake2.calls, "run 2 made no model call"
    assert (run2.answers["a"].status, run2.answers["a"].value) == (AS.FILLED, good_v), "same FILLED value on replay"
    assert run2.answers["b"].status is AS.BLANK_OPTIONAL and run2.answers["c"].status is AS.BLANK_OPTIONAL


# ------------------------------------------------------------------ pin 5: rows that are not model decisions (review F2)

def test_d202_e_rows_that_are_not_model_decisions_keep_their_audit_evidence_byte_identical():
    """A composed TEXTAREA row, a composed FILE row (D-186), a lock-decided row (L1-L7) and a tier-1/2 resolve row carry
    no quote: `audit_row(...)["evidence"]` equals `a.evidence or None` (as before D-202), whatever quote_values hold."""
    import test_q74_model_sees_sensitive as base
    from questions_support import field
    rctx = T.rctx()
    rules = T.rules()
    why = T.pf("k-why", "Why do you want to work here?", FT.TEXTAREA, required=True, widget="text")
    cl = T.pf("k-cl", "Cover Letter", FT.FILE, required=True, widget="file")
    decl = T.pf("k-d", "Are you currently employed by the government of any country?", FT.TEXT)
    lk = locks.lock_page([why, cl, decl], rctx, rules, today=T.TODAY, uploaded={},
                         composed={"k-why": "I like Alex Testcase's tools.", "k-cl": "Dear team, I am Alex Testcase."},
                         composed_files={"k-cl": r"C:\data\apply\7\cover_letter.docx"})
    rows = [(why.field, lk["k-why"]), (cl.field, lk["k-cl"])]
    if lk.get("k-d") is not None:
        rows.append((decl.field, lk["k-d"]))
    sal = field("s", "What is your expected salary?", FT.TEXT)
    p = base.s_profile()
    p["pay"]["expected_salary"] = {"amount": 41234, "currency": "SGD", "period": "monthly", "negotiable": True}
    a_res, _be, _ctx = base.resolve_one(sal, on=True, replies=[], p=p)
    rows.append((sal, a_res))
    assert len(rows) >= 3 and {a.source for _f, a in rows} >= {"composed"}, "precondition: the row kinds exist"
    assert lk["k-cl"].note.startswith("composed file: "), "precondition: the D-186 composed FILE row"
    assert a_res.status is AS.FILLED and a_res.source == "profile:pay.expected_salary", (a_res.status, a_res.source)
    heavy = tuple(F.quote_s_values(dataclasses.replace(rctx, model_sees_sensitive=True), T.TODAY)) + ("Testcase", "Alex")
    for f, a in rows:
        want = a.evidence or None
        assert not a.evidence, f"REPORT: a non-model row carries a quote ({f.label!r}: {a.evidence!r})"
        assert apply_flow.audit_row("questions", f, a, heavy)["evidence"] == want, f.label
        assert apply_flow.audit_row("questions", f, a)["evidence"] == want, f.label
        assert PF.stored_quote(a.evidence, a, heavy) == a.evidence, f.label


# ------------------------------------------------------------------ pin 6: corrective pass and account swap (review F3)

def _rejected(key, quote, *, evidence=True):
    return Answer(key, None, AnswerTier.NONE, "", 0.0, AS.BLANK_OPTIONAL, note="G3: quote not in the source",
                  evidence=quote if evidence else "")


def test_d202_f_on_the_corrective_pass_a_rejected_quote_is_redacted_in_its_audit_row():
    """Next shows errors: a second `fill_page` on the same step. The quote of the checked field stays verbatim; the
    rejected one (private pronouns, extra answer, salary amount) is redacted in the row recorded after the pass."""
    quote = "xe/xem Plumbago-7731 " + H.SALARY
    ok_q = "Python, SQL"

    def script(nav, services):
        step = nav.step_id(None, None)
        if step != "one":
            return N.outcome("two", [N.pf("c", "Nationality")])
        calls = script.__dict__.setdefault("n", [])
        calls.append(1)
        good = Answer("one:good", "Python", AnswerTier.LLM, "resume", 0.8, AS.FILLED, evidence=ok_q)
        bad = _rejected("one:bad", quote if len(calls) > 1 else "", evidence=len(calls) > 1)
        return N.outcome("one", [N.pf("one:good", "Skills", required=False), N.pf("one:bad", WHY, required=False)],
                         answers={"one:good": good, "one:bad": bad})

    w, jid = N.world(profile=H._d201_profile())
    try:
        nav = N.FakeNav()
        nav.errors = [("Skills is required",)]
        with N.scripted(nav, script) as seen:
            r, _f, _say, _m = N.run(w, jid, nav)
        assert [s for s, _ in seen][:2] == ["one", "one"], "precondition: the corrective pass ran"
        rows = {x["label"]: x for x in w.store.answers(r.attempt_id)}
        assert rows["Skills"]["evidence"] == ok_q, "a checked quote stays verbatim"
        ev = str(rows[WHY]["evidence"] or "")
        assert PRIVATE in ev, ev
        for m in ("xe/xem", "Plumbago-7731", H.SALARY):
            assert m not in ev, f"the corrective-pass row still holds {m[:3]!r}..."
    finally:
        w.close()


def test_d202_f_the_account_swap_refreshes_quote_values_before_the_first_record():
    """`account()` swaps the ResolveContext (`account_email` = the identity the site uses) and must set
    `_Attempt.quote_values` from it: a rejected quote holding the swapped address is redacted in the first recorded
    row, and the address is in `quote_values` when the first `record` runs."""
    swapped = "swapped.account@example.test"
    seen_qv = []
    real_record = apply_flow._Attempt.record

    def record(self, step, fields):
        seen_qv.append(tuple(self.quote_values))
        return real_record(self, step, fields)

    class Nav(N.FakeNav):
        def account_wall(self, page):
            return "wall" if not getattr(self, "walled", False) else None

        def sign_in(self, page, ctx, password):
            return None

    def script(nav, services):
        nav.walled = True
        a = _rejected("one:bad", f"mail me at {swapped} about 987654")
        return N.outcome("one", [N.pf("one:bad", WHY, required=False)], answers={"one:bad": a})

    from jobscraper.apply.accounts import Identity
    saved = (apply_flow.choose_identity, apply_flow._Run.sign_in, apply_flow._Attempt.record)
    apply_flow.choose_identity = lambda *_a, **_k: Identity(swapped, apply_flow.SIGN_IN)
    apply_flow._Run.sign_in = lambda self, *a, **k: None
    apply_flow._Attempt.record = record
    w, jid = N.world(profile=H._d201_profile())
    try:
        nav = Nav(steps=("one", "review"))
        with N.scripted(nav, script):
            r, _f, _say, _m = N.run(w, jid, nav)
        first = [x for x in w.store.answers(r.attempt_id) if x["label"] == WHY]
        assert seen_qv and swapped in seen_qv[0], "quote_values holds the swapped account address at the first record"
        assert first, (r.state, r.reason, r.reason_detail)
        ev = str(first[0]["evidence"] or "")
        assert PRIVATE in ev and swapped not in ev, ev
    finally:
        apply_flow.choose_identity, apply_flow._Run.sign_in, apply_flow._Attempt.record = saved
        w.close()


# ------------------------------------------------------------------ pin 7: whole tokens

def test_d202_g_a_number_is_blanked_as_a_whole_token_and_ordinary_words_stay_with_the_switch_on_or_off():
    """`quote_s_values` + `llm_fill.redact` on a private salary of 4321: blanked in "4321 SGD", kept in "43210" and
    "ID4321"; "12 months", "yes", "true" untouched; the legal first name stays; the value set is the same either way."""
    p = H._d201_profile()
    p["pay"]["current_salary"] = {"amount": 4321, "currency": "SGD", "period": "monthly"}
    on = dataclasses.replace(T.rctx(p), model_sees_sensitive=True)
    off = dataclasses.replace(on, model_sees_sensitive=False)
    vals = F.quote_s_values(on, T.TODAY)
    assert vals == F.quote_s_values(off, T.TODAY), "the set does not read the switch"
    assert "4321" in vals, "precondition: the amount is its own token"
    red = lambda s: L.redact(s, vals)
    assert red("4321 SGD") == f"{PRIVATE} SGD"
    assert red("43210") == "43210" and red("ID4321") == "ID4321" and red("143210") == "143210"
    for same in ("12 months", "yes", "true", "No", "Zyxquill built it"):
        assert red(same) == same, same
    assert not {"yes", "no", "true", "false"} & {v.lower() for v in vals}
