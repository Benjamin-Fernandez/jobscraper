"""What a request handler needs, handed over by FastAPI instead of imported.

Routers never construct a `Store` or load config themselves. They ask for them
here, and `create_app` decides what they get: the real store in production, a
fake in `tests/test_web.py`. That seam is why the whole API is testable without
a database.

The store is opened per request, inside the handler, by `open_store`, and
closed when the handler is done. One connection per request means no connection
is ever shared by two requests running at once on FastAPI's thread pool.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Request

from jobscraper.config import Config


def get_config(request: Request) -> Config:
    return request.app.state.cfg


def get_jobs(request: Request) -> Any:
    """The app's one `JobManager` (web/jobs.py), built by `create_app`."""
    return request.app.state.jobs


@contextmanager
def open_store(request: Request) -> Iterator[Any]:
    """Yield a store for this request and close it afterwards."""
    store = request.app.state.store_factory()
    try:
        yield store
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()
