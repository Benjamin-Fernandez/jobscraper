"""Q-121 flow review fixes F2-F7, F9, F13, F14 and the trial ruling: pins.

What each guards, in the words of the review (docs/reviews/Q-121-flow-code.md) and the Coordinator's
rulings: F2 an "Answered for you" question never takes another question's key (Keep would
overwrite the owner's own answer); F3 an open question is not demoted by an assumed sighting and
a stopped role stays "ready to retry"; F5 a failed "Add another" is a note, the attempt goes on
to the scan; F7 secrets are registered before the tailor/compose prompt; F13 the guess count of a
page filled twice is counted once; a new trial size restarts the trial; a refused prompt in the
compose step is `error` "prompt check" under both policies; config values never raise.
Same seam as tests/test_always_flow.py (tests/always_flow_support.py): mock Ollama on
127.0.0.1:11434, fake navigator, temp DB, test config, "Example Co"; the web app only through
TestClient (nothing starts a job). Verify: python tests/run_tests.py -k always_flow
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import Net, backend, make, nav_class, page, run_batch  # noqa: E402
from vault_support import memory_keyring  # noqa: E402

from jobscraper import apply_flow, backends  # noqa: E402
from jobscraper.apply import always as AL, questions as Q  # noqa: E402
from jobscraper.apply.contracts import AttemptState as ST, FieldType, ReasonCode as R  # noqa: E402
from jobscraper.config import ApplyConfig, ComposeConfig, trial_runs_value  # noqa: E402

ALWAYS = {"fill_policy": "always"}
LABEL = "Preferred coding language"


@contextlib.contextmanager
def web(w):
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    cfg = Config({"paths": {"db": str(w.db_path), "applicant": str(w.cfg.applicant_path),
                            "shortlist": str(w.tmp / "data" / "shortlist.json"),
                            "profile": str(w.tmp / "data" / "profile.derived.yaml"),
                            "resume_dir": str(w.tmp / "data")},
                  "web": {"host": "127.0.0.1", "port": 8765}})
    app = create_app(cfg)

    class Idle:
        def current(self, tail=200):
            from jobscraper.web.jobs import IDLE
            return dict(IDLE, log=[])

    app.state.jobs = Idle()
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def _profile_with_answer():
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["extra"] = {"favourite_language": {
        "title": "Favourite language", "description": "", "kind": "text", "sensitive": False,
        "labels": ["what is your favourite programming language"], "value": "Python"}}
    return p


def _naming_system() -> str:
    return Q.NAMING_SYSTEM


# ================================================================== F2: no naming for an assumed question

def test_an_assumed_question_is_never_named_by_the_model_and_remembering_it_leaves_the_owners_answer_alone():
    # Q-127 T0: the Keep route is retired; the same need is "Use a different answer next time" on the
    # answer row (POST .../answers/{id}/remember), which never touches another entry (design H2).
    import llm_fill_t2 as T
    w, _cid, jobs = make(1, profile=_profile_with_answer())
    try:
        namings = []

        def chat(body):
            if body["messages"][0]["content"] == _naming_system():
                namings.append(body)             # the model would say: this is the same as favourite_language
                return httpx.Response(200, json={"message": {"content": json.dumps(
                    {"key": "zz_model_key", "title": "t", "description": "", "same_as": "favourite_language"})},
                    "done_reason": "stop"})
            return S.answering(value="Rust")(body)
        net = Net(chat)
        script = S.real_page([T.pf("lang", LABEL, FieldType.TEXT, required=True)], "one")
        res, _f, _s = run_batch(w, jobs, nav_class()(), backend(net), script, **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason_detail)
        sent = [b for _m, p, b in net.log if p == "/api/chat" and _naming_system()[:30] in b]
        assert not namings and not sent, "F2: no naming call is spent on an assumed question"
        groups = w.store.question_groups("assumed")
        assert len(groups) == 1 and groups[0]["key"] not in ("favourite_language", "zz_model_key"), groups
        with web(w) as client:
            from jobscraper import applicant
            row = [a for a in w.store.answers(res[0].attempt_id) if a["label"] == LABEL][0]
            r = client.post(f"/api/applications/{jobs[0]}/attempts/{res[0].attempt_id}/answers/{row['id']}/remember",
                            json={"value": "Rust", "only_employer": False,
                                  "etag": applicant.etag(w.cfg.applicant_path)})
            assert r.status_code == 200, r.text
            assert r.json()["key"] not in ("favourite_language", "zz_model_key"), r.json()
        extra = yaml.safe_load(Path(w.cfg.applicant_path).read_text(encoding="utf-8"))["extra"]
        assert extra["favourite_language"]["value"] == "Python", "the owner's own answer is untouched"
        assert [e["value"] for k, e in extra.items() if k != "favourite_language"] == ["Rust"], extra
    finally:
        w.close()


# ================================================================== F3: an open question stays open

def _unknown_colour():
    U = S._u()

    def script(nav, services, ctx, rctx):
        f = U.pf("colour", "Favourite colour", required=True)
        return U.outcome("one", [f], {"colour": U.ans("colour", None, status=S.AnswerStatus.UNKNOWN,
                                                      note="no profile value")}, unknown_required=("colour",))
    return script


def _assumed_colour():
    U = S._u()

    def script(nav, services, ctx, rctx):
        f = U.pf("colour", "Favourite colour", required=True)
        a = dataclasses.replace(U.ans("colour", "Blue"), source="assumption", assumed=True, evidence="a guess")
        return U.outcome("one", [f], {"colour": a}, assumed=("colour",))
    return script


def test_an_assumed_sighting_does_not_demote_an_open_question_and_the_stopped_role_stays_retryable():
    w, _cid, jobs = make(2)
    try:
        res, _f, _s = run_batch(w, jobs[:1], nav_class()(), backend(Net()), _unknown_colour(), **ALWAYS)
        assert res[0].reason is R.UNANSWERABLE_REQUIRED
        before = w.store.conn.execute("SELECT status, reason FROM questions").fetchall()
        assert len(before) == 1 and before[0]["status"] == "open"
        res, _f, _s = run_batch(w, jobs[1:], nav_class()(), backend(Net()), _assumed_colour(), **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT
        after = w.store.conn.execute("SELECT status, reason FROM questions").fetchall()
        assert [(r["status"], r["reason"]) for r in after] == [(before[0]["status"], before[0]["reason"])], \
            "F3: still open, reason not rewritten by the assumed sighting"
        assert [g["labels"][0] for g in w.store.question_groups("open")] == ["Favourite colour"]
        assert w.store.question_groups("assumed") == []
        assert jobs[0] in {c["job_id"] for c in w.store.retry_candidates()}, "the stopped role is still 'ready to retry'"
    finally:
        w.close()


def test_an_answered_question_seen_as_assumed_becomes_assumed_and_keeps_its_reason():
    from questions_support import question_row
    w, _cid, jobs = make(1)
    try:
        now = "2026-11-12T12:00:00"
        row = question_row(key="colour", label="Favourite colour", kind="text", reason="no_rule")
        qid = w.store.upsert_question(row, now)
        w.store.set_questions_status("colour", "answered", now, ids=[qid])
        w.store.upsert_question({**row, "reason": "assumed"}, now)
        got = w.store.conn.execute("SELECT status, reason FROM questions WHERE id=?", (qid,)).fetchone()
        assert (got["status"], got["reason"]) == ("assumed", "no_rule"), dict(got)
    finally:
        w.close()


# ================================================================== F5: a failed Add is a note

def _short_add_page():
    U = S._u()

    def script(nav, services, ctx, rctx):
        services.log("E5: 1 of 2 education entries added (the Add button did not respond)")
        f = U.pf("school", "School", required=True)
        a = U.ans("school", "Nanyang Example University",
                  note="E5: another education entry could not be added (no button) - this value was typed")
        return U.outcome("one", [f], {"school": a}, fill_failed=("school",))
    return script


def test_a_failed_add_under_always_is_a_note_on_the_attempt_and_the_scan_still_runs():
    w, _cid, jobs = make(1)
    try:
        res, _f, say = run_batch(w, jobs, nav_class()(), backend(Net()), _short_add_page(), **ALWAYS)
        r = res[0]
        assert r.state is ST.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
        assert "pre-Submit scan passed" in say.text, "the attempt went on to the scan"
        assert w.store.attempt(r.attempt_id)["entries_note"] == "1 of 2 education entries added"
        assert w.store.entries_notes([r.attempt_id, 999]) == {r.attempt_id: "1 of 2 education entries added"}
        assert ' entries="1 of 2 education entries added"' in say.text
    finally:
        w.close()
    w, _cid, jobs = make(1)                           # strict: unchanged, a failed Add stops (D-174), no note
    try:
        res, _f, say = run_batch(w, jobs, nav_class()(), backend(Net()), _short_add_page())
        assert res[0].reason is R.VALIDATION_ERROR, (res[0].state, res[0].reason)
        assert not w.store.attempt(res[0].attempt_id)["entries_note"] and "entries=" not in say.text
    finally:
        w.close()


# ================================================================== F7: secrets before the tailor prompt

def test_the_known_secrets_are_registered_before_the_tailor_resume_step():
    from apply_flow_support import EMAIL
    secret = 'Pw"Dummy\\Zq7 x9!'
    with memory_keyring():
        w, _cid, jobs = make(1)
        try:
            nav = nav_class()()
            S.put_account(w, nav, EMAIL, secret)
            net = Net()
            be = backend(net)
            seen = {}
            real = apply_flow._Run.resume

            def resume(self, at, job):
                for leak in S.forms(secret):
                    try:
                        be.complete("tailor", f"resume of the applicant {leak}")
                        seen.setdefault("sent", []).append(leak)
                    except backends.PromptRefused:
                        seen.setdefault("refused", []).append(leak)
                return real(self, at, job)
            apply_flow._Run.resume = resume
            try:
                res, _f, _s = run_batch(w, jobs, nav, be, **ALWAYS)
            finally:
                apply_flow._Run.resume = real
            assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason_detail)
            assert "sent" not in seen and len(seen["refused"]) == 2, seen
            assert not net.carries(*S.forms(secret)), "no request body carries it, tailor path included"
        finally:
            w.close()


def test_a_refused_prompt_in_the_compose_step_is_error_prompt_check_under_both_policies():
    U = S._u()
    for policy in ("always", "strict"):
        w, _cid, jobs = make(1)
        try:
            calls = []

            def script(nav, services, ctx, rctx):
                f = U.pf("cover", "Cover letter", required=True)
                return U.outcome("one", [f], {"cover": U.ans("cover", None, status=S.AnswerStatus.UNKNOWN,
                                                              note="compose needed")},
                                 compose_needed=("cover",))

            def fake_compose(*a, **kw):
                calls.append(kw)
                return SimpleNamespace(ok=False, error="transport: PromptRefused (prompt refused)", text="",
                                       model="", prompt_hash="")
            real = apply_flow.tailor_flow.compose
            apply_flow.tailor_flow.compose = fake_compose
            try:
                res, _f, _s = run_batch(w, jobs, nav_class()(), backend(Net()), script, fill_policy=policy,
                                        compose=ComposeConfig(enabled=True))
            finally:
                apply_flow.tailor_flow.compose = real
            r = res[0]
            assert calls, "the compose step ran"
            assert r.state is ST.FAILED and r.reason is R.ERROR and r.reason_detail == "prompt check", \
                (policy, r.state, r.reason, r.reason_detail)
        finally:
            w.close()


# ================================================================== F13: a page filled twice counts once

def test_the_guess_count_of_a_page_filled_again_is_not_counted_twice():
    def pages(nav, services, ctx, rctx):
        step = nav.step_id(None, None)
        key = "one" if step == "one" else "two"          # the review-time refill repeats page two
        return S.real_page(S.req_numbers(key, 5), key)(nav, services, ctx, rctx)
    w, _cid, jobs = make(1)
    try:
        nav = nav_class()(steps=("one", "two", "review"))
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), pages, hits=lambda n: ("x",) if n == 1 else (),
                                 **ALWAYS)
        assert len(say.calls) == 3, "pages one and two, plus one refill"
        assert res[0].state is ST.READY_TO_SUBMIT, \
            (res[0].state, res[0].reason, res[0].reason_detail, "10 guesses are within the limit of 12")
    finally:
        w.close()


def test_the_corrective_pass_after_next_errors_does_not_double_the_guess_count_either():
    def pages(nav, services, ctx, rctx):
        step = nav.step_id(None, None)
        return S.real_page(S.req_numbers(step, 5), step)(nav, services, ctx, rctx)
    w, _cid, jobs = make(1)
    try:
        Base = nav_class()

        class ErrOnce(Base):                              # the first Next on page two shows an error
            n = 0

            def next_step(self, pg, ctx):
                self.n += 1
                if self.n == 2:
                    return S.StepResult(step=self.steps[self.at], errors=["Field is required"])
                return super().next_step(pg, ctx)
        nav = ErrOnce(steps=("one", "two", "review"))
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), pages, **ALWAYS)
        assert len(say.calls) == 3, "page one, page two, page two again (corrective)"
        assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason, res[0].reason_detail)
    finally:
        w.close()


def test_a_stopped_attempts_detail_names_the_step_and_holds_no_value_or_secret():
    for policy_script, want in (
            (S.stop_with(R.UNANSWERABLE_REQUIRED, "would be guesses: too many last-resort answers", step="two"),
             " on two"),
            (S.stop_with(R.OWNER_FACT_MISSING, "date of birth", step="two", field_key="dob", label="Date of Birth",
                         target_path="identity.date_of_birth", sensitive=True), "on two)")):
        w, _cid, jobs = make(1)
        try:
            res, _f, say = run_batch(w, jobs, nav_class()(steps=("two", "review")), backend(Net()), policy_script,
                                     **ALWAYS)
            detail = res[0].reason_detail
            assert detail.endswith(want) or want in detail, detail
            for personal in ("1990", "Alex", "alex.testcase", "Nanyang"):
                assert personal not in detail and personal not in say.text.split("failed reason")[-1][:300], personal
        finally:
            w.close()


# ================================================================== trial: reset both ways, unreadable counter

def test_a_new_trial_size_restarts_the_trial_and_the_same_size_does_not():
    from jobscraper.store import Store
    w, _cid, _jobs = make(1)
    try:
        def used():
            st = Store(w.db_path)
            try:
                return st.always_trial_used()
            finally:
                st.close()

        def set_used(n):
            w.store.set_setting(w.store.ALWAYS_TRIAL_USED, n)
            w.store.commit()
        with web(w) as client:
            set_used(2)
            assert client.put("/api/apply/settings", json={"always_trial_runs": 3}).status_code == 200
            assert used() == 0, "a different size starts a new trial"
            set_used(2)
            assert client.put("/api/apply/settings", json={"always_trial_runs": 3}).status_code == 200
            assert used() == 2, "the same size changes nothing"
            assert client.put("/api/apply/settings", json={"headed": False}).status_code == 200
            assert used() == 2, "a save without the key changes nothing"
            assert client.put("/api/apply/settings", json={"always_trial_runs": 0}).status_code == 200
            assert used() == 0, "turning it off is a different size too"
    finally:
        w.close()


def test_an_unreadable_trial_counter_runs_a_dry_run_with_a_warning_never_a_crash_or_a_submit():
    w, _cid, jobs = make(1)
    try:
        nav = nav_class()()

        def broken():
            raise RuntimeError("settings table gone")
        w.store.always_trial_used = broken
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=False, always_trial_runs=1, **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT and nav.submits == 0
        assert "trial" in say.text.lower() and "?" in say.text, "the log line says the count is unknown"
    finally:
        w.close()


# ================================================================== F9: config values never raise

def test_config_odd_values_never_raise_and_read_as_the_documented_value():
    inf, nan = yaml.safe_load(".inf"), yaml.safe_load(".nan")
    logging.disable(logging.CRITICAL)
    try:
        for raw, want in ((3, 3), (3.0, 3), ("3.0", 3), (" 4 ", 4), (0, 0), (20, 20), (25, 20), (inf, 20),
                          (-yaml.safe_load(".inf"), 0), (nan, 0), (3.5, 0), (-1, 0), (True, 0), ("many", 0),
                          ([2], 0), ({"a": 1}, 0), (None, 0), ("", 0)):
            assert trial_runs_value(raw) == want, (raw, trial_runs_value(raw), want)
            assert ApplyConfig.from_raw({"always_trial_runs": raw}).always_trial_runs == want, raw
        default = dict(ApplyConfig().llm_fill.max_entries)
        assert default == {"education": 2, "experience": 3}
        for me, want in (({"education": 1}, {"education": 1, "experience": 3}),
                         ({"education": 2.0}, {"education": 2, "experience": 3}),
                         ({"education": 99}, {"education": 20, "experience": 3}),
                         ({"education": inf}, default), ({"education": nan}, default),
                         ({"education": "two"}, default), ({"education": True}, default),
                         ({"education": 2.5}, default), ({"education": None}, default),
                         ("many", default), ([1, 2], default), (7, default), (None, default)):
            got = dict(ApplyConfig.from_raw({"llm_fill": {"max_entries": me}}).llm_fill.max_entries)
            assert got == want, (me, got, want)
        hash(ApplyConfig.from_raw({"llm_fill": {"max_entries": {"education": 1}}}).llm_fill)   # stays hashable
    finally:
        logging.disable(logging.NOTSET)
