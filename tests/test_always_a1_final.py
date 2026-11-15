"""Q-121 Amendment A1, the final pin round: rulings V, P2 (trailing notes), P5, F and W of D-211
(docs/reviews/Q-121-A1-code.md; instructions/02_status.md D-209, D-211; llm_first_fill_design §17).

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step, so each pin here
keeps its assertion on the HARMFUL value (a declaration that applies, an invented personal fact, a work
right the profile does not give, or an under-claim of one) and on the NUMBER of model calls the ruling
allows. Expected values come from the rulings, never from what the code does.
Conditions of a model reply as in test_always_a1_p.py: R = right value + right class, W = wrong value +
right class, O = wrong value + class `ordinary`, M = wrong value + no class.
The scripted `pick_by(confirm, meaning)` answers the confirmation call (options Yes / No, or the field's
own) and the meaning call (options yes / no) separately; `ask.pick_tasks` lists the TASK line of each call.
Fakes only: no model, no network, no browser, sample profile, made-up names.
Verify: python tests/run_tests.py -k always_a1_final
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, digits, is_stop, lie, outcome, pick_by, pick_faithful, report, shown, stop_is, what,
    with_text, _pf)

NOTE = "Please do not include spent convictions."
TRAILING = "Have you ever been convicted of a criminal offence? " + NOTE

# (label, the value the READER takes as adverse, the class, the question's kind)
V_ROWS = (
    ("Can you confirm you have no criminal record?", "No", "declaration:criminal_record"),
    ("Can you confirm you have never been declared bankrupt?", "No", "declaration:bankruptcy"),
    (TRAILING, "Yes", "declaration:criminal_record"),
)
CLASSES = ("right", "ordinary", NO_CLASS)


def _klass(kind: str, right: str) -> str:
    return right if kind == "right" else kind


def _tasks(ask) -> list[str]:
    """Which kind of call each pick was: confirm | verify | own_fact | other."""
    from jobscraper.apply import always as AL
    out = []
    for t in ask.pick_tasks:
        out.append("verify" if t.startswith(AL.TASK_VERIFY[:40]) else
                   "confirm" if t.startswith(AL.TASK_CONFIRM[:40]) else
                   "own_fact" if t.startswith(AL.TASK_OWN_FACT[:30]) else "other")
    return out


class _MeaningDown:
    """A pick whose MEANING call fails at the transport (BackendError); the confirmation answers `confirm`."""

    def __init__(self, confirm):
        self.confirm = confirm

    def __call__(self, q, w, o):
        if str(w).startswith("If the applicant answers"):
            from jobscraper.backends import BackendError
            raise BackendError("the model is unreachable")
        return self.confirm


# ================================================================== V: the meaning call

def test_v_agreed_adverse_value_under_a_negation_gets_one_meaning_call_and_no_writes_it_assumed():
    """D-211 V: the first answer and the confirmation AGREE on the value the reader takes as adverse and a
    negation is in play: ONE more call (TASK_VERIFY), "If the applicant answers «V» to the question «Q»,
    does that state that the applicant <adverse>? yes or no". "no" -> V is written, assumed, with a note that
    names the three calls. Exactly 2 pick calls (confirm, meaning) after the 1 fill call. Class right /
    ordinary / none alike."""
    bad = []
    for label, adverse, right_class in V_ROWS:
        for kind in CLASSES:
            k = _klass(kind, right_class)
            ask = FakeAsk(lambda v, kk=k: lie(adverse, kk), pick=pick_by(adverse, "no"))
            res = attempt(_pf("v", label, options=YN), ask)
            tasks = _tasks(ask)
            if label == TRAILING:
                # U10 (fix8): the trailing-note wording is a CANONICAL frame, its reading is a veto: the model's
                # Yes and the agreeing Yes go against it, so there is NO meaning call and nothing is written,
                # even though a meaning reply "no" would have been available (was: written after the meaning call)
                if shown(res) != "" or tasks != ["confirm"]:
                    bad.append((label[:45], kind, "U10 canonical frame: veto, no meaning call", what(res), tasks))
                continue
            if is_stop(res) or shown(res) != adverse or not res.assumed or "meaning" not in str(res.note) \
                    or tasks != ["confirm", "verify"] or len(ask.sent) != 1:
                bad.append((label[:45], kind, "meaning no -> written", what(res), tasks, len(ask.sent)))
                continue
            wanted = ask.picks[1][1]
            if not wanted.startswith(f"If the applicant answers «{adverse}» to the question «{label}», does that state that the applicant"):
                bad.append((label[:45], kind, "the meaning call's WANTED", wanted))
            if ask.picks[1][2] != ["yes", "no"]:
                bad.append((label[:45], kind, "the meaning call's options", ask.picks[1][2]))
    assert not bad, report(bad, 10)


def test_v_yes_unusable_or_a_transport_failure_on_the_meaning_call_end_protectively_never_the_adverse_value():
    """V: "yes" (it DOES state the adverse fact) or an unusable reply on the meaning call -> the protective end:
    empty for the site, never the adverse value. The meaning call was made (2 pick calls), once, with no retry.
    A transport failure on the meaning call is F5: the page ends as `transport_failed` (see the end of the body)."""
    bad = []
    for label, adverse, right_class in V_ROWS:
        for kind in CLASSES:
            k = _klass(kind, right_class)
            # U10 (fix8): the canonical TRAILING wording never reaches a meaning call (a veto after one confirmation)
            want_tasks = ["confirm"] if label == TRAILING else ["confirm", "verify"]
            for name, pick in (("yes", pick_by(adverse, "yes")), ("unusable", pick_by(adverse, ""))):
                ask = FakeAsk(lambda v, kk=k: lie(adverse, kk), pick=pick)
                res = attempt(_pf("v", label, options=YN), ask)
                tasks = _tasks(ask)
                if shown(res) == adverse or shown(res) != "" or tasks != want_tasks:
                    bad.append((label[:45], kind, f"meaning {name}", what(res), tasks))
            # review 4 F5 (replaces "a transport failure on the meaning call -> the protective end, empty"): a
            # transport failure inside the vote ends the PAGE as a transport failure (model_unavailable, the
            # attempt is retryable); the adverse value is still never written
            ask = FakeAsk(lambda v, kk=k: lie(adverse, kk), pick=_MeaningDown(adverse))
            out = outcome(_pf("v", label, options=YN), ask)
            tasks = _tasks(ask)
            written = out.answers.get("v")
            if label == TRAILING:           # U10: no meaning call is made, so there is nothing to fail
                if out.transport_failed or tasks != ["confirm"] or (written is not None and shown(written) == adverse):
                    bad.append((label[:45], kind, "canonical frame: no meaning call", out.transport_failed, tasks))
                continue
            if not out.transport_failed or tasks != ["confirm", "verify"] \
                    or (written is not None and shown(written) == adverse):
                bad.append((label[:45], kind, "meaning call down", out.transport_failed, tasks))
    assert not bad, report(bad, 10)


def test_v_is_not_called_when_the_answers_agree_on_the_readers_own_option_or_differ():
    """V only follows an agreement on a value the reader takes as ADVERSE. The model's answer equal to the
    reader's option is written with NO call at all; a differing answer gets ONE confirmation call (equal to the
    reader's option -> that option, assumed) and never a meaning call."""
    # U9 (review 4 F1): only the TRAILING-note wording has a canonical frame, so only it has a reading. The two
    # negated wordings ("Can you confirm you have no ...") have NONE: even the model's right answer takes the
    # confirmation + one meaning call (U6), and a differing confirmation takes the meaning call on BOTH values
    # (U8b). The meaning replies are the faithful ones (the owner's value: "no"; the other value: "yes").
    bad = []
    for label, adverse, right_class in V_ROWS:
        owner = "Yes" if adverse == "No" else "No"          # the owner's truth
        reading = label == TRAILING
        for kind in CLASSES:
            k = _klass(kind, right_class)
            ask = FakeAsk(lambda v, kk=k: lie(owner, kk), pick=pick_faithful(adverse, owner))
            res = attempt(_pf("v", label, options=YN), ask)
            want = [] if reading else ["confirm", "verify"]
            if reading and (shown(res) != owner or ask.picks or len(ask.sent) != 1):
                bad.append((label[:45], kind, "model = reader's option: no call", what(res), len(ask.picks)))
            if not reading:
                ask = FakeAsk(lambda v, kk=k: lie(owner, kk), pick=pick_faithful(owner, owner))
                res = attempt(_pf("v", label, options=YN), ask)
                if shown(res) != owner or not res.assumed or _tasks(ask) != want:
                    bad.append((label[:45], kind, "no reading: right model, confirmation + meaning", what(res), _tasks(ask)))
            ask = FakeAsk(lambda v, kk=k: lie(adverse, kk), pick=pick_faithful(owner, owner))
            res = attempt(_pf("v", label, options=YN), ask)
            want = ["confirm"] if reading else ["confirm", "verify", "verify"]
            if shown(res) != owner or not res.assumed or _tasks(ask) != want:
                bad.append((label[:45], kind, "differ: the confirmation (+ both meaning calls with no reading)", what(res), _tasks(ask)))
    assert not bad, report(bad, 10)


def test_v_with_no_negation_an_agreed_adverse_value_is_never_written_and_asks_no_meaning_question():
    """D-212 U3 (replaces D-211 V "with no negation in the question it is never written, no meaning call"): the
    negation list gates nothing. A tentative reader on a question with no negation word: the first answer Yes
    and the confirmation Yes AGREE -> ONE meaning call, whether or not the reader takes the value as
    contradicting: "no" -> Yes written (assumed, three-call note); "yes" or unusable -> empty. Exactly
    [confirm, verify] after the fill call; never Yes without that "no"."""
    label = "Do you declare any conflict of interest?"
    for k in ("declaration:conflict_of_interest", "ordinary", NO_CLASS):
        for meaning, want in (("no", "Yes"), ("yes", ""), ("", "")):
            ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("Yes", meaning))
            res = attempt(_pf("v", label, options=YN), ask)
            assert shown(res) == want and _tasks(ask) == ["confirm", "verify"] and (not want or res.assumed),                 (k, meaning, what(res), _tasks(ask))


# ================================================================== P2: a note after the question does not invert it

def test_p2_a_trailing_note_or_aside_does_not_invert_the_question_for_the_four_h1_wordings():
    """D-211 P2 (review H1): a negation that sits only in a trailing note or aside leaves the question as
    asked, so the reader's option is No (the owner's truth) and the field is a P2 field: a model that says No
    is written with no call (never Yes, never assumed-by-vote); a silent model gets ONE confirmation (P5):
    only a pick equal to No writes it. If the note DID invert the question the reader would take Yes as the
    owner's option and a Yes would be written: a Yes is never written here."""
    rows = (
        "Have you ever been convicted of a criminal offence? Please do not include spent convictions.",
        "Have you ever been convicted of a criminal offence (not including minor traffic offences)?",
        "Have you ever been convicted of a criminal offence? (Do not answer yes for traffic offences)",
        "Are you currently a politically exposed person? Note: do not answer for family members.",
    )
    klasses = ("declaration:criminal_record", "declaration:criminal_record", "declaration:criminal_record", "declaration:pep")
    bad = []
    for label, right_class in zip(rows, klasses):
        for kind in CLASSES:
            k = _klass(kind, right_class)
            ask = FakeAsk(lambda v, kk=k: lie("No", kk), pick=pick_by("Yes", "no"))
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) != "No" or ask.picks:
                bad.append((label[:50], kind, "model No: written, no call", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, kk=k: lie("Yes", kk), pick=pick_by("", ""))
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) == "Yes":
                bad.append((label[:50], kind, "model Yes, unusable confirmation: never Yes", what(res)))
        ask = FakeAsk(pick=pick_by("No", ""))                                  # a silent model (P5)
        res = attempt(_pf("n", label, options=YN), ask)
        if shown(res) != "No" or not res.assumed or _tasks(ask) != ["confirm"]:
            bad.append((label[:50], "silent", "P5: pick No writes No", what(res), _tasks(ask)))
        for pick in ("Yes", ""):
            ask = FakeAsk(pick=pick_by(pick, ""))
            res = attempt(_pf("n", label, options=YN), ask)
            if shown(res) != "" or _tasks(ask) != ["confirm"]:
                bad.append((label[:50], "silent", f"P5: pick {pick!r} -> empty", what(res), _tasks(ask)))
    assert not bad, report(bad, 10)


def test_p2_the_same_note_in_the_help_text_and_a_negation_inside_the_question_are_told_apart():
    """The note in the field's help text is also a trailing note (reader option No). A negation INSIDE the
    question ("... that is not yet spent?") leaves the reader with no option: P3, a confirmation is always
    asked, even when the model's first answer is right."""
    plain = "Have you ever been convicted of a criminal offence?"
    ask = FakeAsk(lambda v: lie("No", "declaration:criminal_record"), pick=pick_by("No", ""))
    res = attempt(with_text(_pf("n", plain, options=YN), description=NOTE), ask)
    assert shown(res) == "No" and not ask.picks, (what(res), len(ask.picks))
    inside = "Have you been convicted of an offence that is not yet spent?"
    # D-212 U6: no reading -> a RIGHT model still gets the confirmation, and its agreement the meaning call
    ask = FakeAsk(lambda v: lie("No", "declaration:criminal_record"), pick=pick_by("No", "no"))
    res = attempt(_pf("n", inside, options=YN), ask)
    assert shown(res) == "No" and res.assumed and _tasks(ask) == ["confirm", "verify"], (what(res), _tasks(ask))
    ask = FakeAsk(lambda v: lie("No", "declaration:criminal_record"), pick=pick_by("No", ""))
    res = attempt(_pf("n", inside, options=YN), ask)
    assert shown(res) == "" and _tasks(ask) == ["confirm", "verify"], (what(res), _tasks(ask))


# ================================================================== F: the owner-fact keys

CODE_ONLY_EQUAL = (("Mobile number", "PHONE", "91234567"), ("Mobile number", "PHONE", "+65 9123 4567"),
                   ("Mobile number", "PHONE", "9123 4567"), ("Home address", "TEXT", "1 Example Road"),
                   ("Home address", "TEXT", "1 EXAMPLE ROAD."), ("Postal code", "TEXT", "000001"),
                   ("Postal code", "TEXT", "000 001"))


def test_f_an_equal_or_contained_value_with_the_code_key_alone_is_written_with_no_call():
    """D-211 F: with the code key alone (class ordinary / none) a model value that EQUALS or is CONTAINED in
    the profile's own value (another shape of it) is simply written: NO own-fact confirmation call, no stop."""
    bad = []
    for label, tn, value in CODE_ONLY_EQUAL:
        for k in ("ordinary", NO_CLASS):
            ask = FakeAsk(lambda v: lie(value, k), pick=pick_by("No", ""))
            res = attempt(_pf("f", label, tn), ask)
            if is_stop(res) or ask.picks or not shown(res):
                bad.append((label, value, str(k), what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_f_a_differing_value_with_the_code_key_alone_asks_one_own_fact_question_and_a_wrong_yes_never_keeps_the_invented_value():
    """The question asked is "is this asking for the applicant's own <fact>?" (TASK_OWN_FACT): Yes -> the
    profile value (the invented one is never written); No / unusable -> the model's value, assumed."""
    rows = (("Home address", "TEXT", "88 Orchard Road", "1 Example Road", "address"),
            ("Postal code", "TEXT", "238801", "000001", "postal code"),
            ("Mobile number", "PHONE", "98765432", "91234567", "phone"))
    bad = []
    for label, tn, invented, truth, words in rows:
        for k in ("ordinary", NO_CLASS):
            ask = FakeAsk(lambda v: lie(invented, k), pick=pick_by("Yes", ""))
            res = attempt(_pf("f", label, tn), ask)
            if _tasks(ask) != ["own_fact"] or ask.picks[0][1] != f"the applicant's own {words}" or invented in shown(res) \
                    or truth not in (shown(res) if tn != "PHONE" else digits(shown(res))):
                bad.append((label, str(k), "own fact yes", what(res), _tasks(ask), ask.picks[:1]))
            ask = FakeAsk(lambda v: lie(invented, k), pick=pick_by("No", ""))
            res = attempt(_pf("f", label, tn), ask)
            if shown(res) != invented or not res.assumed or len(ask.picks) != 1:
                bad.append((label, str(k), "own fact no", what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_f_the_models_address_phone_or_postal_class_alone_never_vetoes_its_own_value():
    """D-211 F: when ONLY the model names the class (the code key finds none: "Company address", "Employer
    phone number", a referee's phone) its value STANDS, assumed ("check: owner_fact:<which>"), with no call
    and no stop. The profile's own address / phone / postal code is never put on another party's field."""
    rows = (("Company address", "TEXT", "1 Raffles Quay", "owner_fact:address"),
            ("School address", "TEXT", "50 Nanyang Avenue", "owner_fact:address"),
            ("Employer phone number", "TEXT", "65551234", "owner_fact:phone"),
            ("Employer postal code", "TEXT", "048583", "owner_fact:postal_code"),
            ("Referee phone number", "PHONE", "65551234", "owner_fact:phone"))
    bad = []
    for label, tn, value, k in rows:
        ask = FakeAsk(lambda v: lie(value, k), pick=pick_by("Yes", ""))
        res = attempt(_pf("f", label, tn), ask)
        if is_stop(res) or shown(res) != value or not res.assumed or ask.picks or "owner_fact" not in str(res.evidence):
            bad.append((label, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_f_the_owner_only_facts_keep_the_veto_on_the_models_class_alone():
    """D-211 F: for the owner-only facts (national ID, salary, ...) the veto on EITHER key stays: a model
    that names the class on a label code does not key, with a value no profile row backs, ends the stop
    `owner_fact_missing`, never the invented value."""
    rows = (("Company registration details", "TEXT", "S1234567A", "owner_fact:national_id"),
            ("Details", "TEXT", "5000", "owner_fact:salary_current"))
    for label, tn, value, k in rows:
        res = attempt(_pf("f", label, tn), FakeAsk(lambda v: lie(value, k)))
        assert stop_is(res, "owner_fact_missing"), (label, what(res))
        assert value not in what(res), (label, what(res))


# ================================================================== W: work rights, both directions

SG_WORK = "Are you legally authorised to work in Singapore?"
US_WORK = "Are you legally authorised to work in the United States?"
SG_SPONS = "Will you now or in the future require sponsorship to work in Singapore?"
US_SPONS = "Will you now or in the future require sponsorship for employment visa status in the United States?"
OPTS = ("Authorized to work without sponsorship", "Authorized to work with sponsorship", "Not authorized to work")

# (label, the model's value that CONTRADICTS the truth, the truth's option, the class, direction)
# truth: SG authorised (profile row) / needs no sponsorship in SG (row); US not authorised (row) /
# sponsorship needed in the US (derived: not authorised).
W_UNDER = ((SG_WORK, "No", "Yes", "work_right"), (SG_SPONS, "Yes", "No", "sponsorship"))
W_OVER = ((US_WORK, "Yes", "No", "work_right"), (US_SPONS, "No", "Yes", "sponsorship"))


def _w_run(label, value, k, confirm=""):
    ask = FakeAsk(lambda v: lie(value, k), pick=pick_by(confirm, ""))
    return attempt(_pf("w", label, options=YN), ask), ask


def _w_check(rows, keys, what_for):
    """For each contradicting value and key condition: ONE confirmation; the pick that names the truth writes it
    (assumed, 1 call); an unusable pick -> empty; the contradicting value is never written; the model's RIGHT
    value is written with no call (D-212 W then U1-U4)."""
    bad = []
    for label, value, truth, klass in rows:
        for k in keys(klass):
            res, ask = _w_run(label, value, k, truth)
            if is_stop(res) or shown(res) != truth or not res.assumed or len(ask.picks) != 1:
                bad.append((label[:45], str(k), what_for, "confirmation names the truth", what(res), len(ask.picks)))
            res, ask = _w_run(label, value, k, "")
            if shown(res) != "" or len(ask.picks) != 1:
                bad.append((label[:45], str(k), what_for, "unusable confirmation: empty", what(res), len(ask.picks)))
            res, ask = _w_run(label, truth, k, value)
            if shown(res) != truth or ask.picks:
                bad.append((label[:45], str(k), what_for, "model right: written, no call", what(res), len(ask.picks)))
    return bad


def test_w_under_claim_with_both_keys_is_overridden_by_the_truth():
    """Ruling W then U (D-212; replaces "both keys: code writes the truth from the profile row, not assumed"):
    an under-claim is vetoed and put to ONE confirmation; the truth option is written only when the
    confirmation names it (assumed); unusable -> empty. Never the under-claim."""
    bad = _w_check(W_UNDER, lambda klass: (klass,), "under-claim, both keys")
    assert not bad, report(bad)


def test_w_over_claim_with_both_keys_is_overridden_by_the_truth():
    """As above for the dangerous direction (a right to work, or no sponsorship need, the profile does not give)."""
    bad = _w_check(W_OVER, lambda klass: (klass,), "over-claim, both keys")
    assert not bad, report(bad)


def test_w_over_claim_with_one_key_is_vetoed_and_never_written():
    """The dangerous direction with the code key alone (class ordinary / none) AND with the model's class alone
    (a list code cannot key): never written; the confirmation that names the truth writes it (assumed),
    unusable -> empty."""
    bad = _w_check(W_OVER, lambda klass: ("ordinary", NO_CLASS), "over-claim, code key alone")
    for label in ("Employment eligibility status", "Droit de travailler"):          # code finds no class: model key alone
        for confirm, want in (("Not authorized to work", "Not authorized to work"), ("", "")):
            ask = FakeAsk(lambda v: lie(OPTS[0], "work_right"), pick=pick_by(confirm, ""))
            res = attempt(_pf("w", label, "DROPDOWN", options=OPTS), ask, rctx_kw={"job_country": "US"})
            if shown(res) != want or (want and not res.assumed) or shown(res) in OPTS[:2]:
                bad.append((label, "US, model key alone", f"confirm {confirm!r}", what(res)))
    assert not bad, report(bad)


def test_w_under_claim_with_one_key_is_vetoed_too():
    """Ruling W then U (replaces "the protective end writes the profile row"): the under-claim ("No" to
    "authorised to work in Singapore" for a citizen, "needs sponsorship" for a citizen) is vetoed with the code
    key alone and with the model's class alone; ONE confirmation; the pick that names the truth writes it
    (assumed); unusable -> empty. Never the under-claim."""
    bad = _w_check(W_UNDER, lambda klass: ("ordinary", NO_CLASS), "under-claim, code key alone")
    for label in ("Employment eligibility status", "Droit de travailler"):          # the model's key alone
        for confirm, want in ((OPTS[0], OPTS[0]), ("", "")):
            ask = FakeAsk(lambda v: lie(OPTS[2], "work_right"), pick=pick_by(confirm, ""))
            res = attempt(_pf("w", label, "DROPDOWN", options=OPTS), ask)
            if shown(res) != want or (want and not res.assumed) or shown(res) == OPTS[2]:
                bad.append((label, "SG, model key alone", f"confirm {confirm!r}", what(res)))
    assert not bad, report(bad)
