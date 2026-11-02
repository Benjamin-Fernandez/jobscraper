"""The apply orchestrator (`apply_flow.run`), driven with a fake adapter and a fake browser
(WP-B7, WP-B9 plumbing, WP-B11; Verify `-k apply_flow`). Queue Q-31.

What is pinned (apply_design §3, §4.1, §4.4, §7.8, §12.1, §17; NF-02, NF-06, NF-09):
  - the guard order profile -> duplicate -> caps -> one in flight, and each refusal's reason;
  - a required `unknown` fails before the browser starts; an optional one is left blank;
  - `submit_clicked_at` is committed (visible to a second connection) BEFORE `submit()`;
  - every unhappy ending after the click is submitted_unconfirmed, never failed;
  - a dry run ends ready_to_submit and never calls `submit`;
  - one audit row per field (a file = name + SHA-256, never a path);
  - no profile value reaches the log (redact), exceptions included;
  - the prefill policies (KEEP / OVERWRITE), the planning deferral and the corrective retry.
The adapter, page and browser are fakes (tests/apply_flow_support.py); the real Greenhouse adapter
in headless Edge is tests/test_apply_e2e.py. No network, no model, temp DB and evidence dir.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import io
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import (  # noqa: E402
    EMAIL, FakeAdapter, FakeBrowserFactory, NoModel, RESUME_BYTES, Say, add_job, default_fields,
    fake_world, make_world, page_signals, registered, stored_value, unknown_optional,
    unknown_required,
)

from jobscraper import apply_flow, applicant  # noqa: E402
from jobscraper.apply.classify import PageSignal  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerSource, AnswerStatus, AnswerTier, AttemptState as S, Canonical, FieldType,
    FormField, ReasonCode as R, StepResult,
)
from jobscraper import store as store_mod  # noqa: E402

RESUME_SHA = hashlib.sha256(RESUME_BYTES).hexdigest()


# ------------------------------------------------------------------ driver

def _run(w, job_ids, adapter, *, dry_run=True, backend=None, apply_over=None, factory=None,
         say=None, when=None):
    """apply_flow.run with the fakes. confirm_timeout_s = 0 and dry_run_hold_s = 0 unless
    overridden, so nothing waits. Returns (results, factory, say)."""
    factory = factory or FakeBrowserFactory()
    say = say if say is not None else Say()
    over = {"dry_run_hold_s": 0, "confirm_timeout_s": 0, **(apply_over or {})}
    acfg = dataclasses.replace(w.cfg.apply, **over)
    with registered(adapter), page_signals(when=when):
        res = apply_flow.run(w.cfg, w.store, list(job_ids), dry_run=dry_run,
                             backend=backend or NoModel(), http=object(),
                             browser_factory=factory, apply_cfg=acfg, say=say,
                             evidence_dir=w.tmp / "evidence")
    return res, factory, say


def _one(w, adapter, jid, **kw):
    res, factory, say = _run(w, [jid], adapter, **kw)
    assert len(res) == 1
    return res[0], factory, say


def _row(w, result):
    return w.store.attempt(result.attempt_id)


def _same_connection_view(db_path, attempt_id):
    """What a SECOND connection sees of the attempt row (committed data only)."""
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute("SELECT state, submit_clicked_at FROM apply_attempts WHERE id = ?",
                           (attempt_id,)).fetchone()
    finally:
        con.close()


# ================================================================== dry run

def test_a_dry_run_ends_ready_to_submit_and_never_calls_submit():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid, dry_run=True)
    assert r.state is S.READY_TO_SUBMIT and r.ok and r.reason is None
    assert "submit" not in ad.calls and "after_submit" not in ad.calls
    row = _row(w, r)
    assert (row["state"], row["mode"], row["ats"], row["plan_source"]) == \
        ("ready_to_submit", "dry_run", "fakeats", "schema")
    assert row["submit_clicked_at"] is None and row["finished_at"]
    assert w.store.application(jid) is None, "a dry run never marks the job applied"
    assert factory.started == 1 and factory.sessions[0].closed
    assert not factory.pages[0].closed, "the filled form stays open for the owner (F-37)"
    w.close()


def test_a_dry_run_holds_the_window_for_the_configured_time():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid, apply_over={"dry_run_hold_s": 30})
    assert factory.sessions[0].holds == [30] and r.state is S.READY_TO_SUBMIT
    assert "stay open for up to 30 s" in say.text
    w.close()


def test_a_dry_run_holds_nothing_when_no_attempt_is_ready():
    w, ad, cid, jid = fake_world()
    ad.fields.append(unknown_required())
    r, factory, say = _one(w, ad, jid, apply_over={"dry_run_hold_s": 30})
    assert r.state is S.FAILED
    assert factory.started == 0 and not factory.sessions
    w.close()


def test_the_attempt_records_the_resume_and_one_audit_row_per_field():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid)
    row = _row(w, r)
    assert (row["resume_file"], row["resume_sha256"], row["resume_source"]) == \
        ("resume.pdf", RESUME_SHA, "original")
    rows = w.answers_by_key(r.attempt_id)
    assert set(rows) == {f.key for f in ad.fields}, "one audit row per planned field (F-39)"
    assert len(w.store.answers(r.attempt_id)) == len(ad.fields), "no field is recorded twice"
    fn = rows["first_name"]
    assert (fn["tier"], fn["status"], fn["field_type"], fn["required"]) == (1, "filled", "text", 1)
    assert fn["source"].startswith("field_map") and fn["label_norm"] == "first name"
    assert stored_value(rows["email"]) == EMAIL
    f = rows["resume"]
    assert f["field_type"] == "file" and f["tier"] == 1
    assert stored_value(f) == {"file": "resume.pdf", "sha256": RESUME_SHA}, \
        "a file is recorded as its name and SHA-256 (§7.8)"
    for a in w.store.answers(r.attempt_id):
        assert str(w.tmp) not in " ".join(str(v) for v in a.values()), "no local path in the audit"
    assert [a.field_key for a in r.answers] == [f.key for f in ad.fields]
    w.close()


def test_evidence_is_numbered_screenshots_beside_the_database():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid)
    folder = w.tmp / "evidence" / str(r.attempt_id)
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["01-open.png", "02-application.png", "03-review.png"], names
    assert [Path(p).name for p in r.screenshots] == names
    assert not (folder / "failed.html").exists()
    w.close()


def test_evidence_root_is_apply_beside_the_database():
    w = make_world()
    assert apply_flow.evidence_root(w.cfg) == w.db_path.parent / "apply"
    w.close()


# ================================================================== required unknown, optional unknown

def test_a_required_unknown_fails_before_the_browser_opens():
    w, ad, cid, jid = fake_world()
    ad.fields.append(unknown_required())
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED
    assert "first pet" in r.reason_detail
    assert factory.started == 0, "Edge must not even start (§4.4)"
    assert "open" not in ad.calls and "fill" not in ad.calls
    row = _row(w, r)
    assert (row["state"], row["reason_code"]) == ("failed", "unanswerable_required")
    assert row["submit_clicked_at"] is None
    rows = w.answers_by_key(r.attempt_id)
    assert rows["question_1"]["status"] == "unknown" and rows["question_1"]["tier"] == 0, \
        "the audit shows what was resolved before it stopped"
    assert rows["first_name"]["status"] == "filled"
    w.close()


def test_a_required_unknown_with_the_model_down_says_so():
    w, ad, cid, jid = fake_world()
    ad.fields.append(unknown_required())
    r, factory, say = _one(w, ad, jid)
    assert "(model unavailable)" in r.reason_detail
    w.close()


def test_an_optional_unknown_is_left_blank_and_the_form_goes_on():
    w, ad, cid, jid = fake_world()
    ad.fields.append(unknown_optional())
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    assert w.answers_by_key(r.attempt_id)["question_2"]["status"] == "blank_optional"
    assert "question_2" not in ad.fill_log[0]
    w.close()


# ================================================================== guards, in order

def test_profile_incomplete_comes_first_even_for_a_duplicate_job():
    w, ad, cid, jid = fake_world(applicant_file=False)
    w.store.set_application_status(jid, "applied")        # also a duplicate, also over the cap
    r, factory, say = _one(w, ad, jid, dry_run=False)
    assert r.state is S.FAILED and r.reason is R.PROFILE_INCOMPLETE
    assert factory.started == 0
    w.close()


def test_a_missing_resume_file_is_profile_incomplete_naming_it():
    w, ad, cid, jid = fake_world(resume=False)
    r, factory, say = _one(w, ad, jid)
    assert r.reason is R.PROFILE_INCOMPLETE and "documents.resume" in r.reason_detail
    assert factory.started == 0
    w.close()


def test_an_unreadable_applicant_file_is_profile_incomplete_without_its_content():
    w, ad, cid, jid = fake_world()
    (w.tmp / "data" / "applicant.yaml").write_text("- not\n- a mapping\n", encoding="utf-8")
    r, factory, say = _one(w, ad, jid)
    assert r.reason is R.PROFILE_INCOMPLETE and r.reason_detail == "applicant.yaml could not be read"
    w.close()


def test_an_applied_job_is_a_duplicate_before_the_caps_are_looked_at():
    w, ad, cid, jid = fake_world()
    w.store.set_application_status(jid, "applied")
    r, factory, say = _one(w, ad, jid, dry_run=False, apply_over={"daily_cap": 0})
    assert r.state is S.FAILED and r.reason is R.DUPLICATE
    assert r.reason_detail.startswith("applied")
    assert factory.started == 0 and "open" not in ad.calls
    w.close()


def test_the_same_job_twice_in_one_batch_is_refused_the_second_time():
    w, ad, cid, jid = fake_world()
    res, factory, say = _run(w, [jid, jid], ad)
    assert [x.state for x in res] == [S.READY_TO_SUBMIT, S.FAILED]
    assert res[1].reason is R.DUPLICATE and "twice in this batch" in res[1].reason_detail
    assert ad.calls.count("open") == 1
    w.close()


def test_a_job_with_an_earlier_clicked_attempt_is_a_duplicate():
    w, ad, cid, jid = fake_world()
    aid = w.store.create_attempt(jid, cid, "auto", "2026-11-02T01:00:00")
    _walk_clicked(w.store, aid, "2026-11-02T01:00:00", "submitted_unconfirmed")
    r, factory, say = _one(w, ad, jid)
    assert r.reason is R.DUPLICATE and "already submitted by JobScraper" in r.reason_detail
    w.close()


def _walk_clicked(store, aid, when, final=None):
    """queued -> ... -> filling, the click recorded (NF-06: before submitting), -> submitting,
    then `final` if given. The store refuses submitting without the click."""
    for s in ("planning", "opening", "filling"):
        store.set_attempt_state(aid, s)
    assert store.mark_submit_clicked(aid, when) is True
    store.set_attempt_state(aid, "submitting")
    if final:
        store.set_attempt_state(aid, final)
    store.commit()


def _clicked_today(w, cid, job_id):
    """A submit click recorded now (inside today's Singapore day) for `job_id`."""
    aid = w.store.create_attempt(job_id, cid, "auto", store_mod.utcnow())
    _walk_clicked(w.store, aid, store_mod.utcnow(), "submitted")


def test_the_daily_cap_refuses_in_auto_mode_and_a_dry_run_ignores_it():
    w, ad, cid, jid = fake_world()
    _, other = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                       company_id=cid, url="https://fake.example.com/jobs/2")
    _clicked_today(w, cid, other)
    r, factory, say = _one(w, ad, jid, dry_run=False, apply_over={"daily_cap": 1})
    assert r.state is S.FAILED and r.reason is R.CAP_REACHED
    assert "1 of 1 today" in r.reason_detail and factory.started == 0
    r2, factory2, _ = _one(w, ad, jid, dry_run=True, apply_over={"daily_cap": 1})
    assert r2.state is S.READY_TO_SUBMIT, "caps count sent applications: a dry run is not one"
    w.close()


def test_the_per_employer_cap_names_the_employer_and_spares_another():
    w, ad, cid, jid = fake_world()
    _, other = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                       company_id=cid, url="https://fake.example.com/jobs/2")
    _clicked_today(w, cid, other)
    r, factory, say = _one(w, ad, jid, dry_run=False,
                           apply_over={"daily_cap": 10, "per_employer_daily_cap": 1})
    assert r.reason is R.CAP_REACHED and "at Fake Co" in r.reason_detail
    c2, j2 = add_job(w.store, key="elsewhere", name="Elsewhere", provider="fakeats", slug="else",
                     external_id="9", url="https://fake.example.com/jobs/9")
    r2, _, _ = _one(w, ad, j2, dry_run=False,
                    apply_over={"daily_cap": 10, "per_employer_daily_cap": 1})
    assert r2.state is S.SUBMITTED, "another employer still has room"
    w.close()


def test_the_in_flight_guard_refuses_while_another_attempt_is_running():
    w, ad, cid, jid = fake_world()
    _, other = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                       company_id=cid, url="https://fake.example.com/jobs/2")
    busy = w.store.create_attempt(other, cid, "dry_run", store_mod.utcnow())
    w.store.set_attempt_state(busy, "planning")
    w.store.conn.commit()
    w.store.reap_attempts = lambda now: 0                 # another process owns it: not ours to reap
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.ERROR
    assert r.reason_detail == "another application is in progress" and factory.started == 0
    w.close()


def test_a_run_starts_by_closing_interrupted_attempts():
    w, ad, cid, jid = fake_world()
    _, j2 = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                    company_id=cid, url="https://fake.example.com/jobs/2")
    _, j3 = add_job(w.store, external_id="3", slug="fakeco", provider="fakeats", key="x",
                    company_id=cid, url="https://fake.example.com/jobs/3")
    a_open = w.store.create_attempt(j2, cid, "dry_run", store_mod.utcnow())
    w.store.set_attempt_state(a_open, "planning")
    w.store.set_attempt_state(a_open, "opening")
    a_clk = w.store.create_attempt(j3, cid, "auto", store_mod.utcnow())
    _walk_clicked(w.store, a_clk, store_mod.utcnow())
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT, "the stale attempts did not block this one"
    assert (w.store.attempt(a_open)["state"], w.store.attempt(a_open)["reason_code"]) == \
        ("failed", "cancelled")
    assert w.store.attempt(a_clk)["state"] == "submitted_unconfirmed", \
        "a clicked attempt is never failed and never resubmitted (NF-06)"
    assert "closed 2 interrupted attempt(s)" in say.text
    w.close()


# ================================================================== NF-06: the click

def test_the_click_time_is_committed_before_submit_is_called():
    w, ad, cid, jid = fake_world()
    seen = {}

    def probe(ctx):
        seen["row"] = _same_connection_view(w.db_path, ctx.attempt_id)    # a second connection
        seen["mine"] = w.store.attempt(ctx.attempt_id)["state"]
    ad.on_submit = probe
    r, factory, say = _one(w, ad, jid, dry_run=False)
    state, clicked = seen["row"]
    assert clicked, "submit_clicked_at must already be committed when submit() runs (NF-06)"
    assert state == "submitting" and seen["mine"] == "submitting"
    assert r.state is S.SUBMITTED
    assert _row(w, r)["submit_clicked_at"] == clicked
    w.close()


def test_submit_is_called_exactly_once_per_attempt():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid, dry_run=False)
    assert ad.calls.count("submit") == 1
    w.close()


def test_a_confirmed_submit_marks_the_application_applied_by_jobscraper():
    w, ad, cid, jid = fake_world()
    ad.after = "confirmed:url"
    r, factory, say = _one(w, ad, jid, dry_run=False)
    assert r.state is S.SUBMITTED and r.confirmation == "url" and r.ok
    row = _row(w, r)
    assert (row["state"], row["confirmation"]) == ("submitted", "url") and row["end_url"]
    app = w.store.application(jid)
    assert app["status"] == "applied" and app["company"] == "Fake Co"
    ev = w.store.conn.execute("SELECT to_status, by FROM app_events WHERE job_id = ? ORDER BY id",
                              (jid,)).fetchall()
    assert (ev[-1][0], ev[-1][1]) == ("applied", "jobscraper"), "the owner sees who made the change"
    assert factory.pages[0].closed, "a finished attempt's tab is closed (only ready_to_submit stays)"
    w.close()


def test_a_mixed_batch_runs_in_order_and_each_attempt_is_independent():
    w, ad, cid, jid = fake_world()
    _, j2 = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                    company_id=cid, url="https://fake.example.com/jobs/2")
    w.store.set_application_status(j2, "applied")
    _, j3 = add_job(w.store, external_id="3", slug="fakeco", provider="fakeats", key="x",
                    company_id=cid, url="https://fake.example.com/jobs/3")
    res, factory, say = _run(w, [jid, j2, j3], ad)
    assert [x.state for x in res] == [S.READY_TO_SUBMIT, S.FAILED, S.READY_TO_SUBMIT]
    assert [x.job_id for x in res] == [jid, j2, j3] and factory.started == 1, "one Edge per run"
    assert len({x.attempt_id for x in res}) == 3
    w.close()


def _after_click_cases():
    """(label, adapter tweak, expected state, expected detail fragment)."""
    return [
        ("submit() raises", lambda a: setattr(a, "submit_exc", RuntimeError("boom")),
         S.SUBMITTED_UNCONFIRMED, "error after submit (RuntimeError)"),
        ("after_submit raises", lambda a: setattr(a, "after", ValueError("nope")),
         S.SUBMITTED_UNCONFIRMED, "error after submit (ValueError)"),
        ("a code is asked for", lambda a: setattr(a, "after", "code_required"),
         S.SUBMITTED_UNCONFIRMED, "security code needed; mailbox not set up"),
        ("the site shows errors", lambda a: setattr(a, "after", "errors"),
         S.SUBMITTED_UNCONFIRMED, "errors after submit"),
        ("nothing in time", lambda a: setattr(a, "after", None),
         S.SUBMITTED_UNCONFIRMED, "no confirmation within the time limit"),
    ]


def test_every_unhappy_ending_after_the_click_is_submitted_unconfirmed_never_failed():
    for label, tweak, state, detail in _after_click_cases():
        w, ad, cid, jid = fake_world()
        tweak(ad)
        r, factory, say = _one(w, ad, jid, dry_run=False)
        assert r.state is state, f"{label}: {r.state} {r.reason_detail}"
        assert detail in r.reason_detail, f"{label}: {r.reason_detail}"
        row = _row(w, r)
        assert row["state"] == "submitted_unconfirmed" and row["submit_clicked_at"], label
        assert row["reason_code"] is None, f"{label}: never failed, so no reason code"
        assert w.store.application(jid) is None, f"{label}: not applied without a confirmation"
        w.close()


def test_a_challenge_page_after_the_click_is_unconfirmed_with_a_note():
    for sig, note in ((PageSignal.CAPTCHA, "captcha after submit"),
                      (PageSignal.BOT_CHALLENGE, "bot check after submit"),
                      (PageSignal.TWO_FACTOR, "two-step code after submit"),
                      (PageSignal.ERROR_PAGE, "error page after submit")):
        w, ad, cid, jid = fake_world()
        ad.after = None
        r, factory, say = _one(w, ad, jid, dry_run=False,
                               when=lambda page, a=ad, s=sig: s if "submit" in a.calls else None)
        assert r.state is S.SUBMITTED_UNCONFIRMED and note in r.reason_detail, (sig, r.reason_detail)
        w.close()


def test_a_bookkeeping_error_after_a_confirmed_submit_never_turns_it_into_failed():
    w, ad, cid, jid = fake_world()

    def boom(*a, **k):
        raise RuntimeError("applications table locked")
    w.store.set_application_status = boom
    r, factory, say = _one(w, ad, jid, dry_run=False)
    row = _row(w, r)
    assert row["state"] in ("submitted", "submitted_unconfirmed") and row["submit_clicked_at"], row
    assert row["state"] != "failed" and row["reason_code"] is None
    w.close()


def test_a_cancel_before_the_click_fails_cancelled_and_one_after_it_is_unconfirmed():
    w, ad, cid, jid = fake_world()
    ad.on_open = lambda page, ctx: (_ for _ in ()).throw(KeyboardInterrupt())
    try:
        _one(w, ad, jid)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("an interrupt must propagate after the attempt is closed")
    row = w.attempt_rows()[0]
    assert (row["state"], row["reason_code"]) == ("failed", "cancelled")
    w.close()
    w, ad, cid, jid = fake_world()
    ad.submit_exc = KeyboardInterrupt()
    try:
        _one(w, ad, jid, dry_run=False)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("an interrupt must propagate")
    row = w.attempt_rows()[0]
    assert row["state"] == "submitted_unconfirmed" and row["submit_clicked_at"]
    assert "interrupted after submit" in row["reason_detail"]
    w.close()


# ================================================================== stops before the click

def test_unsupported_ats_fails_before_planning_the_browser():
    w = make_world()
    _, jid = add_job(w.store, key="odd", name="Odd Co", provider="somethingelse", slug="odd",
                     external_id="1", url="https://careers.example.com/jobs/1")
    r, factory, say = _one(w, FakeAdapter(), jid)
    assert r.state is S.FAILED and r.reason is R.UNSUPPORTED_ATS
    assert r.reason_detail == "somethingelse" and factory.started == 0
    w.close()


def test_a_closed_schema_fails_posting_closed_before_the_browser():
    from jobscraper.apply.contracts import ApplyFailure
    w, ad, cid, jid = fake_world()
    ad.schema_exc = ApplyFailure(R.POSTING_CLOSED, "", step="planning")
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.POSTING_CLOSED and factory.started == 0
    w.close()


def test_a_job_that_does_not_exist_fails_with_a_reason_not_a_crash():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, "no-such-job")
    assert r.state is S.FAILED and r.reason is R.ERROR and r.reason_detail == "no such job"
    w.close()


def test_a_page_signal_before_the_form_stops_all_input_and_keeps_evidence():
    cases = ((PageSignal.CAPTCHA, R.CAPTCHA), (PageSignal.BOT_CHALLENGE, R.BOT_CHALLENGE),
             (PageSignal.CLOSED, R.POSTING_CLOSED), (PageSignal.TWO_FACTOR, R.SMS_OR_2FA),
             (PageSignal.VERIFY_EMAIL, R.MAIL_NOT_SET_UP), (PageSignal.ERROR_PAGE, R.PAGE_UNRECOGNISED))
    for sig, reason in cases:
        w, ad, cid, jid = fake_world()
        r, factory, say = _one(w, ad, jid, when=lambda page, s=sig: s)
        assert r.state is S.FAILED and r.reason is reason, (sig, r.state, r.reason)
        assert "fill" not in ad.calls and "submit" not in ad.calls, "no input past a stop sign"
        folder = w.tmp / "evidence" / str(r.attempt_id)
        assert (folder / "failed.html").is_file() and any(p.name.endswith("-failed.png")
                                                           for p in folder.iterdir()), sig
        assert factory.pages[0].closed
        w.close()


def test_a_failure_text_for_the_owner_is_logged_without_a_value():
    w, ad, cid, jid = fake_world()
    ad.fields.append(unknown_required())
    r, factory, say = _one(w, ad, jid)
    assert "reason=unanswerable_required" in say.text
    assert EMAIL not in say.text
    w.close()


def test_an_unexpected_exception_before_the_click_fails_with_its_type_only():
    w, ad, cid, jid = fake_world()
    ad.on_open = lambda page, ctx: (_ for _ in ()).throw(RuntimeError(f"cannot type {EMAIL}"))
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.ERROR and r.reason_detail == "RuntimeError"
    assert EMAIL not in say.text and "[redacted]" in say.text, "the exception line is redacted"
    row = _row(w, r)
    assert EMAIL not in " ".join(str(v) for v in row.values())
    w.close()


# ================================================================== the log (NF-02, NF-09)

def test_no_profile_value_appears_in_captured_stdout():
    w, ad, cid, jid = fake_world()
    ad.log_in_open = f"typing {EMAIL} and phone 91234567 for Alex Testcase"
    buf = io.StringIO()
    with registered(ad), page_signals(), contextlib.redirect_stdout(buf):
        res = apply_flow.run(w.cfg, w.store, [jid], dry_run=True, backend=NoModel(),
                             http=object(), browser_factory=FakeBrowserFactory(),
                             apply_cfg=dataclasses.replace(w.cfg.apply, dry_run_hold_s=0),
                             evidence_dir=w.tmp / "evidence")        # say = print (the default)
    out = buf.getvalue()
    assert res[0].state is S.READY_TO_SUBMIT
    for v in applicant.redaction_values(w.profile):
        assert v.lower() not in out.lower(), f"profile value leaked to stdout: {v[:3]}..."
    assert "[redacted]" in out and "typing" in out, "the adapter's line was logged, redacted"
    assert "ready_to_submit" in out
    w.close()


def test_redact_replaces_whole_values_longest_first_ignoring_case():
    vals = ["alex.testcase@example.com", "Alex", "1 Example Road"]
    assert apply_flow.redact("mail ALEX.TESTCASE@example.com now", vals) == "mail [redacted] now"
    assert apply_flow.redact("Alex lives at 1 Example Road", vals) == "[redacted] lives at [redacted]"
    assert apply_flow.redact("no values here", vals) == "no values here"


def test_redact_does_not_eat_a_word_that_merely_contains_a_value():
    assert apply_flow.redact("captcha shown", ["cap"]) == "captcha shown"
    assert apply_flow.redact("grade cap 4.2", ["cap"]) == "grade [redacted] 4.2"
    assert apply_flow.redact("short", ["sh"]) == "short", "values under 3 characters are ignored"
    assert apply_flow.redact("x", [None, "", "  "]) == "x"


def test_attempt_log_lines_carry_state_and_counts_but_no_answers():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid)
    text = say.text
    assert f"[attempt {r.attempt_id}] queued job={jid} mode=dry_run" in text
    assert "planning step=planning" in text and "filling step=application" in text
    assert "fields=5 filled=5" in text and "ready_to_submit" in text
    assert "Testcase" not in text and "91234567" not in text
    w.close()


def test_a_cp1252_console_never_ends_an_attempt():
    w, ad, cid, jid = fake_world()
    ad.log_in_open = "a log line with a snowman \u2603"
    calls = []

    def say(line):
        calls.append(line)
        line.encode("cp1252")                              # raises UnicodeEncodeError for the snowman
    r, _, _ = _one(w, ad, jid, say=say)
    assert r.state is S.READY_TO_SUBMIT and any("snowman ?" in c for c in calls)
    w.close()


# ================================================================== steps, retry, limits

def test_a_wizard_goes_step_by_step_and_records_each_field_once():
    w, ad, cid, jid = fake_world()
    ad.dom = True
    ad.next_results = [StepResult("contact"), StepResult("review", is_review=True)]
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT and ad.calls.count("read_step") == 2
    assert _row(w, r)["plan_source"] == "dom"
    assert len(w.store.answers(r.attempt_id)) == len(ad.fields)
    w.close()


def test_a_wizard_that_never_reaches_review_fails_after_the_step_limit():
    w, ad, cid, jid = fake_world()
    ad.dom = True
    ad.next_results = [StepResult(f"s{i}") for i in range(10)]
    r, factory, say = _one(w, ad, jid, apply_over={"max_wizard_steps": 3})
    assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED
    assert r.reason_detail == "fakeats: too many steps" and ad.calls.count("read_step") == 3
    w.close()


def test_the_attempt_deadline_ends_it_as_a_timeout():
    w, ad, cid, jid = fake_world()
    r, factory, say = _one(w, ad, jid, apply_over={"attempt_timeout_s": -1})
    assert r.state is S.FAILED and r.reason is R.ERROR and r.reason_detail == "timed out"
    w.close()


def test_a_required_field_that_will_not_take_its_value_is_a_validation_error():
    w, ad, cid, jid = fake_world()
    ad.fill_failed = [["phone"]]
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR and "Phone" in r.reason_detail
    assert "next_step" not in ad.calls, "a field that failed its read-back stops the form"
    assert w.answers_by_key(r.attempt_id)["phone"]["status"] == "fill_failed"
    w.close()


def test_an_optional_field_that_will_not_take_its_value_is_recorded_and_skipped():
    w, ad, cid, jid = fake_world()
    ad.fields.append(FormField("preferred_name", "Preferred First Name", FieldType.TEXT, False,
                               canonical=Canonical.PREFERRED_NAME))
    p = w.profile
    p["identity"]["preferred_name"] = "Lex"
    (w.tmp / "data" / "applicant.yaml").write_text(__import__("yaml").safe_dump(p), encoding="utf-8")
    ad.fill_failed = [["preferred_name"]]
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    assert w.answers_by_key(r.attempt_id)["preferred_name"]["status"] == "fill_failed"
    w.close()


def test_the_corrective_retry_refills_the_flagged_field_once_then_goes_on():
    w, ad, cid, jid = fake_world()
    ad.next_results = [StepResult("application", errors=("Phone",)),
                       StepResult("application", is_review=True)]
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    assert len(ad.fill_log) == 2 and set(ad.fill_log[1]) == {"phone"}, "only the flagged field again"
    assert "re-filled after an error" in w.answers_by_key(r.attempt_id)["phone"]["note"]
    assert "errors after Next: Phone" in say.text
    w.close()


def test_a_second_error_after_the_retry_is_a_validation_error():
    w, ad, cid, jid = fake_world()
    ad.next_results = [StepResult("application", errors=("Phone",)),
                       StepResult("application", errors=("Phone",))]
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.VALIDATION_ERROR and r.reason_detail == "Phone"
    assert ad.calls.count("next_step") == 2, "retried once, not again"
    w.close()


def test_an_optional_field_the_site_wants_after_all_is_re_resolved_as_required():
    w, ad, cid, jid = fake_world()
    ad.fields.append(unknown_optional(label="Describe your favourite hobby in detail"))
    ad.next_results = [StepResult("application", errors=("Describe your favourite hobby in detail",))]
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED
    assert "favourite hobby" in r.reason_detail
    w.close()


# ================================================================== prefill policies (D-70)

def _prefill_world(source="mygreenhouse", shown=None, fields=None):
    w, ad, cid, jid = fake_world()
    ad.fields = list(fields if fields is not None else default_fields() + [
        FormField("city", "City", FieldType.TEXT, False, canonical=Canonical.CITY)])
    ad.prefill_source = "mygreenhouse"
    ad.prefill_value = source
    ad.shown = shown or {}
    return w, ad, jid


def test_keep_keeps_a_site_value_and_fills_only_the_empty_fields():
    w, ad, jid = _prefill_world(shown={"first_name": "Pat", "last_name": "Q", "phone": "81234567",
                                       "email": "other@example.org", "resume": "old.pdf"})
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    filled = ad.fill_log[0]
    assert "first_name" not in filled and "last_name" not in filled and "phone" not in filled, \
        "non-empty site values are kept"
    assert filled["email"] == EMAIL, "the email is always ours (the watched mailbox)"
    assert filled["resume"].endswith("resume.pdf"), "the resume is always ours"
    assert filled["city"] == "Singapore", "an empty field is filled as usual"
    rows = w.answers_by_key(r.attempt_id)
    fn = rows["first_name"]
    assert (fn["status"], fn["tier"], fn["source"], fn["confidence"]) == \
        ("prefilled", 0, "mygreenhouse", 0.95)
    assert fn["note"] == "differs from profile (field_map:first_name)" and stored_value(fn) == "Pat"
    assert rows["email"]["status"] == "filled" and "replaced site value" in rows["email"]["note"]
    assert rows["resume"]["status"] == "filled"
    assert "prefill: mygreenhouse" in say.text
    w.close()


def test_keep_records_an_equal_value_as_already_on_page_with_no_input():
    w, ad, jid = _prefill_world(shown={"email": EMAIL, "first_name": "Alex"})
    r, factory, say = _one(w, ad, jid)
    assert "email" not in ad.fill_log[0], "the page already shows our email: nothing to type"
    rows = w.answers_by_key(r.attempt_id)
    assert rows["email"]["status"] == "filled" and "already on page" in rows["email"]["note"]
    assert rows["first_name"]["status"] == "prefilled" and rows["first_name"]["note"] == ""
    w.close()


def test_keep_overwrites_an_employer_specific_declaration_with_the_resolver_answer():
    from jobscraper.apply.contracts import Option
    rel = FormField("rel", "Do you have relatives working at Fake Co?", FieldType.DROPDOWN, True,
                    options=(Option("Yes"), Option("No")), section="questions")
    w, ad, jid = _prefill_world(fields=default_fields() + [rel], shown={"rel": "Yes"})
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    assert ad.fill_log[0].get("rel") in ("No", ["No"]), "a saved 'Yes' about THIS employer never stands"
    row = w.answers_by_key(r.attempt_id)["rel"]
    assert row["status"] == "filled" and row["tier"] == 4
    w.close()


def test_a_required_unknown_reaches_the_browser_only_when_mygreenhouse_may_answer_it():
    # prefilled by MyGreenhouse -> ready
    w, ad, jid = _prefill_world(fields=default_fields() + [unknown_required()],
                                shown={"question_1": "Rex"})
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT and factory.started == 1
    assert "checked again after the mygreenhouse autofill" in say.text
    row = w.answers_by_key(r.attempt_id)["question_1"]
    assert (row["status"], row["source"]) == ("prefilled", "mygreenhouse")
    w.close()
    # still empty after the prefill -> unanswerable_required, with the browser already open
    w, ad, jid = _prefill_world(fields=default_fields() + [unknown_required()])
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED and factory.started == 1
    assert "submit" not in ad.calls
    w.close()
    # MyGreenhouse switched off -> fails before the browser
    w, ad, jid = _prefill_world(fields=default_fields() + [unknown_required()])
    r, factory, say = _one(w, ad, jid, apply_over={"mygreenhouse": False})
    assert r.reason is R.UNANSWERABLE_REQUIRED and factory.started == 0
    w.close()


def test_a_failing_prefill_falls_back_to_the_full_fill():
    w, ad, jid = _prefill_world(shown={"first_name": "Pat"})
    ad.prefill_exc = RuntimeError(f"autofill broke for {EMAIL}")
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    assert ad.fill_log[0]["first_name"] == "Alex", "no prefill: every answer is typed"
    assert "prefill skipped: RuntimeError" in say.text and EMAIL not in say.text
    w.close()


def test_overwrite_replaces_site_values_keeps_an_optional_unanswerable_one_and_fails_a_required_one():
    w, ad, jid = _prefill_world(source="workday_last_application",
                                shown={"first_name": "Pat", "city": "Johor", "question_2": "Penang"},
                                fields=default_fields() + [unknown_optional()])
    ad.prefill_source = "workday_last_application"
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.READY_TO_SUBMIT
    assert ad.fill_log[0]["first_name"] == "Alex", "OVERWRITE: our answer wins"
    row = w.answers_by_key(r.attempt_id)["question_2"]
    assert (row["status"], row["source"], row["confidence"]) == \
        ("prefilled", "workday_last_application", 0.9)
    assert "replaced site value" in w.answers_by_key(r.attempt_id)["first_name"]["note"]
    w.close()
    w, ad, jid = _prefill_world(source="workday_last_application", shown={"question_1": "Rex"},
                                fields=default_fields() + [unknown_required()])
    r, factory, say = _one(w, ad, jid, apply_over={"mygreenhouse": True})
    assert r.state is S.FAILED and r.reason is R.UNANSWERABLE_REQUIRED, \
        "an unanswerable required field is never kept, even from a last application"
    w.close()


def test_keep_and_overwrite_decisions_on_their_own():
    f = FormField("city", "City", FieldType.TEXT, False)
    ans = Answer("city", "Singapore", AnswerTier.PROFILE_RULE, "profile:contact.city", 0.9)
    none = Answer("city", None, AnswerTier.NONE, "", 0.0, AnswerStatus.UNKNOWN)
    assert apply_flow.overwrite_decision(f, ans, "Johor") == "overwrite"
    assert apply_flow.overwrite_decision(f, none, "Johor") == "keep"
    assert apply_flow.overwrite_decision(f, none, "") == "fill"
    req = dataclasses.replace(f, required=True)
    assert apply_flow.overwrite_decision(req, none, "Johor") == "fill", "required + unanswerable: fail closed"
    box = FormField("c", "I agree", FieldType.CHECKBOX, True)
    assert apply_flow.keep_decision(box, ans, "false", EMAIL) == "overwrite"
    assert apply_flow.keep_decision(f, None, "x", EMAIL) == "keep"


def test_apply_prefill_policy_audits_a_kept_value_with_a_note_when_it_differs():
    f = FormField("city", "City", FieldType.TEXT, False)
    ans = Answer("city", "Singapore", AnswerTier.PROFILE_RULE, "profile:contact.city", 0.9)
    audit, to_fill = apply_flow.apply_prefill_policy("mygreenhouse", [f], {"city": ans},
                                                     {"city": "Johor"}, EMAIL)
    assert to_fill == {} and audit["city"].status is AnswerStatus.PREFILLED
    assert audit["city"].value == "Johor" and audit["city"].tier is AnswerTier.NONE
    assert audit["city"].note == "differs from profile (profile:contact.city)"
    audit, to_fill = apply_flow.apply_prefill_policy("mygreenhouse", [f], {"city": ans},
                                                     {"city": "singapore"}, EMAIL)
    assert audit["city"].note == "", "an equal value (after §7.1 normalisation) is no conflict"
    audit, to_fill = apply_flow.apply_prefill_policy("mygreenhouse", [f], {"city": ans},
                                                     {"city": ""}, EMAIL)
    assert "city" in to_fill, "empty: the planned answer is filled"


# ================================================================== resume choice (WP-B9 plumbing)

def _fake_tailor(w, jid, *, ok=True, tailored_id=42, raises=None):
    """Patch tailor_flow.tailor_for_apply; returns the list of calls and the file written."""
    from jobscraper import tailor_flow
    from jobscraper.tailor.contracts import TailorResult, TailorStatus
    out = w.tmp / "data" / "tailored_fake.pdf"
    out.write_bytes(b"%PDF-1.4 tailored\n")
    calls = []

    def fake(cfg, store, job_id, *, backend, say=None):
        calls.append(job_id)
        if raises:
            raise raises
        return TailorResult(job_id=job_id, ok=ok, status=TailorStatus.DRAFT if ok else TailorStatus.FAILED,
                            tailored_id=tailored_id if ok else None,
                            pdf_path=str(out) if ok else None, coverage_before=0.2,
                            coverage_after=0.6, **({} if ok else {}))
    saved = tailor_flow.tailor_for_apply
    tailor_flow.tailor_for_apply = fake
    return calls, out, saved


def test_a_tailored_resume_is_uploaded_recorded_and_marked_sent_only_after_submission():
    from jobscraper import tailor_flow
    w, ad, cid, jid = fake_world(tailor=True)
    calls, out, saved = _fake_tailor(w, jid)
    sent = []
    w.store.mark_tailored_sent = lambda tid, now=None: sent.append(tid)
    try:
        r, factory, say = _one(w, ad, jid, dry_run=False)
    finally:
        tailor_flow.tailor_for_apply = saved
    assert r.state is S.SUBMITTED and calls == [jid]
    row = _row(w, r)
    assert (row["resume_file"], row["resume_source"], row["tailored_id"]) == \
        ("tailored_fake.pdf", "tailored", 42)
    assert row["resume_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert ad.fill_log[0]["resume"] == str(out), "the tailored file is what the form receives"
    assert sent == [42], "the tailored file becomes `sent` once the application is confirmed"
    assert "resume: tailored (pdf), coverage 20% -> 60%" in say.text
    rows = w.answers_by_key(r.attempt_id)
    assert stored_value(rows["resume"])["file"] == "tailored_fake.pdf"
    w.close()


def test_a_dry_run_with_a_tailored_resume_does_not_mark_it_sent():
    from jobscraper import tailor_flow
    w, ad, cid, jid = fake_world(tailor=True)
    calls, out, saved = _fake_tailor(w, jid)
    sent = []
    w.store.mark_tailored_sent = lambda tid, now=None: sent.append(tid)
    try:
        r, factory, say = _one(w, ad, jid, dry_run=True)
    finally:
        tailor_flow.tailor_for_apply = saved
    assert r.state is S.READY_TO_SUBMIT and sent == []
    w.close()


def test_a_tailor_failure_falls_back_to_the_original_resume_and_the_attempt_goes_on():
    from jobscraper import tailor_flow
    for kw in ({"ok": False}, {"raises": RuntimeError("word is not installed")}):
        w, ad, cid, jid = fake_world(tailor=True)
        calls, out, saved = _fake_tailor(w, jid, **kw)
        try:
            r, factory, say = _one(w, ad, jid, dry_run=False)
        finally:
            tailor_flow.tailor_for_apply = saved
        assert r.state is S.SUBMITTED, kw
        row = _row(w, r)
        assert (row["resume_file"], row["resume_source"], row["tailored_id"]) == \
            ("resume.pdf", "original", None), kw
        assert "resume: original" in say.text
        w.close()


def test_with_the_tailor_off_it_is_never_called_and_no_tailoring_state_is_entered():
    from jobscraper import tailor_flow
    w, ad, cid, jid = fake_world(tailor=False)
    calls, out, saved = _fake_tailor(w, jid)
    try:
        r, factory, say = _one(w, ad, jid)
    finally:
        tailor_flow.tailor_for_apply = saved
    assert calls == [] and "tailoring" not in say.text
    w.close()


# ================================================================== lane B review oracles (Q-31)
# docs/reviews/M20-lane-B.md. These fail until lane B's fixes land (F1, F4); that is expected.

def test_f1_our_resume_is_uploaded_even_when_the_page_shows_a_file_of_the_same_name():
    from jobscraper import tailor_flow
    w, ad, jid = _prefill_world(shown={"resume": "tailored_fake.pdf"})
    w.cfg.raw["tailor"] = {"enabled": True}
    cid = w.store.conn.execute("SELECT company_id FROM jobs WHERE job_id = ?", (jid,)).fetchone()[0]
    calls, out, saved = _fake_tailor(w, jid)
    try:
        r, factory, say = _one(w, ad, jid, dry_run=False)
    finally:
        tailor_flow.tailor_for_apply = saved
    assert r.state is S.SUBMITTED
    assert ad.fill_log[0].get("resume") == str(out), \
        "MyGreenhouse showed a same-named file: ours must still be uploaded (D-70, 9.1.1)"
    row = w.answers_by_key(r.attempt_id)["resume"]
    assert row["status"] == "filled" and "already on page" not in (row["note"] or "")
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    assert stored_value(row)["sha256"] == sha, "the audit hash is the hash of the file uploaded"
    assert _row(w, r)["resume_sha256"] == sha
    w.close()


def test_f1_a_same_named_original_resume_is_replaced_too_in_a_dry_run():
    w, ad, jid = _prefill_world(shown={"resume": "resume.pdf", "email": EMAIL})
    r, factory, say = _one(w, ad, jid)
    assert "resume" in ad.fill_log[0], "a file name match proves nothing about the file's content"
    assert "email" not in ad.fill_log[0], "an equal email still needs no input (decision 4, accepted)"
    w.close()


def test_f1_apply_prefill_policy_never_skips_the_resume_input():
    f = FormField("resume", "Resume/CV", FieldType.FILE, True, canonical=Canonical.RESUME)
    ans = Answer("resume", "C:/x/resume.pdf", AnswerTier.FIELD_MAP, "field_map:resume", 0.99)
    for source in ("mygreenhouse", "workday_last_application"):
        audit, to_fill = apply_flow.apply_prefill_policy(source, [f], {"resume": ans},
                                                         {"resume": "resume.pdf"}, EMAIL)
        assert "resume" in to_fill, f"{source}: the file field must reach the adapter"
        assert "already on page" not in audit["resume"].note


def _in_progress(w, cid, n, *, clicked=False):
    """An attempt another process is running right now (started a moment ago)."""
    _, other = add_job(w.store, external_id=str(100 + n), slug="fakeco", provider="fakeats",
                       key="x", company_id=cid, url=f"https://fake.example.com/jobs/{100 + n}")
    aid = w.store.create_attempt(other, cid, "auto", store_mod.utcnow())
    if clicked:
        _walk_clicked(w.store, aid, store_mod.utcnow())
    else:
        for s in ("planning", "opening", "filling"):
            w.store.set_attempt_state(aid, s)
        w.store.commit()
    return aid


@contextlib.contextmanager
def _lock_held_by_another_process(w):
    """A real second process holding `<evidence dir>/run.lock` (the lane B run lock, review F4)."""
    path = w.tmp / "evidence" / "run.lock"
    src = Path(__file__).resolve().parents[1] / "src"
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from jobscraper import apply_flow\n"
            "lock = apply_flow.RunLock(%r)\n"
            "print('locked' if lock.acquire() else 'busy', flush=True)\n"
            "sys.stdin.readline()\n"
            "lock.release()\n") % (str(src), str(path))
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "locked", "the helper process could not take the lock"
        yield
    finally:
        try:
            proc.stdin.write("\n")
            proc.stdin.flush()
        except OSError:
            pass
        proc.wait(timeout=30)


def test_f4_a_run_starts_nothing_and_reaps_nothing_while_another_process_holds_the_run_lock():
    for clicked, state in ((False, "filling"), (True, "submitting")):
        w, ad, cid, jid = fake_world()
        live = _in_progress(w, cid, 1, clicked=clicked)
        with _lock_held_by_another_process(w):
            res, factory, say = _run(w, [jid], ad)
        assert res == [] and factory.started == 0, "a second run must start nothing"
        assert "another apply run is in progress; nothing was started" in say.text
        row = w.store.attempt(live)
        assert row["state"] == state and row["finished_at"] is None, \
            f"the other run's live attempt must not be rewritten (clicked={clicked}): {row['state']}"
        assert len(w.attempt_rows()) == 1, "no attempt row was created for the refused run"
        # the other process is gone (its lock is released): now its attempt is a dead run's
        res, factory, say = _run(w, [jid], ad)
        assert res and res[0].state is S.READY_TO_SUBMIT, say.text
        closed = w.store.attempt(live)
        assert closed["state"] == ("submitted_unconfirmed" if clicked else "failed"), closed
        w.close()


def test_f4_the_run_lock_is_released_when_a_run_ends_even_by_an_error():
    w, ad, cid, jid = fake_world()
    r1, _, _ = _one(w, ad, jid)
    assert r1.state is S.READY_TO_SUBMIT
    ad.on_open = lambda page, ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    _, j2 = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                    company_id=cid, url="https://fake.example.com/jobs/2")
    r2, _, _ = _one(w, ad, j2)
    assert r2.state is S.FAILED
    ad.on_open = None
    _, j3 = add_job(w.store, external_id="3", slug="fakeco", provider="fakeats", key="x",
                    company_id=cid, url="https://fake.example.com/jobs/3")
    r3, _, _ = _one(w, ad, j3)
    assert r3.state is S.READY_TO_SUBMIT, "a finished run leaves no lock behind"
    lock = apply_flow.RunLock(w.tmp / "evidence" / "run.lock")
    assert lock.acquire(), "and the lock file is free"
    lock.release()
    w.close()


def test_f3_a_missing_submit_button_fails_before_the_click_is_recorded():
    w, ad, cid, jid = fake_world()
    ad.submit_ready = lambda page: False
    r, factory, say = _one(w, ad, jid, dry_run=False)
    assert r.state is S.FAILED and r.reason is R.PAGE_UNRECOGNISED, (r.state, r.reason, r.reason_detail)
    assert "submit button" in r.reason_detail and "submit" not in ad.calls
    assert _row(w, r)["submit_clicked_at"] is None, "nothing was sent, so the job is not blocked"
    w.close()


def test_f5_a_failure_detail_never_carries_a_profile_value_into_the_row_or_the_result():
    from jobscraper.apply.contracts import ApplyFailure
    w, ad, cid, jid = fake_world()
    ad.schema_exc = ApplyFailure(R.VALIDATION_ERROR, f"the site said {EMAIL} is not valid", step="planning")
    r, factory, say = _one(w, ad, jid)
    assert r.state is S.FAILED and EMAIL not in r.reason_detail and "[redacted]" in r.reason_detail
    assert EMAIL not in " ".join(str(v) for v in _row(w, r).values())
    assert EMAIL not in say.text
    w.close()


def test_f6_a_digit_value_is_redacted_even_next_to_other_digits_but_words_stay_whole():
    assert apply_flow.redact("call +6591234567 now", ["91234567"]) == "call +65[redacted] now"
    assert apply_flow.redact("postal S000001", ["000001"]) == "postal S[redacted]"
    assert apply_flow.redact("captcha and cap", ["cap"]) == "captcha and [redacted]"


def test_f4_the_flow_rechecks_duplicates_just_before_the_click():
    w, ad, cid, jid = fake_world()
    ad.on_open = lambda page, ctx: w.store.set_application_status(jid, "applied")   # applied by hand meanwhile
    r, factory, say = _one(w, ad, jid, dry_run=False)
    assert "submit" not in ad.calls, "the job became a duplicate after the guards: never click"
    assert r.state is S.FAILED and r.reason is R.DUPLICATE
    assert _row(w, r)["submit_clicked_at"] is None
    w.close()


def test_f4_the_flow_rechecks_the_caps_just_before_the_click():
    w, ad, cid, jid = fake_world()
    _, other = add_job(w.store, external_id="2", slug="fakeco", provider="fakeats", key="x",
                       company_id=cid, url="https://fake.example.com/jobs/2")
    ad.on_open = lambda page, ctx: _clicked_today(w, cid, other)      # another run sent one meanwhile
    r, factory, say = _one(w, ad, jid, dry_run=False, apply_over={"daily_cap": 1})
    assert "submit" not in ad.calls, "the cap was reached after the guards: never click"
    assert r.state is S.FAILED and r.reason is R.CAP_REACHED, (r.state, r.reason, r.reason_detail)
    assert _row(w, r)["submit_clicked_at"] is None
    w.close()


# ================================================================== helpers and drift guards

def test_day_start_is_singapore_midnight_in_utc():
    # 2026-11-02 20:00 UTC is already 2026-11-03 04:00 in Singapore
    now = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
    assert apply_flow.day_start_utc(now) == "2026-11-02T16:00:00"
    now = datetime(2026, 11, 2, 15, 59, tzinfo=timezone.utc)          # 23:59 in Singapore
    assert apply_flow.day_start_utc(now) == "2026-11-01T16:00:00"
    now = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)           # exactly SG midnight
    assert apply_flow.day_start_utc(now) == "2026-11-02T16:00:00"


def test_the_store_transition_table_matches_the_contract_and_drift_is_caught():
    apply_flow.check_attempt_table()                                  # no raise now
    saved = dict(store_mod.ATTEMPT_TRANSITIONS)
    try:
        store_mod.ATTEMPT_TRANSITIONS["queued"] = frozenset(saved["queued"] | {"submitted"})
        try:
            apply_flow.check_attempt_table()
        except RuntimeError as exc:
            assert "differs" in str(exc)
        else:
            raise AssertionError("a drifted copy of the table must stop the run")
    finally:
        store_mod.ATTEMPT_TRANSITIONS.clear()
        store_mod.ATTEMPT_TRANSITIONS.update(saved)


def test_same_value_compares_text_choice_files_and_sets_the_same_way_the_page_shows_them():
    ans = lambda v, **k: Answer("f", v, AnswerTier.PROFILE_RULE, "profile:x", 0.9, **k)   # noqa: E731
    t = FormField("f", "L", FieldType.TEXT)
    assert apply_flow.same_value(t, ans("Hello  World"), "hello world")
    assert not apply_flow.same_value(t, ans("a"), "b")
    d = FormField("f", "L", FieldType.DROPDOWN)
    assert apply_flow.same_value(d, ans("N", option_labels=("No",)), "No")
    fl = FormField("f", "L", FieldType.FILE)
    assert apply_flow.same_value(fl, ans("C:/x/y/resume.pdf"), "resume.pdf")
    m = FormField("f", "L", FieldType.MULTI_CHOICE)
    assert apply_flow.same_value(m, ans(["A", "B"], option_labels=("A", "B")), ["b", "a"])
    cb = FormField("f", "L", FieldType.CHECKBOX)
    assert apply_flow.same_value(cb, ans("true"), "true")
