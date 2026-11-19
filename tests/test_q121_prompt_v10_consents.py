"""Q-121 C: the always-answer prompt must NAME the two new consent classes (D-229 C1-C3; design
llm_first_fill_design.md section 18.1; architect request B). RED UNTIL `eng/Q-121-consents` lands
its prompt change: the schema enum already follows FIELD_CLASS_CHOICES (pinned in
test_always_a1_prompt), but a model that is never told what `consent_sharing:group`,
`consent_sharing:third_party` and `consent_checks` mean will file those boxes under
`consent_privacy` (agreed by default) or `ordinary`. Do not weaken: merge order is the fix.
Pure text pins on SYSTEM_ALWAYS; no model.
Verify: python tests/run_tests.py -k q121_prompt_v10_consents
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_support  # noqa: E402,F401  (puts src on sys.path)


def _rules():
    from jobscraper.apply import always
    flat = re.sub(r"\s+", " ", always.SYSTEM_ALWAYS)
    return always, flat


def test_rule_12_names_the_three_new_class_strings():
    always, flat = _rules()
    i = flat.index("12. class, given before value")
    rule12 = flat[i:]
    for s in ("consent_sharing:group", "consent_sharing:third_party", "consent_checks"):
        assert s in rule12, s


def test_the_prompt_version_moved_with_the_new_wording():
    always, _ = _rules()
    assert always.PROMPT_VERSION != "always:v2"
