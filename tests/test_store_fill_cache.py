"""Store oracles for D-78 lane N (Q-35 WP-T4 store half; llm_fill_design §13.3, §14;
apply_design §10.5, §12.4; WP-N5 + the amendment deltas).

  - `fill_cache`: put/get round trip; a different job, inputs_hash, model or prompt_version
    is a miss; a put on the same key replaces; `facts_used_hash` comes back for the caller's
    check; purge by age; a damaged row is a miss; an old-shape table (keyed on `facts_hash`)
    is rebuilt on open;
  - `accounts_for_tenant` lower-cases emails and the host; `applied_on_tenant` needs a click;
  - `annotate_answers` sets notes by (step, field_key) and does not commit.
Temp DBs only (nothing under data/). Verify: python tests/run_tests.py -k store_fill_cache
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.store:Store.fill_cache_get", "jobscraper.store:Store.accounts_for_tenant")

JOB = "job-0001"
PV, MODEL = "fill:v2", "fake-fill:1"


def test_the_store_module_imports():
    import jobscraper.store as S
    assert S.SCHEMA_VERSION >= 3


def _store():
    from jobscraper.store import Store
    d = Path(tempfile.mkdtemp(prefix="fillcache_t_"))
    return Store(d / "t.db"), d / "t.db"


def _row(sig="sig-a", inputs="in-1", facts="facts-1", value="Yes", pv=PV, model=MODEL):
    return {"field_sig": sig, "prompt_version": pv, "model": model, "inputs_hash": inputs,
            "facts_used_hash": facts, "decision": {"value": value, "source": "facts", "fact_refs": ["F3"]}}


@needs(*NEEDS)
def test_fill_cache_round_trip_and_every_key_part_is_a_miss_when_changed():
    st, _ = _store()
    try:
        assert st.fill_cache_put(JOB, [_row(), _row(sig="sig-b", value="No")]) == 2
        got = st.fill_cache_get(JOB, ["sig-a", "sig-b", "sig-c"], PV, MODEL, "in-1")
        assert set(got) == {"sig-a", "sig-b"}
        assert got["sig-a"]["decision"] == {"value": "Yes", "source": "facts", "fact_refs": ["F3"]}
        assert got["sig-a"]["facts_used_hash"] == "facts-1", "returned for the caller's §13.3 check"
        assert st.fill_cache_get("job-0002", ["sig-a"], PV, MODEL, "in-1") == {}, "never across jobs"
        assert st.fill_cache_get(JOB, ["sig-a"], PV, MODEL, "in-2") == {}, "inputs changed"
        assert st.fill_cache_get(JOB, ["sig-a"], PV, "other-model:1", "in-1") == {}, "model changed"
        assert st.fill_cache_get(JOB, ["sig-a"], "fill:v3", MODEL, "in-1") == {}, "prompt changed"
        assert st.fill_cache_get(JOB, [], PV, MODEL, "in-1") == {}
    finally:
        st.close()


@needs(*NEEDS)
def test_fill_cache_put_replaces_and_purge_drops_old_rows():
    st, _ = _store()
    try:
        st.fill_cache_put(JOB, [_row(value="Yes", facts="facts-1")], now="2026-10-01T00:00:00Z")
        st.fill_cache_put(JOB, [_row(value="No", facts="facts-2")], now="2026-10-01T00:00:00Z")
        got = st.fill_cache_get(JOB, ["sig-a"], PV, MODEL, "in-1")["sig-a"]
        assert got["decision"]["value"] == "No" and got["facts_used_hash"] == "facts-2"
        assert st.conn.execute("SELECT COUNT(*) FROM fill_cache").fetchone()[0] == 1
        st.fill_cache_put(JOB, [_row(sig="sig-new")], now="2026-11-02T00:00:00Z")
        assert st.fill_cache_purge("2026-10-03T00:00:00Z") == 1
        assert set(st.fill_cache_get(JOB, ["sig-a", "sig-new"], PV, MODEL, "in-1")) == {"sig-new"}
    finally:
        st.close()


@needs(*NEEDS)
def test_a_damaged_cache_row_is_a_miss():
    st, _ = _store()
    try:
        st.fill_cache_put(JOB, [{**_row(), "decision_json": "{not json"}])
        assert st.fill_cache_get(JOB, ["sig-a"], PV, MODEL, "in-1") == {}
    finally:
        st.close()


@needs(*NEEDS)
def test_an_old_shape_fill_cache_is_rebuilt_on_open():
    from jobscraper.store import Store
    st, path = _store()
    st.conn.execute("DROP TABLE fill_cache")
    st.conn.execute("""CREATE TABLE fill_cache (job_id TEXT, field_sig TEXT, prompt_version TEXT,
                       model TEXT, facts_hash TEXT, decision_json TEXT, created_at TEXT)""")
    st.conn.execute("INSERT INTO fill_cache VALUES ('j','s','p','m','f','{}','2026-01-01')")
    st.conn.commit()
    st.close()
    st = Store(path)
    try:
        cols = {r[1] for r in st.conn.execute("PRAGMA table_info(fill_cache)")}
        assert {"inputs_hash", "facts_used_hash"} <= cols and "facts_hash" not in cols
        assert st.conn.execute("SELECT COUNT(*) FROM fill_cache").fetchone()[0] == 0
        assert st.fill_cache_put(JOB, [_row()]) == 1
    finally:
        st.close()


@needs(*NEEDS)
def test_accounts_for_tenant_is_lower_case_and_per_tenant():
    st, _ = _store()
    try:
        host = "exampleco.wd3.myworkdayjobs.com"
        st.upsert_account("workday", host.upper(), "Alex.Testcase@Example.com",
                          f"jobscraper:workday:{host}", "created")
        st.upsert_account("workday", host, "alex.backup@example.net",
                          f"jobscraper:workday:{host}", "exists_no_password")
        st.upsert_account("workday", "other.wd1.myworkdayjobs.com", "alex.testcase@example.com",
                          "jobscraper:workday:other.wd1.myworkdayjobs.com", "verified")
        got = st.accounts_for_tenant("workday", "ExampleCo.WD3.myworkdayjobs.com")
        assert got == {"alex.testcase@example.com": "created", "alex.backup@example.net": "exists_no_password"}
        assert st.accounts_for_tenant("greenhouse", host) == {}
    finally:
        st.close()


@needs(*NEEDS, "jobscraper.store:Store.applied_on_tenant", "jobscraper.store:Store.annotate_answers")
def test_applied_on_tenant_needs_a_submit_click_and_annotate_does_not_commit():
    from apply_flow_support import add_job, make_world
    w = make_world()
    try:
        st = w.store
        cid, jid = add_job(st, key="exampleco", name="Example Employer", provider="workday", slug="exampleco",
                           external_id="REQ-0001",
                           url="https://exampleco.wd3.myworkdayjobs.com/External/job/Singapore/Graduate_REQ-0001")
        host = "exampleco.wd3.myworkdayjobs.com"
        aid = st.create_attempt(jid, cid, "dry_run", "2026-11-02T00:00:00Z")
        st.update_attempt(aid, ats="workday", tenant_host=host)
        st.commit()
        assert st.applied_on_tenant("workday", host) is False, "no click yet"
        st.conn.execute("UPDATE apply_attempts SET submit_clicked_at = '2026-11-02T00:01:00Z' WHERE id = ?", (aid,))
        st.commit()
        assert st.applied_on_tenant("workday", host.upper()) is True
        assert st.applied_on_tenant("workday", "other.wd1.myworkdayjobs.com") is False
        base = {"label": "Q", "label_norm": "q", "field_type": "text", "required": True, "tier": 3,
                "source": "llm", "confidence": 0.9, "status": "filled"}
        st.add_answers(aid, [dict(base, step="my_information", field_key="a"),
                             dict(base, step="questions_4", field_key="a"),
                             dict(base, step="questions_4", field_key="b")])
        st.commit()
        n = st.annotate_answers(aid, {("questions_4", "a"): "review: changed by the site",
                                      ("questions_4", "zz"): "no such row"})
        assert n == 1
        notes = {(r["step"], r["field_key"]): r["note"] for r in st.answers(aid)}
        assert notes[("questions_4", "a")] == "review: changed by the site"
        assert notes[("my_information", "a")] is None and notes[("questions_4", "b")] is None
        other = sqlite3.connect(str(w.db_path))
        try:
            seen = other.execute("SELECT note FROM apply_answers WHERE attempt_id = ? AND step = ? "
                                 "AND field_key = ?", (aid, "questions_4", "a")).fetchone()
        except sqlite3.OperationalError:
            seen = ("locked",)                               # the writer holds the lock: not committed
        finally:
            other.close()
        assert seen in ((None,), ("locked",)), "annotate_answers does not commit"
        st.commit()
    finally:
        w.close()


if WAITING[_W0:]:
    print(f"[test_store_fill_cache] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
