"""Q-121 Amendment A1 oracles, part 3: the code key and the design-review rows C1-C6, C9
(llm_first_fill_design §17.1, §17.2, §17.4; pin groups (17)-(22), (25); docs/reviews/Q-121-A1-design.md).

K  `always.code_key(pf, ctx) -> (FieldClass | None, which)`: the narrowed detectors of §17.2, one table.
17 C1  the six polarity rows (model right and wrong; class `declaration:*` and `ordinary`; a confirm call
       that returns "" ends protectively).
18 C2  the nine non-fact labels (no veto) and containment for the real address / postal / phone fields.
19 C3  the unclassed adverse yes/no (dismissed, litigation, visa refusal, investigation).
20 C4  contradicting keys (NDA willingness, expected vs current salary).
21 C5  one box that carries two consents.
22 C6  self-ID: a synonym option, no truthful option.
25 C9  age, SSN, tax ID, driver licence number, employee ID are owner facts.
Fakes only; expected values from the design. Verify: python tests/run_tests.py -k always_a1_c
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    DELETE, NO_CLASS, YN, FakeAsk, attempt, code_key_of, digits, is_empty, is_stop, is_ticked, is_unticked,
    labels, lie, pick_by, pick_faithful, profile_with, report, say, shown, stop_is, what, with_text, _pf, _profile)


# ================================================================== K: the code key, one table

def test_k_code_key_names_the_designed_class_and_which():
    O = "ordinary"
    rows = (
        # (label, type, options, class, which or None = any)
        ("I consent to the processing of my personal data", "CHECKBOX", (), "consent_privacy", None),
        ("May we keep your details on file for future roles?", "RADIO", YN, "consent_retention", None),
        ("Sign me up for job alerts", "CHECKBOX", (), "marketing", None),
        ("Would you like to receive our newsletter?", "RADIO", YN, "marketing", None),
        ("I certify that the information above is true and complete", "CHECKBOX", (), "certification", None),
        ("I have read and understood the code of conduct", "CHECKBOX", (), "acknowledgement", None),
        ("Are you a politically exposed person?", "RADIO", YN, "declaration", "pep"),
        ("Have you ever been convicted of a criminal offence?", "RADIO", YN, "declaration", "criminal_record"),
        ("Have you ever been declared bankrupt?", "RADIO", YN, "declaration", "bankruptcy"),
        ("Have you ever been dismissed or asked to resign from any employment?", "RADIO", YN, "declaration", "other"),
        ("Any pending litigation or legal proceedings against you?", "RADIO", YN, "declaration", "other"),
        ("Have you ever been refused a visa or denied entry to a country?", "RADIO", YN, "declaration", "other"),
        ("Are you currently under investigation by any regulator?", "RADIO", YN, "declaration", "other"),
        ("Are you legally authorised to work in Singapore?", "RADIO", YN, "work_right", None),
        ("Will you now or in the future require sponsorship for employment visa status?", "RADIO", YN, "sponsorship", None),
        ("Date of birth", "DATE", (), "owner_fact", "date_of_birth"),
        ("Year of birth", "TEXT", (), "owner_fact", "date_of_birth"),
        ("Geburtsdatum", "TEXT", (), "owner_fact", "date_of_birth"),
        ("Date of birth - Year", "DROPDOWN", ("2001", "2002", "2003"), "owner_fact", "date_of_birth"),
        ("How old are you?", "NUMBER", (), "owner_fact", "age"),
        ("Social security number", "TEXT", (), "owner_fact", "national_id"),
        ("Tax ID", "TEXT", (), "owner_fact", "national_id"),
        ("Driver licence number", "TEXT", (), "owner_fact", "other_id"),
        ("Employee ID", "TEXT", (), "owner_fact", "other_id"),
        ("Class of degree", "TEXT", (), "owner_fact", "grade"),
        ("Last drawn salary", "TEXT", (), "owner_fact", "salary_current"),
        ("Expected salary", "TEXT", (), "owner_fact", "salary_expected"),
        ("Home address", "TEXT", (), "owner_fact", "address"),
        ("Postal code", "TEXT", (), "owner_fact", "postal_code"),
        ("Mobile number", "PHONE", (), "owner_fact", "phone"),
        ("Gender", "DROPDOWN", ("Male", "Female", "Prefer not to say"), "self_id", "gender"),
        ("Are you Hispanic or Latino?", "RADIO", YN, "self_id", None),
        ("Ethnic origin", "DROPDOWN", ("Asian", "White", "Prefer not to say"), "self_id", None),
        ("Do you have a disability?", "RADIO", YN, "self_id", "disability"),
        ("Referee email", "EMAIL", (), "other_person", None),
        ("Emergency contact phone number", "PHONE", (), "other_person", None),
        # ordinary: the code finds nothing (review H1 rows, willingness, the C2 non-facts)
        *[(lab, "RADIO", YN, O, None) for lab, _m in __import__("test_always_a1").H1_ROWS],
        ("Are you willing to sign an NDA?", "RADIO", YN, O, None),
        ("Are you willing to relocate?", "RADIO", YN, O, None),
        ("Can you confirm you have 2 years of Python?", "RADIO", YN, O, None),
        ("Experience with privacy or marketing tools?", "TEXT", (), O, None),
        ("Do you know someone here who can refer you?", "RADIO", YN, O, None),
    )
    bad = []
    for label, tn, options, klass, which in rows:
        got = code_key_of(_pf("k", label, tn, options=options))
        if got[0] != klass or (which is not None and got[1] != which):
            bad.append((label, tn, "want", (klass, which), "got", got))
    assert not bad, report(bad, 12)


C2_NON_FACTS = (
    ("Email address", "EMAIL", ()), ("Confirm email address", "EMAIL", ()), ("Home page URL", "URL", ()),
    ("Home country", "DROPDOWN", ("Singapore", "Malaysia")), ("IP address", "TEXT", ()),
    ("Phone Device Type", "DROPDOWN", ("Mobile", "Home", "Work")),
    ("Country Phone Code", "DROPDOWN", ("Singapore (+65)", "Malaysia (+60)")),
    ("Phone Extension", "TEXT", ()), ("Do you have a mobile phone?", "RADIO", YN),
)


def test_k_the_nine_non_fact_labels_are_not_address_postal_or_phone_owner_facts():
    bad = []
    for label, tn, options in C2_NON_FACTS:
        k, w = code_key_of(_pf("n", label, tn, options=options))
        if k == "owner_fact" and w in ("address", "postal_code", "phone"):
            bad.append((label, tn, (k, w)))
    assert not bad, report(bad)


def test_k_a_choice_list_a_checkbox_and_another_persons_field_are_never_an_address_postal_or_phone_fact():
    bad = []
    for label, tn, options in (("Mobile number", "DROPDOWN", ("91234567", "98765432")), ("Home address", "RADIO", ("Yes", "No")),
                               ("Postal code", "CHECKBOX", ()), ("Referee phone number", "PHONE", ()),
                               ("Referee postal code", "TEXT", ())):
        k, w = code_key_of(_pf("n", label, tn, options=options))
        if k == "owner_fact" and w in ("address", "postal_code", "phone"):
            bad.append((label, tn, (k, w)))
    assert not bad, report(bad)


# ================================================================== (17) C1: the six polarity rows

C1_ROWS = (
    # (label, type, options, ADVERSE value, RIGHT value, model class)
    ("Is it untrue that you have never been bankrupt?", "RADIO", YN, "Yes", "No", "declaration:bankruptcy"),
    ("Is it false that you have no criminal record?", "RADIO", YN, "Yes", "No", "declaration:criminal_record"),
    ("Do you deny that you are a politically exposed person?", "RADIO", YN, "No", "Yes", "declaration:pep"),
    ("Would it be incorrect to say you have been convicted of an offence?", "RADIO", YN, "No", "Yes", "declaration:criminal_record"),
    ("Tick if you are a politically exposed person", "CHECKBOX", (), "true", "false", "declaration:pep"),
    ("Check this box if you have been convicted of a criminal offence", "CHECKBOX", (), "true", "false", "declaration:criminal_record"),
)


def _is_adverse(res, adverse: str, tn: str) -> bool:
    return is_ticked(res) if tn == "CHECKBOX" else shown(res) == adverse


def test_a1_c1_a_wrong_model_value_is_never_written_whatever_the_class_and_the_confirm_call_says():
    """Model WRONG (the adverse value). The adverse value is never written, in any class condition and
    whatever an unusable or differing confirmation says. D-211 P3 (replaces "a usable confirm pick that
    differs from the model's wrong answer is written"): the four implicit-negator rows have no code
    reading, so the model's first answer and ONE confirmation decide; a confirmation that DIFFERS from
    the first answer (the right option) or is unusable -> the protective end (empty), one call. (A
    confirmation that AGREES with a wrong first answer is written: the accepted residual, not pinned.)
    The two tick-box rows state the adverse fact with no negation: never ticked."""
    bad = []
    for label, tn, options, adverse, right, klass in C1_ROWS:
        for k in (klass, "ordinary", NO_CLASS):
            for pick in ("", right):
                ask = FakeAsk(lambda v, k=k: lie(adverse, k), pick=lambda q, w, o, x=pick: x)
                res = attempt(_pf("p", label, tn, options=options), ask)
                if _is_adverse(res, adverse, tn):
                    bad.append((label, k, f"confirm={pick!r}", "adverse written", what(res)))
                elif tn != "CHECKBOX" and (shown(res) != "" or not 1 <= len(ask.picks) <= 2):
                    # D-212 U8: a differing confirmation gets a meaning call on its own value (this single-valued
                    # pick answers it unusably): 1 or 2 calls, the end is empty
                    bad.append((label, k, f"confirm={pick!r}", "differ / unusable -> empty",
                                what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_a1_c1_a_right_model_value_is_never_turned_into_the_adverse_one_by_the_reader():
    bad = []
    for label, tn, options, adverse, right, klass in C1_ROWS:
        for k in (klass, "ordinary", None):
            for pick in ("", right):
                ask = FakeAsk(lambda v, k=k: say(right, "default", "default:no_declaration", klass=k), pick=lambda q, w, o, x=pick: x)
                res = attempt(_pf("p", label, tn, options=options), ask)
                if _is_adverse(res, adverse, tn):
                    bad.append((label, k, f"confirm={pick!r}", what(res)))
    assert not bad, report(bad, 10)


def test_a1_c1_a_silent_model_never_gets_the_adverse_value_from_the_generic_no_rule():
    bad = []
    for label, tn, options, adverse, right, _k in C1_ROWS:
        res = attempt(_pf("p", label, tn, options=options), FakeAsk())
        if _is_adverse(res, adverse, tn):
            bad.append((label, what(res)))
    assert not bad, report(bad)


def test_a1_c1_the_checkbox_rule_a_declaration_box_without_a_negation_reads_ticked_as_it_applies():
    """Design 17.1: ticked = the declaration applies (H = ticked); both keys -> untick."""
    for label, _tn, _o, _adv, _right, klass in C1_ROWS[4:]:
        res = attempt(_pf("p", label, "CHECKBOX"), FakeAsk(lambda v: lie("true", klass)))
        assert is_unticked(res), (label, what(res))
    # the same box when the owner's truth is True: ticking is right and must not be blocked
    res = attempt(_pf("p", "Tick if you are a politically exposed person", "CHECKBOX"),
                  FakeAsk(lambda v: say("true", "profile", "profile:declarations.pep", klass="declaration:pep")),
                  profile_with(declarations__pep=True))
    assert is_ticked(res), what(res)


# ================================================================== (18) C2: no veto on non-fact labels

def test_a1_c2_the_nine_non_fact_labels_keep_the_models_value_and_never_stop():
    from apply_flow_support import EMAIL
    bad = []
    rows = (("Email address", "EMAIL", (), "careers@example.org", ("careers@example.org", EMAIL)),
            ("Confirm email address", "EMAIL", (), "careers@example.org", ("careers@example.org", EMAIL)),
            ("Home page URL", "URL", (), "https://example.org/me", None),
            ("Home country", "DROPDOWN", ("Singapore", "Malaysia"), "Singapore", ("Singapore",)),
            ("IP address", "TEXT", (), "192.0.2.1", ("192.0.2.1",)),
            ("Phone Device Type", "DROPDOWN", ("Mobile", "Home", "Work"), "Mobile", ("Mobile",)),
            ("Country Phone Code", "DROPDOWN", ("Singapore (+65)", "Malaysia (+60)"), "Singapore (+65)", ("Singapore (+65)",)),
            ("Phone Extension", "TEXT", (), "123", ("123",)),
            ("Do you have a mobile phone?", "RADIO", YN, "Yes", ("Yes",)))
    for label, tn, options, value, allowed in rows:
        for k in ("ordinary", None):
            res = attempt(_pf("n", label, tn, options=options), FakeAsk(lambda v, k=k: say(value, "resume", "", klass=k)))
            v = shown(res)
            leaked = "1 Example Road" in v or (tn not in ("PHONE",) and "91234567" in digits(v) and "phone" not in label.lower())
            if is_stop(res) or leaked or (allowed is not None and v not in allowed):
                bad.append((label, k, "want", allowed or value, what(res)))
    assert not bad, report(bad, 10)


def test_a1_c2_real_fields_are_accepted_by_containment_not_equality():
    p = profile_with(contact__phone_number="90000000", contact__address_line1="Line 1", contact__address_line2="Line 2")
    bad = []
    for label, tn, value, klass in (("Mobile number", "PHONE", "+65 9000 0000", "owner_fact:phone"),
                                    ("Phone number", "TEXT", "9000 0000", "owner_fact:phone"),
                                    ("Home address", "TEXT", "Line 1, Line 2", "owner_fact:address")):
        res = attempt(_pf("m", label, tn), FakeAsk(lambda v: say(value, "profile", "profile:contact.phone_number", klass=klass)), p)
        v = shown(res)
        ok = digits("90000000") in digits(v) if "phone" in klass else "line 1" in v.lower()
        if is_stop(res) or not ok or (tn == "TEXT" and v != value):
            bad.append((label, value, what(res)))
    assert not bad, report(bad)


def test_a1_c2_a_vetoed_phone_with_the_profile_holding_one_is_the_profiles_value_never_owner_fact_missing():
    for tn in ("PHONE", "TEXT"):
        res = attempt(_pf("m", "Phone number", tn), FakeAsk(lambda v: lie("98765432", "owner_fact:phone")))
        assert not is_stop(res) and digits("91234567") in digits(shown(res)), (tn, what(res))


def test_a1_c2_another_persons_phone_is_not_the_applicants_phone():
    res = attempt(_pf("m", "Referee phone number", "TEXT"), FakeAsk(lambda v: lie("91234567", "ordinary")))
    assert "91234567" not in digits(shown(res)), what(res)


# ================================================================== (19) C3: the unclassed adverse yes/no

C3_LABELS = ("Have you ever been dismissed or asked to resign from any employment?",
             "Any pending litigation or legal proceedings against you?",
             "Have you ever been refused a visa or denied entry to a country?",
             "Are you currently under investigation by any regulator?")


def test_a1_c3_an_adverse_yes_is_never_written_with_class_ordinary_or_no_class():
    bad = []
    for label in C3_LABELS:
        for k in ("ordinary", NO_CLASS, "declaration:other", None):
            for assumed in (True, False):
                res = attempt(_pf("x", label, options=YN), FakeAsk(lambda v, k=k, a=assumed: say("Yes", "assumption", "", a, klass=k)))
                if shown(res) == "Yes":
                    bad.append((label, k, f"assumed={assumed}", what(res)))
        res = attempt(_pf("x", label, options=YN), FakeAsk())
        if shown(res) == "Yes":
            bad.append((label, "silent", what(res)))
    assert not bad, report(bad)


def test_a1_c3_with_both_keys_the_owners_none_applies_is_written_and_a_true_history_is_left_alone():
    # D-212 U2 / U3 / U4 + U9 (replaces "both keys: code writes the owner's none-applies No"): the model's Yes differs
    # from the reader's No -> ONE confirmation; pick No -> No (assumed); unusable -> empty; never Yes. U9: "Any pending
    # litigation ..." is no canonical frame (no reading): the differing confirmation gets the meaning call on BOTH
    # values (U8b), so 3 calls instead of 1; the other three wordings keep their reading and 1 call.
    for label in C3_LABELS:
        canonical = not label.startswith("Any pending")
        ask = FakeAsk(lambda v: lie("Yes", "declaration:other"), pick=pick_faithful("No", "No"))
        res = attempt(_pf("x", label, options=YN), ask)
        assert shown(res) == "No" and res.assumed and len(ask.picks) == (1 if canonical else 3), (label, what(res), len(ask.picks))
        ask = FakeAsk(lambda v: lie("Yes", "declaration:other"), pick=pick_by("", ""))
        res = attempt(_pf("x", label, options=YN), ask)
        assert shown(res) == "" and len(ask.picks) == 1, (label, what(res))
    # an unclassed question the code key does not claim is the model's own answer
    res = attempt(_pf("x", "Have you ever visited Singapore?", options=YN), FakeAsk(lambda v: say("Yes", "resume", "", klass="ordinary")))
    assert shown(res) == "Yes", what(res)


# ================================================================== (20) C4: contradicting keys

def test_a1_c4_nda_willingness_is_ordinary_the_models_protected_class_is_dropped_and_yes_stays():
    p = profile_with(declarations__willing_to_sign_nda=True)
    for klass in ("declaration:non_compete", "declaration:other"):
        ask = FakeAsk(lambda v, k=klass: say("Yes", "profile", "profile:declarations.willing_to_sign_nda", klass=k))
        res = attempt(_pf("n", "Are you willing to sign an NDA?", options=YN), ask, p)
        assert shown(res) == "Yes", (klass, what(res))
        assert not ask.picks, f"no confirm call for a willingness question: {ask.picks}"


def test_a1_c4_expected_salary_named_as_current_by_the_model_takes_t_from_the_expected_figure_and_never_stops():
    bad = []
    for value, basis in (("5000", "profile"), ("9000", "assumption")):
        res = attempt(_pf("s", "Expected salary", "TEXT"), FakeAsk(lambda v, x=value, b=basis: say(x, b, "profile:pay.expected_salary" if b == "profile" else "", b == "assumption", klass="owner_fact:salary_current")))
        v = shown(res)
        if is_stop(res) or "5000" not in v or "9000" in v:
            bad.append((value, basis, what(res)))
    assert not bad, report(bad)


# ================================================================== (21) C5: one box, two consents

COMBINED_MARKETING = "I agree to the Privacy Policy and to receive marketing communications"
COMBINED_RETENTION = "I agree to the Privacy Policy and to keep my details for future roles"


def _details():
    from jobscraper.apply.contracts import CONSENT_REFUSED_DETAILS
    return CONSENT_REFUSED_DETAILS


def test_a1_c5_a_required_combined_box_with_marketing_refused_ends_consent_refused_naming_marketing():
    bad = []
    for name, ask in (("silent", FakeAsk()), ("ticks, consent_privacy", FakeAsk(lambda v: lie("true", "consent_privacy"))),
                      ("ticks, marketing", FakeAsk(lambda v: lie("true", "marketing"))),
                      ("ticks, ordinary", FakeAsk(lambda v: lie("true", "ordinary"))), ("ticks, no class", FakeAsk(lambda v: lie("true", NO_CLASS)))):
        res = attempt(_pf("c", COMBINED_MARKETING, "CHECKBOX"), ask, profile_with(consents__talent_pool_opt_in=DELETE))
        if not stop_is(res, "consent_refused", "consents.talent_pool_opt_in") or res.detail != _details()["consents.talent_pool_opt_in"]:
            bad.append((name, what(res)))
    assert not bad, report(bad)


def test_a1_c5_the_same_box_optional_is_left_unticked_and_with_every_consent_agreed_it_is_ticked():
    res = attempt(_pf("c", COMBINED_MARKETING, "CHECKBOX", required=False), FakeAsk(lambda v: lie("true", "consent_privacy")),
                  profile_with(consents__talent_pool_opt_in=DELETE))
    assert is_unticked(res), what(res)
    res = attempt(_pf("c", COMBINED_MARKETING, "CHECKBOX"), FakeAsk(), profile_with(consents__talent_pool_opt_in=True))
    assert is_ticked(res), what(res)


def test_a1_c5_a_combined_box_with_retention_refused_names_the_retention_detail():
    p = profile_with(consents__data_retention_consent=False)
    for name, ask in (("silent", FakeAsk()), ("ticks, ordinary", FakeAsk(lambda v: lie("true", "ordinary")))):
        res = attempt(_pf("c", COMBINED_RETENTION, "CHECKBOX"), ask, p)
        assert stop_is(res, "consent_refused", "consents.data_retention_consent"), (name, what(res))
        assert res.detail == _details()["consents.data_retention_consent"], (name, what(res))


# ================================================================== (22) C6: self-ID synonyms and dead ends

def test_a1_c6_a_synonym_option_is_the_owners_option_through_the_confirm_pick():
    bad = []
    for edits, label, options, model, want in (
            ({"identity__gender": "male"}, "Gender", ("Man", "Woman", "Non-binary"), "Woman", "Man"),
            ({"identity__gender": "male"}, "Gender", ("Man", "Woman", "Non-binary"), "Man", "Man"),
            ({"singapore_status__marital_status": "single"}, "Marital status", ("Single (never married)", "Married", "Divorced"),
             "Married", "Single (never married)")):
        for klass in ("self_id", "ordinary"):
            k = (f"self_id:gender" if "Gender" in label else "self_id:marital") if klass == "self_id" else "ordinary"
            ask = FakeAsk(lambda v, m=model, k=k: lie(m, k), pick=lambda q, w, o, x=want: x)
            res = attempt(_pf("g", label, "DROPDOWN", options=options), ask, profile_with(**edits))
            if shown(res) != want:
                bad.append((label, model, klass, "want", want, what(res)))
    assert not bad, report(bad)


def test_a1_c6_a_required_gender_list_without_a_truthful_option_ends_validation_error_with_the_detail():
    from jobscraper.apply.contracts import ReasonCode
    bad = []
    for label, kind, options in (("Gender", "gender", ("Male", "Female", "Other")), ("Race", "race", ("Chinese", "Malay", "Indian", "Other"))):
        for name, ask in (("silent", FakeAsk()), ("model guesses", FakeAsk(lambda v, o=options: lie(o[0], f"self_id:{kind}")))):
            res = attempt(_pf("g", label, "DROPDOWN", options=options), ask)     # profile: decline
            if not (is_stop(res) and res.reason is ReasonCode.VALIDATION_ERROR
                    and res.detail.startswith(f"no {kind} option matches your profile") and res.detail.endswith("on Application")):
                bad.append((label, name, what(res)))
    assert not bad, report(bad)


def test_a1_c6_an_optional_self_id_list_with_no_truthful_option_is_left_empty():
    res = attempt(_pf("g", "Gender", "DROPDOWN", required=False, options=("Male", "Female", "Other")),
                  FakeAsk(lambda v: lie("Male", "self_id:gender")))
    assert is_empty(res), what(res)


# ================================================================== (25) C9: owner facts the profile lacks

def test_a1_c9_ssn_tax_id_driver_licence_and_employee_id_stop_owner_fact_missing_never_an_invented_value():
    bad = []
    for label, which in (("Social security number", "national_id"), ("Tax ID", "national_id"),
                         ("Driver licence number", "other_id"), ("Employee ID", "other_id"), ("Tax number", "national_id")):
        for k in (f"owner_fact:{which}", "ordinary", NO_CLASS):
            res = attempt(_pf("i", label, "TEXT"), FakeAsk(lambda v, k=k: lie("123-45-6789", k)))
            if not stop_is(res, "owner_fact_missing") or "123-45" in str(res.detail):
                bad.append((label, k, what(res)))
        res = attempt(_pf("i", label, "TEXT"), FakeAsk())
        if not stop_is(res, "owner_fact_missing"):
            bad.append((label, "silent", what(res)))
    assert not bad, report(bad)
