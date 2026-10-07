"""`PUT|DELETE /api/dismissals/{job_id}` - "Not interested" in the Inbox (M17).

Marking a role Not interested used to hide it for the browser session only
(open question Q2), so after a restart it came back at the top as new. It is
now stored: the shortlist carries `dismissed_at`, and the Inbox lists those
roles in their own section at the bottom. DELETE moves one back.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Request

from jobscraper.web.deps import open_store

router = APIRouter(tags=["dismissals"])

JOB_ID = Path(..., pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


@router.put("/dismissals/{job_id}")
def dismiss(request: Request, job_id: str = JOB_ID) -> dict[str, Any]:
    """Mark a role Not interested. Idempotent: the first time is kept."""
    with open_store(request) as store:
        at = store.dismiss(job_id)
    return {"job_id": job_id, "dismissed_at": at}


@router.delete("/dismissals/{job_id}")
def undismiss(request: Request, job_id: str = JOB_ID) -> dict[str, Any]:
    """Move a role back to the Inbox's new roles. `removed` is false when it
    was not marked."""
    with open_store(request) as store:
        removed = store.undismiss(job_id)
    return {"job_id": job_id, "removed": removed}
