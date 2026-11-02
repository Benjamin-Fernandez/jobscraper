"""T2 model-call oracles (Q-35 WP-T2, lane M WP-M4; llm_fill_design §6, §11; TR-1, TR-4, TR-11).

  - `ask` on a page chunk: one decision per answered open field; the prompt ends with
    `FIELDS (JSON):` + one array, then the fixed final line; no S value anywhere in what the
    model saw (system, user, format), although a field shows the sample phone;
  - FACTS is byte-identical across two calls (prefix reuse);
  - a malformed reply is re-asked once, then BackendError; a transport failure is BackendError;
  - `redact` hides an S value in any spacing.
Fake model: tests/llm_fill_support.py FakeFillBackend. Skip-clean until `llm_fill` exists.
Verify: python tests/run_tests.py -k llm_fill_model
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.llm_fill:ask", "jobscraper.apply.llm_fill:chunks",
         "jobscraper.apply.llm_fill:redact", "jobscraper.apply.llm_fill:FINAL_LINE",
         "jobscraper.apply.facts:fact_catalogue")
WHY = "Why do you want to work here?"


def test_the_model_oracles_file_loads():
    from llm_fill_support import FakeFillBackend
    assert FakeFillBackend(replies=[]).model_id == "fake-fill:1"


def _setup(replies):
    from jobscraper.apply import facts as F, llm_fill as L
    from jobscraper.apply.contracts import FieldType as FT, ValueOrigin
    from llm_fill_support import FakeFillBackend
    import llm_fill_t2 as T
    ctx = T.rctx()
    phone = ctx.profile["contact"]["phone_number"]
    fields = [T.pf("k-why", WHY, FT.TEXTAREA, required=True),
              T.pf("k-ref", "Referee phone", FT.TEXT, shown=phone, origin=ValueOrigin.RESUME_IMPORT)]
    chunk = L.chunks(fields, {}, 20)[0]
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    return L, ctx, chunk, cat, FakeFillBackend(replies=replies), T


@needs(*NEEDS)
def test_ask_keeps_the_prompt_order_and_sends_no_s_value():
    reply = {"kind": "page", "repeat": True,
             "reply": {f"|{WHY}": {"source": "job", "ref": "", "value": "The role fits.", "evidence": "role"}}}
    L, ctx, chunk, cat, be, T = _setup([reply])
    got = L.ask(be, chunk, cat, ctx, step_title="Application Questions", s_values=T.secrets(), cfg={})
    assert [d.field_key for d in got] == ["k-why"] and got[0].value == "The role fits."
    user = be.calls[0].user
    i = user.rindex("FIELDS (JSON):")
    assert user.rstrip().endswith(L.FINAL_LINE) and user.index(L.FINAL_LINE) > i
    assert user.index("FACTS") < user.index("RESUME") < i
    be.assert_no_secrets(T.secrets())
    L.ask(be, chunk, cat, ctx, step_title="Application Questions", s_values=T.secrets(), cfg={})
    facts_of = [c.user[c.user.index("FACTS"):c.user.index("RESUME")] for c in be.calls]
    assert facts_of[0] == facts_of[1], "FACTS byte-identical across calls"


@needs(*NEEDS)
def test_a_malformed_reply_is_asked_once_more_then_a_backend_error():
    from jobscraper.backends import BackendError
    bad = {"kind": "page", "match": "FIELDS (JSON):", "text": "not json", "repeat": True}
    L, ctx, chunk, cat, be, T = _setup([bad])
    try:
        L.ask(be, chunk, cat, ctx, step_title="Q", s_values=T.secrets(), cfg={})
    except BackendError:
        pass
    else:
        raise AssertionError("a reply still malformed after one retry is a BackendError")
    assert len(be.calls) == 2, "exactly one retry"
    L, ctx, chunk, cat, be, T = _setup([{"kind": "page", "match": "FIELDS", "raise": "BackendError"}])
    try:
        L.ask(be, chunk, cat, ctx, step_title="Q", s_values=T.secrets(), cfg={})
    except BackendError:
        pass
    else:
        raise AssertionError("a transport failure is a BackendError")


@needs(*NEEDS)
def test_redact_hides_an_s_value_in_any_spacing():
    from jobscraper.apply import llm_fill as L
    from llm_fill_support import find_secrets
    import llm_fill_t2 as T
    s = T.secrets()
    phone = T.rctx().profile["contact"]["phone_number"]
    text = f"call {phone[:4]} {phone[4:]} or {T.EMAIL.upper()}"
    assert not find_secrets(L.redact(text, s), s)


if WAITING[_W0:]:
    print(f"[test_llm_fill_model] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
