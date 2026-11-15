"""Q-121 always-answer FIX-ROUND pins (D-208; llm_first_fill_design §3.4 D1-D10, §4.2 S1, §4.6
last resort and the owner-fact stop, §6; the Coordinator's rulings D1a, D1b, D2, Q1, Q2, 1-3).

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step. Each pin
below drives the public entry points the other always oracles use (`fill_page_always` through
`_run` / `_one`, `last_resort` through `_lr`, `briefing.build`), with the fake `ask` scripted to
the WRONG answer wherever the rule must beat the model and to NOTHING where the last resort
must decide. Dummy sample profile only; no model, no network, no browser.

A red pin here is a DEFECT in the code, never a reason to change the expected value.
Verify: python tests/run_tests.py -k always_fix_pins
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402
from test_always_fill import (  # noqa: E402
    NEEDS, YN, FakeAsk, _lr, _one, _pf, _profile, _run, _shown, pick_by, say)
from always_a1_support import pick_faithful  # noqa: E402
from test_always_briefing import _build, _lines  # noqa: E402


def _stop_or_answer(field, ask, profile=None, **kw):
    """The AlwaysStop the page raised, else the Answer (so a pin can say which happened)."""
    from jobscraper.apply import always as AL
    try:
        return _one(field, ask, profile, **kw)[0]
    except AL.AlwaysStop as exc:
        return exc


def _is_stop(res, fact: str, target: str | None = None) -> bool:
    from jobscraper.apply import always as AL
    from jobscraper.apply.contracts import ReasonCode
    return isinstance(res, AL.AlwaysStop) and res.reason is ReasonCode.OWNER_FACT_MISSING \
        and res.detail == fact and (target is None or res.target_path == target)


def _is_refusal_stop(res, key: str) -> bool:
    """Ruling A / R-c, as amended by A1 (design 17.2, 17.6): the owner's explicit false consent on a
    required box that cannot say No ends `consent_refused`, target `consents.<key>`, with the
    designed detail `CONSENT_REFUSED_DETAILS["consents.<key>"]` (it was `owner_fact_missing` with
    "your profile says no" before the amendment)."""
    from jobscraper.apply import always as AL
    from jobscraper.apply.contracts import CONSENT_REFUSED_DETAILS, ReasonCode
    return isinstance(res, AL.AlwaysStop) and res.reason is ReasonCode.CONSENT_REFUSED \
        and res.target_path == f"consents.{key}" \
        and res.detail == CONSENT_REFUSED_DETAILS[f"consents.{key}"]


def _what(res) -> str:
    from jobscraper.apply import always as AL
    if isinstance(res, AL.AlwaysStop):
        return f"STOP {res.reason.value} {res.detail!r} {res.target_path!r}"
    return f"{res.value!r} source={res.source} assumed={res.assumed} evidence={res.evidence!r}"


def _tick(a) -> bool:
    """True when the answer says yes / ticks the box."""
    if a.option_labels:
        return _shown(a) == "Yes"
    return a.value == "true"


def _say_bool(kind: str, yes: bool, basis="default", ref="default:consent", assumed=False):
    word = ("true" if yes else "false") if kind == "CHECKBOX" else ("Yes" if yes else "No")
    return say(word, basis, ref, assumed)


# ------------------------------------------------------------------ D1a: ambiguous, one truth

RELATIVES = ("Do you have any relatives employed by the company?",
             "Are any of your relatives employed by the company?")


@needs(*NEEDS)
def test_d1a_ambiguous_relatives_wording_gets_the_owners_no_whatever_the_model_cites():
    """D-212 U2 / U3 / U4 (replaces "code writes the owner's No over a model Yes with no call"): the model's Yes
    differs from the reader's No, so ONE confirmation states the owner's truth: a pick No -> No, assumed,
    standing kept, the note says "the AI answered Yes"; an unusable pick -> empty; a pick Yes (it sides with
    the model) -> the meaning call, and only "no" writes the Yes (assumed). Whatever rule the model cites."""
    models = (("default", "default:no_declaration"), ("default", "default:employer_history"),
              ("profile", "profile:declarations.relatives_at_company"), ("assumption", ""))
    bad = []
    for label in RELATIVES:
        for basis, ref in models:
            mk = lambda **kw: FakeAsk(lambda v, b=basis, r=ref: say("Yes", b, r, b == "assumption"), **kw)   # noqa: E731
            ask = mk(pick=pick_by("No", ""))
            a, out = _one(_pf("rel", label, options=YN), ask)
            if _shown(a) != "No" or not a.assumed or "rel" not in out.standing_kept or len(ask.picks) != 1                     or "the AI answered Yes" not in (a.note + " " + a.evidence):
                bad.append((label, basis, "confirm No", _what(a), a.note, out.standing_kept, len(ask.picks)))
            ask = mk(pick=pick_by("", ""))
            a, _ = _one(_pf("rel", label, options=YN), ask)
            if _shown(a) != "" or len(ask.picks) != 1:
                bad.append((label, basis, "confirm unusable", _what(a), len(ask.picks)))
            for meaning in ("yes", ""):
                ask = mk(pick=pick_by("Yes", meaning))
                a, _ = _one(_pf("rel", label, options=YN), ask)
                # U10 (fix8): both relatives wordings are canonical frames: a confirmation that sides with the model's
                # Yes against the frame is a veto, NO meaning call (was 2 calls, now 1); the Yes is still never written
                if _shown(a) != "" or len(ask.picks) != 1:
                    bad.append((label, basis, f"confirm Yes, meaning {meaning!r}", _what(a), len(ask.picks)))
    assert not bad, bad


@needs(*NEEDS)
def test_d1a_the_models_disagreement_is_only_a_note_and_agreement_or_silence_gives_the_same_no():
    """U1: the model's No equals the reader's No: written, no call, not assumed. A silent model gets ONE
    confirmation: pick No -> No (assumed); unusable -> empty (U4: never code's own No)."""
    for label in RELATIVES:
        ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration"), pick=pick_by("Yes", "no"))
        a, out = _one(_pf("rel", label, options=YN), ask)
        assert _shown(a) == "No" and not a.assumed and "rel" not in out.standing_kept and not ask.picks, _what(a)
        ask = FakeAsk(pick=pick_by("No", ""))
        a2, _ = _one(_pf("rel", label, options=YN), ask)               # silent: A6 alone
        assert _shown(a2) == "No" and a2.assumed and len(ask.picks) == 1, (label, _what(a2), len(ask.picks))
        ask = FakeAsk(pick=pick_by("", ""))
        a3, _ = _one(_pf("rel", label, options=YN), ask)
        assert _shown(a3) == "" and len(ask.picks) == 1, (label, _what(a3))


@needs(*NEEDS)
def test_d1a_an_ordinary_yes_no_question_keeps_the_models_answer():
    # negative control: nothing here is a declaration, so neither D1a nor D2 nor D1b may act
    for label in ("Are you comfortable working with Python every day?",
                  "Can you work from our Singapore office three days a week?"):
        for said in ("Yes", "No"):
            a, out = _one(_pf("q", label, options=YN),
                          FakeAsk(lambda v, s=said: say(s, "resume", "")))
            assert _shown(a) == said and not a.assumed and not out.standing_kept, (label, said, _what(a))


# ------------------------------------------------------------------ D1b: a rule the answer cites

CONFLICT = "Do you declare any conflict of interest with this role?"


@needs(*NEEDS)
def test_d1b_a_declaration_the_model_says_yes_while_citing_a_default_rule_is_replaced_by_the_rule():
    """D-212 U2 / U3 (replaces "code writes the cited rule's No over the model's Yes"): the model's Yes
    differs from the reader's No -> ONE confirmation; the pick No writes No (assumed, standing kept, note
    "the AI answered Yes"); an unusable pick or one that sides with the Yes without a "no" meaning reply
    -> empty. Never Yes unchecked."""
    for ref in ("default:no_declaration", "default:employer_history"):
        # U9 / U8b: CONFLICT ("Do you declare any conflict of interest?") has NO reading, so the differing confirmation
        # (No) gets the meaning call on BOTH values (No -> "no", Yes -> "yes"): 3 calls, then No is written (assumed,
        # the note names the AI's Yes). The U8b path does not mark the standing answer kept.
        ask = FakeAsk(lambda v, r=ref: say("Yes", "default", r), pick=pick_faithful("No", "No"))
        a, out = _one(_pf("c", CONFLICT, options=YN), ask)
        assert _shown(a) == "No" and a.assumed and len(ask.picks) == 3, (ref, _what(a), len(ask.picks))
        assert "c" in out.assumed, out.assumed
        assert "the AI answered Yes" in a.note, a.note
        for pick, meaning, calls in (("", "", 1), ("Yes", "yes", 2), ("Yes", "", 2)):
            ask = FakeAsk(lambda v, r=ref: say("Yes", "default", r), pick=pick_by(pick, meaning))
            a, _ = _one(_pf("c", CONFLICT, options=YN), ask)
            assert _shown(a) == "" and len(ask.picks) == calls, (ref, pick, meaning, _what(a), len(ask.picks))
    # control (U6 / U9, replaces "an answer agreeing with the rule is written with no call"): with no reading even the
    # model's right No takes the confirmation and ONE meaning call ("no"): written, assumed, 2 calls
    ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration"), pick=pick_faithful("No", "No"))
    a, out = _one(_pf("c", CONFLICT, options=YN), ask)
    assert _shown(a) == "No" and a.assumed and len(ask.picks) == 2, _what(a)


@needs(*NEEDS)
def test_d1b_a_question_that_is_not_a_declaration_is_never_turned_into_no():
    # A1 (design 17.2 `other`, review C3, ruling R-a): "Have you ever been dismissed from
    # employment?" is NO LONGER unclassed: an adverse-history frame + the noun "dismissed" is the
    # code key of `declaration:other`, so a Yes is never written (the pre-amendment pin kept it).
    # D-212 U2-U4 (replaces "both keys: code writes the owner's No"; "one key: pick No / '' / Yes"):
    # the model's Yes differs from the reader's No, with both keys or one: ONE confirmation. Pick No -> No,
    # assumed, standing kept, note "the AI answered Yes"; unusable -> empty; pick Yes (sides with the
    # model) -> the meaning call, which needs "no" to write the Yes; otherwise empty. Never an unchecked Yes.
    for klass in (None, "ordinary"):
        mk = lambda pick: FakeAsk(lambda v: say("Yes", "default", "default:no_declaration", klass=klass), pick=pick)   # noqa: E731
        ask = mk(pick_by("No", ""))
        a, out = _one(_pf("d", "Have you ever been dismissed from employment?", options=YN), ask)
        assert _shown(a) == "No" and a.assumed and len(ask.picks) == 1, (klass, "dismissed", _what(a), len(ask.picks))
        assert "d" in out.standing_kept and "the AI answered Yes" in (a.note + " " + a.evidence), (a.note, a.evidence)
        # U10 (fix8): "Have you ever been dismissed ..." is a canonical frame: a confirming Yes is a veto, no meaning call
        for pick, meaning, calls in (("", "", 1), ("Yes", "", 1), ("Yes", "yes", 1)):
            ask = mk(pick_by(pick, meaning))
            a, _ = _one(_pf("d", "Have you ever been dismissed from employment?", options=YN), ask)
            assert _shown(a) == "" and len(ask.picks) == calls, (klass, pick, meaning, _what(a), len(ask.picks))
    # ruling 3+4 kept: a certification is not an adverse declaration. The owner's certify_true
    # (sample: true) answers it: Yes, from that profile row, not assumed; never No.
    for said in ("Yes", "No"):
        a, out = _one(_pf("d", "Do you declare that the above is true?", options=YN),
                      FakeAsk(lambda v, s=said: say(s, "default", "default:no_declaration")))
        assert _shown(a) == "Yes" and a.source == "profile:consents.certify_true" and not a.assumed,             (said, _what(a))
    # an acknowledgement of a policy is Yes, never No (design 17.2: of anything but a privacy notice
    # it follows `consents.certify_true`; the sample has it true -> from that row, not assumed;
    # unset -> the D5 default, assumed). The model's No is kept as a note.
    for said in ("Yes", "No"):
        a, out = _one(_pf("p", "Have you read our conflict of interest policy?", options=YN),
                      FakeAsk(lambda v, s=said: say(s, "default", "default:no_declaration")))
        assert _shown(a) == "Yes" and not a.assumed and a.source == "profile:consents.certify_true", (said, _what(a))
        assert ("p" in out.standing_kept) is (said == "No"), (said, out.standing_kept)
        unset = _profile()
        unset["consents"].pop("certify_true")
        a, out = _one(_pf("p", "Have you read our conflict of interest policy?", options=YN),
                      FakeAsk(lambda v, s=said: say(s, "default", "default:no_declaration")), unset)
        assert _shown(a) == "Yes" and a.assumed and a.source == "default:consent", (said, "unset", _what(a))


@needs(*NEEDS)
def test_d1b_a_declaration_the_owner_says_yes_to_is_flagged_never_rewritten():
    """D-212 U1-U3 (replaces "the model's No stays, marked assumed"): the owner's truth is Yes. The model's Yes
    equals the reader's option: written, no call, not assumed. The model's No differs: ONE confirmation, a
    pick Yes writes Yes (assumed); an unusable pick -> empty. A pick No (sides with the model) -> the meaning
    call; only "no" writes the No (assumed, three-call note)."""
    p = _profile(declarations__conflict_audit_independence=True)
    # U9: CONFLICT has no reading, so even the model's right Yes takes the confirmation (Yes = the truth) and ONE
    # meaning call ("no": it does not state that no conflict exists): written, assumed, 2 calls. A model No with the
    # truth's Yes as the confirmation: the meaning call on BOTH values (U8b, 3 calls) then Yes.
    ask = FakeAsk(lambda v: say("Yes", "default", "default:no_declaration"), pick=pick_faithful("Yes", "Yes"))
    a2, _ = _one(_pf("c", CONFLICT, options=YN), ask, p)
    assert _shown(a2) == "Yes" and a2.assumed and len(ask.picks) == 2, _what(a2)
    ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration"), pick=pick_faithful("Yes", "Yes"))
    a, _ = _one(_pf("c", CONFLICT, options=YN), ask, p)
    assert _shown(a) == "Yes" and a.assumed and len(ask.picks) == 3, _what(a)
    for pick, meaning, want, calls in (("", "", "", 1), ("No", "", "", 2), ("No", "yes", "", 2), ("No", "no", "No", 2)):
        ask = FakeAsk(lambda v: say("No", "default", "default:no_declaration"), pick=pick_by(pick, meaning))
        a, _ = _one(_pf("c", CONFLICT, options=YN), ask, p)
        assert _shown(a) == want and len(ask.picks) == calls and (not want or a.assumed), (pick, meaning, _what(a), len(ask.picks))


@needs(*NEEDS)
def test_d1b_the_other_code_built_rules_also_beat_a_contradicting_model():
    # D5 (the owner refuses the consent), D9 (willing_to_relocate false), D10 (health: No)
    # ruling A: a required box the owner refuses is never ticked and the attempt stops
    res = _stop_or_answer(_pf("pc", "I consent to the processing of my personal data", "CHECKBOX"),
                          FakeAsk(lambda v: say("true", "default", "default:consent")),
                          _profile(consents__privacy_consent=False))
    assert _is_refusal_stop(res, "privacy_consent"), ("D5", _what(res))
    a, _ = _one(_pf("pc", "I consent to the processing of my personal data", "CHECKBOX", required=False),
                FakeAsk(lambda v: say("true", "default", "default:consent")),
                _profile(consents__privacy_consent=False))
    assert not _tick(a), ("D5 optional", _what(a))
    a, out = _one(_pf("rl", "Are you willing to relocate?", options=YN),
                  FakeAsk(lambda v: say("Yes", "default", "default:willing")),
                  _profile(availability__willing_to_relocate=False))
    assert _shown(a) == "No" and a.assumed and "default:willing" in a.source, ("D9", _what(a))


@needs(*NEEDS)
def test_d1b_d10_a_health_question_the_model_answers_yes_gets_one_confirmation_and_the_owners_no():
    """D-212 U2 / U3 / U4 (replaces "code writes the owner's No for health"): health is a declaration, so the
    model's Yes (it differs from the reader's No) gets ONE confirmation call stating the owner's truth. Pick
    No -> No, assumed. An unusable pick, or one that sides with the Yes (health has no contradiction
    statement, so no meaning call is possible) -> empty. Never an unchecked Yes.
    DEFECT while red: `declaration:health` has no `truth_text`, so NO confirmation is asked (0 calls) and
    the required question always ends empty for the site."""
    label = "Do you have a health condition that affects your work?"
    ask = FakeAsk(lambda v: say("Yes", "default", "default:health"), pick=pick_by("No", ""))
    a, out = _one(_pf("h", label, options=YN), ask)
    assert _shown(a) == "No" and a.assumed and len(ask.picks) == 1, ("D10", _what(a), len(ask.picks))
    for pick in ("", "Yes"):
        ask = FakeAsk(lambda v: say("Yes", "default", "default:health"), pick=pick_by(pick, "no"))
        a, out = _one(_pf("h", label, options=YN), ask)
        assert _shown(a) == "" and len(ask.picks) <= 1, ("D10", pick, _what(a), len(ask.picks))


# ------------------------------------------------------------------ D2: marketing

MARKETING = (("Would you like to receive our marketing communications?", "RADIO"),
             ("Subscribe to our newsletter", "CHECKBOX"),
             ("I would like to receive promotional offers", "CHECKBOX"),
             ("Would you like to join our talent community?", "RADIO"),
             ("Join our talent pool", "RADIO"),
             ("Add me to your mailing list", "CHECKBOX"),
             ("Sign me up for job alerts", "CHECKBOX"),
             ("I agree to receive marketing emails about future roles", "CHECKBOX"),
             ("Do you agree to receive marketing emails about future roles?", "RADIO"))


@needs(*NEEDS)
def test_d2_a_marketing_word_follows_talent_pool_opt_in_whatever_the_model_says():
    bad = []
    for label, kind in MARKETING:
        for opt_in in (False, True):
            for required in (True, False):
                p = _profile(consents__talent_pool_opt_in=opt_in)
                field = _pf("m", label, kind, required=required, options=YN if kind == "RADIO" else ())
                # the model says the opposite, citing the retention row (the old bug's source)
                ask = FakeAsk(lambda v, o=opt_in, k=kind: _say_bool(
                    k, not o, "profile", "profile:consents.data_retention_consent"))
                a, _ = _one(field, ask, p)
                if _tick(a) is not opt_in:
                    bad.append((label, f"opt_in={opt_in}", f"required={required}", _what(a)))
    assert not bad, bad


@needs(*NEEDS)
def test_d2_marketing_emails_about_future_roles_is_not_ticked_by_the_retention_row():
    label = "I agree to receive marketing emails about future roles"
    for required in (True, False):
        a, _ = _one(_pf("m", label, "CHECKBOX", required=required),
                    FakeAsk(lambda v: say("true", "profile", "profile:consents.data_retention_consent")))
        assert not _tick(a), (required, "model ticked from the retention row", _what(a))
    a, _ = _one(_pf("m", label, "CHECKBOX"), FakeAsk())                     # silent: F0 must not tick it
    assert not _tick(a), ("silent", _what(a))
    a, _ = _one(_pf("m", label, "CHECKBOX"), FakeAsk(), _profile(consents__talent_pool_opt_in=True))
    assert _tick(a), ("opted in, silent", _what(a))


@needs(*NEEDS)
def test_d2_a_marketing_tick_is_undone_whatever_basis_the_model_cites():
    bases = (("default", "default:consent"), ("default", "default:talent_pool"),
             ("profile", "profile:consents.data_retention_consent"),
             ("profile", "profile:consents.privacy_consent"), ("assumption", ""))
    label = "Subscribe to our newsletter"
    for basis, ref in bases:
        ask = FakeAsk(lambda v, b=basis, r=ref: say("true", b, r, b == "assumption"))
        for required in (True, False):
            a, _ = _one(_pf("m", label, "CHECKBOX", required=required), ask)
            assert not _tick(a), (basis, ref, required, _what(a))
        # ruling 4: the sample sets talent_pool_opt_in: false, so the profile row answers it:
        # unticked, that source, not assumed, the model's tick a note
        a, out = _one(_pf("m", label, "CHECKBOX", required=False), ask)
        assert a.value == "false" and a.source == "profile:consents.talent_pool_opt_in"             and not a.assumed and "m" in out.standing_kept, (basis, ref, _what(a))
    # control: with the key UNSET the D2 default still undoes the tick, marked assumed
    unset = _profile()
    unset["consents"].pop("talent_pool_opt_in")
    for basis, ref in bases:
        a, _ = _one(_pf("m", label, "CHECKBOX", required=False),
                    FakeAsk(lambda v, b=basis, r=ref: say("true", b, r, b == "assumption")), unset)
        assert not _tick(a) and a.assumed, (basis, ref, "unset key", _what(a))


@needs(*NEEDS)
def test_d2_last_resort_alone_answers_marketing_from_the_opt_in_not_the_retention_row():
    bad = []
    for label, kind in MARKETING:
        for opt_in in (False, True):
            st = _lr(_pf("m", label, kind, options=YN if kind == "RADIO" else ()),
                     _profile(consents__talent_pool_opt_in=opt_in))
            ticked = st.usable and (st.value == "true" or tuple(st.labels) == ("Yes",))
            if ticked is not opt_in:
                bad.append((label, f"opt_in={opt_in}", st.usable, st.value, st.labels, st.note))
    assert not bad, bad


@needs(*NEEDS)
def test_d2_a_pure_retention_consent_still_follows_data_retention_consent():
    box = "I agree that you keep my details on file for future roles"
    ask_q = "May we keep your details on file for future roles?"
    bad = []
    for ret in (True, False):
        for opt_in in (True, False):                   # the marketing key must not leak into it
            p = _profile(consents__data_retention_consent=ret, consents__talent_pool_opt_in=opt_in)
            res = _stop_or_answer(_pf("r", box, "CHECKBOX"), FakeAsk(), p)      # required (the default)
            if ret and not (not isinstance(res, Exception) and _tick(res)):
                bad.append(("checkbox", "retention=True", f"opt_in={opt_in}", _what(res)))
            if not ret and not _is_refusal_stop(res, "data_retention_consent"):    # ruling A: stop
                bad.append(("checkbox", "retention=False", f"opt_in={opt_in}", _what(res)))
            if not ret:                                                         # optional: unticked, no stop
                res = _stop_or_answer(_pf("r", box, "CHECKBOX", required=False),
                                      FakeAsk(lambda v: say("true", "default", "default:consent")), p)
                if isinstance(res, Exception) or _tick(res):
                    bad.append(("optional checkbox", "retention=False", f"opt_in={opt_in}", _what(res)))
            a, _ = _one(_pf("r", ask_q, options=YN), FakeAsk(), p)
            if _shown(a) != ("Yes" if ret else "No"):
                bad.append(("radio", f"retention={ret}", f"opt_in={opt_in}", _what(a)))
    assert not bad, bad


@needs(*NEEDS)
def test_d2_negative_control_a_retention_consent_without_a_marketing_word_is_ticked():
    box = "I agree that you keep my details on file for future roles"
    a, _ = _one(_pf("r", box, "CHECKBOX"),
                FakeAsk(lambda v: say("true", "profile", "profile:consents.data_retention_consent")))
    assert _tick(a) and not a.assumed, _what(a)
    a, _ = _one(_pf("r", box, "CHECKBOX"), FakeAsk())
    assert _tick(a) and a.source == "profile:consents.data_retention_consent" and not a.assumed, _what(a)


@needs(*NEEDS)
def test_d2_does_not_reach_a_consent_that_has_no_marketing_word():
    a, _ = _one(_pf("pc", "I consent to the processing of my personal data", "CHECKBOX"), FakeAsk())
    assert _tick(a), _what(a)
    a, out = _one(_pf("pn", "Do you agree to our privacy notice?", options=YN),
                  FakeAsk(lambda v: say("Yes", "default", "default:consent")))
    assert _shown(a) == "Yes" and not a.assumed and not out.standing_kept, _what(a)


# ------------------------------------------------------------------ Q1: owner-only facts

DOB_BASES = (("assumption", ""), ("default", "default:no_declaration"), ("job", ""), ("unknown", ""),
             ("resume", ""), ("profile", "profile:identity.date_of_birth"), ("extra", "extra:nope"))


@needs(*NEEDS)
def test_q1_a_model_date_of_birth_without_a_verified_basis_stops_never_todays_date():
    p = _profile(identity__date_of_birth=None)
    bad = []
    for type_name in ("DATE", "TEXT"):
        for basis, ref in DOB_BASES:
            res = _stop_or_answer(_pf("dob", "Date of birth", type_name),
                                  FakeAsk(lambda v, b=basis, r=ref: say("2026-11-12", b, r, b == "assumption")), p)
            if not _is_stop(res, "date of birth", "identity.date_of_birth"):
                bad.append((type_name, basis, ref, _what(res)))
    assert not bad, bad
    res = _stop_or_answer(_pf("dob", "Date of birth", "DATE"), FakeAsk(), p)      # model silent: F1
    assert _is_stop(res, "date of birth", "identity.date_of_birth"), _what(res)


@needs(*NEEDS)
def test_q1_a_date_of_birth_citing_a_computed_date_fact_still_stops():
    # A "standing:" ref can be made to match (today's date IS standing:today) but it is
    # not the owner's date of birth: no basis in the profile or resume.
    p = _profile(identity__date_of_birth=None)
    bad = []
    for type_name in ("DATE", "TEXT"):
        for ref in ("standing:today", "standing:earliest_start"):
            res = _stop_or_answer(_pf("dob", "Date of birth", type_name),
                                  FakeAsk(lambda v, r=ref: say("2026-11-12", "standing", r)), p)
            if not _is_stop(res, "date of birth", "identity.date_of_birth"):
                bad.append((type_name, ref, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_q1_a_date_of_birth_in_the_profile_is_filled_and_the_models_other_date_discarded():
    for type_name in ("DATE", "TEXT"):
        for basis, ref in (("profile", "profile:identity.date_of_birth"), ("assumption", "")):
            a, _ = _one(_pf("dob", "Date of birth", type_name),
                        FakeAsk(lambda v, b=basis, r=ref: say("1999-01-01", b, r, b == "assumption")))
            assert a.value == "2002-03-14" and a.source == "profile:identity.date_of_birth", (type_name, basis, _what(a))
        a, _ = _one(_pf("dob", "Date of birth", type_name),
                    FakeAsk(lambda v: say("2002-03-14", "profile", "profile:identity.date_of_birth")))
        assert a.value == "2002-03-14" and not a.assumed, (type_name, _what(a))


def _no_grade_profile():
    p = _profile()
    p["education"][0]["grade"] = None
    p["education"][0]["grade_scale"] = None
    return p


NO_GRADE_RESUME = "Alex Testcase\nNanyang Example University, Bachelor of Engineering, 2021 - 2025\n"
GRADE_RESUME = NO_GRADE_RESUME + "CGPA 3.85 / 4.00\n"


@needs(*NEEDS)
def test_q1_an_invented_grade_stops_a_number_field_and_is_never_written():
    p = _no_grade_profile()
    bad = []
    for basis, ref in (("assumption", ""), ("resume", ""), ("profile", "profile:education[0].grade"),
                       ("default", "default:how_heard"), ("job", ""), ("unknown", "")):
        res = _stop_or_answer(_pf("gpa", "Cumulative GPA", "NUMBER"),
                              FakeAsk(lambda v, b=basis, r=ref: say("3.9", b, r, b == "assumption")), p,
                              rctx_kw={"resume_text": NO_GRADE_RESUME})
        if not _is_stop(res, "grade", "education[0].grade"):
            bad.append((basis, ref, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_q1_the_stale_gpa_case_an_unset_profile_ref_no_longer_writes_the_invented_grade():
    # the old pin: TEXT "GPA", grade unset, model "3.8" citing the unset ref -> "3.8" assumed.
    # Now the invented grade is discarded and the last resort writes the resume's grade.
    p = _profile()
    p["education"][0]["grade"] = None
    a, out = _one(_pf("gpa", "GPA", "TEXT"),
                  FakeAsk(lambda v: say("3.8", "profile", "profile:education[0].grade")), p)
    assert a.value == "4.20 / 5.00" and a.assumed and a.source == "fallback:F4", _what(a)
    assert "gpa" in out.assumed and "3.8" not in str(a.value)


@needs(*NEEDS)
def test_q1_a_text_grade_field_gets_the_resumes_grade_or_na_never_an_invented_figure():
    p = _no_grade_profile()
    invented = FakeAsk(lambda v: say("3.9", "assumption", "", True, "x"))
    a, _ = _one(_pf("gpa", "Cumulative GPA", "TEXT"), invented, p, rctx_kw={"resume_text": NO_GRADE_RESUME})
    assert a.value == "N/A" and a.assumed, ("resume has none", _what(a))
    a, _ = _one(_pf("gpa", "Cumulative GPA", "TEXT"), FakeAsk(), p, rctx_kw={"resume_text": NO_GRADE_RESUME})
    assert a.value == "N/A" and a.assumed, ("silent, resume has none", _what(a))
    a, _ = _one(_pf("gpa", "Cumulative GPA", "TEXT"), FakeAsk(), p, rctx_kw={"resume_text": GRADE_RESUME})
    assert a.value == "3.85 / 4.00" and a.assumed and a.source == "fallback:F4", ("silent", _what(a))
    a, _ = _one(_pf("gpa", "Cumulative GPA", "TEXT"), invented, p, rctx_kw={"resume_text": GRADE_RESUME})
    assert a.value == "3.85 / 4.00" and a.assumed, ("invented 3.9 beside a resume grade", _what(a))


@needs(*NEEDS)
def test_q1_a_grade_on_the_resume_cited_as_resume_is_filled_not_assumed():
    p = _no_grade_profile()
    for type_name in ("NUMBER", "TEXT"):
        a, _ = _one(_pf("gpa", "Cumulative GPA", type_name),
                    FakeAsk(lambda v: say("3.85", "resume", "")), p, rctx_kw={"resume_text": GRADE_RESUME})
        assert str(a.value) == "3.85" and a.source == "resume" and not a.assumed, (type_name, _what(a))
    a, _ = _one(_pf("gpa", "Cumulative GPA", "NUMBER"), FakeAsk(), p, rctx_kw={"resume_text": GRADE_RESUME})
    assert str(a.value) == "3.85", _what(a)                       # silent: the resume's grade, no stop


@needs(*NEEDS)
def test_q1_a_grade_present_in_the_profile_is_filled_without_a_stop():
    # negative control: nothing here may stop or be replaced
    for type_name in ("NUMBER", "TEXT"):
        a, _ = _one(_pf("gpa", "Cumulative GPA", type_name),
                    FakeAsk(lambda v: say("4.20", "profile", "profile:education[0].grade")))
        assert str(a.value) == "4.20" and a.source == "profile:education[0].grade" and not a.assumed, \
            (type_name, _what(a))
        a, _ = _one(_pf("gpa", "Cumulative GPA", type_name), FakeAsk())
        assert str(a.value).startswith("4.20"), (type_name, "silent", _what(a))
    # fix2 B (replaces "a choice list is not a numeric fact: a model pick stands"): a grade list is written
    # only when one option holds the profile's (or the resume's) grade. With no grade anywhere an invented
    # "First Class" is never written: required -> the owner-fact stop, optional -> empty.
    opts = ("First Class", "Second Upper", "Other")
    for required in (True, False):
        res = _stop_or_answer(_pf("g", "Grade", "DROPDOWN", options=opts, required=required),
                              FakeAsk(lambda v: say("First Class", "assumption", "", True, "x")), _no_grade_profile())
        if required:
            assert _is_stop(res, "grade"), ("required, no grade", _what(res))
        else:
            assert not hasattr(res, "reason") and _shown(res) == "", ("optional, no grade", _what(res))
    # a band that holds the profile's 4.20 is written
    a, _ = _one(_pf("g", "Grade", "DROPDOWN", options=("3.0 - 3.9", "4.0 - 4.5", "Other")),
                FakeAsk(lambda v: say("4.0 - 4.5", "assumption", "", True, "x")))
    assert _shown(a) == "4.0 - 4.5", _what(a)


@needs(*NEEDS)
def test_q1_a_salary_figure_needs_the_profile_else_the_application_stops():
    p = _profile()
    p["pay"] = {}
    bad = []
    for type_name in ("NUMBER", "TEXT"):
        for basis, ref in (("assumption", ""), ("profile", "profile:pay.expected_salary"), ("job", "")):
            res = _stop_or_answer(_pf("sal", "Expected salary", type_name),
                                  FakeAsk(lambda v, b=basis, r=ref: say("5000", b, r, b == "assumption")), p)
            if not _is_stop(res, "expected salary", "pay.expected_salary"):
                bad.append((type_name, basis, ref, _what(res)))
    assert not bad, bad
    # control: the profile's figure is filled, a model's different figure is discarded for it
    a, _ = _one(_pf("sal", "Expected salary", "NUMBER"),
                FakeAsk(lambda v: say("5000", "profile", "profile:pay.expected_salary")))
    assert str(a.value) == "5000" and a.source == "profile:pay.expected_salary" and not a.assumed, _what(a)
    a, _ = _one(_pf("sal", "Expected salary", "NUMBER"), FakeAsk(lambda v: say("9999", "assumption", "", True, "x")))
    assert str(a.value) == "5000", _what(a)


@needs(*NEEDS)
def test_q1_national_id_passport_and_bank_details_stop_for_the_owner():
    bad = []
    for label, fact in (("NRIC number", "national ID number"), ("National ID number", "national ID number"),
                        ("Passport number", "passport number"), ("Bank account number", "bank details")):
        for name, ask in (("model invented", FakeAsk(lambda v: say("S9999999Z", "assumption", "", True, "x"))),
                          ("model cited a profile ref", FakeAsk(lambda v: say("S9999999Z", "profile", "profile:identity.nric"))),
                          ("model silent", FakeAsk())):
            res = _stop_or_answer(_pf("idf", label, "TEXT"), ask)
            if not _is_stop(res, fact):
                bad.append((label, name, _what(res)))
    assert not bad, bad


# ------------------------------------------------------------------ Q2 + rulings 1-2: work rights

_LABEL = {"auth": "Are you legally authorised to work in {}?",
          "spon": "Will you now or in the future require visa sponsorship to work in {}?",
          "nosp": "Can you work in {} without visa sponsorship?"}
SG, US, DE = "Singapore", "the United States", "Germany"


def _check_rows(edits: dict, rows: list[tuple]) -> None:
    """Each row (kind, country, wanted, source tail, assumed) is the owner's work-rights truth (D-209 (2)).
    D-212 U / W (replaces "code writes the truth over a wrong or silent model"): code never writes its own
    reading on its own authority. Per row, four runs:
      - the model RIGHT: written, ZERO calls (U1);
      - the model WRONG and the confirmation names the truth: the truth option, from that row's source,
        marked assumed, ONE call (U2 / U3);
      - the model SILENT, the same;
      - the model WRONG and an unusable confirmation: empty, never the wrong value (U4).
    The `derived` rows (the assumed "No" for a country with no row) are not firm: they get the same four
    runs but the source tail is not asserted for the model-right run."""
    p = _profile(**edits)
    bad = []
    for kind, country, want, tail, assumed in rows:
        label = _LABEL[kind].format(country)
        wrong = "No" if want == "Yes" else "Yes"
        source = "profile:singapore_status." + tail
        if kind == "nosp":
            # "... without visa sponsorship?": the reader has no reading of the negation (U6): even a RIGHT
            # model costs the confirmation and a meaning call ("no" = the value does not contradict the
            # truth); the differing-confirmation cells are U8's (test_always_a1_u::test_u8_*)
            ask = FakeAsk(lambda v: say(want, "default", "default:work_rights"), pick=pick_by(want, "no"))
            a, _ = _one(_pf("wr", label, options=YN), ask, p)
            if _shown(a) != want or not a.assumed or len(ask.picks) != 2:
                bad.append(("no reading, model right", label, _shown(a), len(ask.picks)))
            ask = FakeAsk(lambda v: say(wrong, "default", "default:work_rights"), pick=pick_by("", ""))
            a, _ = _one(_pf("wr", label, options=YN), ask, p)
            if _shown(a) != "":
                bad.append(("no reading, model wrong, unusable confirmation", label, _shown(a), len(ask.picks)))
            continue
        ask = FakeAsk(lambda v: say(want, "default", "default:work_rights"), pick=pick_by("Yes" if want == "Yes" else "No", ""))
        a, _ = _one(_pf("wr", label, options=YN), ask, p)
        if _shown(a) != want or ask.picks:
            bad.append(("model right", label, _shown(a), len(ask.picks)))
        for who, mk in (("model wrong", lambda: FakeAsk(lambda v: say(wrong, "default", "default:work_rights"), pick=pick_by(want, ""))),
                        ("model silent", lambda: FakeAsk(pick=pick_by(want, "")))):
            ask = mk()
            a, _ = _one(_pf("wr", label, options=YN), ask, p)
            got = (_shown(a), a.source, bool(a.assumed), len(ask.picks))
            wanted = (want, source, True, 1)
            if got != wanted:
                bad.append((who, label, got, wanted))
        ask = FakeAsk(lambda v: say(wrong, "default", "default:work_rights"), pick=pick_by("", ""))
        a, _ = _one(_pf("wr", label, options=YN), ask, p)
        if _shown(a) != "" or len(ask.picks) != 1:
            bad.append(("model wrong, unusable confirmation", label, _shown(a), len(ask.picks)))
    assert not bad, bad


NAT = "nationality"


@needs(*NEEDS)
def test_q2_the_nationality_country_without_a_row_is_authorised_and_needs_no_sponsorship():
    _check_rows(dict(singapore_status__authorised_to_work={"US": False}, singapore_status__requires_sponsorship={}), [
        ("auth", SG, "Yes", NAT, False), ("spon", SG, "No", NAT, False), ("nosp", SG, "Yes", NAT, False),
        ("auth", US, "No", "authorised_to_work.US", False), ("spon", US, "Yes", "authorised_to_work.US", False),
        ("auth", DE, "No", "authorised_to_work.derived", True), ("spon", DE, "Yes", "authorised_to_work.derived", True),
        ("nosp", DE, "No", "authorised_to_work.derived", True)])


@needs(*NEEDS)
def test_q2_an_explicit_false_row_for_the_nationality_wins_and_sponsorship_follows_it():
    _check_rows(dict(singapore_status__authorised_to_work={"SG": False}, singapore_status__requires_sponsorship={}), [
        ("auth", SG, "No", "authorised_to_work.SG", False), ("spon", SG, "Yes", "authorised_to_work.SG", False),
        ("auth", DE, "No", "authorised_to_work.derived", True), ("spon", DE, "Yes", "authorised_to_work.derived", True)])


@needs(*NEEDS)
def test_q2_the_sample_profiles_own_rows_and_an_unlisted_country():
    _check_rows({}, [          # authorised_to_work {SG: true, US: false}, requires_sponsorship {SG: false}
        ("auth", SG, "Yes", "authorised_to_work.SG", False), ("spon", SG, "No", "requires_sponsorship.SG", False),
        ("auth", US, "No", "authorised_to_work.US", False), ("spon", US, "Yes", "authorised_to_work.US", False),
        ("auth", DE, "No", "authorised_to_work.derived", True), ("spon", DE, "Yes", "authorised_to_work.derived", True),
        ("nosp", SG, "Yes", "authorised_to_work.SG", False), ("nosp", US, "No", "authorised_to_work.US", False),
        ("nosp", DE, "No", "authorised_to_work.derived", True)])


@needs(*NEEDS)
def test_q2_not_authorised_means_sponsorship_yes_even_when_the_default_sponsorship_row_says_no():
    # the sponsorship `default` row may answer a country the owner IS authorised in, never one
    # they are not authorised in
    _check_rows(dict(singapore_status__authorised_to_work={"SG": True, "US": False},
                     singapore_status__requires_sponsorship={"default": False}), [
        ("spon", SG, "No", "requires_sponsorship.default", False),
        ("spon", US, "Yes", "authorised_to_work.US", False),
        ("spon", DE, "Yes", "authorised_to_work.derived", True)])
    _check_rows(dict(singapore_status__authorised_to_work={"SG": False},
                     singapore_status__requires_sponsorship={"default": False}), [
        ("auth", SG, "No", "authorised_to_work.SG", False),
        ("spon", SG, "Yes", "authorised_to_work.SG", False),
        ("spon", US, "Yes", "authorised_to_work.derived", True)])
    _check_rows(dict(singapore_status__authorised_to_work={"SG": True, "default": False},
                     singapore_status__requires_sponsorship={"SG": False, "default": False}), [
        ("auth", DE, "No", "authorised_to_work.default", False),
        ("spon", DE, "Yes", "authorised_to_work.default", False)])


@needs(*NEEDS)
def test_q2_default_rows_answer_an_unlisted_country_and_the_nationality_beats_them():
    _check_rows(dict(singapore_status__authorised_to_work={"default": True},
                     singapore_status__requires_sponsorship={"default": False}), [
        ("auth", DE, "Yes", "authorised_to_work.default", False), ("spon", DE, "No", "requires_sponsorship.default", False),
        ("auth", US, "Yes", "authorised_to_work.default", False), ("spon", US, "No", "requires_sponsorship.default", False),
        ("auth", SG, "Yes", NAT, False), ("spon", SG, "No", NAT, False)])


@needs(*NEEDS)
def test_q2_the_nationality_needs_no_sponsorship_even_with_a_default_sponsorship_true():
    _check_rows(dict(singapore_status__authorised_to_work={"US": False},
                     singapore_status__requires_sponsorship={"default": True}), [
        ("spon", SG, "No", NAT, False), ("auth", SG, "Yes", NAT, False),
        ("spon", US, "Yes", "authorised_to_work.US", False), ("spon", DE, "Yes", "authorised_to_work.derived", True)])
    # and where the owner IS authorised elsewhere via a default row, that default sponsorship
    # row does apply (it is only the nationality it cannot override)
    _check_rows(dict(singapore_status__authorised_to_work={"US": True},
                     singapore_status__requires_sponsorship={"default": True}), [
        ("spon", US, "Yes", "requires_sponsorship.default", False), ("spon", SG, "No", NAT, False)])


@needs(*NEEDS)
def test_q2_an_explicit_row_always_wins_over_a_derivation():
    _check_rows(dict(singapore_status__authorised_to_work={"US": False},
                     singapore_status__requires_sponsorship={"SG": True}), [
        ("spon", SG, "Yes", "requires_sponsorship.SG", False),       # beats "the nationality needs none"
        ("auth", SG, "Yes", NAT, False)])
    _check_rows(dict(singapore_status__authorised_to_work={"SG": True, "DE": True},
                     singapore_status__requires_sponsorship={}), [
        ("auth", DE, "Yes", "authorised_to_work.DE", False)])        # beats "an unlisted country: no"


@needs(*NEEDS)
def test_q2_not_authorised_but_needs_no_sponsorship_is_never_written():
    profiles = ({}, dict(singapore_status__authorised_to_work={"US": False}, singapore_status__requires_sponsorship={}),
                dict(singapore_status__authorised_to_work={"SG": False}, singapore_status__requires_sponsorship={}),
                dict(singapore_status__authorised_to_work={"SG": True, "US": False},
                     singapore_status__requires_sponsorship={"default": False}),
                dict(singapore_status__authorised_to_work={"default": False}, singapore_status__requires_sponsorship={"default": False}),
                dict(singapore_status__authorised_to_work={"US": False}, singapore_status__requires_sponsorship={"default": True}))
    bad = []
    for edits in profiles:
        p = _profile(**edits)
        for country in (SG, US, DE):
            own_sponsorship_row = bool((p["singapore_status"]["requires_sponsorship"] or {}).get(
                {SG: "SG", US: "US", DE: "DE"}[country]) is not None)
            if own_sponsorship_row:
                continue                   # an explicit row is the owner's own word
            auth, _ = _one(_pf("a", _LABEL["auth"].format(country), options=YN), FakeAsk(), p)
            spon, _ = _one(_pf("s", _LABEL["spon"].format(country), options=YN), FakeAsk(), p)
            if _shown(auth) == "No" and _shown(spon) == "No":
                bad.append((edits, country))
    assert not bad, bad


# ------------------------------------------------------------------ ruling 3: the briefing

@needs("jobscraper.apply.briefing:build")
def test_r3_the_consent_line_says_keeping_details_for_future_roles_only_when_retention_is_true():
    tail = "Keeping your details on file to be considered for future roles or openings: "
    for value, word in ((True, "yes"), (False, "no"), ("UNSET", "no")):
        p = _profile_for_briefing()
        if value == "UNSET":
            p["consents"].pop("data_retention_consent", None)
        else:
            p["consents"]["data_retention_consent"] = value
        b, _ = _build(p)
        line = _lines(b.text)["default:consent"]
        assert tail + word + "." in line, (value, line[-160:])
        assert tail + ("no" if word == "yes" else "yes") + "." not in line, (value, line[-160:])


def _profile_for_briefing() -> dict:
    from test_always_briefing import _profile as briefing_profile
    return briefing_profile()


@needs("jobscraper.apply.briefing:build")
def test_r3_the_marketing_line_lists_no_future_roles_and_says_a_mixed_question_is_marketing():
    for opt_in, word in ((False, "No."), (True, "Yes (the profile opts in).")):
        p = _profile_for_briefing()
        p["consents"]["talent_pool_opt_in"] = opt_in
        b, _ = _build(p)
        line = _lines(b.text)["default:talent_pool"]
        listed, _, rest = line.partition("A question that mixes")
        assert "future roles" not in listed, listed
        assert "newsletter" in listed and "talent community" in listed and "job alerts" in listed, listed
        assert listed.rstrip().endswith(word), (opt_in, listed[-60:])
        assert "marketing question" in rest and "future roles" in rest, line   # the mixed example is named


@needs("jobscraper.apply.briefing:build")
def test_r3_the_briefing_has_a_line_for_the_nationality_country_when_no_map_lists_it():
    p = _profile_for_briefing()
    p["singapore_status"]["authorised_to_work"] = {"US": False}
    p["singapore_status"]["requires_sponsorship"] = {}
    b, _ = _build(p)
    L = _lines(b.text)
    assert "standing:work_rights.SG" in L and "standing:work_rights.SG" in b.refs, sorted(L)
    sg = L["standing:work_rights.SG"]
    assert "has the right to work (no row: a citizen of this country)" in sg, sg
    assert "needs no visa sponsorship (no row: a citizen of this country)" in sg, sg
    assert "own row" not in sg, sg
    us = L["standing:work_rights.US"]
    assert "does not have the right to work (own row)" in us and "needs visa sponsorship (no row: follows the right to work)" in us, us
    other = L["standing:work_rights.other"]
    assert "does not have the right to work (no row: assumed)" in other and "needs visa sponsorship (no row: assumed)" in other, other
    d3 = L["default:work_rights"]
    assert "A sponsorship question follows the right to work" in d3, d3
    # control: a country a map DOES list keeps its own-row wording, never the citizen wording
    p2 = _profile_for_briefing()
    b2, _ = _build(p2)
    sg2 = _lines(b2.text)["standing:work_rights.SG"]
    assert "a citizen of this country" not in sg2 and "own row" in sg2, sg2


@needs("jobscraper.apply.briefing:build")
def test_r3_a_default_row_prints_as_the_every_other_country_row():
    p = _profile_for_briefing()
    p["singapore_status"]["authorised_to_work"] = {"default": True, "US": False}
    p["singapore_status"]["requires_sponsorship"] = {"default": False}
    b, _ = _build(p)
    other = _lines(b.text)["standing:work_rights.other"]
    assert "has the right to work (every-other-country row)" in other, other
    assert "needs no visa sponsorship (every-other-country row)" in other, other
