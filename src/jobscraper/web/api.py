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
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jobscraper.config import Config, load_config
from jobscraper.web import routers

STATIC_DIR = Path(__file__).resolve().parent / "static"

UNBUILT_HINT = ("The web UI has not been built.\n"
                "  cd web\n  npm install\n  npm run build\n"
                "See web/README.md.\n")


def _default_store_factory(cfg: Config) -> Callable[[], Any]:
    """Open the real store on demand - one connection per request.

    Nothing is opened at startup, so `/` serves even when the database is
    missing or unreadable. `check_same_thread=False` because FastAPI may create
    the connection on one pool thread and close it on another; each request
    still gets its own connection, so none is ever shared concurrently.
    """
    def factory() -> Any:
        from jobscraper.store import Store
        return Store(cfg.db_path, check_same_thread=False)
    return factory


def _include_routers(app: FastAPI) -> None:
    """Mount every `router` found in `web/routers/` under `/api`."""
    for info in sorted(pkgutil.iter_modules(routers.__path__),
                       key=lambda i: i.name):
        module = importlib.import_module(f"{routers.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router, prefix="/api")


# The only Host headers the app answers. There is no login (PRD R-9), so a page
# on another site that rebinds its own domain name to 127.0.0.1 could otherwise
# read and change the application record from the user's browser (DNS
# rebinding). Such a request carries the attacker's hostname, not one of these.
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "::1"]


def create_app(cfg: Optional[Config] = None,
               store_factory: Optional[Callable[[], Any]] = None,
               static_dir: Path = STATIC_DIR,
               allowed_hosts: Optional[list[str]] = None) -> FastAPI:
    """Build the app. Every argument has a production default.

    `allowed_hosts` defaults to `web.allowed_hosts` in config.yaml, else the
    loopback names - extend it only if you deliberately serve under another name.
    """
    cfg = cfg or load_config()
    app = FastAPI(title="JobScraper", version="2")
    hosts = allowed_hosts or list(cfg.web.get("allowed_hosts") or DEFAULT_ALLOWED_HOSTS)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
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
