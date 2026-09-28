"""`GET /api/postings/{job_id}` - one posting's full description (M16).

The Inbox's detail pane shows the job scope the way LinkedIn does: the
description as the employer wrote it. The shortlist file carries only the short
fields a card needs, so the description is fetched here, one posting at a time,
when a role is opened - from the `jobs` table, where the scrape stored it as
plain text.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request

from jobscraper.web.deps import open_store

router = APIRouter(tags=["postings"])

JOB_ID = Path(..., pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


@router.get("/postings/{job_id}")
def get_posting(request: Request, job_id: str = JOB_ID) -> dict[str, Any]:
    """The posting as stored: `description` is '' when the board gave none."""
    with open_store(request) as store:
        job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no posting {job_id!r}")
    return {"job_id": job_id, "title": job.get("title"), "company": job.get("company"),
            "location": job.get("location"), "posted_at": job.get("posted_at"),
            "url": job.get("url"), "description": _clean(job.get("jd_text"))}


def _clean(text) -> str:
    """Some boards send text whose dashes were mis-decoded upstream; show them
    as a dash rather than the replacement character."""
    return (text or "").replace("\ufffd", "\u2013").strip()
