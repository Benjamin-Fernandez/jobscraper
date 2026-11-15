"""Q-121 always-answer pins, fix round 2 (D-208; the Coordinator's rulings R3, R4 and item 1).

R3  Certification and acknowledgement questions are not adverse declarations: "Do you declare /
    certify / confirm that the above is true" is Yes from `consents.certify_true` (unset: Yes,
    assumed); "Have you read / agree to our <policy | code of conduct>" is Yes (assumed), and a
    privacy notice follows `consents.privacy_consent`; the last resort never applies the
    declarations' No to a question with no matched class; a real adverse declaration still gets No.
R4  An explicit consent value in the profile beats the model in both directions.
Item 1  An owner-only fact's value stands only when its basis points at THAT fact.

Under `always` with `mode: auto` every filled form is SUBMITTED, so each pin scripts the fake
`ask` to the WRONG answer (or to nothing). A red pin is a defect in the code, not in the value.
Dummy sample profile only; no model, no network, no browser.
Verify: python tests/run_tests.py -k always_consent_pins
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402
from test_always_fill import NEEDS, YN, FakeAsk, _one, _pf, _profile, _shown, say  # noqa: E402
from test_always_fix_pins import (  # noqa: E402
    GRADE_RESUME, NO_GRADE_RESUME, _is_refusal_stop, _is_stop, _no_grade_profile, _say_bool,
    _stop_or_answer, _tick, _what)


def _consents(**kv):
    p = _profile()
    for k, v in kv.items():
        if v == "UNSET":
            p["consents"].pop(k, None)
        else:
            p["consents"][k] = v
    return p


def _opts(kind: str):
    return YN if kind == "RADIO" else ()


# ------------------------------------------------------------------ R3

CERT_LABELS = (("Do you declare that the above is true?", "RADIO"),
               ("Do you certify that the information provided is true and complete?", "RADIO"),
               ("Please confirm that the information above is accurate", "RADIO"),
               ("I certify that the information provided is true and complete", "CHECKBOX"))


@needs(*NEEDS)
def test_r3_a_certification_is_yes_from_certify_true_whatever_the_model_says():
    p = _consents(certify_true=True)
    bad = []
    for label, kind in CERT_LABELS:
        asks = (("silent", FakeAsk()),
                ("model no", FakeAsk(lambda v, k=kind: _say_bool(k, False, "default", "default:consent"))),
                ("model yes (declaration rule)",
                 FakeAsk(lambda v, k=kind: _say_bool(k, True, "default", "default:no_declaration"))))
        for who, ask in asks:
            a, _ = _one(_pf("c", label, kind, options=_opts(kind)), ask, p)
            if not (_tick(a) and a.source == "profile:consents.certify_true" and not a.assumed):
                bad.append((label, who, _what(a)))
    assert not bad, bad


@needs(*NEEDS)
def test_r3_a_certification_with_certify_true_unset_is_yes_assumed_never_the_declarations_no():
    p = _consents(certify_true="UNSET")
    bad = []
    for label, kind in CERT_LABELS:
        a, _ = _one(_pf("c", label, kind, options=_opts(kind)), FakeAsk(), p)
        if not (_tick(a) and a.assumed):
            bad.append((label, _what(a)))
    assert not bad, bad


ACKS = (("Have you read our code of conduct?", False),
        ("Have you read our conflict of interest policy?", False),
        ("Do you agree to our privacy notice?", True))


@needs(*NEEDS)
def test_r3_a_policy_acknowledgement_is_yes_assumed_and_a_privacy_notice_follows_privacy_consent():
    # A1 (design 17.2, acknowledgement row): an acknowledgement of a PRIVACY notice follows
    # `consents.privacy_consent`; of ANYTHING ELSE (code of conduct, policy) it follows
    # `consents.certify_true`: set (the sample: true) -> Yes from that row, not assumed; unset ->
    # Yes by the D5 default, assumed. `privacy_consent` never decides a non-privacy acknowledgement.
    bad = []
    for label, privacy in ACKS:
        # privacy_consent unset (certify_true stays true in the sample)
        a, _ = _one(_pf("k", label, options=YN), FakeAsk(), _consents(privacy_consent="UNSET"))
        if _shown_yes(a) is False or (privacy and not a.assumed) \
                or (not privacy and (a.assumed or a.source != "profile:consents.certify_true")):
            bad.append((label, "privacy_consent unset", _what(a)))
        # privacy_consent true
        a, _ = _one(_pf("k", label, options=YN), FakeAsk(), _consents(privacy_consent=True))
        if _shown_yes(a) is False or a.assumed \
                or a.source != ("profile:consents.privacy_consent" if privacy else "profile:consents.certify_true"):
            bad.append((label, "privacy_consent true", _what(a)))
        if not privacy:
            # certify_true unset: a non-privacy acknowledgement is then the D5 default, assumed
            a, _ = _one(_pf("k", label, options=YN), FakeAsk(), _consents(certify_true="UNSET"))
            if _shown_yes(a) is False or not a.assumed or a.source != "default:consent":
                bad.append((label, "certify_true unset", _what(a)))
            # certify_true false: the refusal is the owner's (R-c); privacy_consent cannot override it
            a, _ = _one(_pf("k", label, options=YN), FakeAsk(), _consents(certify_true=False, privacy_consent=True))
            if a.option_labels != ("No",):
                bad.append((label, "certify_true false", _what(a)))
    assert not bad, bad


def _shown_yes(a) -> bool:
    return bool(a.option_labels) and a.option_labels[0] == "Yes"


@needs(*NEEDS)
def test_r3_a_question_with_no_matched_declaration_class_never_gets_the_declarations_no():
    # Intent kept: a question that is no adverse declaration never gets the DECLARATIONS' No
    # (source default:no_declaration / a declarations row). A1 (17.2: the acknowledgement and
    # certification frames need an OBJECT of the class): "Do you acknowledge?" after a separate
    # sentence and "read the above" have no frame, so they are ordinary: a model answer stands as
    # given, and a silent model ends at design 4.6 F2 "anything else -> No", assumed, source
    # `fallback:F2` (the as-built ordinary end, not a declaration).
    p = _consents(privacy_consent="UNSET", certify_true="UNSET")
    # D-211 C (replaces "a model No on 'read the above' stands, the label has no frame"): "Do you confirm
    # that you have read the above?" IS an acknowledgement frame ("the above" is its object), and with
    # certify_true unset the standing answer is Yes, assumed (D5): a model's Yes is kept, the model's No is
    # overridden by code (both keys), a silent model gets Yes assumed. Never the declarations' No.
    bad = []
    for said in ("Yes", "No"):
        a, _ = _one(_pf("u", "Do you confirm that you have read the above?", options=YN),
                    FakeAsk(lambda v, s=said: say(s, "default", "default:consent")), p)
        if a.option_labels != ("Yes",) or not a.assumed or "declaration" in a.source:
            bad.append(("read the above", f"model {said}", _what(a)))
    for label in ("Please be advised that we process your data. Do you acknowledge?",):
        for said in ("Yes", "No"):                                   # a model answer is its own
            a, _ = _one(_pf("u", label, options=YN), FakeAsk(lambda v, s=said: say(s, "default", "default:consent")), p)
            if _shown(a) != said or a.source != "default:consent":
                bad.append((label, f"model {said}", _what(a)))
    for label in ("Please be advised that we process your data. Do you acknowledge?",
                  "Do you confirm that you have read the above?"):
        a, _ = _one(_pf("u", label, options=YN), FakeAsk(), p)          # silent
        # ruling C (after code review 2, L3): a silent model on an unframed acknowledgement is Yes, assumed
        # (the F2 generic No of 4.6 is gone for it); never the declarations' No
        if a.option_labels != ("Yes",) or not a.assumed or "declaration" in a.source:
            bad.append((label, "silent", _what(a)))
    # the two labels that DO carry a frame are never No either (certification / acknowledgement -> Yes)
    for label in ("Do you declare that the above is true?", "Have you read our conflict of interest policy?"):
        a, _ = _one(_pf("u", label, options=YN), FakeAsk(), p)
        if a.option_labels != ("Yes",) or not a.assumed:
            bad.append((label, "framed, silent", _what(a)))
    assert not bad, bad


ADVERSE = ("Do you declare any conflict of interest?", "Do you declare any conflict of interest with this role?")


@needs(*NEEDS)
def test_r3_an_adverse_declaration_with_the_verb_still_gets_no_when_the_model_says_yes():
    # Intent kept: a real adverse declaration never goes out as Yes. A1: the model's Yes citing a
    # default rule -> D1b writes the rule's No (both keys); the model agreeing -> No, not assumed; a
    # SILENT model on this tentative reader ("Do you declare ...?" fails the D-90 frame gate) no
    # longer gets a guessed No from F2: the protective end is EMPTY for the site (17.2: the none
    # option only with a confident reader or a confirm pick) and never Yes.
    # D-212 U2-U4 (replaces "the model's Yes citing a default rule -> code writes the rule's No; a silent model
    # ends empty"): the model's Yes differs from the reader's No -> ONE confirmation: pick No -> No (assumed),
    # unusable / a pick that sides with the Yes without a "no" meaning reply -> empty. Never Yes. A silent
    # model gets the same one confirmation.
    # U9 (review 4 F1; replaces the 1-call / no-call counts): "Do you declare any conflict of interest ...?" is no
    # canonical frame, so the reader has NO reading and every path takes the confirmation + meaning calls: a
    # differing confirmation (No) gets the meaning call on BOTH values (U8b, 3 calls); a silent model 2 calls (U8);
    # even the model's right No takes confirmation + meaning (U6, 2 calls). Never Yes written.
    from always_a1_support import pick_by, pick_faithful
    bad = []
    for label in ADVERSE:
        for ref in ("default:no_declaration", "default:employer_history"):
            ask = FakeAsk(lambda v, r=ref: say("Yes", "default", r), pick=pick_faithful("No", "No"))
            a, _ = _one(_pf("a", label, options=YN), ask)
            if a.option_labels != ("No",) or not a.assumed or len(ask.picks) != 3:
                bad.append((label, ref, "confirmation No", _what(a), len(ask.picks)))
            ask = FakeAsk(lambda v, r=ref: say("Yes", "default", r), pick=pick_by("Yes", ""))
            a, _ = _one(_pf("a", label, options=YN), ask)
            if _shown(a) != "" or len(ask.picks) != 2:
                bad.append((label, ref, "confirmation Yes, meaning unusable", _what(a), len(ask.picks)))
        ask = FakeAsk(pick=pick_faithful("No", "No"))
        a, _ = _one(_pf("a", label, options=YN), ask)                                # silent
        if a.option_labels != ("No",) or not a.assumed or len(ask.picks) != 2:
            bad.append((label, "silent, confirmation No", _what(a), len(ask.picks)))
        ask = FakeAsk(pick=pick_by("", ""))
        a, _ = _one(_pf("a", label, options=YN), ask)
        if _shown(a) != "":
            bad.append((label, "silent, unusable", _what(a)))
        ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration"), pick=pick_faithful("No", "No"))
        a, _ = _one(_pf("a", label, options=YN), ask)                                # control: agreeing
        if a.option_labels != ("No",) or not a.assumed or len(ask.picks) != 2:
            bad.append((label, "model agrees", _what(a), len(ask.picks)))
        # one key (the model calls it ordinary): the confirmation for the owner's truth, then the meaning calls
        ask = FakeAsk(lambda v: say("Yes", "assumption", "", True, klass="ordinary"), pick=pick_faithful("No", "No"))
        a, _ = _one(_pf("a", label, options=YN), ask)
        if a.option_labels != ("No",) or not a.assumed:
            bad.append((label, "class ordinary + confirm No", _what(a)))
    assert not bad, bad


# ------------------------------------------------------------------ R4

CONSENT_QUESTIONS = (
    ("talent_pool_opt_in", "Subscribe to our newsletter", "CHECKBOX"),
    ("talent_pool_opt_in", "Would you like to join our talent community?", "RADIO"),
    ("data_retention_consent", "I agree that you keep my details on file for future roles", "CHECKBOX"),
    ("data_retention_consent", "May we keep your details on file for future roles?", "RADIO"),
    ("certify_true", "I certify that the information provided is true and complete", "CHECKBOX"),
    ("certify_true", "Do you certify that the information provided is true and complete?", "RADIO"),
    ("privacy_consent", "I consent to the processing of my personal data", "CHECKBOX"),
    ("privacy_consent", "Do you consent to the processing of your personal data?", "RADIO"))


def _r4_failures(select) -> list:
    bad = []
    for key, label, kind in CONSENT_QUESTIONS:
        for value in (True, False):
            p = _consents(**{key: value})
            for required in (True, False):
                if not select(kind, required, value):
                    continue
                for ref in (f"profile:consents.{key}", "default:consent"):      # incl. the very row it contradicts
                    basis = "profile" if ref.startswith("profile:") else "default"
                    ask = FakeAsk(lambda v, k=kind, x=value, b=basis, r=ref: _say_bool(k, not x, b, r))
                    res = _stop_or_answer(_pf("c", label, kind, required=required, options=_opts(kind)), ask, p)
                    where = (key, kind, f"profile={value}", f"required={required}", ref)
                    refused_box = kind == "CHECKBOX" and required and not value
                    if refused_box and key != "talent_pool_opt_in":
                        # ruling A: never ticked, and the attempt stops naming the consent
                        if not _is_refusal_stop(res, key):
                            bad.append((*where, "no refusal stop", _what(res)))
                        continue
                    if isinstance(res, Exception):
                        bad.append((*where, "unexpected stop", _what(res)))
                        continue
                    a, out = res, None
                    if _tick(a) is not value:
                        bad.append((*where, "wrong value", _what(a)))
                    elif refused_box:
                        continue                         # marketing: a required box left unticked for the site
                    elif a.source != f"profile:consents.{key}" or a.assumed:
                        bad.append((*where, "source/assumed", _what(a)))
                    elif "the AI answered" not in (a.note + " " + a.evidence):
                        bad.append((*where, "the model's answer is not a note", a.note, a.evidence))
    return bad


@needs(*NEEDS)
def test_r4_an_explicit_consent_value_beats_the_model_in_both_directions():
    # yes/no questions and optional boxes: written with the profile row as source, not assumed
    bad = _r4_failures(lambda kind, required, value: kind == "RADIO" or not required)
    assert not bad, bad
    # a required box the profile says yes to is ticked from the row too
    bad = _r4_failures(lambda kind, required, value: kind == "CHECKBOX" and required and value)
    assert not bad, bad


@needs(*NEEDS)
def test_r4_a_required_box_the_profile_refuses_is_never_ticked_and_the_attempt_stops():
    # the model ticks "I consent / I certify / keep my details" citing the very row that says
    # false (or a default rule): ruling A, the box stays unticked and the attempt stops
    # `owner_fact_missing` with target consents.<key> (marketing: unticked, no stop)
    bad = _r4_failures(lambda kind, required, value: kind == "CHECKBOX" and required and not value)
    assert not bad, bad


@needs(*NEEDS)
def test_r4_negative_control_an_unset_consent_key_leaves_the_models_answer_standing():
    # A1 (design 17.2, T column "Unset"): privacy, certification and acknowledgement -> agree (D5,
    # derived, ASSUMED), so with BOTH keys naming the class code writes Yes over the model's No;
    # retention unset -> the model decides. Only retention keeps the old "model's answer stands".
    bad = []
    for key, label, kind in CONSENT_QUESTIONS:
        if key == "talent_pool_opt_in":
            continue                                  # D2 still forces No/unticked when unset (below)
        p = _consents(**{key: "UNSET"})
        for said in (True, False):
            a, _ = _one(_pf("c", label, kind, required=False, options=_opts(kind)),
                        FakeAsk(lambda v, k=kind, x=said: _say_bool(k, x, "default", "default:consent")), p)
            if key in ("certify_true", "privacy_consent"):
                if not (_tick(a) and a.assumed and a.source == "default:consent"):
                    bad.append((key, kind, f"model={said}", "derived agree, assumed", _what(a)))
                continue
            if _tick(a) is not said or a.source == f"profile:consents.{key}":      # retention
                bad.append((key, kind, f"model={said}", _what(a)))
    for label, kind in (("Subscribe to our newsletter", "CHECKBOX"),
                        ("Would you like to join our talent community?", "RADIO")):
        a, _ = _one(_pf("c", label, kind, required=False, options=_opts(kind)),
                    FakeAsk(lambda v, k=kind: _say_bool(k, True, "default", "default:consent")),
                    _consents(talent_pool_opt_in="UNSET"))
        if _tick(a):
            bad.append(("talent_pool_opt_in unset", kind, _what(a)))
    assert not bad, bad


# ------------------------------------------------------------------ Item 1: bases that point at THAT fact

# (fact the stop names, label, field type, a value the model might invent, an extra entry's question)
OWNER_FACTS = (
    ("date of birth", "Date of birth", "DATE", "2026-11-12", "date of birth"),
    ("national ID number", "NRIC number", "TEXT", "S1234567D", "nric number"),
    ("passport number", "Passport number", "TEXT", "E1234567", "passport number"),
    ("bank details", "Bank account number", "TEXT", "123456789", "bank account number"),
    ("expected salary", "Expected salary", "NUMBER", "5000", "expected salary"),
    ("grade", "Cumulative GPA", "NUMBER", "3.9", "cumulative gpa"))


def _profile_without_owner_facts() -> dict:
    p = _no_grade_profile()
    p["identity"]["date_of_birth"] = None
    p["pay"] = {}
    p["singapore_status"]["nric_last4"] = ""
    return p


@needs(*NEEDS)
def test_item1_an_unrelated_standing_ref_or_another_fields_path_never_verifies_an_owner_fact():
    p = _profile_without_owner_facts()
    p["extra"] = {"colour": {"title": "Favourite colour", "kind": "text", "description": "", "sensitive": False,
                             "labels": ["favourite colour"], "value": "blue"}}
    bad = []
    for fact, label, kind, value, _extra in OWNER_FACTS:
        for basis, ref in (("standing", "standing:today"), ("standing", "standing:earliest_start"),
                           ("standing", "standing:experience_years"), ("profile", "profile:contact.phone_number"),
                           ("profile", "profile:identity.legal_first_name"), ("extra", "extra:colour")):
            res = _stop_or_answer(_pf("f", label, kind),
                                  FakeAsk(lambda v, b=basis, r=ref, x=value: say(x, b, r)), p,
                                  rctx_kw={"resume_text": NO_GRADE_RESUME})
            if not _is_stop(res, fact):
                bad.append((fact, ref, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_item1_a_standing_fact_of_another_class_does_not_verify_a_salary_or_grade_either():
    p = _profile_without_owner_facts()
    bad = []
    for fact, label, value in (("expected salary", "Expected salary", "5000"), ("grade", "Cumulative GPA", "3.9")):
        for basis, ref in (("standing", "standing:experience_months"), ("standing", "standing:today"),
                           ("profile", "profile:pay.months_per_year")):
            res = _stop_or_answer(_pf("f", label, "NUMBER"),
                                  FakeAsk(lambda v, b=basis, r=ref, x=value: say(x, b, r)),
                                  p, rctx_kw={"resume_text": NO_GRADE_RESUME})
            if not _is_stop(res, fact):
                bad.append((fact, ref, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_item1_negative_control_the_right_path_with_a_matching_value_is_filled_not_assumed():
    p = _profile()
    p["singapore_status"]["nric_last4"] = "567D"
    cases = (("Date of birth", "DATE", "2002-03-14", "profile", "profile:identity.date_of_birth", None),
             ("Date of birth", "TEXT", "2002-03-14", "profile", "profile:identity.date_of_birth", None),
             ("NRIC number", "TEXT", "567D", "profile", "profile:singapore_status.nric_last4", None),
             ("Expected salary", "NUMBER", "5000", "profile", "profile:pay.expected_salary", None),
             ("Expected salary", "NUMBER", "5000", "standing", "standing:expected_pay_monthly", None),
             ("Cumulative GPA", "NUMBER", "4.20", "profile", "profile:education[0].grade", None),
             ("Cumulative GPA", "NUMBER", "3.85", "resume", "", GRADE_RESUME))
    bad = []
    for label, kind, value, basis, ref, resume in cases:
        pp = _no_grade_profile() if basis == "resume" else p
        res = _stop_or_answer(_pf("f", label, kind), FakeAsk(lambda v, b=basis, r=ref, x=value: say(x, b, r)), pp,
                              rctx_kw={"resume_text": resume} if resume else None)
        if isinstance(res, Exception) or str(res.value) != value or res.assumed:
            bad.append((label, kind, ref or basis, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_item1_an_extra_entry_asking_for_the_same_fact_counts_as_its_basis():
    values = {"date of birth": "2001-02-03", "national ID number": "S7654321D", "passport number": "E7654321",
              "bank details": "987654321", "expected salary": "6000", "grade": "3.7"}
    bad = []
    for fact, label, kind, _invented, extra_label in OWNER_FACTS:
        p = _profile_without_owner_facts()
        p["extra"] = {"saved": {"title": label, "kind": "text", "description": "", "sensitive": True,
                                "labels": [extra_label], "value": values[fact]}}
        res = _stop_or_answer(_pf("f", "Please give your " + label.lower(), kind),
                              FakeAsk(lambda v, x=values[fact]: say(x, "extra", "extra:saved")), p,
                              rctx_kw={"resume_text": NO_GRADE_RESUME})
        if isinstance(res, Exception) or str(res.value) != values[fact]:
            bad.append((fact, _what(res)))
    assert not bad, bad
