"""Q-121 fix6 pins (real-model run, pages 3 / 26 / 28 / 30) and the review-4 F7 residual.

  (1) COMPUTED FACTS carry `standing:prior_roles` (every role held, built by code from `experience[]`; the words that
      internships and part-time roles count as work experience) and `standing:similar_roles` (class ordinary: Yes
      when any role or project relates to the job's field or uses its main skills; No only when nothing is related).
      With no roles there is no `prior_roles` line.
  (2) `standing:ns_served` for each `ns_status` value (completed -> HAS served; none when unset).
  (3) Work-rights sentences: for a citizen or permanent resident the truth sentence says "may work there with no
      restriction or limit" and the contradiction sentence adds "or has any restriction or limit on the right to work
      there"; a pass holder keeps the old sentences.
  (4) The briefing stays byte-deterministic and its section order unchanged.
  F7  (a DEFECT pin) a SILENT model with NO model class on a declaration- or work-rights-shaped question no code key
      covers: nothing is written with 0 calls unless a canonical frame gave the reader a reading (ruling U9).

Fakes only: no model, no network, sample profile (Singapore citizen, National Service completed), made-up names.
Verify: python tests/run_tests.py -k always_a1_fix6
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402
from test_always_briefing import NEEDS, _build, _lines, _profile as _bprofile  # noqa: E402
from always_a1_support import (  # noqa: E402
    NO_CLASS, YN, FakeAsk, attempt, lie, pick_by, report, shown, what, _pf)
from always_a1_support import profile_with  # noqa: E402


# ------------------------------------------------------------------ (1) prior_roles / similar_roles

@needs(*NEEDS)
def test_fix6_prior_roles_lists_every_role_newest_first_with_the_internship_words():
    b, _ = _build()
    L = _lines(b.text)
    line = L["standing:prior_roles"]
    assert "internships and part-time roles count as work experience" in line, line
    assert "| 2: " in line, line                                  # the count, then the roles
    for title, employer in (("Data Intern", "Sample Analytics"), ("Software Engineering Intern", "Example Logistics Pte Ltd")):
        assert f"{title} at {employer}" in line, (title, line)
    assert line.index("Data Intern at Sample Analytics") < line.index("Software Engineering Intern at"), "newest first"
    # an open-ended role says so; a role with no end date is not given a made-up one
    p = _bprofile()
    p["experience"].insert(0, {"employer": "Current Dummy Pte Ltd", "title": "Engineer", "start": "2023-11",
                               "end": None, "location": "Singapore", "description": "Dummy.", "from_resume": False})
    b2, _ = _build(p)
    assert "Engineer at Current Dummy Pte Ltd (2023-11 to no end date)" in _lines(b2.text)["standing:prior_roles"]


@needs(*NEEDS)
def test_fix6_with_no_roles_there_is_no_prior_roles_line():
    """Coordinator's rule: absent roles -> no `prior_roles` line (the model must not read "0 roles held" as a fact it
    can contradict from the resume)."""
    p = _bprofile()
    p["experience"] = []
    b, _ = _build(p)
    assert "standing:prior_roles" not in _lines(b.text) and "standing:prior_roles" not in b.refs, \
        _lines(b.text).get("standing:prior_roles")


@needs(*NEEDS)
def test_fix6_similar_roles_states_the_rule_for_an_ordinary_class_question():
    b, _ = _build()
    line = _lines(b.text)["standing:similar_roles"]
    assert "class ordinary" in line, line
    assert "relates" in line and "main skills" in line, line
    assert "No only when nothing is related" in line, line
    assert "Yes if any role" in line, line


# ------------------------------------------------------------------ (2) ns_served

@needs(*NEEDS)
def test_fix6_ns_served_follows_each_ns_status_and_is_absent_when_unset():
    cases = (("completed", "HAS served"), ("serving", "IS serving"),
             ("exempted", "has not done National Service"), ("not_applicable", "has not done National Service"))
    for status, words in cases:
        p = _bprofile()
        p["singapore_status"]["ns_status"] = status
        b, _ = _build(p)
        line = _lines(b.text).get("standing:ns_served", "")
        assert words in line, (status, line)
        assert ("HAS served" in line) == (status == "completed"), (status, line)    # never "served" for another status
    for unset in (None, ""):
        p = _bprofile()
        p["singapore_status"]["ns_status"] = unset
        b, _ = _build(p)
        assert "standing:ns_served" not in _lines(b.text) and "standing:ns_served" not in b.refs, unset


# ------------------------------------------------------------------ (4) the facts list and the section order

@needs(*NEEDS)
def test_fix6_the_computed_facts_list_holds_the_three_new_ids_in_place_and_the_section_order_is_unchanged():
    from jobscraper.apply import briefing as BR
    b, _ = _build()
    ids = [ref for ref, _label, _value in BR.computed_facts(_bprofile(), today="2026-11-12")]
    for new in ("standing:prior_roles", "standing:similar_roles", "standing:ns_served"):
        assert new in ids and ids.count(new) == 1, (new, ids)
    assert ids.index("standing:experience_months") < ids.index("standing:prior_roles") < ids.index("standing:similar_roles") \
        < ids.index("standing:graduation_year"), ids
    assert ids.index("standing:currently_employed") < ids.index("standing:ns_served"), ids
    assert all(ref in b.refs for ref in ("standing:prior_roles", "standing:similar_roles", "standing:ns_served"))
    headings = [ln for ln in b.text.splitlines() if ln.startswith("== ") and ln.endswith(" ==")]
    # the three new lines add NO section: the fixed sections keep their order
    order = ("PROFILE", "COMPUTED FACTS", "STANDING RULES")
    pos = [headings.index(f"== {n} ==") for n in order if f"== {n} ==" in headings]
    assert len(pos) == len(order) and pos == sorted(pos), headings


@needs(*NEEDS)
def test_fix6_the_new_lines_are_byte_deterministic_and_do_not_depend_on_today():
    b1, _ = _build()
    b2, _ = _build()
    assert b1.text == b2.text and b1.hash == b2.hash
    b3, _ = _build(today="2027-03-01")
    L1, L3 = _lines(b1.text), _lines(b3.text)
    for ref in ("standing:prior_roles", "standing:similar_roles", "standing:ns_served"):
        assert L1[ref] == L3[ref], (ref, L1[ref], L3[ref])


# ------------------------------------------------------------------ (3) work-rights sentences

CITIZEN_Q = "Do you have any restrictions on your right to work in Singapore?"      # a CANONICAL frame since U10b (fix8)
# the sentence pins need the meaning call, which a canonical frame never reaches (U10: a veto), so they use a wording
# with NO frame: the owner's truth is the same (no restriction)
CITIZEN_Q_NOFRAME = "Is there any restriction on your right to work in Singapore?"


def _wanted(ask):
    conf = [p[1] for p in ask.picks if not p[1].startswith("If the applicant answers")]
    meaning = [p[1] for p in ask.picks if p[1].startswith("If the applicant answers")]
    return conf, meaning


def _citizen_sentences(profile):
    """The confirmation's truth sentence and the meaning call's contradiction sentence for the Singapore question."""
    ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_by("Yes", "yes"))      # the model's Yes agrees: a meaning call
    attempt(_pf("u", CITIZEN_Q_NOFRAME, options=YN), ask, profile)
    return _wanted(ask)


def test_fix6_a_citizen_has_a_no_restriction_truth_and_a_restriction_contradicts_it():
    conf, meaning = _citizen_sentences(None)
    assert conf and "may work there with no restriction or limit" in conf[0], conf
    assert "citizen of Singapore" in conf[0], conf
    assert meaning and "or has any restriction or limit on the right to work there" in meaning[0], meaning


def test_fix6_a_permanent_resident_has_the_same_sentences_and_names_the_status():
    p = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pr")
    conf, meaning = _citizen_sentences(p)
    assert conf and "permanent resident of Singapore" in conf[0] and "no restriction or limit" in conf[0], conf
    assert meaning and "restriction or limit on the right to work" in meaning[0], meaning


def test_fix6_a_pass_holder_keeps_the_old_sentences():
    p = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pass",
                     singapore_status__work_pass="ep")
    conf, meaning = _citizen_sentences(p)
    assert conf and "no restriction or limit" not in conf[0] and "citizen" not in conf[0], conf
    assert meaning and "restriction or limit" not in meaning[0], meaning
    assert "not authorised to work" in meaning[0], meaning


def test_fix6_a_citizens_no_restriction_answer_is_written_and_a_yes_never_is():
    """The owner's truth is "no restriction": a model No (right) with the agreeing confirmation and a "no" meaning reply is
    written (assumed, 2 calls); a model Yes (an invented restriction) is never written without a faithful check."""
    from always_a1_support import pick_faithful
    # (a) no frame: the right No takes the confirmation and the meaning call (2 calls); (b) the canonical frame (U10b,
    # fix8): the right No is written with NO call; a wrong Yes needs the one confirmation that equals the frame; an agreeing
    # wrong Yes pair is a veto with no meaning call. An invented restriction is written in none of them.
    ask = FakeAsk(lambda v: lie("No", "work_right"), pick=pick_by("No", "no"))
    res = attempt(_pf("u", CITIZEN_Q_NOFRAME, options=YN), ask)
    assert shown(res) == "No" and len(ask.picks) == 2, (what(res), len(ask.picks))
    ask = FakeAsk(lambda v: lie("No", "work_right"), pick=pick_by("No", "no"))
    res = attempt(_pf("u", CITIZEN_Q, options=YN), ask)
    assert shown(res) == "No" and not ask.picks, ("framed, right model", what(res), len(ask.picks))
    for q, calls in ((CITIZEN_Q_NOFRAME, 3), (CITIZEN_Q, 1)):
        ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_faithful("No", "No"))
        res = attempt(_pf("u", q, options=YN), ask)
        assert shown(res) == "No" and len(ask.picks) == calls, ("a wrong Yes, right confirmation", q, what(res), len(ask.picks))
    for q, calls in ((CITIZEN_Q_NOFRAME, 2), (CITIZEN_Q, 1)):
        ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick_by("Yes", "yes"))
        res = attempt(_pf("u", q, options=YN), ask)
        assert shown(res) == "" and len(ask.picks) == calls, ("an invented restriction must not be written", q, what(res), len(ask.picks))


# ------------------------------------------------------------------ F7: a silent model, no class, no code key

# (label, the wrong value the F2 fallback writes for the sample owner). No canonical frame, so by U9 no reading.
F7_SILENT = (
    ("Are you independent of Example Employer?", "No"),
    ("Are you restricted from working in the United States?", "No"),       # an OVER-claim for a US posting
    ("Are you currently on a student visa?", "Yes"),                      # a false claim for a Singapore citizen
    ("Are you a fit and proper person?", "No"),
)


def test_f7_a_silent_model_on_a_declaration_or_work_rights_question_with_no_code_key_is_never_written_with_no_call():
    """F7 (ruling U + U9; the engineer's residual; DEFECT pin): a SILENT model (no value, no class) on a declaration- or
    work-rights-shaped question that no code key covers falls back to the F2 generic "No" (or "Yes") with 0 picks. A
    silent model on such a question gets the confirmation call; nothing is written with 0 picks unless a canonical
    frame gave the reader a reading."""
    bad = []
    for label, written in F7_SILENT:
        ask = FakeAsk(pick=pick_by("", ""))
        res = attempt(_pf("u", label, options=YN), ask)
        if shown(res) == written and not ask.picks:
            bad.append((label[:50], what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_f7_a_silent_model_on_a_military_question_is_not_answered_no_for_a_completed_owner():
    """F7 / F3: "Have you served in the military, including National Service?" is ORDINARY (no declaration truth), and the
    owner COMPLETED National Service (`standing:ns_served`). A silent model must not end on the generic "No" with 0
    picks: a false statement of no service."""
    ask = FakeAsk(pick=pick_by("", ""))
    res = attempt(_pf("u", "Have you served in the military, including National Service?", options=YN), ask)
    assert shown(res) != "No", ("a false 'no military service' from the F2 fallback", what(res), len(ask.picks))
