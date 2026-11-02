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
def _world(*, seed: bool = True):
    """(client, path, ids, fake_jobs, cfg). The applicant.yaml holds the synthetic sample profile."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        path.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8", newline="\n")
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
def test_get_lists_open_groups_ready_waiting_mode_and_busy():
    with _world() as (c, _p, ids, fake, cfg):
        r = c.get("/api/questions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert {"mode", "groups", "ready", "waiting", "busy"} <= set(body), sorted(body)
        assert body["mode"] in ("auto", "dry_run") and body["mode"] == cfg.apply.mode
        assert body["busy"] is False
        keys = {g["key"] for g in body["groups"]}
        assert keys == {"visa_status", "has_driving_licence", "work_arrangements", "favourite_language",
                        "available_from", "years_with_python", "availability.notice_period_days",
                        "solo_question"}
        visa = next(g for g in body["groups"] if g["key"] == "visa_status")
        assert len(visa["variants"]) == 2 and visa["waiting"] == 2
        assert set(visa["employers"]) == {"Shopee", "Grab"}
        assert body["ready"] == [], "every job still has an open question"
        waiting = {w["job_id"]: w for w in body["waiting"]}
        assert set(waiting) == {ids["j1"], ids["j2"], ids["j3"]}
        assert waiting[ids["j3"]]["open"] == 1 and waiting[ids["j1"]]["open"] >= 4
        fake.busy = True
        assert c.get("/api/questions").json()["busy"] is True


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

@needs(*GATE)
def test_answer_yes_no_writes_an_extra_entry_with_the_normalised_label():
    with _world() as (c, path, ids, _f, _cfg):
        et = _etag(path)
        r = _answer(c, path, key="has_driving_licence", value=True)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answered"] == [ids["licence"]] and body["etag"] != et and body["etag"] == _etag(path)
        e = _saved(path)["extra"]["has_driving_licence"]
        assert e["kind"] == "yes_no" and e["value"] is True and e["sensitive"] is False
        assert e["labels"] == ["do you hold a valid driving licence"]
        assert e["title"] == "Driving licence"
        g = _group(c, "has_driving_licence")
        assert g["status"] == "answered" and g["current"]["value"] is True
        assert "has_driving_licence" not in {x["key"] for x in c.get("/api/questions").json()["groups"]}


@needs(*GATE)
def test_answer_choice_merges_labels_picks_and_seen_across_two_variants():
    with _world() as (c, path, ids, _f, _cfg):
        r = _answer(c, path, key="visa_status",
                    picks={str(ids["visa_a"]): ["Citizen"], str(ids["visa_b"]): ["Singapore Citizen"]})
        assert r.status_code == 200, r.text
        assert sorted(r.json()["answered"]) == sorted([ids["visa_a"], ids["visa_b"]])
        e = _saved(path)["extra"]["visa_status"]
        assert e["kind"] == "choice"
        assert set(e["labels"]) == {"what is your visa status", "current work pass type"}
        assert set(e["picks"]) == {"citizen", "singapore citizen"}
        assert set(e["seen"]) == {"citizen", "pr", "others", "employment pass", "s pass", "singapore citizen"}
        assert set(e["picks"]) <= set(e["seen"])
        g = _group(c, "visa_status")
        assert set(g["current"]["picks"]) == {"citizen", "singapore citizen"}


@needs(*GATE)
def test_answer_multi_text_date_and_number_write_their_value_shapes():
    with _world() as (c, path, ids, _f, _cfg):
        assert _answer(c, path, key="work_arrangements",
                       picks={str(ids["work"]): ["Hybrid", "On site"]}).status_code == 200
        assert _answer(c, path, key="favourite_language", value="Python").status_code == 200
        assert _answer(c, path, key="available_from", value="2026-02-02").status_code == 200
        assert _answer(c, path, key="years_with_python", value=3).status_code == 200
        ex = _saved(path)["extra"]
        assert set(ex["work_arrangements"]["picks"]) == {"hybrid", "on site"}
        assert set(ex["work_arrangements"]["seen"]) == {"hybrid", "on site", "remote"}
        assert ex["favourite_language"]["value"] == "Python" and ex["favourite_language"]["kind"] == "text"
        assert ex["available_from"]["value"] == "2026-02-02" and ex["available_from"]["kind"] == "date"
        assert ex["years_with_python"]["value"] == 3 and ex["years_with_python"]["kind"] == "number"


@needs(*GATE)
def test_a_profile_gap_answer_writes_the_profile_path_not_extra():
    with _world() as (c, path, ids, _f, _cfg):
        r = _answer(c, path, key="availability.notice_period_days", value=30)
        assert r.status_code == 200, r.text
        saved = _saved(path)
        assert saved["availability"]["notice_period_days"] == 30
        assert "availability.notice_period_days" not in (saved.get("extra") or {})
        assert _group(c, "availability.notice_period_days")["status"] == "answered"
        bad = _answer(c, path, key="availability.notice_period_days", value=30,
                      picks={str(ids["notice"]): ["x"]})
        assert bad.status_code == 422, "picks are not accepted for a profile-gap group"


@needs(*GATE)
def test_an_employer_scoped_answer_goes_to_by_employer_after_the_base():
    with _world() as (c, path, ids, _f, _cfg):
        assert _answer(c, path, key="has_driving_licence", value=True).status_code == 200
        # the same group again with a narrower scope (QD 10.2 "Change answer"); only Shopee asked it
        grab = _answer(c, path, key="has_driving_licence", employer="Grab", value=False)
        assert grab.status_code == 422, "Grab never asked this question: not one of the group's employers"
        r = _answer(c, path, key="has_driving_licence", employer="Shopee", value=False)
        assert r.status_code == 200, r.text
        e = _saved(path)["extra"]["has_driving_licence"]
        assert e["value"] is True, "the base is untouched"
        assert e["by_employer"]["shopee"]["value"] is False, "keyed by the sightings' normalised employer"
        nope = _answer(c, path, key="has_driving_licence", employer="Nobody Ltd", value=False)
        assert nope.status_code == 422, "the employer must be one of the group's employers"


# ================================================================== refusals

@needs(*GATE)
def test_a_bad_option_label_is_422_and_nothing_is_saved():
    with _world() as (c, path, ids, _f, _cfg):
        before = path.read_bytes()
        r = _answer(c, path, key="visa_status", picks={str(ids["visa_a"]): ["Not an option"]})
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == "invalid" or r.json().get("errors") is not None
        assert path.read_bytes() == before
        assert _group(c, "visa_status", "open") is not None, "the question is still open"


@needs(*GATE)
def test_a_stale_etag_is_409_and_an_unknown_key_is_404_and_a_broken_file_is_409_unreadable():
    with _world() as (c, path, ids, _f, _cfg):
        stale = _etag(path)
        p = profile()
        p["identity"]["pronouns"] = "they/them"
        path.write_text(yaml.safe_dump(p, sort_keys=False), encoding="utf-8")
        elsewhere = path.read_bytes()
        r = c.post("/api/questions/answer", json={"key": "has_driving_licence", "value": True, "etag": stale})
        assert r.status_code == 409 and r.json()["detail"] == "changed", r.text
        assert path.read_bytes() == elsewhere
        assert _answer(c, path, key="no_such_key", value=True).status_code == 404
        path.write_text("identity: [unclosed\n  - : :\n", encoding="utf-8")
        broken = path.read_bytes()
        r = c.post("/api/questions/answer", json={"key": "has_driving_licence", "value": True,
                                                   "etag": _etag(path)})
        assert r.status_code == 409 and r.json()["detail"] == "unreadable", r.text
        assert path.read_bytes() == broken, "a broken file is never overwritten"


# ================================================================== dismiss and retry

@needs(*GATE)
def test_dismiss_is_204_marks_the_group_dismissed_and_leaves_the_profile_alone():
    with _world() as (c, path, ids, _f, _cfg):
        before = path.read_bytes()
        r = c.post("/api/questions/solo_question/dismiss")
        assert r.status_code == 204, r.text
        assert path.read_bytes() == before
        assert _group(c, "solo_question", "open") is None
        assert _group(c, "solo_question", "all")["status"] == "dismissed"
        body = c.get("/api/questions").json()
        assert ids["j3"] not in {x["job_id"] for x in body["ready"]}, "a dismissed question never makes a job ready"
        assert c.post("/api/questions/no_such_key/dismiss").status_code == 404


@needs(*GATE)
def test_answering_the_last_open_question_of_a_job_makes_it_ready_and_retry_takes_only_ready_jobs():
    with _world() as (c, path, ids, fake, _cfg):
        r = _answer(c, path, key="solo_question", value="Nothing")
        assert r.status_code == 200, r.text
        ready = r.json()["ready"]
        assert [x["job_id"] for x in ready] == [ids["j3"]]
        assert {"job_id", "attempt_id", "company", "title"} <= set(ready[0])
        assert ready[0]["attempt_id"] == ids["a3"] and ready[0]["company"] == "Shopee"
        assert [x["job_id"] for x in c.get("/api/questions").json()["ready"]] == [ids["j3"]]

        # a job with open questions is refused, and so is a mix
        bad = c.post("/api/questions/retry", json={"job_ids": [ids["j1"]]})
        assert bad.status_code == 422, bad.text
        assert bad.json()["detail"] == "not_ready" and bad.json()["job_ids"] == [ids["j1"]]
        mixed = c.post("/api/questions/retry", json={"job_ids": [ids["j3"], ids["j1"]]})
        assert mixed.status_code == 422 and fake.started == [], "nothing starts unless every id is ready"
        assert c.post("/api/questions/retry", json={"job_ids": [f"j{i}" for i in range(21)]}).status_code == 422

        ok = c.post("/api/questions/retry", json={"job_ids": [ids["j3"]]})
        assert ok.status_code == 202, ok.text
        assert "job" in ok.json()
        assert len(fake.started) == 1
        kind, opts = fake.started[0]
        assert kind == "apply" and opts["job_ids"] == [ids["j3"]]
        assert "dry_run" not in opts, "cmd_apply uses the effective mode (AD 14.1): the web never forces dry run"


@needs(*GATE)
def test_retry_while_a_job_runs_is_409_busy():
    with _world() as (c, path, ids, fake, _cfg):
        assert _answer(c, path, key="solo_question", value="Nothing").status_code == 200
        fake.busy = True
        r = c.post("/api/questions/retry", json={"job_ids": [ids["j3"]]})
        assert r.status_code == 409 and r.json()["detail"] == "busy", r.text
        assert fake.started == []


@needs(*GATE, "jobscraper.web.jobs:cli_command")
def test_the_apply_job_argv_carries_no_dry_run_flag_when_the_web_asks_for_the_effective_mode():
    from jobscraper.web.jobs import KINDS, cli_command
    if "apply" not in KINDS:
        return                                      # lane B's `apply` kind is not merged
    argv = cli_command()("apply", {"job_ids": ["abc"]})
    assert argv[-2:] == ["apply", "abc"] and "--dry-run" not in argv, argv


report_waiting("test_web_questions", _MARK)
