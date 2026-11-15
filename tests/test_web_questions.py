"""WP-Q0 oracles for `/api/questions` (questions_design.md 9.2, 6.1, 7.1; WP-Q3): the list, the answer
algorithm for every kind, employer scope, profile-gap answers, dismiss, retry.

Skip-clean until `jobscraper.web.routers.questions`, the Q-block store methods and lane B's attempts
exist (the questions hang off failed attempts). Every test builds the real app over a temp config, a temp
database and a temp applicant.yaml; the JobManager is a FAKE that records `start(kind, opts)` and can
report busy, so no child process ever starts (no network, never data/ or port 8765).

ASSUMED beyond the design:
  * `employer` in the answer body is a company name from the group's `employers` list; the write key is the
    sightings' `employer_norm` (QD 9.2 step 3). A scoped answer is made after the base answer (a new choice
    entry with only an override would have an empty base `picks`, which QD 6.1 forbids).
  * Retry (QD 9.2): `jobs.start("apply", {"job_ids": [...]})`: no `dry_run` key in opts.
  * `answered` in the 200 body is the list of question ids written; `ready` is the post-answer ready list.
  * A `picks` body for a profile-gap group is refused with 422 (QD 9.2 step 2).
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    NOW, failed_attempt, make_job, needs, profile, question_row, report_waiting, seed_question, waiting_mark,
)

_MARK = waiting_mark()
GATE = ("jobscraper.web.routers.questions", "jobscraper.store:Store.question_groups",
        "jobscraper.store:Store.create_attempt", "jobscraper.applicant:etag")

VISA_A = ("What is your visa status?", ("Citizen", "PR", "Others"))
VISA_B = ("Current work pass type", ("Employment Pass", "S Pass", "Singapore Citizen"))


class FakeJobs:
    """Records `start`; `busy` makes it refuse like the real JobManager (JobBusy)."""

    def __init__(self):
        self.started: list[tuple[str, dict]] = []
        self.busy = False

    def current(self, tail: int = 200) -> dict:
        from jobscraper.web.jobs import IDLE
        return dict(IDLE, log=[]) if not self.busy else dict(IDLE, state="running", kind="apply", log=[])

    def _running(self) -> bool:
        return self.busy

    def start(self, kind: str, opts: dict, tail: int = 200) -> dict:
        from jobscraper.web.jobs import JobBusy
        if self.busy:
            raise JobBusy("a job is already running")
        self.started.append((kind, dict(opts)))
        return {"id": "fake-1", "kind": kind, "state": "running", "log": []}


def _seed(st) -> dict:
    """Companies, jobs, failed attempts and open questions. Returns the ids the tests need."""
    ids: dict = {}
    c_shopee = st.insert_company("shopee", "Shopee", "https://shopee.example")
    c_grab = st.insert_company("grab", "Grab", "https://grab.example")
    j1, j2, j3 = make_job(st, c_shopee, 1), make_job(st, c_grab, 2), make_job(st, c_shopee, 3)
    a1, a2, a3 = (failed_attempt(st, j, c) for j, c in ((j1, c_shopee), (j2, c_grab), (j3, c_shopee)))
    ids.update(j1=j1, j2=j2, j3=j3, a1=a1, a2=a2, a3=a3, c_shopee=c_shopee, c_grab=c_grab)

    def q(attempt, job, cid, emp, **kw):
        return seed_question(st, attempt_id=attempt, job_id=job, company_id=cid, employer_norm=emp, **kw)

    ids["visa_a"] = q(a1, j1, c_shopee, "shopee", key="visa_status", title="Visa status", kind="choice",
                      label=VISA_A[0], options=VISA_A[1])
    ids["visa_b"] = q(a2, j2, c_grab, "grab", key="visa_status", title="Visa status", kind="choice",
                      label=VISA_B[0], options=VISA_B[1], field_key="q2")
    ids["licence"] = q(a1, j1, c_shopee, "shopee", key="has_driving_licence", title="Driving licence",
                       kind="yes_no", label="Do you hold a valid driving licence?", options=("Yes", "No"),
                       field_key="q3")
    ids["work"] = q(a1, j1, c_shopee, "shopee", key="work_arrangements", title="Work arrangements",
                    kind="multi", label="Which work arrangements suit you?",
                    options=("Hybrid", "On site", "Remote"), field_key="q4")
    ids["lang"] = q(a2, j2, c_grab, "grab", key="favourite_language", title="Favourite language", kind="text",
                    label="What is your favourite programming language?", field_key="q5")
    ids["start"] = q(a2, j2, c_grab, "grab", key="available_from", title="Available from", kind="date",
                     label="When can you start?", field_key="q6")
    ids["years"] = q(a2, j2, c_grab, "grab", key="years_with_python", title="Years with Python", kind="number",
                     label="How many years of Python experience do you have?", field_key="q7")
    ids["notice"] = q(a1, j1, c_shopee, "shopee", key="availability.notice_period_days",
                      target_path="availability.notice_period_days", named_by="profile", reason="profile_gap",
                      title="Notice period, in days", kind="number", label="Notice period",
                      field_key="q8")
    ids["solo"] = q(a3, j3, c_shopee, "shopee", key="solo_question", title="Solo", kind="text",
                    label="Anything the team should know?", field_key="q9")
    st.commit()
    return ids


@contextmanager
def _world(*, seed: bool = True, resume: bool = False):
    """(client, path, ids, fake_jobs, cfg). The applicant.yaml holds the synthetic sample profile.
    `resume=True` adds a dummy resume.pdf: retry goes through the enqueue helper (Q-120), which
    checks the profile is complete first (422 `profile_incomplete` otherwise)."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        path.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8", newline="\n")
        if resume:
            (data / "resume.pdf").write_bytes(b"%PDF-1.4 dummy resume for the retry pins")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765}})
        st = Store(cfg.db_path)
        ids = _seed(st) if seed else {}
        st.close()
        app = create_app(cfg)
        fake = FakeJobs()
        app.state.jobs = fake
        with TestClient(app, base_url="http://localhost") as client:
            yield client, path, ids, fake, cfg


def _etag(path) -> str:
    import jobscraper.applicant as A
    return A.etag(path)


def _saved(path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _answer(c, path, **body):
    body.setdefault("etag", _etag(path))
    return c.post("/api/questions/answer", json=body)


def _group(c, key, status="all"):
    got = {g["key"]: g for g in c.get(f"/api/questions?status={status}").json()["groups"]}
    return got.get(key)


# ================================================================== harness (run now)

def test_the_harness_fake_job_manager_records_and_refuses_when_busy():
    f = FakeJobs()
    assert f.current()["state"] == "idle"
    assert f.start("apply", {"job_ids": ["a"]})["kind"] == "apply" and f.started == [("apply", {"job_ids": ["a"]})]
    f.busy = True
    assert f.current()["state"] == "running"
    try:
        f.start("apply", {"job_ids": ["a"]})
    except Exception as e:
        assert type(e).__name__ == "JobBusy"
    else:
        raise AssertionError("busy must refuse")


# ================================================================== GET


@needs(*GATE)
def test_get_mode_follows_the_apply_mode_setting():
    from jobscraper.store import Store
    with _world() as (c, _p, _ids, _fake, cfg):
        st = Store(cfg.db_path)
        st.set_setting("apply.mode", "auto")
        st.commit()
        st.close()
        assert c.get("/api/questions").json()["mode"] == "auto"


# ================================================================== answers, one per kind (QD 6.1 shapes)


# ================================================================== refusals


# ================================================================== dismiss and retry


@needs(*GATE, "jobscraper.web.jobs:cli_command")
def test_the_apply_job_argv_carries_no_dry_run_flag_when_the_web_asks_for_the_effective_mode():
    from jobscraper.web.jobs import KINDS, cli_command
    if "apply" not in KINDS:
        return                                      # lane B's `apply` kind is not merged
    argv = cli_command()("apply", {"job_ids": ["abc"]})
    assert argv[-2:] == ["apply", "abc"] and "--dry-run" not in argv, argv


report_waiting("test_web_questions", _MARK)
