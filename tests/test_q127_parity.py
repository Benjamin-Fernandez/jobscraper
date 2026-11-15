"""Q-127 W1 parity and shape pins (design B.5, B.8; W1 handoff (b) (c)).

`web/` may not import the stage code (tests/test_layering.py), so `web/remember.py` holds COPIES of
`apply.plan.norm_label` / `is_generic` and `apply.questions.slug_key`. A copy that drifts would write
an `extra` entry under a label the resolver never matches, so the copies are pinned against the
originals over a table of 15 labels. Also: `applicant.SECTIONS`, `path_filled`, the `extra` metadata
rules (`promoted`, `employer`, `labels: []` only with `promoted`) and the saved-answers routes
(`GET /api/apply/remembered`, `DELETE /api/apply/remembered/{key}`), at route level on a temp profile.
Made-up names only; no model, no network, nothing from data/.
Verify: python tests/run_tests.py -k q127_parity
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_support  # noqa: E402,F401
from test_q127_web import _file, _world  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper.apply import plan, questions  # noqa: E402
from jobscraper.web import remember as W  # noqa: E402

LABELS = [
    "Please specify", "Details", "Notice period (days)", "Are you comfortable with occasional travel?",
    "What is your favourite programming language", "  Preferred   Work   Arrangement  ",
    "Do you hold a valid driving licence?", "<b>Why do you want to join Example Co?</b>",
    "How many years of Python experience do you have", "Earliest start date (DD/MM/YYYY)",
    "Expected salary (SGD, per month)", "Have you previously worked for Northwind?",
    "Why Acme Trading", "Cover letter / motivation", "Where would you like to work in 2027, hybrid or remote, "
    "or on site at one of our five offices in the region",
    "Résumé or CV", "Q1", "Please tell us about a project you are proud of",
]
assert len(LABELS) >= 15


def test_q127_parity_norm_label_and_is_generic_agree_with_the_apply_package():
    for label in LABELS:
        assert W.norm_label(label) == plan.norm_label(label), label
        n = plan.norm_label(label)
        assert W.is_generic(n) == plan.is_generic(n), label
        assert W.is_generic(label) == plan.is_generic(label), label


def test_q127_parity_slug_key_agrees_with_the_apply_package_alone_and_with_taken_keys():
    taken = ["notice_period_days", "preferred_work_arrangement", "q1", "question"]
    for label in LABELS:
        n = plan.norm_label(label)
        assert W.slug_key(n) == questions.slug_key(n), label
        assert W.slug_key(n, taken) == questions.slug_key(n, taken), (label, taken)
        assert W.slug_key(n, [W.slug_key(n)]) == questions.slug_key(n, [questions.slug_key(n)]), label


# ---- the sections of the Profile page --------------------------------------------------------------

def test_q127_every_form_item_is_in_exactly_one_section_and_there_are_ten():
    assert [s.id for s in applicant.SECTIONS] == [
        "identity", "contact", "work_rights", "availability_pay", "education", "experience",
        "skills_links", "equal_opportunity", "consents_declarations", "files"]
    assert [s.title for s in applicant.SECTIONS] == [
        "Identity", "Contact", "Work rights", "Availability and pay", "Education", "Experience",
        "Skills, languages and links", "Equal-opportunity questions", "Consents and declarations", "Files"]
    placed = [p for s in applicant.SECTIONS for p in s.paths]
    assert len(placed) == len(set(placed)), "an item sits in two sections"
    items = [i.path for g in applicant.FORM if g.id != "extra" for i in g.items]
    assert sorted(placed) == sorted(items), "every form item (but `extra`) is in a section"
    assert applicant.sections_json()[0] == {"id": "identity", "title": "Identity",
                                            "paths": list(applicant.SECTIONS[0].paths)}


def test_q127_path_filled_follows_missing_for_apply_and_a_consent_must_be_true():
    prof = {"identity": {"first_name": "Sam"}, "consents": {"privacy_consent": False, "certify_true": True},
            "education": [{"school": "Example University", "grade": "2.1"}, {"school": "Northwind College"}]}
    assert applicant.path_filled(prof, "identity.first_name") is True
    assert applicant.path_filled(prof, "identity.last_name") is False
    assert applicant.path_filled(prof, "consents.privacy_consent") is False, "a refused consent is not filled"
    assert applicant.path_filled(prof, "consents.certify_true") is True
    assert applicant.path_filled(prof, "education[0].grade") is True
    assert applicant.path_filled(prof, "education[1].grade") is False
    assert applicant.path_filled({}, "identity.first_name") is False and applicant.path_filled(None, "x.y") is False


def _entry(**over):
    e = {"title": "T", "description": "", "kind": "text", "sensitive": False,
         "labels": ["some question here"], "value": "v"}
    e.update(over)
    return e


def test_q127_empty_labels_are_valid_only_with_promoted_and_employer_and_promoted_are_metadata():
    assert applicant.extra_entry_errors("k1", _entry(labels=[])), "no labels, not promoted: invalid"
    assert applicant.extra_entry_errors("k1", _entry(labels=[], promoted=False))
    assert applicant.extra_entry_errors("k1", _entry(labels=[], promoted=True)) == []
    assert applicant.extra_entry_errors("k1", _entry(employer="Example Co")) == []
    assert applicant.extra_entry_errors("k1", _entry(promoted="yes")), "promoted must be a bool"
    assert {"promoted", "employer"} <= set(applicant.EXTRA_META_FIELDS)


def test_q127_drop_unchanged_extra_errors_keeps_every_other_error_and_changed_entries():
    bad = _entry(kind="number", value="x")
    old = {"extra": {"a": bad, "b": _entry()}}
    new_same = copy.deepcopy(old)
    new_same["identity"] = {"first_name": "Sam"}
    errs = applicant.validate(new_same)
    assert any(e.path.startswith("extra.a") for e in errs)
    kept = applicant.drop_unchanged_extra_errors(errs, new_same, old)
    assert not [e for e in kept if e.path.startswith("extra.")], "an unchanged invalid entry is tolerated"
    changed = copy.deepcopy(new_same)
    changed["extra"]["a"]["value"] = "still x"
    kept2 = applicant.drop_unchanged_extra_errors(applicant.validate(changed), changed, old)
    assert [e for e in kept2 if e.path.startswith("extra.a")], "a changed invalid entry still fails"
    other = {"extra": "not a mapping"}
    assert applicant.drop_unchanged_extra_errors(applicant.validate(other), other, old)


# ---- the saved-answers routes -----------------------------------------------------------------------

def _entries():
    return {
        "work_mode": {"title": "Work mode", "description": "", "kind": "text", "sensitive": False,
                      "labels": ["preferred work arrangement"], "value": "Hybrid", "employer": "Example Co"},
        "notice": {"title": "Notice", "description": "", "kind": "number", "sensitive": False,
                   "labels": ["how much notice do you need"], "value": 30},
        "broken": {"title": "Broken", "description": "", "kind": "number", "sensitive": False,
                   "labels": ["a broken one"], "value": "not a number"},
        "promo": {"title": "More about you", "description": "", "kind": "text", "sensitive": False,
                  "labels": [], "value": "x", "promoted": True},
    }


def test_q127_get_remembered_lists_the_saved_answers_with_scope_and_never_a_promoted_one():
    with _world([], extra=_entries()) as (client, cfg, ids):
        body = client.get("/api/apply/remembered").json()
        assert set(body) == {"items", "count", "etag", "unreadable"}
        assert body["unreadable"] is False and body["etag"] == client.get("/api/applicant").json()["etag"]
        by_key = {i["key"]: i for i in body["items"]}
        assert set(by_key) == {"work_mode", "notice", "broken"} and body["count"] == 3, "no promoted entry"
        assert set(by_key["work_mode"]) >= {"key", "title", "value_text", "scope_text", "employer", "kind",
                                            "sensitive", "needs_attention"}
        assert "Hybrid" in by_key["work_mode"]["value_text"] and "Example Co" in by_key["work_mode"]["scope_text"]
        assert by_key["notice"]["scope_text"] == "Every application"
        assert by_key["broken"]["needs_attention"] is True and by_key["notice"]["needs_attention"] is False
        for text in (by_key["work_mode"]["value_text"], str(body)):
            assert str(cfg.applicant_path) not in text


def test_q127_get_remembered_reads_an_unreadable_profile_as_empty_and_unreadable():
    with _world([], extra=_entries()) as (client, cfg, ids):
        Path(cfg.applicant_path).write_text("identity: [unclosed" + chr(10), encoding="utf-8")
        body = client.get("/api/apply/remembered").json()
        assert body["unreadable"] is True and body["items"] == [] and body["count"] == 0


def test_q127_forget_removes_one_entry_with_the_etag_and_touches_nothing_else():
    with _world([], extra=_entries()) as (client, cfg, ids):
        etag = client.get("/api/apply/remembered").json()["etag"]
        before = applicant.load(cfg.applicant_path)
        r = client.delete(f"/api/apply/remembered/work_mode?etag={etag}")
        assert r.status_code == 200 and r.json()["key"] == "work_mode" and r.json()["forgotten"] is True
        after = applicant.load(cfg.applicant_path)
        assert "work_mode" not in after["extra"]
        assert {k: v for k, v in before["extra"].items() if k != "work_mode"} == after["extra"]
        assert {k: v for k, v in before.items() if k != "extra"} == {k: v for k, v in after.items() if k != "extra"}
        assert r.json()["etag"] == client.get("/api/apply/remembered").json()["etag"]


def test_q127_forget_is_409_on_a_stale_etag_404_for_no_entry_and_never_for_a_promoted_one():
    with _world([], extra=_entries()) as (client, cfg, ids):
        before = _file(cfg)
        etag = client.get("/api/apply/remembered").json()["etag"]
        stale = client.delete("/api/apply/remembered/notice?etag=not-the-etag")
        assert stale.status_code == 409 and "changed" in stale.text
        assert client.delete(f"/api/apply/remembered/nosuchkey?etag={etag}").status_code == 404
        promo = client.delete(f"/api/apply/remembered/promo?etag={etag}")
        assert promo.status_code == 404, "a promoted topic is not a saved answer and cannot be forgotten here"
        assert _file(cfg) == before, "nothing written by any refusal"
        Path(cfg.applicant_path).write_text("identity: [unclosed" + chr(10), encoding="utf-8")
        gone = client.delete(f"/api/apply/remembered/notice?etag={etag}")
        assert gone.status_code == 409 and "unreadable" in gone.text


def test_q127_forgetting_an_entry_makes_the_resolver_fall_back_to_the_details():
    from questions_support import FIX, field, resolve_one
    entry = {"title": "Weekend", "description": "", "kind": "text", "sensitive": False,
             "labels": ["describe your ideal weekend routine"], "value": "Hiking"}
    with _world([], extra={"weekend": entry}) as (client, cfg, ids):
        rules = FIX / "questions.sample.yaml"
        f = field("q", "Describe your ideal weekend routine")
        assert resolve_one(f, applicant.load(cfg.applicant_path), rules, employer="Example Co").source == "memory:extra.weekend"
        etag = client.get("/api/apply/remembered").json()["etag"]
        assert client.delete(f"/api/apply/remembered/weekend?etag={etag}").status_code == 200
        a = resolve_one(f, applicant.load(cfg.applicant_path), rules, employer="Example Co")
        assert not a.source.startswith("memory:extra."), a.source


def test_q127_the_profile_file_is_valid_yaml_after_a_forget():
    with _world([], extra=_entries()) as (client, cfg, ids):
        etag = client.get("/api/apply/remembered").json()["etag"]
        client.delete(f"/api/apply/remembered/notice?etag={etag}")
        assert isinstance(yaml.safe_load(Path(cfg.applicant_path).read_text(encoding="utf-8")), dict)
