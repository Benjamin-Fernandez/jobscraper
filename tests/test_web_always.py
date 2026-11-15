"""Q-121 WP-W1 pins: the web API of the always-answer filler (llm_first_fill_design 6.3, 7.2).

This is the owner's only view of what the local model ASSUMED on a submitted application and the
only place to correct it, so the pins are exact:

  A. "Answered for you": `GET /api/questions?status=assumed` (item shape, `counts`), Keep and
     Change (the value lands under the question's OWN key, exactly as sent; an invalid or refused
     request saves NOTHING; 404 / 409 `dismissed` / `not_assumed` / `changed`; a foreign Origin 403);
  B. Settings: `fill_policy` and `always_trial_runs` round-trip, bad values 422 and save nothing,
     the effective policy and the plain reason when `always` is configured but not in force,
     `GET /api/apply/status` `fill{}`;
  C. attempt rows carry `assumed` / `assumed_text`; the `owner_fact_missing` and
     `document_missing` texts;
  D. AGREEMENT: web/ holds COPIES of `apply.questions.kept_value` and of
     `apply_flow.effective_policy` (the layering rule keeps it from importing them). The copies
     must return what the originals return.

Real app over a temp config, temp DB and temp applicant.yaml; the job manager is a FAKE (no job, no
browser, no network, no port, nothing from data/). Dummy employer only. Never starts an apply job.
"""
from __future__ import annotations

import contextlib
import copy
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import profile  # noqa: E402
from questions_support import NOW, make_job, seed_question  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper import store as store_mod  # noqa: E402

EVIL = {"Origin": "https://evil.example"}
ITEM_KEYS = {"question_id", "label", "kind", "options", "sensitive", "employer", "company", "role",
             "job_id", "attempt_id", "value", "answer", "reason", "source", "basis", "text", "can_keep"}
ENV_KEYS = ("JOBSCRAPER_BACKEND", "JOBSCRAPER_OLLAMA_URL")


class _FakeJobs:
    """Records `start`; never runs anything."""

    def __init__(self):
        self.started: list[tuple[str, dict]] = []

    def current(self, tail: int = 200) -> dict:
        from jobscraper.web.jobs import IDLE
        return dict(IDLE, log=[])

    def start(self, kind: str, opts: dict, tail: int = 200) -> dict:
        self.started.append((kind, dict(opts)))
        return {"id": "fake-1", "kind": kind, "state": "running", "log": []}


# What is seeded: (name, question key, kind, label, options, what JobScraper sent, sensitive, reason)
SEEDS = [
    ("licence", "has_driving_licence", "yes_no", "Do you hold a valid driving licence?",
     ("Yes", "No"), "Yes", False, "the form asked and your profile is silent"),
    ("visa", "visa_status", "choice", "What is your visa status?",
     ("Citizen", "PR", "Others"), "PR", False, "your profile says you live here"),
    ("badpass", "work_pass", "choice", "Current work pass type",
     ("Employment Pass", "S Pass"), "Dependant Pass", False, "a guess"),
    ("lang", "favourite_language", "text", "What is your favourite programming language?",
     (), "Python", False, "your resume is mostly Python"),
    ("work", "work_arrangements", "multi", "Which work arrangements suit you?",
     ("Hybrid", "On site", "Remote"), ["Hybrid", "Remote"], False, "typical for the role"),
    ("years", "years_with_python", "number", "How many years of Python experience do you have?",
     (), 3, False, "counted from your resume"),
    ("salary", "salary_note", "text", "Anything to add about pay?",
     (), "5000", True, "model quote redacted (private field)"),
]


def _answer_row(field_key, label, kind, value, reason, source="assumption", status="filled",
                assumed=True):
    # the question KIND "multi" is a FieldType `multi_choice` in apply_answers; the store decodes a
    # list only for the real field types (Store._JSON_FIELD_TYPES), so "multi" would read back as text
    field_type = {"multi": "multi_choice"}.get(kind, kind)
    return {"step": "s1", "field_key": field_key, "label": label, "label_norm": label.lower(),
            "field_type": field_type, "required": True, "tier": 3, "source": source, "confidence": 0.5,
            "status": status, "value_json": value, "evidence": reason, "assumed": assumed}


@contextlib.contextmanager
def _world(*, budget=None, apply_block=None, seed=True):
    """Yield (client, cfg, ids, fake_jobs). `ids` maps the seed names to question ids and holds
    `job`, `cid`, `attempt`. The model-location environment is cleared for the run."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            path = data / "applicant.yaml"
            path.write_text(yaml.safe_dump(profile(), sort_keys=False), encoding="utf-8", newline="\n")
            (data / "resume.pdf").write_bytes(b"%PDF-1.4 dummy resume for the Q-121 web pins")
            raw = {"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                             "shortlist": str(data / "shortlist.json"),
                             "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                   "web": {"host": "127.0.0.1", "port": 8765},
                   "apply": {"mode": "dry_run", "always_available": True,   # D-223: released here; tests/test_always_lock.py pins the lock
                             **(apply_block or {})}}
            if budget is not None:
                raw["budget"] = budget
            cfg = Config(raw)
            st = Store(cfg.db_path)
            cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
            job = make_job(st, cid, 1)
            aid = st.create_attempt(job, cid, "dry_run", NOW)
            for s in ("planning", "opening", "filling", "ready_to_submit"):
                st.set_attempt_state(aid, s)
            ids = {"job": job, "cid": cid, "attempt": aid}
            if seed:
                rows = []
                for i, (name, key, kind, label, options, sent, sens, reason) in enumerate(SEEDS):
                    fk = f"q{i}"
                    ids[name] = seed_question(
                        st, attempt_id=aid, job_id=job, company_id=cid, employer_norm="exampleco",
                        field_key=fk, key=key, kind=kind, label=label, options=options,
                        sensitive=sens, reason="assumed")
                    rows.append(_answer_row(fk, label, kind, sent, reason))
                # a profile-gap question the model answered (Keep writes the profile path)
                ids["notice"] = seed_question(
                    st, attempt_id=aid, job_id=job, company_id=cid, employer_norm="exampleco",
                    field_key="q20", key="availability.notice_period_days",
                    target_path="availability.notice_period_days", named_by="profile",
                    kind="number", label="Notice period in days", reason="assumed")
                rows.append(_answer_row("q20", "Notice period in days", "number", 30, "a month is usual"))
                # a question asked under its own context: saved per employer
                ids["scoped"] = seed_question(
                    st, attempt_id=aid, job_id=job, company_id=cid, employer_norm="exampleco",
                    field_key="q21", key="grad_programme", kind="text",
                    label="Graduate programme | Example Co", label_norm="graduate programme | example co",
                    reason="assumed")
                rows.append(_answer_row("q21", "Graduate programme | Example Co", "text",
                                        "Engineering", "the role title says engineering"))
                # a still-open question and a dismissed one: neither may be kept or changed
                ids["open"] = seed_question(
                    st, attempt_id=aid, job_id=job, company_id=cid, employer_norm="exampleco",
                    field_key="q30", key="open_question", kind="text", label="Open question?",
                    reason="no_rule")
                ids["dismissed"] = seed_question(
                    st, attempt_id=aid, job_id=job, company_id=cid, employer_norm="exampleco",
                    field_key="q31", key="put_aside", kind="text", label="Put aside?", reason="assumed")
                st.add_answers(aid, rows + [_answer_row("q31", "Put aside?", "text", "x", "r")])
                st.set_questions_status("put_aside", "dismissed", NOW)
            st.commit()
            st.close()
            app = create_app(cfg)
            fake = _FakeJobs()
            app.state.jobs = fake
            with TestClient(app, base_url="http://localhost") as client:
                yield client, cfg, ids, fake
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _extra(cfg):
    p = applicant.load(cfg.applicant_path)
    return p.get("extra") or {}


def _file(cfg):
    return Path(cfg.applicant_path).read_bytes()


def _assumed(client):
    return client.get("/api/questions", params={"status": "assumed"}).json()


def _item(client, qid):
    for g in _assumed(client)["groups"]:
        for it in g.get("assumed", []):
            if it["question_id"] == qid:
                return it
    return None


def _status_of(cfg, qid):
    st = store_mod.Store(cfg.db_path)
    try:
        return next(r["status"] for r in st.question_rows() if int(r["id"]) == qid)
    finally:
        st.close()


# ------------------------------------------------------------------ A. "Answered for you"


def test_a_foreign_origin_cannot_keep_change_or_switch_the_policy():
    with _world() as (client, cfg, ids, fake):
        was = _file(cfg)
        r = client.post(f"/api/questions/{ids['lang']}/keep", headers=EVIL)
        assert r.status_code == 403, r.text
        r = client.post(f"/api/questions/{ids['lang']}/change", headers=EVIL, json={"value": "x"})
        assert r.status_code == 403
        r = client.put("/api/apply/settings", headers=EVIL, json={"fill_policy": "always"})
        assert r.status_code == 403
        r = client.post(f"/api/questions/{ids['lang']}/keep", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403
        assert _file(cfg) == was and _status_of(cfg, ids["lang"]) == "assumed"
        assert client.get("/api/apply/settings").json()["fill_policy"] == "strict"
        assert fake.started == []


# ------------------------------------------------------------------ B. Settings: how forms are answered


def test_policy_and_trial_round_trip_and_defaults_stay_as_config_has_them():
    with _world() as (client, _cfg, _ids, fake):
        r = client.put("/api/apply/settings", json={"fill_policy": "always", "always_trial_runs": 3})
        assert r.status_code == 200, r.text
        for body in (r.json(), client.get("/api/apply/settings").json()):
            assert body["fill_policy"] == "always" and body["always_trial_runs"] == 3
            assert body["fill_policy_effective"] == "always" and body["fill_policy_inactive"] is None
            assert body["always_trial_text"] == "Next 3 not sent"
            assert body["always_trial_used"] == 0 and body["always_trial_left"] == 3
            assert body["defaults"]["fill_policy"] == "strict" and body["defaults"]["always_trial_runs"] == 0
        assert client.put("/api/apply/settings", json={"fill_policy": "strict"}).json()["fill_policy"] == "strict"
        for ok in (0, 20):                                          # the boundaries
            assert client.put("/api/apply/settings", json={"always_trial_runs": ok}).status_code == 200
            assert client.get("/api/apply/settings").json()["always_trial_runs"] == ok
        assert client.get("/api/apply/settings").json()["always_trial_text"] == "Next 20 not sent"
        assert fake.started == []                                   # saving a setting starts nothing


def test_a_bad_policy_or_trial_value_is_422_naming_the_field_and_saves_nothing():
    with _world() as (client, _cfg, _ids, _f):
        client.put("/api/apply/settings", json={"fill_policy": "always", "always_trial_runs": 5,
                                                 "daily_cap": 7})
        before = client.get("/api/apply/settings").json()
        bad = [("always_trial_runs", v) for v in (21, -1, "3", 3.5, None, True, [3], 2 ** 40)] \
            + [("fill_policy", v) for v in ("ALWAYS", "Always", "", None, 3, True, ["always"], "ask")]
        for field, value in bad:
            r = client.put("/api/apply/settings", json={field: value})
            assert r.status_code == 422, (field, value, r.status_code)
            body = r.json()
            assert body["detail"] == "invalid" and [e["field"] for e in body["errors"]] == [field], (field, value)
            assert body["errors"][0]["message"], (field, value)
            assert client.get("/api/apply/settings").json() == before, (field, value)
        # all-or-nothing: a good value sent with a bad one is not saved either
        r = client.put("/api/apply/settings", json={"daily_cap": 99, "fill_policy": "bogus"})
        assert r.status_code == 422 and client.get("/api/apply/settings").json() == before
        assert client.put("/api/apply/settings", json={"always_trial_runs": 21, "fill_policy": "strict"}
                          ).status_code == 422
        assert client.get("/api/apply/settings").json() == before


def test_always_that_is_configured_but_not_in_force_says_why_in_plain_words():
    cases = [
        ("a model on another host", {"ollama_url": "http://ollama.example:11434"}, {"fill": "llm"},
         "isn't on this computer"),
        ("an Ollama cloud tag", {"ollama_model": "qwen3:cloud"}, {"fill": "llm"}, "isn't on this computer"),
        ("a -cloud tag", {"ollama_model": "gpt-oss:120b-cloud"}, {"fill": "llm"}, "isn't on this computer"),
        ("the model switched off", {"enable_llm": False}, {"fill": "llm"}, "isn't on this computer"),
        ("fill: rules", {}, {"fill": "rules"}, "switched off in the configuration"),
    ]
    for label, budget, apply_block, words in cases:
        with _world(budget=budget, apply_block={**apply_block, "fill_policy": "always"}) as (client, _c, _i, _f):
            for body in (client.get("/api/apply/settings").json(),
                         client.get("/api/apply/status").json()["fill"]):
                assert body["fill_policy_effective"] == "strict", label
                assert words in body["fill_policy_inactive"], (label, body["fill_policy_inactive"])
                assert body["fill_policy_inactive"].startswith("Always answer is off for now"), label
            # the configured value is still shown as chosen; only the effective one differs
            assert client.get("/api/apply/settings").json()["fill_policy"] == "always", label
    # a local model, the LLM filler, strict: nothing to explain
    with _world(budget={}, apply_block={"fill": "llm", "fill_policy": "strict"}) as (client, _c, _i, _f):
        body = client.get("/api/apply/settings").json()
        assert body["fill_policy_effective"] == "strict" and body["fill_policy_inactive"] is None


def test_the_status_block_reports_the_policy_in_force_and_the_trial_that_is_left():
    with _world(apply_block={"fill_policy": "always", "always_trial_runs": 3}) as (client, cfg, _i, _f):
        fill = client.get("/api/apply/status").json()["fill"]
        assert fill == {"fill_policy_effective": "always", "fill_policy_inactive": None,
                        "always_trial_runs": 3, "always_trial_left": 3}
        text = {}
        for used in (1, 3, 9):
            st = store_mod.Store(cfg.db_path)
            st.set_setting("apply.always_trial_used", used)
            st.close()
            body = client.get("/api/apply/settings").json()
            text[used] = (body["always_trial_text"], body["always_trial_left"], body["always_trial_used"])
        assert text == {1: ("Next 3 not sent (2 left)", 2, 1), 3: ("Next 3 not sent (done)", 0, 3),
                        9: ("Next 3 not sent (done)", 0, 9)}
    with _world() as (client, _c, _i, _f):                          # nothing set: strict, no trial
        assert client.get("/api/apply/status").json()["fill"] == {
            "fill_policy_effective": "strict", "fill_policy_inactive": None,
            "always_trial_runs": 0, "always_trial_left": 0}
        assert client.get("/api/apply/settings").json()["always_trial_text"] == "Off"


# ------------------------------------------------------------------ C. attempt rows and reason texts


def _finished_attempt(st, job, cid, *, assumed_filled=0, assumed_skipped=0, plain=0, state="ready"):
    aid = st.create_attempt(job, cid, "dry_run", NOW)
    for s in ("planning", "opening", "filling"):
        st.set_attempt_state(aid, s)
    rows = [_answer_row(f"a{i}", f"Field a{i}", "text", "v", "r") for i in range(assumed_filled)]
    rows += [_answer_row(f"s{i}", f"Field s{i}", "text", "v", "r", status="skipped")
             for i in range(assumed_skipped)]
    rows += [_answer_row(f"p{i}", f"Field p{i}", "text", "v", "r", source="profile:x", assumed=False)
             for i in range(plain)]
    st.add_answers(aid, rows)
    if state == "ready":
        st.set_attempt_state(aid, "ready_to_submit")
    return aid


def test_attempt_rows_carry_how_many_answers_were_assumed():
    with _world(seed=False) as (client, cfg, ids, _f):
        st = store_mod.Store(cfg.db_path)
        cid = ids["cid"]
        j1, j2, j3 = ids["job"], make_job(st, cid, 2), make_job(st, cid, 3)
        _finished_attempt(st, j1, cid, assumed_filled=3, assumed_skipped=2, plain=4)
        _finished_attempt(st, j2, cid, assumed_filled=1)
        _finished_attempt(st, j3, cid, plain=2)
        for j in (j1, j2, j3):
            st.set_application_status(j, "to_apply")
        st.commit()
        st.close()
        rows = {r["job_id"]: r["last_attempt"] for r in client.get("/api/applications").json()}
        assert (rows[j1]["assumed"], rows[j1]["assumed_text"]) == (3, "3 answers assumed")   # skipped rows do not count
        assert (rows[j2]["assumed"], rows[j2]["assumed_text"]) == (1, "1 answer assumed")
        assert (rows[j3]["assumed"], rows[j3]["assumed_text"]) == (0, "")
        listed = client.get(f"/api/applications/{j1}/attempts").json()
        assert [(a["assumed"], a["assumed_text"]) for a in listed][0] == (3, "3 answers assumed")
        # an attempt row keeps every earlier key (additive only)
        assert {"id", "mode", "state", "kind", "reason_code", "text", "hint", "queued_at",
                "finished_at", "submit_clicked_at", "resume_source"} <= set(rows[j1])


def test_the_queues_recent_list_carries_the_assumed_count_for_the_runs_panel():
    with _world(seed=False) as (client, cfg, ids, _f):
        st = store_mod.Store(cfg.db_path)
        _finished_attempt(st, make_job(st, ids["cid"], 2), ids["cid"], assumed_filled=2, plain=1)
        st.commit()
        st.close()
        recent = client.get("/api/apply/queue").json()["recent"]
        by = {r["attempt_id"]: r for r in recent}
        assert by[2]["assumed"] == 2 and by[2]["assumed_text"] == "2 answers assumed", recent
        assert by[1]["assumed"] == 0 and by[1]["assumed_text"] == "", recent


def test_owner_fact_missing_waits_for_the_owner_and_document_missing_stops_with_their_texts():
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode
    with _world(seed=False) as (client, cfg, ids, _f):
        st = store_mod.Store(cfg.db_path)
        cid = ids["cid"]
        j1, j2 = make_job(st, cid, 2), make_job(st, cid, 3)
        for job, code, detail in ((j1, ReasonCode.OWNER_FACT_MISSING, "date of birth"),
                                  (j2, ReasonCode.DOCUMENT_MISSING, "photo")):
            aid = st.create_attempt(job, cid, "dry_run", NOW)
            st.set_attempt_state(aid, S.PLANNING)
            st.set_attempt_state(aid, S.FAILED, reason=code, detail=detail)
            st.set_application_status(job, "to_apply")
        st.commit()
        st.close()
        rows = {r["job_id"]: r["last_attempt"] for r in client.get("/api/applications").json()}
        fact, doc = rows[j1], rows[j2]
        assert fact["kind"] == "needs_input" and fact["reason_code"] == "owner_fact_missing"
        assert fact["text"] == ("This form asks for your date of birth, which isn't in your profile or "
                                "resume. Nothing was sent.")
        assert fact["hint"] == "Add it in Profile → Your details, then click Try again."   # contract v9 wording
        assert doc["kind"] == "stopped" and doc["reason_code"] == "document_missing"
        assert doc["text"] == "This form needs a photo, and your profile has none. Nothing was sent."
        assert doc["hint"] == "Add it in Profile → Your details → Files, then try again."   # contract v9 wording


# ------------------------------------------------------------------ D. AGREEMENT with the originals


def test_the_routers_effective_policy_agrees_with_apply_flow_effective_policy():
    from jobscraper import backends
    from jobscraper.apply_flow import effective_policy
    from jobscraper.config import ApplyConfig, Config
    from jobscraper.store import Store
    from jobscraper.web.routers.apply import fill_state
    budgets = [{}, {"ollama_url": "http://127.0.0.1:11434"}, {"ollama_url": "http://localhost:11434"},
               {"ollama_url": "http://[::1]:11434"}, {"ollama_url": "http://0.0.0.0:11434"},
               {"ollama_url": "http://ollama:11434"}, {"ollama_url": "https://ollama.example"},
               {"ollama_url": "not a url"}, {"ollama_model": "qwen3:cloud"},
               {"ollama_model": "gpt-oss:120b-cloud"}, {"ollama_model": "QWEN3:CLOUD"},
               {"ollama_model": "llama3:8b"}, {"enable_llm": False}, {"backend": "off"},
               {"backend": "none"}, {"backend": "openai"}, {"backend": "OLLAMA"}]
    applies = [{"fill_policy": p, "fill": f, "always_available": a}       # D-223: both locks, so the copy agrees locked and released
               for p in ("always", "strict") for f in ("llm", "rules") for a in (True, False)]
    saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
    diffs = []
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            st = Store(Path(tmp) / "t.db")
            for budget in budgets:
                for ab in applies:
                    cfg = Config({"budget": budget, "apply": ab})
                    want, why = effective_policy(ApplyConfig.from_raw(ab), backends.build(budget))
                    got = fill_state(cfg, st)
                    if got["fill_policy_effective"] != want.value or bool(got["fill_policy_inactive"]) != bool(why):
                        diffs.append((budget, ab, "flow", want.value, why, "web", got["fill_policy_effective"],
                                      got["fill_policy_inactive"]))
            # the environment overrides decide the same way on both sides
            for env, budget in (({"JOBSCRAPER_OLLAMA_URL": "http://ollama:11434"}, {}),
                                ({"JOBSCRAPER_BACKEND": "off"}, {}),
                                ({"JOBSCRAPER_OLLAMA_URL": "http://127.0.0.1:11434"},
                                 {"ollama_url": "http://ollama:11434"})):
                os.environ.update(env)
                try:
                    ab = {"fill_policy": "always", "fill": "llm", "always_available": True}
                    want, why = effective_policy(ApplyConfig.from_raw(ab), backends.build(budget))
                    got = fill_state(Config({"budget": budget, "apply": ab}), st)
                    if got["fill_policy_effective"] != want.value:
                        diffs.append((env, budget, want.value, got["fill_policy_effective"]))
                finally:
                    for k in env:
                        os.environ.pop(k, None)
            st.close()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    assert not diffs, "the router's effective-policy copy drifted:\n" + "\n".join(map(str, diffs))
