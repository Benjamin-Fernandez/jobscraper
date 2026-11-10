"""T2 lock oracles (Q-35 WP-T2, lane M WP-M2; llm_fill_design §4; test plan §5 lock precedence).

  - the email field locks to the account email (L-tier contact), so the model is never asked;
  - a locked key rides in its chunk as context only: it is not an open field and has no
    property in the output schema, even when the model would reply for it;
  - `qualified_labels` tells two generic "Other" fields apart.
Skip-clean until `jobscraper.apply.locks` / `llm_fill` exist. Verify: -k llm_fill_locks
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.locks:lock_page", "jobscraper.apply.locks:qualified_labels",
         "jobscraper.apply.llm_fill:chunks", "jobscraper.apply.llm_fill:schema",
         "jobscraper.apply.facts:fact_catalogue")


def test_the_locks_oracles_file_loads():
    import llm_fill_t2 as T
    assert T.EMAIL.endswith("@example.com")


def _page():
    # k-why is an ordinary free TEXTAREA (G3's compose rule), NOT a compose target (LF §19.1: a
    # "why do you want to work here" label is one, and K2 keeps those out of the page schema).
    from jobscraper.apply.contracts import FieldType as FT
    import llm_fill_t2 as T
    return [T.pf("k-email", "Email Address", FT.EMAIL, required=True),
            T.pf("k-why", "Describe a project you are proud of", FT.TEXTAREA, required=True, widget="text"),
            T.pf("k-city", "City", FT.TEXT)]


@needs(*NEEDS)
def test_the_email_is_locked_and_never_offered_to_the_model():
    from jobscraper.apply import facts as F, llm_fill as L, locks
    import llm_fill_t2 as T
    ctx, fields = T.rctx(), _page()
    locked = locks.lock_page(fields, ctx, T.rules(), today=T.TODAY, uploaded={})
    assert "k-email" in locked and locked["k-email"].value == T.EMAIL
    assert "k-why" not in locked, "an open question is the model's"
    cs = L.chunks(fields, {}, 20, locked=list(locked))
    open_keys = {f.field.key for c in cs for f in c.fields if f.field.key not in c.locked}
    assert "k-email" not in open_keys and "k-why" in open_keys
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    for c in cs:
        props = set((L.schema(c, cat, ctx, s_values=T.secrets()).get("properties") or {}))
        assert "k-email" not in props, "a locked key has no schema property"


@needs(*NEEDS)
def test_generic_labels_get_qualified_by_their_context():
    from jobscraper.apply import locks
    import llm_fill_t2 as T
    a = T.pf("k1", "Other", group="work_experience#1", group_title="Work Experience 1")
    b = T.pf("k2", "Other", group="education#1", group_title="Education 1")
    q = locks.qualified_labels([a, b])
    assert q.get("k1") and q.get("k2") and q["k1"] != q["k2"]


# ------------------------------------------------------------------ L8 (Q-45 WP-T7; LF §4, §19.2)
# Composed text. ASSUMED call shape (one place, `_l8`): K2 gives `lock_page` the apply flow's
# `ctx.composed` / `ctx.composed_files` as the keyword arguments `composed` / `composed_files`
# (the lock pre-pass has no AttemptContext; `uploaded` arrives the same way). Gate: those
# parameters exist. If lane M names them differently, change `L8_GATE` and `_l8` only.

def _l8_gap() -> str:
    import inspect
    try:
        from jobscraper.apply import locks
        params = inspect.signature(locks.lock_page).parameters
    except (ImportError, AttributeError, ValueError):
        return "jobscraper.apply.locks:lock_page"
    return "" if {"composed", "composed_files"} <= set(params) else "locks.lock_page(composed=, composed_files=)"


L8_GAP = _l8_gap()


def needs_l8(fn):
    if L8_GAP:
        WAITING.append((fn.__name__, L8_GAP))
        return None
    return fn


L8_TEXT = ("I want to join Example Employer because I enjoy building reliable data tools, and my "
           "internship taught me to ship small, tested changes. I would like to keep learning with your team.")


def _l8(fields, *, composed=None, files=None, **kw):
    from jobscraper.apply import locks
    import llm_fill_t2 as T
    return locks.lock_page(fields, T.rctx(), T.rules(), today=T.TODAY, uploaded={},
                           composed=dict(composed or {}), composed_files=dict(files or {}), **kw)


@needs_l8
def test_l8_a_composed_text_fills_its_textarea_target_with_the_whole_text():
    from jobscraper.apply.contracts import AnswerStatus as AS, AnswerTier, FieldType as FT
    import llm_fill_t2 as T
    why = T.pf("k-why", "Why do you want to work here?", FT.TEXTAREA, required=True, widget="text")
    locked = _l8([why], composed={"k-why": L8_TEXT})
    a = locked.get("k-why")
    assert a is not None and a.status is AS.FILLED and a.value == L8_TEXT, a
    assert a.tier is AnswerTier.LLM and a.source == "composed" and a.rule_id == "compose:v1", \
        (a.tier, a.source, a.rule_id)
    assert a.confidence == 0.9


@needs_l8
def test_l8_a_composed_cover_letter_file_is_filled_and_its_audit_value_is_the_whole_text():
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import llm_fill_t2 as T
    cl = T.pf("k-cl", "Cover Letter", FT.FILE, required=True, widget="file")
    path = r"C:\data\apply\7\cover_letter.docx"
    a = _l8([cl], composed={"k-cl": L8_TEXT}, files={"k-cl": path}).get("k-cl")
    assert a is not None and a.status is AS.FILLED and a.source == "composed", a
    assert a.value == L8_TEXT, "the audit row holds the whole text, a FILE too (LF §19.5)"
    assert "cover_letter.docx" in (a.note or ""), "the note names the uploaded file"


@needs_l8
def test_l8_only_a_compose_target_takes_a_composed_text_never_another_field_or_the_resume_slot():
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import llm_fill_t2 as T
    proj = T.pf("k-proj", "Describe a project you are proud of", FT.TEXTAREA, required=True, widget="text")
    tx = T.pf("k-tx", "Why do you want to work here?", FT.TEXT, required=True)         # TEXT, not TEXTAREA
    res = T.pf("k-res", "Resume", FT.FILE, required=True, widget="file")
    locked = _l8([proj, tx, res], composed={"k-proj": L8_TEXT, "k-tx": L8_TEXT, "k-res": L8_TEXT},
                 files={"k-res": r"C:\data\apply\7\cover_letter.docx"})
    for key in ("k-proj", "k-tx"):
        a = locked.get(key)
        assert a is None or a.value != L8_TEXT, (key, "not a compose target (LF §19.1)")
    r = locked.get("k-res")
    assert r is None or r.source != "composed", "the resume slot (L1) is never a composed file"


@needs_l8
def test_l8_without_a_composed_entry_a_required_target_stays_unknown_and_goes_to_no_model():
    from jobscraper.apply import llm_fill as L
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import llm_fill_t2 as T
    why = T.pf("k-why", "Why do you want to work here?", FT.TEXTAREA, required=True, widget="text")
    cl = T.pf("k-cl", "Cover Letter", FT.FILE, required=True, widget="file")
    locked = _l8([why, cl])
    for key in ("k-why", "k-cl"):
        a = locked.get(key)
        assert a is None or a.status is not AS.FILLED, (key, a)
    # compose targets never reach the page model (LF §19, G3 compose rule is for other TEXTAREAs)
    cs = L.chunks([why, cl], {}, 20, locked=list(locked))
    open_keys = {f.field.key for c in cs for f in c.fields if f.field.key not in c.locked}
    assert not open_keys & {"k-why", "k-cl"}, f"a compose target is never an open model field: {open_keys}"


if WAITING[_W0:]:
    print(f"[test_llm_fill_locks] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
