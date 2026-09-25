"""`GET /api/runs` - the list behind the run selector (PRD 8.5).

The selector is the replacement for v1's one-HTML-file-per-run: pick a run and
the same page shows it. Runs come from the store (every batch, including ones
that accepted nothing) merged with the shortlist's own per-run accepted counts,
so a run with zero roles still appears and says so.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from jobscraper.config import Config
from jobscraper.web.data import load_shortlist
from jobscraper.web.deps import get_config, open_store

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(request: Request,
              cfg: Config = Depends(get_config)) -> list[dict[str, Any]]:
    """Newest first: `run_no`, `started_at`, `finished_at`, `status`,
    `accepted`, and the run's `stats` (companies_due, postings_seen, ... -
    what the Runs tab's history table shows)."""
    shortlist = load_shortlist(cfg.shortlist_path)
    with open_store(request) as store:
        stored = [dict(r) for r in store.list_runs()]

    runs: dict[int, dict[str, Any]] = {}
    for row in stored:
        n = int(row["run_no"])
        runs[n] = {"run_no": n, "started_at": row.get("started_at"),
                   "finished_at": row.get("finished_at"),
                   "status": row.get("status"), "accepted": None,
                   "stats": row.get("stats") or {}}
    for row in shortlist["runs"]:
        n = int(row["run_no"])
        entry = runs.setdefault(n, {"run_no": n, "started_at": None,
                                    "finished_at": None, "status": None,
                                    "accepted": None, "stats": {}})
        entry["finished_at"] = entry["finished_at"] or row.get("finished_at")
        entry["accepted"] = row.get("accepted")

    # A run the shortlist does not summarise: count its jobs directly.
    for entry in runs.values():
        if entry["accepted"] is None:
            entry["accepted"] = sum(1 for j in shortlist["jobs"]
                                    if j.get("run_no") == entry["run_no"])
    return sorted(runs.values(), key=lambda r: r["run_no"], reverse=True)
