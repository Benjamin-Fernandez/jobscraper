"""Q-121 C: contract v10 (completed), `not_answered_view` pins: the closed `reason_key`, the
row-aware hint (`can_remember`), the strict question-reason table, and the hostile-note property
over text, hint AND key. Companion of test_q121_contracts_v10.py (shares its hostile notes).
No model, no network, no store, no process. Made-up names only.
Verify: python tests/run_tests.py -k q121_contracts_v10
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_support  # noqa: E402,F401  (puts src on sys.path)
from test_q121_contracts_v10 import HOSTILE, LEAK_TOKENS, _all_pairs  # noqa: E402

PATHY = ("/", "\\", " ", ":", "http", "{", "}", "\n", "\t", "..", "@")


def _c():
    from jobscraper.apply import contracts
    return contracts


def _view(note="", **kw):
    return _c().not_answered_view(note, **kw)


def _qreasons():
    C = _c()
    return [r.value for r in C.QuestionReason] + ["", "zzz", "ZEBRAWORDS {detail}", None, [], 7, object()]


def _marker_for(C, code):
    return next((m for m, c in C.NOT_ANSWERED_MARKERS if c is code), "")


def _probe(marker):
    return marker + "consents.group_sharing" if marker.endswith(": ") else marker


# ---- the view and the three-value function agree ------------------------------------------------

def test_the_view_has_four_fields_and_the_reason_function_agrees_with_it_on_every_input():
    C = _c()
    r = C.NOT_ANSWERED_REASONS[C.NotAnsweredReason.SURPLUS_ENTRY]
    v = _view("surplus entry", required=True)
    assert (v.code, v.text, v.hint, v.key) == (C.NotAnsweredReason.SURPLUS_ENTRY, r.text, r.hint, "")
    n = 0
    for note in HOSTILE + ["", None, "not agreed: consents.group_sharing", "compose needed: the tailor writes this"]:
        for fc in ("", "ordinary", "consent_checks", "garbage:{detail}"):
            for req in (True, False):
                for cr in (True, False):
                    for qr in ("", "no_rule", "compose_needed", "zzz"):
                        v = C.not_answered_view(note, field_class=fc, required=req, can_remember=cr,
                                                question_reason=qr)
                        assert C.not_answered_reason(note, field_class=fc, required=req, can_remember=cr,
                                                     question_reason=qr) == (v.code, v.text, v.hint)
                        n += 1
    assert n >= 40 * 4 * 2 * 2 * 4


# ---- the key is closed -------------------------------------------------------------------------

def test_a_consent_key_is_a_known_consent_key_or_empty_never_text_from_the_note():
    C = _c()
    D = C.CONSENT_REFUSED_DETAILS
    for key in D:                                        # a key the note names comes back as itself
        assert _view(f"not agreed: {key}", required=True).key == key
        assert _view(f"Left empty for the site's validation: NOT AGREED: {key.upper()} x").key == key
    for junk in ("ZEBRAWORDS", "C:\\Users\\Someone\\cv.pdf", "https://zebra.example/consents.x",
                 "consents.unknown_thing", "consents.", "consents.group", "../consents/x",
                 "{detail}", "consents x"):
        v = _view(f"not agreed: {junk}", required=True)
        assert v.code is C.NotAnsweredReason.CONSENT_NOT_AGREED, junk
        assert v.key == "", junk
        assert v.text == f"You haven't agreed to {C.NOT_ANSWERED_ANY_DETAIL}.", junk
    # no key in the note: the class's key; no class either: ""
    for cls, key in C.CONSENT_KEY_BY_CLASS.items():
        v = _view("not agreed: ???", field_class=cls, required=True)
        assert v.key == (key if key in D else ""), cls
    assert _view("not agreed: ???", field_class="ordinary", required=True).key == ""
    assert _view("your profile says no to this", field_class="consent_checks").key == \
        "consents.background_checks"
    for key in D:                                        # whatever the caller passes as detail_key
        assert _view(f"not agreed: {key}", detail_key="identity.date_of_birth").key == key


def test_the_place_code_carries_exactly_the_work_rights_key_whatever_detail_key_is_passed():
    C = _c()
    assert C.NOT_ANSWERED_WORK_RIGHTS_KEY == "singapore_status.authorised_to_work"
    for dk in ("", "identity.date_of_birth", "https://zebra.example", "C:\\x", None, 5, ["a"]):
        for req in (True, False):
            v = _view("place not recognised", required=req, detail_key=dk)
            assert v.code is C.NotAnsweredReason.PLACE_UNKNOWN
            assert v.key == C.NOT_ANSWERED_WORK_RIGHTS_KEY, dk


def test_the_work_rights_key_names_a_real_item_in_your_details():
    from jobscraper import applicant
    item, _sub = applicant.form_item(_c().NOT_ANSWERED_WORK_RIGHTS_KEY)
    assert item is not None


def test_a_missing_detail_carries_the_detail_key_only_when_lower_case_dotted_and_80_chars_or_fewer():
    C = _c()
    ok = ["identity.date_of_birth", "pay.expected_salary", "contact.phone_number", "a", "a.b.c",
          "education.degree_2", "a" * 80, "a" * 39 + "." + "a" * 40]
    bad = ["", "../x", "../../etc/passwd", "Identity.Dob", "IDENTITY.DOB", "a b", "Example Co",
           "https://zebra.example/x", "http://x", "C:\\x", "C:/x", "\\\\host\\share", "a/b", "a:b",
           "a" * 81, "a." + "b" * 80, "a..b", "a.", ".a", ".", "a\nb", "a\tb", "a b.c",
           "x{detail}", "{detail}", "a@b.example", "caf\u00e9.x", "a'b", 'a"b', "a;b", None, 5, 1.5,
           ["a.b"], ("a.b",), {"a": 1}, b"a.b", object()]
    for dk in ok:
        v = _view("comes only from your profile", required=True, detail_key=dk)
        assert v.code is C.NotAnsweredReason.DETAIL_MISSING and v.key == dk, dk
        v = _view("", required=True, question_reason="profile_gap", detail_key=dk)
        assert v.code is C.NotAnsweredReason.DETAIL_MISSING and v.key == dk, dk
    for dk in bad:
        v = _view("comes only from your profile", required=True, detail_key=dk)
        assert v.code is C.NotAnsweredReason.DETAIL_MISSING and v.key == "", repr(dk)
        v = _view("", required=True, question_reason="profile_gap", detail_key=dk)
        assert v.code is C.NotAnsweredReason.DETAIL_MISSING and v.key == "", repr(dk)


def test_every_other_code_has_an_empty_key_whatever_detail_key_is_passed():
    C = _c()
    key_codes = set(C.NOT_ANSWERED_KEY_CODES)
    assert key_codes == {C.NotAnsweredReason.CONSENT_NOT_AGREED, C.NotAnsweredReason.PLACE_UNKNOWN,
                         C.NotAnsweredReason.DETAIL_MISSING}
    seen = set()
    for code in C.NotAnsweredReason:
        if code in key_codes:
            continue
        note = _marker_for(C, code)
        for dk in ("identity.date_of_birth", "a", "../x", "https://zebra.example", None):
            for req in (True, False):
                v = _view(note, required=req, detail_key=dk)
                if code in C.NOT_ANSWERED_WITHOUT_MARKER:
                    assert note == ""
                    assert v.code is (C.NotAnsweredReason.NO_ANSWER if req else C.NotAnsweredReason.UNKNOWN)
                else:
                    assert v.code is code, (code, note)
                assert v.key == "", (code, dk)
                seen.add(v.code)
    assert seen == set(C.NotAnsweredReason) - key_codes


def test_no_key_ever_holds_a_separator_a_space_a_colon_or_http():
    C = _c()
    allowed_keys = set(C.CONSENT_REFUSED_DETAILS) | {C.NOT_ANSWERED_WORK_RIGHTS_KEY, ""}
    for note in HOSTILE + [f"not agreed: {h}" for h in HOSTILE] + [f"comes only from your profile {h}" for h in HOSTILE]:
        for fc in ("", "consent_checks", "consent_sharing:group", "garbage"):
            for qr in ("", "profile_gap", "no_rule"):
                for dk in ("", note, "identity.date_of_birth"):
                    k = _view(note, field_class=fc, required=True, question_reason=qr, detail_key=dk).key
                    assert isinstance(k, str)
                    assert not any(p in k.lower() for p in PATHY), repr(k)
                    if k not in allowed_keys:
                        assert k == dk and re.fullmatch(r"[a-z][a-z0-9_.]{0,79}", k), repr(k)


# ---- can_remember ------------------------------------------------------------------------------

def test_a_row_that_cannot_be_remembered_never_gets_a_next_time_hint():
    C = _c()
    assert "next time" in C.NOT_ANSWERED_HINT_REMEMBER      # the control: the hint it replaces says so
    for h in (C.NOT_ANSWERED_HINT_BY_HAND, C.NOT_ANSWERED_HINT_DETAILS, C.NOT_ANSWERED_HINT_OPTIONAL):
        assert "next time" not in h.lower()
    for code, r in C.NOT_ANSWERED_REASONS.items():
        assert "next time" not in r.hint.lower(), code      # no fixed hint says it either
    for note in HOSTILE[:20] + [_probe(m) for m, _ in C.NOT_ANSWERED_MARKERS] + ["", "zzz"]:
        for fc in ("", "ordinary", "consent_checks", "declaration:pep", "other_person"):
            for req in (True, False):
                for qr in _qreasons():
                    v = _view(note, field_class=fc, required=req, can_remember=False, question_reason=qr)
                    assert "next time" not in v.hint.lower(), (note[:30], fc, req, qr)
    assert _view("zzz", field_class="ordinary", required=True, can_remember=False).hint == \
        C.NOT_ANSWERED_HINT_BY_HAND
    assert _view("zzz", field_class="ordinary", required=True, can_remember=True).hint == \
        C.NOT_ANSWERED_HINT_REMEMBER
    # every other hint is unchanged by can_remember
    for note in [_probe(m) for m, _ in C.NOT_ANSWERED_MARKERS] + ["", "zzz"]:
        for fc in ("", "ordinary", "work_right"):
            for req in (True, False):
                a = _view(note, field_class=fc, required=req, can_remember=True)
                b = _view(note, field_class=fc, required=req, can_remember=False)
                if a.hint == C.NOT_ANSWERED_HINT_REMEMBER:
                    assert b.hint == C.NOT_ANSWERED_HINT_BY_HAND, (note, fc, req)
                else:
                    assert b.hint == a.hint, (note, fc, req)


# ---- the strict question reason ----------------------------------------------------------------

def test_the_strict_question_reason_table_is_total_disjoint_and_exact():
    C = _c()
    T = C.STRICT_QUESTION_REASON_TO_NOT_ANSWERED
    assert set(T) | set(C.QUESTION_REASONS_ANSWERED) == set(C.QuestionReason)
    assert not (set(T) & set(C.QUESTION_REASONS_ANSWERED))
    assert set(C.QUESTION_REASONS_ANSWERED) == {C.QuestionReason.ASSUMED}
    assert not (set(T.values()) & set(C.NOT_ANSWERED_WITHOUT_MARKER))
    NA, QR = C.NotAnsweredReason, C.QuestionReason
    assert T == {QR.NO_RULE: NA.NOT_IN_DETAILS, QR.UNGROUNDED: NA.NOT_CONFIRMED,
                 QR.PROFILE_GAP: NA.DETAIL_MISSING, QR.NO_OPTION_FITS: NA.NO_OPTION_FITS,
                 QR.ATTESTATION_UNCLEAR: NA.NOT_CONFIRMED, QR.CONFLICT: NA.WORK_RIGHTS_DIFFER,
                 QR.COMPOSE_NEEDED: NA.COMPOSE_NEEDED}
    assert len(T) == 7


def test_the_question_reason_picks_the_code_when_no_marker_matches():
    C = _c()
    for qr, code in C.STRICT_QUESTION_REASON_TO_NOT_ANSWERED.items():
        for form in (qr, qr.value):
            for note in ("", "zzz nothing known", None):
                for req in (True, False):
                    v = _view(note, required=req, question_reason=form)
                    assert v.code is code, (qr, note, req)
                    if code is not C.NotAnsweredReason.DETAIL_MISSING:
                        assert v.text == C.NOT_ANSWERED_REASONS[code].text
    assert _view("", required=True, question_reason="compose_needed").code is C.NotAnsweredReason.COMPOSE_NEEDED
    # always's own note maps to the same code with no question reason at all
    assert _view("compose needed: the tailor writes this text").code is C.NotAnsweredReason.COMPOSE_NEEDED


def test_a_marker_in_the_note_beats_the_question_reason():
    C = _c()
    for qr in C.QuestionReason:
        for marker, code in C.NOT_ANSWERED_MARKERS:
            assert _view(_probe(marker), required=True, question_reason=qr).code is code, (qr, marker)
    assert _view("reverted", question_reason="compose_needed").code is C.NotAnsweredReason.SITE_CLEARED


def test_an_assumed_or_unknown_question_reason_falls_to_the_default_and_never_raises():
    C = _c()
    for qr in ("assumed", C.QuestionReason.ASSUMED, "", "zzz", "Compose_Needed ", "{detail}", None, [], {}, 7,
               3.5, object(), b"no_rule", ("no_rule",), "x" * 5000):
        for req, code in ((True, C.NotAnsweredReason.NO_ANSWER), (False, C.NotAnsweredReason.UNKNOWN)):
            v = _view("", required=req, question_reason=qr)
            assert v.code is code, repr(qr)
            assert v.key == "" and "{" not in v.text + v.hint


# ---- the hostile property over text, hint AND key, under every question reason -----------------

def test_text_hint_and_key_of_the_view_stay_in_the_finite_set_under_every_question_reason():
    C = _c()
    allowed = _all_pairs()
    known_keys = set(C.CONSENT_REFUSED_DETAILS) | {C.NOT_ANSWERED_WORK_RIGHTS_KEY, ""}
    notes = HOSTILE + [f"{C.NOT_ANSWERED_SITE_PREFIX}{h}" for h in HOSTILE[:10]] + [
        f"not agreed: {h}" for h in HOSTILE[:10]]
    n = 0
    for note in notes:
        for fc in ("", "ordinary", "consent_checks", "consent_sharing:third_party", "garbage:{detail}"):
            for req in (True, False):
                for cr in (True, False):
                    for qr in _qreasons():
                        for dk in (note, "identity.date_of_birth"):   # a hostile and a well-shaped key
                            v = C.not_answered_view(note, field_class=fc, required=req, can_remember=cr,
                                                    question_reason=qr, detail_key=dk)
                            assert isinstance(v.code, C.NotAnsweredReason)
                            assert (v.text, v.hint) in allowed, (note[:40], fc, req, cr, qr)
                            for out in (v.text, v.hint, v.key):
                                assert "{" not in out and "}" not in out, (note[:40], out)
                                assert "http" not in out.lower()
                                for tok in LEAK_TOKENS:
                                    assert tok.lower() not in out.lower(), (note[:40], tok)
                            assert not re.search(r"[A-Za-z]:\\|\\|\w/\w|\n|\r|\t", v.text + v.hint)
                            assert not any(p in v.key.lower() for p in PATHY), repr(v.key)
                            if v.key not in known_keys:
                                assert v.code is C.NotAnsweredReason.DETAIL_MISSING and v.key == dk
                            if v.code not in C.NOT_ANSWERED_KEY_CODES:
                                assert v.key == ""
                            n += 1
    assert n >= 40 * 5 * 2 * 2 * 12


# ---- the consent-refused text stays v9 ---------------------------------------------------------

def test_the_consent_refused_text_is_still_byte_identical_to_v9():
    C = _c()
    assert C.REASON_TEXTS[C.ReasonCode.CONSENT_REFUSED].text == (
        "This form needs you to agree to {detail}, and your profile says no. Nothing was sent.")
