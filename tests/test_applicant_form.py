"""WP-Q0 oracles for the Profile form schema, the save behaviour, `extra` validation and the D-75
work-rights validation (questions_design.md 3.1, 3.2, 6.1, 8.1). Built by WP-W1 and WP-P9 (lane Q).

Skip-clean (`needs`): a test is not defined until the thing it checks exists.
  applicant.py:  FORM, form_json(), etag(path), save(path, profile, *, keep_commented_copy=True)  [QD 3.1, 3.2]
                 work_rights(profile, country) -> (authorised, needs_sponsorship)                   [QD 8.1]
                 work_rights_text(profile) -> str                                                  [QD 8.1]
ASSUMED shapes (change the helper named, nothing else):
  form_json() -> list of group dicts {id, title, note, items:[{path, label, kind, options, help, sub,
                 required, recommended, sensitive}]}                                  -> `_form_items`
  An `extra` validation error's path is `extra.<key>.<field>` (QD 6.1); for a malformed key the
  path starts with `extra`.
No network; every file lives in a temp folder.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    EXTRA_SAMPLE, ROOT, SAMPLE, extra_block, needs, profile, profile_with_extra, report_waiting,
    waiting_mark,
)

_MARK = waiting_mark()
TEMPLATE = ROOT / "config" / "applicant.example.yaml"
BACKUP_NAME = "applicant.commented-backup.yaml"


def _A():
    return importlib.import_module("jobscraper.applicant")


def _form_items(form: list[dict]) -> list[dict]:
    """Every item of every group, entries' sub-items not included."""
    return [it for g in form for it in g["items"]]


def _leaf_paths(node, prefix: str = "") -> list[str]:
    """Dotted leaf paths of a mapping; a list contributes `path[0].key` for its first entry's keys."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += _leaf_paths(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        if node and isinstance(node[0], dict):
            out += _leaf_paths(node[0], f"{prefix}[0]")
        else:
            out.append(prefix)
    else:
        out.append(prefix)
    return out


def _bare(path: str) -> str:
    import re
    return re.sub(r"\[\d+\]", "", path)


# kinds whose item covers every path beneath it (QD 3.2: entries, maps, salary, lists)
_COVERING = {"entries", "country_bool_map", "salary", "list_text", "list_url", "fixed"}


def _covered(path: str, items: list[dict]) -> bool:
    bare = _bare(path)
    for it in items:
        ip = it["path"]
        if bare == ip:
            return True
        if it["kind"] in _COVERING and (bare.startswith(ip + ".")):
            return True
    return False


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _commented_text() -> str:
    """The sample profile as hand-written YAML: it has `#` comment lines."""
    text = SAMPLE.read_text(encoding="utf-8")
    assert any(ln.lstrip().startswith("#") for ln in text.splitlines())
    return text


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


# ================================================================== fixtures (run now)

def test_the_extra_sample_covers_every_kind_and_is_well_formed_synthetic_data():
    import re
    from jobscraper.apply.contracts import EXTRA_KEY_PATTERN, QuestionKind
    from jobscraper.apply.plan import norm_label
    ex = extra_block()
    assert {e["kind"] for e in ex.values()} == {k.value for k in QuestionKind}, "one entry per kind"
    assert any(e["sensitive"] for e in ex.values()) and not all(e["sensitive"] for e in ex.values())
    with_override = [k for k, e in ex.items() if e.get("by_employer")]
    assert with_override == ["visa_status"], "exactly one entry has a by_employer override"
    for key, e in ex.items():
        assert re.fullmatch(EXTRA_KEY_PATTERN, key), key
        assert e["labels"] and all(norm_label(x) == x for x in e["labels"]), f"{key}: labels are normalised"
        if e["kind"] in ("choice", "multi"):
            assert e["picks"] and set(e["picks"]) <= set(e["seen"]), key
            for ov in (e.get("by_employer") or {}).values():
                assert set(ov["picks"]) <= set(ov["seen"]), key
        else:
            assert e["value"] is not None, key
    text = EXTRA_SAMPLE.read_text(encoding="utf-8")
    assert "@" not in text and "http" not in text, "no email or link in a fixture"
    assert yaml.safe_load(text).keys() == {"extra"}, "the fixture is the extra block only"


def test_the_profile_with_extra_still_validates_today():
    """Unknown top-level keys round-trip untouched (QD 3.1), so adding `extra` never breaks validate."""
    assert _A().validate(profile_with_extra()) == []


# ================================================================== FORM and form_json (WP-W1)

@needs("jobscraper.applicant:FORM", "jobscraper.applicant:form_json")
def test_every_leaf_of_the_template_is_a_form_path_or_inside_an_entries_or_map_item():
    A = _A()
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    items = _form_items(A.form_json())
    leaves = [p for p in _leaf_paths(template) if p != "version"]
    assert leaves, "the template has leaves"
    missing = [p for p in leaves if not _covered(p, items)]
    assert not missing, f"the Application details form has no field for: {missing}"


@needs("jobscraper.applicant:FORM", "jobscraper.applicant:form_json")
def test_form_starts_with_the_fourteen_profile_groups_in_design_order_and_ids_are_unique():
    A = _A()
    form = A.form_json()
    ids = [g["id"] for g in form]
    assert len(ids) == len(set(ids)), "group ids are unique"
    # QD 3.2 groups 1-14 are the profile's own; 15 (`extra`) and 16 (other keys) are rendered by the UI
    want = ["identity", "contact", "singapore_status", "us_self_id", "availability", "pay", "education",
            "experience", "skills_languages", "links", "documents", "sourcing", "consents", "declarations"]
    assert ids[:len(want)] == want, ids
    paths = [it["path"] for it in _form_items(form)]
    assert len(paths) == len(set(paths)), "no path appears twice"
    for must in ("contact.email", "contact.backup_email", "singapore_status.authorised_to_work",
                 "singapore_status.requires_sponsorship", "pay.expected_salary", "education"):
        assert must in paths, must


@needs("jobscraper.applicant:FORM", "jobscraper.applicant:form_json")
def test_form_json_flags_come_from_the_path_tables_not_by_hand():
    A = _A()
    items = _form_items(A.form_json())
    required, recommended = set(A.REQUIRED_PATHS), set(A.RECOMMENDED_PATHS)

    def related(item_path: str, table: set[str]) -> bool:
        """The item is a table path, or a map/entries item holding one (pay.expected_salary)."""
        return any(p == item_path or p.startswith(item_path + ".") for p in table)

    for it in items:
        p = it["path"]
        if p in required:
            assert it["required"], (p, "is in REQUIRED_PATHS, so it is flagged required")
        if not related(p, required):
            assert not it["required"], (p, "is flagged required but no REQUIRED_PATHS entry is under it")
        if p in recommended:
            assert it["recommended"], (p, "is in RECOMMENDED_PATHS, so it is flagged recommended")
        if not related(p, recommended):
            assert not it["recommended"], (p, "is flagged recommended but no RECOMMENDED_PATHS entry is under it")
        assert bool(it["sensitive"]) == A.is_sensitive(p), (p, "sensitive comes from is_sensitive")
    by_path = {it["path"]: it for it in items}
    assert by_path["identity.date_of_birth"]["sensitive"] is True
    assert by_path["contact.city"]["sensitive"] is False, "city and country are not S (AD 5.3)"


# ================================================================== save (WP-W1, QD 3.1)

@needs("jobscraper.applicant:etag", "jobscraper.applicant:FORM")
def test_save_keeps_key_order_and_appends_new_keys_at_the_end():
    A = _A()
    d = _tmp()
    path = _write(d / "applicant.yaml", _commented_text())
    p = A.load(path)
    top_before = list(p)
    inner_before = list(p["identity"])
    p["identity"]["preferred_name"] = "Lex"
    p["extra"] = extra_block()
    A.save(path, p)
    again = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert list(again) == top_before + ["extra"], "existing keys keep their order; extra is appended"
    assert list(again["identity"]) == inner_before
    assert again["identity"]["preferred_name"] == "Lex"


@needs("jobscraper.applicant:etag", "jobscraper.applicant:FORM")
def test_first_save_of_a_commented_file_keeps_one_copy_of_it():
    A = _A()
    d = _tmp()
    original = _commented_text()
    path = _write(d / "applicant.yaml", original)
    backup = d / BACKUP_NAME
    assert not backup.exists()
    p = A.load(path)
    p["identity"]["pronouns"] = "they/them"
    A.save(path, p)
    assert backup.read_text(encoding="utf-8") == original, "the copy holds the file as it was, comments included"
    assert not any(ln.lstrip().startswith("#") for ln in path.read_text(encoding="utf-8").splitlines()), \
        "the saved file has no comments (AD 5.1 is unchanged)"
    # The copy is made only if it does not exist yet: change it, comment the file again, save again.
    backup.write_text("# SENTINEL\n", encoding="utf-8")
    _write(path, "# a new hand comment\n" + path.read_text(encoding="utf-8"))
    p = A.load(path)
    p["identity"]["pronouns"] = "she/her"
    A.save(path, p)
    assert backup.read_text(encoding="utf-8") == "# SENTINEL\n", "an existing copy is never overwritten"


@needs("jobscraper.applicant:etag", "jobscraper.applicant:FORM")
def test_no_copy_on_the_second_save_when_there_were_no_comments_or_when_asked_not_to():
    A = _A()
    d = _tmp()
    path = _write(d / "applicant.yaml", _commented_text())
    p = A.load(path)
    A.save(path, p)                      # first save: copy made (covered above)
    (d / BACKUP_NAME).unlink()
    p["identity"]["pronouns"] = "x"
    A.save(path, p)                      # the file now has no comments
    assert not (d / BACKUP_NAME).exists(), "nothing to preserve, no copy"

    d2 = _tmp()
    plain = _write(d2 / "applicant.yaml", yaml.safe_dump(profile(), sort_keys=False))
    A.save(plain, A.load(plain))
    assert not (d2 / BACKUP_NAME).exists(), "a file that never had comments gets no copy"

    d3 = _tmp()
    commented = _write(d3 / "applicant.yaml", _commented_text())
    A.save(commented, A.load(commented), keep_commented_copy=False)
    assert not (d3 / BACKUP_NAME).exists(), "keep_commented_copy=False writes no copy"


@needs("jobscraper.applicant:etag")
def test_etag_is_the_first_16_hex_of_the_file_hash_and_changes_with_the_bytes():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    assert A.etag(path) == "", "an absent file has the empty etag"
    _write(path, "version: 1\n")
    e1 = A.etag(path)
    assert e1 == hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    assert A.etag(path) == e1, "stable for the same bytes"
    _write(path, "version: 1\n# changed\n")
    assert A.etag(path) != e1


# ================================================================== `extra` validation (QD 6.1)

def _errs(p: dict) -> list:
    return _A().validate(p)


def _paths(errs) -> set[str]:
    return {e.path for e in errs}


@needs("jobscraper.applicant:FORM")
def test_the_sample_extra_block_validates_clean():
    p = profile_with_extra()
    assert _errs(p) == [], _errs(p)
    assert set(p["extra"]) == {"visa_status", "has_driving_licence", "work_arrangements", "favourite_language",
                               "available_from", "years_with_python", "mother_tongue"}


@needs("jobscraper.applicant:FORM")
def test_extra_validation_names_each_bad_field():
    def bad(mutate, want_prefix):
        p = profile_with_extra()
        mutate(p["extra"])
        errs = _errs(p)
        assert any(e.path.startswith(want_prefix) for e in errs), (want_prefix, errs)
        return errs

    def bad_key(ex):
        ex["Visa Status!"] = ex.pop("visa_status")
    bad(bad_key, "extra")
    assert any("Visa Status!" in e.path or "Visa Status!" in e.message for e in _errs(_with(bad_key))),         "the error names the key"

    bad(lambda ex: ex["visa_status"].update(picks=["not offered"]), "extra.visa_status.picks")      # picks not within seen
    # a choice needs a base pick, unless it has employer-scoped answers (D-76 item 3, tested below)
    bad(lambda ex: (ex["visa_status"].pop("by_employer", None), ex["visa_status"].update(picks=[])),
        "extra.visa_status.picks")
    bad(lambda ex: ex["has_driving_licence"].update(value="yes"), "extra.has_driving_licence.value")
    bad(lambda ex: ex["years_with_python"].update(value="three"), "extra.years_with_python.value")
    bad(lambda ex: ex["available_from"].update(value="02/02/2026"), "extra.available_from.value")
    bad(lambda ex: ex["favourite_language"].update(value="x" * 2001), "extra.favourite_language.value")
    bad(lambda ex: ex["favourite_language"].update(labels=[]), "extra.favourite_language.labels")
    bad(lambda ex: ex["favourite_language"].update(labels="what is it"), "extra.favourite_language.labels")
    bad(lambda ex: ex["favourite_language"].update(kind="essay"), "extra.favourite_language.kind")
    bad(lambda ex: ex["favourite_language"].update(sensitive="no"), "extra.favourite_language.sensitive")
    bad(lambda ex: ex["visa_status"]["by_employer"].update({"": {"value": None, "picks": ["citizen"],
                                                                   "seen": ["citizen"]}}),
        "extra.visa_status.by_employer")
    bad(lambda ex: ex["visa_status"]["by_employer"].update(
        {"shopee": {"value": None, "picks": ["citizen", "gone"], "seen": ["citizen"]}}),
        "extra.visa_status.by_employer")
    bad(lambda ex: ex["visa_status"].update(by_employer=["shopee"]), "extra.visa_status.by_employer")


@needs("jobscraper.applicant:FORM")
def test_a_choice_with_employer_answers_may_have_empty_base_picks_d76():
    """D-76 item 3: a choice question's first answer may be employer-scoped only."""
    p = profile_with_extra()
    assert p["extra"]["visa_status"].get("by_employer"), "the sample entry has employer-scoped answers"
    p["extra"]["visa_status"]["picks"] = []
    assert not [e for e in _errs(p) if e.path.startswith("extra.visa_status")], _errs(p)


def _with(mutate) -> dict:
    p = profile_with_extra()
    mutate(p["extra"])
    return p


@needs("jobscraper.applicant:FORM")
def test_extra_error_messages_never_repeat_the_answer():
    p = profile_with_extra()
    p["extra"]["favourite_language"]["value"] = 12345          # wrong type for text
    p["extra"]["mother_tongue"]["value"] = ["Mandarin"]        # wrong type for text, sensitive
    for e in _errs(p):
        assert "12345" not in e.message and "Mandarin" not in e.message, e


# ================================================================== D-75 validation (WP-P9, QD 8.1)

@needs("jobscraper.applicant:work_rights")
def test_default_key_is_accepted_in_both_work_rights_maps():
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"SG": True, "default": True}
    p["singapore_status"]["requires_sponsorship"] = {"SG": False, "default": False}
    assert _errs(p) == []
    p["singapore_status"]["authorised_to_work"] = {"default": None}
    assert _errs(p) == [], "a null value is allowed (QD 8.1: bool or null)"


@needs("jobscraper.applicant:work_rights")
def test_a_lowercase_country_key_and_a_non_bool_default_are_errors():
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"sg": True}
    errs = _errs(p)
    assert any(e.path.startswith("singapore_status.authorised_to_work") for e in errs), errs
    assert any("default" in e.message and "2-letter" in e.message for e in errs), \
        "the message becomes 'keys must be 2-letter ISO country codes or default'"
    p = profile()
    p["singapore_status"]["requires_sponsorship"] = {"SG": False, "default": "yes"}
    errs = _errs(p)
    assert any(e.path.startswith("singapore_status.requires_sponsorship") for e in errs), errs


@needs("jobscraper.applicant:work_rights")
def test_the_template_with_default_keys_validates_clean():
    """QD 13 test_apply_contracts addition (kept here): the sample with `default` keys is valid."""
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"SG": True, "default": True}
    p["singapore_status"]["requires_sponsorship"] = {"SG": False, "default": False}
    assert _errs(p) == []
    # and without them (the sample's own maps): absent = the standing answer
    assert _errs(profile()) == []


@needs("jobscraper.applicant:work_rights")
def test_work_rights_picks_country_then_default_then_the_standing_answer():
    A = _A()
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"SG": True, "US": False, "default": True}
    p["singapore_status"]["requires_sponsorship"] = {"SG": False, "US": True, "default": False}
    assert A.work_rights(p, "SG") == (True, False)
    assert A.work_rights(p, "US") == (False, True)
    assert A.work_rights(p, "CA") == (True, False), "the default covers every country not listed"
    p["singapore_status"]["authorised_to_work"] = {"SG": True}
    p["singapore_status"]["requires_sponsorship"] = {}
    assert A.work_rights(p, "US") == (True, False), "no default key: the standing answer (authorised, no sponsorship)"
    p["singapore_status"].pop("authorised_to_work")
    p["singapore_status"].pop("requires_sponsorship")
    assert A.work_rights(p, "GB") == (True, False), "an absent map always has an answer"
    assert A.work_rights({}, "SG") == (True, False)


@needs("jobscraper.applicant:work_rights_text")
def test_work_rights_text_is_exact_for_the_defaults_and_names_each_difference():
    A = _A()
    p = profile()
    p["singapore_status"]["authorised_to_work"] = {"SG": True, "default": True}
    p["singapore_status"]["requires_sponsorship"] = {"SG": False, "default": False}
    assert A.work_rights_text(p) == "The applicant has the right to work and needs no visa sponsorship."
    assert A.work_rights_text({}) == "The applicant has the right to work and needs no visa sponsorship."
    p["singapore_status"]["authorised_to_work"] = {"SG": True, "US": False, "default": True}
    p["singapore_status"]["requires_sponsorship"] = {"SG": False, "US": True, "default": False}
    text = A.work_rights_text(p)
    assert text.startswith("The applicant has the right to work and needs no visa sponsorship.")
    assert "For US: does not have the right to work." in text
    assert "For US: needs visa sponsorship." in text
    p["singapore_status"]["authorised_to_work"] = {"default": False}
    p["singapore_status"]["requires_sponsorship"] = {"default": True}
    assert A.work_rights_text(p).startswith("The applicant does not have the right to work and needs visa sponsorship.")


report_waiting("test_applicant_form", _MARK)
