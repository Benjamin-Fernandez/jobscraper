"""Q-121 Amendment A1, the pin round for the RE-REVIEW after D-219 (docs/reviews/Q-121-final.md, "Re-review after D-219": N1,
N2, M4, M5) and the Coordinator's rulings D-220 (P: places, R: keep on file).

RED = DEFECT until eng fix (re-review, D-220). Rows that must stay as they are today (the 30 Singapore-job wordings, the
pure retention wordings, the controls) are GREEN today and are marked "expected GREEN".

D-220 as pinned:
  P1  the job country's truth is used with NO model call only when, after the frame words and ONE exact name / alias of the
      job country, no content word is left.
  P2  otherwise ONE place call: the model QUOTES the words of the question that say where the work would be, or NONE.
  P3  code accepts the quote only if it is a substring of the label and, with articles stripped, exactly ONE country's name or
      known alias (job country: Singapore, SG, S'pore, Republic of Singapore; others incl. US / USA / U.S. / U.S.A. / the
      States / America, UK / U.K. / Great Britain / Britain / England): that country's facts. NONE counts only when code also
      finds no place word. Any other quote ("outside Singapore", "Singapore and any other country", "the Gulf", "any
      location", "APAC", a city), an unusable or non-substring reply, or a disagreement between model and code: the field ends
      EMPTY with "work rights: place not recognised", whatever the answer / confirmation / meaning calls say. A transport
      failure in the place call ends the page `model_unavailable` (`transport_failed`). P4 code's own reading of another
      country / region / unrecognised place always vetoes. P5 the place call counts in the page cap.
  R   a keep-on-file label is pure retention only when nothing is left after the frame words and a closed list of neutral
      words (future / other / similar roles, positions, vacancies, opportunities; "consider me for"; durations); ANY residue
      makes the truth `retention AND talent_pool_opt_in`.

THE PLACE-CALL FAKE: the shared `FakeAsk` (tests/test_always_fill.py) recognises the place call by its TASK line ("Quote the words of
QUESTION ...") and answers {"quote": <reply>}; `PlaceAsk` here only defaults the reply to "NONE". A row scripts `place=` (a quote,
"NONE", garbage, a quote not in the label, or a callable(label)), `place_down=True` raises BackendError; place calls are recorded in
`place_calls`.

Fakes only: no model, no network, no browser; sample profile (a Singapore citizen: authorised in SG, NOT in the US / UK, all
declarations false, retention consent true, talent pool opt-in false); made-up names ("Example Employer", "Atlantis").
Verify: python tests/run_tests.py -k always_a1_final_r6
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, outcome, page, pick_by, pick_faithful, profile_with, report, shown,
    what, _pf)
from test_always_a1_fix8 import _kinds  # noqa: E402

CLASSES = ("right", "ordinary", NO_CLASS)
NOTE = "place not recognised"
GARBAGE = "§§ ?? §§"
NOT_IN_LABEL = "Zzyzx Province"


def _k(kind, right):
    return right if kind == "right" else kind


def _opp(v):
    return "No" if v == "Yes" else "Yes"


def _f(label, *, required=True, options=YN, key="u"):
    return _pf(key, label, "RADIO", required=required, options=options)


def _note(res) -> str:
    return "" if is_stop(res) else f"{res.note} {res.evidence}"


class PlaceAsk(FakeAsk):
    """`FakeAsk` whose place call (D-220 P2, schema {"quote": str}) answers `place` by default "NONE"; the place call itself is
    recognised and recorded by the shared fake (tests/test_always_fill.py, helper tests/place_quote.py)."""

    def __init__(self, answer=None, *, place="NONE", place_down=False, pick=None, **kw):
        super().__init__(answer, pick=pick, place=place, place_down=place_down, **kw)


# ================================================================== N1: "the States", "outside Singapore", other places

# (frame, class, the Singapore-based value (WRONG for any other country), the right value for the United States)
N1_FRAMES = (
    ("Are you authorised to work {p}?", "work_right", "Yes", "No"),
    ("Do you require sponsorship to work {p}?", "sponsorship", "No", "Yes"),
    ("Do you have any restrictions on your right to work {p}?", "work_right", "No", "Yes"),
)
OUTSIDE_PLACE_REPLIES = ("Singapore", "outside Singapore", "NONE", GARBAGE, NOT_IN_LABEL)


def test_n1a_outside_singapore_ends_empty_with_the_note_whatever_the_model_the_votes_and_the_place_reply_say():
    """N1: "... work outside Singapore" (a named country inside an exclusion): no truth, no reading: the field ends EMPTY with
    "work rights: place not recognised", for a right / wrong model, a confirmation that follows the Singapore text or the
    truth, and every place reply (a lying "Singapore", the phrase itself, NONE, garbage, a quote not in the label). DEFECT
    while red (review: the Singapore value is written in 12 of 12 cells, a right model overwritten)."""
    bad = []
    for tmpl, klass, sg, _us in N1_FRAMES:
        label = tmpl.format(p="outside Singapore")
        for value in ("Yes", "No"):
            for kind in ("right", "ordinary"):
                for pick in (pick_faithful(sg, sg), pick_faithful(_opp(sg), _opp(sg))):
                    for reply in OUTSIDE_PLACE_REPLIES:
                        ask = PlaceAsk(lambda v, k=_k(kind, klass), x=value: lie(x, k), place=reply, pick=pick)
                        res = attempt(_f(label), ask)
                        if is_stop(res) or shown(res) != "" or res.fills or NOTE not in _note(res):
                            bad.append((label[:58], value, kind, reply, what(res)))
    assert not bad, report(bad, 10)


def test_n1b_the_states_with_a_place_call_that_quotes_the_states_uses_the_united_states_facts():
    """N1 / P3: "... work in the States" with a place call that quotes "the States" (an alias of the US): the US facts (not
    authorised, needs sponsorship, restricted). A right model + a confirmation that follows the US truth: the right value is
    written; a wrong model + a confirmation that follows the SINGAPORE text: never the Singapore-based value. Exactly one place
    call per field. DEFECT while red (review: the Singapore value written with 0 calls)."""
    bad = []
    for tmpl, klass, sg, us in N1_FRAMES:
        label = tmpl.format(p="in the States")
        for kind in CLASSES:
            ask = PlaceAsk(lambda v, k=_k(kind, klass), r=us: lie(r, k), place="the States", pick=pick_faithful(us, us))
            res = attempt(_f(label), ask)
            if shown(res) != us or len(ask.place_calls) != 1:
                bad.append((label[:58], kind, "right model + US-truth confirmation", what(res), len(ask.place_calls)))
            ask = PlaceAsk(lambda v, k=_k(kind, klass), w=sg: lie(w, k), place="the States", pick=pick_faithful(sg, sg))
            res = attempt(_f(label), ask)
            if shown(res) == sg:
                bad.append((label[:58], kind, "wrong model + Singapore-text confirmation", what(res), len(ask.place_calls)))
            ask = PlaceAsk(lambda v, k=_k(kind, klass), r=us: lie(r, k), place="the States", pick=pick_faithful(sg, sg))
            res = attempt(_f(label), ask)
            if shown(res) == sg:
                bad.append((label[:58], kind, "right model + Singapore-text confirmation", what(res), len(ask.place_calls)))
    assert not bad, report(bad, 10)


def test_n1c_the_states_with_an_unusable_or_disagreeing_place_reply_ends_empty_with_the_note():
    """N1 / P3: "... work in the States" and a place reply that is garbage, NOT in the label, "Singapore" (a lying model) or
    NONE (code finds the place word "the States"): EMPTY with the place note, whatever the model and the votes say."""
    bad = []
    for tmpl, klass, sg, us in N1_FRAMES:
        label = tmpl.format(p="in the States")
        for reply in (GARBAGE, NOT_IN_LABEL, "Singapore", "NONE"):
            for value in ("Yes", "No"):
                for pick in (pick_faithful(sg, sg), pick_faithful(us, us)):
                    ask = PlaceAsk(lambda v, k=klass, x=value: lie(x, k), place=reply, pick=pick)
                    res = attempt(_f(label), ask)
                    if is_stop(res) or shown(res) != "" or res.fills or NOTE not in _note(res):
                        bad.append((label[:58], reply, value, what(res)))
    assert not bad, report(bad, 10)


N1_PLACES = (   # (the words the label says, a proper-noun place: NONE must not be accepted)
    ("in the States", True), ("in the Gulf", True), ("in the Czech Republic", True), ("in the Emirates", True),
    ("in the Nordics", True), ("in the PRC", True), ("in the Republic of Korea", True),
    ("in the Kingdom of Saudi Arabia", True), ("in the Caribbean", True), ("in the Bay Area", True),
    ("in a foreign country", False), ("in any of our offices", False),
    ("in Singapore and any other country", True), ("outside Singapore", True),
)
# "the States" is a US alias (N1b); every other phrase is not one country: it must end empty
N1_EMPTY_PLACES = tuple(p for p in N1_PLACES if p[0] != "in the States")


def test_n1d_the_reviews_14_place_phrases_end_empty_with_the_note():
    """N1: the review's 13 place phrases other than "the States" (the Gulf, the Czech Republic, the Emirates, the Nordics, the
    PRC, the Republic of Korea, the Kingdom of Saudi Arabia, the Caribbean, the Bay Area, a foreign country, any of our offices,
    "Singapore and any other country", "outside Singapore"), each in the authorised frame, a right and a wrong model: EMPTY
    with the place note; the place reply is the phrase itself, garbage, or (for a named place only) NONE. The
    Singapore-based value is never written."""
    bad = []
    for words, named in N1_EMPTY_PLACES:
        label = f"Are you authorised to work {words}?"
        replies = [words.replace("in ", "", 1) if words.startswith("in ") else words, GARBAGE] + (["NONE"] if named else [])
        for reply in replies:
            for value in ("Yes", "No"):
                ask = PlaceAsk(lambda v, x=value: lie(x, "work_right"), place=reply, pick=pick_faithful("Yes", "Yes"))
                res = attempt(_f(label), ask)
                if is_stop(res) or shown(res) != "" or res.fills or NOTE not in _note(res):
                    bad.append((label[:62], reply, value, what(res)))
    assert not bad, report(bad, 10)


# ================================================================== P3 mechanics

def test_p3_a_quote_that_is_not_in_the_label_or_names_no_single_country_ends_empty():
    """P3: a quote that is not a substring of the label ("Zzyzx Province") ends EMPTY with the note; so does "any location"
    (M5: "Are you authorised to work in any location?" must not take Singapore's truth), whatever the model says."""
    bad = []
    for label, reply in (("Are you authorised to work in the States?", NOT_IN_LABEL),
                         ("Are you authorised to work in Singapore and the States?", "Texas"),
                         ("Are you authorised to work in any location?", "any location"),
                         ("Are you authorised to work in any location?", "NONE"),
                         ("Are you authorised to work in any location?", GARBAGE)):
        for value in ("Yes", "No"):
            ask = PlaceAsk(lambda v, x=value: lie(x, "work_right"), place=reply, pick=pick_faithful("Yes", "Yes"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or res.fills or NOTE not in _note(res):
                bad.append((label[:58], reply, value, what(res)))
    assert not bad, report(bad)


def test_p3_a_lying_quote_singapore_on_outside_singapore_is_disagreed_by_code_and_ends_empty():
    """P3: the model quotes "Singapore" on "... work outside Singapore" (a lying model): code's exclusion / residue reading
    disagrees: EMPTY with the note (also in the sponsorship frame, a right and a wrong model)."""
    bad = []
    for label in ("Are you legally authorised to work outside Singapore?", "Do you require sponsorship to work outside Singapore?"):
        for value in ("Yes", "No"):
            ask = PlaceAsk(lambda v, x=value: lie(x, "work_right"), place="Singapore", pick=pick_faithful(value, value))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:58], value, what(res)))
    assert not bad, report(bad)


def test_p3_a_model_none_while_the_label_holds_a_place_word_ends_empty():
    """P3: the model says NONE but the label holds a place word (Atlantis, Narnia, the Gulf): EMPTY with the note."""
    bad = []
    for place in ("Atlantis", "Narnia", "the Gulf"):
        label = f"Are you authorised to work in {place}?"
        for value in ("Yes", "No"):
            ask = PlaceAsk(lambda v, x=value: lie(x, "work_right"), place="NONE", pick=pick_faithful(value, value))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:58], value, what(res)))
    assert not bad, report(bad)


def test_p3_an_alias_of_the_job_country_quoted_from_the_label_gives_singapores_answer():
    """P3 / M4 improved: "SG" and "S'pore" (known aliases of the job country) answer with Singapore's facts: a right model
    answer is written (Yes authorised, No sponsorship), with the model's quote of that alias or NONE, never left empty."""
    bad = []
    for alias in ("SG", "S'pore", "the Republic of Singapore"):
        for tmpl, klass, right in (("Are you authorised to work in {a}?", "work_right", "Yes"),
                                   ("Do you require sponsorship to work in {a}?", "sponsorship", "No")):
            label = tmpl.format(a=alias)
            for reply in (alias.replace("the ", ""), "NONE"):
                ask = PlaceAsk(lambda v, k=klass, r=right: lie(r, k), place=reply, pick=pick_faithful(right, right))
                res = attempt(_f(label), ask)
                if is_stop(res) or shown(res) != right or NOTE in _note(res):
                    bad.append((label[:58], reply, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_p3_a_transport_failure_in_the_place_call_ends_the_page_as_model_unavailable():
    """P3: the place call (a label that needs one: "in the States") fails at the transport (BackendError): the PAGE ends
    `transport_failed` (the flow ends FAILED / model_unavailable); the field is not quietly left empty or answered."""
    bad = []
    for tmpl, klass, sg, _us in N1_FRAMES:
        label = tmpl.format(p="in the States")
        ask = PlaceAsk(lambda v, k=klass, x=sg: lie(x, k), place_down=True, pick=pick_faithful(sg, sg))
        out = outcome(_f(label), ask)
        if not out.transport_failed:
            bad.append((label[:58], "page not ended", what(out.answers["u"]) if out.answers.get("u") else "", len(ask.place_calls)))
    assert not bad, report(bad)


def test_p3_control_a_pure_singapore_label_makes_no_place_call_so_a_dead_place_call_changes_nothing():
    """P1 control (expected GREEN): "Are you legally authorised to work in Singapore?" holds only frame words and the job
    country's name: NO place call; with a place call that would fail, the answer is still written and the page not ended."""
    ask = PlaceAsk(lambda v: lie("Yes", "work_right"), place_down=True, pick=pick_faithful("Yes", "Yes"))
    out = outcome(_f("Are you legally authorised to work in Singapore?"), ask)
    res = out.answers["u"]
    assert not out.transport_failed and shown(res) == "Yes" and not ask.place_calls, (what(res), len(ask.place_calls))


# ================================================================== the regression table: 30 Singapore-job wordings

# (label, right value, today's source, today's assumed flag, today's model calls on the field, PURE: no place call at all)
# "today's" = measured on int/Q-121 b61954c with a right model, class from code's key, a faithful confirmation. PURE = only frame
# words and the job country's exact name (P1): exactly ZERO place calls; every other row may force AT MOST ONE place call
# (the reviewer's "residue" cases), and the scripted place reply is the job country's name where the label has one, else NONE.
SG_AUTH = "profile:singapore_status.authorised_to_work.SG"
SG_SPON = "profile:singapore_status.requires_sponsorship.SG"
SG_RES = "profile:singapore_status.authorised_to_work"
ASSUME = "assumption"
REGRESSION = (
    ("Are you legally authorised to work in Singapore?", "Yes", SG_AUTH, False, 0, True),
    ("Do you require sponsorship to work in Singapore?", "No", SG_SPON, False, 0, True),
    ("Will you now or in the future require sponsorship for employment visa status?", "No", SG_SPON, False, 0, False),
    ("Are you a Singapore Citizen or Permanent Resident?", "Yes", "profile:singapore_status.residency_status", False, 0, False),
    ("Do you have the right to work in the country where this role is based?", "Yes", SG_AUTH, False, 0, False),
    ("Do you have any restrictions on your right to work in Singapore?", "No", SG_RES, False, 0, True),
    ("Are you authorised to work in Singapore?", "Yes", SG_AUTH, False, 0, True),
    ("Are you eligible to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Are you entitled to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Are you permitted to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Do you have the legal right to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Do you need a work pass to work in Singapore?", "No", ASSUME, True, 2, False),
    ("Do you require visa sponsorship to work in Singapore?", "No", SG_SPON, False, 0, True),
    ("Will you require visa sponsorship now or in the future?", "No", SG_SPON, False, 0, False),
    ("Will you require sponsorship for an Employment Pass?", "No", ASSUME, True, 2, False),
    ("Are you legally authorised to work in this country?", "Yes", SG_AUTH, False, 0, True),
    ("Are you authorised to work here?", "Yes", SG_AUTH, False, 0, False),
    ("Are you legally eligible to work without sponsorship?", "Yes", ASSUME, True, 2, False),
    ("Can you work in Singapore without sponsorship?", "Yes", ASSUME, True, 2, False),
    ("Do you currently hold the right to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Are you authorized to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Is your right to work in Singapore restricted?", "No", SG_RES, False, 0, False),
    ("Do you have any limitations on your right to work in this country?", "No", SG_RES, False, 0, False),
    ("Are you prohibited from working in Singapore?", "No", ASSUME, True, 2, False),
    ("Do you require an employment visa to work in Singapore?", "No", ASSUME, True, 0, False),
    ("Are you a foreign national requiring a work permit to work in Singapore?", "No", ASSUME, True, 2, False),
    ("Will you need your employer to apply for a work permit for you in Singapore?", "No", ASSUME, True, 2, False),
    ("Are you legally authorised to work in the country in which this role is located?", "Yes", SG_AUTH, False, 0, False),
    ("Are you currently authorised to work in Singapore?", "Yes", SG_AUTH, False, 0, False),
    ("Do you require sponsorship to work in the country where this role is based?", "No", SG_SPON, False, 0, False),
)


def _place_reply_for(label: str) -> str:
    return "Singapore" if "Singapore" in label else "NONE"


def test_regression_thirty_singapore_job_wordings_stay_answered_exactly_as_today():
    """THE REGRESSION TABLE (expected GREEN today; must stay GREEN after the fix): 30 common wordings on a Singapore job, a
    right model, class from code's key, a faithful confirmation: the value, the source, the assumed flag and the number of model
    calls on the field (not counting place calls) are exactly today's. Place calls: ZERO for a pure form (frame words + the job
    country's exact name), at most ONE for any other wording (a residue), with the scripted reply "Singapore" / NONE; a place
    call never changes the answer. Re-based on D-222 S3 for the row "Are you a Singapore Citizen or Permanent Resident?" only (source `profile:singapore_status.residency_status`, assumed False, 0 calls)."""
    bad = []
    assert len(REGRESSION) == 30
    for label, right, source, assumed, calls, pure in REGRESSION:
        ask = PlaceAsk(lambda v, r=right: lie(r), place=_place_reply_for(label), pick=pick_faithful(right, right))
        res = attempt(_f(label), ask)
        n_place = len(ask.place_calls)
        if is_stop(res) or shown(res) != right or str(res.source) != source or bool(res.assumed) is not assumed \
                or len(ask.picks) != calls or NOTE in _note(res):
            bad.append((label[:56], "answer", what(res), len(ask.picks)))
        if n_place > (0 if pure else 1):
            bad.append((label[:56], "place calls", n_place, "pure" if pure else "residue"))
    assert not bad, report(bad, 10)


def test_regression_a_wrong_model_answer_on_the_same_wordings_is_never_written():
    """Regression guard (expected GREEN): the 30 wordings with a WRONG model answer, an agreeing confirmation and faithful
    meaning calls never end on the wrong value (two ordinary-keyed rows, 4 and 25, are the model's own answer today and are
    left out)."""
    bad = []
    for label, right, _s, _a, _c, _p in REGRESSION:
        if label in ("Are you a Singapore Citizen or Permanent Resident?", "Do you require an employment visa to work in Singapore?"):
            continue
        wrong = _opp(right)
        ask = PlaceAsk(lambda v, w=wrong: lie(w), place=_place_reply_for(label), pick=pick_faithful(wrong, right))
        res = attempt(_f(label), ask)
        if shown(res) == wrong:
            bad.append((label[:56], what(res), len(ask.place_calls)))
    assert not bad, report(bad)


# ================================================================== the page cap (P5)

def test_p5_six_work_rights_fields_that_each_need_a_place_call_stay_within_the_page_cap():
    """P5: a page of 6 work-rights fields that each need the place call ("in the States", the three frames x 2 wordings):
    at most ONE place call per field, the page is not stopped (no `unanswerable_required` / too many calls), no transport
    failure, and every answer is the United States's facts or empty, never the Singapore-based value. Pinned until the
    engineer's cap formula is known: `place calls <= fields`. DEFECT while red (the Singapore value is written today)."""
    labels = (("Are you authorised to work in the States?", "work_right", "Yes", "No"),
              ("Are you legally authorised to work in the States?", "work_right", "Yes", "No"),
              ("Do you require sponsorship to work in the States?", "sponsorship", "No", "Yes"),
              ("Will you require sponsorship to work in the States?", "sponsorship", "No", "Yes"),
              ("Do you have any restrictions on your right to work in the States?", "work_right", "No", "Yes"),
              ("Is your right to work in the States restricted?", "work_right", "No", "Yes"))
    fields = [_f(lab, key=f"w{i}") for i, (lab, *_r) in enumerate(labels)]
    by_label = {f"w{i}": (k, us) for i, (_l, k, _sg, us) in enumerate(labels)}
    ask = PlaceAsk(lambda v: lie(by_label[v["id"]][1], by_label[v["id"]][0]), place="the States", pick=pick_faithful("No", "No"))
    out = outcome_page(fields, ask)
    assert out is not None, "the page was stopped"
    bad = []
    if out.transport_failed or len(ask.place_calls) > len(fields):
        bad.append(("page", out.transport_failed, len(ask.place_calls)))
    for i, (lab, _k2, sg, us) in enumerate(labels):
        a = out.answers.get(f"w{i}")
        if a is None or shown(a) == sg:
            bad.append((lab[:56], "Singapore-based value", what(a) if a else None))
    assert not bad, report(bad)


def outcome_page(fields, ask):
    """The PageOutcome of a page, or None when the page raised a stop."""
    from always_a1_support import _run
    from jobscraper.apply import always as AL
    try:
        return _run(list(fields), ask, None)
    except AL.AlwaysStop:
        return None


# ================================================================== N2 / R: keep on file with any residue

N2_REVIEW = (
    "Keep my application on file and reach out to me about other jobs",
    "Keep my application on file and send me relevant roles",
    "Keep my application on file so we can stay in touch",
    "Keep my application on file and message me on WhatsApp",
    "Keep my application on file and call me about opportunities",
    "Keep my application on file and invite me to events",
    "Retain my details for future positions and get in touch",
)
N2_OWN = (   # wordings with a residue the engineer has never seen
    "Keep my application on file and add me to your WhatsApp group",
    "Keep my application on file and tell me about graduate programmes",
    "Keep my CV on file and email me about graduate programmes",
    "Keep my details on file and enrol me in your alumni network",
    "Keep my application on file and ping me when something opens up",
)
N2_SHARING = (   # D-224 5a: third-party SHARING is its own consent, not retention: moved out of the both-consents table
    "Keep my CV on file and share my details with affiliates",
    "Keep my application on file and pass it to hiring managers in other group companies",
)
N2_CLASSES = ("marketing", "consent_retention", "ordinary", NO_CLASS)
N2_PURE = (
    "Keep my application on file for future roles",
    "Keep my application on file for similar positions",
    "Please consider me for other opportunities and keep my details on file",
)
N2_PURE_NEW = "Retain my CV for up to 2 years for other vacancies"   # code has no key for "retain": red until R is built


def _box(label):
    return _pf("b", label, "CHECKBOX", required=False)


def test_n2_a_keep_on_file_label_with_any_residue_needs_both_consents():
    """N2 / R: the review's 8 labels and 6 wordings of the tester's own, each a keep-on-file frame plus something else (a
    contact, a message, an invitation, an addition to a group, sharing): the truth is `retention AND talent_pool_opt_in`:
    retention true / opt-in false -> NOT ticked (the model says tick; class marketing / retention / ordinary / none alike);
    both true -> ticked. DEFECT while red (review: ticked, not assumed, 0 calls)."""
    bad = []
    only = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    both = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=True)
    for label in N2_REVIEW + N2_OWN:
        for klass in N2_CLASSES:
            for name, prof, want in (("retention only", only, False), ("both", both, True)):
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                res = attempt(_box(label), ask, prof)
                if is_stop(res) or is_ticked(res) is not want:
                    bad.append((label[:56], name, klass, "want ticked" if want else "want NOT ticked", what(res)))
    assert not bad, report(bad, 12)


def test_n2_sharing_with_a_third_party_is_unticked_in_every_consent_combination():
    """D-224 5a (moved out of the both-consents test above): "... share my details with affiliates" and "... pass it to hiring
    managers in other group companies" are third-party SHARING, which no profile consent covers: NOT ticked whatever the
    retention / opt-in values and whatever class the model names, source `default:no_third_party_sharing`."""
    bad = []
    for label in N2_SHARING:
        for ret in (True, False):
            for pool in (True, False):
                prof = profile_with(consents__data_retention_consent=ret, consents__talent_pool_opt_in=pool)
                for klass in N2_CLASSES:
                    ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                    res = attempt(_box(label), ask, prof)
                    if is_stop(res) or is_ticked(res) or "no_third_party_sharing" not in str(res.source):
                        bad.append((label[:56], ret, pool, klass, what(res)))
    assert not bad, report(bad, 12)


def test_n2_control_pure_retention_wordings_stay_ticked_with_retention_only():
    """R control (expected GREEN): "for future roles", "for similar positions", "consider me for other opportunities": nothing is
    left after the frame and the neutral list: retention alone ticks the box, whatever
    class the model names and whether it ticks or not."""
    bad = []
    prof = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    for label in N2_PURE:
        for klass in N2_CLASSES:
            for said in ("true", "false"):
                ask = FakeAsk(lambda v, k=klass, s=said: lie(s, k), pick=pick_by("", ""))
                res = attempt(_box(label), ask, prof)
                if is_stop(res) or not is_ticked(res):
                    bad.append((label[:56], klass, said, what(res)))
    assert not bad, report(bad)


def test_n2_a_pure_retain_wording_with_a_duration_follows_the_retention_consent_alone():
    """R (D-220): "Retain my CV for up to 2 years for other vacancies" (a verb the code has no key for today: the box then
    follows the model and its class, and a model class `marketing` ends it UNTICKED, "protective end: marketing"): nothing is
    left after the frame, the duration and the neutral list, so the box follows `consents.data_retention_consent` alone (true ->
    ticked) whatever class the model names and whether it ticks or not, as test_always_a1_fix9 fix9-2 pins for the older
    wordings. RED until R is built (assumed from D-220 R + fix9-2; say so if the ruling meant otherwise)."""
    bad = []
    prof = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    for klass in N2_CLASSES:
        for said in ("true", "false"):
            ask = FakeAsk(lambda v, k=klass, s=said: lie(s, k), pick=pick_by("", ""))
            res = attempt(_box(N2_PURE_NEW), ask, prof)
            if is_stop(res) or not is_ticked(res):
                bad.append((klass, said, what(res)))
    assert not bad, report(bad)


def test_n2_a_third_party_sharing_box_is_never_ticked_in_any_consent_combination():
    """D-220 R, Coordinator ruling (round 4): "Keep my CV on file and let recruiters from partner firms see it" is a
    third-party SHARING consent: the product keeps it as it is (the resolver reads "partner" as a relatives word and the box ends
    unticked: the conservative outcome): NOT ticked in ANY of the four combinations of retention / talent-pool consent, whatever
    the model's class and whether it ticks (expected GREEN, pinned as it IS)."""
    label = "Keep my CV on file and let recruiters from partner firms see it"
    bad = []
    for ret in (True, False):
        for pool in (True, False):
            prof = profile_with(consents__data_retention_consent=ret, consents__talent_pool_opt_in=pool)
            for klass in N2_CLASSES:
                ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("", ""))
                res = attempt(_box(label), ask, prof)
                if is_stop(res) or is_ticked(res):
                    bad.append((f"retention {ret}", f"pool {pool}", klass, what(res)))
    assert not bad, report(bad)


# ================================================================== round 4: the engineer's choices the ruling left open

def test_choice_a_leading_in_is_stripped_from_the_models_quote():
    """Engineer's choice (`quoted_place`): the model's quote may carry a leading "in" / "within" ("in the States", "in
    Singapore"): it is stripped before the country is read, so the quote of a country is accepted either way. "in the States"
    gives the US facts (a right model + a US-truth confirmation: "No"); "in Singapore" on a residue label gives Singapore's."""
    bad = []
    ask = PlaceAsk(lambda v: lie("No", "work_right"), place="in the States", pick=pick_faithful("No", "No"))
    res = attempt(_f("Are you authorised to work in the States?"), ask)
    if is_stop(res) or shown(res) != "No" or NOTE in _note(res) or len(ask.place_calls) != 1:
        bad.append(("in the States", what(res), len(ask.place_calls)))
    ask = PlaceAsk(lambda v: lie("Yes", "work_right"), place="in Singapore", pick=pick_faithful("Yes", "Yes"))
    res = attempt(_f("Are you currently authorised to work for Example Employer in Singapore?"), ask)
    if is_stop(res) or shown(res) != "Yes" or NOTE in _note(res):
        bad.append(("in Singapore", what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_choice_this_country_the_country_where_the_role_is_based_and_here_make_no_place_call():
    """Engineer's choice (`pure_work_label`): "this country", "the country where this role is based" and "here" count as the
    job country: NO place call (a dead place call would end the page: it must not matter) and Singapore's answer is written, in
    the authorised and the sponsorship frames."""
    bad = []
    for label, klass, right in (("Are you authorised to work in this country?", "work_right", "Yes"),
                                ("Are you authorised to work in the country where this role is based?", "work_right", "Yes"),
                                ("Are you authorised to work here?", "work_right", "Yes"),
                                ("Do you require sponsorship to work in this country?", "sponsorship", "No"),
                                ("Do you require sponsorship to work in the country where this role is based?", "sponsorship", "No"),
                                ("Do you require sponsorship to work here?", "sponsorship", "No")):
        ask = PlaceAsk(lambda v, k=klass, r=right: lie(r, k), place_down=True, pick=pick_faithful(right, right))
        out = outcome(_f(label), ask)
        res = out.answers["u"]
        if out.transport_failed or ask.place_calls or shown(res) != right:
            bad.append((label[:60], what(res), len(ask.place_calls), out.transport_failed))
    assert not bad, report(bad)


def test_choice_a_quoted_country_followed_at_once_by_and_or_or_is_rejected():
    """Engineer's choice (`quoted_place`, `_PLACE_JOINS`): the model quotes "Singapore" but the label goes on "or Malaysia" /
    "and the States": not one country: EMPTY with the place note, whatever the model and the votes say."""
    bad = []
    for label in ("Are you authorised to work in Singapore or Malaysia?", "Are you authorised to work in Singapore and the States?",
                  "Do you require sponsorship to work in Singapore or Malaysia?"):
        for value in ("Yes", "No"):
            ask = PlaceAsk(lambda v, x=value: lie(x, "work_right"), place="Singapore", pick=pick_faithful(value, value))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:60], value, what(res)))
    assert not bad, report(bad)


def test_choice_standing_place_agrees_the_strict_readers_singapore_answer_is_dropped_for_the_states():
    """Engineer's choice (`standing_place_agrees`): the strict reader's standing answer for a work-rights label is used only
    when it was read for the same country as the place the filler read. "... in the States" with the place quoted as "the
    States": NEVER Singapore's answer (no `.SG` source, never the Singapore-based value), whatever the model and the votes say."""
    bad = []
    for label, klass, sg in (("Are you authorised to work in the States?", "work_right", "Yes"),
                             ("Do you require sponsorship to work in the States?", "sponsorship", "No")):
        for value in ("Yes", "No"):
            for pick in (pick_by(sg, "no"), pick_by(_opp(sg), "no"), pick_by("", "")):
                ask = PlaceAsk(lambda v, k=klass, x=value: lie(x, k), place="the States", pick=pick)
                res = attempt(_f(label), ask)
                if not is_stop(res) and (shown(res) == sg or str(res.source).endswith(".SG")):
                    bad.append((label[:50], value, what(res)))
    assert not bad, report(bad)


def test_choice_cap_six_place_call_fields_stay_under_the_formula_and_a_fixed_cap_never_grows():
    """Engineer's choice (P5): the page cap is `3 x chunks + 20 + 3 per voted field + 1 per E1 call + 1 per place call`: a page
    of six fields that each need the place call makes exactly six place calls and is NOT stopped; a FIXED `max_calls_page`
    never grows for a place call: with cap 3 the same page stops (`unanswerable_required`, "too many model calls") after at
    most 2 place calls."""
    from jobscraper.apply.contracts import ReasonCode
    labels = ("Are you authorised to work in the States?", "Are you legally authorised to work in the States?",
              "Do you require sponsorship to work in the States?", "Will you require sponsorship to work in the States?",
              "Do you have any restrictions on your right to work in the States?", "Is your right to work in the States restricted?")
    fields = [_f(lab, key=f"w{i}") for i, lab in enumerate(labels)]
    ask = PlaceAsk(lambda v: lie("No", "work_right"), place="the States", pick=pick_faithful("No", "No"))
    out = outcome_page(fields, ask)
    bad = []
    if out is None or out.transport_failed or len(ask.place_calls) != 6:
        bad.append(("default cap", None if out is None else out.transport_failed, len(ask.place_calls)))
    ask = PlaceAsk(lambda v: lie("No", "work_right"), place="the States", pick=pick_faithful("No", "No"))
    got = page(fields, ask, cfg={"max_calls_page": 3})
    if not (is_stop(got) and got.reason is ReasonCode.UNANSWERABLE_REQUIRED and "too many model calls" in got.detail) \
            or len(ask.place_calls) > 2:
        bad.append(("fixed cap 3", "stop" if is_stop(got) else "no stop", len(ask.place_calls)))
    assert not bad, report(bad)


def test_accepted_limits_all_caps_for_us_spain_korea_and_the_czech_republic_end_empty():
    """Accepted limits, pinned as they ARE: an ALL-CAPS label ("... TO WORK FOR US?": "US" reads as the United States and as
    the job country, D-76) and a real country the resolver does not map (Spain, Korea, the Czech Republic) end EMPTY with the
    place note, whatever the model says and quotes (the shared fake's sensible quote)."""
    bad = []
    for label in ("DO YOU REQUIRE SPONSORSHIP TO WORK FOR US?", "Are you authorised to work in Spain?",
                  "Are you authorised to work in Korea?", "Are you authorised to work in the Czech Republic?"):
        for value in ("Yes", "No"):
            ask = PlaceAsk(lambda v, x=value: lie(x, "work_right"), place=None, pick=pick_by(value, "no"))
            res = attempt(_f(label), ask)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((label[:56], value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)
