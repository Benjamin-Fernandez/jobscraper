"""Q-76 (N11, N12): the Applications list carries each job's newest auto-apply
attempt, and an attempts route lists them all.

D1 Store.last_attempts: newest attempt per job, with a count; absent when none.
D2 attempt_view: the SPA's view of one attempt row (kind, copy, no paths/URLs).
D3 GET /api/applications: last_attempt / attempts / posting on every row, and
   one last_attempts() call per request, never one per row.
D4 GET /api/applications/{job_id}/attempts: newest first, [] for none, 422 for a
   bad id.

Designed in docs/architecture/q76_application_detail.md.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jobscraper.apply.contracts import (REASON_TEXTS, STATE_TEXTS, AttemptState,  # noqa: E402
                                        ReasonCode)
from jobscraper.store import Store  # noqa: E402
from jobscraper.web.routers.applications import attempt_view  # noqa: E402

from test_web import _world  # noqa: E402

T0 = "2026-11-01T01:00:00"
T1 = "2026-11-02T01:00:00"
T2 = "2026-11-03T01:00:00"


def _store() -> tuple[Store, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    return Store(Path(tmp.name) / "q76.db"), tmp


def _fail(st: Store, job_id: str, reason: str, now: str, *, mode: str = "dry_run",
          detail: str | None = None) -> int:
    aid = st.create_attempt(job_id, None, mode, now)
    st.set_attempt_state(aid, "planning")
    st.set_attempt_state(aid, "failed", reason=reason, detail=detail)
    st.commit()
    return aid


def _row(**kw) -> dict:
    base = {"id": 1, "job_id": "a1b2c3", "mode": "dry_run", "state": "queued", "reason_code": None,
            "reason_detail": None, "queued_at": T0, "finished_at": None, "submit_clicked_at": None,
            "resume_source": None}
    base.update(kw)
    return base


# ---------------------------------------------------------------- D1

def test_q76_d1_last_attempts_is_the_newest_per_job_with_a_count():
    st, tmp = _store()
    try:
        first = _fail(st, "job1", "captcha", T0)
        newest = _fail(st, "job1", "unanswerable_required", T2, detail="Why us?")
        _fail(st, "job2", "cancelled", T1)
        latest = st.last_attempts()
        assert set(latest) == {"job1", "job2"}, "a job with no attempt is absent"
        assert latest["job1"]["id"] == newest and latest["job1"]["id"] > first
        assert latest["job1"]["reason_code"] == "unanswerable_required"
        assert latest["job1"]["attempts"] == 2
        assert latest["job2"]["attempts"] == 1
    finally:
        st.close()
        tmp.cleanup()


def test_q76_d1_last_attempts_follows_the_id_not_the_clock():
    """Newest = the highest id (how attempts_for_job orders), whatever queued_at says."""
    st, tmp = _store()
    try:
        _fail(st, "job1", "captcha", T2)
        later = _fail(st, "job1", "error", T0)       # queued stamp is older, id is higher
        assert st.last_attempts()["job1"]["id"] == later
    finally:
        st.close()
        tmp.cleanup()


def test_q76_d1_no_attempts_is_an_empty_map():
    st, tmp = _store()
    try:
        assert st.last_attempts() == {}
    finally:
        st.close()
        tmp.cleanup()


# ---------------------------------------------------------------- D2

def test_q76_d2_each_kind():
    def kind(**kw):
        return attempt_view(_row(**kw))["kind"]

    assert kind(state="queued") == "running"
    for s in ("tailoring", "planning", "opening", "signing_in", "signing_up", "filling",
              "verifying_email", "submitting"):
        assert kind(state=s) == "running", s
    assert kind(state="submitted") == "sent"
    assert kind(state="submitted_unconfirmed") == "unconfirmed"
    assert kind(state="ready_to_submit") == "dry_run"
    assert kind(state="failed", reason_code="unanswerable_required", reason_detail="x") == "needs_input"
    assert kind(state="failed", reason_code="profile_incomplete", reason_detail="x") == "needs_input"
    assert kind(state="failed", reason_code="cancelled") == "cancelled"
    for code in ("captcha", "bot_challenge", "login_failed", "posting_closed", "unsupported_ats", "error"):
        assert kind(state="failed", reason_code=code, reason_detail="x") == "stopped", code


def test_q76_d2_every_reason_code_has_a_kind_text_and_hint():
    for code in ReasonCode:
        v = attempt_view(_row(state="failed", reason_code=code.value, reason_detail="the detail"))
        assert v["kind"] in {"needs_input", "cancelled", "stopped"}, code
        assert v["text"] and "{detail}" not in v["text"], code
        assert v["hint"] == REASON_TEXTS[code].hint


def test_q76_d2_detail_is_formatted_into_the_text():
    v = attempt_view(_row(state="failed", reason_code="unanswerable_required", reason_detail="Why us?"))
    assert "Why us?" in v["text"]
    v = attempt_view(_row(state="failed", reason_code="unanswerable_required", reason_detail=None))
    assert "{detail}" not in v["text"], "a missing detail leaves no placeholder"


def test_q76_d2_state_copy_for_unconfirmed_and_dry_run():
    v = attempt_view(_row(state="submitted_unconfirmed"))
    assert (v["text"], v["hint"]) == (STATE_TEXTS[AttemptState.SUBMITTED_UNCONFIRMED].text,
                                      STATE_TEXTS[AttemptState.SUBMITTED_UNCONFIRMED].hint)
    v = attempt_view(_row(state="ready_to_submit"))
    assert v["text"] == STATE_TEXTS[AttemptState.READY_TO_SUBMIT].text
    assert attempt_view(_row(state="submitted"))["text"] == ""


def test_q76_d2_an_unknown_reason_or_state_never_raises():
    v = attempt_view(_row(state="failed", reason_code="from_a_future_version", reason_detail="x"))
    assert v["kind"] == "stopped" and v["text"] == "" and v["reason_code"] == "from_a_future_version"
    v = attempt_view(_row(state="failed", reason_code=None))
    assert v["kind"] == "stopped"
    v = attempt_view(_row(state="a_state_from_the_future"))
    assert v["kind"] == "stopped"
    v = attempt_view(_row(state=None))
    assert v["kind"] == "stopped"


def test_q76_d2_leaks_no_path_or_url():
    """job_log, end_url, tenant_host and resume_sha256 stay on the server."""
    row = _row(state="failed", reason_code="captcha", reason_detail="x", job_log="C:/secret/log.txt",
               end_url="https://acme.wd3.example/apply/9", tenant_host="acme.wd3.example",
               resume_sha256="ab" * 32, resume_file="C:/Users/me/resume.pdf", confirmation="CONF-1")
    v = attempt_view(row)
    assert set(v) == {"id", "mode", "state", "kind", "reason_code", "text", "hint",
                      "queued_at", "finished_at", "submit_clicked_at", "resume_source"}
    blob = repr(v)
    for secret in ("secret", "acme.wd3", "resume.pdf", "CONF-1", "ab" * 8):
        assert secret not in blob, secret


# ---------------------------------------------------------------- D3

def test_q76_d3_applications_rows_carry_the_newest_attempt_and_the_posting():
    with _world() as (client, open_store):
        st = open_store()
        st.set_application_status("a1b2c3", "applied")                     # on the fixture shortlist
        st.set_application_status("gone1", "applied", company="Old Co", role="Eng",
                                  url="https://example.org/x")             # off it
        st.set_application_status("plain", "applied", company="Plain Co", role="Eng",
                                  url="https://example.org/p")             # no attempt
        _fail(st, "a1b2c3", "captcha", T0)
        _fail(st, "a1b2c3", "unanswerable_required", T1, detail="Why us?")
        _fail(st, "gone1", "posting_closed", T0, detail="x")
        st.close()
        rows = {r["job_id"]: r for r in client.get("/api/applications").json()}
    okx = rows["a1b2c3"]
    assert okx["attempts"] == 2
    assert okx["last_attempt"]["kind"] == "needs_input"
    assert "Why us?" in okx["last_attempt"]["text"]
    assert okx["posting"] is not None
    assert {"reason", "matched_skills", "yoe_min", "decided_at", "closed"} <= set(okx["posting"])
    assert rows["gone1"]["posting"] is None, "off the shortlist: no posting facts"
    assert rows["gone1"]["last_attempt"]["kind"] == "stopped"
    assert rows["plain"]["last_attempt"] is None and rows["plain"]["attempts"] == 0
    assert rows["plain"]["posting"] is None


def test_q76_d3_one_last_attempts_call_per_request_not_one_per_row():
    calls = []
    real = Store.last_attempts

    def spy(self):
        calls.append(1)
        return real(self)

    with _world() as (client, open_store):
        st = open_store()
        for job_id in ("a1b2c3", "d4e5f6", "g7h8i9", "j0k1l2", "m3n4o5"):
            st.set_application_status(job_id, "applied", company="Co", role="R", url="https://example.org/x")
            _fail(st, job_id, "captcha", T0)
        st.close()
        Store.last_attempts = spy
        try:
            rows = client.get("/api/applications").json()
        finally:
            Store.last_attempts = real
    assert len(rows) == 5
    assert len(calls) == 1, f"{len(calls)} last_attempts calls for {len(rows)} rows"


def test_q76_d3_an_empty_list_still_works():
    with _world() as (client, _):
        assert client.get("/api/applications").json() == []


# ---------------------------------------------------------------- D4

def test_q76_d4_attempts_route_lists_newest_first():
    with _world() as (client, open_store):
        st = open_store()
        first = _fail(st, "a1b2c3", "captcha", T0)
        second = _fail(st, "a1b2c3", "cancelled", T1, mode="auto")
        _fail(st, "d4e5f6", "error", T2, detail="x")
        st.close()
        r = client.get("/api/applications/a1b2c3/attempts")
    assert r.status_code == 200
    body = r.json()
    assert [a["id"] for a in body] == [second, first]
    assert [a["kind"] for a in body] == ["cancelled", "stopped"]
    assert [a["mode"] for a in body] == ["auto", "dry_run"]
    assert "job_log" not in body[0] and "end_url" not in body[0]


def test_q76_d4_no_attempts_is_an_empty_list_not_a_404():
    with _world() as (client, _):
        r = client.get("/api/applications/a1b2c3/attempts")
        assert r.status_code == 200 and r.json() == []
        r = client.get("/api/applications/neverheardof/attempts")
        assert r.status_code == 200 and r.json() == []


def test_q76_d4_a_malformed_job_id_is_refused():
    with _world() as (client, _):
        for bad in ("a%20b", "..%2Fx", "x" * 200, "a;b"):
            r = client.get(f"/api/applications/{bad}/attempts")
            assert r.status_code in (404, 422), (bad, r.status_code)
        assert client.get("/api/applications/a b/attempts").status_code == 422
