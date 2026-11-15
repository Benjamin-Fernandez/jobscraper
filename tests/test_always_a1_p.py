"""Q-121 Amendment A1, the Coordinator's NEW rulings P1-P3, P5, F1-F4, C, M2, M7 after the second code
review (docs/reviews/Q-121-A1-code.md, H1 H2 H3 M1 M2 M5 M6 M7 L3 L4). They replace the engineer's
departure R-f (2). Every pin is RED on int/Q-121 8a27495 by design and turns green when
`eng/Q-121-A1-fix1` lands; a pin still red after that is a DEFECT. Fakes only (the scripted `ask`),
sample profile, made-up employer "Example Employer", no model, no network, no browser.

Conditions of a model reply, as in the review: R = right value + right class, W = wrong value + right
class, O = wrong value + class `ordinary`, M = wrong value + no class. The fake scripts the model
reply and the confirmation pick per call and every pin asserts the number of calls.
Verify: python tests/run_tests.py -k always_a1_p
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, pick_by, pick_faithful, profile_with, report, say, shown,
    what, with_text, DELETE, _pf, _profile)

CONFLICT = "Do you declare any conflict of interest?"           # a tentative reader
PLAIN = "Have you ever been convicted of a criminal offence?"     # a confident reader, no negation token


def _conditions(klass, right, wrong):
    """(name, model value, class) for R, W, O, M."""
    return (("R", right, klass), ("W", wrong, klass), ("O", wrong, "ordinary"), ("M", wrong, NO_CLASS))


# ================================================================== P1 / P2: a stray negation token

H1_ROWS = (   # (label, class) every wording of review H1; the owner's truth is "No" (none applies)
    ("Have you been convicted of an offence that is not yet spent?", "declaration:criminal_record"),
    ("Have you ever been convicted of a criminal offence? Please do not include spent convictions.", "declaration:criminal_record"),
    ("Have you ever been convicted of a criminal offence (not including minor traffic offences)?", "declaration:criminal_record"),
    ("Have you ever been convicted of a criminal offence? (Do not answer yes for traffic offences)", "declaration:criminal_record"),
    ("Have you ever been declared bankrupt and not been discharged?", "declaration:bankruptcy"),
    ("Are you currently a politically exposed person? Note: do not answer for family members.", "declaration:pep"),
    ("Is there any reason you could not work for us, such as a criminal conviction?", "declaration:criminal_record"),
    ("Is anything stopping you from declaring that you are not bankrupt?", "declaration:bankruptcy"),
)


def test_p1_a_stray_negation_token_never_makes_code_write_the_adverse_yes_in_any_condition_or_confirm():
    bad = []
    for label, klass in H1_ROWS:
        for name, value, k in _conditions(klass, "No", "Yes"):
            for pick in ("No", "Yes", ""):
                if name != "R" and pick == "Yes":
                    continue          # a confirmation that AGREES with a wrong first answer is written (P2/P3, residual R3)
                ask = FakeAsk(lambda v, x=value, kk=k: lie(x, kk), pick=lambda q, w, o, p=pick: p)
                res = attempt(_pf("p", label, options=YN), ask)
                if shown(res) == "Yes":
                    bad.append((label[:55], name, f"confirm={pick!r}", "the adverse Yes was written", what(res)))
    assert not bad, report(bad, 10)


# The four wordings of review H1 (docs/reviews/Q-121-A1-code.md) where the negation sits ONLY in a trailing
# note or aside: it does not invert the question, so the reader reads the question itself (option No)
# and the field is a P2 field. The other four rows hold the negation inside the question: the reader
# has no reading of it -> P3 (one confirmation always).
H1_TRAILING_NOTE = (H1_ROWS[1], H1_ROWS[2], H1_ROWS[3], H1_ROWS[5])
H1_IN_QUESTION = (H1_ROWS[0], H1_ROWS[4], H1_ROWS[6], H1_ROWS[7])


def test_p2_the_h1_rows_split_into_four_trailing_notes_and_four_negations_inside_the_question():
    assert all(("do not include" in r[0] or "(not including" in r[0] or "(Do not answer" in r[0] or "Note: do not" in r[0])
               for r in H1_TRAILING_NOTE), H1_TRAILING_NOTE
    assert not any(("do not include" in r[0] or "(not including" in r[0] or "(Do not answer" in r[0] or "Note: do not" in r[0])
                   for r in H1_IN_QUESTION), H1_IN_QUESTION


def test_p2_a_negation_token_with_the_model_right_costs_no_call_when_the_reader_has_the_same_option():
    """D-212 U1 / U6 (replaces D-211 "in-question negations: ONE confirmation, agree -> written"): a call is
    skipped ONLY when the model's first answer equals the reader's option. On a trailing-note row the model's
    No equals the reader's No: written, ZERO calls, whatever a confirmation would have said (the note only
    narrows the question, D-212 N3). A negation INSIDE the question leaves the reader with no option (U6):
    even a RIGHT model gets ONE confirmation, and a confirmation that agrees gets ONE meaning call; only a
    "no" writes the No (assumed, three-call note); "yes" / unusable -> empty; a confirmation that differs
    from the first answer -> empty (U8 adds a meaning call on the confirmation's value: 1 or 2 calls). Never Yes."""
    bad = []
    for label, klass in H1_TRAILING_NOTE:
        for k in (klass, "ordinary", NO_CLASS):
            for pick in ("No", "Yes", ""):
                ask = FakeAsk(lambda v, kk=k: lie("No", kk), pick=lambda q, w, o, p=pick: p)
                res = attempt(_pf("p", label, options=YN), ask)
                if is_stop(res) or shown(res) != "No" or ask.picks or len(ask.sent) != 1:
                    bad.append((label[:55], k, f"confirm={pick!r}", "U1: equal answer, no call", what(res),
                                f"picks={len(ask.picks)}", f"calls={len(ask.sent)}"))
    for label, klass in H1_IN_QUESTION:
        for k in (klass, "ordinary", NO_CLASS):
            for meaning, want in (("no", "No"), ("yes", ""), ("", "")):
                ask = FakeAsk(lambda v, kk=k: lie("No", kk), pick=pick_by("No", meaning))
                res = attempt(_pf("p", label, options=YN), ask)
                if is_stop(res) or shown(res) != want or (want and not res.assumed) or len(ask.picks) != 2 or len(ask.sent) != 1:
                    bad.append((label[:55], k, f"U6: confirm agrees, meaning {meaning!r}", what(res),
                                f"picks={len(ask.picks)}", f"calls={len(ask.sent)}"))
            for pick in ("", "Yes"):
                ask = FakeAsk(lambda v, kk=k: lie("No", kk), pick=pick_by(pick, ""))
                res = attempt(_pf("p", label, options=YN), ask)
                if shown(res) != "" or not 1 <= len(ask.picks) <= 2:
                    bad.append((label[:55], k, f"U6: confirm={pick!r}", "differ / unusable -> empty", what(res), f"picks={len(ask.picks)}"))
    assert not bad, report(bad, 10)


def test_u6_a_negation_inside_the_question_is_no_longer_a_residual_an_agreed_yes_needs_the_meaning_call():
    """D-212 U6 (replaces test_p3_accepted_residual_a_negation_inside_the_question_*): review H1's wrong Yes on
    the four in-question negations. The model's Yes and the confirmation's Yes AGREE; there is no reading,
    so the agreed value gets ONE meaning call. "no" -> Yes written (assumed): that is the model's own claim
    three times over, not a code shortcut. "yes" or unusable -> empty. Exactly 2 pick calls, never 1."""
    bad = []
    for label, klass in H1_IN_QUESTION:
        for k in (klass, "ordinary", NO_CLASS):
            for meaning, want in (("no", "Yes"), ("yes", ""), ("", "")):
                ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("Yes", meaning))
                res = attempt(_pf("p", label, options=YN), ask)
                if shown(res) != want or len(ask.picks) != 2 or (want and not res.assumed):
                    bad.append((label[:55], k, f"meaning {meaning!r}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_p2_a_wrong_model_yes_on_a_trailing_note_row_gets_one_confirmation_and_never_goes_out_as_yes_unchecked():
    """The model's Yes DIFFERS from the reader's No: ONE confirmation. A pick equal to the reader's No is
    written (assumed); an unusable pick -> the protective end (empty). A pick that AGREES with the Yes is the
    V case (a meaning call, pinned in test_always_a1_v.py): with no usable meaning answer, never Yes."""
    bad = []
    for label, klass in H1_TRAILING_NOTE:
        for k in (klass, "ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("No"))
            res = attempt(_pf("p", label, options=YN), ask)
            if is_stop(res) or shown(res) != "No" or not res.assumed or len(ask.picks) != 1:
                bad.append((label[:55], k, "confirm No", what(res), len(ask.picks)))
            for pick in ("", "Yes"):
                ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by(pick, ""))
                res = attempt(_pf("p", label, options=YN), ask)
                # U10 (fix8): the trailing-note wordings are canonical frames: a confirmation that AGREES with the
                # model's Yes goes against the frame's reading, a veto with NO meaning call (was 2 picks, now 1)
                if shown(res) != "" or len(ask.picks) != 1:
                    bad.append((label[:55], k, f"confirm={pick!r}, meaning unusable", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_p1_help_text_with_a_negation_token_counts_the_same_a_call_only_when_the_answers_differ():
    """D-211 P1/P2: a negation in the HELP TEXT counts like one in the label (no silent override with no call
    when the keys agree). The help note is a trailing note, so the reader reads the question (option No).
    The model's No equals it: written, ZERO calls. The model's wrong Yes: ONE confirmation; the pick No
    writes No (assumed); an unusable pick -> empty; never Yes."""
    note = "Please do not include spent convictions."
    mk = lambda: with_text(_pf("p", PLAIN, options=YN), description=note)           # noqa: E731
    ask = FakeAsk(lambda v: lie("No", "declaration:criminal_record"), pick=lambda q, w, o: "No")
    res = attempt(mk(), ask)
    assert shown(res) == "No" and not ask.picks and len(ask.sent) == 1, (what(res), len(ask.picks))
    ask = FakeAsk(lambda v: lie("Yes", "declaration:criminal_record"), pick=pick_by("No"))
    res = attempt(mk(), ask)
    assert shown(res) == "No" and res.assumed and len(ask.picks) == 1, (what(res), len(ask.picks))
    ask = FakeAsk(lambda v: lie("Yes", "declaration:criminal_record"), pick=pick_by(""))
    res = attempt(mk(), ask)
    assert shown(res) == "" and len(ask.picks) == 1, (what(res), len(ask.picks))


def test_p1_control_a_plain_label_with_both_keys_a_confident_reader_and_yes_no_options_needs_no_second_call():
    """D-212 U1 / U2 (replaces D-211 P1 "a plain label, both keys, a confident reader: code writes its own No with
    no second call"): the ONLY thing that skips a call is the model's answer equal to the reader's option. A
    model No on a plain label: written, ZERO calls. A model Yes: ONE confirmation call, whatever the label
    and the keys; pick No -> No (assumed), never Yes."""
    bad = []
    for label in (PLAIN, "Are you a politically exposed person?", "Have you ever been declared bankrupt?"):
        ask = FakeAsk(lambda v: lie("No"), pick=pick_by("Yes", "no"))           # the class defaults to the code key
        res = attempt(_pf("p", label, options=YN), ask)
        if shown(res) != "No" or ask.picks or len(ask.sent) != 1:
            bad.append((label, "model right", what(res), len(ask.picks), len(ask.sent)))
        ask = FakeAsk(lambda v: lie("Yes"), pick=pick_by("No", ""))
        res = attempt(_pf("p", label, options=YN), ask)
        if shown(res) != "No" or not res.assumed or len(ask.picks) != 1 or len(ask.sent) != 1:
            bad.append((label, "model wrong", what(res), len(ask.picks), len(ask.sent)))
    assert not bad, report(bad)


def test_p2_a_tentative_reader_gets_one_confirmation_when_the_models_answer_differs_from_the_readers_option():
    # the model's Yes differs from the reader's No -> ONE call; the pick that equals the reader's No is
    # written (assumed); "" / unusable -> the protective end (empty for a tentative reader), never Yes
    # U9 / U8b: CONFLICT ("Do you declare ...") is no canonical frame, so the differing confirmation (No) gets the meaning
    # call on BOTH values (No -> "no", Yes -> "yes"): 3 calls, then No is written (assumed)
    ask = FakeAsk(lambda v: lie("Yes"), pick=pick_faithful("No", "No"))
    res = attempt(_pf("d", CONFLICT, options=YN), ask)
    assert shown(res) == "No" and res.assumed and len(ask.picks) == 3, (what(res), len(ask.picks))
    for pick in ("", "Maybe"):
        ask = FakeAsk(lambda v: lie("Yes"), pick=lambda q, w, o, p=pick: p)
        res = attempt(_pf("d", CONFLICT, options=YN), ask)
        assert shown(res) == "" and len(ask.picks) == 1, (pick, what(res), len(ask.picks))


# ================================================================== P3: H unknown

BARE = (("Criminal record", "declaration:criminal_record"), ("Bankruptcy", "declaration:bankruptcy"),
        ("PEP status", "declaration:pep"), ("Politically exposed person (PEP)", "declaration:pep"),
        ("Non-compete agreement", "declaration:non_compete"))
UNKNOWN_H = (   # label, RIGHT value, ADVERSE value, class, options
    ("Is it untrue that you have never been bankrupt?", "No", "Yes", "declaration:bankruptcy", YN),
    ("Do you deny that you are a politically exposed person?", "Yes", "No", "declaration:pep", YN),
    ("Is it false that you have no criminal record?", "No", "Yes", "declaration:criminal_record", YN),
    ("Es-tu une personne politiquement exposée ?", "Non", "Oui", "declaration:pep", ("Oui", "Non")),
)


def test_p3_bare_noun_labels_never_end_empty_for_a_right_model_and_never_yes_for_a_wrong_one():
    """Review M1 + H2, D-212 U1 / U3 / U6 (replaces "H is known or first answer and confirmation agree ->
    written with no further call"): "Criminal record" etc. is a bare noun. When the reader reads it and the
    model's No equals its option: written, no call. When it has no reading: ONE confirmation, and a
    confirmation that AGREES gets ONE meaning call: model right + confirm No + meaning "no" -> No (never
    empty). A flipped confirmation, an unusable one and a "yes" / unusable meaning reply end empty. A
    wrong model never gives Yes (the confirmation that sides with its Yes is the accepted triple vote)."""
    bad = []
    for label, klass in BARE:
        for name, value, k in _conditions(klass, "No", "Yes"):
            for pick in ("No", "Yes", ""):
                if name != "R" and pick == "Yes":
                    continue          # model wrong + confirmation agreeing: the meaning call decides (U3), pinned in test_u6_*
                meaning = "no" if pick == value else ""
                ask = FakeAsk(lambda v, x=value, kk=k: lie(x, kk), pick=pick_by(pick, meaning))
                res = attempt(_pf("p", label, options=YN), ask)
                if shown(res) == "Yes" or (name == "R" and pick == "No" and shown(res) != "No") or len(ask.picks) > 2:
                    bad.append((label, name, f"confirm={pick!r}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_p3_work_authorization_with_no_country_is_not_vetoed_for_a_right_model_answer():
    """Ruling W (D-211, being built on eng/Q-121-A1-fix1; RED until then = a defect): the truth comes from the
    nationality rule (a citizen of Singapore, no visa needed) and the options can be classified, so a value
    that contradicts it in EITHER direction is vetoed: an under-claim ("Not authorized to work") too, with
    one key (O, M) as with both (W). A right model answer is written."""
    options = ("Authorized to work without sponsorship", "Authorized to work with sponsorship", "Not authorized to work")
    bad = []
    for label in ("Work authorization", "Work authorisation status"):
        for name, value, k in _conditions("work_right", options[0], options[2]):
            ask = FakeAsk(lambda v, x=value, kk=k: lie(x, kk), pick=lambda q, w, o: options[0])
            res = attempt(_pf("w", label, "DROPDOWN", options=options), ask)
            if shown(res) == options[2] or (name == "R" and shown(res) != options[0]):
                bad.append((label, name, what(res)))
    assert not bad, report(bad)


def test_p3_h_unknown_first_answer_and_confirmation_agree_written_differ_the_protective_end_one_call():
    """D-212 U3 / U6 (replaces D-211 P3 "agree -> written, differ -> the protective end, one call"): no code
    reading -> ONE confirmation. It AGREES with the first answer -> ONE meaning call: "no" -> written
    (assumed), "yes" / unusable -> empty (so a right model + the same confirmation + meaning "no" -> the right
    value, 2 calls). It DIFFERS (the right model + a flipped confirmation, or a wrong model + the right one) or
    is unusable -> empty after 1 call (U8 adds a meaning call on the confirmation's value: 1 or 2 calls).
    Every row under the model's declared class; the English rows also under class `ordinary`. The French row
    under class `ordinary` is the accepted R2 / M8 residual, pinned separately below."""
    bad = []
    for label, right, adverse, klass, options in UNKNOWN_H:
        for k in ((klass,) if label.startswith("Es-tu") else (klass, "ordinary")):
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(right, "no"))
            res = attempt(_pf("p", label, options=options), ask)
            if shown(res) != right or not res.assumed or len(ask.picks) != 2:
                bad.append((label, k, "agree + meaning no", what(res), len(ask.picks)))
            for meaning in ("yes", ""):
                ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(right, meaning))
                res = attempt(_pf("p", label, options=options), ask)
                if shown(res) != "" or len(ask.picks) != 2:
                    bad.append((label, k, f"agree + meaning {meaning!r}", what(res), len(ask.picks)))
            # right model, a confirmation that flips to the adverse option: never the adverse option
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(adverse, ""))
            res = attempt(_pf("p", label, options=options), ask)
            if shown(res) not in ("",) or not 1 <= len(ask.picks) <= 2:
                bad.append((label, k, "right model, flipped confirm", what(res), len(ask.picks)))
            # wrong model, the confirmation says the right one: they DIFFER -> empty, never "the pick because it differs"
            ask = FakeAsk(lambda v, kk=k, a=adverse: lie(a, kk), pick=pick_by(right, ""))
            res = attempt(_pf("p", label, options=options), ask)
            if shown(res) != "" or not 1 <= len(ask.picks) <= 2:
                bad.append((label, k, "wrong model, right confirm", what(res), len(ask.picks)))
            # unusable confirmation
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by("", ""))
            res = attempt(_pf("p", label, options=options), ask)
            if shown(res) != "" or len(ask.picks) != 1:
                bad.append((label, k, "unusable confirm", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_p3_accepted_residual_a_non_english_adverse_question_the_model_calls_ordinary_keeps_the_models_answer():
    """DOCUMENTS an accepted residual (D-211 P3): a French question the model labels `ordinary`, which no code
    key frames, is not a declaration for the code at all: the model's answer stands (assumed), with NO
    confirmation call. A wrong "Oui" written here is the residual the Coordinator accepted; the pin exists so
    that a change to it (a fix or a regression) is seen. The model naming the class (`declaration:pep`) is
    pinned in the test above and is not affected."""
    label, right, adverse, _klass, options = UNKNOWN_H[3]
    for said in (right, adverse):
        ask = FakeAsk(lambda v, x=said: lie(x, "ordinary"), pick=pick_by("Non"))
        res = attempt(_pf("p", label, options=options), ask)
        assert shown(res) == said and res.assumed and not ask.picks, (said, what(res), len(ask.picks))



# ================================================================== P5: a silent model, tentative reader

def test_p5_a_silent_model_on_a_tentative_reader_gets_the_confirmation_pick_only_if_it_equals_the_readers_option():
    # U8 / U9: no reading, so the silent model's confirmation (No) gets ONE meaning call ("no") before it is written
    ask = FakeAsk(pick=pick_faithful("No", "No"))
    res = attempt(_pf("d", CONFLICT, options=YN), ask)
    assert shown(res) == "No" and res.assumed and len(ask.picks) == 2, (what(res), len(ask.picks))
    # an unusable confirmation: 1 call, empty. A confirmation "Yes" (the contradiction) gets its own meaning call
    # (U8: no reading), which here repeats "Yes" = "yes, it states the conflict": 2 calls, empty, never Yes written
    for pick, calls in (("", 1), ("Yes", 2)):
        ask = FakeAsk(pick=lambda q, w, o, p=pick: p)
        res = attempt(_pf("d", CONFLICT, options=YN), ask)
        assert shown(res) == "" and len(ask.picks) == calls, (pick, what(res), len(ask.picks))


# ================================================================== F1 / F2: the owner-fact key is the applicant's OWN fact

NOT_OWN = (   # (label, type, the model's correct value)
    ("Company address", "TEXT", "1 Raffles Quay"), ("Employer address", "TEXT", "1 Raffles Quay"),
    ("School address", "TEXT", "50 Nanyang Avenue"), ("Address of institution", "TEXT", "50 Nanyang Avenue"),
    ("Employer phone number", "TEXT", "65551234"), ("Company phone", "TEXT", "65551234"),
    ("School contact number", "TEXT", "67901234"), ("Employer postal code", "TEXT", "048583"),
    ("Postal code of company", "TEXT", "048583"), ("Age at graduation", "TEXT", "23"),
    ("Age of your oldest project", "TEXT", "3"), ("Mobile phone model", "TEXT", "iPhone 13"),
    ("Phone brand you use", "TEXT", "Apple"), ("Street you grew up on", "TEXT", "Orchard"),
    ("Pay grade of the role", "TEXT", "E3"), ("Salary range of the role you applied for", "TEXT", "3000-4000"),
)
IN_ENTRY = (("Address", "1 Raffles Quay"), ("Phone number", "65551234"), ("Postal code", "048583"))


def test_f1_a_fact_that_is_not_the_applicants_own_keeps_the_models_correct_value_in_every_condition():
    bad = []
    for label, tn, value in NOT_OWN:
        for k in ("ordinary", NO_CLASS):
            for pick in ("", "No"):
                ask = FakeAsk(lambda v, x=value, kk=k: say(x, "resume", "", klass=kk), pick=lambda q, w, o, p=pick: p)
                res = attempt(_pf("n", label, tn), ask)
                if shown(res) != value:
                    bad.append((label, k, f"confirm={pick!r}", "want", value, what(res)))
    assert not bad, report(bad, 10)


def test_f1_address_phone_and_postal_code_inside_a_work_experience_education_or_reference_group_are_not_the_applicants():
    bad = []
    for group, title in (("experience[0]", "Work experience"), ("education[0]", "Education"), ("reference[0]", "Referee")):
        for label, value in IN_ENTRY:
            for k in ("ordinary", NO_CLASS):
                ask = FakeAsk(lambda v, x=value, kk=k: say(x, "resume", "", klass=kk), pick=lambda q, w, o: "")
                res = attempt(_pf("n", label, "TEXT", group=group, group_title=title), ask)
                if shown(res) != value:
                    bad.append((group, label, k, "want", value, what(res)))
    assert not bad, report(bad, 10)


def test_f2_with_the_code_key_only_code_does_not_overwrite_one_confirmation_decides():
    """"Residential address" (the applicant's own) with the model answering under another class: ONE
    confirmation ("is this asking for the applicant's own address?"): yes -> the profile value; no or
    unusable -> the model's value, assumed."""
    bad = []
    for label, tn, invented, profile_value in (("Residential address", "TEXT", "5 Other Street", "1 Example Road"),
                                               ("Mobile number", "TEXT", "98765432", "91234567")):
        for pick, want, assumed in (("Yes", profile_value, None), ("No", invented, True), ("", invented, True)):
            ask = FakeAsk(lambda v, x=invented: lie(x, "ordinary"), pick=lambda q, w, o, p=pick: p)
            res = attempt(_pf("n", label, tn), ask)
            ok = profile_value in shown(res) if pick == "Yes" else shown(res) == want and res.assumed
            if is_stop(res) or not ok or len(ask.picks) != 1:
                bad.append((label, f"confirm={pick!r}", "want", want, what(res), len(ask.picks)))
    assert not bad, report(bad)


# ================================================================== F3 / F4

def test_f3_an_invented_text_grade_is_never_written_in_grade_cumulative_gpa_cgpa_final_grade():
    bad = []
    for label in ("Grade", "Cumulative GPA", "CGPA", "Final grade"):
        for invented in ("First Class", "Distinction"):
            res = attempt(_pf("g", label, "TEXT"), FakeAsk(lambda v, x=invented: lie(x, "owner_fact:grade")))
            if is_stop(res) or invented in shown(res) or shown(res) != "4.20 / 5.00":
                bad.append((label, invented, "want the profile grade", what(res)))
    assert not bad, report(bad)


def test_f4_city_right_after_postal_code_is_not_written_the_postal_code():
    bad = []
    for said, k in (("Singapore", "ordinary"), ("Singapore", None), (None, None)):
        ask = FakeAsk((lambda v, s=said, kk=k: lie(s, kk)) if said else None)
        res = attempt(with_text(_pf("c", "City", "TEXT"), context="Postal code"), ask)
        if shown(res) != "Singapore":
            bad.append((said, k, "want the city", what(res)))
    assert not bad, report(bad)


def test_f4_a_date_of_birth_label_with_a_format_hint_is_filled_in_that_format():
    bad = []
    for label in ("D.O.B. (DD/MM/YYYY)", "Date of birth (DD/MM/YYYY)"):
        for k in ("owner_fact:date_of_birth", "ordinary"):
            res = attempt(_pf("d", label, "TEXT"), FakeAsk(lambda v, kk=k: lie("1999-05-17", kk)))
            if shown(res) != "14/03/2002":
                bad.append((label, k, "want 14/03/2002", what(res)))
    assert not bad, report(bad)


# ================================================================== C: retention unset, silent acknowledgement

def test_c_retention_key_unset_the_models_value_is_written_assumed_for_both_wordings_and_shapes():
    bad = []
    p = profile_with(consents__data_retention_consent=DELETE)
    for label, tn, opts, said in (("May we keep your details on file for future roles?", "RADIO", YN, "Yes"),
                                  ("I agree to you keeping my CV for future vacancies", "CHECKBOX", (), "true"),
                                  ("I agree that you keep my details on file for future roles", "CHECKBOX", (), "true")):
        res = attempt(_pf("r", label, tn, options=opts), FakeAsk(lambda v, s=said: say(s, "default", "default:consent", False, "x")), p)
        if is_stop(res) or not res.assumed or "check" not in str(res.evidence):
            bad.append((label, what(res)))
    assert not bad, report(bad)


def test_c_a_silent_model_on_an_unframed_acknowledgement_or_certification_gets_yes_ticked_assumed():
    bad = []
    for label, tn in (("I have read and understood the above", "CHECKBOX"), ("I agree", "CHECKBOX"), ("I accept", "CHECKBOX"),
                      ("I confirm", "CHECKBOX"), ("I understand and agree", "CHECKBOX"), ("Do you acknowledge?", "RADIO"),
                      ("Please be advised that we process your data. Do you acknowledge?", "RADIO"),
                      ("Do you confirm that you have read the above?", "RADIO")):
        res = attempt(_pf("a", label, tn, options=YN if tn == "RADIO" else ()), FakeAsk())
        yes = shown(res) == "Yes" if tn == "RADIO" else is_ticked(res)
        if is_stop(res) or not yes or not res.assumed:
            bad.append((label, tn, what(res)))
    assert not bad, report(bad)


# ================================================================== M2: spouse / family declarations

SPOUSE = ("Is your spouse, parent or sibling employed by Example Employer?", "Does your spouse or partner work for Example Employer?",
          "Do you or your spouse hold shares in Example Employer?", "Is your manager a relative?",
          "Do you have a parent or guardian who is a politically exposed person?",
          "Are you, your spouse or your partner a politically exposed person?",
          "Is your spouse or a close family member a politically exposed person?")


def test_m2_a_spouse_or_family_declaration_is_a_declaration_a_wrong_yes_never_goes_out_in_all_four_conditions():
    # U9 (review 4 F1; replaces "R must be No with an unusable confirmation"): "Is your manager a relative?" and "Are you,
    # your spouse or your partner a PEP?" are no canonical frame, so a right "No" needs the confirmation and the
    # meaning call ("no") before it is written; with an unusable check it is left empty. A wrong Yes is never written
    # either way (the pep wording has a PEP truth sentence too, pinned by the same rows).
    bad = []
    for label in SPOUSE:
        for name, value, k in _conditions("declaration:relatives_at_company", "No", "Yes"):
            res = attempt(_pf("p", label, options=YN), FakeAsk(lambda v, x=value, kk=k: lie(x, kk), pick=lambda q, w, o: ""))
            if shown(res) == "Yes":
                bad.append((label[:55], name, "unusable check", what(res)))
            res = attempt(_pf("p", label, options=YN),
                          FakeAsk(lambda v, x=value, kk=k: lie(x, kk), pick=pick_faithful("No", "No")))
            if shown(res) == "Yes" or (name == "R" and shown(res) != "No"):
                bad.append((label[:55], name, "right confirmation, faithful meaning", what(res)))
    assert not bad, report(bad, 10)


# ================================================================== M7: options with no ASCII letters

def test_m7_options_with_no_ascii_letters_never_collapse_to_the_first_option():
    bad = []
    for said, want in (("否", "否"), ("是", "是")):
        res = attempt(_pf("q", "Are you currently studying part time?", "RADIO", options=("是", "否")),
                      FakeAsk(lambda v, s=said: lie(s, "ordinary")))
        if shown(res) != want:
            bad.append((said, want, what(res)))
    assert not bad, report(bad)
