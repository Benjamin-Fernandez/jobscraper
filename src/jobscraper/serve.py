"""The local viewer.

A browser page opened from `file://` cannot write to your spreadsheet - that is a
browser security rule, not something to work around. So the match page is served
over loopback instead, and the Applied ticks POST back here. Each tick writes the
database and rewrites `application_tracker.xlsx` before the response returns, so
by the time the checkbox turns green the spreadsheet on disk already says so.

Bound to 127.0.0.1 only, and the Host header is checked, so nothing off this
machine can reach it - including a hostile page in another tab trying to rebind
DNS at us.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .output import sync_applied
from .store import Store

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
MAX_BODY = 64 * 1024


class ViewerState:
    """Everything the handler needs, plus the lock that serialises writes."""

    def __init__(self, db_path: Path, page: Path, tracker: Path):
        self.page = page
        self.tracker = tracker
        self.lock = threading.Lock()
        # Worker threads share one connection, guarded by self.lock.
        self.store = Store(db_path, check_same_thread=False)

    def close(self) -> None:
        self.store.close()

    def state(self) -> dict[str, Any]:
        with self.lock:
            return self.store.applied_map()

    def set_applied(self, job_id: str, applied: bool, role: str,
                    company: str, url: str) -> dict[str, Any]:
        with self.lock:
            rec = self.store.set_applied(job_id, applied, role, company, url)
            rows = sync_applied(self.tracker, self.store)
        rec["tracker_rows_changed"] = rows
        return rec


class Handler(BaseHTTPRequestHandler):
    server_version = "JobScraperViewer/1.0"
    state: ViewerState                      # injected by serve_view

    # ---------------- plumbing ----------------

    def log_message(self, fmt: str, *args) -> None:
        pass                                # the console belongs to the CLI

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                            # browser navigated away mid-write

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ---------------- routes ----------------

    def do_GET(self) -> None:               # noqa: N802
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            if not self.state.page.exists():
                self._send(404, b"No match page yet - run the scraper first.",
                           "text/plain; charset=utf-8")
                return
            self._send(200, self.state.page.read_bytes(),
                       "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(200, self.state.state())
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:              # noqa: N802
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        if self.path.split("?", 1)[0] != "/api/applied":
            self._json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "bad length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "bad length"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "bad json"})
            return

        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            self._json(400, {"error": "job_id required"})
            return

        try:
            rec = self.state.set_applied(
                job_id,
                bool(payload.get("applied")),
                str(payload.get("role") or ""),
                str(payload.get("company") or ""),
                str(payload.get("url") or ""),
            )
        except PermissionError:
            # Almost always the tracker being open in Excel holding a write lock.
            self._json(409, {"error": "tracker_locked",
                             "message": "application_tracker.xlsx is open in "
                                        "Excel - close it and tick again."})
            return
        except Exception as exc:
            self._json(500, {"error": exc.__class__.__name__,
                             "message": str(exc)[:200]})
            return

        self._json(200, {"ok": True, "job_id": job_id,
                         "applied": bool(rec.get("applied")),
                         "applied_at": rec.get("applied_at") or "",
                         "tracker_rows_changed":
                             rec.get("tracker_rows_changed", 0)})


def serve_view(db_path: Path, page: Path, tracker: Path, port: int = 8765,
               open_browser: bool = True, host: str = "127.0.0.1") -> int:
    """Serve the match page until Ctrl+C. Returns a process exit code."""
    state = ViewerState(db_path, page, tracker)
    handler = type("BoundHandler", (Handler,), {"state": state})

    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        state.close()
        print(f"cannot bind {host}:{port} - {exc}")
        print("another viewer may already be running; try --port 8766")
        return 1

    httpd.daemon_threads = True
    url = f"http://{host}:{httpd.server_port}/"
    print(f"viewer      {url}")
    print(f"page        {page}")
    print(f"tracker     {tracker}")
    print("Tick 'Applied' on a card and the tracker updates immediately.")
    print("Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nviewer stopped")
    finally:
        httpd.shutdown()
        httpd.server_close()
        state.close()
    return 0
