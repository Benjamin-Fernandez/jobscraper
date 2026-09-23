"""HTTP layer: per-host rate limiting, robots.txt, typed errors, bounded retry.

Every network failure is classified (see models.py). The class decides whether the
call is retried in-run and whether it counts toward quarantine.
"""
from __future__ import annotations

import random
import threading
import time
import urllib.robotparser
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .models import BLOCKED, GONE, RETRYABLE, SCHEMA, TRANSIENT, UNKNOWN


# Public ATS JSON APIs. robots.txt on these hosts targets crawlers walking the
# HTML job boards; the API endpoints are published for programmatic access.
ATS_API_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
    "api.smartrecruiters.com",
    "apply.workable.com",
}


class FetchError(Exception):
    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status

    def __str__(self) -> str:
        return f"[{self.kind}] {self.message}"


def classify_status(status: int) -> str:
    if status in (403, 401, 451):
        return BLOCKED
    if status in (404, 410):
        return GONE
    if status == 429 or 500 <= status < 600:
        return TRANSIENT
    if 400 <= status < 500:
        return SCHEMA
    return UNKNOWN


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError,
                        httpx.ReadError, httpx.RemoteProtocolError,
                        httpx.WriteError, httpx.PoolTimeout)):
        return TRANSIENT
    if isinstance(exc, httpx.TooManyRedirects):
        return SCHEMA
    return UNKNOWN


class HttpClient:
    """Shared client. Thread-safe: per-host locks serialize pacing, not requests."""

    def __init__(self, user_agent: str, timeout: float = 25.0,
                 delay: float = 0.7, max_retries: int = 3,
                 respect_robots: bool = True):
        self.delay = delay
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-SG,en;q=0.9",
            },
        )
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    # -------- pacing --------

    def _host_lock(self, host: str) -> threading.Lock:
        with self._guard:
            if host not in self._locks:
                self._locks[host] = threading.Lock()
            return self._locks[host]

    def _pace(self, host: str) -> None:
        lock = self._host_lock(host)
        with lock:
            prev = self._last.get(host, 0.0)
            wait = self.delay - (time.monotonic() - prev)
            if wait > 0:
                time.sleep(wait + random.uniform(0, 0.15))
            self._last[host] = time.monotonic()

    # -------- robots --------

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        if parts.netloc.lower() in ATS_API_HOSTS:
            # Documented public job-board APIs. Their robots.txt governs web
            # crawlers, not the JSON endpoints companies publish deliberately
            # for exactly this purpose. Rate limiting still applies.
            return True
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp: Optional[urllib.robotparser.RobotFileParser]
            try:
                resp = self._client.get(f"{host}/robots.txt", timeout=8.0)
                if resp.status_code == 200 and len(resp.text) < 500_000:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(resp.text.splitlines())
                else:
                    rp = None
            except Exception:
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True

    # -------- requests --------

    def request(self, method: str, url: str, *, expect: str = "any",
                check_robots: bool = True, **kw: Any) -> httpx.Response:
        """Perform a request with pacing and bounded retry.

        `expect`: "json" | "html" | "any" — controls the schema check.
        Raises FetchError on any failure.
        """
        if check_robots and not self.allowed(url):
            raise FetchError(BLOCKED, f"robots.txt disallows {url}")

        host = urlparse(url).netloc
        last: Optional[FetchError] = None

        for attempt in range(self.max_retries):
            self._pace(host)
            try:
                resp = self._client.request(method, url, **kw)
            except Exception as exc:  # network-level
                kind = classify_exception(exc)
                last = FetchError(kind, f"{type(exc).__name__}: {exc}")
                if kind in RETRYABLE and attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.5))
                    continue
                raise last

            if resp.status_code >= 400:
                kind = classify_status(resp.status_code)
                last = FetchError(kind, f"HTTP {resp.status_code} for {url}",
                                  resp.status_code)
                retriable = kind in RETRYABLE and attempt < self.max_retries - 1
                if retriable:
                    backoff = min(2 ** attempt, 8)
                    ra = resp.headers.get("Retry-After")
                    if ra:
                        try:
                            backoff = max(backoff, min(float(ra), 30.0))
                        except ValueError:
                            pass
                    time.sleep(backoff + random.uniform(0, 0.5))
                    continue
                raise last

            if expect == "json":
                ctype = resp.headers.get("content-type", "")
                if "json" not in ctype.lower():
                    # Some ATS endpoints serve JSON as text/plain; try parsing anyway.
                    try:
                        resp.json()
                    except Exception:
                        raise FetchError(
                            SCHEMA,
                            f"expected JSON, got {ctype or 'unknown'} for {url}",
                            resp.status_code)
            return resp

        raise last or FetchError(UNKNOWN, f"request failed for {url}")

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("POST", url, **kw)

    def get_json(self, url: str, **kw: Any) -> Any:
        resp = self.request("GET", url, expect="json", **kw)
        try:
            return resp.json()
        except Exception as exc:
            raise FetchError(SCHEMA, f"malformed JSON from {url}: {exc}",
                             resp.status_code)

    def post_json(self, url: str, **kw: Any) -> Any:
        resp = self.request("POST", url, expect="json", **kw)
        try:
            return resp.json()
        except Exception as exc:
            raise FetchError(SCHEMA, f"malformed JSON from {url}: {exc}",
                             resp.status_code)

    def close(self) -> None:
        self._client.close()
