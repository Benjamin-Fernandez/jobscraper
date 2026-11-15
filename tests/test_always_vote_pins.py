"""Q-121 always-answer pins, fix round 3 (D-208; the Coordinator's rulings A, B, C, D).

A  An explicit false consent is never ticked or answered Yes; a required box with no way to say
   No stops the attempt (`owner_fact_missing`, target `consents.<key>`).
B  An adverse declaration, tentative reader, every matched class false, the model differs: ONE
   confirmation call stating the owner's truth, then two out of three decide; always assumed.
   [A1, design 17.1 / ruling R-f (2): the vote is REPLACED by the two-key table. Both keys + a
   known H -> the owner's option is written (assumed on a tentative reader), no vote call. One
   key, or H unknown -> the model's value is never written; A5, then ONE confirm call whose pick
   is written (assumed) only when it differs from every vetoed value, else the protective end.
   The intent, "a model's wrong Yes on an adverse declaration never goes out", is pinned below for a
   confident reader, a tentative reader and an unknown-polarity wording.]
C  "Understand / agree to our terms | code of conduct | policy" is Yes, assumed, never from
   `privacy_consent`; only privacy / personal data / data protection / PDPA wording follows it.
D  A certification with `certify_true` unset, or an acknowledgement with no key set, is Yes,
   assumed, even when the model says No (its No kept as a note).

The fake model is scripted PER CALL (`VoteAsk`): the field call says the wrong thing, the
confirmation call (the only non-FIELDS call) says what each case needs, and the calls are
counted. Dummy sample profile only; no model, no network, no browser.
Verify: python tests/run_tests.py -k always_vote_pins
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402
from test_always_fill import (  # noqa: E402
    FIELDS_HEAD, NEEDS, YN, FakeAsk, _pf, _profile, _run, say)
from test_always_fix_pins import _is_refusal_stop, _say_bool, _stop_or_answer, _tick, _what  # noqa: E402


class VoteAsk(FakeAsk):
    """Field calls answer `answer(view)`; the confirmation call (no FIELDS block) replies
    `confirm` (a choice string) or raises a transport error when `boom`. Confirmation calls
    are recorded in `confirms` (system + user text)."""

    def __init__(self, answer=None, *, confirm: str = "", boom: bool = False, right: str = ""):
        # `right` (U9 / U8b): when given, a MEANING call about the value V answers what a faithful reader would
        # ("no" for the right value, "yes" for any other); without it every call gets `confirm`
        def pick(q, w, o):
            m = re.search(r"answers «(.*?)» to the question", str(w)) if right else None
            if m:
                return "no" if m.group(1).strip().lower() == right.lower() else "yes"
            return confirm
        super().__init__(answer, pick=pick)
        self.boom = boom
        self.confirms: list[str] = []

    def __call__(self, messages, schema, **kw):
        user = messages[1]["content"]
        if FIELDS_HEAD not in user:
            self.confirms.append(messages[0]["content"] + "\n" + user)
            if self.boom:
                from jobscraper.backends import BackendError
                raise BackendError("the model is unreachable")
        return super().__call__(messages, schema, **kw)


def _vote(label, ask, profile=None, *, options=YN, kind="RADIO", required=True):
    out = _run([_pf("v", label, kind, required=required, options=options)], ask, profile)
    return out.answers["v"], out


def _words(a) -> str:
    return "No" if a.option_labels == ("No",) else "Yes" if a.option_labels == ("Yes",) else str(a.value)


CONFLICT = "Do you declare any conflict of interest?"
WRONG_YES = lambda v: say("Yes", "assumption", "", True, "unsure")  # noqa: E731


# ------------------------------------------------------------------ B: the confirmation vote

READERS = (   # (name, label, the class code reads, the owner's truth for the sample, the adverse value)
    ("confident reader", "Do you have any conflict of interest?", "declaration:conflict_audit_independence", "No", "Yes"),
    ("tentative reader", CONFLICT, "declaration:conflict_audit_independence", "No", "Yes"),
    ("unknown polarity", "Is it untrue that you have never been bankrupt?", "declaration:bankruptcy", "No", "Yes"),
)


@needs(*NEEDS)
def test_b_a_models_wrong_yes_on_an_adverse_declaration_never_goes_out_for_every_reader_class_and_confirm():
    # (old: a_differing_model_answer_gets_one_confirmation_and_two_of_three_decide; the intent kept)
    from always_a1_support import NO_CLASS
    bad = []
    for name, label, klass, truth, adverse in READERS:
        for k in (None, klass, "ordinary", NO_CLASS):
            # ruling P2/P3: a confirmation that AGREES with the model's wrong Yes is written (R3 residual)
            for pick in ("", truth, "Maybe"):
                ask = VoteAsk(lambda v, k=k, a=adverse: say(a, "assumption", "", True, "unsure", klass=k), confirm=pick)
                a, out = _vote(label, ask)
                if _words(a) == adverse or (a.option_labels and _words(a) != truth):
                    bad.append((name, k, f"confirm={pick!r}", "adverse or off-list written", _what(a)))
                if _words(a) == truth and not (a.assumed or name == "confident reader"):
                    bad.append((name, k, f"confirm={pick!r}", "a non-confident reader's No must be assumed", _what(a)))
    assert not bad, bad


@needs(*NEEDS)
def test_b_both_keys_and_a_known_reader_write_the_owners_option_with_no_vote_call():
    """D-212 U2 / U3 / U4 (replaces "a confident reader with both keys: code writes the rule's No with no call,
    whatever a confirmation would have said"): code never writes its own reading alone. The model's Yes
    differs from the reader's No -> ONE confirmation call (the field call + 1): the pick No writes No,
    assumed, note "the AI answered Yes". "", "Maybe" and a transport error end empty (U4). A pick Yes
    sides with the model: ONE meaning call; this fake answers it "Yes" (unusable) -> empty. Never Yes."""
    # review 4 F5 (replaces "a transport error ends empty"): a transport failure on the confirmation ends the PAGE as a
    # transport failure; nothing is written for the field, never the Yes.
    bad = []
    for name, label in (("confident", "Do you have any conflict of interest?"),):
        for reply in ("No", "Yes", "", "Maybe", None):
            ask = VoteAsk(WRONG_YES, confirm=reply or "", boom=reply is None)
            if reply is None:
                out = _run([_pf("v", label, "RADIO", options=YN)], ask, None)
                written = out.answers.get("v")
                if not out.transport_failed or len(ask.confirms) != 1                         or (written is not None and _words(written) == "Yes"):
                    bad.append((name, "transport error", out.transport_failed, len(ask.confirms)))
                continue
            a, out = _vote(label, ask)
            want = "No" if reply == "No" else ""
            calls = 1       # U10 (fix8): "Do you have any conflict of interest?" is a canonical frame: a confirming Yes is a veto, NO meaning call
            if _words(a) == "Yes" or (want and _words(a) != want) or (not want and a.option_labels)                     or (want and not a.assumed) or len(ask.confirms) != calls or out.model_calls != 1 + calls                     or (want and "the AI answered Yes" not in (a.note + " " + a.evidence)):
                bad.append((name, repr(reply), _what(a), len(ask.confirms), out.model_calls))
    assert not bad, bad


@needs(*NEEDS)
def test_b_one_key_only_the_class_veto_then_one_confirm_pick_decides_assumed():
    """The model calls a declaration `ordinary` (one key = the code's). D-212 U2-U4 (replaces "A5 asks again,
    then one confirm call"): no A5 round; ONE confirmation call. Pick No -> No, assumed; "", "Maybe" and a
    transport error -> empty; pick Yes -> the meaning call, unusable here -> empty. Never Yes."""
    # U9 (CONFLICT has no reading) + F5: the differing confirmation No gets the meaning call on BOTH values (U8b, 3 calls,
    # faithful replies) before the No is written; a Yes that sides with the model gets one meaning call, which a
    # faithful reader answers "yes" (it states the conflict): empty; a transport error ends the page (F5).
    bad = []
    for reply, want, calls in (("No", "No", 3), ("", "", 1), ("Yes", "", 2), ("Maybe", "", 1), (None, "", 1)):
        ask = VoteAsk(lambda v: say("Yes", "assumption", "", True, "unsure", klass="ordinary"),
                      confirm=reply or "", boom=reply is None, right="No")
        if reply is None:
            out = _run([_pf("v", CONFLICT, "RADIO", options=YN)], ask, None)
            written = out.answers.get("v")
            if not out.transport_failed or len(ask.confirms) != 1 or (written is not None and _words(written) == "Yes"):
                bad.append(("transport error", out.transport_failed, len(ask.confirms)))
            continue
        a, out = _vote(CONFLICT, ask)
        if _words(a) != want and not (want == "" and a.option_labels == ()) or (want and not a.assumed)                 or len(ask.confirms) != calls:
            bad.append((repr(reply), want, _what(a), len(ask.confirms), out.model_calls))
    assert not bad, bad


@needs(*NEEDS)
def test_b_any_basis_the_model_cites_goes_through_the_same_two_key_rule():
    # (old: any_basis_the_model_cites_goes_through_the_same_vote) a Yes with ANY basis is replaced
    # by the owner's No when both keys name the class (assumed: tentative reader); with the model's
    # class `ordinary` the same Yes is vetoed and only the confirm pick can write the No.
    bad = []
    for basis, ref in (("assumption", ""), ("resume", ""), ("job", ""), ("unknown", ""),
                       ("profile", "profile:declarations.conflict_audit_independence")):
        # ruling P2: the tentative reader's option differs from the model's Yes -> ONE confirmation; a
        # pick that equals the reader's No is written, assumed
        # U9: CONFLICT has no reading: the differing confirmation (No) gets the meaning call on both values (3 calls)
        ask = VoteAsk(lambda v, b=basis, r=ref: say("Yes", b, r, b == "assumption"), confirm="No", right="No")
        a, out = _vote(CONFLICT, ask)
        if _words(a) != "No" or not a.assumed or len(ask.confirms) != 3:
            bad.append((basis, ref, "both keys", _what(a), len(ask.confirms), out.model_calls))
        ask = VoteAsk(lambda v, b=basis, r=ref: say("Yes", b, r, b == "assumption", klass="ordinary"), confirm="No", right="No")
        a, out = _vote(CONFLICT, ask)
        if _words(a) != "No" or not a.assumed or len(ask.confirms) != 3:
            bad.append((basis, ref, "class ordinary", _what(a), len(ask.confirms), out.model_calls))
    assert not bad, bad


@needs(*NEEDS)
def test_b_the_confirmation_prompt_states_the_owners_truth_and_carries_no_secret_or_extra_identity():
    from apply_flow_support import EMAIL
    from jobscraper.apply import always as AL
    secret = "Pw-DUMMY-7Zq!x9"
    # one key (class ordinary) so that the confirm call is made (design 17.1: only a veto asks)
    # U9: the confirmation (call 1) is followed by the meaning calls of the no-reading vote (U8b: 3 calls in all);
    # the secret pins below look at every call, the WANTED / QUESTION pins at the confirmation itself
    ask = VoteAsk(lambda v: say("Yes", "assumption", "", True, "unsure", klass="ordinary"), confirm="No", right="No")
    _run([_pf("v", CONFLICT, "RADIO", options=YN)], ask, None, audit={"password": secret},
         uploaded={"pw": secret}, page_text=f"password: {secret}")
    assert len(ask.confirms) == 3, ask.confirms
    text = ask.confirms[0]
    assert AL.TASK_CONFIRM in text, text[-400:]
    assert "WANTED: The applicant has no conflict of interest" in text, text[-400:]
    # A1 M2c (design 17.4): the question is JSON-quoted in the pick body
    assert f"QUESTION (JSON): {__import__('json').dumps(CONFLICT)}" in text, text[-400:]
    for call in ask.users:                       # every call of the page: field call, A5, confirm
        assert secret not in call and "password" not in call.lower().replace("passwords", ""), "a secret reached a prompt"
    # what is specific to THIS call - everything after the page marker - holds the question, the
    # owner's truth and the options, and no identity value at all
    tail = text[text.index("== PAGE =="):]
    for forbidden in (EMAIL, "alex.testcase", "Alex", "Testcase", "2002-03-14", "91234567", "Nanyang"):
        assert forbidden.lower() not in tail.lower(), (forbidden, tail)


@needs(*NEEDS)
def test_b_negative_controls_no_confirmation_where_the_vote_does_not_apply():
    """U1 + U9 (replaces "a model that agrees with the reader / a true class: written with no call"): the only thing
    that skips a call is the model's answer EQUAL to a reader's option the label's canonical frame gives. CONFLICT
    ("Do you declare ...") and the negated wording have NO reading, so the vote's calls decide and a RIGHT first answer
    survives a flipped confirmation: the first answer and the confirmation differ -> the meaning call on BOTH values
    (U8b, 3 calls), the value whose own check says "no" while the other's says "yes" is written (assumed). Never the
    wrong value."""
    bad = []
    ask = VoteAsk(lambda v: say("Yes", "default", "default:no_declaration"), confirm="No", right="No")
    a, out = _vote(CONFLICT, ask)
    if _words(a) != "No" or not a.assumed or len(ask.confirms) != 3:
        bad.append(("default cite, confirmation No", _what(a), len(ask.confirms)))
    ask = VoteAsk(lambda v: say("Yes", "default", "default:no_declaration"), confirm="")
    a, out = _vote(CONFLICT, ask)
    if a.option_labels or len(ask.confirms) != 1:
        bad.append(("default cite, unusable confirmation", _what(a), len(ask.confirms)))
    # a negated wording: "I confirm I have no conflict of interest" + model Yes (a statement the owner makes: Yes is
    # right) + a FLIPPED confirmation No: the Yes survives (its own check says "no", the No's says "yes")
    ask = VoteAsk(lambda v: say("Yes", "assumption", "", True, "x"), confirm="No", right="Yes")
    a, out = _vote("I confirm I have no conflict of interest", ask)
    if _words(a) != "Yes" or len(ask.confirms) != 3:
        bad.append(("negated", _what(a), len(ask.confirms)))
    # a class that is TRUE in the profile: the right Yes survives a flipped confirmation, and a right confirmation
    # (Yes) needs ONE meaning call
    p = _profile(declarations__conflict_audit_independence=True)
    for ref in ("", "default:no_declaration"):
        for confirm, calls in (("No", 3), ("Yes", 2)):
            ask = VoteAsk(lambda v, r=ref: say("Yes", "default" if r else "assumption", r, not r), confirm=confirm,
                          right="Yes")
            a, out = _vote(CONFLICT, ask, p)
            if _words(a) != "Yes" or len(ask.confirms) != calls:
                bad.append(("true class", ref, f"confirm {confirm}", _what(a), len(ask.confirms)))
    # the right No survives a flipped confirmation too
    ask = VoteAsk(lambda v: say("No", "default", "default:no_declaration"), confirm="Yes", right="No")
    a, out = _vote(CONFLICT, ask)
    if _words(a) != "No" or len(ask.confirms) != 3:
        bad.append(("agree, flipped confirmation", _what(a), len(ask.confirms)))
    assert not bad, bad


# ------------------------------------------------------------------ A: the refused consent

REFUSED = (("data_retention_consent", "I agree that you keep my details on file for future roles",
            "May we keep your details on file for future roles?"),
           ("certify_true", "I certify that the information provided is true and complete",
            "Do you certify that the information provided is true and complete?"),
           ("privacy_consent", "I consent to the processing of my personal data",
            "Do you consent to the processing of your personal data?"))


def _refused_profile(key):
    p = _profile()
    p["consents"][key] = False
    return p


@needs(*NEEDS)
def test_a_a_refused_consent_is_never_ticked_stops_when_required_and_is_a_note_when_not():
    bad = []
    for key, box, question in REFUSED:
        p = _refused_profile(key)
        for ref, basis in ((f"profile:consents.{key}", "profile"), ("default:consent", "default"), ("", "assumption")):
            ask = lambda: FakeAsk(lambda v, b=basis, r=ref: say("true", b, r, b == "assumption"))   # noqa: E731
            res = _stop_or_answer(_pf("c", box, "CHECKBOX"), ask(), p)                     # required box
            if not _is_refusal_stop(res, key):
                bad.append((key, ref, "required box", _what(res)))
            res = _stop_or_answer(_pf("c", box, "CHECKBOX", required=False), ask(), p)     # optional box
            if isinstance(res, Exception) or _tick(res) or "the AI answered" not in (res.note + res.evidence):
                bad.append((key, ref, "optional box", _what(res)))
            res = _stop_or_answer(_pf("c", question, "RADIO", options=YN),                  # yes/no with a No
                                  FakeAsk(lambda v, b=basis, r=ref: say("Yes", b, r, b == "assumption")), p)
            if isinstance(res, Exception) or _words(res) != "No" or res.assumed \
                    or res.source != f"profile:consents.{key}":
                bad.append((key, ref, "yes/no", _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_a_a_list_with_no_way_to_say_no_stops_instead_of_agreeing():
    # a required consent offered as a one-option list ("I agree"): nothing can state No
    bad = []
    for key, _box, question in REFUSED:
        res = _stop_or_answer(_pf("c", question, "DROPDOWN", options=("I agree",)),
                              FakeAsk(lambda v: say("I agree", "default", "default:consent")), _refused_profile(key))
        if not _is_refusal_stop(res, key):
            bad.append((key, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_a_an_agree_or_do_not_agree_pair_answers_do_not_agree_for_a_refused_consent():
    # the No option is worded "I do not agree" / "I do not acknowledge": the owner's refusal
    # must pick it, not the model's "I agree"
    bad = []
    for key, _box, question in REFUSED:
        for opts in (("I agree", "I do not agree"), ("I acknowledge", "I do not acknowledge")):
            res = _stop_or_answer(_pf("c", question, "RADIO", options=opts),
                                  FakeAsk(lambda v, o=opts: say(o[0], "default", "default:consent")), _refused_profile(key))
            if isinstance(res, Exception) or res.option_labels != (opts[1],):
                bad.append((key, opts, _what(res)))
    assert not bad, bad


@needs(*NEEDS)
def test_a_marketing_keeps_the_d2_rule_unticked_and_no_stop():
    p = _profile(consents__talent_pool_opt_in=False)
    res = _stop_or_answer(_pf("m", "Subscribe to our newsletter", "CHECKBOX"),
                          FakeAsk(lambda v: say("true", "default", "default:consent")), p)
    assert not isinstance(res, Exception) and not _tick(res), _what(res)


# ------------------------------------------------------------------ C: terms and policies are not privacy

TERMS = ("Do you understand our terms and conditions?", "Do you agree to our terms of use?",
         "Have you read our code of conduct?", "Do you accept our anti-bribery policy?")
PRIVACY = ("Do you agree to our privacy notice?", "Do you agree to our personal data protection statement?",
           "Do you accept our PDPA notice?")


@needs(*NEEDS)
def test_c_terms_code_and_named_policies_follow_certify_true_never_privacy_consent():
    # (old: ..._are_yes_assumed_whatever_privacy_consent_says) design 17.2 acknowledgement row: an
    # acknowledgement of anything but a privacy notice follows `consents.certify_true`. Sample
    # (true): Yes from that row, NOT assumed, whatever `privacy_consent` is; unset: Yes by the D5
    # default, ASSUMED; false: No (R-c: the owner's explicit refusal is never overridden).
    bad = []
    for privacy in (False, True):
        for cert, want, assumed, source in ((True, "Yes", False, "profile:consents.certify_true"),
                                            ("UNSET", "Yes", True, "default:consent"),
                                            (False, "No", False, "profile:consents.certify_true")):
            p = _profile(consents__privacy_consent=privacy)
            if cert == "UNSET":
                p["consents"].pop("certify_true")
            else:
                p["consents"]["certify_true"] = cert
            for label in TERMS:
                for who, ask in (("silent", FakeAsk()),
                                 ("model no (default)", FakeAsk(lambda v: say("No", "default", "default:consent"))),
                                 ("model yes (default)", FakeAsk(lambda v: say("Yes", "default", "default:consent"))),
                                 ("model no (privacy row)", FakeAsk(lambda v: say("No", "profile", "profile:consents.privacy_consent")))):
                    a, _ = _vote(label, ask, p)
                    if _words(a) != want or a.assumed is not assumed or a.source != source:
                        bad.append((f"privacy={privacy}", f"certify_true={cert}", label, who, _what(a)))
    assert not bad, bad


@needs(*NEEDS)
def test_c_only_privacy_wording_follows_privacy_consent():
    bad = []
    for privacy in (False, True):
        p = _profile(consents__privacy_consent=privacy)
        for label in PRIVACY:
            for who, ask in (("silent", FakeAsk()),
                             ("model opposite", FakeAsk(lambda v, x=privacy: say("No" if x else "Yes", "default", "default:consent")))):
                a, _ = _vote(label, ask, p)
                if _words(a) != ("Yes" if privacy else "No") or a.source != "profile:consents.privacy_consent" or a.assumed:
                    bad.append((f"privacy={privacy}", label, who, _what(a)))
    assert not bad, bad


# ------------------------------------------------------------------ D: an unset key means Yes, assumed

@needs(*NEEDS)
def test_d_a_certification_or_acknowledgement_with_no_key_set_is_yes_assumed_even_if_the_model_says_no():
    # A1: an acknowledgement of a policy / code of conduct follows `certify_true` (17.2), so "no key
    # set" for those two rows means certify_true UNSET (the old profile had it true); a privacy
    # notice follows privacy_consent. Both keys name the class -> Yes (the D5 derived default),
    # assumed, whatever the model said; the model's No stays as a note.
    bad = []
    unset_cert = _profile()
    unset_cert["consents"].pop("certify_true")
    unset_priv = _profile()
    unset_priv["consents"].pop("privacy_consent")
    cases = (("certify (radio)", "Do you certify that the information provided is true and complete?", "RADIO", unset_cert),
             ("certify (box)", "I certify that the information provided is true and complete", "CHECKBOX", unset_cert),
             ("code of conduct", "Have you read our code of conduct?", "RADIO", unset_cert),
             ("policy", "Do you accept our anti-bribery policy?", "RADIO", unset_cert),
             ("privacy notice, key unset", "Do you agree to our privacy notice?", "RADIO", unset_priv))
    for name, label, kind, p in cases:
        a, _ = _vote(label, FakeAsk(lambda v, k=kind: _say_bool(k, False, "default", "default:consent")), p,
                     options=YN if kind == "RADIO" else (), kind=kind)
        if not (_tick(a) and a.assumed and "the AI answered" in (a.note + " " + a.evidence)):
            bad.append((name, _what(a), a.note))
    assert not bad, bad


@needs(*NEEDS)
def test_d_negative_controls_a_set_key_decides_and_a_plain_consent_is_the_models():
    bad = []
    # the key explicitly TRUE: Yes from that row, not assumed, the model's No a note
    for label, kind in (("Do you certify that the information provided is true and complete?", "RADIO"),
                        ("I certify that the information provided is true and complete", "CHECKBOX"),
                        ("Do you agree to our privacy notice?", "RADIO")):
        a, _ = _vote(label, FakeAsk(lambda v, k=kind: _say_bool(k, False, "default", "default:consent")),
                     _profile(), options=YN if kind == "RADIO" else (), kind=kind)
        if not (_tick(a) and not a.assumed and a.source.startswith("profile:consents.")):
            bad.append((label, _what(a)))
    # A1 (17.2 "Unset"): a privacy consent with the key unset is the D5 derived agree -> Yes, assumed,
    # over the model's No (both keys); RETENTION with its key unset is "the model decides": the
    # model's No stands. (Old pin: the model's No stood for the privacy consent too.)
    unset = _profile()
    unset["consents"].pop("privacy_consent")
    a, _ = _vote("Do you consent to the processing of your personal data?",
                 FakeAsk(lambda v: say("No", "default", "default:consent")), unset)
    if _words(a) != "Yes" or not a.assumed or a.source != "default:consent":
        bad.append(("plain privacy consent, key unset", _what(a)))
    unset = _profile()
    unset["consents"].pop("data_retention_consent")
    a, _ = _vote("May we keep your details on file for future roles?",
                 FakeAsk(lambda v: say("No", "default", "default:consent")), unset)
    if _words(a) != "No":
        bad.append(("retention, key unset", _what(a)))
    assert not bad, bad
