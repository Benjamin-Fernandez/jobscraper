"""R3 review pins (docs/reviews/Q-35-R3.md F1-F6, F8, the cache round trip, pick arguments) for
`pagefill.fill_page`. Same harness as test_apply_pagefill (headless Edge on synthetic pages, strict
FakeFillBackend, recording FakeServices); stubs `review_*` from tests/llm_fill_pages.py.

Skip-clean until `pagefill.fill_page` exists (lane R, `eng/Q-35-R-page`). Site behaviour the review
needs that the fake shim never shows (a swallowed Delete or Add) is injected per test with a
capture-phase click listener.
Verify: python tests/run_tests.py -k pagefill
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402
from llm_fill_support import FIX, FakeFillBackend  # noqa: E402
import test_apply_pagefill as P  # noqa: E402

_W0 = len(WAITING)
FILL = P.FILL
TIMED_OUT = "transport: timed out"
RES = "Python, SQL, PostgreSQL, Git"


def test_the_review_stubs_are_present():
    for name in ("review_optional_prompt", "review_required_prompt", "review_entries", "review_collide"):
        assert (FIX / "stubs" / f"{name}.html").is_file(), name


def _d(source, ref="", value="", evidence=""):
    return {"source": source, "ref": ref, "value": value, "evidence": evidence}


def _reply_file(tmp: Path, calls: list) -> Path:
    p = tmp / "reply.json"
    p.write_text(json.dumps({"calls": calls}), encoding="utf-8")
    return p


def _all(kind, reply):
    return {"kind": kind, "repeat": True, "reply": reply}


def _values(pg) -> str:
    return pg.evaluate("() => [...document.querySelectorAll('input,textarea')].map(e => e.value).join('|')")


def _pills(pg, aid) -> list:
    return pg.evaluate(f"""() => [...document.querySelectorAll('[data-automation-id="{aid}"] [data-automation-id="selectedItem"]')]
                           .map(e => e.title)""")


def _key(out, label, group_title=""):
    return next(pf.field.key for pf in out.fields if pf.field.label == label and pf.group_title == group_title)


SWALLOW = """sel => document.addEventListener('click', ev => {
  if (ev.target.closest(sel)) { ev.stopImmediatePropagation(); ev.preventDefault(); } }, true)"""


class _Clock(P.FakeServices):
    """The deadline passes once the backend has made `n` calls of `kind`."""

    def __init__(self, backend, page, kind: str, n: int = 1):
        super().__init__(backend, page, 600.0)
        self._kind, self._n = kind, n

    def deadline_left(self) -> float:
        return 0.0 if sum(c.kind == self._kind for c in self.backend.calls) >= self._n else 600.0


def _run(pg, step, reply_file, services_cls=None, **kw):
    """`P._fill` with a custom FakeServices class (the clock or the cache)."""
    from jobscraper.apply.pagefill import fill_page
    fb = FakeFillBackend.from_file(reply_file)
    with tempfile.TemporaryDirectory() as tmp:
        ctx, rctx = P._world(Path(tmp))
        sv = (services_cls or P.FakeServices)(fb, pg, **kw) if services_cls else P.FakeServices(fb, pg)
        pg.evaluate(P.INPUTS)
        out = fill_page(pg, P.FakeNav(step), ctx, rctx, sv)
        return out, rctx, sv, fb


OPTIONAL_REPLY = [
    _all("page", {"|Primary programming language": _d("resume", "", "Python", RES),
                  "|Strongest skill": _d("resume", "", "Python", RES)}),
    _all("corrective", {"|Primary programming language": _d("resume", "", "Python", RES),
                        "|Strongest skill": _d("resume", "", "Python", RES)}),
    {"kind": "pick", "repeat": True, "raw": {"choice": "Python (Programming Language)"}},
]


@needs(*FILL)
def test_f1_an_optional_prompt_whose_fill_failed_is_reset_or_flagged_never_kept():
    from jobscraper.apply import guards as G
    from jobscraper.apply.contracts import AnswerStatus as AS
    with P._open("stubs/review_optional_prompt.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        out, _r, _sv, _fb = _run(pg, "questions", _reply_file(Path(tmp), OPTIONAL_REPLY))
        k = _key(out, "Primary programming language")
        a = out.answers[k]
        pills = _pills(pg, "formField-primaryLanguage")
        assert a.status is not AS.FILLED, "a failed fill is never reported as ours"
        flagged = a.status is AS.PREFILLED and a.note == G.UNVERIFIED_NOTE
        assert pills == [] or flagged, (pills, a.status, a.note)
        assert "Java" not in pills or flagged, "the site default is never kept silently"


@needs(*FILL)
def test_every_pick_passes_sensitive_and_deny():
    from jobscraper.apply import llm_fill as L
    seen: list[dict] = []
    real = L.pick_option

    def spy(*a, **kw):
        seen.append(kw)
        return real(*a, **kw)
    with P._open("stubs/review_optional_prompt.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        L.pick_option = spy
        try:
            _run(pg, "questions", _reply_file(Path(tmp), OPTIONAL_REPLY))
        finally:
            L.pick_option = real
    assert seen, "the search for 'Python' needs a pick between two suggestions"
    for kw in seen:
        assert "sensitive" in kw and "deny" in kw and "s_values" in kw, sorted(kw)


@needs(*FILL)
def test_f4_a_required_search_miss_is_unknown_and_captured():
    from jobscraper.apply import questions as Q
    reply = [_all("page", {"|Main programming language": _d("resume", "", "Python", RES)}),
             _all("second", {"|Main programming language": _d("resume", "", "Python", RES)}),
             _all("corrective", {"|Main programming language": _d("resume", "", "Python", RES)})]
    with P._open("stubs/review_required_prompt.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        out, rctx, sv, _fb = _run(pg, "questions", _reply_file(Path(tmp), reply))
        k = _key(out, "Main programming language")
        assert k in out.unknown_required and k not in out.fill_failed, (out.unknown_required, out.fill_failed)
        caps = Q.capture_page(out.fields, out.answers, rctx, sv.rules)
        assert [c.field_key for c in caps] == [k], caps


@needs(*FILL)
def test_f3_the_deadline_inside_second_is_transport_timed_out_and_nothing_is_captured():
    from jobscraper.apply import questions as Q
    with P._open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        out, rctx, sv, _fb = _run(pg, "my_information", FIX / "wd_a/02-my_information/reply.json",
                                  services_cls=_Clock, kind="page")
        assert out.transport_failed is True and out.unknown_required == (), (out.transport_failed, out.unknown_required)
        assert any(a.note == TIMED_OUT for a in out.answers.values())
        assert Q.capture_page(out.fields, out.answers, rctx, sv.rules) == []


@needs(*FILL)
def test_f3_the_deadline_between_rechecks_stops_the_next_recheck():
    with P._open("wd_a/03-my_experience/page.html") as pg:
        if pg is None:
            return
        out, _r, _sv, fb = _run(pg, "my_experience", FIX / "wd_a/03-my_experience/reply.json",
                                services_cls=_Clock, kind="recheck")
        assert sum(c.kind == "recheck" for c in fb.calls) == 1, [c.kind for c in fb.calls]
        assert out.transport_failed is True and out.unknown_required == ()


ENTRY_REPLY = [
    _all("entry", {"Languages 1|Language": _d("profile", "profile:languages[0].language", "English"),
                   "Languages 1|I am fluent in this language.": _d("profile", "profile:languages[0].spoken", "true"),
                   "Languages 1|Overall": _d("profile", "profile:languages[0].spoken", "Native"),
                   "Languages 2|Language": _d("profile", "profile:languages[1].language", "Mandarin"),
                   "Languages 2|I am fluent in this language.": _d("unknown"),
                   "Languages 2|Overall": _d("profile", "profile:languages[1].spoken", "")}),
    _all("corrective", {"Languages 2|Overall": _d("profile", "profile:languages[1].spoken", "")}),
]


@needs(*FILL)
def test_f2_a_swallowed_delete_never_leaves_the_junk_entry_silently():
    with P._open("stubs/review_entries.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(SWALLOW, '[data-automation-id="panel-set-delete-button"]')
        out, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
        junk_left = "Japanese" in pg.evaluate(
            "() => [...document.querySelectorAll('button[aria-haspopup=\"listbox\"]')].map(e => e.textContent).join('|')")
        reported = bool(out.unknown_required or out.fill_failed or out.transport_failed)
        assert not junk_left or reported, "the delete failed and nothing cleared, flagged or stopped"


@needs(*FILL)
def test_f5_an_entry_added_at_a_deleted_index_is_filled_and_a_failed_add_is_reported():
    with P._open("stubs/review_entries.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        out, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
        shown = pg.evaluate(
            "() => [...document.querySelectorAll('button[aria-haspopup=\"listbox\"]')].map(e => e.textContent)")
        new_keys = {pf.field.key for pf in out.fields if pf.group_title == "Languages 2"}
        reported = set(out.unknown_required) | set(out.fill_failed)
        assert "Japanese" not in shown
        assert "Mandarin" in shown or new_keys & reported, (shown, out.unknown_required, out.fill_failed)
    with P._open("stubs/review_entries.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(SWALLOW, '[data-automation-id="add-button"]')
        out, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
        assert out.unknown_required or out.fill_failed, "E5 asked for an entry the site never added"


@needs(*FILL)
def test_f6_a_revealed_field_on_a_reused_ordinal_is_filled_itself():
    reply = [_all("page", {"|Favourite tool": _d("resume", "", "Git", RES)})]
    with P._open("stubs/review_collide.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        from jobscraper.apply.pagefill import fill_page
        fb = FakeFillBackend.from_file(_reply_file(Path(tmp), reply))
        ctx, rctx = P._world(Path(tmp), declarations__relatives_at_company=True)
        sv = P.FakeServices(fb, pg)
        pg.evaluate(P.INPUTS)
        out = fill_page(pg, P.FakeNav("questions"), ctx, rctx, sv)
        vals = pg.evaluate("() => ['tool1', 'tool2', 'tool3'].map(a => "
                           "document.querySelector(`[data-automation-id=\"formField-${a}\"] input`).value)")
        assert vals == ["Git", "Git", "Git"], (vals, out.fill_failed, out.unknown_required)


class _Cache(P.FakeServices):
    """A fill_cache that replays what an earlier run stored."""

    def __init__(self, backend, page, rows=()):
        super().__init__(backend, page, 600.0)
        self.rows = {r["field_sig"]: r for r in rows}
        self.asked: list = []

    def cache_get(self, job_id, sigs, prompt_version, model, inputs_hash) -> dict:
        self.asked.extend(sigs)
        return {s: self.rows[s] for s in sigs if s in self.rows}


@needs(*FILL)
def test_cache_round_trip_replays_by_field_sig_and_never_stores_second_or_corrective():
    reply = FIX / "wd_a/02-my_information/reply.json"
    with P._open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        out1, _r, sv1, fb1 = _run(pg, "my_information", reply)
    rows = [r for put in sv1.puts for r in put]
    assert rows, "a page with fresh model decisions stores them"
    assert not {r["decision"]["via"] for r in rows} & {"second", "corrective"}
    with P._open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        out2, _r, sv2, fb2 = _run(pg, "my_information", reply, services_cls=_Cache, rows=rows)
    assert {r["field_sig"] for r in rows} <= set(sv2.asked), "the same field_sig is asked for"
    k1 = sum(len(c.keys) for c in fb1.calls if c.kind == "page")
    k2 = sum(len(c.keys) for c in fb2.calls if c.kind == "page")
    assert k2 < k1, (k1, k2)
    by_label = lambda o: {o_pf.field.label: (o.answers[o_pf.field.key].status, o.answers[o_pf.field.key].value)
                          for o_pf in o.fields if o_pf.field.key in o.answers}
    assert by_label(out2) == by_label(out1)


@needs(*FILL)
def test_f8_a_decision_the_site_rejected_is_not_cached():
    with P._open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        out, _r, sv, fb = _run(pg, "my_information", FIX / "wd_a/02-my_information/reply.json")
    corrected = [c for c in fb.calls if c.kind == "corrective"]
    if not corrected:
        return                       # nothing was rejected on this run: nothing to check
    refs = {r["decision"]["ref"] for put in sv.puts for r in put}
    rejected = {"standing:how_heard", "profile:contact.phone_country_code"}
    assert not refs & rejected, refs & rejected


if WAITING[_W0:]:
    print(f"[test_apply_pagefill_review] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
