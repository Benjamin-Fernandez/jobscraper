"""Q-121 Amendment A1, the U round: ruling U of D-212 (code NEVER writes its own reading over the model's on its own
authority, for `declaration`, `work_right` and `sponsorship` by either key), ruling W, the third review's
N1-N6 / M6 tables (docs/reviews/Q-121-A1-fix1.md), U8 and fix2 A-E.

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step. Every pin keeps its
assertion on the HARMFUL value (a declaration that applies, a work-rights claim the profile does not give or an
inverted one, an applicant's own detail in another party's field, an invented grade). Expected values come from the
rulings, never from what the code does.

Calls (D-212): U1 the model's answer equals the option the reader takes as the owner's truth -> written, NO call (the
only thing that skips a call). U2 anything else -> ONE confirmation (a tick box: "Should the box ... be ticked? yes or
no"). U3 the confirmation equals the READER's option -> written (assumed); it equals the MODEL's first answer ->
ONE meaning call (reader contradicting OR no reading): "no" -> written (assumed, three-call note), "yes" / unusable
-> the protective end. U4 the protective end never writes code's reading: empty / unticked. U8 (red until built on
eng/Q-121-A1-fix1) with NO reading a confirmation that DIFFERS from the first answer gets the meaning call on the
CONFIRMATION's value.
`pick_by(confirm, meaning)` scripts the two kinds of call; `ask.picks` / `ask.pick_tasks` list them.
Fakes only: no model, no network, no browser, sample profile, made-up names.
Verify: python tests/run_tests.py -k always_a1_u
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, outcome, page, pick_by, pick_faithful, profile_with, report,
    say, shown, stop_is, what, with_text, _pf, _profile)

CLASSES = ("right", "ordinary", NO_CLASS)


def _k(kind, right):
    return right if kind == "right" else kind


# ================================================================== N1: a positive-polarity word gives the reader no reading

N1_ROWS = (   # (label, the class); the owner's truth is "no record", so the RIGHT answer is Yes
    ("Is your criminal record clean?", "declaration:criminal_record"),
    ("Do you have a clean criminal record?", "declaration:criminal_record"),
    ("Do you have a clear criminal record?", "declaration:criminal_record"),
    ("Do you have a spotless disciplinary record?", "declaration:regulatory_disciplinary"),
    ("Is your financial history clean (no bankruptcy)?", "declaration:bankruptcy"),
)


def test_n1_a_clean_record_question_a_right_yes_is_written_after_one_confirmation_and_one_meaning_call():
    """N1 / U3 / U6: "Is your criminal record clean?": the reader has no reading, so even a RIGHT Yes gets ONE
    confirmation; it agrees -> ONE meaning call; "no" writes the Yes (assumed); "yes" / unusable -> empty.
    Exactly two pick calls, never the empty end the third review found for a right model."""
    bad = []
    for label, klass in N1_ROWS:
        for kind in CLASSES:
            k = _k(kind, klass)
            for meaning, want in (("no", "Yes"), ("yes", ""), ("", "")):
                ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("Yes", meaning))
                res = attempt(_pf("n", label, options=YN), ask)
                if shown(res) != want or len(ask.picks) != 2 or (want and not res.assumed):
                    bad.append((label[:40], kind, f"meaning {meaning!r}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_n1_a_clean_record_question_the_adverse_no_is_never_written_without_a_check():
    """N1: a flipped confirmation on a RIGHT Yes, and a wrong No (the model ignored the polarity), must never end
    with the adverse No written unmarked / with no call (the review's `No~/2` and `No/1`). With an unusable
    meaning reply every such cell ends empty, after at least one confirmation call."""
    bad = []
    for label, klass in N1_ROWS:
        for kind in CLASSES:
            k = _k(kind, klass)
            ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("No", ""))        # right model, flipped confirmation
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) != "" or not 1 <= len(ask.picks) <= 2:
                bad.append((label[:40], kind, "right Yes + flipped confirmation", what(res), len(ask.picks)))
            for pick in ("", "No"):
                ask = FakeAsk(lambda v, kk=k: lie("No", kk), pick=pick_by(pick, ""))     # wrong No
                res = attempt(_pf("n", label, options=YN), ask)
                if shown(res) != "" or not 1 <= len(ask.picks) <= 2:
                    bad.append((label[:40], kind, f"wrong No, confirmation {pick!r}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== N2: a negated work-rights question

N2_ROWS = (   # (label, the RIGHT answer for a Singapore citizen, class)
    ("Do you not require a visa to work in Singapore?", "Yes", "sponsorship"),
    ("Will you not need sponsorship to work in Singapore?", "Yes", "sponsorship"),
    ("Are you not authorised to work in Singapore?", "No", "work_right"),
    ("Is there anything that prevents you from working in Singapore without sponsorship?", "No", "work_right"),
    ("Do you lack the right to work in Singapore?", "No", "work_right"),
)


def test_n2_a_negated_work_rights_question_never_ends_with_the_inverted_claim():
    """N2 / U3 / U4 (the review's `No/2` unmarked on a right model): no reading of the negated question, so a RIGHT
    model gets ONE confirmation and, when it agrees, ONE meaning call ("no" writes it, assumed). A flipped or
    unusable confirmation, or a "yes" meaning reply, ends EMPTY: the inverted claim ("I need a visa", "I am not
    authorised") is never written, marked or not, whatever the class condition."""
    bad = []
    for label, right, klass in N2_ROWS:
        wrong = "No" if right == "Yes" else "Yes"
        for kind in CLASSES:
            k = _k(kind, klass)
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(right, "no"))
            res = attempt(_pf("w", label, options=YN), ask)
            if shown(res) != right or not res.assumed or len(ask.picks) != 2:
                bad.append((label[:40], kind, "right + agreeing confirmation + meaning no", what(res), len(ask.picks)))
            for pick, meaning in ((wrong, ""), ("", ""), (right, "yes"), (right, "")):
                ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(pick, meaning))
                res = attempt(_pf("w", label, options=YN), ask)
                if shown(res) == wrong or shown(res) != "":
                    bad.append((label[:40], kind, f"right model, confirmation {pick!r}, meaning {meaning!r}", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=pick_by("", ""))
            res = attempt(_pf("w", label, options=YN), ask)
            if shown(res) != "" or len(ask.picks) < 1:
                bad.append((label[:40], kind, "wrong model: never unmarked, never with no call", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== N3: a note that maps Yes / No is part of the question

N3_ROWS = (   # (label, the RIGHT answer under the note, class)
    ("Do you have any criminal convictions? Select Yes to confirm you have none.", "Yes", "declaration:criminal_record"),
    ("Do you have any criminal convictions? (Yes = you have none)", "Yes", "declaration:criminal_record"),
    ("Have you ever been bankrupt? Answer Yes if you have never been bankrupt.", "Yes", "declaration:bankruptcy"),
    ("Do you have any criminal convictions? If not, please select No.", "No", "declaration:criminal_record"),
    ("Have you ever been convicted of a criminal offence? (Do not answer yes if the conviction is spent)", "No",
     "declaration:criminal_record"),
)


def test_n3_a_note_that_maps_yes_and_no_gives_the_reader_no_reading_so_nothing_is_written_unchecked():
    """N3: "Select Yes to confirm you have none" inverts the question and a note that only narrows it does not.
    The mapping notes leave the reader with no reading: a right model gets a confirmation + a meaning call
    ("no" writes, assumed); a wrong model (it ignored the note) is never written with no call; a flipped
    confirmation ends empty."""
    bad = []
    for label, right, klass in N3_ROWS:
        wrong = "No" if right == "Yes" else "Yes"
        for kind in CLASSES:
            k = _k(kind, klass)
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(right, "no"))
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) != right or not res.assumed or len(ask.picks) != 2:
                bad.append((label[:45], kind, "right + agreeing + meaning no", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=pick_by(wrong, ""))
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) != "" or not 1 <= len(ask.picks) <= 2:
                bad.append((label[:45], kind, "right + flipped confirmation", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=pick_by("", ""))
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) != "" or len(ask.picks) < 1:
                bad.append((label[:45], kind, "wrong model (ignored the note): never unmarked, never no call", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== U5: the three required "not a PEP" boxes

NOT_BOXES = ("I am not a politically exposed person", "Tick if you are not a politically exposed person",
             "Please tick here if you have no criminal record")


def test_u5_a_required_not_a_pep_box_with_a_right_model_ends_ticked():
    """U5 (the negation list gates nothing): a RIGHT model (it ticks) on the three required statement boxes ends
    TICKED. "I am not a PEP" has a reading: ticked with ZERO calls (U1). The two "Tick if ... not / no" boxes have
    none: ONE box confirmation ("Should the box ... be ticked?") and, as it agrees, ONE meaning call; "no" -> ticked
    (assumed, 2 calls); "yes" or unusable -> unticked."""
    bad = []
    for label in NOT_BOXES:
        for kind in CLASSES:
            k = _k(kind, "declaration:pep" if "politically" in label else "declaration:criminal_record")
            ask = FakeAsk(lambda v, kk=k: lie("true", kk), pick=pick_by("yes", "no"))
            res = attempt(_pf("b", label, "CHECKBOX"), ask)
            reading = label.startswith("I am not")
            if not is_ticked(res) or len(ask.picks) != (0 if reading else 2) or (not reading and not res.assumed):
                bad.append((label[:45], kind, "right model ticks", what(res), len(ask.picks)))
            if not reading:
                for meaning in ("yes", ""):
                    ask = FakeAsk(lambda v, kk=k: lie("true", kk), pick=pick_by("yes", meaning))
                    res = attempt(_pf("b", label, "CHECKBOX"), ask)
                    if is_ticked(res):
                        bad.append((label[:45], kind, f"meaning {meaning!r} must not tick", what(res)))
    assert not bad, report(bad, 10)


def test_u5_a_required_not_a_pep_box_with_a_wrong_or_silent_model_is_never_ticked_without_a_confirmation_yes():
    """A wrong (unticked) or silent model on the three boxes: ONE box confirmation. Only a "yes" confirmation can
    tick, never code's own reading; "no" / unusable -> unticked. (The no-reading boxes with a "yes" that DIFFERS
    from the model's unticked reply need U8's meaning call: pinned in test_u8_*.)"""
    bad = []
    for label in NOT_BOXES:
        klass = "declaration:pep" if "politically" in label else "declaration:criminal_record"
        for who, mk in (("wrong", lambda v, kk=klass: lie("false", kk)), ("silent", None)):
            for confirm in ("no", ""):
                ask = FakeAsk(mk, pick=pick_by(confirm, "")) if mk else FakeAsk(pick=pick_by(confirm, ""))
                res = attempt(_pf("b", label, "CHECKBOX"), ask)
                if is_ticked(res) or len(ask.picks) != 1:
                    bad.append((label[:45], who, f"confirm {confirm!r}", what(res), len(ask.picks)))
        # the box with a reading: a "yes" confirmation ticks it (assumed), exactly one call
        if label.startswith("I am not"):
            for who, mk in (("wrong", lambda v, kk=klass: lie("false", kk)), ("silent", None)):
                ask = FakeAsk(mk, pick=pick_by("yes", "")) if mk else FakeAsk(pick=pick_by("yes", ""))
                res = attempt(_pf("b", label, "CHECKBOX"), ask)
                if not is_ticked(res) or not res.assumed or len(ask.picks) != 1:
                    bad.append((label[:45], who, "confirm yes ticks it, assumed", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== U2 / U4 / U7: calls, the box question, the protective end

def test_u2_a_tick_box_confirmation_asks_should_the_box_be_ticked_with_yes_no_options():
    """U7: a tick box is confirmed by "<truth> Should the box «label» be ticked? Answer yes or no." with the options
    yes / no (a box has no option list). One call; it is a box call, never an own-fact or meaning call."""
    label = "Tick if you are a politically exposed person"
    ask = FakeAsk(lambda v: lie("true", "declaration:pep"), pick=pick_by("no", ""))
    res = attempt(_pf("b", label, "CHECKBOX"), ask)
    assert not is_ticked(res) and len(ask.picks) == 1, (what(res), len(ask.picks))
    q, wanted, options = ask.picks[0]
    assert f"Should the box «{label}» be ticked? Answer yes or no." in wanted and options == ["yes", "no"], (wanted, options)
    assert "tick box" in ask.pick_tasks[0].lower() or "tick box" in ask.users[-1].lower(), ask.pick_tasks


def test_u4_the_protective_end_writes_nothing_for_yes_no_boxes_lists_and_work_rights_when_the_confirmation_is_unusable():
    """U4: with an unusable confirmation EVERY kind of U field (yes/no, tick box, option list, work rights, a
    sponsorship question) ends empty / unticked, whatever the model said; code's own reading and the
    none-applies option are written only when the confirmation itself named them."""
    bad = []
    cases = (
        ("yes/no", lambda: _pf("u", "Have you ever been declared bankrupt?", options=YN), "Yes", "declaration:bankruptcy"),
        ("box", lambda: _pf("u", "Tick if you have been declared bankrupt", "CHECKBOX"), "true", "declaration:bankruptcy"),
        ("list", lambda: _pf("u", "Do any of the following apply?", "RADIO",
                             options=("Criminal conviction", "Bankruptcy", "None of the above")), "Bankruptcy", "declaration:bankruptcy"),
        ("work right", lambda: _pf("u", "Are you legally authorised to work in the United States?", options=YN), "Yes", "work_right"),
        ("sponsorship", lambda: _pf("u", "Will you now or in the future require sponsorship to work in Singapore?", options=YN),
         "Yes", "sponsorship"),
    )
    for name, mk, wrong, klass in cases:
        for who, ask in (("wrong model", FakeAsk(lambda v, w=wrong, k=klass: lie(w, k), pick=pick_by("", ""))),
                         ("silent model", FakeAsk(pick=pick_by("", "")))):
            res = attempt(mk(), ask)
            if is_stop(res) or is_ticked(res) or shown(res) not in ("", "false"):
                bad.append((name, who, what(res)))
    assert not bad, report(bad)
    # the none-applies option IS written when the confirmation itself named it
    ask = FakeAsk(lambda v: lie("Bankruptcy", "declaration:bankruptcy"), pick=pick_by("None of the above", ""))
    res = attempt(_pf("u", "Do any of the following apply?", "RADIO",
                      options=("Criminal conviction", "Bankruptcy", "None of the above")), ask)
    assert shown(res) == "None of the above" and res.assumed and len(ask.picks) == 1, what(res)


# ================================================================== U8: no reading, a confirmation that differs from the model

U8_ROWS = (   # (label, class, the model's WRONG value, the confirmation's right value)
    ("Is your criminal record clean?", "declaration:criminal_record", "No", "Yes"),
    ("Do you have a clean criminal record?", "declaration:criminal_record", "No", "Yes"),
    ("Es-tu une personne politiquement exposée ?", "declaration:pep", "Oui", "Non"),
)


def _u8_options(label):
    return ("Oui", "Non") if label.startswith("Es-tu") else YN


def _u8_kinds(label):
    return CLASSES if not label.startswith("Es-tu") else ("right",)     # French + class ordinary: the accepted R2 / M8 residual


def _meaning_by(confirm, *, yes_for=(), unusable_for=(), down_for=()):
    """A scripted pick: the confirmation call gets `confirm`; a meaning call is answered by the value it is asked
    about («V» in its WANTED): "yes" for a value in `yes_for`, unusable for `unusable_for`, a transport failure
    for `down_for`, else "no". So a test can say what each CHECK says, however many meaning calls are made."""
    import re
    from jobscraper.backends import BackendError

    def pick(q, w, o):
        if not str(w).startswith("If the applicant answers"):
            return confirm
        v = re.search(r"«(.*?)»", str(w)).group(1)
        if v in down_for:
            raise BackendError("the model is unreachable")
        return "yes" if v in yes_for else "" if v in unusable_for else "no"
    return pick


def _asked_about(ask, value):
    return any(f"If the applicant answers «{value}»" in p[1] for p in ask.picks)


def test_u8_with_no_reading_a_differing_confirmation_that_the_meaning_call_clears_is_written():
    """U8: no reading, the model's first answer differs from the confirmation. The meaning call is made on the
    CONFIRMATION's value; when it says "no" (the value does not contradict the truth) and the first answer's
    own check says "yes" (it does), the confirmation's value is written, assumed. (U8b, as built: the first
    answer is checked too, so 2 or 3 pick calls.) Class right / ordinary / none."""
    bad = []
    for label, klass, wrong, right in U8_ROWS:
        for kind in _u8_kinds(label):
            k = _k(kind, klass)
            ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=_meaning_by(right, yes_for=(wrong,)))
            res = attempt(_pf("u", label, options=_u8_options(label)), ask)
            if shown(res) != right or not res.assumed or not 2 <= len(ask.picks) <= 3 or not _asked_about(ask, right):
                bad.append((label[:40], kind, "confirmation differs, its meaning no", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u8_a_yes_or_unusable_meaning_reply_or_a_transport_failure_on_a_differing_confirmation_ends_empty():
    """U8: "yes" (the confirmation's value DOES contradict the truth) or an unusable reply on the meaning call
    about it -> the protective end: empty, never the model's wrong value and never the confirmation's value. The
    meaning call was made. A transport failure on that call is review 4 F5 (replaces "ends empty"): the page ends
    as a transport failure, nothing wrong is written."""
    bad = []
    for label, klass, wrong, right in U8_ROWS:
        for kind in _u8_kinds(label):
            k = _k(kind, klass)
            for name, kw in (("yes", dict(yes_for=(right, wrong))), ("unusable", dict(unusable_for=(right,)))):
                ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=_meaning_by(right, **kw))
                res = attempt(_pf("u", label, options=_u8_options(label)), ask)
                if shown(res) != "" or not _asked_about(ask, right):
                    bad.append((label[:40], kind, f"meaning {name}", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, kk=k, w=wrong: lie(w, kk), pick=_meaning_by(right, down_for=(right,)))
            out = outcome(_pf("u", label, options=_u8_options(label)), ask)
            written = out.answers.get("u")
            if not out.transport_failed or not _asked_about(ask, right) or (written is not None and shown(written) == wrong):
                bad.append((label[:40], kind, "meaning call down (F5)", out.transport_failed, len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u8_a_silent_model_has_no_first_answer_so_one_meaning_call_on_the_confirmation_decides():
    """U8: a silent model: the confirmation's value gets ONE meaning call: "no" -> written (assumed, 2 pick calls),
    "yes" / unusable -> empty."""
    bad = []
    for label, klass, wrong, right in U8_ROWS:
        if label.startswith("Es-tu"):
            continue       # a French question, no class and no key: an ordinary field (the accepted R2 / M8 residual)
        for name, kw, want in (("no", {}, right), ("yes", dict(yes_for=(right,)), ""), ("unusable", dict(unusable_for=(right,)), "")):
            ask = FakeAsk(pick=_meaning_by(right, **kw))
            res = attempt(_pf("u", label, options=_u8_options(label)), ask)
            if shown(res) != want or len(ask.picks) != 2 or (want and not res.assumed):
                bad.append((label[:40], f"meaning {name}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u8b_a_right_model_and_a_flipped_confirmation_never_write_the_flipped_value_on_two_no_replies():
    """D-212 U8b (ruled; eng/Q-121-A1-fix1 c218bf8): no reading, the model's first answer is RIGHT and the
    confirmation flipped it. BOTH values get a meaning call; a value is written only when its own call says "no"
    and the other's says "yes". Both "no" -> empty, never the flipped (adverse) value: the cell the engineer
    flagged as a residual (two of three calls). "flipped: yes, first: no" writes the model's own first answer."""
    bad = []
    for label, klass, wrong, right in U8_ROWS:
        for kind in _u8_kinds(label):
            k = _k(kind, klass)
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=_meaning_by(wrong))
            res = attempt(_pf("u", label, options=_u8_options(label)), ask)
            if shown(res) != "":
                bad.append((label[:40], kind, "both meaning replies no: never the flipped value", what(res)))
            ask = FakeAsk(lambda v, kk=k, r=right: lie(r, kk), pick=_meaning_by(wrong, yes_for=(wrong,)))
            res = attempt(_pf("u", label, options=_u8_options(label)), ask)
            if shown(res) != right or not res.assumed:
                bad.append((label[:40], kind, "flipped: yes, first: no -> the model's own answer", what(res)))
    assert not bad, report(bad, 10)


def test_u8_a_no_reading_tick_box_the_model_left_unticked_is_ticked_only_by_a_yes_confirmation_and_a_no_meaning_reply():
    """U8 (box cells): a no-reading tick box ("Tick if you are not a PEP") the model left unticked or answered
    nothing: the confirmation "yes" DIFFERS from the unticked reply, so the meaning call is made on the TICKED
    value: "no" -> ticked (assumed) (U8b: for a model that unticked it, the unticked value's own check must say
    "yes"); "yes" / unusable -> unticked."""
    bad = []
    label = "Tick if you are not a politically exposed person"
    for who, mk in (("wrong (unticked)", lambda v: lie("false", "declaration:pep")), ("silent", None)):
        for name, kw, ticked in (("no", dict(yes_for=("unticked",)), True), ("yes", dict(yes_for=("ticked", "unticked")), False),
                                 ("unusable", dict(unusable_for=("ticked",)), False)):
            ask = FakeAsk(mk, pick=_meaning_by("yes", **kw)) if mk else FakeAsk(pick=_meaning_by("yes", **kw))
            res = attempt(_pf("b", label, "CHECKBOX"), ask)
            if is_ticked(res) is not ticked or (ticked and not res.assumed) or not 2 <= len(ask.picks) <= 3:
                bad.append((who, f"meaning {name} on ticked", what(res), len(ask.picks)))
    assert not bad, report(bad)


# ================================================================== fix2 A-E (real-model failures of the rehearsal)

OWN = {"phone": "91234567", "postal": "000001", "address": "1 Example Road", "email": "alex.testcase@example.com"}
ENTRY_GROUPS = (("experience[0]", "Work experience"), ("education[0]", "Education"), ("reference[0]", "Referee"))
ENTRY_FIELDS = (   # (label, type, the applicant's own value, the model's class when "right")
    ("Phone number", "TEXT", OWN["phone"], "owner_fact:phone"),
    ("Postal code", "TEXT", OWN["postal"], "owner_fact:postal_code"),
    ("Address", "TEXT", OWN["address"], "owner_fact:address"),
    ("Email address", "EMAIL", OWN["email"], "other_person"),
)


def test_fix2_a_the_applicants_own_phone_postal_code_address_or_email_in_an_employer_school_or_referee_entry_is_never_written():
    """fix2 A (the real-model "Phone number" / "Postal code" inside a Work experience group): the applicant's OWN
    value is vetoed and re-asked; a required TEXT then ends "N/A" (a reference entry: "Available on request"),
    anything else empty. The own value is never written, in any class condition, required or not."""
    bad = []
    for group, title in ENTRY_GROUPS:
        for label, tn, own, klass in ENTRY_FIELDS:
            for kind in CLASSES:
                k = _k(kind, klass)
                for required in (True, False):
                    ask = FakeAsk(lambda v, x=own, kk=k: lie(x, kk), pick=pick_by("No", ""))
                    res = attempt(_pf("n", label, tn, group=group, group_title=title, required=required), ask)
                    got = shown(res)
                    if is_stop(res) or own in got or (not required and got != ""):
                        bad.append((group, label, kind, "req" if required else "opt", what(res)))
                    elif required and tn == "TEXT" and got not in ("N/A", "Available on request"):
                        bad.append((group, label, kind, "required TEXT must end N/A", what(res)))
    assert not bad, report(bad, 10)


def test_fix2_b_a_grade_list_is_written_only_when_an_option_holds_the_profiles_grade():
    """fix2 B ("Highest qualification grade" never an option absent from the profile): with no grade in the
    profile or the resume a model pick ("First Class") is never written: required -> the owner-fact stop,
    optional -> empty. With a profile grade 4.20 an option that holds it ("4.0 - 4.5") is written; a list
    with no such option is treated like no grade."""
    from always_a1_support import DELETE
    no_grade = {"education": [{"institution": "Nanyang Example University", "degree": "Bachelor of Engineering",
                               "major": "Computer Engineering", "start": "2021-08", "end": "2025-06", "grade_type": "cap",
                               "grade": "", "grade_scale": "", "from_resume": False}]}
    opts = ("First Class", "Second Upper", "Other")
    for required in (True, False):
        res = attempt(_pf("g", "Highest qualification grade", "DROPDOWN", options=opts, required=required),
                      FakeAsk(lambda v: lie("First Class", "ordinary")), profile_with(**no_grade),
                      rctx_kw={"resume_text": "Alex Testcase. Skills: Python."})
        if required:
            assert stop_is(res, "owner_fact_missing"), ("required, no grade", what(res))
        else:
            assert shown(res) == "" and not is_stop(res), ("optional, no grade", what(res))
    bands = ("3.0 - 3.9", "4.0 - 4.5", "Other")
    res = attempt(_pf("g", "Highest qualification grade", "DROPDOWN", options=bands), FakeAsk(lambda v: lie("3.0 - 3.9", "ordinary")))
    assert shown(res) != "3.0 - 3.9", ("a band that does not hold 4.20 is never written", what(res))
    res = attempt(_pf("g", "Highest qualification grade", "DROPDOWN", options=("First Class", "Second Upper")),
                  FakeAsk(lambda v: lie("First Class", "ordinary")))
    assert stop_is(res, "owner_fact_missing") and "First Class" not in what(res), ("no option holds 4.20", what(res))


def test_fix2_c_your_email_after_a_referrers_name_is_the_applicants_and_the_referrers_email_never_is():
    """fix2 C: a label led by "Your / My" is the applicant's own even right after another person's field
    ("Your email address" after "Referrer's name" -> the applicant's email, with or without a model answer);
    "Referrer's email" never gets the applicant's email (the model's other-person value stands, a silent model
    leaves it empty)."""
    for model in (None, "someone@example.org"):
        ask = FakeAsk(lambda v: lie(model, "ordinary")) if model else FakeAsk()
        res = attempt(with_text(_pf("n", "Your email address", "EMAIL"), context="Referrer's name"), ask)
        assert shown(res) == OWN["email"], (model, what(res))
    res = attempt(with_text(_pf("n", "Referrer's email", "EMAIL"), context="Referrer's name"), FakeAsk())
    assert OWN["email"] not in what(res) and shown(res) == "", what(res)
    res = attempt(with_text(_pf("n", "Referrer's email", "EMAIL"), context="Referrer's name"), FakeAsk(lambda v: lie("ref@example.org", "ordinary")))
    assert shown(res) == "ref@example.org", what(res)


def test_fix2_d_a_protected_class_only_the_model_names_on_a_default_answer_is_rechecked_once():
    """fix2 D (the real-model "Have you worked on similar roles before?" labelled `declaration:non_compete`): ONE
    extra field call re-asks with the class definition (the neutral re-check), on a default basis AND, since the
    fix4 ruling (replaces "a resume basis gets no extra call"), on a profile or resume basis for a declaration /
    work-rights / sponsorship class. 2 field calls in all, both bases. The forced class correction does NOT run for
    a declaration the model keeps (fix4 ruling, replaces the 3 / 2 call count of the first fix4 build): the class
    stands, so the model's "No" is the reader's option (written, no call, no "class corrected" note) and its "Yes"
    is never written without the vote (here an unusable confirmation: empty)."""
    label = "Have you worked on similar roles before?"
    for basis, ref in (("default", "default:no_declaration"), ("resume", "")):
        ask = FakeAsk(lambda v, b=basis, r=ref: say("No", b, r, klass="declaration:non_compete"), pick=pick_by("", ""))
        res = attempt(_pf("n", label, options=YN), ask)
        assert len(ask.sent) == 2, (basis, "field calls", len(ask.sent), what(res))
        assert shown(res) == "No" and "class corrected" not in str(res.note) and not ask.picks, (basis, what(res))
        ask = FakeAsk(lambda v, b=basis, r=ref: say("Yes", b, r, klass="declaration:non_compete"), pick=pick_by("", ""))
        res = attempt(_pf("n", label, options=YN), ask)
        assert len(ask.sent) == 2 and shown(res) == "", (basis, "a kept declaration's Yes", len(ask.sent), what(res))


def test_fix2_e_an_explicit_keep_on_file_frame_is_retention_even_when_the_model_says_marketing():
    """fix2 E: "Please keep my application on file for 12 months" is `consent_retention` whatever class the model
    gives: it follows `consents.data_retention_consent`, never the marketing opt-in."""
    label = "Please keep my application on file for 12 months"
    for retention, opt_in, want in ((True, False, True), (False, True, False)):
        p = profile_with(consents__data_retention_consent=retention, consents__talent_pool_opt_in=opt_in)
        res = attempt(_pf("c", label, "CHECKBOX", required=False),
                      FakeAsk(lambda v: say("true", "default", "default:consent", klass="marketing")), p)
        assert is_ticked(res) is want, (retention, opt_in, what(res))


# ================================================================== N4 / N5 / N6 / M6

def test_n4_a_grade_or_salary_inside_an_entry_comes_from_that_entrys_facts_or_stays_empty():
    """N4: "GPA" / "Grade" in an education entry is the profile's grade (4.20 / 5.00), never the model's
    "First Class" / "4.9/5.0"; "Salary" / "Monthly salary" in an employment entry is never the applicant's
    EXPECTED salary (5000): a required TEXT ends "N/A", an optional one empty."""
    bad = []
    for label, value in (("GPA", "First Class"), ("Grade", "4.9/5.0"), ("CGPA", "Distinction")):
        res = attempt(_pf("n", label, "TEXT", group="education[0]", group_title="Education", required=True), FakeAsk(lambda v, x=value: lie(x, "ordinary")))
        if value in shown(res) or "4.20" not in shown(res):
            bad.append((label, value, what(res)))
    for label in ("Salary", "Monthly salary", "Annual salary"):
        for required, want in ((True, "N/A"), (False, "")):
            res = attempt(_pf("n", label, "TEXT", group="experience[0]", group_title="Work experience", required=required),
                          FakeAsk(lambda v: lie("3200", "ordinary")))
            if shown(res) != want or "5000" in shown(res) or "3200" in shown(res):
                bad.append((label, "req" if required else "opt", "want", want, what(res)))
    assert not bad, report(bad)


def test_n5_the_date_of_birth_of_a_dependant_child_or_next_of_kin_is_never_the_applicants():
    """N5: "Date of birth of dependant / child / spouse / next of kin" is another person's: the model's value
    stands (assumed), never the owner's date of birth (2002-03-14, or 14/03/2002)."""
    bad = []
    for label in ("Date of birth of dependant", "Date of birth of child", "Date of birth of your spouse",
                  "Dependant's date of birth", "Date of birth of next of kin"):
        for kind in ("ordinary", NO_CLASS, "owner_fact:date_of_birth"):
            res = attempt(_pf("n", label, "TEXT"), FakeAsk(lambda v, kk=kind: lie("2015-01-02", kk)))
            if "2002" in what(res) or "14/03" in what(res):
                bad.append((label, str(kind), "the owner's date of birth was written", what(res)))
            elif kind != "owner_fact:date_of_birth" and (is_stop(res) or shown(res) != "2015-01-02"):
                bad.append((label, str(kind), "the model's value stands", what(res)))     # the model's own class alone: vetoed, empty
    assert not bad, report(bad)


def test_n6_an_unusable_own_fact_check_ends_at_the_stop_or_empty_for_an_owner_only_fact_and_keeps_the_value_for_a_shared_one():
    """N6: the own-fact check unusable. Owner-ONLY fact (age): required -> the owner-fact stop, optional -> empty,
    never the model's year-shaped invention. address / phone / postal code: the model's value, assumed."""
    bad = []
    for required in (True, False):
        res = attempt(_pf("a", "Age", "NUMBER", required=required), FakeAsk(lambda v: lie("1999", "ordinary"), pick=pick_by("", "")))
        if required and not stop_is(res, "owner_fact_missing") or (not required and (is_stop(res) or shown(res) != "")):
            bad.append(("Age", "req" if required else "opt", what(res)))
    for label, tn, value in (("Home address", "TEXT", "88 Orchard Road"), ("Postal code", "TEXT", "238801"), ("Mobile number", "PHONE", "98765432")):
        res = attempt(_pf("n", label, tn), FakeAsk(lambda v, x=value: lie(x, "ordinary"), pick=pick_by("", "")))
        if is_stop(res) or shown(res) != value or not res.assumed:
            bad.append((label, "shared fact, unusable check", what(res)))
    assert not bad, report(bad)


def test_m6_an_employers_or_verification_contact_email_never_gets_the_applicants_email():
    """M6 / N8: "Employer's contact email (for verification)", "Contact email of previous employer", "Verification
    contact email" are another party's: the model's value stands (assumed), a silent model leaves them empty;
    the applicant's own email is never written."""
    bad = []
    for label in ("Employer's contact email (for verification)", "Contact email of previous employer", "Verification contact email"):
        res = attempt(_pf("n", label, "EMAIL"), FakeAsk(lambda v: lie("hr@example.org", "ordinary")))
        if shown(res) != "hr@example.org" or OWN["email"] in what(res):
            bad.append((label, "model value", what(res)))
        res = attempt(_pf("n", label, "EMAIL"), FakeAsk())
        if OWN["email"] in what(res) or shown(res) != "":
            bad.append((label, "silent", what(res)))
    assert not bad, report(bad)


# ================================================================== the page cap

# U12 (fix8): the WHOLE label "Criminal record", "Bankruptcy", "Politically exposed person (PEP)", "Non-compete agreement",
# "Criminal convictions" is now a canonical frame (a reading), so those five are replaced here by off-list near-misses that
# still have NO reading ("Criminal record check", "Bankruptcy status", ...): the cap arithmetic is unchanged
BARE_NOUNS = ("Criminal record check", "Bankruptcy status", "PEP status", "Politically exposed person status",
              "Non-compete obligations",
              "Disciplinary action", "Shareholding", "Government employment", "Regulatory sanctions", "Insolvency",
              "Criminal convictions history", "Regulatory disciplinary action", "Criminal offences", "Bankruptcy history",
              "Relatives employed", "Restrictive covenants")


def test_u_cap_a_page_of_sixteen_bare_noun_declarations_with_a_right_model_finishes_under_the_cap():
    """D-212 cap arithmetic: a page of 16 bare-noun declarations (no reading, so every field costs a confirmation and
    a meaning call) with a RIGHT model: no content failure ("too many model calls"), every answer No (assumed).
    The old default cap (3 x chunks + 20 = 23) would have failed this page; the new one grows by 2 per field
    waiting for a vote. An explicit `llm_fill.max_calls_page` is unchanged: it still caps exactly."""
    fields = [_pf(f"d{i}", label, options=YN) for i, label in enumerate(BARE_NOUNS)]
    ask = FakeAsk(lambda v: lie("No"), pick=pick_by("No", "no"))
    res = page(fields, ask)
    assert not is_stop(res), what(res)
    calls = len(ask.users)
    voted = [k for k, a in res.items() if a.assumed]
    assert calls > 23, ("this page must need more calls than the OLD cap allowed", calls)
    assert len(voted) == 16 and all(shown(res[k]) == "No" for k in res), {k: shown(a) for k, a in res.items()}


# ================================================================== U8b: the five cells, the silent cell, the box pair, the source, the cap

BARE = "Criminal record check"   # a noun phrase with NO reading (U12 made the bare "Criminal record" a frame); the owner's truth is "none", so the right answer is No


def _bare(first, confirm, *, yes_for=(), unusable_for=(), down_for=(), klass="declaration:criminal_record", options=YN):
    ask = FakeAsk(lambda v: lie(first, klass), pick=_meaning_by(confirm, yes_for=yes_for, unusable_for=unusable_for, down_for=down_for))
    return attempt(_pf("u", BARE, options=options), ask), ask


def test_u8b_the_five_cells_for_a_bare_noun_label_are_written_only_by_a_consistent_pair_of_meaning_replies():
    """D-212 U8b: no reading and the confirmation's value differs from the first answer: BOTH values get a meaning
    call (3 pick calls: confirmation + two meaning calls). A value is written (assumed, a note naming the calls) only
    when its own call says "no" AND the other's says "yes". Cells for "Criminal record check" (right = No), under
    class right / ordinary / missing:
      1. first RIGHT (No), confirmation flipped (Yes), (first: no, flipped: yes) -> the first answer;
      2. the same with (no, no) -> empty;  3. (yes, yes) -> empty;
      4. first WRONG (Yes), confirmation right (No), (first: yes, confirmation: no) -> the confirmation's value;
      5. the same with (no, no) -> empty.
    Never the wrong / flipped value."""
    bad = []
    for kind in CLASSES:
        k = _k(kind, "declaration:criminal_record")
        cells = (
            ("1 first right, flipped, (no,yes)", "No", "Yes", dict(yes_for=("Yes",)), "No"),
            ("2 first right, flipped, (no,no)", "No", "Yes", {}, ""),
            ("3 first right, flipped, (yes,yes)", "No", "Yes", dict(yes_for=("No", "Yes")), ""),
            ("4 first wrong, confirmation right, (yes,no)", "Yes", "No", dict(yes_for=("Yes",)), "No"),
            ("5 first wrong, confirmation right, (no,no)", "Yes", "No", {}, ""),
        )
        for name, first, confirm, kw, want in cells:
            res, ask = _bare(first, confirm, klass=k, **kw)
            if shown(res) != want or len(ask.picks) != 3 or (want and not res.assumed) \
                    or not (_asked_about(ask, first) and _asked_about(ask, confirm)):
                bad.append((kind, name, what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u8b_an_unusable_reply_or_a_transport_failure_on_either_meaning_call_ends_empty():
    """U8b: "either unusable -> the protective end": for the consistent pair (first yes, confirmation no) an
    unusable reply on EITHER call leaves the field empty. A transport failure on either call is review 4 F5
    (replaces "ends empty"): the page ends as a transport failure and the flipped value is not written."""
    bad = []
    for kind in CLASSES:
        k = _k(kind, "declaration:criminal_record")
        for name, kw in (("confirmation's call unusable", dict(yes_for=("Yes",), unusable_for=("No",))),
                         ("first's call unusable", dict(unusable_for=("Yes",)))):
            res, ask = _bare("Yes", "No", klass=k, **kw)
            if shown(res) != "":
                bad.append((kind, name, what(res), len(ask.picks)))
        for name, kw in (("confirmation's call down", dict(yes_for=("Yes",), down_for=("No",))),
                         ("first's call down", dict(down_for=("Yes",)))):
            ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=_meaning_by("No", **kw))
            out = outcome(_pf("u", BARE, options=YN), ask)
            written = out.answers.get("u")
            if not out.transport_failed or (written is not None and shown(written) == "No"):
                bad.append((kind, name, "F5", out.transport_failed, len(ask.picks)))
    assert not bad, report(bad)


def test_u8b_a_silent_model_has_two_calls_the_confirmation_and_one_meaning_call():
    """U8b: a silent model has no first answer: the confirmation's value is written after its meaning call says
    "no" (2 pick calls, assumed); "yes" / unusable -> empty."""
    bad = []
    for name, kw, want in (("no", {}, "No"), ("yes", dict(yes_for=("No",)), ""), ("unusable", dict(unusable_for=("No",)), "")):
        ask = FakeAsk(pick=_meaning_by("No", **kw))
        res = attempt(_pf("u", BARE, options=YN), ask)
        if shown(res) != want or len(ask.picks) != 2 or (want and not res.assumed):
            bad.append((name, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_u8b_a_tick_box_follows_the_same_rule_and_its_meaning_call_says_what_ticking_or_leaving_it_unticked_states():
    """U8b, a no-reading box ("Tick if you are not a PEP"): the meaning call asks what TICKING it, or LEAVING IT
    UNTICKED, states. The model ticked (right), the confirmation says no (unticked): (ticked: no, unticked: yes)
    -> ticked (the first answer, assumed, 3 calls); (no, no) or (yes, yes) -> unticked. The model unticked and the
    confirmation says yes: (unticked: yes, ticked: no) -> ticked; (no, no) -> unticked."""
    label = "Tick if you are not a politically exposed person"
    bad = []
    cells = (
        ("ticked, confirm no, (ticked no, unticked yes)", lambda v: lie("true", "declaration:pep"), "no", dict(yes_for=("unticked",)), True),
        ("ticked, confirm no, (no, no)", lambda v: lie("true", "declaration:pep"), "no", {}, False),
        ("ticked, confirm no, (yes, yes)", lambda v: lie("true", "declaration:pep"), "no", dict(yes_for=("ticked", "unticked")), False),
        ("unticked, confirm yes, (unticked yes, ticked no)", lambda v: lie("false", "declaration:pep"), "yes", dict(yes_for=("unticked",)), True),
        ("unticked, confirm yes, (no, no)", lambda v: lie("false", "declaration:pep"), "yes", {}, False),
    )
    for name, mk, confirm, kw, ticked in cells:
        ask = FakeAsk(mk, pick=_meaning_by(confirm, **kw))
        res = attempt(_pf("b", label, "CHECKBOX"), ask)
        if is_ticked(res) is not ticked or (ticked and not res.assumed) or len(ask.picks) != 3:
            bad.append((name, "ticked" if is_ticked(res) else "unticked", len(ask.picks)))
        if ask.picks and not any("leaving it unticked" in p[1] or "ticking it" in p[1] for p in ask.picks[1:]):
            bad.append((name, "the box meaning call wording", [p[1][:80] for p in ask.picks[1:]]))
    assert not bad, report(bad)


def test_u_a_declaration_that_applies_cites_the_profile_row_it_follows():
    """A declaration the profile says APPLIES (pep = true) is answered Yes / ticked from `profile:declarations.pep`,
    not from `default:no_declaration`: the yes/no, the box "I am a PEP" and "Tick if you are a PEP" cite that row;
    bankruptcy = true with a model No and a confirmation Yes -> Yes (assumed) citing declarations.bankruptcy."""
    p = profile_with(declarations__pep=True, declarations__bankruptcy=True)
    ask = FakeAsk(lambda v: lie("Yes", "declaration:pep"))
    res = attempt(_pf("r", "Are you a politically exposed person?", options=YN), ask, p)
    assert shown(res) == "Yes" and res.source == "profile:declarations.pep", what(res)
    for label in ("I am a politically exposed person", "Tick if you are a politically exposed person"):
        res = attempt(_pf("r", label, "CHECKBOX"), FakeAsk(lambda v: lie("true", "declaration:pep"), pick=pick_by("yes", "no")), p)
        assert is_ticked(res) and res.source == "profile:declarations.pep", (label, what(res))
    ask = FakeAsk(lambda v: lie("No", "declaration:bankruptcy"), pick=pick_by("Yes", ""))
    res = attempt(_pf("r", "Have you ever been declared bankrupt?", options=YN), ask, p)
    assert shown(res) == "Yes" and res.assumed and res.source == "profile:declarations.bankruptcy", what(res)


def test_u_cap_sixteen_bare_noun_declarations_where_every_pair_differs_cost_at_most_49_calls_under_the_cap():
    """D-212 U8b cap: CALLS_PER_VOTE is 3. A page of 16 bare-noun declarations where the model is wrong and the
    confirmation right on every field (3 calls each) costs 1 + 48 = 49 calls against a cap of 71, finishes
    with no content failure and writes the right value (assumed) on every field."""
    fields = [_pf(f"d{i}", label, options=YN) for i, label in enumerate(BARE_NOUNS)]
    ask = FakeAsk(lambda v: lie("Yes"), pick=_meaning_by("No", yes_for=("Yes",)))
    res = page(fields, ask)
    assert not is_stop(res), what(res)
    assert 23 < len(ask.users) <= 49, len(ask.users)
    assert all(shown(a) == "No" and a.assumed for a in res.values()), {k: shown(a) for k, a in res.items()}
