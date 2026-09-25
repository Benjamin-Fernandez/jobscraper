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
import os
import pkgutil
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jobscraper.config import Config, load_config
from jobscraper.web import routers
from jobscraper.web.jobs import CommandBuilder, JobManager, cli_command

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

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _host_allowed(host: Optional[str], hosts: list[str]) -> bool:
    """`host` against the allowed list, with TrustedHost's `*` / `*.x` forms."""
    if not host:
        return False
    host = host.lower()
    for pattern in hosts:
        pattern = pattern.lower()
        if pattern == "*" or pattern == host:
            return True
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
    return False


class CrossSiteWriteGuard:
    """Refuse a write to `/api` that a browser says came from another site.

    The Host check stops DNS rebinding, but not a plain cross-site request: a
    page anywhere on the web can make the user's browser POST a form to
    http://127.0.0.1:8765 with no CORS preflight, and its Host header is ours.
    Since M11 such a request could start a run or a model call. Browsers mark
    it: `Origin` names the other site (or is "null"), `Sec-Fetch-Site` says
    "cross-site". Either one gets a 403. Requests with neither - curl, the
    CLI, tests - are not from a browser page and pass. The origin's port is
    ignored, so the Vite dev server's proxy (localhost:5173) still works.
    """

    def __init__(self, app: Any, hosts: list[str]):
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if (scope["type"] == "http" and scope["method"] in UNSAFE_METHODS
                and scope["path"].startswith("/api/") and self._cross_site(scope)):
            response = PlainTextResponse("cross-site request refused", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _cross_site(self, scope: dict) -> bool:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        if headers.get("sec-fetch-site", "").lower() == "cross-site":
            return True
        origin = headers.get("origin")
        if origin is None:
            return False
        try:
            host = urlsplit(origin.strip()).hostname
        except ValueError:
            return True
        return not _host_allowed(host, self.hosts)


def create_app(cfg: Optional[Config] = None,
               store_factory: Optional[Callable[[], Any]] = None,
               static_dir: Path = STATIC_DIR,
               allowed_hosts: Optional[list[str]] = None,
               job_command: Optional[CommandBuilder] = None,
               config_path: Optional[str | os.PathLike] = None) -> FastAPI:
    """Build the app. Every argument has a production default.

    `allowed_hosts` defaults to `web.allowed_hosts` in config.yaml, else the
    loopback names - extend it only if you deliberately serve under another name.

    `job_command` builds the argv of a background job (M11-T3); the default is
    the CLI itself, given `--config config_path` when that is set. Without it
    the child finds its config as this process did (`JOBSCRAPER_CONFIG`, which
    it inherits, else `config/config.yaml`). Jobs log under `data/jobs/`, beside
    the database.
    """
    cfg = cfg or load_config()
    app = FastAPI(title="JobScraper", version="2")
    hosts = allowed_hosts or list(cfg.web.get("allowed_hosts") or DEFAULT_ALLOWED_HOSTS)
    # Added last runs first: the Host check wraps the cross-site check.
    app.add_middleware(CrossSiteWriteGuard, hosts=hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.state.cfg = cfg
    app.state.store_factory = store_factory or _default_store_factory(cfg)
    app.state.jobs = JobManager(cfg.db_path.parent / "jobs",
                                job_command or cli_command(config_path))

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
