"""Control from the web app (M11): settings, the profile, background jobs, and
the resume upload - the API contract in PRD section 10, M11.

Every test builds the real app over a temp config, a temp database and a temp
data directory. Background jobs run a stub command (a few lines of Python)
instead of the CLI, so nothing here touches the network or a model.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from jobscraper.config import Config  # noqa: E402
from jobscraper.store import Store  # noqa: E402
from jobscraper.web.api import create_app  # noqa: E402

ENABLED = 30
INTERESTS = ["software engineering", "trade operations"]


def _config(tmp: Path, batch_size: int = 10) -> Config:
    data = tmp / "data"
    return Config({
        "paths": {"db": str(data / "jobscraper.db"),
                  "shortlist": str(data / "shortlist.json"),
                  "profile": str(data / "profile.derived.yaml"),
                  "resume_dir": str(data)},
        "run": {"batch_size": batch_size, "cycle_days": 14},
        "judge": {"interests": INTERESTS},
        "web": {"host": "127.0.0.1", "port": 8765},
    })


@contextmanager
def _world(enabled: int = ENABLED, disabled: int = 2, **app_kw):
    """(client, cfg, data_dir) over `enabled` enabled companies in a temp DB."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg = _config(Path(tmp))
        st = Store(cfg.db_path)
        for i in range(enabled + disabled):
            st.insert_company(f"co{i}", f"Company {i}", f"https://co{i}.example",
                              enabled=i < enabled)
        st.close()
        app = create_app(cfg, **app_kw)
        with TestClient(app, base_url="http://localhost") as client:
            yield client, cfg, cfg.db_path.parent


def _stored(cfg: Config, key: str):
    st = Store(cfg.db_path)
    try:
        return st.get_setting(key)
    finally:
        st.close()


# ---------------------------------------------------------------- M11-T2

def test_web_settings_default_to_config_with_the_cadence():
    with _world() as (c, cfg, _):
        r = c.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {"batch_size": 10, "batch_size_default": 10,
                        "enabled_companies": ENABLED, "cycle_days": 14,
                        "runs_per_day_needed": 0.2}        # 30 / 10 / 14


def test_web_settings_round_trip_a_batch_size():
    with _world() as (c, cfg, _):
        r = c.put("/api/settings", json={"batch_size": 25})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["batch_size"] == 25 and body["batch_size_default"] == 10
        assert body["runs_per_day_needed"] == 0.1          # 30 / 25 / 14
        assert c.get("/api/settings").json() == body
        assert _stored(cfg, "batch_size") == "25"          # what `run` reads


def test_web_settings_accept_the_bounds():
    with _world() as (c, cfg, _):
        assert c.put("/api/settings", json={"batch_size": 1}).status_code == 200
        r = c.put("/api/settings", json={"batch_size": ENABLED})
        assert r.status_code == 200 and r.json()["batch_size"] == ENABLED


def test_web_settings_refuse_out_of_range_and_non_integers():
    with _world() as (c, cfg, _):
        for bad in (0, -1, ENABLED + 1, "12", 2.5, True, None):
            r = c.put("/api/settings", json={"batch_size": bad})
            assert r.status_code == 422, (bad, r.status_code, r.text)
        assert c.put("/api/settings", json={}).status_code == 422
        assert _stored(cfg, "batch_size") is None          # nothing was written
        assert c.get("/api/settings").json()["batch_size"] == 10


def test_web_settings_ignore_a_corrupt_stored_value():
    with _world() as (c, cfg, _):
        st = Store(cfg.db_path)
        st.set_setting("batch_size", "lots")
        st.close()
        assert c.get("/api/settings").json()["batch_size"] == 10


def test_web_profile_without_a_derived_profile_is_not_an_error():
    with _world() as (c, cfg, _):
        r = c.get("/api/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["present"] is False
    assert body["interests"] == INTERESTS                  # config, still shown
    assert set(body) == {"present", "profile_version", "source_file", "parsed_at",
                         "summary", "skills", "target_titles", "interests"}


def test_web_profile_serves_the_derived_profile():
    with _world() as (c, cfg, _):
        cfg.profile_path.write_text(yaml.safe_dump({
            "source_file": "resume.pdf", "source_hash": "sha256:ab",
            "parsed_at": "2026-09-24", "profile_version": 3,
            "summary": "Backend engineer.", "skills": ["python", "sql"],
            "target_titles": ["backend engineer"], "title_aliases": {},
            "years_experience": 1}), encoding="utf-8")
        r = c.get("/api/profile")
    assert r.status_code == 200
    assert r.json() == {"present": True, "profile_version": 3,
                        "source_file": "resume.pdf", "parsed_at": "2026-09-24",
                        "summary": "Backend engineer.", "skills": ["python", "sql"],
                        "target_titles": ["backend engineer"],
                        "interests": INTERESTS}


def test_web_profile_that_is_not_a_mapping_reads_as_absent():
    with _world() as (c, cfg, _):
        cfg.profile_path.write_text("- just\n- a list\n", encoding="utf-8")
        r = c.get("/api/profile")
        assert r.status_code == 200 and r.json()["present"] is False
        cfg.profile_path.write_text("key: [unclosed\n", encoding="utf-8")
        r = c.get("/api/profile")
        assert r.status_code == 200 and r.json()["present"] is False
