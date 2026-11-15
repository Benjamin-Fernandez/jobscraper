"""Q-121 Amendment A1, the U9 round (part 2): the fourth review's F3-F6 (docs/reviews/Q-121-A1-rulingU.md) and fix4.
Part 1 (F1 / F2 and the canonical-frame controls) is tests/test_always_a1_u9.py; the rulings are listed there.

  F3  a military / National Service question has no declaration truth: ORDINARY. If the model keeps a declaration
      class after the neutral re-check its answer stands, assumed, note "check: national service"; never a "No"
      written from `government_employment`.
  F4  the meaning sentence for a not-authorised truth also covers "needs no sponsorship"; the `other` sentence covers
      every adverse-history kind.
  F5  a transport failure inside a vote ends the page as one (`transport_failed`), never as "the check did not agree".
  F6  a required declaration the site PRE-FILLED with a contradicting option is never left on that option after a
      failed vote: cleared, or the attempt stops (`validation_error`) naming the field.
  fix4 the forced class correction runs only when the model names a consent or marketing class code's frame does not
      find in an English label; for a declaration / work-rights / sponsorship class only the neutral re-check runs; a
      "Your / My / Applicant's" name, email or phone is filled from the profile before the model; every declaration
      class has a truth sentence in both polarities; a long class-check instruction arrives whole (PROBLEM_MAX).

Every pin keeps its assertion on the HARMFUL value. Fakes only: no model, no network, no browser, sample profile (a
Singapore citizen, National Service completed, all declarations false), made-up names.
Verify: python tests/run_tests.py -k always_a1_u9
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, outcome, pick_by, report, say, shown, what, with_text,
    _pf, _profile, profile_with)
from jobscraper.apply.contracts import AnswerStatus, ValueOrigin  # noqa: E402
from jobscraper.backends import BackendError  # noqa: E402

CLASSES = ("right", "ordinary", NO_CLASS)


def _k(kind, right):
    return right if kind == "right" else kind


def _field(label, *, tn="RADIO", required=True, **kw):
    return _pf("u", label, tn, required=required, options=YN if tn == "RADIO" else (), **kw)


def _meaning_wanted(ask):
    return [p[1] for p in ask.picks if p[1].startswith("If the applicant answers")]


# ================================================================== F3: military / National Service has no declaration truth

NS_LABELS = ("Have you served in the military, including National Service?", "Have you completed National Service?",
             "Are you a Singaporean male who has completed full-time National Service?")
NS_KINDS = ("declaration:government_employment", "ordinary", NO_CLASS)   # the sample owner has COMPLETED National Service


def test_u9_f3_a_right_yes_to_a_national_service_question_is_never_turned_into_a_no():
    """F3 (the review's `No~/1`: a right Yes + one flipped confirmation wrote a false "no military service"): the
    question is ORDINARY. Whatever class the model names and whatever a flipped confirmation would say, the model's
    right Yes is written with NO confirmation call. A model that keeps `declaration:government_employment` is
    marked assumed with the note "check: national service"."""
    bad = []
    for label in NS_LABELS:
        for kind in NS_KINDS:
            ask = FakeAsk(lambda v, kk=kind: lie("Yes", kk), pick=pick_by("No", "no"))
            res = attempt(_field(label), ask)
            if shown(res) != "Yes" or ask.picks:
                bad.append((label[:45], kind, what(res), len(ask.picks)))
            elif kind == NS_KINDS[0] and "check: national service" not in f"{res.note} {res.evidence}":
                bad.append((label[:45], kind, "the national-service note is missing", what(res)))
    assert not bad, report(bad, 10)


def test_u9_f3_a_wrong_no_to_a_national_service_question_is_replaced_by_the_profiles_yes_never_written():
    """F3 -> fix7 ruling 2 (old: "a wrong No the model keeps stands, marked assumed"): a label that plainly asks whether
    the applicant has served / completed National Service takes its answer from `singapore_status.ns_status`; the
    sample owner COMPLETED it, so a model "No" (even under `declaration:government_employment`) is REPLACED by the
    profile's Yes (not assumed, source the ns_status row, a note that says the AI answered No), with 0 calls. A false
    "no military service" is never written, and never from a `default:` declaration source."""
    bad = []
    for label in NS_LABELS:
        for kind in NS_KINDS:
            ask = FakeAsk(lambda v, kk=kind: lie("No", kk), pick=pick_by("No", "no"))
            res = attempt(_field(label), ask)
            if shown(res) != "Yes" or ask.picks or "singapore_status.ns_status" not in str(res.source) \
                    or "the AI answered No" not in f"{res.note} {res.evidence}":
                bad.append((label[:45], kind, what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f3_a_silent_model_on_the_completed_national_service_question_gets_the_profile_yes_never_a_no():
    ask = FakeAsk(pick=pick_by("No", "no"))
    res = attempt(_field("Have you completed National Service?"), ask)
    assert shown(res) == "Yes" and not ask.picks, what(res)


def test_u9_f3_contrast_government_employment_is_still_a_declaration_for_a_government_agency_question():
    """F3 contrast: "Have you ever worked for a government agency?" IS the declaration. The owner's truth is No: a model
    No is written with no call (canonical frame); a model Yes gets ONE confirmation (No) and the No is written,
    assumed. A Yes is never written unchecked."""
    label = "Have you ever worked for a government agency?"
    bad = []
    for kind in CLASSES:
        k = _k(kind, "declaration:government_employment")
        ask = FakeAsk(lambda v, kk=k: lie("No", kk), pick=pick_by("Yes", "yes"))
        res = attempt(_field(label), ask)
        if shown(res) != "No" or ask.picks:
            bad.append((kind, "model No", what(res), len(ask.picks)))
        ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("No", "no"))
        res = attempt(_field(label), ask)
        if shown(res) != "No" or not res.assumed or len(ask.picks) != 1:
            bad.append((kind, "model Yes", what(res), len(ask.picks)))
    assert not bad, report(bad)


# ================================================================== F4: the two meaning sentences

def test_u9_f4_the_meaning_sentence_for_a_not_authorised_truth_also_covers_needs_no_sponsorship():
    """F4: the sample is NOT authorised to work in the United States. A model "No" to "Do you require visa sponsorship to
    work in the United States?" (a false "needs no sponsorship") that the confirmation agrees with gets ONE meaning
    call. Its sentence must name BOTH contradictions ("authorised to work there" AND "needs no visa sponsorship"), so a
    literal reader says "yes" and the over-claim is not written."""
    # U10 (fix8): "Do you require visa sponsorship ..." is now a canonical frame, so an agreeing wrong No is a veto with
    # no meaning call (pinned in test_always_a1_fix8); this pin needs a wording with NO frame to reach the meaning call
    label = "Is visa sponsorship required for you to work in the United States?"
    bad = []
    for kind in CLASSES:
        ask = FakeAsk(lambda v, kk=_k(kind, "sponsorship"): lie("No", kk), pick=pick_by("No", "yes"))
        res = attempt(_field(label), ask)
        wanted = _meaning_wanted(ask)
        if len(wanted) != 1 or not re.search(r"authori[sz]ed to work", wanted[0]) \
                or not re.search(r"needs no (?:visa )?sponsorship", wanted[0]) or shown(res) != "":
            bad.append((kind, what(res), wanted))
    assert not bad, report(bad)


def test_u9_f4_the_other_meaning_sentence_covers_every_adverse_history_kind():
    """F4: `other` is five-way (dismissed / resigned, litigation, investigation / sanction, refused a visa / deported)
    and the model names `other` for ANY unrecognised adverse question, so the sentence also says "any other adverse
    event or interest". A literal reader then says "yes" to a Yes about outside business interests; the Yes is not
    written."""
    bad = []
    need = ("dismissed", "litigation", "investigation", "sanction", "visa", "deported", "any other adverse")
    # U10 (fix8): "Have you ever been dismissed ..." / "Do you have any ..." are canonical frames (a veto, no meaning
    # call); the two wordings here have NO frame, so the meaning call (and its sentence) is still reached
    for label in ("Any history of being dismissed from a job?", "Any outside business interests?"):
        ask = FakeAsk(lambda v: lie("Yes", "declaration:other"), pick=pick_by("Yes", "yes"))
        res = attempt(_field(label), ask)
        wanted = _meaning_wanted(ask)
        if len(wanted) != 1 or [w for w in need if w not in wanted[0]] or shown(res) != "":
            bad.append((label[:40], what(res), [w for w in need if not wanted or w not in wanted[0]]))
    assert not bad, report(bad)


# ================================================================== F5: a transport failure is not "the check did not agree"

def _down(exc=BackendError):
    def pick(q, w, o):
        raise exc("the model is unreachable")
    return pick


def _meaning_down(confirm, exc=BackendError):
    def pick(q, w, o):
        if str(w).startswith("If the applicant answers"):
            raise exc("the model is unreachable")
        return confirm
    return pick


F5_CELLS = (   # (label, type, the class, the model's wrong value, the confirmation that agrees with it)
    ("Have you ever been convicted of a criminal offence?", "RADIO", "declaration:criminal_record", "Yes", "Yes"),
    ("Is your criminal record satisfactory?", "RADIO", "declaration:criminal_record", "No", "No"),
    ("Are you legally authorised to work in the United States?", "RADIO", "work_right", "Yes", "Yes"),
    ("I am a politically exposed person", "CHECKBOX", "declaration:pep", "true", "yes"),
)


# U10 (fix8): on a canonical frame an agreeing wrong pair ends with NO meaning call, so a transport failure on the
# meaning call needs wordings with no reading (a box, a yes/no, a work-rights and an adverse-history one)
F5_MEANING_CELLS = (
    ("Is your criminal record satisfactory?", "RADIO", "declaration:criminal_record", "No", "No"),
    ("Is visa sponsorship required for you to work in the United States?", "RADIO", "sponsorship", "No", "No"),
    ("Any history of being dismissed from a job?", "RADIO", "declaration:other", "Yes", "Yes"),
    ("PEP status", "CHECKBOX", "declaration:pep", "true", "yes"),     # U12: the bare "Politically exposed person (PEP)" is a frame
)


def _wrong_value(written, value):
    return written is not None and (shown(written) == value or (value == "true" and is_ticked(written)))


def test_u9_f5_a_transport_failure_on_the_confirmation_ends_the_page_as_one_never_as_a_failed_check():
    """F5 (replaces "the check did not agree: left empty"): a BackendError or TimeoutError on the confirmation call ends
    the PAGE as `transport_failed` (model_unavailable, retryable). The wrong value is not written, the note does not say
    the check "did not agree", and exactly one call was made."""
    bad = []
    for exc in (BackendError, TimeoutError):
        for label, tn, klass, wrong, _conf in F5_CELLS:
            for kind in CLASSES:
                ask = FakeAsk(lambda v, kk=_k(kind, klass), w=wrong: lie(w, kk), pick=_down(exc))
                out = outcome(_field(label, tn=tn), ask)
                written = out.answers.get("u")
                if not out.transport_failed or len(ask.picks) != 1 or _wrong_value(written, wrong) \
                        or (written is not None and "did not agree" in str(written.note)):
                    bad.append((exc.__name__, label[:40], kind, out.transport_failed, len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f5_a_transport_failure_on_a_meaning_call_ends_the_page_as_one():
    """F5: the confirmation agrees with the model and the MEANING call fails at the transport (BackendError or
    TimeoutError): the page ends as a transport failure and the wrong value is not written."""
    bad = []
    for exc in (BackendError, TimeoutError):
        for label, tn, klass, wrong, conf in F5_MEANING_CELLS:
            ask = FakeAsk(lambda v, kk=klass, w=wrong: lie(w, kk), pick=_meaning_down(conf, exc))
            out = outcome(_field(label, tn=tn), ask)
            written = out.answers.get("u")
            if not out.transport_failed or _wrong_value(written, wrong):
                bad.append((exc.__name__, label[:40], out.transport_failed, len(ask.picks)))
    assert not bad, report(bad, 10)


def test_u9_f5_contrast_an_unusable_reply_is_a_failed_check_not_a_transport_failure():
    """F5 contrast: an UNUSABLE confirmation is the check not agreeing: the field ends empty (the site validates), the
    page does not end as a transport failure, the wrong value is not written."""
    bad = []
    for label, tn, klass, wrong, _conf in F5_CELLS:
        ask = FakeAsk(lambda v, kk=klass, w=wrong: lie(w, kk), pick=pick_by("", ""))
        out = outcome(_field(label, tn=tn), ask)
        written = out.answers.get("u")
        if out.transport_failed or written is None or _wrong_value(written, wrong):
            bad.append((label[:40], out.transport_failed, what(written) if written is not None else None))
    assert not bad, report(bad)


# ================================================================== F6: a required declaration the site pre-filled

F6_CELLS = (   # (label, type, options, the site's pre-selected ADVERSE value, the class)
    ("Have you ever been convicted of a criminal offence?", "RADIO", YN, "Yes", "declaration:criminal_record"),
    ("Have you ever been convicted of a criminal offence?", "DROPDOWN", ("Select", "Yes", "No"), "Yes",
     "declaration:criminal_record"),
    ("Are you a politically exposed person?", "RADIO", YN, "Yes", "declaration:pep"),
    ("I have been convicted of a criminal offence", "CHECKBOX", (), "true", "declaration:criminal_record"),
)


def _pre(label, tn, options, shown_value, *, required):
    return _pf("u", label, tn, required=required, options=options, shown=shown_value, origin=ValueOrigin.SITE_DEFAULT)


def _left_on_the_adverse_option(res) -> bool:
    """True when the field would be submitted still holding the site's adverse option: an Answer that neither wrote a
    value nor cleared the field (BLANK_OPTIONAL), and no stop naming the field."""
    if is_stop(res):
        return not (res.reason.value == "validation_error" and res.field_key == "u")
    return res.status not in (AnswerStatus.FILLED, AnswerStatus.BLANK_OPTIONAL)


def test_u9_f6_a_required_pre_selected_adverse_option_is_never_left_after_a_failed_vote():
    """F6 (the review: a required radio pre-selected "Yes", the vote ends empty, the page keeps the site's "Yes"): when
    the vote fails (a silent model with an unusable / adverse confirmation, or a model that agrees with the
    pre-selected value and a "yes" meaning reply) the REQUIRED field is never left on the adverse option: cleared, or
    the attempt stops with `validation_error` naming the field."""
    bad = []
    for label, tn, options, adverse, klass in F6_CELLS:
        yes = "yes" if tn == "CHECKBOX" else "Yes"
        for name, ask in (("silent, unusable confirmation", FakeAsk(pick=pick_by("", ""))),
                          ("silent, confirmation sides with the adverse option", FakeAsk(pick=pick_by(yes, "yes"))),
                          ("model agrees with the site, meaning yes",
                           FakeAsk(lambda v, a=adverse, k=klass: lie(a, k), pick=pick_by(yes, "yes")))):
            res = attempt(_pre(label, tn, options, adverse, required=True), ask)
            if _left_on_the_adverse_option(res):
                bad.append((tn, label[:40], name, what(res)))
    assert not bad, report(bad)


def test_u9_f6_an_optional_pre_selected_adverse_option_is_cleared_after_a_failed_vote():
    """F6: an OPTIONAL field the site pre-selected on the adverse option is CLEARED (BLANK_OPTIONAL) when the vote
    fails, never left holding the unconfirmed value."""
    bad = []
    for label, tn, options, adverse, _klass in F6_CELLS:
        res = attempt(_pre(label, tn, options, adverse, required=False), FakeAsk(pick=pick_by("", "")))
        if is_stop(res) or res.status is not AnswerStatus.BLANK_OPTIONAL:
            bad.append((tn, label[:40], what(res)))
    assert not bad, report(bad)


def test_u9_f6_controls_a_pre_selected_right_option_does_not_stop_and_a_model_no_overwrites_the_adverse_one():
    """F6 controls: a required radio pre-selected "No" (the owner's truth) is not an unconfirmed value: no stop even
    when the vote fails. A model that answers No over a pre-selected "Yes" writes the No."""
    bad = []
    label = "Have you ever been convicted of a criminal offence?"
    res = attempt(_pre(label, "RADIO", YN, "No", required=True), FakeAsk(pick=pick_by("", "")))
    if is_stop(res):
        bad.append(("pre-selected No", what(res)))
    ask = FakeAsk(lambda v: lie("No", "declaration:criminal_record"), pick=pick_by("No", "no"))
    res = attempt(_pre(label, "RADIO", YN, "Yes", required=True), ask)
    if shown(res) != "No":
        bad.append(("model No over a pre-selected Yes", what(res)))
    assert not bad, report(bad)


# ================================================================== fix4

def test_u9_fix4_a_marketing_class_the_code_frame_does_not_find_gets_one_corrected_ask_and_ends_ordinary():
    """fix4 (1): "Do you have experience in other roles of this type?" labelled `marketing` by the model is an experience
    question: ONE corrected ask ("this question is class ordinary"), taken as an ordinary answer. Field calls: 3 on a
    default basis (main, neutral re-check, corrected ask), 2 on a profile or resume basis (main, corrected ask). The
    Yes stands whatever the opt-in row says (never forced to the talent-pool No), assumed, with the note
    "class corrected: marketing -> ordinary"."""
    label = "Do you have experience in other roles of this type?"
    bad = []
    for basis, ref, calls in (("default", "default:consent", 3), ("profile", "profile:consents.talent_pool_opt_in", 2),
                              ("resume", "", 2)):
        for opt_in in (False, True):
            ask = FakeAsk(pick=pick_by("", ""))
            ask.answer = lambda v, b=basis, r=ref, a=ask: say("Yes" if len(a.sent) >= 1 else "No", b, r, klass="marketing")
            res = attempt(_field(label), ask, profile_with(consents__talent_pool_opt_in=opt_in))
            if len(ask.sent) != calls or shown(res) != "Yes" or not res.assumed \
                    or "class corrected: marketing -> ordinary" not in f"{res.note} {res.evidence}":
                bad.append((basis, opt_in, len(ask.sent), what(res)))
    assert not bad, report(bad)


def test_u9_fix4_the_forced_correction_never_runs_for_a_declaration_the_model_keeps():
    """fix4 ruling (replaces the first build, which corrected a kept declaration): "Do you have any health issues we
    should know about?" labelled `declaration:health` and KEPT after the neutral re-check stays a declaration: 2 field
    calls (main + re-check), never a third; no "class corrected" note; the model's Yes is checked (one confirmation:
    No -> No assumed; Yes / unusable -> empty), never written as an ordinary answer."""
    label = "Do you have any health issues we should know about?"
    bad = []
    for basis, ref in (("default", "default:no_declaration"), ("resume", "")):
        for confirm, want in (("No", "No"), ("Yes", ""), ("", "")):
            ask = FakeAsk(lambda v, b=basis, r=ref: say("Yes", b, r, klass="declaration:health"), pick=pick_by(confirm, ""))
            res = attempt(_field(label), ask)
            if len(ask.sent) != 2 or len(ask.picks) != 1 or shown(res) != want \
                    or "class corrected" in f"{res.note} {res.evidence}":
                bad.append((basis, f"confirmation {confirm!r}", len(ask.sent), len(ask.picks), what(res)))
    assert not bad, report(bad)


OWN = (   # (label, type, the profile value: the sample applicant's own)
    ("Your name", "TEXT", "Alex Testcase"), ("Applicant's name", "TEXT", "Alex Testcase"),
    ("Your email address", "EMAIL", "alex.testcase@example.com"), ("Your phone number", "PHONE", "91234567"),
    ("My mobile number", "PHONE", "91234567"),
)


def test_u9_fix4_a_your_or_my_name_email_or_phone_is_the_applicants_own_whatever_class_the_model_names():
    """fix4 (3): "Your name", "Applicant's name", "Your email address", "Your phone number" and "My mobile number" are the
    applicant's own: the profile value is written BEFORE the model (no field call), whatever class the model would name
    (an owner-fact ID, another person, a declaration, ordinary, none) and whatever value it would give."""
    bad = []
    for label, tn, value in OWN:
        for kind in ("owner_fact:other_id", "other_person", "declaration:other", "ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, kk=kind: lie("Pat Someone", kk))
            res = attempt(_pf("u", label, tn, required=True), ask)
            if is_stop(res) or shown(res) != value or ask.sent:
                bad.append((label, str(kind)[:14], what(res), len(ask.sent)))
    assert not bad, report(bad)


def test_u9_fix4_a_referees_name_is_not_the_applicants_and_keeps_the_models_value():
    """fix4 (3) limit: "Your referee's name" names ANOTHER person; it never takes the applicant's own name."""
    res = attempt(_pf("u", "Your referee's name", "TEXT", required=True), FakeAsk(lambda v: lie("Pat Someone", "other_person")))
    assert "Alex" not in shown(res) and "Testcase" not in shown(res), what(res)


def _confirm_wanted(ask):
    return [p[1] for p in ask.picks if not p[1].startswith("If the applicant answers")]


def test_u9_fix4_every_declaration_class_has_a_truth_sentence_in_both_polarities():
    """fix4 (4): the confirmation call states the owner's truth for EVERY declaration class, in both polarities, so the
    class is not left with no confirmation (and an empty field): the three employer-history classes ("has worked for /
    has never worked for this employer", "is / is not a current employee", "has / has not applied before") and health."""
    bad = []
    cases = (   # (label, class, rctx kwargs, a word the WANTED sentence must hold, a word it must not hold)
        ("Have you ever worked for this company before?", "declaration:prior_employment_at_company",
         {"employer_name": "Sample Analytics"}, "has worked for this employer", "never"),
        ("Have you ever worked for this company before?", "declaration:prior_employment_at_company",
         {}, "has never worked for this employer", None),
        ("Are you a current employee of this company?", "declaration:current_employee_at_company",
         {}, "is not a current employee of this employer", None),
        ("Have you previously applied to this company?", "declaration:previously_applied",
         {"previously_applied": True}, "has applied to this employer before", "not applied"),
        ("Have you previously applied to this company?", "declaration:previously_applied",
         {}, "has not applied to this employer before", None),
        ("Do you have any health issues we should know about?", "declaration:health",
         {}, "has no health condition", None),
    )
    for label, klass, kw, holds, not_holds in cases:
        wrong = "No" if "has worked" in holds or "has applied" in holds else "Yes"
        ask = FakeAsk(lambda v, k=klass, w=wrong: lie(w, k), pick=pick_by("", ""))
        res = attempt(_field(label), ask, rctx_kw=dict(kw))
        wanted = _confirm_wanted(ask)
        if not wanted or holds not in wanted[0] or (not_holds and not_holds in wanted[0]):
            bad.append((label[:40], klass, dict(kw), wanted[:1], what(res)))
    assert not bad, report(bad)


def test_u9_fix4_a_long_class_check_instruction_arrives_whole_not_cut_at_200_characters():
    """fix4: a field view's `problem` was cut at 200 characters, which cut every class check (214-416 characters) before its
    instruction. PROBLEM_MAX = 480 holds the longest class check and corrected ask whole, and the instruction's LAST
    sentence reaches the model on the re-check call."""
    from jobscraper.apply import always as AL
    lengths = []
    for value in AL.CLASS_DEFS:
        from jobscraper.apply.contracts import FieldClass
        klass = FieldClass(value) if value in {c.value for c in FieldClass} else None
        if klass is None:
            continue
        lengths.append(len(AL.class_check_problem(klass, "other")))
        lengths.append(len(AL.class_correct_problem(klass, "other")))
    assert max(lengths) > 200, ("the pin must exercise a problem longer than the old cap", max(lengths))
    assert max(lengths) <= AL.PROBLEM_MAX, (max(lengths), AL.PROBLEM_MAX)
    last = "the class is ordinary: answer it from the resume and profile."
    ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration", klass="declaration:non_compete"), pick=pick_by("", ""))
    attempt(_field("Have you worked on similar roles before?"), ask)
    assert len(ask.users) == 2 and last in ask.users[1], ("the re-check's last sentence did not reach the model",
                                                          ask.users[1][-400:] if len(ask.users) > 1 else None)
