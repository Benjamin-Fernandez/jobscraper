"""The web app: the SPA is served, and the API keeps its documented shapes.

Every test builds the app with `create_app(cfg, store_factory=...)`, handing it
a config that points at a fixture shortlist (tests/fixtures/shortlist.json, the
PRD 8.3[6] shape) and a real store in a temp directory. That is the seam the
design asks for: the web layer reads what the pipeline already produced
(PRD 8.2), so it is tested without running the pipeline.

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
                                 **kw), base_url="http://localhost")


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


REAL_CONFIG = ROOT / "config" / "config.yaml"


def _config_file(tmp: Path, statuses: list[str] | None = None, **paths: str) -> Config:
    """The shipped config.yaml, edited as a user would, written and loaded afresh.

    Going through `load_config` on a real file is the test's "restart": nothing
    carries over from the config the process started with.
    """
    import yaml

    from jobscraper.config import load_config
    raw = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    raw["paths"].update(paths)
    if statuses is not None:
        raw["applications"]["statuses"] = statuses
    p = tmp / f"config-{len(list(tmp.glob('config-*.yaml')))}.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(p)


@contextmanager
def _world(shortlist: Path = FIXTURE, runs: int = 12,
           statuses: list[str] | None = None):
    """A real v2 store in a temp dir, `runs` finished runs, and a client.

    Yields (client, open_store). Every request opens and closes its own
    connection, exactly as in production. `statuses`, when given, builds the
    app from a copy of the shipped config.yaml with that status vocabulary.
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
        if statuses is None:
            cfg = _cfg(shortlist=str(shortlist), db=str(db))
        else:
            cfg = _config_file(Path(tmp), statuses, shortlist=str(shortlist), db=str(db))
        yield (TestClient(create_app(cfg, store_factory=open_store),
                          base_url="http://localhost"), open_store)


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


def test_web_applications_lists_every_status_with_its_timeline():
    with _world() as (client, open_store):
        store = open_store()
        store.set_application_status("a1b2c3", "applied")
        store.set_application_status("a1b2c3", "interviewing")
        # An orphan: applied to, but not (or no longer) in the shortlist.
        store.set_application_status("gone1", "applied", company="Old Co",
                                     role="Engineer", url="https://example.org/x")
        store.close()
        r = client.get("/api/applications")
    assert r.status_code == 200
    rows = {row["job_id"]: row for row in r.json()}
    assert set(rows) == {"a1b2c3", "gone1"}
    okx = rows["a1b2c3"]
    assert okx["status"] == "interviewing"
    assert okx["company"] == "OKX", "the shortlist describes a job the store cannot"
    assert okx["role"] == "DevOps / Site Reliability Engineer"
    assert okx["run_no"] == 12
    assert [e["to_status"] for e in okx["events"]] == ["applied", "interviewing"]
    assert okx["events"][1]["from_status"] == "applied"
    assert rows["gone1"]["company"] == "Old Co"
    assert rows["gone1"]["run_no"] is None


def test_web_stats_counts_per_status_and_run_in_config_order():
    with _world() as (client, open_store):
        store = open_store()
        store.set_application_status("a1b2c3", "applied")
        store.set_application_status("j1k2l3", "applied")
        store.set_application_status("m4n5o6", "rejected")
        store.close()
        r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["statuses"] == Config({}).application_statuses
    assert list(body["by_status"])[:len(body["statuses"])] == body["statuses"]
    assert body["by_status"]["applied"] == 2
    assert body["by_status"]["rejected"] == 1
    assert body["by_status"]["offer"] == 0
    assert body["by_run"] == {"12": 3, "11": 2}


# ---------------------------------------------------------------- M6-T2

def _events(open_store, job_id: str) -> list[dict]:
    store = open_store()
    try:
        return store.application_events(job_id)
    finally:
        store.close()


def test_web_posting_applied_twice_appends_exactly_one_event():
    with _world() as (client, open_store):
        first = client.post("/api/applications/a1b2c3", json={"status": "applied"})
        second = client.post("/api/applications/a1b2c3", json={"status": "applied"})
        events = _events(open_store, "a1b2c3")
        shown = {j["id"]: j for j in client.get("/api/shortlist?run=12").json()}
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["event_appended"] is True
    assert second.json()["event_appended"] is False
    assert len(events) == 1, events
    assert shown["a1b2c3"]["status"] == "applied", "the write must show on read"


def test_web_status_change_appends_and_notes_update_without_an_event():
    with _world() as (client, open_store):
        client.post("/api/applications/a1b2c3", json={"status": "applied"})
        client.post("/api/applications/a1b2c3",
                    json={"status": "applied", "notes": "referral from Sam"})
        r = client.post("/api/applications/a1b2c3", json={"status": "interviewing"})
        events = _events(open_store, "a1b2c3")
    assert r.json()["application"]["notes"] == "referral from Sam"
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "applied"), ("applied", "interviewing")]


def test_web_rejects_a_status_outside_the_configured_vocabulary():
    with _world() as (client, open_store):
        r = client.post("/api/applications/a1b2c3", json={"status": "ghosted"})
        events = _events(open_store, "a1b2c3")
    assert r.status_code == 422
    assert events == []


def test_web_write_requires_a_json_body():
    """A cross-site HTML form can only send form or text bodies; refuse them."""
    with _world() as (client, open_store):
        r = client.post("/api/applications/a1b2c3",
                        content='{"status": "applied"}',
                        headers={"Content-Type": "text/plain"})
        events = _events(open_store, "a1b2c3")
    assert r.status_code == 422
    assert events == []


def test_web_rejects_a_malformed_job_id():
    with _world() as (client, _):
        r = client.post("/api/applications/a%20b", json={"status": "applied"})
    assert r.status_code == 422


# ---------------------------------------------------------------- M8-T2
#
# The status vocabulary is config: config.yaml `applications.statuses` ->
# Config.application_statuses -> `GET /api/stats` `statuses` -> the Applications
# dropdown (web/src/tabs/Applications.vue), and the same list gates `POST`.
# `web/tests/Applications.test.js` proves the dropdown half with no code change.

WITH_ON_HOLD = ["to_apply", "applied", "interviewing", "on_hold", "offer",
                "rejected", "withdrawn"]


def test_web_a_status_added_to_config_is_served_and_accepted_with_no_code_change():
    """The M8-T2 Verify: add `on_hold` to config.yaml, restart, it is live."""
    with _world(statuses=WITH_ON_HOLD) as (client, open_store):
        stats = client.get("/api/stats").json()
        r = client.post("/api/applications/a1b2c3", json={"status": "on_hold"})
        rows = {row["job_id"]: row for row in client.get("/api/applications").json()}
        after = client.get("/api/stats").json()
    assert stats["statuses"] == WITH_ON_HOLD, "served in config order"
    assert r.status_code == 200, r.text
    assert rows["a1b2c3"]["status"] == "on_hold"
    assert after["by_status"]["on_hold"] == 1

    with _world() as (client, _):                  # the shipped vocabulary
        refused = client.post("/api/applications/a1b2c3", json={"status": "on_hold"})
    assert refused.status_code == 422, "without the config line it is refused"


def test_web_a_status_config_change_leaves_prefilter_verdicts_valid():
    """M8-T2's second half: `prefilter` rows are keyed on rules_hash, which is a
    hash of rules.yaml alone. Editing config.yaml must not change it, or every
    stored verdict would silently go stale and be re-evaluated."""
    from jobscraper.filter import load_rules
    from jobscraper.models import RawJob
    from jobscraper.store import Store
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        before = _config_file(tmp)
        after = _config_file(tmp, WITH_ON_HOLD)
        assert after.application_statuses == WITH_ON_HOLD
        assert after.application_statuses != before.application_statuses
        assert after.rules_path == before.rules_path

        hash_before = load_rules(before.rules_path).hash
        hash_after = load_rules(after.rules_path).hash
        assert hash_after == hash_before, "a status edit re-keyed the prefilter"

        store = Store(tmp / "jobscraper.db")
        try:
            cid = store.insert_company("acme", "Acme", "https://acme.example/careers")
            raw = RawJob(external_id="1", title="SRE", url="https://acme.example/1",
                         location="Singapore")
            jid = raw.job_id(cid, "greenhouse")
            store.upsert_job(jid, cid, raw, 1, True)
            store.commit()
            store.save_prefilter(jid, 1, hash_before, passed=True, overlap_score=3)
            assert store.get_prefilter(jid, 1, hash_after) is not None
            assert store.jobs_pending_prefilter(1, hash_after) == [], (
                "the posting would be prefiltered again after a status edit")
        finally:
            store.close()

    rules_doc = load_rules(before.rules_path).path.read_text(encoding="utf-8")
    assert "statuses" not in rules_doc, "the vocabulary belongs in config.yaml only"


def test_web_shipped_vocabulary_keeps_the_two_statuses_the_inbox_names():
    """The Inbox has no dropdown: its one button writes `applied`, and it treats
    `to_apply` as not applied yet. Everything else in the list is free to change,
    but dropping either of these from config would break that button."""
    import yaml
    raw = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    statuses = raw["applications"]["statuses"]
    assert {"to_apply", "applied"} <= set(statuses), statuses
    assert len(statuses) == len(set(statuses)), "duplicate status in config"



def test_web_refuses_a_foreign_host_header():
    """DNS rebinding (R-9): a page that points its own domain at 127.0.0.1 sends
    that domain as the Host header. The app must not answer it."""
    c = _client()
    assert c.get("/api/runs").status_code == 200
    evil = c.get("/api/runs", headers={"host": "attacker.example"})
    assert evil.status_code == 400
    assert c.get("/api/runs", headers={"host": "127.0.0.1:8765"}).status_code == 200


def test_web_allowed_hosts_can_be_extended_in_config():
    cfg = _cfg()
    cfg.raw["web"]["allowed_hosts"] = ["jobs.home.lan"]
    c = TestClient(create_app(cfg), base_url="http://jobs.home.lan")
    assert c.get("/api/runs").status_code == 200
    assert c.get("/api/runs", headers={"host": "localhost"}).status_code == 400
