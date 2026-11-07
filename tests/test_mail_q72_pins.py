"""Q-72 a (D-161): the ten "Row 7a oracles" of mail_status_design.md section 16, as tests.
Verify: `python tests/run_tests.py -k mail_q72`.

Expected values come from the design (MS 3, 8 row 7a and its note, 16), not from the build. Until
the engineer's lane (eng/Q-72-untracked) merges, the 7a cases fail with a plain message (there is
no `Reason.MAYBE_UNTRACKED`, and `decide` answers NONE `terminal`); the oracles that say "unchanged"
(3-6, 8 except its first half, 9, 10) pass both before and after, and guard the rows that must not move.

Fixture (MS 16): three Acme applications, `rejected` by the owner on 2026-10-13 (`owner_changed_at` =
`last_event_at` = that day), Workday mail from Acme with employer signals only. For an AMBIGUOUS
match these tests pass the first candidate as `app` and every candidate as `candidates`, as
test_mail_transition does.

Oracle -> test (the flow cases use the Northwind world of mail_flow_support, standing in for Acme):
 1  test_q72_o1_*            2  test_q72_o2_* (pure) and test_q72_o2_flow_*
 3  test_q72_o3_*            4  test_q72_o4_*            5  test_q72_o5_*
 6  test_q72_o6_*            7  test_q72_o7_*            8  test_q72_o8_*
 9  test_q72_o9_* (pure) and test_q72_o9_flow_*          10 test_q72_o10_*
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    TRANSITION, WAITING, FakeMailServer, app_candidate, assert_live, build_policy, decide, eml,
    golden_statuses, make_eml, needs, note_waiting, unit_header,
)
from mail_flow_support import (  # noqa: E402
    NW_NEWS, FakeBackend, config, connect, memory_keyring, rows, run, seed, statuses, tmpdir,
)

_W0 = len(WAITING)
FLOW = "jobscraper.mailstatus_flow:sync"
OWNER = "2026-10-13T09:00:00"            # the owner closed all three on this day
ACK_AT = "2026-11-02T01:00:00"           # the D-160 acknowledgement
REJ_AT = "2026-11-03T01:00:00"           # the D-160 rejection
EMPLOYER_ONLY = ("employer_domain", "tenant", "name_in_subject", "name_in_body")
ROLES = ("DevOps Engineer", "Data Analyst", "Software Engineer")


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


def _acme(n=1, status="rejected", **kw):
    d = dict(job_id=f"acme-{n}", status=status, company_names=("Acme",), role=ROLES[(n - 1) % 3] + " (old)",
             employer_domains=("acme.example",), tenants=("acme",), owner_changed_at=OWNER,
             last_event_at=OWNER)
    first = kw.pop("first_event_at", "2026-10-01T09:00:00")
    d.update(kw)
    return dataclasses.replace(app_candidate(d), first_event_at=first)


def _closed(k=3):
    return [_acme(n) for n in range(1, k + 1)]


def _h(received_at):
    h, _b = unit_header("Acme Careers <no-reply@acme.example>", "Thank you for applying", "Hello.")
    return dataclasses.replace(h, received_at=received_at)


def _v(category, status_words=True):
    c = _c()
    return c.Verdict(c.Category(category), c.Tier.RULE, quote="Quoted sentence.", rule_id="x.y",
                     status_words=status_words, model="")


def _m(apps, kind=None, signals=EMPLOYER_ONLY):
    c = _c()
    sig = tuple(c.Signal(s) for s in signals)
    if kind is None:
        kind = "ambiguous" if len(apps) > 1 else "strong"
    if kind == "ambiguous":
        return c.MatchResult(c.MatchKind.AMBIGUOUS, None, tuple(a.job_id for a in apps), sig)
    return c.MatchResult(c.MatchKind(kind), apps[0].job_id, (), sig)


def _decide(apps, category, *, at=ACK_AT, kind=None, signals=EMPLOYER_ONLY, status_words=True,
            policy=None):
    return decide(apps[0], _v(category, status_words), _m(apps, kind, signals), _h(at),
                  policy or build_policy(), candidates=tuple(apps))


def _is(ch, kind, reason, to="<any>"):
    got = (ch.kind.value, ch.reason.value)
    assert got == (kind, reason), f"{got} != {(kind, reason)} ({ch})"
    if to != "<any>":
        assert ch.to_status == to, f"to_status {ch.to_status!r} != {to!r} ({ch})"


def _untracked(ch):
    _is(ch, "suggest", "maybe_untracked", to=None)


def _terminal(ch):
    _is(ch, "none", "terminal")


def _offered(apps, category, at=ACK_AT, kind=None):
    """The candidates row 4 would offer (transition.remaining_candidates)."""
    from jobscraper.mailstatus import transition
    return [a.job_id for a in transition.remaining_candidates(
        apps[0], _v(category), _m(apps, kind), _h(at), build_policy(), candidates=tuple(apps))]


# ------------------------------------------------------------------ the contract (MS 3)

def test_q72_contract_has_the_reason_its_text_and_is_a_suggestion():
    c = _c()
    assert hasattr(c.Reason, "MAYBE_UNTRACKED"), \
        "contracts.Reason.MAYBE_UNTRACKED missing (MS 3, D-161): waiting for eng/Q-72-untracked"
    r = c.Reason.MAYBE_UNTRACKED
    assert r.value == "maybe_untracked"
    assert r in c.SUGGEST_REASONS and r not in c.SKIP_REASONS
    assert c.REASON_TEXTS[r] == "This email may be about an application you haven't added."
    assert c.CONTRACT_VERSION == 1, "D-161: CONTRACT_VERSION stays 1"


# ------------------------------------------------------------------ 1

@needs(TRANSITION)
def test_q72_o1_the_d160_acknowledgement_over_three_closed_applications_asks_a_question():
    apps = _closed(3)
    _untracked(_decide(apps, "acknowledged", at=ACK_AT, kind="ambiguous"))
    # MS 8 7a note: `remaining_candidates` still returns () for it (row 4 offers none; the flow
    # stores the matcher's candidates, pinned in test_q72_o1_flow_*).
    assert _offered(apps, "acknowledged", kind="ambiguous") == []
    assert _offered(apps, "rejected", at=REJ_AT, kind="ambiguous") == []


# ------------------------------------------------------------------ 2

@needs(TRANSITION)
def test_q72_o2_a_single_closed_application_gives_the_same_reason():
    for kind in ("strong", "weak"):                       # MS 8 row 7a: STRONG or WEAK
        _untracked(_decide([_acme(1)], "acknowledged", kind=kind))


@needs(FLOW)
def test_q72_o2_flow_stores_a_suggestion_with_no_target_and_leaves_the_message_unattached():
    with _World() as w:
        gm = "1800000000000007201"
        ack = make_eml(NW_NEWS[0], "Thank you for applying to Northwind Traders",
                       "Hi Alex, thank you for applying for the Graduate Platform Engineer role at "
                       "Northwind Traders. Our team will review your application and contact you if "
                       "your experience matches our needs.", date="Mon, 02 Nov 2026 09:00:00 +0800")
        w.srv.deliver(ack, gm_msgid=gm, gm_thrid=gm)
        rep = run(w.cfg, w.srv, backend=FakeBackend(), now=w.now)
        counts = rep.accounts[0].counts
        assert counts["suggested"] == 1 and counts["applied"] == 0, counts
        ev = rows(w.st, "SELECT job_id, from_status, to_status, kind, state, reason, category, candidates_json "
                        "FROM mail_evidence WHERE gm_msgid=?", gm)
        assert len(ev) == 1, ev
        job_id, frm, to, kind, state, reason, category, cj = ev[0]
        assert (job_id, frm, to, kind, state) == (None, None, None, "suggestion", "open"), ev
        assert (reason, category) == ("maybe_untracked", "acknowledged"), ev
        cands = json.loads(cj)
        assert [(x["job_id"], x["status"]) for x in cands] == [("nw-dataeng", "rejected")], cands
        msg = rows(w.st, "SELECT job_id, outcome, reason FROM mail_messages WHERE gm_msgid=?", gm)
        assert msg == [(None, "suggested", "maybe_untracked")], \
            f"mail_messages.job_id must stay NULL so the thread never attaches (MS 8 note): {msg}"
        assert statuses(w.st) == {"nw-dataeng": "rejected"}, "a suggestion changes nothing"
        sugg = w.st.mail_suggestions(w.now)
        assert len(sugg) == 1 and sugg[0]["reason"] == "maybe_untracked" and sugg[0]["to_status"] is None
        assert [x["job_id"] for x in sugg[0]["candidates"]] == ["nw-dataeng"], sugg
        # The thread is not attached, so a later rejection in the same thread is not silent either.
        w.srv.deliver(eml("rej_not_move_forward.eml"), gm_msgid="1800000000000007202", gm_thrid=gm)
        rep2 = run(w.cfg, w.srv, backend=FakeBackend(), now="2026-11-02T13:00:00")
        assert rep2.accounts[0].counts["suggested"] == 1, rep2.accounts[0].counts
        again = rows(w.st, "SELECT reason, job_id FROM mail_evidence WHERE gm_msgid=?", "1800000000000007202")
        assert again == [("maybe_untracked", None)], again


_ACK = ("Hi Alex, thank you for applying for the Graduate Platform Engineer role at Northwind Traders. "
        "Our team will review your application and contact you if your experience matches our needs.")


def _ack_mail(srv, gm="1800000000000007301"):
    srv.deliver(make_eml(NW_NEWS[0], "Thank you for applying to Northwind Traders", _ACK,
                         date="Mon, 02 Nov 2026 09:00:00 +0800"), gm_msgid=gm, gm_thrid=gm)
    return gm


@needs(FLOW)
def test_q72_o1_flow_three_closed_applications_store_one_suggestion_offering_all_three():
    with _World(three=True) as w:
        assert statuses(w.st) == {"nw-dataeng": "rejected", "nw-analyst": "rejected", "nw-cloud": "rejected"}
        gm = _ack_mail(w.srv)
        rep = run(w.cfg, w.srv, backend=FakeBackend(), now=w.now)
        counts = rep.accounts[0].counts
        assert counts["suggested"] == 1 and counts["applied"] == 0, counts
        msg = rows(w.st, "SELECT job_id, outcome, reason, match_json FROM mail_messages WHERE gm_msgid=?", gm)
        assert len(msg) == 1 and msg[0][:3] == (None, "suggested", "maybe_untracked"), msg
        mj = json.loads(msg[0][3])
        assert mj["kind"] == "ambiguous" and "role" not in mj["signals"] and "req_id" not in mj["signals"], mj
        ev = rows(w.st, "SELECT job_id, from_status, to_status, kind, state, reason, candidates_json "
                        "FROM mail_evidence WHERE gm_msgid=?", gm)
        assert len(ev) == 1 and ev[0][:6] == (None, None, None, "suggestion", "open", "maybe_untracked"), ev
        cands = json.loads(ev[0][6])
        assert sorted((x["job_id"], x["status"]) for x in cands) == \
            [("nw-analyst", "rejected"), ("nw-cloud", "rejected"), ("nw-dataeng", "rejected")], cands
        sugg = w.st.mail_suggestions(w.now)
        assert len(sugg) == 1 and sorted(x["job_id"] for x in sugg[0]["candidates"]) == \
            ["nw-analyst", "nw-cloud", "nw-dataeng"], sugg


def _snapshot(st):
    return (rows(st, "SELECT job_id, status FROM applications ORDER BY job_id"),
            rows(st, "SELECT job_id, from_status, to_status, by, at FROM app_events ORDER BY id"))


@needs(FLOW)
def test_q72_f2_flow_a_maybe_untracked_suggestion_cannot_be_accepted_only_dismissed():
    with _World(three=True) as w:
        gm = _ack_mail(w.srv)
        run(w.cfg, w.srv, backend=FakeBackend(), now=w.now)
        eid = rows(w.st, "SELECT id FROM mail_evidence WHERE gm_msgid=?", gm)[0][0]
        before = _snapshot(w.st)
        ranks = {"to_apply": 0, "applied": 1, "assessment": 2, "interviewing": 3, "offer": 4}
        terminal = ("rejected", "withdrawn")
        for job in (None, "nw-dataeng", "nw-cloud"):         # with or without a candidate picked
            assert w.st.mail_accept(eid, job, w.now, ranks=ranks, terminal=terminal) == (False, "not_open"), job
        assert rows(w.st, "SELECT state FROM mail_evidence WHERE id=?", eid) == [("open",)]
        assert _snapshot(w.st) == before, "a refused accept must change nothing"
        assert w.st.mail_dismiss(eid, w.now) == (True, "ok")
        assert rows(w.st, "SELECT state FROM mail_evidence WHERE id=?", eid) == [("dismissed",)]
        assert not w.st.mail_suggestions(w.now)
        assert _snapshot(w.st) == before, "Got it changes no application and writes no event"
        assert rows(w.st, "SELECT job_id FROM mail_messages WHERE gm_msgid=?", gm) == [(None,)]


# ------------------------------------------------------------------ 3, 4

@needs(TRANSITION)
def test_q72_o3_a_role_or_req_id_in_the_mail_keeps_a_late_duplicate_silent():
    apps = _closed(3)
    for sig in ("role", "req_id"):
        _terminal(_decide(apps, "acknowledged", kind="ambiguous", signals=EMPLOYER_ONLY + (sig,)))
        _terminal(_decide([apps[0]], "acknowledged", signals=EMPLOYER_ONLY + (sig,)))


@needs(TRANSITION)
def test_q72_o4_a_thread_signal_keeps_it_silent():
    apps = _closed(3)
    _terminal(_decide(apps, "acknowledged", kind="ambiguous", signals=("thread",) + EMPLOYER_ONLY))
    _terminal(_decide([apps[0]], "acknowledged", signals=("thread",)))


# ------------------------------------------------------------------ 5

@needs(TRANSITION)
def test_q72_o5_an_open_sibling_means_7a_never_fires():
    sibling = _acme(4, "applied", last_event_at="2026-10-20T09:00:00", owner_changed_at="2026-10-20T09:00:00")
    # The ack: the sibling is already `applied` -> same_status. NONE with the first candidate's reason.
    _is(_decide([sibling] + _closed(3), "acknowledged", kind="ambiguous"), "none", "same_status")
    _is(_decide(_closed(3) + [sibling], "acknowledged", kind="ambiguous"), "none", "terminal")
    # The rejection: the sibling would move to `rejected` -> several_applications, offering it (only it).
    apps = _closed(3) + [sibling]
    _is(_decide(apps, "rejected", at=REJ_AT, kind="ambiguous"), "suggest", "several_applications",
        to="rejected")
    assert _offered(apps, "rejected", at=REJ_AT, kind="ambiguous") == ["acme-4"]


# ------------------------------------------------------------------ 6

@needs(TRANSITION)
def test_q72_o6_mail_not_newer_than_every_candidates_last_event_stays_silent():
    newer_event = "2026-11-02T09:00:00"                      # after ACK_AT
    for last in (newer_event, ACK_AT):                       # later than, and equal to, the mail
        apps = _closed(3)
        apps[2] = dataclasses.replace(apps[2], last_event_at=last)       # owner_changed_at stays 10-13
        _terminal(_decide(apps, "acknowledged", kind="ambiguous"))
        _terminal(_decide([apps[2]], "acknowledged"))
    # The control: strictly newer than every event is still the question.
    apps = _closed(3)
    apps[2] = dataclasses.replace(apps[2], last_event_at="2026-11-02T00:59:59")
    _untracked(_decide(apps, "acknowledged", kind="ambiguous"))


# ------------------------------------------------------------------ 7

@needs(TRANSITION)
def test_q72_o7_the_d160_rejection_asks_unless_a_role_is_named():
    apps = _closed(3)
    _untracked(_decide(apps, "rejected", at=REJ_AT, kind="ambiguous"))
    _untracked(_decide([apps[0]], "rejected", at=REJ_AT))
    _terminal(_decide(apps, "rejected", at=REJ_AT, kind="ambiguous", signals=EMPLOYER_ONLY + ("role",)))
    _terminal(_decide([apps[0]], "rejected", at=REJ_AT, signals=EMPLOYER_ONLY + ("req_id",)))


# ------------------------------------------------------------------ 8

@needs(TRANSITION)
def test_q72_o8_other_categories_are_unchanged():
    apps = _closed(3)
    for cat in ("withdrawn", "posting_closed", "kept_on_file"):
        _terminal(_decide(apps, cat, at=REJ_AT, kind="ambiguous"))
        _terminal(_decide([apps[0]], cat, at=REJ_AT))
    for kind_apps, kind in ((apps, "ambiguous"), ([apps[0]], None)):
        _is(_decide(kind_apps, "no_change", kind=kind), "none", "no_update")                  # row 1
        _is(_decide(kind_apps, "unknown", status_words=False, kind=kind), "none", "no_status_words")  # row 2
    # `unknown` WITH status words is row 2's `unclear`, not 7a.
    _is(_decide([apps[0]], "unknown", status_words=True), "suggest", "unclear", to=None)


@needs(TRANSITION)
def test_q72_o8_interview_on_the_same_fixture_is_the_reopen_path_not_7a():
    apps = _closed(3)
    _is(_decide(apps, "interview", kind="ambiguous"), "suggest", "several_applications",
        to="interviewing")                                                              # row 4
    assert _offered(apps, "interview", kind="ambiguous") == ["acme-1", "acme-2", "acme-3"]
    _is(_decide([apps[0]], "interview"), "suggest", "reopen", to="interviewing")        # row 7
    for cat in ("assessment", "offer"):                  # MS note: never silent, never 7a
        got = _decide(apps, cat, kind="ambiguous")
        assert got.reason.value == "several_applications", got
        assert _decide([apps[0]], cat).reason.value == "reopen"


# ------------------------------------------------------------------ 9

def _devops(status="applied", **kw):
    """The row the owner adds afterwards: first event (and owner change) after the mail."""
    return _acme(4, status, role="DevOps Engineer", first_event_at="2026-11-04T09:00:00",
                 owner_changed_at="2026-11-04T09:00:00", last_event_at="2026-11-04T09:00:00", **kw)


@needs(TRANSITION)
def test_q72_o9_adding_the_application_afterwards_is_unchanged():
    d = _devops()
    _is(_decide([d], "acknowledged", signals=EMPLOYER_ONLY + ("role", "req_id")), "none", "owner_newer")
    _is(_decide([d], "rejected", at=REJ_AT, signals=EMPLOYER_ONLY + ("role", "req_id")),
        "suggest", "backfilled", to="rejected")


class _World:
    """The Northwind world with ONE closed application (stands in for Acme), or the golden pair."""
    def __init__(self, *, golden_pair=False, three=False):
        self.golden_pair, self.three, self.now = golden_pair, three, "2026-11-02T12:00:00"

    def __enter__(self):
        from jobscraper.store import Store
        self._kr = memory_keyring()
        self._kr.__enter__()
        self.cfg = config(tmpdir("q72_"))
        self.st = Store(self.cfg.db_path)
        seed(self.st, at="2026-09-15T09:00:00")
        self.srv = FakeMailServer()
        res, self.aid = connect(self.cfg, self.srv)
        assert res == "ok", res
        self.st.mail_account_set(self.aid, first_sync_from="2026-09-14T00:00:00")
        if self.three:                       # the D-160 shape: three applications at one employer, all closed
            cid = self.st.conn.execute("SELECT id FROM companies WHERE key='northwind'").fetchone()[0]
            self.st.conn.execute("INSERT INTO jobs (job_id, company_id, title, url) VALUES (?,?,?,?)",
                                 ("nw-cloud", cid, "Graduate Cloud Analyst",
                                  "https://boards.greenhouse.io/northwind/jobs/3333"))
            self.st.conn.commit()
            self.st.set_application_status("nw-cloud", "to_apply", company="Northwind Traders Pte Ltd",
                                           role="Graduate Cloud Analyst")
            for j in ("nw-dataeng", "nw-analyst", "nw-cloud"):
                self.st.set_application_status(j, "rejected")
            self.st.conn.execute("UPDATE app_events SET at=?", (OWNER,))
            self.st.conn.commit()
        elif not self.golden_pair:
            self.st.conn.execute("DELETE FROM app_events WHERE job_id='nw-analyst'")
            self.st.conn.execute("DELETE FROM applications WHERE job_id='nw-analyst'")
            self.st.set_application_status("nw-dataeng", "rejected")
            self.st.conn.execute("UPDATE app_events SET at=?", (OWNER,))
            self.st.conn.commit()
        return self

    def __exit__(self, *exc):
        self.st.close()
        self._kr.__exit__(*exc)


@needs(FLOW)
def test_q72_o9_flow_backfilled_retest_is_unchanged():
    """Golden mail (ack 20 Oct for nw-dataeng, rejection 1 Nov for nw-analyst); the owner then adds
    both as `applied` (first event 2 Nov, after the mail): ack -> owner_newer, rejection -> backfilled."""
    with _World(golden_pair=True) as w:
        w.st.set_application_status("nw-dataeng", "applied")
        w.st.set_application_status("nw-analyst", "applied")
        w.st.conn.execute("UPDATE app_events SET at='2026-11-02T11:00:00'")
        w.st.conn.commit()
        w.srv.deliver(eml("ack_gh_saved_role.eml"), gm_msgid="1800000000000001001", gm_thrid="1800000000000001001")
        w.srv.deliver(eml("rej_not_move_forward.eml"), gm_msgid="1800000000000001019", gm_thrid="1800000000000001019")
        run(w.cfg, w.srv, backend=FakeBackend(), now=w.now)
        assert statuses(w.st) == {"nw-dataeng": "applied", "nw-analyst": "applied"}
        ack = rows(w.st, "SELECT outcome, reason FROM mail_messages WHERE gm_msgid='1800000000000001001'")
        assert ack and ack[0][1] == "owner_newer", ack
        assert not rows(w.st, "SELECT 1 FROM mail_evidence WHERE gm_msgid='1800000000000001001'")
        sugg = [s for s in w.st.mail_suggestions(w.now) if s["gm_msgid"] == "1800000000000001019"]
        assert len(sugg) == 1 and sugg[0]["reason"] == "backfilled" and sugg[0]["to_status"] == "rejected", sugg
        assert not [s for s in w.st.mail_suggestions(w.now) if s["reason"] == "maybe_untracked"]


# ------------------------------------------------------------------ 10

@needs(TRANSITION)
def test_q72_o10_an_owner_added_status_is_custom_status_not_7a():
    p = build_policy(statuses=list(golden_statuses()) + ["on_hold"])
    held = _acme(5, "on_hold")
    _is(_decide([held], "acknowledged", policy=p), "suggest", "custom_status", to="applied")
    _is(_decide([held], "rejected", at=REJ_AT, policy=p), "suggest", "custom_status", to="rejected")
    mixed = [held] + _closed(2)
    got = _decide(mixed, "acknowledged", kind="ambiguous", policy=p)
    assert got.reason.value == "several_applications", f"row 5 keeps its candidate in, so 7a is out: {got}"


def test_mail_q72_oracles_are_live():
    assert_live(TRANSITION, _W0, "test_mail_q72_pins")


note_waiting("test_mail_q72_pins", _W0)
