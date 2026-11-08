"""WP-Q0 oracles for capture inside the orchestrator (questions_design.md 4.1, 5.3, 11; WP-Q1b): an attempt
that stops `failed(unanswerable_required)` records every required question nobody could answer, and a retry
after the owner's answer is answered by tier 3.

Skip-clean until lane B's `apply_flow.run` and lane Q's capture exist. The harness is a FAKE adapter, a fake
browser and a scripted model injected through `apply_flow.run(..., browser_factory=, backend=, http=)` and by
replacing the module-level `apply_flow.detect` (the flow imports it by name). Nothing opens Edge; no network;
temp folders only (the master resume, tailored folder and aliases are pointed away from data/).

Lane B's public entry point is `run(cfg, store, job_ids, *, dry_run, backend, http, browser_factory, apply_cfg,
say, evidence_dir) -> list[AttemptResult]` (eng/M20-B-browser-greenhouse, apply_flow.py). The fake adapter
implements the AtsAdapter protocol (apply/contracts.py); `FakeAdapter(dom=False)` plans from a schema (capture
point 1, before the browser opens), `FakeAdapter(dom=True)` reads fields from the page (capture point 2).
ASSUMED: capture log line `question captured key=<key> kind=<kind> reason=<reason>` (QD 4.1) and, on a failure
inside capture, `question capture failed: <ExcType>`; `question naming unavailable` (QD 11).
The first test needs only lane B and proves the harness itself.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    FIX, BackendError, Backend, Completion, extra_block, field, make_job, needs, profile, report_waiting,
    waiting_mark, yes_no,
)

from jobscraper.apply.contracts import (  # noqa: E402
    AttemptState as S, Canonical, FieldType, FormPlan, ReasonCode, StepResult, Tenant,
)
from jobscraper.apply.plan import norm_label  # noqa: E402

_MARK = waiting_mark()
RUN = ("jobscraper.apply_flow:run",)
CAPTURE = (*RUN, "jobscraper.apply.questions:capture", "jobscraper.store:Store.upsert_question",
           "jobscraper.apply_flow:_capture_questions")
TENANT = Tenant(ats="fake", host="jobs.example", board="fake")
NAMING_MARK = "You name a question from a job application form"
SECRETS = ("Testcase", "alex.testcase@example.com", "91234567", "2002-03-14", "1 Example Road", "000001",
           "Mandarin", "Hiking", "Citizen-answer")

WEEKEND = field("f_weekend", "Describe your ideal weekend.", FieldType.TEXTAREA)
VISA = field("f_visa", "What is your visa status?", FieldType.DROPDOWN, ("Citizen", "PR", "Others"))
FIRST = field("f_first", "First name", FieldType.TEXT, canonical=Canonical.FIRST_NAME)
OPTIONAL = field("f_opt", "Anything else?", FieldType.TEXTAREA, required=False)
DECLARE = yes_no("f_decl", "Please declare any matters we should be aware of.")


# ------------------------------------------------------------------ the fakes

class FakePage:
    url = "https://jobs.example/apply"

    def locator(self, _selector):
        return self

    def count(self):
        return 0

    def title(self):
        return ""

    def evaluate(self, *_a, **_k):
        return ""

    def close(self):
        pass


class FakeBrowser:
    def __init__(self, page_error: BaseException | None = None):
        self.pages, self.page_error = 0, page_error

    def new_page(self):
        if self.page_error is not None:
            raise self.page_error
        self.pages += 1
        return FakePage()

    def close(self):
        pass

    def hold(self, _s):
        pass


class FakeAdapter:
    name = "fake"
    needs_account = False
    password_rules = None
    mail_domains = ()
    otp_pattern = ""
    prefill_source = ""

    def __init__(self, fields, *, dom: bool = False):
        self.fields, self.dom = list(fields), dom

    def match_url(self, url):
        return None

    def tenant_from_company(self, job):
        return TENANT

    def plan_from_schema(self, ctx):
        if self.dom:
            return None
        return FormPlan(ats="fake", job_id=ctx.job["job_id"], apply_url="https://jobs.example/apply",
                        source="schema", fields=list(self.fields))

    def open(self, page, ctx):
        pass

    def account_wall(self, page):
        return None

    def sign_in(self, page, ctx, password):
        raise AssertionError("a test attempt never signs in")

    def sign_up(self, page, ctx, password):
        raise AssertionError("a test attempt never creates an account")

    def enter_code(self, page, ctx, code):
        raise AssertionError("a test attempt never enters a code")

    def prefill(self, page, ctx):
        return ""

    def read_values(self, page, ctx, fields):
        return {}

    def read_step(self, page, ctx):
        return "application", list(self.fields)

    def fill(self, page, ctx, fields, answers):
        return []

    def next_step(self, page, ctx):
        return StepResult(step="review", is_review=True)

    def submit(self, page, ctx):
        raise AssertionError("a test attempt must never submit")

    def after_submit(self, page, ctx):
        return None

    def visible_errors(self, page):
        return ()

    def forget(self, ctx):
        pass


class RoutingBackend(Backend):
    """Answering requests are refused (the model is 'down' for answers). A naming request (QD 5.3) gets
    the scripted reply for its question label, or raises when `naming_error` is set."""
    name = "routing"
    model_id = "routing-model"

    def __init__(self, naming: dict | None = None, naming_error: bool = False):
        self.naming = naming or {}
        self.naming_error = naming_error
        self.naming_calls: list[dict] = []
        self.answer_calls = 0

    @property
    def available(self) -> bool:
        return True

    def complete(self, system, user, max_tokens=4096, *, format=None, temperature=None, seed=None, top_k=None):
        if NAMING_MARK not in system:
            self.answer_calls += 1
            raise BackendError("model down for answers")
        self.naming_calls.append({"system": system, "user": user, "format": format, "temperature": temperature,
                                  "seed": seed, "max_tokens": max_tokens})
        if self.naming_error:
            raise BackendError("naming down")
        label = user.split("\n", 1)[0].removeprefix("QUESTION: ").strip()
        reply = self.naming.get(label) or {"key": "model_named", "title": "Model named", "description": "d",
                                           "same_as": ""}
        return Completion(text=json.dumps(reply))


class World:
    def __init__(self, tmp: Path, *, naming: bool = False, capture: bool = True, extra: dict | None = None,
                 naming_cap: int = 10):
        from jobscraper.config import Config
        from jobscraper.store import Store
        data = tmp / "data"
        data.mkdir()
        (data / "resume.pdf").write_bytes(b"%PDF-1.4\n% fixture, not a real resume\n")
        prof = profile()
        if extra is not None:
            prof["extra"] = extra
        self.path = data / "applicant.yaml"
        self.path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8")
        self.cfg = Config({
            "paths": {"db": str(data / "jobscraper.db"), "applicant": str(self.path),
                      "questions": str(FIX / "questions.sample.yaml"), "resume_dir": str(data),
                      "master_resume": str(data / "master_resume.json"), "tailored_dir": str(data / "tailored"),
                      "shortlist": str(data / "shortlist.json"), "profile": str(data / "profile.derived.yaml")},
            "tailor": {"enabled": False},
            "apply": {"mode": "dry_run", "dry_run_hold_s": 0},
            "question_capture": {"enabled": capture, "llm_naming": naming, "naming_max_per_attempt": naming_cap},
            "web": {"host": "127.0.0.1", "port": 8765}})
        self.store = Store(self.cfg.db_path)
        self.cid = self.store.insert_company("shopee", "Shopee", "https://shopee.example")
        self.tmp, self.lines = tmp, []
        self._n = 0

    def job(self) -> str:
        self._n += 1
        return make_job(self.store, self.cid, self._n)

    def run(self, job_id, adapter, *, dry_run=True, backend=None, browser=None):
        flow = importlib.import_module("jobscraper.apply_flow")
        original = flow.detect
        flow.detect = lambda job: (adapter, TENANT)
        try:
            return flow.run(self.cfg, self.store, [job_id], dry_run=dry_run, backend=backend or RoutingBackend(),
                            http=object(), browser_factory=lambda _acfg: browser or FakeBrowser(),
                            apply_cfg=self.cfg.apply, say=self.lines.append, evidence_dir=self.tmp / "evidence")[0]
        finally:
            flow.detect = original

    def groups(self, status="open") -> dict:
        return {g["key"]: g for g in self.store.question_groups(status)}

    def close(self):
        self.store.close()


class _world:
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self) -> World:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.w = World(Path(self.tmp.name), **self.kw)
        return self.w

    def __exit__(self, *exc):
        self.w.close()
        self.tmp.cleanup()


def _extra_without_visa() -> dict:
    """The sample `extra:` block minus `visa_status`. With it, tier 3 correctly answers this file's
    VISA field for Shopee (`by_employer.shopee` picks [citizen], same employer, same options), so
    nothing is captured: the tests that want the VISA question captured use this block instead.
    The other entries (incl. the sensitive one) stay, for the redaction checks."""
    ex = extra_block()
    ex.pop("visa_status")
    return ex


def _stopped(res):
    assert res.state is S.FAILED and res.reason is ReasonCode.UNANSWERABLE_REQUIRED, (res.state, res.reason,
                                                                                     res.reason_detail)


# ================================================================== the fakes (run now)

def test_the_fake_adapter_satisfies_the_protocol_and_the_routing_backend_routes_by_system_prompt():
    from jobscraper.apply.contracts import AtsAdapter
    assert isinstance(FakeAdapter([WEEKEND]), AtsAdapter), "the fake implements every AtsAdapter method"
    plan = FakeAdapter([WEEKEND, VISA]).plan_from_schema(type("C", (), {"job": {"job_id": "j"}})())
    assert plan.source == "schema" and [f.key for f in plan.fields] == ["f_weekend", "f_visa"]
    assert FakeAdapter([WEEKEND], dom=True).plan_from_schema(None) is None
    be = RoutingBackend()
    try:
        be.complete("You answer one question on a job application", "QUESTION: x")
    except BackendError:
        pass
    else:
        raise AssertionError("answering requests are refused")
    named = json.loads(be.complete(NAMING_MARK + " so it can be saved", "QUESTION: Anything?\nTYPE: text").text)
    assert set(named) == {"key", "title", "description", "same_as"} and len(be.naming_calls) == 1
    assert norm_label(WEEKEND.label) == "describe your ideal weekend"


# ================================================================== the harness (lane B only)

@needs(*RUN)
def test_the_harness_ends_a_schema_plan_with_unanswerable_required_before_the_browser_opens():
    with _world() as w:
        browser = FakeBrowser()
        res = w.run(w.job(), FakeAdapter([FIRST, WEEKEND, VISA, OPTIONAL]), browser=browser)
        _stopped(res)
        assert browser.pages == 0, "a planning stop never opens the browser"
        by_key = {a.field_key: a for a in res.answers}
        assert by_key["f_first"].fills and by_key["f_first"].source == "field_map:first_name"
        assert not by_key["f_weekend"].fills and not by_key["f_visa"].fills


# ================================================================== capture at the two points (QD 4.1)

@needs(*CAPTURE)
def test_a_schema_plan_with_two_required_unknowns_captures_both_with_sightings():
    with _world() as w:
        jid = w.job()
        res = w.run(jid, FakeAdapter([FIRST, WEEKEND, VISA, OPTIONAL]))
        _stopped(res)
        groups = w.groups()
        assert set(groups) == {"describe_ideal_weekend", "visa_status"}, sorted(groups)   # slugs (naming off)
        assert groups["describe_ideal_weekend"]["kind"] == "text" and groups["visa_status"]["kind"] == "choice"
        v = groups["visa_status"]["variants"]
        assert len(v) == 1 and [o["label"] if isinstance(o, dict) else o for o in v[0]["options"]] == \
            ["Citizen", "PR", "Others"]
        assert groups["visa_status"]["employers"] == ["Shopee"]
        assert not groups["visa_status"]["sensitive"] and groups["visa_status"]["named_by"] == "rule"
        cand = {c["job_id"]: c for c in w.store.retry_candidates()}
        assert cand[jid]["attempt_id"] == res.attempt_id and cand[jid]["open"] == 2 and cand[jid]["dismissed"] == 0
        assert "Anything else?" not in {g["title"] for g in groups.values()}, "an optional field is not captured"


@needs(*CAPTURE)
def test_an_auto_mode_run_captures_too_and_still_never_opens_the_browser_for_a_planning_stop():
    with _world() as w:
        browser = FakeBrowser()
        res = w.run(w.job(), FakeAdapter([WEEKEND, VISA]), dry_run=False, browser=browser)
        _stopped(res)
        assert browser.pages == 0
        assert set(w.groups()) == {"describe_ideal_weekend", "visa_status"}, "capture runs in dry-run and auto alike"


@needs(*CAPTURE)
def test_a_dom_step_with_required_unknowns_is_captured_at_the_filling_point():
    with _world() as w:
        browser = FakeBrowser()
        jid = w.job()
        res = w.run(jid, FakeAdapter([FIRST, WEEKEND, VISA], dom=True), browser=browser)
        _stopped(res)
        assert browser.pages == 1, "the DOM adapter opened the page before it could read the step"
        assert set(w.groups()) == {"describe_ideal_weekend", "visa_status"}
        assert {c["job_id"]: c["open"] for c in w.store.retry_candidates()} == {jid: 2}


@needs(*CAPTURE)
def test_a_declaration_the_resolver_could_not_settle_is_captured_as_private_and_a_sensitive_one_is_never_named():
    be = RoutingBackend()
    with _world(naming=True) as w:
        res = w.run(w.job(), FakeAdapter([DECLARE]), backend=be)
        _stopped(res)
        g = next(iter(w.groups().values()))
        assert g["sensitive"] is True and g["named_by"] == "rule"
        assert be.naming_calls == [], "a sensitive question makes no naming call (QD 5.3)"


# ================================================================== it never changes an outcome (QD 4.1, 11)

@needs(*CAPTURE)
def test_a_store_error_inside_capture_leaves_the_outcome_and_logs_the_exception_type():
    from jobscraper.store import Store
    original = Store.upsert_question

    def boom(self, *a, **k):
        raise RuntimeError("disk on fire")
    Store.upsert_question = boom
    try:
        with _world() as w:
            res = w.run(w.job(), FakeAdapter([WEEKEND, VISA]))
            _stopped(res)
            assert any("question capture failed: RuntimeError" in ln for ln in w.lines), w.lines
            assert not any("disk on fire" in ln for ln in w.lines), "the log names the type, not the message"
    finally:
        Store.upsert_question = original


@needs(*CAPTURE)
def test_capture_can_be_switched_off():
    with _world(capture=False) as w:
        res = w.run(w.job(), FakeAdapter([WEEKEND, VISA]))
        _stopped(res)
        assert w.groups("all") == {} and not any("question captured" in ln for ln in w.lines)


@needs(*CAPTURE)
def test_a_by_employer_pick_answers_the_visa_field_for_its_own_employer_only():
    """apply_design tier 3: `visa_status.by_employer.shopee` (picks [citizen]) answers this file's
    VISA field at Shopee, so it is not captured; the same field at another employer gets only the
    entry's general picks ("singapore citizen" is no option here), so it IS captured. Pins that the
    override is neither ignored for its employer nor applied to the wrong one."""
    with _world(extra=extra_block()) as w:
        _stopped(w.run(w.job(), FakeAdapter([FIRST, WEEKEND, VISA])))
        assert set(w.groups()) == {"describe_ideal_weekend"}, sorted(w.groups())
    with _world(extra=extra_block()) as w:
        other = w.store.insert_company("othercorp", "Othercorp", "https://othercorp.example")
        res = w.run(make_job(w.store, other, 77), FakeAdapter([FIRST, WEEKEND, VISA]))
        _stopped(res)
        assert set(w.groups()) == {"describe_ideal_weekend", "visa_status"}, sorted(w.groups())


@needs(*CAPTURE)
def test_the_job_log_holds_key_kind_and_reason_but_no_profile_value_and_no_answer():
    with _world(extra=_extra_without_visa()) as w:
        res = w.run(w.job(), FakeAdapter([FIRST, WEEKEND, VISA]))
        _stopped(res)
        text = "\n".join(w.lines)
        captured = re.findall(r"question captured key=(\S+) kind=(\w+) reason=(\w+)", text)
        assert sorted(captured) == [("describe_ideal_weekend", "text", "no_rule"), ("visa_status", "choice", "no_rule")]
        for secret in SECRETS:
            assert secret not in text, f"{secret!r} reached the job log"


# ================================================================== naming goes through the attempt's backend (QD 5.3)

@needs(*CAPTURE)
def test_naming_uses_the_attempts_backend_with_the_fixed_call_and_a_prompt_free_of_profile_and_employer():
    from jobscraper.apply import questions
    be = RoutingBackend(naming={
        "Describe your ideal weekend.": {"key": "ideal_weekend", "title": "Ideal weekend", "description": "d",
                                          "same_as": ""},
        "What is your visa status?": {"key": "visa_type", "title": "Visa type", "description": "d", "same_as": ""}})
    with _world(naming=True, extra=_extra_without_visa()) as w:
        res = w.run(w.job(), FakeAdapter([WEEKEND, VISA]), backend=be)
        _stopped(res)
        groups = w.groups()
        assert set(groups) == {"ideal_weekend", "visa_type"}, sorted(groups)
        assert all(g["named_by"] == "model" for g in groups.values())
    assert len(be.naming_calls) == 2
    for c in be.naming_calls:
        assert c["format"] == questions.NAMING_SCHEMA and c["temperature"] == 0 and c["seed"] == 7
        assert c["max_tokens"] == 200 and c["system"] == questions.NAMING_SYSTEM
        low = c["user"].lower()
        for secret in SECRETS + ("shopee",):
            assert secret.lower() not in low, f"{secret!r} must never reach a naming prompt"


@needs(*CAPTURE)
def test_a_naming_failure_falls_back_to_slugs_and_logs_it_and_the_cap_limits_the_calls():
    be = RoutingBackend(naming_error=True)
    with _world(naming=True) as w:
        res = w.run(w.job(), FakeAdapter([WEEKEND, VISA]), backend=be)
        _stopped(res)
        assert set(w.groups()) == {"describe_ideal_weekend", "visa_status"}
        assert any("question naming unavailable" in ln for ln in w.lines), w.lines
    be = RoutingBackend()
    with _world(naming=True, naming_cap=1) as w:
        res = w.run(w.job(), FakeAdapter([WEEKEND, VISA]), backend=be)
        _stopped(res)
        assert len(be.naming_calls) == 1, "naming_max_per_attempt caps the model calls; the rest get slugs"
        named = sorted(g["named_by"] for g in w.groups().values())
        assert named == ["model", "rule"]


# ================================================================== answer, retry, answered at tier 3 (QD 6.2, 9.2)

@needs(*CAPTURE)
def test_after_the_owner_answers_a_second_attempt_answers_both_questions_from_extra():
    import jobscraper.applicant as A
    with _world() as w:
        jid = w.job()
        first = w.run(jid, FakeAdapter([FIRST, WEEKEND, VISA]))
        _stopped(first)
        # the owner answers in Profile -> Application details (what POST /api/questions/answer writes)
        prof = A.load(w.path)
        extra = prof.setdefault("extra", {})
        for key, g in w.groups().items():
            labels = sorted({norm_label(x) for x in g["labels"]})
            if g["kind"] == "choice":
                opts = [o["norm"] if isinstance(o, dict) and "norm" in o else norm_label(o["label"] if isinstance(o, dict) else o)
                        for o in g["variants"][0]["options"]]
                extra[key] = {"title": g["title"], "description": "", "kind": "choice", "sensitive": False,
                              "labels": labels, "value": None, "picks": ["citizen"], "seen": opts}
            else:
                extra[key] = {"title": g["title"], "description": "", "kind": "text", "sensitive": False,
                              "labels": labels, "value": "Hiking"}
            w.store.set_questions_status(key, "answered", "2026-11-02T12:00:00")
        w.store.commit()
        A.save(w.path, prof)
        # the retry: a NEW attempt for the same job (a failed attempt does not block it)
        browser = FakeBrowser(page_error=RuntimeError("stop after planning"))
        second = w.run(jid, FakeAdapter([FIRST, WEEKEND, VISA]), browser=browser)
        assert second.attempt_id != first.attempt_id
        assert second.reason is not ReasonCode.UNANSWERABLE_REQUIRED, "both required questions are answered now"
        by_key = {a.field_key: a for a in second.answers}
        assert by_key["f_weekend"].source == "memory:extra.describe_ideal_weekend", by_key["f_weekend"]
        assert by_key["f_weekend"].value == "Hiking"
        assert by_key["f_visa"].source == "memory:extra.visa_status", by_key["f_visa"]
        assert list(by_key["f_visa"].option_labels) == ["Citizen"]
        assert all(c["job_id"] != jid for c in w.store.retry_candidates()), \
            "the job's newest attempt no longer stopped on a question"


report_waiting("test_apply_flow_questions", _MARK)
