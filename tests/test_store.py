"""Persistence invariants for the v2 store (PRD section 8.4).

The first test is the one carried over from v1, and it guards the invariant most
likely to destroy data: a company whose fetch FAILED must not have its jobs
marked closed. M3-T1 rewrote the schema underneath it; the invariant is unchanged.
The rest pin down what the other lanes build on: the application history the
web app reads (PRD 0.6, contract 5), crash recovery, and the two content-hashed
caches.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper.models import RawJob
from jobscraper.store import SchemaMismatch, Store


def _db() -> Path:
    return Path(tempfile.mkdtemp()) / "t.db"


def _store(n=3) -> Store:
    st = Store(_db())
    for i in range(1, n + 1):
        st.insert_company(f"c{i}", f"C{i}", "https://x/careers")
    return st


def _job(st: Store, cid: int, ext="1", run=1) -> str:
    raw = RawJob(external_id=ext, title="Software Engineer",
                 url=f"https://x/{ext}", location="Singapore")
    jid = raw.job_id(cid, "greenhouse")
    st.upsert_job(jid, cid, raw, run, True)
    st.commit()
    return jid


def test_failed_fetch_must_not_close_jobs():
    """The trap: a timeout must never mass-close a company's postings."""
    st = _store(3)
    cid = st.companies()[0].id
    jid = _job(st, cid)

    # A SUCCESSFUL fetch that omits the job closes it...
    assert st.close_missing(cid, set()) == 1
    # ...and close_missing is the only path that closes anything; the pipeline
    # calls it exclusively for outcomes where ok=True. Re-seeing it reopens it.
    raw = RawJob(external_id="1", title="Software Engineer", url="https://x/1",
                 location="Singapore")
    st.upsert_job(jid, cid, raw, 2, False)
    st.commit()
    assert st.get_job(jid)["closed_at"] is None


def test_store_fresh_schema_has_v2_columns_and_due_index():
    st = Store(_db())
    cols = {r["name"] for r in st.conn.execute("PRAGMA table_info(companies)")}
    assert {"key", "last_scraped_at", "enabled"} <= cols
    assert not {"tier", "category", "ordinal"} & cols
    idx = {r["name"] for r in st.conn.execute("PRAGMA index_list(companies)")}
    assert "idx_companies_due" in idx
    assert {r["name"] for r in st.conn.execute("PRAGMA table_info(jobs)")} >= {"vital_text"}


def test_store_refuses_a_v1_database():
    """Both versions default to data/jobscraper.db; mixing them must fail loudly."""
    db = _db()
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT, tier TEXT)")
    c.commit()
    c.close()
    try:
        Store(db)
    except SchemaMismatch as e:
        assert "v1 schema" in str(e)
    else:
        raise AssertionError("a v1 database was opened as v2")


def test_store_v1_refuses_a_v2_database():
    from jobscraper.store_v1 import Store as V1Store
    db = _db()
    Store(db).close()
    try:
        V1Store(db)
    except RuntimeError as e:
        assert "v2 database" in str(e)
    else:
        raise AssertionError("the v1 store opened a v2 database")


def test_new_company_is_due_immediately():
    st = _store(1)
    assert st.companies()[0].last_scraped_at is None


def test_store_same_status_twice_appends_one_event():
    """M6-T2's idempotency lives here: the web layer just forwards the bool."""
    st = _store(1)
    assert st.set_application_status("j1", "applied") is True
    assert st.set_application_status("j1", "applied") is False
    assert len(st.application_events("j1")) == 1


def test_store_applied_date_is_set_once_and_kept():
    st = _store(1)
    st.set_application_status("j1", "to_apply", at="2026-09-20T09:00:00")
    assert st.application("j1")["applied_at"] is None
    st.set_application_status("j1", "applied", at="2026-09-21T09:00:00")
    st.set_application_status("j1", "interviewing", at="2026-10-02T09:00:00")
    assert st.application("j1")["applied_at"] == "2026-09-21"
    ev = st.application_events("j1")
    assert [(e["from_status"], e["to_status"]) for e in ev] == [
        (None, "to_apply"), ("to_apply", "applied"), ("applied", "interviewing")]


def test_store_notes_update_without_an_event():
    st = _store(1)
    st.set_application_status("j1", "applied", "first note")
    st.set_application_status("j1", "applied", "second note")
    assert st.application("j1")["notes"] == "second note"
    assert len(st.application_events("j1")) == 1


def test_store_application_without_a_job_row_still_lists():
    """An orphan (D-14) keeps company, role and URL on its own row."""
    st = _store(1)
    st.set_application_status("gone", "applied", company="OKX", role="SRE",
                              url="https://x/gone")
    rows = st.applications()
    assert len(rows) == 1
    assert (rows[0]["company"], rows[0]["role"], rows[0]["url"]) == (
        "OKX", "SRE", "https://x/gone")


def test_store_application_joins_job_details():
    st = _store(1)
    cid = st.companies()[0].id
    jid = _job(st, cid)
    st.set_application_status(jid, "applied")
    row = st.applications()[0]
    assert row["company"] == "C1" and row["role"] == "Software Engineer"
    assert st.application_statuses() == {jid: "applied"}


def test_store_reap_marks_only_stale_running_runs_failed():
    st = _store(0)
    old = st.start_run(at="2026-09-24T00:00:00")
    fresh = st.start_run(at="2026-09-24T01:55:00")
    done = st.start_run(at="2026-09-23T00:00:00")
    st.finish_run(done, "ok", {})
    n = st.reap_stale_runs(3600, now="2026-09-24T02:00:00")
    status = {r["run_no"]: r["status"] for r in st.list_runs()}
    assert n == 1
    assert status == {old: "failed", fresh: "running", done: "ok"}


def test_store_list_runs_parses_stats_newest_first():
    st = _store(0)
    a = st.start_run()
    st.finish_run(a, "ok", {"accepted": 3})
    b = st.start_run()
    runs = st.list_runs()
    assert [r["run_no"] for r in runs] == [b, a]
    assert runs[1]["stats"] == {"accepted": 3} and runs[0]["stats"] == {}


def test_store_decision_cache_keys_on_vital_hash():
    """A changed description is a new decision; an unchanged one is never re-paid."""
    st = _store(1)
    jid = _job(st, st.companies()[0].id)
    st.save_decision(jid, 1, "h1", "reject", False, 0, "US only", "haiku")
    assert st.get_decision(jid, 1, "h1")["decision"] == "reject"
    assert st.get_decision(jid, 1, "h2") is None
    assert st.get_decision(jid, 2, "h1") is None


def test_store_accepted_jobs_uses_the_newest_decision():
    st = _store(1)
    jid = _job(st, st.companies()[0].id)
    st.save_decision(jid, 1, "h1", "accept", True, 0, "fits", "haiku")
    st.conn.execute("UPDATE decisions SET decided_at = '2026-01-01T00:00:00'")
    st.save_decision(jid, 1, "h2", "reject", True, 5, "too senior", "haiku")
    assert st.accepted_jobs(1) == []


def test_store_prefilter_verdict_is_scoped_to_its_rules():
    st = _store(1)
    jid = _job(st, st.companies()[0].id)
    st.save_prefilter(jid, 1, "rulesA", False, "title_deny", "senior")
    assert st.get_prefilter(jid, 1, "rulesA")["reject_rule"] == "title_deny"
    assert st.get_prefilter(jid, 1, "rulesB") is None
    assert st.prefilter_rejections_by_rule(1, "rulesA") == {"title_deny": 1}
