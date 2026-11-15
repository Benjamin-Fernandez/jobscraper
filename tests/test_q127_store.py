"""Q-127 Release 1 store pins for lane S1 (q127_profile_questions_design.md B.5, B.8 pin 20-a).

RED UNTIL `eng/Q-127-S1` MERGES into this branch: schema v9 (`apply_answers.field_class`) and the
four store methods `answer_row`, `attempt_field_question`, `mark_answer_corrected`,
`waiting_on_details` do not exist on `int/Q-121` at 0ddd971. Every test below is expected to fail
there (AttributeError / version 8 / missing column) and to pass once S1 is in.

Assumed shapes (B.5 fixes the NAMES, not the return shapes; see comms/outbox/tester.md):
- `answer_row(answer_id)` -> the `apply_answers` row as a dict (every column, incl. `field_class`,
  `options_json`, `corrected_json`), or None.
- `attempt_field_question(attempt_id, field_key)` -> the attempt's captured `questions` row for that
  field (a dict with `id`, `key`, `label_norm`, `status`), or None. It joins `question_sightings`.
- `mark_answer_corrected(answer_id, value_json, now)` stamps `corrected_json` / `corrected_at` AND
  marks that attempt's `questions` rows for the field `answered` (B.2b "the write ... and marks");
  `value_json` is JSON text. It deletes nothing and does not commit (the caller commits).
- `waiting_on_details()` -> `[{"job_id", "attempt_id", "paths": [profile paths]}]` for jobs whose
  newest attempt stopped waiting on the owner (`owner_fact_missing`) with a path-bearing sighting.
- `add_answers` stores a row's `field_class` key; a row without one reads "" or NULL.

Migrations are built from the same v6 fixture the v7 / v8 pins use (`test_store_always._v6_database`).
Verify: python tests/run_tests.py -k q127_store
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import failed_attempt, make_job, seed_question  # noqa: E402
from test_store_always import TABLES, _cols, _snapshot, _v6_database  # noqa: E402

from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.store import SCHEMA_VERSION, Store, utcnow  # noqa: E402

NOW = "2026-11-15T09:00:00+00:00"


# ---- fixtures: a v6-shaped and a v8-shaped database ------------------------------------------

def _set_shape(path: Path, version: str) -> None:
    """Remove `field_class` (a v9 column) if this build created it, and stamp the version."""
    con = sqlite3.connect(str(path))
    if "field_class" in [r[1] for r in con.execute("PRAGMA table_info(apply_answers)")]:
        con.execute("ALTER TABLE apply_answers DROP COLUMN field_class")
    con.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (version,))
    con.commit()
    con.close()


def _v6(path: Path) -> None:
    _v6_database(path)                 # no `assumed`, no `trial`, version 6
    _set_shape(path, "6")


def _v8(path: Path) -> None:
    _v6_database(path)
    Store(path).close()                # migrate to this build: `assumed` and `trial` exist
    _set_shape(path, "8")


def _raw(path: Path) -> dict:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    out = {}
    for t in TABLES:
        try:
            out[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
        except sqlite3.OperationalError:
            pass
    con.close()
    return out


def _migrates_to_v9(builder, label: str) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        builder(path)
        before = _raw(path)
        con = sqlite3.connect(str(path))
        assert "field_class" not in [r[1] for r in con.execute("PRAGMA table_info(apply_answers)")], label
        con.close()
        assert before["apply_answers"] and before["questions"] and before["applications"] \
            and before["apply_attempts"] and before["apply_queue"] and before["settings"], \
            f"the {label} fixture has data to lose"
        st = Store(path)
        try:
            assert SCHEMA_VERSION == 9
            assert st.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "9"
            assert st.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert "field_class" in _cols(st, "apply_answers")
            now = _snapshot(st)
            for t, rows in before.items():
                assert len(now[t]) == len(rows), (label, t, len(rows), len(now[t]))
                for old, new in zip(rows, now[t]):
                    new = dict(new)
                    for added, want in (("field_class", None), ("assumed", 0), ("trial", 0)):
                        if added not in old and added in new:
                            assert new.pop(added) == want, (label, t, added)
                    assert new == old, (label, t, old, new)
            for r in st.answers(before["apply_answers"][0]["attempt_id"]):
                assert r["field_class"] is None, "an answer written before v9 has no class"
            first = _snapshot(st)
        finally:
            st.close()
        st = Store(path)                                          # a second open changes nothing
        try:
            assert _snapshot(st) == first
            assert _cols(st, "apply_answers").count("field_class") == 1
            assert st.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            st.close()


def test_q127_the_schema_version_is_9():
    assert SCHEMA_VERSION == 9


def test_q127_a_v6_database_migrates_to_v9_in_one_open_with_every_row_intact():
    _migrates_to_v9(_v6, "v6")


def test_q127_a_v8_database_migrates_to_v9_in_one_open_with_every_row_intact():
    _migrates_to_v9(_v8, "v8")


def test_q127_a_newer_database_keeps_its_version_number():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        _v8(path)
        Store(path).close()
        con = sqlite3.connect(str(path))
        con.execute("UPDATE meta SET value = '10' WHERE key = 'schema_version'")   # a newer build's file
        con.commit()
        con.close()
        st = Store(path)
        try:
            assert st.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "10"
        finally:
            st.close()


# ---- the answer's class ---------------------------------------------------------------------

def _row(label: str, key: str, **kw) -> dict:
    from jobscraper.apply.plan import norm_label
    base = {"step": "one", "field_key": key, "label": label, "label_norm": norm_label(label),
            "field_type": "text", "required": True, "tier": 5, "source": "assumption",
            "confidence": 0.5, "status": "filled", "value_json": "Hybrid", "assumed": True,
            "options_json": [{"label": "Hybrid", "value": "h"}, {"label": "Remote", "value": "r"}]}
    base.update(kw)
    return base


def _world(tmp: Path):
    st = Store(tmp / "t.db")
    cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example/careers")
    job = make_job(st, cid, 1)
    aid = failed_attempt(st, job, cid, reason="unanswerable_required")
    return st, cid, job, aid


def test_q127_writing_an_answer_stores_its_class_and_reads_it_back():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))
        try:
            st.add_answers(aid, [
                _row("Preferred work arrangement", "q1", field_class="ordinary"),
                _row("Have you been convicted of an offence", "q2", field_class="declaration:criminal_record",
                     source="declaration", assumed=False),
                _row("Notice period", "q3")])
            st.commit()
            rows = {r["field_key"]: r for r in st.answers(aid)}
            assert rows["q1"]["field_class"] == "ordinary"
            assert rows["q2"]["field_class"] == "declaration:criminal_record"
            assert not rows["q3"]["field_class"]                       # none given: "" or NULL
            assert C.field_class_of(rows["q2"]["field_class"]) is C.FieldClass.DECLARATION
            assert C.follows_your_details(rows["q2"]["source"], rows["q2"]["field_class"])
        finally:
            st.close()


# ---- answer_row (the read for "What was sent") ----------------------------------------------

def test_q127_answer_row_returns_every_column_the_what_was_sent_route_needs_or_none():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))
        try:
            st.add_answers(aid, [_row("Preferred work arrangement", "q1", field_class="ordinary",
                                      note="best guess", section="work")])
            st.commit()
            rid = st.answers(aid)[0]["id"]
            r = st.answer_row(rid)
            assert r["id"] == rid and r["attempt_id"] == aid
            # the keys the route turns into ANSWERS_FIELD_KEYS (value, label, class, source, options ...)
            for col in ("step", "field_key", "label", "label_norm", "field_type", "required", "value_json",
                        "source", "status", "assumed", "note", "options_json", "corrected_json",
                        "corrected_at", "field_class"):
                assert col in r, col
            assert r["field_class"] == "ordinary" and r["source"] == "assumption" and r["assumed"] == 1
            assert [o["label"] for o in json.loads(r["options_json"])] == ["Hybrid", "Remote"]
            assert r["corrected_json"] is None
            assert st.answer_row(999_999) is None
        finally:
            st.close()


# ---- attempt_field_question -----------------------------------------------------------------

def test_q127_attempt_field_question_finds_the_captured_row_of_that_attempt_and_field():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))
        try:
            qid = seed_question(st, attempt_id=aid, job_id=job, company_id=cid, key="work_mode",
                                label="Preferred work arrangement", kind="text", field_key="q1",
                                employer_norm="exampleco")
            q = st.attempt_field_question(aid, "q1")
            assert q["id"] == qid and q["label_norm"] == "preferred work arrangement"
            assert q["key"] == "work_mode" and q["status"] == "open"
            assert st.attempt_field_question(aid, "q2") is None            # another field of the attempt
            assert st.attempt_field_question(aid + 1000, "q1") is None     # another attempt
        finally:
            st.close()


# ---- mark_answer_corrected ------------------------------------------------------------------

def test_q127_remembering_a_label_marks_that_attempts_question_rows_answered_and_deletes_nothing():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))
        try:
            job2 = make_job(st, cid, 2)
            aid2 = failed_attempt(st, job2, cid)
            st.add_answers(aid, [_row("Preferred work arrangement", "q1"), _row("Other thing", "q2")])
            st.add_answers(aid2, [_row("Preferred work arrangement", "q1")])
            q1 = seed_question(st, attempt_id=aid, job_id=job, company_id=cid, key="work_mode",
                               label="Preferred work arrangement", kind="text", field_key="q1",
                               employer_norm="exampleco")
            q2 = seed_question(st, attempt_id=aid, job_id=job, company_id=cid, key="other_thing",
                               label="Other thing", kind="text", field_key="q2", employer_norm="exampleco")
            q3 = seed_question(st, attempt_id=aid2, job_id=job2, company_id=cid, key="work_mode_b",
                               label="Preferred work arrangement b", kind="text", field_key="q1",
                               employer_norm="exampleco")
            st.commit()
            counts = {t: st.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("questions", "question_sightings", "apply_answers", "apply_attempts")}
            target = [r for r in st.answers(aid) if r["field_key"] == "q1"][0]
            st.mark_answer_corrected(target["id"], json.dumps("Remote"), NOW)
            st.commit()

            got = st.answer_row(target["id"])
            assert json.loads(got["corrected_json"]) == "Remote" and got["corrected_at"] == NOW
            assert got["value_json"] == target["value_json"], "the value that was sent is never rewritten"
            status = {r["id"]: r["status"] for r in st.conn.execute("SELECT id, status FROM questions")}
            assert status[q1] == "answered"
            assert status[q2] == "open" and status[q3] == "open", "other fields and attempts are untouched"
            assert counts == {t: st.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts}
            other = [r for r in st.answers(aid) if r["field_key"] == "q2"][0]
            assert other["corrected_json"] is None
        finally:
            st.close()


def test_q127_marking_an_answer_with_no_captured_row_still_stamps_it():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))
        try:
            st.add_answers(aid, [_row("Preferred work arrangement", "q1")])
            st.commit()
            rid = st.answers(aid)[0]["id"]
            st.mark_answer_corrected(rid, json.dumps(["a", "b"]), NOW)
            st.commit()
            assert json.loads(st.answer_row(rid)["corrected_json"]) == ["a", "b"]
        finally:
            st.close()


# ---- waiting_on_details ---------------------------------------------------------------------

def test_q127_waiting_on_details_lists_the_roles_that_stopped_for_a_detail_with_the_paths():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))                 # job 1: stopped on an unanswered question
        try:
            job_dob = make_job(st, cid, 2)
            a_dob = failed_attempt(st, job_dob, cid, reason="owner_fact_missing")
            seed_question(st, attempt_id=a_dob, job_id=job_dob, company_id=cid, key="identity.date_of_birth",
                          target_path="identity.date_of_birth", label="Date of birth", kind="date",
                          reason="profile_gap", sensitive=True, field_key="dob", employer_norm="exampleco")
            seed_question(st, attempt_id=a_dob, job_id=job_dob, company_id=cid, key="education[0].grade",
                          target_path="education[0].grade", label="Final grade", kind="text",
                          reason="profile_gap", field_key="grade", employer_norm="exampleco")
            seed_question(st, attempt_id=aid, job_id=job, company_id=cid, key="work_mode",
                          label="Preferred work arrangement", kind="text", field_key="q1",
                          employer_norm="exampleco")                       # no path: not a detail
            waiting = st.waiting_on_details()
            assert [w["job_id"] for w in waiting] == [job_dob]
            w = waiting[0]
            assert w["attempt_id"] == a_dob
            assert sorted(w["paths"]) == ["education[0].grade", "identity.date_of_birth"]
        finally:
            st.close()


def test_q127_a_later_attempt_that_stopped_for_something_else_is_no_longer_waiting():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st, cid, job, aid = _world(Path(tmp))
        try:
            a1 = failed_attempt(st, job, cid, reason="owner_fact_missing", now="2026-11-15T09:00:00+00:00")
            seed_question(st, attempt_id=a1, job_id=job, company_id=cid, key="identity.date_of_birth",
                          target_path="identity.date_of_birth", label="Date of birth", kind="date",
                          reason="profile_gap", sensitive=True, field_key="dob", employer_norm="exampleco")
            assert [w["job_id"] for w in st.waiting_on_details()] == [job]
            failed_attempt(st, job, cid, reason="validation_error", now="2026-11-15T10:00:00+00:00")
            assert st.waiting_on_details() == []
        finally:
            st.close()


def test_q127_waiting_on_details_is_empty_on_an_empty_database():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "t.db")
        try:
            assert st.waiting_on_details() == []
        finally:
            st.close()
