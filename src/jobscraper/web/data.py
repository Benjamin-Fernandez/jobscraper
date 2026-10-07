"""Reading `shortlist.json` and joining it with application status (D-5).

The engine owns `shortlist.json` and regenerates it freely; the user's status
lives only in the database. Neither is allowed to hold the other's data, so the
web app is the one place they meet - at read time, here. Keeping the join in one
module means every router agrees on what "a job with its status" looks like.

The file is re-read on every request. It is small, it changes underneath a
running server whenever a batch finishes, and a cache would serve a stale queue.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RunSelector = Union[int, str, frozenset]   # a run number, "all", or a set of runs

# `?run=week` / `month`: runs that finished within this many days (M15).
RANGES = {"week": 7, "month": 30}

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


def _finished(stamp: Any) -> Optional[_dt.datetime]:
    try:
        return _dt.datetime.fromisoformat(str(stamp)[:19])
    except (TypeError, ValueError):
        return None


def resolve_run(shortlist: Mapping[str, Any], run: str,
                now: Optional[_dt.datetime] = None) -> Optional[RunSelector]:
    """Turn the `?run=` value into what `jobs_for` filters by (M15):

    `all`; `latest` (the newest run, kept for old links); `week` / `month` (the
    runs that finished in the last 7 / 30 days, UTC); `12` or `12,14` (the runs
    the user chose). None means no runs at all.
    """
    if run == "all":
        return "all"
    if run == "latest":
        nums = run_numbers(shortlist)
        return nums[0] if nums else None
    if run in RANGES:
        now = now or _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        since = now - _dt.timedelta(days=RANGES[run])
        return frozenset(int(r["run_no"]) for r in shortlist["runs"]
                         if "run_no" in r and (_finished(r.get("finished_at")) or since) > since)
    nums = [int(x) for x in run.split(",")]
    return nums[0] if len(nums) == 1 else frozenset(nums)


def jobs_for(shortlist: Mapping[str, Any],
             run: Optional[RunSelector]) -> list[dict[str, Any]]:
    """The shortlisted jobs for one run (or all), as fresh dicts."""
    if run is None:
        return []
    if isinstance(run, frozenset):
        return [dict(j) for j in shortlist["jobs"] if j.get("run_no") in run]
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


# ---------------------------------------------------------------- one posting, two ids (M17)

def posting_key(url: Any) -> str:
    """A posting's URL compared loosely: the scheme, the host's case, a trailing
    slash, a #fragment and utm_* tracking parameters do not make it another
    posting. Anything else in the query (Greenhouse's gh_jid) does."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not k.lower().startswith("utm_")))
    return urlunsplit(("", parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def mark_tracked_twins(jobs: list[dict[str, Any]],
                       applications: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The same posting can reach the shortlist under two ids - two watched
    companies sharing one job board (Grab and Grab Financial Group) - so a role
    already applied for can come back as new. A job with no status of its own
    whose URL is that of a tracked application gets `tracked_as` (that
    application's job id and status) and the Inbox leaves it out. Only the URL
    counts as sure: two open postings with the same title at one company are
    usually separate openings, and those stay in the Inbox."""
    tracked: dict[str, dict[str, Any]] = {}
    for app in applications:
        key = posting_key(app.get("url"))
        if key:
            tracked.setdefault(key, {"job_id": app.get("job_id"), "status": app.get("status")})
    for job in jobs:
        twin = None
        if not job.get("status"):
            hit = tracked.get(posting_key(job.get("url")))
            if hit and hit["job_id"] != job.get("id"):
                twin = hit
        job["tracked_as"] = twin
    return jobs
