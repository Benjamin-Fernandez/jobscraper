"""Q-127 Release 1 web-backend pins for lane W1 (q127_profile_questions_design.md B.2b, B.5, B.8 pins
1-5, 13, 15). Pin 21 (Other keys) is a vitest pin: web/tests/q127-other-keys.test.js.

RED UNTIL `eng/Q-127-W1` MERGES (and, for the class rows, `eng/Q-127-S1`: `apply_answers.field_class`;
and for the scoped-resolve test, F1: `extra_entry_applies` in apply/resolve.py). Only
`test_q127_web_fixture_builds_*` is green on int/Q-121 at 0ddd971; it proves the fixtures.

The real app over a temp config, temp DB and a temp COPY of the sample applicant file; the job manager
is a fake that records `start` (no job, no browser, no network, nothing from data/). Made-up employer
only ("Example Co", "Northwind"). Never calls POST /api/apply.

Names B.5 leaves open, assumed here (see comms/outbox/tester.md): the remember body is
`{value | picks (list of option labels), only_employer, etag}`; the answer fields `options` is the
list of offered option labels; the 409 / 422 / 410 reasons are found in the response text.
Verify: python tests/run_tests.py -k q127_web
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import profile  # noqa: E402
from questions_support import FIX, NOW, chosen, field, make_job, resolve_one, seed_question, yes_no  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.apply.plan import norm_label  # noqa: E402
from jobscraper.apply.questions import slug_key  # noqa: E402

ENV_KEYS = ("JOBSCRAPER_BACKEND", "JOBSCRAPER_OLLAMA_URL")
RULES = FIX / "questions.sample.yaml"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class _FakeJobs:
    def __init__(self):
        self.started: list = []

    def current(self, tail: int = 200) -> dict:
        from jobscraper.web.jobs import IDLE
        return dict(IDLE, log=[])

    def start(self, kind, opts, tail: int = 200) -> dict:
        self.started.append((kind, dict(opts)))
        return {"id": "fake-1", "kind": kind, "state": "running", "log": []}


def R(name, label, *, ftype="text", options=(), source="assumption", status="filled", assumed=True,
      evidence="", field_class="", value="x", capture=None, qkind="text", required=True, job=1,
      capture_norm=None, sensitive=False):
    """One audit row to seed. `capture` = (question key, named_by) adds a captured `questions` row."""
    return dict(name=name, label=label, ftype=ftype, options=list(options), source=source, status=status,
                assumed=assumed, evidence=evidence, field_class=field_class, value=value,
                capture=capture, qkind=qkind, required=required, job=job, capture_norm=capture_norm, sensitive=sensitive)


@contextlib.contextmanager
def _world(rows=(), *, extra=None, profile_edit=None, state="failed", reason="unanswerable_required",
           attempt_note=None, trial=False, waiting_path=None, submitted_first=False):
    """Yield (client, cfg, ids). ids: job, job2, cid, attempt, attempt2, and per row name
    `a:<name>` (answer id) and `q:<name>` (captured question id)."""
    from fastapi.testclient import TestClient
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            prof = profile()
            if extra is not None:
                prof["extra"] = copy.deepcopy(extra)
            if profile_edit:
                profile_edit(prof)
            path = data / "applicant.yaml"
            path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
            (data / "resume.pdf").write_bytes(b"%PDF-1.4 dummy resume for the Q-127 web pins")
            raw = {"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                             "shortlist": str(data / "shortlist.json"),
                             "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                   "web": {"host": "127.0.0.1", "port": 8765},
                   "apply": {"mode": "dry_run"}}
            cfg = Config(raw)
            st = Store(cfg.db_path)
            cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
            job, job2 = make_job(st, cid, 1), make_job(st, cid, 2)
            ids = {"job": job, "job2": job2, "cid": cid}
            for j in (job, job2):
                st.set_application_status(j, "to_apply")

            def attempt(j, final, code=None, detail="x"):
                aid = st.create_attempt(j, cid, "auto" if final == "submitted" else "dry_run", NOW)
                for s in (S.PLANNING, S.OPENING, S.FILLING):
                    st.set_attempt_state(aid, s)
                if final == "submitted":
                    st.conn.execute("UPDATE apply_attempts SET submit_clicked_at = ? WHERE id = ?", (NOW, aid))
                    st.set_attempt_state(aid, S.SUBMITTING)
                    st.set_attempt_state(aid, S.SUBMITTED)
                elif final == "failed":
                    st.set_attempt_state(aid, S.FAILED, reason=ReasonCode(code), detail=detail)
                else:
                    st.set_attempt_state(aid, S.READY_TO_SUBMIT)
                return aid

            if submitted_first:
                ids["attempt_sent"] = attempt(job, "submitted")
            ids["attempt"] = attempt(job, state, reason) if state == "failed" else attempt(job, state)
            ids["attempt2"] = attempt(job2, "submitted")
            if attempt_note or trial:
                st.conn.execute("UPDATE apply_attempts SET entries_note = ?, trial = ? WHERE id = ?",
                                (attempt_note, int(trial), ids["attempt"]))
            by_attempt: dict[int, list] = {}
            for i, r in enumerate(rows):
                fk = f"f{i}"
                aid = ids["attempt2"] if r["job"] == 2 else ids["attempt"]
                jid = job2 if r["job"] == 2 else job
                opts = [{"label": o, "value": o} for o in r["options"]] or None
                by_attempt.setdefault(aid, []).append((r, fk, {
                    "step": "s1", "field_key": fk, "label": r["label"], "label_norm": norm_label(r["label"]),
                    "field_type": r["ftype"], "required": r["required"], "tier": 3, "source": r["source"],
                    "confidence": 0.5, "status": r["status"], "value_json": r["value"],
                    "evidence": r["evidence"] or None, "assumed": r["assumed"],
                    "options_json": opts, "field_class": r["field_class"], "sensitive": r["sensitive"]}))
                if r["capture"]:
                    ids["q:" + r["name"]] = seed_question(
                        st, attempt_id=aid, job_id=jid, company_id=cid, employer_norm="exampleco",
                        field_key=fk, key=r["capture"][0], named_by=r["capture"][1], kind=r["qkind"],
                        label=r["label"], options=r["options"], reason="no_rule",
                        **({"label_norm": r["capture_norm"]} if r["capture_norm"] else {}))
            for aid, items in by_attempt.items():
                st.add_answers(aid, [row for _r, _fk, row in items])
                got = {a["field_key"]: a["id"] for a in st.answers(aid)}
                for r, fk, _row in items:
                    ids["a:" + r["name"]] = got[fk]
            if waiting_path:
                qid = seed_question(st, attempt_id=ids["attempt"], job_id=job, company_id=cid,
                                    employer_norm="exampleco", field_key="dobf", key=waiting_path,
                                    target_path=waiting_path, label="Date of birth", kind="date",
                                    reason="profile_gap", sensitive=True)
                ids["q:waiting"] = qid
            st.commit()
            st.close()
            app = create_app(cfg)
            app.state.jobs = _FakeJobs()
            with TestClient(app, base_url="http://localhost") as client:
                yield client, cfg, ids
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _etag(client) -> str:
    return client.get("/api/applicant").json()["etag"]


def _answers(client, ids, attempt="attempt", job="job"):
    return client.get(f"/api/applications/{ids[job]}/attempts/{ids[attempt]}/answers")


def _remember(client, ids, name, *, etag=None, **body):
    body.setdefault("etag", etag if etag is not None else _etag(client))
    return client.post(f"/api/applications/{ids['job']}/attempts/{ids['attempt']}/answers/"
                       f"{ids['a:' + name]}/remember", json=body)


def _file(cfg) -> bytes:
    return Path(cfg.applicant_path).read_bytes()


def _extra(cfg) -> dict:
    return applicant.load(cfg.applicant_path).get("extra") or {}


def _db(cfg, sql, *a):
    import sqlite3
    con = sqlite3.connect(str(cfg.db_path))
    try:
        return con.execute(sql, a).fetchall()
    finally:
        con.close()


def _status_of_questions(cfg) -> dict:
    return {r[0]: r[1] for r in _db(cfg, "SELECT id, status FROM questions")}


def _by_label(resp) -> dict:
    return {f["label"]: f for f in resp.json()["fields"]}


# ---- fixtures prove themselves (green on int/Q-121) ------------------------------------------------

def test_q127_web_fixture_builds_and_the_old_routes_still_work_before_w1():
    rows = [R("a", "Preferred work arrangement", capture=("work_mode", "model"))]
    with _world(rows, attempt_note="1 of 2 education entries added", trial=True, waiting_path="identity.date_of_birth",
                submitted_first=True) as (client, cfg, ids):
        assert client.get("/api/applications").status_code == 200
        assert ids["a:a"] and ids["q:a"] and ids["attempt2"] != ids["attempt"]
        assert _etag(client)


# ---- pin 1: the answers route ----------------------------------------------------------------------

SOURCE_ROWS = [   # (source, status, assumed, evidence, basis words: exact, or a prefix when it ends in "*")
    ("profile:identity.first_name", "filled", False, "", "From your details*"),
    ("field_map:first_name", "filled", False, "", "From your details*"),
    ("memory:extra.work_mode", "filled", False, "", "Your saved answer"),
    ("standing:years_experience", "filled", False, "", "Worked out from your details"),
    ("default:no_nda", "filled", False, "", "Your standing answer"),
    ("declaration", "filled", False, "", "Your standing answer"),
    ("resume", "filled", False, "", "From your resume"),
    ("job", "filled", False, "", "From the job posting"),
    ("composed", "filled", False, "", "Written for this application"),
    ("field_map:resume", "filled", False, "", "Your resume file"),
    ("field_map:email", "filled", False, "", "Your application email"),
    ("llm", "filled", False, "", "Written by the local AI from your details"),
    ("mygreenhouse", "prefilled", False, "", "Kept from the site"),
    ("workday_last_application", "prefilled", False, "", "Kept from the site"),
    ("site_default", "prefilled", False, "", "Kept from the site"),
    ("resume_import", "prefilled", False, "", "Kept from the site"),
    ("assumption", "filled", True, "no preference stated", "Assumed: no preference stated"),
    ("fallback:F2", "filled", True, "", "Assumed: nothing in your details or resume covered it"),
    ("llm", "unknown", False, "", "Not answered"),
    ("llm", "ungrounded", False, "", "Not answered"),
]


def _source_rows():
    return [R(f"s{i}", f"Source row number {i}", source=s, status=st, assumed=a, evidence=ev,
              value=None if st in ("unknown", "ungrounded") else "v")
            for i, (s, st, a, ev, _w) in enumerate(SOURCE_ROWS)]


def test_q127_every_source_gives_its_basis_words_and_the_not_answered_and_assumed_rows_are_marked():
    with _world(_source_rows(), attempt_note="1 of 2 education entries added", trial=True) as (client, cfg, ids):
        r = _answers(client, ids)
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"attempt", "employer", "fields"} and body["employer"] == "Example Co"
        got = _by_label(r)
        for i, (source, status, assumed, evidence, want) in enumerate(SOURCE_ROWS):
            f = got[f"Source row number {i}"]
            assert set(f) == set(C.ANSWERS_FIELD_KEYS), f
            words = f["basis_text"]
            assert words.startswith(want[:-1]) if want.endswith("*") else words == want, (source, status, words)
            assert f["assumed"] is assumed, source
            if status in ("unknown", "ungrounded"):
                assert f["status"] == "not_answered", source
            else:
                assert f["status"] == "not_sent", "a stopped attempt sent nothing: " + source
            if assumed:
                assert f["reason_text"] == evidence or not evidence, source


def test_q127_the_attempt_block_shows_entries_note_and_trial_and_a_sent_row_says_sent():
    rows = [R("a", "Preferred work arrangement"), R("b", "Sent on the other job", job=2)]
    with _world(rows, attempt_note="1 of 2 education entries added", trial=True) as (client, cfg, ids):
        a = _answers(client, ids).json()["attempt"]
        assert set(a) == set(C.ANSWERS_ATTEMPT_KEYS)
        assert a["id"] == ids["attempt"] and a["entries_note"] == "1 of 2 education entries added"
        assert a["trial"] is True
        sent = _answers(client, ids, attempt="attempt2", job="job2").json()
        assert [f["status"] for f in sent["fields"]] == ["sent"]
        assert sent["attempt"]["trial"] is False and not sent["attempt"]["entries_note"]


def test_q127_an_attempt_of_another_job_or_an_unknown_one_is_404_and_nothing_leaks():
    rows = [R("a", "Preferred work arrangement", evidence="a reason", source="assumption")]
    with _world(rows) as (client, cfg, ids):
        assert client.get(f"/api/applications/{ids['job2']}/attempts/{ids['attempt']}/answers").status_code == 404
        assert client.get(f"/api/applications/{ids['job']}/attempts/99999/answers").status_code == 404
        assert client.get(f"/api/applications/nosuchjob/attempts/{ids['attempt']}/answers").status_code == 404
        text = _answers(client, ids).text
        for leak in (str(cfg.db_path), str(cfg.applicant_path), "://", "password", "Traceback"):
            assert leak not in text, leak
        assert "log" not in json.loads(text)["attempt"]


# ---- pin 13: refusals write nothing -------------------------------------------------------------------

PROTECTED_SOURCES = ["profile:identity.first_name", "field_map:first_name", "standing:work_rights_sg",
                     "default:no_nda", "declaration"]
PROTECTED_CLASSES = ["declaration:criminal_record", "declaration:pep", "consent_privacy", "consent_retention",
                     "marketing", "work_right", "sponsorship", "self_id:gender", "owner_fact:date_of_birth"]


def _protected_rows():
    rows = [R(f"src{i}", f"Protected source number {i}", source=s, assumed=False, capture=(f"k_src{i}", "model"))
            for i, s in enumerate(PROTECTED_SOURCES)]
    rows += [R(f"cls{i}", f"Protected class number {i}", source="assumption", field_class=c,
               capture=(f"k_cls{i}", "model")) for i, c in enumerate(PROTECTED_CLASSES)]
    return rows


def test_q127_the_answers_route_offers_no_remember_on_a_protected_source_or_class():
    with _world(_protected_rows()) as (client, cfg, ids):
        got = _by_label(_answers(client, ids))
        for i, _s in enumerate(PROTECTED_SOURCES):
            f = got[f"Protected source number {i}"]
            assert f["can_remember"] is False and f["refusal"] == "follows_your_details", f
        for i, _c in enumerate(PROTECTED_CLASSES):
            f = got[f"Protected class number {i}"]
            assert f["can_remember"] is False and f["refusal"] == "follows_your_details", f


def test_q127_remember_on_each_protected_source_and_class_is_refused_and_writes_nothing():
    rows = _protected_rows()
    with _world(rows, extra={"keepme": {"title": "Keep me", "description": "", "kind": "text", "sensitive": False,
                                        "labels": ["some other question here"], "value": "mine"}}) as (client, cfg, ids):
        before_file = _file(cfg)
        before_q = _status_of_questions(cfg)
        etag = _etag(client)
        for r in rows:
            resp = _remember(client, ids, r["name"], etag=etag, value="Yes", only_employer=True)
            assert resp.status_code == 422, (r["name"], resp.status_code, resp.text)
            assert "follows_your_details" in resp.text, r["name"]
        assert _file(cfg) == before_file, "the applicant file is byte-identical"
        assert _status_of_questions(cfg) == before_q, "no question row was marked answered"
        assert _db(cfg, "SELECT COUNT(*) FROM apply_answers WHERE corrected_json IS NOT NULL") == [(0,)]


# ---- pin 2: remember for each kind and scope -----------------------------------------------------------

KINDS = [   # (name, label, field_type, options, qkind, body for a value, expected stored value / picks)
    ("yn", "Are you comfortable with occasional travel", "dropdown", ["Yes", "No"], "yes_no", {"value": True}, True),
    ("ch", "Where would you prefer to be based", "dropdown", ["Hybrid", "Remote", "On site"], "choice",
     {"picks": ["Remote"]}, None),
    ("tx", "Describe your ideal weekend routine", "text", [], "text", {"value": "Hiking and reading"}, "Hiking and reading"),
    ("nu", "How many projects did you lead", "number", [], "number", {"value": 4}, 4),
    ("dt", "Earliest date you could attend a workshop", "date", [], "date", {"value": "2027-02-01"}, "2027-02-01"),
]


def _remember_rows():
    rows = []
    for name, label, ft, opts, qk, _b, _w in KINDS:
        for scope in ("emp", "all"):
            rows.append(R(f"{name}_{scope}", f"{label} {scope}", ftype=ft, options=opts, qkind=qk,
                          capture=(f"model_key_{name}_{scope}", "model"), value=None))
    return rows


def test_q127_remember_writes_one_new_entry_for_the_exact_label_with_scope_and_answers_the_rows():
    rows = _remember_rows()
    with _world(rows) as (client, cfg, ids):
        for name, label, _ft, opts, qk, body, want in KINDS:
            for scope in ("emp", "all"):
                row = f"{name}_{scope}"
                label_norm = norm_label(f"{label} {scope}")
                existing = list(_extra(cfg))
                qs_before = _status_of_questions(cfg)
                resp = _remember(client, ids, row, only_employer=(scope == "emp"), **body)
                assert resp.status_code == 200, (row, resp.status_code, resp.text)
                out = resp.json()
                assert {"key", "remembered_text", "ready_to_retry", "etag"} <= set(out), out
                key = out["key"]
                assert KEY_RE.match(key) and key != f"model_key_{name}_{scope}", "never the captured row's key (H2)"
                assert key == slug_key(label_norm, existing), "slug of the exact label, next free suffix"
                entry = _extra(cfg)[key]
                assert entry["labels"] == [label_norm] and entry["kind"] == qk
                assert "by_employer" not in entry and not entry.get("promoted")
                assert applicant.extra_entry_errors(key, entry) == [], entry
                if qk == "choice":
                    picks = {norm_label(p) for p in entry["picks"]}
                    seen = {norm_label(s) for s in entry["seen"]}
                    assert picks == {"remote"} and picks <= seen and seen == {norm_label(o) for o in opts}
                else:
                    assert entry["value"] == want
                if scope == "emp":
                    assert entry.get(C.EXTRA_EMPLOYER_FIELD) == "Example Co"
                else:
                    assert not entry.get(C.EXTRA_EMPLOYER_FIELD)
                assert out["etag"] == _etag(client)
                assert _db(cfg, "SELECT corrected_json FROM apply_answers WHERE id = ?", ids["a:" + row])[0][0] is not None
                after = _status_of_questions(cfg)
                assert after[ids["q:" + row]] == "answered"
                for qid, st in qs_before.items():
                    if qid != ids["q:" + row]:
                        assert after[qid] == st, "only this attempt's rows for this field are answered"
                assert len(after) == len(qs_before), "nothing deleted"
        assert not [p for p in _extra(cfg) if not KEY_RE.match(p)]


def test_q127_ready_to_retry_follows_the_last_question_row_of_the_attempt():
    rows = [R("one", "First open question here", capture=("k1", "model"), value=None),
            R("two", "Second open question here", capture=("k2", "model"), value=None)]
    with _world(rows) as (client, cfg, ids):
        first = _remember(client, ids, "one", value="Alpha", only_employer=True)
        assert first.status_code == 200 and first.json()["ready_to_retry"] is False
        second = _remember(client, ids, "two", value="Beta", only_employer=True)
        assert second.status_code == 200 and second.json()["ready_to_retry"] is True
        row = [r for r in client.get("/api/applications").json() if r["job_id"] == ids["job"]][0]
        assert row["last_attempt"]["ready_to_retry"] is True


def test_q127_a_stale_etag_is_409_and_a_generic_label_with_no_captured_row_is_422_and_neither_writes():
    rows = [R("ok", "A perfectly ordinary question", capture=("k1", "model"), value=None),
            R("gen", "Please specify", value=None)]
    with _world(rows) as (client, cfg, ids):
        before, before_q = _file(cfg), _status_of_questions(cfg)
        stale = _remember(client, ids, "ok", etag="not-the-etag", value="x", only_employer=True)
        assert stale.status_code == 409
        too_general = _remember(client, ids, "gen", value="x", only_employer=True)
        assert too_general.status_code == 422 and "too_general" in too_general.text
        assert _file(cfg) == before and _status_of_questions(cfg) == before_q


def test_q127_a_bare_generic_label_is_never_remembered_but_its_contextual_form_is():
    """Coordinator ruling: an entry for the bare "Please specify" would answer every such label on
    every form. Only the contextual form "norm | context", as real captured rows carry it, is
    rememberable; the bare label is refused (422 too_general) even when a row was captured for it."""
    ctx = "please specify | @s1#0"
    rows = [R("bare", "Please specify", capture=("k_bare", "model"), value=None),
            R("ctx", "Please specify", capture=("k_ctx", "model"), value=None, capture_norm=ctx)]
    with _world(rows) as (client, cfg, ids):
        before = _file(cfg)
        refused = _remember(client, ids, "bare", value="Details here", only_employer=True)
        assert refused.status_code == 422 and "too_general" in refused.text, refused.text
        assert _file(cfg) == before, "nothing written for the bare label"
        ok = _remember(client, ids, "ctx", value="Details here", only_employer=True)
        assert ok.status_code == 200, ok.text
        entry = _extra(cfg)[ok.json()["key"]]
        assert entry["labels"] == [ctx], "the contextual label, never the bare one"
        assert "please specify" not in entry["labels"]


# ---- pin 15: a correction never touches another entry --------------------------------------------------

OTHER = {"title": "Work mode", "description": "", "kind": "text", "sensitive": False,
         "labels": ["preferred work arrangement"], "value": "Hybrid"}


def test_q127_a_model_named_row_whose_key_holds_another_entry_leaves_that_entry_untouched():
    rows = [R("a", "Where would you like to work", capture=("work_mode", "model"), value=None)]
    with _world(rows, extra={"work_mode": OTHER}) as (client, cfg, ids):
        resp = _remember(client, ids, "a", value="Remote", only_employer=False)
        assert resp.status_code == 200, resp.text
        key = resp.json()["key"]
        assert key != "work_mode"
        extra = _extra(cfg)
        assert extra["work_mode"] == OTHER, "the other entry is byte-identical afterwards"
        assert extra[key]["labels"] == ["where would you like to work"]


def test_q127_a_label_shared_with_other_wordings_is_409_shared_answer_and_writes_nothing():
    shared = dict(OTHER, labels=["where would you like to work", "preferred work arrangement"])
    rows = [R("a", "Where would you like to work", capture=("k1", "model"), value=None)]
    with _world(rows, extra={"work_mode": shared}) as (client, cfg, ids):
        before, before_q = _file(cfg), _status_of_questions(cfg)
        resp = _remember(client, ids, "a", value="Remote", only_employer=True)
        assert resp.status_code == 409 and "shared_answer" in resp.text
        assert _file(cfg) == before and _status_of_questions(cfg) == before_q


def test_q127_a_label_held_by_an_entry_of_its_own_is_updated_by_scope_not_duplicated():
    own = dict(OTHER, labels=["where would you like to work"], employer="Example Co")
    rows = [R("a", "Where would you like to work", capture=("k1", "model"), value=None)]
    with _world(rows, extra={"work_mode": own}) as (client, cfg, ids):
        resp = _remember(client, ids, "a", value="Remote", only_employer=False)
        assert resp.status_code == 200, resp.text
        extra = _extra(cfg)
        assert resp.json()["key"] == "work_mode" and list(extra) == ["work_mode"]
        assert extra["work_mode"]["value"] == "Remote" and not extra["work_mode"].get(C.EXTRA_EMPLOYER_FIELD)


# ---- pin 3: a strict resolve returns the remembered answer ---------------------------------------------

def test_q127_a_strict_resolve_of_the_remembered_label_returns_the_remembered_answer():
    rows = [R("yn", "Are you comfortable with occasional travel", ftype="dropdown", options=["Yes", "No"],
              qkind="yes_no", capture=("k_yn", "model"), value=None),
            R("tx", "Describe your ideal weekend routine", capture=("k_tx", "model"), value=None)]
    with _world(rows) as (client, cfg, ids):
        k1 = _remember(client, ids, "yn", value=True, only_employer=False).json()["key"]
        k2 = _remember(client, ids, "tx", value="Hiking and reading", only_employer=False).json()["key"]
        prof = applicant.load(cfg.applicant_path)
        a = resolve_one(yes_no("q", "Are you comfortable with occasional travel"), prof, RULES, employer="Example Co")
        assert a.source == f"memory:extra.{k1}" and chosen(a) == ("Yes",), a
        b = resolve_one(field("q", "Describe your ideal weekend routine"), prof, RULES, employer="Example Co")
        assert b.source == f"memory:extra.{k2}" and b.value == "Hiking and reading", b
        c = resolve_one(field("q", "Describe your ideal weekend routine"), prof, RULES, employer="Northwind")
        assert c.source == f"memory:extra.{k2}", "an every-employer answer reaches any employer"


def test_q127_an_only_this_employer_answer_reaches_that_employer_and_no_other_RED_UNTIL_F1():
    rows = [R("tx", "Describe your ideal weekend routine", capture=("k_tx", "model"), value=None)]
    with _world(rows) as (client, cfg, ids):
        key = _remember(client, ids, "tx", value="Hiking and reading", only_employer=True).json()["key"]
        prof = applicant.load(cfg.applicant_path)
        f = field("q", "Describe your ideal weekend routine")
        assert resolve_one(f, prof, RULES, employer="Example Co").source == f"memory:extra.{key}"
        assert resolve_one(f, prof, RULES, employer="Northwind").source != f"memory:extra.{key}"
        assert resolve_one(f, prof, RULES, employer="Example Co Singapore", aliases=("Example Co",)
                           ).source == f"memory:extra.{key}"


# ---- pin 4: the retired questions routes ---------------------------------------------------------------

OLD_SHAPE = {"mode", "groups", "counts", "ready", "waiting", "busy", "model_sees_private", "retired"}


def test_q127_get_questions_keeps_the_full_old_shape_with_every_list_empty_for_every_status():
    rows = [R("a", "An open question for the old list", capture=("k_old", "rule"), value=None)]
    with _world(rows) as (client, cfg, ids):
        assert _db(cfg, "SELECT COUNT(*) FROM questions WHERE status = 'open'") == [(1,)], "the row is still there"
        for status in ("open", "answered", "assumed", "all"):
            r = client.get(f"/api/questions?status={status}")
            assert r.status_code == 200, status
            b = r.json()
            assert set(b) == OLD_SHAPE, (status, set(b) ^ OLD_SHAPE)
            assert b["groups"] == [] and b["ready"] == [] and b["waiting"] == []
            assert b["counts"] == {"open": 0, "assumed": 0, "answered": 0, "dismissed": 0}
            assert b["retired"] is True
            assert isinstance(b["busy"], bool) and isinstance(b["model_sees_private"], bool)
            assert b["mode"] in ("dry_run", "auto", "off") or isinstance(b["mode"], str)
        assert _db(cfg, "SELECT COUNT(*) FROM questions WHERE status = 'open'") == [(1,)], "nothing deleted"


def test_q127_every_old_question_writer_answers_410_retired_and_writes_nothing():
    rows = [R("a", "An open question for the old list", capture=("k_old", "rule"), value=None)]
    with _world(rows) as (client, cfg, ids):
        before, before_q = _file(cfg), _status_of_questions(cfg)
        qid = ids["q:a"]
        calls = [("/api/questions/answer", {"key": "k_old", "value": "x", "etag": _etag(client)}),
                 ("/api/questions/k_old/dismiss", None),
                 ("/api/questions/retry", {"job_ids": [ids["job"]]}),
                 (f"/api/questions/{qid}/keep", {}),
                 (f"/api/questions/{qid}/change", {"value": "x"})]
        for url, body in calls:
            r = client.post(url, json=body) if body is not None else client.post(url)
            assert r.status_code == 410, (url, r.status_code, r.text)
            assert C.QUESTIONS_RETIRED in r.text, url
        assert _file(cfg) == before and _status_of_questions(cfg) == before_q
        assert client.app.state.jobs.started == [], "the retired retry route enqueued nothing"


# ---- pin 5: details_needed ----------------------------------------------------------------------------

def test_q127_details_needed_is_what_is_missing_plus_what_waiting_roles_need():
    def blank(p):
        p.setdefault("identity", {})["date_of_birth"] = None
    with _world([], profile_edit=blank, reason="owner_fact_missing", waiting_path="identity.date_of_birth") as (client, cfg, ids):
        st = client.get("/api/apply/status").json()
        needed = st["details_needed"]
        assert isinstance(needed, list) and len(needed) == len(set(needed)), needed
        assert set(st["missing"]) <= set(needed), "everything missing is needed"
        assert "identity.date_of_birth" in needed, "a waiting role's path is needed while it is empty"

        def fill(p):
            p["identity"]["date_of_birth"] = "2001-02-03"
        prof = applicant.load(cfg.applicant_path)
        fill(prof)
        Path(cfg.applicant_path).write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
        after = client.get("/api/apply/status").json()
        assert "identity.date_of_birth" not in after["details_needed"], "filled: no longer needed"
        assert set(after["missing"]) <= set(after["details_needed"])


def test_q127_ready_to_retry_for_a_waiting_role_needs_every_waited_path_filled_and_never_after_a_submit():
    def blank(p):
        p.setdefault("identity", {})["date_of_birth"] = None
    with _world([], profile_edit=blank, reason="owner_fact_missing", waiting_path="identity.date_of_birth") as (client, cfg, ids):
        def last():
            return [r for r in client.get("/api/applications").json() if r["job_id"] == ids["job"]][0]["last_attempt"]
        assert last()["ready_to_retry"] is False
        prof = applicant.load(cfg.applicant_path)
        prof["identity"]["date_of_birth"] = "2001-02-03"
        Path(cfg.applicant_path).write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
        assert last()["ready_to_retry"] is True
    with _world([], reason="owner_fact_missing", waiting_path="identity.date_of_birth",
                submitted_first=True) as (client, cfg, ids):
        prof = applicant.load(cfg.applicant_path)
        prof.setdefault("identity", {})["date_of_birth"] = "2001-02-03"
        Path(cfg.applicant_path).write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
        row = [r for r in client.get("/api/applications").json() if r["job_id"] == ids["job"]][0]
        assert row["last_attempt"]["ready_to_retry"] is False, "a job with a submitted attempt is never ready"


def test_q127_an_owner_fact_stop_for_a_fact_with_no_field_says_so_on_the_row():
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode
    with _world([]) as (client, cfg, ids):
        from jobscraper.store import Store
        st = Store(cfg.db_path)
        aid = st.create_attempt(ids["job2"], ids["cid"], "dry_run", NOW)
        for s in (S.PLANNING, S.OPENING, S.FILLING):
            st.set_attempt_state(aid, s)
        st.set_attempt_state(aid, S.FAILED, reason=ReasonCode.OWNER_FACT_MISSING, detail="passport number")
        st.commit()
        st.close()
        row = [r for r in client.get("/api/applications").json() if r["job_id"] == ids["job2"]][0]
        la = row["last_attempt"]
        assert la["no_field"] is True
        assert la["text"] == C.OWNER_FACT_NO_FIELD_TEXT.text.format(detail="passport number")
        assert la["hint"] == C.OWNER_FACT_NO_FIELD_HINT


# ---- the M4 server rule (design B.5 PUT) --------------------------------------------------------------

def test_q127_a_section_save_succeeds_past_an_unchanged_invalid_extra_entry_but_not_a_changed_one():
    bad = {"title": "Old", "description": "", "kind": "number", "sensitive": False,
           "labels": ["some old wording here"], "value": "not a number"}
    with _world([], extra={"old_one": bad}) as (client, cfg, ids):
        body = client.get("/api/applicant").json()
        prof = body["profile"]
        prof["identity"]["first_name"] = "Alexandra"
        ok = client.put("/api/applicant", json={"profile": prof, "etag": body["etag"]})
        assert ok.status_code == 200, ok.text
        assert applicant.load(cfg.applicant_path)["identity"]["first_name"] == "Alexandra"
        body = client.get("/api/applicant").json()
        prof = body["profile"]
        prof["extra"]["old_one"]["value"] = "still not a number"
        changed = client.put("/api/applicant", json={"profile": prof, "etag": body["etag"]})
        assert changed.status_code == 422, "an entry the request changed is validated"


# ---- T0: what the retired Keep / Change / answer routes protected, now through remember --------------

def test_q127_a_pick_that_is_not_an_offered_option_is_422_and_nothing_is_saved():
    rows = [R("ch", "Where would you prefer to be based", ftype="dropdown", options=["Hybrid", "Remote"],
              qkind="choice", capture=("k_ch", "model"), value=None)]
    with _world(rows) as (client, cfg, ids):
        before, before_q = _file(cfg), _status_of_questions(cfg)
        for body in ({"picks": ["Dependant Pass"]}, {"picks": ["Hybrid", "Remote"]}, {"picks": []}):
            r = _remember(client, ids, "ch", only_employer=True, **body)
            assert r.status_code == 422 and "invalid" in r.text, (body, r.status_code, r.text)
        assert _file(cfg) == before and _status_of_questions(cfg) == before_q
        assert _db(cfg, "SELECT COUNT(*) FROM apply_answers WHERE corrected_json IS NOT NULL") == [(0,)]


def test_q127_a_wrong_value_for_the_kind_is_422_and_nothing_is_saved():
    rows = [R("nu", "How many projects did you lead", ftype="number", qkind="number", capture=("k_nu", "model"), value=None),
            R("yn", "Are you comfortable with occasional travel", ftype="dropdown", options=["Yes", "No"],
              qkind="yes_no", capture=("k_yn", "model"), value=None),
            R("dt", "Earliest date you could attend a workshop", ftype="date", qkind="date",
              capture=("k_dt", "model"), value=None)]
    with _world(rows) as (client, cfg, ids):
        before = _file(cfg)
        for name, bad in (("nu", "many"), ("yn", "perhaps"), ("dt", "next spring")):
            r = _remember(client, ids, name, value=bad, only_employer=True)
            assert r.status_code == 422, (name, r.status_code, r.text)
        assert _file(cfg) == before


def test_q127_remember_on_an_unknown_or_foreign_answer_is_404_and_a_broken_profile_is_409_unreadable():
    rows = [R("a", "A perfectly ordinary question", capture=("k1", "model"), value=None),
            R("b", "Sent on the other job", job=2)]
    with _world(rows) as (client, cfg, ids):
        etag = _etag(client)
        before = _file(cfg)
        base = f"/api/applications/{ids['job']}/attempts/{ids['attempt']}/answers"
        assert client.post(f"{base}/99999/remember", json={"value": "x", "etag": etag}).status_code == 404
        foreign = client.post(f"{base}/{ids['a:b']}/remember", json={"value": "x", "etag": etag})
        assert foreign.status_code == 404, "an answer of another job's attempt"
        assert _file(cfg) == before
        Path(cfg.applicant_path).write_text("identity: [unclosed" + chr(10), encoding="utf-8")
        broken = Path(cfg.applicant_path).read_bytes()
        r = _remember(client, ids, "a", etag=etag, value="x", only_employer=True)
        assert r.status_code == 409 and "unreadable" in r.text, r.text
        assert Path(cfg.applicant_path).read_bytes() == broken, "an unreadable file is never overwritten"


def test_q127_a_remember_keeps_the_replaced_profile_as_prev_and_a_refused_one_does_not():
    rows = [R("ok", "A perfectly ordinary question", capture=("k1", "model"), value=None),
            R("no", "Protected source number", source="profile:identity.first_name", assumed=False)]
    with _world(rows) as (client, cfg, ids):
        prev = Path(cfg.applicant_path).with_name("applicant.prev.yaml")
        assert not prev.exists()
        before = _file(cfg)
        assert _remember(client, ids, "no", value="x", only_employer=True).status_code == 422
        assert not prev.exists(), "a refused remember writes no prev copy"
        assert _remember(client, ids, "ok", value="Alpha", only_employer=True).status_code == 200
        assert prev.exists() and prev.read_bytes() == before, "the replaced profile is kept as applicant.prev.yaml"


def test_q127_a_multi_choice_is_remembered_with_every_pick_and_a_private_row_stays_private():
    rows = [R("mu", "Which work arrangements suit you", ftype="multi_choice", options=["Hybrid", "On site", "Remote"],
              qkind="multi", capture=("k_mu", "model"), value=["Hybrid"], sensitive=True)]
    with _world(rows) as (client, cfg, ids):
        r = _remember(client, ids, "mu", picks=["Hybrid", "Remote"], only_employer=False)
        assert r.status_code == 200, r.text
        entry = _extra(cfg)[r.json()["key"]]
        assert entry["kind"] == "multi" and entry["value"] is None
        assert {norm_label(p) for p in entry["picks"]} == {"hybrid", "remote"}
        assert entry["sensitive"] is True, "a private field stays private when remembered"
        assert applicant.extra_entry_errors(r.json()["key"], entry) == []


def test_q127_a_remembered_row_shows_what_was_saved_and_a_redacted_reason_is_never_shown():
    rows = [R("a", "A perfectly ordinary question", capture=("k1", "model"), value=None, evidence="no preference stated"),
            R("red", "Anything to add about pay", sensitive=True, evidence="model quote redacted (private field)")]
    with _world(rows) as (client, cfg, ids):
        got = _by_label(_answers(client, ids))
        assert got["A perfectly ordinary question"]["remembered_text"] == ""
        assert got["Anything to add about pay"]["reason_text"] == ""
        assert "redacted" not in json.dumps(got).lower()
        assert _remember(client, ids, "a", value="Alpha", only_employer=True).status_code == 200
        after = _by_label(_answers(client, ids))["A perfectly ordinary question"]
        assert "Alpha" in after["remembered_text"], after


def test_q127_details_needed_lists_one_field_once_not_the_field_and_its_sub_path_RED_UNTIL_F1():
    """Known gap (U1 / U3 handoffs): the salary is `pay.expected_salary` (a waiting role) and
    `pay.expected_salary.amount` (missing). The shell badge counts what the server lists, so one field
    must be listed once. Pinned as the deduplicated behaviour."""
    def blank(p):
        p["pay"] = {"expected_salary": None}
    with _world([], profile_edit=blank, reason="owner_fact_missing", waiting_path="pay.expected_salary") as (client, cfg, ids):
        needed = client.get("/api/apply/status").json()["details_needed"]
        assert needed, "something is needed"
        nested = [(a, b) for a in needed for b in needed if a != b and a.startswith(b + ".")]
        assert not nested, f"a field is listed twice (path and sub-path): {nested}"
