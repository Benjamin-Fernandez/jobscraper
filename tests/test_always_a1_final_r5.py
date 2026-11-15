"""Q-121 Amendment A1, the pin round for the FIFTH review (docs/reviews/Q-121-final.md) and the Coordinator's rulings D-219.

RED = DEFECT until eng fix (review Q-121-final, D-219).

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step, so every pin keeps its assertion on
the HARMFUL outcome (a Singapore-based work-rights value written for another country, an experience "Yes" over a right
"No", a marketing opt-in granted by a retention consent, an exception option written as "none applies") and on the NUMBER
and KIND of model calls the ruling allows. Expected values come from the rulings, never from what the code does. One test
function per finding so the red / green picture reads by finding:

  H1   the country of a work-rights / sponsorship / restriction label comes only from the resolver's reading
       (a) a named OTHER country, abbreviations included (US, USA, U.S., UK): never the Singapore-based value;
       (b) an unrecognised place or a region (Atlantis, Narnia, New York, EU, Europe): NO truth, NO reading, NO model answer
           written: the field ends EMPTY with a note "place not recognised", whatever the model / confirmation / meaning say;
       (c) regression: "Singapore" spelled out and no place at all on a Singapore job are answered as before.
  H2   E1 (the focused experience call) fires only when, after the similarity / role / experience / time words are removed,
       the label holds no content word: ten mixed labels keep the model's right "No" and make NO experience call.
  H3   a keep-on-file frame WITH a marketing / contact object is answered by `retention AND talent_pool_opt_in`.
  H4   only a bare none-applies option skips the meaning call: "No ... apart from ...", "No ... in the last 10 years",
       "..., pending review", "No known ..." go to the meaning call.
  M1   a model class `ordinary` with an empty / off-list value on a required Yes/No or choice list: ONE single-field ask.
  M2   a place or time clause on a TRUE truth (`previously_applied`) goes to the vote, never written by code alone.
  L1   a transport failure (BackendError / TimeoutError) inside the single-field ask ends the page as `model_unavailable`.

Fakes only: no model, no network, no browser; sample profile (a Singapore citizen: authorised in SG, NOT in the US / UK,
National Service completed, two internships, all declarations false, retention consent true, talent pool opt-in false);
made-up names ("Example Employer", "Atlantis", "Narnia").
Verify: python tests/run_tests.py -k always_a1_final_r5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, outcome, page, pick_by, pick_faithful, profile_with, report,
    shown, what, _pf)
from test_always_a1_fix8 import CONFLICT_LIST, E1_LABELS, _exp, _kinds  # noqa: E402

CLASSES = ("right", "ordinary", NO_CLASS)


def _k(kind, right):
    return right if kind == "right" else kind


def _f(label, *, tn="RADIO", required=True, options=YN, key="u"):
    return _pf(key, label, tn, required=required, options=options if tn in ("RADIO", "DROPDOWN") else ())


def _note(res) -> str:
    return "" if is_stop(res) else f"{res.note} {res.evidence}"


# ================================================================== H1: the country of a work-rights label

# (frame, the class a model names, the RIGHT answer for a not-authorised country: US / UK; a Singapore citizen
# is authorised in Singapore, needs no sponsorship there and has no restriction there)
H1_FRAMES = (
    ("Are you legally authorised to work in {c}?", "work_right", "No", "Yes"),
    ("Will you require sponsorship to work in {c}?", "sponsorship", "Yes", "No"),
    ("Do you require visa sponsorship for {c}?", "sponsorship", "Yes", "No"),
    ("Do you have any restrictions on your right to work in {c}?", "work_right", "Yes", "No"),
    ("Is your right to work in {c} restricted?", "work_right", "Yes", "No"),
)                      # (label, class, right answer OTHER country, right answer SINGAPORE)
H1_OTHER = ("the US", "the USA", "the U.S.", "the UK")


def _opp(v):
    return "No" if v == "Yes" else "Yes"


def test_h1a_a_named_other_country_never_gets_the_singapore_based_value():
    """H1 (a): US / USA / U.S. / UK, five frames, class right / ordinary / missing. (1) a RIGHT model answer is not turned
    into the Singapore-based one by the vote (review: sponsorship in the US, model Yes, confirmation No -> No written, 3
    calls); (2) a WRONG model answer with an agreeing confirmation and faithful meaning calls is never written; (3) with
    model, confirmation and meaning all right, the right value is written (nothing to protect against: no over-protection).
    The Singapore-based value (the opposite of the right one) is NEVER written, "No restrictions" for a restriction
    question included. DEFECT while red."""
    bad = []
    for tmpl, klass, right, _sg in H1_FRAMES:
        wrong = _opp(right)
        for c in H1_OTHER:
            label = tmpl.format(c=c)
            for kind in CLASSES:
                # the confirmer reads the text code gives it (the SINGAPORE truth: `wrong` here); its meaning calls are
                # faithful to that text: V = the Singapore value does not state the contradiction
                ask = FakeAsk(lambda v, k=_k(kind, klass), r=right: lie(r, k), pick=pick_faithful(wrong, wrong))
                res = attempt(_f(label), ask)
                if shown(res) == wrong:
                    bad.append((label[:56], kind, "right model, Singapore-text confirmation", what(res), _kinds(ask)))
                ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_faithful(wrong, wrong))
                res = attempt(_f(label), ask)
                if shown(res) == wrong:
                    bad.append((label[:56], kind, "wrong model x3", what(res), _kinds(ask)))
                ask = FakeAsk(lambda v, k=_k(kind, klass), r=right: lie(r, k), pick=pick_faithful(right, right))
                res = attempt(_f(label), ask)
                if shown(res) != right:
                    bad.append((label[:56], kind, "all right: the right value must stand", what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


def test_h1a_the_restriction_frame_with_a_wrong_no_is_never_written_with_no_call():
    """H1 (a), U10b `restrict` branch: "restrictions on your right to work in the US / USA / U.S. / UK", the model's wrong
    "No", ANY confirmation: never "No" (a Singapore citizen claims no restriction in the US); 0-call writes included."""
    bad = []
    for tmpl in ("Do you have any restrictions on your right to work in {c}?",
                 "Is your right to work in {c} restricted?"):
        for c in H1_OTHER:
            label = tmpl.format(c=c)
            for kind in CLASSES:
                for pick in (pick_by("No", "no"), pick_by("Yes", "yes"), pick_by("", "")):
                    ask = FakeAsk(lambda v, k=_k(kind, "work_right"): lie("No", k), pick=pick)
                    res = attempt(_f(label), ask)
                    if shown(res) == "No":
                        bad.append((label[:56], kind, what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


UNKNOWN_PLACES = ("Atlantis", "Narnia", "New York", "the EU", "Europe")
H1B_FRAMES = (
    ("Are you legally authorised to work in {c}?", "work_right"),
    ("Will you require sponsorship to work in {c}?", "sponsorship"),
    ("Do you have any restrictions on your right to work in {c}?", "work_right"),
)


def test_h1b_an_unrecognised_place_or_a_region_ends_empty_with_the_note_whatever_the_model_says():
    """H1 (b): Atlantis, Narnia, New York, the EU, Europe x authorised / sponsorship / restriction frames. NO truth, NO
    code reading, NO model answer is written: the field ends EMPTY (a required field then fails the page: nothing is
    written, `fills` is False) with a note containing "place not recognised", for the model's Yes and No, class right /
    ordinary / missing, and a confirmation or meaning reply of yes / no / unusable. DEFECT while red (review M3: "Atlantis",
    model Yes -> Yes written with 0 calls from the Singapore row)."""
    bad = []
    for tmpl, klass in H1B_FRAMES:
        for place in UNKNOWN_PLACES:
            label = tmpl.format(c=place)
            for value in ("Yes", "No"):
                for kind in CLASSES:
                    for pick in (pick_by("Yes", "yes"), pick_by("No", "no"), pick_by("", "")):
                        ask = FakeAsk(lambda v, k=_k(kind, klass), x=value: lie(x, k), pick=pick)
                        res = attempt(_f(label), ask)
                        if is_stop(res) or shown(res) != "" or res.fills or "place not recognised" not in _note(res):
                            bad.append((label[:56], value, kind, what(res)))
    assert not bad, report(bad, 10)


def test_h1b_a_silent_model_on_an_unrecognised_place_also_ends_empty_with_the_note():
    """H1 (b), silent model: the single-field ask must not be used to guess a country that is not recognised."""
    bad = []
    for tmpl, _klass in H1B_FRAMES:
        for place in UNKNOWN_PLACES:
            label = tmpl.format(c=place)
            ask = FakeAsk(pick=lambda q, w, o: "Yes")
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or res.fills or "place not recognised" not in _note(res):
                bad.append((label[:56], what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


H1C_CELLS = (   # (label, class, the right answer): a Singapore job, a Singapore citizen
    ("Are you legally authorised to work in Singapore?", "work_right", "Yes"),
    ("Are you legally authorised to work in this country?", "work_right", "Yes"),
    ("Will you require sponsorship to work in Singapore?", "sponsorship", "No"),
    ("Will you now or in the future require visa sponsorship?", "sponsorship", "No"),
    ("Do you have any restrictions on your right to work in Singapore?", "work_right", "No"),
    ("Is your right to work in this country restricted?", "work_right", "No"),
)


def test_h1c_regression_singapore_spelled_out_and_no_place_at_all_are_answered_as_before():
    """H1 (c): the same frames with "Singapore" spelled out, and with no place at all on a Singapore job, keep today's
    answers: a right model answer is written; a wrong one with an agreeing confirmation and faithful meaning calls is
    never written; a right confirmation turns a wrong model answer into the right one. (Expected GREEN today.)"""
    bad = []
    for label, klass, right in H1C_CELLS:
        wrong = _opp(right)
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass), r=right: lie(r, k), pick=pick_faithful(wrong, right))
            res = attempt(_f(label), ask)
            if shown(res) != right:
                bad.append((label[:56], kind, "right model", what(res), _kinds(ask)))
            ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_faithful(wrong, right))
            res = attempt(_f(label), ask)
            if shown(res) == wrong:
                bad.append((label[:56], kind, "wrong model x3", what(res), _kinds(ask)))
            ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_faithful(right, right))
            res = attempt(_f(label), ask)
            if shown(res) != right:
                bad.append((label[:56], kind, "wrong model, right confirmation", what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


# ================================================================== H2: E1 only for a pure similar-experience label

H2_MIXED = (
    "Have you worked in a similar role where you were dismissed?",
    "Have you worked in a similar role as a politically exposed person?",
    "Have you worked in a similar role under a non-compete agreement?",
    "Have you worked in a similar role with a criminal record?",
    "Have you worked in a similar role and been subject to a disciplinary investigation?",
    "Have you worked in a similar role and been made redundant?",
    "Have you worked in a similar role in a government agency?",
    "Have you held a similar role at a competitor of Example Employer?",
    "Have you worked in a similar role in the United States?",
    "Have you worked in a similar role requiring a work visa?",
)


def _experience_pick(q, w, o):
    """A focused experience call (the briefing's similar-roles rule invites) says yes; anything else is unusable."""
    return "yes" if str(w).startswith("Roles the applicant has held") else ""


def test_h2_a_mixed_label_keeps_the_models_right_no_and_makes_no_experience_call():
    """H2: ten labels that add a protected / content word to a similar-role question; model "No" (right), class
    `ordinary` or missing, roles in the profile: the answer STANDS ("No") and NO focused experience call is made. Silent
    model: the last resort does not write "Yes" from an experience call either. DEFECT while red (review: "Yes" written,
    assumed, note "experience check")."""
    bad = []
    for label in H2_MIXED:
        for kind in ("ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, k=kind: lie("No", k), pick=_experience_pick)
            res = attempt(_f(label), ask)
            if shown(res) != "No" or "experience" in _kinds(ask):
                bad.append((label[:60], kind, "model No", what(res), _kinds(ask)))
        ask = FakeAsk(pick=_experience_pick)
        res = attempt(_f(label), ask)
        if shown(res) == "Yes" or "experience" in _kinds(ask):
            bad.append((label[:60], "silent", what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


def test_h2_control_the_two_pure_similar_experience_questions_are_still_checked_by_e1():
    """H2 control: pure similar-experience labels (the ruling examples of test_always_a1_fix8) still get ONE focused call
    whose "yes" is written (assumed, note "experience check")."""
    bad = []
    for label in E1_LABELS[:2]:
        res, ask = _exp("No", "yes", label)
        if shown(res) != "Yes" or not res.assumed or _kinds(ask) != ["experience"]:
            bad.append((label[:50], what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== H3: keep-on-file AND a marketing / contact object

H3_LABELS = (
    "Keep my application on file and email me about similar roles",
    "Keep me posted on events and keep my application on file",
    "Keep my CV on file and contact me about promotions",
)
H3_CLASSES = ("marketing", "consent_retention", "ordinary", NO_CLASS)


def test_h3_a_keep_and_contact_box_follows_retention_and_the_marketing_opt_in_together():
    """H3: retention true / talent_pool_opt_in false -> NOT ticked, under model class marketing, retention, ordinary and
    none alike (the model says tick); both true -> ticked; retention false (opt-in true) -> not ticked. DEFECT while red
    (review: ticked, not assumed, 0 calls: a marketing opt-in granted from the retention consent)."""
    bad = []
    cases = (("retention only", profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False), False),
             ("both", profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=True), True),
             ("opt-in only", profile_with(consents__data_retention_consent=False, consents__talent_pool_opt_in=True), False))
    for label in H3_LABELS:
        for name, prof, want_ticked in cases:
            for klass in H3_CLASSES:
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                res = attempt(_pf("b", label, "CHECKBOX", required=False), ask, prof)
                if is_stop(res) or is_ticked(res) is not want_ticked:
                    bad.append((label[:44], name, klass, "want ticked" if want_ticked else "want NOT ticked", what(res)))
    assert not bad, report(bad, 10)


def test_h3_control_pure_retention_wordings_still_follow_the_retention_consent_alone():
    """H3 control: pure keep-on-file wordings with retention true / opt-in false stay ticked (two rows)."""
    bad = []
    prof = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    for label in ("Please keep my application on file for 12 months", "Keep my application on file for future roles"):
        for klass in H3_CLASSES:
            ask = FakeAsk(lambda v, k=klass: lie("false", k), pick=pick_by("", ""))
            res = attempt(_pf("b", label, "CHECKBOX", required=False), ask, prof)
            if not is_ticked(res):
                bad.append((label[:44], klass, what(res)))
    assert not bad, report(bad)


# ================================================================== H4: only a bare none-applies option skips the meaning call

CRIM_LIST = ("Yes, I have a criminal record", "{none}")
CONV_LIST = ("Yes, I have been convicted", "{none}")
H4_NARROWED = (    # (label, adverse option, the narrowed "none" option, class)
    ("Criminal record", "Yes, I have a criminal record", "No criminal record apart from one traffic offence",
     "declaration:criminal_record"),
    ("Criminal convictions", "Yes, I have been convicted", "No convictions in the last 10 years",
     "declaration:criminal_record"),
    ("Conflict of interest", CONFLICT_LIST[0], "No conflict of interest, pending review",
     "declaration:conflict_audit_independence"),
    ("Conflict of interest", CONFLICT_LIST[0], "No known conflict", "declaration:conflict_audit_independence"),
)
H4_BARE = (
    ("Criminal record", "Yes, I have a criminal record", "None of the above", "declaration:criminal_record"),
    ("Criminal record", "Yes, I have a criminal record", "No criminal record", "declaration:criminal_record"),
)


def test_h4_a_narrowed_none_option_agreed_by_model_and_confirmation_goes_to_the_meaning_call():
    """H4: model and confirmation AGREE on "No criminal record apart from one traffic offence" / "No convictions in the last
    10 years" / "No conflict of interest, pending review" / "No known conflict": the MEANING call is made, and one that
    says it states the contradiction ("yes") leaves the field empty: nothing is written. Class right / ordinary / missing.
    DEFECT while red (review: written, assumed, no meaning call)."""
    bad = []
    for label, adverse, none, klass in H4_NARROWED:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, n=none, k=_k(kind, klass): lie(n, k), pick=pick_by(none, "yes"))
            res = attempt(_f(label, options=(adverse, none)), ask)
            if shown(res) != "" or "meaning" not in _kinds(ask):
                bad.append((none[:48], kind, what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


def test_h4_control_a_bare_none_option_still_skips_the_meaning_call():
    """H4 control: "None of the above" and "No criminal record" agreed by model and confirmation are written with NO
    meaning call (a meaning reply "yes" that would have emptied the field is never asked). (Expected GREEN today.)"""
    bad = []
    for label, adverse, none, klass in H4_BARE:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, n=none, k=_k(kind, klass): lie(n, k), pick=pick_by(none, "yes"))
            res = attempt(_f(label, options=(adverse, none)), ask)
            if shown(res) != none or "meaning" in _kinds(ask):
                bad.append((none, kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_h4_control_a_plain_no_option_in_a_choice_list_still_goes_to_the_meaning_call():
    """H4 control (D-219 H4 as corrected): the ruling only TIGHTENS `pure_none_option`; nothing that goes to the meaning
    call today may skip it. A bare "No" option of a CHOICE LIST is not a statement (`pure_none_option`), so, agreed by
    model and confirmation, it keeps going to the meaning call; a "yes" reply (it states the contradiction) leaves the field
    empty. (A Yes / No FIELD is the U12 frame and is not affected.) Expected GREEN today."""
    adverse, none, klass = "Yes, I have a criminal record", "No", "declaration:criminal_record"
    bad = []
    for kind in CLASSES:
        ask = FakeAsk(lambda v, k=_k(kind, klass): lie(none, k), pick=pick_by(none, "yes"))
        res = attempt(_f("Criminal record", options=(adverse, none)), ask)
        if shown(res) != "" or "meaning" not in _kinds(ask):
            bad.append((none, kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== M1: class ordinary + an unusable value = no class

M1_CELLS = (   # (label, options, a usable answer for the single-field ask)
    ("Are you a member of a trade union?", YN, "Yes"),
    ("Are you on a bond with a previous employer?", YN, "No"),
    ("Which category best describes your status?", ("Student", "Graduate", "Employed", "Other"), "Graduate"),
)
M1_EMPTY = ""                             # an empty value the model may give with class `ordinary`
M1_OFFLIST = ("Maybe", "N/A")             # off-list values: the existing option-pick step is a model call on the field


def test_m1_a_class_ordinary_with_an_empty_value_gets_exactly_one_single_field_ask():
    """M1 / fix7-1: the model names `ordinary` but gives an EMPTY value on a REQUIRED Yes/No or choice list: exactly ONE
    single-field ask, never a 0-call generic "No" / "Other". The ask's usable answer is written; an unusable one leaves the
    required field empty."""
    bad = []
    for label, opts, usable in M1_CELLS:
        ask = FakeAsk(lambda v: lie(M1_EMPTY, "ordinary"), pick=lambda q, w, o: "")
        res = attempt(_f(label, options=opts), ask)
        if _kinds(ask) != ["ask"] or shown(res) != "":
            bad.append((label[:44], "unusable ask", what(res), _kinds(ask)))
        ask = FakeAsk(lambda v: lie(M1_EMPTY, "ordinary"), pick=lambda q, w, o, u=usable: u)
        res = attempt(_f(label, options=opts), ask)
        if _kinds(ask) != ["ask"] or shown(res) != usable:
            bad.append((label[:44], "usable ask", what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


def test_m1_a_class_ordinary_with_an_off_list_value_is_never_a_zero_call_generic_answer():
    """M1 (D-219 addendum 1): an OFF-LIST value ("Maybe", "N/A") under class `ordinary` goes through the existing option-pick
    step, which is a model call ON THAT FIELD and stays: with a usable pick it is exactly ONE call and the pick is written;
    with an unusable pick the required field is left empty (never a generic "No" / "Other"), and at least one call was made.
    (The unusable path makes 3 calls today: two picks and the single-field ask; the ruling's "exactly one" is pinned for the
    usable pick only.)"""
    bad = []
    for label, opts, usable in M1_CELLS:
        for reply in M1_OFFLIST:
            ask = FakeAsk(lambda v, r=reply: lie(r, "ordinary"), pick=lambda q, w, o, u=usable: u)
            res = attempt(_f(label, options=opts), ask)
            if len(ask.picks) != 1 or shown(res) != usable:
                bad.append((label[:44], repr(reply), "usable pick", what(res), _kinds(ask)))
            ask = FakeAsk(lambda v, r=reply: lie(r, "ordinary"), pick=lambda q, w, o: "")
            res = attempt(_f(label, options=opts), ask)
            if not ask.picks or shown(res) != "":
                bad.append((label[:44], repr(reply), "unusable pick", what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


# ================================================================== M2: a place / time clause on a TRUE truth

M2_LABELS = (
    "Have you applied to Example Employer in the last 6 months?",
    "Have you applied to Example Employer in Germany?",
    "Have you applied to Example Employer other than through this website?",
)


def test_m2_a_place_or_time_clause_on_a_true_truth_goes_to_the_vote_not_written_by_code_alone():
    """M2: `previously_applied` true: the frame matches before the clause is read, so code wrote "Yes" alone (0 calls). A
    place or time clause on a TRUE truth goes to the vote: a confirmation call is made, and a confirmation that DISAGREES
    ("No") leaves the answer not written as code's Yes. Model right ("Yes", class ordinary / missing) and silent.
    DEFECT while red."""
    bad = []
    for label in M2_LABELS:
        for name, answer in (("model Yes ordinary", lambda v: lie("Yes", "ordinary")),
                             ("model Yes no class", lambda v: lie("Yes", NO_CLASS)), ("silent", None)):
            ask = FakeAsk(answer, pick=pick_by("No", "no"))
            res = attempt(_f(label), ask, rctx_kw={"previously_applied": True})
            if "confirm" not in _kinds(ask) or shown(res) == "Yes":
                bad.append((label[:56], name, what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


def test_m2_control_the_plain_frame_on_a_true_truth_is_still_written_with_no_call():
    """M2 control: "Have you previously applied to Example Employer?" with `previously_applied` true: Yes, 0 calls."""
    ask = FakeAsk(lambda v: lie("Yes", "ordinary"), pick=pick_by("No", "no"))
    res = attempt(_f("Have you previously applied to Example Employer?"), ask, rctx_kw={"previously_applied": True})
    assert shown(res) == "Yes" and not ask.picks, (what(res), _kinds(ask))


# ================================================================== L1: a transport failure in the single-field ask (F5)

L1_CELLS = (
    ("Do you enjoy working in a team environment?", YN),
    ("Do you have a driving licence?", YN),
    ("How often are you available for meetings?", ("Rarely", "Sometimes", "Often")),
)


def test_l1_a_transport_failure_in_the_single_field_ask_ends_the_page_as_model_unavailable():
    """L1 / F5: the single-field ask (silent model, no key, no class) hits a BackendError or a TimeoutError: the PAGE ends
    as `transport_failed` (the flow ends FAILED / model_unavailable), the field is not quietly left empty. DEFECT while
    red (review: `_f2_ask` swallows the failure, `hit = None`)."""
    from jobscraper.backends import BackendError
    bad = []
    for label, opts in L1_CELLS:
        for exc in (BackendError("the model is unreachable"), TimeoutError("timed out")):
            def pick(q, w, o, e=exc):
                if str(w).startswith("the applicant's true answer"):
                    raise e
                return ""
            ask = FakeAsk(pick=pick)
            out = outcome(_f(label, options=opts), ask)
            if not out.transport_failed:
                bad.append((label[:44], type(exc).__name__, "page not ended", out.answers.get("u") and what(out.answers["u"]),
                            _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== D-219 addendum (round 2)

# ---- ruling 3: words after "in" / "within" that are not places keep the job's country (`always.work_place`, `_NOT_A_PLACE`)

NOT_A_PLACE = ("order", "future", "addition", "respect", "accordance", "relation", "connection", "case", "terms", "line",
               "full", "part", "advance", "person", "writing", "general", "particular", "practice", "principle", "lieu",
               "compliance")           # the engineer's closed list: one row per word
LOOKALIKE_PLACES = ("Orderland", "Fullerton", "Casablanca")    # contain a list word but ARE places (made up / not mapped)


def test_ruling3_a_word_after_in_that_is_not_a_place_keeps_the_jobs_country():
    """D-219 addendum 3: "Will you require sponsorship in <word> to work for us?" for each word of the closed list, "within 6
    months" and "within 30 days" (a digit): no place, so the job's country (Singapore: a citizen needs no sponsorship): a right
    model "No" is written, nothing is left empty with the place note."""
    labels = [f"Will you require sponsorship in {w} to work for us?" for w in NOT_A_PLACE] + [
        "Will you require sponsorship within 6 months to work for us?",
        "Will you require sponsorship within 30 days to work for us?"]
    bad = []
    for label in labels:
        ask = FakeAsk(lambda v: lie("No", "sponsorship"), pick=pick_faithful("No", "No"))
        res = attempt(_f(label), ask)
        if is_stop(res) or shown(res) != "No" or "place not recognised" in _note(res):
            bad.append((label[:60], what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


def test_ruling3_lookalike_words_that_are_places_still_end_empty_with_the_note():
    """D-219 addendum 3: "in Orderland", "in Fullerton", "in Casablanca" are places the program cannot map (the list matches
    whole words only): the field ends EMPTY with "place not recognised", whatever the model says."""
    bad = []
    for place in LOOKALIKE_PLACES:
        label = f"Will you require sponsorship to work in {place}?"
        for value in ("Yes", "No"):
            ask = FakeAsk(lambda v, x=value: lie(x, "sponsorship"), pick=pick_by(value, "no"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or "place not recognised" not in _note(res):
                bad.append((label[:56], value, what(res)))
    assert not bad, report(bad)


# ---- ruling 7: accepted fail-safe, pinned as it IS

def test_ruling7_a_real_place_the_resolver_does_not_map_ends_empty_with_the_note():
    """D-219 addendum 7 (accepted, fail-safe): "Are you authorised to work in Spain?" and "... in London?" end EMPTY with the
    place note (the resolver maps neither): never a Singapore-based Yes, whatever the model says."""
    bad = []
    for place in ("Spain", "London"):
        label = f"Are you authorised to work in {place}?"
        for value in ("Yes", "No"):
            ask = FakeAsk(lambda v, x=value: lie(x, "work_right"), pick=pick_by(value, "no"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or "place not recognised" not in _note(res):
                bad.append((label, value, what(res)))
    assert not bad, report(bad)


# ---- ruling 4: RED UNTIL the follow-up on branch eng/Q-121-A1-fix1 MERGES

def test_ruling4_international_student_keeps_the_jobs_answer():
    """D-219 addendum 4 (RETARGETED in round 4: the "anywhere in Singapore" row moved to the next test, see D-220 P6).
    "Do you require sponsorship as an international student?" keeps the job-country answer ("international" before student /
    applicant / candidate / graduate is not a place): a right "No" is written. Neither ends empty with the place note."""
    bad = []
    for label, klass, right in (("Do you require sponsorship as an international student?", "sponsorship", "No"),
                                ("Do you require sponsorship as an international graduate?", "sponsorship", "No"),
                                ("Do you require sponsorship as an international candidate?", "sponsorship", "No")):
        ask = FakeAsk(lambda v, k=klass, r=right: lie(r, k), pick=pick_faithful(right, right))
        res = attempt(_f(label), ask)
        if is_stop(res) or shown(res) != right or "place not recognised" in _note(res):
            bad.append((label[:60], what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_ruling4_anywhere_in_singapore_now_ends_empty_with_the_note_and_no_place_call():
    """RETARGETED in round 4 (D-220 P6): "Are you authorised to work anywhere in Singapore?" used to keep Singapore's answer
    (D-219 addendum 4, a named real country wins over "anywhere"); code's own reading now vetoes "anywhere" (P4): the field
    ends EMPTY with "work rights: place not recognised" and NO place call is made, whatever the model says."""
    bad = []
    for value in ("Yes", "No"):
        ask = FakeAsk(lambda v, x=value: lie(x, "work_right"), pick=pick_by(value, "no"))
        res = attempt(_f("Are you authorised to work anywhere in Singapore?"), ask)
        if is_stop(res) or shown(res) != "" or "place not recognised" not in _note(res) or ask.place_calls:
            bad.append((value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_ruling4_control_anywhere_in_the_eu_still_ends_empty_with_the_note():
    """D-219 addendum 4 control: "Are you authorised to work anywhere in the EU?" is a region: EMPTY with the place note."""
    bad = []
    for value in ("Yes", "No"):
        ask = FakeAsk(lambda v, x=value: lie(x, "work_right"), pick=pick_by(value, "no"))
        res = attempt(_f("Are you authorised to work anywhere in the EU?"), ask)
        if is_stop(res) or shown(res) != "" or "place not recognised" not in _note(res):
            bad.append((value, what(res)))
    assert not bad, report(bad)


# ---- ruling 5: RED UNTIL the same follow-up MERGES (every stored answer carries the class it was decided under)

def test_ruling5_every_answer_stores_the_class_it_was_decided_under():
    """D-219 addendum 5. RED UNTIL the follow-up on `eng/Q-121-A1-fix1` merges. One page: a declaration, a work-rights
    question, a consent box and an ordinary question, answered by the fake model: `Answer.field_class` is the head of each
    class string (declaration / work_right / consent_privacy / ordinary)."""
    fields = [_f("Have you ever been convicted of a criminal offence?", key="decl"),
              _f("Are you legally authorised to work in Singapore?", key="wr"),
              _pf("box", "I agree to the privacy policy", "CHECKBOX", required=False),
              _f("Do you enjoy working in a team environment?", key="ord")]
    ask = FakeAsk(lambda v: {"decl": lie("No"), "wr": lie("Yes"), "box": lie("true"), "ord": lie("Yes", "ordinary")}.get(v["id"]),
                  pick=pick_by("", ""))
    got = page(fields, ask)
    assert not is_stop(got), got
    want = {"decl": "declaration", "wr": "work_right", "box": "consent_privacy", "ord": "ordinary"}
    bad = [(k, want[k], getattr(got.get(k), "field_class", "<none>")) for k in want
           if str(getattr(got.get(k), "field_class", "")).split(":")[0] != want[k]]
    assert not bad, report(bad)


def test_ruling5_when_code_and_model_disagree_on_a_protected_field_the_protected_class_is_stored():
    """D-219 addendum 5. RED UNTIL the follow-up merges. Code's key says declaration (criminal record) / work right, the
    model names `ordinary`, the field was treated as protected: the stored class is the PROTECTED one, not `ordinary`."""
    bad = []
    for label, klass, right in (("Have you ever been convicted of a criminal offence?", "declaration", "No"),
                                ("Are you legally authorised to work in Singapore?", "work_right", "Yes")):
        ask = FakeAsk(lambda v, r=right: lie(r, "ordinary"), pick=pick_by("", ""))
        res = attempt(_f(label), ask)
        got = "" if is_stop(res) else str(res.field_class)
        if got.split(":")[0] != klass:
            bad.append((label[:50], "stored", got, what(res)))
    assert not bad, report(bad)


# ---- ruling 6: H3 wording: a contact verb triggers the both-consents rule; "future roles / positions" alone do not

def test_ruling6_a_contact_verb_needs_both_consents_but_future_roles_alone_is_retention():
    """D-219 addendum 6. Retention true / talent_pool_opt_in false: "Keep my application on file and contact me about future
    positions" (a contact verb) is NOT ticked; "Keep my application on file for future roles and positions" (no contact verb)
    is ticked. Model class marketing / retention / ordinary / none alike."""
    prof = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    bad = []
    for label, want_ticked in (("Keep my application on file and contact me about future positions", False),
                               ("Keep my application on file for future roles and positions", True)):
        for klass in H3_CLASSES:
            ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
            res = attempt(_pf("b", label, "CHECKBOX", required=False), ask, prof)
            if is_stop(res) or is_ticked(res) is not want_ticked:
                bad.append((label[:50], klass, "want ticked" if want_ticked else "want NOT ticked", what(res)))
    assert not bad, report(bad)
