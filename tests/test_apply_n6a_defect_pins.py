"""Pins for the code defects found while settling the WP-N6a oracles (Q-35, 2026-11-07).

Both are in files outside lane N's N-block (contracts / resolve / the page reader). They fail until
fixed; each names its defect id (the outbox entry carries reproduction, expected vs actual, severity).

  D1  `CHOICE_TYPES` is {DROPDOWN, MULTI_CHOICE, RADIO}, but the generic reader types every
      react-select / combobox / Workday prompt as TYPEAHEAD (`page.py` push(..., 'typeahead')).
      Every deterministic option fit in resolve.py / declarations.py / facts.py is gated on
      `CHOICE_TYPES`, so on such a field `fit_decline`, `fit_kind` (enum), `fit_bool` return None:
      a required Gender / race / veteran / disability question on a Greenhouse react-select stops the
      attempt `unanswerable_required` ("profile rule identity.gender: no offered option fits") although
      the option "I don't wish to answer" is on offer. The same field read from the schema API is a
      DROPDOWN and works (old path).
  D2  Greenhouse's resume `<input type=file style=display:none>` behind an "Attach" button is not
      read as a field under the generic reader, so `fill_page` never attaches the resume (no audit
      row, `files.resume` empty). tests/fixtures/apply/greenhouse/form.html mirrors the live markup.
Verify: python tests/run_tests.py -k apply_n6a_defect_pins
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT  # noqa: E402,F401

from jobscraper.apply import resolve  # noqa: E402
from jobscraper.apply.contracts import FieldType, FormField, Option  # noqa: E402

GENDER = ("Male", "Female", "Non-Binary", "I don't wish to answer")
YESNO = ("Yes", "No")


def _field(ftype: FieldType, label: str, options) -> FormField:
    return FormField("f", label, ftype, True, options=tuple(Option(o) for o in options))


def test_d1_the_option_fits_treat_a_typeahead_with_options_like_a_dropdown():
    for label, options, check in (
        ("Gender", GENDER, lambda f: resolve.fit_decline(f)),
        ("Gender", GENDER, lambda f: resolve.fit_kind(f, "enum", "decline", value_map=None, profile={})),
        ("Gender", GENDER, lambda f: resolve.fit_kind(f, "enum", "male", value_map=None, profile={})),
        ("Are you currently an employee?", YESNO, lambda f: resolve.fit_bool(f, False)),
        ("Do you need sponsorship?", YESNO, lambda f: resolve.fit_bool(f, True)),
    ):
        want = check(_field(FieldType.DROPDOWN, label, options))
        assert want is not None, "the DROPDOWN reference must fit"
        got = check(_field(FieldType.TYPEAHEAD, label, options))
        assert got == want, f"D1: {label!r} as a TYPEAHEAD with the same options gives {got!r}, a DROPDOWN {want!r}"


def test_d2_the_greenhouse_hidden_resume_input_is_read_as_a_file_field():
    from apply_flow_support import FixtureServer, edge_available
    if not edge_available():
        return
    from playwright.sync_api import sync_playwright
    from jobscraper.apply import page as P
    with FixtureServer() as fx:
        fx.set_posting("6237419004", "form.html", "")
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel="msedge", headless=True)
            try:
                pg = b.new_page()
                pg.goto(fx.base + "/dataiku/jobs/6237419004")
                fields = P.read_page(pg, scope="", sections=[], origin="", step="form")
            finally:
                b.close()
    files = [pf for pf in fields if pf.field.type is FieldType.FILE]
    assert files, "D2: no FILE field read; the resume would never be attached (labels: " \
        + ", ".join(pf.field.label for pf in fields[:8]) + ")"
    assert any(pf.field.required for pf in files), "the resume is required on this form"
