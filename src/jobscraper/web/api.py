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
import logging
import os
import pkgutil
import uuid
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jobscraper.config import Config, load_config
from jobscraper.web import routers
from jobscraper.web.applyqueue import ApplyQueueRunner
from jobscraper.web.connections import ModelHealth
from jobscraper.web.jobs import CommandBuilder, JobManager, cli_command
from jobscraper.web.mailsync import MailCommand, MailSyncRunner, cli_mail_command

STATIC_DIR = Path(__file__).resolve().parent / "static"

log = logging.getLogger(__name__)


class SpaFiles(StaticFiles):
    """The built UI, with caching that survives an update.

    The entry page (`index.html`) names the bundle's files, which get new names
    on every build. Served with no Cache-Control, a browser may keep reusing an
    old copy of the page - and so the old app - long after an update: seen on
    2026-09-28, when the app window kept showing M16 after M17 was installed.
    So the page is `no-cache` (always revalidated: a cheap 304 when unchanged),
    and the files under `assets/`, whose content never changes under one name,
    may be kept for a year."""

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        if path.replace("\\", "/").startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

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


class SecurityHeaders:
    """Headers on every response that stop another site framing the app.

    Since M11 the UI has buttons that start runs and upload a resume. A page
    that framed it could trick a click into one (clickjacking), and those
    requests would be same-origin, so no Host or Origin check would catch them.
    """

    HEADERS = [(b"x-frame-options", b"DENY"),
               (b"content-security-policy", b"frame-ancestors 'none'"),
               (b"x-content-type-options", b"nosniff")]

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in self.HEADERS if k not in names]
            await send(message)

        await self.app(scope, receive, with_headers)


class UnhandledErrors:
    """An error no route handled: logged with a request id, answered in the
    app's error shape (C-6).

    Before, such an error was a bare 500 and nothing was recorded anywhere.
    Now the log gets the traceback, the method, the path and an id, and the
    browser gets `{"detail", "request_id"}` - the id to quote, never the
    exception text. A middleware, not `add_exception_handler`: Starlette
    re-raises after its handler answers, which would log every error twice.
    If the response had already started, the error is logged and re-raised:
    there is no clean answer left to give.
    """

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watch(message: dict) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watch)
        except Exception:
            request_id = uuid.uuid4().hex[:12]
            log.exception("unhandled error on %s %s [request %s]",
                          scope.get("method"), scope.get("path"), request_id)
            if started:
                raise
            response = JSONResponse(
                {"detail": "Something went wrong on the server. It has been logged.",
                 "request_id": request_id}, status_code=500)
            await response(scope, receive, send)


def create_app(cfg: Optional[Config] = None,
               store_factory: Optional[Callable[[], Any]] = None,
               static_dir: Path = STATIC_DIR,
               allowed_hosts: Optional[list[str]] = None,
               job_command: Optional[CommandBuilder] = None,
               config_path: Optional[str | os.PathLike] = None,
               mail_timer: bool = False,
               mail_command: Optional[MailCommand] = None,
               apply_queue_worker: bool = False) -> FastAPI:
    """Build the app. Every argument has a production default.

    `allowed_hosts` defaults to `web.allowed_hosts` in config.yaml, else the
    loopback names - extend it only if you deliberately serve under another name.

    `job_command` builds the argv of a background job (M11-T3); the default is
    the CLI itself, given `--config config_path` when that is set. Without it
    the child finds its config as this process did (`JOBSCRAPER_CONFIG`, which
    it inherits, else `config/config.yaml`). Jobs log under `data/jobs/`, beside
    the database.

    `app.state.mail` is the F-50 `MailSyncRunner` (mail_status_design §10.1).
    Its timer runs only with `mail_timer=True`, which `cmd_web` passes unless
    `JOBSCRAPER_MAIL_SYNC=0`: tests and dev instances never read a mailbox by
    themselves. `mail_command` builds the sync / connect children (default: the
    `mail` CLI verbs), so tests stub them.

    `app.state.model_health` is the Q-100 `ModelHealth` cache behind
    `/api/connections` (q100_ui_design §3.3); tests may replace it.

    `app.state.apply_queue` is the Q-120 `ApplyQueueRunner` (apply_queue_design
    §3.4). It starts the auto-apply worker only with `apply_queue_worker=True`,
    which `cmd_web` passes per `applyqueue.apply_queue_wanted(os.environ)`: tests
    and the default never start a worker and run no tick (review H1), and a
    disabled app still records clicks but shows the queue as `disabled` (H2). The
    runner looks `app.state.jobs` and `app.state.store_factory` up at every kick,
    so a fake swapped in after this returns is the only manager it can reach.
    """
    cfg = cfg or load_config()
    app = FastAPI(title="JobScraper", version="2")
    hosts = allowed_hosts or list(cfg.web.get("allowed_hosts") or DEFAULT_ALLOWED_HOSTS)
    # Added last runs first: the Host check wraps the cross-site check.
    app.add_middleware(CrossSiteWriteGuard, hosts=hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.add_middleware(UnhandledErrors)          # its 500 still gets the headers below
    app.add_middleware(SecurityHeaders)          # outermost: every response
    app.state.cfg = cfg
    app.state.store_factory = store_factory or _default_store_factory(cfg)
    app.state.jobs = JobManager(cfg.db_path.parent / "jobs",
                                job_command or cli_command(config_path),
                                store_factory=app.state.store_factory)
    app.state.mail = MailSyncRunner(cfg, cfg.db_path.parent, app.state.store_factory,
                                    app.state.jobs,
                                    mail_command or cli_mail_command(config_path))
    # Q-100 §3.3: the hub's cached model check. Its probe runs on a daemon thread,
    # so no request ever waits on Ollama.
    app.state.model_health = ModelHealth(lambda: cfg.budget)
    app.state.apply_queue = ApplyQueueRunner(app.state, enabled=apply_queue_worker)
    if apply_queue_worker:
        # M2: the restart pause first; the tick only after it (Starlette runs
        # startup handlers in registration order). Disabled: neither runs.
        # Names differ from the mail runner's (`start_timer`, `stop`): pins tell
        # the two apart by handler `__name__`.
        app.router.add_event_handler("startup", app.state.apply_queue.pause_apply_queue_on_startup)
        app.router.add_event_handler("startup", app.state.apply_queue.start_apply_queue)
        app.router.add_event_handler("shutdown", app.state.apply_queue.stop_apply_queue)
    if mail_timer:
        app.router.add_event_handler("startup", app.state.mail.start_timer)
    app.router.add_event_handler("shutdown", app.state.mail.stop)

    # API first: the static mount below catches every path it is given, so
    # anything registered after it would be unreachable.
    _include_routers(app)

    if (static_dir / "index.html").is_file():
        app.mount("/", SpaFiles(directory=static_dir, html=True), name="spa")
    else:
        @app.get("/", response_class=PlainTextResponse, include_in_schema=False)
        def unbuilt() -> str:
            return UNBUILT_HINT

    return app
