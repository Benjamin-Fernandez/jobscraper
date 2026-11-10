"""Q-80 pins (KA-1): six review findings, each red on personal ee4d8a0 and green once fixed.

  R3 re-review (docs/reviews/Q-35-R3-rereview.md)
    F12  one failed delete must not make a successful delete in the same section look unconfirmed
    F14  a failed E5 Add must not mark already-filled entries "E5: entry not added"
  N6a review (docs/reviews/Q-35-N6a.md)
    F3   the attempt deadline starts after the warm-up (injected clock, no sleeping)
    F4   a hidden file input with only an unrelated sibling button (a Submit) is not a file field
    F5   the model_unavailable detail tells a timeout from a model that is missing or refuses
    F6   rows that were typed are not marked "not applied" after a later stop in the same page

Headless Edge on local pages only (the F12 / F14 stubs, an inline F4 page, a local Greenhouse
fixture server for F6); the model is scripted. F3 and F5 need no browser. Controls (the
behaviour that must NOT change) sit next to each pin so a fix that just drops the check stays red.
Skip-clean without Edge. Verify: python tests/run_tests.py -k apply_q80
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import edge_available  # noqa: E402
from apply_support import needs  # noqa: E402
import test_apply_pagefill as P  # noqa: E402
from test_apply_pagefill_review import (  # noqa: E402
    ENTRY_REPLY, OPTIONAL_REPLY, SWALLOW, _reply_file, _run, _values,
)
from test_apply_flow_n6a import FakeModel, FakeNav, ans, outcome, pf, run, scripted, two_steps, world  # noqa: E402

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus, AttemptState as S, FieldType, ReasonCode as R,
)

FILL = P.FILL
DELETE_NOTE = "E3: delete not confirmed"
DELETE_SEL = '[data-entry="{n}"] [data-automation-id="panel-set-delete-button"]'


def _by_group(out, title: str) -> set:
    return {x.field.key for x in out.fields if x.group_title == title}


# ------------------------------------------------------------------ R3 F12

@needs(*FILL)
def test_f12_one_swallowed_delete_does_not_make_the_delete_that_worked_look_unconfirmed():
    """Two junk entries (2 and 3) in one section; the delete of 3 works, the delete of 2 is
    swallowed. Only entry 2 is "not confirmed": its required fields stop the page. Entry 3 is
    really gone, so none of its keys may be in `unknown_required` or carry the E3 note."""
    with P._open("stubs/q80_entries3.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(SWALLOW, DELETE_SEL.format(n=2))
        out, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
        shown = _values(pg)
        assert "Chess Club Treasurer" not in shown, "the delete of entry 3 should have worked"
        assert "Campus Robot League" in shown, "the delete of entry 2 was swallowed"
        k2, k3 = _by_group(out, "Work Experience 2"), _by_group(out, "Work Experience 3")
        assert k2 and k3, ("the outcome must still list both groups", [x.group_title for x in out.fields])
        stopped = set(out.unknown_required)
        assert k2 & stopped, "control: the entry that is still there stops the page"
        assert not (k3 & stopped), f"F12: entry 3 is gone but its keys are unknown_required: {sorted(k3 & stopped)}"
        noted = [k for k in k3 if k in out.answers and DELETE_NOTE in (out.answers[k].note or "")]
        assert not noted, f"F12: entry 3 carries the E3 note: {noted}"


# ------------------------------------------------------------------ R3 F14

@needs(*FILL)
def test_f14_a_failed_add_does_not_mark_the_entries_that_were_filled_as_not_added():
    """D-173 (ruling on R3 F14): the Add control is swallowed. The attempt keeps stopping
    (fail closed): (a) the section's keys are still in `fill_failed` or `unknown_required`.
    The wording was the defect: (b) no row's note says "entry not added" (that reads as if a
    value we typed were missing) and (c) a note names the section and says another entry
    "could not be added"."""
    with P._open("stubs/review_entries.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(SWALLOW, '[data-automation-id="add-button"]')
        out, _r, sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
        section_keys = {x.field.key for x in out.fields}
        assert section_keys, "the outcome lists the section's fields"
        stopped = (set(out.fill_failed) | set(out.unknown_required)) & section_keys
        assert stopped, "(a) a failed Add must keep the page stopping: nothing in fill_failed / unknown_required"
        notes = {k: (a.note or "") for k, a in out.answers.items()}
        old = sorted(k for k, n in notes.items() if "entry not added" in n.lower())
        assert not old, f"(b) the old wording 'entry not added' is on rows: {old}"
        named = [n for k, n in notes.items()
                 if "could not be added" in n.lower() and "work experience" in n.lower().replace("_", " ")]
        assert named, ("(c) no row note names the section and says another entry could not be added",
                       sorted(set(notes.values())))


# ------------------------------------------------------------------ review M1 (F12 cross-check)

# A site that re-creates a deleted entry without the reader's mark: the delete click works, the
# old group's controls are gone from the page, but a fresh copy takes its place. Keys alone say
# "gone"; the section count (2 entries, 1 expected) says the delete did not happen.
RECREATE = """sel => document.addEventListener('click', ev => {
  const btn = ev.target.closest(sel);
  const grp = btn && btn.closest('[role="group"][data-entry]');
  if (!grp) return;
  const copy = grp.cloneNode(true), host = grp.parentElement, next = grp.nextElementSibling;
  copy.querySelectorAll('[data-llmfill]').forEach(e => e.removeAttribute('data-llmfill'));
  copy.removeAttribute('data-llmfill');
  setTimeout(() => host.insertBefore(copy, next), 0);      // after the site's own delete has run
}, true)"""


@needs(*FILL)
def test_m1_a_delete_that_the_keys_call_done_but_the_section_count_denies_stops_the_page():
    """Review M1: the section count is the independent signal. Entry 2's delete is clicked, its
    marked controls vanish, but an unmarked copy takes its place (count 2, expected 1). The
    required fields of the entry must stop the page with an E3 "delete not confirmed" note."""
    with P._open("stubs/review_entries.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(RECREATE, DELETE_SEL.format(n=2))
        out, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
        k2 = _by_group(out, "Work Experience 2")
        assert k2, [x.group_title for x in out.fields]
        stopped = k2 & set(out.unknown_required)
        assert stopped, ("M1: the section still has its old count but nothing stopped the page",
                         out.unknown_required, out.fill_failed)
        assert any("delete not confirmed" in (out.answers[k].note or "").lower() for k in stopped if k in out.answers),             sorted({(out.answers[k].note or "") for k in stopped if k in out.answers})


# ------------------------------------------------------------------ review M2a (F5, pagefill half)

def _transport_notes(out) -> set:
    return {a.note for a in out.answers.values() if (a.note or "").startswith("transport:")}


@needs(*FILL)
def test_m2a_a_backend_error_in_the_page_call_is_noted_model_unavailable_not_timed_out():
    """`fill_page` with a scripted model that refuses (BackendError, no timeout in the text):
    the rows say "transport: model unavailable". A scripted TimeoutError says "timed out"."""
    for raiser, want, other in (("BackendError", "transport: model unavailable", "timed out"),
                                ("timeout", "transport: timed out", "model unavailable")):
        with P._open("wd_a/02-my_information/page.html") as pg, tempfile.TemporaryDirectory() as tmp:
            if pg is None:
                return
            calls = [{"kind": "page", "repeat": True, "match": "FIELDS", "raise": raiser}]
            out, _r, _sv, _fb = _run(pg, "my_information", _reply_file(Path(tmp), calls))
            notes = _transport_notes(out)
            assert out.transport_failed is True, raiser
            assert notes == {want}, (raiser, notes)
            assert not any(other in n for n in notes), (raiser, notes)


@needs(*FILL)
def test_m2a_a_backend_error_in_a_pick_call_is_noted_model_unavailable_not_timed_out():
    """The same split on the other path (`_picker`): the page call answers, the option pick fails."""
    for raiser, want in (("BackendError", "transport: model unavailable"), ("timeout", "transport: timed out")):
        calls = [c if c.get("kind") != "pick" else {"kind": "pick", "repeat": True, "match": "", "raise": raiser}
                 for c in OPTIONAL_REPLY]
        with P._open("stubs/review_optional_prompt.html") as pg, tempfile.TemporaryDirectory() as tmp:
            if pg is None:
                return
            out, _r, _sv, _fb = _run(pg, "questions", _reply_file(Path(tmp), calls))
            assert out.transport_failed is True, (raiser, out.fill_failed)
            # every row has an answer by the time a pick fails, so the cause may be on no row
            # (review note; the flow then falls back to "timed out"): the notes that exist must be right
            assert _transport_notes(out) <= {want}, (raiser, _transport_notes(out))


# ------------------------------------------------------------------ review M2b (F14, flow half)

@needs(*FILL)
def test_m2b_a_failed_add_ends_the_attempt_validation_error_and_says_an_entry_could_not_be_added():
    """The real outcome of a swallowed Add goes through the real `apply_flow.page_result`: the
    attempt ends `validation_error` and the detail names the missing entry, not just a list of
    field labels (D-173)."""
    with P._open("stubs/review_entries.html") as pg, tempfile.TemporaryDirectory() as tmp:
        if pg is None:
            return
        pg.evaluate(SWALLOW, '[data-automation-id="add-button"]')
        real, _r, _sv, _fb = _run(pg, "my_experience", _reply_file(Path(tmp), ENTRY_REPLY))
    assert real.fill_failed or real.unknown_required, "the page must have stopped"
    w, jid = world()
    try:
        nav = FakeNav()
        with scripted(nav, lambda n, s: dataclasses.replace(real, step="one")):
            r, _f, _s, _m = run(w, jid, nav)
    finally:
        w.close()
    assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR, (r.state, r.reason, r.reason_detail)
    assert "could not be added" in r.reason_detail, r.reason_detail


# ------------------------------------------------------------------ N6a F3

class _Clock:
    """An injected monotonic clock: it moves only when a test moves it."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _SlowModel(FakeModel):
    """warm() takes `seconds` on the injected clock, and does nothing else."""

    def __init__(self, clock: _Clock, seconds: float):
        super().__init__()
        self._clock, self._seconds = clock, seconds

    def warm(self, keep_alive=None):
        super().warm(keep_alive)
        self._clock.t += self._seconds


def test_f3_a_slow_model_warm_up_does_not_eat_the_attempt_deadline():
    """The attempt budget is 420 s (Greenhouse). A warm-up that takes 500 s on the clock (a cold
    load while discovery shares Ollama) is not the attempt's time: the attempt still runs to
    the review with about the whole budget left when the first page is filled."""
    w, jid = world()
    clock, left = _Clock(), []
    real_time = apply_flow.time
    budget = w.cfg.apply.attempt_timeout_s
    try:
        nav = FakeNav()

        def script(n, services):
            left.append(services.deadline_left())
            return two_steps(n, services)
        apply_flow.time = types.SimpleNamespace(monotonic=clock, sleep=real_time.sleep, time=real_time.time)
        with scripted(nav, script):
            r, _f, _s, model = run(w, jid, nav, _SlowModel(clock, 500.0))
    finally:
        apply_flow.time = real_time
        w.close()
    assert model.warmed == 1
    assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
    assert left and left[0] > budget - 60, f"F3: {left[0] if left else None:.0f} s left of {budget} after a 500 s warm-up"


def test_f3_control_the_deadline_still_runs_out_when_the_pages_are_slow():
    """The fix moves the start of the budget; it does not remove it. Time that passes after the
    warm-up still ends the attempt `error` "timed out on <step>"."""
    w, jid = world()
    clock = _Clock()
    real_time = apply_flow.time
    budget = w.cfg.apply.attempt_timeout_s
    try:
        nav = FakeNav()

        def script(n, services):
            clock.t += budget + 5                           # the page itself was slow
            return two_steps(n, services)
        apply_flow.time = types.SimpleNamespace(monotonic=clock, sleep=real_time.sleep, time=real_time.time)
        with scripted(nav, script):
            r, _f, _s, _m = run(w, jid, nav, _SlowModel(clock, 100.0))
    finally:
        apply_flow.time = real_time
        w.close()
    assert r.state is S.FAILED and r.reason is R.ERROR and "timed out" in r.reason_detail, \
        (r.state, r.reason, r.reason_detail)


# ------------------------------------------------------------------ N6a F5

def _transport_stop(note: str):
    """One page whose model call failed with `note`; the deadline is not expired."""
    w, jid = world()
    try:
        nav = FakeNav()

        def script(n, s):
            return outcome("one", [pf("a", "First name")],
                           {"a": ans("a", None, status=AnswerStatus.UNKNOWN, note=note)},
                           transport_failed=True)
        with scripted(nav, script):
            r, _f, _s, _m = run(w, jid, nav)
        return r
    finally:
        w.close()


def test_f5_a_model_that_is_gone_is_not_reported_as_a_timeout():
    r = _transport_stop("transport: model unavailable")
    assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (r.state, r.reason)
    assert "timed out" not in r.reason_detail, f"F5: detail says {r.reason_detail!r} for a missing or refusing model"
    assert "model unavailable" in r.reason_detail and "one" in r.reason_detail, r.reason_detail


def test_f5_a_real_timeout_still_says_timed_out_and_names_the_step():
    r = _transport_stop("transport: timed out")
    assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (r.state, r.reason)
    assert "timed out" in r.reason_detail and "one" in r.reason_detail, r.reason_detail


# ------------------------------------------------------------------ N6a F4

_FIELD = '<div class="field"><label for="n">Full name</label><input id="n" type="text"></div>'
_CV = '<input id="cv" type="file" style="display:none">'
SUBMIT = '<button type="submit">Submit application</button>'
ATTACH = '<button type="button" onclick="document.getElementById(\'cv\').click()">Attach</button>'


def _file_fields(*bodies: str) -> list:
    """The FILE fields `page.read_page` finds on each local page (one Edge, one page per body)."""
    from playwright.sync_api import sync_playwright
    from jobscraper.apply import page as PG
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        try:
            for body in bodies:
                pg = b.new_page()
                pg.set_content(f"<!doctype html><html><body>{body}</body></html>")
                fields = PG.read_page(pg, scope="", sections=[], origin="", step="form")
                out.append([x for x in fields if x.field.type is FieldType.FILE])
                pg.close()
        finally:
            b.close()
    return out


def test_f4_a_hidden_file_input_in_a_form_level_wrapper_with_the_submit_button_is_not_read():
    """The review's own example: the input's parent is the form, which also holds Submit."""
    if not edge_available():
        return
    (got,) = _file_fields(f"<form>{_FIELD}{_CV}{SUBMIT}</form>")
    assert not got, "F4: a hidden file input beside the form's Submit button is exposed as a FILE field"


def test_f4_a_hidden_file_input_beside_only_a_submit_button_in_a_plain_div_is_not_read():
    """The fix text says the sibling button must not itself be a submit. Same markup with the
    parent a plain div (not the form): the input is still no one's upload control."""
    if not edge_available():
        return
    (got,) = _file_fields(f'<form>{_FIELD}<div class="actions">{_CV}<button type="submit">Send it</button></div></form>')
    assert not got, "F4: a hidden file input whose only sibling button is a submit is exposed as a FILE field"


def test_f4_control_a_hidden_file_input_with_its_own_attach_button_or_label_is_still_read():
    """D2 stays: the Greenhouse shape (a field div with a label and an Attach button) and a
    hidden input behind a visible label[for] are both FILE fields."""
    if not edge_available():
        return
    attach, labelled = _file_fields(
        f'<form>{_FIELD}<div class="field"><label>Resume</label>{_CV}{ATTACH}</div>{SUBMIT}</form>',
        f'<form>{_FIELD}<div class="field"><label for="cv">Upload resume</label>{_CV}</div></form>')
    assert attach, "D2: the Attach-button file input is no longer read"
    assert labelled, "D2: the hidden input behind a visible label is no longer read"


# ------------------------------------------------------------------ N6a F6

def _gh_attempt(page: str, model):
    from test_apply_e2e import _gh_profile_with_owner_answers, run_local
    return run_local(dry_run=True, fill="llm", backend=model, profile=_gh_profile_with_owner_answers(), page=page)


def _drop(model, label: str):
    """The scripted model with no answer for the question `label`."""
    for entry in model.replies:
        if entry.get("kind") in ("page", "second", "corrective"):
            entry["reply"] = {k: v for k, v in entry["reply"].items() if label not in k}
    return model


def test_f6_rows_typed_before_a_later_stop_are_not_marked_not_applied():
    """Typing the first name reveals a required question the model cannot answer (step 10 of
    pagefill): the page stops `unanswerable_required` AFTER step 9 typed the other fields.
    Their audit rows must not say "not applied": they are on the employer's page."""
    if not edge_available():
        return
    from test_apply_e2e import _scripted_gh_model
    run_ = _gh_attempt("q80_reveal.html", _scripted_gh_model())
    r = run_.r
    assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
    assert "pet" in r.reason_detail.lower(), r.reason_detail
    rows = run_.answers()
    first = rows["form:first_name"]
    assert "not applied" not in (first["note"] or "").lower(), f"F6: {dict(first)}"
    assert first["status"] == "filled", dict(first)
    assert run_.fx.only_local(), run_.fx.requests


def test_f6_control_a_stop_before_anything_is_typed_still_marks_the_rows_not_applied():
    """Step 7: a required question unknown from the start stops the page with nothing typed.
    Those rows are decided only, so "not applied" stays (R3 F10)."""
    if not edge_available():
        return
    from test_apply_e2e import _scripted_gh_model
    model = _drop(_scripted_gh_model(), "salary expectations")
    run_ = _gh_attempt("form.html", model)
    r = run_.r
    assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
    rows = run_.answers()
    first = rows["form:first_name"]
    assert first["status"] == "skipped" and "not applied" in (first["note"] or "").lower(), dict(first)
