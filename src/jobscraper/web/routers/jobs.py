"""`/api/jobs/*` - start a run or a profile refresh, watch it, stop it (M11-T3).

The Runs tab drives the engine through these four routes and nothing else. The
work itself happens in a child process running the CLI (see `web/jobs.py`), so
the web app never imports the pipeline and a crashed run is just a `failed` job.

A run's batch size is resolved here - the request's, else the stored setting,
else config - and passed to the CLI as `--batch-size`, so the log header shows
exactly what ran.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from jobscraper.config import Config
from jobscraper.web.control import effective_batch_size
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.jobs import JobBusy, JobIdle, JobManager, JobNotOurs

router = APIRouter(tags=["jobs"])

TAIL = Query(200, ge=0, le=5000, description="how many trailing log lines")


class RunRequest(BaseModel):
    """Body of `POST /api/jobs/run`; both fields optional, the body too."""
    batch_size: Optional[StrictInt] = Field(None, ge=1)
    dry_run: StrictBool = False


def _start(jobs: JobManager, kind: str, opts: dict[str, Any]) -> dict[str, Any]:
    try:
        return jobs.start(kind, opts)
    except JobBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        # strerror only: str(exc) carries filesystem paths.
        reason = exc.strerror or type(exc).__name__
        raise HTTPException(status_code=500,
                            detail=f"could not start the {kind}: {reason}") from exc


@router.post("/jobs/run", status_code=202)
def start_run(request: Request, body: Optional[RunRequest] = None,
              cfg: Config = Depends(get_config),
              jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Start `jobscraper run`; `409` if a job is already running."""
    body = body or RunRequest()
    with open_store(request) as store:
        enabled = int(store.stats()["enabled"])
        batch = body.batch_size or effective_batch_size(cfg, store)
    # Before the first sync there are no companies to bound against yet.
    if body.batch_size is not None and enabled and body.batch_size > enabled:
        raise HTTPException(
            status_code=422,
            detail=f"batch_size must be between 1 and {enabled} "
                   f"(the enabled companies); got {body.batch_size}")
    return _start(jobs, "run", {"batch_size": batch, "dry_run": body.dry_run})


@router.post("/jobs/profile", status_code=202)
def start_profile(jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Re-derive the profile from the stored resume; `409` if busy."""
    return _start(jobs, "profile", {})


@router.get("/jobs/current")
def current_job(tail: int = TAIL,
                jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """The running job, else the last one, else `state: idle`; with its log tail."""
    return jobs.current(tail)


@router.post("/jobs/cancel")
def cancel_job(jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Terminate the running job; `409` if there is none."""
    try:
        return jobs.cancel()
    except (JobIdle, JobNotOurs) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
