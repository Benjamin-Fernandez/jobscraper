"""Q-121 Amendment A1 contract v8 pins (llm_first_fill_design §17.2, §17.3, §17.6, §17.7 pin 30;
apply/contracts.py).

The expected lists are WRITTEN OUT here from the design, not derived from the code under test:
a renamed class, a reordered enum, an `ordinary` that drifts to the front (review C6: a decoder
leans to the first enum entry, so the common value must not sit there), a changed owner-facing
sentence all go red. No model, no network.
Verify: python tests/run_tests.py -k always_a1_contract
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_support  # noqa: E402,F401  (puts src on sys.path)

EXPECTED_CLASSES = ("consent_privacy", "consent_retention", "marketing", "certification",
                    "acknowledgement", "declaration", "work_right", "sponsorship", "owner_fact",
                    "self_id", "other_person", "ordinary")

DECLARATION_WHICH = ("pep", "conflict_audit_independence", "shareholding_in_company",
                     "relatives_at_company", "criminal_record", "bankruptcy", "regulatory_disciplinary",
                     "non_compete", "health", "prior_employment_at_company",
                     "current_employee_at_company", "previously_applied", "government_employment",
                     "other")
OWNER_FACT = ("date_of_birth", "age", "national_id", "passport", "bank", "grade", "salary_current",
              "salary_expected", "address", "postal_code", "phone", "other_id")
SELF_ID = ("gender", "race", "religion", "marital", "disability", "veteran", "other")

EXPECTED_CHOICES = (
    ("consent_privacy", "consent_retention", "marketing", "certification", "acknowledgement")
    + tuple(f"declaration:{w}" for w in DECLARATION_WHICH)
    + ("work_right", "sponsorship")
    + tuple(f"owner_fact:{w}" for w in OWNER_FACT)
    + tuple(f"self_id:{w}" for w in SELF_ID)
    + ("other_person", "ordinary"))


def _c():
    from jobscraper.apply import contracts
    return contracts


def test_a1_contract_version_is_at_least_8():
    assert _c().CONTRACT_VERSION >= 8


def test_a1_field_class_members_in_order_and_ordinary_is_last():
    C = _c()
    assert tuple(m.value for m in C.FieldClass) == EXPECTED_CLASSES
    assert list(C.FieldClass)[-1] is C.FieldClass.ORDINARY
    assert list(C.FieldClass)[0] is not C.FieldClass.ORDINARY


def test_a1_which_lists_are_exactly_the_designed_ones():
    C = _c()
    assert tuple(C.OWNER_FACT_WHICH) == OWNER_FACT
    assert "other_id" in C.OWNER_FACT_WHICH                              # review C9
    assert tuple(C.SELF_ID_WHICH) == SELF_ID
    assert tuple(C.FIELD_CLASS_WHICH[C.FieldClass.DECLARATION]) == DECLARATION_WHICH
    assert tuple(C.FIELD_CLASS_WHICH[C.FieldClass.OWNER_FACT]) == OWNER_FACT
    assert tuple(C.FIELD_CLASS_WHICH[C.FieldClass.SELF_ID]) == SELF_ID
    # only these three classes take a `which`
    assert set(C.FIELD_CLASS_WHICH) == {C.FieldClass.DECLARATION, C.FieldClass.OWNER_FACT,
                                        C.FieldClass.SELF_ID}


def test_a1_declaration_which_excludes_disability_and_nda_willingness():
    """Disability is self-ID; NDA willingness is an ordinary question (D9, review C4)."""
    w = _c().FIELD_CLASS_WHICH[_c().FieldClass.DECLARATION]
    assert "disability" not in w and "nda_willingness" not in w
    assert "other" in w
    labels = {d.value for d in _c().DeclarationLabel}
    assert set(w) - {"other"} <= labels
    assert labels - set(w) == {"disability", "nda_willingness"}


def test_a1_field_class_choices_are_the_42_strings_in_order_ordinary_last():
    C = _c()
    assert len(EXPECTED_CHOICES) == 42
    assert tuple(C.FIELD_CLASS_CHOICES) == EXPECTED_CHOICES
    assert len(set(C.FIELD_CLASS_CHOICES)) == 42
    assert C.FIELD_CLASS_SEP == ":"


def test_a1_ordinary_is_never_the_first_schema_enum_entry_and_always_the_last():
    ch = _c().FIELD_CLASS_CHOICES
    assert ch[-1] == "ordinary" and ch[0] != "ordinary" and ch.index("ordinary") == len(ch) - 1


def test_a1_model_decision_has_the_class_and_which_with_silent_defaults():
    C = _c()
    d = C.ModelDecision("k", C.FillSource.UNKNOWN)
    assert d.klass is None and d.which == ""
    d2 = C.ModelDecision("k", C.FillSource.UNKNOWN, klass=C.FieldClass.DECLARATION, which="pep")
    assert d2.klass is C.FieldClass.DECLARATION and d2.which == "pep"


def test_a1_consent_refused_reason_code_and_texts_are_the_designed_sentences():
    C = _c()
    assert C.ReasonCode.CONSENT_REFUSED.value == "consent_refused"
    t = C.REASON_TEXTS[C.ReasonCode.CONSENT_REFUSED]
    assert t.text == ("This form needs you to agree to {detail}, and your profile says no. "
                      "Nothing was sent.")
    assert t.hint == ("To agree, change it in Profile → Consents, then click Try again. "
                      "Otherwise apply by hand or skip this role.")
    assert set(C.REASON_TEXTS) == set(C.ReasonCode)


def test_a1_owner_fact_missing_text_is_unchanged_because_the_web_parses_it():
    C = _c()
    t = C.REASON_TEXTS[C.ReasonCode.OWNER_FACT_MISSING]
    assert t.text == ("This form asks for your {detail}, which isn't in your profile or resume. "
                      "Nothing was sent.")
    # contract v9 (Q-127): the hint no longer points at the retired Questions page; the `text`
    # above is what attempts.js parses and is unchanged.
    assert t.hint == "Add it in Profile → Your details, then click Try again."


def test_a1_consent_refused_details_keys_and_texts():
    C = _c()
    assert dict(C.CONSENT_REFUSED_DETAILS) == {
        "consents.privacy_consent": "the processing of your personal data",
        "consents.data_retention_consent": "keeping your details on file for future roles",
        "consents.certify_true": "a statement that your answers are true and complete",
        "consents.talent_pool_opt_in": "receiving marketing messages",
    }
    t = C.REASON_TEXTS[C.ReasonCode.CONSENT_REFUSED]
    for key, detail in C.CONSENT_REFUSED_DETAILS.items():
        s = t.text.format(detail=detail)
        assert "{" not in s and detail in s, key


def test_a1_content_failure_markers_and_text():
    C = _c()
    assert tuple(C.CONTENT_FAILURE_MARKERS) == ("no usable answers", "would be guesses", "last resort")
    assert C.CONTENT_FAILURE_TEXT.text == (
        "The local AI couldn't answer this form without guessing, so JobScraper stopped. "
        "Nothing was sent.")
    assert C.CONTENT_FAILURE_TEXT.hint == (
        "Apply by hand, or skip this role. If this happens on most forms, check the AI with "
        "“python -m jobscraper doctor”.")
    assert "{detail}" not in C.CONTENT_FAILURE_TEXT.text            # shown instead of REASON_TEXTS[...]


def test_a1_the_content_failure_markers_are_the_ones_always_py_writes():
    """Review F10: apply_flow checked its own copy at import time; the one copy lives in contracts."""
    from jobscraper.apply import always as AL
    d = AL.content_failure_detail(_c().CONTENT_FAILURE_MARKERS[0], "on one")
    assert d.startswith(_c().CONTENT_FAILURE_MARKERS), d
    assert tuple(AL.CONTENT_FAILURE_MARKERS) == tuple(_c().CONTENT_FAILURE_MARKERS)
