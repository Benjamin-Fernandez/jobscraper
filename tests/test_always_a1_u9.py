"""Q-121 Amendment A1, the U9 round: the fourth review (docs/reviews/Q-121-A1-rulingU.md, F1-F6) and the fix4 build.

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step. Every pin keeps its
assertion on the HARMFUL value (a declaration the owner does not have, an over- or under-claim of work rights, an
answer written with no check). Expected values come from the rulings, never from what the code does:

  U1  the model's first answer equals the option the READER takes as the owner's truth -> written, no call.
  U2  otherwise (they differ, no reading, silent model) -> ONE confirmation stating the owner's truth.
  U3  the confirmation equals the reader's option -> written (assumed); equals the model's first answer -> ONE
      meaning call: "no" -> written (assumed), "yes" / unusable -> the protective end (U4: empty, never code's reading).
  U8b no reading + a confirmation that differs from the first answer -> a meaning call on BOTH values; written only
      when its own call says "no" and the other's says "yes".
  U9  (F1) the reader's reading counts ONLY for a label that matches a CANONICAL frame of the class and holds nothing
      that could change its meaning; every other wording has no reading. So such a wording is never written with 0
      calls, and a right answer plus ONE flipped confirmation never writes the wrong value.
  F2  `declaration:other` / class-less adverse history is "none applies" unless a profile declaration of the SAME kind
      is true: a repeat application is not a reason to leave "Have you ever been dismissed?" empty.
  F3  a military / National Service question has no declaration truth; F4 the two meaning sentences; F5 a transport
      failure inside a vote ends the page as one; F6 a pre-filled adverse option is never left after a failed vote.
  fix4 the forced class correction is for consent / marketing only; "Your / My" name, email, phone come from the
      profile before the model; every declaration class has a truth sentence.

`pick_faithful(confirm, right)` scripts the confirmation and a faithful meaning reply ("no" for the right value, "yes"
for any other). Fakes only: no model, no network, no browser, sample profile (a Singapore citizen: authorised in SG,
NOT authorised in the US, all declarations false), made-up names.
Verify: python tests/run_tests.py -k always_a1_u9
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, outcome, pick_by, pick_faithful, profile_with, report,
    say, shown, what, with_text, _pf, _profile)

CLASSES = ("right", "ordinary", NO_CLASS)


def _k(kind, right):
    return right if kind == "right" else kind


def _field(label, *, tn="RADIO", required=True, **kw):
    return _pf("u", label, tn, required=required, options=YN if tn == "RADIO" else (), **kw)


def _meaning_wanted(ask):
    return [p[1] for p in ask.picks if p[1].startswith("If the applicant answers")]


# ================================================================== F1: declarations with a word the reader does not know

# (label, the class, "keyed": code's own key finds the class). The owner's declarations are all false: the right
# answer to each is Yes. A wording code does not key (keyed False) is pinned under the model's class only; with the
# class `ordinary` / missing on BOTH keys the model's answer stands (the accepted R2 / M8 / F7 residual).
F1_DECL = (
    ("Is your criminal record satisfactory?", "declaration:criminal_record", True),
    ("Is your disciplinary record satisfactory?", "declaration:regulatory_disciplinary", True),
    ("Can you pass a criminal background check?", "declaration:criminal_record", True),
    ("Are you in compliance with all non-compete obligations?", "declaration:non_compete", True),
    ("Are you fully compliant with the conflict of interest policy?", "declaration:conflict_audit_independence", True),
    ("Are your relatives independent of Example Employer?", "declaration:relatives_at_company", True),
    ("Are you independent of Example Employer?", "declaration:conflict_audit_independence", False),
    ("Are you a fit and proper person?", "declaration:regulatory_disciplinary", False),
    ("Are you of good character?", "declaration:criminal_record", False),
    ("Are you financially solvent?", "declaration:bankruptcy", False),
)
RIGHT_YES, WRONG_NO = "Yes", "No"


def _decl_cells(rows=F1_DECL):
    for label, klass, keyed in rows:
        for kind in (CLASSES if keyed else ("right",)):
            yield label, kind, _k(kind, klass)


def test_u9_f1_declarations_a_wrong_no_is_never_written_with_no_call():
    """F1: "Is your criminal record satisfactory?" etc.: the reader's old option was the wrong No, so the model's lazy
    No was written with 0 calls and no mark. Now: a no-reading wording, so ONE confirmation + the meaning calls: the
    right confirmation (Yes) with faithful meaning replies -> Yes (assumed, 3 calls: U8b). Never "No", never 0 calls."""
    bad = []
    for label, kind, k in _decl_cells():
        ask = FakeAsk(lambda v, kk=k: lie(WRONG_NO, kk), pick=pick_faithful(RIGHT_YES, RIGHT_YES))
        res = attempt(_field(label), ask)
        if shown(res) != RIGHT_YES or not res.assumed or len(ask.picks) != 3:
            bad.append((label[:42], kind, "wrong No, right confirmation", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f1_declarations_a_wrong_no_with_an_agreeing_or_unusable_confirmation_ends_empty():
    """F1: the model's wrong No and a confirmation that AGREES with it get ONE meaning call, which a faithful reader
    answers "yes" (the No states the record is not satisfactory): empty. An unusable confirmation: empty after one
    call. Whatever the replies, the No is never written without a "no" meaning reply."""
    bad = []
    for label, kind, k in _decl_cells():
        ask = FakeAsk(lambda v, kk=k: lie(WRONG_NO, kk), pick=pick_faithful(WRONG_NO, RIGHT_YES))
        res = attempt(_field(label), ask)
        if shown(res) != "" or len(ask.picks) != 2:
            bad.append((label[:42], kind, "wrong No, agreeing confirmation", what(res), len(ask.picks)))
        ask = FakeAsk(lambda v, kk=k: lie(WRONG_NO, kk), pick=pick_by("", ""))
        res = attempt(_field(label), ask)
        if shown(res) != "" or len(ask.picks) != 1:
            bad.append((label[:42], kind, "wrong No, unusable confirmation", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f1_declarations_a_right_yes_and_one_flipped_confirmation_never_writes_the_wrong_no():
    """F1 (the review's `No~/1`): a RIGHT Yes followed by ONE flipped confirmation (No) used to write the reader's
    wrong option. Now a differing confirmation on a no-reading wording gets the meaning call on BOTH values: the
    faithful pair (Yes: "no", No: "yes") writes the Yes; two "no" replies, two "yes" replies or an unusable one end
    empty. The wrong No is written in none of them."""
    bad = []
    for label, kind, k in _decl_cells():
        ask = FakeAsk(lambda v, kk=k: lie(RIGHT_YES, kk), pick=pick_faithful(WRONG_NO, RIGHT_YES))
        res = attempt(_field(label), ask)
        if shown(res) != RIGHT_YES or len(ask.picks) != 3:
            bad.append((label[:42], kind, "right Yes, flipped confirmation, faithful", what(res), len(ask.picks)))
        for name, pick in (("both no", pick_by(WRONG_NO, "no")), ("both yes", pick_by(WRONG_NO, "yes")),
                           ("unusable", pick_by(WRONG_NO, ""))):
            ask = FakeAsk(lambda v, kk=k: lie(RIGHT_YES, kk), pick=pick)
            res = attempt(_field(label), ask)
            if shown(res) != "":
                bad.append((label[:42], kind, f"right Yes, flipped confirmation, meaning {name}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f1_declarations_right_model_right_confirmation_and_meaning_no_writes_the_yes_in_two_calls():
    """F1 control: a right Yes, the right confirmation and a "no" meaning reply -> Yes, assumed, exactly 2 calls (the
    price of an unrecognised wording); a "yes" or unusable meaning reply -> empty."""
    bad = []
    for label, kind, k in _decl_cells():
        ask = FakeAsk(lambda v, kk=k: lie(RIGHT_YES, kk), pick=pick_by(RIGHT_YES, "no"))
        res = attempt(_field(label), ask)
        if shown(res) != RIGHT_YES or not res.assumed or len(ask.picks) != 2:
            bad.append((label[:42], kind, "right/right/no", what(res), len(ask.picks)))
        for meaning in ("yes", ""):
            ask = FakeAsk(lambda v, kk=k: lie(RIGHT_YES, kk), pick=pick_by(RIGHT_YES, meaning))
            res = attempt(_field(label), ask)
            if shown(res) != "":
                bad.append((label[:42], kind, f"right/right/meaning {meaning!r}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f1_declarations_a_silent_model_is_asked_and_never_gets_the_wrong_no_from_code():
    """F1: a silent model on the KEYED wordings (the class is code's key): ONE confirmation, then ONE meaning call on
    the confirmation's value (U8): the right Yes with a "no" reply is written (assumed, 2 calls); a confirmation No
    is never written (its faithful meaning is "yes": empty)."""
    bad = []
    for label, klass, keyed in F1_DECL:
        if not keyed:
            continue
        ask = FakeAsk(pick=pick_faithful(RIGHT_YES, RIGHT_YES))
        res = attempt(_field(label), ask)
        if shown(res) != RIGHT_YES or not res.assumed or len(ask.picks) != 2:
            bad.append((label[:42], "silent, confirmation Yes", what(res), len(ask.picks)))
        ask = FakeAsk(pick=pick_faithful(WRONG_NO, RIGHT_YES))
        res = attempt(_field(label), ask)
        if shown(res) == WRONG_NO or shown(res) != "":
            bad.append((label[:42], "silent, confirmation No", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== F1: work rights with a word the reader does not know

# (label, the RIGHT answer for the sample: Singapore authorised, United States NOT authorised, "keyed")
F1_WORK = (
    ("Do you have any restrictions on your right to work in the United States?", "Yes", True),
    ("Is your right to work in the United States limited in any way?", "Yes", True),
    ("Is there any restriction on your right to work in Singapore?", "No", True),
    ("Are you restricted from working in the United States?", "Yes", False),
    ("Are you prohibited from working in the United States?", "Yes", False),
    ("Would you be working in the United States on a temporary visa?", "Yes", False),
    ("Are you currently on a student visa?", "No", False),
    ("Are you a foreign national requiring a work pass?", "No", False),
    ("Are you a foreigner?", "No", False),
)


# U10b (fix8): the two restriction wordings that are CANONICAL work-rights frames ("Do you have any restrictions on your
# right to work in <country>?", "Is your right to work in <country> limited in any way?"; Yes = NOT freely authorised).
# A frame is a reading: the right model answer costs 0 calls, a wrong one is overruled by ONE confirmation that equals the
# frame, and an agreeing wrong pair is a veto (U10: 1 call, no meaning call). The other wordings keep the U9 no-reading path.
def _framed(label):
    return label.startswith(("Do you have any restrictions on your right", "Is your right to work in"))


def _work_cells():
    for label, right, keyed in F1_WORK:
        wrong = "No" if right == "Yes" else "Yes"
        for kind in (CLASSES if keyed else ("right",)):
            yield label, right, wrong, kind, _k(kind, "work_right")


def test_u9_f1_work_rights_a_lazy_wrong_answer_is_never_written_with_no_call():
    """F1 (the review's `No/0` over-claim for a US posting and `Yes/0` under-claim for Singapore): "restrictions /
    limited / prohibited / temporary visa / student visa / foreigner" wordings have no reading. A wrong model answer is
    not written with 0 calls: the right confirmation + faithful meaning replies write the RIGHT value (3 calls)."""
    bad = []
    for label, right, wrong, kind, k in _work_cells():
        ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=pick_faithful(right, right))
        res = attempt(_field(label), ask)
        # U10b: a framed wording needs only the ONE confirmation that equals the frame (1 call); no frame: 3 calls (U8b)
        if shown(res) != right or len(ask.picks) != (1 if _framed(label) else 3):
            bad.append((label[:45], kind, f"wrong {wrong}, right confirmation", what(res), len(ask.picks)))
        ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=pick_faithful(wrong, right))
        res = attempt(_field(label), ask)
        # U10: the agreeing wrong pair against a frame is a veto with NO meaning call (1 call); no frame: 2 calls
        if shown(res) != "" or len(ask.picks) != (1 if _framed(label) else 2):
            bad.append((label[:45], kind, f"wrong {wrong}, agreeing confirmation", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f1_work_rights_a_right_answer_and_one_flipped_confirmation_never_writes_the_wrong_claim():
    """F1: a right model answer followed by ONE flipped confirmation: the meaning call on both values writes the right
    one; two equal replies or an unusable one end empty. The wrong claim (a work authorisation the profile does not
    give, or a restriction the owner does not have) is written in none of them."""
    bad = []
    for label, right, wrong, kind, k in _work_cells():
        ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_faithful(wrong, right))
        res = attempt(_field(label), ask)
        # U10b: a right model answer on a framed wording equals the frame: written with 0 calls (U1), whatever a
        # confirmation would say; no frame: the flipped confirmation costs 3 calls
        if shown(res) != right or len(ask.picks) != (0 if _framed(label) else 3):
            bad.append((label[:45], kind, "right, flipped confirmation, faithful", what(res), len(ask.picks)))
        for name, pick in (("both no", pick_by(wrong, "no")), ("both yes", pick_by(wrong, "yes")), ("unusable", pick_by(wrong, ""))):
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick)
            res = attempt(_field(label), ask)
            if shown(res) != (right if _framed(label) else "") or (_framed(label) and ask.picks):
                bad.append((label[:45], kind, f"right, flipped confirmation, meaning {name}", what(res)))
    assert not bad, report(bad, 10)


def test_u9_f1_work_rights_right_model_right_confirmation_and_meaning_no_writes_in_two_calls():
    bad = []
    for label, right, wrong, kind, k in _work_cells():
        ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(right, "no"))
        res = attempt(_field(label), ask)
        if _framed(label):      # U10b: the right answer on a frame is written with no call at all (U1)
            if shown(res) != right or ask.picks:
                bad.append((label[:45], kind, "framed right model: 0 calls", what(res), len(ask.picks)))
        elif shown(res) != right or not res.assumed or len(ask.picks) != 2:
            bad.append((label[:45], kind, "right/right/no", what(res), len(ask.picks)))
        ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(right, "yes"))
        res = attempt(_field(label), ask)
        if shown(res) != (right if _framed(label) else ""):
            bad.append((label[:45], kind, "right/right/yes", what(res)))
    assert not bad, report(bad, 10)


def test_u9_f1_work_rights_a_silent_model_never_gets_the_wrong_claim_from_a_keyed_wording():
    """F1: a silent model on the keyed wordings: the confirmation's value gets ONE meaning call (U8). The right value
    with a faithful reply is written (2 calls); the wrong value is never written."""
    bad = []
    for label, right, keyed in ((w[0], w[1], w[2]) for w in F1_WORK):
        if not keyed:
            continue
        wrong = "No" if right == "Yes" else "Yes"
        ask = FakeAsk(pick=pick_faithful(right, right))
        res = attempt(_field(label), ask)
        # U10b: a framed wording takes the confirmation that equals the frame (1 call); no frame: + the meaning call
        if shown(res) != right or len(ask.picks) != (1 if _framed(label) else 2):
            bad.append((label[:45], "silent, right confirmation", what(res), len(ask.picks)))
        ask = FakeAsk(pick=pick_faithful(wrong, right))
        res = attempt(_field(label), ask)
        if shown(res) == wrong or shown(res) != "":
            bad.append((label[:45], "silent, wrong confirmation", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== U9 controls: a canonical frame still costs nothing

CANON_DECL = (   # (label, class): all declarations false, so the right answer is No
    ("Have you ever been convicted of a criminal offence?", "declaration:criminal_record"),
    ("Are you a politically exposed person?", "declaration:pep"),
    ("Have you ever been declared bankrupt?", "declaration:bankruptcy"),
    ("Do you have any conflict of interest?", "declaration:conflict_audit_independence"),
    ("Are you bound by a non-compete agreement?", "declaration:non_compete"),
    ("Have you ever been dismissed from a job?", "declaration:other"),
)


def test_u9_control_a_canonical_declaration_frame_with_a_right_model_costs_no_call():
    """U1 / U9: "Have you ever been convicted ...?", "Are you a politically exposed person?" and the like are canonical:
    the reader's No equals the model's No -> written with ZERO calls, in every class condition."""
    bad = []
    for label, klass in CANON_DECL:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, kk=_k(kind, klass): lie("No", kk), pick=pick_by("Yes", "yes"))
            res = attempt(_field(label), ask)
            if shown(res) != "No" or ask.picks:
                bad.append((label[:45], kind, what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_control_a_canonical_declaration_frame_with_a_wrong_model_costs_one_confirmation():
    """U2 / U3 / U9: a canonical frame keeps its reading, so a model Yes is answered by ONE confirmation (the owner's
    truth) and the pick No is written (assumed). Never Yes."""
    bad = []
    for label, klass in CANON_DECL:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, kk=_k(kind, klass): lie("Yes", kk), pick=pick_by("No", "no"))
            res = attempt(_field(label), ask)
            if shown(res) != "No" or not res.assumed or len(ask.picks) != 1:
                bad.append((label[:45], kind, what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_control_a_canonical_work_rights_and_sponsorship_frame_costs_no_call_and_a_wrong_model_one():
    """U1 / U9 for work rights: "Are you legally authorised to work in <country>?" and "Will you ... require
    sponsorship ...?" are canonical. Singapore: Yes / No with 0 calls; the United States (not authorised): "No" with 0
    calls; an over-claim (Yes for the US) gets ONE confirmation and the pick "No" is written."""
    bad = []
    for label, klass, right in (("Are you legally authorised to work in Singapore?", "work_right", "Yes"),
                                ("Are you legally authorised to work in the United States?", "work_right", "No"),
                                ("Will you now or in the future require sponsorship to work in Singapore?", "sponsorship", "No")):
        wrong = "No" if right == "Yes" else "Yes"
        for kind in CLASSES:
            k = _k(kind, klass)
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(wrong, "yes"))
            res = attempt(_field(label), ask)
            if shown(res) != right or ask.picks:
                bad.append((label[:45], kind, "right model: no call", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=pick_by(right, "no"))
            res = attempt(_field(label), ask)
            if shown(res) != right or len(ask.picks) != 1:
                bad.append((label[:45], kind, "wrong model: one confirmation", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_control_a_canonical_tick_box_frame_with_a_right_model_costs_no_call_and_a_wrong_one_costs_one():
    """U1 / U2 for a box: "I have never been convicted of a criminal offence" ticked (the owner's truth) -> ticked with
    no call. A model that leaves it unticked -> ONE box confirmation ("Should the box ... be ticked?") and a "yes"
    ticks it (assumed). "I am a politically exposed person" ticked by the model -> never ticked unchecked: ONE
    confirmation, "no" unticks."""
    bad = []
    for kind in CLASSES:
        k = _k(kind, "declaration:criminal_record")
        ask = FakeAsk(lambda v, kk=k: lie("true", kk), pick=pick_by("no", "no"))
        res = attempt(_field("I have never been convicted of a criminal offence", tn="CHECKBOX"), ask)
        if not is_ticked(res) or ask.picks:
            bad.append((kind, "right tick", what(res), len(ask.picks)))
        ask = FakeAsk(lambda v, kk=k: lie("false", kk), pick=pick_by("yes", "no"))
        res = attempt(_field("I have never been convicted of a criminal offence", tn="CHECKBOX"), ask)
        if not is_ticked(res) or len(ask.picks) != 1:
            bad.append((kind, "unticked by the model, confirmation yes", what(res), len(ask.picks)))
        kp = _k(kind, "declaration:pep")
        ask = FakeAsk(lambda v, kk=kp: lie("true", kk), pick=pick_by("no", "no"))
        res = attempt(_field("I am a politically exposed person", tn="CHECKBOX"), ask)
        if is_ticked(res) or len(ask.picks) != 1:
            bad.append((kind, "wrong tick of the PEP box", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== F2: a repeat application

F2_LABELS = ("Have you ever been dismissed from a job?", "Have you ever been asked to resign?",
             "Do you have any pending legal proceedings?", "Have you ever been refused a visa?",
             "Are you currently under investigation by any regulator?")
F2_CONTEXTS = (   # (name, profile, rctx kwargs): the posting's employer, and what the profile / history holds
    ("previously applied here", None, {"previously_applied": True}),
    ("prior employment at the posting employer", None, {"employer_name": "Sample Analytics"}),
    ("a current employee of the posting employer", None, {"employer_name": "Sample Analytics", "previously_applied": True}),
    ("one true declaration (a PEP)", profile_with(declarations__pep=True), {}),
)


def test_u9_f2_a_repeat_application_answers_an_adverse_history_question_with_a_right_model_in_no_calls():
    """F2 (the review: 32 of 49 wordings ended EMPTY with a right model on a second application): with prior employment
    here, a previous application here, or one true declaration, "Have you ever been dismissed from a job?" and the
    like with a right "No" are ANSWERED No with the designed calls (canonical frame: none), in every class
    condition. Never empty, never Yes."""
    bad = []
    for name, prof, kw in F2_CONTEXTS:
        for label in F2_LABELS:
            for kind in CLASSES:
                ask = FakeAsk(lambda v, kk=_k(kind, "declaration:other"): lie("No", kk), pick=pick_by("No", "no"))
                res = attempt(_field(label), ask, prof, rctx_kw=dict(kw))
                if shown(res) != "No" or ask.picks:
                    bad.append((name, label[:40], kind, what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f2_a_repeat_application_with_a_wrong_yes_gets_the_none_applies_no_after_one_confirmation():
    """F2: the same contexts with a model Yes (the harmful value): ONE confirmation (the owner's truth: none applies)
    and the pick No is written, assumed. The Yes is never written."""
    bad = []
    for name, prof, kw in F2_CONTEXTS:
        for label in F2_LABELS:
            ask = FakeAsk(lambda v: lie("Yes", "declaration:other"), pick=pick_by("No", "no"))
            res = attempt(_field(label), ask, prof, rctx_kw=dict(kw))
            if shown(res) != "No" or not res.assumed or len(ask.picks) != 1:
                bad.append((name, label[:40], what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f2_a_non_canonical_adverse_question_on_a_repeat_application_takes_the_vote_not_the_empty_end():
    """F2 + U9: "Is there any reason you could not work for us?" has no canonical frame: a right model No takes the
    confirmation + ONE meaning call ("no"): No, assumed, 2 calls, in every repeat context. It is never left empty by
    the owner's truth being "unknown"."""
    bad = []
    for name, prof, kw in F2_CONTEXTS:
        ask = FakeAsk(lambda v: lie("No", "declaration:other"), pick=pick_by("No", "no"))
        res = attempt(_field("Is there any reason you could not work for us?"), ask, prof, rctx_kw=dict(kw))
        if shown(res) != "No" or not res.assumed or len(ask.picks) != 2:
            bad.append((name, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_u9_f2_the_prior_employment_rows_are_never_the_pool_but_a_true_row_of_the_same_kind_is():
    """F2: the truth for `other` is "none applies" unless a profile declaration of the SAME kind is true. A true row
    the named classes do not cover (here `tribunal_findings`) makes the truth unknown: a model's lazy "No" to
    "Have you ever been dismissed from a job?" is then NOT written with 0 calls (it is checked, ending empty when
    the check does not agree), where every prior-employment / applied-here context above answers it."""
    p = profile_with(declarations__tribunal_findings=True)
    ask = FakeAsk(lambda v: lie("No", "declaration:other"), pick=pick_by("Yes", "yes"))
    res = attempt(_field("Have you ever been dismissed from a job?"), ask, p)
    assert shown(res) != "No", ("a true row of the same kind: the lazy No is never written", what(res), len(ask.picks))
    assert shown(res) == "" or ask.picks, ("empty, or written only after a check", what(res), len(ask.picks))
