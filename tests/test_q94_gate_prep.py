"""Q-94 gate-prep pins (tester): four small fixes the M20 gate depends on.

  1. WP-A04 end to end (Q-30 review F5, docs/reviews/Q-30.md): the REAL config/questions.yaml, loaded
     by `resolve.load_rules`, answers the work-rights questions through its two `country_bool` rows
     (the sample applicant: authorised {SG: true, US: false}, sponsorship {SG: false}); the four
     per-country `.SG`/`.US` rows are gone. The D-75 cases over the fixture rules file stay in
     test_apply_resolve_rules.py.
  2. Q-43: an experience `end` of Present / current / now / ongoing / to date reads as None (ongoing)
     and validates clean; a real date is kept; an empty string keeps the behaviour it had.
  3. R3 F11: one definition each. `pagefill.L1_KEPT_NOTE is locks.L1_KEPT_NOTE` and
     `pagefill.FACT_SOURCES is guards.FACT_SOURCES`, and no second copy of the text / the triple
     lives anywhere else in src/.
  4. Q-46 e, loop half (no browser): a Next that neither changes the step nor shows an error is
     pressed once, then the same read comes back and the attempt ends PAGE_UNRECOGNISED "shown
     again". The browser half (the real Workday navigator on a page whose Next does nothing) is in
     test_q94_gate_prep_edge.py.

Each pin is defined only once its feature is in the tree (the repo's gating habit); one line at import
says what waits. `Q94_FORCE=1` defines every pin regardless, to see how a missing feature fails.
No network, no model, no Edge, synthetic applicant, temp DB, never data/ or port 8765.
Verify: python tests/run_tests.py -k q94
"""
from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402
from questions_support import (  # noqa: E402
    REAL_RULES, StubBackend, chosen, profile, resolve_one, yes_no,
)

import yaml  # noqa: E402

from jobscraper.apply.contracts import AnswerStatus, AnswerTier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jobscraper"
FORCE = bool(os.environ.get("Q94_FORCE"))
_WAITING: list[tuple[str, str]] = []


def gated(ready: bool, what: str):
    """The decorated pin is not defined until `ready` (or Q94_FORCE); the reason is printed once."""
    def deco(fn):
        if ready or FORCE:
            return fn
        _WAITING.append((getattr(fn, "__name__", "?"), what))
        return None
    return deco


AUTH = "singapore_status.authorised_to_work"
SPONS = "singapore_status.requires_sponsorship"
RESOLVER = ("jobscraper.apply.resolve:label_countries", "jobscraper.applicant:work_rights")


def _real_rows() -> list[dict]:
    return (yaml.safe_load(REAL_RULES.read_text(encoding="utf-8")) or {}).get("questions") or []


def _real_has_country_bool() -> bool:
    return any(isinstance(e, dict) and e.get("kind") == "country_bool" for e in _real_rows())


def _q43_landed() -> bool:
    from jobscraper import applicant as A
    p = profile()
    p["experience"] = [{"employer": "E", "title": "T", "start": "2022-01", "end": "Present"}]
    return A.normalise(p)["experience"][0]["end"] is None


def _f11_landed() -> bool:
    try:
        from jobscraper.apply import guards, locks
    except ImportError:
        return False
    return hasattr(locks, "L1_KEPT_NOTE") and hasattr(guards, "FACT_SOURCES")


# ================================================================== 1. WP-A04 end to end

def _ask_real(label, **kw):
    spy = StubBackend([{"choice": 0, "evidence": "x"}] * 4)        # would answer if asked: a call is a failure
    a = resolve_one(yes_no("q", label), profile(), REAL_RULES, backend=spy, **kw)
    assert spy.calls == [], f"the model must not be asked for {label!r}"
    return a


def _expect(a, label, *, answer, rule_id, suffix):
    where = repr(label)
    assert a.status is AnswerStatus.FILLED, (where, a)
    assert chosen(a) == (answer,), (where, chosen(a), a.source)
    assert a.tier is AnswerTier.PROFILE_RULE and not a.sensitive, (where, a.tier)
    assert a.rule_id == rule_id, (where, a.rule_id)
    assert a.source == f"profile:{rule_id}.{suffix}", (where, a.source)


@gated(_real_has_country_bool(), "config/questions.yaml country_bool rows (WP-A04)")
def test_q94_real_file_has_two_country_bool_rows_and_no_per_country_keys():
    rows = {e["key"]: e for e in _real_rows()}
    assert rows[AUTH]["kind"] == rows[SPONS]["kind"] == "country_bool"
    old = [k for k in rows if k.startswith((AUTH + ".", SPONS + "."))]
    assert not old, f"the old per-country keys are gone, found {old}"
    assert not [k for k in rows if re.search(r"(authorised_to_work|requires_sponsorship)\.(SG|US)$", k)]
    assert "without" in (rows[SPONS].get("exclude") or []), "the sponsorship row excludes `without`"
    assert not any("without" in s for s in rows[SPONS]["synonyms"])


@gated(_real_has_country_bool(), "config/questions.yaml country_bool rows (WP-A04)")
@needs(*RESOLVER)
def test_q94_real_file_load_rules_resolves_the_four_work_rights_questions_through_the_new_rows():
    from jobscraper.apply import resolve
    resolve.load_rules(REAL_RULES)                                   # the real file loads: kinds, synonyms, excludes
    _expect(_ask_real("Are you legally authorised to work in Singapore?"),
            "Are you legally authorised to work in Singapore?", answer="Yes", rule_id=AUTH, suffix="SG")
    _expect(_ask_real("Are you eligible to work in the United States?"),
            "Are you eligible to work in the United States?", answer="No", rule_id=AUTH, suffix="US")
    _expect(_ask_real("Do you now or in the future require visa sponsorship?"),
            "Do you now or in the future require visa sponsorship?", answer="No", rule_id=SPONS, suffix="SG")
    _expect(_ask_real("Will you require an Employment Pass?"),
            "Will you require an Employment Pass?", answer="No", rule_id=SPONS, suffix="SG")


@gated(_real_has_country_bool(), "config/questions.yaml country_bool rows (WP-A04)")
@needs(*RESOLVER)
def test_q94_real_file_able_to_work_without_sponsorship_hits_the_authorised_row_not_sponsorship():
    label = "Are you able to work without sponsorship?"
    a = _ask_real(label)                                  # no country named: the job's, SG; a(SG) and not s(SG)
    assert a.rule_id == AUTH, (a.rule_id, "must be the authorised row, not " + SPONS)
    assert a.status is AnswerStatus.FILLED and chosen(a) == ("Yes",), (chosen(a), a.source)
    # the same words with a visa need make the answer No, still from the authorised row
    p = profile()
    p["singapore_status"]["requires_sponsorship"] = {"SG": True}
    spy = StubBackend([{"choice": 0, "evidence": "x"}] * 4)
    b = resolve_one(yes_no("q", label), p, REAL_RULES, backend=spy)
    assert spy.calls == [] and b.rule_id == AUTH and chosen(b) == ("No",), (b.rule_id, chosen(b))


@gated(_real_has_country_bool(), "config/questions.yaml country_bool rows (WP-A04)")
@needs(*RESOLVER)
def test_q94_real_file_the_countrys_own_key_decides_and_an_unlisted_country_uses_the_standing_answer():
    # sample map {SG: true, US: false}: the US key says No; Canada has no key and no default -> standing Yes
    a = _ask_real("Are you authorized to work in the United States?")
    assert a.rule_id == AUTH and chosen(a) == ("No",) and a.source.endswith(".US"), (chosen(a), a.source)
    c = _ask_real("Are you eligible to work in Canada?")
    assert c.rule_id == AUTH and chosen(c) == ("Yes",) and c.tier is AnswerTier.PROFILE_RULE, (chosen(c), c.source)
    assert c.source.endswith(".standing"), c.source


# ---- D-180 / D-181 (Q-94 review F1, F2; questions_design.md 8.2): two false answers closed

def _resolve_real(label):
    """(answer, number of model calls) for a yes/no label through the real rules on the sample applicant."""
    spy = StubBackend([{"choice": 0, "evidence": "x"}] * 4)
    a = resolve_one(yes_no("q", label), profile(), REAL_RULES, backend=spy)
    return a, len(spy.calls)


def _note_lands(label: str, text: str) -> bool:
    try:
        return text in _resolve_real(label)[0].note
    except Exception:                                   # noqa: BLE001 - a gate probe must never break the import
        return False


_D180 = _note_lands("Are you authorised to work in London?", "place not recognised")
_D181 = _note_lands("Are you a US citizen or permanent resident?", "names another country")

SG_AUTH_SOURCE = f"profile:{AUTH}.SG"


def _stopped(label, note):
    a, calls = _resolve_real(label)
    assert calls == 0, f"{label!r}: a stop never reaches the model ({calls} calls)"
    assert a.status is AnswerStatus.UNKNOWN and not a.fills, (label, a.status, a.source)
    assert note in a.note, (label, a.note)
    assert not a.sensitive, label
    assert a.tier is not AnswerTier.LLM, (label, a.tier)
    return a


@gated(_D180, "resolve: D-180 place not recognised")
@needs(*RESOLVER)
def test_q94_d180_an_unknown_place_or_a_region_stops_the_work_rights_label_unanswered():
    for label in ("Are you authorised to work in London?",
                  "Are you legally authorised to work worldwide?",   # "able to work worldwide?" matches no row: out of D-180 scope
                  "Are you authorised to work anywhere in APAC?",
                  "Do you require visa sponsorship to work in EMEA?",
                  "Do you require visa sponsorship to work in Europe or Asia?"):
        a = _stopped(label, "place not recognised")
        assert a.source != SG_AUTH_SOURCE and "SG" not in a.source, (label, a.source)


@gated(_D180, "resolve: D-180 place not recognised")
@needs(*RESOLVER)
def test_q94_d180_spain_is_either_stopped_as_an_unknown_place_or_answered_for_spain_never_for_singapore():
    label = "Are you authorised to work in Spain?"
    from jobscraper.apply import resolve
    a, calls = _resolve_real(label)
    assert calls == 0, "never the model"
    if resolve.label_countries("are you authorised to work in spain") == {"ES"}:   # the engineer added Spain
        assert a.status is AnswerStatus.FILLED and a.rule_id == AUTH, (a.status, a.rule_id, a.note)
        # the sample map has no ES key and no default: the standing answer, not the SG key
        assert a.source == f"profile:{AUTH}.standing", a.source
    else:
        _stopped(label, "place not recognised")


@gated(_D180, "resolve: D-180 place not recognised")
@needs(*RESOLVER)
def test_q94_d180_labels_with_no_place_or_a_generic_place_keep_the_job_country_singapore():
    for label in ("Are you authorised to work in this country?",
                  "Are you authorised to work in the location of this role?",
                  "Are you authorised to work in the country where this job is located?",
                  "Do you have the right to work?"):
        a, calls = _resolve_real(label)
        assert calls == 0, label
        assert a.status is AnswerStatus.FILLED and chosen(a) == ("Yes",), (label, a.status, a.note)
        assert a.rule_id == AUTH and a.source == SG_AUTH_SOURCE, (label, a.rule_id, a.source)
    a, _ = _resolve_real("Are you authorised to work in Singapore?")
    assert a.status is AnswerStatus.FILLED and a.source == SG_AUTH_SOURCE and chosen(a) == ("Yes",)
    # the sponsorship row keeps step 2 as well
    b, _ = _resolve_real("Do you require visa sponsorship to work in this country?")
    assert b.status is AnswerStatus.FILLED and b.rule_id == SPONS and chosen(b) == ("No",), (b.rule_id, b.note)


@gated(_D181, "resolve: D-181 names another country")
@needs(*RESOLVER)
def test_q94_d181_a_singapore_residency_row_never_answers_another_countrys_citizenship():
    for label in ("Are you a US citizen or permanent resident?",
                  "Are you a Canadian citizen or permanent resident?",
                  "Are you a citizen or permanent resident of the United States?"):
        a = _stopped(label, "names another country")
        assert "residency_status" not in a.source, (label, a.source)


@gated(_D181, "resolve: D-181 names another country")
@needs(*RESOLVER)
def test_q94_d181_a_bare_british_citizen_label_is_never_answered_from_the_singapore_row():
    # "Are you a British citizen?" matches no residency synonym (those need "singapore citizen", "are you a
    # citizen" ...), so D-181's stop (matched rows only) cannot fire and the label takes the tier-5 path.
    # Pinned: the Singapore row never answers it. The strict stop is only for labels that match a row.
    a, _calls = _resolve_real("Are you a British citizen?")
    assert "residency_status" not in a.rule_id + a.source and "work_pass" not in a.rule_id + a.source,         (a.rule_id, a.source)
    assert not (a.status is AnswerStatus.FILLED and a.tier is AnswerTier.PROFILE_RULE), (a.status, a.tier)
    # and the demonym stops a label that DOES match a residency row
    b = _stopped("Are you a British citizen or permanent resident?", "names another country")
    assert "residency_status" not in b.source


@gated(_D181, "resolve: D-181 names another country")
@needs(*RESOLVER)
def test_q94_d181_the_singapore_and_the_no_country_citizenship_labels_still_answer_from_the_singapore_row():
    for label in ("Are you a Singapore Citizen or Permanent Resident?",
                  "Are you a Singaporean citizen?",              # the Singapore demonym is the one that stays
                  "Are you a citizen or permanent resident?"):
        a, calls = _resolve_real(label)
        assert calls == 0, label
        assert a.status is AnswerStatus.FILLED and chosen(a) == ("Yes",), (label, a.status, a.note)
        assert a.rule_id.startswith("singapore_status.residency_status") and a.tier is AnswerTier.PROFILE_RULE,             (label, a.rule_id)


# ================================================================== 2. Q-43 ongoing entry end

def _with_end(end, lst="experience"):
    p = profile()
    entry = {"employer": "Example Pte Ltd", "title": "Intern", "start": "2022-01", "end": end}
    p[lst] = [entry]
    return p


@gated(_q43_landed(), "applicant.normalise reading Present as ongoing (Q-43)")
def test_q94_q43_present_current_now_ongoing_to_date_end_reads_as_none_and_validates_clean():
    from jobscraper import applicant as A
    for word in ("Present", "present ", "Current", "now", "Ongoing", "to date"):
        p = _with_end(word)
        before = copy.deepcopy(p)
        n = A.normalise(p)
        assert n["experience"][0]["end"] is None, (word, n["experience"][0]["end"])
        assert n["experience"][0]["start"] == "2022-01", "only the end is read this way"
        assert p == before, "normalise returns a copy"
        assert A.normalise(n) == n, "idempotent"
        errs = [(e.path, e.message) for e in A.validate(p)]
        assert not [e for e in errs if e[0].startswith("experience")], (word, errs)


@gated(_q43_landed(), "applicant.normalise reading Present as ongoing (Q-43)")
def test_q94_q43_the_word_is_accepted_in_any_case_and_with_spaces():
    from jobscraper import applicant as A
    for word in ("PRESENT", "  Present  ", "Current ", "NOW", "ongoing", "To Date"):
        n = A.normalise(_with_end(word))
        assert n["experience"][0]["end"] is None, repr(word)


@gated(_q43_landed(), "applicant.normalise reading Present as ongoing (Q-43)")
def test_q94_q43_a_real_date_stays_a_date_and_other_words_are_still_refused():
    from jobscraper import applicant as A
    n = A.normalise(_with_end("2023-05"))
    assert n["experience"][0]["end"] == "2023-05"
    assert not [e for e in A.validate(_with_end("2023-05")) if e.path.startswith("experience")]
    assert A.normalise(_with_end("2023-05-17"))["experience"][0]["end"] == "2023-05-17", "a full day is kept"
    for junk in ("sometime", "2023-13", "tomorrow"):
        errs = {e.path for e in A.validate(_with_end(junk))}
        assert "experience[0].end" in errs, (junk, errs)
    p = _with_end("Present")
    p["experience"][0]["end"] = "Present"
    p["experience"][0]["start"] = "2022-01"
    assert A.normalise(p)["experience"][0]["end"] is None


@gated(_q43_landed(), "applicant.normalise reading Present as ongoing (Q-43)")
def test_q94_q43_an_empty_end_keeps_the_behaviour_it_had_a_blank_string_stays_blank_and_validates_clean():
    # Read before Q-43 (2026-11-10, 874f1dc): normalise("") -> "" (untouched), validate: no error for
    # an empty end (`_empty` skips it). The fix must not turn a blank into a date or into an error.
    from jobscraper import applicant as A
    for blank in ("", None):
        p = _with_end(blank)
        assert A.normalise(p)["experience"][0]["end"] == blank, repr(blank)
        assert not [e for e in A.validate(p) if e.path.startswith("experience")], repr(blank)


# ================================================================== 3. R3 F11 one definition

@gated(_f11_landed(), "locks.L1_KEPT_NOTE and guards.FACT_SOURCES (R3 F11)")
def test_q94_f11_pagefill_uses_the_one_l1_kept_note_from_locks():
    from jobscraper.apply import locks, pagefill
    assert pagefill.L1_KEPT_NOTE is locks.L1_KEPT_NOTE
    assert locks.L1_KEPT_NOTE == "L1: kept, uploaded in this attempt"      # the audit rows carry this text
    hits = [p.name for p in SRC.rglob("*.py") if '"L1: kept, uploaded in this attempt"' in p.read_text(encoding="utf-8")]
    assert hits == ["locks.py"], f"the note text is written once, in locks.py: {hits}"


@gated(_f11_landed(), "locks.L1_KEPT_NOTE and guards.FACT_SOURCES (R3 F11)")
def test_q94_f11_pagefill_uses_the_one_fact_sources_from_guards():
    from jobscraper.apply import guards, pagefill
    from jobscraper.apply.contracts import FillSource
    assert pagefill.FACT_SOURCES is guards.FACT_SOURCES
    assert guards.FACT_SOURCES == frozenset({FillSource.PROFILE, FillSource.EXTRA, FillSource.STANDING})
    triple = re.compile(r"FillSource\.PROFILE,\s*FillSource\.EXTRA,\s*FillSource\.STANDING")
    hits = [p.name for p in SRC.rglob("*.py") if triple.search(p.read_text(encoding="utf-8"))]
    assert hits == ["guards.py"], f"the fact-source set is written once, in guards.py: {hits}"


# ================================================================== 4. Q-46 e, loop half

def _flow():
    import test_apply_flow_n6a as N
    return N


def test_q94_q46e_a_next_that_changes_nothing_is_pressed_once_then_the_same_read_ends_the_attempt():
    N = _flow()
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    w, jid = N.world()
    try:
        nav = N.FakeNav()
        nav.stay = True                       # Next returns the same step, no errors (Workday's silent no-op)
        with N.scripted(nav, N.two_steps) as seen:
            r, *_ = N.run(w, jid, nav)
        assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED, (r.state, r.reason, r.reason_detail)
        assert "shown again" in r.reason_detail and "one" in r.reason_detail, r.reason_detail
        assert nav.calls.count("next") == 1, f"Next pressed {nav.calls.count('next')} times: {nav.calls}"
        assert len(seen) == 2, "the page was read twice (once before the click, once after), pressed once"
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None
    finally:
        w.close()


_PENDING = sorted({w for _n, w in _WAITING})
if _PENDING:
    print(f"[q94_gate_prep] {len(_WAITING)} pins wait for: {', '.join(_PENDING)}")
