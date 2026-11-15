"""Q-127 Release 1 contract v9 pins (docs/architecture/q127_profile_questions_design.md B.2, B.5 table
"Contract v9 as built"; apply/contracts.py). No model, no network, no store.

The expected texts and sets are WRITTEN OUT from the design, not derived from the code under test.
Release 2 names (topics, TopicStatus, TOPIC_MIN_COUNT, TOPIC_KINDS) must NOT exist yet.
Verify: python tests/run_tests.py -k q127_contracts
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_support  # noqa: E402,F401  (puts src on sys.path)


def _c():
    from jobscraper.apply import contracts
    return contracts


# ---- the version and the absence of Release 2 -----------------------------------------------

def test_the_contract_is_at_least_v9():
    assert _c().CONTRACT_VERSION >= 9


def test_no_release_2_name_exists_in_the_contract_yet():
    C = _c()
    for name in ("TopicStatus", "TOPIC_MIN_COUNT", "TOPIC_KINDS", "TopicsConfig"):
        assert not hasattr(C, name), f"{name} is Release 2 (schema v10), not part of contract v9"


# ---- basis words (B.2b table) -----------------------------------------------------------------

# (source, status, assumed, reason, form_label) -> the words, from the design table.
BASIS_CASES = [
    ("profile:identity.first_name", "filled", False, "", "First name", "From your details: First name"),
    ("field_map:first_name", "filled", False, "", "First name", "From your details: First name"),
    ("profile", "filled", False, "", "", "From your details"),                       # strict "profile" with no path
    ("memory:extra.work_mode", "filled", False, "", "", "Your saved answer"),
    ("memory", "filled", False, "", "", "Your saved answer"),
    ("standing:years_experience", "filled", False, "", "", "Worked out from your details"),
    ("default:no_nda", "filled", False, "", "", "Your standing answer"),
    ("declaration", "filled", False, "", "", "Your standing answer"),
    ("resume", "filled", False, "", "", "From your resume"),
    ("job", "filled", False, "", "", "From the job posting"),
    ("composed", "filled", False, "", "", "Written for this application"),
    ("field_map:resume", "filled", False, "", "", "Your resume file"),
    ("field_map:email", "filled", False, "", "", "Your application email"),
    ("llm", "filled", False, "", "", "Written by the local AI from your details"),
    ("mygreenhouse", "prefilled", False, "", "", "Kept from the site"),
    ("workday_last_application", "prefilled", False, "", "", "Kept from the site"),
    ("site_default", "prefilled", False, "", "", "Kept from the site"),
    ("resume_import", "prefilled", False, "", "", "Kept from the site"),
    ("keep", "prefilled", False, "", "", "Kept from the site"),
    ("assumption", "filled", True, "no preference stated", "", "Assumed: no preference stated"),
    ("fallback:F2", "filled", True, "the first option", "", "Assumed: the first option"),
    ("assumption", "filled", True, "", "", "Assumed: nothing in your details or resume covered it"),
    ("fallback:F3", "filled", True, "   ", "", "Assumed: nothing in your details or resume covered it"),
    ("profile:availability", "filled", True, "failed the basis check", "", "Assumed: failed the basis check"),
    ("llm", "unknown", False, "", "", "Not answered"),
    ("profile:x", "ungrounded", False, "", "", "Not answered"),
]


def test_basis_text_gives_the_designed_words_for_every_source_row():
    C = _c()
    for source, status, assumed, reason, label, want in BASIS_CASES:
        got = C.basis_text(source, status=status, assumed=assumed, reason=reason, form_label=label)
        assert got == want, (source, status, assumed, got, want)


def test_every_answer_source_has_basis_words_for_a_filled_row():
    C = _c()
    for src in C.AnswerSource:
        words = C.basis_text(src.value, status="filled", assumed=src in (C.AnswerSource.ASSUMPTION,
                                                                          C.AnswerSource.FALLBACK),
                             form_label="First name")
        assert words.strip(), f"AnswerSource.{src.name} has no basis words"


def test_a_source_the_table_does_not_name_has_no_basis_line():
    assert _c().basis_text("not_a_source:x") == ""


def test_no_basis_text_names_a_company_or_carries_a_company_slot():
    C = _c()
    texts = list(C.BASIS_TEXTS.values()) + list(C.FIELD_MAP_BASIS.values()) + [
        C.BASIS_FROM_DETAILS, C.BASIS_FROM_DETAILS_BARE, C.BASIS_ASSUMED, C.BASIS_ASSUMED_NO_REASON,
        C.BASIS_NOT_ANSWERED]
    for t in texts:
        low = t.lower()
        assert "employer" not in low and "company" not in low and "{employer}" not in low, t
        assert not set(t.replace("{label}", "").replace("{reason}", "")) & {"{", "}"}, t   # only the two slots
    # the only slots are the details-form title and the stored reason
    assert "{label}" in C.BASIS_FROM_DETAILS and "{reason}" in C.BASIS_ASSUMED


# ---- remember refusals (H3) -------------------------------------------------------------------

def test_the_refusal_codes_are_the_route_codes():
    C = _c()
    assert {r.value for r in C.RememberRefusal} == {"follows_your_details", "shared_answer", "too_general"}
    assert set(C.REMEMBER_REFUSAL_TEXTS) == set(C.RememberRefusal)
    assert C.REMEMBER_REFUSAL_TEXTS[C.RememberRefusal.FOLLOWS_YOUR_DETAILS] == \
        "This answer follows your details. Change it in Your details."
    assert C.REMEMBER_REFUSAL_TEXTS[C.RememberRefusal.SHARED_ANSWER].startswith(
        "This question shares a saved answer with other questions.")
    assert "{label}" in C.REMEMBER_REFUSAL_TEXTS[C.RememberRefusal.TOO_GENERAL]


def test_the_refused_sets_are_exactly_the_h3_lists():
    C = _c()
    assert {s.value for s in C.REMEMBER_REFUSED_SOURCES} == {
        "profile", "field_map", "standing", "default", "declaration"}
    assert {k.value for k in C.REMEMBER_REFUSED_CLASSES} == {
        "declaration", "consent_privacy", "consent_retention", "marketing", "work_right",
        "sponsorship", "self_id", "owner_fact"}


def test_every_protected_source_refuses_a_remember():
    C = _c()
    for source in ("profile:identity.first_name", "profile", "field_map:email", "field_map:resume",
                   "standing:work_rights_sg", "default:no_nda", "declaration"):
        assert C.follows_your_details(source), source
        assert C.follows_your_details(source, ""), source


def test_every_protected_class_refuses_a_remember_whatever_the_source():
    C = _c()
    classes = ["declaration:pep", "declaration:criminal_record", "declaration:other", "declaration",
               "consent_privacy", "consent_retention", "marketing", "work_right", "sponsorship",
               "self_id:gender", "self_id:disability", "self_id:other", "owner_fact:date_of_birth",
               "owner_fact:passport", "owner_fact:other_id"]
    for cls in classes:
        for source in ("assumption", "llm", "resume", "fallback:F2", "memory:extra.x", ""):
            assert C.follows_your_details(source, cls), (source, cls)


def test_an_ordinary_model_answer_may_be_remembered():
    C = _c()
    for source, cls in [("assumption", ""), ("assumption", "ordinary"), ("llm", "ordinary"),
                        ("resume", "ordinary"), ("job", "ordinary"), ("fallback:F2", "ordinary"),
                        ("llm", "certification"), ("llm", "acknowledgement"), ("llm", "other_person"),
                        ("memory:extra.work_mode", "ordinary"), ("composed", ""), ("mygreenhouse", "")]:
        assert not C.follows_your_details(source, cls), (source, cls)


def test_a_source_with_no_class_and_an_unknown_class_string_are_not_refused_by_the_class_rule():
    C = _c()
    assert not C.follows_your_details("assumption", "not_a_class:x")
    assert not C.follows_your_details("", "")


def test_field_class_of_reads_the_head_of_the_stored_string():
    C = _c()
    assert C.field_class_of("declaration:pep") is C.FieldClass.DECLARATION
    assert C.field_class_of("owner_fact:date_of_birth") is C.FieldClass.OWNER_FACT
    assert C.field_class_of("ordinary") is C.FieldClass.ORDINARY
    assert C.field_class_of("") is None and C.field_class_of(None) is None
    assert C.field_class_of("bogus:pep") is None


def test_every_class_choice_the_filler_can_write_round_trips_through_field_class_of():
    C = _c()
    for choice in C.FIELD_CLASS_CHOICES:
        assert C.field_class_of(choice) is not None, choice


# ---- scope of a remembered answer -------------------------------------------------------------

def test_the_scope_names_and_texts():
    C = _c()
    assert {s.value for s in C.RememberScope} == {"employer", "every"}
    assert C.EXTRA_EMPLOYER_FIELD == "employer"
    assert C.REMEMBER_SCOPE_TEXTS[C.RememberScope.EVERY] == "Every application"
    assert C.REMEMBER_SCOPE_TEXTS[C.RememberScope.EMPLOYER].format(employer="Example Co") == "Only Example Co"


def test_an_unscoped_entry_applies_to_every_employer():
    C = _c()
    for entry in ({"value": "x"}, {"value": "x", "employer": ""}, {"value": "x", "employer": None}):
        assert C.extra_entry_applies(entry, "Example Co")
        assert C.extra_entry_applies(entry, "Northwind", ["Acme Trading"])
        assert C.extra_entry_applies(entry, "")


def test_a_scoped_entry_applies_to_its_employer_and_to_no_other():
    C = _c()
    entry = {"value": "x", "employer": "Example Co"}
    assert C.extra_entry_applies(entry, "Example Co")
    assert not C.extra_entry_applies(entry, "Northwind")
    assert not C.extra_entry_applies(entry, "Acme Trading", ["Northwind"])


def test_the_employer_comparison_ignores_case_and_spacing_only():
    C = _c()
    entry = {"employer": "Example  Co"}
    assert C.extra_entry_applies(entry, "  example co ")
    assert C.extra_entry_applies(entry, "EXAMPLE CO")
    assert not C.extra_entry_applies(entry, "Example Co Ltd")      # a longer name is another employer
    assert not C.extra_entry_applies(entry, "Example")
    assert not C.extra_entry_applies(entry, "ExampleCo")


def test_a_scoped_entry_applies_through_an_alias_of_the_employer():
    C = _c()
    entry = {"employer": "Example Co"}
    assert C.extra_entry_applies(entry, "Example Co Singapore", ["Example Co", "Example Group"])
    assert C.extra_entry_applies(entry, "Example Co Singapore", ("EXAMPLE co",))
    assert not C.extra_entry_applies(entry, "Example Co Singapore", ["Example Group"])


def test_a_scoped_entry_never_applies_when_the_attempt_has_no_employer_name():
    C = _c()
    assert not C.extra_entry_applies({"employer": "Example Co"}, "")
    assert not C.extra_entry_applies({"employer": "Example Co"}, "", ["", ""])


# ---- what was sent route shape ---------------------------------------------------------------

def test_the_answers_route_keys_and_statuses():
    C = _c()
    assert C.ANSWERS_ATTEMPT_KEYS == ("id", "kind", "state", "finished_at", "trial", "entries_note")
    assert C.ANSWERS_FIELD_KEYS == (
        "id", "step", "label", "type", "required", "value_text", "basis_text", "assumed",
        "reason_text", "status", "remembered_text", "can_remember", "refusal", "options")
    assert {s.value for s in C.SentFieldStatus} == {"sent", "not_answered", "not_sent"}
    for k in C.ANSWERS_ATTEMPT_KEYS + C.ANSWERS_FIELD_KEYS:      # no path, URL, log or password
        assert not any(w in k for w in ("path", "url", "log", "password", "secret")), k


# ---- retired questions, labels, no-field facts -----------------------------------------------

def test_the_questions_retired_code_and_text():
    C = _c()
    assert C.QUESTIONS_RETIRED == "retired"
    assert C.QUESTIONS_RETIRED_TEXT == ("This page is out of date. Reload it, then answer from the "
                                        "application's What was filled.")


def test_the_fill_policy_labels_show_strict_as_stop_when_unsure():
    C = _c()
    assert C.FILL_POLICY_LABELS == {C.FillPolicy.ALWAYS: "Always answer",
                                    C.FillPolicy.STRICT: "Stop when unsure"}
    assert set(C.FILL_POLICY_LABELS) == set(C.FillPolicy)


def test_the_no_field_facts_are_the_four_fixed_titles():
    C = _c()
    assert C.NO_FIELD_FACTS == {
        "passport": "passport number", "bank": "bank account details",
        "national_id": "full NRIC or national ID number", "other_id": "driving licence or other ID number"}
    assert C.NO_FIELD_FACT_TITLES == frozenset(C.NO_FIELD_FACTS.values())
    assert set(C.NO_FIELD_FACTS) <= set(C.FIELD_CLASS_WHICH[C.FieldClass.OWNER_FACT])
    # the five owner facts that DO have a field are not in the no-field list
    for which in ("date_of_birth", "grade", "salary_expected", "address", "postal_code", "phone"):
        assert which not in C.NO_FIELD_FACTS


def test_the_no_field_stop_text_and_hint():
    C = _c()
    assert C.OWNER_FACT_NO_FIELD_HINT == "Your details have no place for it yet. Apply by hand, or skip this role."
    assert C.OWNER_FACT_NO_FIELD_TEXT.hint == C.OWNER_FACT_NO_FIELD_HINT
    shown = C.OWNER_FACT_NO_FIELD_TEXT.text.format(detail=C.NO_FIELD_FACTS["passport"])
    assert shown == ("This form asks for your passport number, which your details can't hold. "
                     "Nothing was sent.")


def test_the_reworded_hints_no_longer_point_at_the_retired_questions_page():
    C = _c()
    hints = {
        C.ReasonCode.UNANSWERABLE_REQUIRED: "Open What was filled for this application to answer it for next "
                                            "time, then click Try again.",
        C.ReasonCode.OWNER_FACT_MISSING: "Add it in Profile → Your details, then click Try again.",
        C.ReasonCode.DOCUMENT_MISSING: "Add it in Profile → Your details → Files, then try again.",
    }
    for code, hint in hints.items():
        assert C.REASON_TEXTS[code].hint == hint, code
    for code, rt in C.REASON_TEXTS.items():
        assert "Questions" not in rt.hint, (code, rt.hint)
    # the text of the owner-fact stop is still what attempts.js parses
    assert C.REASON_TEXTS[C.ReasonCode.OWNER_FACT_MISSING].text == (
        "This form asks for your {detail}, which isn't in your profile or resume. Nothing was sent.")


def test_an_answer_carries_a_field_class_that_defaults_to_empty():
    C = _c()
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(C.Answer)}
    assert "field_class" in fields and fields["field_class"].default == ""
