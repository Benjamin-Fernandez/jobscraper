"""Q-114 / owner decisions D-203 + D-204: the cap rule and the shipped values.

A cap of 0 means "no limit". The owner's values are no daily limit (`daily_cap: 0`) and 10
Submit clicks per employer per day. Pinned three ways:

  A. the orchestrator (`apply_flow.run`, auto mode, fakes only): `cap_refusal` does not refuse
     at daily_cap=0 with 25 clicks today, refuses the tenth click at an employer capped at 10
     ("10 of 10 today at Fake Co", CAP_REACHED), never refuses at per_employer_daily_cap=0;
  B. the web preflight `POST /api/apply` (real app, temp DB, a FAKE job manager so no job
     starts): the same three facts, and a dry run never looks at the caps;
  C. the shipped config/config.yaml and the `ApplyConfig()` defaults.

No browser, no network, no server on a port, no data/. Dummy employers only.
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import add_job, fake_world  # noqa: E402
from apply_support import profile  # noqa: E402
from test_apply_flow import _clicked_today, _one  # noqa: E402

from jobscraper import store as store_mod  # noqa: E402
from jobscraper.apply_flow import day_start_utc  # noqa: E402
from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R  # noqa: E402
from jobscraper.config import ApplyConfig, ROOT, load_config  # noqa: E402

# ------------------------------------------------------------------ A. the orchestrator


def _clicks_at_fakeco(w, cid, n):
    """n Submit clicks today at Fake Co (n distinct other jobs)."""
    for i in range(n):
        _, other = add_job(w.store, external_id=f"c{i}", slug="fakeco", provider="fakeats", key="x",
                           company_id=cid, url=f"https://fake.example.com/jobs/c{i}")
        _clicked_today(w, cid, other)


def test_q114_a_flow_zero_means_no_limit_and_ten_per_employer_refuses_the_tenth():
    # daily_cap 0: 25 clicks today, spread over 25 other employers, still submits
    w, ad, cid, jid = fake_world()
    try:
        for i in range(25):
            ocid, ojob = add_job(w.store, key=f"other{i}", name=f"Other {i}", provider="fakeats",
                                 slug=f"other{i}", external_id=f"o{i}",
                                 url=f"https://fake.example.com/o/{i}")
            _clicked_today(w, ocid, ojob)
        assert w.store.apply_counts(cid, day_start_utc())[0] == 25
        r, factory, _ = _one(w, ad, jid, dry_run=False,
                             apply_over={"daily_cap": 0, "per_employer_daily_cap": 10})
        assert r.reason is not R.CAP_REACHED and r.state is S.SUBMITTED, (r.state, r.reason, r.reason_detail)
    finally:
        w.close()

    # per_employer 10: nine clicks at the employer are fine ...
    w, ad, cid, jid = fake_world()
    try:
        _clicks_at_fakeco(w, cid, 9)
        r, _, _ = _one(w, ad, jid, dry_run=False,
                       apply_over={"daily_cap": 0, "per_employer_daily_cap": 10})
        assert r.state is S.SUBMITTED, (r.state, r.reason, r.reason_detail)
    finally:
        w.close()

    # ... ten already clicked refuses, naming the count, the cap and the employer
    w, ad, cid, jid = fake_world()
    try:
        _clicks_at_fakeco(w, cid, 10)
        r, factory, _ = _one(w, ad, jid, dry_run=False,
                             apply_over={"daily_cap": 0, "per_employer_daily_cap": 10})
        assert r.state is S.FAILED and r.reason is R.CAP_REACHED, (r.state, r.reason)
        assert r.reason_detail == "10 of 10 today at Fake Co", r.reason_detail
        assert factory.started == 0
    finally:
        w.close()

    # per_employer 0 never refuses, however many clicks
    w, ad, cid, jid = fake_world()
    try:
        _clicks_at_fakeco(w, cid, 30)
        r, _, _ = _one(w, ad, jid, dry_run=False,
                       apply_over={"daily_cap": 0, "per_employer_daily_cap": 0})
        assert r.state is S.SUBMITTED, (r.state, r.reason, r.reason_detail)
    finally:
        w.close()


# ------------------------------------------------------------------ B. the web preflight


class _FakeJobs:
    """Records `start`; never runs anything."""

    def __init__(self):
        self.started: list[tuple[str, dict]] = []

    def current(self, tail: int = 200) -> dict:
        from jobscraper.web.jobs import IDLE
        return dict(IDLE, log=[])

    def start(self, kind: str, opts: dict, tail: int = 200) -> dict:
        self.started.append((kind, dict(opts)))
        return {"id": "fake-1", "kind": kind, "state": "running", "log": []}


def _preflight(mode: str, daily_cap: int, per_employer: int, clicks: int, worker: bool = False):
    """Seed `clicks` Submit clicks today at one employer (distinct jobs), then POST /api/apply
    for one more job of that employer. Returns (status_code, json body, fake jobs).

    Q-120 (D-205): POST /api/apply only queues the role. The default app (`worker=False`)
    never starts a job; with `worker=True` the app is built with `apply_queue_worker=True`
    (start-up hook run by the TestClient) and the queue runner starts the worker on the
    fake swapped in after `create_app`."""
    import yaml
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    from questions_support import make_job
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        path.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8", newline="\n")
        (data / "resume.pdf").write_bytes(b"%PDF-1.4 dummy resume for the preflight")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765},
                      "apply": {"mode": mode, "daily_cap": daily_cap,
                                "per_employer_daily_cap": per_employer}})
        st = Store(cfg.db_path)
        cid = st.insert_company("fakeco", "Fake Co", "https://fakeco.example")
        for n in range(clicks):
            job = make_job(st, cid, n)
            aid = st.create_attempt(job, cid, "auto", store_mod.utcnow())
            for s in ("planning", "opening", "filling"):
                st.set_attempt_state(aid, s)
            assert st.mark_submit_clicked(aid, store_mod.utcnow()) is True
            st.set_attempt_state(aid, "submitting")
            st.set_attempt_state(aid, "submitted")
        target = make_job(st, cid, 1000)
        st.commit()
        st.close()
        app = create_app(cfg, apply_queue_worker=worker)
        app.state.apply_queue.tick_s = 3600          # no background tick inside the test
        fake = _FakeJobs()
        app.state.jobs = fake
        with TestClient(app, base_url="http://localhost") as client:
            resp = client.post("/api/apply", json={"job_ids": [target]})
        return resp.status_code, resp.json(), fake


def test_q114_b_preflight_zero_means_no_limit_ten_per_employer_and_dry_run_skips_caps():
    # daily_cap 0, 25 clicks today, employer uncapped (0): accepted and queued; the default
    # app (no worker, Q-120 H1) starts nothing
    code, body, fake = _preflight("auto", daily_cap=0, per_employer=0, clicks=25)
    assert code == 202 and len(body["accepted"]) == 1 and body["refused"] == [], (code, body)
    assert len(body["queued"]) == 1 and body["queued"][0]["position"] == 1, body
    assert fake.started == [] and body["started"] is False
    # the same click on an app with the worker switched on: the queue worker starts
    code, body, fake = _preflight("auto", daily_cap=0, per_employer=0, clicks=25, worker=True)
    assert code == 202 and len(body["queued"]) == 1, (code, body)
    assert fake.started == [("apply", {"queue": True})] and body["started"] is True, body

    # employer at 10 of 10: refused cap_reached, nothing started
    code, body, fake = _preflight("auto", daily_cap=0, per_employer=10, clicks=10)
    assert code == 422 and body["detail"] == "refused", (code, body)
    assert [x["reason_code"] for x in body["refused"]] == ["cap_reached"], body
    assert fake.started == []

    # nine at the employer: still accepted
    code, body, fake = _preflight("auto", daily_cap=0, per_employer=10, clicks=9)
    assert code == 202 and len(body["accepted"]) == 1, (code, body)

    # a dry run never counts clicks: both caps "reached" yet accepted
    code, body, fake = _preflight("dry_run", daily_cap=1, per_employer=1, clicks=3)
    assert code == 202 and body["mode"] == "dry_run" and body["refused"] == [], (code, body)
    assert len(body["queued"]) == 1 and fake.started == []


# ------------------------------------------------------------------ C. the shipped values


def test_q114_c_shipped_config_is_auto_no_daily_limit_ten_per_employer_and_fresh_install_is_safe():
    """owner decisions D-203/D-204: change this pin only when the owner changes them."""
    shipped = load_config(ROOT / "config" / "config.yaml").apply
    assert (shipped.mode, shipped.daily_cap, shipped.per_employer_daily_cap) == ("auto", 0, 10)

    # a fresh install with no `apply:` block never auto-submits (dry run, the old 10 and 2)
    fresh = ApplyConfig()
    assert (fresh.mode, fresh.daily_cap, fresh.per_employer_daily_cap) == ("dry_run", 10, 2)
    assert dataclasses.asdict(ApplyConfig.from_raw(None))["mode"] == "dry_run"
