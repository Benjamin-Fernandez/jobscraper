"""Pins for the lane F review (docs/reviews/Q-60-flow.md) and its decisions D-157
(instructions/02_status.md; Q-60). Verify: `python tests/run_tests.py -k mail_d157`.

Pins for behaviour lanes F and S are still building fail until those land; each names its item.
Also the FL-2 oracles the T5/T6 files didn't cover: undo is never re-applied by a reconnect, the
runner's child env and the timer's PAUSED skip. FakeMailServer + temp DB + in-memory keyring.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    MATCH, REAL_RULES, RULES, RULES_MIN, TRANSITION, WAITING, FakeMailServer, app_candidate,
    assert_live, build_policy, decide, eml, golden_own, load, needs, note_waiting, unit_header,
)
from mail_flow_support import (  # noqa: E402
    PASSWORD, FakeBackend, config, connect, golden_mail, memory_keyring, news, rows, run, seed,
    statuses, tmpdir,
)

_W0 = len(WAITING)
FLOW = "jobscraper.mailstatus_flow:sync"
NOW = "2026-11-02T12:00:00"
REJ_ID = "1800000000000001019"         # golden rej_not_move_forward.eml: nw-analyst, 1 Nov 2026
POISON = (b"From: Out of office <hr@b\xc3\xbccher.example>\r\n"
          b"To: alex.applicant@inbox.example\r\nSubject: Automatic reply\r\n"
          b"Date: Sat, 31 Oct 2026 08:00:00 +0000\r\nAuto-Submitted: auto-replied\r\n"
          b"Message-ID: <ooo-1@mail.example.org>\r\nMIME-Version: 1.0\r\n"
          b"Content-Type: text/plain; charset=utf-8\r\n\r\nI am out of the office this week.\r\n")


class _World:
    def __init__(self, mail_status=None, *, seeded_at="2026-09-15T09:00:00"):
        self.mail_status, self.seeded_at = mail_status, seeded_at

    def __enter__(self):
        from jobscraper.store import Store
        self._kr = memory_keyring()
        self.mem = self._kr.__enter__()
        self.cfg = config(tmpdir("d157_"), self.mail_status)
        self.st = Store(self.cfg.db_path)
        seed(self.st, at=self.seeded_at)
        self.srv = FakeMailServer()
        res, self.aid = connect(self.cfg, self.srv)
        assert res == "ok", res
        return self

    def __exit__(self, *exc):
        self.st.close()
        self._kr.__exit__(*exc)


def _no_surrogates(st):
    for table in ("mail_messages", "mail_evidence", "mail_accounts"):
        for row in rows(st, f"SELECT * FROM {table}"):
            for v in row:
                if isinstance(v, str):
                    v.encode("utf-8")       # a lone surrogate raises here


# ------------------------------------------------------------------ (a) FL-1
@needs(FLOW)
def test_mail_d157a_a_raw_utf8_auto_reply_does_not_wedge_the_mailbox():
    with _World() as w:
        w.srv.deliver(POISON, gm_msgid="1800000000000004001")
        golden_mail(w.srv)
        rep = run(w.cfg, w.srv, backend=FakeBackend())
        assert statuses(w.st)["nw-analyst"] == "rejected", (rep.accounts, statuses(w.st))
        assert rows(w.st, "SELECT outcome FROM mail_messages WHERE gm_msgid='1800000000000004001'") == \
            [("skipped",)]
        assert w.st.mail_account(w.aid)["state"] == "ok"
        _no_surrogates(w.st)


def _failing(ids):
    """Patch `_Sync.process` to raise for these X-GM-MSGIDs (a stand-in for any one-message bug)."""
    from jobscraper import mailstatus_flow as flow
    real = flow._Sync.process

    def process(self, acc, h, **kw):
        if str(h.gm_msgid) in ids:
            raise RuntimeError("one-message bug")
        return real(self, acc, h, **kw)
    flow._Sync.process = process
    return lambda: setattr(flow._Sync, "process", real)


@needs(FLOW)
def test_mail_d157a_a_failing_message_is_skipped_internal_and_three_in_a_row_stop():
    with _World() as w:
        for i in (1, 2):
            news(w.srv, f"18000000000000041{i:02d}")
        golden_mail(w.srv)
        news(w.srv, "1800000000000004103")
        undo = _failing({"1800000000000004101", "1800000000000004102", "1800000000000004103"})
        try:
            rep = run(w.cfg, w.srv, backend=FakeBackend())
        finally:
            undo()
        assert statuses(w.st)["nw-analyst"] == "rejected", "two failures, then good mail: it goes on"
        got = rows(w.st, "SELECT gm_msgid, outcome, reason FROM mail_messages WHERE gm_msgid LIKE '180000000000000410%'")
        assert sorted(got) == [(f"18000000000000041{i:02d}", "skipped", "internal") for i in (1, 2, 3)], got
        assert rep.accounts[0].counts.get("errors") == 3, rep.accounts[0].counts
        assert w.st.mail_account(w.aid)["state"] == "ok", "never three in a row"
    with _World() as w:
        ids = [news(w.srv, f"18000000000000042{i:02d}") for i in (1, 2, 3)]
        golden_mail(w.srv)
        undo = _failing(set(ids))
        try:
            rep = run(w.cfg, w.srv, backend=FakeBackend())
        finally:
            undo()
        acc = w.st.mail_account(w.aid)
        assert acc["state"] == "error" and acc["state_code"] == "internal", acc
        assert statuses(w.st)["nw-analyst"] == "interviewing", "stopped after the third failure"
        assert len(rows(w.st, "SELECT 1 FROM mail_messages WHERE reason='internal'")) == 3


# ------------------------------------------------------------------ (b) FL-3
@needs(FLOW)
def test_mail_d157b_a_disconnect_during_sync_leaves_no_orphans():
    with _World() as w:
        golden_mail(w.srv)
        news(w.srv, "1800000000000004301")
        real = w.st.mail_seen_many

        def seen_then_disconnect(aid, ids):
            out = real(aid, ids)
            w.st.mail_account_delete(aid)       # the owner clicks Disconnect mid-run
            return out
        w.st.mail_seen_many = seen_then_disconnect
        run(w.cfg, w.srv, backend=FakeBackend(), store=w.st)
        for table in ("mail_messages", "mail_cursors", "mail_evidence"):
            assert rows(w.st, f"SELECT COUNT(*) FROM {table} WHERE account_id=?", w.aid) == [(0,)], table
        assert w.st.mail_account(w.aid) is None


# ------------------------------------------------------------------ (c) FL-4
def test_mail_d157c_cmd_web_with_jobscraper_db_has_no_timer_unless_asked():
    import uvicorn
    from jobscraper import cli
    tmp = tmpdir("d157c_")
    _, path = config(tmp, write=True)
    seen, saved = [], uvicorn.run
    old = {k: os.environ.get(k) for k in ("JOBSCRAPER_DB", "JOBSCRAPER_MAIL_SYNC")}
    uvicorn.run = lambda app, **kw: seen.append(app)
    try:
        os.environ["JOBSCRAPER_DB"] = str(tmp / "copy.db")
        for sync, want in ((None, False), ("0", False), ("1", True)):
            if sync is None:
                os.environ.pop("JOBSCRAPER_MAIL_SYNC", None)
            else:
                os.environ["JOBSCRAPER_MAIL_SYNC"] = sync
            cli.main(["--config", str(path), "web"])
            handlers = [getattr(h, "__name__", "") for h in seen[-1].router.on_startup]
            assert ("start_timer" in handlers) is want, (sync, handlers)
    finally:
        uvicorn.run = saved
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------ (d) FL-5
@needs(FLOW)
def test_mail_d157d_an_unavailable_model_burns_no_retries():
    with _World() as w:
        gm = news(w.srv, "1800000000000004401")
        off = FakeBackend(available=False)
        for i in range(6):
            run(w.cfg, w.srv, backend=off, now=f"2026-11-02T{12 + i}:00:00")
        assert off.calls == []
        assert rows(w.st, "SELECT outcome, retries FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("pending_model", 0)], "six ticks with the model off are not six tries"
        run(w.cfg, w.srv, backend=off, now="2026-11-06T12:00:00")
        assert rows(w.st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("suggested", "model_unavailable")], "age (3 days) still expires it"


# ------------------------------------------------------------------ (e) FL-6, supersedes D-156 (2)
@needs(FLOW)
def test_mail_d157e_owner_triggers_ignore_retry_after_the_timer_respects_it():
    with _World() as w:
        for state, code in (("error", "network"), ("backoff", "rate_limited")):
            for trigger, runs in (("timer", False), ("startup", False), ("manual", True), ("cli", True)):
                w.st.mail_account_set(w.aid, state=state, state_code=code, retry_after="2026-11-02T13:00:00")
                n = len(w.srv.commands("LOGIN"))
                rep = run(w.cfg, w.srv, trigger=trigger, now=NOW)
                assert (len(rep.accounts) == 1) is runs, (state, trigger, rep)
                assert len(w.srv.commands("LOGIN")) == n + int(runs), (state, trigger)


# ------------------------------------------------------------------ (f) FL-7
@needs("jobscraper.web.routers.mail:list_suggestions")
def test_mail_d157f_get_mail_and_suggestions_never_write():
    from fastapi.testclient import TestClient
    from jobscraper.web.api import create_app
    with _World({"model": False}) as w:
        news(w.srv, "1800000000000004601")
        run(w.cfg, w.srv, backend=FakeBackend())
        w.st.set_application_status("nw-analyst", "offer")      # the suggestion is now stale
        w.st.set_application_status("nw-dataeng", "applied")
        probe = sqlite3.connect(w.cfg.db_path)
        before = probe.execute("PRAGMA data_version").fetchone()[0]
        app = create_app(w.cfg, static_dir=tmpdir() / "none", mail_command=lambda k, o: ["none"])
        with TestClient(app, base_url="http://localhost") as client:
            for _ in range(3):
                assert client.get("/api/mail").status_code == 200
                assert client.get("/api/mail/suggestions").status_code == 200
        after = probe.execute("PRAGMA data_version").fetchone()[0]
        probe.close()
        assert after == before, "a GET committed a write (FL-7)"


# ------------------------------------------------------------------ (h) FL-9
@needs(FLOW)
def test_mail_d157h_a_backfilled_application_gets_a_suggestion():
    with _World(seeded_at="2026-11-02T11:00:00") as w:      # entered after the 1 Nov rejection
        golden_mail(w.srv)
        run(w.cfg, w.srv, backend=FakeBackend())
        assert statuses(w.st)["nw-analyst"] == "interviewing", "owner_newer: never automatic"
        sugg = [s for s in w.st.mail_suggestions(NOW) if s["gm_msgid"] == REJ_ID]
        assert len(sugg) == 1 and sugg[0]["reason"] == "backfilled" and sugg[0]["to_status"] == "rejected", sugg


@needs(FLOW)
def test_mail_d157h_an_undone_mail_stays_silent_even_after_a_reconnect():
    with _World() as w:
        golden_mail(w.srv)
        run(w.cfg, w.srv, backend=FakeBackend())
        ev = w.st.application_events("nw-analyst")[-1]
        assert ev["by"] == "mail"
        assert w.st.mail_undo(ev["evidence_id"], NOW) == (True, "ok")
        run(w.cfg, w.srv, backend=FakeBackend(), now="2026-11-02T13:00:00")
        assert w.st.mail_account_delete(w.aid)
        res, aid2 = connect(w.cfg, w.srv, now="2026-11-02T14:00:00")
        assert res == "ok" and aid2 != w.aid
        run(w.cfg, w.srv, backend=FakeBackend(), now="2026-11-02T15:00:00")
        assert statuses(w.st)["nw-analyst"] == "interviewing", "an undone mail is never re-applied"
        assert not [s for s in w.st.mail_suggestions("2026-11-02T15:00:00") if s["gm_msgid"] == REJ_ID]


# ------------------------------------------------------------------ (i) F3 residual
REJ = "Thank you for your interest. Unfortunately, we will not be moving forward with your application."


@needs(RULES, MATCH, TRANSITION)
def test_mail_d157i_a_display_name_with_extra_words_is_not_strong():
    from jobscraper.mailstatus import contracts as c, match as M, rules as R
    app = app_candidate(dict(job_id="gx", status="applied", company_names=("Globex",), role="Graduate Analyst",
                             employer_domains=(), tenants=(), owner_changed_at=None, last_event_at=None))
    for path in [RULES_MIN] + ([REAL_RULES] if REAL_RULES.exists() else []):
        rules_obj = load(path)
        # D-157 (i) and its addendum: recruiting words before or after the name still name the
        # employer; any other extra word ("Labs", "at Night", a bare "At") is only WEAK.
        for name, strong in (("Globex Labs", False), ("Globex Careers", True), ("Globex", True),
                             ("Globex Talent Acquisition", True), ("Careers at Globex", True),
                             ("Recruiting at Globex", True), ("Jobs at Globex", True),
                             ("Talent Acquisition at Globex", True), ("Globex at Night", False),
                             ("At Globex", False)):
            h, b = unit_header(f"{name} <no-reply@us.greenhouse-mail.io>", "Your application", REJ,
                               auth="pass")
            g = R.header_gate(h, rules_obj, own=golden_own(), window_start="2026-08-01T00:00:00",
                              threads=frozenset(), employer_regs=frozenset())
            assert g is None, (path.name, name, g)
            m = M.match(h, b, (app,), rules_obj)
            assert (m.kind == c.MatchKind.STRONG) is strong, (path.name, name, m)
            if not strong:
                assert m.kind == c.MatchKind.WEAK, (path.name, name, m)
            if not strong:
                ch = decide(app, R.classify(h, b, rules_obj), m, h, build_policy())
                assert ch is None or ch.kind != c.ChangeKind.AUTO, (path.name, name, ch)


# ------------------------------------------------------------------ D-158
@needs(FLOW)
def test_mail_d158_a_locked_db_during_record_skips_no_message():
    with _World() as w:
        golden_mail(w.srv)
        real, n = w.st.mail_record, []

        def locked(**kw):
            n.append(kw["message"].get("gm_msgid"))
            if len(n) == 2:
                raise sqlite3.OperationalError("database is locked")
            return real(**kw)
        w.st.mail_record = locked
        run(w.cfg, w.srv, backend=FakeBackend(), store=w.st)
        w.st.mail_record = real
        assert rows(w.st, "SELECT COUNT(*) FROM mail_messages WHERE gm_msgid=?", REJ_ID) == [(0,)]
        assert statuses(w.st)["nw-analyst"] == "interviewing"
        run(w.cfg, w.srv, backend=FakeBackend(), now="2026-11-02T13:00:00")
        assert statuses(w.st)["nw-analyst"] == "rejected", "the next run processes the message"
        assert rows(w.st, "SELECT COUNT(*) FROM mail_messages")[0][0] == 2


@needs(FLOW)
def test_mail_d158_a_cursor_write_after_a_disconnect_makes_no_orphan():
    from jobscraper import mailstatus_flow as flow
    with _World() as w:
        golden_mail(w.srv)
        run(w.cfg, w.srv, backend=FakeBackend())
        cur = w.st.mail_cursor(w.aid, "all")
        assert w.st.mail_account_delete(w.aid)
        w.st.mail_cursor_set(flow.Cursor(w.aid, "all", cur["mailbox"], int(cur["uidvalidity"]),
                                         int(cur["last_uid"]) + 5, NOW))
        assert rows(w.st, "SELECT COUNT(*) FROM mail_cursors WHERE account_id=?", w.aid) == [(0,)]


@needs(FLOW)
def test_mail_d158_accepting_a_backfilled_suggestion_applies_it():
    with _World(seeded_at="2026-11-02T11:00:00") as w:
        golden_mail(w.srv)
        run(w.cfg, w.srv, backend=FakeBackend())
        sugg = [s for s in w.st.mail_suggestions(NOW) if s["gm_msgid"] == REJ_ID]
        assert len(sugg) == 1 and sugg[0]["reason"] == "backfilled", sugg
        ms = w.cfg.mail_status
        assert w.st.mail_accept(sugg[0]["id"], None, NOW, ranks=dict(ms.ranks), terminal=ms.terminal) == \
            (True, "ok"), "a backfilled suggestion is the owner's call, not a 409"
        assert statuses(w.st)["nw-analyst"] == "rejected"


@needs(FLOW)
def test_mail_d158_a_poison_message_is_skipped_internal_and_counted():
    from jobscraper.mailstatus.contracts import Reason
    with _World() as w:
        gm = news(w.srv, "1800000000000005001")
        golden_mail(w.srv)
        undo = _failing({gm})
        try:
            rep = run(w.cfg, w.srv, backend=FakeBackend())
        finally:
            undo()
        assert rows(w.st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("skipped", Reason.INTERNAL.value)]
        assert Reason.INTERNAL.value == "internal"
        assert rep.accounts[0].counts["errors"] == 1, rep.accounts[0].counts
        assert statuses(w.st)["nw-analyst"] == "rejected"


# ------------------------------------------------------------------ FL-2 (8): the runner
@needs("jobscraper.web.mailsync:MailSyncRunner")
def test_mail_d157_fl2_runner_env_and_the_timer_skips_paused():
    from jobscraper.store import Store
    from jobscraper.web import mailsync
    env = mailsync.child_env()
    assert all(PASSWORD not in str(v) and "CANARYpw" not in str(v) for v in env.values())
    with memory_keyring():
        cfg = config(tmpdir("d157r_"))
        st = Store(cfg.db_path)
        aid = st.mail_account_add("p@inbox.example", host="imap.gmail.com", port=993,
                                  vault_service="jobscraper:imap:imap.gmail.com", shared_with_apply=False,
                                  consent_version="x", first_sync_from="2026-05-06T00:00:00", now=NOW)
        st.mail_account_set(aid, state="paused", state_code="login_refused")
        st.close()
        calls = []
        runner = mailsync.MailSyncRunner(cfg, Path(cfg.db_path).parent, lambda: Store(cfg.db_path), None,
                                         lambda k, o: calls.append((k, o)) or ["none"])
        assert runner.tick("timer") is False and calls == [], "the timer never retries a pause"


def test_mail_d157_pins_are_live():
    assert_live(FLOW, _W0, "test_mail_d157_pins")


note_waiting("test_mail_d157_pins", _W0)
