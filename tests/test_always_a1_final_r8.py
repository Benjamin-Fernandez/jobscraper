"""Q-121 Amendment A1, the REPLAY round: the always-answer filler's place call (D-220 / D-221) against what the REAL local model
(qwen3:14b, the exact prompt of `always.place_call`) was seen to reply, plus the Coordinator's ruling D-222 (S1) and the keep-on-file
retention follow-up.

SOURCE OF THE REPLIES: `tests/fixtures/apply/place_replies_qwen3_14b.json` (label -> the model's quote, or "NONE"), recorded by the
Coordinator on 2026-11-15 from a real-model run (qwen3:14b via Ollama); this file only REPLAYS them, it never calls a model. The
replay fake (`ReplayAsk`) answers the place call FROM THE FIXTURE for these labels and FAILS THE TEST LOUDLY (`ask.check()`) when a
place call arrives for a label that is neither in the fixture nor scripted by the row; the miss is recorded, not raised inside the
filler, so a broad `except` in the code cannot hide it.

RED UNTIL the engineer's D-222 commit on `eng/Q-121-A1-fix1` (measured at int/Q-121 735a446; each failure line names the row):
  S1   test_s1_*                           a status word (citizen, PR, work pass ...) after the job country's name is no place of work
  S1   test_s1_work_pass_that_ties_you...  the NONE reply for "... Singapore work pass that ties you ..." ends with the place note
  KEEP test_keep_on_file_*_model_says_false  the box ticked from `consents.data_retention_consent` when the model says false
  FOLLOW test_replay_followers_*           "Singapore permanently" / "under an Employment Pass" (the engineer's followers commit;
                                           overlaps r7 `test_durations_and_ordinary_followers_keep_singapores_facts`)
GREEN TODAY (guards and the real replies that already end right): the foreign-status guards, the five "in Singapore" labels, the pure
"country where this role is based" / "in which you are applying" / "international student" rows, the five US labels (EMPTY with the place
note: an ACCEPTED LIMIT, pinned as it is), "your home country", "outside Singapore", "Singapore's neighbouring countries".

Fakes only: no model, no network, no browser; sample profile (`tests/fixtures/apply/applicant.sample.yaml`: a Singapore citizen,
authorised in SG and not in the US, sponsorship not needed in SG, retention consent true, talent-pool opt-in false); made-up names only.
Verify: python tests/run_tests.py -k always_a1_final_r8
"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, pick_by, pick_faithful, profile_with, report, say, shown, what, _pf)

NOTE = "place not recognised"
FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "apply" / "place_replies_qwen3_14b.json")
                     .read_text(encoding="utf-8"))


def _f(label, *, required=True, options=YN, key="u"):
    return _pf(key, label, "RADIO", required=required, options=options)


def _box(label):
    return _pf("b", label, "CHECKBOX", required=False)


def _note(res) -> str:
    return "" if is_stop(res) else f"{res.note} {res.evidence}"


def _src(res) -> str:
    return "" if is_stop(res) else str(res.source or "")


def _opp(v):
    return "No" if v == "Yes" else "Yes"


class ReplayAsk(FakeAsk):
    """`FakeAsk` whose place call is answered from the recorded real-model replies. `scripted`: None (the fixture only), a dict
    label -> reply (overrides the fixture), or a str (that reply for every label: an explicit script). A label in neither is
    recorded in `unscripted` and `check()` fails the test."""

    def __init__(self, answer=None, *, pick=None, scripted=None, **kw):
        self.scripted = scripted
        self.unscripted: list[str] = []
        super().__init__(answer, pick=pick, place=self._reply, **kw)

    def _reply(self, label):
        if isinstance(self.scripted, str):
            return self.scripted
        if isinstance(self.scripted, dict) and label in self.scripted:
            return self.scripted[label]
        if label in FIXTURE:
            return FIXTURE[label]
        self.unscripted.append(label)
        return "NONE"

    def check(self):
        assert not self.unscripted, f"a place call arrived for a label that is not in the fixture and not scripted: {self.unscripted}"


def _go(label, value, klass, *, pick=None, scripted=None, profile=None, options=YN):
    """One attempt: a model that answers `value` under class `klass`; returns (result, ask) after the replay check."""
    ask = ReplayAsk(lambda v: lie(value, klass), pick=pick or pick_faithful(value, value), scripted=scripted)
    res = attempt(_f(label, options=options), ask, profile)
    ask.check()
    return res, ask


@contextlib.contextmanager
def code_key(mode):
    """`natural` = the code's own key; `none` = code finds no class; `work_right` = code names work_right (confident)."""
    from jobscraper.apply import always as AL
    if mode == "natural":
        yield
        return
    real = AL.code_key_full
    key = AL.CodeKey() if mode == "none" else AL.CodeKey(AL.FC.WORK_RIGHT, confident=True)
    AL.code_key_full = lambda pf, ctx, standing=None: key
    try:
        yield
    finally:
        AL.code_key_full = real


# ================================================================== the fixture itself

def test_the_fixture_is_the_recorded_table_of_24_real_replies():
    assert len(FIXTURE) == 24 and all(isinstance(k, str) and isinstance(v, str) and v for k, v in FIXTURE.items())
    assert FIXTURE["Are you a Singapore citizen?"] == "NONE"
    assert FIXTURE["Are you authorised to work in your home country?"] == "your home country"


def test_the_replay_fake_fails_loudly_on_a_label_that_is_not_in_the_fixture():
    """The replay discipline itself: an unscripted label is recorded and `check()` raises (a row can script it)."""
    ask = ReplayAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"))
    attempt(_f("Are you allowed to work in Singapore on a full-time basis?"), ask)
    assert ask.unscripted == ["Are you allowed to work in Singapore on a full-time basis?"] and ask.place_calls
    try:
        ask.check()
    except AssertionError:
        pass
    else:
        raise AssertionError("check() did not fail on an unscripted place call")
    ask = ReplayAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("Yes", "Yes"), scripted={"Are you allowed to work in Singapore on a full-time basis?": "Atlantis"})
    attempt(_f("Are you allowed to work in Singapore on a full-time basis?"), ask)
    ask.check()


# ================================================================== item 1: D-222 S1, a status word names no place of work

S1_CITIZEN = ("Are you a Singapore citizen?", "Are you a Singapore Citizen or Permanent Resident?", "Are you a Singaporean or Singapore PR?")
S1_CLASSES = ("work_right", "owner_fact", "ordinary", NO_CLASS)
CODE_KEYS = ("natural", "none", "work_right")


def test_s1_a_singapore_status_question_is_answered_yes_with_no_place_call():
    """D-222 S1 (RED until the fix): "Are you a Singapore citizen?" / "... Citizen or Permanent Resident?" / "Are you a Singaporean or
    Singapore PR?" on a Singapore job, the sample profile a Singapore citizen: a right model "Yes" is written with ZERO place calls and
    no place note, under every model class (work_right, owner_fact, ordinary, none) and with the code's own key, no code key, and a
    code key work_right (the real rehearsal row: model class work_right, no code key, ended EMPTY with the note)."""
    bad = []
    for label in S1_CITIZEN:
        for mode in CODE_KEYS:
            for klass in S1_CLASSES:
                with code_key(mode):
                    res, ask = _go(label, "Yes", klass)
                if is_stop(res) or shown(res) != "Yes" or ask.place_calls or NOTE in _note(res):
                    bad.append((label[:50], f"key={mode}", f"class={klass}", what(res), f"{len(ask.place_calls)} place calls"))
    assert not bad, report(bad, 12)


def test_s1_a_wrong_model_no_is_never_written_for_a_singapore_status_question():
    """D-222 S1 (RED until the fix): the same three labels, a WRONG model "No" (a confirmation that sides with it or with the truth,
    faithful meaning calls): "No" is never written; the right value or empty. Every class, every key."""
    bad = []
    for label in S1_CITIZEN:
        for mode in CODE_KEYS:
            for klass in S1_CLASSES:
                for pick in (pick_faithful("No", "Yes"), pick_faithful("Yes", "Yes"), pick_by("No", "yes")):
                    with code_key(mode):
                        res, ask = _go(label, "No", klass, pick=pick)
                    if is_stop(res) or shown(res) not in ("Yes", ""):
                        bad.append((label[:50], f"key={mode}", f"class={klass}", what(res)))
    assert not bad, report(bad, 12)


def test_s1_work_pass_that_ties_you_to_one_employer_is_never_the_place_note_and_never_yes():
    """D-222 S1 (RED until the fix): "Do you hold a Singapore work pass that ties you to one employer?" (the real reply to the one
    place call is NONE): never the note "place not recognised"; the outcome is the truth for a citizen ("No") or empty after the votes,
    never "Yes". A right model "No" ends "No" or empty; a wrong model "Yes" ends "No" or empty."""
    label = "Do you hold a Singapore work pass that ties you to one employer?"
    bad = []
    for klass in ("work_right", "ordinary", NO_CLASS):
        for value in ("No", "Yes"):
            for pick in (pick_faithful(value, "No"), pick_faithful("No", "No")):
                res, ask = _go(label, value, klass, pick=pick)
                if is_stop(res) or NOTE in _note(res) or shown(res) not in ("No", "") or len(ask.place_calls) > 1:
                    bad.append((klass, f"model {value}", what(res), len(ask.place_calls)))
    assert not bad, report(bad, 12)


def test_s1_a_valid_singapore_work_pass_question_makes_no_place_call():
    """D-222 S1 (expected GREEN today): "Do you currently hold a valid Singapore work pass?" has no place call (the job country's
    adjective on a status word). Only the call count is pinned (see the outbox on what is written)."""
    bad = []
    for klass in ("work_right", "ordinary", NO_CLASS):
        for value in ("Yes", "No"):
            res, ask = _go("Do you currently hold a valid Singapore work pass?", value, klass, pick=pick_faithful(value, "No"))
            if ask.place_calls or NOTE in _note(res):
                bad.append((klass, value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


# ================================================================== item 2: guards, another country's status is not the job country

FOREIGN = ("Are you a US citizen?", "Are you a Malaysian citizen or PR?", "Do you hold a UK visa?", "Are you a citizen of the United States?")


WORK_RIGHTS_ROWS = ("authorised_to_work", "requires_sponsorship", "residency_status", "work_pass")   # Singapore-only work-rights facts


def test_guard_another_countrys_status_is_never_answered_from_a_singapore_work_rights_row():
    """GUARD (must hold before and after D-222 S2): "Are you a US citizen?" / "Are you a Malaysian citizen or PR?" / "Do you hold a UK
    visa?" / "Are you a citizen of the United States?" on a Singapore job: whatever the model's class, value and confirmation, the
    answer's source, evidence and note never name a Singapore WORK-RIGHTS row (`authorised_to_work.SG`, `requires_sponsorship`, the
    residency row used as a work right, the work pass). The owner's `nationality` fact IS the right source for "not a US citizen" and is
    allowed. Narrowed from the substring "singapore_status" (D-222 S2 ruling): the purpose is unchanged."""
    bad = []
    for label in FOREIGN:
        for klass in ("work_right", "sponsorship", "ordinary", NO_CLASS):
            for value in ("Yes", "No"):
                for pick in (pick_faithful(value, "No"), pick_faithful("No", "No")):
                    res, ask = _go(label, value, klass, pick=pick, scripted="NONE")
                    low = _src(res) + " " + _note(res)
                    if any(row in low for row in WORK_RIGHTS_ROWS) or len(ask.place_calls) > 1:
                        bad.append((label[:44], klass, value, what(res)))
    assert not bad, report(bad, 12)


def test_guard_another_countrys_status_is_no_from_the_owners_facts_under_every_class_with_no_place_call():
    """D-222 S2 (the deliberate flip of the former as-it-is pin): "Are you a US citizen?", "Are you a Malaysian citizen or PR?", "Are
    you a citizen of the United States?" -> "No" for the sample profile (a Singapore citizen), and "Do you hold a UK visa?" -> "No", with
    NO place call, under every model class (work_right, sponsorship, ordinary, none). A model "Yes" whose confirmation states the truth is
    never written: the answer is "No" with the source the nationality fact (the UK visa: `default:status_not_held`); a confirmation that
    sides with the wrong model ends "No" or empty, never "Yes"; a right model "No" ends "No"."""
    bad = []
    for label in FOREIGN:
        src = "default:status_not_held" if "visa" in label else "profile:singapore_status.nationality"
        for klass in ("work_right", "sponsorship", "ordinary", NO_CLASS):
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("No", "No"), scripted="NONE")      # wrong model, truthful check
            if is_stop(res) or shown(res) != "No" or _src(res) != src or ask.place_calls:
                bad.append((label[:44], klass, "model Yes, truthful check", what(res), len(ask.place_calls)))
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("Yes", "No"), scripted="NONE")     # wrong model, check sides with it
            if is_stop(res) or shown(res) not in ("No", "") or ask.place_calls:
                bad.append((label[:44], klass, "model Yes, model-sided check", what(res), len(ask.place_calls)))
            res, ask = _go(label, "No", klass, pick=pick_faithful("No", "No"), scripted="NONE")       # right model
            if is_stop(res) or shown(res) != "No" or ask.place_calls:
                bad.append((label[:44], klass, "model No", what(res), len(ask.place_calls)))
    assert not bad, report(bad, 12)


def test_guard_a_singapore_citizen_working_in_malaysia_ends_empty_with_the_note():
    """GUARD: "Are you a Singapore citizen working in Malaysia?" names another place of work: EMPTY with the place note under the
    class work_right, whatever the value, the confirmation and the place reply (NONE: code finds "Malaysia"; "Malaysia": not the job
    country; "Singapore": a lying model)."""
    bad = []
    label = "Are you a Singapore citizen working in Malaysia?"
    for reply in ("NONE", "Malaysia", "Singapore"):
        for value in ("Yes", "No"):
            for pick in (pick_faithful(value, "Yes"), pick_faithful("Yes", "Yes")):
                res, ask = _go(label, value, "work_right", pick=pick, scripted=reply)
                if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                    bad.append((reply, value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


# ================================================================== item 3: the other real replies, as they must end

IN_SG = (   # (label, class, the sample profile's truth for a Singapore job)
    ("Are you legally authorised to work in Singapore on a full-time basis?", "work_right", "Yes"),
    ("Are you eligible to work in Singapore without employer sponsorship?", "work_right", "Yes"),
    ("Do you have the unrestricted right to work in Singapore?", "work_right", "Yes"),
    ("Are you currently authorised to work in Singapore for any employer?", "work_right", "Yes"),
    ("Will you require a work visa to take up employment in Singapore?", "sponsorship", "No"),
)
PURE_SG = (  # the job country with no (or a long) quote: Singapore's facts
    ("Do you have the right to work in the country where this role is based?", "work_right", "Yes"),
    ("Are you legally authorized to work in the country in which you are applying?", "work_right", "Yes"),
    ("Do you require sponsorship as an international student?", "sponsorship", "No"),
    ("Your work authorisation status in Singapore", "work_right", "Yes"),
)
US_LABELS = (
    "Are you legally authorised to work in the US?",
    "Is your right to work in the United States limited in any way?",
    "Your work authorisation status in the United States",
    "Do you have any restrictions on your right to work in the US?",
    "Do you have any restrictions on your right to work in the USA?",
)


def _truth_rows(rows, test):
    """For each row: a right model writes the truth; a wrong model (the opposite, a confirmation that sides with it, faithful meaning
    calls) never writes the opposite."""
    bad = []
    for label, klass, truth in rows:
        res, ask = _go(label, truth, klass, pick=pick_faithful(truth, truth))
        if is_stop(res) or shown(res) != truth or NOTE in _note(res) or len(ask.place_calls) > 1:
            bad.append((label[:60], "right model", what(res), len(ask.place_calls)))
        res, ask = _go(label, _opp(truth), klass, pick=pick_faithful(_opp(truth), truth))
        if shown(res) == _opp(truth):
            bad.append((label[:60], "wrong model", what(res), len(ask.place_calls)))
    return bad


def test_replay_the_five_in_singapore_labels_with_the_quote_singapore_use_singapores_facts():
    """The five non-pure "... in Singapore ..." labels, the real reply "Singapore": Singapore's facts (authorised "Yes", needs no
    sponsorship "No"), at most one place call; a wrong model's opposite is never written."""
    bad = _truth_rows(IN_SG, "in_sg")
    assert not bad, report(bad)


def test_replay_country_where_the_role_is_based_applying_in_and_international_student_use_singapores_facts():
    """"the country where this role is based" (NONE, pure), "the country in which you are applying" (the long quote), "as an
    international student" (NONE) and "Your work authorisation status in Singapore": Singapore's facts."""
    bad = _truth_rows(PURE_SG, "pure")
    assert not bad, report(bad)


def test_replay_the_five_us_labels_with_the_real_reply_none_end_empty_with_the_note_never_a_singapore_value():
    """ACCEPTED LIMIT, pinned as it IS: the five US / United States labels with the real reply NONE end EMPTY with the place note (the
    model did not quote "US" / "United States", and code reading another country vetoes NONE); never a Singapore-based value, under
    the class work_right / ordinary / none, value Yes or No, either confirmation."""
    bad = []
    for label in US_LABELS:
        for klass in ("work_right", "ordinary", NO_CLASS):
            for value in ("Yes", "No"):
                for pick in (pick_faithful(value, "Yes"), pick_faithful(_opp(value), "Yes")):
                    res, ask = _go(label, value, klass, pick=pick)
                    if is_stop(res) or shown(res) != "" or NOTE not in _note(res) or "singapore_status" in _src(res):
                        bad.append((label[:56], klass, value, what(res), len(ask.place_calls)))
    assert not bad, report(bad, 12)


def test_replay_followers_singapore_permanently_and_under_an_employment_pass_use_singapores_facts():
    """RED UNTIL the engineer's followers commit (D-221 L5: ordinary prepositions and time adverbs after a quoted place): "Are you
    authorised to work in Singapore permanently?" and "Are you able to work in Singapore under an Employment Pass?" with the real
    reply "Singapore": Singapore's facts, "Yes" for a right model. Overlaps r7 `test_durations_and_ordinary_followers_keep_singapores_
    facts` (one row each here)."""
    bad = []
    for label in ("Are you authorised to work in Singapore permanently?", "Are you able to work in Singapore under an Employment Pass?"):
        res, ask = _go(label, "Yes", "work_right")
        if is_stop(res) or shown(res) != "Yes" or NOTE in _note(res) or len(ask.place_calls) > 1:
            bad.append((label[:62], what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_replay_your_home_country_ends_empty_with_the_place_note():
    """"Are you authorised to work in your home country?": the real reply quotes "your home country" (not a country name): EMPTY with
    the place note, whatever the value and the confirmation. NOTE: GREEN at 735a446 with the real reply (the red r7 row uses the
    fake's sensible quote NONE, under which code finds no place word)."""
    bad = []
    for value in ("Yes", "No"):
        for pick in (pick_faithful(value, "Yes"), pick_faithful("Yes", "Yes")):
            res, ask = _go("Are you authorised to work in your home country?", value, "work_right", pick=pick)
            if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                bad.append((value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


def test_replay_outside_singapore_and_neighbouring_countries_end_empty():
    """"Are you legally authorised to work outside Singapore?" (the real quote "outside Singapore") and "... Singapore's neighbouring
    countries?" (the quote is the whole phrase, not a country): EMPTY, whatever the value and the confirmation."""
    bad = []
    for label in ("Are you legally authorised to work outside Singapore?", "Are you authorised to work in Singapore's neighbouring countries?"):
        for value in ("Yes", "No"):
            for pick in (pick_faithful(value, "Yes"), pick_faithful("Yes", "Yes")):
                res, ask = _go(label, value, "work_right", pick=pick)
                if is_stop(res) or shown(res) != "" or NOTE not in _note(res):
                    bad.append((label[:56], value, what(res), len(ask.place_calls)))
    assert not bad, report(bad)


# ================================================================== item 4: keep on file, a model that says FALSE (the real model did)

KEEP_LABELS = ("Keep my application on file for future roles", "Retain my CV for up to 2 years for other vacancies")


def _keep(label, said, prof, klass="consent_retention", basis="none"):
    """The real model's reply to an optional keep-on-file box: `basis` "none" (the prompt's rule 5), value `said`."""
    ask = FakeAsk(lambda v: say(said, basis, "", False, "none", klass=klass), pick=pick_by("", ""))
    return attempt(_box(label), ask, prof)


def test_keep_on_file_is_ticked_from_the_retention_consent_when_the_model_says_false():
    """RED UNTIL the engineer's fix (today: unticked with the note "optional: nothing in the briefing"): "Keep my application on file
    for future roles" and "Retain my CV for up to 2 years for other vacancies", the model class consent_retention with the value
    false (what the real model replied), the profile's `consents.data_retention_consent` true and talent pool false: TICKED."""
    prof = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    bad = []
    for label in KEEP_LABELS:
        for klass in ("consent_retention", "ordinary", NO_CLASS):
            for basis in ("none", "assumption"):
                res = _keep(label, "false", prof, klass, basis)
                if is_stop(res) or not is_ticked(res):
                    bad.append((label[:50], klass, f"basis {basis}", what(res)))
    assert not bad, report(bad)


def test_keep_on_file_stays_unticked_when_the_retention_consent_is_false():
    """With `consents.data_retention_consent` false the same two boxes are NOT ticked, whatever the model says (true or false) and
    the talent-pool opt-in."""
    bad = []
    for label in KEEP_LABELS:
        for pool in (False, True):
            prof = profile_with(consents__data_retention_consent=False, consents__talent_pool_opt_in=pool)
            for said in ("true", "false"):
                res = _keep(label, said, prof)
                if is_stop(res) or is_ticked(res):
                    bad.append((label[:50], f"pool={pool}", said, what(res)))
    assert not bad, report(bad)


def test_keep_on_file_with_a_residue_wording_is_unticked_without_the_talent_pool_even_when_the_model_says_true():
    """REGRESSION GUARD: "Keep my application on file ... and email me about similar roles" is a contact on top of retention, so the
    truth is retention AND talent_pool_opt_in: with the model saying TRUE and talent_pool_opt_in false the box is NOT ticked (retention
    consent true)."""
    prof = profile_with(consents__data_retention_consent=True, consents__talent_pool_opt_in=False)
    bad = []
    for label in ("Keep my application on file for future roles and email me about similar roles",
                  "Retain my CV for up to 2 years and email me about similar roles"):
        for klass in ("consent_retention", "marketing", "ordinary", NO_CLASS):
            res = _keep(label, "true", prof, klass)
            if is_stop(res) or is_ticked(res):
                bad.append((label[:56], klass, what(res)))
    assert not bad, report(bad)


# ================================================================== D-222 S3: a BARE citizenship / residency question is a canonical frame

S3_SHAPES = (
    "Are you a Singapore citizen?", "Are you a Singapore national?", "Are you a citizen of Singapore?",
    "Are you a Singapore Citizen or Permanent Resident?", "Are you a Singaporean or Singapore PR?", "Are you a Singaporean?",
    "Do you hold Singapore citizenship?", "Do you hold a Singapore passport?")
S3_NON_CANONICAL = (    # (label, the truth for the sample citizen, the WRONG value): they stay on the vote path (assumed, 2-3 calls)
    ("Are you a Singapore citizen by birth?", "Yes", "No"),
    ("Are you a Singapore citizen or a citizen of another country?", "Yes", "No"),
    ("Are you not a Singapore citizen?", "No", "Yes"),
    ("Have you been a Singapore citizen since 2020?", "Yes", "No"),
)


def test_s3_a_bare_citizenship_question_with_a_right_model_is_written_with_no_further_call_from_the_profile_fact():
    """RED UNTIL the engineer's S3 commit (`eng/Q-121-A1-fix1`; measured at int/Q-121 f2cd4e8: 2 calls, source `assumption`, assumed
    True): the 8 canonical shapes (citizen, national, citizen of, citizen or PR, PR, Singaporean, citizenship, passport) with a RIGHT
    model "Yes": written "Yes" with NO call beyond the page fill (no confirmation or meaning pick, no place call), the source a
    `profile:singapore_status.*` fact, assumed False. A WRONG model "No": "No" is never written (the confirmation path: "Yes" or
    empty), whether the confirmation sides with the model or states the truth. NOTE for the Coordinator: "Are you a Singapore PR?" is
    RULING (Coordinator, 2026-11-15): a bare "Are you a Singapore PR?" is NOT a citizen's shape (see the next test); the PR slot here is the combined "Singaporean or Singapore PR?", which stays "Yes"."""
    bad = []
    for label in S3_SHAPES:
        for klass in ("work_right", NO_CLASS):
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("Yes", "Yes"), scripted="NONE")
            if (is_stop(res) or shown(res) != "Yes" or ask.picks or ask.place_calls
                    or not _src(res).startswith("profile:singapore_status.") or res.assumed):
                bad.append((label[:50], klass, "right model", what(res), f"{len(ask.picks)} picks, {len(ask.place_calls)} place"))
            for pick in (pick_faithful("No", "Yes"), pick_faithful("Yes", "Yes")):
                res, ask = _go(label, "No", klass, pick=pick, scripted="NONE")
                if is_stop(res) or shown(res) not in ("Yes", ""):
                    bad.append((label[:50], klass, "wrong model", what(res)))
    assert not bad, report(bad, 12)


def test_s3_a_bare_permanent_resident_question_follows_the_residency_status_not_citizenship():
    """RULING (Coordinator, 2026-11-15; RED UNTIL the engineer's S3 follow-up): a bare "Are you a Singapore PR?" / "Are you a Singapore
    permanent resident?" is true only when the owner's residency status is PR. For the sample citizen: "No", source the residency fact
    (`profile:singapore_status.residency_status`); a right model "No" is written with NO further call, not assumed; a model "Yes" is
    never written. With a PR profile (`residency_status: pr`, built in memory from the sample) a right model "Yes" is written the same
    way and a model "No" is never written."""
    bad = []
    for label in ("Are you a Singapore PR?", "Are you a Singapore permanent resident?"):
        for status, truth in (("citizen", "No"), ("pr", "Yes")):
            prof = profile_with(singapore_status__residency_status=status)
            wrong = "Yes" if truth == "No" else "No"
            ask = ReplayAsk(lambda v: lie(truth, "work_right"), pick=pick_faithful(truth, truth), scripted="NONE")
            res = attempt(_f(label), ask, prof)
            ask.check()
            if (is_stop(res) or shown(res) != truth or ask.picks or ask.place_calls
                    or _src(res) != "profile:singapore_status.residency_status" or res.assumed):
                bad.append((label[:44], status, "right model", what(res), f"{len(ask.picks)} picks, {len(ask.place_calls)} place"))
            for pick in (pick_faithful(wrong, truth), pick_faithful(truth, truth)):
                ask = ReplayAsk(lambda v: lie(wrong, "work_right"), pick=pick, scripted="NONE")
                res = attempt(_f(label), ask, prof)
                if is_stop(res) or shown(res) not in (truth, ""):
                    bad.append((label[:44], status, "wrong model", what(res)))
    assert not bad, report(bad, 12)


def test_s3_non_canonical_citizenship_wordings_stay_on_the_vote_path_and_never_write_the_wrong_value():
    """"... citizen by birth", "... citizen or a citizen of another country", "Are you NOT a Singapore citizen", "... citizen since 2020"
    are not canonical frames: the right value is written only through the votes (assumed True, 2-3 pick calls) or the field ends
    empty (a joined or negated wording may), and the WRONG value is never written, whatever the confirmation says."""
    bad = []
    for label, truth, wrong in S3_NON_CANONICAL:
        for klass in ("work_right", NO_CLASS):
            res, ask = _go(label, truth, klass, pick=pick_faithful(truth, truth), scripted="NONE")
            if is_stop(res) or shown(res) not in (truth, "") or (shown(res) and (not res.assumed or not 2 <= len(ask.picks) <= 3)):
                bad.append((label[:50], klass, "right model", what(res), f"{len(ask.picks)} picks"))
            for pick in (pick_faithful(wrong, truth), pick_faithful(truth, truth)):
                res, ask = _go(label, wrong, klass, pick=pick, scripted="NONE")
                if is_stop(res) or shown(res) == wrong:
                    bad.append((label[:50], klass, "wrong model", what(res)))
    assert not bad, report(bad, 12)


def test_s3_passport_number_and_nric_fin_still_stop_owner_fact_missing():
    """UNCHANGED by S3: "Passport number" and "NRIC / FIN" are owner facts the profile does not hold: STOP `owner_fact_missing`."""
    from always_a1_support import stop_is
    bad = []
    for label in ("Passport number", "NRIC / FIN"):
        for klass in ("owner_fact", "ordinary", NO_CLASS):
            ask = ReplayAsk(lambda v: lie("S1234567A", klass), pick=pick_faithful("", ""), scripted="NONE")
            res = attempt(_pf("u", label, "TEXT", required=True), ask)
            if not stop_is(res, "owner_fact_missing"):
                bad.append((label, klass, what(res)))
    assert not bad, report(bad)


# ================================================================== D-222: work-pass questions for a citizen

WORK_PASS = ("Do you currently hold a valid Singapore work pass?", "Do you hold a Singapore Employment Pass?",
             "Do you hold a Singapore work pass that ties you to one employer?")


def test_work_pass_questions_are_no_for_a_citizen_and_a_model_yes_is_never_written():
    """D-222: "Do you currently hold a valid Singapore work pass?", "... a Singapore Employment Pass?", "... that ties you to one employer?"
    -> "No" for a Singapore citizen (the sample's `work_pass: none_required`): a model "Yes" with a confirmation that states the truth ends
    "No", source `profile:singapore_status.work_pass`; a confirmation that sides with the model ends "No" or empty, never "Yes"; a right
    model "No" ends "No". Never the place note; no place call for the first two wordings (the third may make one: the real reply is NONE)."""
    bad = []
    for label in WORK_PASS:
        most = 1 if "ties you" in label else 0
        for klass in ("work_right", "ordinary", NO_CLASS):
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("No", "No"))
            if (is_stop(res) or shown(res) != "No" or _src(res) != "profile:singapore_status.work_pass" or NOTE in _note(res)
                    or len(ask.place_calls) > most):
                bad.append((label[:56], klass, "model Yes, truthful check", what(res), len(ask.place_calls)))
            res, ask = _go(label, "Yes", klass, pick=pick_faithful("Yes", "No"))
            if is_stop(res) or shown(res) not in ("No", "") or NOTE in _note(res) or len(ask.place_calls) > most:
                bad.append((label[:56], klass, "model Yes, model-sided check", what(res), len(ask.place_calls)))
            res, ask = _go(label, "No", klass, pick=pick_faithful("No", "No"))
            if is_stop(res) or shown(res) != "No" or NOTE in _note(res) or len(ask.place_calls) > most:
                bad.append((label[:56], klass, "model No", what(res), len(ask.place_calls)))
    assert not bad, report(bad, 12)
