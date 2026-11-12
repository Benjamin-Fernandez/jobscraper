"""Q-120 (D-205) store oracles for the auto-apply queue (apply_queue_design §2, §3.1, §4;
review H3, M3, L3, L6). In mode `auto` a queued role becomes a real submission, so these pin
the invariants at the only layer with SQL:

  I2 a job waits at most once, never while it has a live attempt, never in two places
     (`queue_take` deletes the row and creates the attempt in one transaction);
  I3 FIFO by (pos, id); only a worker return goes to the front, and a fresh click wins over it;
  M3 a paused queue or a pending yield makes `queue_take` consume nothing;
  H3 a role whose application row is gone or no longer `to_apply` is never taken;
  two connections racing `queue_take` never get the same job;
  a v5 database opens as v6 with the table and keeps its rows.

Temp databases only: no web app, no job, no browser, no network, never data/.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import make_job  # noqa: E402

from jobscraper.store import SCHEMA_VERSION, Store, utcnow  # noqa: E402

NOW = "2026-11-12T08:00:00Z"


@contextmanager
def _world(n_jobs: int = 3, to_apply: bool = True):
    """(store, path, cid, [job ids]) on a temp DB; each job has a `to_apply` row if asked."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        st = Store(path, check_same_thread=False)
        cid = st.insert_company("fakeco", "Fake Co", "https://fakeco.example")
        jobs = [make_job(st, cid, n) for n in range(1, n_jobs + 1)]
        if to_apply:
            for j in jobs:
                st.set_application_status(j, "to_apply")
        st.commit()
        try:
            yield st, path, cid, jobs
        finally:
            st.close()


def _add(st, job, cid, mode="dry_run", source="inbox"):
    pos = st.queue_add(job, cid, mode, source, NOW)
    st.commit()
    return pos


def _attempts(st, job=None) -> list[dict]:
    sql, args = "SELECT * FROM apply_attempts", ()
    if job is not None:
        sql, args = sql + " WHERE job_id = ?", (job,)
    return [dict(r) for r in st.conn.execute(sql, args)]


def test_queue_add_positions_duplicate_remove_and_clear():
    """I2: a second click on a waiting role adds nothing; positions are 1-based in click order."""
    with _world(3) as (st, _p, cid, (j1, j2, j3)):
        assert [_add(st, j, cid) for j in (j1, j2, j3)] == [1, 2, 3]
        assert _add(st, j2, cid, mode="auto", source="retry") is None           # already waiting
        items = st.queue_items()
        assert [(i["job_id"], i["position"], i["mode"], i["source"]) for i in items] == [
            (j1, 1, "dry_run", "inbox"), (j2, 2, "dry_run", "inbox"), (j3, 3, "dry_run", "inbox")]
        assert items[0]["company"] == "Fake Co" and items[0]["role"] == "Engineer 1", items[0]
        assert st.conn.execute("SELECT COUNT(*) FROM apply_queue WHERE job_id = ?",
                               (j2,)).fetchone()[0] == 1
        # a mode or source outside the CHECK never lands
        for mode, source in (("min", "inbox"), ("auto", "cron")):
            try:
                st.queue_add(j1 + "x", cid, mode, source, NOW)
            except sqlite3.IntegrityError:
                st.rollback()
            else:
                raise AssertionError(f"queue_add accepted mode={mode!r} source={source!r}")
        # remove the middle one: the rest close up
        assert st.queue_remove(j2) is True and st.queue_remove(j2) is False
        assert st.queue_positions() == {j1: 1, j3: 2}
        assert st.queue_clear() == 2 and st.queue_items() == [] and _attempts(st) == []


def test_queue_take_is_fifo_creates_one_dry_run_attempt_and_deletes_the_row():
    """I2/I3/I5: the head goes, exactly one `queued` attempt in mode dry_run replaces it (the
    item's own mode travels as `item_mode`), and the role can't be queued again while live."""
    with _world(2) as (st, _p, cid, (j1, j2)):
        assert st.queue_take(utcnow()) == (None, [])                            # empty: nothing
        _add(st, j1, cid, mode="auto")
        _add(st, j2, cid)
        item, dropped = st.queue_take(utcnow())
        assert dropped == [] and item["job_id"] == j1 and item["item_mode"] == "auto", item
        assert item["source"] == "inbox"
        rows = _attempts(st)
        assert len(rows) == 1 and rows[0]["id"] == item["attempt_id"], rows
        assert (rows[0]["state"], rows[0]["mode"], rows[0]["job_id"]) == ("queued", "dry_run", j1)
        assert st.queue_positions() == {j2: 1}                                   # never in two places
        assert st.live_attempt(j1)["id"] == item["attempt_id"]
        # I2 defence in depth: a click while the role is in flight inserts nothing
        assert _add(st, j1, cid) is None and st.queue_positions() == {j2: 1}
        item2, _ = st.queue_take(utcnow())
        assert item2["job_id"] == j2 and len(_attempts(st)) == 2


def test_queue_return_goes_to_the_front_and_a_fresh_click_wins_over_it():
    """I3 + L6: a returned item is next; a return for a role the owner clicked again meanwhile
    leaves the click's row untouched."""
    with _world(3) as (st, _p, cid, (j1, j2, j3)):
        _add(st, j1, cid, mode="auto")
        _add(st, j2, cid)
        item, _ = st.queue_take(utcnow())
        st.set_attempt_state(item["attempt_id"], "failed", reason="cancelled", detail="test")
        st.commit()
        st.queue_return(j1, cid, "auto", "returned: model_unavailable", utcnow())
        items = st.queue_items()
        assert [(i["job_id"], i["source"]) for i in items] == [(j1, "returned"), (j2, "inbox")], items
        assert items[0]["note"] == "returned: model_unavailable" and items[0]["mode"] == "auto"
        assert st.queue_take(utcnow())[0]["job_id"] == j1                       # front is taken next

        _add(st, j3, cid, mode="dry_run")                                        # the fresh click
        before = st.queue_items()
        st.queue_return(j3, cid, "auto", "returned: browser_unavailable", utcnow())
        assert st.queue_items() == before, (before, st.queue_items())          # click's row wins


def test_paused_queue_or_pending_yield_takes_nothing_and_first_pause_wins():
    """M3: a committed Pause/Cancel or a yield request can't be overtaken by a take; L3 the
    first pause reason stays."""
    with _world(1) as (st, _p, cid, (j1,)):
        assert st.queue_pause_if_waiting("restarted", NOW) is False             # nothing waits
        _add(st, j1, cid)
        assert st.queue_pause("owner", None, NOW) is True
        assert st.queue_pause("cancelled", None, NOW) is False
        assert st.queue_pause_if_waiting("restarted", NOW) is False
        assert st.queue_pause_state()["reason"] == "owner"
        assert st.queue_take(utcnow()) == (None, [])
        assert st.queue_positions() == {j1: 1} and _attempts(st) == []          # consumed nothing

        st.queue_resume("2026-11-12T09:00:00Z")
        assert st.queue_pause_state() is None
        assert st.get_setting(Store.QUEUE_RESUMED_AT) == "2026-11-12T09:00:00Z"
        st.queue_request_yield()
        assert st.queue_take(utcnow()) == (None, [])
        assert st.queue_positions() == {j1: 1} and _attempts(st) == []
        assert st.queue_take_yield() is True and st.queue_take_yield() is False # read and clear
        assert st.queue_take(utcnow())[0]["job_id"] == j1

        _add(st, make_job(st, cid, 9), cid)                                      # restart pause
        assert st.queue_pause_if_waiting("restarted", NOW) is True
        assert st.queue_pause_state()["reason"] == "restarted"


def test_take_drops_roles_whose_application_is_gone_or_no_longer_to_apply():
    """H3/P19: an untracked role (no application row) or one marked applied while waiting is
    deleted at take and reported, never turned into an attempt."""
    with _world(3, to_apply=False) as (st, _p, cid, (j1, j2, j3)):
        st.set_application_status(j2, "applied")
        st.set_application_status(j3, "to_apply")
        for j in (j1, j2, j3):
            _add(st, j, cid)
        item, dropped = st.queue_take(utcnow())
        assert item["job_id"] == j3 and dropped == [j1, j2], (item, dropped)
        assert _attempts(st, j1) == [] and _attempts(st, j2) == []
        assert st.queue_items() == []


def test_delete_application_removes_the_queue_row_in_the_same_commit():
    """H3: untracking a waiting role takes it out of the queue; the worker never sees it."""
    with _world(2) as (st, path, cid, (j1, j2)):
        _add(st, j1, cid)
        _add(st, j2, cid)
        assert st.delete_application(j1) is True
        other = Store(path)                                                      # another connection
        try:
            assert other.queue_positions() == {j2: 1}
        finally:
            other.close()
        item, dropped = st.queue_take(utcnow())
        assert item["job_id"] == j2 and dropped == [] and _attempts(st, j1) == []


def test_two_connections_racing_queue_take_never_get_the_same_job():
    """I2 across processes: BEGIN IMMEDIATE serialises the takes. (a) A held write lock makes
    the second taker wait, then it sees the head gone; (b) threads on separate connections
    take distinct jobs, one attempt each."""
    with _world(8) as (st, path, cid, jobs):
        for j in jobs:
            _add(st, j, cid)
        a, b = Store(path, check_same_thread=False), Store(path, check_same_thread=False)
        try:
            # (a) a holds the lock and takes; b waits for it
            got: dict = {}
            a.begin_immediate()
            t = threading.Thread(target=lambda: got.update(b=b.queue_take(utcnow())[0]))
            t.start()
            time.sleep(0.3)
            assert t.is_alive(), "the second taker must wait for the write lock"
            head = a.conn.execute("SELECT job_id FROM apply_queue ORDER BY pos, id LIMIT 1").fetchone()
            a.conn.execute("DELETE FROM apply_queue WHERE job_id = ?", (head[0],))
            a.create_attempt(head[0], cid, "dry_run", utcnow())                  # a's take, by hand
            a.conn.commit()
            t.join(10)
            assert got["b"]["job_id"] == jobs[1] != head[0] == jobs[0], got

            # (b) three threads, two takes each
            conns = [a, b, Store(path, check_same_thread=False)]
            taken: list = []
            errors: list = []
            barrier = threading.Barrier(3)

            def worker(s):
                try:
                    barrier.wait(5)
                    for _ in range(2):
                        item, _d = s.queue_take(utcnow())
                        if item:
                            taken.append(item["job_id"])
                except BaseException as exc:                                     # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(s,)) for s in conns]
            for th in threads:
                th.start()
            for th in threads:
                th.join(30)
            conns[2].close()
            assert errors == [], errors
            assert sorted(taken) == sorted(jobs[2:]) and len(set(taken)) == 6, taken
            counts = st.conn.execute(
                "SELECT job_id, COUNT(*) FROM apply_attempts GROUP BY job_id").fetchall()
            assert {r[0]: r[1] for r in counts} == {j: 1 for j in jobs}, counts
            assert st.queue_items() == []
        finally:
            a.close()
            b.close()


def test_a_v5_database_opens_as_v6_with_the_table_and_keeps_its_rows():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        st = Store(path)
        cid = st.insert_company("fakeco", "Fake Co", "https://fakeco.example")
        j1 = make_job(st, cid, 1)
        st.set_application_status(j1, "to_apply")
        st.commit()
        # make it a v5 file: no queue table, no index, version 5
        st.conn.execute("DROP INDEX IF EXISTS idx_apply_queue_pos")
        st.conn.execute("DROP TABLE apply_queue")
        st.conn.execute("UPDATE meta SET value = '5' WHERE key = 'schema_version'")
        st.conn.commit()
        st.close()

        st = Store(path)
        try:
            assert SCHEMA_VERSION == 6
            assert st.conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "6"
            names = {r[0] for r in st.conn.execute("SELECT name FROM sqlite_master")}
            assert {"apply_queue", "idx_apply_queue_pos"} <= names, names
            assert st.application(j1)["status"] == "to_apply"                   # kept
            assert st.get_job(j1) is not None
            assert _add(st, j1, cid) == 1 and st.queue_take(utcnow())[0]["job_id"] == j1
        finally:
            st.close()
