"""Q-121 Amendment A1, the fix9 pin round (real-model run, pages 20 / 26 / 28; coordinator rulings fix9-1, fix9-2, W).

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step, so every pin keeps its assertion
on the HARMFUL value (a work-rights or sponsorship claim the profile does not give, a retention consent given or
withheld against the profile, an answer on a default rule that does not belong to it written as if it were a profile
fact). Expected values come from the rulings, never from what the code does:

  fix9-1  CODE KEYS for wordings that had none (class detection only; no reading, no canonical frame): SPONSORSHIP for
          a need word plus the employer applying for / obtaining / sponsoring a work permit / pass / visa for the
          applicant; WORK RIGHT for "prohibited from working in X", "on a temporary or student visa", "a foreigner /
          foreign national requiring a work pass / permit", "a work pass that ties you to one employer". With the key
          firing, a WRONG model answer meets ruling W and the vote EVEN WHEN the model's class is `ordinary` or
          missing: never the contradicting value, class right / ordinary / missing alike.
  fix9-2  an explicit keep-on-file wording ("Please keep my application on file for 12 months", "I wish to be
          considered for other suitable roles") is RETENTION whatever class the model gives: the box follows
          `consents.data_retention_consent` (true -> ticked, false -> unticked; a REQUIRED one with false ->
          `consent_refused`), 0 calls.
  A-def   an ORDINARY answer that rests on a default rule that does not belong to it (`default:willing`,
          `default:no_declaration` on "Are you liable for reservist duties?") must be marked ASSUMED, never written as a
          profile fact (real-model run, part 28).

Fakes only: no model, no network, no browser, sample profile (a Singapore citizen: authorised in SG, NOT authorised in
the US, National Service completed, all declarations false, retention consent true), made-up names.
Verify: python tests/run_tests.py -k always_a1_fix9
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, code_key_of, is_stop, is_ticked, is_unticked, lie, pick_by, pick_faithful,
    profile_with, report, say, shown, stop_is, what, _pf)

CLASSES = ("right", "ordinary", NO_CLASS)


def _k(kind, right):
    return right if kind == "right" else kind


def _f(label, *, tn="RADIO", required=True, **kw):
    return _pf("u", label, tn, required=required, options=YN if tn == "RADIO" else (), **kw)


# ================================================================== fix9-1: the work-permit and work-rights keys

# (label, class, the RIGHT answer for the sample owner). Singapore: authorised, needs no sponsorship, no restriction.
# United States: NOT authorised, needs sponsorship. A country-less wording reads the posting's country (Singapore).
FIX9_CELLS = (
    ("Will you need your employer to apply for a work permit for you in Singapore?", "sponsorship", "No"),
    ("Will you need your employer to apply for a work permit for you in the United States?", "sponsorship", "Yes"),
    ("Do you need us to sponsor a work pass in Singapore?", "sponsorship", "No"),
    ("Do you need us to sponsor a work pass in the United States?", "sponsorship", "Yes"),
    ("Will Example Co have to obtain an employment pass for you in Singapore?", "sponsorship", "No"),
    ("Will Example Co have to obtain an employment pass for you in the United States?", "sponsorship", "Yes"),
    ("Are you prohibited from working in Singapore?", "work_right", "No"),
    ("Are you prohibited from working in the United States?", "work_right", "Yes"),
    ("Are you a foreign national requiring a work permit to work in Singapore?", "work_right", "No"),
    ("Are you a foreign national requiring a work permit to work in the United States?", "work_right", "Yes"),
    ("Are you on a temporary or student visa?", "work_right", "No"),
    ("Do you hold a work pass that ties you to one employer?", "work_right", "No"),
)


def _opposite(v):
    return "No" if v == "Yes" else "Yes"


def test_fix9_1_each_new_wording_is_keyed_to_its_family_by_code_alone():
    """fix9-1: code's own class key names the family for every wording (class detection only: nothing here says what the
    right answer is). Controls with a need word but no pass, or a pass but no employer-applies verb, stay unkeyed."""
    bad = []
    for label, klass, _right in FIX9_CELLS:
        got = code_key_of(_f(label))[0]
        if got != klass:
            bad.append((label[:60], "want", klass, "got", got))
    for label in ("Will you need your employer to provide a laptop?", "Do you need us to sponsor your conference ticket?",
                  "Will you need your employer to apply for a parking permit for you?",
                  "Do you hold a library card that ties you to one branch?"):
        got = code_key_of(_f(label))[0]
        if got in ("sponsorship", "work_right"):
            bad.append((label[:60], "control wrongly keyed", got))
    assert not bad, report(bad)


def test_fix9_1_a_wrong_model_answer_is_never_written_whatever_class_the_model_names():
    """fix9-1 + W: model WRONG (the opposite of the owner's truth), the confirmation agreeing with it and a FAITHFUL meaning
    reply (it does state the contradiction: "yes"): the contradicting value is never written, for an authorised and a
    not-authorised country, class right / ordinary / missing. (A wrong pair that a meaning reply "no" blesses is the
    accepted three-answers residual where code has no reading, U10: not pinned.)"""
    bad = []
    for label, klass, right in FIX9_CELLS:
        wrong = _opposite(right)
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_faithful(wrong, right))
            res = attempt(_f(label), ask)
            if shown(res) == wrong:
                bad.append((label[:62], kind, "wrong x3", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_fix9_1_a_wrong_model_answer_is_checked_not_written_with_no_call_under_every_class():
    """fix9-1: a wrong model answer on a keyed wording is never written with 0 calls (the vote runs: at least one pick),
    even when the model's class is `ordinary` or missing (the real-model row: with the class blanked, "Will you need your
    employer to apply for a work permit for you in the United States?" was written "No" for an applicant not authorised)."""
    bad = []
    for label, klass, right in FIX9_CELLS:
        wrong = _opposite(right)
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_faithful(right, right))
            res = attempt(_f(label), ask)
            if shown(res) == wrong or not ask.picks:
                bad.append((label[:62], kind, what(res), len(ask.picks)))
            elif shown(res) not in (right, ""):
                bad.append((label[:62], kind, "neither the truth nor empty", what(res)))
    assert not bad, report(bad, 10)


def test_fix9_1_the_exact_real_model_row_with_the_class_blanked_is_never_written_no():
    """The real-model row, spelled out: not authorised in the United States, the model's wrong No, class `ordinary` or
    missing, a confirmation that agrees: never "No" (here the field ends empty or takes the truth after the vote)."""
    label = "Will you need your employer to apply for a work permit for you in the United States?"
    bad = []
    for kind in ("ordinary", NO_CLASS):
        for pick in (pick_by("No", "yes"), pick_by("", ""), pick_by("Yes", "yes"), pick_by("Yes", "")):
            ask = FakeAsk(lambda v, k=kind: lie("No", k), pick=pick)
            res = attempt(_f(label), ask)
            if shown(res) == "No":
                bad.append((kind, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_fix9_1_a_right_model_answer_is_not_overridden_and_a_silent_model_never_gets_a_blind_no():
    """fix9-1 control: a RIGHT model answer on a keyed wording is not turned into the wrong one; a SILENT model is asked
    (never a blind generic No from code on a not-authorised country)."""
    bad = []
    for label, klass, right in FIX9_CELLS:
        wrong = _opposite(right)
        ask = FakeAsk(lambda v, k=klass, r=right: lie(r, k), pick=pick_faithful(wrong, right))
        res = attempt(_f(label), ask)
        if shown(res) == wrong:
            bad.append((label[:60], "right model", what(res), len(ask.picks)))
        ask = FakeAsk(pick=pick_faithful(right, right))
        res = attempt(_f(label), ask)
        if shown(res) == wrong:
            bad.append((label[:60], "silent model", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


# ================================================================== fix9-2: an explicit keep-on-file box is retention

RETAIN = ("Please keep my application on file for 12 months", "I wish to be considered for other suitable roles")
RETAIN_CLASSES = ("consent_retention", "marketing", "ordinary", NO_CLASS, "declaration:other")


def test_fix9_2_the_box_follows_the_retention_consent_whatever_class_the_model_names():
    """fix9-2: consent TRUE -> the box is ticked, consent FALSE -> unticked (optional box), for each model class, with the
    model ticking AND with the model leaving it unticked, and 0 calls. The box never follows the model's class or value."""
    bad = []
    for label in RETAIN:
        for consent, want_ticked in ((True, True), (False, False)):
            p = profile_with(consents__data_retention_consent=consent)
            for klass in RETAIN_CLASSES:
                for said in ("true", "false"):
                    ask = FakeAsk(lambda v, k=klass, s=said: lie(s, k), pick=pick_by("", ""))
                    res = attempt(_pf("b", label, "CHECKBOX", required=False), ask, p)
                    if is_stop(res) or is_ticked(res) is not want_ticked or ask.picks:
                        bad.append((label[:34], f"consent {consent}", klass, f"model {said}", what(res), len(ask.picks)))
    assert not bad, report(bad, 10)


def test_fix9_2_a_required_retention_box_with_the_consent_refused_stops_with_consent_refused():
    """fix9-2: a REQUIRED keep-on-file box and `data_retention_consent: false` -> the attempt stops (`consent_refused`),
    never ticked, for every model class; with the consent true it is ticked."""
    bad = []
    for label in RETAIN:
        for klass in RETAIN_CLASSES:
            ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
            res = attempt(_pf("b", label, "CHECKBOX", required=True), ask, profile_with(consents__data_retention_consent=False))
            if not stop_is(res, "consent_refused"):
                bad.append((label[:34], klass, "refused + required", what(res)))
            ask = FakeAsk(lambda v, k=klass: lie("false", k), pick=pick_by("", ""))
            res = attempt(_pf("b", label, "CHECKBOX", required=True), ask)
            if is_stop(res) or not is_ticked(res):
                bad.append((label[:34], klass, "true + required", what(res)))
    assert not bad, report(bad, 10)


# ================================================================== A-def: a default rule that does not belong is ASSUMED

ORDINARY_DEFAULT_ROWS = (    # (label, the default rule the real model cited)
    ("Are you liable for reservist duties?", "default:willing"),
    ("Are you liable for reservist duties?", "default:no_declaration"),
    ("Do you hold a reserve rank or commission?", "default:willing"),
    ("Do you hold a reserve rank or commission?", "default:no_declaration"),
)


def test_a_def_an_ordinary_answer_on_a_default_rule_that_does_not_belong_is_marked_assumed():
    """Real-model run, part 28: "Are you liable for reservist duties?" and "Do you hold a reserve rank or commission?" (the
    profile holds neither fact) were written "No" with source `default:willing` / `default:no_declaration` and NOT marked
    assumed, so they read as profile facts. Expected: any such answer is marked ASSUMED (or the field is left empty).
    DEFECT while red."""
    bad = []
    for label, ref in ORDINARY_DEFAULT_ROWS:
        for kind in ("ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, r=ref, k=kind: say("No", "default", r, False, klass=k), pick=pick_by("", ""))
            res = attempt(_f(label), ask)
            if shown(res) != "" and not res.assumed:
                bad.append((label, ref, kind, what(res), len(ask.picks)))
    assert not bad, report(bad)
