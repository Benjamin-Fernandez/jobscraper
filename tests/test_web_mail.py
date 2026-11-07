"""WP-T6 oracles: the mail routes and the web runner (mail_status_design.md 10.1, 11.1, 4, 13).
Verify: `python tests/run_tests.py -k web_mail`.

`create_app(..., mail_command=stub)`: the children are tiny `python -c` stubs, so no route ever
reads a mailbox. Real syncs (for suggestions and timeline events) run in process against the
FakeMailServer. The in-memory keyring stands in for Credential Manager. No network.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import WAITING, FakeMailServer, assert_live, needs, note_waiting  # noqa: E402
from mail_flow_support import (  # noqa: E402
    ADDRESS, NOW, NW_NEWS, PASSWORD, captured_logs, config, connect, golden_mail, memory_keyring,
    news, run, seed, tmpdir,
)

_W0 = len(WAITING)
ROUTES = "jobscraper.web.routers.mail:add_account"
SERVICE = "jobscraper:imap:imap.gmail.com"
EVIL = {"Origin": "https://evil.example"}


def _consent():
    from jobscraper.mailstatus.contracts import CONSENT_VERSION
    return CONSENT_VERSION


class Stub:
    """A `MailCommand`: records (kind, opts); add/set_password children read one stdin line,
    echo it to stdout and stderr (the runner must never pass that on) and end with `result`;
    sync children sleep `sleep` seconds."""

    def __init__(self, tmp: Path, result=None, sleep: float = 0.0):
        self.tmp, self.calls, self.sleep = tmp, [], sleep
        self.result = result or {"result": "ok", "account_id": 1}

    def __call__(self, kind, opts):
        self.calls.append((kind, dict(opts)))
        if kind == "sync":
            return [sys.executable, "-c", f"import time; time.sleep({self.sleep})"]
        got = self.tmp / f"stdin_{len(self.calls)}.txt"
        code = ("import sys, json; line = sys.stdin.readline(); "
                f"open({str(got)!r}, 'w').write(line); "
                "print('echo ' + line); sys.stderr.write('echo ' + line); "
                f"print(json.dumps({self.result!r}))")
        return [sys.executable, "-c", code]


@contextlib.contextmanager
def _app(mail_status=None, *, result=None, sleep=0.0, mail_timer=False):
    """(client, cfg, stub, mem); the DB is seeded; children are stubs."""
    from fastapi.testclient import TestClient
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    with memory_keyring() as mem:
        tmp = tmpdir("web_mail_")
        cfg = config(tmp, {"model": False, **(mail_status or {})})
        st = Store(cfg.db_path)
        seed(st)
        st.close()
        stub = Stub(tmp, result, sleep)
        app = create_app(cfg, static_dir=tmp / "no_static", mail_command=stub, mail_timer=mail_timer)
        try:
            with TestClient(app, base_url="http://localhost") as client:
                yield client, cfg, stub, mem
        finally:
            proc = app.state.mail._proc
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(10)


def _store(cfg):
    from jobscraper.store import Store
    return Store(cfg.db_path)


def _account(cfg, address=ADDRESS, shared=False):
    st = _store(cfg)
    try:
        return st.mail_account_add(address, host="imap.gmail.com", port=993, vault_service=SERVICE,
                                   shared_with_apply=shared, consent_version=_consent(),
                                   first_sync_from="2026-05-06T00:00:00", now=NOW)
    finally:
        st.close()


def _wait(proc):
    if proc is not None:
        proc.wait(30)


@needs(ROUTES)
def test_web_mail_the_password_reaches_only_the_child_stdin():
    with _app() as (client, cfg, stub, mem), captured_logs() as logs:
        body = {"address": ADDRESS.upper(), "app_password": PASSWORD, "consent_version": _consent()}
        r = client.post("/api/mail/accounts", json=body)
        assert r.status_code == 200 and r.json() == {"ok": True, "account_id": 1}, r.text
        assert (stub.tmp / "stdin_1.txt").read_text() == PASSWORD.replace(" ", "") + "\n"
        kind, opts = stub.calls[0]
        assert kind == "add" and opts["address"] == ADDRESS and "CANARYpw" not in json.dumps(opts)
        assert stub.calls[1][0] == "sync" and stub.calls[1][1]["trigger"] == "connect"
        _wait(client.app.state.mail._proc)
        texts = [r.text, logs.getvalue()]
        texts += [p.read_text(encoding="utf-8") for p in (Path(cfg.db_path).parent / "jobs" / "mail").glob("*.log")]
        stub.result = {"result": "login_refused"}
        r = client.post("/api/mail/accounts", json={**body, "address": "other@inbox.example"})
        assert r.status_code == 400 and r.json()["code"] == "login_refused", r.text
        texts.append(r.text)
        for bad in (b'{"app_password": "CANARYpw abcd efgh", ', b'["CANARYpw abcd efgh"]',
                    json.dumps({**body, "app_password": ["CANARYpw"]}).encode(),
                    json.dumps({**body, "address": ["CANARYpw abcd efgh"]}).encode(),
                    json.dumps({**body, "consent_version": "v0"}).encode()):
            r = client.post("/api/mail/accounts", content=bad, headers={"Content-Type": "application/json"})
            assert r.status_code == 400 and r.json()["code"] == "bad_input", (bad, r.text)
            texts.append(r.text)
        r = client.put("/api/mail/accounts/1/password", json={"app_password": 12345678})
        assert r.status_code == 400
        texts += [r.text, client.get("/api/mail").text, logs.getvalue()]
        for t in texts:
            assert "CANARYpw" not in t and "abcd" not in t, t[:300]
        assert mem.d == {}, "the stub child stores nothing, and neither does the web process"


@needs(ROUTES)
def test_web_mail_no_timer_by_default_and_the_env_switch():
    with _app() as (client, cfg, stub, mem):
        assert client.app.state.mail.timer_running is False
        assert client.get("/api/mail").json()["sync"]["next_at"] is None
    with _app(mail_timer=True) as (client, cfg, stub, mem):
        assert client.app.state.mail.timer_running is True
        assert client.get("/api/mail").json()["sync"]["next_at"]
        assert stub.calls == [], "the first tick waits startup_delay_s"
    import uvicorn
    from jobscraper import cli
    seen = []
    saved, old_env = uvicorn.run, os.environ.get("JOBSCRAPER_MAIL_SYNC")
    uvicorn.run = lambda app, **kw: seen.append(app)
    _, path = config(tmpdir("web_mail_env_"), write=True)
    try:
        for env, want in (("0", False), ("1", True)):
            os.environ["JOBSCRAPER_MAIL_SYNC"] = env
            cli.main(["--config", str(path), "web"])
            assert seen, "cmd_web built no app"
            handlers = [getattr(h, "__name__", "") for h in seen[-1].router.on_startup]
            assert ("start_timer" in handlers) is want, (env, handlers)
    finally:
        uvicorn.run = saved
        if old_env is None:
            os.environ.pop("JOBSCRAPER_MAIL_SYNC", None)
        else:
            os.environ["JOBSCRAPER_MAIL_SYNC"] = old_env


@needs(ROUTES)
def test_web_mail_check_now_is_single_flight():
    with _app(sleep=20) as (client, cfg, stub, mem):
        assert client.post("/api/mail/sync").json()["code"] == "no_mailbox"
        _account(cfg)
        r = client.post("/api/mail/sync")
        assert r.status_code == 202 and stub.calls[-1] == ("sync", {"trigger": "manual"}), r.text
        assert client.get("/api/mail").json()["sync"]["running"] is True
        r = client.post("/api/mail/sync")
        assert r.status_code == 409 and r.json()["code"] == "busy"
        assert [k for k, _ in stub.calls].count("sync") == 1
        log = next((Path(cfg.db_path).parent / "jobs" / "mail").glob("*-mailsync*.log"))
        assert log.read_text(encoding="utf-8").startswith("$ mail sync")
    with _app({"enabled": "no"}) as (client, cfg, stub, mem):
        _account(cfg)
        assert client.post("/api/mail/sync").json()["code"] == "disabled" and stub.calls == []


@needs(ROUTES)
def test_web_mail_disconnect_keeps_a_shared_vault_entry_only():
    with _app() as (client, cfg, stub, mem):
        mem.d[(SERVICE, ADDRESS)] = "pw1"
        mem.d[(SERVICE, "shared@inbox.example")] = "pw2"
        mem.d[(SERVICE, "apply.box@inbox.example")] = "pw3"
        a = _account(cfg)
        b = _account(cfg, "shared@inbox.example", shared=True)
        st = _store(cfg)
        st.set_setting("apply.mail.username", "Apply.Box@inbox.example")
        st.close()
        c = _account(cfg, "apply.box@inbox.example")
        assert client.delete(f"/api/mail/accounts/{a}").json() == {"ok": True, "vault_kept": False}
        assert client.delete(f"/api/mail/accounts/{b}").json() == {"ok": True, "vault_kept": True}
        assert client.delete(f"/api/mail/accounts/{c}").json() == {"ok": True, "vault_kept": True}
        assert set(mem.d) == {(SERVICE, "shared@inbox.example"), (SERVICE, "apply.box@inbox.example")}
        assert client.delete(f"/api/mail/accounts/{a}").status_code == 404
        assert client.get("/api/mail").json()["accounts"] == []


@needs(ROUTES)
def test_web_mail_new_routes_refuse_cross_site_writes():
    with _app() as (client, cfg, stub, mem):
        aid = _account(cfg)
        body = {"address": ADDRESS, "app_password": PASSWORD, "consent_version": _consent()}
        for method, url, kw in (("post", "/api/mail/accounts", {"json": body}),
                                ("post", "/api/mail/accounts/application", {"json": {}}),
                                ("put", f"/api/mail/accounts/{aid}/password", {"json": body}),
                                ("patch", f"/api/mail/accounts/{aid}", {"json": {"enabled": False}}),
                                ("delete", f"/api/mail/accounts/{aid}", {}),
                                ("post", "/api/mail/sync", {}),
                                ("post", "/api/mail/suggestions/1/accept", {"json": {}}),
                                ("post", "/api/mail/suggestions/1/dismiss", {}),
                                ("post", "/api/mail/evidence/1/undo", {})):
            r = getattr(client, method)(url, headers=EVIL, **kw)
            assert r.status_code == 403, (method, url, r.status_code)
        assert stub.calls == [] and len(client.get("/api/mail").json()["accounts"]) == 1
        r = client.patch(f"/api/mail/accounts/{aid}", json={"enabled": "false"})
        assert r.status_code == 400, "a bool, not text"
        assert client.patch(f"/api/mail/accounts/{aid}", json={"enabled": False}).json()["enabled"] is False


def test_web_mail_gmail_url_is_built_from_the_account_and_message_id():
    from jobscraper.web.mailsync import gmail_url
    assert gmail_url(ADDRESS, "1800000000000001001") == \
        f"https://mail.google.com/mail/?authuser={ADDRESS}#all/{1800000000000001001:x}"
    assert gmail_url(None, "1800000000000001001") is None and gmail_url(ADDRESS, "x1") is None
    assert gmail_url("a+b@inbox.example", 255).endswith("authuser=a%2Bb@inbox.example#all/ff")


@needs(ROUTES)
def test_web_mail_suggestions_events_accept_and_undo():
    with _app() as (client, cfg, stub, mem):
        srv = FakeMailServer()
        assert connect(cfg, srv)[0] == "ok"
        golden_mail(srv)
        news(srv, "1800000000000002010")
        run(cfg, srv, trigger="cli")
        apps = {a["job_id"]: a for a in client.get("/api/applications").json()}
        ev = apps["nw-analyst"]["events"][-1]
        assert ev["by"] == "mail" and ev["to_status"] == "rejected", ev
        assert ev["mail"]["evidence_id"] and ev["mail"]["kind"] == "auto"
        assert all("by" in e and "mail" in e for a in apps.values() for e in a["events"])
        sugg = client.get("/api/mail/suggestions").json()["suggestions"]
        s = next(x for x in sugg if x["gmail_url"].endswith(f"#all/{1800000000000002010:x}"))
        assert s["reason"] == "unclear" and s["subject"] == NW_NEWS[1]
        assert {c["job_id"] for c in s["candidates"]} == {"nw-dataeng", "nw-analyst"}
        assert s["gmail_url"].startswith("https://mail.google.com/mail/?authuser=")
        r = client.post(f"/api/mail/suggestions/{s['id']}/accept", json={"job_id": 5})
        assert r.status_code == 400
        r = client.post(f"/api/mail/suggestions/{s['id']}/dismiss")
        assert r.status_code == 200
        r = client.post(f"/api/mail/suggestions/{s['id']}/accept", json={})
        assert r.status_code == 409 and r.json()["code"] == "not_open"
        assert client.post("/api/mail/suggestions/99999/accept", json={}).status_code == 404
        eid = ev["mail"]["evidence_id"]
        r = client.post(f"/api/mail/evidence/{eid}/undo")
        assert r.status_code == 200 and r.json()["status"] == "interviewing", r.text
        r = client.post(f"/api/mail/evidence/{eid}/undo")
        assert r.status_code in (404, 409), r.text


def test_web_mail_oracles_are_live():
    assert_live(ROUTES, _W0, "test_web_mail")


note_waiting("test_web_mail", _W0)
