"""Q-121 Amendment A1, closing pass part 2: the Coordinator's departures R-f (1)-(5) from design 17
and the engineer's departure (6). Fakes only; expected values from the design and the rulings.
(Departure (7), a plain grade text stays F4 and class-of-degree wording stops, is pinned already by
test_always_fix_pins::test_q1_* and test_always_a1::test_a1_h3_class_of_degree_...)
Verify: python tests/run_tests.py -k always_a1_close_rf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, code_key_of, is_stop, is_ticked, is_unticked, lie, page, pick_by, profile_with, report,
    say, shown, stop_is, what, _pf)

CONFLICT = "Do you declare any conflict of interest?"          # a tentative reader (the D-90 frame gate fails)
CONFIDENT = "Do you have any conflict of interest?"


# ================================================================== R-f (1): a required box left unticked is no answer

def test_rf1_a_required_consent_box_the_model_leaves_unticked_is_decided_by_code_not_taken_as_no():
    box = "I consent to the processing of my personal data"
    bad = []
    for klass in ("consent_privacy", "ordinary", NO_CLASS):
        # key true: the unticked reply counts as no answer; the owner's consent ticks it (design 17.2)
        res = attempt(_pf("c", box, "CHECKBOX"), FakeAsk(lambda v, k=klass: say("false", "default", "default:consent", klass=k)))
        if not is_ticked(res) or res.source != "profile:consents.privacy_consent":
            bad.append(("key true", klass, what(res)))
        # key false: no answer, so code decides: a required box with no refusing option -> consent_refused (R-c)
        res = attempt(_pf("c", box, "CHECKBOX"), FakeAsk(lambda v, k=klass: say("false", "default", "default:consent", klass=k)),
                      profile_with(consents__privacy_consent=False))
        if not stop_is(res, "consent_refused", "consents.privacy_consent"):
            bad.append(("key false", klass, what(res)))
    assert not bad, report(bad)


def test_rf1_a_required_declaration_box_the_model_leaves_unticked_is_never_ticked_when_it_states_the_adverse_fact():
    """D-211 P1 / P5 (replaces "code ticks 'I am not a PEP' with no call"): a positive box ("Tick if you are a
    PEP") is never ticked, whatever happens. A NEGATED statement box ("I am not a politically exposed
    person") holds a negation word, so code does not tick it on its own reading: the model's unticked reply is
    no answer (P5) and only a confirmation equal to the reader's option may tick it; an unusable one ->
    the protective end, unticked. The harmful outcomes are asserted here (a PEP box ticked by guess, or the
    positive one ticked); the call itself is pinned in the next test."""
    bad = []
    for klass in ("declaration:pep", "ordinary"):
        res = attempt(_pf("b", "I am not a politically exposed person", "CHECKBOX"),
                      FakeAsk(lambda v, k=klass: say("false", "default", "default:no_declaration", klass=k),
                              pick=pick_by("", "")))
        if is_ticked(res):          # an unusable confirmation: ticking would be code's own reading of a negation
            bad.append(("I am not a PEP", klass, "ticked with no usable confirmation", what(res)))
        res = attempt(_pf("b", "Tick if you are a politically exposed person", "CHECKBOX"),
                      FakeAsk(lambda v, k=klass: say("false", "default", "default:no_declaration", klass=k),
                              pick=pick_by("Yes", "yes")))
        if is_ticked(res):
            bad.append(("Tick if PEP", klass, what(res)))
    assert not bad, report(bad)


def test_rf1_p5_a_negated_statement_box_with_an_unticked_model_reply_gets_one_confirmation_call():
    """D-211 P5: a silent (unticked) model on a negated statement as a tick box: ONE confirmation call; the box
    is ticked only when the pick equals the reader's option, else the protective end. DEFECT while red: the
    code makes NO call on a checkbox (`_confirm_pick` returns None for a field with no options), so this
    required attestation box ("I am not a politically exposed person") can never be ticked: it ends
    unticked for every pick (fail-safe, but the ruled vote does not exist for boxes)."""
    for klass in ("declaration:pep", "ordinary", NO_CLASS):
        ask = FakeAsk(lambda v, k=klass: say("false", "default", "default:no_declaration", klass=k), pick=pick_by("", ""))
        res = attempt(_pf("b", "I am not a politically exposed person", "CHECKBOX"), ask)
        assert not is_ticked(res), (klass, what(res))
        assert len(ask.picks) == 1, (klass, "P5: one confirmation call expected, got", len(ask.picks))


def test_rf1_negative_control_an_optional_box_left_unticked_by_a_model_on_an_ordinary_question_stays_unticked():
    res = attempt(_pf("b", "I would like to be contacted by phone", "CHECKBOX", required=False),
                  FakeAsk(lambda v: say("false", "resume", "", klass="ordinary")))
    assert is_unticked(res), what(res)


# ================================================================== R-f (2): the vote is replaced
# (the H-unknown half of R-f (2) is SUPERSEDED by ruling P3: tests/test_always_a1_p.py)


def test_rf2_with_both_keys_and_a_known_h_the_owners_option_is_written_with_no_confirm_call():
    """D-212 U1-U4 (replaces "both keys + a known reader: code writes the owner's option with NO call"): code
    never writes its own reading alone. The model's wrong value differs from the reader's option -> ONE
    confirmation (the field call + 1): pick = the owner's option -> that option, assumed; unusable -> empty;
    a pick that sides with the wrong value -> the meaning call, unusable here -> empty. The model's RIGHT
    value is written with NO call (U1)."""
    bad = []
    for label, truth in ((CONFIDENT, "No"), ("Are you a politically exposed person?", "No"),
                         ("Are you legally authorised to work in Singapore?", "Yes")):
        wrong = "Yes" if truth == "No" else "No"
        ask = FakeAsk(lambda v, t=truth: say(t, "assumption", "", True, "guess"), pick=pick_by(wrong, "no"))
        res = attempt(_pf("p", label, options=YN), ask)
        if shown(res) != truth or ask.picks or len(ask.sent) != 1:
            bad.append((label, "model right", what(res), len(ask.picks), len(ask.sent)))
        # U10 (fix8): all three labels are canonical frames: a confirmation that sides with the model's wrong
        # value is a veto with NO meaning call (was 2 picks, now 1); the value is still never written
        for pick, want, picks in ((truth, truth, 1), ("", "", 1), (wrong, "", 1)):
            ask = FakeAsk(lambda v, w=wrong: say(w, "assumption", "", True, "guess"), pick=pick_by(pick, ""))
            res = attempt(_pf("p", label, options=YN), ask)
            if shown(res) != want or len(ask.picks) != picks or len(ask.sent) != 1 or (want and not res.assumed):
                bad.append((label, f"model wrong, confirm {pick!r}", what(res), len(ask.picks), len(ask.sent)))
    assert not bad, report(bad)


# ================================================================== R-f (3): M3 governs the yes/no mapping and F2's fit

M3_YN = (("Yes", "No, but I have in the past"), ("Yes, but I need sponsorship", "No"),
         ("Yes, only part time", "No longer"), ("Yes", "Not currently"))


def test_rf3_the_yes_no_mapping_and_f2_never_pick_an_option_that_adds_or_drops_a_negation_or_qualifier():
    bad = []
    for options in M3_YN:
        qualified = [o for o in options if o not in ("Yes", "No")]
        for said in (None, "Yes", "No"):
            ask = FakeAsk((lambda v, s=said: lie(s, "ordinary")) if said else None, pick=lambda q, w, o: "")
            res = attempt(_pf("q", "Are you currently studying part time?", "DROPDOWN", options=options), ask)
            if shown(res) in qualified:
                bad.append((options, f"model {said}", "wrote the qualified option", what(res)))
    assert not bad, report(bad)


# ================================================================== R-f (4): the added frame words

def test_rf4_add_me_and_include_me_are_marketing_have_you_read_is_an_acknowledgement():
    bad = []
    rows = (("Add me to your mailing list", "CHECKBOX", "marketing"), ("Include me in your talent community", "CHECKBOX", "marketing"),
            ("Add me to the job alerts", "RADIO", "marketing"), ("Add me to your newsletter", "CHECKBOX", "marketing"),
            ("Have you read our code of conduct?", "RADIO", "acknowledgement"),
            ("Have you read our privacy notice?", "RADIO", "acknowledgement"),
            ("Have you read our conflict of interest policy?", "RADIO", "acknowledgement"),   # not declaration:conflict (ruling 3)
            # negative controls: the same verbs without an object of the class stay ordinary
            ("Have you read any of our blog posts?", "RADIO", "ordinary"), ("Have you read the job description?", "RADIO", "ordinary"),
            ("Please add me to the shortlist", "CHECKBOX", "ordinary"), ("Include me in the interview round", "CHECKBOX", "ordinary"))
    for label, tn, klass in rows:
        got = code_key_of(_pf("k", label, tn, options=YN if tn == "RADIO" else ()))
        if got[0] != klass:
            bad.append((label, tn, "want", klass, "got", got))
    assert not bad, report(bad)


# ================================================================== R-f (5): the per-page call cap

def _page4():
    return [_pf(f"t{i}", f"Dummy short question {i}", "TEXT") for i in range(3)] + [_pf("o", "Dummy optional", "TEXT", required=False)]


def test_rf5_the_cap_spent_with_required_fields_still_open_stops_the_page_as_a_content_failure():
    from jobscraper.apply.contracts import CONTENT_FAILURE_MARKERS, ReasonCode
    # the model answers only t0: A3 uses one call, A5 the second = the cap, t1 and t2 are still open
    ask = FakeAsk(lambda v: say("x", "assumption", "", True) if v["id"] == "t0" else None)
    res = page(_page4(), ask, cfg={"max_calls_page": 2})
    assert is_stop(res) and res.reason is ReasonCode.UNANSWERABLE_REQUIRED \
        and res.detail.startswith(CONTENT_FAILURE_MARKERS[0]) and "too many model calls" in res.detail, what(res)


def test_rf5_negative_controls_a_spent_cap_with_nothing_required_open_or_a_cap_with_room_is_no_stop():
    # every required field answered by the one call: the cap is spent, nothing is open -> no stop
    ask = FakeAsk(lambda v: say("x", "assumption", "", True) if v["id"] != "o" else None)
    res = page(_page4(), ask, cfg={"max_calls_page": 1})
    assert not is_stop(res), what(res)
    assert res["t1"].value == "x" and res["o"].value in (None, ""), res
    # room for the A5 call: the open required fields get their must-answer round and the page ends normally
    ask = FakeAsk(lambda v: say("x", "assumption", "", True) if v["id"] == "t0" else None)
    res = page(_page4(), ask, cfg={"max_calls_page": 3})
    assert not is_stop(res), what(res)


# ================================================================== engineer departure (6): an optional vetoed field

def test_dep6_an_optional_vetoed_field_also_gets_the_must_answer_round_and_the_protective_end():
    """D-212 U2 / U4 (replaces "an optional vetoed field gets the A5 must-answer round, then the protective end
    writes the owner's No"): there is no A5 round any more (ONE field call); ONE confirmation call; the pick
    No writes No (assumed); an unusable pick, or one that sides with the model's Yes (then the meaning call,
    unusable here), leaves the optional field empty. Never Yes."""
    label = "Do you have a relative working at Example Employer?"
    bad = []
    # U10 (fix8): "Do you have a relative working at ..." is a canonical frame; the model's Yes and an agreeing Yes
    # confirmation go against its reading: a veto, the protective end, NO meaning call (was 2 calls, now 1).
    for pick, want, picks in (("No", "No", 1), ("", "", 1), ("Yes", "", 1)):
        ask = FakeAsk(lambda v: lie("Yes", "ordinary"), pick=pick_by(pick, ""))
        res = attempt(_pf("r", label, options=YN, required=False), ask)
        if shown(res) != want or len(ask.sent) != 1 or len(ask.picks) != picks:
            bad.append((f"pick={pick!r}", what(res), len(ask.sent), len(ask.picks)))
    assert not bad, report(bad)
