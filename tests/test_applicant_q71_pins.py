"""Q-71 lane G (details form backend) pins: country validation and options, the control / show_when /
autocomplete hints in the form JSON, consents counted only when True, documents_status naming files
only, and POST /api/applicant/check writing nothing. Spec: the lane G entry in
comms/outbox/software-engineer.md and docs/reviews/Q-71-details-form-audit.md.

Synthetic data only (the sample profile), temp dirs, no network, never data/ or port 8765.
"""
from __future__ import annotations

import copy
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from apply_support import profile as sample  # noqa: E402
from jobscraper import applicant as A  # noqa: E402

NOT_A_COUNTRY = "is not a country code. Pick a country from the list"


def _errors(p: dict) -> dict[str, str]:
    return {e.path: e.message for e in A.validate(p)}


def _items() -> dict[str, dict]:
    return {i["path"]: i for g in A.form_json() for i in g["items"]}


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------- country validation

def test_a_country_must_be_an_iso_code_from_the_list():
    assert len(A.COUNTRY_NAMES) == 249
    assert _errors({"contact": {"country": "XX"}}) == {"contact.country": NOT_A_COUNTRY}
    assert "contact.country" not in _errors({"contact": {"country": "SI"}})      # Slovenia is a real code
    assert "contact.country" not in _errors({"contact": {"country": "SG"}})


def test_a_typed_name_or_a_lowercase_code_is_not_a_country_code():
    for bad in ("Singapore", "sg", "Sg", "SGP", "S"):
        assert _errors({"contact": {"country": bad}}).get("contact.country") == NOT_A_COUNTRY, bad
    assert _errors({"singapore_status": {"nationality": "Singaporean"}}) == {
        "singapore_status.nationality": NOT_A_COUNTRY}
    assert "singapore_status.nationality" not in _errors({"singapore_status": {"nationality": "SG"}})


def test_a_work_rights_key_must_be_a_known_code_and_the_error_sits_on_the_map():
    for field in ("authorised_to_work", "requires_sponsorship"):
        path = f"singapore_status.{field}"
        assert _errors({"singapore_status": {field: {"ZZ": True}}}) == {path: NOT_A_COUNTRY}
        assert _errors({"singapore_status": {field: {"SG": True, "default": False}}}) == {}
        # A malformed key keeps its older message (test_applicant_form pins the same wording).
        assert _errors({"singapore_status": {field: {"U": True}}}) == {
            path: "keys must be 2-letter ISO country codes or default"}


def test_the_sample_profile_still_validates_clean():
    assert A.validate(sample()) == []


# ---------------------------------------------------------------- form JSON hints

def test_country_items_carry_the_whole_list_with_singapore_first():
    items = _items()
    for path in ("contact.country", "singapore_status.nationality"):
        opts = items[path]["options"]
        assert len(opts) == 249 and opts[0] == {"value": "SG", "label": "Singapore (SG)"}, path
        assert {o["value"] for o in opts} == set(A.COUNTRY_NAMES)
        assert len({o["value"] for o in opts}) == 249
        assert all(o["label"].endswith(f"({o['value']})") for o in opts)
    # The work-rights maps get the list as country_options; their own options stay empty.
    for path in ("singapore_status.authorised_to_work", "singapore_status.requires_sponsorship"):
        it = items[path]
        assert it["options"] == [] and len(it["country_options"]) == 249
        assert it["country_options"][0]["value"] == "SG"
        assert "default" not in {o["value"] for o in it["country_options"]}


def test_yes_no_control_is_on_declarations_and_relocation_but_not_on_consents():
    items = _items()
    for path, it in items.items():
        if it["kind"] != "bool":
            continue
        if path.startswith("declarations.") or path == "availability.willing_to_relocate":
            assert it.get("control") == "yes_no", path
        else:
            assert "control" not in it, path
    assert any(p.startswith("consents.") and it["kind"] == "bool" for p, it in items.items())
    assert "control" not in items["consents.privacy_consent"]


def test_show_when_ties_the_follow_up_fields_to_their_trigger_with_json_values():
    items = _items()
    assert items["singapore_status.race_other"]["show_when"] == {
        "path": "singapore_status.race", "values": ["other"]}
    assert items["declarations.holdings"]["show_when"] == {
        "path": "declarations.shareholding_in_company", "values": [True]}
    assert items["declarations.relatives_employers"]["show_when"] == {
        "path": "declarations.relatives_at_company", "values": [True]}
    assert items["singapore_status.ord_date"]["show_when"] == {
        "path": "singapore_status.ns_status", "values": ["completed", "serving"]}
    for it in items.values():                      # every trigger is a real item, so the form can read it
        if "show_when" in it:
            assert it["show_when"]["path"] in items, it["path"]
    assert sum(1 for it in items.values() if "show_when" in it) == 4


def test_autocomplete_tokens_are_set_for_the_contact_fields_and_off_for_the_backup_email():
    items = _items()
    want = {
        "identity.legal_first_name": "given-name", "identity.legal_last_name": "family-name",
        "identity.preferred_name": "nickname", "identity.date_of_birth": "bday",
        "contact.email": "email", "contact.backup_email": "off",
        "contact.phone_country_code": "tel-country-code", "contact.phone_number": "tel-national",
        "contact.address_line1": "address-line1", "contact.address_line2": "address-line2",
        "contact.postal_code": "postal-code", "contact.city": "address-level2",
        "contact.country": "country", "links.linkedin": "url", "links.github": "url",
        "links.portfolio": "url",
    }
    for path, token in want.items():
        assert items[path].get("autocomplete") == token, path
    assert "autocomplete" not in items["singapore_status.race"]            # absent = the client's default


# ---------------------------------------------------------------- consents count only when True

def test_consents_are_filled_only_when_true():
    tmp = _tmp()
    (tmp / "resume.pdf").write_bytes(b"%PDF-1.4")
    base = copy.deepcopy(sample())
    assert A.missing_for_apply(base, tmp) == []
    full = A.completeness(base)
    assert full[0] == full[1]
    for key in ("privacy_consent", "certify_true"):
        for bad in (False, None, "yes", 1):
            p = copy.deepcopy(base)
            p["consents"][key] = bad
            assert A.missing_for_apply(p, tmp) == [f"consents.{key}"], (key, bad)
            assert A.completeness(p)[0] == full[0] - 1, (key, bad)
        gone = copy.deepcopy(base)
        del gone["consents"][key]
        assert A.missing_for_apply(gone, tmp) == [f"consents.{key}"]
    # The data-retention and talent-pool consents are the owner's choice either way.
    other = copy.deepcopy(base)
    other["consents"]["data_retention_consent"] = False
    other["consents"]["talent_pool_opt_in"] = False
    assert A.missing_for_apply(other, tmp) == []


# ---------------------------------------------------------------- documents_status

def test_documents_status_names_files_only():
    tmp = _tmp()
    data = tmp / "owner-private-folder"
    data.mkdir()
    (data / "resume.pdf").write_bytes(b"%PDF-1.4 resume")
    (data / "transcript.pdf").write_bytes(b"%PDF-1.4 transcript!")
    p = copy.deepcopy(sample())
    p["documents"] = {"transcript": "transcript.pdf"}
    got = A.documents_status(p, data)
    assert got["resume"]["name"] == "resume.pdf" and got["resume"]["size"] == len(b"%PDF-1.4 resume")
    assert got["transcript"]["name"] == "transcript.pdf" and got["transcript"]["size"] == 20
    for doc in got.values():
        assert set(doc) == {"name", "size", "modified"}
        assert doc["modified"].endswith("+00:00") and "T" in doc["modified"]
    assert "owner-private-folder" not in repr(got) and str(tmp) not in repr(got)


def test_documents_status_is_none_when_there_is_no_file():
    tmp = _tmp()
    p = copy.deepcopy(sample())
    p["documents"] = {"transcript": "missing.pdf", "resume": ""}
    assert A.documents_status(p, tmp) == {"resume": None, "transcript": None}
    assert A.documents_status({}, tmp) == {"resume": None, "transcript": None}


# ---------------------------------------------------------------- the web routes

@contextmanager
def _world(prof: dict | None = None):
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        if prof is not None:
            path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765}})
        with TestClient(create_app(cfg), base_url="http://localhost") as client:
            yield client, path, data


def _listing(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("jobscraper.db"))


def test_check_returns_errors_and_leaves_the_file_alone():
    prof = copy.deepcopy(sample())
    with _world(prof) as (client, path, data):
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        files = _listing(data)
        bad = copy.deepcopy(prof)
        bad["contact"]["country"] = "XX"
        bad["contact"]["email"] = "not an email"
        r = client.post("/api/applicant/check", json={"profile": bad})
        assert r.status_code == 200, r.text
        errs = {e["path"]: e["message"] for e in r.json()["errors"]}
        assert errs["contact.country"] == NOT_A_COUNTRY and "contact.email" in errs
        assert all(set(e) == {"path", "message"} for e in r.json()["errors"])
        ok = client.post("/api/applicant/check", json={"profile": prof})
        assert ok.status_code == 200 and ok.json() == {"errors": []}
        assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
        assert _listing(data) == files, "no backup, copy or temp file appeared"


def test_check_works_with_no_applicant_file_and_creates_none():
    with _world() as (client, path, data):
        assert not path.exists()
        r = client.post("/api/applicant/check", json={"profile": {"contact": {"country": "XX"}}})
        assert r.status_code == 200
        assert [e["path"] for e in r.json()["errors"]] == ["contact.country"]
        assert not path.exists() and _listing(data) == []


def test_check_refuses_a_body_that_is_not_a_profile_object():
    with _world(copy.deepcopy(sample())) as (client, path, _data):
        before = path.read_bytes()
        assert client.post("/api/applicant/check", json={"profile": "text"}).status_code == 422
        assert client.post("/api/applicant/check", json={}).status_code == 422
        assert path.read_bytes() == before


def test_get_applicant_carries_documents_status_with_names_only():
    prof = copy.deepcopy(sample())
    with _world(prof) as (client, _path, data):
        none = client.get("/api/applicant").json()
        assert none["documents_status"] == {"resume": None, "transcript": None}
        (data / "resume.pdf").write_bytes(b"%PDF-1.4 resume")
        got = client.get("/api/applicant").json()["documents_status"]
        assert got["resume"]["name"] == "resume.pdf" and got["resume"]["size"] == 15
        assert got["transcript"] is None
        assert str(data) not in repr(got) and data.parent.name not in repr(got)