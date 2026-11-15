"""Q-121 WP-S1 store pins (llm_first_fill_design §6, §7.3, §12; schema v7).

Schema v7 adds `apply_answers.assumed`, the question status `assumed`, and the first-use trial
counter (a `settings` row). The owner's live database is migrated by the first launch after the
merge, so the migration pin must fail if ANY existing row is lost or changed. A v6 database is
built by creating a current one, filling every table the owner's data lives in, removing the new
column and stamping version 6; the pin then reopens it and compares every row.
Verify: python tests/run_tests.py -k store_always
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import failed_attempt, make_job, question_row, seed_question  # noqa: E402

from jobscraper.store import SCHEMA_VERSION, Store, utcnow  # noqa: E402

TABLES = ("companies", "jobs", "applications", "app_events", "apply_attempts", "apply_answers", "apply_queue",
          "questions", "question_sightings", "settings", "answer_memory", "ats_accounts", "fill_cache")


def _snapshot(st: Store) -> dict:
    out = {}
    for t in TABLES:
        try:
            rows = [dict(r) for r in st.conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
        except Exception:                                       # a table this build does not have
            continue
        out[t] = rows
    out["meta"] = {r["key"]: r["value"] for r in st.conn.execute("SELECT key, value FROM meta")}
    return out


def _cols(st: Store, table: str) -> list[str]:
    return [r["name"] for r in st.conn.execute(f"PRAGMA table_info({table})")]


def _v6_database(path: Path) -> dict:
    """A v6 file with rows in every table the owner's data lives in. Returns the ids."""
    st = Store(path)
    cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example/careers")
    j1, j2, j3 = (make_job(st, cid, n) for n in (1, 2, 3))
    st.set_application_status(j1, "applied")
    st.set_application_status(j2, "to_apply")
    st.set_application_status(j3, "to_apply")
    a1 = failed_attempt(st, j1, cid, reason="owner_fact_missing")
    st.add_answers(a1, [
        {"step": "one", "field_key": "one:first_name", "label": "First name", "label_norm": "first name",
         "field_type": "text", "required": True, "tier": 1, "source": "profile:identity.first_name",
         "confidence": 0.9, "status": "filled", "value_json": "Alex", "note": "kept", "evidence": "quote"},
        {"step": "one", "field_key": "one:notice", "label": "Notice", "label_norm": "notice",
         "field_type": "number", "required": False, "tier": 2, "source": "profile:availability",
         "confidence": 0.8, "status": "skipped", "value_json": 0}])
    seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, key="visa", label="Visa status", kind="text",
                  employer_norm="exampleco")
    q2 = seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, key="lang", label="Language", kind="text",
                       field_key="q2", employer_norm="exampleco")
    st.set_questions_status("lang", "answered", utcnow(), ids=[q2])
    assert st.queue_add(j2, cid, "auto", "inbox", utcnow()) is not None
    assert st.queue_add(j3, cid, "dry_run", "inbox", utcnow()) is not None
    st.set_setting("apply.mode", "auto")
    st.set_setting("apply.daily_cap", "0")
    st.set_setting("some.owner.setting", "keep me")
    st.commit()
    # make it a v6 file: no `assumed` column, version 6
    st.conn.execute("ALTER TABLE apply_answers DROP COLUMN assumed")
    if "trial" in _cols(st, "apply_attempts"):                       # v8 (Q-121 A1-W): not in a v6 file
        st.conn.execute("ALTER TABLE apply_attempts DROP COLUMN trial")
    st.conn.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
    st.conn.commit()
    st.close()
    return {"cid": cid, "jobs": (j1, j2, j3), "a1": a1}


def test_the_schema_version_is_at_least_8():
    assert SCHEMA_VERSION >= 8      # v8 = apply_attempts.trial (Q-121 A1-W); the v7 -> v8 pin is in test_always_a1_w


def test_a_v6_database_opens_as_the_current_version_with_every_row_intact_and_old_answers_unassumed():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        ids = _v6_database(path)
        import sqlite3
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
        assert "assumed" not in [r["name"] for r in con.execute("PRAGMA table_info(apply_answers)")]
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "6"
        v6 = {}
        for t in TABLES:
            try:
                v6[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
            except sqlite3.OperationalError:
                pass
        con.close()
        assert v6["apply_answers"] and v6["apply_queue"] and v6["questions"] and v6["applications"] \
            and v6["apply_attempts"] and v6["settings"] and v6["question_sightings"], "the v6 file has data to lose"

        st = Store(path)
        try:
            assert st.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
            assert "assumed" in _cols(st, "apply_answers") and "trial" in _cols(st, "apply_attempts")
            now = _snapshot(st)
            for t, rows in v6.items():
                assert len(now[t]) == len(rows), (t, len(rows), len(now[t]))
                for before, after in zip(rows, now[t]):
                    if t == "apply_answers":
                        assert after.pop("assumed") == 0, "an answer from before v7 reads as not assumed"
                    if t == "apply_attempts":
                        assert after.pop("trial") == 0, "an attempt from before v8 reads as not a trial"
                    assert after == before, (t, before, after)
            assert st.assumed_count(ids["a1"]) == 0
            assert [q["status"] for q in st.conn.execute("SELECT status FROM questions ORDER BY id")] == \
                ["open", "answered"]
            assert st.queue_positions() == {ids["jobs"][1]: 1, ids["jobs"][2]: 2}
            assert st.get_setting("some.owner.setting") == "keep me" and st.get_setting("apply.mode") == "auto"
            assert st.always_trial_used() == 0
            first = _snapshot(st)
        finally:
            st.close()
        st = Store(path)                                             # a second open changes nothing
        try:
            assert _snapshot(st) == first
            assert _cols(st, "apply_answers").count("assumed") == 1
        finally:
            st.close()


def test_a_new_answer_row_can_be_assumed_and_only_filled_or_prefilled_ones_are_counted():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "jobscraper.db")
        try:
            cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
            j = make_job(st, cid, 1)
            a = failed_attempt(st, j, cid)
            b = failed_attempt(st, make_job(st, cid, 2), cid)
            base = {"step": "one", "label": "L", "label_norm": "l", "field_type": "text", "required": True,
                    "tier": 5, "source": "assumption", "confidence": 0.5}
            rows = [{**base, "field_key": f"k{i}", "status": s, "assumed": m}
                    for i, (s, m) in enumerate((("filled", True), ("prefilled", True), ("skipped", True),
                                                ("unknown", True), ("filled", False), ("failed", True)))]
            st.add_answers(a, rows)
            st.add_answers(b, [{**base, "field_key": "x", "status": "filled"}])      # `assumed` left out -> 0
            st.commit()
            assert st.assumed_count(a) == 2
            assert st.assumed_counts([a, b, 12345]) == {a: 2}
            assert [r["assumed"] for r in st.answers(b)] == [0]
            assert st.assumed_counts([]) == {}
        finally:
            st.close()


def _q(**kw):
    return question_row(key=kw.pop("key", "colour"), label=kw.pop("label", "Favourite colour"), kind="text", **kw)


def test_question_status_moves_as_the_assumed_card_needs():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "jobscraper.db")
        try:
            now = utcnow()
            qid = st.upsert_question(_q(reason="assumed"), now)
            status = lambda: st.conn.execute("SELECT status FROM questions WHERE id=?", (qid,)).fetchone()[0]
            assert status() == "assumed", "a new assumed row is not open"
            assert st.upsert_question(_q(reason="assumed"), now) == qid and status() == "assumed"
            st.set_questions_status("colour", "answered", now, ids=[qid])
            assert status() == "answered"
            st.upsert_question(_q(reason="assumed"), now)
            assert status() == "assumed", "answered but its saved answer was not used this time"
            st.upsert_question(_q(reason="no_rule"), now)
            assert status() == "open", "a later non-assumed sighting reopens it"
            st.upsert_question(_q(reason="assumed"), now)
            reason = lambda: st.conn.execute("SELECT reason FROM questions WHERE id=?", (qid,)).fetchone()[0]
            assert status() == "open" and reason() == "no_rule",                 "F3: an open question stays open and keeps its reason when an assumed sighting arrives"
            st.set_questions_status("colour", "dismissed", now, ids=[qid])
            st.upsert_question(_q(reason="assumed"), now)
            assert status() == "dismissed", "dismissed stays dismissed"
            st.upsert_question(_q(reason="no_rule"), now)
            assert status() == "dismissed"
        finally:
            st.close()


def test_the_trial_counter_counts_up_commits_and_reads_garbage_as_zero():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        st = Store(path)
        try:
            assert st.always_trial_used() == 0
            assert st.count_always_trial() == 1 and st.count_always_trial() == 2
            assert st.always_trial_used() == 2
            st.set_setting(Store.ALWAYS_TRIAL_USED, "garbage")
            assert st.always_trial_used() == 0
            st.set_setting(Store.ALWAYS_TRIAL_USED, "-4")
            assert st.always_trial_used() == 0
        finally:
            st.close()
        st = Store(path)                                            # it was committed
        try:
            assert st.always_trial_used() == 0
            st.set_setting(Store.ALWAYS_TRIAL_USED, 5)
            st.close()
            st = Store(path)
            assert st.always_trial_used() == 5 and Store.ALWAYS_TRIAL_USED == "apply.always_trial_used"
        finally:
            st.close()


def test_an_attempt_that_only_asked_for_answered_for_you_cards_is_not_a_retry_candidate():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "jobscraper.db")
        try:
            cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
            j1, j2 = make_job(st, cid, 1), make_job(st, cid, 2)
            a1 = failed_attempt(st, j1, cid, reason="unanswerable_required")
            a2 = failed_attempt(st, j2, cid, reason="owner_fact_missing")
            seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, key="colour", label="Colour", kind="text",
                          reason="assumed")
            seed_question(st, attempt_id=a2, job_id=j2, company_id=cid, key="dob", label="Date of Birth",
                          kind="text", reason="profile_gap", target_path="identity.date_of_birth", sensitive=True)
            got = {c["job_id"] for c in st.retry_candidates()}
            assert got == {j2}, "an owner-fact attempt is retried after the owner answers; an assumed-only one is not"
        finally:
            st.close()
