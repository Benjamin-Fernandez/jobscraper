"""WP-T3: widget family oracles (LF §3.2; review M8, M14). Verify `-k apply_widgets`.

Skip-clean until `jobscraper.apply.widgets` (and the reader) exist. Headless Edge on the synthetic
fixtures; without a browser each test prints a note and passes.

ASSUMED call shapes (build plan WP-R2), all in `_fill` / `_value` below:
  widgets.fill(page, field: PageField, value) -> bool    True only when the read-back equals value
  widgets.read(page, field: PageField) -> Value
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_support import WAITING, needs  # noqa: E402
from test_apply_page_reader import _open, _read  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.page:read_page", "jobscraper.apply.page:entry_sections",
         "jobscraper.apply.widgets:fill", "jobscraper.apply.widgets:read")


def _fill(pg, pf, value) -> bool:
    from jobscraper.apply import widgets as W
    return W.fill(pg, pf, value)


def _value(pg, pf):
    from jobscraper.apply import widgets as W
    return W.read(pg, pf)


def _by_label(pg, group_title: str = ""):
    return {pf.field.label: pf for pf in _read(pg) if pf.group_title == group_title}


def test_the_widget_fixtures_are_present():
    """Always runs (so `-k apply_widgets` is green before lane R): the stubs these oracles drive."""
    from llm_fill_support import FIX
    for rel in ("stubs/listbox_error.html", "stubs/dates.html", "stubs/prompt_categories.html",
                "stubs/enter_form.html", "wd_a/01-autofill_with_resume/page.html", "wd_a/03-my_experience/page.html"):
        assert (FIX / rel).is_file(), rel
    assert '"drop": {"lb-always": "always", "lb-once": "once"}' in (FIX / "stubs/listbox_error.html").read_text(encoding="utf-8")


INPUTS = "() => { window.__n = 0; document.addEventListener('input', () => window.__n++, true); }"


@needs(*NEEDS)
def test_a_listbox_counts_as_filled_only_when_the_site_keeps_the_value():
    """S-5b error 6: the button showed the option, the site held nothing."""
    with _open("stubs/listbox_error.html") as pg:
        if pg is None:
            return
        f = _by_label(pg)
        assert _fill(pg, f["Phone Device Type"], "Mobile") is True
        assert _value(pg, f["Phone Device Type"]) == "Mobile"
        assert _fill(pg, f["Degree"], "Diploma") is False, "text shown + error after blur = not filled"
        assert _fill(pg, f["Country"], "Malaysia") is False
        assert _fill(pg, _by_label(pg)["Country"], "Malaysia") is True, "the corrective fill takes"


@needs(*NEEDS)
def test_dates_fill_by_section_and_an_equal_date_is_not_retyped():
    with _open("stubs/dates.html") as pg:
        if pg is None:
            return
        pg.evaluate(INPUTS)
        f = _by_label(pg)
        assert _fill(pg, f["From"], "2026-03") is True
        assert pg.evaluate("window.__n") == 0, "2026-03 equals the shown 3/2026"
        assert _fill(pg, f["To"], "2025-06") is True
        assert _fill(pg, f["Date of Signature"], "2026-01-05") is True
        assert _fill(pg, f["Graduation Year"], "2025") is True
        vals = pg.evaluate("""() => [...document.querySelectorAll('input[data-automation-id^="dateSection"]')]
              .map(i => i.value).filter(Boolean)""")
        assert sorted(int(v) for v in vals) == sorted([3, 2026, 6, 2025, 5, 1, 2026, 2025])
        got = {k: [int(x) for x in re.findall(r"\d+", str(_value(pg, v)))] for k, v in _by_label(pg).items()}
        assert got["Date of Signature"] in ([5, 1, 2026], [2026, 1, 5])


@needs(*NEEDS)
def test_a_multi_prompt_removes_wrong_pills_and_reads_back_as_a_set():
    with _open("wd_a/03-my_experience/page.html") as pg:
        if pg is None:
            return
        skills = _by_label(pg)["Type to Add Skills"]
        assert _fill(pg, skills, ["Python", "PostgreSQL"]) is True
        assert sorted(_value(pg, skills)) == ["PostgreSQL", "Python"]


@needs(*NEEDS)
def test_a_category_leaf_is_chosen_through_its_category():
    with _open("stubs/prompt_categories.html") as pg:
        if pg is None:
            return
        (pf,) = _read(pg)
        assert _fill(pg, pf, "Company Website > Company Website Charlie") is True
        assert pg.locator('[data-automation-id="selectedItem"]').get_attribute("title") == "Company Website Charlie"


@needs(*NEEDS)
def test_an_upload_reads_back_by_the_file_name_shown():
    with _open("wd_a/01-autofill_with_resume/page.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        path = Path(tmp) / "Alex_Testcase_Resume.pdf"
        path.write_bytes(b"%PDF-1.4\n%synthetic\n")
        (pf,) = _read(pg)
        assert _fill(pg, pf, str(path)) is True
        assert _value(pg, pf) == "Alex_Testcase_Resume.pdf"      # input.files is emptied by the site


@needs(*NEEDS)
def test_text_radio_and_checkbox_round_trip():
    with _open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        f = _by_label(pg)
        assert _fill(pg, f["Phone Extension"], "12") and _value(pg, f["Phone Extension"]) == "12"
        q = "Have you previously worked for Example Employer?"
        assert _fill(pg, f[q], "No") and _value(pg, f[q]) == "No"
        assert _fill(pg, f["I have a preferred name"], "true") and _value(pg, f["I have a preferred name"]) == "true"


@needs(*NEEDS)
def test_enter_is_never_pressed_inside_a_form_with_a_submit_control():
    """Review M8: an implicit submit would bypass submit_clicked_at (NF-06)."""
    with _open("stubs/enter_form.html") as pg:
        if pg is None:
            return
        f = _by_label(pg)
        assert _fill(pg, f["City"], "Singapore") is True
        _fill(pg, f["Country Phone Code"], "Malaysia (+60)")
        assert pg.evaluate("document.body.dataset.formSubmits") == "0"


@needs(*NEEDS)
def test_a_search_driven_prompt_reads_back_the_intended_option_not_the_first_hit():
    """Review M14: every family reads back equal to the intended value."""
    with _open("stubs/enter_form.html") as pg:
        if pg is None:
            return
        pf = _by_label(pg)["Country Phone Code"]
        assert _fill(pg, pf, "Malaysia (+60)") is True
        assert _value(pg, pf) == "Malaysia (+60)"


if WAITING[_W0:]:
    print(f"[test_apply_widgets] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
