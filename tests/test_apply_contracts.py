"""Auto-apply oracles (M20): state machine, reason codes, profile rules, resolver tiers,
declarations, fail-closed paths, duplicate and cap guards, the Greenhouse plan and the
page classifier. Plan: tests/plans/apply_test_plan.md. Design: docs/architecture/apply_design.md.

Three kinds of test live here:
  1. Contract tests (run now): only `jobscraper.apply.contracts`.
  2. Fixture integrity (run now): the fixtures match the design and hold no personal data.
  3. Oracles for modules M20 builds. Each is decorated `@needs(<module>)`; until that module
     exists the test is not defined (the runner never sees it) and one line at import names
     what is waiting. Engineers: `python tests/run_tests.py -k apply_contracts` is your Verify.

Signatures come from the design. Where the design leaves one open, the ASSUMED call sits in
one helper below (`_load_rules`), so a different name is a one-line change here.
No network: the Greenhouse schema comes from tests/fixtures, browser tests open local files.
"""
from __future__ import annotations

import importlib
import json
import re
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.apply.contracts import (  # noqa: E402
    REASON_TEXTS, STATE_TEXTS, SUCCESS_STATES, TERMINAL_STATES, TRANSITIONS,
    Answer, AnswerStatus, AnswerTier, ApplyFailure, AttemptContext, AttemptResult,
    AttemptState as S, Canonical, DeclarationLabel, FieldType, FormField, Option,
    ReasonCode, ResolveContext, Secret, Tenant, can_transition,
)
from jobscraper.backends import Backend, BackendError, Completion  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "apply"
GH = FIX / "greenhouse"
SAMPLE = FIX / "applicant.sample.yaml"
QUESTIONS = FIX / "questions.sample.yaml"
NOW = "2026-11-02T10:00:00"   # store.TIME_FMT, UTC

# ------------------------------------------------------------------ gating

_WAITING: list[tuple[str, str]] = []


def _missing(spec: str) -> str:
    """'' if `spec` is importable, else what is missing. `spec` is a module, or
    `module:Attr.attr` for something that must exist inside an existing module."""
    mod, _, attr = spec.partition(":")
    try:
        obj = importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name and (mod == e.name or mod.startswith(e.name + ".")):
            return mod
        raise                                   # the module exists but is broken: a real failure
    for part in filter(None, attr.split(".")):
        if not hasattr(obj, part):
            return spec
        obj = getattr(obj, part)
    return ""


def needs(*specs: str):
    """Define the test only once everything in `specs` exists (see the module doc)."""
    gone = [m for m in (_missing(s) for s in specs) if m]

    def deco(fn):
        if gone:
            _WAITING.append((fn.__name__, gone[0]))
            return None
        return fn
    return deco


# ------------------------------------------------------------------ helpers

def _profile() -> dict:
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


def _schema(board: str) -> dict:
    return json.loads((GH / f"gh_{board}.json").read_text(encoding="utf-8"))


def _f(key, label, type=FieldType.TEXT, options=(), required=True, canonical=None, max_length=None):
    return FormField(key=key, label=label, type=type, required=required,
                     options=tuple(Option(o) for o in options), canonical=canonical,
                     max_length=max_length)


def _yn(key, label, required=True):
    return _f(key, label, FieldType.DROPDOWN, ("Yes", "No"), required)


def _chosen(a: Answer) -> tuple:
    if a.option_labels:
        return tuple(a.option_labels)
    return tuple(a.value) if isinstance(a.value, list) else (a.value,)


class StubBackend(Backend):
    """Scripted model. Each reply is a dict (sent as JSON), a raw string, or an exception."""
    name = "stub"
    model_id = "stub-model"

    def __init__(self, replies=()):
        self.replies = list(replies)
        self.calls: list[dict] = []

    @property
    def available(self) -> bool:
        return True

    def complete(self, system, user, max_tokens=4096, *, format=None, temperature=None,
                 seed=None, top_k=None):
        self.calls.append({"system": system, "user": user, "format": format,
                           "temperature": temperature, "seed": seed, "max_tokens": max_tokens})
        if not self.replies:
            raise BackendError("stub: no reply scripted")
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return Completion(text=r if isinstance(r, str) else json.dumps(r))


RESUME_TEXT = ("Alex Testcase\nExperience\nSoftware Engineering Intern, Example Logistics Pte Ltd\n"
               "Built REST APIs in Python and Postgres for shipment tracking.\n")


def _load_rules(path: Path):
    R = importlib.import_module("jobscraper.apply.resolve")
    return R.load_rules(path)                   # ASSUMED name (design names only the type QuestionRules)


def _resolve(fields, *, backend=None, employer="Example Employer", aliases=(),
             previously_applied=False, profile=None, jd="", resume=RESUME_TEXT):
    R = importlib.import_module("jobscraper.apply.resolve")
    ctx = ResolveContext(profile=profile or _profile(), employer_name=employer,
                         employer_aliases=tuple(aliases), previously_applied=previously_applied,
                         jd_text=jd, resume_text=resume, resume_path="C:/fixture/Alex_Testcase_Resume.pdf",
                         ats="greenhouse")
    out = R.resolve_all(list(fields), ctx, backend=backend or StubBackend(),
                        rules=_load_rules(QUESTIONS), memory=lambda *_a: None)
    assert set(out) == {f.key for f in fields}, "every field gets exactly one Answer"
    return out


def _one(field, **kw) -> Answer:
    return _resolve([field], **kw)[field.key]


# ================================================================== 1. contracts (run now)

def test_every_non_terminal_state_may_fail_and_terminal_states_are_final():
    for st in S:
        if st in TERMINAL_STATES:
            assert TRANSITIONS[st] == frozenset(), f"{st} is terminal: no automatic way out"
        elif st is S.SUBMITTING:
            # D-69 / NF-06: once Submit is clicked an attempt ends only submitted or
            # submitted_unconfirmed, never failed.
            assert not can_transition(st, S.FAILED), "no submitting -> failed (D-69)"
            assert TRANSITIONS[st] <= {S.VERIFYING_EMAIL, S.SUBMITTED, S.SUBMITTED_UNCONFIRMED}
        else:
            assert can_transition(st, S.FAILED), f"{st} must be able to fail"
    assert SUCCESS_STATES <= TERMINAL_STATES


def test_only_the_review_page_leads_to_submit_and_a_dry_run_never_submits():
    assert can_transition(S.FILLING, S.SUBMITTING)
    assert can_transition(S.FILLING, S.READY_TO_SUBMIT)
    into_submitting = {src for src, dst in TRANSITIONS.items() if S.SUBMITTING in dst}
    assert into_submitting == {S.FILLING, S.VERIFYING_EMAIL}, "only review page or the emailed code (4.2)"
    assert not can_transition(S.READY_TO_SUBMIT, S.SUBMITTING), "dry run is terminal"
    assert not can_transition(S.SUBMITTED, S.SUBMITTING), "never a second automatic Submit"
    assert not can_transition(S.SUBMITTED_UNCONFIRMED, S.SUBMITTING)
    assert not can_transition(S.QUEUED, S.SUBMITTED)
    for success in SUCCESS_STATES:
        sources = {src for src, dst in TRANSITIONS.items() if success in dst}
        allowed = {S.SUBMITTING} | ({S.VERIFYING_EMAIL} if success is S.SUBMITTED_UNCONFIRMED else set())
        assert sources == allowed, f"{success} only after a Submit click"
    assert not can_transition(S.VERIFYING_EMAIL, S.SUBMITTED), "a code page cannot prove success"
    # NF-06 with the click flag: after the click, failed is rejected; before it, no success state.
    assert not can_transition(S.VERIFYING_EMAIL, S.FAILED, clicked=True)
    assert not can_transition(S.VERIFYING_EMAIL, S.SUBMITTED_UNCONFIRMED, clicked=False)
    assert can_transition(S.VERIFYING_EMAIL, S.SUBMITTED_UNCONFIRMED, clicked=True)


def test_every_reason_code_has_owner_copy_and_detail_fills_cleanly():
    assert set(REASON_TEXTS) == set(ReasonCode)
    for code, rt in REASON_TEXTS.items():
        assert rt.text and rt.hint, code
        rendered = rt.text.format(detail="Example label")
        assert "{" not in rendered and "}" not in rendered, code
    assert set(STATE_TEXTS) == {S.SUBMITTED_UNCONFIRMED, S.READY_TO_SUBMIT}


def test_stop_reasons_tell_the_owner_nothing_was_sent():
    for code in (ReasonCode.CAPTCHA, ReasonCode.BOT_CHALLENGE, ReasonCode.ERROR):
        t = REASON_TEXTS[code].text.lower()
        assert "nothing was sent" in t or "before sending" in t, code


def test_answer_tiers_follow_the_f32_order():
    assert [t.name for t in sorted(AnswerTier) if t] == [
        "FIELD_MAP", "PROFILE_RULE", "MEMORY", "DECLARATION", "LLM"]


def test_an_answer_fills_only_when_filled_with_a_value():
    a = Answer("k", "x", AnswerTier.FIELD_MAP, "field_map:email", 1.0)
    assert a.fills
    for v in (None, "", []):
        assert not Answer("k", v, AnswerTier.FIELD_MAP, "s", 1.0).fills
    for st in AnswerStatus:
        if st is not AnswerStatus.FILLED:
            assert not Answer("k", "x", AnswerTier.LLM, "llm", 0.9, status=st).fills, st


def test_secrets_never_print_and_vault_names_are_per_tenant():
    s = Secret("not-a-real-password-1!")
    assert "not-a-real" not in repr(s) and "not-a-real" not in str(s) and "not-a-real" not in f"{s}"
    assert s.reveal() == "not-a-real-password-1!"
    t = Tenant("workday", "Example.WD3.myworkdayjobs.com", "example")
    assert t.vault_service == "jobscraper:workday:example.wd3.myworkdayjobs.com"


def test_apply_failure_carries_its_reason_and_only_dry_run_or_submitted_is_ok():
    e = ApplyFailure(ReasonCode.UNANSWERABLE_REQUIRED, "Gender", step="form")
    assert e.reason is ReasonCode.UNANSWERABLE_REQUIRED and e.detail == "Gender" and e.step == "form"
    ok = {st for st in S if AttemptResult(1, "j", st).ok}
    assert ok == {S.SUBMITTED, S.READY_TO_SUBMIT}


# ================================================================== 2. fixtures (run now)

def _design_template() -> dict:
    text = (ROOT / "docs" / "architecture" / "apply_design.md").read_text(encoding="utf-8")
    m = re.search(r"```yaml\n(# JobScraper applicant profile: TEMPLATE.*?)```", text, re.S)
    assert m, "the §5.4 template block moved"
    return yaml.safe_load(m.group(1))


def _keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        path = f"{prefix}{k}"
        out.add(path)
        if isinstance(v, dict) and path not in ("singapore_status.authorised_to_work",
                                                "singapore_status.requires_sponsorship"):
            out |= _keys(v, path + ".")
    return out


def test_sample_applicant_has_exactly_the_design_template_keys():
    tpl, sample = _design_template(), _profile()
    assert _keys(sample) == _keys(tpl), sorted(_keys(sample) ^ _keys(tpl))
    for lst in ("education", "experience"):
        assert set(sample[lst][0]) == set(tpl[lst][0]), lst


def test_sample_applicant_is_a_fake_person():
    p = _profile()
    text = SAMPLE.read_text(encoding="utf-8")
    assert p["contact"]["email"].endswith("@example.com")
    assert not re.search(r"\b[STFGM]\d{7}[A-Z]\b", text), "no NRIC-shaped string"
    assert re.fullmatch(r"[3689]\d{7}", p["contact"]["phone_number"])


def test_greenhouse_fixtures_are_public_schemas_with_no_personal_data():
    for board in ("vercel", "dataiku"):
        raw = (GH / f"gh_{board}.json").read_text(encoding="utf-8")
        d = json.loads(raw)
        assert d["questions"] and "location_questions" in d
        emails = set(re.findall(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+", raw))
        assert all(e.endswith(f"@{board}.com") for e in emails), emails   # company role mailboxes only
        for leak in ("benjamin", "fernandez", "test@example.com"):
            assert leak not in raw.lower()


def test_form_html_has_an_element_for_every_dataiku_field():
    html = (GH / "form.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    d = _schema("dataiku")
    names = {f["name"] for q in d["questions"] for f in q["fields"]}
    names |= {str(q["id"]) for q in d["demographic_questions"]["questions"]}
    names |= {"country", "candidate-location", "gdpr_processing_consent_given_1",
              "gdpr_retention_consent_given_1"}
    assert names <= ids, sorted(names - ids)
    assert 'class="grecaptcha-badge"' in html and "size=invisible" in html
    assert "bframe" not in html, "the plain form has no visible challenge"
    assert 'button type="submit"' in html
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html, "no network"
    challenge = (GH / "form_challenge.html").read_text(encoding="utf-8")
    assert 'src="recaptcha/bframe.html' in challenge


# ================================================================== 3a. applicant profile (lane P)

@needs("jobscraper.applicant")
def test_sample_profile_validates_clean_and_is_complete():
    A = importlib.import_module("jobscraper.applicant")
    p = _profile()
    assert A.validate(p) == []
    assert set(A.missing_for_apply(p)) <= {"documents.resume"}, "only the resume file may be reported"


@needs("jobscraper.applicant")
def test_validation_names_each_bad_field():
    A = importlib.import_module("jobscraper.applicant")
    cases = [
        (("contact", "postal_code"), "12345", "contact.postal_code"),
        (("contact", "email"), "alex.example.com", "contact.email"),
        (("contact", "phone_number"), "12345678", "contact.phone_number"),
        (("contact", "phone_country_code"), "65", "contact.phone_country_code"),
        (("pay", "months_per_year"), 15, "pay.months_per_year"),
        (("availability", "willing_to_travel_pct"), 120, "availability.willing_to_travel_pct"),
        (("singapore_status", "nric_last4"), "1234", "singapore_status.nric_last4"),
        (("identity", "gender"), "unknown_value", "identity.gender"),
    ]
    for (sec, key), bad, path in cases:
        p = _profile()
        p[sec][key] = bad
        errs = A.validate(p)
        assert path in {e.path for e in errs}, (path, errs)
    p = _profile()
    p["pay"]["expected_salary"]["amount"] = -5
    assert "pay.expected_salary.amount" in {e.path for e in A.validate(p)}
    p = _profile()
    p["education"][0]["end"] = "2020-01"            # before start 2021-08
    assert any(e.path.startswith("education[0]") for e in A.validate(p))
    p = _profile()
    p["contact"]["address_line2"] = "S1234567D"      # a full NRIC anywhere is an error
    assert A.validate(p), "a full NRIC-shaped string must be rejected"


@needs("jobscraper.applicant")
def test_missing_for_apply_lists_required_paths():
    A = importlib.import_module("jobscraper.applicant")
    p = _profile()
    p["contact"]["email"] = ""
    p["education"] = []
    p["consents"]["certify_true"] = None
    missing = set(A.missing_for_apply(p))
    assert {"contact.email", "education", "consents.certify_true"} <= missing, missing


@needs("jobscraper.applicant")
def test_llm_extract_and_logs_never_carry_sensitive_values():
    A = importlib.import_module("jobscraper.applicant")
    p = _profile()
    dumped = json.dumps(A.llm_extract(p), default=str)
    for secret in ("2002-03-14", "91234567", "alex.testcase@example.com", "000001",
                   "1 Example Road", "2022-06", "pep", "criminal"):
        assert secret not in dumped, secret
    assert "Example Logistics Pte Ltd" in dumped, "experience is on the allow-list"
    red = A.redaction_values(p)
    assert "alex.testcase@example.com" in red and "91234567" in red


@needs("jobscraper.applicant")
def test_computed_facts_from_experience_and_education():
    A = importlib.import_module("jobscraper.applicant")
    f = A.computed_facts(_profile(), date(2026, 11, 2))
    assert f["graduation_year"] == 2025
    assert f["experience_years"] == 0
    assert 8 <= f["experience_months"] <= 10   # 2 internships, 4 + 6 months (inclusive/exclusive: see plan)


# ================================================================== 3b. labels and declarations (lane P)

@needs("jobscraper.apply.plan")
def test_norm_label_rules():
    norm = importlib.import_module("jobscraper.apply.plan").norm_label
    assert norm("1. What is your <b>Email</b> Address? *") == "what is your email address"
    assert norm("Don’t you (required)") == "don't you"   # D-69: apostrophes kept
    assert norm("C++ / C# experience (optional)") == "c++ c# experience"


@needs("jobscraper.apply.declarations", "jobscraper.apply.plan")
def test_declaration_classifier_labels_each_class_and_flags_ambiguity():
    D = importlib.import_module("jobscraper.apply.declarations")
    norm = importlib.import_module("jobscraper.apply.plan").norm_label
    cases = {
        "Are you a politically exposed person (PEP)?": DeclarationLabel.PEP,
        "Do you hold shares in this company?": DeclarationLabel.SHAREHOLDING,
        "Do you have any relatives working at the company?": DeclarationLabel.RELATIVES,
        "Have you ever been convicted of a crime?": DeclarationLabel.CRIMINAL_RECORD,
        "Have you previously worked for us?": DeclarationLabel.PRIOR_EMPLOYMENT,
        "Have you previously applied to this company?": DeclarationLabel.PREVIOUSLY_APPLIED,
        "Are you bound by any agreement such as a non-compete?": DeclarationLabel.NON_COMPETE,
        "What is your favourite programming language?": None,
    }
    for label, want in cases.items():
        assert D.classify(norm(label), "") == want, label
    assert D.classify(norm("Please declare anything else we should know"), "") is D.AMBIGUOUS
    assert D.classify(norm("Have you been convicted of an offence or declared bankrupt?"), "") is D.AMBIGUOUS


@needs("jobscraper.apply.declarations")
def test_company_match_rules():
    m = importlib.import_module("jobscraper.apply.declarations").company_match
    assert m("DBS Bank Ltd", "DBS")
    assert m("Grab", "Grab Financial Group")
    assert m("Example Logistics Pte Ltd", "example logistics")
    assert not m("Example Logistics", "Sample Analytics")
    assert not m("Acme", "Apex Acme")


@needs("jobscraper.apply.resolve")
def test_declarations_answer_no_by_default_from_the_profile():
    for key, label, cls in [
        ("q1", "Are you a politically exposed person?", "pep"),
        ("q2", "Do you have any conflict of interest with an audit client?", "conflict_audit_independence"),
        ("q3", "Have you ever been declared bankrupt?", "bankruptcy"),
        ("q4", "Have you been subject to any regulatory or disciplinary action?", "regulatory_disciplinary"),
    ]:
        a = _one(_yn(key, label))
        assert _chosen(a) == ("No",), label
        assert a.tier is AnswerTier.DECLARATION and a.sensitive and a.source == f"declaration:{cls}", a


@needs("jobscraper.apply.resolve")
def test_prior_employment_is_deduced_from_experience_including_internships():
    q = _yn("q", "Have you previously worked for Example Logistics?")
    assert _chosen(_one(q, employer="Example Logistics")) == ("Yes",)
    assert _chosen(_one(q, employer="ELX", aliases=("Example Logistics",))) == ("Yes",)
    assert _chosen(_one(q, employer="Dataiku")) == ("No",)
    a = _one(q, employer="Sample Analytics Pte Ltd")      # the 2025 internship
    assert _chosen(a) == ("Yes",) and a.source == "declaration:prior_employment_at_company"


@needs("jobscraper.apply.resolve")
def test_holdings_relatives_and_previously_applied_answer_yes_when_true():
    assert _chosen(_one(_yn("q", "Do you hold shares in this company?"), employer="Shareco")) == ("Yes",)
    assert _chosen(_one(_yn("q", "Do you have relatives working at this company?"),
                        employer="Kinfolk")) == ("Yes",)
    q = _yn("q", "Have you previously applied to this company?")
    assert _chosen(_one(q, previously_applied=True)) == ("Yes",)
    assert _chosen(_one(q, previously_applied=False)) == ("No",)


@needs("jobscraper.apply.resolve")
def test_unlabelled_attestation_fails_closed_and_never_reaches_the_model():
    be = StubBackend([{"choice": 1, "evidence": "x"}] * 4)
    for label in ("Please declare any matters we should be aware of.",
                  "Have you been convicted of an offence or declared bankrupt?"):
        a = _one(_yn("q", label), backend=be)
        assert a.status is AnswerStatus.UNKNOWN and not a.fills, label
    a = _one(_yn("q", "Please declare any matters we should be aware of.", required=False), backend=be)
    assert a.status is AnswerStatus.BLANK_OPTIONAL
    assert be.calls == [], "attestations never go to the LLM"


@needs("jobscraper.apply.resolve")
def test_a_required_checkbox_is_never_ticked_on_a_false_statement():
    clear = _f("c1", "I confirm I am not a politically exposed person", FieldType.CHECKBOX)
    assert _one(clear).value == "true"
    false_claim = _f("c2", "I am a politically exposed person", FieldType.CHECKBOX)
    assert _one(false_claim).status is AnswerStatus.UNKNOWN


@needs("jobscraper.apply.resolve")
def test_health_questions_take_decline_or_fail():
    opts = ("Yes", "No", "I prefer not to say")
    a = _one(_f("h", "Do you have any medical condition we should know about?", FieldType.DROPDOWN, opts))
    assert _chosen(a) == ("I prefer not to say",)
    a = _one(_yn("h", "Do you have any medical condition we should know about?"))
    assert a.status is AnswerStatus.UNKNOWN
    a = _one(_yn("h", "Do you have any medical condition we should know about?", required=False))
    assert a.status is AnswerStatus.BLANK_OPTIONAL


# ================================================================== 3c. tiers 1, 2 and 5 (lane P)

@needs("jobscraper.apply.resolve")
def test_tier1_field_map_answers_from_the_profile():
    fields = [
        _f("first_name", "First Name", canonical=Canonical.FIRST_NAME),
        _f("email", "Email", FieldType.EMAIL, canonical=Canonical.EMAIL),
        _f("country", "Country", FieldType.DROPDOWN, ("France +33", "Singapore +65"),
           canonical=Canonical.PHONE_COUNTRY_CODE),
        _f("resume", "Resume/CV", FieldType.FILE, canonical=Canonical.RESUME),
        _f("4000563004", "Gender", FieldType.DROPDOWN,
           ("Male", "Female", "Non-Binary", "I don't wish to answer"), canonical=Canonical.EEO_GENDER),
    ]
    out = _resolve(fields)
    assert out["first_name"].value == "Alex" and out["first_name"].tier is AnswerTier.FIELD_MAP
    assert out["first_name"].confidence == 1.0 and out["first_name"].source == "field_map:first_name"
    assert out["email"].value == "alex.testcase@example.com"
    assert _chosen(out["country"]) == ("Singapore +65",)
    assert out["resume"].value == "C:/fixture/Alex_Testcase_Resume.pdf"
    assert _chosen(out["4000563004"]) == ("I don't wish to answer",), "decline maps to the decline option"


@needs("jobscraper.apply.resolve")
def test_tier2_profile_rules_map_onto_offered_options():
    out = _resolve([
        _yn("spons", "Would you require a visa sponsorship or visa transfer for this opportunity?"),
        _f("res", "What is your residency status?", FieldType.DROPDOWN,
           ("Singapore Citizen", "Permanent Resident", "Foreigner")),
        _f("sal", "What are your salary expectations?"),
    ])
    assert _chosen(out["spons"]) == ("No",) and out["spons"].tier is AnswerTier.PROFILE_RULE
    assert _chosen(out["res"]) == ("Singapore Citizen",) and out["res"].sensitive
    assert out["sal"].value == "5000"


@needs("jobscraper.apply.resolve")
def test_a_sensitive_question_with_no_matching_option_stops_without_the_model():
    be = StubBackend([{"choice": 0, "evidence": "Singapore"}] * 4)
    a = _one(_f("res", "What is your residency status?", FieldType.DROPDOWN, ("Option A", "Option B")),
             backend=be)
    assert a.status is AnswerStatus.UNKNOWN and be.calls == []


@needs("jobscraper.apply.resolve")
def test_tier5_text_with_an_invented_number_is_rejected_after_one_retry():
    bad = {"unknown": False, "text": "I led a team of 12 engineers building REST APIs in Python."}
    be = StubBackend([bad, bad])
    a = _one(_f("t", "Tell us about a project you are proud of.", FieldType.TEXTAREA), backend=be)
    assert a.status is AnswerStatus.UNGROUNDED and not a.fills
    assert len(be.calls) == 2, "one call plus exactly one retry"
    assert "PREVIOUS ANSWER WAS REJECTED BECAUSE" in be.calls[1]["user"]
    assert "12" in a.note


@needs("jobscraper.apply.resolve")
def test_tier5_text_with_an_invented_employer_is_rejected():
    bad = {"unknown": False, "text": "I built search features at Google using Python."}
    a = _one(_f("t", "Tell us about a project you are proud of.", FieldType.TEXTAREA),
             backend=StubBackend([bad, bad]))
    assert a.status is AnswerStatus.UNGROUNDED and "google" in a.note.lower()


@needs("jobscraper.apply.resolve")
def test_tier5_grounded_text_is_filled_and_recorded():
    good = {"unknown": False, "text": "I built REST APIs in Python for shipment tracking."}
    be = StubBackend([good])
    a = _one(_f("t", "Tell us about a project you are proud of.", FieldType.TEXTAREA), backend=be)
    assert a.fills and a.tier is AnswerTier.LLM and a.source == "llm" and a.confidence == 0.8
    assert a.model == "stub-model" and re.fullmatch(r"[0-9a-f]{16}", a.prompt_hash)
    prompt = be.calls[0]["system"] + be.calls[0]["user"]
    for secret in ("2002-03-14", "91234567", "alex.testcase@example.com", "000001", "1 Example Road"):
        assert secret not in prompt, f"sensitive value {secret!r} reached the model"


@needs("jobscraper.apply.resolve")
def test_tier5_choice_needs_two_agreeing_runs_and_a_verbatim_quote():
    q = _f("lang", "Which programming language do you use most?", FieldType.DROPDOWN, ("Python", "Rust"))
    be = StubBackend([{"choice": 0, "evidence": "REST APIs in Python"}] * 2)
    a = _one(q, backend=be)
    assert _chosen(a) == ("Python",) and a.confidence == 0.9
    assert [c["temperature"] for c in be.calls] == [0, 0.7] and {c["seed"] for c in be.calls} == {7}
    disagree = StubBackend([{"choice": 0, "evidence": "Python"}, {"choice": 1, "evidence": "Python"}])
    assert not _one(q, backend=disagree).fills
    invented = StubBackend([{"choice": 1, "evidence": "five years of Rust"}] * 2)
    assert not _one(q, backend=invented).fills


@needs("jobscraper.apply.resolve")
def test_model_unavailable_leaves_a_required_field_unknown_and_an_optional_one_blank():
    q = _f("t", "Tell us about a project you are proud of.", FieldType.TEXTAREA)
    a = _one(q, backend=StubBackend([BackendError("down")] * 3))
    assert a.status is AnswerStatus.UNKNOWN and "model unavailable" in a.note
    opt = _f("o", "Anything else you would like to share?", FieldType.TEXTAREA, required=False)
    assert _one(opt, backend=StubBackend([{"unknown": True, "text": ""}])).status is AnswerStatus.BLANK_OPTIONAL


# ================================================================== 3d. Greenhouse plan, detection (lane B)

class _Http:
    def __init__(self, payload=None, status=None):
        self.payload, self.status, self.urls = payload, status, []

    def _go(self, url):
        self.urls.append(url)
        if self.status:
            from jobscraper.scrape.net import FetchError, classify_status
            raise FetchError(classify_status(self.status), f"HTTP {self.status}", status=self.status)
        return self.payload

    def get_json(self, url, **_kw):
        return self._go(url)


def _ctx(http, board="dataiku", posting="6237419004"):
    return AttemptContext(
        attempt_id=1, job={"job_id": "j1", "provider": "greenhouse", "slug": board, "external_id": posting,
                           "url": f"https://job-boards.greenhouse.io/{board}/jobs/{posting}", "name": board},
        tenant=Tenant("greenhouse", "job-boards.greenhouse.io", board, posting_id=posting),
        dry_run=True, email="alex.testcase@example.com", resume_path="C:/fixture/r.pdf",
        log=lambda _l: None, screenshot=lambda _p, _s: "", deadline=1e18, http=http)


@needs("jobscraper.apply.ats")
def test_greenhouse_urls_give_the_tenant():
    gh = importlib.import_module("jobscraper.apply.ats").REGISTRY["greenhouse"]
    assert gh.name == "greenhouse" and gh.needs_account is False
    t = gh.match_url("https://job-boards.greenhouse.io/dataiku/jobs/6237419004")
    assert (t.board, t.posting_id, t.host) == ("dataiku", "6237419004", "job-boards.greenhouse.io")
    t = gh.match_url("https://boards.greenhouse.io/embed/job_app?for=vercel&token=6128387004")
    assert (t.board, t.posting_id) == ("vercel", "6128387004")
    assert gh.match_url("https://jobs.lever.co/example/abc") is None


@needs("jobscraper.apply.ats")
def test_greenhouse_plan_from_the_dataiku_schema():
    gh = importlib.import_module("jobscraper.apply.ats").REGISTRY["greenhouse"]
    http = _Http(_schema("dataiku"))
    plan = gh.plan_from_schema(_ctx(http))
    assert http.urls == ["https://boards-api.greenhouse.io/v1/boards/dataiku/jobs/6237419004?questions=true"]
    assert plan.source == "schema" and plan.ats == "greenhouse"
    f = plan.by_key()
    assert f["first_name"].canonical is Canonical.FIRST_NAME and f["first_name"].required
    assert f["resume"].type is FieldType.FILE and f["resume"].canonical is Canonical.RESUME
    assert f["resume_text"].alt_of == "resume" and f["cover_letter_text"].alt_of == "cover_letter"
    assert f["question_20424893004"].type is FieldType.DROPDOWN
    assert [o.label for o in f["question_20424893004"].options] == ["Yes", "No"]
    assert f["question_20424895004"].type is FieldType.TEXT and f["question_20424895004"].required
    assert f["candidate-location"].canonical is Canonical.LOCATION
    assert f["country"].canonical is Canonical.PHONE_COUNTRY_CODE
    g = f["4000563004"]
    assert g.section == "demographic" and g.required and len(g.options) == 4
    assert f["gdpr_processing_consent_given"].type is FieldType.CHECKBOX
    assert f["gdpr_processing_consent_given"].canonical is Canonical.CONSENT_PRIVACY
    assert f["gdpr_retention_consent_given"].canonical is Canonical.CONSENT_RETENTION


@needs("jobscraper.apply.ats")
def test_greenhouse_vercel_plan_has_no_consent_boxes_when_the_flags_are_off():
    gh = importlib.import_module("jobscraper.apply.ats").REGISTRY["greenhouse"]
    plan = gh.plan_from_schema(_ctx(_Http(_schema("vercel")), "vercel", "6128387004"))
    keys = set(plan.by_key())
    assert not any(k.startswith("gdpr_") for k in keys)
    assert "question_19316838004" in keys and plan.by_key()["question_19316841004"].canonical is Canonical.LINKEDIN


@needs("jobscraper.apply.ats")
def test_greenhouse_schema_404_is_posting_closed():
    gh = importlib.import_module("jobscraper.apply.ats").REGISTRY["greenhouse"]
    try:
        gh.plan_from_schema(_ctx(_Http(status=404)))
    except ApplyFailure as e:
        assert e.reason is ReasonCode.POSTING_CLOSED
    else:
        raise AssertionError("a 404 schema must end the attempt as posting_closed")


@needs("jobscraper.apply.detect")
def test_no_adapter_is_unsupported_ats():
    detect = importlib.import_module("jobscraper.apply.detect").detect
    try:
        detect({"job_id": "j", "provider": "somethingelse", "slug": "x",
                "url": "https://careers.example.com/jobs/1", "external_id": "1"})
    except ApplyFailure as e:
        assert e.reason is ReasonCode.UNSUPPORTED_ATS
    else:
        raise AssertionError("expected unsupported_ats")


# ================================================================== 3e. store guards (lane B)

def _store():
    from jobscraper.store import Store
    return Store(Path(tempfile.mkdtemp()) / "t.db")


def _job(st, cid, n, url=None):
    from jobscraper.models import RawJob
    raw = RawJob(f"x{n}", f"Engineer {n}", url or f"https://x.example/jobs/{n}", "Singapore")
    jid = raw.job_id(cid, "greenhouse")
    st.upsert_job(jid, cid, raw, 1, True)
    st.commit()
    return jid


_PATH_TO_SUBMIT = (S.PLANNING, S.OPENING, S.FILLING, S.SUBMITTING)


def _walk(st, aid, states):
    for s in states:
        st.set_attempt_state(aid, s)


@needs("jobscraper.store:Store.create_attempt")
def test_store_refuses_a_transition_the_table_does_not_allow():
    st = _store()
    cid = st.insert_company("x", "X", "https://x.example")
    aid = st.create_attempt(_job(st, cid, 1), cid, "auto", NOW)
    try:
        st.set_attempt_state(aid, S.SUBMITTED)
    except ValueError:
        pass
    else:
        raise AssertionError("queued -> submitted must raise ValueError")
    st.close()


@needs("jobscraper.store:Store.create_attempt")
def test_a_posting_can_succeed_only_once():
    st = _store()
    cid = st.insert_company("x", "X", "https://x.example")
    jid = _job(st, cid, 1)
    a1 = st.create_attempt(jid, cid, "auto", NOW)
    _walk(st, a1, _PATH_TO_SUBMIT + (S.SUBMITTED,))
    a2 = st.create_attempt(jid, cid, "auto", NOW)
    _walk(st, a2, _PATH_TO_SUBMIT)
    try:
        st.set_attempt_state(a2, S.SUBMITTED_UNCONFIRMED)
        st.commit()
    except (sqlite3.IntegrityError, ValueError):
        pass
    else:
        raise AssertionError("the unique index must refuse a second success for one job (NF-06)")
    st.close()


@needs("jobscraper.store:Store.apply_duplicate")
def test_duplicate_guard_covers_applied_twins_and_clicked_attempts():
    st = _store()
    c1 = st.insert_company("x", "X", "https://x.example")
    c2 = st.insert_company("y", "Y", "https://y.example")
    applied = _job(st, c1, 1, url="https://boards.example/jobs/77")
    twin = _job(st, c2, 2, url="https://boards.example/jobs/77/")
    clicked, fresh = _job(st, c1, 3), _job(st, c1, 4)
    st.set_application_status(applied, "applied")
    st.commit()
    assert (st.apply_duplicate(applied) or "").startswith("applied")
    assert "same posting as" in (st.apply_duplicate(twin) or "")
    aid = st.create_attempt(clicked, c1, "auto", NOW)
    _walk(st, aid, _PATH_TO_SUBMIT[:-1])
    st.mark_submit_clicked(aid, NOW)
    st.commit()
    assert st.apply_duplicate(clicked) == "already submitted by JobScraper"
    assert st.apply_duplicate(fresh) is None
    st.close()


@needs("jobscraper.store:Store.apply_counts")
def test_caps_count_only_clicked_attempts():
    st = _store()
    cid = st.insert_company("x", "X", "https://x.example")
    for n in range(3):
        aid = st.create_attempt(_job(st, cid, n), cid, "auto" if n < 2 else "dry_run", NOW)
        if n < 2:
            _walk(st, aid, _PATH_TO_SUBMIT[:-1])
            st.mark_submit_clicked(aid, NOW)
    st.commit()
    assert tuple(st.apply_counts(cid, "2026-11-01T16:00:00")) == (2, 2)   # SG midnight in UTC
    assert tuple(st.apply_counts(cid, "2026-11-02T16:00:00")) == (0, 0)
    st.close()


@needs("jobscraper.store:Store.reap_attempts")
def test_the_reaper_never_fails_a_clicked_attempt():
    st = _store()
    cid = st.insert_company("x", "X", "https://x.example")
    a1 = st.create_attempt(_job(st, cid, 1), cid, "auto", NOW)
    _walk(st, a1, (S.PLANNING, S.OPENING, S.FILLING))
    a2 = st.create_attempt(_job(st, cid, 2), cid, "auto", NOW)
    _walk(st, a2, _PATH_TO_SUBMIT[:-1])
    st.mark_submit_clicked(a2, NOW)
    st.set_attempt_state(a2, S.SUBMITTING)
    st.commit()
    st.reap_attempts(NOW)                        # design §13 form; §4.3 adds job_running (see plan)
    r1, r2 = st.attempt(a1), st.attempt(a2)
    assert (r1["state"], r1["reason_code"]) == ("failed", "cancelled")
    assert r2["state"] == "submitted_unconfirmed"
    st.close()


# ================================================================== 3f. page classifier on local pages (lane B)

def _classify_file(name: str) -> str | None:
    """classify() on a local fixture page in headless Edge; None if Edge can't start here."""
    from playwright.sync_api import sync_playwright
    C = importlib.import_module("jobscraper.apply.classify")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge", headless=True)
        except Exception as e:                   # no Edge on this machine: say so, don't fake a pass
            print(f"  note: Edge did not start ({type(e).__name__}); classifier check not run")
            return None
        try:
            page = browser.new_page()
            page.goto((GH / name).as_uri())
            page.wait_for_load_state("load")
            sig = C.classify(page)
            return getattr(sig, "value", sig)
        finally:
            browser.close()


@needs("jobscraper.apply.classify", "playwright")
def test_classifier_ignores_the_invisible_recaptcha_and_stops_on_a_visible_challenge():
    ok = _classify_file("form.html")
    if ok is None:
        return
    assert ok == "ok", "the invisible anchor and .grecaptcha-badge are on every Greenhouse board"
    assert _classify_file("form_challenge.html") == "captcha"
    assert _classify_file("closed.html") == "closed"
    assert _classify_file("bot_check.html") == "bot_challenge"


if _WAITING:
    print(f"[test_apply_contracts] {len(_WAITING)} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in _WAITING})))
