"""Q-121 Amendment A1 oracles, part 2: pin groups (9)-(15) of llm_first_fill_design §17.7
(review docs/reviews/Q-121-always-code.md M3, M4, M5, M6, M7, M8, L1, L3, L5).

Same method as tests/test_always_a1.py: fakes only, expected values from the design, every input of a
group is run and all failing ones are reported. No model, no network, no browser.
Verify: python tests/run_tests.py -k always_a1_b
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, digits, is_empty, is_stop, labels, lie, page, pick_by, pick_faithful, profile_with,
    report, say, shown, stop_is, what, with_text, _pf, _profile)


# ================================================================== (9) M3: option matching

M3_NO_MATCH = (
    ("No", ("Yes", "No, but I have in the past", "Prefer not to say")),
    ("No", ("Yes", "No longer employed", "Prefer not to say")),
    ("Yes", ("No", "Yes, but I am on a visa", "Prefer not to say")),
    ("Female", ("Male", "Non-female", "Prefer not to say")),
    ("Male", ("Female", "Female and Male", "Prefer not to say")),
    ("Citizen", ("Permanent Resident", "Citizen of another country")),
    ("Singapore", ("Malaysia", "Singapore PR")),
    ("Not Hispanic or Latino", ("Hispanic or Latino", "Prefer not to say")),          # review C7
    ("Hispanic or Latino", ("Not Hispanic or Latino", "Prefer not to say")),            # and the mirror
)


def test_a1_m3_r1_never_picks_an_option_that_adds_or_drops_a_negation_or_a_qualifier():
    from jobscraper.apply import always as AL
    bad = []
    for wanted, options in M3_NO_MATCH:
        got = AL.r1_pick(wanted, options)
        lad = AL.ladder(wanted, options)[0]
        if got is not None or lad is not None:
            bad.append((wanted, options, "r1_pick", got, "ladder", lad))
    assert not bad, report(bad)


def test_a1_m3_exact_and_near_matches_still_resolve():
    """R0 on an exact option, R1 on an honest near-match (the pins that must not break)."""
    from jobscraper.apply import always as AL
    cases = (("Yes", ("Yes", "No"), "Yes"), ("no", ("Yes", "No"), "No"),
             ("Citizen of Singapore", ("Singapore Citizen", "Other"), "Singapore Citizen"),
             ("Not Hispanic or Latino", ("Hispanic or Latino", "Not Hispanic or Latino"), "Not Hispanic or Latino"))
    bad = [(w, o, want, AL.ladder(w, o)[0]) for w, o, want in cases if AL.ladder(w, o)[0] != want]
    assert not bad, report(bad)


def test_a1_m3_a_model_value_that_is_only_a_longer_option_is_not_written_as_that_option():
    bad = []
    for model, options in (("No", ("Yes", "No, but I was in the past", "Prefer not to say")),
                           ("Yes", ("No", "Yes, but I am on a visa", "Prefer not to say"))):
        near = options[1]
        ask = FakeAsk(lambda v, m=model: say(m, "resume", "", klass="ordinary"), pick=lambda q, w, o: "")
        res = attempt(_pf("e", "Are you employed elsewhere right now?", "DROPDOWN", options=options), ask)
        if shown(res) == near:
            bad.append((model, options, what(res)))
    assert not bad, report(bad)


# ================================================================== (10) M4: self-ID

SELF_ID_ROWS = (
    # (label, type, options, model's value, class, the designed value)
    ("Gender", "DROPDOWN", ("Male", "Female", "Other", "Prefer not to say"), "Male", "self_id:gender", "Prefer not to say"),
    ("Race", "DROPDOWN", ("Chinese", "Malay", "Indian", "Other", "Prefer not to say"), "Chinese", "self_id:race", "Prefer not to say"),
    ("Religion", "DROPDOWN", ("Buddhism", "Christianity", "Islam", "Other", "Prefer not to say"), "Islam", "self_id:religion", "Prefer not to say"),
    ("Marital status", "DROPDOWN", ("Single", "Married", "Prefer not to say"), "Single", "self_id:marital", "Prefer not to say"),
    ("Do you have a disability?", "RADIO", ("Yes", "No"), "Yes", "self_id:disability", "No"),
    ("Disability status", "RADIO", ("Yes, I have a disability", "No, I do not have a disability", "I do not want to answer"),
     "Yes, I have a disability", "self_id:disability", "I do not want to answer"),
    ("Are you a protected veteran?", "RADIO", ("Yes", "No"), "Yes", "self_id:veteran", "No"),
    ("Veteran status", "RADIO", ("I am a protected veteran", "I am not a protected veteran", "I do not wish to answer"),
     "I am a protected veteran", "self_id:veteran", "I do not wish to answer"),
)


def test_a1_m4_self_id_ends_on_the_profile_decline_option_or_no_never_the_models_guess():
    """Profile: gender/race/religion/marital/disability/veteran all `decline` (D4); disability and veteran
    default No (D-87) when only Yes/No is offered. Whatever class the model gives, and whatever it picked."""
    bad = []
    for label, tn, options, model, klass, want in SELF_ID_ROWS:
        for k in (klass, "ordinary", NO_CLASS):
            res = attempt(_pf("s", label, tn, options=options), FakeAsk(lambda v: lie(model, k)))
            if shown(res) != want:
                bad.append((label, k, "want", want, what(res)))
    assert not bad, report(bad)


def test_a1_m4_a_required_self_id_list_with_no_decline_option_is_never_other_and_never_a_first_option():
    bad = []
    for label, options in (("Gender", ("Male", "Female", "Other")), ("Race", ("Chinese", "Malay", "Indian", "Other"))):
        for name, ask in (("silent", FakeAsk()), ("model guesses", FakeAsk(lambda v, o=options: lie(o[0], "self_id:gender")))):
            res = attempt(_pf("s", label, "DROPDOWN", options=options), ask)
            if not (is_stop(res) or is_empty(res)):
                bad.append((label, name, what(res)))
            elif is_stop(res) and res.reason.value != "validation_error":
                bad.append((label, name, "a stop, but not validation_error", what(res)))
    assert not bad, report(bad)


def test_a1_m4_self_id_follows_a_set_profile_value():
    p = profile_with(identity__gender="female", singapore_status__race="chinese")
    res = attempt(_pf("g", "Gender", "DROPDOWN", options=("Male", "Female", "Prefer not to say")), FakeAsk(lambda v: lie("Male", "self_id:gender")), p)
    assert shown(res) == "Female", what(res)
    res = attempt(_pf("r", "Race", "DROPDOWN", options=("Chinese", "Malay", "Prefer not to say")), FakeAsk(lambda v: lie("Malay", "self_id:race")), p)
    assert shown(res) == "Chinese", what(res)


# ================================================================== (11) M5: unclassed and non-English declarations

def test_a1_m5_dismissal_and_litigation_yes_is_never_written():
    """D-212 U2 / U3 / U4 + U9 (replaces "class declaration:other: code writes the none-applies No"): the model's
    Yes differs from the reader's No, in every class condition -> ONE confirmation; pick No -> No (assumed);
    unusable -> empty; a pick that sides with the Yes -> the meaning call, unusable here -> empty. A Yes is
    never written without a "no" meaning reply. U9: "Any pending litigation ..." is no canonical frame, so it
    has NO reading: a differing confirmation (No) gets the meaning call on BOTH values (U8b: No -> "no",
    Yes -> "yes": 3 calls) before the No is written."""
    bad = []
    for label, canonical in (("Have you been dismissed or asked to resign from any employment?", True),
                             ("Any pending litigation or legal proceedings against you?", False)):
        for klass in ("declaration:other", "ordinary", NO_CLASS):
            ask = FakeAsk(lambda v: lie("Yes", klass), pick=pick_faithful("No", "No"))
            res = attempt(_pf("x", label, options=YN), ask)
            if shown(res) != "No" or not res.assumed or len(ask.picks) != (1 if canonical else 3):
                bad.append((label, klass, "confirmation No", what(res), len(ask.picks)))
            # U10 (fix8): on a canonical frame the model's Yes and a confirming Yes AGREE against the frame's reading:
            # a veto, the protective end, NO meaning call (1 pick). With no frame (no reading) the meaning call stays (2).
            for pick, picks in (("", 1), ("Yes", 1 if canonical else 2)):
                ask = FakeAsk(lambda v: lie("Yes", klass), pick=pick_by(pick, ""))
                res = attempt(_pf("x", label, options=YN), ask)
                if shown(res) != "" or len(ask.picks) != picks:
                    bad.append((label, klass, f"confirmation {pick!r}", what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_a1_m5_the_french_pep_question_goes_to_the_confirm_call_and_never_writes_oui():
    """D-212 U2 / U3 / U6 (replaces D-211 P3 "differ -> empty, agree -> written with no further call"): no code
    reading of a French question. The model's first answer is never equal to a reader's option, so ONE
    confirmation is asked (WANTED is the owner's truth, never the model's value). It AGREES with the first
    answer -> ONE meaning call: "no" -> written (assumed, three-call note), "yes" / unusable -> empty. It
    DIFFERS from the first answer -> the confirmation's value is the one checked (U8, pinned in the U
    file); with an unusable meaning reply -> empty. An unusable confirmation -> empty. Never an unchecked Oui."""
    f = lambda: _pf("pep", "Es-tu une personne politiquement exposée ?", options=("Oui", "Non"))
    for pick in ("", "Non"):
        ask = FakeAsk(lambda v: lie("Oui", "declaration:pep"), pick=pick_by(pick, ""))
        res = attempt(f(), ask)
        assert shown(res) == "" and not res.assumed, (pick, what(res))
        assert 1 <= len(ask.picks) <= 2 and "truth" in ask.pick_tasks[0].lower(), (ask.picks, ask.pick_tasks)
        assert "Oui" not in ask.picks[0][1], ask.picks                        # WANTED is the owner's truth, not the model's value
    for meaning, want in (("no", "Oui"), ("yes", ""), ("", "")):              # the agreed (wrong) Oui: only a "no" meaning reply
        ask = FakeAsk(lambda v: lie("Oui", "declaration:pep"), pick=pick_by("Oui", meaning))
        res = attempt(f(), ask)
        assert shown(res) == want and len(ask.picks) == 2 and (not want or res.assumed), (meaning, what(res), len(ask.picks))
    ask = FakeAsk(lambda v: lie("Non", "declaration:pep"), pick=pick_by("Non", "no"))
    res = attempt(f(), ask)
    assert shown(res) == "Non" and res.assumed and len(ask.picks) == 2, (what(res), len(ask.picks))


def test_a1_m5_a_country_less_work_rights_list_uses_the_jobs_country():
    """D-212 W / U (replaces "code writes the citizen option / vetoes with no call"): the job is in SG and
    the owner is a Singapore citizen (the truth: authorised, no sponsorship). The model's under-claim
    ("Not authorized") is vetoed: ONE confirmation naming the truth; the pick that names the citizen option
    is written (assumed); unusable -> empty. For a job in the US (authorised_to_work US=false): the model's
    over-claim is never written in any class condition."""
    options = ("Authorized without sponsorship", "Authorized with sponsorship", "Not authorized")
    bad = []
    ask = FakeAsk(lambda v: lie("Not authorized", "work_right"), pick=pick_by(options[0], ""))
    res = attempt(_pf("v", "Visa status", "DROPDOWN", options=options), ask)
    if shown(res) != options[0] or not res.assumed or len(ask.picks) != 1:
        bad.append(("job in SG, SG citizen, confirmation names the citizen option", what(res), len(ask.picks)))
    ask = FakeAsk(lambda v: lie("Not authorized", "work_right"), pick=pick_by("", ""))
    res = attempt(_pf("v", "Visa status", "DROPDOWN", options=options), ask)
    if shown(res) != "":
        bad.append(("job in SG, unusable confirmation", what(res)))
    for klass in ("work_right", "sponsorship", "ordinary", NO_CLASS):
        res = attempt(_pf("v", "Visa status", "DROPDOWN", options=options),
                      FakeAsk(lambda v: lie("Authorized without sponsorship", klass)), rctx_kw={"job_country": "US"})
        if shown(res) == "Authorized without sponsorship" or shown(res) == "Authorized with sponsorship":
            bad.append(("job in US, authorised_to_work US=false", klass, what(res)))
    assert not bad, report(bad)


# ================================================================== (12) M6: call budget

class _Unparseable:
    """An ask whose every reply is `not json`; counts the calls and keeps each TASK line."""

    def __init__(self, text="not json"):
        self.calls, self.tasks, self.text = 0, [], text

    def __call__(self, messages, schema, *, max_tokens, temperature=0.0, seed=7):
        self.calls += 1
        self.tasks.append(messages[1]["content"].rstrip().splitlines()[-1])
        return {"text": self.text, "done_reason": "stop"}


def _twenty():
    return ([_pf(f"t{i}", f"Dummy short question {i}", "TEXT") for i in range(14)]
            + [_pf(f"d{i}", f"Dummy choice question {i}", "DROPDOWN", options=("Alpha", "Beta")) for i in range(6)])


def test_a1_m6_an_unparseable_model_costs_at_most_six_calls_and_ends_in_the_content_failure_before_a5():
    from jobscraper.apply import always as AL
    from jobscraper.apply.contracts import CONTENT_FAILURE_MARKERS, ReasonCode
    ask = _Unparseable()
    res = page(_twenty(), ask)
    assert is_stop(res), "twenty unparseable replies must end in the content failure"
    assert res.reason is ReasonCode.UNANSWERABLE_REQUIRED and res.detail.startswith(CONTENT_FAILURE_MARKERS[0]), res.detail
    assert ask.calls <= 6, f"{ask.calls} calls (design: retry once, split once, <= 6 a chunk)"
    assert not [t for t in ask.tasks if t.startswith(AL.TASK_MUST[:30])], "A5 must not run after a known content failure"


def test_a1_m6_the_per_page_call_cap_is_a_content_failure():
    from jobscraper.apply.contracts import CONTENT_FAILURE_MARKERS, ReasonCode
    ask = _Unparseable("{}")                               # valid JSON, no answers: A5 would go on asking
    res = page([_pf(f"t{i}", f"Dummy short question {i}", "TEXT") for i in range(8)], ask, cfg={"max_calls_page": 2})
    assert is_stop(res) and res.reason is ReasonCode.UNANSWERABLE_REQUIRED, what(res)
    assert res.detail.startswith(CONTENT_FAILURE_MARKERS[0]) and "too many model calls" in res.detail, res.detail
    assert ask.calls <= 2, ask.calls


# ================================================================== (13) M7: other persons' fields

def test_a1_m7_another_persons_contact_field_never_gets_the_applicants_details():
    from apply_flow_support import EMAIL
    rows = (("Email address", "EMAIL", "Supervisor name"), ("Referral email", "EMAIL", ""),
            ("Email of person who referred you", "EMAIL", ""), ("Your mentor's phone number", "PHONE", ""),
            ("Phone", "PHONE", "Manager name"), ("Contact email", "EMAIL", "Recruiter name"),
            ("Colleague email", "EMAIL", ""), ("Friend's phone number", "PHONE", ""))
    bad = []
    for label, tn, context in rows:
        for name, ask in (("model gives the applicant's", FakeAsk(lambda v: lie(EMAIL if tn == "EMAIL" else "91234567", "other_person"))),
                          ("no class", FakeAsk(lambda v: lie(EMAIL if tn == "EMAIL" else "91234567", NO_CLASS))),
                          ("silent", FakeAsk())):
            res = attempt(with_text(_pf("o", label, tn, required=True), context=context), ask)
            v = shown(res)
            if EMAIL in v or "alex.testcase" in v.lower() or "91234567" in digits(v):
                bad.append((label, context, name, what(res)))
    assert not bad, report(bad)


def test_a1_m7_a_name_field_after_a_supervisor_field_is_not_the_applicants_name():
    bad = []
    for label in ("Full name", "Name", "First name"):
        res = attempt(with_text(_pf("n", label, "TEXT"), context="Supervisor"), FakeAsk(lambda v: lie("Alex Testcase", "other_person")))
        if "Testcase" in shown(res) or "Alex" in shown(res):
            bad.append((label, what(res)))
    assert not bad, report(bad)


# ================================================================== (14) M8: salary

def test_a1_m8_current_or_last_drawn_salary_is_never_the_expected_figure():
    bad = []
    for label in ("Last drawn salary", "Current salary", "Previous salary", "Present salary"):
        for name, ask in (("silent", FakeAsk()), ("model invents the expected figure", FakeAsk(lambda v: lie("5000", "owner_fact:salary_current"))),
                          ("model, class ordinary", FakeAsk(lambda v: lie("5000", "ordinary")))):
            res = attempt(_pf("s", label, "TEXT"), ask)                    # the sample has pay.current_salary = null
            if shown(res) != "N/A" or not res.assumed:
                bad.append((label, name, "want N/A, assumed", what(res)))
            res = attempt(_pf("s", label, "NUMBER"), ask)
            if not stop_is(res, "owner_fact_missing") or "current salary" not in res.detail:
                bad.append((label, name, "NUMBER: the stop 'current salary'", what(res)))
    assert not bad, report(bad)


def test_a1_m8_a_set_current_salary_is_used_and_the_expected_salary_is_still_the_expected_figure():
    p = profile_with(pay__current_salary={"amount": 3500, "currency": "SGD", "period": "monthly"})
    res = attempt(_pf("s", "Last drawn salary", "TEXT"), FakeAsk(lambda v: lie("5000", "owner_fact:salary_current")), p)
    assert "3500" in shown(res) and "5000" not in shown(res), what(res)
    res = attempt(_pf("e", "Expected monthly salary (SGD)", "NUMBER"), FakeAsk(lambda v: lie("9000", "owner_fact:salary_expected")))
    assert "5000" in shown(res) and "9000" not in shown(res), what(res)


# ================================================================== (15) L1, L3, L5

def test_a1_l1_an_implicit_negation_never_makes_code_write_the_adverse_yes_over_a_correct_no():
    bad = []
    for label, klass in (("Is there anything that prevents you from confirming you have no criminal record?", "declaration:criminal_record"),
                         ("Are you NOT free of any conflict of interest?", "declaration:conflict_audit_independence")):
        for k in (klass, "ordinary", None):
            for pick in ("", "No", "Yes"):
                ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration", klass=k), pick=lambda q, w, o, x=pick: x)
                res = attempt(_pf("n", label, options=YN), ask)
                if shown(res) == "Yes" and pick != "Yes":
                    bad.append((label, k, f"confirm={pick!r}", what(res)))
    assert not bad, report(bad)


def test_a1_l3_a_kept_site_value_on_an_identity_field_must_equal_the_profile():
    from jobscraper.apply.contracts import ValueOrigin
    bad = []
    for label, tn, site, truth in (("Home address", "TEXT", "88 Orchard Road", "1 Example Road"),
                                   ("Postal code", "TEXT", "238801", "000001")):
        f = _pf("k", label, tn, shown=site, origin=ValueOrigin.RESUME_IMPORT)
        res = attempt(f, FakeAsk(lambda v: say(site, "keep", "", klass=None)))
        if is_stop(res) or site in shown(res) or truth not in shown(res):
            bad.append((label, "site value is not the profile's", what(res)))
        f2 = _pf("k", label, tn, shown=truth, origin=ValueOrigin.RESUME_IMPORT)
        res = attempt(f2, FakeAsk(lambda v: say(truth, "keep", "", klass=None)))
        if is_stop(res) or "N/A" in shown(res):
            bad.append((label, "site value equals the profile's: keep is fine", what(res)))
    assert not bad, report(bad)


def test_a1_l5_accept_and_agree_verbs_make_a_certification_the_owners_certify_true():
    bad = []
    for label in ("Do you accept that the above information is complete and correct?",
                  "Do you agree that the information above is true and accurate?"):
        for klass in ("certification", None):
            res = attempt(_pf("c", label, options=YN), FakeAsk(lambda v: lie("No", klass)))
            if shown(res) != "Yes":
                bad.append((label, klass, what(res)))
    assert not bad, report(bad)
