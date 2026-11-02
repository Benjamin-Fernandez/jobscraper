"""WP-Q0 oracles for D-75, the work-rights defaults (questions_design.md 8.1, 8.2, 13 oracles 1-15).

Every case runs through the real resolver (`resolve.resolve_all`) over the fixture rules file
tests/fixtures/apply/questions_d75.yaml (the two `country_bool` rows plus trimmed residency and work-pass
rows). Once WP-A04 puts the same two rows in config/questions.yaml, every case runs over that file too:
`_rule_files()` adds it as soon as it holds a `kind: country_bool` row.

Built by WP-P9 (lane Q: `applicant.work_rights`, the `country_bool` kind, `resolve.label_countries`,
`ResolveContext.job_country`, `grounding_text`, `user_prompt`). Skip-clean until `resolve.label_countries`
and `applicant.work_rights` exist. The fixture integrity tests below run now.

`source` is `profile:singapore_status.<map>.<C or default or standing>` and `rule_id` is the map key
(QD 8.2 step 6). No model is called by any case except where a stub is scripted to prove it is not.
No network, synthetic data only.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import textwrap
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    D75_RULES, REAL_RULES, StubBackend, chosen, ctx_for, field, needs, profile, report_waiting,
    resolve_one, waiting_mark, with_work_rights, yes_no,
)

from jobscraper.apply.contracts import AnswerStatus, AnswerTier, FieldType  # noqa: E402

_MARK = waiting_mark()
AUTH = "singapore_status.authorised_to_work"
SPONS = "singapore_status.requires_sponsorship"
GATE = ("jobscraper.apply.resolve:label_countries", "jobscraper.applicant:work_rights")


def _R():
    return importlib.import_module("jobscraper.apply.resolve")


def _has_country_bool(path: Path) -> bool:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    return any(isinstance(e, dict) and e.get("kind") == "country_bool" for e in data.get("questions") or [])


def _rule_files() -> list[Path]:
    """The fixture always; the real file once WP-A04 has put the country_bool rows in it."""
    return [D75_RULES] + ([REAL_RULES] if _has_country_bool(REAL_RULES) else [])


def _spy() -> StubBackend:
    """A model that WOULD answer if asked: a call is a failure of D-75 (it never reaches the model)."""
    return StubBackend([{"choice": 0, "evidence": "x"}] * 4)


def _ask(label, prof, rules, **kw):
    be = _spy()
    a = resolve_one(yes_no("q", label), prof, rules, backend=be, **kw)
    assert be.calls == [], f"{rules.name}: the model must not be called for {label!r}"
    return a


def _expect(a, rules, label, *, answer, rule_id, source_suffix=None):
    where = f"[{rules.name}] {label!r}"
    assert a.status is AnswerStatus.FILLED, (where, a)
    assert chosen(a) == (answer,), (where, a)
    assert a.tier is AnswerTier.PROFILE_RULE and not a.sensitive, (where, a)
    assert a.rule_id == rule_id, (where, a.rule_id)
    assert a.confidence == 0.95, where
    if source_suffix is not None:
        assert a.source == f"profile:{rule_id}.{source_suffix}", (where, a.source)


# ================================================================== fixtures (run now)

def test_the_d75_fixture_has_the_two_country_bool_rows_built_to_the_researchers_rules():
    data = yaml.safe_load(D75_RULES.read_text(encoding="utf-8"))
    rows = {e["key"]: e for e in data["questions"]}
    auth, spons = rows[AUTH], rows[SPONS]
    assert auth["kind"] == spons["kind"] == "country_bool"
    assert not [k for k in rows if k.startswith((AUTH + ".", SPONS + "."))], "the four per-country rows are gone"
    need_a = {"right to work", "eligible to work", "authorized to work", "work authorization",
              "without sponsorship"}
    need_s = {"require sponsorship", "visa sponsorship", "now or in the future require",
              "work permit required", "require an employment pass"}
    assert need_a <= set(auth["synonyms"]) and need_s <= set(spons["synonyms"])
    assert "without" in (spons.get("exclude") or []), "the sponsorship row excludes `without`"
    assert not any("without" in s for s in spons["synonyms"]), "`without ...` phrases belong to the authorised row"
    assert not auth.get("exclude"), "no country excludes: the country is detected, not excluded"
    assert "value_map" not in auth and "yes_if" not in auth and "value_map" not in spons and "yes_if" not in spons
    assert rows["singapore_status.residency_status"]["yes_if"][0]["id"] == "sg_citizen"
    assert rows["singapore_status.work_pass"]["yes_if"][0]["id"] == "holds_ep"


def test_the_real_questions_file_either_has_no_country_bool_yet_or_both_rows_in_the_a04_shape():
    data = yaml.safe_load(REAL_RULES.read_text(encoding="utf-8"))
    rows = {e["key"]: e for e in data["questions"]}
    if not _has_country_bool(REAL_RULES):
        return                              # WP-A04 has not landed: the fixture stands in
    assert AUTH in rows and SPONS in rows
    assert rows[AUTH]["kind"] == rows[SPONS]["kind"] == "country_bool"
    assert not [k for k in rows if k.startswith((AUTH + ".", SPONS + "."))]
    assert "without" in (rows[SPONS].get("exclude") or []) and not any("without" in s for s in rows[SPONS]["synonyms"])


# ================================================================== label_countries (QD 8.2 step 1)

@needs(*GATE)
def test_label_countries_names_countries_by_phrase_and_alias_and_never_by_the_word_us():
    lc = _R().label_countries
    assert lc("are you authorized to work in the united states") == {"US"}
    for alias in ("united states of america", "u s", "u s a", "usa", "america"):
        assert lc(f"work in {alias}") == {"US"}, alias
    for alias in ("uk", "u k", "britain", "great britain", "england", "united kingdom"):
        assert lc(f"work in the {alias}") == {"GB"}, alias
    for alias in ("european union", "eu", "eea", "europe"):
        assert lc(f"work in the {alias}") == {"EU"}, alias
    for alias in ("uae", "united arab emirates"):
        assert lc(f"work in the {alias}") == {"AE"}, alias
    assert lc("are you eligible to work in canada") == {"CA"}
    assert lc("are you authorised to work for us") == set(), "`us` alone is never a country"
    assert lc("do you have a right to work in singapore or canada") == {"SG", "CA"}
    assert lc("where are you located") == set()


# ================================================================== oracles 1-12 (QD 13)

@needs(*GATE)
def test_d75_1_authorised_in_the_us_with_the_default_true_answers_yes_from_default():
    label = "Are you legally authorized to work in the United States?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "default": True}, {"SG": False, "default": False})
        a = _ask(label, prof, rules)
        _expect(a, rules, label, answer="Yes", rule_id=AUTH, source_suffix="default")


@needs(*GATE)
def test_d75_2_the_countrys_own_key_beats_the_default():
    label = "Are you legally authorized to work in the United States?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "US": False, "default": True}, {"SG": False, "default": False})
        a = _ask(label, prof, rules)
        _expect(a, rules, label, answer="No", rule_id=AUTH, source_suffix="US")


@needs(*GATE)
def test_d75_3_sponsorship_now_or_in_the_future_answers_no_for_the_job_country():
    label = "Will you now or in the future require sponsorship for employment visa status (e.g. H-1B)?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "default": True}, {"SG": False, "default": False})
        a = _ask(label, prof, rules)
        _expect(a, rules, label, answer="No", rule_id=SPONS, source_suffix="SG")   # no country named: the job's


@needs(*GATE)
def test_d75_4_an_absent_map_uses_the_standing_answer_for_the_uk():
    label = "Do you require visa sponsorship to work in the UK?"
    for rules in _rule_files():
        a = _ask(label, with_work_rights(None, None), rules)
        _expect(a, rules, label, answer="No", rule_id=SPONS, source_suffix="standing")


@needs(*GATE)
def test_d75_5_a_label_naming_no_country_means_the_job_country_sg():
    label = "Are you authorised to work in the country where this job is located?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "US": False, "default": False}, {"SG": False})
        a = _ask(label, prof, rules)                 # default is False here: only the SG key says Yes
        _expect(a, rules, label, answer="Yes", rule_id=AUTH, source_suffix="SG")
        a = _ask(label, prof, rules, job_country="US")
        _expect(a, rules, label, answer="No", rule_id=AUTH, source_suffix="US")   # the context decides


@needs(*GATE)
def test_d75_6_work_permit_required_answers_no():
    label = "Work permit required?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "default": True}, {"SG": False, "default": False})
        a = _ask(label, prof, rules)
        _expect(a, rules, label, answer="No", rule_id=SPONS)


@needs(*GATE)
def test_d75_7_canada_with_no_maps_is_yes_by_the_standing_answer():
    label = "Are you eligible to work in Canada?"
    for rules in _rule_files():
        a = _ask(label, with_work_rights(None, None), rules)
        _expect(a, rules, label, answer="Yes", rule_id=AUTH, source_suffix="standing")


@needs(*GATE)
def test_d75_8_without_sponsorship_combines_authorisation_and_the_sponsorship_need():
    # Written "U.S." (normalises to the alias `u s`). QD 13 writes "US", but a bare "US" normalises to
    # `us`, which QD 8.2 says is never a country ("work for us"): see the tester outbox, question 1.
    label = "Can you work in the U.S. without sponsorship?"
    for rules in _rule_files():
        needs_visa = with_work_rights({"SG": True, "US": True}, {"SG": False, "US": True})
        a = _ask(label, needs_visa, rules)           # a(US) = true, s(US) = true -> a and not s = false
        _expect(a, rules, label, answer="No", rule_id=AUTH)
        defaults = with_work_rights({"default": True}, {"default": False})
        a = _ask(label, defaults, rules)             # a = true, s = false -> true
        _expect(a, rules, label, answer="Yes", rule_id=AUTH)


@needs(*GATE)
def test_d75_9_countries_that_disagree_stop_without_the_model():
    label = "Are you authorised to work in the U.S. or Canada?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "US": False, "default": True}, {"SG": False})
        be = _spy()
        a = resolve_one(yes_no("q", label), prof, rules, backend=be)
        assert be.calls == [], f"[{rules.name}] D-75: a conflict never reaches the model"
        assert a.status is AnswerStatus.UNKNOWN and not a.fills, (rules.name, a)
        assert "work rights differ" in a.note, (rules.name, a.note)
        assert "US" in a.note and "CA" in a.note, "the note names the countries"
        assert not a.sensitive, "a conflict is not a sensitive stop"
    # the same label, when the values agree, is answered
    prof = with_work_rights({"SG": True, "default": True}, {"SG": False})
    for rules in _rule_files():
        _expect(_ask(label, prof, rules), rules, label, answer="Yes", rule_id=AUTH)


@needs(*GATE)
def test_d75_10_for_us_is_the_employer_not_the_country():
    label = "Are you authorised to work for us?"
    for rules in _rule_files():
        prof = with_work_rights({"SG": True, "US": False, "default": True}, {"SG": False, "US": True})
        a = _ask(label, prof, rules)
        _expect(a, rules, label, answer="Yes", rule_id=AUTH, source_suffix="SG")


@needs(*GATE)
def test_d75_11_citizenship_still_comes_from_the_residency_status_row():
    label = "Are you a Singapore Citizen?"
    for rules in _rule_files():
        a = _ask(label, profile(), rules)
        assert chosen(a) == ("Yes",), (rules.name, a)
        assert a.rule_id == "singapore_status.residency_status#sg_citizen", (rules.name, a.rule_id)
        assert a.sensitive, "residency is S (never sent to the model)"


@needs(*GATE)
def test_d75_12_a_work_pass_question_still_comes_from_the_work_pass_row():
    label = "Do you hold an Employment Pass?"
    for rules in _rule_files():
        a = _ask(label, profile(), rules)
        assert chosen(a) == ("No",), (rules.name, a)         # work_pass is none_required in the sample
        assert a.rule_id == "singapore_status.work_pass#holds_ep", (rules.name, a.rule_id)


# ================================================================== fit and shape (QD 8.2 step 5)

@needs(*GATE)
def test_a_work_rights_question_with_options_that_are_not_yes_no_is_not_answered_by_this_tier():
    f = field("q", "Are you eligible to work in Canada?", FieldType.DROPDOWN,
              ("Citizen", "Permanent resident", "Work permit"))
    for rules in _rule_files():
        be = StubBackend([{"choice": 0, "evidence": "x"}] * 2)
        a = resolve_one(f, with_work_rights(None, None), rules, backend=be)
        assert not (a.tier is AnswerTier.PROFILE_RULE and a.rule_id == AUTH), (rules.name, a)
        assert not a.sensitive, "not a sensitive stop: the later tiers may still try"


@needs(*GATE)
def test_a_text_or_checkbox_field_takes_the_work_rights_answer_too():
    for rules in _rule_files():
        t = resolve_one(field("q", "Are you legally authorised to work in Singapore?", FieldType.TEXT),
                        profile(), rules, backend=_spy())
        assert t.value == "Yes" and t.rule_id == AUTH, (rules.name, t)
        c = resolve_one(field("q", "I am eligible to work in Canada", FieldType.CHECKBOX),
                        with_work_rights(None, None), rules, backend=_spy())
        assert c.value == "true" and c.rule_id == AUTH, (rules.name, c)


# ================================================================== oracles 13-15 (QD 13)

@needs(*GATE)
def test_d75_13_missing_for_apply_no_longer_lists_the_two_sg_paths():
    import jobscraper.applicant as A
    assert "singapore_status.authorised_to_work.SG" not in A.REQUIRED_PATHS
    assert "singapore_status.requires_sponsorship.SG" not in A.REQUIRED_PATHS
    prof = with_work_rights({}, {})
    miss = A.missing_for_apply(prof, resume_dir=tempfile.mkdtemp())
    assert "singapore_status.authorised_to_work.SG" not in miss
    assert "singapore_status.requires_sponsorship.SG" not in miss
    prof = with_work_rights(None, None)
    assert not [m for m in A.missing_for_apply(prof, resume_dir=tempfile.mkdtemp())
                if m.startswith(("singapore_status.authorised", "singapore_status.requires"))]


@needs(*GATE)
def test_d75_14_the_grounding_text_and_the_tier5_prompt_carry_the_standing_work_rights():
    import jobscraper.applicant as A
    sentence = "The applicant has the right to work and needs no visa sponsorship."
    prof = with_work_rights({"SG": True, "default": True}, {"SG": False, "default": False})
    assert A.grounding_text(prof).rstrip().endswith(sentence), "work_rights_text is the last line"
    assert A.grounding_text(with_work_rights(None, None)).rstrip().endswith(sentence), "absent maps: the standing answer"
    differs = with_work_rights({"SG": True, "US": False, "default": True}, {"SG": False})
    assert A.grounding_text(differs).rstrip().endswith(A.work_rights_text(differs))
    assert "For US: does not have the right to work." in A.grounding_text(differs)

    R = _R()
    f = field("q", "Why do you want to work here?", FieldType.TEXTAREA)
    prompt = R.user_prompt(f, "text", ctx_for(prof), 255)
    assert '"work_rights"' in prompt, "the APPLICANT JSON gains a work_rights key"
    assert sentence in prompt
    be = StubBackend([{"unknown": True, "text": ""}])
    resolve_one(f, prof, D75_RULES, backend=be)
    assert be.calls and sentence in be.calls[0]["user"], "the model is always told the standing work rights"


@needs(*GATE)
def test_d75_15_the_loader_refuses_country_bool_on_another_key_and_with_value_map_or_yes_if():
    R = _R()

    def load(body: str):
        d = Path(tempfile.mkdtemp())
        p = d / "questions.yaml"
        p.write_text(textwrap.dedent(body), encoding="utf-8")
        return R.load_rules(p)

    ok = """
        version: 1
        questions:
          - key: singapore_status.authorised_to_work
            kind: country_bool
            synonyms: [right to work]
          - key: singapore_status.requires_sponsorship
            kind: country_bool
            synonyms: [require sponsorship]
            exclude: [without]
    """
    assert len(load(ok).rules) == 2, "the two map keys load"

    def refused(body: str, why: str):
        try:
            load(body)
        except ValueError as e:
            assert "country_bool" in str(e) or "singapore_status" in str(e) or "kind" in str(e), (why, str(e))
        else:
            raise AssertionError(f"the loader must refuse: {why}")

    refused("""
        version: 1
        questions:
          - key: availability.notice_period_days
            kind: country_bool
            synonyms: [notice period]
    """, "country_bool on another key")
    refused("""
        version: 1
        questions:
          - key: singapore_status.authorised_to_work
            kind: country_bool
            synonyms: [right to work]
            value_map: {yes: [yes]}
    """, "value_map on country_bool")
    refused("""
        version: 1
        questions:
          - key: singapore_status.authorised_to_work
            kind: country_bool
            synonyms: [right to work]
            yes_if:
              - {id: x, values: [yes], synonyms: [abc]}
    """, "yes_if on country_bool")


report_waiting("test_apply_resolve_rules", _MARK)
