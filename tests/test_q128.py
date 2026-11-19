"""Q-128 pins: five small fixes to the live app (the owner's daily app; answering locked to "Stop when unsure").

  1. `store.not_answered_counts` and the chip's number: the Applications row says how many questions an
     attempt left unanswered WITHOUT opening "What was filled"; the number must always equal the count that
     panel shows (rows the answers route marks `not_answered`).
  2. The doctor says the screens' words ("Stop when unsure", "Always answer"), never "Ask me first" / "asks".
  3. Settings -> Apply -> "Answers you corrected": the scope sentence, incl. employers with their own answer.
  4. The three "details needed" counts (shell badge, Profile tab label, status line) agree, with the salary
     amount missing AND two waiting applications naming `pay.expected_salary` / `pay.expected_salary.amount`.
     The server side is the real app over a temp config; the web side is the REAL `detailSections.js`
     run by node over the server's real payloads (skipped with a printed note when node is absent: the
     vitest suite still pins the pure functions).
  5. The wording sweep is a vitest pin: web/tests/q128.test.js.

Temp databases and temp files only: no CLI verb is run against the repository's own `data/`, no model, no
network, nothing from port 8765 / 11434. Made-up names only ("Example Co", "Northwind").
Verify: python tests/run_tests.py -k q128
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_flow_support import Net, backend  # noqa: E402
from questions_support import NOW, make_job, seed_question  # noqa: E402
from test_always_flow_trial import _doctor  # noqa: E402
from test_q127_web import R, _answers, _world  # noqa: E402

from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.store import Store  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ================================================================== 1. store.not_answered_counts

def _row(label, status, *, ftype="text", required=True):
    return {"step": "s1", "field_key": "k_" + label.replace(" ", "_"), "label": label, "label_norm": label.lower(),
            "field_type": ftype, "required": required, "tier": 3, "source": "llm", "confidence": 0.5,
            "status": status, "value_json": None if status in ("unknown", "ungrounded") else "x"}


def _store():
    tmp = tempfile.mkdtemp(prefix="q128_")
    st = Store(Path(tmp) / "t.db")
    cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
    return st, cid, tmp


def _attempt(st, cid, n, rows):
    job = make_job(st, cid, n)
    aid = st.create_attempt(job, cid, "dry_run", NOW)
    st.add_answers(aid, rows)
    st.commit()
    return aid


def test_q128_not_answered_counts_counts_exactly_the_rows_the_panel_calls_not_answered():
    st, cid, tmp = _store()
    try:
        a = _attempt(st, cid, 1, [
            _row("Unknown one", "unknown"),
            _row("Ungrounded one", "ungrounded"),
            _row("Optional unknown", "unknown", required=False),       # not limited to required: the panel's isn't
            _row("Filled", "filled"), _row("Prefilled", "prefilled"),
            _row("Skipped", "skipped"), _row("Blank optional", "blank_optional", required=False),
            _row("Hidden unknown", "unknown", ftype="hidden"),
            _row("Hidden ungrounded", "ungrounded", ftype="hidden"),
        ])
        got = st.not_answered_counts([a])
        assert got == {a: 3}, got
    finally:
        st.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_q128_an_attempt_with_nothing_unanswered_is_absent_and_reads_as_zero():
    st, cid, tmp = _store()
    try:
        a = _attempt(st, cid, 1, [_row("Filled", "filled"), _row("Skipped", "skipped"),
                                  _row("Hidden", "unknown", ftype="hidden")])
        b = _attempt(st, cid, 2, [])                                    # no audit rows at all
        got = st.not_answered_counts([a, b])
        assert got == {}, "an attempt with none is absent (the same contract as assumed_counts)"
        assert got.get(a, 0) == 0 and got.get(b, 0) == 0
    finally:
        st.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_q128_several_attempts_in_one_call_are_counted_apart_and_an_unknown_id_is_absent():
    st, cid, tmp = _store()
    try:
        a = _attempt(st, cid, 1, [_row("A1", "unknown"), _row("A2", "unknown"), _row("A3", "ungrounded")])
        b = _attempt(st, cid, 2, [_row("B1", "ungrounded"), _row("B ok", "filled")])
        c = _attempt(st, cid, 3, [_row("C ok", "filled")])
        got = st.not_answered_counts([a, b, c, 99999])
        assert got == {a: 3, b: 1}, got
        assert 99999 not in got and c not in got
        assert st.not_answered_counts([b]) == {b: 1}, "asking for one attempt never counts another's rows"
        assert st.not_answered_counts([a, a, b]) == {a: 3, b: 1}, "a repeated id is counted once"
        assert st.not_answered_counts([]) == {}
        assert st.not_answered_counts([str(a)]) == {a: 3}, "ids may come as text from a row"
    finally:
        st.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_q128_not_answered_counts_survives_more_ids_than_one_query_chunk():
    """The store asks 500 ids at a time; a list of 600 attempts must still come back right."""
    st, cid, tmp = _store()
    try:
        a = _attempt(st, cid, 1, [_row("A1", "unknown")])
        b = _attempt(st, cid, 2, [_row("B1", "ungrounded"), _row("B2", "unknown")])
        ids = [a] + list(range(10_000, 10_598)) + [b]
        assert len(ids) == 600
        assert st.not_answered_counts(ids) == {a: 1, b: 2}
    finally:
        st.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ---- the chip and the panel can never disagree (the pin that matters) ---------------------------------

MIXED = [   # one stopped attempt (job 1): every kind of row the panel could meet
    R("u1", "Question one", status="unknown", value=None, assumed=False),
    R("u2", "Question two", status="ungrounded", value=None, assumed=False),
    R("u3", "Question three optional", status="unknown", value=None, assumed=False, required=False),
    R("f1", "Filled thing", status="filled", assumed=False),
    R("p1", "Prefilled thing", status="prefilled", assumed=False, source="site_default"),
    R("s1", "Skipped thing", status="skipped", assumed=False),
    R("b1", "Blank optional thing", status="blank_optional", assumed=False, required=False),
    R("h1", "Hidden token", status="unknown", ftype="hidden", value=None, assumed=False),
    # the other job's attempt (it was sent): rows of its own, counted on its own
    R("j2u", "Other job unknown", status="unknown", value=None, assumed=False, job=2),
    R("j2f", "Other job filled", status="filled", assumed=False, job=2),
]


def _panel_count(client, ids, attempt, job):
    r = _answers(client, ids, attempt=attempt, job=job)
    assert r.status_code == 200, r.text
    return sum(1 for f in r.json()["fields"] if f["status"] == "not_answered")


def _row_of(client, job_id):
    return [r for r in client.get("/api/applications").json() if r["job_id"] == job_id][0]


def test_q128_the_list_chip_count_equals_the_number_of_not_answered_rows_the_panel_lists():
    with _world(MIXED) as (client, cfg, ids):
        panel1 = _panel_count(client, ids, "attempt", "job")
        panel2 = _panel_count(client, ids, "attempt2", "job2")
        assert (panel1, panel2) == (3, 1), "the fixture should give the panel 3 and 1: " + repr((panel1, panel2))
        row1, row2 = _row_of(client, ids["job"]), _row_of(client, ids["job2"])
        assert row1["last_attempt"]["not_answered"] == panel1
        assert row2["last_attempt"]["not_answered"] == panel2
        # the per-job attempts list carries the same number for every attempt it lists
        for job, attempt, want in (("job", "attempt", panel1), ("job2", "attempt2", panel2)):
            listed = client.get(f"/api/applications/{ids[job]}/attempts").json()
            mine = [a for a in listed if a["id"] == ids[attempt]]
            assert mine and mine[0]["not_answered"] == want, (job, mine)
        assert type(row1["last_attempt"]["not_answered"]) is int


def test_q128_a_row_with_no_unanswered_rows_says_zero_and_a_job_with_no_attempt_has_no_chip_data():
    rows = [R("f1", "Filled thing", status="filled", assumed=False)]
    with _world(rows, state="dry_run", reason=None) as (client, cfg, ids):
        assert _row_of(client, ids["job"])["last_attempt"]["not_answered"] == 0
        assert _panel_count(client, ids, "attempt", "job") == 0


def test_q128_the_applications_list_asks_for_the_counts_once_not_once_per_row():
    calls = []
    real = Store.not_answered_counts

    def spy(self, attempt_ids):
        calls.append(list(attempt_ids))
        return real(self, attempt_ids)

    Store.not_answered_counts = spy
    try:
        with _world(MIXED) as (client, cfg, ids):
            calls.clear()
            assert client.get("/api/applications").status_code == 200
            assert len(calls) == 1, f"one query for the whole list, got {len(calls)}"
            assert len(calls[0]) >= 2, "both rows' attempts go in that one call"
    finally:
        Store.not_answered_counts = real


# ================================================================== 2. the doctor says the screens' words

def _policy_lines(out: str) -> list[str]:
    lines = out.splitlines()
    keep = []
    for i, ln in enumerate(lines):
        if ln.startswith("fill policy"):
            keep.append(ln)
            j = i + 1
            while j < len(lines) and lines[j].startswith("               "):      # its continuation lines
                keep.append(lines[j])
                j += 1
    return keep


def test_q128_the_doctor_labels_are_the_screens_labels():
    """The one table the doctor reads is the table the Settings screen shows (not two copies that drift)."""
    assert C.FILL_POLICY_LABELS[C.FillPolicy.STRICT] == "Stop when unsure"
    assert C.FILL_POLICY_LABELS[C.FillPolicy.ALWAYS] == "Always answer"
    vue = (REPO / "web" / "src" / "components" / "ApplySettings.vue").read_text(encoding="utf-8")
    assert "{ always: 'Always answer', strict: 'Stop when unsure' }" in vue, "the Settings screen's own words moved"


def test_q128_the_doctor_says_stop_when_unsure_in_all_three_off_cases_and_never_ask_me_first():
    cases = {
        "strict": _doctor(apply_block={}, be=backend(Net())),
        "locked": _doctor(apply_block={"always_available": False, "fill_policy": "always"}, be=backend(Net())),
        "non-local model": _doctor(apply_block={"fill_policy": "always"},
                                   be=backend(Net(), url="http://ollama:11434")),
    }
    for name, out in cases.items():
        lines = _policy_lines(out)
        assert lines, (name, out)
        blob = "\n".join(lines)
        assert lines[0].startswith("fill policy    Stop when unsure"), (name, lines)
        assert "Ask me first" not in out and "Ask me first" not in blob, (name, out)
        assert "asks" not in blob.lower() and "(strict)" not in blob, (name, blob)
        assert "fill policy    Always answer" not in blob, (name, "the running-always line is not shown here")
    assert "Always answer is not released on this install" in "\n".join(_policy_lines(cases["locked"]))
    assert "Always answer is off for now" in "\n".join(_policy_lines(cases["non-local model"]))
    assert "WARNING" in cases["non-local model"] and "WARNING" not in cases["strict"]
    # strict: tells the owner what to do (the way out), in the screens' own words
    assert "What was filled" in cases["strict"] and "Try again" in cases["strict"]
    # control: with Always answer released and a local model, the policy line is the always one
    on = _doctor(apply_block={"fill_policy": "always"}, be=backend(Net()))
    assert _policy_lines(on)[0].startswith("fill policy    Always answer"), on
    assert "Ask me first" not in on


# ================================================================== 3. "Answers you corrected": the scope text

def test_q128_the_saved_answer_scope_sentence_in_the_four_cases():
    from jobscraper.web.routers.apply import _scope_text, remembered_view
    assert _scope_text({}) == "Every application"
    assert _scope_text({"employer": "Example Co"}) == "Only Example Co"
    assert _scope_text({"by_employer": {"northwind": "Yes"}}) == "Every application; 1 employer has their own answer"
    assert _scope_text({"by_employer": {"northwind": "Yes", "exampleco": "No"}}) == \
        "Every application; 2 employers have their own answer"
    # edge: an empty / not-a-dict by_employer is "Every application"; an employer wins over by_employer
    assert _scope_text({"by_employer": {}}) == "Every application"
    assert _scope_text({"by_employer": "oops"}) == "Every application"
    assert _scope_text({"employer": "Example Co", "by_employer": {"a": 1}}) == "Only Example Co"
    # the old sentence is gone
    assert "answered differently" not in _scope_text({"by_employer": {"a": 1, "b": 2}})
    # and through the saved-answers view the owner reads
    prof = {"extra": {"work_mode": {"title": "Work arrangement", "kind": "text", "value": "Hybrid",
                                    "labels": ["work arrangement"], "by_employer": {"northwind": "Remote"}}}}
    view = remembered_view(prof)
    assert [v["scope_text"] for v in view] == ["Every application; 1 employer has their own answer"], view


# ================================================================== 4. the three counts agree

NODE = shutil.which("node")
COUNTS_JS = REPO / "tests" / "js" / "q128_counts.mjs"


def _add_waiting_job(cfg, n, path):
    """A role of its own whose newest attempt stopped for `path` (a waiting application)."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode
    st = Store(cfg.db_path)
    try:
        cid = st.insert_company(f"northwind{n}", f"Northwind {n}", "https://northwind.example")
        job = make_job(st, cid, 50 + n)
        st.set_application_status(job, "to_apply")
        aid = st.create_attempt(job, cid, "dry_run", NOW)
        for s in (S.PLANNING, S.OPENING, S.FILLING):
            st.set_attempt_state(aid, s)
        st.set_attempt_state(aid, S.FAILED, reason=ReasonCode("owner_fact_missing"), detail="x")
        seed_question(st, attempt_id=aid, job_id=job, company_id=cid, employer_norm=f"northwind{n}",
                      field_key="sal", key=f"waiting_{n}", target_path=path, label="Expected salary",
                      kind="text", reason="profile_gap")
        st.commit()
    finally:
        st.close()


def _counts(client, tmp):
    status = client.get("/api/apply/status").json()
    form = client.get("/api/applicant").json()
    payload = {"missing": form["missing"], "needed_by": form["needed_by"], "form": form["form"]}
    src = Path(tmp) / "payload.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    out = subprocess.run([NODE, str(COUNTS_JS), str(src)], capture_output=True, text=True, timeout=60,
                         cwd=str(REPO))
    assert out.returncode == 0, out.stderr or out.stdout
    web = json.loads(out.stdout)
    return {"shell badge": len(status["details_needed"]), "profile tab": web["tab"],
            "status line": web["line"], "labels": web["labels"], "status": status, "form": form}


def test_q128_the_shell_badge_the_profile_tab_and_the_status_line_say_the_same_number():
    if NODE is None:
        print("  (node not found: the web half of this pin is skipped; vitest still pins the pure functions)")
        return

    def salary_missing(p):
        p["pay"] = {"expected_salary": None}

    def salary_and_education_missing(p):
        p["pay"] = {"expected_salary": None}
        p["education"] = []

    for edit, want, why in ((salary_missing, 1, "only the expected salary is missing"),
                            (salary_and_education_missing, 2, "education is missing too")):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            # one waiting role on the sub-path (the world's own), a second on the item itself
            with _world([], profile_edit=edit, reason="owner_fact_missing",
                        waiting_path="pay.expected_salary.amount") as (client, cfg, ids):
                _add_waiting_job(cfg, 2, "pay.expected_salary")
                got = _counts(client, tmp)
                status = got["status"]
                assert "pay.expected_salary.amount" in status["missing"] or "pay.expected_salary" in status["missing"], \
                    status["missing"]
                waiting_paths = {p for w in got["form"]["waiting"] for p in w["paths"]}
                assert {"pay.expected_salary", "pay.expected_salary.amount"} <= waiting_paths, \
                    f"the fixture must have two applications naming the two salary paths: {waiting_paths}"
                assert (got["shell badge"], got["profile tab"], got["status line"]) == (want, want, want), \
                    (why, {k: got[k] for k in ("shell badge", "profile tab", "status line", "labels")},
                     status["details_needed"], status["missing"])
                assert len(got["labels"]) == want, "one label per detail, the salary named once"
                assert "Expected salary" in got["labels"]
