"""Q-121 WP-0: contract v7 pins (D-208, llm_first_fill_design.md §7.1, ADR-0011).

Verify: `python tests/run_tests.py -k apply_contracts_v7`. Pure checks on
`jobscraper.apply.contracts`; v7 is additive, so every older construction must still work.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerTier, FillPolicy, FillSource, ModelDecision, PageOutcome, QueuePause,
    ReasonCode, ResolveContext, REASON_TEXTS,
)


def test_contract_version_is_at_least_7():
    assert C.CONTRACT_VERSION >= 7


def test_fill_policy_values_and_the_default_context_stays_strict():
    assert [p.value for p in FillPolicy] == ["strict", "always"]
    assert ResolveContext(profile={}, employer_name="X").fill_policy is FillPolicy.STRICT


def test_old_constructions_still_work_and_the_new_fields_default_empty():
    a = Answer("f1", "Singapore", AnswerTier.PROFILE_RULE, "profile:contact.country", 0.95)
    assert a.assumed is False
    d = ModelDecision(field_key="f1", source=FillSource.UNKNOWN)
    assert d.assumed is False
    o = PageOutcome(step="my_information")
    assert o.assumed == () and o.fallback == () and o.standing_kept == ()


def test_new_reason_codes_have_plain_copy_that_formats_with_a_detail():
    for code in (ReasonCode.DOCUMENT_MISSING, ReasonCode.OWNER_FACT_MISSING):
        rt = REASON_TEXTS[code]
        assert rt.text and rt.hint, code
        assert "{detail}" in rt.text, code
        rendered = rt.text.format(detail="date of birth")
        assert "date of birth" in rendered and "{" not in rendered, code
        assert "nothing was sent" in rendered.lower(), code


def test_default_and_fallback_rule_ids_are_unique_non_empty_strings():
    for rules in (C.DEFAULT_RULES, C.FALLBACK_RULES):
        assert rules and all(isinstance(r, str) and r.strip() for r in rules)
        assert len(set(rules)) == len(rules)
    assert not set(C.DEFAULT_RULES) & set(C.FALLBACK_RULES)


def test_v6_names_survive_v7():
    assert QueuePause.OWNER.value == "owner"
    assert hasattr(C, "QUEUE_PAUSE_TEXTS") and hasattr(C, "RETURNS_ITEM")
