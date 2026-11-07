"""WP-T3 (amended): `apply.pagefill.fill_page` oracles (LF §8; review H3, H7, M6, M9; TR-7, TR-9).
Verify `-k apply_pagefill` (owns WP-R3's Verify).

Skip-clean until pagefill and the lane M modules it calls exist. Headless Edge on the synthetic
fixtures, the scripted FakeFillBackend (strict: an unscripted model call fails the test and names
the call), a recording `FillServices` fake and a minimal navigator. Signatures are the ones LF §8
pins: `fill_page(page, nav, ctx, rctx, services) -> PageOutcome`, `page.scan_required(page, scope)`.
"""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_support import WAITING, needs  # noqa: E402
from llm_fill_support import FIX, SAMPLE, FakeFillBackend  # noqa: E402
from test_apply_page_reader import SCOPE, _open, _read  # noqa: E402

from jobscraper.apply.contracts import (  # noqa: E402
    AttemptContext, EntrySection, PasswordRules, ResolveContext, StepResult, Tenant, ValueOrigin,
)

_W0 = len(WAITING)
ROOT = Path(__file__).resolve().parents[1]
FILL = ("jobscraper.apply.pagefill:fill_page", "jobscraper.apply.page:read_page", "jobscraper.apply.widgets:fill",
        "jobscraper.apply.locks:lock_page", "jobscraper.apply.guards:decide", "jobscraper.apply.llm_fill:ask",
        "jobscraper.apply.facts:fact_catalogue")
CFG = {"num_ctx": 32768, "page_timeout_s": 120, "max_fields_per_call": 20, "long_list": 15, "keep_alive": "",
       "second_opinion": True, "cache": True, "max_followups": 25, "max_reveal_rounds": 2, "debug_dump": False}
# Snapshot of everything a fill could change: values, ticks, pills, listbox texts, entry panels.
SNAP = """() => JSON.stringify({
  v: [...document.querySelectorAll('input,textarea')].map(e => [e.value, e.checked]),
  b: [...document.querySelectorAll('button[aria-haspopup="listbox"]')].map(e => e.textContent.trim()),
  p: [...document.querySelectorAll('[data-automation-id="selectedItem"]')].map(e => e.title),
  g: document.querySelectorAll('[role="group"][data-entry]').length,
  f: [...document.querySelectorAll('[data-automation-id="file-upload-item-name"]')].map(e => e.textContent)})"""
INPUTS = """() => { window.__ev = 0; for (const t of ['input', 'change'])
  document.addEventListener(t, () => window.__ev++, true); }"""


# The synthetic resume `_world` writes. `_fill`'s temp dir is gone when it returns, so an oracle
# hashes these bytes, never `ctx.resume_path` (lane R's R3 run, 2026-11-03).
RESUME_BYTES = b"%PDF-1.4\n%synthetic sample resume\n"


class FakeServices:
    """FillServices with a pinned clock; records classify calls with the page's event count then."""

    def __init__(self, backend, page=None, deadline: float = 600.0):
        from jobscraper.apply import resolve
        self.backend, self.model, self.cfg = backend, "fake-fill:1", dict(CFG)
        self.rules = resolve.load_rules(ROOT / "config" / "questions.yaml")
        self._page, self._deadline = page, deadline
        self.classified: list[int] = []
        self.puts: list[Any] = []
        self.lines: list[str] = []

    def today(self) -> str: return "2026-11-03"
    def now(self) -> float: return 1793700000.0
    def deadline_left(self) -> float: return self._deadline
    def cache_get(self, job_id, sigs, prompt_version, model, inputs_hash) -> dict: return {}
    def cache_put(self, job_id, rows) -> None: self.puts.append(rows)
    def log(self, line: str) -> None: self.lines.append(line)

    def classify(self, page) -> None:
        self.classified.append(page.evaluate("() => window.__ev || 0"))


class FakeNav:
    name, needs_account, password_rules, mail_domains, otp_pattern = "fakewd", True, PasswordRules(), (), ""

    def __init__(self, step: str): self.step = step
    def match_url(self, url): return None
    def tenant_from_company(self, job): return None
    def precheck(self, ctx): return None
    def open(self, page, ctx): return None
    def choose_entry(self, page, ctx): return "resume_import"
    def account_wall(self, page): return None
    def sign_in(self, page, ctx, password): return None
    def sign_up(self, page, ctx, password): return ""
    def enter_code(self, page, ctx, code): return None
    def step_id(self, page, ctx): return self.step
    def scope(self, page, ctx): return SCOPE
    def next_step(self, page, ctx): return StepResult(step="next")
    def submit(self, page, ctx): raise AssertionError("fill_page must never submit")
    def after_submit(self, page, ctx): return None
    def visible_errors(self, page): return ()

    def entry_sections(self, page, ctx) -> list[EntrySection]:
        from jobscraper.apply import page as P
        return P.entry_sections(page, SCOPE)


def _world(tmp: Path, **profile_changes):
    p = copy.deepcopy(yaml.safe_load(SAMPLE.read_text(encoding="utf-8")))
    for path, v in profile_changes.items():
        a, b = path.split("__")
        p[a][b] = v
    resume = tmp / "Alex_Testcase_Resume.pdf"
    resume.write_bytes(RESUME_BYTES)
    ctx = AttemptContext(attempt_id=1, job={"id": "job-1", "company": "Example Employer"},
                         tenant=Tenant(ats="workday", host="example.test", board="example"), dry_run=True,
                         email=p["contact"]["email"], resume_path=str(resume), log=lambda s: None,
                         screenshot=lambda pg, s: "", deadline=0.0, prefill=ValueOrigin.RESUME_IMPORT.value)
    rctx = ResolveContext(profile=p, employer_name="Example Employer", jd_text=(FIX / "jd_sample.txt").read_text(),
                          resume_text=(FIX / "resume_sample.txt").read_text(), resume_path=str(resume),
                          ats="workday", account_email=p["contact"]["email"])
    return ctx, rctx


def _fill(pg, step: str, reply_file: Path | None, *, deadline: float = 600.0, **profile_changes):
    from jobscraper.apply.pagefill import fill_page
    fb = FakeFillBackend.from_file(reply_file) if reply_file else FakeFillBackend(replies=[])
    with tempfile.TemporaryDirectory() as tmp:
        ctx, rctx = _world(Path(tmp), **profile_changes)
        sv = FakeServices(fb, pg, deadline)
        pg.evaluate(INPUTS)
        out = fill_page(pg, FakeNav(step), ctx, rctx, sv)
        return out, ctx, sv, fb


@needs(*FILL)
def test_a_page_that_stops_is_left_exactly_as_the_site_put_it():
    """M9 / TR-7: step 7 returns before ANY fill, clear, reset, delete or add (wd_b, S-5b)."""
    with _open("wd_b/02-my_information/page.html") as pg:
        if pg is None:
            return
        before = pg.evaluate(SNAP)
        out, _ctx, sv, _fb = _fill(pg, "my_information", FIX / "wd_b/02-my_information/reply.json")
        labels = {pf.field.key: pf.field.label for pf in out.fields}
        assert [labels[k] for k in out.unknown_required] == ["Address Line 2"]
        assert out.transport_failed is False and out.fill_failed == ()
        assert pg.evaluate(SNAP) == before and pg.evaluate("window.__ev") == 0
        assert sv.classified == [], "no classify: nothing is about to be typed"


@needs(*FILL)
def test_no_time_left_stops_before_any_model_call_or_typing():
    with _open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        before = pg.evaluate(SNAP)
        out, _ctx, _sv, fb = _fill(pg, "my_information", FIX / "wd_a/02-my_information/reply.json", deadline=0.0)
        assert fb.calls == [] and pg.evaluate(SNAP) == before
        assert out.unknown_required or out.transport_failed


@needs(*FILL)
def test_classify_runs_before_the_first_keystroke():
    """M6: AD §8.4 'classify before each fill' (model calls can take minutes)."""
    with _open("wd_a/02-my_information/page.html") as pg:
        if pg is None:
            return
        _out, _ctx, sv, _fb = _fill(pg, "my_information", FIX / "wd_a/02-my_information/reply.json")
        assert sv.classified and sv.classified[0] == 0


@needs(*FILL)
def test_an_upload_is_recorded_in_ctx_uploaded_with_its_hash():
    """L1: only files this attempt uploaded are ever kept (H6)."""
    with _open("wd_a/01-autofill_with_resume/page.html") as pg:
        if pg is None:
            return
        out, ctx, _sv, fb = _fill(pg, "autofill_with_resume", None)
        assert fb.calls == [], "FILE fields never reach the model"
        want = hashlib.sha256(RESUME_BYTES).hexdigest()
        assert ctx.uploaded == {"Alex_Testcase_Resume.pdf": want}
        assert pg.inner_text('[data-automation-id="file-upload-item-name"]') == "Alex_Testcase_Resume.pdf"
        assert out.unknown_required == () and out.fill_failed == ()


@needs(*FILL)
def test_a_required_field_revealed_by_our_answer_gets_a_second_round_and_stops_when_unanswerable():
    """H7: "Yes" (a declaration lock, relatives true) reveals a required textarea."""
    reply = {"calls": [{"kind": "page", "repeat": True, "reply": {"|If yes, please specify": {
        "source": "unknown", "ref": "", "value": "", "evidence": ""}}}]}
    with _open("stubs/reveal.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        rf = Path(tmp) / "reply.json"
        rf.write_text(__import__("json").dumps(reply), encoding="utf-8")
        out, _ctx, _sv, fb = _fill(pg, "questions", rf, declarations__relatives_at_company=True)
        labels = {pf.field.key: pf.field.label for pf in out.fields}
        assert "If yes, please specify" in [labels.get(k, "") for k in out.unknown_required]
        assert [c.keys for c in fb.calls] == [("|If yes, please specify",)]


@needs(*FILL, "jobscraper.apply.page:scan_required")
def test_scan_required_lists_visible_required_controls_that_are_empty():
    from jobscraper.apply import page as P
    with _open("wd_b/02-my_information/page.html") as pg:
        if pg is None:
            return
        labels = {pf.field.key: pf.field.label for pf in _read(pg)}
        hit = {labels.get(k, k) for k in P.scan_required(pg, SCOPE)}
        assert {"How Did You Hear About Us?", "Address Line 2", "Phone Device Type"} <= hit
        assert "Given Name(s)" not in hit and "Phone Extension" not in hit


@needs(*FILL)
def test_my_experience_fixes_every_s5b_entry_error_before_moving_on():
    """S-5b 3, 4, 5, 6 and E3 on wd_a My Experience, with G9 leftovers cleared (H3)."""
    with _open("wd_a/03-my_experience/page.html") as pg:
        if pg is None:
            return
        out, _ctx, _sv, _fb = _fill(pg, "my_experience", FIX / "wd_a/03-my_experience/reply.json")
        assert out.unknown_required == () and out.fill_failed == (), (out.unknown_required, out.fill_failed)
        values = pg.evaluate("() => [...document.querySelectorAll('input,textarea')].map(e => e.value).join('|')")
        assert "Campus Robot League" not in values, "E3: the junk entry is deleted"
        we = {pf.field.label: pf for pf in _read(pg) if pf.group_title == "Work Experience 1"}
        assert "Projects:" not in str(we["Role Description"].shown), "E4: recheck replaced the parser text"
        we2 = {pf.field.label: pf for pf in _read(pg) if pf.group_title == "Work Experience 2"}
        assert we2["Location"].shown in ("", None), "G6 + G9: header city rejected, then cleared"
        assert "Japanese" not in [pf.shown for pf in _read(pg) if pf.field.label == "Language"], \
            "E3/E6: the language the profile doesn't list is gone"


if WAITING[_W0:]:
    print(f"[test_apply_pagefill] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))


def test_the_pagefill_fixtures_are_present():
    """Always runs (so `-k apply_pagefill` is green before lanes M and R)."""
    for rel in ("wd_b/02-my_information/reply.json", "wd_a/02-my_information/reply.json",
                "wd_a/03-my_experience/reply.json", "stubs/reveal.html", "resume_sample.txt", "jd_sample.txt"):
        assert (FIX / rel).is_file(), rel
    assert (ROOT / "config" / "questions.yaml").is_file()
