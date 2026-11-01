"""HttpClient.request(): the retry policy is unchanged, but a failure now
carries a block signature (P0-D5), and a 200 that is really a Cloudflare
challenge page must not be mistaken for a schema error.

httpx.MockTransport stands in for the network - the same pattern test_ollama.py
uses for the model transport - via the `transport=` constructor parameter added
here for exactly this purpose. No live network, no real host.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from jobscraper.models import BLOCKED, SCHEMA, TRANSIENT  # noqa: E402
from jobscraper.scrape.net import FetchError, HttpClient  # noqa: E402


def _client(handler, **kw):
    kw.setdefault("max_retries", 1)
    kw.setdefault("delay", 0.0)
    kw.setdefault("respect_robots", False)      # no second call for robots.txt
    return HttpClient("JobScraper-Test/1.0",
                      transport=httpx.MockTransport(handler), **kw)


def test_httpclient_without_a_transport_still_builds_a_real_client():
    """The new `transport=` kwarg defaults to None: every existing call site
    (pipeline.make_client, discovery, company_search) is unaffected."""
    c = HttpClient("JobScraper-Test/1.0")
    try:
        assert c._client is not None
    finally:
        c.close()


def test_fetcherror_signature_defaults_empty_and_stays_positional_compatible():
    exc = FetchError(BLOCKED, "HTTP 403 for x", 403)
    assert exc.signature == "" and exc.status == 403 and exc.kind == BLOCKED


def test_request_attaches_the_block_signature_on_a_4xx():
    def handler(request):
        return httpx.Response(403, headers={"cf-ray": "abc"}, text="blocked")
    c = _client(handler)
    try:
        c.get("https://x.example/jobs")
        raise AssertionError("expected a FetchError")
    except FetchError as exc:
        assert exc.kind == BLOCKED and exc.signature == "cloudflare"


def test_request_attaches_rate_limited_signature_and_still_retries():
    """429 keeps retrying exactly as before (RETRYABLE); the signature is
    metadata, not a change to the retry policy."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="slow down")
    c = _client(handler, max_retries=2)
    try:
        c.get("https://x.example/jobs")
        raise AssertionError("expected a FetchError")
    except FetchError as exc:
        assert exc.kind == TRANSIENT and exc.signature == "rate_limited"
    assert len(calls) == 2, "429 is still retried like any other transient error"


def test_request_surfaces_a_200_challenge_page_as_blocked_not_schema():
    def handler(request):
        return httpx.Response(200, text="Just a moment...",
                              headers={"content-type": "text/html"})
    c = _client(handler)
    try:
        c.get_json("https://x.example/jobs")
        raise AssertionError("expected a FetchError")
    except FetchError as exc:
        assert exc.kind == BLOCKED and exc.signature == "cloudflare"


def test_request_keeps_a_genuine_schema_error_for_ordinary_bad_json():
    def handler(request):
        return httpx.Response(200, text="<html>not json, not a challenge</html>",
                              headers={"content-type": "text/html"})
    c = _client(handler)
    try:
        c.get_json("https://x.example/jobs")
        raise AssertionError("expected a FetchError")
    except FetchError as exc:
        assert exc.kind == SCHEMA and exc.signature == ""
