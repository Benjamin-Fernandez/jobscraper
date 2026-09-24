"""Reading `shortlist.json` and joining it with application status (D-5).

The engine owns `shortlist.json` and regenerates it freely; the user's status
lives only in the database. Neither is allowed to hold the other's data, so the
web app is the one place they meet - at read time, here. Keeping the join in one
module means every router agrees on what "a job with its status" looks like.

The file is re-read on every request. It is small, it changes underneath a
running server whenever a batch finishes, and a cache would serve a stale queue.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

RunSelector = Union[int, str]           # a run number, "latest" or "all"

# Application fields merged onto a shortlisted job. A job with no application
# row still appears, with these set to None (M6-T1).
STATUS_FIELDS = ("status", "notes", "applied_at", "updated_at")


def load_shortlist(path: Path) -> dict[str, Any]:
    """The shortlist as a dict with `runs` and `jobs` lists, never missing.

    No file yet (no batch has run, or someone deleted it - it is disposable) is
    an empty queue, not an error.
    """
    if not path.is_file():
        return {"runs": [], "jobs": []}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    data.setdefault("runs", [])
    data.setdefault("jobs", [])
    return data


def run_numbers(shortlist: Mapping[str, Any]) -> list[int]:
    """Every run the shortlist mentions, newest first."""
    nums = {int(r["run_no"]) for r in shortlist["runs"] if "run_no" in r}
    nums |= {int(j["run_no"]) for j in shortlist["jobs"] if "run_no" in j}
    return sorted(nums, reverse=True)


def resolve_run(shortlist: Mapping[str, Any], run: str) -> Optional[RunSelector]:
    """Turn the `?run=` value into a run number, "all", or None for no runs."""
    if run == "all":
        return "all"
    if run == "latest":
        nums = run_numbers(shortlist)
        return nums[0] if nums else None
    return int(run)


def jobs_for(shortlist: Mapping[str, Any],
             run: Optional[RunSelector]) -> list[dict[str, Any]]:
    """The shortlisted jobs for one run (or all), as fresh dicts."""
    if run is None:
        return []
    return [dict(j) for j in shortlist["jobs"]
            if run == "all" or j.get("run_no") == run]


def status_map(applications: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Application rows keyed by job id. Accepts dicts or sqlite3.Row."""
    out: dict[str, dict[str, Any]] = {}
    for row in applications:
        row = dict(row)
        out[str(row["job_id"])] = row
    return out


def with_status(jobs: Iterable[dict[str, Any]],
                statuses: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge each job's application fields onto it. Never drops a job."""
    out = []
    for job in jobs:
        app = statuses.get(str(job.get("id")), {})
        merged = dict(job)
        merged.setdefault("closed", False)
        for field in STATUS_FIELDS:
            merged[field] = app.get(field)
        out.append(merged)
    return out
