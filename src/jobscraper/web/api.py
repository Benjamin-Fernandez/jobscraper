"""The web app: the API routers plus the built single-page UI, in one process.

Everything the browser sees comes from here - `/api/*` for data and `/` for the
Vue bundle Vite writes into `static/`. The bundle is committed, so this runs
from a plain Python checkout with no node toolchain present (PRD M10-T3).

`create_app` takes its collaborators as arguments instead of reaching for
globals, so tests can hand it a fixture shortlist and a fake store and exercise
the real routes with no database on disk.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from jobscraper.config import Config, load_config
from jobscraper.web import routers

STATIC_DIR = Path(__file__).resolve().parent / "static"

UNBUILT_HINT = ("The web UI has not been built.\n"
                "  cd web\n  npm install\n  npm run build\n"
                "See web/README.md.\n")


def _default_store_factory(cfg: Config) -> Callable[[], Any]:
    """Open the real store on demand - one connection per request.

    Opened inside the request's worker thread rather than shared, because a
    SQLite connection may not cross threads and FastAPI runs sync endpoints on
    a thread pool.
    """
    def factory() -> Any:
        from jobscraper.store import Store
        return Store(cfg.db_path)
    return factory


def _include_routers(app: FastAPI) -> None:
    """Mount every `router` found in `web/routers/` under `/api`."""
    for info in sorted(pkgutil.iter_modules(routers.__path__),
                       key=lambda i: i.name):
        module = importlib.import_module(f"{routers.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router, prefix="/api")


def create_app(cfg: Optional[Config] = None,
               store_factory: Optional[Callable[[], Any]] = None,
               static_dir: Path = STATIC_DIR) -> FastAPI:
    """Build the app. Every argument has a production default."""
    cfg = cfg or load_config()
    app = FastAPI(title="JobScraper", version="2")
    app.state.cfg = cfg
    app.state.store_factory = store_factory or _default_store_factory(cfg)

    # API first: the static mount below catches every path it is given, so
    # anything registered after it would be unreachable.
    _include_routers(app)

    if (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    else:
        @app.get("/", response_class=PlainTextResponse, include_in_schema=False)
        def unbuilt() -> str:
            return UNBUILT_HINT

    return app
