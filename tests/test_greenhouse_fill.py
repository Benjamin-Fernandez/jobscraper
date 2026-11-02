"""The Greenhouse adapter against the local fixture form, in headless Edge (WP-B6, WP-B12; Verify
`-k greenhouse_fill` / `-k greenhouse`). Queue Q-31.

The adapter is driven directly (no orchestrator): open, plan, resolve, fill, read back, Next, Submit,
the after-submit signals, validation errors, and the MyGreenhouse prefill on both fixture pages
(signed in / signed out) plus the §9.1.2 link-label rule. A local http.server stands in for the
board and API. Browser tests skip cleanly (one note) if Edge or Playwright is unavailable.
"""
from __future__ import annotations

import atexit
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import (  # noqa: E402
    EMAIL, FixtureServer, GH, INPUT_RECORDER_JS, NoModel, Say, edge_acfg, edge_available,
    local_http, make_world,
)

from jobscraper.apply import resolve as R  # noqa: E402
from jobscraper.apply.ats import REGISTRY  # noqa: E402
from jobscraper.apply.ats.greenhouse import link_canonical  # noqa: E402
from jobscraper.apply.browser import BrowserSession  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerTier, ApplyFailure, AttemptContext, Canonical, FieldType, ReasonCode, ResolveContext,
    StepResult, Tenant,
)
from jobscraper.config import ApplyConfig  # noqa: E402

POSTING = "6237419004"
HOWHEARD = "where did you see or hear about this job"
ADAPTER = REGISTRY["greenhouse"]
_SESSION: dict = {}


# ------------------------------------------------------------------ browser helpers

def _session() -> BrowserSession:
    """One headless Edge (temp profile) for the module, closed at exit."""
    if "s" not in _SESSION:
        w = make_world()
        acfg = edge_acfg(ApplyConfig(), str(w.tmp / "edge-profile"))
        _SESSION["s"] = BrowserSession(acfg).start()
        _SESSION["w"] = w
        atexit.register(_SESSION["s"].close)
    return _SESSION["s"]


def _page():
    page = _session().new_page()
    page.add_init_script("(" + INPUT_RECORDER_JS + ")()")
    return page


def _world():
    _session()
    return _SESSION["w"]


_ATTEMPT = [1000]


def _ctx(base_url: str, *, board="dataiku", posting=POSTING, log=None):
    _ATTEMPT[0] += 1
    w = _world()
    return AttemptContext(
        attempt_id=_ATTEMPT[0],
        job={"job_id": "j-gh", "provider": "greenhouse", "slug": board, "external_id": posting,
             "url": f"https://job-boards.greenhouse.io/{board}/jobs/{posting}"},
        tenant=Tenant("greenhouse", "job-boards.greenhouse.io", board, posting_id=posting),
        dry_run=True, email=EMAIL, resume_path=str(w.resume), log=log or Say(),
        screenshot=lambda p, s: "", deadline=1e18, http=local_http())


def _answers(plan, ctx):
    """The real resolver over the synthetic profile; the how-heard question comes from memory."""
    w = _world()
    rctx = ResolveContext(profile=w.profile, employer_name="Dataiku", resume_text="",
                          resume_path=ctx.resume_path, ats="greenhouse")
    rules = R.load_rules(w.cfg.questions_path)
    mem = lambda ln, ft, ats: json.dumps("LinkedIn") if ln == HOWHEARD else None      # noqa: E731
    return R.resolve_all(plan.fields, rctx, backend=NoModel(), rules=rules, memory=mem)


def _opened(fx, page_name="form.html", query=""):
    fx.set_posting(POSTING, page_name, query)
    ctx = _ctx(fx.base)
    page = _page()
    plan = ADAPTER.plan_from_schema(ctx)
    ADAPTER.open(page, ctx)
    return ctx, page, plan


def _filled(fx, page_name="form.html", query=""):
    ctx, page, plan = _opened(fx, page_name, query)
    step, fields = ADAPTER.read_step(page, ctx)
    answers = _answers(plan, ctx)
    failed = ADAPTER.fill(page, ctx, fields, answers)
    return ctx, page, plan, fields, answers, failed


def _done(ctx, page):
    ADAPTER.forget(ctx)
    page.close()


# ================================================================== open, fill, read back

def test_the_adapter_fills_every_planned_field_and_reads_each_one_back():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan, fields, answers, failed = _filled(fx)
        try:
            assert failed == [], f"fields that did not take their value: {failed}"
            assert {f.key for f in fields} == {f.key for f in plan.fields}, "every planned field is on the page"
            vals = ADAPTER.read_values(page, ctx, fields)
            assert vals["first_name"] == "Alex" and vals["last_name"] == "Testcase"
            assert vals["email"] == EMAIL and vals["phone"] == "91234567"
            assert vals["resume"] == "resume.pdf"
            assert vals["candidate-location"] == "Singapore, Singapore"
            assert vals["question_20424893004"] == "No" and vals["question_20424897004"] == "LinkedIn"
            assert vals["gdpr_processing_consent_given"] == "true"
            assert vals["gdpr_retention_consent_given"] == "true"
            assert vals["question_20424899004"].startswith("https://www.linkedin.com/in/")
            for f in fields:
                a = answers[f.key]
                if a.fills and f.type is not FieldType.HIDDEN:
                    assert vals[f.key] not in ("", [], "false"), f"{f.key} was not read back"
                else:
                    assert vals[f.key] in ("", "false", []), f"{f.key} should still be empty: {vals[f.key]!r}"
            nxt = ADAPTER.next_step(page, ctx)
            assert nxt == StepResult(step="application", is_review=True, errors=())
            assert ADAPTER.visible_errors(page) == ()
            assert ADAPTER.submit_ready(page) is True
            assert ADAPTER.after_submit(page, ctx) is None, "nothing is confirmed before Submit"
        finally:
            _done(ctx, page)
        assert fx.only_local()


def test_the_phone_country_is_filled_before_the_phone():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan = _opened(fx)
        order, real = [], ADAPTER._fill_one
        try:
            ADAPTER._fill_one = lambda p, f, a: (order.append(f.key), real(p, f, a))[1]
            fields = [f for f in plan.fields if f.key in ("phone", "country")]
            ans = {"phone": Answer("phone", "91234567", AnswerTier.FIELD_MAP, "field_map:phone", 0.99),
                   "country": Answer("country", "Singapore +65", AnswerTier.FIELD_MAP,
                                     "field_map:phone_country_code", 0.9)}
            failed = ADAPTER.fill(page, ctx, fields, ans)
            vals = ADAPTER.read_values(page, ctx, fields)
        finally:
            del ADAPTER._fill_one
            _done(ctx, page)
        assert order == ["country", "phone"], order
        assert failed == [] and vals["country"] == "Singapore +65" and vals["phone"] == "91234567"


def test_read_values_on_an_empty_form_say_empty_in_each_types_own_way():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan = _opened(fx)
        try:
            fields = [f for f in plan.fields if f.type is not FieldType.HIDDEN]
            vals = ADAPTER.read_values(page, ctx, fields)
        finally:
            _done(ctx, page)
        by = {f.key: f for f in fields}
        for k, v in vals.items():
            t = by[k].type
            if t is FieldType.CHECKBOX:
                assert v == "false", k
            elif t is FieldType.MULTI_CHOICE:
                assert v == [], k
            else:
                assert v == "", (k, v)


def test_open_on_a_page_without_the_form_marker_is_page_unrecognised():
    if not edge_available():
        return
    with FixtureServer() as fx:
        fx.set_posting(POSTING, "confirm.html")          # a page with no #first_name and no stop sign
        ctx = _ctx(fx.base)
        page = _page()
        try:
            ADAPTER.open(page, ctx)
        except ApplyFailure as exc:
            assert exc.reason is ReasonCode.PAGE_UNRECOGNISED and exc.detail == "greenhouse: application"
        else:
            raise AssertionError("open() must raise page_unrecognised when #first_name never appears")
        finally:
            _done(ctx, page)


def test_open_names_the_stop_sign_when_the_page_is_one():
    if not edge_available():
        return
    for name, reason in (("closed.html", ReasonCode.POSTING_CLOSED), ("bot_check.html", ReasonCode.BOT_CHALLENGE),
                         ("form_challenge.html", None)):
        with FixtureServer() as fx:
            fx.set_posting(POSTING, name)
            ctx = _ctx(fx.base)
            page = _page()
            try:
                ADAPTER.open(page, ctx)
                assert reason is None, f"{name}: the form marker is on the challenge page, open() returns"
            except ApplyFailure as exc:
                assert exc.reason is reason, (name, exc.reason)
            finally:
                _done(ctx, page)


# ================================================================== submit, confirmation, errors

def test_submit_then_after_submit_confirms_by_text_and_counts_one_click():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan, fields, answers, failed = _filled(fx)
        try:
            ADAPTER.submit(page, ctx)
            got = None
            for _ in range(20):
                got = ADAPTER.after_submit(page, ctx)
                if got:
                    break
                page.wait_for_timeout(200)
            assert got == "confirmed:text", got
            assert page.evaluate("document.body.dataset.submitCount") == "1"
        finally:
            _done(ctx, page)


def test_after_submit_on_the_navigated_thank_you_page_is_confirmed_by_text():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan, fields, answers, failed = _filled(fx, query="after=navigate")
        try:
            ADAPTER.submit(page, ctx)
            page.wait_for_url("**/confirm.html", timeout=8000)
            assert ADAPTER.after_submit(page, ctx) == "confirmed:text"
        finally:
            _done(ctx, page)


def test_a_security_code_prompt_is_code_required_and_enter_code_types_into_its_box():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan, fields, answers, failed = _filled(fx, query="after=code")
        try:
            ADAPTER.submit(page, ctx)
            got = None
            for _ in range(20):
                got = ADAPTER.after_submit(page, ctx)
                if got:
                    break
                page.wait_for_timeout(200)
            assert got == "code_required", got
            ADAPTER.enter_code(page, ctx, "AB12CD34")
            assert page.locator("#security-code-block input").first.input_value() == "AB12CD34"
            assert page.evaluate("document.body.dataset.submitCount") == "0", "no submission yet"
        finally:
            _done(ctx, page)


def test_a_server_side_error_after_submit_is_errors_naming_the_field_by_its_label():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan, fields, answers, failed = _filled(fx, query="after=errors")
        try:
            ADAPTER.submit(page, ctx)
            got = None
            for _ in range(20):
                got = ADAPTER.after_submit(page, ctx)
                if got:
                    break
                page.wait_for_timeout(200)
            assert got == "errors", got
            errs = ADAPTER.visible_errors(page)
            assert any(e.startswith("Email") for e in errs), errs
            assert EMAIL not in " ".join(errs), "errors name labels, never the typed value"
        finally:
            _done(ctx, page)


def test_submitting_an_empty_form_lists_the_required_fields_as_validation_errors():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan = _opened(fx)
        try:
            ADAPTER.submit(page, ctx)
            page.wait_for_timeout(300)
            errs = ADAPTER.visible_errors(page)
            joined = " | ".join(errs)
            assert errs and "First Name" in joined, errs
            nxt = ADAPTER.next_step(page, ctx)
            assert nxt.is_review and nxt.errors == errs, "the flow reads the same errors after Next"
            assert ADAPTER.after_submit(page, ctx) == "errors"
            assert page.evaluate("document.body.dataset.submitCount") == "0"
        finally:
            _done(ctx, page)


def test_without_a_submit_button_submit_raises_and_submit_ready_is_false():
    if not edge_available():
        return
    with FixtureServer() as fx:
        fx.set_posting(POSTING, "confirm.html")
        ctx = _ctx(fx.base)
        page = _page()
        try:
            page.goto(fx.base + f"/dataiku/jobs/{POSTING}")
            assert ADAPTER.submit_ready(page) is False
            try:
                ADAPTER.submit(page, ctx)
            except ApplyFailure as exc:
                assert exc.reason is ReasonCode.PAGE_UNRECOGNISED and exc.detail == "greenhouse: submit button"
            else:
                raise AssertionError("submit() must raise when there is no Submit button")
        finally:
            _done(ctx, page)


# ================================================================== MyGreenhouse (D-70 9.1.1)

def _recorded_inputs(page):
    return page.evaluate("window.__inputs || []")


def test_mygreenhouse_signed_in_prefill_returns_mygreenhouse_and_the_fields_fill_in():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan = _opened(fx, "form_mygreenhouse_signed_in.html")
        try:
            fields = [f for f in plan.fields if f.type is not FieldType.HIDDEN]
            before = ADAPTER.read_values(page, ctx, fields)
            assert before["first_name"] == "" and before["email"] == ""
            got = ADAPTER.prefill(page, ctx)
            assert got == "mygreenhouse"
            after = ADAPTER.read_values(page, ctx, fields)
            assert after["first_name"] == "Alex" and after["last_name"] == "Testcase"
            assert after["email"] == "saved.mygh@example.org" and after["phone"] == "81234567"
            assert after["question_20424899004"] == "https://www.linkedin.com/in/alex-saved"
            assert "mygh_email" not in _recorded_inputs(page), "no sign-in email was typed"
            assert "mygreenhouse: autofilled" in ctx.log.text
        finally:
            _done(ctx, page)


def test_mygreenhouse_signed_out_prefill_is_empty_closes_the_dialog_and_types_nothing():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan = _opened(fx, "form_mygreenhouse_signed_out.html")
        try:
            fields = [f for f in plan.fields if f.type is not FieldType.HIDDEN]
            before = ADAPTER.read_values(page, ctx, fields)
            assert ADAPTER.prefill(page, ctx) == ""
            assert page.locator("#mygh_dialog").count() == 0, "the sign-in dialog is closed"
            assert "mygh_email" not in _recorded_inputs(page), "nothing typed into the sign-in"
            assert ADAPTER.read_values(page, ctx, fields) == before, "the form is as it was"
            assert "mygreenhouse: not signed in" in ctx.log.text
        finally:
            _done(ctx, page)


def test_prefill_without_an_autofill_button_returns_empty_and_says_why():
    if not edge_available():
        return
    with FixtureServer() as fx:
        ctx, page, plan = _opened(fx)
        try:
            assert ADAPTER.prefill(page, ctx) == ""
            assert "mygreenhouse: no button" in ctx.log.text
        finally:
            _done(ctx, page)


# ================================================================== §9.1.2 link labels (WP-B12)

def test_link_labels_are_tagged_by_phrase_only_when_exactly_one_site_matches():
    assert link_canonical("LinkedIn URL") is Canonical.LINKEDIN
    assert link_canonical("Github URL") is Canonical.GITHUB
    assert link_canonical("Portfolio link") is Canonical.WEBSITE
    assert link_canonical("Personal site") is Canonical.WEBSITE
    assert link_canonical("Your website") is Canonical.WEBSITE
    assert link_canonical("Twitter URL") is None
    assert link_canonical("Other URL") is None
    assert link_canonical("LinkedIn or GitHub") is None, "two canonicals: none"
    assert link_canonical("Please share your LinkedIn profile or another link to your work") is None, \
        "a one-token phrase matches only labels of 4 tokens or fewer (7.1)"


def test_the_dataiku_plan_tags_its_linkedin_and_github_questions():
    class H:
        def get_json(self, url, **kw):
            return json.loads((GH / "gh_dataiku.json").read_text(encoding="utf-8"))
    ctx = AttemptContext(
        attempt_id=1, job={"job_id": "j"}, tenant=Tenant("greenhouse", "h", "dataiku", posting_id=POSTING),
        dry_run=True, email=EMAIL, resume_path="C:/x/r.pdf", log=lambda l: None,
        screenshot=lambda p, s: "", deadline=1e18, http=H())
    plan = ADAPTER.plan_from_schema(ctx)
    by = plan.by_key()
    ADAPTER.forget(ctx)
    assert by["question_20424899004"].canonical is Canonical.LINKEDIN
    assert by["question_20424901004"].canonical is Canonical.GITHUB
    assert by["question_20424900004"].canonical is None, "Twitter URL"
    assert by["question_20424902004"].canonical is None, "Other URL"
    assert by["question_20424898004"].canonical is None, "Current Company is not a link"
