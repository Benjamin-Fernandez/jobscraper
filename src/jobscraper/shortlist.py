"""Publish the accepted roles as a file the web app can read.

`data/shortlist.json` is regenerated from the database on every run and is safe
to delete. It carries no application status: that belongs in the database,
because a file the engine rewrites is the wrong place to keep something the user
typed.

This module is a publisher, not a pipeline stage - it is the one module that both
the pipeline and the web app may import.

See PRD sections 8.3[6] and 8.2.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .store import Store, utcnow

VERSION = 1


def build(store: Store, profile_version: int, now: Optional[str] = None,
          rules_hash: Optional[str] = None) -> dict[str, Any]:
    """The shortlist document, in a deterministic order (M5-T1).

    jobs: (run_no DESC, company ASC, id ASC); runs: run_no DESC. A job whose
    posting has since closed stays, flagged `closed: true`, so a role you were
    about to apply to does not vanish without explanation (Q4). With
    `rules_hash`, only roles that still pass the current rules are listed.
    """
    rows = store.accepted_jobs(profile_version, rules_hash=rules_hash)
    jobs = []
    for r in rows:
        job = {"id": r["job_id"], "run_no": r["run_no"], "company": r["company"],
               "title": r["title"], "url": r["url"], "location": r["location"],
               "posted_at": r["posted_at"] or None, "yoe_min": r["yoe_min"],
               "reason": r["reason"], "decided_at": r["decided_at"]}
        if r["closed_at"]:
            job["closed"] = True
        jobs.append(job)
    jobs.sort(key=lambda j: (-(j["run_no"] or 0), (j["company"] or "").lower(), j["id"]))

    accepted: dict[int, int] = {}
    for j in jobs:
        accepted[j["run_no"]] = accepted.get(j["run_no"], 0) + 1
    runs = [{"run_no": r["run_no"], "finished_at": r["finished_at"],
             "accepted": accepted.get(r["run_no"], 0)}
            for r in store.list_runs() if r["status"] == "ok"]
    return {"version": VERSION, "generated_at": now or utcnow(),
            "profile_version": profile_version, "runs": runs, "jobs": jobs}


def write(store: Store, path: Path, profile_version: int,
          now: Optional[str] = None,
          rules_hash: Optional[str] = None) -> dict[str, Any]:
    """Regenerate the file atomically: the web app never reads half a shortlist."""
    doc = build(store, profile_version, now=now, rules_hash=rules_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return doc
