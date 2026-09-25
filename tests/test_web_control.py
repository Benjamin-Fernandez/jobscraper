"""Control from the web app (M11): settings, the profile, background jobs, and
the resume upload - the API contract in PRD section 10, M11.

Every test builds the real app over a temp config, a temp database and a temp
data directory. Background jobs run a stub command (a few lines of Python)
instead of the CLI, so nothing here touches the network or a model.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from jobscraper.config import Config  # noqa: E402
from jobscraper.store import Store  # noqa: E402
from jobscraper.web.api import create_app  # noqa: E402

ENABLED = 30
INTERESTS = ["software engineering", "trade operations"]


def _config(tmp: Path, batch_size: int = 10) -> Config:
    data = tmp / "data"
    return Config({
        "paths": {"db": str(data / "jobscraper.db"),
                  "shortlist": str(data / "shortlist.json"),
                  "profile": str(data / "profile.derived.yaml"),
                  "resume_dir": str(data)},
        "run": {"batch_size": batch_size, "cycle_days": 14},
        "judge": {"interests": INTERESTS},
        "web": {"host": "127.0.0.1", "port": 8765},
    })


@contextmanager
def _world(enabled: int = ENABLED, disabled: int = 2, **app_kw):
    """(client, cfg, data_dir) over `enabled` enabled companies in a temp DB."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg = _config(Path(tmp))
        st = Store(cfg.db_path)
        for i in range(enabled + disabled):
            st.insert_company(f"co{i}", f"Company {i}", f"https://co{i}.example",
                              enabled=i < enabled)
        st.close()
        app = create_app(cfg, **app_kw)
        with TestClient(app, base_url="http://localhost") as client:
            yield client, cfg, cfg.db_path.parent


def _stored(cfg: Config, key: str):
    st = Store(cfg.db_path)
    try:
        return st.get_setting(key)
    finally:
        st.close()


# ---------------------------------------------------------------- M11-T2

def test_web_settings_default_to_config_with_the_cadence():
    with _world() as (c, cfg, _):
        r = c.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {"batch_size": 10, "batch_size_default": 10,
                        "enabled_companies": ENABLED, "cycle_days": 14,
                        "runs_per_day_needed": 0.2}        # 30 / 10 / 14


def test_web_settings_round_trip_a_batch_size():
    with _world() as (c, cfg, _):
        r = c.put("/api/settings", json={"batch_size": 25})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["batch_size"] == 25 and body["batch_size_default"] == 10
        assert body["runs_per_day_needed"] == 0.1          # 30 / 25 / 14
        assert c.get("/api/settings").json() == body
        assert _stored(cfg, "batch_size") == "25"          # what `run` reads


def test_web_settings_accept_the_bounds():
    with _world() as (c, cfg, _):
        assert c.put("/api/settings", json={"batch_size": 1}).status_code == 200
        r = c.put("/api/settings", json={"batch_size": ENABLED})
        assert r.status_code == 200 and r.json()["batch_size"] == ENABLED


def test_web_settings_refuse_out_of_range_and_non_integers():
    with _world() as (c, cfg, _):
        for bad in (0, -1, ENABLED + 1, "12", 2.5, True, None):
            r = c.put("/api/settings", json={"batch_size": bad})
            assert r.status_code == 422, (bad, r.status_code, r.text)
        assert c.put("/api/settings", json={}).status_code == 422
        assert _stored(cfg, "batch_size") is None          # nothing was written
        assert c.get("/api/settings").json()["batch_size"] == 10


def test_web_settings_ignore_a_corrupt_stored_value():
    with _world() as (c, cfg, _):
        st = Store(cfg.db_path)
        st.set_setting("batch_size", "lots")
        st.close()
        assert c.get("/api/settings").json()["batch_size"] == 10


def test_web_profile_without_a_derived_profile_is_not_an_error():
    with _world() as (c, cfg, _):
        r = c.get("/api/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["present"] is False
    assert body["interests"] == INTERESTS                  # config, still shown
    assert set(body) == {"present", "profile_version", "source_file", "parsed_at",
                         "summary", "skills", "target_titles", "interests"}


def test_web_profile_serves_the_derived_profile():
    with _world() as (c, cfg, _):
        cfg.profile_path.write_text(yaml.safe_dump({
            "source_file": "resume.pdf", "source_hash": "sha256:ab",
            "parsed_at": "2026-09-24", "profile_version": 3,
            "summary": "Backend engineer.", "skills": ["python", "sql"],
            "target_titles": ["backend engineer"], "title_aliases": {},
            "years_experience": 1}), encoding="utf-8")
        r = c.get("/api/profile")
    assert r.status_code == 200
    assert r.json() == {"present": True, "profile_version": 3,
                        "source_file": "resume.pdf", "parsed_at": "2026-09-24",
                        "summary": "Backend engineer.", "skills": ["python", "sql"],
                        "target_titles": ["backend engineer"],
                        "interests": INTERESTS}


def test_web_profile_that_is_not_a_mapping_reads_as_absent():
    with _world() as (c, cfg, _):
        cfg.profile_path.write_text("- just\n- a list\n", encoding="utf-8")
        r = c.get("/api/profile")
        assert r.status_code == 200 and r.json()["present"] is False
        cfg.profile_path.write_text("key: [unclosed\n", encoding="utf-8")
        r = c.get("/api/profile")
        assert r.status_code == 200 and r.json()["present"] is False


# ---------------------------------------------------------------- M11-T3

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

# Stub jobs: what the child would be, minus the network and the model. Each
# echoes its kind and options so a test can see what the API asked for.
QUICK = ("import sys, os\n"
         "print('kind', sys.argv[1]); print('opts', sys.argv[2])\n"
         "print('encoding', os.environ.get('PYTHONIOENCODING'))\n"
         "print('caf\\u00e9 \\u2192 done'); print('last line')\n")
FAILS = "import sys\nprint('about to fail')\nsys.exit(3)\n"
SLOW = "import time\nprint('started', flush=True)\ntime.sleep(60)\n"


def _stub(script: str):
    def build(kind: str, opts: dict) -> list[str]:
        return [sys.executable, "-c", script, kind, json.dumps(opts, sort_keys=True)]
    return build


def _wait(c: TestClient, timeout: float = 30.0) -> dict:
    """Poll /api/jobs/current until the job is no longer running."""
    deadline = time.monotonic() + timeout
    while True:
        job = c.get("/api/jobs/current").json()
        if job["state"] != "running" or time.monotonic() > deadline:
            return job
        time.sleep(0.1)


def _record(data: Path) -> dict:
    return json.loads((data / "jobs" / "current.json").read_text(encoding="utf-8"))


JOB_KEYS = {"id", "kind", "state", "started_at", "finished_at", "exit_code", "log"}


def test_web_jobs_idle_before_anything_ran():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        r = c.get("/api/jobs/current")
    assert r.status_code == 200
    job = r.json()
    assert set(job) == JOB_KEYS
    assert job["state"] == "idle" and job["log"] == [] and job["id"] is None


def test_web_jobs_run_starts_finishes_and_keeps_its_log():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        r = c.post("/api/jobs/run")
        assert r.status_code == 202, r.text
        started = r.json()
        assert set(started) == JOB_KEYS
        assert started["kind"] == "run" and started["state"] == "running"
        assert started["started_at"] and started["finished_at"] is None
        job = _wait(c)
        assert job["id"] == started["id"]
        assert job["state"] == "succeeded" and job["exit_code"] == 0, job
        assert job["finished_at"]
        # no body: the stored-or-config batch size, not a dry run
        assert 'opts {"batch_size": 10, "dry_run": false}' in job["log"], job["log"]
        assert "encoding utf-8" in job["log"]
        assert "caf\u00e9 \u2192 done" in job["log"]                 # UTF-8 survives
        assert job["log"][-1] == "last line"
        logs = list((data / "jobs").glob("*-run.log"))
        assert len(logs) == 1 and logs[0].stem == job["id"]


def test_web_jobs_run_passes_the_requested_batch_and_dry_run():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        st = Store(cfg.db_path)
        st.set_setting("batch_size", 25)
        st.close()
        assert c.post("/api/jobs/run").status_code == 202
        assert 'opts {"batch_size": 25, "dry_run": false}' in _wait(c)["log"]
        r = c.post("/api/jobs/run", json={"batch_size": 5, "dry_run": True})
        assert r.status_code == 202, r.text
        assert 'opts {"batch_size": 5, "dry_run": true}' in _wait(c)["log"]


def test_web_jobs_run_refuses_a_bad_batch_size():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        for bad in (0, -1, ENABLED + 1, "5", 2.5):
            r = c.post("/api/jobs/run", json={"batch_size": bad})
            assert r.status_code == 422, (bad, r.status_code)
        assert c.post("/api/jobs/run", json={"dry_run": "yes"}).status_code == 422
        assert c.get("/api/jobs/current").json()["state"] == "idle"


def test_web_jobs_profile_refresh_is_a_job_too():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        r = c.post("/api/jobs/profile")
        assert r.status_code == 202 and r.json()["kind"] == "profile"
        job = _wait(c)
        assert job["state"] == "succeeded" and "kind profile" in job["log"]


def test_web_jobs_a_failing_job_reports_failed_with_its_exit_code():
    with _world(job_command=_stub(FAILS)) as (c, cfg, data):
        assert c.post("/api/jobs/run").status_code == 202
        job = _wait(c)
    assert job["state"] == "failed" and job["exit_code"] == 3
    assert "about to fail" in job["log"]


def test_web_jobs_one_at_a_time_and_cancel_terminates():
    with _world(job_command=_stub(SLOW)) as (c, cfg, data):
        assert c.post("/api/jobs/run").status_code == 202
        try:
            assert c.post("/api/jobs/run").status_code == 409
            assert c.post("/api/jobs/profile").status_code == 409
            assert c.get("/api/jobs/current").json()["state"] == "running"
            pid = _record(data)["pid"]
        finally:
            r = c.post("/api/jobs/cancel")
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["state"] == "failed" and job["finished_at"], job
        assert "cancelled" in job["log"][-1]
        assert not _alive(pid)
        # the slot is free again
        assert c.post("/api/jobs/cancel").status_code == 409
        assert c.post("/api/jobs/run").status_code == 202
        c.post("/api/jobs/cancel")


def test_web_jobs_cancel_when_idle_is_409():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        assert c.post("/api/jobs/cancel").status_code == 409


def test_web_jobs_tail_limits_the_log():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        c.post("/api/jobs/run")
        _wait(c)
        log = c.get("/api/jobs/current", params={"tail": 2}).json()["log"]
        assert log == ["caf\u00e9 \u2192 done", "last line"]
        assert c.get("/api/jobs/current", params={"tail": -1}).status_code == 422


def _alive(pid: int) -> bool:
    from jobscraper.web.jobs import pid_alive
    return pid_alive(pid)


def test_web_jobs_a_process_that_vanished_is_failed_not_running():
    """Killed from outside (Task Manager, OOM): the next request says failed."""
    with _world(job_command=_stub(SLOW)) as (c, cfg, data):
        assert c.post("/api/jobs/run").status_code == 202
        pid = _record(data)["pid"]
        _kill(pid)
        job = _wait(c, timeout=10)
    assert job["state"] == "failed", job


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        import signal
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def _write_record(data: Path, pid: int) -> None:
    (data / "jobs").mkdir(parents=True, exist_ok=True)
    (data / "jobs" / "20260925T000000Z-run.log").write_text("earlier output\n",
                                                           encoding="utf-8")
    (data / "jobs" / "current.json").write_text(json.dumps({
        "id": "20260925T000000Z-run", "kind": "run", "state": "running",
        "started_at": "2026-09-25T00:00:00", "finished_at": None,
        "exit_code": None, "pid": pid, "log": "20260925T000000Z-run.log"}),
        encoding="utf-8")


def test_web_jobs_a_recorded_job_whose_process_is_gone_reads_failed():
    """The web app restarted and the job's process is gone, exit code unknown:
    `failed`, never `running` forever - and the slot is free."""
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg = _config(Path(tmp))
        Store(cfg.db_path).close()
        _write_record(cfg.db_path.parent, done.pid)
        with TestClient(create_app(cfg, job_command=_stub(QUICK)),
                        base_url="http://localhost") as c:
            job = c.get("/api/jobs/current").json()
            assert job["state"] == "failed" and job["exit_code"] is None, job
            assert job["log"] == ["earlier output"]
            assert c.post("/api/jobs/run").status_code == 202
            _wait(c)


def test_web_jobs_a_recorded_job_still_running_holds_the_slot():
    """After a web restart, a job the old process started and that is still
    alive keeps the one-job lock. This process has no handle on it, so it will
    not kill a PID it did not start (the PID may have been reused)."""
    orphan = subprocess.Popen([sys.executable, "-c", SLOW],
                              stdout=subprocess.DEVNULL)
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg = _config(Path(tmp))
            Store(cfg.db_path).close()
            _write_record(cfg.db_path.parent, orphan.pid)
            with TestClient(create_app(cfg, job_command=_stub(QUICK)),
                            base_url="http://localhost") as c:
                assert c.get("/api/jobs/current").json()["state"] == "running"
                assert c.post("/api/jobs/run").status_code == 409
                assert c.post("/api/jobs/cancel").status_code == 409
                assert orphan.poll() is None
                orphan.kill()
                orphan.wait()
                assert _wait(c, timeout=10)["state"] == "failed"
    finally:
        if orphan.poll() is None:
            orphan.kill()


def test_web_jobs_default_command_is_the_cli_as_a_child_process():
    from jobscraper.web.jobs import child_env, cli_command
    build = cli_command(None)
    assert build("run", {"batch_size": 7, "dry_run": True}) == [
        sys.executable, "-m", "jobscraper", "run", "--batch-size", "7", "--dry-run"]
    assert build("run", {"batch_size": 7, "dry_run": False}) == [
        sys.executable, "-m", "jobscraper", "run", "--batch-size", "7"]
    assert cli_command("C:/x/config.yaml")("profile", {}) == [
        sys.executable, "-m", "jobscraper", "--config", "C:/x/config.yaml",
        "profile", "--refresh"]
    env = child_env()
    src = str(ROOT / "src")
    assert env["PYTHONPATH"].split(os.pathsep)[0] == src
    assert env["PYTHONIOENCODING"] == "utf-8" and env["PYTHONUNBUFFERED"] == "1"


def test_web_jobs_default_command_really_runs_the_cli():
    """The real child, end to end, on a verb that needs no network: `--help`."""
    from jobscraper.web.jobs import child_env
    out = subprocess.run([sys.executable, "-m", "jobscraper", "run", "--help"],
                         env=child_env(), capture_output=True, text=True,
                         cwd=tempfile.gettempdir(), timeout=60)
    assert out.returncode == 0 and "--batch-size" in out.stdout, out.stderr


# ------------------------------------------- cross-site request guard (R-9)

def test_web_refuses_a_cross_site_write():
    """A page on another site can POST a form to 127.0.0.1 with no preflight.
    Its Origin gives it away; nothing may start."""
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        evil = {"Origin": "https://attacker.example"}
        assert c.post("/api/jobs/profile", headers=evil).status_code == 403
        assert c.post("/api/jobs/run", headers={
            "Origin": "null", "Content-Type": "text/plain"}).status_code == 403
        assert c.post("/api/jobs/cancel", headers={
            "Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.put("/api/settings", json={"batch_size": 5},
                     headers=evil).status_code == 403
        assert c.get("/api/jobs/current").json()["state"] == "idle"
        # reads are unaffected, and so is the app's own origin (any port: the
        # Vite dev server proxies from :5173)
        assert c.get("/api/settings", headers=evil).status_code == 200
        r = c.post("/api/jobs/run", headers={"Origin": "http://localhost:5173",
                                             "Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 202, r.text
        _wait(c)


# ---------------------------------------------------------------- M11-T4

import hashlib  # noqa: E402
import io  # noqa: E402
import zipfile  # noqa: E402

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MB = 1024 * 1024


def _pdf(size: int = 2048) -> bytes:
    head = b"%PDF-1.7\n% resume\n"
    return head + b"x" * max(0, size - len(head))


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document>Jane Doe</w:document>")
    return buf.getvalue()


def _files(d: Path) -> set[str]:
    """What is in the resume directory, ignoring the database's own files."""
    return {p.name for p in d.iterdir()
            if p.is_file() and not p.name.startswith("jobscraper.db")}


def _put(c: TestClient, body, content_type: str | None = PDF, **headers):
    if content_type is not None:
        headers["Content-Type"] = content_type
    return c.put("/api/resume", content=body, headers=headers)


def test_resume_upload_saves_a_pdf_and_hashes_it():
    body = _pdf()
    with _world() as (c, cfg, data):
        r = _put(c, body)
        assert r.status_code == 200, r.text
        assert r.json() == {"saved": "resume.pdf", "bytes": len(body),
                            "sha256": hashlib.sha256(body).hexdigest()}
        assert (cfg.resume_dir / "resume.pdf").read_bytes() == body
        assert _files(data) == {"resume.pdf"}          # no temp file left behind


def test_resume_upload_accepts_media_type_parameters_and_case():
    with _world() as (c, cfg, data):
        assert _put(c, _pdf(), "Application/PDF; charset=binary").status_code == 200


def test_resume_upload_keeps_exactly_one_resume():
    with _world() as (c, cfg, data):
        assert _put(c, _pdf()).status_code == 200
        r = _put(c, _docx(), DOCX)
        assert r.status_code == 200 and r.json()["saved"] == "resume.docx", r.text
        assert _files(data) == {"resume.docx"}
        assert _put(c, _pdf()).status_code == 200
        assert _files(data) == {"resume.pdf"}


def test_resume_upload_over_5_mb_is_413_and_writes_nothing():
    with _world() as (c, cfg, data):
        assert _put(c, _pdf(6 * MB)).status_code == 413
        assert _put(c, _pdf(5 * MB + 1)).status_code == 413
        assert _files(data) == set()
        assert _put(c, _pdf(5 * MB)).status_code == 200    # the cap itself is fine


def test_resume_upload_counts_the_bytes_not_just_the_header():
    """A chunked body has no Content-Length to check; the cap still holds."""
    def chunks():
        yield b"%PDF-1.7\n"
        for _ in range(7):
            yield b"x" * MB

    with _world() as (c, cfg, data):
        r = _put(c, chunks())
        assert r.status_code == 413
        assert _files(data) == set()


def test_resume_upload_refuses_a_file_that_is_not_what_it_claims():
    with _world() as (c, cfg, data):
        assert _put(c, b"just some text, not a pdf").status_code == 415
        assert _put(c, _docx(), PDF).status_code == 415          # zip labelled pdf
        assert _put(c, _pdf(), DOCX).status_code == 415          # pdf labelled docx
        assert _put(c, b"PK\x03\x04 not a zip", DOCX).status_code == 415
        other_zip = io.BytesIO()
        with zipfile.ZipFile(other_zip, "w") as z:
            z.writestr("xl/workbook.xml", "<workbook/>")          # a spreadsheet
        assert _put(c, other_zip.getvalue(), DOCX).status_code == 415
        assert _put(c, b"").status_code == 415
        assert _files(data) == set()


def test_resume_upload_refuses_forms_and_other_types():
    """A cross-site page can send these three with no CORS preflight; the
    raw-body, non-form content type is the CSRF guard (PRD M11)."""
    with _world() as (c, cfg, data):
        r = c.put("/api/resume", files={"file": ("resume.pdf", _pdf(), PDF)})
        assert r.status_code == 415                               # multipart/form-data
        assert _put(c, b"a=b", "application/x-www-form-urlencoded").status_code == 415
        assert _put(c, _pdf(), "text/plain").status_code == 415
        assert _put(c, _pdf(), None).status_code == 415           # no content type
        assert _put(c, _pdf(), "application/octet-stream").status_code == 415
        assert c.post("/api/resume", content=_pdf(),
                      headers={"Content-Type": PDF}).status_code == 405
        assert _files(data) == set()


def test_resume_upload_rejected_keeps_the_existing_resume():
    with _world() as (c, cfg, data):
        good = _pdf()
        assert _put(c, good).status_code == 200
        assert _put(c, b"not a pdf").status_code == 415
        assert _put(c, _pdf(6 * MB)).status_code == 413
        assert (cfg.resume_dir / "resume.pdf").read_bytes() == good
        assert _files(data) == {"resume.pdf"}


def test_resume_upload_a_failed_write_leaves_no_partial_file():
    """If the final rename fails, the old resume stands and no temp file remains."""
    from jobscraper.web.routers import resume as resume_router
    with _world() as (c, cfg, data):
        good = _pdf()
        assert _put(c, good).status_code == 200
        real = resume_router.os.replace

        def broken(src, dst):
            raise OSError("disk full")

        resume_router.os.replace = broken
        try:
            r = _put(c, _pdf(4096))
        finally:
            resume_router.os.replace = real
        assert r.status_code == 500
        assert (cfg.resume_dir / "resume.pdf").read_bytes() == good
        assert _files(data) == {"resume.pdf"}


def test_web_pages_cannot_be_framed_by_another_site():
    """Security review (M11-T4): the UI now has buttons that start runs and
    upload files, so a foreign page must not be able to frame it and trick a
    click (clickjacking) - those requests would be same-origin."""
    with _world() as (c, cfg, data):
        for path in ("/", "/api/settings"):
            r = c.get(path)
            assert r.headers["x-frame-options"] == "DENY", path
            assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
            assert r.headers["x-content-type-options"] == "nosniff"


def test_web_jobs_old_logs_are_pruned():
    with _world(job_command=_stub(QUICK)) as (c, cfg, data):
        jobs_dir = data / "jobs"
        jobs_dir.mkdir()
        for i in range(5):
            (jobs_dir / f"2026010{i}T000000Z-run.log").write_text("old\n",
                                                                  encoding="utf-8")
        c.app.state.jobs.keep_logs = 3
        assert c.post("/api/jobs/run").status_code == 202
        job = _wait(c)
        logs = sorted(p.name for p in jobs_dir.glob("*.log"))
        assert len(logs) == 3 and f"{job['id']}.log" in logs, logs
        assert "20260104T000000Z-run.log" in logs          # the newest old ones stay


def test_web_jobs_a_start_failure_does_not_leak_paths():
    def missing(kind, opts):
        return [str(ROOT / "no-such-dir" / "no-such-python.exe")]

    with _world(job_command=missing) as (c, cfg, data):
        r = c.post("/api/jobs/run")
        assert r.status_code == 500
        assert "no-such-dir" not in r.text, r.text
        assert c.get("/api/jobs/current").json()["state"] == "failed"
        assert c.post("/api/jobs/cancel").status_code == 409


def test_resume_upload_refuses_a_cross_site_put():
    with _world() as (c, cfg, data):
        r = _put(c, _pdf(), Origin="https://attacker.example")
        assert r.status_code == 403
        assert _files(data) == set()
