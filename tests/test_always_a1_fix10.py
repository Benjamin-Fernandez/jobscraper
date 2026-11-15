"""Q-121 Amendment A1, the fix10 pin round (fix10 b: a true/false fact confirms only on its own family; fix7-1 for choice lists).

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step, so every pin keeps its assertion on
the HARMFUL outcome (an answer that merely MATCHES the value of an unrelated true/false fact written as if the profile
backed it; a first-option / neutral pick on a choice list nothing classed, with 0 calls). Expected values come from the
rulings, never from what the code does:

  fix10 b   a boolean `profile:` row, or a `standing:` line valued yes / no, backs an answer only on a question of its OWN
            family. On any other question the value the model gave stays (it is the model's judgement) but the answer is
            marked ASSUMED, note "basis not confirmed". Own family: over 18, willing to relocate, currently employed,
            worked for this employer before, applied here before (code keys the last two as declarations: 0 calls).
  fix10 a   (pinned in test_always_a1_fix9.py::test_a_def_*: `default:willing` / `default:no_declaration` cites on a
            reservist question). Here only the two rows that file does not hold: a `standing:prior_roles` cite and a
            `default:talent_pool` cite on an unrelated ordinary question.
  fix7-1    a REQUIRED choice list (not only a yes/no) with NO code key and NO model class gets exactly ONE single-field
            ask, never the first option / the neutral option with 0 calls; an unusable reply leaves it empty for the site;
            a model class (incl. `ordinary`) keeps the ladder as built; the profile-derived lists (how did you hear,
            country, graduation year) are unchanged; an OPTIONAL unclassed list with no reply gets no call and stays empty.
  protected a declaration and a work-rights question on the SAME page as those rows are answered as they would be alone
            (the reader's truth), and neither mechanism adds a call for them.

Fakes only: no model, no network, no browser, sample profile (a Singapore citizen: authorised in SG, NOT in the US, all
declarations false), made-up names ("Example Employer").
Verify: python tests/run_tests.py -k always_a1_fix10
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, lie, page, report, say, shown, what, _pf)
from test_always_a1_fix8 import _kinds  # noqa: E402

NOT_CONFIRMED = "basis not confirmed"


def _f(label, *, key="u", tn="RADIO", required=True, options=YN):
    return _pf(key, label, tn, required=required, options=options if tn in ("RADIO", "DROPDOWN") else ())


def _cite(value, ref, klass="ordinary"):
    """The model's reply for an ordinary question: `value` backed by the cited row (`profile:` / `standing:` / `default:`),
    not marked assumed by the model."""
    return say(value, ref.split(":", 1)[0], ref, False, klass=klass)


def _note(res) -> str:
    return "" if is_stop(res) else f"{res.note} {res.evidence}"


# ================================================================== fix10 b (a): a matching fact on an unrelated question

UNRELATED = (    # (label, the value the model gave, the true/false row it cites: the value MATCHES the row)
    ("Are you liable for reservist duties?", "No", "standing:worked_here"),
    ("Do you hold a reserve rank or commission?", "No", "profile:declarations.government_employment"),
    ("Do you own a car?", "Yes", "profile:consents.privacy_consent"),
    ("Do you own a car?", "Yes", "profile:singapore_status.authorised_to_work.SG"),
    ("Do you have a car?", "No", "standing:currently_employed"),
)


def test_fix10_b_a_matching_true_false_fact_on_an_unrelated_question_is_marked_assumed_basis_not_confirmed():
    """fix10 b (a): five unrelated yes/no questions, each citing a true/false row whose value equals the model's answer.
    The value stays (the model's judgement, 0 calls) but is marked ASSUMED with the note "basis not confirmed", so it never
    reads as a profile fact. DEFECT while red (an unrelated fact written as a confirmed basis)."""
    bad = []
    for label, value, ref in UNRELATED:
        ask = FakeAsk(lambda v, x=value, r=ref: _cite(x, r), pick=lambda q, w, o: "")
        res = attempt(_f(label), ask)
        if shown(res) != value or not res.assumed or NOT_CONFIRMED not in _note(res) or ask.picks:
            bad.append((label[:40], ref, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix10_b_the_same_cites_are_assumed_when_the_model_names_no_class_at_all():
    """fix10 b (a), the cut-schema variant: a reply with no `class` key is judged the same way (family comes from code's
    key and the model's class; neither names the fact's family on these questions)."""
    bad = []
    for label, value, ref in UNRELATED:
        ask = FakeAsk(lambda v, x=value, r=ref: _cite(x, r, NO_CLASS), pick=lambda q, w, o: "")
        res = attempt(_f(label), ask)
        if shown(res) != value or not res.assumed or NOT_CONFIRMED not in _note(res):
            bad.append((label[:40], ref, what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== fix10 b (b): the fact's OWN question stays confirmed

OWN = (    # (label, value, row): the question belongs to the row's family
    ("Are you over 18?", "Yes", "standing:age_18_plus"),
    ("Are you willing to relocate?", "No", "profile:availability.willing_to_relocate"),
    ("Are you currently employed?", "No", "standing:currently_employed"),
    ("Have you ever worked for Example Employer before?", "No", "standing:worked_here"),
    ("Have you previously applied to Example Employer?", "No", "standing:previously_applied"),
)


def test_fix10_b_a_true_false_fact_on_its_own_question_stays_confirmed_not_assumed():
    """fix10 b (b): five questions that cite their OWN fact are written as the row says, NOT marked assumed, with no
    "basis not confirmed" note and no extra call (control: the family check must not over-reach)."""
    bad = []
    for label, value, ref in OWN:
        ask = FakeAsk(lambda v, x=value, r=ref: _cite(x, r), pick=lambda q, w, o: "")
        res = attempt(_f(label), ask)
        if shown(res) != value or res.assumed or NOT_CONFIRMED in _note(res) or ask.picks:
            bad.append((label[:45], ref, what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== fix10 a, the rows fix9 does not hold

OTHER_FAMILY = (    # a judged standing line / a default rule cited on a question of another family
    ("Do you own a car?", "No", "standing:prior_roles"),
    ("Do you own a car?", "No", "default:talent_pool"),
)


def test_fix10_a_a_standing_or_default_cite_on_another_family_is_marked_assumed():
    """fix10 a (the rows beside test_always_a1_fix9's reservist rows): a `standing:prior_roles` cite on a car question and
    a `default:talent_pool` cite on an ordinary field are marked ASSUMED, note "basis not confirmed", value kept."""
    bad = []
    for label, value, ref in OTHER_FAMILY:
        ask = FakeAsk(lambda v, x=value, r=ref: _cite(x, r), pick=lambda q, w, o: "")
        res = attempt(_f(label), ask)
        if shown(res) != value or not res.assumed or NOT_CONFIRMED not in _note(res):
            bad.append((label[:40], ref, what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== fix7-1 for choice lists

UNCLASSED_LISTS = (    # a REQUIRED list nothing keys or classes (the engineer's two)
    ("Do you enjoy working in a team environment?", ("Yes", "No", "Not sure")),
    ("Which shift do you prefer?", ("Morning", "Evening", "No preference")),
)


def test_fix7_1_choice_a_silent_model_on_an_unclassed_required_list_gets_exactly_one_ask_never_a_blind_pick():
    """fix7-1 (choice lists): no code key, no model class, a silent model: exactly ONE single-field ask. A usable reply is
    written (assumed, note "single-field ask"); the neutral option / the first option never comes with 0 calls."""
    bad = []
    for label, opts in UNCLASSED_LISTS:
        for tn in ("RADIO", "DROPDOWN"):
            reply = opts[-1]                      # the neutral / last option: not what a blind first-option pick gives
            ask = FakeAsk(pick=lambda q, w, o, r=reply: r)
            res = attempt(_f(label, tn=tn, options=opts), ask)
            if shown(res) != reply or not res.assumed or _kinds(ask) != ["ask"] or "single-field ask" not in _note(res):
                bad.append((label[:34], tn, reply, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_choice_an_unusable_ask_leaves_the_required_list_empty_for_the_site():
    """fix7-1 (choice lists): an ask answering "" / an option the list does not have leaves the REQUIRED list empty for the
    site (one call, a note saying so): never the first / the neutral option."""
    bad = []
    for label, opts in UNCLASSED_LISTS:
        for reply in ("", "Maybe", "Prefer not to say"):
            ask = FakeAsk(pick=lambda q, w, o, r=reply: r)
            res = attempt(_f(label, options=opts), ask)
            if shown(res) != "" or _kinds(ask) != ["ask"] or "left empty for the site" not in _note(res):
                bad.append((label[:34], reply, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_choice_a_model_class_ordinary_with_no_usable_value_gets_one_single_field_ask():
    """Q-121 final M1 (D-219) RETARGETED: this pin used to assert that a model class `ordinary` with an empty value keeps the
    ladder as built (no ask, the first option, assumed). M1 replaced that: `ordinary` + no usable value is no class for
    fix7-1, so the required list gets exactly ONE single-field ask, its usable answer is written, never the first option
    with 0 calls."""
    bad = []
    for label, opts in UNCLASSED_LISTS:
        ask = FakeAsk(lambda v: lie("", "ordinary"), pick=lambda q, w, o: opts[-1])
        res = attempt(_f(label, options=opts), ask)
        if _kinds(ask) != ["ask"] or shown(res) != opts[-1]:
            bad.append((label[:34], what(res), _kinds(ask)))
        ask = FakeAsk(lambda v: lie("", "ordinary"), pick=lambda q, w, o: "")
        res = attempt(_f(label, options=opts), ask)
        if _kinds(ask) != ["ask"] or shown(res) != "":
            bad.append((label[:34], "unusable ask", what(res), _kinds(ask)))
    assert not bad, report(bad)


PROFILE_LISTS = (    # (label, options, what the profile gives, the fix10 / F3 step that gives it)
    ("How did you hear about this job?", ("Company website", "LinkedIn", "Referral", "Other"), "Company website"),
    ("Country of residence", ("Singapore", "Malaysia", "India"), "Singapore"),
    ("Graduation year", ("2024", "2025", "2026", "2027"), "2025"),
)


def test_fix7_1_choice_the_profile_derived_lists_are_unchanged_with_no_call():
    """fix7-1 (choice lists): how did you hear / country / graduation year come from the profile or a standing rule with a
    silent model, 0 calls, never the single-field ask (and the same with a usable ask on offer)."""
    bad = []
    for label, opts, want in PROFILE_LISTS:
        ask = FakeAsk(pick=lambda q, w, o: opts[-1])
        res = attempt(_f(label, options=opts), ask)
        if shown(res) != want or ask.picks:
            bad.append((label[:34], want, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_choice_an_optional_unclassed_list_with_no_reply_gets_no_call_and_stays_empty():
    """fix7-1 (choice lists): an OPTIONAL list the model leaves silent gets no last resort at all: 0 calls, empty."""
    bad = []
    for label, opts in UNCLASSED_LISTS:
        ask = FakeAsk(pick=lambda q, w, o: opts[-1])
        res = attempt(_f(label, options=opts, required=False), ask)
        if shown(res) != "" or ask.picks:
            bad.append((label[:34], what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== protected classes: unchanged beside these rows

DECL = "Have you ever been declared bankrupt?"
SG = "Are you legally authorised to work in Singapore?"
US = "Are you legally authorised to work in the United States?"
TEAM = "Do you enjoy working in a team environment?"


def _mixed_fields():
    """The fix10 rows (an unrelated cite, an own-family cite, an unclassed choice list) with a declaration and two
    work-rights questions on the same page; the last three are the protected rows."""
    return [_f("Do you own a car?", key="car"), _f("Are you over 18?", key="age"),
            _f(TEAM, key="team", options=("Yes", "No", "Not sure")),
            _f(DECL, key="decl"), _f(SG, key="sg"), _f(US, key="us")]


def _answers_for(wrong: bool):
    """The model on that page: the declaration and the work-rights answers RIGHT (`wrong` False) or the opposite."""
    truth = {"decl": "No", "sg": "Yes", "us": "No"}
    refs = {"decl": ("default", "default:no_declaration"),
            "sg": ("profile", "profile:singapore_status.authorised_to_work.SG"),
            "us": ("profile", "profile:singapore_status.authorised_to_work.US")}

    def answer(v):
        k = v["id"]
        if k == "car":
            return _cite("Yes", "profile:consents.privacy_consent")
        if k == "age":
            return _cite("Yes", "standing:age_18_plus")
        if k in truth:
            val = truth[k] if not wrong else ("Yes" if truth[k] == "No" else "No")
            return say(val, refs[k][0], refs[k][1], False)
        return None                                   # the team list: a silent model
    return answer


def test_protected_a_declaration_and_work_rights_beside_the_fix10_rows_get_the_readers_truth_and_no_ask():
    """Protected-class regression: with the model RIGHT, the declaration and both work-rights answers on the mixed page are
    exactly those written for the same three fields alone (bankrupt No, Singapore Yes, United States No), with no extra
    call: the only single-field ask on the page is the unclassed team list's."""
    mixed = FakeAsk(_answers_for(False), pick=lambda q, w, o: "Not sure")
    alone = FakeAsk(_answers_for(False), pick=lambda q, w, o: "Not sure")
    res = page(_mixed_fields(), mixed)
    ref = page(_mixed_fields()[3:], alone)
    assert not is_stop(res) and not is_stop(ref), (what(res) if is_stop(res) else "", what(ref) if is_stop(ref) else "")
    got = {k: shown(res[k]) for k in ("decl", "sg", "us")}
    assert got == {"decl": "No", "sg": "Yes", "us": "No"}, got
    assert got == {k: shown(ref[k]) for k in ("decl", "sg", "us")}
    assert _kinds(mixed).count("ask") == 1, _kinds(mixed)                       # the team list only
    assert [k for k in _kinds(mixed) if k != "ask"] == _kinds(alone), (_kinds(mixed), _kinds(alone))
    assert shown(res["team"]) == "Not sure" and shown(res["age"]) == "Yes" and not res["age"].assumed
    assert res["car"].assumed and NOT_CONFIRMED in _note(res["car"])


def test_protected_a_wrong_model_answer_on_those_fields_is_never_written_beside_the_fix10_rows():
    """Protected-class regression: with the model WRONG on the declaration and on both work-rights questions (and a
    reader that gives nothing), the contradicting value is never written for any of them, on the mixed page either."""
    bad = []
    wrong = {"decl": "Yes", "sg": "No", "us": "Yes"}
    res = page(_mixed_fields(), FakeAsk(_answers_for(True), pick=lambda q, w, o: ""))
    if is_stop(res):
        return                                        # a stop of the page is a protective end too
    for k, bad_value in wrong.items():
        if shown(res[k]) == bad_value:
            bad.append((k, what(res[k])))
    assert not bad, report(bad)
