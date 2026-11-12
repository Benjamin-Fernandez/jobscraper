"""Q-119 pins: the generic reader reads ONE field per react-select. Verify `-k select_helpers`.

Defect (owner's first live auto-apply, Greenhouse): an EMPTY react-select renders a hidden helper
`input[required][tabindex=-1][aria-hidden=true]` (class ending `requiredInput`) as the last child of
its `.select-shell`. The reader returned it as a second, label-less, required field that nothing
could answer. Fix (page.py READER_JS): an input that is aria-hidden AND out of the tab order is a
widget helper and is skipped; the real combobox is marked required when such a helper sits in its
`.select__container`.

Page: tests/fixtures/apply/greenhouse_select_helpers.html (anonymised, hand-written markup, static
HTML and inline CSS). Same skip-clean pattern as tests/test_apply_page_reader.py: headless Edge on a
127.0.0.1 server; without a browser the test prints a note and returns (it does not assert).

Not pinned here, by design: the grouping of the education fields (open design item, Q-119 B).
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_fill_support import FixtureDir, browser_page  # noqa: E402

ROOT = Path(__file__).resolve().parent / "fixtures" / "apply"
PAGE = "greenhouse_select_helpers.html"
SELECTS = ["Country", "How did you hear about us?", "Pronouns", "School", "Degree"]


@contextmanager
def _open():
    got = browser_page()
    if got is None:
        yield None
        return
    pw, browser, pg = got
    try:
        with FixtureDir(ROOT) as srv:
            pg.goto(srv.url(PAGE))
            yield pg
    finally:
        browser.close()
        pw.stop()


def _read(pg):
    from jobscraper.apply import page as P
    return P.read_page(pg, scope="", sections=P.entry_sections(pg, ""))


def test_the_select_helper_fixture_is_present_and_has_the_helpers():
    """Always runs: the page exists, is static, and really carries the hidden twins the fix targets."""
    html = (ROOT / PAGE).read_text(encoding="utf-8")
    assert "<script" not in html.lower() and "http" not in html.lower()
    assert html.count('aria-hidden="true" class="css-1x2y3z-requiredInput"') == 4   # 4 of the 5 selects
    assert html.count('role="combobox"') == 5


def test_each_react_select_is_read_as_one_field_with_its_real_label():
    """(a) the five selects give exactly five react_select fields, labelled, and nothing has an empty label."""
    with _open() as pg:
        if pg is None:
            return
        fields = _read(pg)
        assert all(pf.field.label.strip() for pf in fields), [pf.field.key for pf in fields if not pf.field.label.strip()]
        selects = [pf.field.label for pf in fields if pf.widget == "react_select"]
        assert selects == SELECTS, selects


def test_a_select_is_required_when_only_its_helper_says_so():
    """(b) 'How did you hear about us?' has no aria-required and no '*': the helper is the only signal.
    'Pronouns' has no helper and no signal: not required."""
    with _open() as pg:
        if pg is None:
            return
        req = {pf.field.label: pf.field.required for pf in _read(pg) if pf.widget == "react_select"}
        assert req["How did you hear about us?"] is True, req
        assert req["Degree"] is True, req          # helper only, inside the education block too
        assert req["Country"] is True and req["School"] is True      # aria-required + helper
        assert req["Pronouns"] is False, req


def test_the_skip_rule_hides_only_helpers_and_the_education_fields_are_all_read():
    """(c) a plain visible input[required] and an aria-hidden input that IS in the tab order are still read;
    (d) the education block's fields are all read with their labels (grouping is a separate open item)."""
    with _open() as pg:
        if pg is None:
            return
        by = {pf.field.label: pf for pf in _read(pg)}
        assert by["Full name"].field.required is True            # (c) visible required text field
        assert "Preferred name" in by                            # (c) aria-hidden but tabindex 0: a real field
        assert "Phone number" in by
        for label in ("School", "Degree", "Start date year", "End date year"):   # (d)
            assert label in by, sorted(by)
        assert len(by) == 10, sorted(by)                         # 5 selects + 5 inputs; no helper twins
