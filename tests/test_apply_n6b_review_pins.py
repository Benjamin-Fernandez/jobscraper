"""Q-35 N6b review F1 (docs/reviews/Q-35-N6b.md): the paths of the auto-mode llm route that must
never press Submit. Fixtures and scripted pages only: no model, no network, no browser.

  (a) `page.scan_required` raising in auto mode fails closed (`validation_error`,
      "review: could not check the required fields"), Submit never called, `submit_clicked_at`
      empty; a dry run (which sends nothing) still ends `ready_to_submit`;
  (b) the daily and the per-employer caps (D-61): refused before the browser when already
      reached, refused by `claim_click` when another click lands after the guards; either way
      `cap_reached`, no Submit, `submit_clicked_at` empty; one click under the cap still submits
      (the control that keeps (b) from passing vacuously);
  (c) the "required text values not shown" log line holds a count only, never a value;
  (d) a bot check or CAPTCHA that replaces the review page after the last Next ends as
      `bot_challenge` / `captcha` (review F2: `check_page` before the pre-Submit scan), the scan
      and Submit never run, nothing is solved.
"""
from __future__ import annotations

import contextlib
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402
from test_apply_flow_llm import N6B_GATE  # noqa: E402
from test_apply_flow_n6b import _scan, _script, _submit_nav, _two_steps, _unit  # noqa: E402

PRIVATE_PHONE = "+65 9123 4567"
PRIVATE_DIGITS = ("91234567", "9123 4567", "9123-4567")
SCAN_BOOM = "boom: reader exploded near 98765432"


def _go(w, jid, nav, *, dry_run, apply_over=None, when=None):
    """One attempt over the FakeNav world with the classifier scripted by `when(page)`
    (None = OK). Returns (result, say)."""
    from apply_flow_support import FakeBrowserFactory, Say, page_signals
    from jobscraper import apply_flow
    from test_apply_flow_llm import _registered
    U = _unit()
    factory, say = FakeBrowserFactory(), Say()
    acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0, **(apply_over or {}))
    with _registered(nav), page_signals(when=when) if when else page_signals():
        res = apply_flow.run(w.cfg, w.store, [jid], dry_run=dry_run, backend=U.FakeModel(), http=object(),
                             browser_factory=factory, apply_cfg=acfg, say=say,
                             evidence_dir=w.tmp / "evidence", now=lambda: 1_700_000_000.0)
    return res[0], say


@contextlib.contextmanager
def _scan_raises(events):
    from jobscraper.apply import page as P
    saved = P.scan_required

    def boom(page, scope=""):
        events.append("scan")
        raise RuntimeError(SCAN_BOOM)
    P.scan_required = boom
    try:
        yield
    finally:
        P.scan_required = saved


def _other_job(w, cid):
    from apply_flow_support import add_job
    _, other = add_job(w.store, key="fakeco", name="Fake Co", provider="fakenav", slug="fakeco",
                       external_id="2", url="https://fake.example.com/jobs/2", company_id=cid)
    return other


def _company(w) -> int:
    return w.store.conn.execute("SELECT company_id FROM jobs").fetchone()[0]


def _click_today(w, cid, job_id):
    """A submit click recorded now (inside today's Singapore day) against `job_id`."""
    from jobscraper import store as store_mod
    aid = w.store.create_attempt(job_id, cid, "auto", store_mod.utcnow())
    for s in ("planning", "opening", "filling"):
        w.store.set_attempt_state(aid, s)
    assert w.store.mark_submit_clicked(aid, store_mod.utcnow()) is True
    w.store.set_attempt_state(aid, "submitting")
    w.store.set_attempt_state(aid, "submitted")
    w.store.commit()


def _assert_never_clicked(w, r, events):
    assert "submit" not in events, events
    assert w.store.attempt(r.attempt_id)["submit_clicked_at"] is None


# ------------------------------------------------------------------ (a) the scan cannot run

@needs(*N6B_GATE)
def test_a_a_scan_that_raises_stops_an_auto_attempt_and_never_submits():
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    from jobscraper.apply_flow import REVIEW_SCAN_FAILED
    assert REVIEW_SCAN_FAILED == "review: could not check the required fields"
    U = _unit()
    w, jid = U.world()
    try:
        events: list[str] = []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan_raises(events):
            r, say = _go(w, jid, nav, dry_run=False)
        assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR, (r.state, r.reason, r.reason_detail)
        assert r.reason_detail == "review: could not check the required fields", r.reason_detail
        assert events.count("scan") == 1, events
        _assert_never_clicked(w, r, events)
        assert w.store.attempt(r.attempt_id)["state"] == "failed"
        assert "98765432" not in say.text and SCAN_BOOM not in say.text, "only the exception type is logged"
        assert "pre-Submit scan could not run (RuntimeError)" in say.text, say.text
    finally:
        w.close()


@needs(*N6B_GATE)
def test_a_a_scan_that_raises_in_a_dry_run_is_logged_and_ends_ready_to_submit():
    from jobscraper.apply.contracts import AttemptState as S
    U = _unit()
    w, jid = U.world()
    try:
        events: list[str] = []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan_raises(events):
            r, say = _go(w, jid, nav, dry_run=True)
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
        _assert_never_clicked(w, r, events)
        assert "pre-Submit scan could not run" in say.text
        assert "98765432" not in say.text
    finally:
        w.close()


# ------------------------------------------------------------------ (b) the caps (D-61)

@needs(*N6B_GATE)
def test_b_a_cap_already_reached_stops_the_auto_llm_attempt_before_the_form_and_never_submits():
    """The guards (`cap_refusal`) refuse before the browser opens: nothing filled, scanned or sent."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    U = _unit()
    for over, needle in (({"daily_cap": 1}, "1 of 1 today"),
                         ({"daily_cap": 10, "per_employer_daily_cap": 1}, "at Fake Co")):
        w, jid = U.world()
        try:
            _click_today(w, _company(w), _other_job(w, _company(w)))
            events: list[str] = []
            nav = _submit_nav(events)
            with _script(nav, _two_steps, events), _scan((), events):
                r, say = _go(w, jid, nav, dry_run=False, apply_over=over)
            assert r.state is S.FAILED and r.reason is R.CAP_REACHED, (over, r.state, r.reason, r.reason_detail)
            assert needle in r.reason_detail, r.reason_detail
            assert events == [], f"nothing may run once the cap is reached: {events}"
            _assert_never_clicked(w, r, events)
        finally:
            w.close()


@needs(*N6B_GATE)
def test_b_a_click_that_lands_after_the_guards_makes_claim_click_refuse_and_nothing_is_submitted():
    """Another run sends one while this attempt fills: the pre-click re-check (claim_click)
    refuses. The scan passed, Submit was reachable, and it is still never pressed."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    U = _unit()
    for over in ({"daily_cap": 1}, {"daily_cap": 10, "per_employer_daily_cap": 1}):
        w, jid = U.world()
        try:
            cid = _company(w)
            other = _other_job(w, cid)
            events: list[str] = []
            nav = _submit_nav(events)
            fired = []

            def script(n, services, ctx, rctx):
                if not fired:
                    fired.append(1)
                    _click_today(w, cid, other)            # lands after the guards, before the click
                return _two_steps(n, services, ctx, rctx)
            with _script(nav, script, events), _scan((), events):
                r, say = _go(w, jid, nav, dry_run=False, apply_over=over)
            assert r.state is S.FAILED and r.reason is R.CAP_REACHED, (over, r.state, r.reason, r.reason_detail)
            assert "scan" in events, "the refusal came at the click, after a passing scan"
            _assert_never_clicked(w, r, events)
        finally:
            w.close()


@needs(*N6B_GATE)
def test_b_one_click_under_the_cap_still_submits_the_control():
    from jobscraper.apply.contracts import AttemptState as S
    U = _unit()
    w, jid = U.world()
    try:
        _click_today(w, _company(w), _other_job(w, _company(w)))
        events: list[str] = []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan((), events):
            r, say = _go(w, jid, nav, dry_run=False, apply_over={"daily_cap": 2, "per_employer_daily_cap": 2})
        assert events.count("submit") == 1, events
        assert r.state in (S.SUBMITTED, S.SUBMITTED_UNCONFIRMED), (r.state, r.reason, r.reason_detail)
        assert w.store.attempt(r.attempt_id)["submit_clicked_at"]
    finally:
        w.close()


@needs(*N6B_GATE)
def test_b_a_dry_run_ignores_a_reached_cap_and_still_never_submits():
    """Caps count sent applications; a dry run is not one (apply_flow: `if not self.dry_run`)."""
    from jobscraper.apply.contracts import AttemptState as S
    U = _unit()
    w, jid = U.world()
    try:
        _click_today(w, _company(w), _other_job(w, _company(w)))
        events: list[str] = []
        nav = _submit_nav(events)
        with _script(nav, _two_steps, events), _scan((), events):
            r, _say = _go(w, jid, nav, dry_run=True, apply_over={"daily_cap": 1})
        assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
        _assert_never_clicked(w, r, events)
    finally:
        w.close()


# ------------------------------------------------------------------ (c) no values in the log

@needs(*N6B_GATE)
def test_c_the_required_text_not_shown_line_holds_a_count_never_a_value():
    from jobscraper.apply.contracts import AttemptState as S
    U = _unit()
    other_private = "Blk 12 Secret Lane #04-56"

    def script(nav, services, ctx, rctx):
        if nav.step_id(None, None) == "one":
            fields = [U.pf("phone", "Mobile number"), U.pf("addr", "Home address")]
            return U.outcome("one", fields, {"phone": U.ans("phone", PRIVATE_PHONE),
                                             "addr": U.ans("addr", other_private)})
        return U.outcome("two", [U.pf("c", "Nationality")])
    for dry in (True, False):
        w, jid = U.world()
        try:
            events: list[str] = []
            nav = _submit_nav(events)
            with _script(nav, script, events), _scan((), events):
                r, say = _go(w, jid, nav, dry_run=dry)
            assert r.state in (S.READY_TO_SUBMIT, S.SUBMITTED, S.SUBMITTED_UNCONFIRMED), (dry, r.state, r.reason_detail)
            lines = [x for x in say.lines if "not shown on the review page" in x]
            assert len(lines) == 1 and "review: 2 required text value(s) not shown" in lines[0], say.text
            for line in say.lines:
                for secret in (PRIVATE_PHONE, other_private, *PRIVATE_DIGITS, "Secret Lane"):
                    assert secret not in line, f"a private value reached a log line: {line!r}"
            assert (r.reason_detail or "").find("9123") < 0
        finally:
            w.close()


# ------------------------------------------------------------------ (d) a bot check at review

@needs(*N6B_GATE)
def test_d_a_bot_check_or_captcha_after_the_last_next_ends_the_attempt_before_the_scan_and_submit():
    """Review F2: the page the last Next lands on is classified before the pre-Submit scan, so the
    owner sees the real reason. The flow only raises: it never interacts with the challenge."""
    from apply_flow_support import PageSignal
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R
    U = _unit()
    for sig, want in ((PageSignal.BOT_CHALLENGE, R.BOT_CHALLENGE), (PageSignal.CAPTCHA, R.CAPTCHA)):
        for dry in (False, True):
            w, jid = U.world()
            try:
                events: list[str] = []
                nav = _submit_nav(events)
                seen: list[str] = []

                def when(page, nav=nav, sig=sig, seen=seen):
                    seen.append(nav.steps[nav.at])
                    return sig if nav.steps[nav.at] == "review" else None
                with _script(nav, _two_steps, events), _scan((), events):
                    r, say = _go(w, jid, nav, dry_run=dry, when=when)
                assert r.state is S.FAILED and r.reason is want, (sig, dry, r.state, r.reason, r.reason_detail)
                assert "review" in seen, "the review page was classified"
                assert "scan" not in events, "the scan must not run on a challenge page"
                _assert_never_clicked(w, r, events)
            finally:
                w.close()
