"""Q-121 closing round G2 (ruling D-226): a STATUS question that names NO country is about the JOB'S country.

The engineer's table (`comms/outbox/software-engineer.md`, D-226 entry) as pins, plus the guards:

  T1  the ten plain wordings x model class {ordinary, work_right, owner_fact, none} x model answer {right, wrong}: a right model is
      written with NO further call (no confirmation, no place call), source a `profile:singapore_status.*` fact, not assumed; a wrong
      model is never written (ONE confirmation: the right value, assumed; a confirmation that agrees with the wrong answer ends
      empty); never a STOP `owner_fact_missing`
  T2  the same on other facts built in memory: a PR, a work-pass holder, and a job in ANOTHER country (US)
  T3  work-pass wordings with no country: no canonical frame (the vote path): "No" for the citizen from `singapore_status.work_pass`
      (assumed), a model "Yes" never written
  T4  a qualifying tail ("by birth", "since 2020") has no code truth (G3): no fact cited, the facts line is in the confirmation
  T5  precedence: consent, other-person and National Service keys run before the status rule
  T6  the twelve non-status uses the engineer tested, and eight more that try to fool the predicate rule, as a radio and as a tick
      box: each behaves exactly as with the status code disabled and is never answered from the status facts

Expected values come from the ruling, never from what the code does. A row that fails against the ruling stays red and its test name
says DEFECT with a severity. Fakes only: no model, no network, no browser; the sample profile (a Singapore citizen) and in-memory
variants of it; made-up names only.
Verify: python tests/run_tests.py -k always_a1_final_r10
"""
from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, consent_profile, is_stop, is_ticked, lie, pick_by, pick_faithful, profile_with, report, shown,
    what, _pf)

FACT = "profile:singapore_status."
CLASSES = ("ordinary", "work_right", "owner_fact", NO_CLASS)

# ------------------------------------------------------------------ helpers


def _opp(v):
    return "No" if v == "Yes" else "Yes"


def _field(label, tn="RADIO", required=True):
    return _pf("u", label, tn, required=required, options=YN if tn == "RADIO" else ())


def _go(label, value, klass, *, pick, prof=None, rk=None, tn="RADIO", required=True):
    ask = FakeAsk(lambda v: lie(value, klass), pick=pick, place="NONE")
    return attempt(_field(label, tn, required), ask, prof, rctx_kw=rk or {}), ask


def _src(res) -> str:
    return "" if is_stop(res) else str(res.source or "")


def _cites_status(res) -> bool:
    s = _src(res)
    return any(k in s for k in ("nationality", "residency_status", "work_pass", "singapore_status"))


def _trace(res) -> str:
    return "" if is_stop(res) else f"{res.evidence} {res.note}"


def _beh(res, ask):
    """What a field ends as, for a byte-for-byte comparison, plus how many calls it cost."""
    if is_stop(res):
        return ("STOP", res.reason.value, res.target_path, len(ask.picks), len(ask.place_calls))
    return (shown(res), _src(res), bool(res.assumed), str(res.evidence), len(ask.picks), len(ask.place_calls))


@contextlib.contextmanager
def _status_code_off():
    """The no-country status code disabled: `status_question` then finds nothing for a label that names no country."""
    from jobscraper.apply import always as AL
    real = AL._no_country_status
    AL._no_country_status = lambda *a, **k: None
    try:
        yield
    finally:
        AL._no_country_status = real


def _status_row(label, truth, prof=None, rk=None):
    """The whole D-226 contract for one plain wording whose truth is `truth`; the failing inputs (empty when it holds)."""
    bad = []
    wrong = _opp(truth)
    for klass in CLASSES:
        # right model: written, no further call, a profile fact, not assumed (a flipped confirmation would be wrong: none is asked)
        res, ask = _go(label, truth, klass, pick=pick_faithful(wrong, truth), prof=prof, rk=rk)
        if (is_stop(res) or shown(res) != truth or res.assumed or not _src(res).startswith(FACT) or ask.picks or ask.place_calls):
            bad.append((label[:44], klass, "right model", what(res), f"{len(ask.picks)} picks {len(ask.place_calls)} place"))
        # wrong model + a faithful confirmation: the truth, assumed, ONE call, a profile fact
        res, ask = _go(label, wrong, klass, pick=pick_faithful(truth, truth), prof=prof, rk=rk)
        if (is_stop(res) or shown(res) != truth or not res.assumed or not _src(res).startswith(FACT) or len(ask.picks) != 1):
            bad.append((label[:44], klass, f"wrong {wrong}, faithful confirmation", what(res), f"{len(ask.picks)} picks"))
        # wrong model + a confirmation that agrees with it: never the wrong value; ends empty after ONE call
        res, ask = _go(label, wrong, klass, pick=pick_faithful(wrong, truth), prof=prof, rk=rk)
        if is_stop(res) or shown(res) != "" or len(ask.picks) != 1:
            bad.append((label[:44], klass, f"wrong {wrong}, agreeing confirmation", what(res), f"{len(ask.picks)} picks"))
        # wrong model + an unusable confirmation: never the wrong value
        res, ask = _go(label, wrong, klass, pick=pick_by("", ""), prof=prof, rk=rk)
        if is_stop(res) or shown(res) == wrong:
            bad.append((label[:44], klass, f"wrong {wrong}, unusable confirmation", what(res)))
    return bad


# ================================================================== T1: the engineer's table, the sample citizen, an SG job

T1_ROWS = (    # (label, the sample citizen's truth)
    ("Are you a citizen or permanent resident?", "Yes"),
    ("Are you a citizen?", "Yes"),
    ("Are you a permanent resident?", "No"),
    ("Are you a PR?", "No"),
    ("Citizen or PR?", "Yes"),
    ("Are you a national of this country?", "Yes"),
    ("Do you hold citizenship or permanent residency?", "Yes"),
    ("Are you a non-citizen?", "No"),
    ("Are you a foreigner?", "No"),
    ("Are you a foreign national?", "No"),
)


def test_t1_a_plain_status_question_with_no_country_follows_the_profile_for_the_job_country_in_every_model_class():
    """D-226: 10 wordings x 4 model classes x {right, wrong} model, for the sample citizen on a Singapore job. The right answer is
    written with NO further call from a `profile:singapore_status.*` fact, not assumed; the wrong one is never written (one
    faithful confirmation -> the truth, assumed; an agreeing confirmation -> empty; unusable -> not the wrong value); never a stop."""
    bad = []
    for label, truth in T1_ROWS:
        bad += _status_row(label, truth)
    assert not bad, report(bad, 12)


def test_t1_the_sources_follow_the_ruling_citizen_wordings_cite_the_nationality_and_resident_wordings_the_residency_status():
    """D-226 (the engineer's table): the fact a right answer cites. A citizen / national / foreigner / non-citizen wording ->
    `nationality`; a permanent resident / PR / "citizen or PR" wording -> `residency_status`."""
    want = {"Are you a citizen?": "nationality", "Are you a national of this country?": "nationality",
            "Are you a non-citizen?": "nationality", "Are you a foreigner?": "nationality", "Are you a foreign national?": "nationality",
            "Are you a PR?": "residency_status", "Are you a permanent resident?": "residency_status",
            "Citizen or PR?": "residency_status", "Are you a citizen or permanent resident?": "residency_status",
            "Do you hold citizenship or permanent residency?": "residency_status"}
    bad = []
    for label, truth in T1_ROWS:
        res, ask = _go(label, truth, "ordinary", pick=pick_faithful(truth, truth))
        if is_stop(res) or not _src(res).endswith("." + want[label]):
            bad.append((label, want[label], what(res)))
    assert not bad, report(bad, 12)


def test_t1_here_and_of_this_country_keep_a_no_country_status_question_canonical():
    """D-226: "of this country" / "here" after the status words name the job's country, so the question stays canonical (the T1
    contract: no call for a right model)."""
    rows = (("Are you a citizen here?", "Yes"), ("Are you a permanent resident of this country?", "No"),
            ("Are you a foreign national here?", "No"), ("Are you a citizen of this country?", "Yes"))
    bad = []
    for label, truth in rows:
        bad += _status_row(label, truth)
    assert not bad, report(bad, 12)


def test_t1_furniture_and_adverbs_keep_the_truth_on_the_vote_path_never_the_wrong_value():
    """D-226 / D-224 3: "(Y/N)", "Please confirm whether", "currently", "still" and the sentence "I am a citizen" keep a no-country
    status question a STATUS question (the profile's fact is the source) but, as with a named country, they are not a canonical
    frame: the vote path. A right model ends with the truth (assumed); a wrong model ends with the truth or empty, never the wrong
    value; never a stop."""
    rows = (("Are you currently a citizen?", "Yes"), ("Please confirm whether you are a citizen (Y/N)", "Yes"),
            ("Are you still a permanent resident?", "No"), ("I am a citizen", "Yes"), ("Are you a citizen? (Y/N)", "Yes"))
    bad = []
    for label, truth in rows:
        wrong = _opp(truth)
        for klass in CLASSES:
            res, ask = _go(label, truth, klass, pick=pick_faithful(truth, truth))
            if is_stop(res) or shown(res) != truth or not _src(res).startswith(FACT):
                bad.append((label[:44], klass, "right model", what(res), len(ask.picks)))
            for pick in (pick_faithful(truth, truth), pick_faithful(wrong, truth), pick_by("", "")):
                res, ask = _go(label, wrong, klass, pick=pick)
                if is_stop(res) or shown(res) not in (truth, ""):
                    bad.append((label[:44], klass, "wrong model", what(res), len(ask.picks)))
    assert not bad, report(bad, 12)


# ================================================================== T2: other profiles and another job country

PR_PROF = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pr")
PASS_PROF = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="foreigner",
                         singapore_status__work_pass="ep")


def test_t2_a_permanent_resident_profile_answers_from_its_own_facts():
    """D-226 on a PR (in memory: nationality MY, residency `pr`): "Are you a citizen?" No; "Are you a PR?" Yes; "Citizen or PR?" Yes;
    "Are you a foreigner?" Yes (a PR is a foreigner: not a citizen of that country); the same contract as T1."""
    rows = (("Are you a citizen?", "No"), ("Are you a PR?", "Yes"), ("Citizen or PR?", "Yes"), ("Are you a foreigner?", "Yes"),
            ("Are you a citizen or permanent resident?", "Yes"), ("Are you a non-citizen?", "Yes"), ("Are you a foreign national?", "Yes"),
            ("Are you a permanent resident?", "Yes"))
    bad = []
    for label, truth in rows:
        bad += _status_row(label, truth, PR_PROF)
    assert not bad, report(bad, 12)


def test_t2_a_work_pass_holder_is_neither_citizen_nor_pr_and_is_a_foreigner():
    """D-226 on a pass holder (in memory: nationality MY, residency `foreigner`, work pass `ep`): "Citizen or PR?" No; "Are you a
    foreigner?" Yes; "Are you a citizen?" No; "Are you a PR?" No."""
    rows = (("Citizen or PR?", "No"), ("Are you a foreigner?", "Yes"), ("Are you a citizen?", "No"), ("Are you a PR?", "No"),
            ("Are you a citizen or permanent resident?", "No"), ("Are you a foreign national?", "Yes"))
    bad = []
    for label, truth in rows:
        bad += _status_row(label, truth, PASS_PROF)
    assert not bad, report(bad, 12)


def test_t2_a_job_in_another_country_asks_about_that_country_so_the_singapore_citizen_is_a_foreigner_there():
    """D-226: the question is about the JOB'S country. With the job in the US the sample (a Singapore citizen) answers "Are you a
    citizen?" No and "Are you a foreigner?" Yes, "Are you a non-citizen?" Yes, "Are you a national of this country?" No."""
    rows = (("Are you a citizen?", "No"), ("Are you a foreigner?", "Yes"), ("Are you a non-citizen?", "Yes"),
            ("Are you a national of this country?", "No"), ("Are you a foreign national?", "Yes"))
    bad = []
    for label, truth in rows:
        bad += _status_row(label, truth, rk={"job_country": "US"})
    assert not bad, report(bad, 12)


def test_t2_the_same_questions_in_singapore_stay_as_in_t1_with_the_job_country_unset_to_the_default():
    """Control for T2: a job in Singapore gives the citizen's answers (the US rows above are the only difference)."""
    bad = []
    for label, truth in (("Are you a citizen?", "Yes"), ("Are you a foreigner?", "No")):
        bad += _status_row(label, truth, rk={"job_country": "SG"})
    assert not bad, report(bad, 12)


# ================================================================== T3: a work pass with no country

T3_LABELS = ("Do you hold a work pass?", "Do you hold an Employment Pass?", "Do you hold an S Pass?")


def test_t3_a_work_pass_question_with_no_country_is_no_for_the_citizen_and_a_model_yes_is_never_written():
    """D-226: there is no work-pass frame, so "Do you hold a work pass / an Employment Pass / an S Pass?" stays on the VOTE path:
    "No" for the sample citizen from `profile:singapore_status.work_pass`, assumed True; a model "Yes" is never written (a faithful
    confirmation gives "No"; a confirmation that sides with the model ends "No" or empty; an unusable one never "Yes"); a model "No"
    ends "No"; never a stop `owner_fact_missing`, whatever class the model names."""
    bad = []
    for label in T3_LABELS:
        for klass in CLASSES:
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("No", "No"))
            if is_stop(res) or shown(res) != "No" or _src(res) != FACT + "work_pass" or not res.assumed:
                bad.append((label, klass, "model Yes, faithful", what(res), len(ask.picks)))
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("Yes", "No"))
            if is_stop(res) or shown(res) not in ("No", ""):
                bad.append((label, klass, "model Yes, model-sided confirmation", what(res), len(ask.picks)))
            res, ask = _go(label, "Yes", klass, pick=pick_by("", ""))
            if is_stop(res) or shown(res) == "Yes":
                bad.append((label, klass, "model Yes, unusable confirmation", what(res), len(ask.picks)))
            res, ask = _go(label, "No", klass, pick=pick_faithful("No", "No"))
            if is_stop(res) or shown(res) != "No" or _src(res) != FACT + "work_pass" or not res.assumed:
                bad.append((label, klass, "model No", what(res), len(ask.picks)))
    assert not bad, report(bad, 12)


def test_t3_the_no_country_work_pass_row_costs_the_same_as_the_named_country_row():
    """D-226 (the engineer: "the 'Singapore work pass' row gives the same"): not a canonical frame, so the same value, source and
    cost as "Do you hold a Singapore work pass?"."""
    bad = []
    for klass in ("ordinary", "work_right", NO_CLASS):
        for val in ("Yes", "No"):
            a = _go("Do you hold a work pass?", val, klass, pick=pick_faithful("No", "No"))
            b = _go("Do you hold a Singapore work pass?", val, klass, pick=pick_faithful("No", "No"))
            if _beh(*a) != _beh(*b):
                bad.append((klass, val, _beh(*a), _beh(*b)))
    assert not bad, report(bad, 8)


# ================================================================== T4: a tail that qualifies the status is G3

def _facts_line(ask) -> str:
    return ask.picks[0][1] if ask.picks else ""


def test_t4_a_citizen_by_birth_has_no_code_truth_no_fact_is_cited_and_the_confirmation_carries_the_facts_line():
    """D-226 / D-223 G3: "Are you a citizen by birth?" -> the model plus ONE agreeing confirmation, assumed, source `assumption`,
    never a profile fact; the confirmation call is given the facts line ("Facts about the applicant: nationality ...; residency
    status ...") so the check can see them; a wrong model with a faithful reader is corrected through the meaning calls (3 picks)."""
    bad = []
    label = "Are you a citizen by birth?"
    for klass in ("ordinary", "work_right", NO_CLASS):
        res, ask = _go(label, "Yes", klass, pick=pick_faithful("Yes", "Yes"))
        if (is_stop(res) or shown(res) != "Yes" or not res.assumed or _src(res) != "assumption" or len(ask.picks) != 1
                or not _facts_line(ask).startswith("Facts about the applicant:")
                or "nationality Singapore" not in _facts_line(ask) or "citizen" not in _facts_line(ask)):
            bad.append((label, klass, "right model", what(res), _facts_line(ask)[:80]))
        res, ask = _go(label, "No", klass, pick=pick_faithful("Yes", "Yes"))
        if is_stop(res) or shown(res) not in ("Yes", "") or _cites_status(res):
            bad.append((label, klass, "wrong model", what(res)))
    assert not bad, report(bad, 8)


def test_t4_DEFECT_medium_have_you_been_a_pr_or_citizen_since_2020_with_no_country_is_written_with_no_check_at_all():
    """DEFECT (severity MEDIUM; pre-existing, not a regression, but the ruling names this wording): D-226 says a qualifying tail
    ("by birth", "since 2020") is G3: no fact cited, the confirmation is given the facts line. "Have you been a permanent resident
    since 2020?" has the same status residue, but "Have you been ..." is not a recognised lead (only "are you / you are / I am" and
    "do you hold / have"), so the question is NOT a status question at all: the model's answer is written with ZERO calls, assumed
    True, source `assumption`, no facts line. With a country named ("Have you been a Singapore permanent resident since 2020?") the
    same model answer costs one confirmation with the facts line. The over-claim of an immigration status the owner does not hold
    (the sample citizen is not a PR) goes to a form with no check. Reproduce: model answer Yes, class ordinary, sample profile.
    Expected (ruling): at least one confirmation whose WANTED carries the facts line, and a wrong model "Yes" never written for the
    citizen from the model alone. Actual: 0 picks, 'Yes' written (class ordinary / none); under class work_right the code instead answers 'No' from the unrelated
    `authorised_to_work` fact after 3 picks. The same for "Have you been a citizen since 2020?"."""
    bad = []
    for label in ("Have you been a permanent resident since 2020?", "Have you been a citizen since 2020?"):
        for klass in ("ordinary", "work_right", NO_CLASS):
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("No", "No"))
            if (not is_stop(res)) and (_cites_status(res) or not ask.picks or "Facts about the applicant:" not in _facts_line(ask)):
                bad.append((label, klass, what(res), f"{len(ask.picks)} picks"))
    assert not bad, report(bad, 8)


def test_t4_control_the_same_since_2020_wording_with_a_country_named_gets_a_confirmation_with_the_facts_line():
    """Control for the DEFECT above (green today): "Have you been a Singapore permanent resident since 2020?" is G3: one or more
    confirmation calls, the facts line, no fact cited as the source."""
    bad = []
    label = "Have you been a Singapore permanent resident since 2020?"
    for klass in ("ordinary", "work_right", NO_CLASS):
        res, ask = _go(label, "Yes", klass, pick=pick_faithful("No", "No"))
        if (not is_stop(res)) and (_cites_status(res) or not ask.picks or "Facts about the applicant:" not in _facts_line(ask)):
            bad.append((label, klass, what(res), f"{len(ask.picks)} picks"))
    assert not bad, report(bad, 8)


def test_t4_a_g3_wording_with_the_owner_fact_class_ends_as_the_same_wording_with_singapore_named():
    """D-226 (the engineer's table, owner_fact column): a model that names `owner_fact` for "Are you a citizen by birth?" gets the
    same outcome as for "Are you a Singapore citizen by birth?" (the existing D-223 G3 row: a STOP `owner_fact_missing`), for either
    model answer: the no-country wording adds no new way to end."""
    bad = []
    for val in ("Yes", "No"):
        a = _go("Are you a citizen by birth?", val, "owner_fact", pick=pick_faithful("Yes", "Yes"))
        b = _go("Are you a Singapore citizen by birth?", val, "owner_fact", pick=pick_faithful("Yes", "Yes"))
        if _beh(*a) != _beh(*b):
            bad.append((val, _beh(*a), _beh(*b)))
    assert not bad, report(bad, 8)


# ================================================================== T5: precedence

def test_t5_a_consent_box_that_starts_with_a_status_phrase_is_decided_by_the_consent_not_by_the_nationality():
    """D-226 precedence: "I am a citizen and agree to receive job alerts" is a marketing consent. With the four consents false it is
    not ticked (a REQUIRED one is not ticked either: marketing never stops), with them true it is ticked, under every class the model
    names, and NEVER from the nationality fact; it ends exactly as "I agree to receive job alerts"."""
    bad = []
    label, plain = "I am a citizen and agree to receive job alerts", "I agree to receive job alerts"
    for kind in ("false", "true"):
        prof = consent_profile(kind)
        for klass in ("marketing", "ordinary", "work_right", "owner_fact", NO_CLASS):
            for required in (False, True):
                outs = []
                for lab in (label, plain):
                    ask = FakeAsk(lambda v, k=klass: lie("true", k), pick=pick_by("yes", "no"), place="NONE")
                    res = attempt(_field(lab, "CHECKBOX", required), ask, prof)
                    outs.append((res, ask))
                res = outs[0][0]
                if _beh(*outs[0]) != _beh(*outs[1]) or _cites_status(res):
                    bad.append((kind, klass, required, "differs from the plain label or cites a status fact", what(res)))
                if kind == "false" and is_ticked(res):
                    bad.append((kind, klass, required, "ticked with consents false", what(res)))
                if kind == "true" and not is_ticked(res):
                    bad.append((kind, klass, required, "not ticked with consents true", what(res)))
    assert not bad, report(bad, 10)


def test_t5_a_question_about_someone_else_is_never_answered_from_the_applicants_status():
    """D-226 precedence: "Is your spouse a citizen?" and "Are your parents permanent residents?" are about another person: never the
    applicant's nationality / residency fact, and they end exactly as the same sentence with a neutral noun ("... a nurse?" /
    "... teachers?"), under every class the model names and either model answer."""
    bad = []
    for label, plain in (("Is your spouse a citizen?", "Is your spouse a nurse?"),
                         ("Are your parents permanent residents?", "Are your parents teachers?")):
        for klass in ("other_person", "ordinary", "work_right", "owner_fact", NO_CLASS):
            for val in ("Yes", "No"):
                outs = [_go(lab, val, klass, pick=pick_by("yes", "no")) for lab in (label, plain)]
                if _beh(*outs[0]) != _beh(*outs[1]) or _cites_status(outs[0][0]):
                    bad.append((label[:40], klass, val, what(outs[0][0]), "vs plain", what(outs[1][0])))
    assert not bad, report(bad, 10)


def test_t5_national_service_as_a_citizen_is_the_national_service_question_not_a_status_question():
    """D-226 precedence: "Have you completed National Service as a citizen?" ends exactly as "Have you completed National Service?"
    (the National Service key), never from the nationality / residency fact, under every class and either model answer."""
    bad = []
    label, plain = "Have you completed National Service as a citizen?", "Have you completed National Service?"
    for klass in ("declaration", "ordinary", "work_right", "owner_fact", NO_CLASS):
        for val in ("Yes", "No"):
            for pick in (pick_faithful("Yes", "Yes"), pick_faithful("No", "No")):
                outs = [_go(lab, val, klass, pick=pick) for lab in (label, plain)]
                if _beh(*outs[0]) != _beh(*outs[1]) or (_cites_status(outs[0][0]) and "ns_status" not in _src(outs[0][0])):
                    bad.append((klass, val, what(outs[0][0]), "vs plain", what(outs[1][0])))
    assert not bad, report(bad, 10)


# ================================================================== T6: non-status uses of the same words

NON_STATUS_12 = (
    "Are you a senior citizen?", "Are you a citizen developer?", "Do you support corporate citizenship?", "Are you a good citizen?",
    "Have you worked with our Citizen Services team?", "Are you a global citizen?", "Are you a Citizen Bank customer?",
    "Do you use the Citizen app?", "Do you have a Citizen account?", "Are you a citizen scientist volunteer?",
    "I am a senior citizen", "Is Citizen your current employer?")
FOOLING_8 = (    # mine: each tries to look like "(are you) a <status word>" with something else after it
    "Are you a citizen of the world?", "Are you a citizen journalist?", "Do you hold a Citizen credit card?",
    "Are you a resident physician?", "Are you a permanent employee?", "Are you a PR professional?",
    "Do you have PR experience?", "Are you a national sales manager?")


def _non_status_bad(labels, *, with_equality=True):
    bad = []
    for label in labels:
        for tn, vals in (("RADIO", ("Yes", "No")), ("CHECKBOX", ("true",))):
            for klass in CLASSES:
                for val in vals:
                    res, ask = _go(label, val, klass, pick=pick_by("yes", "no"), tn=tn)
                    if with_equality:
                        with _status_code_off():
                            off = _go(label, val, klass, pick=pick_by("yes", "no"), tn=tn)
                        if _beh(res, ask) != _beh(*off):
                            bad.append((label[:44], tn, klass, val, "differs from status-code-off", _beh(res, ask)[:3], _beh(*off)[:3]))
                    if not is_stop(res) and (_cites_status(res) or "work_right:status" in _trace(res)):
                        bad.append((label[:44], tn, klass, val, "answered from a status fact", what(res)))
    return bad


def test_t6_control_the_status_code_off_switch_really_changes_a_true_status_question():
    """Control for the T6 comparisons (they would pass vacuously if the switch did nothing): with `_no_country_status` disabled
    "Are you a citizen?" no longer ends as the canonical profile answer (a right model costs a call and is not written from the
    fact with no check), so the equality in the two tests below is a real comparison."""
    on = _go("Are you a citizen?", "Yes", "ordinary", pick=pick_faithful("Yes", "Yes"))
    with _status_code_off():
        off = _go("Are you a citizen?", "Yes", "ordinary", pick=pick_faithful("Yes", "Yes"))
    assert _beh(*on) != _beh(*off), (_beh(*on), _beh(*off))
    assert not on[1].picks and not on[0].assumed and off[0].assumed, (what(on[0]), what(off[0]))


def test_t6_the_twelve_non_status_uses_of_citizen_behave_exactly_as_with_the_status_code_disabled():
    """D-226 guard (the engineer's list): "senior citizen", "citizen developer", "corporate citizenship", "good citizen", "Citizen
    Services team", "global citizen", "Citizen Bank customer", "Citizen app", "Citizen account", "citizen scientist", "I am a senior
    citizen", "Is Citizen your current employer?", each as a radio and as a tick box, under four model classes: the outcome (value,
    source, assumed flag, evidence, number of confirmation and place calls) is identical with `_no_country_status` disabled, and no
    status fact is ever the source."""
    bad = _non_status_bad(NON_STATUS_12)
    assert not bad, report(bad, 12)


def test_t6_eight_more_labels_that_try_to_fool_the_predicate_rule_are_not_answered_from_the_status_facts():
    """D-226 guard (mine): "citizen of the world", "citizen journalist", "Citizen credit card", "resident physician", "permanent
    employee", "PR professional", "PR experience", "national sales manager": radio and tick box, four classes: never answered from
    the nationality / residency / work-pass fact and identical to the status-code-disabled outcome."""
    bad = _non_status_bad(FOOLING_8)
    assert not bad, report(bad, 12)


def test_t6_a_non_status_label_is_never_a_work_rights_or_status_stop_for_the_citizen():
    """D-226 guard: no label of the two lists ends as a STOP `owner_fact_missing` for a class the model names other than
    `owner_fact`, and none ends as a stop of any kind with class `ordinary` (the status code adds no new stop)."""
    bad = []
    for label in NON_STATUS_12 + FOOLING_8:
        for tn, val in (("RADIO", "Yes"), ("CHECKBOX", "true")):
            res, ask = _go(label, val, "ordinary", pick=pick_by("yes", "no"), tn=tn)
            with _status_code_off():
                off = _go(label, val, "ordinary", pick=pick_by("yes", "no"), tn=tn)
            if is_stop(res) and not is_stop(off[0]):
                bad.append((label[:44], tn, what(res)))
    assert not bad, report(bad, 8)


# ------------------------------------------------------------------ a tick box is a status statement only when its whole label is

def _box_faithful():
    """A scripted `pick` for a status TICK BOX that reads like a faithful reader: the confirmation says "yes" when it states the
    applicant IS what the box says; the meaning call says "yes" exactly when the value asked about states what the question says."""
    def pick(q, w, o):
        w = str(w)
        if w.startswith("If the applicant answers"):
            ticked = re.search(r"answers .(ticked|unticked).", w).group(1) == "ticked"
            claims_not = "state that the applicant is not" in w or "state that the applicant does not" in w
            return "yes" if claims_not == (not ticked) else "no"
        return "no" if w.startswith("The applicant is not") or w.startswith("The applicant does not") else "yes"
    return pick


def test_t6_a_tick_box_whose_whole_label_is_a_plain_status_statement_follows_the_facts():
    """D-226 / G1: "I am a citizen" as a tick box is ticked for the sample citizen and NOT ticked for a PR (in memory) or a pass
    holder, under every class the model names (the model says tick); "I am a permanent resident" the other way round for the
    citizen."""
    bad = []
    rows = (("I am a citizen", None, True), ("I am a citizen", PR_PROF, False), ("I am a citizen", PASS_PROF, False),
            ("I am a permanent resident", None, False), ("I am a permanent resident", PR_PROF, True))
    for label, prof, want in rows:
        for klass in CLASSES:
            res, ask = _go(label, "true", klass, pick=_box_faithful(), prof=prof, tn="CHECKBOX")
            ticked = (not is_stop(res)) and is_ticked(res)
            if is_stop(res) or ticked is not want:
                bad.append((label, "PR" if prof is PR_PROF else "pass" if prof is PASS_PROF else "citizen", klass,
                            "want ticked" if want else "want unticked", what(res)))
    assert not bad, report(bad, 10)
