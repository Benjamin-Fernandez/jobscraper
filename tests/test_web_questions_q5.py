"""T5 / WP-Q5 oracles for `/api/questions/answer` (review Q-30 F3, LF §12.1-12.2; lane M probe list):

  - a choice group with two variants: picking one answers only that row (the group stays open);
    picking the other answers the group;
  - `[]` for a variant drops its norms from `picks`, keeps them in `seen` and reopens that row;
  - an employer-scoped yes/no answer answers only the row that employer asked;
  - a generic (qualified-label) text group asked by one employer is saved under
    `by_employer[<employer_norm>]` with no base value; asked by two employers and sent without
    `employer` -> 422 and nothing saved.
Real app over a temp config, DB and applicant.yaml (the `test_web_questions` harness, seeded here
with synthetic employers); no child process, never data/ or port 8765.
Verify: python tests/run_tests.py -k web_questions_q5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import failed_attempt, make_job, needs, report_waiting, seed_question, waiting_mark  # noqa: E402

_MARK = waiting_mark()
GATE = ("jobscraper.web.routers.questions", "jobscraper.store:Store.question_row_employers",
        "jobscraper.store:Store.create_attempt", "jobscraper.applicant:etag")

EX, SC = "Example Employer", "Sample Corp"
EX_N, SC_N = "example employer", "sample corp"


def test_the_q5_oracles_load():
    import test_web_questions as W
    assert W.FakeJobs


def _seed(cfg) -> dict:
    from jobscraper.store import Store
    st = Store(cfg.db_path)
    try:
        c_ex = st.insert_company("example-employer", EX, "https://example.example")
        c_sc = st.insert_company("sample-corp", SC, "https://sample.example")
        j1, j2 = make_job(st, c_ex, 101), make_job(st, c_sc, 102)
        a1, a2 = failed_attempt(st, j1, c_ex), failed_attempt(st, j2, c_sc)

        def q(attempt, job, cid, emp, **kw):
            return seed_question(st, attempt_id=attempt, job_id=job, company_id=cid, employer_norm=emp, **kw)
        ids = {
            "visa_a": q(a1, j1, c_ex, EX_N, key="visa_status", title="Visa status", kind="choice",
                        label="What is your visa status?", options=("Citizen", "PR", "Others"), field_key="v1"),
            "visa_b": q(a2, j2, c_sc, SC_N, key="visa_status", title="Visa status", kind="choice",
                        label="Residency status", options=("Singapore Citizen", "Employment Pass", "Other"),
                        field_key="v2"),
            "lic_a": q(a1, j1, c_ex, EX_N, key="has_licence", title="Driving licence", kind="yes_no",
                       label="Do you hold a valid driving licence?", options=("Yes", "No"), field_key="l1"),
            "lic_b": q(a2, j2, c_sc, SC_N, key="has_licence", title="Driving licence", kind="yes_no",
                       label="Do you have a driving licence?", options=("Yes", "No"), field_key="l2"),
            "spec_1": q(a1, j1, c_ex, EX_N, key="offers_detail", title="Please specify", kind="text",
                        label="Please specify", label_norm="please specify | do you hold other offers",
                        field_key="s1"),
            "spec_2a": q(a1, j1, c_ex, EX_N, key="notice_detail", title="Please specify", kind="text",
                         label="Please specify", label_norm="please specify | notice period", field_key="s2"),
        }
        # the second generic group is asked by Sample Corp too (a second sighting of the same row)
        st.add_sighting(ids["spec_2a"], a2, j2, c_sc, SC_N, "greenhouse", "", "s3", "Please specify", True,
                        "2026-11-02T10:05:00")
        st.commit()
        return ids
    finally:
        st.close()


def _rows(cfg, key) -> dict[int, str]:
    from jobscraper.store import Store
    st = Store(cfg.db_path)
    try:
        return {int(r["id"]): r["status"] for r in st.questions_by_key(key)}
    finally:
        st.close()


def _world():
    import test_web_questions as W
    return W._world(seed=False)


report_waiting("test_web_questions_q5", _MARK)
