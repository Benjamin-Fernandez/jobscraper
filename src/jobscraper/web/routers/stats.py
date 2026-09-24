"""`GET /api/stats` - counts per status and per run (PRD 8.5).

Deliberately small: it exists so a future Stats tab has an endpoint to grow
into. It also serves the configured status vocabulary, in order, so the UI
never hardcodes a list that config can change (M8-T2).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Request

from jobscraper.config import Config
from jobscraper.web.data import load_shortlist
from jobscraper.web.deps import get_config, open_store

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(request: Request,
              cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """`statuses` (ordered vocabulary), `by_status`, `by_run` (shortlisted jobs)."""
    shortlist = load_shortlist(cfg.shortlist_path)
    with open_store(request) as store:
        counts = Counter(dict(r)["status"] for r in store.applications())
    statuses = cfg.application_statuses
    by_status = {s: counts.get(s, 0) for s in statuses}
    # A status config no longer lists still gets counted, not silently lost.
    by_status.update({s: n for s, n in counts.items() if s not in by_status})
    by_run = Counter(str(j["run_no"]) for j in shortlist["jobs"] if "run_no" in j)
    return {"statuses": statuses, "by_status": by_status,
            "by_run": dict(sorted(by_run.items(), key=lambda kv: -int(kv[0])))}
