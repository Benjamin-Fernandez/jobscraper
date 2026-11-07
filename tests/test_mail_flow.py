"""WP-T5 oracles: the sync flow end to end (mail_status_design.md 5.1-5.5, 10.2, 12, 13).
Verify: `python tests/run_tests.py -k mail_flow`.

FakeMailServer (tests/mail_support) through the real ImapTransport, a temp DB seeded with two
Northwind applications, a fake model backend and the in-memory keyring. No network.
"""
from __future__ import annotations

import contextlib
import io
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    GMAIL_LOGIN_ERRORS, WAITING, FakeMailServer, assert_live, make_eml, needs, note_waiting,
)
from mail_flow_support import (  # noqa: E402
    ADDRESS, NOW, PASSWORD, FakeBackend, captured_logs, config, connect, golden_mail,
    memory_keyring, news, rows, run, seed, statuses, tmpdir,
)

_W0 = len(WAITING)
FLOW = "jobscraper.mailstatus_flow:sync"
LATER = "2026-11-02T14:00:00"
REFUSED = next(k for k, v in GMAIL_LOGIN_ERRORS.items() if v == "login_refused")


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


@contextlib.contextmanager
def _world(mail_status=None, *, rules=None):
    """(cfg, store, server, account_id) with the account connected."""
    from jobscraper.store import Store
    with memory_keyring() as mem:
        tmp = tmpdir("mail_flow_")
        cfg = config(tmp, mail_status, rules=rules)
        st = Store(cfg.db_path)
        seed(st)
        srv = FakeMailServer()
        res, aid = connect(cfg, srv)
        assert res == "ok" and aid, res
        assert ("jobscraper:imap:imap.gmail.com", ADDRESS) in mem.d
        try:
            yield cfg, st, srv, aid
        finally:
            st.close()


def _counts(rep):
    assert len(rep.accounts) == 1, rep
    return rep.accounts[0].counts


@needs(FLOW)
def test_mail_flow_first_sync_then_resume_reprocesses_nothing():
    c = _c()
    with _world() as (cfg, st, srv, aid):
        golden_mail(srv)
        be = FakeBackend()
        r1 = run(cfg, srv, trigger="cli", backend=be)
        assert r1.code is c.SyncCode.OK and _counts(r1)["applied"] == 2, r1
        assert statuses(st) == {"nw-dataeng": "applied", "nw-analyst": "rejected"}
        ev = st.application_events("nw-analyst")[-1]
        assert ev["by"] == "mail" and ev["evidence_id"]
        n = rows(st, "SELECT COUNT(*) FROM mail_messages")[0][0]
        r2 = run(cfg, srv, backend=be)
        c2 = _counts(r2)
        assert (c2["scanned"], c2["bodies"], c2["applied"], c2["suggested"]) == (0, 0, 0, 0), c2
        assert rows(st, "SELECT COUNT(*) FROM mail_messages")[0][0] == n
        assert [r[0] for r in rows(st, "SELECT state FROM mail_sync_runs ORDER BY id")] == ["ok", "ok"]
        assert srv.violations == [] and not any(srv.seen(b.role) for b in srv.boxes if b.role)


@needs(FLOW)
def test_mail_flow_uidvalidity_change_and_a_spam_move_are_deduped():
    c = _c()
    with _world() as (cfg, st, srv, aid):
        golden_mail(srv)
        spam = news(srv, "1800000000000002001", to=("junk",),
                    subject="Thank you for applying to Northwind Traders",
                    body="Thank you for applying. We have received your application for the Graduate Analyst role.")
        run(cfg, srv, backend=FakeBackend())
        n = rows(st, "SELECT COUNT(*) FROM mail_messages")[0][0]
        events = sum(len(st.application_events(j)) for j in ("nw-dataeng", "nw-analyst"))
        new_validity = srv.change_validity("all")
        srv.move(spam, "junk", "all")
        r2 = run(cfg, srv, backend=FakeBackend(), now=LATER)
        c2 = _counts(r2)
        # a new UIDVALIDITY re-finds the place by date (SINCE the last scan day), so the moved
        # message (new UID 3) and anything since that day come back, all deduped by X-GM-MSGID
        assert any(v[0] == "UID SEARCH" and "SINCE" in v for v in srv.log), srv.log[-6:]
        assert r2.code is c.SyncCode.OK and c2["scanned"] >= 1 and c2["duplicates"] == c2["scanned"], c2
        assert rows(st, "SELECT COUNT(*) FROM mail_messages WHERE gm_msgid=?", spam) == [(1,)]
        assert c2["applied"] == 0 and rows(st, "SELECT COUNT(*) FROM mail_messages")[0][0] == n
        assert sum(len(st.application_events(j)) for j in ("nw-dataeng", "nw-analyst")) == events
        assert st.mail_cursor(aid, "all")["uidvalidity"] == new_validity


@needs(FLOW)
def test_mail_flow_a_dropped_connection_resumes_after_the_last_stored_message():
    c = _c()
    with _world() as (cfg, st, srv, aid):
        golden_mail(srv)
        news(srv, "1800000000000002002")
        srv.drop_after = 9                  # LOGIN CAPABILITY LIST EXAMINE SEARCH SEARCH FETCH, one body
        r1 = run(cfg, srv, backend=FakeBackend())
        assert r1.accounts[0].code is c.SyncCode.NETWORK, r1.accounts[0]
        stored = [r[0] for r in rows(st, "SELECT uid FROM mail_messages WHERE role='all' ORDER BY uid")]
        assert 1 <= len(stored) < 3, stored
        assert st.mail_cursor(aid, "all")["last_uid"] == max(stored)
        acc = st.mail_account(aid)
        assert acc["state"] == "error" and acc["retry_after"] > NOW
        srv.drop_after = None
        r2 = run(cfg, srv, backend=FakeBackend(), now=LATER)
        c2 = _counts(r2)
        assert r2.code is c.SyncCode.OK and c2["scanned"] == 3 - len(stored) and c2["duplicates"] == 0, c2
        assert sorted(r[0] for r in rows(st, "SELECT uid FROM mail_messages WHERE role='all'")) == [1, 2, 3]
        assert st.mail_account(aid)["state"] == "ok" and st.mail_account(aid)["retry_after"] is None


@needs(FLOW)
def test_mail_flow_body_cap_and_deadline_give_partial():
    c = _c()
    from jobscraper import mailstatus_flow as flow
    with _world({"max_bodies_per_sync": 1}) as (cfg, st, srv, aid):
        golden_mail(srv)
        r1 = run(cfg, srv, backend=FakeBackend())
        assert r1.code is c.SyncCode.PARTIAL and _counts(r1)["bodies"] == 1, r1
        assert rows(st, "SELECT state FROM mail_sync_runs ORDER BY id DESC LIMIT 1") == [("partial",)]
        r2 = run(cfg, srv, backend=FakeBackend(), now=LATER)
        assert _counts(r2)["bodies"] == 1
        assert statuses(st) == {"nw-dataeng": "applied", "nw-analyst": "rejected"}
    with _world() as (cfg, st, srv, aid):
        golden_mail(srv)
        ticks = iter([0.0] + [10_000.0] * 1000)
        saved = flow.time
        flow.time = types.SimpleNamespace(monotonic=lambda: next(ticks), sleep=saved.sleep, time=saved.time)
        try:
            r = run(cfg, srv, backend=FakeBackend())
        finally:
            flow.time = saved
        assert r.code is c.SyncCode.PARTIAL, r
        assert rows(st, "SELECT COUNT(*) FROM mail_messages")[0][0] == 0
        assert statuses(st) == {"nw-dataeng": "to_apply", "nw-analyst": "interviewing"}


@needs(FLOW)
def test_mail_flow_model_down_pending_retried_then_expired():
    with _world() as (cfg, st, srv, aid):
        gm = news(srv, "1800000000000002003")
        down = FakeBackend(fail=True)
        r1 = run(cfg, srv, backend=down)
        assert _counts(r1)["pending_model"] == 1 and len(down.calls) == 1
        assert rows(st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("pending_model", "model_unavailable")]
        for i in range(5):
            run(cfg, srv, backend=FakeBackend(fail=True), now=f"2026-11-02T1{3 + i}:00:00")
            if rows(st, "SELECT outcome FROM mail_messages WHERE gm_msgid=?", gm)[0][0] != "pending_model":
                break
        assert rows(st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("suggested", "model_unavailable")]
        sugg = [s for s in st.mail_suggestions(LATER) if s["gm_msgid"] == gm]
        assert len(sugg) == 1 and sugg[0]["reason"] == "model_unavailable" and sugg[0]["to_status"] is None


@needs(FLOW)
def test_mail_flow_model_retry_resolves_and_defer_model_makes_no_call():
    with _world() as (cfg, st, srv, aid):
        gm = news(srv, "1800000000000002004")
        be = FakeBackend()
        r1 = run(cfg, srv, backend=be, defer_model=True)
        assert _counts(r1)["pending_model"] == 1 and be.calls == []
        assert rows(st, "SELECT outcome, reason, retries FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("pending_model", "model_deferred", 0)], "deferral isn't a failed try"
        run(cfg, srv, backend=be, now=LATER)
        assert len(be.calls) == 1
        call = be.calls[0]
        assert call["format"]["required"] == ["category", "quote"] and call["temperature"] == 0 \
            and call["seed"] == 7 and call["max_tokens"] == 200
        assert ADDRESS not in call["user"] and "http" not in call["user"]
        assert rows(st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("suggested", "unclear")]


@needs(FLOW)
def test_mail_flow_login_refused_pauses_and_network_backs_off():
    c = _c()
    with _world() as (cfg, st, srv, aid):
        golden_mail(srv)
        srv.login_error = REFUSED
        r1 = run(cfg, srv)
        assert r1.accounts[0].code is c.SyncCode.LOGIN_REFUSED
        acc = st.mail_account(aid)
        assert (acc["state"], acc["state_code"], acc["retry_after"]) == ("paused", "login_refused", None)
        n = len(srv.commands("LOGIN"))
        r2 = run(cfg, srv, now=LATER)
        assert r2.accounts == [] and len(srv.commands("LOGIN")) == n, "the timer never retries a pause"
        r3 = run(cfg, srv, trigger="manual", now=LATER)
        assert len(r3.accounts) == 1 and len(srv.commands("LOGIN")) == n + 1, "the owner may try it"
        srv.login_error = None
        st.mail_account_set(aid, state="ok", state_code=None, retry_after=None)
        srv.connect_error = ConnectionRefusedError("refused")
        r4 = run(cfg, srv, now=LATER)
        assert r4.accounts[0].code is c.SyncCode.NETWORK
        acc = st.mail_account(aid)
        assert acc["state"] == "error" and acc["retry_after"] > LATER and acc["fail_count"] >= 1
        assert run(cfg, srv, now=LATER).accounts == [], "held back until retry_after"
        srv.connect_error = None
        r5 = run(cfg, srv, now="2026-11-03T14:00:00")
        assert r5.accounts[0].code is c.SyncCode.OK and st.mail_account(aid)["state"] == "ok"


@needs(FLOW)
def test_mail_flow_rules_invalid_stops_the_run():
    c = _c()
    bad = tmpdir("rules_bad_") / "mail_rules.yaml"
    bad.write_text("version: 2\nplatforms: []\n", encoding="utf-8")
    with _world(rules=bad) as (cfg, st, srv, aid):
        golden_mail(srv)
        with captured_logs() as logs:
            r = run(cfg, srv)
        assert r.code is c.SyncCode.RULES_INVALID and r.accounts == []
        assert srv.commands("LOGIN") == [("LOGIN", ADDRESS)], "only the connect test logged in"
        assert rows(st, "SELECT state, code FROM mail_sync_runs") == [("failed", "rules_invalid")]
        assert "rules file is invalid" in logs.getvalue()


@needs(FLOW)
def test_mail_flow_disabled_and_busy():
    c = _c()
    with _world({"enabled": "false"}) as (cfg, st, srv, aid):
        assert run(cfg, srv).code is c.SyncCode.DISABLED
    with _world() as (cfg, st, srv, aid):
        assert st.mail_run_begin("timer", 1, NOW, 660)
        assert run(cfg, srv).code is c.SyncCode.BUSY
        try:
            run(cfg, srv, trigger="whenever")
        except ValueError:
            pass
        else:
            raise AssertionError("an unknown trigger must be refused")


@needs(FLOW)
def test_mail_flow_canary_never_reaches_the_log_or_stdout():
    """MS 13: subjects, bodies, display names, sender addresses, the account address and the
    password never appear in log records or on stdout."""
    marks = ("CANARYsubj42", "CANARYbody42", "CANARYname42", "canary-sender-42")
    with _world() as (cfg, st, srv, aid):
        golden_mail(srv)
        srv.deliver(make_eml("CANARYname42 Hiring <canary-sender-42@us.greenhouse-mail.io>",
                             "CANARYsubj42 about your application to Northwind Traders",
                             "Hi, CANARYbody42: there is news about your application to Northwind "
                             "Traders. Please read the update."), gm_msgid="1800000000000002005")
        srv.deliver(make_eml("CANARYname42 <canary-sender-42@mail.example.org>", "CANARYsubj42 hello",
                             "CANARYbody42"), gm_msgid="1800000000000002006")
        out = io.StringIO()
        with captured_logs() as logs, contextlib.redirect_stdout(out):
            run(cfg, srv, backend=FakeBackend(fail=True))
            run(cfg, srv, backend=FakeBackend(), now=LATER)
            srv.login_error = REFUSED
            run(cfg, srv, trigger="manual", now="2026-11-02T15:00:00")
        text = logs.getvalue() + out.getvalue()
        assert "mail sync account" in text, "the capture works"
        for m in marks + (ADDRESS, PASSWORD, "CANARYpw", "abcd efgh"):
            assert m.lower() not in text.lower(), (m, [ln for ln in text.splitlines() if m.lower() in ln.lower()])
        assert b"CANARYpw" not in Path(cfg.db_path).read_bytes()


def test_mail_flow_oracles_are_live():
    assert_live("jobscraper.mailstatus_flow", _W0, "test_mail_flow")


note_waiting("test_mail_flow", _W0)
