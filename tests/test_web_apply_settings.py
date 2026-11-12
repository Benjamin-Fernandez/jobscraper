"""Q-111: pins for GET/PUT /api/apply/settings (apply_design section 14.3).

These endpoints switch auto-apply between real submission ("auto") and "dry_run" and set the
daily caps, so the pins are exact:

  1. GET shape: the six keys, writable, `defaults` = config alone; a PUT moves the top level
     but never `defaults`;
  2. the safety pin: PUT mode dry_run is seen by /api/apply/status, by
     `cfg.apply.with_settings(store.get_setting)` and by the POST preflight (a dry run is not
     refused by reached caps; it never clicks); PUT auto flips all three back;
  3. validation is all-or-nothing (422 {detail: "invalid", errors}), boundaries exact;
  4. booleans round-trip through the settings table; compose_enabled reaches `compose.enabled`;
  5. the caps a PUT stores are the caps the POST preflight enforces.

Real app, temp DB, a FAKE job manager (no job, no browser, no network, no port, no data/).
Dummy employer only.
"""
from __future__ import annotations

import contextlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import profile  # noqa: E402
from questions_support import make_job  # noqa: E402

from jobscraper import store as store_mod  # noqa: E402

SIX = {"mode", "daily_cap", "per_employer_daily_cap", "headed", "captcha_wait_s", "compose_enabled"}


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


@contextlib.contextmanager
def _world(*, mode="auto", daily_cap=0, per_employer=10, clicks=0, headed=True,
           captcha_wait_s=0, compose=False):
    """Yield (client, cfg, target_job_id, fake_jobs): a real app on a temp DB with a complete
    dummy profile, `clicks` Submit clicks today at one employer, and one more job of it."""
    import yaml
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        path.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8", newline="\n")
        (data / "resume.pdf").write_bytes(b"%PDF-1.4 dummy resume for the settings pins")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765},
                      "apply": {"mode": mode, "daily_cap": daily_cap,
                                "per_employer_daily_cap": per_employer, "headed": headed,
                                "captcha_wait_s": captcha_wait_s, "compose": {"enabled": compose}}})
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
        app = create_app(cfg)
        fake = _FakeJobs()
        app.state.jobs = fake
        with TestClient(app, base_url="http://localhost") as client:
            yield client, cfg, target, fake


def _effective(cfg):
    """`cfg.apply` with the settings table applied, read through a fresh store."""
    from jobscraper.store import Store
    st = Store(cfg.db_path)
    try:
        return cfg.apply.with_settings(st.get_setting)
    finally:
        st.close()


def _post(client, target):
    resp = client.post("/api/apply", json={"job_ids": [target]})
    return resp.status_code, resp.json()


# ------------------------------------------------------------------ 1. GET shape


def test_apply_settings_get_returns_six_keys_and_a_put_moves_values_not_defaults():
    with _world(mode="dry_run", daily_cap=7, per_employer=3, headed=False, captcha_wait_s=30,
                compose=False) as (client, cfg, _t, fake):
        cfg_values = {"mode": "dry_run", "daily_cap": 7, "per_employer_daily_cap": 3,
                      "headed": False, "captcha_wait_s": 30, "compose_enabled": False}
        resp = client.get("/api/apply/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == SIX | {"writable", "defaults"}, sorted(body)
        assert body["writable"] is True
        assert {k: body[k] for k in SIX} == cfg_values
        assert body["defaults"] == cfg_values

        resp = client.put("/api/apply/settings", json={
            "mode": "auto", "daily_cap": 12, "per_employer_daily_cap": 4, "headed": True,
            "captcha_wait_s": 90, "compose_enabled": True})
        assert resp.status_code == 200, resp.text
        moved = {"mode": "auto", "daily_cap": 12, "per_employer_daily_cap": 4,
                 "headed": True, "captcha_wait_s": 90, "compose_enabled": True}
        assert {k: resp.json()[k] for k in SIX} == moved       # the PUT answers with the new view
        again = client.get("/api/apply/settings").json()
        assert {k: again[k] for k in SIX} == moved
        assert again["defaults"] == cfg_values                  # config.yaml alone, untouched
        assert again["writable"] is True
        assert fake.started == []                               # saving a setting starts nothing


# ------------------------------------------------------------------ 2. the safety pin


def test_apply_settings_mode_switch_is_seen_by_status_effective_config_and_preflight():
    # auto, both caps already reached (3 clicks today at one employer, caps of 1)
    with _world(mode="auto", daily_cap=1, per_employer=1, clicks=3) as (client, cfg, target, fake):
        assert client.get("/api/apply/status").json()["mode"] == "auto"
        code, body = _post(client, target)
        assert code == 422 and [x["reason_code"] for x in body["refused"]] == ["cap_reached"], (code, body)
        assert fake.started == []

        # switch to dry_run
        resp = client.put("/api/apply/settings", json={"mode": "dry_run"})
        assert resp.status_code == 200 and resp.json()["mode"] == "dry_run", resp.text
        assert client.get("/api/apply/status").json()["mode"] == "dry_run"
        assert _effective(cfg).mode == "dry_run"
        assert cfg.apply.mode == "auto"                         # config.yaml itself is not rewritten
        # a dry run never clicks, so reached caps do not refuse it
        code, body = _post(client, target)
        assert code == 202 and body["mode"] == "dry_run" and body["refused"] == [], (code, body)
        assert body["accepted"] == [target]
        # Q-120 (D-205): the click queues the role with the effective mode; the default app
        # (no worker, H1) starts nothing
        assert body["queued"] == [{"job_id": target, "position": 1}], body
        assert [w["mode"] for w in client.get("/api/apply/queue").json()["waiting"]] == ["dry_run"]
        assert fake.started == []
        # take it out again so the next click meets the caps, not `already_queued`
        assert client.delete(f"/api/apply/queue/{target}").status_code == 204

        # and back to auto: all three views flip back, the caps bite again
        resp = client.put("/api/apply/settings", json={"mode": "auto"})
        assert resp.status_code == 200 and resp.json()["mode"] == "auto", resp.text
        assert client.get("/api/apply/status").json()["mode"] == "auto"
        assert _effective(cfg).mode == "auto"
        code, body = _post(client, target)
        assert code == 422 and [x["reason_code"] for x in body["refused"]] == ["cap_reached"], (code, body)
        assert fake.started == []                               # nothing ever started
        assert client.get("/api/apply/queue").json()["waiting"] == []   # and nothing queued


# ------------------------------------------------------------------ 3. validation


def test_apply_settings_validation_is_all_or_nothing_with_exact_boundaries():
    with _world(mode="auto", daily_cap=3, per_employer=2, captcha_wait_s=5) as (client, cfg, _t, fake):
        before = client.get("/api/apply/settings").json()

        # one bad value refuses the whole body: the good daily_cap is not written
        resp = client.put("/api/apply/settings", json={"daily_cap": 5, "per_employer_daily_cap": 101})
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"] == "invalid"
        assert [e["field"] for e in body["errors"]] == ["per_employer_daily_cap"], body
        assert all(e["message"] for e in body["errors"])
        assert client.get("/api/apply/settings").json() == before          # daily_cap still 3
        assert _effective(cfg).daily_cap == 3

        # every refused value, each alone; nothing changes
        bad = [{"daily_cap": 501}, {"daily_cap": -1}, {"per_employer_daily_cap": 101},
               {"per_employer_daily_cap": -1}, {"captcha_wait_s": 601}, {"captcha_wait_s": -1},
               {"daily_cap": "5"}, {"daily_cap": True}, {"per_employer_daily_cap": False},
               {"captcha_wait_s": True}, {"daily_cap": 5.5}, {"daily_cap": None},
               {"mode": "yolo"}, {"mode": "AUTO"}, {"mode": True},
               {"headed": "true"}, {"headed": 1}, {"compose_enabled": "yes"}, {"compose_enabled": 0},
               {"nonsense": 1}, {"daily_cap": 5, "nonsense": 1},
               {}]
        for payload in bad:
            resp = client.put("/api/apply/settings", json=payload)
            assert resp.status_code == 422, (payload, resp.status_code, resp.text)
            assert resp.json()["detail"] == "invalid" and resp.json()["errors"], payload
        for payload in ([], "mode", 5):                        # not an object at all
            resp = client.put("/api/apply/settings", json=payload)
            assert resp.status_code == 422 and resp.json()["detail"] == "invalid", (payload, resp.text)
        assert client.get("/api/apply/settings").json() == before
        assert fake.started == []

        # the inclusive boundaries are accepted
        for payload in ({"daily_cap": 0}, {"daily_cap": 500}, {"per_employer_daily_cap": 0},
                        {"per_employer_daily_cap": 100}, {"captcha_wait_s": 0}, {"captcha_wait_s": 600}):
            resp = client.put("/api/apply/settings", json=payload)
            assert resp.status_code == 200, (payload, resp.text)
            (field, value), = payload.items()
            assert resp.json()[field] == value and type(resp.json()[field]) is int, payload
            assert client.get("/api/apply/settings").json()[field] == value


# ------------------------------------------------------------------ 4. booleans


def test_apply_settings_booleans_round_trip_and_compose_reaches_the_effective_config():
    with _world(headed=True, compose=False) as (client, cfg, _t, _f):
        # no stored key: the config value stands, in the view and in the effective config
        eff = _effective(cfg)
        assert (eff.headed, eff.compose.enabled) == (True, False)

        for want in (False, True):
            resp = client.put("/api/apply/settings", json={"headed": want})
            assert resp.status_code == 200 and resp.json()["headed"] is want, resp.text
            assert client.get("/api/apply/settings").json()["headed"] is want
            assert _effective(cfg).headed is want

        resp = client.put("/api/apply/settings", json={"compose_enabled": True})
        assert resp.status_code == 200 and resp.json()["compose_enabled"] is True, resp.text
        assert _effective(cfg).compose.enabled is True
        assert cfg.apply.compose.enabled is False               # the config still says off
        assert client.get("/api/apply/settings").json()["defaults"]["compose_enabled"] is False

        resp = client.put("/api/apply/settings", json={"compose_enabled": False})
        assert resp.status_code == 200 and resp.json()["compose_enabled"] is False
        assert _effective(cfg).compose.enabled is False
        # the other compose knobs survive the rebuild
        assert _effective(cfg).compose.letter_max_words == cfg.apply.compose.letter_max_words


# ------------------------------------------------------------------ 5. the caps take effect


def test_apply_settings_stored_caps_are_the_caps_the_preflight_enforces():
    # config would allow it (10 per employer, no daily limit); one click today at the employer
    with _world(mode="auto", daily_cap=0, per_employer=10, clicks=1) as (client, cfg, target, fake):
        # Q-120 (D-205): an accepted click queues the role (no start on the default app); each
        # accepted click is taken out again so the next one meets the caps, not `already_queued`
        code, body = _post(client, target)
        assert code == 202 and body["accepted"] == [target], (code, body)
        assert body["queued"] == [{"job_id": target, "position": 1}] and fake.started == [], body
        assert client.delete(f"/api/apply/queue/{target}").status_code == 204

        resp = client.put("/api/apply/settings", json={"per_employer_daily_cap": 1})
        assert resp.status_code == 200
        code, body = _post(client, target)
        assert code == 422 and body["detail"] == "refused", (code, body)
        assert [x["reason_code"] for x in body["refused"]] == ["cap_reached"], body
        assert "1 of 1 today at Fake Co" in body["refused"][0]["text"], body
        assert client.get("/api/apply/queue").json()["waiting"] == []     # nothing queued

        # 0 = no limit
        resp = client.put("/api/apply/settings", json={"per_employer_daily_cap": 0})
        assert resp.status_code == 200 and resp.json()["per_employer_daily_cap"] == 0
        code, body = _post(client, target)
        assert code == 202 and body["accepted"] == [target], (code, body)
        assert body["queued"] == [{"job_id": target, "position": 1}] and fake.started == [], body
        assert client.delete(f"/api/apply/queue/{target}").status_code == 204

        # the daily cap is read the same way
        resp = client.put("/api/apply/settings", json={"daily_cap": 1})
        assert resp.status_code == 200
        code, body = _post(client, target)
        assert code == 422 and [x["reason_code"] for x in body["refused"]] == ["cap_reached"], (code, body)
        assert "1 of 1 today" in body["refused"][0]["text"], body


# ------------------------------------------------------------------ 6. cross-site writes (Q-116)


def test_apply_settings_put_from_another_site_is_refused_and_writes_nothing():
    """The settings page saves on change, so a PUT is one click away for any page on the web
    that can make the owner's browser send one: the mode could be flipped to real submission.
    CrossSiteWriteGuard answers 403 to a foreign Origin (or `Sec-Fetch-Site: cross-site`)
    before the route runs; the stored settings, the effective config and the job manager
    are all as they were. Same-origin and header-less requests (curl, tests) still pass, and
    a GET is a read, so it is not guarded."""
    with _world(mode="dry_run", daily_cap=7, per_employer=3, headed=False, captcha_wait_s=30,
                compose=False) as (client, cfg, _t, fake):
        before = client.get("/api/apply/settings").json()
        change = {"mode": "auto", "daily_cap": 500, "compose_enabled": True, "headed": True}
        for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"},
                        {"Origin": "https://evil.example", "Content-Type": "text/plain"}):
            resp = client.put("/api/apply/settings", json=change, headers=headers)
            assert resp.status_code == 403, (headers, resp.status_code, resp.text)
        # nothing was written: GET, the effective config and the table all say so
        after = client.get("/api/apply/settings", headers={"Origin": "https://evil.example"})
        assert after.status_code == 200                      # reads are not guarded
        assert after.json() == before
        eff = _effective(cfg)
        assert (eff.mode, eff.daily_cap, eff.headed) == ("dry_run", 7, False)
        assert client.get("/api/apply/status").json()["mode"] == "dry_run"
        assert fake.started == []
        # the guard is about the Origin, not the route: the same change from here goes through
        ok = client.put("/api/apply/settings", json={"daily_cap": 9},
                        headers={"Origin": "http://localhost:5173"})
        assert ok.status_code == 200 and ok.json()["daily_cap"] == 9
        assert _effective(cfg).mode == "dry_run"
