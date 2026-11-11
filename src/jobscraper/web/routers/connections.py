"""`/api/connections` - the Connected accounts hub (Q-100, q100_ui_design §3).

`GET /api/connections` is read-only and fast. It reads the store, asks the vault
yes-or-no questions (local Credential Manager reads, no network), and takes the
mail runner's and the job slot's status as they are. It never opens IMAP, never
starts a sync, and never waits on the model: the model item comes from the
cached `ModelHealth` snapshot, whose probe runs on its own thread (§3.3). No vault
value, nor anything derived from one, is ever in the body (ADR-0009, D-191), and
no path: the Edge profile's holds the Windows user name. All mapping lives in
`web/connections.py`.

`POST /api/connections/model/check` is the hub's "Check again": a forced
background probe, answered 202 at once. It writes nothing, but it is a POST, so
`CrossSiteWriteGuard` refuses it from another site like every other `/api` write.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from jobscraper import vault
from jobscraper.store import utcnow
from jobscraper.web.connections import ModelHealth, compose, lockfile_busy

router = APIRouter(tags=["connections"])

log = logging.getLogger(__name__)

NO_STORE = {"Cache-Control": "no-store"}


def _vault_has(service: str, username: str) -> bool:
    """Is there a vault entry? The value is dropped at once; only the boolean
    leaves this function. A VaultError propagates: compose turns it into
    `check_failed` with fixed copy."""
    return vault.get(service, username) is not None


def _model_health(request: Request) -> ModelHealth:
    """`app.state.model_health` (made by `create_app`); built here for an app
    that was assembled without it."""
    state = request.app.state
    mh = getattr(state, "model_health", None)
    if mh is None:
        cfg = state.cfg
        mh = state.model_health = ModelHealth(lambda: cfg.budget)
    return mh


def _runner_view(request: Request) -> dict[str, Any]:
    """The mail runner's status calls only: never a sync, a connect or IMAP."""
    runner = getattr(request.app.state, "mail", None)
    if runner is None:
        return {"timer_running": False, "running": False, "started_at": None,
                "next_at": None}
    try:
        return {"timer_running": bool(runner.timer_running), **runner.status()}
    except Exception as exc:
        log.warning("connections: mail runner status failed (%s)", type(exc).__name__)
        return {"timer_running": bool(getattr(runner, "timer_running", False)),
                "running": False, "started_at": None, "next_at": None}


def _job_view(request: Request) -> dict[str, Any]:
    jobs = getattr(request.app.state, "jobs", None)
    if jobs is None:
        return {"state": "idle", "kind": None}
    try:
        return jobs.current(tail=0)
    except Exception as exc:
        log.warning("connections: job slot status failed (%s)", type(exc).__name__)
        return {"state": "idle", "kind": None}


@router.get("/connections")
def get_connections(request: Request) -> JSONResponse:
    """Schema v1 (§3.1). 503 `{code: "unavailable"}` when the store can't be
    opened, like `/api/healthz`; any other failing source degrades its own item."""
    snapshot = _model_health(request).snapshot()
    try:
        store = request.app.state.store_factory()
    except Exception:
        log.exception("connections: the database cannot be opened")
        return JSONResponse({"code": "unavailable"}, status_code=503, headers=NO_STORE)
    try:
        body = compose(request.app.state.cfg, store, _runner_view(request),
                       _job_view(request), snapshot, _vault_has, lockfile_busy, utcnow())
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()
    return JSONResponse(body, headers=NO_STORE)


@router.post("/connections/model/check", status_code=202)
def check_model(request: Request) -> JSONResponse:
    """Start a fresh model probe now (unless one is running) and return at once;
    the hub polls GET for the answer."""
    snap = _model_health(request).snapshot(force=True)
    return JSONResponse({"checking": bool(snap.get("in_flight"))}, status_code=202,
                        headers=NO_STORE)
