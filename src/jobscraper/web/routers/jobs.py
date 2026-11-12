"""`/api/jobs/*` - start a run or a profile refresh, watch it, stop it (M11-T3).

The Runs tab drives the engine through these four routes and nothing else. The
work itself happens in a child process running the CLI (see `web/jobs.py`), so
the web app never imports the pipeline and a crashed run is just a `failed` job.

A run's batch size is resolved here - the request's, else the stored setting,
else config - and passed to the CLI as `--batch-size`, so the log header shows
exactly what ran.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from jobscraper.apply.contracts import QueuePause
from jobscraper.config import Config
from jobscraper.store import utcnow
from jobscraper.web.applyqueue import slot_of
from jobscraper.web.control import effective_batch_size
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.jobs import JobBusy, JobIdle, JobManager, JobNotOurs, JobStuck

router = APIRouter(tags=["jobs"])
log = logging.getLogger(__name__)

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
    """Start `jobscraper run`. While the auto-apply worker runs: 202 `{job: <the
    apply job>, deferred: true}` (Q-120 §3.5); any other running job: `409`."""
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
    opts = {"batch_size": batch, "dry_run": body.dry_run}
    # Q-120 §6: while the auto-apply worker holds the slot, the run waits its turn.
    # The worker finishes the current role and yields (no pause); the runner then
    # starts this run and the queue goes on after it. Other busy kinds: 409.
    runner = getattr(request.app.state, "apply_queue", None)
    slot, cur = slot_of(jobs)
    if slot == "apply" and runner is not None and runner.enabled:
        runner.defer_run(opts)
        with open_store(request) as store:
            store.queue_request_yield()
        return {"job": cur, "deferred": True}
    return _start(jobs, "run", opts)


@router.post("/jobs/profile", status_code=202)
def start_profile(jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Re-derive the profile from the stored resume; `409` if busy."""
    return _start(jobs, "profile", {})


@router.post("/jobs/titles", status_code=202)
def start_titles(jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Ask Qwen for job-title recommendations (M15); `409` if busy. The result
    is stored and served by `GET /api/titles`."""
    return _start(jobs, "titles", {})


@router.post("/jobs/companies", status_code=202)
def start_companies(jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Search the user's uploaded list for careers sites (M16); `409` if busy.
    Progress is written per company and served by `GET /api/companies/list`."""
    return _start(jobs, "companies", {})


@router.get("/jobs/current")
def current_job(tail: int = TAIL,
                jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """The running job, else the last one, else `state: idle`; with its log tail."""
    return jobs.current(tail)


@router.post("/jobs/cancel")
def cancel_job(request: Request, jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    """Stop the running job; `409` if there is none, `500` if it will not die.

    The auto-apply worker (Q-120, review M3): the queue's `cancelled` pause is
    committed before the signal, so neither the worker (its take honours the
    pause) nor the runner's tick goes on to the next role. If that write fails,
    the runner's restart gate closes for this process instead (fail closed)."""
    slot, _cur = slot_of(jobs)
    if slot == "apply":
        try:
            with open_store(request) as store:
                store.queue_pause(QueuePause.CANCELLED, None, utcnow())
        except Exception:                   # noqa: BLE001 - the owner's Cancel still goes
            log.exception("could not pause the auto-apply queue before the cancel")
            runner = getattr(request.app.state, "apply_queue", None)
            if runner is not None:
                runner.close_gate()
    try:
        return jobs.cancel()
    except (JobIdle, JobNotOurs) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JobStuck as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
