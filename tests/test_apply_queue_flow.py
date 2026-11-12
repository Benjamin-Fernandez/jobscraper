"""The auto-apply queue WORKER (`apply_flow.run_queue`, Q-120, D-205): oracle pins.

In mode `auto` every role the worker runs is a real submission, so these pin what must
never happen (apply_queue_design §3.2, §4.1 as built, §5, §6, §8; review H4, M3, M4, M5):
  P1   never two attempts in flight: two auto roles run one after the other;
  P10  a role queued in dry run never submits, whatever the effective mode;
  P10b a role queued in auto does not submit after the owner switched to dry run;
       `pick_mode` gives "auto" only for auto + auto without --dry-run;
  a paused queue takes nothing; P6 the pre-take model check and a browser launch error;
  the pause table as built (Coordinator 2026-11-12): content failure -> fill_failed, not
  returned; transport -> model_unavailable, returned; one unanswerable question goes on;
  the streaks (3 same failures, 3 errors, 2 bot checks); P8 a refused role goes on;
  a role whose Submit was clicked is NEVER returned to the queue, whatever the pause;
  the daily cap; P14 yield; P15 parent gone; P9 dry-run tabs and the hold;
  P20 per-role state (profile, resume) does not leak; the batch `run` is unchanged.
Fakes only (tests/apply_flow_support.py): temp DB, fake adapter / browser, NoModel.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import (  # noqa: E402
    FakeAdapter, FakeBrowserFactory, FakeSession, NoModel, Say, add_job, fake_world,
    page_signals, registered, sample_profile, unknown_required,
)

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply.classify import PageSignal  # noqa: E402
from jobscraper.apply.contracts import ApplyFailure, ReasonCode as R  # noqa: E402
from jobscraper.store import Store, utcnow  # noqa: E402

TERMINAL = ("submitted", "submitted_unconfirmed", "ready_to_submit", "failed")


# ------------------------------------------------------------------ harness

class PerJob(FakeAdapter):
    """FakeAdapter whose form (and open hook) can differ per job id."""

    def __init__(self) -> None:
        super().__init__()
        self.base = list(self.fields)
        self.fields_for: dict[str, list] = {}
        self.open_for: dict[str, object] = {}
        self.opened: list[str] = []

    def plan_from_schema(self, ctx):
        jid = str(ctx.job.get("job_id", ""))
        self.fields = list(self.fields_for.get(jid, self.base))
        return super().plan_from_schema(ctx)

    def open(self, page, ctx):
        jid = str(ctx.job.get("job_id", ""))
        self.opened.append(jid)
        hook = self.open_for.get(jid)
        if hook is not None:
            hook(page, ctx)
        return super().open(page, ctx)


class UpModel:
    """A model that is running but never gives a usable reply (no JSON): an unanswerable
    question then fails as itself, not as "model unavailable" (NoModel's note)."""
    available = True
    name = "fake"
    model_id = "fake"

    def warm(self, keep_alive=None):
        pass

    def complete(self, *a, **k):
        from jobscraper.backends import Completion
        return Completion("not json")


def _world(n=2, **kw):
    """(world, adapter, company_id, [job ids]) with n `to_apply` fakeats jobs."""
    w, _, cid, j1 = fake_world(**kw)
    jobs = [j1]
    for i in range(2, n + 1):
        _, j = add_job(w.store, key="fakeco", name="Fake Co", provider="fakeats", slug="fakeco",
                       external_id=str(i), url=f"https://fake.example.com/jobs/{i}", company_id=cid)
        jobs.append(j)
    for j in jobs:
        w.store.set_application_status(j, "to_apply")
    w.store.commit()
    return w, PerJob(), cid, jobs


def _enqueue(w, cid, jobs, mode):
    for j in jobs:
        assert w.store.queue_add(j, cid, mode, "inbox", utcnow()) is not None
    w.store.commit()


def _queue(w, ad, *, mode="dry_run", over=None, backend=None, factory=None, when=None,
           should_stop=None, force=False, cfg_fn=None):
    """run_queue with the fakes; caps off, no waits, fill=rules unless overridden.
    `cfg_fn(acfg)` = the effective settings at each call (default: always acfg)."""
    factory = factory or FakeBrowserFactory()
    say = Say()
    base = {"dry_run_hold_s": 0, "confirm_timeout_s": 0, "fill": "rules", "mode": mode,
            "daily_cap": 0, "per_employer_daily_cap": 0, **(over or {})}
    acfg = dataclasses.replace(w.cfg.apply, **base)
    fn = (lambda: cfg_fn(acfg)) if cfg_fn else (lambda: acfg)
    with registered(ad), page_signals(when=when):
        out = apply_flow.run_queue(w.cfg, w.store, backend=backend or NoModel(), apply_cfg_fn=fn,
                                   http=object(), browser_factory=factory, say=say,
                                   evidence_dir=w.tmp / "evidence", should_stop=should_stop,
                                   force_dry_run=force)
    return out, factory, say


def _rows(w):
    return w.attempt_rows()


def _by_job(w):
    return {r["job_id"]: r for r in _rows(w)}


def _live(w) -> int:
    marks = ",".join("?" * len(TERMINAL))
    return w.store.conn.execute(
        f"SELECT COUNT(*) FROM apply_attempts WHERE state NOT IN ({marks})", TERMINAL).fetchone()[0]


def _pause(w):
    return w.store.queue_pause_state()


# ================================================================== P1 one in flight

def test_p1_two_auto_roles_run_one_after_the_other_with_exactly_one_live_attempt():
    w, ad, cid, (j1, j2) = _world(2)
    live_at_open = []
    for j in (j1, j2):
        ad.open_for[j] = lambda page, ctx: live_at_open.append(_live(w))
    _enqueue(w, cid, [j1, j2], "auto")
    out, factory, say = _queue(w, ad, mode="auto")
    assert live_at_open == [1, 1], f"live attempts at each page open: {live_at_open}"
    rows = _by_job(w)
    assert [rows[j]["state"] for j in (j1, j2)] == ["submitted", "submitted"], rows
    assert rows[j1]["finished_at"] <= rows[j2]["queued_at"], "role 2 was taken only after role 1 ended"
    assert ad.calls.count("submit") == 2 and len(_rows(w)) == 2
    assert (out.paused, out.waiting, out.yielded, out.lock_refused) == ("", 0, False, False)
    assert _live(w) == 0
    w.close()


# ================================================================== P10 / P10b the mode never upgrades

def test_pick_mode_is_auto_only_for_auto_and_auto_without_force():
    values = ("auto", "dry_run", "", None, "AUTO", "auto ", "dry-run", 1)
    for item in values:
        for eff in values:
            for force in (False, True):
                got = apply_flow.pick_mode(item, eff, force)
                want = "auto" if (item == "auto" and eff == "auto" and not force) else "dry_run"
                assert got == want, (item, eff, force, got)


def test_p10_p10b_a_dry_role_an_owner_switch_and_dry_run_flag_never_click_submit():
    # P10: queued in dry run, effective mode auto at pick.
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "dry_run")
    _queue(w, ad, mode="auto")
    row = _by_job(w)[j1]
    assert (row["state"], row["mode"], row["submit_clicked_at"]) == ("ready_to_submit", "dry_run", None)
    assert "submit" not in ad.calls, "P10: a role queued in dry run was submitted"
    w.close()
    # P10b: both queued in auto; the owner switches to dry run while role 1 is submitting.
    w, ad, cid, (j1, j2) = _world(2)
    eff = {"mode": "auto"}
    ad.on_submit = lambda ctx: eff.update(mode="dry_run")
    _enqueue(w, cid, [j1, j2], "auto")
    _queue(w, ad, mode="auto", cfg_fn=lambda a: dataclasses.replace(a, mode=eff["mode"]))
    rows = _by_job(w)
    assert rows[j1]["state"] == "submitted"
    assert (rows[j2]["state"], rows[j2]["mode"], rows[j2]["submit_clicked_at"]) == \
        ("ready_to_submit", "dry_run", None), "P10b: the switch to dry run was not honoured"
    assert ad.calls.count("submit") == 1
    w.close()
    # --dry-run (force): auto + auto still never submits.
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "auto")
    _queue(w, ad, mode="auto", force=True)
    row = _by_job(w)[j1]
    assert (row["state"], row["mode"], row["submit_clicked_at"]) == ("ready_to_submit", "dry_run", None)
    assert "submit" not in ad.calls
    w.close()


# ================================================================== pre-take stops

def test_a_paused_queue_takes_nothing_creates_no_attempt_and_starts_no_browser():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "auto")
    w.store.queue_pause("owner", None, utcnow())
    takes = []
    real = w.store.queue_take
    w.store.queue_take = lambda now: (takes.append(now), real(now))[1]
    out, factory, say = _queue(w, ad, mode="auto")
    assert takes == [], "the worker asked the store for a role while the queue was paused"
    assert _rows(w) == [] and factory.started == 0 and ad.calls == []
    assert w.store.queue_positions() == {j1: 1, j2: 2}
    assert out.paused == "owner" and out.results == []
    w.close()


def test_p6_the_model_unavailable_before_a_take_pauses_with_no_attempt_and_no_browser():
    w, ad, cid, (j1,) = _world(1)
    _enqueue(w, cid, [j1], "auto")
    out, factory, say = _queue(w, ad, mode="auto", over={"fill": "llm"}, backend=NoModel())
    assert _pause(w)["reason"] == "model_unavailable" and out.paused == "model_unavailable"
    assert _rows(w) == [] and factory.started == 0
    assert w.store.queue_positions() == {j1: 1}, "the head stays where it is"
    w.close()


def test_p6_a_browser_launch_error_returns_the_role_to_the_front_and_takes_no_other():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "auto")

    def broken(acfg):
        raise RuntimeError("cannot launch")
    out, factory, say = _queue(w, ad, mode="auto", factory=broken)
    st = _pause(w)
    assert st["reason"] == "browser_unavailable" and "Edge could not start" in (st["detail"] or "")
    assert [r["job_id"] for r in _rows(w)] == [j1], "the next role was taken after a launch error"
    assert _rows(w)[0]["state"] == "failed" and _rows(w)[0]["submit_clicked_at"] is None
    assert w.store.queue_positions() == {j1: 1, j2: 2}, "the role goes back to position 1"
    item = [i for i in w.store.queue_items() if i["job_id"] == j1][0]
    assert item["mode"] == "auto" and "browser_unavailable" in (item["note"] or "")
    w.close()


# ================================================================== the pause table as built

def test_content_failure_pauses_fill_failed_not_returned_and_transport_returns():
    for detail in (apply_flow.content_failure_detail(apply_flow.FILL_NO_USABLE_ANSWERS, "the model gave none"),
                   apply_flow.content_failure_detail(apply_flow.FILL_WOULD_BE_GUESSES, "3 answers")):
        w, ad, cid, (j1, j2) = _world(2)

        def content(page, ctx, d=detail):
            raise ApplyFailure(R.UNANSWERABLE_REQUIRED, d)
        ad.open_for[j1] = content
        _enqueue(w, cid, [j1, j2], "dry_run")
        _queue(w, ad)
        assert _pause(w)["reason"] == "fill_failed", detail
        assert w.store.queue_positions() == {j2: 1}, "a content failure is NOT returned"
        assert [r["job_id"] for r in _rows(w)] == [j1]
        w.close()
    w, ad, cid, (j1, j2) = _world(2)

    def transport(page, ctx):
        raise ApplyFailure(R.MODEL_UNAVAILABLE, "model unavailable (timeout)")
    ad.open_for[j1] = transport
    _enqueue(w, cid, [j1, j2], "dry_run")
    _queue(w, ad)
    assert _pause(w)["reason"] == "model_unavailable"
    assert w.store.queue_positions() == {j1: 1, j2: 2}, "a transport failure is returned"
    w.close()


def test_one_unanswerable_question_goes_on_and_three_in_a_row_pause_repeated_failures():
    w, ad, cid, (j1, j2) = _world(2)
    ad.fields_for[j1] = [*ad.base, unknown_required()]
    _enqueue(w, cid, [j1, j2], "dry_run")
    out, _, _ = _queue(w, ad, backend=UpModel())
    rows = _by_job(w)
    assert (rows[j1]["state"], rows[j1]["reason_code"]) == ("failed", "unanswerable_required")
    assert rows[j2]["state"] == "ready_to_submit" and out.paused == "" and _pause(w) is None
    w.close()
    w, ad, cid, jobs = _world(4)
    for j in jobs:
        ad.fields_for[j] = [*ad.base, unknown_required()]
    _enqueue(w, cid, jobs, "dry_run")
    _queue(w, ad, backend=UpModel())
    st = _pause(w)
    assert st["reason"] == "repeated_failures" and "unanswerable required" in (st["detail"] or "")
    assert len(_rows(w)) == 3 and w.store.queue_positions() == {jobs[3]: 1}, "not returned"
    w.close()


def test_three_errors_pause_repeated_errors_and_two_bot_checks_pause_bot_checks():
    w, ad, cid, jobs = _world(4)
    for j in jobs:
        ad.open_for[j] = lambda page, ctx: (_ for _ in ()).throw(RuntimeError("kaput"))
    _enqueue(w, cid, jobs, "dry_run")
    _queue(w, ad)
    assert [r["reason_code"] for r in _rows(w)] == ["error"] * 3
    assert _pause(w)["reason"] == "repeated_errors"
    assert w.store.queue_positions() == {jobs[3]: 1}
    w.close()
    w, ad, cid, jobs = _world(3)
    _enqueue(w, cid, jobs, "dry_run")
    _queue(w, ad, when=lambda page: PageSignal.CAPTCHA)
    assert [r["reason_code"] for r in _rows(w)] == ["captcha", "captcha"]
    assert _pause(w)["reason"] == "bot_checks"
    assert w.store.queue_positions() == {jobs[2]: 1}, "the two are not returned; the third waits"
    w.close()


def test_p8_a_refused_twin_does_not_stop_the_next_and_the_batch_run_is_unchanged():
    w, ad, cid, (j1, j2) = _world(2)
    _, twin = add_job(w.store, key="fakeco", name="Fake Co", provider="fakeats", slug="fakeco",
                      external_id="99", url="https://fake.example.com/jobs/1", company_id=cid)
    w.store.set_application_status(twin, "applied")
    w.store.commit()
    _enqueue(w, cid, [j1, j2], "dry_run")
    out, _, _ = _queue(w, ad)
    rows = _by_job(w)
    assert (rows[j1]["state"], rows[j1]["reason_code"]) == ("failed", "duplicate")
    assert rows[j2]["state"] == "ready_to_submit" and out.paused == "" and out.waiting == 0
    w.close()
    # The batch `apply <ids>` keeps its own duplicate guard.
    w, ad, cid, (j1,) = _world(1)
    acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0, fill="rules")
    with registered(ad), page_signals():
        res = apply_flow.run(w.cfg, w.store, [j1, j1], dry_run=True, backend=NoModel(),
                             http=object(), browser_factory=FakeBrowserFactory(), apply_cfg=acfg,
                             say=Say(), evidence_dir=w.tmp / "evidence")
    assert [r.state.value for r in res] == ["ready_to_submit", "failed"]
    assert res[1].reason is R.DUPLICATE and res[1].reason_detail == "the same job twice in this batch"
    w.close()


# ================================================================== NF-06: never returned after a click

def test_a_role_whose_submit_was_clicked_is_never_returned_whatever_the_pause():
    """Every pause that returns a role, driven on a failed row; the control (no click)
    proves each case reaches the return branch, so the clicked case is not vacuous."""
    cases = (("profile_incomplete", "contact.email", {}, "profile_incomplete"),
             ("model_unavailable", "model unavailable", {}, "model_unavailable"),
             ("error", "Edge went away", {"browser_failed": "Edge could not start (X)"},
              "browser_unavailable"),
             ("cap_reached", "1 of 1 today", {"last_cap": "daily"}, "daily_limit"))
    orig = apply_flow._Run.attempt
    for reason, detail, attrs, want in cases:
        for clicked in (True, False):
            w, ad, cid, (j1, j2) = _world(2)
            _enqueue(w, cid, [j1, j2], "dry_run")

            def fake_attempt(self, job_id, *, attempt_id=None, reason=reason, detail=detail,
                             attrs=attrs, clicked=clicked):
                r = orig(self, job_id, attempt_id=attempt_id)
                self.store.conn.execute(
                    "UPDATE apply_attempts SET state = 'failed', reason_code = ?, reason_detail = ?,"
                    " submit_clicked_at = ? WHERE id = ?",
                    (reason, detail, utcnow() if clicked else None, r.attempt_id))
                self.store.commit()
                for k, v in attrs.items():
                    setattr(self, k, v)
                return r
            apply_flow._Run.attempt = fake_attempt
            try:
                _queue(w, ad)
            finally:
                apply_flow._Run.attempt = orig
            assert _pause(w)["reason"] == want, (reason, clicked, _pause(w))
            pos = w.store.queue_positions()
            if clicked:
                assert j1 not in pos, f"{want}: a role with Submit clicked went back to the queue"
                assert pos == {j2: 1}
            else:
                assert pos == {j1: 1, j2: 2}, (want, pos)
            w.close()


def test_the_daily_cap_pauses_daily_limit_and_returns_the_role_the_employer_cap_does_not():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "auto")
    _queue(w, ad, mode="auto", over={"daily_cap": 1})
    st = _pause(w)
    assert st["reason"] == "daily_limit" and "1 of 1 today" in (st["detail"] or "")
    assert w.store.queue_positions() == {j2: 1}, "the refused role is back at the front"
    assert ad.calls.count("submit") == 1
    w.close()
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "auto")
    out, _, _ = _queue(w, ad, mode="auto", over={"per_employer_daily_cap": 1})
    rows = _by_job(w)
    assert (rows[j2]["state"], rows[j2]["reason_code"]) == ("failed", "cap_reached")
    assert out.paused == "" and w.store.queue_positions() == {}
    w.close()


# ================================================================== P14 yield, P15 parent gone

def test_p14_a_yield_before_a_take_ends_without_a_pause_and_during_a_role_after_it():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    w.store.queue_request_yield()
    out, factory, _ = _queue(w, ad)
    assert out.yielded and _rows(w) == [] and factory.started == 0 and _pause(w) is None
    assert w.store.queue_positions() == {j1: 1, j2: 2}
    assert not w.store.get_setting(Store.QUEUE_YIELD), "the yield flag is consumed"
    w.close()
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    ad.open_for[j1] = lambda page, ctx: w.store.queue_request_yield()
    out, _, _ = _queue(w, ad)
    assert [(r["job_id"], r["state"]) for r in _rows(w)] == [(j1, "ready_to_submit")]
    assert out.yielded and _pause(w) is None and w.store.queue_positions() == {j2: 1}
    w.close()


def test_p15_the_parent_gone_pauses_app_closed_after_the_current_role():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    gone = {"v": False}
    ad.open_for[j1] = lambda page, ctx: gone.update(v=True)
    out, _, _ = _queue(w, ad, should_stop=lambda: gone["v"])
    assert [(r["job_id"], r["state"]) for r in _rows(w)] == [(j1, "ready_to_submit")], \
        "the role in progress finishes"
    assert _pause(w)["reason"] == "app_closed" and out.paused == "app_closed"
    assert w.store.queue_positions() == {j2: 1}
    w.close()


# ================================================================== P9 dry-run tabs and the hold

def test_p9_dry_run_keeps_three_tabs_and_a_role_added_during_the_hold_runs_in_the_same_session():
    w, ad, cid, jobs = _world(6)
    _enqueue(w, cid, jobs[:5], "dry_run")
    seen_at_hold = []

    class Session(FakeSession):
        def hold(self, seconds):
            seen_at_hold.append(len(w.attempt_rows()))
            if len(seen_at_hold) == 1:              # the owner adds a role during the hold
                assert w.store.queue_add(jobs[5], cid, "dry_run", "inbox", utcnow())
                w.store.commit()
            return super().hold(seconds)

    class Factory(FakeBrowserFactory):
        def __call__(self, acfg):
            s = Session(acfg)
            self.sessions.append(s)
            return s
    factory = Factory()
    out, _, say = _queue(w, ad, factory=factory, over={"dry_run_hold_s": 10})
    assert [r["state"] for r in _rows(w)] == ["ready_to_submit"] * 6
    assert seen_at_hold and seen_at_hold[0] == 5, "no hold before the queue was empty"
    assert factory.started == 1, "the role added during the hold ran in the same session"
    pages = factory.pages
    assert len(pages) == 6 and [p.closed for p in pages] == [True] * 3 + [False] * 3, \
        "at most 3 filled tabs stay open; the oldest close first"
    assert "closed the oldest dry-run tab" in say.text and out.waiting == 0
    w.close()


# ================================================================== P20 per-role state

def test_p20_begin_item_reads_profile_and_resume_per_role_and_nothing_leaks():
    w, ad, cid, (j1, j2) = _world(2)
    _enqueue(w, cid, [j1, j2], "dry_run")
    p2 = sample_profile(email="second.person@example.com")
    p2["contact"]["phone_number"] = "98765432"

    def owner_edits(page, ctx):                     # mid-queue: a new profile and resume
        w.cfg.applicant_path.write_text(yaml.safe_dump(p2, sort_keys=False), encoding="utf-8")
        w.resume.write_bytes(w.resume.read_bytes() + b"% edited\n")
    ad.open_for[j1] = owner_edits
    _queue(w, ad)
    first, second = ad.fill_log[0], ad.fill_log[1]
    assert first["email"] == w.profile["contact"]["email"] and first["email"] != second["email"]
    assert second["email"] == "second.person@example.com" and second["phone"] == "98765432"
    assert first["phone"] != "98765432", "role 1 used values from after its start"
    rows = _by_job(w)
    assert rows[j1]["resume_sha256"] != rows[j2]["resume_sha256"], "the resume is read per role"
    w.close()
