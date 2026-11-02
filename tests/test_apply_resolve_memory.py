"""WP-Q0 oracles for tier 3 reading `extra:` from the applicant profile (questions_design.md 6.1, 6.2;
ADR-0005; WP-Q2). Every case goes through the real resolver (`resolve.resolve_all`) with a profile that
carries the synthetic `extra` entries of tests/fixtures/apply/applicant_extra.sample.yaml.

Skip-clean until `resolve._extra_answer` exists (QD 6.2 names it; the tests never call it directly).
The rules file is tests/fixtures/apply/questions.sample.yaml (the P-lane fixture: a residency rule that is
sensitive, a notice-period rule), so these oracles do not depend on the researcher's real file.

ASSUMED (QD 6.2, 11): the notes `memory ambiguous: <k1>, <k2>` and `memory entry invalid: <key>` reach the
final Answer's `note`; they have their own tests (`..._note`) so the behaviour oracles stay independent
of where the engineer merges notes. No model is called except by a scripted stub that proves it is not.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    FIX, BackendError, StubBackend, chosen, field, needs, profile_with_extra, report_waiting,
    resolve_one, waiting_mark, yes_no,
)

from jobscraper.apply.contracts import AnswerStatus, AnswerTier, FieldType  # noqa: E402

_MARK = waiting_mark()
RULES = FIX / "questions.sample.yaml"
GATE = ("jobscraper.apply.resolve:_extra_answer",)


def _nomodel() -> StubBackend:
    """A model that would answer if asked: a call is a failure."""
    return StubBackend([{"unknown": False, "text": "MODEL ANSWER"}] * 4)


def _ask(f, prof=None, *, employer="Example Employer", aliases=(), backend=None, memory=None):
    be = backend or _nomodel()
    a = resolve_one(f, prof or profile_with_extra(), RULES, backend=be, employer=employer,
                    aliases=aliases, memory=memory)
    return a, be


def _memory(a) -> bool:
    return a.tier is AnswerTier.MEMORY and a.source.startswith("memory:extra.")


def _visa(options, kind=FieldType.DROPDOWN):
    return field("q", "What is your visa status?", kind, options)


VISA_OPTS = ("Singapore Citizen", "Permanent Resident", "Employment Pass")


# ================================================================== fixtures (run now)

def test_the_sample_extra_labels_match_no_tier2_rule_and_no_declaration_class():
    """So an oracle below can only be answered by tier 3: the sample labels are nobody else's."""
    from jobscraper.apply import declarations
    from jobscraper.apply.plan import norm_label
    rules = importlib_resolve().load_rules(RULES)
    for key, entry in profile_with_extra()["extra"].items():
        for label in entry["labels"]:
            assert label == norm_label(label), (key, label)
            best, _score = rules.select(label, None)
            assert not best, f"{key}: {label!r} is answered by tier-2 rule {[r.key for r in best]}"
            assert declarations.classify(label, "") is None, f"{key}: {label!r} is a declaration"


def importlib_resolve():
    import importlib
    return importlib.import_module("jobscraper.apply.resolve")


# ================================================================== fits per kind (QD 6.2 step 4)

@needs(*GATE)
def test_yes_no_fits_a_dropdown_a_checkbox_and_a_text_field():
    label = "Do you hold a valid driving licence?"
    a, be = _ask(yes_no("q", label))
    assert chosen(a) == ("Yes",) and _memory(a), a
    assert be.calls == []
    a, _ = _ask(field("q", label, FieldType.CHECKBOX))
    assert a.value == "true" and _memory(a), a
    a, _ = _ask(field("q", label, FieldType.TEXT))
    assert a.value == "Yes" and _memory(a), a


@needs(*GATE)
def test_a_false_yes_no_answers_no_but_never_unticks_a_required_checkbox():
    p = profile_with_extra()
    p["extra"]["has_driving_licence"]["value"] = False
    label = "Do you hold a valid driving licence?"
    a, _ = _ask(yes_no("q", label), p)
    assert chosen(a) == ("No",) and _memory(a), a
    a, _ = _ask(field("q", label, FieldType.CHECKBOX), p, backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "a required checkbox is not 'answered' by leaving it unticked (fit_bool)"


@needs(*GATE)
def test_choice_answers_with_the_one_offered_pick_on_a_dropdown_or_radio():
    for ftype in (FieldType.DROPDOWN, FieldType.RADIO):
        a, _ = _ask(_visa(VISA_OPTS, ftype))
        assert chosen(a) == ("Singapore Citizen",) and _memory(a), (ftype, a)
        assert a.option_labels == ("Singapore Citizen",)


@needs(*GATE)
def test_choice_needs_exactly_one_pick_among_the_offered_options():
    p = profile_with_extra()
    p["extra"]["visa_status"]["picks"] = ["singapore citizen", "permanent resident"]
    a, _ = _ask(_visa(VISA_OPTS), p, backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "two picks offered: no single answer"
    a, _ = _ask(_visa(("Employment Pass", "S Pass")), backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "no pick offered: no answer"
    assert not a.fills


@needs(*GATE)
def test_matching_is_by_equal_normalised_option_labels_never_by_substring():
    a, _ = _ask(_visa(("Singapore Citizen (SG)", "Permanent Resident", "Employment Pass")),
                backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "'singapore citizen (sg)' does not equal 'singapore citizen'"


@needs(*GATE)
def test_multi_answers_the_offered_picks_only_when_every_offered_option_is_known():
    f = field("q", "Which work arrangements suit you?", FieldType.MULTI_CHOICE, ("Hybrid", "On site", "Remote"))
    a, _ = _ask(f)
    assert _memory(a) and list(chosen(a)) == ["Hybrid", "On site"], a
    unseen = field("q", "Which work arrangements suit you?", FieldType.MULTI_CHOICE,
                   ("Hybrid", "On site", "Fully remote"))
    a, _ = _ask(unseen, backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "an offered option the owner never decided on: no answer"
    none_picked = field("q", "Which work arrangements suit you?", FieldType.MULTI_CHOICE, ("Remote",))
    a, _ = _ask(none_picked, backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "offered and known, but none of them picked: nothing to answer"


@needs(*GATE)
def test_text_date_and_number_fit_their_fields():
    a, _ = _ask(field("q", "What is your favourite programming language?", FieldType.TEXT))
    assert a.value == "Python" and _memory(a), a
    a, _ = _ask(field("q", "What is your favourite programming language?", FieldType.TEXTAREA))
    assert a.value == "Python" and _memory(a)
    a, _ = _ask(field("q", "When can you start?", FieldType.DATE))
    assert a.value == "2026-02-02" and _memory(a), a
    a, _ = _ask(field("q", "How many years of Python experience do you have?", FieldType.NUMBER))
    assert a.value == "3" and _memory(a), a
    a, _ = _ask(field("q", "How many years of Python experience do you have?", FieldType.TEXT))
    assert a.value == "3" and _memory(a), a


@needs(*GATE)
def test_a_kind_that_does_not_suit_the_field_type_gives_no_answer():
    be = StubBackend([BackendError("down")] * 3)
    a, _ = _ask(field("q", "What is your favourite programming language?", FieldType.DROPDOWN,
                      ("Rust", "Go")), backend=be)
    assert not _memory(a), "a text answer 'Python' is not any of the offered options"
    a, _ = _ask(field("q", "When can you start?", FieldType.CHECKBOX), backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a), "a date does not tick a box"


# ================================================================== source, rule_id, sensitive (QD 6.2 step 5)

@needs(*GATE)
def test_source_rule_id_confidence_and_sensitive_follow_the_entry():
    a, _ = _ask(yes_no("q", "Do you hold a valid driving licence?"))
    assert a.source == "memory:extra.has_driving_licence"
    assert a.rule_id == "extra.has_driving_licence"
    assert a.tier is AnswerTier.MEMORY and a.confidence == 0.95
    assert a.sensitive is False and a.status is AnswerStatus.FILLED
    s, be = _ask(field("q", "What is your mother tongue?", FieldType.TEXT))
    assert s.value == "Mandarin" and s.sensitive is True, "sensitive passes through from the entry"
    assert s.source == "memory:extra.mother_tongue"
    assert be.calls == []


# ================================================================== by_employer (QD 6.2 step 3)

@needs(*GATE)
def test_by_employer_beats_the_base_for_that_employer_only_and_an_alias_counts():
    shopee_opts = ("Citizen", "PR", "Others")
    f = _visa(shopee_opts)
    a, _ = _ask(f, employer="Shopee Pte Ltd")
    assert chosen(a) == ("Citizen",) and _memory(a), a
    assert a.rule_id == "extra.visa_status@shopee", "a scoped answer says so"
    assert a.source == "memory:extra.visa_status"
    a, _ = _ask(f, employer="SeaMoney Pte Ltd", aliases=("Shopee",))
    assert chosen(a) == ("Citizen",) and a.rule_id == "extra.visa_status@shopee", "an alias of the employer counts"
    # another employer is answered from the base entry, whose picks are the base option set
    a, _ = _ask(_visa(VISA_OPTS), employer="Grab Holdings")
    assert chosen(a) == ("Singapore Citizen",) and a.rule_id == "extra.visa_status", a
    # the override REPLACES the base for its employer: base picks do not apply there
    a, _ = _ask(_visa(VISA_OPTS), employer="Shopee Pte Ltd", backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a)


# ================================================================== what tier 3 must not answer

@needs(*GATE)
def test_an_employer_specific_declaration_label_is_never_answered_from_extra():
    p = profile_with_extra(relatives_check={
        "title": "Relatives", "description": "", "kind": "yes_no", "sensitive": False,
        "labels": ["do you have relatives working at the company"], "value": False})
    f = yes_no("q", "Do you have relatives working at the company?")
    a, be = _ask(f, p, employer="Kinfolk Pte Ltd")          # the sample profile lists Kinfolk as a relative's employer
    assert a.tier is AnswerTier.DECLARATION, a
    assert a.source.startswith("declaration:") and chosen(a) == ("Yes",), "tier 4 owns it, and it says Yes"
    assert be.calls == []
    a, _ = _ask(f, p, employer="Somebody Else Ltd")
    assert a.tier is AnswerTier.DECLARATION and not _memory(a)


@needs(*GATE)
def test_a_tier2_answer_beats_an_extra_entry_with_the_same_label():
    p = profile_with_extra(notice_clash={
        "title": "Notice", "description": "", "kind": "text", "sensitive": False,
        "labels": ["what is your notice period"], "value": "99"})
    a, _ = _ask(field("q", "What is your notice period?", FieldType.TEXT), p)
    assert a.tier is AnswerTier.PROFILE_RULE and a.value == "0", a


@needs(*GATE)
def test_extra_is_asked_before_the_answer_memory_table():
    seen = []

    def memory(label_norm, field_type, ats):
        seen.append(label_norm)
        return json.dumps("No")

    a, _ = _ask(yes_no("q", "Do you hold a valid driving licence?"), memory=memory)
    assert chosen(a) == ("Yes",) and a.source == "memory:extra.has_driving_licence"
    a, _ = _ask(yes_no("q", "Do you hold a boat licence?"), memory=memory)
    assert chosen(a) == ("No",) and a.source == "memory:do you hold a boat licence", \
        "an unmatched label still reaches the existing answer_memory lookup"


@needs(*GATE)
def test_a_sensitive_tier2_no_fit_stop_is_answered_by_a_matching_extra_entry():
    """QD 6.2 order change: the owner's own explicit answer is a fact they gave, so tier 3 is consulted
    before a tier-2 stop (fail-closed is kept for everything else)."""
    f = field("q", "What is your residency status?", FieldType.DROPDOWN, ("Option A", "Option B"))
    p = profile_with_extra(residency_form={
        "title": "Residency (this form)", "description": "", "kind": "choice", "sensitive": True,
        "labels": ["what is your residency status"], "value": None,
        "picks": ["option a"], "seen": ["option a", "option b"]})
    a, be = _ask(f, p)
    assert chosen(a) == ("Option A",) and _memory(a), a
    assert a.source == "memory:extra.residency_form" and a.sensitive is True
    assert be.calls == [], "still never the model"
    # without the entry, the same field still stops
    a, be = _ask(f, profile_with_extra())
    assert a.status is AnswerStatus.UNKNOWN and not a.fills and be.calls == []


@needs(*GATE)
def test_two_entries_with_the_same_label_give_no_answer():
    p = profile_with_extra()
    twin = copy.deepcopy(p["extra"]["visa_status"])
    twin["title"] = "Visa status again"
    p["extra"]["visa_again"] = twin
    a, _ = _ask(_visa(VISA_OPTS), p, backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a) and not a.fills, "ambiguous: the resolver does not guess which entry"


@needs(*GATE)
def test_a_malformed_entry_is_skipped_not_fatal():
    p = profile_with_extra()
    p["extra"]["has_driving_licence"]["value"] = "yes"           # yes_no wants a bool
    a, _ = _ask(yes_no("q", "Do you hold a valid driving licence?"), p,
                backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a) and a.status is AnswerStatus.UNKNOWN, a
    p = profile_with_extra()
    del p["extra"]["visa_status"]["picks"]                       # a hand edit dropped a field
    a, _ = _ask(_visa(VISA_OPTS), p, backend=StubBackend([BackendError("down")] * 3))
    assert not _memory(a)
    p = profile_with_extra()
    p["extra"]["favourite_language"] = "just a string"           # not even a mapping
    a, _ = _ask(field("q", "Do you hold a valid driving licence?", FieldType.TEXT), p)
    assert _memory(a), "one broken entry does not stop the others"


@needs(*GATE)
def test_ambiguous_label_note_names_both_keys():
    p = profile_with_extra()
    twin = copy.deepcopy(p["extra"]["visa_status"])
    p["extra"]["visa_again"] = twin
    f = field("q", "What is your visa status?", FieldType.DROPDOWN, VISA_OPTS)
    # a sensitive-stop field would hide the note behind tier 5; use the plain dropdown with the model down
    a, _ = _ask(f, p, backend=StubBackend([BackendError("down")] * 3))
    assert "memory ambiguous" in a.note and "visa_status" in a.note and "visa_again" in a.note, a.note


@needs(*GATE)
def test_malformed_entry_note_names_the_key():
    p = profile_with_extra()
    p["extra"]["has_driving_licence"]["value"] = "yes"
    a, _ = _ask(yes_no("q", "Do you hold a valid driving licence?"), p,
                backend=StubBackend([BackendError("down")] * 3))
    assert "memory entry invalid: has_driving_licence" in a.note, a.note


# ================================================================== rule_id on a final unknown (QD 6.2, last paragraph)

@needs(*GATE)
def test_a_final_unknown_carries_the_one_tier2_key_it_matched():
    """Capture reads `rule_id` to tell a profile gap from a question nobody has a rule for."""
    a, _ = _ask(field("q", "What is your residency status?", FieldType.DROPDOWN, ("Option A", "Option B")))
    assert a.status is AnswerStatus.UNKNOWN
    assert a.rule_id == "singapore_status.residency_status", "sensitive no-fit stop"
    p = profile_with_extra()
    p["availability"]["notice_period_days"] = None
    a, _ = _ask(field("q", "What is your notice period?", FieldType.TEXT), p,
                backend=StubBackend([BackendError("down")] * 3))
    assert a.status is AnswerStatus.UNKNOWN and a.rule_id == "availability.notice_period_days", \
        "a non-sensitive rule that found no value, then the model was down"
    a, _ = _ask(field("q", "Describe your ideal weekend in detail.", FieldType.TEXTAREA),
                backend=StubBackend([BackendError("down")] * 3))
    assert a.status is AnswerStatus.UNKNOWN and a.rule_id == "", "no tier-2 key matched: nothing to name"


report_waiting("test_apply_resolve_memory", _MARK)
