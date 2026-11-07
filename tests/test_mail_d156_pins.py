"""Pins for the lane F open questions decided in D-156 (instructions/02_status.md; Q-60).
Verify: `python tests/run_tests.py -k mail_d156`.

1. `config.as_bool` and `transition.as_bool` (two copies: layering forbids one import) agree.
2. (`retry_after` vs Check now: superseded by D-157 (e), pinned in test_mail_d157_pins.py.)
3. `model: false`: mail the rules can't decide becomes an `unclear` suggestion, with no model call
   and no pending row.
4. An ambiguous unclear or portal suggestion lists every candidate application.
FakeMailServer + temp DB + in-memory keyring; no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import WAITING, FakeMailServer, assert_live, needs, note_waiting  # noqa: E402
from mail_flow_support import (  # noqa: E402
    FakeBackend, config, connect, memory_keyring, news, rows, run, seed, tmpdir,
)

_W0 = len(WAITING)
FLOW = "jobscraper.mailstatus_flow:sync"
NOW = "2026-11-02T12:00:00"
PORTAL = ("There is a new message in your candidate portal about your application to Northwind "
          "Traders. Please log in to view it.")


class _World:
    def __init__(self, mail_status=None):
        self.mail_status = mail_status

    def __enter__(self):
        from jobscraper.store import Store
        self._kr = memory_keyring()
        self._kr.__enter__()
        self.cfg = config(tmpdir("d156_"), self.mail_status)
        self.st = Store(self.cfg.db_path)
        seed(self.st)
        self.srv = FakeMailServer()
        res, self.aid = connect(self.cfg, self.srv)
        assert res == "ok", res
        return self

    def __exit__(self, *exc):
        self.st.close()
        self._kr.__exit__(*exc)


@needs("jobscraper.config:as_bool", "jobscraper.mailstatus.transition:as_bool")
def test_mail_d156_both_as_bool_copies_agree():
    from jobscraper.config import as_bool as a
    from jobscraper.mailstatus.transition import as_bool as b
    values = [True, False, 0, 1, -1, 2, 0.0, 0.5, "", " ", "true", "True", "TRUE", " true ", "yes",
              "y", "t", "on", "1", "false", "False", "no", "n", "f", "off", "0", "00", "1.0",
              "nope", "maybe", "enabled", None, [], {}, [0], b"false", "\tfalse\n"]
    for v in values:
        for d in (True, False):
            assert a(v, d) == b(v, d), (v, d, a(v, d), b(v, d))
            assert isinstance(a(v, d), bool), (v, d)
    assert a("false", True) is False and a("yes", False) is True and a("maybe", True) is True


@needs(FLOW)
def test_mail_d156_model_false_makes_an_unclear_suggestion_without_a_call():
    with _World({"model": False}) as w:
        gm = news(w.srv, "1800000000000003001")
        be = FakeBackend()
        rep = run(w.cfg, w.srv, backend=be)
        assert be.calls == [] and rep.accounts[0].counts["pending_model"] == 0, rep
        assert rows(w.st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid=?", gm) == \
            [("suggested", "unclear")]
        assert w.st.mail_pending(w.aid, NOW, 3) == []
        assert rows(w.st, "SELECT COUNT(*) FROM mail_messages WHERE outcome='pending_model'") == [(0,)]


@needs(FLOW)
def test_mail_d156_an_ambiguous_unclear_or_portal_suggestion_lists_every_candidate():
    with _World({"model": False}) as w:
        unclear = news(w.srv, "1800000000000003002")
        portal = news(w.srv, "1800000000000003003", subject="New message in your portal", body=PORTAL)
        run(w.cfg, w.srv, backend=FakeBackend())
        got = {}
        for gm in (unclear, portal):
            r = rows(w.st, "SELECT e.reason, e.job_id, e.candidates_json FROM mail_evidence e "
                           "WHERE e.gm_msgid=?", gm)
            assert len(r) == 1, (gm, r)
            reason, job_id, cands = r[0]
            got[gm] = reason
            ids = sorted(c["job_id"] if isinstance(c, dict) else c for c in json.loads(cands or "[]"))
            assert ids == ["nw-analyst", "nw-dataeng"], (gm, reason, ids)
            assert job_id is None, "the system never picks one for an ambiguous suggestion"
        assert got[unclear] == "unclear" and got[portal] in ("portal_check", "unclear"), got
        listed = {s["gm_msgid"]: s for s in w.st.mail_suggestions(NOW)}
        for gm in (unclear, portal):
            assert {c["job_id"] for c in listed[gm]["candidates"]} == {"nw-analyst", "nw-dataeng"}


def test_mail_d156_pins_are_live():
    assert_live(FLOW, _W0, "test_mail_d156_pins")


note_waiting("test_mail_d156_pins", _W0)
