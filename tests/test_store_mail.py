"""WP-T5 oracles: the F-50 store methods (mail_status_design.md 8, 9, 10.2; F-50m/n/s).
Verify: `python tests/run_tests.py -k store_mail`. Temp DB only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import WAITING, assert_live, needs, note_waiting  # noqa: E402
from mail_flow_support import ADDRESS, NOW, rows, seed, statuses, tmpdir  # noqa: E402

_W0 = len(WAITING)
STORE = "jobscraper.store:Store.mail_record"
RECEIVED = "2026-10-26T09:00:00"
RANKS = {"to_apply": 0, "applied": 1, "assessment": 2, "interviewing": 3, "offer": 4}
TERMINAL = ("rejected", "withdrawn")


def _store():
    from jobscraper.store import Store
    st = Store(tmpdir("store_mail_") / "t.db")
    seed(st)
    return st


def _account(st, address=ADDRESS):
    from jobscraper.mailstatus.contracts import CONSENT_VERSION
    return st.mail_account_add(address, vault_service="jobscraper:imap:imap.gmail.com",
                               consent_version=CONSENT_VERSION, first_sync_from="2026-08-01T00:00:00",
                               now=NOW)


def _msg(gm, *, outcome="applied", reason="forward", job_id=None, uid=1, category="acknowledged",
         received=RECEIVED):
    return {"gm_msgid": gm, "gm_thrid": gm, "role": "all", "validity": 600, "uid": uid,
            "received_at": received, "sender_domain": "northwind.example", "outcome": outcome,
            "reason": reason, "category": category, "tier": "rule", "rule_id": "x.y",
            "job_id": job_id, "match_json": {"kind": "strong", "signals": [], "candidates": []}}


def _cur(aid, uid):
    return {"account_id": aid, "role": "all", "mailbox": "[Gmail]/All Mail", "validity": 600,
            "last_uid": uid, "last_scan_at": NOW}


def _ev(frm, to, *, reason="forward", category="acknowledged", job_id=None, candidates=None):
    e = {"subject": "Your application", "quote": "Thank you for applying.", "category": category,
         "tier": "rule", "rule_id": "x.y", "reason": reason, "from_status": frm, "to_status": to}
    if job_id is not None:
        e["job_id"] = job_id
    if candidates is not None:
        e["candidates_json"] = candidates
    return e


def _auto(st, aid, gm="1", *, job="nw-dataeng", frm="to_apply", to="applied", uid=1, now=NOW):
    return st.mail_record(account_id=aid, message=_msg(gm, job_id=job, uid=uid), cursor=_cur(aid, uid),
                          change={"kind": "auto", "job_id": job, "from_status": frm, "to_status": to},
                          evidence=_ev(frm, to), now=now)


def _suggest(st, aid, gm="2", *, job="nw-analyst", frm="interviewing", to="offer", uid=2,
             candidates=None, reason="weak_match", category="offer", now=NOW, received=RECEIVED):
    ev = _ev(frm, to, reason=reason, category=category, job_id=job, candidates=candidates)
    return st.mail_record(account_id=aid, message=_msg(gm, outcome="suggested", reason=reason, uid=uid,
                                                       category=category, received=received),
                          cursor=_cur(aid, uid),
                          change={"kind": "suggest", "job_id": job, "from_status": frm, "to_status": to},
                          evidence=ev, now=now)


@needs(STORE)
def test_store_mail_schema_and_events_carry_by_and_evidence():
    from jobscraper import store
    assert store.SCHEMA_VERSION >= 5
    st = _store()
    aid = _account(st)
    res = _auto(st, aid)
    assert res["outcome"] == "applied" and res["event_id"] and res["evidence_id"]
    ev = st.application_events("nw-dataeng")
    assert ev[-1]["by"] == "mail" and ev[-1]["evidence_id"] == res["evidence_id"]
    assert ev[0]["by"] is None and ev[0]["evidence_id"] is None
    assert statuses(st)["nw-dataeng"] == "applied"
    assert st.application("nw-dataeng")["applied_at"] == RECEIVED[:10], "applied_at = the email date"
    assert st.mail_cursor(aid, "all")["last_uid"] == 1
    for col in ("address", "subject"):
        assert col not in [r[1] for r in st.conn.execute("PRAGMA table_info(mail_messages)")], col


@needs(STORE)
def test_store_mail_record_is_one_transaction():
    """F-50s: the cursor upsert fails -> no message row, no status, event or evidence."""
    st = _store()
    aid = _account(st)
    real = st._mail_cursor_upsert

    def boom(cursor):
        raise RuntimeError("disk full")
    st._mail_cursor_upsert = boom
    try:
        _auto(st, aid)
    except RuntimeError:
        pass
    else:
        raise AssertionError("the failure must propagate")
    st._mail_cursor_upsert = real
    assert rows(st, "SELECT COUNT(*) FROM mail_messages") == [(0,)]
    assert rows(st, "SELECT COUNT(*) FROM mail_evidence") == [(0,)]
    assert statuses(st)["nw-dataeng"] == "to_apply"
    assert len(st.application_events("nw-dataeng")) == 1
    assert st.mail_cursor(aid, "all") is None
    assert _auto(st, aid)["outcome"] == "applied", "the retry stores it"


@needs(STORE)
def test_store_mail_record_rechecks_and_dedupes():
    st = _store()
    aid = _account(st)
    # The owner moved it meanwhile: the AUTO change becomes no_change / owner_newer.
    res = _auto(st, aid, job="nw-analyst", frm="applied", to="assessment")
    assert res == {"outcome": "no_change", "event_id": None, "evidence_id": None}
    assert rows(st, "SELECT outcome, reason FROM mail_messages") == [("no_change", "owner_newer")]
    assert statuses(st)["nw-analyst"] == "interviewing"
    # Stored already: only the cursor moves, nothing is applied twice.
    first = _auto(st, aid, gm="5", uid=5)
    again = st.mail_record(account_id=aid, message=_msg("5", job_id="nw-dataeng", uid=5),
                           cursor=_cur(aid, 9),
                           change={"kind": "auto", "job_id": "nw-dataeng", "from_status": "to_apply",
                                   "to_status": "applied"}, evidence=_ev("to_apply", "applied"), now=NOW)
    assert first["event_id"] and again["event_id"] is None and again["outcome"] == "applied"
    assert st.mail_cursor(aid, "all")["last_uid"] == 9
    assert rows(st, "SELECT COUNT(*) FROM mail_evidence") == [(1,)]
    assert st.mail_seen_many(aid, ["5", "1", "404"]) == {"5", "1"}


@needs(STORE)
def test_store_mail_lease_is_single_flight():
    st = _store()
    run = st.mail_run_begin("timer", 111, NOW, 660)
    assert run and st.mail_run_begin("manual", 222, NOW, 660) is None
    assert st.mail_run_heartbeat(run, NOW)
    later = "2026-11-02T13:00:00"                          # the first one's heartbeat is stale
    run2 = st.mail_run_begin("timer", 333, later, 660)
    assert run2 and run2 != run
    assert rows(st, "SELECT state FROM mail_sync_runs WHERE id = ?", run) == [("abandoned",)]
    assert st.mail_run_heartbeat(run, later) is False, "the abandoned run must stop"
    st.mail_run_end(run2, "ok", "ok", {"scanned": 1}, later)
    assert st.mail_last_run()["state"] == "ok"
    assert st.mail_run_begin("timer", 444, later, 660), "an ended run holds nothing"


@needs(STORE)
def test_store_mail_accept_rechecks_status_owner_and_direction():
    st = _store()
    aid = _account(st)
    ok = _suggest(st, aid)["evidence_id"]
    assert st.mail_accept(ok, None, NOW, ranks=RANKS, terminal=TERMINAL) == (True, "ok")
    assert statuses(st)["nw-analyst"] == "offer"
    ev = st.mail_evidence(ok)
    assert ev["state"] == "accepted" and ev["event_id"] and ev["current_status"] == "offer"
    assert rows(st, "SELECT job_id FROM mail_messages WHERE gm_msgid = '2'") == [("nw-analyst",)]
    assert st.application_events("nw-analyst")[-1]["by"] == "mail"
    assert st.mail_accept(ok, None, NOW, ranks=RANKS, terminal=TERMINAL) == (False, "not_open")
    # The status moved since the email -> changed.
    s2 = _suggest(st, aid, gm="3", uid=3, job="nw-dataeng", frm="to_apply", to="applied")["evidence_id"]
    st.set_application_status("nw-dataeng", "assessment")
    assert st.mail_accept(s2, None, NOW, ranks=RANKS, terminal=TERMINAL) == (False, "changed")
    # Backwards by the ranks -> changed.
    s3 = _suggest(st, aid, gm="4", uid=4, job="nw-dataeng", frm="assessment", to="applied",
                  received="2026-12-01T09:00:00")["evidence_id"]
    assert st.mail_accept(s3, None, NOW, ranks=RANKS, terminal=TERMINAL) == (False, "changed")
    assert st.mail_accept(99999, None, NOW) == (False, "not_found")


@needs(STORE)
def test_store_mail_accept_ambiguous_pick_and_no_target():
    st = _store()
    aid = _account(st)
    cands = [{"job_id": "nw-dataeng", "status": "to_apply"}, {"job_id": "nw-analyst", "status": "interviewing"}]
    amb = _suggest(st, aid, job=None, frm=None, to="rejected", candidates=cands, reason="several_applications",
                   category="rejected")["evidence_id"]
    view = [s for s in st.mail_suggestions(NOW) if s["id"] == amb][0]
    assert {c["job_id"] for c in view["candidates"]} == {"nw-dataeng", "nw-analyst"}
    assert st.mail_accept(amb, None, NOW, ranks=RANKS, terminal=TERMINAL) == (False, "not_found")
    assert st.mail_accept(amb, "someone-else", NOW, ranks=RANKS, terminal=TERMINAL) == (False, "not_found")
    assert st.mail_accept(amb, "nw-dataeng", NOW, ranks=RANKS, terminal=TERMINAL) == (True, "ok")
    assert statuses(st) == {"nw-dataeng": "rejected", "nw-analyst": "interviewing"}
    assert st.mail_evidence(amb)["job_id"] == "nw-dataeng"
    # An unclear suggestion has no target: dismiss only.
    unclear = _suggest(st, aid, gm="7", uid=7, to=None, reason="unclear", category="unknown")["evidence_id"]
    assert st.mail_accept(unclear, None, NOW) == (False, "not_open")
    assert st.mail_dismiss(unclear, NOW) == (True, "ok")
    assert st.mail_dismiss(unclear, NOW) == (False, "not_open")
    assert st.mail_dismiss(424242, NOW) == (False, "not_found")


@needs(STORE)
def test_store_mail_suggestions_go_superseded_when_the_status_moves():
    st = _store()
    aid = _account(st)
    sid = _suggest(st, aid, job="nw-dataeng", frm="to_apply", to="applied")["evidence_id"]
    assert [s["id"] for s in st.mail_suggestions(NOW)] == [sid]
    st.set_application_status("nw-dataeng", "applied")
    assert st.mail_suggestions(NOW) == []
    assert st.mail_evidence(sid)["state"] == "superseded"


@needs(STORE)
def test_store_mail_undo_only_while_latest():
    st = _store()
    aid = _account(st)
    r = _auto(st, aid)
    assert st.mail_undo(r["evidence_id"], NOW) == (True, "ok")
    assert statuses(st)["nw-dataeng"] == "to_apply"
    assert st.application("nw-dataeng")["applied_at"] is None, "applied_at restored"
    assert st.application_events("nw-dataeng")[-1]["by"] is None, "the undo is the owner's act"
    assert st.mail_evidence(r["evidence_id"])["state"] == "undone"
    assert st.mail_undo(r["evidence_id"], NOW) == (False, "not_open")
    assert rows(st, "SELECT COUNT(*) FROM mail_messages WHERE gm_msgid = '1'") == [(1,)], "dedupe kept"
    r2 = _auto(st, aid, gm="8", uid=8, job="nw-analyst", frm="interviewing", to="offer")
    st.set_application_status("nw-analyst", "rejected")
    assert st.mail_undo(r2["evidence_id"], NOW) == (False, "not_latest")
    assert st.mail_evidence_for(["nw-analyst"])[r2["evidence_id"]]["undoable"] is False
    assert st.mail_undo(31337, NOW) == (False, "not_found")


@needs(STORE)
def test_store_mail_delete_relink_and_disconnect_cascade():
    st = _store()
    aid = _account(st)
    auto = _auto(st, aid)["evidence_id"]
    acc = _suggest(st, aid)["evidence_id"]
    st.mail_accept(acc, None, NOW, ranks=RANKS, terminal=TERMINAL)
    open_ = _suggest(st, aid, gm="3", uid=3, job="nw-analyst", frm="offer", to="rejected",
                     category="rejected")["evidence_id"]
    gone = _suggest(st, aid, gm="4", uid=4, job="nw-analyst", frm="offer", to="withdrawn",
                    category="withdrawn")["evidence_id"]
    st.mail_dismiss(gone, NOW)
    assert st.mail_account_delete(aid) is True
    left = dict(rows(st, "SELECT id, account_id FROM mail_evidence"))
    assert set(left) == {auto, acc} and set(left.values()) == {None}, left
    assert rows(st, "SELECT COUNT(*) FROM mail_messages") == [(0,)]
    assert rows(st, "SELECT COUNT(*) FROM mail_cursors") == [(0,)]
    assert st.mail_account(aid) is None and st.mail_account_delete(aid) is False
    assert open_ not in left
    # delete_application: evidence goes with the history; message rows stay unlinked.
    aid2 = _account(st, "second@inbox.example")
    _auto(st, aid2, gm="11", uid=11, job="nw-dataeng", frm="applied", to="assessment")
    assert st.delete_application("nw-dataeng")
    assert rows(st, "SELECT COUNT(*) FROM mail_evidence WHERE job_id = 'nw-dataeng'") == [(0,)]
    assert rows(st, "SELECT job_id FROM mail_messages WHERE gm_msgid = '11'") == [(None,)]


@needs(STORE)
def test_store_mail_relink_moves_evidence_and_threads():
    st = _store()
    aid = _account(st)
    url = "https://boards.greenhouse.io/northwind/jobs/9999"
    st.conn.execute("INSERT INTO applications (job_id, status, url, company, role, updated_at) "
                    "VALUES ('v1-orphan', 'applied', ?, 'Northwind', 'Graduate Analyst', ?)", (url, NOW))
    st.conn.commit()
    _auto(st, aid, gm="21", uid=21, job="v1-orphan", frm="applied", to="assessment")
    cid = st.conn.execute("SELECT id FROM companies WHERE key='northwind'").fetchone()[0]
    st.conn.execute("INSERT INTO jobs (job_id, company_id, title, url) VALUES ('nw-new', ?, 'Graduate Analyst', ?)",
                    (cid, url))
    st.conn.commit()
    assert st.relink_orphan_applications() == 1
    assert rows(st, "SELECT DISTINCT job_id FROM mail_evidence") == [("nw-new",)]
    assert rows(st, "SELECT job_id FROM mail_messages WHERE gm_msgid = '21'") == [("nw-new",)]


@needs(STORE)
def test_store_mail_purge_windows():
    st = _store()
    aid = _account(st)
    old = "2026-01-01T00:00:00"
    st.mail_record(account_id=aid, message=_msg("31", outcome="unmatched", reason="no_application", uid=31),
                   cursor=_cur(aid, 31), now=old)
    st.mail_record(account_id=aid, message=_msg("32", outcome="skipped", reason="bulk", uid=32),
                   cursor=_cur(aid, 32), now=NOW)
    st.mail_record(account_id=aid, message=_msg("33", outcome="no_change", reason="same_status",
                                                 job_id="nw-analyst", uid=33), cursor=_cur(aid, 33), now=old)
    d = _suggest(st, aid, gm="34", uid=34, now=old)["evidence_id"]
    st.mail_dismiss(d, "2026-07-01T00:00:00")
    o = _suggest(st, aid, gm="35", uid=35, now=old)["evidence_id"]
    got = st.mail_purge(NOW)
    assert got["messages"] >= 1 and got["suggestions"] == 1, got
    left = {r[0] for r in rows(st, "SELECT gm_msgid FROM mail_messages")}
    assert "31" not in left and {"32", "33"} <= left, left
    ev = {r[0] for r in rows(st, "SELECT id FROM mail_evidence")}
    assert d not in ev and o in ev


def test_store_mail_oracles_are_live():
    assert_live(STORE, _W0, "test_store_mail")


note_waiting("test_store_mail", _W0)
