"""WP-T0: contract v5 oracles (D-78, ADR-0006, llm_fill_design.md §2-§9; Q-35).

Verify: `python tests/run_tests.py -k apply_contracts_v5`. Pure checks on
`jobscraper.apply.contracts`; nothing here needs a browser, a model or a store.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    GENERIC_LABELS, PREFILL_SOURCES, REASON_TEXTS, SITE_VALUE_SOURCES, TRUSTED_ORIGINS,
    Answer, AnswerSource, AnswerStatus, AnswerTier, EntryGroup, EntrySection, Fact, FieldType,
    FillSource, FormField, ModelDecision, PageField, PageOutcome, PasswordRules, ReasonCode,
    SiteNavigator, StepResult, Tenant, ValueOrigin,
)
from jobscraper.apply.plan import norm_label  # noqa: E402

SITE_ORIGINS = (ValueOrigin.SITE_DEFAULT, ValueOrigin.RESUME_IMPORT, ValueOrigin.MYGREENHOUSE,
                ValueOrigin.WORKDAY_LAST_APPLICATION)


def test_contract_version_is_at_least_5():
    assert C.CONTRACT_VERSION >= 5


def test_model_unavailable_has_owner_copy_that_says_nothing_was_sent():
    assert ReasonCode.MODEL_UNAVAILABLE.value == "model_unavailable"
    rt = REASON_TEXTS[ReasonCode.MODEL_UNAVAILABLE]
    rendered = rt.text.format(detail="timed out on my_information")
    assert "timed out on my_information" in rendered
    assert "{" not in rendered and "}" not in rendered
    assert "nothing was sent" in rendered.lower()
    assert "doctor" in rt.hint


def test_site_value_origins_are_answer_sources():
    """LF §3.3 / §7: an Answer's `source` for a kept value is the origin's value."""
    for o in SITE_ORIGINS:
        assert AnswerSource(o.value).value == o.value, o
    # EMPTY and OURS are not site values: neither may name the source of a kept answer
    for o in (ValueOrigin.EMPTY, ValueOrigin.OURS):
        assert o.value not in {s.value for s in AnswerSource}, o


def test_site_value_sources_cover_the_prefill_sources_and_the_resume_import():
    assert SITE_VALUE_SOURCES >= PREFILL_SOURCES
    assert AnswerSource.RESUME_IMPORT in SITE_VALUE_SOURCES
    for s in ("standing", "resume", "job"):
        assert AnswerSource(s)  # v5 additions exist


def test_only_mygreenhouse_is_a_trusted_origin():
    """G8: only the owner's own MyGreenhouse entries are kept without grounding."""
    assert TRUSTED_ORIGINS == frozenset({ValueOrigin.MYGREENHOUSE})
    assert ValueOrigin.RESUME_IMPORT not in TRUSTED_ORIGINS
    assert ValueOrigin.OURS not in TRUSTED_ORIGINS


def test_generic_labels_are_already_normalised_and_contain_the_q30_cases():
    for g in GENERIC_LABELS:
        assert norm_label(g) == g, g
    for g in ("if yes please specify", "please specify", "other"):
        assert g in GENERIC_LABELS


def test_fill_sources_match_the_model_output_schema_enum():
    """LF §6.3: the `source` enum the model answers with."""
    assert [s.value for s in FillSource] == ["profile", "extra", "standing", "resume", "job",
                                             "keep", "unknown"]


def test_page_field_defaults_and_immutability():
    ff = FormField(key="f1", label="Country", type=FieldType.DROPDOWN, required=True)
    pf = PageField(field=ff, widget="aria_listbox")
    assert pf.shown == "" and pf.origin is ValueOrigin.EMPTY
    assert pf.group == "" and pf.group_title == "" and pf.context == "" and pf.error == ""
    assert pf.options_complete is True
    try:
        pf.shown = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("PageField must be frozen")


def test_entry_types_and_fact_defaults():
    g = EntryGroup(section="work_experience", index=2, title="Work Experience 2", locator="#p2")
    assert g.delete_locator == ""
    s = EntrySection(section="work_experience", title="Work Experience", entries=(g,))
    assert s.add_locator == "" and s.required is False and s.entries[0].index == 2
    f = Fact(ref="profile:contact.city", title="City")
    assert f.private is False and f.is_set is True and f.kind == "text" and f.entry == ""


def test_model_decision_and_page_outcome_defaults():
    d = ModelDecision(field_key="f1", source=FillSource.UNKNOWN)
    assert d.ref == "" and d.value is None and d.evidence == "" and d.via == "page"
    o = PageOutcome(step="my_information")
    assert o.fields == [] and o.answers == {} and o.unknown_required == ()
    assert o.fill_failed == () and o.model_calls == 0 and o.model_seconds == 0.0


def test_answer_still_builds_positionally_with_six_args_and_has_the_v5_audit_fields():
    a = Answer("f1", "Singapore", AnswerTier.PROFILE_RULE, "profile:contact.country", 0.95,
               AnswerStatus.FILLED)
    assert a.fills
    assert a.evidence == "" and a.shown is None and a.origin == "" and a.entry == ""
    assert Answer("f2", "x", AnswerTier.NONE, "standing:today", 0.95).source_kind \
        is AnswerSource.STANDING


class _MinimalNavigator:
    """Implements every SiteNavigator member with no behaviour (LF §9.4 step 1-3)."""
    name = "example"
    needs_account = False
    password_rules = PasswordRules()
    mail_domains: tuple[str, ...] = ()
    otp_pattern = ""

    def match_url(self, url: str) -> Optional[Tenant]: return None
    def tenant_from_company(self, job: dict[str, Any]) -> Optional[Tenant]: return None
    def precheck(self, ctx) -> None: return None
    def open(self, page, ctx) -> None: return None
    def choose_entry(self, page, ctx) -> str: return ""
    def account_wall(self, page) -> Optional[str]: return None
    def sign_in(self, page, ctx, password) -> None: return None
    def sign_up(self, page, ctx, password) -> str: return ""
    def enter_code(self, page, ctx, code: str) -> None: return None
    def step_id(self, page, ctx) -> str: return "form"
    def scope(self, page, ctx) -> str: return ""
    def entry_sections(self, page, ctx) -> list: return []
    def next_step(self, page, ctx) -> StepResult: return StepResult(step="review", is_review=True)
    def submit(self, page, ctx) -> None: return None
    def after_submit(self, page, ctx) -> Optional[str]: return None
    def visible_errors(self, page) -> tuple[str, ...]: return ()


def test_a_minimal_class_with_every_member_is_a_site_navigator():
    assert isinstance(_MinimalNavigator(), SiteNavigator)


def test_a_class_missing_a_navigation_member_is_not_a_site_navigator():
    body = {k: v for k, v in vars(_MinimalNavigator).items()
            if not k.startswith("__") and k != "submit"}
    NoSubmit = type("NoSubmit", (), body)
    assert not isinstance(NoSubmit(), SiteNavigator)


def test_amended_v5_fields_default_empty_and_are_not_shared():
    """Amendment after stage E (additive v5): resume_entries, other_employers, pre_import,
    uploaded, transport_failed."""
    from jobscraper.apply.contracts import AttemptContext, ResolveContext
    r = ResolveContext(profile={}, employer_name="Example Employer")
    assert r.resume_entries == () and r.other_employers == ()
    kw = dict(attempt_id=1, job={}, tenant=Tenant(ats="workday", host="example.test", board="example"),
              dry_run=True, email="", resume_path="", log=lambda s: None,
              screenshot=lambda p, s: "", deadline=0.0)
    a, b = AttemptContext(**kw), AttemptContext(**kw)
    assert a.pre_import == {} and a.uploaded == {}
    a.uploaded["cv.pdf"] = "0" * 64
    a.pre_import["k"] = "v"
    assert b.uploaded == {} and b.pre_import == {}, "default dicts must not be shared"
    assert PageOutcome(step="x").transport_failed is False
    assert ModelDecision(field_key="f", source=FillSource.KEEP).via == "page"


class _MinimalServices:
    backend = None
    model = "fake"
    rules = None
    cfg: dict = {}

    def today(self) -> str: return "2026-11-03"
    def now(self) -> float: return 0.0
    def deadline_left(self) -> float: return 60.0
    def classify(self, page) -> None: return None
    def cache_get(self, job_id, sigs, prompt_version, model, inputs_hash) -> dict: return {}
    def cache_put(self, job_id, rows) -> None: return None
    def log(self, line: str) -> None: return None


def test_a_minimal_class_with_every_member_is_fill_services():
    from jobscraper.apply.contracts import FillServices
    assert isinstance(_MinimalServices(), FillServices)
    body = {k: v for k, v in vars(_MinimalServices).items() if not k.startswith("__") and k != "classify"}
    assert not isinstance(type("NoClassify", (), body)(), FillServices), "classify is required (review M6)"


def test_site_navigator_has_no_fill_side_members():
    """D-78: navigators navigate; reading and filling are generic (LF §9)."""
    members = {n for n in dir(SiteNavigator) if not n.startswith("_")}
    for gone in ("fill", "read_step", "plan_from_schema", "prefill", "read_values"):
        assert gone not in members, gone
