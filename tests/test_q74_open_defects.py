"""Q-74 re-review defect pins (docs/reviews/Q-74.md, "Re-review (fixes)": R1, R2; R3 is a matrix).

`test_q74_r1_*` and `test_q74_r2_*` are EXPECTED TO FAIL until the next fix round: they pin the
behaviour the re-review asks for. The control tests (`*_control_*`) pass today and keep the failing
pins honest. Synthetic values only; scripted model; no network.

R1 (over-blocking, flag on): a protected word that is generic, or also present in the non-protected
corpus (resume, JD, employer name), must not block an otherwise grounded answer.
R2 (form wording): a protected value must be caught under the wording the form uses
("Singapore Permanent Resident" for residency `pr`, "Buddhism" for religion `buddhist`, "Woman" for
gender `female`), not only under the stored slug.
R3: `is_local_config(b) == is_local(build(b))` across a matrix (passes today).
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_q74_model_sees_sensitive as base  # noqa: E402  (helpers only; its tests are not re-exported)
from questions_support import REAL_RULES, StubBackend, ctx_for, field, yes_no  # noqa: E402

from jobscraper import backends  # noqa: E402
from jobscraper.apply import resolve as R  # noqa: E402
from jobscraper.apply.contracts import AnswerStatus, FieldType  # noqa: E402


def _profile(*, ns=None, disability=None, holdings=None, residency=None, religion=None, gender=None) -> dict:
    p = base.s_profile()
    if ns:
        p["singapore_status"]["ns_status"] = ns
    if disability:
        p["us_self_id"]["disability_status"] = disability
    if holdings:
        p["declarations"]["holdings"] = holdings
    if residency:
        p["singapore_status"]["residency_status"] = residency
    if religion:
        p["singapore_status"]["religion"] = religion
    if gender:
        p["identity"]["gender"] = gender
    return p


def _text(text, *, on, p, employer="Example Employer", label="Tell us about yourself"):
    be = StubBackend([{"text": text}] * 2)
    ctx = dataclasses.replace(ctx_for(p, employer=employer), model_sees_sensitive=on)
    f = field("t", label, FieldType.TEXTAREA)
    out = R.resolve_all([f], ctx, backend=be, rules=R.load_rules(REAL_RULES), memory=lambda *_a: None)
    return out["t"], be


# ------------------------------------------------------------------ R1

def test_q74_r1_control_the_same_text_fills_with_the_flag_off():
    a, _ = _text("I completed my degree in Python and built REST APIs.", on=False, p=_profile(ns="completed"))
    assert a.status is AnswerStatus.FILLED, a.note


def test_q74_r1_generic_word_completed_does_not_block_a_text_answer():
    """ns_status 'completed' is protected; an ordinary sentence containing the word must still fill."""
    a, be = _text("I completed my degree in Python and built REST APIs.", on=True, p=_profile(ns="completed"))
    assert a.status is AnswerStatus.FILLED and a.sensitive is False, (a.status, a.note)
    assert len(be.calls) == 1


def test_q74_r1_a_yes_option_is_not_blocked_by_a_protected_yes():
    """us_self_id.disability_status 'yes' makes 'yes' protected; a Yes pick grounded in the resume must fill."""
    f = yes_no("r", "Do you have experience building REST APIs?")
    a, _be, _ = base.resolve_one(f, on=True, p=_profile(disability="yes"),
                                 replies=[{"choice": 0, "evidence": "Built REST APIs in Python"}] * 2)
    assert a.status is AnswerStatus.FILLED and a.option_labels == ("Yes",) and a.sensitive is False, \
        (a.status, a.note)


def test_q74_r1_employer_in_holdings_is_not_blocked_when_it_is_in_the_plain_corpus():
    """declarations.holdings holds 'Shareco Ltd'; the employer name is in the non-protected corpus."""
    a, be = _text("I would like to join Shareco Ltd and build REST APIs.", on=True,
                  p=_profile(holdings=["Shareco Ltd"]), employer="Shareco Ltd")
    assert a.status is AnswerStatus.FILLED and a.sensitive is False, (a.status, a.note)
    assert len(be.calls) == 1


# ------------------------------------------------------------------ R2

R2_LABEL = "Please select the option that applies to you for our internal headcount record"
R2_EVIDENCE = "right to work and needs no visa sponsorship"


def _pick(options, p):
    f = field("a", R2_LABEL, FieldType.DROPDOWN, options)
    a, be, _ = base.resolve_one(f, on=True, p=p, replies=[{"choice": 0, "evidence": R2_EVIDENCE}] * 2)
    return a, be


def test_q74_r2_control_a_non_protected_option_with_the_same_evidence_fills():
    a, be = _pick(("Other", "Singapore Permanent Resident"), _profile(residency="pr"))
    assert be.calls, "the tier-5 path ran (no rule caught the label)"
    assert a.status is AnswerStatus.FILLED, (a.status, a.note)


def test_q74_r2_residency_pr_is_caught_under_the_form_wording():
    a, be = _pick(("Singapore Permanent Resident", "Other"), _profile(residency="pr"))
    assert be.calls
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is True and a.value is None, (a.status, a.value)


def test_q74_r2_religion_is_caught_under_the_form_wording():
    a, be = _pick(("Buddhism", "Other"), _profile(religion="buddhist"))
    assert be.calls
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is True and a.value is None, (a.status, a.value)


def test_q74_r2_gender_is_caught_under_the_form_wording():
    a, be = _pick(("Woman", "Man"), _profile(gender="female"))
    assert be.calls
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is True and a.value is None, (a.status, a.value)


# ------------------------------------------------------------------ R3

def test_q74_r3_is_local_config_equals_is_local_of_build_across_configs():
    budgets = [
        {}, {"ollama_url": "http://localhost:11434"}, {"ollama_url": "http://ollama:11434"},
        {"ollama_model": "gpt-oss:120b-cloud"}, {"backend": "off"}, {"enable_llm": False},
        {"ollama_url": "http://[::1]:11434/", "ollama_model": "qwen3:14b"},
    ]
    envs = [base.CLEAN,
            dict(JOBSCRAPER_BACKEND=None, JOBSCRAPER_OLLAMA_URL="http://ollama:11434"),
            dict(JOBSCRAPER_BACKEND=None, JOBSCRAPER_OLLAMA_URL=base.LOCAL),
            dict(JOBSCRAPER_BACKEND="off", JOBSCRAPER_OLLAMA_URL=None)]
    for e in envs:
        with base.env(**e):
            for b in budgets:
                assert backends.is_local_config(b) is backends.is_local(backends.build(b)), (e, b)
