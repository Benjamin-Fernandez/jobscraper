"""Q-121 closure fix round G (D-222 S1-S3, D-223 G1-G3 + M2, D-224 items 1, 3, 5a, 5b): the pins for the two HIGH faults of the closure
review (`docs/reviews/Q-121-closure.md`) and for what the engineer's fix changed. The same review's own probes (`p21.py`, `p23.py`,
`p2.py`, `p3.py`, `p18.py`, `p19.py`) are the source of the labels.

  H1  a consent / certification / acknowledgement / retention / marketing box or question that merely mentions "Singapore citizen" is
      decided by the CONSENT family from the consents, never from the nationality fact
  H2  a question about someone else, National Service, a scholarship, passport validity, "renounced / former / intend" is never answered
      FROM the nationality / residency fact
  G1  precedence: each protected code key behaves the same with or without a status phrase in its label
  G2  a PLAIN status sentence is decided by code whatever class the model names (never an `owner_fact_missing` stop); D-224 3 form
      furniture keeps it plain; "by descent / previously / dual / another country" go to G3 (no fact cited)
  5a  third-party SHARING is its own consent (`default:no_third_party_sharing`); the excluded wordings are unchanged
  M2  sentence punctuation and time subordinators no longer empty a plain Singapore wording; "throughout" is left out ON PURPOSE
  M1  accepted limit, pinned as it is

Fakes only: no model, no network, no browser; the sample profile (a Singapore citizen) and in-memory variants of it; made-up names only.
Verify: python tests/run_tests.py -k always_a1_final_r9
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, consent_profile, is_stop, is_ticked, lie, pick_by, pick_faithful, profile_with, report, stop_is,
    shown, what, _pf, code_key_of)

# ------------------------------------------------------------------ helpers


def _radio(label, *, required=True):
    return _pf("u", label, "RADIO", required=required, options=YN)


def _box(label, *, required=False):
    return _pf("b", label, "CHECKBOX", required=required)


def _src(res) -> str:
    return "" if is_stop(res) else str(res.source or "")


def _cites_nationality(res) -> bool:
    """True when the written answer names the nationality or residency fact as its source (the review's `...nationality` /
    `...residency_status`). A source on another fact (`authorised_to_work`, `work_pass`, `ns_status`) is not this check."""
    s = _src(res)
    return "nationality" in s or "residency_status" in s


def _box_faithful(truth: bool):
    """A scripted `pick` for the status TICK BOX "I am a Singapore citizen" that reads like a faithful reader: the confirmation says
    "yes" when the sentence it is given says the applicant IS a citizen; the meaning call says "yes" (a contradiction) exactly when
    the value asked about states the opposite of `truth`."""
    import re

    def pick(q, w, o):
        w = str(w)
        if w.startswith("If the applicant answers"):
            ticked = re.search(r"answers .(ticked|unticked).", w).group(1) == "ticked"
            claims_not = "is not a citizen" in w            # the statement the question asks about
            claim_of_value_is_not = not ticked              # ticked says "I am a citizen", unticked says the opposite
            return "yes" if claims_not == claim_of_value_is_not else "no"
        return "yes" if w.startswith("The applicant is a citizen") else "no"
    return pick


def _opp(v):
    return "No" if v == "Yes" else "Yes"


def _place(quote):
    return quote


def _beh(res):
    """What a field ends as, for a byte-for-byte comparison: a stop (reason + target) or (shown, source, assumed)."""
    if is_stop(res):
        return ("STOP", res.reason.value, res.target_path)
    return (shown(res), _src(res), bool(res.assumed))


CLASSES = ("ordinary", "work_right", "owner_fact", "consent_privacy", "marketing", NO_CLASS)

# ================================================================== H1: consent words beat a status word

H1_BOXES = (    # (label, the class the model names for it)
    ("I consent to the collection and use of my personal data as a Singapore citizen or PR under the PDPA", "consent_privacy"),
    ("I agree to the privacy policy and confirm I am a Singapore citizen", "consent_privacy"),
    ("I certify that I am a Singapore citizen and that the information provided is true and complete", "certification"),
    ("I acknowledge that I have read the notice for Singapore citizen applicants", "acknowledgement"),
    ("Keep my application on file; I am a Singapore citizen", "consent_retention"),
    ("I am a Singapore citizen and agree to receive job alerts", "marketing"),
)
H1_RADIOS = (
    ("Do you consent to the processing of your personal data as a Singapore citizen?", "consent_privacy"),
    ("As a Singapore citizen, do you agree to be contacted about other roles?", "marketing"),
    ("Do you agree to keep your application on file? (Singapore citizens only)", "consent_retention"),
    ("Are you a Singapore citizen and do you agree to receive our newsletter?", "marketing"),
)
KEEP_RADIO = "Do you agree to keep your application on file? (Singapore citizens only)"


def _h1_box(label, klass, profile, required):
    ask = FakeAsk(lambda v: lie("true", klass), pick=pick_by("yes", "no"), place="NONE")
    return attempt(_box(label, required=required), ask, profile)


def test_h1_with_every_consent_false_a_consent_box_that_names_a_status_is_never_ticked():
    """H1 (review p21): the owner's four consents are false. A REQUIRED privacy / certification / acknowledgement / retention box ->
    STOP `consent_refused`; the REQUIRED marketing box is unticked (it has never stopped: pinned as it is); an OPTIONAL box is unticked;
    under the class the model names and under five others (ordinary, work_right, owner_fact, privacy, marketing, none); and NEVER a source
    that cites the nationality or residency fact."""
    bad = []
    prof = consent_profile("false")
    for label, own in H1_BOXES:
        for klass in (own,) + CLASSES:
            for required in (True, False):
                res = _h1_box(label, klass, prof, required)
                if is_ticked(res) or _cites_nationality(res):
                    bad.append((label[:50], klass, required, "ticked or cites the fact", what(res)))
                elif required and own != "marketing" and not stop_is(res, "consent_refused"):
                    bad.append((label[:50], klass, "required", "want STOP consent_refused", what(res)))
                elif (not required or own == "marketing") and is_stop(res):
                    bad.append((label[:50], klass, required, "want unticked, got a stop", what(res)))
    assert not bad, report(bad, 12)


def test_h1_with_every_consent_true_the_same_boxes_are_ticked():
    """H1, the other direction: all four consents true -> ticked (required and optional) under every model class, never a
    nationality / residency source (the consent decides; the status word does not)."""
    bad = []
    prof = consent_profile("true")
    for label, own in H1_BOXES:
        for klass in (own,) + CLASSES:
            for required in (True, False):
                res = _h1_box(label, klass, prof, required)
                if is_stop(res) or not is_ticked(res) or _cites_nationality(res):
                    bad.append((label[:50], klass, required, what(res)))
    assert not bad, report(bad, 12)


def test_h1_yes_no_questions_that_name_a_status_follow_the_consents_not_the_nationality():
    """H1 (review p23): the radios. All consents false -> "No"; all true -> "Yes", under every model class. One safe empty is allowed
    and pinned as it is: "Do you agree to keep your application on file? (Singapore citizens only)" under the model class
    `work_right` ends empty (never the opposite of the consent)."""
    bad = []
    for kind, want in (("false", "No"), ("true", "Yes")):
        prof = consent_profile(kind)
        for label, own in H1_RADIOS:
            for klass in (own,) + CLASSES:
                ask = FakeAsk(lambda v, k=klass: lie("Yes", k),
                              pick=lambda q, w, o: "no" if str(w).startswith("If the") else "yes", place="NONE")
                res = attempt(_radio(label), ask, prof)
                got = shown(res)
                ok_empty = label == KEEP_RADIO and klass == "work_right" and got == ""
                if (got != want and not ok_empty) or _cites_nationality(res):
                    bad.append((label[:50], kind, klass, f"want {want}", what(res)))
    assert not bad, report(bad, 12)


# ================================================================== H2: no answer FROM the nationality fact

H2_LABELS = (
    "Is your spouse a Singapore citizen?", "Is your father a Singapore citizen?", "Is your mother a Singapore citizen or PR?",
    "Is your referee a Singapore citizen?", "Is your emergency contact a Singapore citizen?",
    "Do you have a family member who is a Singapore citizen?", "Is your spouse a Singapore PR?",
    "Does the role require a Singapore citizen?",
    "Have you completed Singapore National Service?", "Have you completed your Singapore National Service obligations?",
    "Are you currently serving Singapore National Service?", "Are you exempted from Singapore National Service?",
    "Are you a Singapore national scholarship holder?", "Do you have a Singapore national certification?",
    "Do you hold a Singapore passport that expires within 6 months?",
    "Do you hold a valid Singapore passport with at least 6 months validity?",
    "Have you ever renounced Singapore citizenship?", "Are you a former Singapore citizen?",
    "Do you intend to apply for Singapore citizenship?", "Would you like to become a Singapore citizen?",
    "Were you a Singapore PR before becoming a citizen?", "Are you a tax resident of Singapore?",
    "Have you been a Singapore PR for at least 2 years?",
)


def test_h2_a_question_that_is_not_a_plain_status_question_is_never_answered_from_the_nationality_fact():
    """H2 (review p1/p2/p3/p18/p19): 23 labels (another person's status, the role's requirement, National Service, a scholarship,
    a certification, passport validity, renounced / former / intend / become / before, tax resident, PR for 2 years) x 6 model classes
    x model Yes / No x a confirmation that follows the model / contradicts it: the written answer (when there is one) never names the
    nationality / residency / work-pass fact as its source. (`singapore_status.ns_status` is the National Service fact and is allowed.)"""
    bad = []
    for label in H2_LABELS:
        for klass in ("ordinary", "work_right", "owner_fact", "other_person", "declaration", NO_CLASS):
            for m in ("Yes", "No"):
                for confirm in (m, _opp(m)):
                    ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(confirm, "No"), place="NONE")
                    res = attempt(_radio(label), ask)
                    if _cites_nationality(res):
                        bad.append((label[:50], klass, m, confirm, what(res)))
    assert not bad, report(bad, 12)


def test_h2_which_key_wins_for_each_review_label():
    """H2, the engineer's table: a spouse / referee / emergency contact is keyed to the other-person rules (`declaration:other` or
    `other_person`); a father / mother / family member / role requirement is NOT keyed `work_right` (never a status question); National
    Service has no `work_right:status` key (the NS mechanic answers it, next test); a scholarship, certification, passport validity,
    renounced / former / intend / become / before / tax resident / PR for 2 years are `work_right:status` with NO code truth (G3)."""
    other = {"Is your spouse a Singapore citizen?": ("declaration", "other"), "Is your referee a Singapore citizen?": ("other_person", ""),
             "Is your spouse a Singapore PR?": ("declaration", "other")}
    not_status = ("Is your father a Singapore citizen?", "Is your mother a Singapore citizen or PR?", "Is your emergency contact a Singapore citizen?",
                  "Do you have a family member who is a Singapore citizen?",
                  "Have you completed Singapore National Service?", "Have you completed your Singapore National Service obligations?",
                  "Are you currently serving Singapore National Service?", "Are you exempted from Singapore National Service?")
    g3 = ("Does the role require a Singapore citizen?", "Are you a Singapore national scholarship holder?", "Do you hold a Singapore passport that expires within 6 months?",
          "Have you ever renounced Singapore citizenship?", "Are you a former Singapore citizen?",
          "Do you intend to apply for Singapore citizenship?", "Would you like to become a Singapore citizen?",
          "Were you a Singapore PR before becoming a citizen?", "Are you a tax resident of Singapore?",
          "Have you been a Singapore PR for at least 2 years?")
    bad = []
    for label, want in other.items():
        got = code_key_of(_radio(label))
        if got != want:
            bad.append((label, "want", want, "got", got))
    for label in not_status:
        got = code_key_of(_radio(label))
        if got[0] == "work_right":
            bad.append((label, "must not be work_right", got))
    for label in g3:
        got = code_key_of(_radio(label))
        if got != ("work_right", "status"):
            bad.append((label, "want G3 key", ("work_right", "status"), "got", got))
    assert not bad, report(bad, 12)


NS_CASES = (    # (label, the right answer for ns_status completed, for ns_status exempted)
    ("Have you completed Singapore National Service?", "Yes", "No"),
    ("Have you completed your Singapore National Service obligations?", "Yes", "No"),
    ("Have you completed national service in Singapore?", "Yes", "No"),
)
# NOT here: "Are you exempted from ..." / "Are you currently serving ..." have NO `ns_status` truth by design (fix7 ruling 2,
# `_NS_NOT_THIS`): the model answers them, marked assumed (outbox: noted, not pinned as a truth).


def test_h2_national_service_follows_ns_status_and_a_contradicting_model_answer_is_never_written():
    """H2 / D-224 5b: with `singapore_status.ns_status` `completed` or `exempted` (the real enum: completed / serving / exempted /
    not_applicable; the review's probe used "exempt", which is not one), a National Service question is answered from that fact
    whatever class the model names: the OPPOSITE of the truth is never written (a stop under the model class `owner_fact` is allowed,
    it is no wrong answer); with a right model the truth is written; no answer cites the nationality fact."""
    bad = []
    for ns, col in (("completed", 1), ("exempted", 2)):
        prof = profile_with(singapore_status__ns_status=ns)
        for label, *truths in NS_CASES:
            truth = truths[col - 1]
            for klass in ("ordinary", "work_right", "owner_fact", "other_person", "declaration", NO_CLASS):
                for m in ("Yes", "No"):
                    for confirm in (m, _opp(m)):
                        ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(confirm, truth), place="NONE")
                        res = attempt(_radio(label), ask, prof)
                        got = shown(res)
                        if (not is_stop(res) and got == _opp(truth)) or _cites_nationality(res):
                            bad.append((ns, label[:50], klass, f"model {m}", f"confirm {confirm}", f"truth {truth}", what(res)))
                        if m == truth and not is_stop(res) and got != truth:
                            bad.append((ns, label[:50], klass, "right model not written", what(res)))
    assert not bad, report(bad, 12)


def test_h2_national_service_ns_status_overrides_a_wrong_model_answer_with_its_own_source():
    """D-224 5b, the two review probes: `completed` + a model "No" to "Have you completed Singapore National Service?" is written "Yes"
    from `profile:singapore_status.ns_status` (never "No"); `exempted` + a model "Yes" is written "No" the same way; under the classes
    ordinary / work_right / declaration / other_person / none."""
    bad = []
    for ns, m, want in (("completed", "No", "Yes"), ("exempted", "Yes", "No")):
        prof = profile_with(singapore_status__ns_status=ns)
        for klass in ("ordinary", "work_right", "declaration", "other_person", NO_CLASS):
            ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(m, want), place="NONE")
            res = attempt(_radio("Have you completed Singapore National Service?"), ask, prof)
            if is_stop(res) or shown(res) != want or _src(res) != "profile:singapore_status.ns_status":
                bad.append((ns, klass, f"model {m}", f"want {want}", what(res)))
    assert not bad, report(bad)


G3_LABELS = (
    "Does the role require a Singapore citizen?",
    "Are you a Singapore national scholarship holder?", "Do you hold a Singapore passport that expires within 6 months?",
    "Have you ever renounced Singapore citizenship?", "Are you a former Singapore citizen?",
    "Do you intend to apply for Singapore citizenship?", "Would you like to become a Singapore citizen?",
    "Are you a Singapore citizen by descent?", "Were you previously a Singapore citizen?", "Are you a dual Singapore citizen?",
)


def test_g3_a_status_wording_with_anything_else_in_it_has_no_code_truth_model_plus_one_confirmation():
    """D-223 G3 on the review's H2 wordings and the D-224 3 "not furniture" ones (by descent, previously, dual): the model's answer
    is written only when ONE confirmation agrees with it (assumed True, source `assumption`, never a profile fact); a differing
    confirmation ends the field empty; under the classes work_right / ordinary / no class."""
    bad = []
    for label in G3_LABELS:
        for klass in ("work_right", "ordinary", NO_CLASS):
            for m in ("Yes", "No"):
                ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(m, m), place="NONE")
                res = attempt(_radio(label), ask)
                if is_stop(res) or shown(res) != m or not res.assumed or _src(res) != "assumption" or len(ask.picks) > 2:
                    bad.append((label[:50], klass, m, "agreeing check", what(res), f"{len(ask.picks)} picks"))
                # D-225 (2), RETARGETED (was: a differing confirmation -> empty): the confirmation reads the owner's facts and, when it
                # differs, each answer gets a meaning call (U8b): a CONSISTENT pair writes that value (assumed, `assumption`, 3 picks)
                ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(_opp(m), m), place="NONE")
                res = attempt(_radio(label), ask)
                if (is_stop(res) or shown(res) != m or not res.assumed or _src(res) != "assumption" or len(ask.picks) != 3
                        or _cites_nationality(res)):
                    bad.append((label[:50], klass, m, "differing check, meaning pair sides with the model", what(res), len(ask.picks)))
                ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(_opp(m), _opp(m)), place="NONE")
                res = attempt(_radio(label), ask)
                if (is_stop(res) or shown(res) != _opp(m) or not res.assumed or _src(res) != "assumption" or len(ask.picks) != 3
                        or _cites_nationality(res)):
                    bad.append((label[:50], klass, m, "differing check, meaning pair sides with the confirmation", what(res), len(ask.picks)))
                # an inconsistent pair (both calls "yes", or both "no") or an unusable one ends EMPTY
                for mean in ("yes", "no", ""):
                    ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_by(_opp(m), mean), place="NONE")
                    res = attempt(_radio(label), ask)
                    if is_stop(res) or shown(res) != "" or _cites_nationality(res):
                        bad.append((label[:50], klass, m, f"differing check, every meaning call {mean!r}: want empty", what(res)))
    assert not bad, report(bad, 12)


# ================================================================== G1: a protected key behaves the same with or without a status phrase

G1_PAIRS = (    # (label with a country + status phrase, the same label with it removed, field type, the model's class, the model's value)
    ("I consent to the collection and use of my personal data as a Singapore citizen or PR under the PDPA",
     "I consent to the collection and use of my personal data under the PDPA", "CHECKBOX", "consent_privacy", "true"),
    ("Keep my application on file; I am a Singapore citizen", "Keep my application on file;", "CHECKBOX", "consent_retention", "true"),
    ("I am a Singapore citizen and agree to receive job alerts", "I agree to receive job alerts", "CHECKBOX", "marketing", "true"),
    ("I certify that I am a Singapore citizen and that the information provided is true and complete",
     "I certify that the information provided is true and complete", "CHECKBOX", "certification", "true"),
    ("I acknowledge that I have read the notice for Singapore citizen applicants",
     "I acknowledge that I have read the notice for applicants", "CHECKBOX", "acknowledgement", "true"),
    ("Is your spouse a Singapore citizen?", "Is your spouse a nurse?", "RADIO", "other_person", "Yes"),
    ("Is your referee a Singapore citizen?", "Is your referee a manager?", "RADIO", "other_person", "Yes"),
    ("Have you ever been convicted of a criminal offence? (Singapore citizens only)",
     "Have you ever been convicted of a criminal offence?", "RADIO", "declaration:criminal", "Yes"),
    ("Have you completed Singapore National Service as a Singapore citizen?", "Have you completed Singapore National Service?",
     "RADIO", "declaration", "No"),
    ("Singapore passport number", "Passport number", "TEXT", "owner_fact", "S1234567A"),
    ("NRIC / FIN (Singapore citizen or PR)", "NRIC / FIN", "TEXT", "owner_fact", "S1234567A"),
)


def test_g1_each_protected_key_behaves_the_same_with_and_without_a_status_phrase_in_the_label():
    """D-223 G1: the status rule never overrides another protected code key or class (the four consents, marketing, certification /
    acknowledgement, other person, a declaration key, National Service, the ID-number labels): for each, ONE label that also holds a
    country + status word ends exactly as the same label with the status words removed (same stop / value, same source, same
    assumed flag), under the class the model names and under ordinary / work_right / none, on three profiles (consents false, true,
    the sample)."""
    bad = []
    for with_status, plain, ftype, own, value in G1_PAIRS:
        for kind in ("false", "true", "sample"):
            if kind == "sample" and "on file" in with_status:      # the retention box's residue needs BOTH consents: a different, older rule
                continue
            prof = consent_profile(kind)
            for klass in (own, "ordinary", "work_right", NO_CLASS):
                outs = []
                for label in (with_status, plain):
                    opts = YN if ftype == "RADIO" else ()
                    f = _pf("u", label, ftype, required=True, options=opts)
                    ask = FakeAsk(lambda v, k=klass: lie(value, k), pick=pick_by("yes", "no"), place="NONE")
                    outs.append(_beh(attempt(f, ask, prof)))
                if outs[0] != outs[1]:
                    bad.append((with_status[:44], kind, klass, "with status", outs[0], "without", outs[1]))
    assert not bad, report(bad, 12)


# ================================================================== G2 / D-224 (1): a PLAIN status sentence is decided by code

S3_FRAMES = (
    "Are you a Singapore citizen?", "Are you a Singapore national?", "Are you a citizen of Singapore?",
    "Are you a Singapore Citizen or Permanent Resident?", "Are you a Singaporean or Singapore PR?", "Are you a Singaporean?",
    "Do you hold Singapore citizenship?", "Do you hold a Singapore passport?")
MODEL_CLASSES = ("owner_fact", "ordinary", "work_right", "consent_privacy", "marketing", NO_CLASS)


def test_g2_a_plain_status_sentence_is_decided_by_code_whatever_class_the_model_names():
    """G2 / D-224 (1): the 8 canonical frames x 6 model classes x model {right, wrong}: a right model is written "Yes" from a
    `profile:singapore_status.*` fact with NO further call (no confirmation, no place call), not assumed; a wrong model's "No" is never
    written ("Yes" or empty); and NEVER a stop `owner_fact_missing` (the model's class `owner_fact` does not turn a plain status question
    into a request for an ID number)."""
    bad = []
    for label in S3_FRAMES:
        for klass in MODEL_CLASSES:
            ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=pick_faithful("Yes", "Yes"), place="NONE")
            res = attempt(_radio(label), ask)
            if (is_stop(res) or shown(res) != "Yes" or ask.picks or ask.place_calls or res.assumed
                    or not _src(res).startswith("profile:singapore_status.")):
                bad.append((label[:44], klass, "right model", what(res), f"{len(ask.picks)} picks {len(ask.place_calls)} place"))
            for pick in (pick_faithful("No", "Yes"), pick_faithful("Yes", "Yes")):
                ask = FakeAsk(lambda v, k=klass: lie("No", k), pick=pick, place="NONE")
                res = attempt(_radio(label), ask)
                if (is_stop(res) and res.reason.value == "owner_fact_missing") or (not is_stop(res) and shown(res) not in ("Yes", "")):
                    bad.append((label[:44], klass, "wrong model", what(res)))
    assert not bad, report(bad, 12)


def test_g2_a_tick_box_whose_whole_label_is_a_plain_status_statement_follows_the_fact():
    """G2 / G1: "I am a Singapore citizen" as a TICK BOX is a status statement: ticked for the citizen, unticked for a profile whose
    nationality is Malaysian and whose residency status is PR (built in memory); under every model class; the model says tick."""
    bad = []
    citizen = profile_with()
    non_citizen = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pr")
    for label in ("I am a Singapore citizen", "I am a Singapore citizen."):
        for klass in MODEL_CLASSES:
            for prof, want in ((citizen, True), (non_citizen, False)):
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=_box_faithful(want), place="NONE")
                res = attempt(_box(label), ask, prof)
                if (not is_stop(res) and is_ticked(res) is not want) or (is_stop(res) and want):
                    bad.append((label, klass, "citizen" if want else "non-citizen", "want ticked" if want else "want unticked", what(res)))
    assert not bad, report(bad, 12)


FURNITURE = (   # D-224 (3): form furniture and now-adverbs keep the profile's truth
    "Are you a Singapore citizen? (Y/N)", "Please confirm: are you a Singapore citizen?", "Are you currently a Singapore citizen?",
    "Are you still a Singapore citizen?", "Please indicate whether you are a Singapore citizen",
    "Do you currently hold a Singapore passport?")


def test_d224_3_form_furniture_keeps_the_profiles_truth():
    """D-224 (3): "(Y/N)", "Please confirm:", "currently", "still", "Please indicate whether ..." keep the status sentence plain: the
    model's right "Yes" ends "Yes" with a `profile:singapore_status.*` source (the vote path: assumed, as for any non-canonical
    wording); a wrong model "No" is never written; under work_right / owner_fact / ordinary."""
    bad = []
    for label in FURNITURE:
        for klass in ("work_right", "owner_fact", "ordinary"):
            ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=pick_faithful("Yes", "Yes"), place="NONE")
            res = attempt(_radio(label), ask)
            if is_stop(res) or shown(res) != "Yes" or not _src(res).startswith("profile:singapore_status."):
                bad.append((label[:48], klass, "right model", what(res)))
            for confirm in ("No", "Yes"):
                ask = FakeAsk(lambda v, k=klass: lie("No", k), pick=pick_faithful(confirm, "Yes"), place="NONE")
                res = attempt(_radio(label), ask)
                if (not is_stop(res)) and shown(res) not in ("Yes", ""):
                    bad.append((label[:48], klass, f"wrong model, confirm {confirm}", what(res)))
    assert not bad, report(bad, 12)


def test_d224_3_not_furniture_by_descent_previously_dual_another_country_never_cite_a_profile_fact():
    """D-224 (3), the other side: "by descent", "previously", "dual" go to G3 (no fact cited: the model plus one confirmation, source
    `assumption`); "... a citizen of another country" and "... or another country's citizen" are place questions: never a profile fact,
    never "No" written for the citizen as a fact, under work_right and none."""
    bad = []
    for label in ("Are you a Singapore citizen by descent?", "Were you previously a Singapore citizen?", "Are you a dual Singapore citizen?",
                  "Are you a citizen of another country?", "Are you a Singapore citizen or another country's citizen?"):
        for klass in ("work_right", NO_CLASS):
            for m in ("Yes", "No"):
                ask = FakeAsk(lambda v, m=m, k=klass: lie(m, k), pick=pick_faithful(m, m), place="NONE")
                res = attempt(_radio(label), ask)
                if _src(res).startswith("profile:") or _cites_nationality(res):
                    bad.append((label[:48], klass, m, what(res)))
    assert not bad, report(bad, 12)


def test_d224_3_also_is_not_form_furniture():
    """Was `..._DEFECT_LOW` (red until D-225 (1)): "Are you also a Singapore citizen?" is G3 (no fact cited: model + a confirmation,
    source `assumption`), not a plain status sentence; the next group pins the whole word list."""
    ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"), place="NONE")
    res = attempt(_radio("Are you also a Singapore citizen?"), ask)
    assert not is_stop(res) and _src(res) == "assumption", what(res)


# ================================================================== 5a: third-party sharing is its own consent

SHARING_BOXES = (
    "Keep my CV on file and let recruiters from partner firms see it",
    "Keep my application on file for roles at our partner companies",
    "I agree to share my details with partner firms. I am a Singapore PR",
    "Consider me for future roles and share my details with hiring managers across the group",
    "I agree that my details may be shared with our trusted partners",
    "Keep my CV on file and share my details with affiliates",
    "Keep my application on file and pass it to hiring managers in other group companies",
    "Keep my application on file for positions with our clients",
)
CONSENT_COMBOS = (   # (name, edits to the sample's consents)
    ("all false", dict(consents__privacy_consent=False, consents__data_retention_consent=False, consents__talent_pool_opt_in=False,
                       consents__certify_true=False)),
    ("privacy+certify only", dict(consents__privacy_consent=True, consents__certify_true=True, consents__data_retention_consent=False,
                                  consents__talent_pool_opt_in=False)),
    ("retention", dict(consents__privacy_consent=True, consents__certify_true=True, consents__data_retention_consent=True,
                       consents__talent_pool_opt_in=False)),
    ("pool", dict(consents__privacy_consent=True, consents__certify_true=True, consents__data_retention_consent=False,
                  consents__talent_pool_opt_in=True)),
    ("retention+pool", dict(consents__privacy_consent=True, consents__certify_true=True, consents__data_retention_consent=True,
                            consents__talent_pool_opt_in=True)),
    ("all true", dict(consents__privacy_consent=True, consents__certify_true=True, consents__data_retention_consent=True,
                      consents__talent_pool_opt_in=True)),
)
SHARE_CLASSES = ("consent_privacy", "consent_retention", "marketing", "ordinary", "declaration:other", NO_CLASS)


def test_5a_third_party_sharing_is_never_ticked_in_any_consent_combination():
    """D-224 5a: 8 sharing wordings (partner firms, partner companies, partner firms + "I am a Singapore PR", hiring managers across the
    group, trusted partners, affiliates, other group companies, our clients) x 6 consent combinations x 6 model classes: an OPTIONAL
    box is unticked, source `default:no_third_party_sharing`, assumed; a REQUIRED box STOPS `consent_refused`."""
    bad = []
    for label in SHARING_BOXES:
        for name, edits in CONSENT_COMBOS:
            prof = profile_with(**edits)
            for klass in SHARE_CLASSES:
                for required in (False, True):
                    ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("yes", "no"), place="NONE")
                    res = attempt(_box(label, required=required), ask, prof)
                    if required:
                        if not stop_is(res, "consent_refused"):
                            bad.append((label[:48], name, klass, "required: want STOP consent_refused", what(res)))
                    elif is_stop(res) or is_ticked(res) or "no_third_party_sharing" not in _src(res) or not res.assumed:
                        bad.append((label[:48], name, klass, "optional: want unticked, default source", what(res)))
    assert not bad, report(bad, 12)


def test_5a_a_yes_no_question_on_sharing_with_a_third_party_is_no_and_never_a_stop():
    """D-224 5a: "May we share your CV with our clients?" and "Do you agree to us passing your application to our affiliates?" are
    answered "No" (source `default:no_third_party_sharing`, assumed) whether required or optional, under every model class and
    whatever the model said; never a stop."""
    bad = []
    for label in ("May we share your CV with our clients?", "Do you agree to us passing your application to our affiliates?"):
        for klass in SHARE_CLASSES:
            for required in (True, False):
                for m in ("Yes", "No"):
                    ask = FakeAsk(lambda v, k=klass, m=m: lie(m, k), pick=pick_by("Yes", "no"), place="NONE")
                    res = attempt(_radio(label, required=required), ask, consent_profile("true"))
                    if is_stop(res) or shown(res) != "No" or "no_third_party_sharing" not in _src(res):
                        bad.append((label[:48], klass, required, m, what(res)))
    assert not bad, report(bad, 12)


def test_5a_the_excluded_wordings_are_not_read_as_sharing_with_a_third_party():
    """D-224 5a, the EXCLUDED wordings are unchanged: sharing within the employer ("with the hiring team", "processed by Example Co and
    its recruitment team"), a processor ("service providers who process it on our behalf") and a negation ("we never share ...")
    never take the `default:no_third_party_sharing` source or its stop detail; "your spouse or partner" / "your domestic partner" stay
    with the relatives / other-person rules (their code key is the other-person family, not a consent)."""
    bad = []
    for label in ("I agree that my details may be shared with the hiring team",
                  "I agree that my details will be processed by Example Co and its recruitment team",
                  "I agree that my details may be shared with service providers who process it on our behalf",
                  "We never share your details with third parties. I agree to the privacy policy"):
        for name, edits in CONSENT_COMBOS:
            for required in (True, False):
                ask = FakeAsk(lambda v: lie("true", "consent_privacy"), pick=pick_by("yes", "no"), place="NONE")
                res = attempt(_box(label, required=required), ask, profile_with(**edits))
                if "no_third_party_sharing" in _src(res) or (is_stop(res) and "other companies" in str(res.detail)):
                    bad.append((label[:50], name, required, what(res)))
    for label in ("Does your spouse or partner work for us?", "Is your domestic partner employed by one of our partner companies?"):
        got = code_key_of(_radio(label))
        if got[0] in ("consent_privacy", "consent_retention", "marketing"):
            bad.append((label, "must stay with the relatives / other-person rules", got))
        ask = FakeAsk(lambda v: lie("Yes", "consent_privacy"), pick=pick_by("Yes", "no"), place="NONE")
        res = attempt(_radio(label), ask)
        if "no_third_party_sharing" in _src(res):
            bad.append((label, what(res)))
    assert not bad, report(bad, 12)


def test_5a_a_required_privacy_box_whose_own_label_says_the_data_may_be_shared_with_affiliates_stops_today_OWNER_QUESTION():
    """Pinned AS IT IS (an open OWNER QUESTION, not judged here; engineer's known limit 2): a REQUIRED privacy box whose own wording
    says the personal data may be disclosed to affiliates ends STOP `consent_refused` today, whatever the owner's privacy consent
    says (privacy true included), because the sharing key comes first in `_key_on`. Real privacy boxes say this often: expect such
    stops in real use until the owner rules."""
    label = "I agree to the privacy policy and consent to my personal data being disclosed to its affiliates"
    bad = []
    for kind in ("sample", "true"):
        ask = FakeAsk(lambda v: lie("true", "consent_privacy"), pick=pick_by("yes", "no"), place="NONE")
        res = attempt(_box(label, required=True), ask, consent_profile(kind))
        if not stop_is(res, "consent_refused"):
            bad.append((kind, what(res)))
    assert not bad, report(bad)


# ================================================================== M2: tails after a plain Singapore wording

M2_ANSWERED = (    # (label, the right model answer): the model quotes "Singapore"
    ("Are you authorised to work in Singapore? Please answer honestly.", "Yes"),
    ("Are you authorised to work in Singapore. Please answer honestly", "Yes"),
    ("Are you authorised to work in Singapore once you graduate?", "Yes"),
    ("Are you authorised to work in Singapore upon graduation?", "Yes"),
    ("Are you authorised to work in Singapore whilst studying?", "Yes"),
    ("Are you authorised to work in Singapore effective immediately?", "Yes"),
    ("Are you authorised to work in Singapore starting January?", "Yes"),
    ("Do you require sponsorship to work in Singapore once your studies end?", "No"),
)


def test_m2_sentence_punctuation_and_time_subordinators_do_not_empty_a_plain_singapore_wording():
    """D-223 M2 (review p20): sentence punctuation ends the follower run ("... in Singapore? Please answer honestly." answered), and
    once / upon / whilst / effective / starting / immediately tails are function words: the model quotes "Singapore", answers right,
    and the field is written with Singapore's truth (never a wrong value: with a model that answers the opposite, the field is not
    written with it)."""
    bad = []
    for label, right in M2_ANSWERED:
        ask = FakeAsk(lambda v: lie(right, "work_right"), pick=pick_faithful(right, right), place="Singapore")
        res = attempt(_radio(label), ask)
        if is_stop(res) or shown(res) != right:
            bad.append((label[:56], "right model", what(res)))
        ask = FakeAsk(lambda v: lie(_opp(right), "work_right"), pick=pick_faithful(_opp(right), right), place="Singapore")
        res = attempt(_radio(label), ask)
        if not is_stop(res) and shown(res) == _opp(right):
            bad.append((label[:56], "wrong model written", what(res)))
    assert not bad, report(bad, 12)


def test_m2_throughout_is_left_out_of_the_function_words_on_purpose_so_those_wordings_end_empty():
    """D-223 M2, pinned with the engineer's reason: "throughout" is NOT a function word. Code's own place reading looks only after "in" /
    "within", and "region" is no region word, so "Are you authorised to work in Singapore throughout the region?" with the quote
    "Singapore" would take Singapore's truth for a region the model never named. Ruled: left out; "throughout the contract" and
    "throughout the region" end EMPTY (a right model, an agreeing confirmation, the place quote "Singapore")."""
    bad = []
    for label in ("Are you authorised to work in Singapore throughout the contract?", "Are you authorised to work in Singapore throughout the region?",
                  "Are you authorised to work in Singapore throughout the contract period?"):
        ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"), place="Singapore")
        res = attempt(_radio(label), ask)
        if is_stop(res) or shown(res) != "":
            bad.append((label[:56], what(res)))
    assert not bad, report(bad)


# ================================================================== M1: a second city after a function word (accepted limit)

M1_LABELS = ("Are you authorised to work in Singapore as well as Mumbai?", "Are you authorised to work in Singapore in addition to Mumbai?")


def test_m1_a_second_city_after_a_function_word_is_answered_from_singapore_when_the_model_under_quotes_as_it_is():
    """M1, an ACCEPTED limit pinned as it IS (D-223: the real model quoted whole phrases in every observed case): a model that quotes
    only "Singapore" for "... in Singapore as well as Mumbai" gets Singapore's truth ("Yes") written; a model that quotes the WHOLE
    phrase ("Singapore as well as Mumbai") leaves the field EMPTY (an unknown place)."""
    bad = []
    for label in M1_LABELS:
        ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"), place="Singapore")
        res = attempt(_radio(label), ask)
        if is_stop(res) or shown(res) != "Yes":
            bad.append((label[:56], "under-quote: written (accepted limit)", what(res)))
        whole = label.split("work in ", 1)[1].rstrip("?")
        ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"), place=whole)
        res = attempt(_radio(label), ask)
        if is_stop(res) or shown(res) != "":
            bad.append((label[:56], "whole quote: want empty", what(res)))
    assert not bad, report(bad)


# ================================================================== D-225 (2): a G3 confirmation is GIVEN THE OWNER'S FACTS

G3_FACT_RULES = (   # (regex on the lower-cased question, what the FACTS line gives for the sample citizen with no pass; "" = they do not settle it)
    (r"renounc|former|non-? ?(singapore )?citizen|non-? ?resident|become|intend to apply|apply for singapore citizenship", "No"),
    (r"\bpr\b.*(for|more than)", "No"),
    (r"work pass|visa|employment pass|permit", "No"),
    (r"will you be a singapore citizen", "Yes"),
)
_MEANING_V = None


def facts_truth(question: str) -> str:
    q = str(question).lower()
    for rx, ans in G3_FACT_RULES:
        if re.search(rx, q):
            return ans
    return ""


def facts_reader(fallback=None):
    """A small FACT-READING scripted `pick`: the G3 confirmation ("Facts about the applicant: ...") is answered from the facts as a
    reader of that line would (`facts_truth`; "" when they do not settle the question); a G3 meaning call ("... other than these facts
    say ...") says "yes" exactly when the value asked about differs from what the facts give ("no" when the facts do not settle it);
    every other call goes to `fallback` (default: unusable)."""
    def pick(q, w, o):
        w = str(w)
        if w.startswith("Facts about the applicant"):
            return facts_truth(q)
        if "other than these facts say" in w:
            m = re.search("answers «(.*?)»", w)
            v = m.group(1).strip().lower() if m else ""
            t = facts_truth(q).lower()
            return "no" if not t or v == t else "yes"
        return fallback(q, w, o) if fallback else ""
    return pick


FACTS_LABELS = ("Have you renounced your Singapore citizenship?", "Are you a former Singapore citizen?",
                "Do you intend to apply for Singapore citizenship?")
NONCITIZEN = "Are you a non-citizen?"      # no country named: NOT a status question at all (see the L6 residual test)


def test_d225_2_the_confirmation_of_a_g3_field_holds_the_owners_facts_and_asserts_no_answer():
    """D-225 (2): the confirmation call for a G3 wording carries "Facts about the applicant: nationality ...; residency status: ...; work
    pass: ..." built from the profile (the sample's three facts; an in-memory Malaysian PR changes them), and code asserts NO answer in
    it: no Yes / No word, no "the answer is" / "correct answer"."""
    bad = []
    variants = ((profile_with(), ("nationality Singapore", "residency status: citizen", "work pass: none")),
                (profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pr"),
                 ("nationality Malaysia", "residency status: permanent resident")))
    for label in FACTS_LABELS + G3_LABELS[:3]:
        for prof, facts in variants:
            ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"), place="NONE")
            attempt(_radio(label), ask, prof)
            conf = [str(w) for _q, w, _o in ask.picks if str(w).startswith("Facts about the applicant")]
            if not conf:
                bad.append((label[:44], "no confirmation call carries a facts line", [str(w)[:60] for _q, w, _o in ask.picks]))
                continue
            w = conf[0]
            missing = [f for f in facts if f not in w]
            if missing:
                bad.append((label[:44], "facts missing", missing, w[:140]))
            if re.search(r"\b(yes|no)\b|the answer is|correct answer|should answer", w, re.I):
                bad.append((label[:44], "the confirmation asserts an answer", w[:200]))
    assert not bad, report(bad, 8)


def test_d225_2_a_wrong_first_answer_on_the_renounce_former_noncitizen_intend_wordings_is_never_written_by_a_fact_reading_pair():
    """D-225 (2): "Have you renounced ...", "Are you a former ...", "Do you intend to apply for Singapore
    citizenship?" for the sample citizen (the facts give "No"): a WRONG model "Yes" with the fact-reading confirmer (it answers "No",
    which differs) and fact-reading meaning calls is NEVER written; the facts-consistent "No" is (assumed, source `assumption`, 3 picks);
    a right model "No" is written on the agreeing confirmation (1 pick); under the model classes work_right / ordinary / none."""
    bad = []
    for label in FACTS_LABELS:
        for klass in ("work_right", "ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=facts_reader(), place="NONE")
            res = attempt(_radio(label), ask)
            if (is_stop(res) and False) or (not is_stop(res) and shown(res) not in ("No", "")):
                bad.append((label[:44], klass, "wrong model: the wrong value was written", what(res)))
            if is_stop(res) or shown(res) != "No" or not res.assumed or _src(res) != "assumption" or len(ask.picks) != 3:
                bad.append((label[:44], klass, "wrong model: want the facts-consistent No, 3 picks", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, k=klass: lie("No", k), pick=facts_reader(), place="NONE")
            res = attempt(_radio(label), ask)
            if is_stop(res) or shown(res) != "No" or _src(res) != "assumption" or len(ask.picks) != 1:
                bad.append((label[:44], klass, "right model: want No on the agreeing confirmation, 1 pick", what(res), len(ask.picks)))
    assert not bad, report(bad, 8)


def test_d225_2_residual_l6_a_citizenship_question_that_names_no_country_has_no_status_reading_DEFECT_LOW():
    """DEFECT (LOW) / the review's accepted residual L6, pinned as it is: "Are you a non-citizen?" names no country, so it has no status
    reading and no facts line. Under the model class `work_right` a wrong model "Yes" ends EMPTY (safe); under `ordinary` or no class the
    model's wrong "Yes" is WRITTEN with 0 picks (assumed, source `assumption`: the model alone). Expected for READY: never written."""
    bad = []
    for klass in ("work_right", "ordinary", NO_CLASS):
        ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=facts_reader(), place="NONE")
        res = attempt(_radio(NONCITIZEN), ask)
        if not is_stop(res) and shown(res) == "Yes":
            bad.append((klass, "wrong Yes written", what(res), f"{len(ask.picks)} picks"))
    assert not bad, report(bad)


def test_d225_2_residual_two_wrong_model_calls_the_wrong_value_is_written_when_the_confirmation_agrees_with_it():
    """Pinned HONESTLY as the residual (two wrong model calls): the same wordings, a wrong first answer "Yes" and an old KNOW-NOTHING
    confirmer that simply agrees with it ("Yes"): written "Yes", assumed, source `assumption`, ONE confirmation (agreement ends the vote),
    no fact cited. Only a confirmer that reads the facts line (the test above) prevents it."""
    bad = []
    for label in FACTS_LABELS:
        for klass in ("work_right", NO_CLASS):
            ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=pick_faithful("Yes", "No"), place="NONE")
            res = attempt(_radio(label), ask)
            if is_stop(res) or shown(res) != "Yes" or not res.assumed or _src(res) != "assumption" or len(ask.picks) != 1:
                bad.append((label[:44], klass, what(res), len(ask.picks)))
    assert not bad, report(bad)


# ================================================================== D-225 (1): the status sentence has its own small allow-list

PLAIN_BREAKERS = ("also", "too", "then", "since", "before", "after", "during", "until", "while", "when", "if", "unless", "either",
                  "both", "any", "some")


def test_d225_1_each_extra_word_in_a_status_label_makes_it_g3_with_no_fact_cited():
    """D-225 (1): "Are you a Singapore citizen <word>?" for also / too / then / since / before / after / during / until / while / when / if
    / unless / either / both / any / some (and "Are you also a Singapore citizen?"): not a plain status sentence, so NOT a canonical frame:
    a right model + an agreeing confirmation is written ("Yes", assumed, source `assumption`, at least one pick), and no answer ever
    cites the nationality / residency fact."""
    bad = []
    labels = [f"Are you a Singapore citizen {w}?" for w in PLAIN_BREAKERS] + ["Are you also a Singapore citizen?"]
    for label in labels:
        for klass in ("work_right", NO_CLASS):
            ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=pick_faithful("Yes", "Yes"), place="NONE")
            res = attempt(_radio(label), ask)
            if is_stop(res) or shown(res) not in ("Yes", "") or _src(res).startswith("profile:") or _cites_nationality(res):
                bad.append((label, klass, what(res)))
            elif shown(res) == "Yes" and (_src(res) != "assumption" or not res.assumed or not ask.picks):
                bad.append((label, klass, "want assumption, assumed, a pick", what(res)))
    assert not bad, report(bad, 10)


def test_d225_1_not_stays_plain_and_a_wrong_yes_for_the_citizen_is_never_written():
    """D-225 (1), the engineer's one departure: "not" stays plain-with-negation. "Are you not a Singapore citizen?" for the sample
    citizen (right answer "No"): a wrong model "Yes" is never written, whatever the confirmation says (siding with it or stating the
    truth), under work_right / none; a right model "No" is not turned into "Yes"."""
    bad = []
    label = "Are you not a Singapore citizen?"
    for klass in ("work_right", NO_CLASS):
        for confirm in ("Yes", "No"):
            ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=pick_faithful(confirm, "No"), place="NONE")
            res = attempt(_radio(label), ask)
            if not is_stop(res) and shown(res) == "Yes":
                bad.append((klass, f"confirm {confirm}", "wrong model: Yes written", what(res)))
            ask = FakeAsk(lambda v, k=klass: lie("No", k), pick=pick_faithful(confirm, "No"), place="NONE")
            res = attempt(_radio(label), ask)
            if not is_stop(res) and shown(res) == "Yes":
                bad.append((klass, f"confirm {confirm}", "right model: turned into Yes", what(res)))
    assert not bad, report(bad)


# ================================================================== D-225 (3): sharing INSIDE the employer follows the privacy consent

INTERNAL_SHARING = (
    "I agree that my details may be shared with the hiring team",
    "I agree that my details may be shared with the hiring manager and interviewers",
    "I agree that my details will be processed by Example Co and its recruitment team",
    "I agree that my details will be reviewed by our HR team",
)
PROCESSORS = (
    "I agree that my details may be shared with service providers who process it on our behalf",
    "I agree that my details may be processed by our applicant-tracking provider acting for Example Co",
)
PRIVACY_CLASSES = ("consent_privacy", "consent_retention", "marketing", "ordinary", "declaration:other", NO_CLASS)


def _privacy_rows(labels):
    """Rows where `labels` do not follow the PRIVACY consent: (label, privacy, class, required, what)."""
    bad = []
    for label in labels:
        for privacy in (False, True):
            prof = profile_with(consents__privacy_consent=privacy)
            for klass in PRIVACY_CLASSES:
                for required in (False, True):
                    ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("yes", "no"), place="NONE")
                    res = attempt(_box(label, required=required), ask, prof)
                    if privacy:
                        ok = (not is_stop(res)) and is_ticked(res)
                    elif required:
                        ok = stop_is(res, "consent_refused")
                    else:
                        ok = (not is_stop(res)) and not is_ticked(res)
                    if not ok:
                        bad.append((label[:48], f"privacy {privacy}", klass, "required" if required else "optional", what(res)))
    return bad


def test_d225_3_sharing_inside_the_employer_follows_the_privacy_consent_under_every_class():
    """D-225 (3): "... shared with the hiring team", "... the hiring manager and interviewers", "... processed by Example Co and its
    recruitment team", "... reviewed by our HR team": privacy false -> an optional box unticked, a required box STOP `consent_refused`;
    privacy true -> ticked; whatever class the model names (before: ticked on the model's answer alone with every consent false)."""
    bad = _privacy_rows(INTERNAL_SHARING)
    assert not bad, report(bad, 10)


def test_d225_3_a_label_with_an_internal_and_a_third_party_recipient_is_third_party():
    """D-225 (3): "... shared with the hiring team and with our partner firms" holds both: third party wins: unticked in every consent
    combination (optional), STOP `consent_refused` when required, under every class."""
    label = "I agree that my details may be shared with the hiring team and with our partner firms"
    bad = []
    for name, edits in CONSENT_COMBOS:
        for klass in PRIVACY_CLASSES:
            for required in (False, True):
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("yes", "no"), place="NONE")
                res = attempt(_box(label, required=required), ask, profile_with(**edits))
                if (required and not stop_is(res, "consent_refused")) or (not required and (is_stop(res) or is_ticked(res))):
                    bad.append((name, klass, required, what(res)))
    assert not bad, report(bad, 10)


def test_d225_3_RED_UNTIL_the_engineers_next_commit_a_processor_acting_for_the_employer_follows_the_privacy_consent():
    """RED UNTIL the engineer's next small commit (measured at 3882537; ruling asked in the engineer's outbox, known limit 1): "... shared
    with service providers who process it on our behalf" and "... processed by our applicant-tracking provider acting for Example Co" are
    the employer's own processors: they follow the PRIVACY consent like the internal recipients (privacy false: unticked / STOP; true:
    ticked), whatever class the model names. Today they have no code key: ticked on the model's answer alone."""
    bad = _privacy_rows(PROCESSORS)
    assert not bad, report(bad, 10)


def test_d225_3_providers_and_partners_for_their_own_marketing_are_third_party():
    """(Green at 3882537; the Coordinator listed it with the red-until rows.) "... shared with service providers and partners for their own marketing" is third-party
    sharing (the recipients use it for themselves): never ticked in any consent combination (optional unticked, required STOP
    `consent_refused`), under every class."""
    label = "I agree that my details may be shared with service providers and partners for their own marketing"
    bad = []
    for name, edits in CONSENT_COMBOS:
        for klass in PRIVACY_CLASSES:
            for required in (False, True):
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("yes", "no"), place="NONE")
                res = attempt(_box(label, required=required), ask, profile_with(**edits))
                if (required and not stop_is(res, "consent_refused")) or (not required and (is_stop(res) or is_ticked(res))):
                    bad.append((name, klass, required, what(res)))
    assert not bad, report(bad, 10)
