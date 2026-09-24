"""`/api/applications` - the user's own record: what they applied to, and when.

This is the only data the web app writes, and it goes to the store alone. The
shortlist is engine-owned and regenerated freely, so it must never hold user
state (D-5).

`POST` is idempotent by construction: the store appends an `app_events` row only
when the status actually changes, so re-sending "applied" (a double click, a
retried request) cannot put a duplicate into the history (M6-T2).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from jobscraper.config import Config
from jobscraper.web.data import load_shortlist
from jobscraper.web.deps import get_config, open_store

router = APIRouter(tags=["applications"])

# Shortlist ids are short hashes; anything else in the path is a mistake.
JOB_ID = Path(..., pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


class StatusChange(BaseModel):
    """Body of `POST /api/applications/{job_id}`.

    `company`, `role` and `url` are optional. When given, they are kept on the
    application row, so the record still describes the job after the posting
    has left the shortlist or the jobs table.
    """
    status: str = Field(..., min_length=1, max_length=40)
    notes: Optional[str] = Field(None, max_length=4000)
    company: Optional[str] = Field(None, max_length=200)
    role: Optional[str] = Field(None, max_length=300)
    url: Optional[str] = Field(None, max_length=2000)


@router.get("/applications")
def list_applications(request: Request,
                      cfg: Config = Depends(get_config)) -> list[dict[str, Any]]:
    """Everything with a status, newest change first, each with its timeline.

    `events` is the row's `app_events` history, oldest first - what the
    Applications tab draws (M8-T1). Where the store has no description of a job,
    the shortlist fills it in.
    """
    by_id = {str(j.get("id")): j for j in load_shortlist(cfg.shortlist_path)["jobs"]}
    with open_store(request) as store:
        rows = [dict(r) for r in store.applications()]
        for row in rows:
            row["events"] = [dict(e) for e in store.application_events(row["job_id"])]
    for row in rows:
        job = by_id.get(str(row["job_id"]), {})
        row["company"] = row.get("company") or job.get("company")
        row["role"] = row.get("role") or job.get("title")
        row["url"] = row.get("url") or job.get("url")
        row["run_no"] = job.get("run_no")
    return rows


@router.post("/applications/{job_id}")
def set_status(body: StatusChange, request: Request, job_id: str = JOB_ID,
               cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Upsert the application and append to its history on a real change."""
    allowed = cfg.application_statuses
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status {body.status!r}; expected one of {allowed}")
    with open_store(request) as store:
        appended = store.set_application_status(
            job_id, body.status, body.notes,
            company=body.company, role=body.role, url=body.url)
        application = store.application(job_id)
    return {"job_id": job_id, "status": body.status,
            "event_appended": bool(appended), "application": application}
