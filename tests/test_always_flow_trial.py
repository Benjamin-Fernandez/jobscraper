"""Q-121 WP-F1/S1 flow oracles, part 3: the first-use trial (oracle 20, §12 rev H3), Keep and
Change on an "Answered for you" answer (oracle 18, §6.3), and `jobscraper doctor` (oracle 9).

The trial is the only gate between `always` and a real submission on the owner's first live
clicks: its pins fail when a trial attempt submits, when a dry-run click is raised to auto, when
a trial is used up by an attempt that never reached the review page, or when it has an effect
under `strict`. The Keep pins fail when the value saved is not the value that was sent.
Same seam as tests/test_always_flow.py (tests/always_flow_support.py).
Verify: python tests/run_tests.py -k always_flow
"""
from __future__ import annotations

import contextlib
import io
import logging
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import Net, backend, make, nav_class, page, run_batch, run_q  # noqa: E402

from jobscraper import apply_flow, cli  # noqa: E402
from jobscraper.apply import always as AL, questions as Q  # noqa: E402
from jobscraper.apply.contracts import AttemptState as ST, FieldType, ReasonCode as R  # noqa: E402

ALWAYS = {"fill_policy": "always"}
SENT = (ST.SUBMITTED, ST.SUBMITTED_UNCONFIRMED)


def _modes(w):
    return [(r["mode"], r["state"], r["submit_clicked_at"] is not None) for r in w.attempt_rows()]


# ================================================================== oracle 20: the trial

def test_the_first_n_attempts_under_always_are_dry_runs_and_the_next_one_submits_per_mode():
    w, _cid, jobs = make(3)
    try:
        nav = nav_class()()
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=False, always_trial_runs=2, **ALWAYS)
        assert [r.state for r in res[:2]] == [ST.READY_TO_SUBMIT, ST.READY_TO_SUBMIT], [r.state for r in res]
        assert res[2].state in SENT
        assert _modes(w) == [("dry_run", "ready_to_submit", False), ("dry_run", "ready_to_submit", False),
                             ("auto", res[2].state.value, True)], _modes(w)
        assert nav.submits == 1, "only the third attempt reached Submit"
        assert w.store.always_trial_used() == 2
        assert "Trial: filled, not sent (trial 1 of 2)" in say.text and "(trial 2 of 2)" in say.text
        assert "(trial 3 of 2)" not in say.text
    finally:
        w.close()


def test_a_dry_run_click_is_never_raised_to_auto_and_never_uses_up_a_trial():
    w, _cid, jobs = make(2)
    try:
        nav = nav_class()()
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=True, always_trial_runs=2, **ALWAYS)
        assert all(r.state is ST.READY_TO_SUBMIT for r in res) and nav.submits == 0
        assert w.store.always_trial_used() == 0, "a dry-run attempt does not count"
        assert "Trial:" not in say.text
        w.store.set_setting(w.store.ALWAYS_TRIAL_USED, 2)                  # the trial is used up: still dry
        w.store.conn.execute("DELETE FROM apply_attempts")
        w.store.commit()
        res, _f, _s = run_batch(w, jobs, nav, backend(Net()), dry_run=True, always_trial_runs=2, **ALWAYS)
        assert all(r.state is ST.READY_TO_SUBMIT for r in res) and nav.submits == 0
        assert [m for m, _s, _c in _modes(w)] == ["dry_run", "dry_run"]
    finally:
        w.close()


def test_no_trial_when_the_count_is_zero_and_never_under_strict():
    for over in ({"fill_policy": "always", "always_trial_runs": 0}, {"fill_policy": "strict", "always_trial_runs": 3}):
        w, _cid, jobs = make(1)
        try:
            nav = nav_class()()
            res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=False, **over)
            assert res[0].state in SENT and nav.submits == 1, (over, res[0].state)
            assert "Trial:" not in say.text and w.store.always_trial_used() == 0
        finally:
            w.close()


def test_a_trial_attempt_that_stops_before_the_review_page_does_not_use_up_the_trial():
    w, _cid, jobs = make(2)
    try:
        nav = nav_class()()
        stop = S.stop_with(R.OWNER_FACT_MISSING, "date of birth", step="one", field_key="dob",
                           label="Date of Birth", target_path="identity.date_of_birth", sensitive=True)
        res, _f, _s = run_batch(w, jobs[:1], nav, backend(Net()), stop, dry_run=False, always_trial_runs=1, **ALWAYS)
        assert res[0].state is ST.FAILED and w.store.always_trial_used() == 0
        res, _f, _s = run_batch(w, jobs[1:], nav, backend(Net()), dry_run=False, always_trial_runs=1, **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT and nav.submits == 0, "the trial was still there for this one"
        assert w.store.always_trial_used() == 1
    finally:
        w.close()


def test_a_trial_counter_that_cannot_be_read_counts_as_a_trial_and_the_attempt_goes_on_as_a_dry_run():
    w, _cid, jobs = make(1)
    try:
        nav = nav_class()()

        def broken():
            raise RuntimeError("settings table gone")
        w.store.always_trial_used = broken
        res, _f, _s = run_batch(w, jobs, nav, backend(Net()), dry_run=False, always_trial_runs=1, **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT and nav.submits == 0, "unreadable counter: nothing is sent"
    finally:
        w.close()


def test_a_trial_counter_that_cannot_be_written_does_not_end_the_attempt():
    w, _cid, jobs = make(1)
    try:
        nav = nav_class()()

        def cannot_write():
            raise RuntimeError("read only")
        w.store.count_always_trial = cannot_write
        res, _f, say = run_batch(w, jobs, nav, backend(Net()), dry_run=False, always_trial_runs=1, **ALWAYS)
        assert res[0].state is ST.READY_TO_SUBMIT and nav.submits == 0
        assert "trial counter not updated" in say.text
    finally:
        w.close()


def test_the_trial_holds_in_the_queue_too_and_only_lowers_the_one_attempt():
    w, cid, jobs = make(2)
    try:
        nav = nav_class()()
        run_q(w, cid, jobs, nav, backend(Net()), item_mode="auto", mode="auto", always_trial_runs=1, **ALWAYS)
        modes = _modes(w)
        assert [m[:2] for m in modes] == [("dry_run", "ready_to_submit"), ("auto", modes[1][1])], modes
        assert modes[1][1] in {s.value for s in SENT} and modes[1][2] is True
        assert nav.submits == 1, "the second queued role submitted per mode; the first did not"
        assert not w.store.queue_positions() and w.store.queue_pause_state() is None
    finally:
        w.close()


# ================================================================== oracle 18: Keep and Change

LANG = "What is your favourite programming language?"


def _lang_page(label=LANG):
    import llm_fill_t2 as T
    return S.real_page([T.pf("lang", label, FieldType.TEXT, required=True)], "one")


@contextlib.contextmanager
def _web(w):
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    cfg = Config({"paths": {"db": str(w.db_path), "applicant": str(w.cfg.applicant_path),
                            "shortlist": str(w.tmp / "data" / "shortlist.json"),
                            "profile": str(w.tmp / "data" / "profile.derived.yaml"),
                            "resume_dir": str(w.tmp / "data")},
                  "web": {"host": "127.0.0.1", "port": 8765}})
    app = create_app(cfg)

    class Idle:                                                    # no job can start from these tests
        def current(self, tail=200):
            from jobscraper.web.jobs import IDLE
            return dict(IDLE, log=[])

    app.state.jobs = Idle()
    with TestClient(app, base_url="http://localhost") as client:
        yield client, cfg


def _first_attempt(w, jobs, value="Python"):
    net = Net(S.answering(value=value))
    res, _f, _s = run_batch(w, jobs[:1], nav_class()(), backend(net), _lang_page(), **ALWAYS)
    assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason_detail)
    groups = w.store.question_groups("assumed")
    assert len(groups) == 1 and groups[0]["labels"] == [LANG], groups
    return groups[0], w.store.assumed_answer(groups[0]["variants"][0]["question_id"])


def _answer(client, w, group, value, job_id=None):
    """Q-127 T0: the cards' answer route is retired (410). The same owner need is "Use a different
    answer next time" on the first attempt's answer row: POST .../answers/{id}/remember, for every
    employer (so the test does not depend on how the employer name is spelled)."""
    from jobscraper import applicant
    row = [a for a in w.store.conn.execute("SELECT * FROM apply_answers WHERE label = ? ORDER BY id", (LANG,))][0]
    att = w.store.attempt(row["attempt_id"])
    r = client.post(f"/api/applications/{att['job_id']}/attempts/{row['attempt_id']}/answers/{row['id']}/remember",
                    json={"value": value, "only_employer": False, "etag": applicant.etag(w.cfg.applicant_path)})
    assert r.status_code == 200, r.text
    return r.json()


def _second_attempt(w, jobs):
    """The next attempt on the same question, through the real always.py: the model is asked
    about every FIELDS call it receives, and we record which labels it was asked about."""
    net = Net(S.answering(value="WRONG-should-not-be-asked"))
    res, _f, _s = run_batch(w, jobs[1:2], nav_class()(), backend(net), _lang_page(), **ALWAYS)
    assert res[0].state is ST.READY_TO_SUBMIT, (res[0].state, res[0].reason_detail)
    asked = [c for c in net.chats if "== FIELDS (JSON) ==" in c["messages"][-1]["content"]]
    return res[0], [LANG in c["messages"][-1]["content"].split("== FIELDS (JSON) ==", 1)[1] for c in asked]


def test_an_assumed_answer_is_listed_with_what_was_sent_and_why():
    w, _cid, jobs = make(2)
    try:
        group, sent = _first_attempt(w, jobs)
        assert group["status"] == "assumed" and group["reason"] == "assumed"
        assert sent["value"] == "Python" and sent["assumed"] is True and sent["source"] == "assumption", sent
        assert sent["reason"] == "dummy", "the card's {reason} is the model's reason"
        assert Q.kept_value(group["kind"], sent["value"]) == "Python"
    finally:
        w.close()


def test_keep_saves_the_sent_value_and_the_next_attempt_answers_from_it_without_an_assumption():
    w, _cid, jobs = make(2)
    try:
        group, sent = _first_attempt(w, jobs)
        with _web(w) as (client, _cfg):
            body = _answer(client, w, group, Q.kept_value(group["kind"], sent["value"]))
        assert body["key"], body
        saved = yaml.safe_load(Path(w.cfg.applicant_path).read_text(encoding="utf-8"))["extra"]
        assert [e["value"] for e in saved.values()] == ["Python"], saved
        assert w.store.question_groups("assumed") == [] and w.store.question_groups("answered")[0]["key"] == group["key"]
        res, labels_asked = _second_attempt(w, jobs)
        rows = [x for x in w.store.answers(res.attempt_id) if x["label"] == LANG]
        assert len(rows) == 1 and rows[0]["value_json"] == "Python" and not rows[0]["assumed"], rows
        assert rows[0]["source"].startswith("memory:"), rows[0]["source"]
        assert not any(labels_asked), "the model was not asked the question again"
        assert w.store.question_groups("assumed") == [], "no new assumed card for an answered question"
    finally:
        w.close()


def test_change_saves_the_owners_value_and_the_next_attempt_uses_it():
    w, _cid, jobs = make(2)
    try:
        group, _sent = _first_attempt(w, jobs)
        with _web(w) as (client, _cfg):
            _answer(client, w, group, "Rust")
        res, labels_asked = _second_attempt(w, jobs)
        rows = [x for x in w.store.answers(res.attempt_id) if x["label"] == LANG]
        assert rows[0]["value_json"] == "Rust" and not rows[0]["assumed"] and rows[0]["source"].startswith("memory:")
        assert not any(labels_asked)
    finally:
        w.close()


def test_keep_saves_exactly_what_was_sent_even_when_it_reads_like_a_number():
    """The audit stores a text answer as written, and `assumed_answer` decodes JSON when it can:
    "3.50" must not come back as the number 3.5, nor "007" or "1e3" change."""
    for text in ("3.50", "1e3", "007", "true", "null", "12.0"):
        w, _cid, jobs = make(1)
        try:
            group, sent = _first_attempt(w, jobs, value=text)
            kept = Q.kept_value(group["kind"], sent["value"])
            assert kept == text, f"sent {text!r}, Keep would save {kept!r}"
        finally:
            w.close()


# ================================================================== oracle 9: doctor

def _doctor(*, apply_block, be, profile=None, spent=0):
    from apply_flow_support import make_world
    # D-223: released by default here; a test passes "always_available": False to see the locked doctor
    w = make_world(apply_block={"always_available": True, **apply_block}, profile=profile)
    (w.tmp / "watchlist.yaml").write_text(
        "version: 1\ncompanies:\n  - name: Acme\n    careers_url: https://acme.example/careers\n"
        "    provider: greenhouse\n    slug: acme\n", encoding="utf-8")
    if spent:
        w.store.set_setting(w.store.ALWAYS_TRIAL_USED, spent)
    out = io.StringIO()
    real = cli.backends.build
    cli.backends.build = lambda _b: be
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--config", str(w.cfg_path), "doctor"])
    finally:
        cli.backends.build = real
        w.close()
    return out.getvalue()


def test_doctor_says_which_fill_policy_applies_and_why_always_is_off():
    strict = _doctor(apply_block={}, be=backend(Net()))
    # Q-128: the doctor says the screens' label ("Stop when unsure"), not "Ask me first (strict)"
    assert "fill policy    Stop when unsure" in strict and "WARNING" not in strict, strict
    on = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()))
    assert "fill policy    Always answer" in on and "not reachable" not in on, on
    for be in (backend(Net(), url="http://ollama:11434"), backend(Net(), model="qwen3:cloud")):
        off = _doctor(apply_block={"fill_policy": "always"}, be=be)
        assert "Stop when unsure - Always answer is off for now" in off, off
        assert "WARNING: fill_policy always is ignored: the AI model isn't on this computer" in off, off
        # Q-128: the off line itself now names "Always answer" (as what is off); the policy line of a
        # running always ("fill policy    Always answer: ...") must not be there
        assert "fill policy    Always answer" not in off and "Always answer:" not in off
    for bad in ("sometimes", 7):
        logging.disable(logging.CRITICAL)
        try:
            out = _doctor(apply_block={"fill_policy": bad}, be=backend(Net()))
        finally:
            logging.disable(logging.NOTSET)
        assert "fill policy    Stop when unsure" in out, out


def test_doctor_shows_the_trial_and_warns_about_a_model_that_is_down():
    out = _doctor(apply_block={"fill_policy": "always", "always_trial_runs": 3}, be=backend(Net()), spent=1)
    assert "trial: the next 2 of 3 application(s) are filled but not sent" in out, out
    down = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net(down=False), model="missing:1b"))
    assert "WARNING: the local model is not reachable" in down, down


def test_doctor_warns_when_the_profile_has_no_work_rights_rows_or_says_yes_everywhere():
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["singapore_status"]["authorised_to_work"] = {}
    p["singapore_status"]["requires_sponsorship"] = {}
    out = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()), profile=p)
    assert "WARNING: no work-rights rows in your profile" in out, out
    q = sample_profile()
    q["singapore_status"]["authorised_to_work"] = {"default": True}
    out = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()), profile=q)
    assert "WARNING: your profile says you may work in every country" in out, out
    q["singapore_status"]["nationality"] = ["SG", "MY"]
    out = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()), profile=q)
    assert "every country" not in out, out
    ok = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()))
    assert "no work-rights rows" not in ok and "every country" not in ok, ok
