"""WP-Q0 oracles for `GET/PUT /api/applicant` (questions_design.md 9.1, 3.1): the shape, the lost-update
guard (etag), the 422 that names the path, an unreadable file, keys the form does not know. Built by
WP-W1 (lane Q, `web/routers/applicant.py`).

Skip-clean until `jobscraper.web.routers.applicant` and `applicant.etag` exist. Every test builds the real
app over a temp config, a temp database and a temp `applicant.yaml` (as tests/test_web_control.py does):
no network, never data/ or port 8765.

ASSUMED beyond the design: an absent file answers GET 200 with `profile == {}`, `etag == ""` and
`file.exists == False` (QD 3.1: `etag` is "" for an absent file); the CrossSiteWriteGuard needs no extra
header from the TestClient (existing PUT tests send none).
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    SAMPLE, profile, profile_with_extra, needs, report_waiting, waiting_mark,
)

import yaml  # noqa: E402

_MARK = waiting_mark()
BACKUP = "applicant.commented-backup.yaml"
GATE = ("jobscraper.web.routers.applicant", "jobscraper.applicant:etag", "jobscraper.applicant:form_json")


@contextmanager
def _world(text: str | None = None, prof: dict | None = None):
    """(client, applicant path, config). `text` writes the file verbatim; `prof` dumps a profile;
    neither leaves the file absent."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        if text is not None:
            path.write_text(text, encoding="utf-8", newline="\n")
        elif prof is not None:
            path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765}})
        with TestClient(create_app(cfg), base_url="http://localhost") as client:
            yield client, path, cfg


# ================================================================== harness (run now)

def test_the_harness_builds_the_real_app_over_a_temp_applicant_file():
    with _world(prof=profile()) as (c, path, cfg):
        assert cfg.applicant_path == path and path.is_file()
        assert c.get("/api/settings").status_code == 200, "the real app answers over the temp config"
        assert str(path.parent).lower() != str(Path("data").resolve()).lower(), "never the live data folder"


# ================================================================== GET

@needs(*GATE)
def test_get_returns_the_profile_the_form_the_etag_and_the_file_state():
    import jobscraper.applicant as A
    with _world(prof=profile_with_extra()) as (c, path, _cfg):
        r = c.get("/api/applicant")
        assert r.status_code == 200, r.text
        body = r.json()
        on_disk_etag = A.etag(path)  # inside the block: the temp dir is gone after it
    assert {"profile", "etag", "errors", "missing", "completeness", "from_resume", "sensitive",
            "form", "file"} <= set(body), sorted(body)
    assert body["profile"]["identity"]["legal_first_name"] == "Alex"
    assert body["etag"] == on_disk_etag and len(body["etag"]) == 16
    assert body["errors"] == []
    assert isinstance(body["missing"], list) and "contact.email" not in body["missing"]
    assert set(body["completeness"]) >= {"filled", "needed"}
    assert body["completeness"]["needed"] > 0
    assert body["form"] == A.form_json(), "the UI renders exactly the server's FORM"
    assert set(body["file"]) >= {"exists", "has_comments", "error"}
    assert body["file"]["exists"] is True and not body["file"]["error"]
    sens = set(body["sensitive"])
    assert "identity.date_of_birth" in sens and "contact.email" in sens
    assert "extra.mother_tongue" in sens, "a sensitive `extra` entry is listed as extra.<key>"
    assert "extra.favourite_language" not in sens
    assert "contact.city" not in sens


@needs(*GATE)
def test_get_flags_a_file_with_comments_and_an_absent_file():
    with _world(text=SAMPLE.read_text(encoding="utf-8")) as (c, _p, _cfg):
        assert c.get("/api/applicant").json()["file"]["has_comments"] is True
    with _world(prof=profile()) as (c, _p, _cfg):
        assert c.get("/api/applicant").json()["file"]["has_comments"] is False
    with _world() as (c, path, _cfg):
        assert not path.exists()
        r = c.get("/api/applicant")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["profile"] == {} and b["etag"] == "" and b["file"]["exists"] is False
        assert "contact.email" in b["missing"], "an empty profile is missing everything required"


@needs(*GATE)
def test_get_on_an_unreadable_file_is_200_with_the_error_and_an_empty_profile():
    with _world(text="identity: [unclosed\n  - : :\n") as (c, path, _cfg):
        before = path.read_bytes()
        r = c.get("/api/applicant")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["profile"] == {}
        assert b["file"]["error"], "the error text is shown to the owner"
        assert path.read_bytes() == before, "reading never changes the file"


# ================================================================== PUT

@needs(*GATE)
def test_put_saves_a_valid_profile_and_returns_the_new_etag():
    import jobscraper.applicant as A
    with _world(prof=profile()) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        edited = got["profile"]
        edited["identity"]["preferred_name"] = "Lex"
        r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["profile"]["identity"]["preferred_name"] == "Lex"
        assert body["etag"] == A.etag(path) and body["etag"] != got["etag"]
        assert set(body) >= {"profile", "etag", "errors", "missing", "completeness", "form", "file"}
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["identity"]["preferred_name"] == "Lex"


@needs(*GATE)
def test_put_with_a_bad_postal_code_is_422_names_the_path_and_changes_nothing():
    with _world(prof=profile()) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        before = path.read_bytes()
        bad = got["profile"]
        bad["contact"]["postal_code"] = "12345"          # Singapore postal codes are 6 digits
        r = c.put("/api/applicant", json={"profile": bad, "etag": got["etag"]})
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["detail"] == "invalid"
        assert "contact.postal_code" in {e["path"] for e in body["errors"]}
        assert path.read_bytes() == before, "nothing is saved on 422"
        assert not (path.parent / BACKUP).exists()


@needs(*GATE)
def test_put_with_a_stale_etag_is_409_changed_and_changes_nothing():
    with _world(prof=profile()) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        # someone else (another tab, a hand edit) changes the file after the form loaded
        edited_elsewhere = profile()
        edited_elsewhere["identity"]["pronouns"] = "they/them"
        path.write_text(yaml.safe_dump(edited_elsewhere, sort_keys=False), encoding="utf-8")
        elsewhere = path.read_bytes()
        mine = got["profile"]
        mine["identity"]["preferred_name"] = "Lex"
        r = c.put("/api/applicant", json={"profile": mine, "etag": got["etag"]})
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "changed"
        assert path.read_bytes() == elsewhere, "the other edit survives"


@needs(*GATE)
def test_put_over_an_unreadable_file_is_409_unreadable_and_never_overwrites_it():
    broken = "identity: [unclosed\n  - : :\n"
    with _world(text=broken) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        r = c.put("/api/applicant", json={"profile": profile(), "etag": got["etag"]})
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "unreadable"
        assert path.read_text(encoding="utf-8") == broken, "a broken file is never overwritten"


@needs(*GATE)
def test_unknown_keys_round_trip_untouched():
    p = profile_with_extra()
    p["future_section"] = {"flag": True, "note": "kept"}
    p["contact"]["fax_number"] = "n/a"
    with _world(prof=p) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        assert got["profile"]["future_section"] == {"flag": True, "note": "kept"}
        assert got["profile"]["contact"]["fax_number"] == "n/a"
        edited = got["profile"]
        edited["identity"]["preferred_name"] = "Lex"
        r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["future_section"] == {"flag": True, "note": "kept"}
    assert saved["contact"]["fax_number"] == "n/a"
    assert saved["extra"]["visa_status"]["picks"] == ["singapore citizen"], "`extra` survives a form save"


@needs(*GATE)
def test_the_first_save_of_a_commented_file_keeps_the_commented_copy_once():
    original = SAMPLE.read_text(encoding="utf-8")
    with _world(text=original) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        edited = got["profile"]
        edited["identity"]["pronouns"] = "she/her"
        assert c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]}).status_code == 200
        backup = path.parent / BACKUP
        assert backup.read_text(encoding="utf-8") == original
        got = c.get("/api/applicant").json()
        assert got["file"]["has_comments"] is False
        edited = got["profile"]
        edited["identity"]["pronouns"] = "he/him"
        assert c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]}).status_code == 200
        assert backup.read_text(encoding="utf-8") == original, "the copy is made once"


report_waiting("test_web_applicant", _MARK)
