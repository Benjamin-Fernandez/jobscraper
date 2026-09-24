"""The web app: the SPA is served, and the API keeps its documented shapes.

Every test builds the app with `create_app(cfg, store_factory=...)`, handing it
a config that points at a fixture shortlist and a real store in a temp
directory. That is the seam
the design asks for: the web layer reads what the pipeline already produced
(PRD 8.2) and is tested without running the pipeline or touching a database.

PRD sections 8.5 and 8.6; tasks M7-T1 onwards.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from jobscraper.config import Config  # noqa: E402
from jobscraper.web.api import STATIC_DIR, create_app  # noqa: E402


def _cfg(**paths: str) -> Config:
    return Config({"paths": dict(paths),
                   "web": {"host": "127.0.0.1", "port": 8765}})


def _client(cfg: Config | None = None, store=None, **kw) -> TestClient:
    return TestClient(create_app(cfg or _cfg(),
                                 store_factory=(lambda: store) if store else None,
                                 **kw))


# ---------------------------------------------------------------- M7-T1

def test_web_serves_the_built_spa_at_root():
    assert (STATIC_DIR / "index.html").is_file(), (
        "the built UI is committed (M10-T3) - run `npm run build` in web/")
    r = _client().get("/")
    assert r.status_code == 200
    assert '<div id="app">' in r.text


def test_web_serves_the_bundles_the_page_references():
    """index.html's asset URLs must resolve, or the page is blank."""
    html = _client().get("/").text
    refs = [part.split('"', 1)[0] for part in html.split('src="')[1:]]
    refs += [part.split('"', 1)[0] for part in html.split('href="')[1:]]
    assets = [r for r in refs if "assets/" in r]
    assert assets, "index.html references no built assets"
    client = _client()
    for ref in assets:
        assert client.get("/" + ref.lstrip("./")).status_code == 200, ref


def test_web_explains_an_unbuilt_ui_instead_of_404ing():
    with tempfile.TemporaryDirectory() as tmp:
        r = _client(static_dir=Path(tmp)).get("/")
    assert r.status_code == 200
    assert "npm run build" in r.text


def test_web_binds_loopback_by_default():
    """No auth exists (R-9); binding wide by default is a regression (8.6)."""
    import os
    saved = os.environ.pop("JOBSCRAPER_HOST", None)
    try:
        assert Config({}).web["host"] == "127.0.0.1"
        assert Config({}).web["port"] == 8765
    finally:
        if saved is not None:
            os.environ["JOBSCRAPER_HOST"] = saved


def test_web_verb_is_wired_into_the_cli():
    from jobscraper.cli import build_parser, cmd_web
    assert build_parser().parse_args(["web"]).fn is cmd_web


# ---------------------------------------------------------------- M7-T2 / M6

FIXTURE = ROOT / "tests" / "fixtures" / "shortlist.json"


@contextmanager
def _world(shortlist: Path = FIXTURE, runs: int = 12):
    """A real v2 store in a temp dir, `runs` finished runs, and a client.

    Yields (client, open_store). Every request opens and closes its own
    connection, exactly as in production.
    """
    from jobscraper.store import Store
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "jobscraper.db"

        def open_store() -> Store:
            return Store(db, check_same_thread=False)

        seed = open_store()
        for _ in range(runs):
            seed.finish_run(seed.start_run(), "ok", {})
        seed.close()
        cfg = _cfg(shortlist=str(shortlist), db=str(db))
        yield TestClient(create_app(cfg, store_factory=open_store)), open_store


def _ids(jobs: list[dict]) -> set[str]:
    return {j["id"] for j in jobs}


def test_web_runs_lists_every_run_newest_first_with_accepted_counts():
    with _world() as (client, _):
        r = client.get("/api/runs")
    assert r.status_code == 200
    runs = r.json()
    assert [x["run_no"] for x in runs] == list(range(12, 0, -1))
    assert {"run_no", "finished_at", "status", "accepted"} <= set(runs[0])
    by_no = {x["run_no"]: x for x in runs}
    assert by_no[12]["accepted"] == 3 and by_no[11]["accepted"] == 2
    # A run that accepted nothing still appears, and says so.
    assert by_no[3]["accepted"] == 0


def test_web_shortlist_latest_and_a_numbered_run_are_different_sets():
    with _world() as (client, _):
        latest = client.get("/api/shortlist?run=latest").json()
        default = client.get("/api/shortlist").json()
        eleven = client.get("/api/shortlist?run=11").json()
        every = client.get("/api/shortlist?run=all").json()
    assert _ids(latest) == {"a1b2c3", "d4e5f6", "g7h8i9"}
    assert _ids(default) == _ids(latest), "no ?run= means latest"
    assert _ids(eleven) == {"j1k2l3", "m4n5o6"}
    assert _ids(every) == _ids(latest) | _ids(eleven)


def test_web_shortlist_unknown_run_is_an_empty_list_not_a_500():
    with _world() as (client, _):
        r = client.get("/api/shortlist?run=99999")
    assert r.status_code == 200
    assert r.json() == []


def test_web_shortlist_rejects_a_malformed_run():
    with _world() as (client, _):
        assert client.get("/api/shortlist?run=12;drop").status_code == 422


def test_web_shortlist_keeps_the_section_8_3_6_fields():
    with _world() as (client, _):
        job = client.get("/api/shortlist?run=12").json()[0]
    for field in ("id", "run_no", "company", "title", "url", "location",
                  "posted_at", "yoe_min", "reason", "decided_at"):
        assert field in job, field


def test_web_shortlist_joins_status_without_dropping_unmarked_jobs():
    """D-5: status comes from the store; a job with no row has status None."""
    with _world() as (client, open_store):
        store = open_store()
        store.set_application_status("a1b2c3", "applied")
        store.close()
        jobs = {j["id"]: j for j in client.get("/api/shortlist?run=12").json()}
    assert len(jobs) == 3, "the join must not drop jobs without a status"
    assert jobs["a1b2c3"]["status"] == "applied"
    assert jobs["d4e5f6"]["status"] is None
    assert jobs["d4e5f6"]["closed"] is False


def test_web_missing_shortlist_is_an_empty_queue():
    with tempfile.TemporaryDirectory() as tmp:
        with _world(shortlist=Path(tmp) / "absent.json", runs=0) as (client, _):
            assert client.get("/api/shortlist").json() == []
            assert client.get("/api/runs").json() == []
