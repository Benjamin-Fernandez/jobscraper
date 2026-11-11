"""WP-T7 (Q-45) flow oracles for composed texts in `apply_flow` (llm_fill_design §19.3, §19.2;
build plan WP-K3 "Done when"): off -> `compose_needed` capture with the page unchanged; on -> text
filled and audited; a failing draft -> capture; `transport` -> `model_unavailable`; no "compose loop".

Written against the spec. `fill_page` is replaced by a script that behaves as §19.2 says (it returns
the field in `PageOutcome.compose_needed` until `ctx.composed` holds a text for it, then a FILLED
answer, source `composed`), and `tailor_flow.compose` / `write_letter` by recording fakes: this file
tests the ORCHESTRATOR only (the compose call itself is test_tailor_compose.py). Harness: the
n6a fakes (fake navigator and browser, temp DB, no Edge, no model).

Gate (K3): `ApplyConfig` has a compose setting, and the YAML shape of design §13.4
(`apply: {compose: {enabled, letter_max_words, answer_max_words, file_format}}`) is what `_world`
writes, so the config field's own name does not matter here. Skip-clean until WP-K3.
Verify: python tests/run_tests.py -k apply_flow_compose
"""
from __future__ import annotations

import contextlib
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING  # noqa: E402

_W0 = len(WAITING)


def _gap() -> str:
    try:
        from jobscraper import config
        names = [f.name for f in dataclasses.fields(config.ApplyConfig)]
    except (ImportError, AttributeError, TypeError):
        return "jobscraper.config:ApplyConfig"
    return "" if any("compose" in n for n in names) else "config.ApplyConfig.compose"


_GAP = _gap()


def needs_k3(fn):
    if _GAP:
        WAITING.append((fn.__name__, _GAP))
        return None
    return fn


TEXT = ("I want to join Fake Co because I enjoy building reliable tools, and my internship taught me "
        "to ship small tested changes.")
WHY = "Why do you want to join us?"


def _imports():
    import test_apply_flow_n6a as N
    from jobscraper import apply_flow, tailor_flow
    from jobscraper.apply.contracts import (AnswerStatus, AnswerTier, AttemptState as S, FieldType,
                                            ReasonCode as R)
    from jobscraper.tailor.contracts import ComposeResult, IssueCode, ValidationIssue
    return N, apply_flow, tailor_flow, AnswerStatus, AnswerTier, S, FieldType, R, ComposeResult, IssueCode, ValidationIssue


@contextlib.contextmanager
def _world(*, enabled=True, file_format="txt"):
    N = _imports()[0]
    w, jid = N.world(apply_block={"compose": {"enabled": enabled, "letter_max_words": 250,
                                              "answer_max_words": 120, "file_format": file_format}})
    try:
        yield w, jid
    finally:
        w.close()


class Compose:
    """Fake `tailor_flow.compose` / `write_letter`: records the calls, returns `results` in turn."""

    def __init__(self, *results):
        self.results, self.calls, self.letters = list(results), [], []

    def compose(self, cfg, req, *, backend, redact, timeout=None):
        self.calls.append(dict(req=req, backend=backend, redact=redact, timeout=timeout))
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

    def write_letter(self, text, path, fmt):
        self.letters.append((text, str(path), fmt))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")      # a stand-in file, so a test can see it exist
        return str(path)


@contextlib.contextmanager
def _patched(fake):
    tf = _imports()[2]
    saved = (tf.compose, tf.write_letter)
    tf.compose, tf.write_letter = fake.compose, fake.write_letter
    try:
        yield
    finally:
        tf.compose, tf.write_letter = saved


@contextlib.contextmanager
def _page(label=WHY, ftype=None, *, stubborn=False, compose_off=False):
    """Script for `fill_page`: one step "one" with a required compose target `q`. Yields a log of the
    ctx.composed / composed_files each call saw. `compose_off` = §19.2's last row (UNKNOWN, note
    `compose_needed: off`, in `unknown_required`); `stubborn` asks for compose even when a text exists."""
    N, apply_flow, _tf, AS, AT, S, FT, R, *_ = _imports()
    ftype = ftype or FT.TEXTAREA
    seen = []

    def fake(page, nav, ctx, rctx, services):
        seen.append((dict(ctx.composed), dict(ctx.composed_files), rctx.job_title))
        f = N.pf("q", label, ftype=ftype)
        if compose_off:
            a = N.ans("q", None, status=AS.UNKNOWN, note="compose_needed: off")
            return N.outcome("one", [f], {"q": a}, unknown_required=("q",))
        if stubborn or not ctx.composed:
            a = N.ans("q", None, status=AS.UNKNOWN, note="compose_needed")
            return N.outcome("one", [f], {"q": a}, compose_needed=("q",))
        text = next(iter(ctx.composed.values()))
        a = dataclasses.replace(N.ans("q", text), tier=AT.LLM, source="composed", rule_id="compose:v1",
                                confidence=0.9)
        return N.outcome("one", [f], {"q": a})
    saved = apply_flow.fill_page
    apply_flow.fill_page = fake
    try:
        yield seen
    finally:
        apply_flow.fill_page = saved


def _run(w, jid, nav=None):
    N = _imports()[0]
    nav = nav or N.FakeNav(steps=("one", "review"))
    return N.run(w, jid, nav) + (nav,)


def _ok(text=TEXT):
    CR = _imports()[8]
    return CR(True, text, (), "fake-model:1b", "h" * 16, 1, "")


def _captured(w):
    return w.store.question_groups("all")


def test_the_compose_flow_oracles_load():
    assert TEXT and WHY


@needs_k3
def test_off_the_target_is_captured_as_compose_needed_and_the_page_is_left_alone():
    N, _af, _tf, AS, AT, S, FT, R, *_ = _imports()
    fake = Compose(_ok())
    with _world(enabled=False) as (w, jid), _patched(fake), _page(compose_off=True) as seen:
        r, _f, say, _m, nav = _run(w, jid)
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail == WHY
        assert fake.calls == [] and len(seen) == 1, "composing is off: no compose call, one page pass"
        assert "next" not in nav.calls, "the page is not advanced"
        groups = _captured(w)
        assert [g["labels"] for g in groups] == [[WHY]]
        assert "reason=compose_needed" in say.text, say.text[-600:]


@needs_k3
def test_on_the_text_is_composed_once_filled_and_audited_whole():
    N, _af, _tf, AS, AT, S, FT, R, *_ = _imports()
    fake = Compose(_ok())
    with _world() as (w, jid), _patched(fake), _page() as seen:
        r, _f, say, _m, nav = _run(w, jid)
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail, say.text[-500:])
        assert len(fake.calls) == 1 and len(seen) >= 2, "compose once, then fill_page again on the same step"
        req = fake.calls[0]["req"]
        assert req.kind == "answer" and WHY in req.question
        assert req.employer == "Fake Co" and req.max_words == 120 and req.max_chars == 1500, req
        assert isinstance(req.s_values, tuple) and req.s_values, "S values go with the request (to be redacted)"
        assert callable(fake.calls[0]["redact"]), "apply_flow passes llm_fill.redact in (stages don't import each other)"
        assert seen[0][0] == {} and list(seen[1][0].values()) == [TEXT], "the second pass sees ctx.composed"
        rows = {x["field_key"]: x for x in w.store.answers(r.attempt_id)}
        row = next(v for k, v in rows.items() if k.startswith("one:"))
        assert row["source"] == "composed" and row["status"] == "filled" and TEXT in str(row["value_json"]), row
        assert "composed 1 text" in say.text and TEXT[:30] not in say.text, "the log line carries no text"


@needs_k3
def test_a_cover_letter_file_target_gets_a_letter_file_under_the_attempt_folder():
    N, _af, _tf, AS, AT, S, FT, R, *_ = _imports()
    fake = Compose(_ok())
    with _world(file_format="docx") as (w, jid), _patched(fake), _page("Cover Letter", FT.FILE) as seen:
        r, *_ = _run(w, jid)
        req = fake.calls[0]["req"]
        assert req.kind == "letter" and req.max_words == 250 and req.max_chars == 4000, req
        assert len(fake.letters) == 1
        text, path, fmt = fake.letters[0]
        assert text == TEXT and fmt == "docx"
        p = Path(path)
        assert p.name == "cover_letter.docx" and str(r.attempt_id) in p.parts, path
        # LF section 19.3: the letter sits directly in the attempt folder, <evidence root>/<attempt id>/
        assert p.parent == w.tmp / "evidence" / str(r.attempt_id), (path, w.tmp / "evidence", r.attempt_id)
        assert p.is_file() and p.name.startswith("cover_letter") and p.suffix in (".docx", ".txt"), path
        assert list(seen[-1][1].values()) == [path], "ctx.composed_files has the path for the upload"


@needs_k3
def test_a_draft_that_fails_its_checks_is_captured_and_ends_unanswerable_required():
    N, _af, _tf, AS, AT, S, FT, R, CR, IC, VI = _imports()
    fake = Compose(CR(False, "", (VI(IC.FACT_ADDED, None, "kafka"),), "m", "h", 2, ""))
    with _world() as (w, jid), _patched(fake), _page() as seen:
        r, _f, say, _m, nav = _run(w, jid)
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED and r.reason_detail == WHY, \
            (r.state, r.reason, r.reason_detail)
        assert len(fake.calls) == 1 and len(seen) == 1, "no second pass after a failed draft"
        assert "reason=compose_needed" in say.text and "failed check" in say.text, say.text[-600:]
        assert [g["labels"] for g in _captured(w)] == [[WHY]]
        assert "next" not in nav.calls


@needs_k3
def test_no_master_is_captured_with_its_own_note():
    N, _af, _tf, AS, AT, S, FT, R, CR, *_ = _imports()
    fake = Compose(CR(False, error="no master"))
    with _world() as (w, jid), _patched(fake), _page():
        r, _f, say, _m, _nav = _run(w, jid)
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, (r.state, r.reason)
        assert "reason=compose_needed" in say.text and "no master" in say.text, say.text[-600:]
        assert [g["labels"] for g in _captured(w)] == [[WHY]]


@needs_k3
def test_a_transport_error_is_model_unavailable_and_captures_nothing():
    N, _af, _tf, AS, AT, S, FT, R, CR, *_ = _imports()
    fake = Compose(CR(False, error="transport: BackendError"))
    with _world() as (w, jid), _patched(fake), _page():
        r, _f, say, _m, nav = _run(w, jid)
        assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (r.state, r.reason, r.reason_detail)
        assert _captured(w) == [], "a transport failure is not a question for the owner"
        assert "next" not in nav.calls


@needs_k3
def test_a_page_that_asks_for_the_same_text_again_ends_as_a_compose_loop_and_sends_nothing():
    N, _af, _tf, AS, AT, S, FT, R, *_ = _imports()
    fake = Compose(_ok())
    with _world() as (w, jid), _patched(fake), _page(stubborn=True) as seen:
        r, _f, say, _m, nav = _run(w, jid)
        assert r.state is S.FAILED and r.reason is R.ERROR, (r.state, r.reason, r.reason_detail)
        assert "compose loop" in r.reason_detail, r.reason_detail
        assert len(fake.calls) == 1 and len(seen) == 2, (len(fake.calls), len(seen))
        assert "next" not in nav.calls


# ---- D-184: the compose model call is capped by the attempt's time left

@contextlib.contextmanager
def _deadline_left(seconds):
    """The attempt deadline reads `seconds` left (patched on the fill services)."""
    apply_flow = _imports()[1]
    saved = apply_flow._FillServices.deadline_left
    apply_flow._FillServices.deadline_left = lambda self: float(seconds)
    try:
        yield
    finally:
        apply_flow._FillServices.deadline_left = saved


@needs_k3
def test_d184_compose_is_called_with_the_attempt_time_left_as_its_timeout():
    fake = Compose(_ok())
    with _world() as (w, jid), _patched(fake), _page(), _deadline_left(7):
        _run(w, jid)
    assert len(fake.calls) == 1, "compose ran once"
    t = fake.calls[0]["timeout"]
    assert t is not None and 1 <= t <= 7, t


@contextlib.contextmanager
def _real_master(w):
    """The real `tailor_flow.compose` needs a cached master: the case_a master, resume file stubbed."""
    import test_tailor_compose as TC
    from jobscraper.profile import resume_ingest
    from jobscraper.tailor import master as master_mod
    saved = (resume_ingest.find_resume, resume_ingest.extract_text, resume_ingest.file_hash)
    m = master_mod.from_dict(TC._master_dict())
    master_mod.save(w.cfg.master_resume_path, m)
    text = chr(10).join(master_mod._leaves(m))
    resume_ingest.find_resume = lambda d: Path(d) / "resume.pdf"
    resume_ingest.extract_text = lambda p: text
    resume_ingest.file_hash = lambda p: "sha256:t7"
    try:
        yield
    finally:
        resume_ingest.find_resume, resume_ingest.extract_text, resume_ingest.file_hash = saved


class TimedModel:
    """A backend that records the `timeout` each `complete` got and then returns or raises."""
    name = "fakemodel"
    model_id = "fake-model:1b"
    available = True

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.timeouts = reply, error, []

    def warm(self, keep_alive=None):
        pass

    def complete(self, system, user, max_tokens=4096, schema=None, timeout=None, *, format=None,
                 temperature=None, seed=None, top_k=None, keep_alive=None):
        import json
        from jobscraper.backends import Completion
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return Completion(json.dumps({"text": self.reply}), 10, 10)


@needs_k3
def test_d184_the_real_compose_hands_the_backend_a_timeout_of_at_most_the_time_left():
    N = _imports()[0]
    model = TimedModel(reply=TEXT)
    with _world() as (w, jid), _real_master(w), _page(), _deadline_left(7):
        N.run(w, jid, N.FakeNav(steps=("one", "review")), model=model)
    assert model.timeouts, "the compose model call happened"
    assert all(t is not None and 1 <= t <= 7 for t in model.timeouts), model.timeouts


@needs_k3
def test_d184_a_timeout_or_transport_error_ends_model_unavailable_and_captures_nothing():
    from jobscraper.backends import BackendError
    N, _af, _tf, AS, AT, S, FT, R, *_ = _imports()
    for err in (BackendError("timed out after 7s"), TimeoutError("timed out"), BackendError("connection refused")):
        model = TimedModel(error=err)
        with _world() as (w, jid), _real_master(w), _page(), _deadline_left(7):
            r, *_rest = N.run(w, jid, N.FakeNav(steps=("one", "review")), model=model)
            assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (err, r.state, r.reason, r.reason_detail)
            assert _captured(w) == [], "a transport failure captures nothing"
            assert model.timeouts and all(t is not None and 1 <= t <= 7 for t in model.timeouts), model.timeouts


if WAITING[_W0:]:
    print(f"[test_apply_flow_compose] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
