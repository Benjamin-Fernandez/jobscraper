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

from ..models import BLOCKED, GONE, RETRYABLE, SCHEMA, TRANSIENT, UNKNOWN


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
    def __init__(self, kind: str, message: str, status: Optional[int] = None,
                 signature: str = ""):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        # A bot-wall signature (C-8), set only when `detect_block` recognised
        # one; "" for an ordinary HTTP error. It is also written into the
        # message ("HTTP 403 (cloudflare) for ..."), which is what the
        # companies table keeps as `last_error`.
        self.signature = signature

    def __str__(self) -> str:
        return f"[{self.kind}] {self.message}"


# ---------------------------------------------------------------- block signatures
#
# A board that bot-walls us must be told apart from a real 403 or a board that
# moved. These markers are the small, well-known tells of the vendors that do it
# at scale; anything else is reported as a plain HTTP error with no signature.

_CAPTCHA_MARKERS = ("captcha",)                      # covers recaptcha, hcaptcha
_CLOUDFLARE_BODY_MARKERS = (
    "just a moment", "attention required! | cloudflare", "cf-chl")
_AKAMAI_CONFIRM_MARKERS = ("reference #", "errors.edgesuite.net")

# `cf-ray` and `server: ...` are present on almost every response a CDN
# proxies, blocked or not - a plain 404, a real app 401, or an unrelated 500
# on a Cloudflare- or Akamai-fronted site all carry them. Trusting them alone
# would call ordinary errors blocks, so they only count on a status that is
# itself block-shaped. `cf-mitigated: challenge` is different: Cloudflare sets
# it specifically when it challenged the request, so it needs no status gate,
# like a body marker.
_HEADER_TRUSTED_STATUSES = {403, 429, 503}

BLOCK_SIGNATURES = ("cloudflare", "akamai", "captcha", "rate_limited", "forbidden")


def _lower_headers(headers: Any) -> dict[str, str]:
    """`headers` as a plain lowercase dict - accepts httpx.Headers or any plain
    dict a test hands in, so `detect_block` needs no particular header type."""
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {str(k).lower(): str(v).lower() for k, v in items}


def detect_block(status: int, headers: Any, body_head: str) -> str:
    """One of `cloudflare`, `akamai`, `captcha`, `rate_limited`, `forbidden`,
    or "" for a response that carries none of those vendors' tells.

    `body_head` is at most the first ~2 KB of the body - enough for every
    marker here without holding a whole challenge page in memory. Body
    markers (challenge page text) decide on any status, including a 200 that
    is really a challenge page. Header-only markers (`cf-ray`, `server:
    cloudflare`, `server: AkamaiGHost`) only decide on a status that is
    itself block-shaped (`_HEADER_TRUSTED_STATUSES`) - see the note above. A
    bare 401/403 with none of the vendor markers falls through to
    "forbidden" last, after rate limiting (429).
    """
    h = _lower_headers(headers)
    body = (body_head or "").lower()

    if any(m in body for m in _CAPTCHA_MARKERS):
        return "captcha"
    if any(m in body for m in _CLOUDFLARE_BODY_MARKERS):
        return "cloudflare"
    if "access denied" in body and any(m in body for m in _AKAMAI_CONFIRM_MARKERS):
        return "akamai"

    if "challenge" in h.get("cf-mitigated", ""):
        return "cloudflare"

    if status in _HEADER_TRUSTED_STATUSES:
        server = h.get("server", "")
        if "cf-ray" in h or server == "cloudflare":
            return "cloudflare"
        if "akamaighost" in server:
            return "akamai"

    if status == 429:
        return "rate_limited"
    if status in (401, 403):
        return "forbidden"
    return ""


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
                 respect_robots: bool = True,
                 transport: Optional[httpx.BaseTransport] = None):
        self.delay = delay
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            # None (the default) is exactly what httpx.Client does without this
            # argument; it exists so tests can swap in httpx.MockTransport
            # without a live network.
            transport=transport,
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

    @staticmethod
    def _body_head(resp: httpx.Response) -> str:
        """The first ~2 KB of a response body, for `detect_block`. A body that
        fails to decode (binary, truncated) contributes no signal - never a
        reason to fail the request harder than the status already does."""
        try:
            return resp.text[:2048]
        except Exception:
            return ""

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
                # The retry policy is unchanged (still driven by `kind` alone);
                # the signature only says who refused, for the Companies tab.
                sig = detect_block(resp.status_code, resp.headers, self._body_head(resp))
                tag = f" ({sig})" if sig else ""
                last = FetchError(kind, f"HTTP {resp.status_code}{tag} for {url}",
                                  resp.status_code, signature=sig)
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
                        # A 200 that is really a Cloudflare (or similar)
                        # challenge page must not look like a malformed-payload
                        # bug in the adapter - it is a block.
                        sig = detect_block(resp.status_code, resp.headers,
                                           self._body_head(resp))
                        if sig:
                            raise FetchError(
                                BLOCKED, f"blocked ({sig}) for {url}",
                                resp.status_code, signature=sig)
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
