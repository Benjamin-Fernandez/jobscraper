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
    from jobscraper.apply.contracts import FieldType as FT
    import llm_fill_t2 as T
    return [T.pf("k-email", "Email Address", FT.EMAIL, required=True),
            T.pf("k-why", "Why do you want to work here?", FT.TEXTAREA, required=True, widget="text"),
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


if WAITING[_W0:]:
    print(f"[test_llm_fill_locks] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
