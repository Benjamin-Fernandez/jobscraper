"""WP-T3: generic page reader oracles (LF §3.1, §3.3; review H7). Verify `-k apply_page_reader`.

Skip-clean: each oracle is defined only once `jobscraper.apply.page` has what it needs. They run
headless Edge on the synthetic fixtures (tests/fixtures/apply/llm_fill, built by
tests/llm_fill_pages.py) served on 127.0.0.1; without a browser they print a note and pass.

Call shapes: LF §8 pinned `page.read_page(page, *, scope, sections, origin: ValueOrigin, rng=None)`;
ASSUMED (build plan WP-R1, the generic default): `page.entry_sections(page, scope) -> list[EntrySection]`.
"""
from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_support import WAITING, needs  # noqa: E402
from llm_fill_support import FIX, FixtureDir, browser_page  # noqa: E402

from jobscraper.apply.contracts import ValueOrigin  # noqa: E402

_W0 = len(WAITING)
SCOPE = '[data-automation-id="applyFlowPage"]'
READER = ("jobscraper.apply.page:read_page", "jobscraper.apply.page:entry_sections")


def _sections(pg):
    from jobscraper.apply import page as P
    return P.entry_sections(pg, SCOPE)


def _read(pg, origin: ValueOrigin = ValueOrigin.RESUME_IMPORT):
    from jobscraper.apply import page as P
    return P.read_page(pg, scope=SCOPE, sections=_sections(pg), origin=origin)


@contextmanager
def _open(rel: str):
    got = browser_page()
    if got is None:
        yield None
        return
    pw, browser, pg = got
    try:
        with FixtureDir() as srv:
            pg.goto(srv.url(rel))
            yield pg
    finally:
        browser.close()
        pw.stop()


def _digits(v) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", str(v))]


def _shown(v, typ: str):
    if typ == "multi_choice":
        return sorted(v or [])
    if typ == "date":
        return _digits(v)
    return (v or "").strip() if isinstance(v, str) else v


def _check(fields, expected: list[dict], where: str) -> None:
    got = {(pf.group_title, pf.field.label): pf for pf in fields}
    want = {(e["group_title"], e["label"]): e for e in expected}
    assert set(got) == set(want), (where, sorted(set(got) ^ set(want)))
    assert len(fields) == len(expected), (where, "duplicate or extra controls read")
    for k, e in want.items():
        pf = got[k]
        f = pf.field
        assert f.type.value == e["type"], (where, k, f.type)
        assert pf.widget == e["widget"], (where, k, pf.widget)
        assert f.required is e["required"], (where, k)
        assert pf.group == e["group"], (where, k, pf.group)
        assert pf.options_complete is e["options_complete"], (where, k)
        if e["options"]:
            assert sorted(o.label for o in f.options) == e["options"], (where, k)
        assert _shown(pf.shown, e["type"]) == _shown(e["shown"], e["type"]), (where, k)
        if e["context"]:
            assert pf.context == e["context"], (where, k, "context = the preceding question")
        if e["help"]:
            assert e["help"] in f.description, (where, k, "help text")


def test_the_reader_fixtures_are_present():
    """Always runs (so `-k apply_page_reader` is green before lane R): the pages these oracles read."""
    for rel in ("stubs/honeypot.html", "stubs/prompt_categories.html", "stubs/dates.html", "stubs/reveal.html",
                "wd_a/02-my_information/page.html", "wd_a/03-my_experience/page.html", "shim.js"):
        assert (FIX / rel).is_file(), rel
    assert len(list(FIX.glob("wd_*/*/fields.json"))) == 8


@needs(*READER)
def test_every_wd_a_and_wd_b_page_reads_to_its_expected_fields():
    for step in sorted(FIX.glob("wd_*/*/fields.json")):
        rel = str(step.parent.relative_to(FIX)).replace("\\", "/") + "/page.html"
        with _open(rel) as pg:
            if pg is None:
                return
            _check(_read(pg), json.loads(step.read_text(encoding="utf-8")), rel)


@needs(*READER)
def test_first_read_marks_site_values_with_the_import_origin_and_empties_as_empty():
    with _open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        for pf in _read(pg, origin=ValueOrigin.RESUME_IMPORT):
            want = ValueOrigin.RESUME_IMPORT if pf.shown not in ("", [], None, "false") else None
            if want:
                assert pf.origin is want, pf.field.label
            elif pf.shown in ("", [], None):
                assert pf.origin is ValueOrigin.EMPTY, pf.field.label


@needs(*READER)
def test_honeypots_and_hidden_value_inputs_are_never_read():
    with _open("stubs/honeypot.html") as pg:
        if pg is None:
            return
        assert [pf.field.label for pf in _read(pg)] == ["Given Name(s)"]


@needs(*READER)
def test_a_hierarchical_prompt_lists_category_paths_one_level_down():
    """S-5b error 1: the model must see the leaves, not only the top-level categories."""
    exp = json.loads((FIX / "stubs/prompt_categories.fields.json").read_text(encoding="utf-8"))[0]["options"]
    with _open("stubs/prompt_categories.html") as pg:
        if pg is None:
            return
        (pf,) = _read(pg)
        assert sorted(o.label for o in pf.field.options) == exp
        assert "Company Website > Company Website Charlie" in exp
        assert pg.locator('[data-automation-id="activeListContainer"]').count() == 0, "popup left open"
        assert pg.locator('[data-automation-id="selectedItem"]').count() == 0, "reading chose an option"


@needs(*READER)
def test_dates_read_section_values_never_the_placeholder():
    with _open("stubs/dates.html") as pg:
        if pg is None:
            return
        got = {pf.field.label: pf for pf in _read(pg)}
        assert _digits(got["From"].shown) == [3, 2026]
        for empty in ("To", "Date of Signature", "Graduation Year"):
            assert got[empty].shown in ("", None), (empty, "aria-valuetext holds a placeholder, not a value")


@needs(*READER)
def test_reading_changes_nothing_on_the_page():
    snap = """() => JSON.stringify([...document.querySelectorAll('input,textarea,button[aria-haspopup="listbox"]')]
      .map(e => [e.value, e.checked, e.textContent.trim()]).concat(
      [...document.querySelectorAll('[data-automation-id="selectedItem"]')].map(p => p.title)))"""
    with _open("wd_a/03-my_experience/page.html") as pg:
        if pg is None:
            return
        before = pg.evaluate(snap)
        _read(pg)
        assert pg.evaluate(snap) == before
        assert pg.locator('[data-automation-id="activeListContainer"]').count() == 0


@needs(*READER)
def test_entry_sections_find_every_repeated_entry_with_its_controls():
    with _open("wd_a/03-my_experience/page.html") as pg:
        if pg is None:
            return
        secs = {s.section: s for s in _sections(pg)}
        assert {k: len(v.entries) for k, v in secs.items()} == \
            {"work_experience": 3, "education": 1, "languages": 2, "websites": 1}
        we = secs["work_experience"]
        assert [g.title for g in we.entries] == ["Work Experience 1", "Work Experience 2", "Work Experience 3"]
        assert all(g.delete_locator for g in we.entries) and we.add_locator
        assert pg.locator(we.entries[2].delete_locator).count() == 1


@needs(*READER)
def test_site_errors_are_attached_to_their_fields():
    with _open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        pg.click('[data-automation-id="pageFooterNextButton"]')
        got = {pf.field.label: pf for pf in _read(pg)}
        assert got["Phone Device Type"].error and got["How Did You Hear About Us?"].error
        assert got["Given Name(s)"].error == ""


@needs(*READER)
def test_a_field_revealed_by_an_answer_is_read_on_the_next_read():
    """Review H7: "Yes" reveals a required follow-up; a re-read must find it."""
    with _open("stubs/reveal.html") as pg:
        if pg is None:
            return
        assert [pf.field.label for pf in _read(pg)] == ["Do you have any relatives working at Example Employer?"]
        pg.click("label:text-is('Yes')")
        again = {pf.field.label: pf for pf in _read(pg)}
        assert again["If yes, please specify"].field.required


if WAITING[_W0:]:
    print(f"[test_apply_page_reader] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
