"""Q-121 Amendment A1, the fix7 / fix8 pin round (U10, U10b, U11, U12, E1, fix7 rulings 1-3).

Under `always` with `mode: auto` every filled form is SUBMITTED with no review step, so every pin keeps its assertion on
the HARMFUL value (a declaration the owner does not have, a work-rights claim the profile does not give, an invented
National Service answer, a family-guess "No") and on the NUMBER of model calls the ruling allows. Expected values come
from the rulings, never from what the code does:

  fix7-1  a yes/no (or any choice field) with NO code key and NO model class is never answered by a family guess: a
          silent model gets ONE single-field ask; unusable -> a required field is empty for the site, an optional one stays empty.
  fix7-2  a label that plainly asks whether the applicant has SERVED / COMPLETED National Service or military service takes
          its answer from `singapore_status.ns_status` (completed or serving -> has served); a model answer that
          contradicts a SET status is replaced (not assumed, a note); reservist / exemption wordings stay ordinary.
  fix7-3  no `standing:prior_roles` line when the profile lists no roles.
  U10     a canonical reading is a VETO: model answer, confirmation (and a meaning reply) all against the frame ->
          nothing written, the protective end, NO meaning call. Option lists keep the meaning call (as built).
  U10b    "Do you have any restrictions / limitations on your right / ability / eligibility to work in X?" and "Is your
          right to work in X restricted / limited (in any way)?" are work-rights frames, Yes = NOT freely authorised.
  U11     model and confirmation AGREE on a pure none-applies option and none applies -> written (assumed), no meaning call.
  U12     a bare declaration noun with plain Yes / No ("Criminal record", "PEP", ...) is a frame, Yes = it applies; extra
          words ("PEP status", "Criminal record check") are not.
  E1      an ordinary "worked in a similar / comparable / related role?" yes/no, roles in the profile, model No or silent:
          ONE focused experience call; its yes / no is written (assumed, note "experience check").

Model conditions: right / wrong / silent; class right / `ordinary` / missing (NO_CLASS). Fakes only: no model, no network,
no browser, sample profile (a Singapore citizen: authorised in SG, NOT authorised in the US, National Service completed,
two internships, all declarations false), made-up names.
Verify: python tests/run_tests.py -k always_a1_fix8
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from apply_support import needs  # noqa: E402
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, is_stop, is_ticked, lie, outcome, pick_by, profile_with, report, shown, what, _pf)
from test_always_briefing import NEEDS, _build, _lines, _profile as _bprofile  # noqa: E402

CLASSES = ("right", "ordinary", NO_CLASS)


def _k(kind, right):
    return right if kind == "right" else kind


def _kinds(ask) -> list[str]:
    """Which kind of call each pick was: confirm | meaning | experience | ask (the single-field ask)."""
    out = []
    for _q, w, _o in ask.picks:
        w = str(w)
        out.append("meaning" if w.startswith("If the applicant answers") else
                   "experience" if w.startswith("Roles the applicant has held") else
                   "ask" if w.startswith("the applicant's true answer") else "confirm")
    return out


def _f(label, *, tn="RADIO", required=True, options=YN, **kw):
    return _pf("u", label, tn, required=required, options=options if tn in ("RADIO", "DROPDOWN") else (), **kw)


# ================================================================== fix7-1: no key, no class, no family guess

UNKEYED = ("Do you enjoy working in a team environment?", "Are you comfortable with a hybrid work arrangement?",
           "Have you previously used our products?", "Do you have a driving licence?")


def test_fix7_1_a_silent_model_on_an_unkeyed_yes_no_gets_one_single_field_ask_never_a_family_guess():
    """fix7-1: no code key, no model class, a silent model: ONE single-field ask (its WANTED asks for the applicant's TRUE
    answer from the profile and resume); the option it names is written (assumed). Never a generic No / Yes with 0 calls."""
    bad = []
    for label in UNKEYED:
        for reply in ("Yes", "No"):
            ask = FakeAsk(pick=lambda q, w, o, r=reply: r)
            res = attempt(_f(label), ask)
            if shown(res) != reply or not res.assumed or _kinds(ask) != ["ask"] or "single-field ask" not in str(res.note):
                bad.append((label[:45], reply, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_an_unusable_single_field_ask_leaves_a_required_field_empty_for_the_site():
    """fix7-1: the ask answers "" or an option the field does not have: a REQUIRED field is left empty for the site (a
    note says so), never a guessed Yes / No."""
    bad = []
    for label in UNKEYED:
        for reply in ("", "Maybe", "Prefer not to say"):
            ask = FakeAsk(pick=lambda q, w, o, r=reply: r)
            res = attempt(_f(label), ask)
            if shown(res) != "" or _kinds(ask) != ["ask"] or "left for the site" not in str(res.note):
                bad.append((label[:45], reply, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_an_optional_unkeyed_yes_no_with_no_usable_answer_stays_empty():
    """fix7-1: an OPTIONAL field the model leaves silent and the ask cannot answer stays empty (never No / Yes)."""
    bad = []
    for label in UNKEYED:
        ask = FakeAsk(pick=lambda q, w, o: "")
        res = attempt(_f(label, required=False), ask)
        if shown(res) != "" or len(ask.picks) > 1:
            bad.append((label[:45], what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_a_usable_model_answer_on_an_unkeyed_yes_no_is_written_as_it_is_with_no_ask():
    """control: the ask exists only for a SILENT model; a model that answers an ordinary question is written as it said
    (right or wrong: an ordinary question has no owner truth in code), with 0 extra calls."""
    bad = []
    for label in UNKEYED:
        for value in ("Yes", "No"):
            ask = FakeAsk(lambda v, x=value: lie(x, "ordinary"), pick=lambda q, w, o: "")
            res = attempt(_f(label), ask)
            if shown(res) != value or ask.picks:
                bad.append((label[:45], value, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_1_a_silent_model_on_an_unkeyed_choice_list_is_asked_once_not_given_the_first_option():
    """fix7-1 ("or any choice field"): a three-option list with no key and a silent model: ONE single-field ask, and an
    unusable reply leaves the required field empty, never the first / a family-guessed option."""
    # a list that is no preference list (F3's R4 picks the first option of "prefer" / "enjoy" lists by design: not pinned)
    opts = ("Rarely", "Sometimes", "Often")
    label = "How often are you available for meetings?"
    ask = FakeAsk(pick=lambda q, w, o: "")
    res = attempt(_f(label, options=opts), ask)
    assert shown(res) == "" and len(ask.picks) == 1, (what(res), _kinds(ask))
    ask = FakeAsk(pick=lambda q, w, o: "Often")
    res = attempt(_f(label, options=opts), ask)
    assert shown(res) == "Often" and len(ask.picks) == 1, (what(res), _kinds(ask))


# ================================================================== fix7-2: National Service from `ns_status`

# (label, the statuses for which the answer is YES): "completed" wording -> only a completed status; "served" / "done"
# wordings -> completed or serving. Exempted / not applicable / unset never say yes.
NS_WORDINGS = (
    ("Have you completed National Service?", ("completed",)),
    ("Have you served in the military?", ("completed", "serving")),
    ("Have you done National Service?", ("completed", "serving")),
)
NS_STATUSES = ("completed", "serving", "exempted", "not_applicable")
NS_SRC = "singapore_status.ns_status"


def test_fix7_2_every_served_or_completed_wording_takes_its_answer_from_the_set_ns_status():
    """fix7-2: three wordings x four set statuses x a SILENT model, a model that CONTRADICTS the status and a model that is
    RIGHT: always the status's answer, 0 calls. Silent / contradicting: sourced from `ns_status`, NOT assumed, the
    contradicting answer named in the note. A status that is not `completed` is never "Yes" to "completed"."""
    bad = []
    for label, yes_for in NS_WORDINGS:
        for status in NS_STATUSES:
            truth = "Yes" if status in yes_for else "No"
            wrong = "No" if truth == "Yes" else "Yes"
            p = profile_with(singapore_status__ns_status=status)
            for name, ans in (("silent", None), ("contradicting", lambda v, w=wrong: lie(w, "ordinary")),
                              ("right", lambda v, t=truth: lie(t, "ordinary"))):
                ask = FakeAsk(ans, pick=pick_by("", ""))
                res = attempt(_f(label), ask, p)
                if shown(res) != truth or ask.picks:
                    bad.append((label[:34], status, name, what(res), len(ask.picks)))
                elif name != "right" and (NS_SRC not in str(res.source) or res.assumed):
                    bad.append((label[:34], status, name, "not sourced from ns_status / assumed", what(res)))
                elif name == "contradicting" and "AI answered" not in f"{res.note} {res.evidence}":
                    bad.append((label[:34], status, name, "no note naming the model's answer", what(res)))
    assert not bad, report(bad, 10)


def test_fix7_2_a_contradicting_model_answer_is_replaced_whatever_class_it_names():
    """fix7-2: the model's wrong "No" to "Have you completed National Service?" (owner: completed) is replaced by Yes
    under every class it may name, including `declaration:government_employment` (a wrong class must not keep it)."""
    bad = []
    for klass in ("ordinary", NO_CLASS, "declaration:government_employment", "declaration:other"):
        ask = FakeAsk(lambda v, k=klass: lie("No", k), pick=pick_by("No", "no"))
        res = attempt(_f("Have you completed National Service?"), ask)
        if shown(res) != "Yes" or ask.picks or NS_SRC not in str(res.source):
            bad.append((klass, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_fix7_2_with_ns_status_unset_the_profile_gives_no_answer_a_silent_model_is_asked_not_told_no():
    """fix7-2: `ns_status` unset -> nothing to take: a silent model gets the single-field ask (1 call) and no code answer
    from the status (never a code-written No); a model's own answer stands unchanged."""
    bad = []
    p = profile_with(singapore_status__ns_status=None)
    for label, _y in NS_WORDINGS:
        ask = FakeAsk(pick=lambda q, w, o: "")
        res = attempt(_f(label), ask, p)
        if shown(res) != "" or NS_SRC in str(getattr(res, "source", "")) or len(ask.picks) != 1:
            bad.append((label[:34], "silent", what(res), _kinds(ask)))
        for value in ("Yes", "No"):
            ask = FakeAsk(lambda v, x=value: lie(x, "ordinary"), pick=pick_by("", ""))
            res = attempt(_f(label), ask, p)
            if shown(res) != value or NS_SRC in str(res.source) or ask.picks:
                bad.append((label[:34], f"model {value}", what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_fix7_2_reservist_and_exemption_wordings_stay_ordinary_the_models_answer_stands():
    """fix7-2: "liable for reservist duties" and "exempted from National Service" are NOT "has served" questions: the
    owner's `completed` status must not overwrite the model's answer (no replacement, no `ns_status` source)."""
    bad = []
    for label in ("Are you liable for reservist duties?", "Have you been exempted from National Service?"):
        for value in ("Yes", "No"):
            ask = FakeAsk(lambda v, x=value: lie(x, "ordinary"), pick=pick_by("", ""))
            res = attempt(_f(label), ask)
            if shown(res) != value or NS_SRC in str(res.source) or ask.picks:
                bad.append((label[:40], f"model {value}", what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== fix7-3: no prior_roles line without roles

@needs(*NEEDS)
def test_fix7_3_the_model_prompt_has_no_prior_roles_line_when_the_profile_lists_no_roles():
    """fix7-3: with `experience: []` the briefing SENT to the model carries no `standing:prior_roles` line (the model must
    not read "0 roles held" as a fact); with roles it carries one. Checked on the prompt the fake received."""
    def has_line(ask):      # the standing:similar_roles rule MENTIONS the id; the facts line STARTS with it
        return [any(ln.startswith("standing:prior_roles |") for ln in u.splitlines()) for u in ask.users]
    ask = FakeAsk(lambda v: lie("No", "ordinary"))
    attempt(_f("Do you enjoy working in a team environment?"), ask, profile_with(experience=[]))
    assert ask.users and not any(has_line(ask)), "a prior_roles line with no roles"
    ask = FakeAsk(lambda v: lie("No", "ordinary"))
    attempt(_f("Do you enjoy working in a team environment?"), ask)
    assert ask.users and all(has_line(ask)), "no prior_roles line with roles"


# ================================================================== U10: a canonical reading is a veto

U10_FRAMES = (   # (label, the class, the model's WRONG answer, the RIGHT answer): sample owner, all declarations false
    ("Have you ever been convicted of a criminal offence?", "declaration:criminal_record", "Yes", "No"),
    ("Are you legally authorised to work in Singapore?", "work_right", "No", "Yes"),
    ("Do you require visa sponsorship to work in the United States?", "sponsorship", "No", "Yes"),
)


def test_u10_three_canonical_frames_wrong_three_times_end_empty_after_one_pick_with_no_meaning_call():
    """U10: the model's wrong answer, an AGREEING confirmation and a meaning reply "no" (which would have WRITTEN the wrong
    value on the old path) -> empty: the protective end, exactly ONE pick (the confirmation), no meaning call. Class
    right / ordinary / missing alike (the code's own key catches each wording)."""
    bad = []
    for label, klass, wrong, _right in U10_FRAMES:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_by(wrong, "no"))
            res = attempt(_f(label), ask)
            if shown(res) != "" or _kinds(ask) != ["confirm"]:
                bad.append((label[:42], kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_u10_a_tick_box_ticked_wrongly_against_a_frame_is_never_ticked_and_no_meaning_call_is_made():
    """U10 for a tick box: "I am a politically exposed person" ticked by the model, the confirmation says yes (ticked)
    and a meaning reply "no" is available: the box is left unticked (empty), one pick, no meaning call."""
    bad = []
    for kind in CLASSES:
        ask = FakeAsk(lambda v, k=_k(kind, "declaration:pep"): lie("true", k), pick=pick_by("yes", "no"))
        res = attempt(_pf("b", "I am a politically exposed person", "CHECKBOX"), ask)
        if is_ticked(res) or _kinds(ask) != ["confirm"]:
            bad.append((kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_u10_a_confirmation_that_equals_the_frames_reading_still_writes_it_with_one_pick():
    """control: model wrong, the confirmation says the RIGHT answer (the frame's own reading): written (assumed), one pick."""
    bad = []
    for label, klass, wrong, right in U10_FRAMES:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass), w=wrong: lie(w, k), pick=pick_by(right, "yes"))
            res = attempt(_f(label), ask)
            if shown(res) != right or not res.assumed or _kinds(ask) != ["confirm"]:
                bad.append((label[:42], kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


CONFLICT_LIST = ("Yes, I have a potential conflict of interest", "No conflict of interest", "Not applicable")


def test_u10_an_option_list_keeps_the_meaning_call_as_built_and_a_yes_or_unusable_reply_never_writes_the_adverse_option():
    """U10 AS BUILT (note for the architect): the veto covers tick boxes and yes/no; a list of STATEMENT options still takes
    the meaning call after an agreed adverse choice (two picks). A "yes" or unusable meaning reply -> empty: the adverse
    option is never written without a "no" reply. (A "no" reply writes it: the as-built residual, not pinned.)"""
    adverse = CONFLICT_LIST[0]
    bad = []
    for meaning in ("yes", ""):
        ask = FakeAsk(lambda v: lie(adverse, "declaration:conflict_audit_independence"), pick=pick_by(adverse, meaning))
        res = attempt(_f("Conflict of interest", options=CONFLICT_LIST), ask)
        if shown(res) != "" or _kinds(ask) != ["confirm", "meaning"]:
            bad.append((meaning, what(res), _kinds(ask)))
    assert not bad, report(bad)


# ================================================================== U10b: the restriction wordings

U10B_WORDINGS = (
    "Do you have any restrictions on your right to work in {c}?",
    "Do you have any limitations on your right to work in {c}?",
    "Is your right to work in {c} restricted?",
    "Is your right to work in {c} limited in any way?",
)
# the ruling also names "ability" and "eligibility" (`_u9_frame` has them): code's CLASS key must know them too
U10B_ABILITY = (
    "Do you have any restrictions on your ability to work in {c}?",
    "Do you have any limitations on your ability to work in {c}?",
    "Do you have any restrictions on your eligibility to work in {c}?",
    "Do you have any limitations on your eligibility to work in {c}?",
)
U10B_COUNTRIES = (("Singapore", "No"), ("the United States", "Yes"))    # Yes = restricted = NOT freely authorised


def _u10b_cells(wordings=U10B_WORDINGS):
    for tmpl in wordings:
        for country, right in U10B_COUNTRIES:
            yield tmpl.format(c=country), right, ("No" if right == "Yes" else "Yes")


def test_u10b_a_right_model_answer_is_written_with_no_call_for_both_wordings_and_both_countries():
    """U10b: a citizen of Singapore: "restrictions on your right to work in Singapore" -> No; in the United States (not
    authorised) -> Yes. A right model answer is written with 0 calls, class right / ordinary / missing."""
    bad = []
    for label, right, _wrong in _u10b_cells():
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, "work_right"), r=right: lie(r, k), pick=pick_by("", ""))
            res = attempt(_f(label), ask)
            if shown(res) != right or ask.picks:
                bad.append((label[:50], kind, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_u10b_a_wrong_model_answer_with_an_agreeing_confirmation_ends_empty_after_one_pick():
    """U10b + U10: the wrong claim (a restriction a citizen does not have; "no restriction" for a country where the owner is
    not authorised), the confirmation agreeing and a meaning "no" -> empty, one pick, no meaning call."""
    bad = []
    for label, _right, wrong in _u10b_cells():
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, "work_right"), w=wrong: lie(w, k), pick=pick_by(wrong, "no"))
            res = attempt(_f(label), ask)
            if shown(res) != "" or _kinds(ask) != ["confirm"]:
                bad.append((label[:50], kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_u10b_a_wrong_model_answer_and_the_right_confirmation_write_the_right_value_in_one_pick():
    bad = []
    for label, right, wrong in _u10b_cells():
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, "work_right"), w=wrong: lie(w, k), pick=pick_by(right, "yes"))
            res = attempt(_f(label), ask)
            if shown(res) != right or _kinds(ask) != ["confirm"]:
                bad.append((label[:50], kind, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_u10b_the_ability_and_eligibility_wordings_are_frames_too_under_every_model_class():
    """U10b names "restrictions / limitations on your right / ABILITY / ELIGIBILITY to work in X". A right model answer is
    written with no call and a wrong one is never written, class right / ordinary / missing alike. DEFECT while red: code's
    class key finds no work-rights class in the ability / eligibility wordings (`code_key` says ordinary), so with a model
    that names `ordinary` or no class the wrong claim is written with 0 calls (an over-claim of the right to work in a
    country where the owner is not authorised, or an invented restriction)."""
    bad = []
    for label, right, wrong in _u10b_cells(U10B_ABILITY):
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, "work_right"), r=right: lie(r, k), pick=pick_by("", ""))
            res = attempt(_f(label), ask)
            if shown(res) != right or ask.picks:
                bad.append((label[:52], kind, "right model", what(res), len(ask.picks)))
            ask = FakeAsk(lambda v, k=_k(kind, "work_right"), w=wrong: lie(w, k), pick=pick_by(wrong, "no"))
            res = attempt(_f(label), ask)
            if shown(res) != "" or _kinds(ask) != ["confirm"]:
                bad.append((label[:52], kind, "wrong x3", what(res), _kinds(ask)))
    assert not bad, report(bad, 10)


# ================================================================== U11: a pure none-applies option, agreed

def test_u11_an_agreed_pure_none_applies_option_is_written_with_no_meaning_call():
    """U11: model and confirmation AGREE on a pure none-applies statement and the owner has no conflict: written, no
    meaning call (the meaning reply "yes" that would have emptied the field is never asked). Three pure options."""
    adverse = CONFLICT_LIST[0]
    bad = []
    for none in ("No conflict of interest", "Not applicable", "I have no conflict of interest"):
        opts = (adverse, none) if none != "No conflict of interest" else CONFLICT_LIST
        ask = FakeAsk(lambda v, n=none: lie(n, "declaration:conflict_audit_independence"), pick=pick_by(none, "yes"))
        res = attempt(_f("Conflict of interest", options=opts), ask)
        if shown(res) != none or "meaning" in _kinds(ask) or len(ask.picks) > 1:
            bad.append((none, what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_u11_a_no_but_option_is_not_pure_and_the_meaning_call_still_runs():
    """U11 limit: "No, but I had one in the past" has a qualifier: NOT pure. Agreed by model and confirmation, it gets the
    meaning call; a "yes" reply (it does state a conflict) -> empty."""
    opts = ("Yes, I have a potential conflict of interest", "No, but I had one in the past")
    ask = FakeAsk(lambda v: lie(opts[1], "declaration:conflict_audit_independence"), pick=pick_by(opts[1], "yes"))
    res = attempt(_f("Conflict of interest", options=opts), ask)
    assert shown(res) == "" and _kinds(ask) == ["confirm", "meaning"], (what(res), _kinds(ask))


def test_u11_the_adverse_option_agreed_is_never_the_pure_none_path():
    """U11 contrast: the ADVERSE option agreed by both is not a none-applies statement; "yes" on the meaning call empties it."""
    adverse = CONFLICT_LIST[0]
    ask = FakeAsk(lambda v: lie(adverse, "declaration:conflict_audit_independence"), pick=pick_by(adverse, "yes"))
    res = attempt(_f("Conflict of interest", options=CONFLICT_LIST), ask)
    assert shown(res) == "" and "meaning" in _kinds(ask), (what(res), _kinds(ask))


# ================================================================== U12: a bare declaration noun with Yes / No

U12_BARE = (("Criminal record", "declaration:criminal_record"), ("Bankruptcy", "declaration:bankruptcy"),
            ("Conflict of interest", "declaration:conflict_audit_independence"),
            ("Politically exposed person (PEP)", "declaration:pep"), ("PEP", "declaration:pep"),
            ("Non-compete agreement", "declaration:non_compete"))
U12_NEAR = (("PEP status", "declaration:pep"), ("Criminal record check", "declaration:criminal_record"),
            ("Conflict of interest policy", "declaration:conflict_audit_independence"))


def test_u12_a_bare_declaration_noun_with_yes_no_takes_a_right_no_with_no_call():
    """U12: the WHOLE label is one class's noun phrase and the options are exactly Yes / No: Yes = it applies. The owner has
    none, so a right "No" is written with 0 calls, class right / ordinary / missing."""
    bad = []
    for label, klass in U12_BARE:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass): lie("No", k), pick=pick_by("", ""))
            res = attempt(_f(label), ask)
            if shown(res) != "No" or ask.picks:
                bad.append((label, kind, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_u12_a_wrong_yes_to_a_bare_noun_is_never_written_and_ends_after_one_pick():
    """U12 + U10: the model's wrong Yes, an agreeing confirmation and a meaning "no" -> empty after ONE pick; the right
    confirmation (No) writes No."""
    bad = []
    for label, klass in U12_BARE:
        for kind in CLASSES:
            ask = FakeAsk(lambda v, k=_k(kind, klass): lie("Yes", k), pick=pick_by("Yes", "no"))
            res = attempt(_f(label), ask)
            if shown(res) != "" or _kinds(ask) != ["confirm"]:
                bad.append((label, kind, "agreeing wrong pair", what(res), _kinds(ask)))
            ask = FakeAsk(lambda v, k=_k(kind, klass): lie("Yes", k), pick=pick_by("No", "yes"))
            res = attempt(_f(label), ask)
            if shown(res) != "No" or _kinds(ask) != ["confirm"]:
                bad.append((label, kind, "right confirmation", what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_u12_a_trailing_question_mark_or_colon_is_still_the_bare_noun():
    bad = []
    for label in ("Criminal record?", "Bankruptcy:", "Conflict of interest *"):
        ask = FakeAsk(lambda v: lie("No", "ordinary"), pick=pick_by("", ""))
        res = attempt(_f(label), ask)
        if shown(res) != "No" or ask.picks:
            bad.append((label, what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_u12_near_misses_with_an_extra_word_or_a_third_option_stay_on_the_no_reading_path():
    """U12 limit: "PEP status", "Criminal record check", "Conflict of interest policy" (an extra word) and a bare noun with a
    "Prefer not to say" option are NOT the frame: they have no reading, so even a right No is not written with 0 calls (the
    confirmation and the meaning call run), and a wrong Yes is never written."""
    bad = []
    for label, klass in U12_NEAR + (("Criminal record", "declaration:criminal_record"),):
        opts = ("Yes", "No", "Prefer not to say") if label == "Criminal record" else YN
        ask = FakeAsk(lambda v, k=klass: lie("No", k), pick=pick_by("No", "no"))
        res = attempt(_f(label, options=opts), ask)
        if len(ask.picks) < 1:
            bad.append((label, "right No written with 0 calls", what(res)))
        ask = FakeAsk(lambda v, k=klass: lie("Yes", k), pick=pick_by("Yes", "yes"))
        res = attempt(_f(label, options=opts), ask)
        if shown(res) == "Yes":
            bad.append((label, "wrong Yes written", what(res)))
    assert not bad, report(bad)


# ================================================================== E1: the focused experience call

E1_LABELS = ("Have you worked in a similar role before?", "Do you have experience in a related position?",
             "Have you held a comparable job?")


def _exp(first, reply, label, profile=None, tn="RADIO"):
    answer = (lambda v, f=first: lie(f, "ordinary")) if first else None
    ask = FakeAsk(answer, pick=lambda q, w, o, r=reply: r)
    return attempt(_f(label, tn=tn), ask, profile), ask


def test_e1_a_no_gets_one_focused_call_and_its_yes_or_no_is_written_assumed_with_the_experience_note():
    """E1: model "No" on an ordinary similar-role question, roles in the profile: ONE focused call; its yes -> Yes (note
    "experience check", assumed), its no -> No. The call carries the roles held, the internship words and the question."""
    bad = []
    for label in E1_LABELS:
        for reply, want in (("yes", "Yes"), ("no", "No")):
            res, ask = _exp("No", reply, label)
            if shown(res) != want or not res.assumed or "experience check" not in str(res.note) or _kinds(ask) != ["experience"]:
                bad.append((label[:40], reply, what(res), _kinds(ask)))
            elif "Internships and part-time roles count as experience" not in ask.picks[0][1] \
                    or "Data Intern" not in ask.picks[0][1] or ask.picks[0][2] != ["yes", "no"]:
                bad.append((label[:40], reply, "the call's WANTED / options", ask.picks[0][1][:120], ask.picks[0][2]))
    assert not bad, report(bad)


def test_e1_an_unusable_focused_reply_leaves_the_models_first_answer():
    bad = []
    for label in E1_LABELS:
        res, ask = _exp("No", "", label)
        if shown(res) != "No" or _kinds(ask) != ["experience"]:
            bad.append((label[:40], what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_e1_a_silent_model_gets_the_focused_call_and_its_answer_is_written():
    bad = []
    for label in E1_LABELS:
        res, ask = _exp(None, "yes", label)
        if shown(res) != "Yes" or not res.assumed or _kinds(ask) != ["experience"]:
            bad.append((label[:40], what(res), _kinds(ask)))
        res, ask = _exp(None, "", label)             # unusable too: the normal last resort, never a blind Yes / No from code
        if shown(res) != "" or _kinds(ask)[:1] != ["experience"]:
            bad.append((label[:40], "silent + unusable", what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_e1_a_first_yes_gets_no_call_and_is_never_turned_into_a_no():
    bad = []
    for label in E1_LABELS:
        res, ask = _exp("Yes", "no", label)
        if shown(res) != "Yes" or ask.picks:
            bad.append((label[:40], what(res), _kinds(ask)))
    assert not bad, report(bad)


def test_e1_free_text_a_number_of_years_a_negated_label_and_a_profile_with_no_roles_get_no_call():
    """E1 limits: "Describe your experience in a similar role" (free text), "2 years of experience in a similar role" (a
    number), "Have you never worked in a similar role?" (negated) and a profile that lists no roles: the model's No stands
    and no focused call is made."""
    bad = []
    for label, tn, prof in (("Describe your experience in a similar role", "TEXT", None),
                            ("Do you have 2 years of experience in a similar role?", "RADIO", None),
                            ("Have you never worked in a similar role?", "RADIO", None),
                            (E1_LABELS[0], "RADIO", profile_with(experience=[]))):
        res, ask = _exp("No", "yes", label, prof, tn)
        if "experience" in _kinds(ask) or (tn == "RADIO" and shown(res) != "No"):
            bad.append((label[:44], tn, what(res), _kinds(ask)))
    assert not bad, report(bad)
