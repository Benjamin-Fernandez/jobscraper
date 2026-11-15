"""Q-121 Amendment A1, lane W oracles: the flow, store and web side of §17.6 / §17.7 (pin groups
(16), (24) C8, (29), the trial marker, `attempt_question_paths`, the schema migration, `doctor`'s
"Profile shape" block). Same seams as tests/test_always_flow*.py (tests/always_flow_support.py: a mock
model, a fake navigator that only counts Submit, a temp DB, employer "Example Co") and
tests/test_q76_attempts.py. Nothing here can start a real application.
Verify: python tests/run_tests.py -k always_a1_w
"""
from __future__ import annotations

import contextlib
import io
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import Net, backend, make, nav_class, page, run_batch, run_q  # noqa: E402
from questions_support import failed_attempt, make_job, seed_question  # noqa: E402

from jobscraper import apply_flow, cli  # noqa: E402
from jobscraper.apply import always as AL  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    CONSENT_REFUSED_DETAILS, CONTENT_FAILURE_MARKERS, CONTENT_FAILURE_TEXT, REASON_TEXTS, AttemptState as ST,
    QueuePause, ReasonCode as R)
from jobscraper.store import Store, utcnow  # noqa: E402
from jobscraper.web.routers.applications import attempt_view  # noqa: E402

ALWAYS = {"fill_policy": "always"}
CONSENT = dict(step="one", field_key="c", label="I consent to the processing of my personal data",
               target_path="consents.privacy_consent", sensitive=False)
T0, T1 = "2026-11-01T01:00:00", "2026-11-02T01:00:00"


def _row(**kw) -> dict:
    base = {"id": 1, "job_id": "a1b2c3", "mode": "dry_run", "state": "failed", "reason_code": None,
            "reason_detail": None, "queued_at": T0, "finished_at": T1, "submit_clicked_at": None, "resume_source": None}
    base.update(kw)
    return base


def _queue_state(w):
    st = w.store.queue_pause_state()
    return (st or {}).get("reason"), (st or {}).get("detail"), list(w.store.queue_positions())


# ================================================================== (16) attempt_view

def test_a1_16_a_content_failure_detail_reads_as_stopped_with_the_content_failure_text_never_needs_input():
    bad = []
    for marker in CONTENT_FAILURE_MARKERS:
        v = attempt_view(_row(reason_code="unanswerable_required", reason_detail=f"{marker}: too many on one"))
        if (v["kind"] != "stopped" or v["text"] != CONTENT_FAILURE_TEXT.text or v["hint"] != CONTENT_FAILURE_TEXT.hint
                or "Needs your answers" in repr(v)):
            bad.append((marker, v["kind"], v["text"]))
    assert not bad, ascii(bad)
    v = attempt_view(_row(reason_code="unanswerable_required", reason_detail="Why us?"))
    assert v["kind"] == "needs_input" and "Why us?" in v["text"], ascii(v)          # a real question still waits for the owner


def test_a1_16_consent_refused_is_needs_input_with_the_designed_text():
    bad = []
    for key, detail in CONSENT_REFUSED_DETAILS.items():
        v = attempt_view(_row(reason_code="consent_refused", reason_detail=detail))
        want = REASON_TEXTS[R.CONSENT_REFUSED]
        if v["kind"] != "needs_input" or v["text"] != want.text.format(detail=detail) or v["hint"] != want.hint:
            bad.append((key, v["kind"], v["text"]))
    assert not bad, ascii(bad)
    assert "agree to the processing of your personal data" in attempt_view(
        _row(reason_code="consent_refused", reason_detail=CONSENT_REFUSED_DETAILS["consents.privacy_consent"]))["text"]


# ================================================================== (24) C8: the streak rule

def _streak(*details):
    return [{"state": "failed", "reason_code": "consent_refused", "reason_detail": d} for d in details]


def test_a1_c8_three_consent_refused_endings_with_different_details_do_not_pause():
    rows = _streak(CONSENT_REFUSED_DETAILS["consents.privacy_consent"], CONSENT_REFUSED_DETAILS["consents.talent_pool_opt_in"],
                   CONSENT_REFUSED_DETAILS["consents.privacy_consent"])
    assert apply_flow.pause_for(rows[0], "", rows) is None, "different details: the queue goes on, no generic 'consent refused' pause"
    mixed = _streak("a", "b", "c")
    assert apply_flow.pause_for(mixed[0], "", mixed) is None


def test_a1_c8_the_same_consent_refused_detail_three_times_pauses_repeated_failures_naming_it():
    d = CONSENT_REFUSED_DETAILS["consents.data_retention_consent"]
    rows = _streak(d, d, d)
    assert apply_flow.pause_for(rows[0], "", rows) == (QueuePause.REPEATED_FAILURES, f"{d} is refused in your profile")
    assert apply_flow.pause_for(rows[0], "", rows[:2] + [{"state": "failed", "reason_code": "model_unavailable", "reason_detail": ""}]) is None


def test_a1_c8_consent_refused_is_per_role_and_a_retry_candidate_once_a_question_is_captured():
    w, cid, jobs = make(2)
    try:
        def script(nav, services, ctx, rctx):
            if ctx.job["job_id"] == jobs[0]:
                raise AL.AlwaysStop(R.CONSENT_REFUSED, CONSENT_REFUSED_DETAILS["consents.privacy_consent"], **CONSENT)
            return page()
        run_q(w, cid, jobs, nav_class()(), backend(Net()), script, **ALWAYS)
        rows = {r["job_id"]: r for r in w.attempt_rows()}
        assert rows[jobs[0]]["state"] == "failed" and rows[jobs[0]]["reason_code"] == "consent_refused", rows[jobs[0]]
        assert CONSENT_REFUSED_DETAILS["consents.privacy_consent"] in rows[jobs[0]]["reason_detail"]
        assert rows[jobs[1]]["state"] == "ready_to_submit", "the next queued role ran: consent_refused is per role"
        pause, _detail, waiting = _queue_state(w)
        assert pause is None and not waiting, "no pause; the failed role is NOT returned to the queue"
    finally:
        w.close()


# ================================================================== (29) the capture targets consents.<key>

def test_a1_29_the_consent_refused_capture_targets_the_consent_key():
    w, cid, jobs = make(1)
    try:
        run_q(w, cid, jobs, nav_class()(), backend(Net()),
              S.stop_with(R.CONSENT_REFUSED, CONSENT_REFUSED_DETAILS["consents.privacy_consent"], **CONSENT), **ALWAYS)
        groups = w.store.question_groups("open")
        assert len(groups) == 1, groups
        assert groups[0]["target_path"] == "consents.privacy_consent", groups[0]
        assert any(c["job_id"] == jobs[0] for c in w.store.retry_candidates()), "after the owner changes it, Try again is offered"
    finally:
        w.close()


def test_a1_29_a_combined_box_names_its_refused_part_in_the_capture():
    w, cid, jobs = make(1)
    try:
        kw = dict(CONSENT, target_path="consents.talent_pool_opt_in", label="I agree to the Privacy Policy and to receive marketing communications")
        run_q(w, cid, jobs, nav_class()(), backend(Net()),
              S.stop_with(R.CONSENT_REFUSED, CONSENT_REFUSED_DETAILS["consents.talent_pool_opt_in"], **kw), **ALWAYS)
        assert [g["target_path"] for g in w.store.question_groups("open")] == ["consents.talent_pool_opt_in"]
        row = w.attempt_rows()[0]
        assert "receiving marketing messages" in row["reason_detail"], row["reason_detail"]
    finally:
        w.close()


def test_a1_retry_candidates_include_a_consent_refused_attempt_with_an_open_question():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "t.db")
        try:
            cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
            j = make_job(st, cid, 1)
            a = failed_attempt(st, j, cid, reason="consent_refused")
            seed_question(st, attempt_id=a, job_id=j, company_id=cid, key="privacy", label="I consent to the processing of my personal data",
                          kind="yes_no", target_path="consents.privacy_consent", employer_norm="exampleco")
            assert [c["job_id"] for c in st.retry_candidates()] == [j]
        finally:
            st.close()


# ================================================================== the content failure is not a "Needs your answers" in the flow

def test_a1_a_content_failure_ends_unanswerable_required_with_a_marker_detail_and_is_not_returned():
    w, cid, jobs = make(1)
    try:
        run_q(w, cid, jobs, nav_class()(), backend(Net()),
              S.stop_with(R.UNANSWERABLE_REQUIRED, AL.content_failure_detail(CONTENT_FAILURE_MARKERS[1], "too many on one")), **ALWAYS)
        row = w.attempt_rows()[0]
        assert row["reason_code"] == "unanswerable_required" and row["reason_detail"].lower().startswith(CONTENT_FAILURE_MARKERS), row
        v = attempt_view(row)
        assert v["kind"] == "stopped" and v["text"] == CONTENT_FAILURE_TEXT.text, ascii(v)
    finally:
        w.close()


def test_a1_is_content_failure_reads_the_contract_markers_and_only_them():
    """Review F10: the markers live in contracts; the queue worker's `is_content_failure` follows them."""
    def row(detail):
        return {"state": "failed", "reason_code": "unanswerable_required", "reason_detail": detail}
    for m in CONTENT_FAILURE_MARKERS:
        assert apply_flow.is_content_failure(row(f"{m}: on one")), m
        assert apply_flow.is_content_failure(row(f"  {m.upper()}: on one")), m
    assert not apply_flow.is_content_failure(row("Why us?"))
    assert not apply_flow.is_content_failure(row("the answer had no usable answers in it"))      # starts-with, not contains


# ================================================================== the trial marker and the owner-fact path

def test_a1_trial_attempts_carry_trial_true_and_the_api_text_the_others_do_not():
    w, _cid, jobs = make(3)
    try:
        nav = nav_class()()
        run_batch(w, jobs, nav, backend(Net()), dry_run=False, always_trial_runs=2, **ALWAYS)
        rows = w.attempt_rows()
        assert [bool(r.get("trial")) for r in rows] == [True, True, False], [r.get("trial") for r in rows]
        views = [attempt_view(r) for r in rows]
        assert [v["trial"] for v in views] == [True, True, False]
        assert views[0]["trial_text"] == "Trial: filled, not sent" and views[2]["trial_text"] == ""
        for j, r in zip(jobs, rows):
            assert bool(w.store.attempts_for_job(j)[0].get("trial")) == bool(r.get("trial"))
    finally:
        w.close()


def test_a1_a_non_trial_dry_run_and_strict_attempts_are_not_marked_trial():
    w, _cid, jobs = make(2)
    try:
        run_batch(w, jobs[:1], nav_class()(), backend(Net()), dry_run=True, always_trial_runs=2, **ALWAYS)
        run_batch(w, jobs[1:], nav_class()(), backend(Net()), dry_run=False, fill_policy="strict", always_trial_runs=2)
        assert [bool(r.get("trial")) for r in w.attempt_rows()] == [False, False]
    finally:
        w.close()


def test_a1_store_attempt_question_paths_maps_each_attempt_to_the_target_path_of_its_question():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "t.db")
        try:
            cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
            j1, j2, j3 = (make_job(st, cid, n) for n in (1, 2, 3))
            a1 = failed_attempt(st, j1, cid, reason="owner_fact_missing")
            a2 = failed_attempt(st, j2, cid, reason="owner_fact_missing")
            a3 = failed_attempt(st, j3, cid, reason="owner_fact_missing")
            seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, key="dob", label="Date of Birth", kind="date",
                          target_path="identity.date_of_birth", employer_norm="exampleco", field_key="q1")
            seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, key="colour", label="Favourite colour", kind="text",
                          target_path="", employer_norm="exampleco", field_key="q2")
            seed_question(st, attempt_id=a2, job_id=j2, company_id=cid, key="colour2", label="Another colour", kind="text",
                          target_path="", employer_norm="exampleco", field_key="q3")
            got = st.attempt_question_paths([a1, a2, a3, 987654])
            assert got == {a1: "identity.date_of_birth"}, got
            assert st.attempt_question_paths([]) == {}
        finally:
            st.close()


def test_a1_the_attempts_api_carries_owner_fact_path_from_the_questions_target():
    from test_q76_attempts import _fail
    from test_web import _world
    with _world() as (client, open_store):
        st = open_store()
        a1 = _fail(st, "a1b2c3", "owner_fact_missing", T0, detail="date of birth (“Date of Birth” on one)")
        seed_question(st, attempt_id=a1, job_id="a1b2c3", key="dob", label="Date of Birth", kind="date",
                      target_path="identity.date_of_birth", sensitive=True, employer_norm="exampleco", field_key="q1")
        a2 = _fail(st, "a1b2c3", "captcha", T1, detail="x")
        st.close()
        body = client.get("/api/applications/a1b2c3/attempts").json()
    by_id = {b["id"]: b for b in body}
    assert by_id[a1]["owner_fact_path"] == "identity.date_of_birth", by_id[a1]
    assert by_id[a2]["owner_fact_path"] is None


# ================================================================== schema v8

def _v7_database(path: Path) -> None:
    """A v7 file with rows in every table: built from a current file with the v8 column removed."""
    from test_store_always import _v6_database
    _v6_database(path)
    Store(path).close()                                   # migrate to the current build
    con = sqlite3.connect(str(path))
    cols = [r[1] for r in con.execute("PRAGMA table_info(apply_attempts)")]
    if "trial" in cols:
        con.execute("ALTER TABLE apply_attempts DROP COLUMN trial")
    con.execute("UPDATE meta SET value = '7' WHERE key = 'schema_version'")
    con.commit()
    con.close()


def test_a1_schema_version_is_at_least_8():
    from jobscraper.store import SCHEMA_VERSION
    assert SCHEMA_VERSION >= 8


def test_a1_a_v7_database_opens_as_v8_with_every_row_intact_and_old_attempts_not_trial():
    from test_store_always import TABLES, _cols, _snapshot
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        _v7_database(path)
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
        assert "trial" not in [r["name"] for r in con.execute("PRAGMA table_info(apply_attempts)")]
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "7"
        v7 = {}
        for t in TABLES:
            try:
                v7[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
            except sqlite3.OperationalError:
                pass
        con.close()
        assert v7["apply_attempts"] and v7["apply_answers"] and v7["questions"] and v7["settings"], "the v7 file has data to lose"
        st = Store(path)
        try:
            assert st.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(__import__("jobscraper.store", fromlist=["SCHEMA_VERSION"]).SCHEMA_VERSION)
            assert "trial" in _cols(st, "apply_attempts")
            now = _snapshot(st)
            for t, rows in v7.items():
                assert len(now[t]) == len(rows), (t, len(rows), len(now[t]))
                for before, after in zip(rows, now[t]):
                    if t == "apply_attempts":
                        assert after.pop("trial") == 0, "an attempt from before v8 reads as not a trial"
                    assert after == before, (t, before, after)
            first = _snapshot(st)
        finally:
            st.close()
        st = Store(path)
        try:
            assert _snapshot(st) == first and _cols(st, "apply_attempts").count("trial") == 1, "a second open changes nothing"
        finally:
            st.close()


# ================================================================== doctor: the Profile shape block

def _doctor(profile):
    from apply_flow_support import make_world
    w = make_world(apply_block={"fill_policy": "always"}, profile=profile)
    (w.tmp / "watchlist.yaml").write_text(
        "version: 1\ncompanies:\n  - name: Acme\n    careers_url: https://acme.example/careers\n"
        "    provider: greenhouse\n    slug: acme\n", encoding="utf-8")
    out = io.StringIO()
    real = cli.backends.build
    cli.backends.build = lambda _b: backend(Net())
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--config", str(w.cfg_path), "doctor"])
    finally:
        cli.backends.build = real
        w.close()
    return out.getvalue()


def _a(x) -> str:
    return str(x).encode("ascii", "backslashreplace").decode("ascii")


def _line(out: str, *needles: str) -> str:
    for ln in out.splitlines():
        low = ln.lower()
        if any(n in low for n in needles):
            return low
    return ""


def test_a1_doctor_prints_a_booleans_only_profile_shape_block_and_no_value():
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["identity"]["date_of_birth"] = "2001-07-09"
    p["identity"]["gender"] = "zorbgender"
    p["contact"]["address_line1"] = "77 Zephyr Lane"
    p["contact"]["postal_code"] = "654321"
    p["contact"]["phone_number"] = "98761234"
    p["education"][0]["grade"] = "3.91"
    p["singapore_status"]["nationality"] = "SG"
    out = _doctor(p)
    assert "profile shape" in out.lower(), _a(out)
    for planted in ("2001-07-09", "09/07/2001", "07/09/2001", "77 Zephyr", "Zephyr", "654321", "98761234", "3.91", "zorbgender"):
        assert planted.lower() not in out.lower(), f"doctor printed a profile value: {planted}"
    shape = out.lower().split("profile shape", 1)[1]
    for key in ("privacy_consent", "data_retention_consent", "talent_pool_opt_in", "certify_true",
                "pep", "criminal_record", "bankruptcy", "relatives_at_company", "non_compete", "government_employment"):
        assert key in shape, f"the Profile shape block should list {key}"
    assert "true" in _line(shape, "privacy_consent") and "false" in _line(shape, "talent_pool_opt_in")
    assert "false" in _line(shape, "criminal_record")


def test_a1_doctor_says_not_set_for_what_the_profile_lacks():
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["identity"]["date_of_birth"] = None
    p["contact"]["address_line1"] = ""
    p["contact"]["postal_code"] = ""
    p["education"][0]["grade"] = ""
    p["consents"].pop("talent_pool_opt_in", None)
    out = _doctor(p)
    assert "profile shape" in out.lower(), _a(out)
    shape = out.lower().split("profile shape", 1)[1]
    for needles in (("date_of_birth", "date of birth"), ("address_line1", "address"), ("postal_code", "postal"),
                    ("grade",), ("talent_pool_opt_in",)):
        assert "not set" in _line(shape, *needles), _a((needles, shape))
