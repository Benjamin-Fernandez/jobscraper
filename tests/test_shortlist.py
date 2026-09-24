"""The shortlist file (M5-T1, PRD 8.3[6], D-5).

It is regenerated on every run and safe to delete, so two properties matter:
regenerating it is deterministic (the web app and any diff see no churn), and it
never carries application status - that lives in the database alone.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper import shortlist
from jobscraper.models import RawJob
from jobscraper.store import Store


def _world():
    tmp = Path(tempfile.mkdtemp())
    st = Store(tmp / "t.db")
    ids = {}
    for key, name in (("okx", "OKX"), ("grab", "Grab"), ("ats", "Atlassian")):
        cid = st.insert_company(key, name, f"https://{key}.example.com")
        for n, run in ((1, 1), (2, 2)):
            raw = RawJob(external_id=f"{key}{n}", title=f"Engineer {n}",
                         url=f"https://{key}.example.com/{n}", location="Singapore")
            jid = raw.job_id(cid, "greenhouse")
            st.upsert_job(jid, cid, raw, run, True)
            ids[(key, n)] = jid
    st.commit()
    for (key, n), jid in ids.items():
        st.save_decision(jid, 1, f"h{n}", "accept", True, 0, f"why {key}", "m")
    for run in (1, 2):
        r = st.start_run(at=f"2026-09-2{run}T09:00:00")
        st.finish_run(r, "ok", {})
    return tmp, st, ids


def test_shortlist_regenerates_byte_identically():
    tmp, st, _ = _world()
    path = tmp / "shortlist.json"
    shortlist.write(st, path, 1, now="2026-09-24T10:00:00")
    first = path.read_text(encoding="utf-8")
    path.unlink()
    shortlist.write(st, path, 1, now="2026-09-24T11:00:00")
    second = path.read_text(encoding="utf-8")
    strip = lambda t: {k: v for k, v in json.loads(t).items() if k != "generated_at"}
    assert strip(first) == strip(second)
    assert first.replace("10:00:00", "11:00:00") == second      # byte-level too


def test_shortlist_order_is_run_desc_then_company_then_id():
    _, st, _ = _world()
    doc = shortlist.build(st, 1)
    keys = [(j["run_no"], j["company"]) for j in doc["jobs"]]
    assert keys == [(2, "Atlassian"), (2, "Grab"), (2, "OKX"),
                    (1, "Atlassian"), (1, "Grab"), (1, "OKX")]
    assert [r["run_no"] for r in doc["runs"]] == [2, 1]
    assert [r["accepted"] for r in doc["runs"]] == [3, 3]


def test_shortlist_never_carries_application_status():
    """D-5: the engine regenerates this file; the user's state is not in it."""
    _, st, ids = _world()
    st.set_application_status(ids[("okx", 1)], "applied")
    text = json.dumps(shortlist.build(st, 1))
    for banned in ('"status"', '"applied"', '"applied_at"'):
        assert banned not in text


def test_shortlist_keeps_closed_roles_flagged():
    """Q4: a role that closed stays, marked stale, rather than vanishing."""
    _, st, ids = _world()
    st.close_missing(st.company_by_key("grab").id, set())
    doc = shortlist.build(st, 1)
    grab = [j for j in doc["jobs"] if j["company"] == "Grab"]
    assert len(grab) == 2 and all(j.get("closed") is True for j in grab)
    assert not any(j.get("closed") for j in doc["jobs"] if j["company"] != "Grab")


def test_shortlist_has_the_documented_shape():
    _, st, _ = _world()
    doc = shortlist.build(st, 1)
    assert set(doc) == {"version", "generated_at", "profile_version", "runs", "jobs"}
    assert set(doc["jobs"][0]) >= {"id", "run_no", "company", "title", "url",
                                   "location", "posted_at", "yoe_min", "reason",
                                   "decided_at"}
