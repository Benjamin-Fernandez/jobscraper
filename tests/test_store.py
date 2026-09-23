"""Persistence invariants.

One test today, and it guards the invariant most likely to destroy data: a
company whose fetch FAILED must not have its jobs marked closed. M3-T1 rewrites
the schema underneath this; the invariant does not change.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tempfile

from jobscraper.models import RawJob
from jobscraper.store import Store

def _store(n=25):
    db = Path(tempfile.mkdtemp()) / "t.db"
    st = Store(db)
    st.sync_companies([{"ordinal": i, "name": f"C{i}", "tier": "T3",
                        "category": "Fintech", "careers_url": "https://x/careers",
                        "role_type_hint": "SWE"} for i in range(1, n + 1)])
    return st

def test_failed_fetch_must_not_close_jobs():
    """The trap: a timeout must never mass-close a company's postings."""
    st = _store(3)
    cid = st.all_companies()[0].id
    raw = RawJob(external_id="1", title="Software Engineer", url="https://x/1",
                 location="Singapore")
    jid = raw.job_id(cid, "greenhouse")
    st.upsert_job(jid, cid, raw, 1, True)
    st.commit()

    # A SUCCESSFUL fetch that omits the job closes it...
    assert st.close_missing(cid, set()) == 1
    # ...and close_missing is the only path that closes anything; runner.py calls
    # it exclusively for outcomes where ok=True. Re-seeing the job reopens it.
    st.upsert_job(jid, cid, raw, 2, False)
    st.commit()
    row = st.conn.execute(
        "SELECT closed_at FROM jobs WHERE job_id=?", (jid,)).fetchone()
    assert row[0] is None
