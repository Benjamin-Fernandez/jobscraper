"""Q-121 Amendment A1, the pin round for the THIRD PASS after D-220 (docs/reviews/Q-121-final.md, "Third pass after D-220": M7, M8, L5,
L6) and the engineer's rulings D-221.

  M7  `_JOB_PLACE` also reads "the country (or location) in which / where you are applying", "the country you are applying to /
      for / in", "where you are applying", "of the / this posting / advertisement / application" as the JOB's own place.
  M8  the keep-on-file neutral list gained would / like / wish / want / happy / active / consideration / considered / suitable /
      relevant / skills / match / matching / available / become, "at", and the legal-form words (pte, ltd, limited, inc, llc, plc,
      corp, co, sdn, bhd, gmbh): a pure retention box with them is ticked by the retention consent alone; ANY other residue makes
      the truth `retention AND talent_pool_opt_in`.
  L5  (amended) a place quote counts only as a COMPLETE place phrase: rejected inside a longer word, before "'s", before and / or;
      what follows must be the end, or a run of words up to the first function word where every word is FRAME vocabulary
      (`always.frame_vocab()`).

RED UNTIL THE ENGINEER'S LAST COMMIT (ordinary prepositions such as under / as / until / after and time adverbs such as
permanently / indefinitely after a quoted place): the rows of `test_durations_and_ordinary_followers_keep_singapores_facts` that
end empty today are named in the failure line; everything else here is expected GREEN at int/Q-121 5c216a7.

Fakes only: no model, no network, no browser; sample profile (a Singapore citizen: authorised in SG, NOT in the US / UK; retention
consent true, talent pool opt-in false); the shared fake answers the place call with the sensible quote of tests/place_quote.py;
made-up names ("Example Employer").
Verify: python tests/run_tests.py -k always_a1_final_r7
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, pick_by, pick_faithful, profile_with, report, shown, what, _pf)
from test_always_a1_fix8 import _kinds  # noqa: E402

NOTE = "place not recognised"


def _f(label, *, required=True, options=YN, key="u"):
    return _pf(key, label, "RADIO", required=required, options=options)


def _box(label):
    return _pf("b", label, "CHECKBOX", required=False)


def _note(res) -> str:
    return "" if is_stop(res) else f"{res.note} {res.evidence}"


def _opp(v):
    return "No" if v == "Yes" else "Yes"


def _place_ask(value, klass="work_right", *, pick=None, place=None):
    return FakeAsk(lambda v: lie(value, klass), pick=pick or pick_faithful(value, value), place=place)


# ================================================================== M7: "the country in which you are applying" is the job's own place

M7_LABELS = (    # (label, the most place calls the engineer's table allows)
    ("Are you legally authorized to work in the country in which you are applying?", 0),
    ("Are you legally authorized to work in the country you are applying to?", 0),
    ("Are you legally authorized to work in the country you are applying for?", 0),
    ("Are you legally authorized to work in the country you are applying in?", 0),
    ("Are you legally authorized to work in the country of the posting?", 0),
    ("Are you legally able to work in the country of this posting?", 1),
)
M7_GUARDS = (    # NOT the job's own place: residence / citizenship / birth: no Singapore truth from the job country
    "Are you authorised to work in the country where you live?",
    "Are you authorised to work in the country where you currently reside?",
    "Are you authorised to work in your country of residence?",
    "Are you authorised to work in the country of your citizenship?",
    "Are you authorised to work in the country where you were born?",
)
M7_HOME = "Are you authorised to work in your home country?"


def test_m7_the_country_you_are_applying_in_is_the_jobs_country_and_answers_with_singapores_facts():
    """M7: the review's 6 labels on a Singapore job: a right model "Yes" is written (Singapore authorised), with at most the
    engineer's table of place calls (0 for five, 0 or 1 for "of this posting"), no place note; a WRONG model "No" with an
    agreeing confirmation and faithful meaning calls is never written (right value or empty)."""
    bad = []
    for label, most in M7_LABELS:
        ask = _place_ask("Yes")
        res = attempt(_f(label), ask)
        if is_stop(res) or shown(res) != "Yes" or NOTE in _note(res) or len(ask.place_calls) > most:
            bad.append((label[:62], "right model", what(res), len(ask.place_calls)))
        ask = _place_ask("No", pick=pick_faithful("No", "Yes"))
        res = attempt(_f(label), ask)
        if shown(res) == "No":
            bad.append((label[:62], "wrong model", what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_m7_guard_residence_citizenship_and_birth_country_are_not_the_jobs_place():
    """M7 guard: "the country where you live / currently reside", "your country of residence", "the country of your citizenship",
    "your home country", "the country where you were born" stay UNKNOWN: EMPTY with the place note, model Yes or No."""
    bad = []
    for label in M7_GUARDS:
        for value in ("Yes", "No"):
            ask = _place_ask(value, pick=pick_by(value, "no"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:62], value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_m7_guard_your_home_country_is_not_the_jobs_place():
    """M7 guard, listed apart because it FAILS at 5c216a7 (candidate DEFECT, MEDIUM): "Are you authorised to work in your home
    country?" is not the job's place (a citizen's home country need not be the job's), so it must end EMPTY with the place note
    like the other five guards. Today the sensible quote is NONE, code finds no place word, and the job country's facts are
    written ("Yes", source `profile:singapore_status.authorised_to_work.SG`, 1 place call): right by coincidence for a
    Singapore citizen on a Singapore job, wrong in general."""
    bad = []
    for value in ("Yes", "No"):
        ask = _place_ask(value, pick=pick_by(value, "no"))
        res = attempt(_f(M7_HOME), ask)
        if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
            bad.append((value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


# ================================================================== M8: pure retention wordings with friendly words

M8_PURE = (    # the review's wordings (the privacy-read "I authorize ... for two years" is left out: it is a privacy consent)
    "I would like Example Employer to keep my CV on file",
    "I would like to be kept on file for future opportunities",
    "Keep my application active for future roles",
    "Retain my information for future consideration",
    "Keep my profile for consideration for future roles",
    "Please keep my details on file for other suitable roles that match my skills",
    "Please keep my CV on file at Example Employer Pte Ltd",
)
M8_RESIDUE = (    # keep on file PLUS something else: a contact, a share, an event, a group, a partner or a client
    "Keep my application on file and send me relevant roles",
    "Keep my application on file so we can stay in touch",
    "Keep my application on file and message me on WhatsApp",
    "Keep my application on file and call me about opportunities",
    "Keep my application on file and invite me to events",
    "Retain my details for future positions and get in touch",
    "Keep my CV on file for 2 years for marketing purposes",
    "Keep my application on file for future opportunities and events",
    "Keep my application on file and let hiring managers see it",
    "Keep my application on file for roles in other regions",
    "Keep my application on file and notify me of new jobs",
    "Keep my application on file and send me updates",
)
M8_SHARING = (    # D-224 5a: third-party SHARING is its own consent: moved out of the both-consents table
    "Keep my CV on file and share my details with affiliates",
    "Keep my application on file for positions with our clients",
)
ONLY = dict(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
BOTH = dict(consents__data_retention_consent=True, consents__talent_pool_opt_in=True)


PASSIVE = "I would like to be kept on file for future opportunities"


def test_m8_pure_retention_boxes_with_friendly_words_are_ticked_by_the_retention_consent_alone():
    """M8: the review's 7 pure wordings ("I would like ...", "active", "consideration", "suitable ... match my skills", "at
    Example Employer Pte Ltd") with retention true / talent false: TICKED under the model classes retention and ordinary when the
    model ticks; the six wordings with a keep-on-file verb are ticked even when the model says false (the box follows the
    retention consent alone). The passive "kept on file" with a model that says false is pinned apart (next test)."""
    bad = []
    prof = profile_with(**ONLY)
    for label in M8_PURE:
        for klass in ("consent_retention", "ordinary"):
            for said in (("true",) if label == PASSIVE else ("true", "false")):
                ask = FakeAsk(lambda v, k=klass, s=said: lie(s, k), pick=pick_by("", ""))
                res = attempt(_box(label), ask, prof)
                if is_stop(res) or not is_ticked(res):
                    bad.append((label[:56], klass, said, what(res)))
    assert not bad, report(bad)


def test_m8_the_passive_kept_on_file_with_a_model_that_says_false_stays_unticked_as_it_is():
    """M8, pinned as it IS (the safe direction: an under-claim of the retention consent): "I would like to be kept on file for
    future opportunities" has no keep-on-file VERB for the code to key, so a model that names retention or ordinary but answers
    false is not overruled: unticked, assumed."""
    prof = profile_with(**ONLY)
    bad = []
    for klass in ("consent_retention", "ordinary"):
        ask = FakeAsk(lambda v, k=klass: lie("false", k), pick=pick_by("", ""))
        res = attempt(_box(PASSIVE), ask, prof)
        if is_stop(res) or is_ticked(res):
            bad.append((klass, what(res)))
    assert not bad, report(bad)


def test_m8_the_kept_on_file_passive_under_a_marketing_class_is_model_decided_not_ticked():
    """M8, pinned as it IS: "I would like to be kept on file for future opportunities" under the model class `marketing` (the
    model named the wrong class: one key, the model's) is NOT ticked, retention true / talent false."""
    prof = profile_with(**ONLY)
    ask = FakeAsk(lambda v: lie("true", "marketing"), pick=pick_by("", ""))
    res = attempt(_box("I would like to be kept on file for future opportunities"), ask, prof)
    assert not is_stop(res) and not is_ticked(res), what(res)


def test_m8_any_residue_needs_both_consents_under_every_class():
    """M8: the third pass's residue wordings (14: a contact, a message, an invitation, sharing, an event, a client, a hiring
    manager, a region, an update): retention only -> NOT ticked; both consents -> ticked; under every model class
    (marketing / retention / ordinary / none)."""
    bad = []
    for label in M8_RESIDUE:
        for klass in ("marketing", "consent_retention", "ordinary", NO_CLASS):
            for name, edits, want in (("retention only", ONLY, False), ("both", BOTH, True)):
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                res = attempt(_box(label), ask, profile_with(**edits))
                if is_stop(res) or is_ticked(res) is not want:
                    bad.append((label[:56], klass, name, "want ticked" if want else "want NOT ticked", what(res)))
    assert not bad, report(bad, 12)


def test_m8_sharing_with_a_third_party_is_unticked_in_every_consent_combination():
    """D-224 5a (moved out of the both-consents test above): "... share my details with affiliates" and "... positions with our
    clients" are third-party SHARING: NOT ticked in any retention / talent-pool combination under every model class, source
    `default:no_third_party_sharing`."""
    bad = []
    for label in M8_SHARING:
        for ret in (True, False):
            for pool in (True, False):
                prof = profile_with(consents__data_retention_consent=ret, consents__talent_pool_opt_in=pool)
                for klass in ("marketing", "consent_retention", "ordinary", NO_CLASS):
                    ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                    res = attempt(_box(label), ask, prof)
                    if is_stop(res) or is_ticked(res) or "no_third_party_sharing" not in str(res.source):
                        bad.append((label[:56], ret, pool, klass, what(res)))
    assert not bad, report(bad, 12)


def test_m8_a_partner_companies_box_is_unticked_in_all_four_consent_combinations():
    """M8 / R, as it IS: "Keep my application on file for roles at our partner companies" is a third-party reach ("partner"):
    NOT ticked in any combination of the retention / talent-pool consents, whatever the model's class."""
    label = "Keep my application on file for roles at our partner companies"
    bad = []
    for ret in (True, False):
        for pool in (True, False):
            prof = profile_with(consents__data_retention_consent=ret, consents__talent_pool_opt_in=pool)
            for klass in ("marketing", "consent_retention", "ordinary", NO_CLASS):
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                res = attempt(_box(label), ask, prof)
                if is_stop(res) or is_ticked(res):
                    bad.append((f"retention {ret}", f"pool {pool}", klass, what(res)))
    assert not bad, report(bad)


# ================================================================== L5 amended: only a COMPLETE place phrase is a place

PARTIAL = ("Are you authorised to work in Singapore's neighbouring countries?",
           "Are you authorised to work in the Singapore region?",
           "Are you authorised to work in the Singapore time zone?",
           "Are you authorised to work in Singapore Airlines?")


def test_l5_a_quote_that_is_only_part_of_a_place_phrase_ends_empty():
    """L5 (amended): the model quotes only "Singapore" from "Singapore's neighbouring countries" / "the Singapore region" / "the
    Singapore time zone" / "Singapore Airlines": a partial phrase, so the quote is rejected: EMPTY with the place note, whatever
    the model and the votes say."""
    bad = []
    for label in PARTIAL:
        for value in ("Yes", "No"):
            ask = _place_ask(value, place="Singapore", pick=pick_faithful(value, value))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:60], value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_l5_bank_of_singapore_is_answered_as_before():
    """L5 control: "Bank of Singapore" (a Singapore name in an employer's name; the quote "Singapore" ends the phrase) is
    answered with Singapore's facts as before: a right model "Yes" is written."""
    ask = _place_ask("Yes", place="Singapore")
    res = attempt(_f("Are you authorised to work for Bank of Singapore?"), ask)
    assert not is_stop(res) and shown(res) == "Yes" and NOTE not in _note(res), (what(res), len(ask.place_calls))


def test_l5_named_regression_guard_the_us_restriction_wordings_keep_the_right_us_value():
    """L5 NAMED REGRESSION GUARD (the amended follower rule must not reject the frame words after a quoted country): "Is your
    right to work in the US / USA / U.S. / United States restricted / limited?" keep the right US value ("Yes", restricted): the
    full grids live in test_always_a1_fix8.py (U10b), test_always_a1_u9.py and test_always_a1_final_r5.py (h1a); ONE row here per
    spelling so this file fails by itself if the follower rule regresses."""
    bad = []
    for c in ("the US", "the USA", "the U.S.", "the United States"):
        for word in ("restricted", "limited"):
            label = f"Is your right to work in {c} {word}?"
            ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "Yes":
                bad.append((label, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_l5_property_every_frame_vocabulary_word_after_a_quoted_singapore_is_never_follower_rejected():
    """L5 PROPERTY: for EVERY word W of `always.frame_vocab()` the label "Are you authorised to work in Singapore W?" with the
    quote "Singapore" is accepted by `quoted_place` (returns the job country), except the two joins "and" / "or": a readable frame is
    never follower-rejected."""
    from jobscraper.apply import always as AL
    bad = []
    # "and" / "or" are in the frame tables but are JOINS: a quote before them is rejected by design (P3 `_PLACE_JOINS`:
    # "Singapore and any other country"), so they are the one exception
    vocab = sorted(w for w in AL.frame_vocab() if w not in ("and", "or"))
    assert len(vocab) > 50, "frame_vocab() looks empty"
    for w in vocab:
        label = f"Are you authorised to work in Singapore {w}?"
        if AL.quoted_place("Singapore", label, "SG") != "SG":
            bad.append(w)
    assert not bad, f"{len(bad)} frame words reject the quote: {bad[:15]}"


# ================================================================== durations and ordinary followers

DURATIONS = (
    "Are you authorised to work in Singapore permanently?",
    "Are you authorised to work in Singapore indefinitely?",
    "Are you authorised to work in Singapore without time limit?",
    "Are you authorised to work in Singapore for more than 6 months?",
    "Are you authorised to work in Singapore after 2027?",
    "Are you authorised to work in Singapore for the next 12 months?",
    "Are you authorised to work in Singapore under an Employment Pass?",
    "Are you authorised to work in Singapore as a foreigner?",
    "Are you authorised to work in Singapore on a permanent basis?",
)
ACCEPTED_EMPTY = (
    "Are you authorised to work in Singapore subject to conditions?",
    "Are you authorised to work in Singapore or elsewhere?",
    "Are you authorised to work in Singapore and overseas?",
)


def test_durations_and_ordinary_followers_keep_singapores_facts():
    """Durations and ordinary followers after "Singapore" (permanently, indefinitely, without time limit, for more than 6
    months, after 2027, for the next 12 months, under an Employment Pass, as a foreigner, on a permanent basis): answered with
    Singapore's facts (a right "Yes" written, a place call at most one). RED UNTIL the engineer's last commit for any row that
    ends empty today (ordinary prepositions under / as / until / after and time adverbs permanently / indefinitely): the failure
    line names the row."""
    bad = []
    for label in DURATIONS:
        ask = _place_ask("Yes", place="Singapore")
        res = attempt(_f(label), ask)
        if is_stop(res) or shown(res) != "Yes" or NOTE in _note(res) or len(ask.place_calls) > 1:
            bad.append((label[:66], what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_conditions_or_elsewhere_and_overseas_end_empty_accepted():
    """Accepted, pinned as they ARE: "... subject to conditions", "... or elsewhere", "... and overseas" end EMPTY with the place
    note (an open-ended or conditional place)."""
    bad = []
    for label in ACCEPTED_EMPTY:
        for value in ("Yes", "No"):
            ask = _place_ask(value, place="Singapore", pick=pick_by(value, "no"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:62], value, what(res)))
    assert not bad, report(bad)


# ================================================================== L6 as it IS

def test_l6_other_than_and_beyond_wordings_end_empty_with_the_note_accepted():
    """L6, accepted and pinned as it IS: "... in Singapore for employers other than your current one?" and "... beyond 2027?"
    end EMPTY with the place note ("other than", "beyond" are open-place words), whatever the model says."""
    bad = []
    for label in ("Are you authorised to work in Singapore for employers other than your current one?",
                  "Are you authorised to work in Singapore beyond 2027?"):
        for value in ("Yes", "No"):
            ask = _place_ask(value, pick=pick_by(value, "no"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:62], value, what(res)))
    assert not bad, report(bad)
