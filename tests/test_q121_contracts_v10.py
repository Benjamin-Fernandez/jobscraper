"""Q-121 C: contract v10 pins (D-229 C1-C4; docs/architecture/llm_first_fill_design.md section 18;
apply/contracts.py). Three engineer lanes build on this contract at once: these pins stop it drifting.
Additive over v9: two consent classes, three consent switches, one fixed reason sentence for every way
a form field can be left unanswered.

No model, no network, no store, no process. Made-up names only. Expected values are WRITTEN OUT
here, not derived from the code under test, except where a test says it checks a table against itself.
Verify: python tests/run_tests.py -k q121_contracts_v10
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_support  # noqa: E402,F401  (puts src on sys.path)

NEW_CLASSES = ("consent_sharing", "consent_checks")
NEW_KEYS = ("consents.group_sharing", "consents.third_party_sharing", "consents.background_checks")
V9_FIELD_KEYS = ("id", "step", "label", "type", "required", "value_text", "basis_text", "assumed",
                 "reason_text", "status", "remembered_text", "can_remember", "refusal", "options")
V9_CONSENT_REFUSED_TEXT = ("This form needs you to agree to {detail}, and your profile says no. "
                           "Nothing was sent.")
NAMES = ("Example", "Northwind")          # made-up employer names: case-sensitive ("For example" is fine)
LINKY = ("http", "www.", "@")


def _clean(part: str, where) -> None:
    for w in NAMES:
        assert w not in part, (where, w)
    for w in LINKY:
        assert w not in part.lower(), (where, w)


def _c():
    from jobscraper.apply import contracts
    return contracts


# ---- version -----------------------------------------------------------------------------------

def test_the_contract_is_at_least_v10():
    assert _c().CONTRACT_VERSION >= 10


# ---- classes -----------------------------------------------------------------------------------

def test_the_two_new_classes_sit_with_the_consent_classes_and_ordinary_is_still_last():
    C = _c()
    names = [m.value for m in C.FieldClass]
    assert names[-1] == "ordinary" and names.count("ordinary") == 1
    assert set(NEW_CLASSES) <= set(names)
    # between the privacy / retention consents and marketing: with the consents, before the rest
    assert names[:4] == ["consent_privacy", "consent_retention", "consent_sharing", "consent_checks"]
    assert names.index("marketing") > names.index("consent_checks")
    assert list(C.FieldClass)[-1] is C.FieldClass.ORDINARY
    assert C.FIELD_CLASS_CHOICES[-1] == "ordinary" and C.FIELD_CLASS_CHOICES[0] != "ordinary"


def test_the_choices_have_no_duplicate_and_hold_every_new_string():
    C = _c()
    ch = C.FIELD_CLASS_CHOICES
    assert len(ch) == len(set(ch))
    assert "consent_checks" in ch                       # a class with no `which` is a bare string
    assert "consent_sharing" not in ch                  # the sharing class is only ever named with a which
    for w in C.CONSENT_SHARING_WHICH:
        assert f"consent_sharing:{w}" in ch, w
    assert tuple(C.CONSENT_SHARING_WHICH) == ("group", "third_party")
    assert tuple(C.FIELD_CLASS_WHICH[C.FieldClass.CONSENT_SHARING]) == ("group", "third_party")
    assert C.FieldClass.CONSENT_CHECKS not in C.FIELD_CLASS_WHICH
    # the three strings sit together, right after consent_retention, in this order
    i = ch.index("consent_retention")
    assert ch[i + 1:i + 4] == ("consent_sharing:group", "consent_sharing:third_party", "consent_checks")
    for s in ch:                                         # every string parses back to a class
        assert C.field_class_of(s) is not None, s


def test_both_new_classes_are_refused_for_remember_under_every_answer_source():
    C = _c()
    for cls in NEW_CLASSES:
        assert C.FieldClass(cls) in C.REMEMBER_REFUSED_CLASSES, cls
    strings = ["consent_checks", "consent_sharing", "consent_sharing:group", "consent_sharing:third_party"]
    sources = [s.value for s in C.AnswerSource] + [f"{s.value}:x" for s in C.AnswerSource] + [
        "", "unknown", "not-a-source", "memory:extra:something", "llm", "composed", "resume", "job",
        "assumption", "fallback", "none"]
    for fc in strings:
        for src in sources:
            assert C.follows_your_details(src, fc) is True, (src, fc)
    # S2 L1: a certification or an acknowledgement is never remembered either, from any source
    for fc in ("certification", "acknowledgement"):
        assert C.FieldClass(fc) in C.REMEMBER_REFUSED_CLASSES, fc
        for src in sources:
            assert C.follows_your_details(src, fc) is True, (src, fc)
    # the control: an ordinary class from a plain source can still be remembered
    assert C.follows_your_details("llm", "ordinary") is False


# ---- switches ----------------------------------------------------------------------------------

def test_exactly_three_switches_with_the_designed_keys_default_off():
    C = _c()
    assert len(C.CONSENT_SWITCHES) == 3
    assert tuple(s.key for s in C.CONSENT_SWITCHES) == NEW_KEYS
    assert C.CONSENT_GROUP_SHARING_KEY == "consents.group_sharing"
    assert C.CONSENT_THIRD_PARTY_SHARING_KEY == "consents.third_party_sharing"
    assert C.CONSENT_BACKGROUND_CHECKS_KEY == "consents.background_checks"
    assert set(C.CONSENTS_DEFAULT_OFF) == set(NEW_KEYS)
    assert len(set(s.key for s in C.CONSENT_SWITCHES)) == 3


def test_every_switch_has_a_sentence_case_title_and_helper_with_no_employer_or_link():
    C = _c()
    for s in C.CONSENT_SWITCHES:
        for part in (s.title, s.help):
            assert part.strip() == part and part, s.key
            assert part[0].isupper(), (s.key, part)
            assert part.rstrip(".") == part.rstrip(".").strip()
            _clean(part, s.key)
            assert "{" not in part and "}" not in part
            assert "\n" not in part
        assert not s.title.endswith(".")                 # a label, not a sentence
        assert s.help.endswith(".")                      # one helper line
        # sentence case: no Title Case Words in the middle of the title
        assert not re.search(r"\s[A-Z][a-z]+\s[A-Z][a-z]+", s.title), s.title
        assert "\u2014" not in part and "\u2013" not in part   # no dashes in owner copy


def test_every_switch_names_the_class_the_filler_decides_for_its_box():
    C = _c()
    by_key = {s.key: s.field_class for s in C.CONSENT_SWITCHES}
    assert by_key == {
        "consents.group_sharing": "consent_sharing:group",
        "consents.third_party_sharing": "consent_sharing:third_party",
        "consents.background_checks": "consent_checks"}
    for fc in by_key.values():
        assert fc in C.FIELD_CLASS_CHOICES


def test_each_new_class_string_maps_to_exactly_one_key_and_keys_are_not_shared():
    C = _c()
    m = C.CONSENT_KEY_BY_CLASS
    assert m["consent_sharing:group"] == "consents.group_sharing"
    assert m["consent_sharing:third_party"] == "consents.third_party_sharing"
    assert m["consent_checks"] == "consents.background_checks"
    for w in C.CONSENT_SHARING_WHICH:
        assert f"consent_sharing:{w}" in m, w
    assert "consent_sharing" not in m                     # the bare string is never a choice
    for k in NEW_KEYS:
        assert sum(1 for v in m.values() if v == k) == 1, k
    # the v8 / v9 strings keep the keys they had
    assert m["consent_privacy"] == "consents.privacy_consent"
    assert m["consent_retention"] == "consents.data_retention_consent"
    assert m["certification"] == "consents.certify_true"
    assert m["marketing"] == "consents.talent_pool_opt_in"
    assert set(m) <= set(C.FIELD_CLASS_CHOICES)


def test_consent_refused_details_cover_every_consent_key_the_contract_names():
    C = _c()
    named = set(C.CONSENT_KEY_BY_CLASS.values()) | set(C.CONSENTS_DEFAULT_OFF) | {
        s.key for s in C.CONSENT_SWITCHES}
    assert named <= set(C.CONSENT_REFUSED_DETAILS), named - set(C.CONSENT_REFUSED_DETAILS)
    assert set(NEW_KEYS) <= set(C.CONSENT_REFUSED_DETAILS)
    seen = set()
    for key, detail in C.CONSENT_REFUSED_DETAILS.items():
        assert detail and detail == detail.strip() and detail[0].islower(), key  # reads mid-sentence
        assert not detail.endswith("."), key
        _clean(detail, key)
        assert "{" not in detail
        assert detail not in seen, ("two keys share one detail", key)
        seen.add(detail)
        chip = f"Needs your agreement: {detail}"          # the Applications chip
        assert re.fullmatch(r"Needs your agreement: [a-z][^.{}]*[a-z]", chip), chip


def test_the_consent_refused_text_is_byte_identical_to_v9_and_the_hint_names_the_new_screen():
    C = _c()
    t = C.REASON_TEXTS[C.ReasonCode.CONSENT_REFUSED]
    assert t.text == V9_CONSENT_REFUSED_TEXT
    assert "Profile \u2192 Your details \u2192 Consents and declarations" in t.hint
    assert "Profile \u2192 Consents," not in t.hint       # the retired wording
    assert t.hint.startswith("To agree, switch it on in ")
    # attempts.js parses the sentence with this pattern: every detail, new ones too, comes back whole
    rx = re.compile(r"^This form needs you to agree to (.+?), and your profile says no", re.I)
    for key, detail in C.CONSENT_REFUSED_DETAILS.items():
        m = rx.match(t.text.format(detail=detail))
        assert m and m.group(1).strip() == detail, key


def test_the_third_party_detail_equals_always_share_detail_when_always_names_it():
    # the contract comment says consents.third_party_sharing equals always.SHARE_DETAIL / SHARE_CONSENT_KEY
    C = _c()
    from jobscraper.apply import always
    if hasattr(always, "SHARE_CONSENT_KEY"):
        assert always.SHARE_CONSENT_KEY == C.CONSENT_THIRD_PARTY_SHARING_KEY
    if hasattr(always, "SHARE_DETAIL"):
        assert always.SHARE_DETAIL == C.CONSENT_REFUSED_DETAILS[C.CONSENT_THIRD_PARTY_SHARING_KEY]


# ---- answers route keys ------------------------------------------------------------------------

def test_the_answers_field_keys_keep_v9_in_order_and_end_with_the_four_reason_keys():
    C = _c()
    k = C.ANSWERS_FIELD_KEYS
    assert k[:len(V9_FIELD_KEYS)] == V9_FIELD_KEYS
    assert k[len(V9_FIELD_KEYS):] == ("reason", "reason_hint", "reason_code", "reason_key")
    assert len(k) == len(V9_FIELD_KEYS) + 4 and len(set(k)) == len(k)
    for name in k:                                       # no path, URL, log or password in a key name
        assert not any(w in name for w in ("path", "url", "log", "password", "secret")), name
    assert C.ANSWERS_ATTEMPT_KEYS == ("id", "kind", "state", "finished_at", "trial", "entries_note")


# ---- reasons: the tables -----------------------------------------------------------------------

def _all_pairs():
    """The finite set of (text, hint) a note can ever produce, built from the tables."""
    C = _c()
    details = list(C.CONSENT_REFUSED_DETAILS.values()) + [C.NOT_ANSWERED_ANY_DETAIL]
    hints = set(C.NOT_ANSWERED_ROW_HINTS)
    out = set()
    for code, r in C.NOT_ANSWERED_REASONS.items():
        texts = [r.text.format(detail=d) for d in details] if "{detail}" in r.text else [r.text]
        for t in texts:
            for h in ([r.hint] if r.hint else sorted(hints)):
                out.add((t, h))
    return out


def test_every_code_has_a_reason_and_every_marker_a_known_code():
    C = _c()
    codes = set(C.NotAnsweredReason)
    assert set(C.NOT_ANSWERED_REASONS) == codes
    assert {c for _, c in C.NOT_ANSWERED_MARKERS} <= codes
    assert C.NotAnsweredReason.UNKNOWN in codes and C.NotAnsweredReason.UNKNOWN.value == "unknown"
    assert len(codes) == 18
    assert {C.NotAnsweredReason.COMPOSE_NEEDED, C.NotAnsweredReason.NO_ANSWER} <= codes
    # every code except the two the row's `required` picks has a marker
    assert C.NOT_ANSWERED_WITHOUT_MARKER == {C.NotAnsweredReason.NO_ANSWER, C.NotAnsweredReason.UNKNOWN}
    assert {c for _, c in C.NOT_ANSWERED_MARKERS} == codes - set(C.NOT_ANSWERED_WITHOUT_MARKER)


def test_the_reason_sentences_are_fixed_plain_and_hold_no_slot_but_detail():
    C = _c()
    for code, r in C.NOT_ANSWERED_REASONS.items():
        for part in (r.text, r.hint):
            if not part:
                continue
            assert part[0].isupper() and part.endswith("."), (code, part)
            _clean(part, code)
            slots = set(re.findall(r"\{[^{}]*\}", part))
            assert slots <= {"{detail}"}, (code, slots)
            assert part.count("{") == part.count("}") == len(re.findall(r"\{detail\}", part))
            assert not re.search(r"[A-Za-z]:\\|\\\\|\w/\w", part), (code, part)
        assert ("{detail}" in r.text) == (code is C.NotAnsweredReason.CONSENT_NOT_AGREED), code
    for h in (C.NOT_ANSWERED_HINT_REMEMBER, C.NOT_ANSWERED_HINT_DETAILS, C.NOT_ANSWERED_HINT_OPTIONAL):
        assert h and h[0].isupper() and h.endswith(".") and "{" not in h


def test_the_consent_not_agreed_hint_points_at_the_consents_screen():
    C = _c()
    r = C.NOT_ANSWERED_REASONS[C.NotAnsweredReason.CONSENT_NOT_AGREED]
    assert "Profile \u2192 Your details \u2192 Consents and declarations" in r.hint
    assert r.text == "You haven't agreed to {detail}."


def test_the_note_the_filler_writes_matches_its_own_marker():
    C = _c()
    assert C.CONSENT_NOT_AGREED_NOTE.format(key="consents.group_sharing") == \
        "not agreed: consents.group_sharing"
    for key in NEW_KEYS:
        code, text, hint = C.not_answered_reason(C.CONSENT_NOT_AGREED_NOTE.format(key=key))
        assert code is C.NotAnsweredReason.CONSENT_NOT_AGREED, key
        assert text == f"You haven't agreed to {C.CONSENT_REFUSED_DETAILS[key]}."


# ---- reasons: not_answered_reason is total ------------------------------------------------------

def _variants(marker: str):
    C = _c()
    yield marker
    yield marker.upper()
    yield marker.title()
    yield f"{marker} and then some trailing text, 42 chars of it."
    yield f"leading words {marker}"
    yield C.NOT_ANSWERED_SITE_PREFIX + marker
    yield (C.NOT_ANSWERED_SITE_PREFIX + marker).upper()
    yield C.NOT_ANSWERED_SITE_PREFIX.title() + marker + " trailing"
    yield f"  {marker}\n\t{marker}  "


def test_every_marker_returns_the_code_the_table_says_and_that_codes_fixed_text_and_hint():
    C = _c()
    for marker, code in C.NOT_ANSWERED_MARKERS:
        probe = marker + "consents.group_sharing" if marker.endswith(": ") else marker
        for v in _variants(probe):
            got_code, text, hint = C.not_answered_reason(v, field_class="ordinary", required=True)
            assert got_code is code, (marker, v, got_code)
            entry = C.NOT_ANSWERED_REASONS[code]
            if "{detail}" in entry.text:
                detail = (C.CONSENT_REFUSED_DETAILS["consents.group_sharing"] if "consents.group" in probe
                          else C.NOT_ANSWERED_ANY_DETAIL)      # the pre-v10 marker names no key
                assert text == entry.text.format(detail=detail), (marker, v)
            else:
                assert text == entry.text, (marker, v)
            assert hint == (entry.hint or C.NOT_ANSWERED_HINT_REMEMBER), (marker, v)


def test_a_marker_that_ends_in_a_space_still_matches_a_real_note_and_none_is_shadowed():
    """Every marker, on its own (trailing space trimmed as a stored note would be), either resolves
    to its own code or is the 'not agreed: ' marker, whose real notes always carry a key after it.
    A marker that resolves to ANOTHER code is shadowed by an earlier marker and can never fire."""
    C = _c()
    for marker, code in C.NOT_ANSWERED_MARKERS:
        if marker.endswith(" "):
            got = C.not_answered_reason(marker + "consents.background_checks")[0]
        else:
            got = C.not_answered_reason(marker)[0]
        assert got is code, (marker, got, code)


def test_an_empty_none_like_or_unknown_note_returns_the_neutral_default():
    C = _c()
    default = C.NOT_ANSWERED_REASONS[C.NotAnsweredReason.UNKNOWN]
    assert default.text == "It was left empty."
    assert C.NOT_ANSWERED_REASONS[C.NotAnsweredReason.NO_ANSWER].text ==         "JobScraper had no answer for this required question."
    for note in ("", "   ", "\n\t", None, 0, False, [], "zzz nothing matches this", "x" * 5000,
                 C.NOT_ANSWERED_SITE_PREFIX, C.NOT_ANSWERED_SITE_PREFIX + "nothing known",
                 "not agreed:"):
        # a REQUIRED row nothing explains is NO_ANSWER; an optional one stays UNKNOWN
        code, text, hint = C.not_answered_reason(note, required=True)
        assert code is C.NotAnsweredReason.NO_ANSWER, repr(note)
        assert text == "JobScraper had no answer for this required question.", repr(note)
        assert hint == C.NOT_ANSWERED_HINT_REMEMBER, repr(note)
        code, text, hint = C.not_answered_reason(note, required=False)
        assert code is C.NotAnsweredReason.UNKNOWN, repr(note)
        assert text == default.text, repr(note)
        assert hint == C.NOT_ANSWERED_HINT_OPTIONAL, repr(note)
    assert C.not_answered_reason("zzz", required=False)[2] == C.NOT_ANSWERED_HINT_OPTIONAL
    assert C.not_answered_reason("zzz", required=True, field_class="consent_checks")[2] == \
        C.NOT_ANSWERED_HINT_DETAILS


def test_the_hint_depends_only_on_required_and_class_when_the_table_leaves_it_open():
    C = _c()
    open_codes = [c for c, r in C.NOT_ANSWERED_REASONS.items() if not r.hint]
    assert open_codes                                      # the design has such codes
    markers = {c: m for m, c in reversed(C.NOT_ANSWERED_MARKERS)}
    for code in open_codes:
        m = markers.get(code, "zzz")
        assert C.not_answered_reason(m, required=False)[2] == C.NOT_ANSWERED_HINT_OPTIONAL, code
        assert C.not_answered_reason(m, required=True, field_class="ordinary")[2] == \
            C.NOT_ANSWERED_HINT_REMEMBER, code
        for fc in ("consent_checks", "consent_sharing:group", "declaration:pep", "work_right",
                   "owner_fact:passport", "self_id:gender"):
            assert C.not_answered_reason(m, required=True, field_class=fc)[2] == \
                C.NOT_ANSWERED_HINT_DETAILS, (code, fc)
    # a fixed hint never moves with the row
    for code in set(C.NotAnsweredReason) - set(open_codes):
        m = markers.get(code, "zzz") if code is not C.NotAnsweredReason.CONSENT_NOT_AGREED else "not agreed: x"
        base = C.not_answered_reason(m, required=True)[2]
        assert C.not_answered_reason(m, required=False)[2] == base, code
        assert C.not_answered_reason(m, required=True, field_class="consent_checks")[2] == base, code


def test_the_consent_detail_comes_from_the_note_key_then_the_class_then_the_generic_phrase():
    C = _c()
    D = C.CONSENT_REFUSED_DETAILS
    n = lambda *a, **k: C.not_answered_reason(*a, **k)[1]      # noqa: E731
    assert n("not agreed: consents.group_sharing") == f"You haven't agreed to {D['consents.group_sharing']}."
    assert n("Not Agreed: CONSENTS.BACKGROUND_CHECKS") == \
        f"You haven't agreed to {D['consents.background_checks']}."
    assert n("not agreed: ???", field_class="consent_checks") == \
        f"You haven't agreed to {D['consents.background_checks']}."
    assert n("not agreed: ???", field_class="consent_sharing:third_party") == \
        f"You haven't agreed to {D['consents.third_party_sharing']}."
    assert n("not agreed: ???", field_class="ordinary") == \
        f"You haven't agreed to {C.NOT_ANSWERED_ANY_DETAIL}."
    assert n("not agreed: ???") == f"You haven't agreed to {C.NOT_ANSWERED_ANY_DETAIL}."
    # the pre-v10 note keeps working (an older row in the database)
    assert C.not_answered_reason("your profile says no to this")[0] is C.NotAnsweredReason.CONSENT_NOT_AGREED


# ---- reasons: the property that matters --------------------------------------------------------

HOSTILE = [
    "Please describe in detail why you believe ZEBRACORP is the right employer for your career growth",
    "ZEBRACORP Pte Ltd",
    "Zebracorp's regional hiring team (Singapore) asks: how many years of experience do you hold?",
    "C:\\Users\\Someone\\Documents\\resume_ZEBRACORP.pdf",
    "\\\\fileserver\\share\\ZEBRACORP\\cv.docx",
    "/home/someone/.config/zebracorp/secret.txt",
    "https://careers.zebracorp.example/apply?token=ZEBRATOKEN&id=7",
    "see http://zebracorp.example/privacy for ZEBRAWORDS",
    "someone.private@zebramail.example",
    "reach me at ZEBRAWORDS <someone@zebramail.example>",
    "the model said: \"ZEBRAWORDS are my honest answer\" and stopped",
    "model quote: 'I am a citizen of ZEBRALAND'",
    "line one ZEBRAWORDS\nline two ZEBRAWORDS\r\nline three",
    "\n\n\n",
    "tab\tseparated\tZEBRAWORDS",
    "{",
    "}",
    "{detail}",
    "{{detail}}",
    "{0}",
    "{key}",
    "{detail.__class__}",
    "{detail!r:>99}",
    "%s %d %(detail)s ZEBRAWORDS",
    "%(detail)s",
    "{0.__class__.__mro__}",
    "{detail:^20}",
    "$HOME ${PATH} `ZEBRAWORDS` $(ZEBRAWORDS)",
    "<script>alert('ZEBRAWORDS')</script>",
    "'; DROP TABLE apply_answers; -- ZEBRAWORDS",
    "ZEBRAWORDS " * 400,
    "Ünïcödé ZEBRAWORDS ß İ ǅ ﬁ ΣΑΣ",
    "\u202eZEBRAWORDS\u200b\u0000",
    "not agreed: ZEBRAWORDS {detail}",
    "not agreed: {detail} ZEBRAWORDS",
    "left empty for the site's validation: ZEBRAWORDS {detail} C:\\temp\\x https://zebra.example",
    "left empty for the site's validation: the check did not agree: 'ZEBRAWORDS'",
    "reverted ZEBRAWORDS to C:\\Users\\x",
    "surplus entry \"ZEBRAWORDS\" {0}",
    "no option is your ZEBRAWORDS at https://zebra.example/q?a={detail}",
]
LEAK_TOKENS = ("ZEBRA", "someone.private", "Someone\\", "zebramail", "fileserver", "DROP TABLE", "script", "ZEBRATOKEN")


def _check_one_output(C, allowed, note, fc, required):
    code, text, hint = C.not_answered_reason(note, field_class=fc, required=required)
    where = (note[:60], fc, required)
    assert isinstance(code, C.NotAnsweredReason), where
    assert (text, hint) in allowed, where
    for out in (text, hint):
        assert "{" not in out and "}" not in out, (where, out)
        assert "http" not in out.lower(), (where, out)
        assert not re.search(r"[A-Za-z]:\\|\\|\w/\w|\n|\r|\t", out), (where, out)
        low = out.lower()
        for tok in LEAK_TOKENS:
            assert tok.lower() not in low, (where, tok)
    return code, text, hint


def test_there_are_forty_hostile_notes():
    assert len(HOSTILE) >= 40


def test_whatever_the_note_holds_only_a_fixed_sentence_pair_comes_back():
    C = _c()
    allowed = _all_pairs()
    assert len(allowed) > len(C.NotAnsweredReason)
    classes = ("", "ordinary", "consent_checks", "consent_sharing:group", "consent_sharing:third_party",
               "declaration:pep", "garbage:{detail}", "ZEBRAWORDS {0}")
    n = 0
    for note in HOSTILE:
        for fc in classes:
            for req in (True, False):
                _check_one_output(C, allowed, note, fc, req)
                n += 1
    assert n >= 40 * len(classes) * 2


def test_a_hostile_text_around_a_real_marker_still_returns_only_the_fixed_pair():
    C = _c()
    allowed = _all_pairs()
    hostile_bits = [h for h in HOSTILE if len(h) < 300][:12]
    for marker, code in C.NOT_ANSWERED_MARKERS:
        for h in hostile_bits:
            for note in (f"{h} {marker} {h}", f"{marker}{h}", f"{C.NOT_ANSWERED_SITE_PREFIX}{h} {marker}"):
                got, text, hint = _check_one_output(C, allowed, note, "consent_checks", True)
                # a hostile word may itself hold an earlier marker: then that code wins, never a new one
                assert got in set(c for _, c in C.NOT_ANSWERED_MARKERS) | set(C.NOT_ANSWERED_WITHOUT_MARKER)


def test_the_only_slot_value_ever_inserted_is_a_consent_detail_or_the_generic_phrase():
    C = _c()
    allowed_details = set(C.CONSENT_REFUSED_DETAILS.values()) | {C.NOT_ANSWERED_ANY_DETAIL}
    entry = C.NOT_ANSWERED_REASONS[C.NotAnsweredReason.CONSENT_NOT_AGREED].text
    head, tail = entry.split("{detail}")
    for note in HOSTILE + ["not agreed: " + h for h in HOSTILE] + ["not agreed: consents.group_sharing " + h for h in HOSTILE]:
        for fc in ("", "consent_checks", "garbage", "{detail}"):
            code, text, _ = C.not_answered_reason(note, field_class=fc)
            if code is C.NotAnsweredReason.CONSENT_NOT_AGREED:
                assert text.startswith(head) and text.endswith(tail), text
                assert text[len(head):len(text) - len(tail)] in allowed_details, text
            else:
                assert text == C.NOT_ANSWERED_REASONS[code].text


def test_a_note_cannot_pick_an_arbitrary_key_or_class_to_widen_the_slot():
    C = _c()
    code, text, _ = C.not_answered_reason("not agreed: consents.nonexistent ZEBRAWORDS",
                                          field_class="not_a_class")
    assert code is C.NotAnsweredReason.CONSENT_NOT_AGREED
    assert text == f"You haven't agreed to {C.NOT_ANSWERED_ANY_DETAIL}."


# ---- the reason pair travels with the new class strings ---------------------------------------

def test_the_new_class_strings_all_resolve_a_hint_without_error():
    C = _c()
    for fc in C.FIELD_CLASS_CHOICES:
        for req in (True, False):
            code, text, hint = C.not_answered_reason("surplus entry", field_class=fc, required=req)
            assert text and hint, (fc, req)
