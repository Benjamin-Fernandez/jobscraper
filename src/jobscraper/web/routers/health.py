"""`GET /api/healthz` - is the app up and can it read its database (C-6).

For a monitor or a quick check from a shell: 200 `{"status": "ok"}`, or 503
`{"status": "unavailable"}` when the database cannot be read. The reason goes
to the log, never to the caller. It carries no data. Not to be confused with
`/api/companies/health`, which is data - every watched company's scan state.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from jobscraper.web.deps import open_store

router = APIRouter(tags=["health"])

log = logging.getLogger(__name__)


@router.get("/healthz")
def healthz(request: Request) -> JSONResponse:
    """200 when the database reads, 503 when it does not."""
    try:
        with open_store(request) as store:
            store.ping()
    except Exception:
        log.exception("health check: the database cannot be read")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
