"""The `apply` verb and the `apply` job kind (WP-B8, WP-B10; Verify `-k apply_cli`). Queue Q-31.

Through `cli.main` as typed, with `apply_flow.run` replaced by a fake flow (exit codes, settings
vs config vs --dry-run, the result table) and a fake browser factory (`open-profile`). `apply show`
reads real attempt rows from a temp DB. One test runs the real CLI in a subprocess on a job whose
ATS is unsupported: no browser, no network, and the output is checked for profile values.
Nothing here touches data/, the live DB, or a real browser.
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import EMAIL, ROOT, Say, add_job, make_world  # noqa: E402

from jobscraper import apply_flow, cli  # noqa: E402
from jobscraper.apply.contracts import AttemptResult, AttemptState as S, ReasonCode as R  # noqa: E402
from jobscraper.store import Store, utcnow  # noqa: E402
from jobscraper.web import jobs as web_jobs  # noqa: E402


def run(cfg_path, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--config", str(cfg_path), *argv])
    return code, out.getvalue(), err.getvalue()


class FakeFlow:
    """Stands in for apply_flow.run: records how it was called and returns canned results."""

    def __init__(self, results=None):
        self.results = results
        self.calls: list[dict] = []

    def __call__(self, cfg, store, job_ids, *, dry_run, backend, http=None, browser_factory=None,
                 apply_cfg=None, say=print, evidence_dir=None):
        self.calls.append({"job_ids": list(job_ids), "dry_run": dry_run, "apply_cfg": apply_cfg})
        say("apply: fake flow ran")
        if self.results is not None:
            return self.results
        return [AttemptResult(i + 1, j, S.READY_TO_SUBMIT) for i, j in enumerate(job_ids)]


@contextlib.contextmanager
def fake_flow(results=None):
    flow = FakeFlow(results)
    saved = apply_flow.run
    apply_flow.run = flow
    try:
        yield flow
    finally:
        apply_flow.run = saved


def _world(**kw):
    w = make_world(**kw)
    w.close()                         # the CLI opens its own connection
    return w


# ================================================================== exit codes

def test_exit_0_when_every_attempt_ended_submitted_or_ready_to_submit():
    w = _world()
    for state in (S.READY_TO_SUBMIT, S.SUBMITTED):
        with fake_flow([AttemptResult(1, "a1", state)]) as flow:
            code, out, err = run(w.cfg_path, "apply", "a1")
        assert code == 0, (state, out, err)
    with fake_flow([AttemptResult(1, "a1", S.SUBMITTED), AttemptResult(2, "a2", S.READY_TO_SUBMIT)]):
        assert run(w.cfg_path, "apply", "a1", "a2")[0] == 0


def test_exit_1_when_any_attempt_failed_or_is_unconfirmed_or_nothing_ran():
    w = _world()
    cases = [
        [AttemptResult(1, "a1", S.FAILED, R.CAPTCHA)],
        [AttemptResult(1, "a1", S.SUBMITTED_UNCONFIRMED, reason_detail="no confirmation")],
        [AttemptResult(1, "a1", S.READY_TO_SUBMIT), AttemptResult(2, "a2", S.FAILED, R.DUPLICATE)],
        [],
    ]
    for results in cases:
        with fake_flow(results):
            code, out, err = run(w.cfg_path, "apply", "a1", "a2")
        assert code == 1, (results, out)


def test_exit_2_on_bad_job_ids_and_the_flow_is_never_started():
    w = _world()
    too_many = [f"j{i}" for i in range(21)]
    for bad in (["bad id"], ["a;b"], ["../x"], ["x" * 81], ["ok", "not ok"], too_many, ["a/b"]):
        with fake_flow() as flow:
            code, out, err = run(w.cfg_path, "apply", *bad)
        assert code == 2 and flow.calls == [], (bad[:2], code)
        assert "give 1-20 job ids" in err, err
    with fake_flow() as flow:
        code, out, err = run(w.cfg_path, "apply", "bad id")
    assert "not a job id: bad id" in err
    assert run(w.cfg_path, "apply", *[f"j{i}" for i in range(20)])[0] in (0, 1), "20 ids is the limit"


def test_exit_2_when_no_ids_at_all():
    w = _world()
    try:
        run(w.cfg_path, "apply")
    except SystemExit as exc:                    # argparse: at least one word
        assert exc.code == 2
    else:
        raise AssertionError("`apply` with nothing to apply to must exit 2")


def test_the_result_table_has_one_line_per_attempt_with_state_and_reason():
    w = _world()
    results = [AttemptResult(7, "j-ready", S.READY_TO_SUBMIT),
               AttemptResult(8, "j-fail", S.FAILED, R.UNANSWERABLE_REQUIRED, "Why us?")]
    with fake_flow(results):
        code, out, err = run(w.cfg_path, "apply", "j-ready", "j-fail")
    lines = out.splitlines()
    assert any(l.startswith("job id") and "attempt" in l and "state" in l and "reason" in l for l in lines)
    ready = next(l for l in lines if l.startswith("j-ready"))
    fail = next(l for l in lines if l.startswith("j-fail"))
    assert "7" in ready and "ready_to_submit" in ready
    assert "8" in fail and "failed" in fail and "unanswerable_required Why us?" in fail
    assert "apply: fake flow ran" in out, "the flow's own one-line-per-state log goes to stdout"


# ================================================================== settings vs config vs --dry-run

def _called_with(w, *argv):
    with fake_flow() as flow:
        run(w.cfg_path, "apply", *argv)
    assert len(flow.calls) == 1
    return flow.calls[0]


def _settings(w, **kv):
    st = Store(w.db_path)
    for k, v in kv.items():
        st.set_setting(k, v)
    st.commit()
    st.close()


def test_config_mode_decides_when_nothing_else_does_and_dry_run_is_the_default():
    w = _world()
    call = _called_with(w, "j1")
    assert call["dry_run"] is True and call["apply_cfg"].mode == "dry_run"
    w = _world(apply_block={"mode": "auto"})
    call = _called_with(w, "j1")
    assert call["dry_run"] is False and call["apply_cfg"].mode == "auto"


def test_dry_run_flag_wins_over_config_and_settings():
    w = _world(apply_block={"mode": "auto"})
    assert _called_with(w, "j1", "--dry-run")["dry_run"] is True
    _settings(w, **{"apply.mode": "auto"})
    assert _called_with(w, "j1", "--dry-run")["dry_run"] is True


def test_the_settings_table_overrides_config_and_anything_but_auto_is_a_dry_run():
    w = _world(apply_block={"mode": "dry_run"})
    _settings(w, **{"apply.mode": "auto"})
    call = _called_with(w, "j1")
    assert call["dry_run"] is False and call["apply_cfg"].mode == "auto", "Settings -> Apply wins"
    _settings(w, **{"apply.mode": "dry_run"})
    assert _called_with(w, "j1")["dry_run"] is True
    for odd in ("yes", "AUTO ", "true", ""):
        _settings(w, **{"apply.mode": odd})
        assert _called_with(w, "j1")["dry_run"] is True, f"{odd!r} must never mean auto"


def test_stored_setting_keys_override_each_config_value_and_absent_ones_fall_back():
    w = _world(apply_block={"daily_cap": 7, "per_employer_daily_cap": 3, "headed": True,
                            "captcha_wait_s": 0,
                            "mail": {"host": "imap.config.example", "port": 993, "username": "cfg-user"}})
    base = _called_with(w, "j1")["apply_cfg"]
    assert (base.daily_cap, base.per_employer_daily_cap, base.headed, base.captcha_wait_s) == (7, 3, True, 0)
    assert (base.mail.host, base.mail.port, base.mail.username) == ("imap.config.example", 993, "cfg-user")
    _settings(w, **{"apply.daily_cap": "3", "apply.headed": "false", "apply.mail.port": "143",
                    "apply.mail.username": "set-user"})
    eff = _called_with(w, "j1")["apply_cfg"]
    assert eff.daily_cap == 3 and eff.headed is False, "a stored text value is coerced to the config type"
    assert eff.per_employer_daily_cap == 3 and eff.captcha_wait_s == 0, "absent keys use config"
    assert (eff.mail.host, eff.mail.port, eff.mail.username) == ("imap.config.example", 143, "set-user")
    _settings(w, **{"apply.per_employer_daily_cap": "1", "apply.captcha_wait_s": "5",
                    "apply.mail.host": "imap.set.example"})
    eff = _called_with(w, "j1")["apply_cfg"]
    assert (eff.per_employer_daily_cap, eff.captcha_wait_s, eff.mail.host) == (1, 5, "imap.set.example")


def test_apply_config_defaults_when_the_block_is_absent():
    w = _world()
    a = w.cfg.apply
    assert (a.mode, a.daily_cap, a.per_employer_daily_cap, a.confirm_timeout_s, a.mail.wait_s) == \
        ("dry_run", 10, 2, 60, 300)


# ================================================================== apply show

def _seed_attempts(w):
    """A dry-run attempt with answers and evidence (and an older one for the same job)."""
    st = Store(w.db_path)
    cid, jid = add_job(st, title="Backend Engineer", name="Acme Corp", key="acme", slug="acme",
                       external_id="42")
    old = st.create_attempt(jid, cid, "dry_run", "2026-11-01T01:00:00")
    st.set_attempt_state(old, "planning")
    st.set_attempt_state(old, "failed", reason="captcha")
    aid = st.create_attempt(jid, cid, "dry_run", utcnow())
    for s in ("planning", "opening", "filling", "ready_to_submit"):
        st.set_attempt_state(aid, s)
    st.update_attempt(aid, ats="greenhouse", resume_file="resume.pdf", resume_source="original")
    st.add_answers(aid, [
        {"step": "application", "field_key": "first_name", "label": "First Name", "label_norm": "first name",
         "field_type": "text", "required": True, "value_json": "Alex", "tier": 1,
         "source": "field_map:first_name", "confidence": 0.99, "status": "filled"},
        {"step": "application", "field_key": "resume", "label": "Resume/CV", "label_norm": "resume cv",
         "field_type": "file", "required": True, "tier": 1, "source": "field_map:resume",
         "confidence": 0.99, "status": "filled",
         "value_json": {"file": "resume.pdf", "sha256": "ab" * 32}},
        {"step": "application", "field_key": "nric", "label": "ID number", "label_norm": "id number",
         "field_type": "text", "required": False, "value_json": None, "tier": 0, "source": "",
         "confidence": 0.0, "status": "blank_optional", "note": "no grounded answer"},
        {"step": "application", "field_key": "dob", "label": "Date of birth", "label_norm": "date of birth",
         "field_type": "text", "required": False, "value_json": "2002-03-14", "tier": 1,
         "source": "field_map:dob", "confidence": 0.9, "status": "filled", "sensitive": True},
    ])
    st.commit()
    st.close()
    folder = apply_flow.evidence_root(w.cfg) / str(aid)
    folder.mkdir(parents=True)
    (folder / "01-open.png").write_bytes(b"png")
    (folder / "failed.html").write_text("<html></html>", encoding="utf-8")
    return jid, old, aid


def test_apply_show_prints_header_every_answer_and_the_evidence():
    w = _world()
    jid, old, aid = _seed_attempts(w)
    code, out, err = run(w.cfg_path, "apply", "show", str(aid))
    assert code == 0, (out, err)
    assert f"attempt {aid}  job {jid}  Acme Corp - Backend Engineer" in out
    assert "ats greenhouse  mode dry_run  state ready_to_submit" in out
    assert "resume resume.pdf (original)" in out
    assert "[application] First Name *" in out and "= Alex" in out
    assert "tier 1  conf 0.99  field_map:first_name  filled" in out
    assert "file resume.pdf sha256 " + "ab" * 32 in out, "a file is shown as name + SHA-256"
    assert "= (blank)" in out and "note: no grounded answer" in out
    assert "= 2002-03-14" in out, "the owner's own terminal shows sensitive values too"
    assert "evidence" in out and "01-open.png" in out and "failed.html" in out
    assert str(w.tmp) in out, "evidence paths are the owner's local paths"


def test_apply_show_by_job_id_shows_the_latest_attempt():
    w = _world()
    jid, old, aid = _seed_attempts(w)
    code, out, err = run(w.cfg_path, "apply", "show", jid)
    assert code == 0 and f"attempt {aid} " in out and f"attempt {old} " not in out
    code, out, err = run(w.cfg_path, "apply", "show", str(old))
    assert code == 0 and "state failed  reason captcha" in out and "evidence: none" in out


def test_apply_show_errors_exit_1_for_unknown_and_2_for_wrong_arguments():
    w = _world()
    code, out, err = run(w.cfg_path, "apply", "show", "9999")
    assert code == 1 and "no attempt for 9999" in err
    code, out, err = run(w.cfg_path, "apply", "show", "nojob")
    assert code == 1 and "no attempt for nojob" in err
    code, out, err = run(w.cfg_path, "apply", "show")
    assert code == 2 and "give one job id or attempt id" in err
    code, out, err = run(w.cfg_path, "apply", "show", "1", "2")
    assert code == 2


# ================================================================== the apply job kind (web)

def test_the_apply_job_kind_builds_the_cli_argv_and_validates_ids():
    build = web_jobs.cli_command()
    argv = build("apply", {"job_ids": ["a1", "b:2", "c_3-x"], "dry_run": True})
    assert argv[:3] == [sys.executable, "-m", "jobscraper"]
    assert argv[3:] == ["apply", "a1", "b:2", "c_3-x", "--dry-run"]
    assert build("apply", {"job_ids": ["a1"]})[3:] == ["apply", "a1"], "no flag unless asked"
    assert build("apply", {"job_ids": ["a1"], "dry_run": False})[-1] == "a1"
    argv = web_jobs.cli_command("/tmp/some config.yaml")("apply", {"job_ids": ["a1"]})
    assert argv[3:5] == ["--config", "/tmp/some config.yaml"] and argv[5:] == ["apply", "a1"]
    assert "apply" in web_jobs.KINDS


def test_the_apply_job_kind_refuses_bad_ids_and_too_many():
    build = web_jobs.cli_command()
    bad_lists = [[], None, ["a b"], ["a;b"], ["../x"], ["x" * 81], ["ok", "$(rm)"], ["a", ""],
                 [f"j{i}" for i in range(21)]]
    for ids in bad_lists:
        try:
            build("apply", {"job_ids": ids})
        except ValueError:
            continue
        raise AssertionError(f"job_ids={ids!r} must be refused")
    try:
        build("apply", {})
    except ValueError:
        pass
    else:
        raise AssertionError("no job_ids must be refused")
    assert build("apply", {"job_ids": [f"j{i}" for i in range(20)]}), "20 is allowed"


def test_f11_the_job_kind_refuses_the_reserved_words_show_and_open_profile():
    build = web_jobs.cli_command()
    for ids in (["show"], ["show", "abc123"], ["abc123", "open-profile"], ["open-profile"]):
        try:
            build("apply", {"job_ids": ids})
        except ValueError:
            continue
        raise AssertionError(f"{ids} would run `apply show` / `open-profile` from a web job")


def test_the_real_cli_from_the_job_kind_argv_logs_lines_without_profile_values():
    """NF-09 smoke: the web job's argv runs the real CLI; stdout (= the Developer-tab log) shows
    one line per state change and none of the applicant's values. The job's ATS is unsupported,
    so no browser starts and nothing leaves the machine."""
    w = make_world()
    st = Store(w.db_path)
    _, jid = add_job(st, key="odd", name="Odd Co", provider="somethingelse", slug="odd",
                     external_id="1", url="https://careers.example.com/jobs/1")
    st.close()
    argv = web_jobs.cli_command(w.cfg_path)("apply", {"job_ids": [jid], "dry_run": True})
    done = subprocess.run(argv, capture_output=True, text=True, env=web_jobs.child_env(),
                          encoding="utf-8", errors="replace", timeout=120, cwd=str(w.tmp))
    out = done.stdout + done.stderr
    assert done.returncode == 1, out
    assert "queued job=" in out and "failed reason=unsupported_ats" in out, out
    assert "somethingelse" in out
    for v in ("alex.testcase", "Testcase", "91234567", "1 Example Road"):
        assert v not in out, f"profile value in the job log: {v}"
    st = Store(w.db_path)
    row = st.attempts_for_job(jid)[-1]
    st.close()
    assert (row["state"], row["reason_code"]) == ("failed", "unsupported_ats")


# ================================================================== apply open-profile

class _Session:
    def __init__(self, acfg, fail_goto=False):
        self.acfg = acfg
        self.fail_goto = fail_goto
        self.visited: list[str] = []
        self.holds: list[float] = []
        self.closed = False

    def new_page(self):
        sess = self

        class Page:
            def goto(self, url, **kw):
                sess.visited.append(url)
                if sess.fail_goto:
                    raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")
        return Page()

    def hold(self, seconds):
        self.holds.append(seconds)

    def close(self):
        self.closed = True


class _Factory:
    def __init__(self, exc=None, fail_goto=False):
        self.exc, self.fail_goto = exc, fail_goto
        self.sessions: list[_Session] = []

    def __call__(self, acfg):
        if self.exc is not None:
            raise self.exc
        s = _Session(acfg, self.fail_goto)
        self.sessions.append(s)
        return s


@contextlib.contextmanager
def factory_in_place(factory):
    saved = apply_flow.default_browser_factory
    apply_flow.default_browser_factory = factory
    try:
        yield factory
    finally:
        apply_flow.default_browser_factory = saved


def test_open_profile_opens_the_default_page_headed_and_holds_until_closed():
    w = _world(apply_block={"headed": False})
    with factory_in_place(_Factory()) as f:
        code, out, err = run(w.cfg_path, "apply", "open-profile")
    s = f.sessions[0]
    assert code == 0 and s.visited == ["https://my.greenhouse.io/"]
    assert s.acfg.headed is True, "headed is forced even when apply.headed is false"
    assert s.holds == [apply_flow.OPEN_PROFILE_HOLD_S] and s.closed
    assert "Edge is open on the JobScraper profile" in out


def test_open_profile_takes_a_url_and_a_failed_navigation_does_not_close_the_window():
    w = _world()
    with factory_in_place(_Factory(fail_goto=True)) as f:
        code, out, err = run(w.cfg_path, "apply", "open-profile", "https://example.com/login")
    s = f.sessions[0]
    assert code == 0 and s.visited == ["https://example.com/login"]
    assert s.holds and s.closed, "the owner still gets the window"


def test_open_profile_with_the_profile_locked_says_so_and_exits_1():
    w = _world()
    locked = RuntimeError("Failed to launch: user data directory is already in use; "
                          "ProcessSingleton")
    with factory_in_place(_Factory(exc=locked)) as f:
        code, out, err = run(w.cfg_path, "apply", "open-profile")
    assert code == 1
    assert apply_flow.PROFILE_LOCKED_TEXT in out
    assert "An apply run is using the profile; try again when it ends." in out


def test_open_profile_with_another_launch_error_names_only_the_type():
    w = _world()
    with factory_in_place(_Factory(exc=OSError("msedge.exe not found"))):
        code, out, err = run(w.cfg_path, "apply", "open-profile")
    assert code == 1 and "Edge could not start: OSError" in out and "msedge" not in out


def test_open_profile_through_the_function_with_a_factory_argument():
    say = Say()
    f = _Factory()
    acfg = _world().cfg.apply
    code = apply_flow.open_profile(acfg, "", say=say, browser_factory=f)
    assert code == 0 and f.sessions[0].visited == ["https://my.greenhouse.io/"]
    assert say.lines == [apply_flow.OPEN_PROFILE_TEXT]


def test_open_profile_rejects_two_urls_and_apply_show_still_works_after_it():
    w = _world()
    code, out, err = run(w.cfg_path, "apply", "open-profile", "https://a.example", "https://b.example")
    assert code == 2 and "at most one URL" in err
    with factory_in_place(_Factory()):
        assert run(w.cfg_path, "apply", "open-profile")[0] == 0
    assert run(w.cfg_path, "apply", "show", "9999")[0] == 1, "show still reports, not crashes"
