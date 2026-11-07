"""Unit tests of the LLM filling loop in apply_flow (Q-35 WP-N6a; llm_fill_design §8, §11, §13.1).

Written by the engineer as a draft, reviewed against the spec and adopted by the tester. `fill_page`
is replaced by a script, the ATS by a fake navigator and browser: no Edge, no model, temp DB.
Verify: python tests/run_tests.py -k apply_flow_n6a
"""
from __future__ import annotations

import contextlib
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import (  # noqa: E402
    FakeBrowserFactory, Say, add_job, make_world, page_signals, registered,
)

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerStatus, AnswerTier, AttemptState as S, FieldType, FormField, PageField,
    PageOutcome, PasswordRules, ReasonCode as R, StepResult, Tenant, ValueOrigin,
)
from jobscraper.backends import BackendError  # noqa: E402


class FakeModel:
    name = "fakemodel"
    model_id = "fake-model:1b"
    available = True

    def __init__(self, warm_error: str = ""):
        self.warm_error, self.warmed, self.keep_alive = warm_error, 0, "unset"

    def warm(self, keep_alive=None):
        self.warmed += 1
        self.keep_alive = keep_alive
        if self.warm_error:
            raise BackendError(self.warm_error)

    def complete(self, *a, **k):
        raise BackendError("not used")


class FakeNav:
    name = "fakenav"
    needs_account = False
    password_rules = PasswordRules()
    mail_domains: tuple = ()
    otp_pattern = ""

    def __init__(self, steps=("one", "two", "review")):
        self.steps, self.at = list(steps), 0
        self.errors = []
        self.calls = []
        self.origin = ValueOrigin.RESUME_IMPORT.value
        self.stay = False

    def match_url(self, url):
        return None

    def tenant_from_company(self, job):
        return Tenant("fakenav", "fake.example.com", "co", posting_id="1")

    def precheck(self, ctx):
        self.calls.append("precheck")

    def open(self, page, ctx):
        self.calls.append("open")

    def choose_entry(self, page, ctx):
        self.calls.append("choose_entry")
        return self.origin

    def account_wall(self, page):
        return None

    def step_id(self, page, ctx):
        return self.steps[self.at]

    def scope(self, page, ctx):
        return ""

    def entry_sections(self, page, ctx):
        return []

    def next_step(self, page, ctx):
        self.calls.append("next")
        if self.errors:
            return StepResult(step=self.steps[self.at], errors=self.errors.pop(0))
        if not self.stay and self.at < len(self.steps) - 1:
            self.at += 1
        return StepResult(step=self.steps[self.at], is_review=self.steps[self.at] == "review")

    def submit_ready(self, page):
        return True

    def submit(self, page, ctx):
        raise AssertionError("a dry run never submits")

    def after_submit(self, page, ctx):
        return None

    def visible_errors(self, page):
        return ()

    def enter_code(self, page, ctx, code):
        raise AssertionError("no code")

    def sign_in(self, page, ctx, password):
        raise AssertionError("no account")

    sign_up = sign_in


def pf(key, label, *, required=True, group="", ftype=FieldType.TEXT) -> PageField:
    return PageField(FormField(key, label, ftype, required, step="x"), widget="text", group=group)


def ans(key, value="v", *, status=AnswerStatus.FILLED, note="") -> Answer:
    return Answer(key, value if status is AnswerStatus.FILLED else None, AnswerTier.LLM,
                  "llm" if status is AnswerStatus.FILLED else "", 0.9, status, note=note)


def outcome(step, fields, answers=None, **kw) -> PageOutcome:
    answers = answers if answers is not None else {f.field.key: ans(f.field.key) for f in fields}
    return PageOutcome(step=step, fields=list(fields), answers=answers, **kw)


@contextlib.contextmanager
def scripted(nav, script):
    seen = []

    def fake(page, nav_, ctx, rctx, services):
        seen.append((nav_.step_id(page, ctx), services))
        return script(nav_, services)
    saved = apply_flow.fill_page
    apply_flow.fill_page = fake
    try:
        yield seen
    finally:
        apply_flow.fill_page = saved


def world(**kw):
    w = make_world(**kw)
    add_job(w.store, key="fakeco", name="Fake Co", provider="fakenav", slug="fakeco",
            external_id="1", url="https://fake.example.com/jobs/1")
    jid = w.store.conn.execute("SELECT job_id FROM jobs").fetchone()[0]
    return w, jid


def run(w, jid, nav, model=None, *, dry_run=True, apply_over=None):
    factory, say = FakeBrowserFactory(), Say()
    acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0, **(apply_over or {}))
    model = model or FakeModel()
    with registered(nav), page_signals():
        res = apply_flow.run(w.cfg, w.store, [jid], dry_run=dry_run, backend=model, http=object(),
                             browser_factory=factory, apply_cfg=acfg, say=say,
                             evidence_dir=w.tmp / "evidence", now=lambda: 1_700_000_000.0)
    return res[0], factory, say, model


def two_steps(nav, services):
    if nav.step_id(None, None) == "one":
        return outcome("one", [pf("a", "First name"), pf("b", "Last name")])
    return outcome("two", [pf("c", "Nationality")])


def reset(w):
    w.store.conn.execute("DELETE FROM apply_attempts")
    w.store.commit()


def test_a_dry_run_walks_the_steps_and_ends_ready_to_submit_with_one_audit_row_per_field():
    w, jid = world()
    try:
        nav = FakeNav()
        with scripted(nav, two_steps) as seen:
            r, factory, say, model = run(w, jid, nav)
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
        assert model.warmed == 1 and model.keep_alive is None, model.keep_alive
        assert nav.calls[:3] == ["precheck", "open", "choose_entry"], nav.calls
        assert [s for s, _ in seen] == ["one", "two"]
        rows = w.store.answers(r.attempt_id)
        assert sorted((x["step"], x["field_key"]) for x in rows) == \
            [("one", "one:first_name"), ("one", "one:last_name"), ("two", "two:nationality")]
        assert all(x["status"] == "filled" and x["source"] == "llm" for x in rows)
        assert all("shown_origin" in x and "evidence" in x for x in rows)
        assert "prefill: resume_import" in say.text
        svc = seen[0][1]
        assert svc.model == "fake-model:1b" and svc.today() == "2023-11-15"
        assert svc.cfg["page_timeout_s"] == 120 and svc.deadline_left() > 0
    finally:
        w.close()


def test_a_failed_warm_up_is_model_unavailable_and_the_browser_never_starts():
    w, jid = world()
    try:
        nav = FakeNav()
        with scripted(nav, two_steps) as seen:
            r, factory, say, _ = run(w, jid, nav, FakeModel(warm_error="Ollama is not running"))
        assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE, (r.state, r.reason)
        assert "not running" in r.reason_detail
        assert factory.started == 0 and seen == [] and "open" not in nav.calls
        row = w.store.attempt(r.attempt_id)
        assert row["step"] == "planning" and row["submit_clicked_at"] is None
    finally:
        w.close()


def test_a_transport_failure_is_model_unavailable_naming_the_step_and_captures_nothing():
    w, jid = world()
    try:
        nav = FakeNav()

        def script(n, s):
            return outcome("one", [pf("a", "First name")],
                           {"a": ans("a", None, status=AnswerStatus.UNKNOWN, note="transport: model unavailable")},
                           transport_failed=True)
        with scripted(nav, script):
            r, _f, _s, _m = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.MODEL_UNAVAILABLE and r.reason_detail == "timed out on one"
        assert w.store.question_groups("all") == []
        assert "next" not in nav.calls
    finally:
        w.close()


def test_an_expired_deadline_is_error_timed_out_never_model_unavailable():
    w, jid = world()
    try:
        nav = FakeNav()

        def script(n, services):
            services.ctx.deadline = apply_flow.time.monotonic() - 1
            return outcome("one", [pf("a", "First name")],
                           {"a": ans("a", None, status=AnswerStatus.UNKNOWN, note="transport: timed out")},
                           transport_failed=True)
        with scripted(nav, script):
            r, _f, _s, _m = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.ERROR and r.reason_detail == "timed out on one", \
            (r.reason, r.reason_detail)
    finally:
        w.close()


def test_a_required_unknown_is_captured_once_stops_the_attempt_and_marks_the_rows_not_applied():
    w, jid = world()
    try:
        nav = FakeNav()

        def script(n, s):
            fields = [pf("a", "First name"), pf("q", "Describe your ideal weekend.", ftype=FieldType.TEXTAREA)]
            return outcome("one", fields, {"a": ans("a", "Alex"),
                                           "q": ans("q", None, status=AnswerStatus.UNKNOWN, note="model: unknown")},
                           unknown_required=("q",))
        with scripted(nav, script):
            r, _f, say, _m = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED
        assert r.reason_detail == "Describe your ideal weekend."
        assert "next" not in nav.calls
        groups = w.store.question_groups()
        assert [g["labels"] for g in groups] == [["Describe your ideal weekend."]]
        assert "question captured key=describe_ideal_weekend kind=text reason=no_rule" in say.text
        rows = {x["field_key"]: x for x in w.store.answers(r.attempt_id)}
        assert rows["one:first_name"]["status"] == "skipped" and rows["one:first_name"]["value_json"] is None
        assert "not applied" in rows["one:first_name"]["note"]
        assert rows["one:describe_your_ideal_weekend"]["status"] == "unknown"
    finally:
        w.close()


def test_a_required_field_the_page_would_not_take_is_a_validation_error():
    w, jid = world()
    try:
        nav = FakeNav()

        def script(n, s):
            return outcome("one", [pf("a", "First name"), pf("b", "Nickname", required=False)],
                           fill_failed=("a",))
        with scripted(nav, script):
            r, *_ = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR and r.reason_detail == "First name"

        reset(w)
        nav = FakeNav()
        with scripted(nav, lambda n, s: outcome(n.step_id(None, None), [pf("b", "Nickname", required=False)],
                                                 fill_failed=("b",))):
            r, *_ = run(w, jid, nav)
        assert r.state is S.READY_TO_SUBMIT, "an optional field that would not take its value is no stop"
    finally:
        w.close()


def test_page_errors_after_next_get_one_more_pass_then_a_validation_error():
    w, jid = world()
    try:
        nav = FakeNav()
        nav.errors = [("First name is required",), ("First name is required",)]
        with scripted(nav, two_steps) as seen:
            r, _f, say, _m = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR
        assert "First name is required" in r.reason_detail
        assert [s for s, _ in seen] == ["one", "one"]
        assert nav.calls.count("next") == 2

        reset(w)
        nav = FakeNav()
        nav.errors = [("First name is required",)]
        with scripted(nav, two_steps) as seen:
            r, *_ = run(w, jid, nav)
        assert r.state is S.READY_TO_SUBMIT and [s for s, _ in seen] == ["one", "one", "two"]
    finally:
        w.close()


def test_the_same_step_with_the_same_fields_twice_is_page_unrecognised():
    w, jid = world()
    try:
        nav = FakeNav()
        nav.stay = True
        with scripted(nav, two_steps):
            r, *_ = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED and "shown again" in r.reason_detail
    finally:
        w.close()


def test_no_fields_on_a_non_review_step_is_page_unrecognised():
    w, jid = world()
    try:
        nav = FakeNav()
        with scripted(nav, lambda n, s: outcome("one", [])):
            r, *_ = run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED and r.reason_detail == "no fields on one"
    finally:
        w.close()


def test_too_many_steps_ends_page_unrecognised():
    w, jid = world()
    try:
        nav = FakeNav(steps=tuple(f"s{i}" for i in range(6)) + ("review",))

        def script(n, s):
            sid = n.step_id(None, None)
            return outcome(sid, [pf(sid, "Q " + sid)])
        with scripted(nav, script):
            r, *_ = run(w, jid, nav, apply_over={"max_wizard_steps": 3})
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED and "too many steps" in r.reason_detail
    finally:
        w.close()


def test_apply_fill_rules_keeps_the_old_path_a_navigator_only_ats_is_unsupported():
    w, jid = world()
    try:
        nav = FakeNav()
        with scripted(nav, two_steps) as seen:
            r, factory, _s, model = run(w, jid, nav, apply_over={"fill": "rules"})
        assert r.state is S.FAILED and r.reason is R.UNSUPPORTED_ATS
        assert factory.started == 0 and seen == [] and model.warmed == 0
    finally:
        w.close()


def test_the_pre_d78_path_captures_its_required_unknowns_and_never_warms_the_model():
    from apply_flow_support import FakeAdapter, unknown_required
    w = make_world()
    try:
        add_job(w.store, key="fakeco", name="Fake Co", provider="fakeats", slug="fakeco",
                external_id="1", url="https://fake.example.com/jobs/1")
        jid = w.store.conn.execute("SELECT job_id FROM jobs").fetchone()[0]
        r, factory, say, model = run(w, jid, FakeAdapter([unknown_required()]))
        assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED
        assert model.warmed == 0 and factory.started == 0
        assert [g["labels"] for g in w.store.question_groups()] == [["What was the name of your first pet?"]]
    finally:
        w.close()


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    sys.exit(1 if failed else 0)