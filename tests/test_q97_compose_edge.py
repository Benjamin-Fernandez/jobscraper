"""Q-97, the Edge part: composed texts on a real page (llm_fill_design section 19.2 / 19.3, WP-K3).

The flow oracles in test_apply_flow_compose.py replace `fill_page`, so nothing tested the real
step 7b (`pagefill._compose_split`, `_composed_path`), L8 (`locks._compose_lock`) and the real upload
of the letter file. These pins run the real `apply_flow.run` (real Workday navigator, subclassed only
to open a local page) with the real `fill_page` over `flow_llm/compose_step.html`: a required
cover-letter FILE input, a required "Why do you want to join us?" TEXTAREA and one ordinary field
(Given Name(s)); Next goes to `compose_review.html`. The model is `FakeFillBackend` (scripted: it
only answers the ordinary field); `tailor_flow.compose` is a recording fake (no real model); the
letter file is written by the REAL `tailor_flow.write_letter`. Headless Edge on 127.0.0.1, temp DB,
synthetic applicant, no network.

  1. compose off (default): failed(unanswerable_required), the targets are captured with
     `compose_needed: off`, the page is as the site put it (no file, empty textarea, Next never
     pressed), submit count 0;
  2. compose on, passing texts: textarea holds the composed text, the FILE input received
     `cover_letter.<docx|txt>` from the attempt folder (the name the page shows is the path in
     `composed_files`), audit rows are source `composed` / rule `compose:v1`, the dry run ends
     ready_to_submit on the Review page, nothing submitted;
  3. compose on, a draft fails its check: `compose_needed: failed check`, nothing filled.

Each test probes Edge with `llm_fill_support.browser_page()` first and returns early when it is None
(the full suite skips the Edge tests after a leaked asyncio loop, peer Q-84). Run on its own:
`python tests/run_tests.py -k q97`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402

GATE = ("jobscraper.apply.pagefill:fill_page", "jobscraper.apply_flow:_fill_services",
        "jobscraper.apply_flow:_Run.compose_step")
START = "flow_llm/compose_step.html"
WHY = "Why do you want to join us?"
COVER = "Cover Letter"
TEXT = ("I want to join Example Employer because I enjoy building reliable tools, and my internship "
        "taught me to ship small tested changes.")
# The page's own readout: `live` is the step page as it is now; `saved` is what the step page held when
# Next was pressed (the fixture keeps it in sessionStorage, the Review page cannot show it).
PAGE_JS = """() => { const a = document.querySelector('#input-21'); const s = sessionStorage.getItem('q97');
  return {live: a ? {area: a.value, given: document.querySelector('#input-9').value,
    files: [...document.querySelectorAll('[data-automation-id="file-upload-item-name"]')].map(e => e.textContent.trim())} : null,
    saved: s ? JSON.parse(s) : null}; }"""


def test_q97_fixtures_are_present():
    d = Path(__file__).resolve().parent / "fixtures" / "apply" / "flow_llm"
    step = (d / "compose_step.html").read_text(encoding="utf-8")
    assert 'type="file"' in step and "<textarea" in step and WHY in step and "applyFlowPage" in step
    assert (d / "compose_review.html").is_file()


def _probe() -> bool:
    from llm_fill_support import browser_page
    p = browser_page()
    if p is None:
        return False
    p[1].close()
    p[0].stop()
    return True


def _backend():
    """Scripted: answers the one ordinary field. The question-naming call that follows a capture is
    refused (BackendError -> "naming unavailable", the capture itself is unaffected)."""
    from llm_fill_support import FakeFillBackend, field_views
    from jobscraper.backends import BackendError

    class Fake(FakeFillBackend):
        def complete(self, system, user, *a, **k):
            if not field_views(user):
                raise BackendError("fake: naming not scripted")
            return super().complete(system, user, *a, **k)
    given = {"|Given Name(s)": {"source": "profile", "ref": "profile:identity.legal_first_name",
                                "value": "Alex", "evidence": ""}}
    return Fake(replies=[{"kind": "page", "repeat": True, "reply": given}], strict=True)


class _Compose:
    """Recording fake of `tailor_flow.compose` (no model); `write_letter` stays the real one."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, cfg, req, *, backend, redact, timeout=None):
        self.calls.append(req)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def _only_the_ordinary_field_went_to_the_model(out) -> None:
    calls = [c for c in out.backend.calls if c.kind == "page"]
    assert calls, "the ordinary field goes to the model"
    for c in calls:
        assert all(WHY not in k and COVER not in k for k in c.keys), c.keys


def _ok(text=TEXT):
    from jobscraper.tailor.contracts import ComposeResult
    return ComposeResult(True, text, (), "fake-model:1b", "h" * 16, 1, "")


def _run(compose_on: bool, fake=None, *, fmt="txt"):
    """One attempt over compose_step.html; the page state at the end and the compose fake."""
    import test_apply_flow_llm as L
    from jobscraper import tailor_flow
    from jobscraper.config import ComposeConfig
    over = {"compose": ComposeConfig(enabled=compose_on, file_format=fmt)}
    saved, saved_js = tailor_flow.compose, L.FINAL_JS
    if fake is not None:
        tailor_flow.compose = fake
    L.FINAL_JS = ("() => { const b = (" + saved_js + ")(); b.q97 = (" + PAGE_JS + ")(); return b; }")
    try:
        return L._run_fixture(START, _backend(), acfg_over=over)
    finally:
        tailor_flow.compose, L.FINAL_JS = saved, saved_js


@needs(*GATE)
def test_q97_1_compose_off_captures_the_targets_and_leaves_the_page_alone():
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    if not _probe():
        return
    fake = _Compose(_ok())
    out = _run(False, fake)
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail in (WHY, COVER), r.reason_detail
        assert fake.calls == [], "composing is off: the compose call is never made"
        _only_the_ordinary_field_went_to_the_model(out)
        groups = w.store.question_groups("all")
        labels = sorted(lab for g in groups for lab in g["labels"])
        assert labels == sorted([COVER, WHY]), labels
        assert {g["reason"] for g in groups} == {"compose_needed"}, [(g["labels"], g["reason"]) for g in groups]
        rows = w.store.answers(r.attempt_id)
        notes = {x["note"] for x in rows if x["status"] == "unknown" and x["note"]}
        assert any(n.startswith("compose_needed: off") for n in notes), notes
        assert not [x for x in rows if x["status"] == "filled"], [(x["field_key"], x["status"]) for x in rows]
        end = out.final
        assert end["submit"] == "0" and end["next"] == "0", end
        assert end["inputs"] == 0, "no input event: the page is exactly as the site put it"
        page = end["q97"]["live"]
        assert page == {"area": "", "given": "", "files": []}, end["q97"]
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None
        assert not list((w.tmp / "evidence" / str(r.attempt_id)).glob("cover_letter*")), "no letter written"
    finally:
        w.close()


@needs(*GATE)
def test_q97_2_compose_on_fills_the_textarea_uploads_the_letter_and_reaches_ready_to_submit():
    from jobscraper.apply.contracts import AttemptState as S
    if not _probe():
        return
    fake = _Compose(_ok(TEXT), _ok(TEXT))
    out = _run(True, fake)
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail, out.say.text[-1500:])
        assert len(fake.calls) == 2, [c.kind for c in fake.calls]
        assert sorted(c.kind for c in fake.calls) == ["answer", "letter"]
        end = out.final
        assert end["path"].endswith("/compose_review.html") and end["submit"] == "0", end
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None
        step = end["q97"]["saved"]
        assert step["area"] == TEXT and step["given"] == "Alex", step
        assert len(step["files"]) == 1, step
        name = step["files"][0]
        assert name.startswith("cover_letter") and Path(name).suffix in (".docx", ".txt"), name
        folder = w.tmp / "evidence" / str(r.attempt_id)
        assert (folder / name).is_file(), (name, list(folder.iterdir()))
        rows = w.store.answers(r.attempt_id)
        composed = [x for x in rows if x["source"] == "composed"]
        assert len(composed) == 2, [(x["field_key"], x["source"], x["status"]) for x in rows]
        assert {x["rule_id"] for x in composed} == {"compose:v1"} and {x["status"] for x in composed} == {"filled"}
        assert len([x for x in composed if TEXT in x["value_json"]]) == 2,             [x["value_json"] for x in composed]      # the whole text (this one has no "/": see the defect pin)
        assert all(TEXT not in k for c in out.backend.calls for k in c.keys + (c.user,)), "the model never sees the text"
    finally:
        w.close()


@needs(*GATE)
def test_q97_3_a_draft_that_fails_its_check_is_captured_and_nothing_is_filled():
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    from jobscraper.tailor.contracts import ComposeResult, IssueCode, ValidationIssue
    if not _probe():
        return
    fake = _Compose(ComposeResult(False, "", (ValidationIssue(IssueCode.FACT_ADDED, None, "kafka"),), "m", "h", 2, ""))
    out = _run(True, fake)
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
        assert len(fake.calls) == 1, "the first failed draft ends the attempt"
        assert "compose_needed" in out.say.text and "failed check" in out.say.text, out.say.text[-800:]
        rows = w.store.answers(r.attempt_id)
        assert any((x["note"] or "").startswith("compose_needed: failed check") for x in rows), \
            [(x["field_key"], x["note"]) for x in rows]
        assert not [x for x in rows if x["status"] == "filled"]
        end = out.final
        assert end["submit"] == "0" and end["next"] == "0" and end["inputs"] == 0, end
        assert not list((w.tmp / "evidence" / str(r.attempt_id)).glob("cover_letter*")), "no letter written"
    finally:
        w.close()


SLASH = "I enjoy CI/CD work and building small reliable tools, so I want to join Example Employer."


@needs(*GATE)
def test_q97_defect_the_audit_value_of_a_composed_file_row_is_the_whole_text():
    """DEFECT PIN (expected to fail until fixed; reported to the engineer as Q-97 D1). LF section
    19.5: "`value` is the whole text, for a FILE too, where the note names the uploaded file".
    `apply_flow._sent_value` treats a FILE row's value as a PATH (`Path(str(a.value)).name`), but for
    a composed row the value is the letter's text, so a text with a "/" (here "CI/CD") is cut at the
    last separator and the audit loses the start of the letter. It also writes sha256 "" (the text
    is not a readable file). The textarea row is unaffected."""
    from jobscraper.apply.contracts import AttemptState as S
    if not _probe():
        return
    out = _run(True, _Compose(_ok(SLASH), _ok(SLASH)))
    if out is None:
        return
    w, r = out.w, out.r
    try:
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
        rows = {x["label"]: x for x in w.store.answers(r.attempt_id) if x["source"] == "composed"}
        assert SLASH in rows[WHY]["value_json"], "the textarea row holds the whole text"
        assert SLASH in rows[COVER]["value_json"], rows[COVER]["value_json"]
        assert rows[COVER]["note"].startswith("composed file: cover_letter"), rows[COVER]["note"]
    finally:
        w.close()
