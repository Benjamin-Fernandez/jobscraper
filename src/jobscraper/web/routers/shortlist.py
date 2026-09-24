"""`GET /api/shortlist?run=latest|<n>|all` - the Inbox's data (PRD 8.5).

One endpoint for every run is the point: the run selector swaps the dataset in
place with a single request instead of navigating to another page (M7-T2).
Each job carries its application status, joined at read time (D-5); a job the
user has not touched still appears, with `status: null`.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from jobscraper.config import Config
from jobscraper.web.data import (jobs_for, load_shortlist, resolve_run,
                                 status_map, with_status)
from jobscraper.web.deps import get_config, open_store

router = APIRouter(tags=["shortlist"])


@router.get("/shortlist")
def get_shortlist(
        request: Request,
        run: str = Query("latest", pattern=r"^(latest|all|\d+)$",
                         description="a run number, `latest` or `all`"),
        cfg: Config = Depends(get_config)) -> list[dict[str, Any]]:
    """Jobs for the run, with status. An unknown run is an empty list."""
    shortlist = load_shortlist(cfg.shortlist_path)
    jobs = jobs_for(shortlist, resolve_run(shortlist, run))
    if not jobs:
        return []
    with open_store(request) as store:
        statuses = status_map(store.applications())
    return with_status(jobs, statuses)
