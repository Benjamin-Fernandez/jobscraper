"""Q-121 WP-F1 flow oracles, part 2: stops and their outcomes (llm_first_fill_design §4.6, §6, §9;
oracle 10 and the flow side of oracle 6), the audit, the K8 scan, and "strict is unchanged".

The question each pin asks: does this ending reach the right queue outcome? A role returned that
must not be loops; a role lost that must be returned never gets applied; a pause that should not
happen stops the owner's whole queue; a per-role stop that pauses (or the reverse) is wrong.
Same seam as tests/test_always_flow.py (tests/always_flow_support.py): a real OllamaBackend over a
mock transport, the real flow, a counting fake navigator, temp DB, test config, "Example Co".
Verify: python tests/run_tests.py -k always_flow
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import Net, backend, make, nav_class, page, run_batch, run_q  # noqa: E402

from jobscraper import apply_flow  # noqa: E402
from jobscraper.backends import BackendError  # noqa: E402
from jobscraper.apply import always as AL  # noqa: E402
from jobscraper.apply.classify import PageSignal  # noqa: E402
from jobscraper.apply.contracts import AttemptState as ST, QueuePause, ReasonCode as R  # noqa: E402

ALWAYS = {"fill_policy": "always"}
DOB = dict(step="one", field_key="dob", label="Date of Birth", target_path="identity.date_of_birth",
           sensitive=True)


def _queue_state(w):
    st = w.store.queue_pause_state()
    return (st or {}).get("reason"), (st or {}).get("detail"), list(w.store.queue_positions())


# ================================================================== oracle 10: transport vs content failures

def _model_ensurer(*codes, calls=None):
    """A scripted model service: the n-th call answers codes[n] (the last repeats)."""
    n = {"i": 0}

    def ensurer(budget, **kw):
        if calls is not None:
            calls.append(kw)
        code = codes[min(n["i"], len(codes) - 1)]
        n["i"] += 1
        return S.backends.ModelReady(code, started=False, detail="d" if code != "ready" else "")
    return ensurer


def test_a_transport_failure_on_a_page_is_retried_once_then_pauses_model_not_answering_and_returns_the_role():
    """Merged with Q-126 (design ollama_autostart_design section 3): the first `failed/model_unavailable` of a
    role on a real Ollama backend, with no Submit click, restarts the model check and sends the role round ONCE;
    the same role failing again pauses `model_not_answering`, with the role back at the front and nothing sent.
    (Before the merge this was one row and the pause `model_unavailable`: the next pin keeps that path.)"""
    w, cid, jobs = make(2)
    try:
        net = Net(down=True, warm_ok=True)                          # the warm-up works, the page call does not
        script = S.real_page(S.req_numbers("q", 1), "one")
        nav = nav_class()()
        run_q(w, cid, jobs, nav, backend(net), script, **ALWAYS)
        rows = w.attempt_rows()
        assert len(rows) == 2, "one attempt and its one retry, then the queue stopped"
        assert rows[0]["job_id"] == rows[1]["job_id"] == jobs[0], "the SAME role went round again; the next never ran"
        for r in rows:
            assert r["state"] == "failed" and r["reason_code"] == "model_unavailable", (r["state"], r["reason_code"])
            assert r["submit_clicked_at"] is None
        assert nav.submits == 0
        pause, _detail, waiting = _queue_state(w)
        assert pause == QueuePause.MODEL_NOT_ANSWERING.value, pause
        assert set(waiting) == set(jobs) and waiting[0] == jobs[0], "the failed role is back at the front"
    finally:
        w.close()


def test_a_transport_failure_followed_by_a_model_that_is_not_ready_pauses_that_reason_after_one_attempt():
    """The pre-merge assertion, on the path that still gives it: the retry's own model check says `not_running`,
    so the role is returned at once with that pause (`model_unavailable`) and is not sent round."""
    w, cid, jobs = make(2)
    try:
        net = Net(down=True, warm_ok=True)
        calls: list = []
        ens = _model_ensurer("ready", "not_running", calls=calls)   # the check before the take, then the retry's
        run_q(w, cid, jobs, nav_class()(), backend(net), S.real_page(S.req_numbers("q", 1), "one"),
              ensurer=ens, **ALWAYS)
        rows = w.attempt_rows()
        assert len(rows) == 1 and rows[0]["state"] == "failed" and rows[0]["reason_code"] == "model_unavailable"
        assert rows[0]["submit_clicked_at"] is None and len(calls) == 2, len(calls)
        pause, _detail, waiting = _queue_state(w)
        assert pause == QueuePause.MODEL_UNAVAILABLE.value, pause
        assert set(waiting) == set(jobs) and waiting[0] == jobs[0]
    finally:
        w.close()


class _VoteDown:
    """Wraps the page's `ask`: the first model call (the field call) goes through, every later one (a vote:
    confirmation or meaning call) fails at the transport."""
    def __init__(self, ask):
        self.ask, self.n = ask, 0

    def __call__(self, *a, **k):
        self.n += 1
        if self.n > 1:
            raise BackendError("the model is unreachable")
        return self.ask(*a, **k)


def test_f5_a_transport_failure_inside_the_always_vote_is_an_ordinary_failed_row_retried_once():
    """F5 (merge handoff): a transport failure INSIDE the always filler's vote ends the page `model_unavailable`
    (`PageOutcome.transport_failed`) as an ordinary `failed` row during FILLING: no Submit click, so it is retried
    ONCE (by the worker's model retry); failing again it pauses `model_not_answering`; nothing is sent."""
    from llm_fill_t2 import pf
    from jobscraper.apply.contracts import FieldType
    label = "Is your criminal record satisfactory?"            # no canonical reading: the vote must be asked
    waves: list[_VoteDown] = []

    def wrap(ask):
        v = _VoteDown(ask)
        waves.append(v)
        return v

    w, cid, jobs = make(2)
    try:
        field = pf("v1", label, FieldType.RADIO, required=True, options=("Yes", "No"))
        script = S.real_page([field], "one", ask_wrap=wrap)
        nav = nav_class()()
        run_q(w, cid, jobs, nav, backend(Net(chat=S.answering(value="No"))), script, **ALWAYS)
        rows = w.attempt_rows()
        assert waves and max(v.n for v in waves) >= 2, "the vote was never reached: the pin does not test the vote"
        assert len(rows) == 2 and rows[0]["job_id"] == rows[1]["job_id"] == jobs[0], len(rows)
        for r in rows:
            assert r["state"] == "failed" and r["reason_code"] == "model_unavailable", (r["state"], r["reason_code"])
            assert r["submit_clicked_at"] is None
        assert nav.submits == 0
        pause, _d, waiting = _queue_state(w)
        assert pause == QueuePause.MODEL_NOT_ANSWERING.value and set(waiting) == set(jobs), (pause, waiting)
    finally:
        w.close()


def test_f5_a_model_ending_after_the_submit_click_is_never_retried():
    """NF-06: a row with a Submit click is not retried (it could send twice). The worker's retry reads the stored
    row, so even a `model_unavailable` ending that carries `submit_clicked_at` ends the run at once: one row, the
    ensurer asked only before the take (no restart), no second row for any role."""
    from test_q126_worker import _attempts
    w, cid, jobs = make(2)
    try:
        calls: list = []
        with _attempts(lambda j, n: "down_clicked" if j == jobs[0] else "ok") as counts:
            run_q(w, cid, jobs, nav_class()(), backend(Net()), ensurer=_model_ensurer("ready", calls=calls), **ALWAYS)
        rows = w.attempt_rows()
        assert len(rows) == 1 and counts.get(jobs[0]) == 1 and jobs[1] not in counts, (len(rows), counts)
        assert rows[0]["submit_clicked_at"] is not None
        assert len(calls) == 1, "no restart of the model check after a clicked row"
        pause, _d, _w = _queue_state(w)
        assert pause == QueuePause.MODEL_UNAVAILABLE.value, pause
    finally:
        w.close()


def test_a_model_that_died_mid_attempt_is_not_reported_as_a_timeout_under_always():
    """N6a F5 (kept by `_transport_cause`): a model that answers HTTP 500 is "model unavailable",
    not "timed out" (the owner is told to start Ollama, not to wait longer)."""
    w, cid, jobs = make(1)
    try:
        net = Net(down=True, warm_ok=True)
        run_q(w, cid, jobs, nav_class()(), backend(net), S.real_page(S.req_numbers("q", 1), "one"), **ALWAYS)
        r = w.attempt_rows()[0]
        assert r["reason_code"] == "model_unavailable", r["reason_code"]
        assert "timed out" not in (r["reason_detail"] or "").lower(), r["reason_detail"]
    finally:
        w.close()


def test_a_warm_up_that_fails_is_model_unavailable_before_edge_opens_under_both_policies():
    for policy in ("always", "strict"):
        w, cid, jobs = make(1)
        try:
            net = Net(down=True)
            nav = nav_class()()
            _out, fac, _say = run_q(w, cid, jobs, nav, backend(net), fill_policy=policy)
            rows = w.attempt_rows()
            # merged with Q-126: the warm-up failure is retried once (a second row), then `model_not_answering`
            assert len(rows) == 2 and rows[0]["job_id"] == rows[1]["job_id"] == jobs[0], (policy, len(rows))
            for r in rows:
                assert r["state"] == "failed" and r["reason_code"] == "model_unavailable" \
                    and r["step"] == "planning", (policy, r["state"], r["reason_code"], r["step"])
                assert r["submit_clicked_at"] is None
            assert fac.started == 0 and "open" not in nav.calls
            pause, _d, waiting = _queue_state(w)
            assert pause == "model_not_answering" and waiting == jobs, (policy, pause, waiting)
        finally:
            w.close()


def _content_failure_checks(w, jobs):
    rows = w.attempt_rows()
    assert len(rows) == 1, "the queue stopped at the first role"
    r = rows[0]
    assert r["state"] == "failed" and r["reason_code"] == "unanswerable_required", (r["state"], r["reason_code"])
    assert apply_flow.is_content_failure(r), r["reason_detail"]
    assert r["reason_detail"].lower().startswith(apply_flow.FILL_WOULD_BE_GUESSES), r["reason_detail"]
    pause, _d, waiting = _queue_state(w)
    assert pause == QueuePause.FILL_FAILED.value, pause
    assert waiting == jobs[1:], "the role is NOT returned: it would fail the same page on every Resume"
    assert r["submit_clicked_at"] is None
    return r


def test_more_guesses_than_the_page_cap_is_a_content_failure_fill_failed_and_not_returned():
    w, cid, jobs = make(2)
    try:
        nav = nav_class()()
        script = S.real_page(S.req_numbers("q", 6), "one")                  # 6 > last_resort_max 5
        run_q(w, cid, jobs, nav, backend(Net()), script, **ALWAYS)
        _content_failure_checks(w, jobs)
        assert nav.submits == 0
    finally:
        w.close()


def test_the_per_attempt_guess_limit_counts_across_pages_in_the_flow():
    def pages(sizes):
        def script(nav, services, ctx, rctx):
            step = nav.step_id(None, None)
            n = sizes[["one", "two", "three"].index(step)]
            return S.real_page(S.req_numbers(step, n), step)(nav, services, ctx, rctx)
        return script
    w, cid, jobs = make(2)
    try:                                                                    # 5 + 5 + 3 = 13 > 12
        nav = nav_class()(steps=("one", "two", "three", "review"))
        run_q(w, cid, jobs, nav, backend(Net()), pages((5, 5, 3)), **ALWAYS)
        r = _content_failure_checks(w, jobs)
        assert r["step"] == "three", "the first two pages were accepted, the third stopped"
        rows = w.store.answers(r["id"])
        assert {x["step"] for x in rows} == {"one", "two"}, "earlier pages keep their audit rows"
        assert nav.submits == 0
    finally:
        w.close()
    w, cid, jobs = make(1)
    try:                                                                    # 5 + 5 + 2 = 12: fine
        nav = nav_class()(steps=("one", "two", "three", "review"))
        run_q(w, cid, jobs, nav, backend(Net()), pages((5, 5, 2)), **ALWAYS)
        r = w.attempt_rows()[0]
        assert r["state"] == "ready_to_submit", (r["state"], r["reason_code"], r["reason_detail"])
        assert w.store.queue_pause_state() is None
    finally:
        w.close()


def test_an_always_stop_whose_detail_lacks_the_marker_is_given_it():
    w, cid, jobs = make(2)
    try:
        script = S.stop_with(R.UNANSWERABLE_REQUIRED, "Address Line 2", step="one")
        run_q(w, cid, jobs, nav_class()(), backend(Net()), script, **ALWAYS)
        _content_failure_checks(w, jobs)
    finally:
        w.close()


# ================================================================== owner_fact_missing, document_missing (§4.6, §9)

def test_owner_fact_missing_waits_with_a_named_question_and_the_next_role_still_runs():
    w, cid, jobs = make(2)
    try:
        def script(nav, services, ctx, rctx):
            if ctx.job["job_id"] == jobs[0]:
                raise AL.AlwaysStop(R.OWNER_FACT_MISSING, "date of birth", **DOB)
            return page()
        nav = nav_class()()
        run_q(w, cid, jobs, nav, backend(Net()), script, **ALWAYS)
        rows = {r["job_id"]: r for r in w.attempt_rows()}
        assert rows[jobs[0]]["state"] == "failed" and rows[jobs[0]]["reason_code"] == "owner_fact_missing"
        assert rows[jobs[0]]["reason_detail"] == "date of birth (“Date of Birth” on one)",             "F4: the detail names the fact, the form's label and the step"
        assert rows[jobs[1]]["state"] == "ready_to_submit", "the next queued role ran"
        assert w.store.queue_pause_state() is None and not w.store.queue_positions()
        groups = w.store.question_groups("open")
        assert len(groups) == 1, groups
        g = groups[0]
        assert g["labels"] == ["Date of Birth"] and g["reason"] == "profile_gap"
        assert g["target_path"] == "identity.date_of_birth" and g["sensitive"], g
        assert any(c["job_id"] == jobs[0] for c in w.store.retry_candidates()), \
            "after the owner answers, the attempt is a retry candidate"
        assert nav.submits == 0
    finally:
        w.close()


def test_the_same_fact_missing_on_three_roles_in_a_row_is_one_pause_naming_it():
    w, cid, jobs = make(4)
    try:
        run_q(w, cid, jobs, nav_class()(), backend(Net()),
              S.stop_with(R.OWNER_FACT_MISSING, "date of birth", **DOB), **ALWAYS)
        assert len(w.attempt_rows()) == 3, "the fourth role was not started"
        pause, detail, waiting = _queue_state(w)
        assert pause == QueuePause.REPEATED_FAILURES.value and "date of birth" in detail, (pause, detail)
        assert waiting == jobs[3:], "the three finished roles are not returned"
    finally:
        w.close()

    def row(code, detail):
        return {"state": "failed", "reason_code": code, "reason_detail": detail}
    mixed = [row("owner_fact_missing", "date of birth"), row("owner_fact_missing", "gpa"),
             row("owner_fact_missing", "date of birth")]
    assert apply_flow.pause_for(mixed[0], "", mixed) is None, "three different facts: the queue goes on"
    same = [row("owner_fact_missing", "gpa")] * 3
    assert apply_flow.pause_for(same[0], "", same) == (QueuePause.REPEATED_FAILURES,
                                                       "gpa is missing from your profile")
    two = same[:2] + [row("model_unavailable", "")]
    assert apply_flow.pause_for(two[0], "", two) is None, "two in a row are not enough"


def test_document_missing_is_per_role_captures_nothing_and_the_queue_goes_on():
    w, cid, jobs = make(2)
    try:
        def script(nav, services, ctx, rctx):
            if ctx.job["job_id"] == jobs[0]:
                raise AL.AlwaysStop(R.DOCUMENT_MISSING, "transcript", step="one", field_key="t", label="Transcript")
            return page()
        run_q(w, cid, jobs, nav_class()(), backend(Net()), script, **ALWAYS)
        rows = {r["job_id"]: r for r in w.attempt_rows()}
        assert rows[jobs[0]]["reason_code"] == "document_missing", rows[jobs[0]]["reason_code"]
        assert rows[jobs[0]]["reason_detail"] == "transcript (on one)", "F4: the document and the step"
        assert rows[jobs[1]]["state"] == "ready_to_submit"
        assert w.store.question_groups("all") == [], "nothing is asked: the owner has to add the document"
        assert w.store.queue_pause_state() is None
    finally:
        w.close()


# ================================================================== audit and "Answered for you" (§6)

def _assumed_page():
    U = S._u()

    def script(nav, services, ctx, rctx):
        fields = [U.pf("a", "First name"), U.pf("b", "Favourite colour"), U.pf("c", "Years of widget work")]
        answers = {
            "a": dataclasses.replace(U.ans("a", "Alex"), source="profile:identity.first_name"),
            "b": dataclasses.replace(U.ans("b", "Blue"), source="assumption", evidence="no basis in profile",
                                     assumed=True),
            "c": dataclasses.replace(U.ans("c", "3"), source="fallback:F2", assumed=True)}
        return U.outcome("one", fields, answers, assumed=("b", "c"), fallback=("c",))
    return script


def test_every_answer_row_has_a_source_assumed_rows_are_marked_counted_and_offered_for_keep_or_change():
    w, _cid, jobs = make(1)
    try:
        res, _f, say = run_batch(w, jobs, nav_class()(), backend(Net()), _assumed_page(), **ALWAYS)
        r = res[0]
        assert r.state is ST.READY_TO_SUBMIT
        rows = {x["field_key"]: x for x in w.store.answers(r.attempt_id)}
        assert len(rows) == 3 and all(x["source"] for x in rows.values()), rows
        marked = {x["label"] for x in rows.values() if x["assumed"]}
        assert marked == {"Favourite colour", "Years of widget work"}, marked
        assert w.store.assumed_count(r.attempt_id) == 2
        assert w.store.assumed_counts([r.attempt_id, 999]) == {r.attempt_id: 2}
        assert " assumed=2" in say.text, "the attempt summary counts them"
        groups = w.store.question_groups("assumed")
        assert sorted(g["labels"][0] for g in groups) == ["Favourite colour", "Years of widget work"]
        assert all(g["reason"] == "assumed" and g["status"] == "assumed" for g in groups), groups
        assert w.store.question_groups("open") == [], "an assumption is not an open question"
    finally:
        w.close()
    w, _cid, jobs = make(1)                                         # an ordinary page under strict: no marks, no cards
    try:
        res, _f, say = run_batch(w, jobs, nav_class()(), backend(Net()))
        assert w.store.assumed_count(res[0].attempt_id) == 0 and " assumed=" not in say.text
        assert w.store.question_groups("assumed") == []
    finally:
        w.close()


def test_an_always_stop_page_keeps_the_attempt_the_reason_and_the_question_but_no_rows_for_that_page():
    w, _cid, jobs = make(1)
    try:
        def script(nav, services, ctx, rctx):
            if nav.step_id(None, None) == "one":
                return page("one", 2)
            raise AL.AlwaysStop(R.OWNER_FACT_MISSING, "date of birth", **{**DOB, "step": "two"})
        nav = nav_class()(steps=("one", "two", "review"))
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), script, **ALWAYS)
        r = res[0]
        row = w.store.attempt(r.attempt_id)
        assert row["state"] == "failed" and row["reason_code"] == "owner_fact_missing"
        assert row["reason_detail"] == "date of birth (“Date of Birth” on two)" and row["step"] == "two",             row["reason_detail"]
        assert "1990" not in row["reason_detail"] and "Alex" not in row["reason_detail"], "no personal value in the detail"
        rows = w.store.answers(r.attempt_id)
        assert {x["step"] for x in rows} == {"one"} and len(rows) == 2, \
            "the earlier page's rows are kept; the stopped page has none (engineer departure 11)"
        assert "always: owner_fact_missing on two" in say.text
        g = w.store.question_groups("open")[0]                     # the owner can still see WHICH field stopped it
        assert g["labels"] == ["Date of Birth"]
        sight = w.store.conn.execute("SELECT step, label FROM question_sightings").fetchall()
        assert [(s["step"], s["label"]) for s in sight] == [("two", "Date of Birth")]
    finally:
        w.close()


# ================================================================== K8 pre-Submit scan under always

def test_a_pre_submit_hit_gets_one_more_round_then_stops_the_attempt_with_nothing_sent():
    for hits, outcome in ((lambda n: ("one:f0",), "fail"), (lambda n: ("one:f0",) if n == 1 else (), "pass")):
        w, _cid, jobs = make(1)
        try:
            nav = nav_class()()
            res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=False, hits=hits, **ALWAYS)
            r = res[0]
            assert len(say.calls) == 2, "one page fill plus exactly one refill round (on the review page)"
            if outcome == "fail":
                assert r.state is ST.FAILED and r.reason is R.VALIDATION_ERROR and nav.submits == 0, \
                    (r.state, r.reason, nav.submits)
            else:
                assert r.state in (ST.SUBMITTED, ST.SUBMITTED_UNCONFIRMED) and nav.submits == 1
        finally:
            w.close()
    w, _cid, jobs = make(1)                                          # strict: no second round, same stop
    try:
        nav = nav_class()()
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=False, hits=lambda n: ("one:f0",))
        assert res[0].reason is R.VALIDATION_ERROR and nav.submits == 0
        assert len(say.calls) == 1, "strict has no second round"
    finally:
        w.close()


# ================================================================== strict unchanged

def _stop_script():
    U = S._u()

    def script(nav, services, ctx, rctx):
        f = U.pf("addr2", "Address Line 2", required=True)
        return U.outcome("one", [f], {"addr2": U.ans("addr2", None, status=S.AnswerStatus.UNKNOWN,
                                                      note="no profile value")}, unknown_required=("addr2",))
    return script


def test_strict_a_required_unknown_still_stops_on_that_field_and_always_does_not_reinterpret_it():
    seen = {}
    for policy in ("strict", "always"):
        w, _cid, jobs = make(1)
        try:
            res, _f, _say = run_batch(w, jobs, nav_class()(), backend(Net()), _stop_script(), fill_policy=policy)
            r = res[0]
            groups = w.store.question_groups("all")
            seen[policy] = (r.state, r.reason, r.reason_detail,
                            [(g["labels"][0], g["reason"], g["status"]) for g in groups],
                            w.store.assumed_count(r.attempt_id))
        finally:
            w.close()
    assert seen["strict"][:3] == (ST.FAILED, R.UNANSWERABLE_REQUIRED, "Address Line 2"), seen["strict"]
    assert len(seen["strict"][3]) == 1 and seen["strict"][3][0][0] == "Address Line 2"
    assert seen["strict"] == seen["always"], seen


def test_never_twice_and_bot_checks_end_the_same_under_both_policies():
    out = {}
    for policy in ("strict", "always"):
        net = Net()
        be = backend(net)
        w, _cid, jobs = make(1)
        try:
            nav = nav_class()()
            first, _f, _s = run_batch(w, jobs, nav, be, dry_run=False, fill_policy=policy)
            assert first[0].state in (ST.SUBMITTED, ST.SUBMITTED_UNCONFIRMED) and nav.submits == 1
            asked = len(net.log)
            second, _f2, _s2 = run_batch(w, jobs, nav, be, dry_run=False, fill_policy=policy)
            assert second[0].state is ST.FAILED and second[0].reason is R.DUPLICATE, (policy, second[0].reason)
            assert nav.submits == 1 and len(net.log) == asked, "no model call, no second click"
            bots = []
            for sig in (PageSignal.CAPTCHA, PageSignal.BOT_CHALLENGE, PageSignal.TWO_FACTOR):
                w.store.conn.execute("DELETE FROM apply_attempts")
                w.store.conn.execute("DELETE FROM applications")
                w.store.commit()
                n2 = nav_class()()
                res, _f3, _s3 = run_batch(w, jobs, n2, be, dry_run=False, signals=(sig,), fill_policy=policy)
                assert n2.submits == 0
                bots.append((res[0].state, res[0].reason))
            out[policy] = (second[0].reason, bots)
        finally:
            w.close()
    assert out["strict"] == out["always"], out
    assert [b[1] for b in out["strict"][1]] == [R.CAPTCHA, R.BOT_CHALLENGE, R.SMS_OR_2FA], out
