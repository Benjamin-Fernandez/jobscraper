"""The local-model transport: Qwen3 served by Ollama (backends.OllamaBackend).

No Ollama is needed to run these: httpx's MockTransport stands in for the
server, so what is pinned is the request the app sends (no thinking, forced
JSON, temperature 0, a context big enough for a batch, the Qwen model - not the
Claude one) and how every failure becomes a BackendError the decide stage can
count and retry, instead of a crash.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from jobscraper import backends as B  # noqa: E402

URL = "http://ollama.test:11434"


def _backend(handler, model="qwen3:14b"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return B.OllamaBackend(url=URL, model=model, num_ctx=16384, client=client)


def _server(tags=("qwen3:14b",), chat=None, seen=None):
    """A fake Ollama: /api/tags lists `tags`; /api/chat returns `chat`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": t} for t in tags]})
        if request.url.path == "/api/chat":
            if seen is not None:
                seen.append(json.loads(request.content))
            return chat or httpx.Response(200, json={
                "message": {"role": "assistant", "content": '{"decisions": []}'},
                "prompt_eval_count": 812, "eval_count": 64})
        return httpx.Response(404)
    return handler


def test_ollama_sends_no_thinking_forced_json_and_the_qwen_model():
    seen: list = []
    b = _backend(_server(seen=seen))
    comp = b.complete("claude-haiku-4-5-20251001", "SYS", "USER", max_tokens=2048)
    body = seen[0]
    assert body["model"] == "qwen3:14b"                 # not the Claude id
    assert body["think"] is False and body["format"] == "json"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 16384, "num_predict": 2048}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == "SYS"
    assert (comp.text, comp.input_tokens, comp.output_tokens) == \
        ('{"decisions": []}', 812, 64)


def test_ollama_unreachable_is_unavailable_with_a_clear_reason():
    def down(request):
        raise httpx.ConnectError("refused", request=request)
    b = _backend(down)
    assert not b.available and "not reachable" in b.unavailable_reason
    try:
        b.complete("m", "s", "u")
        raise AssertionError("an unreachable Ollama must raise BackendError")
    except B.BackendError:
        pass


def test_ollama_model_not_pulled_says_how_to_fix_it():
    b = _backend(_server(tags=("llama3.2:latest",)))
    assert not b.available and "ollama pull qwen3:14b" in b.unavailable_reason


def test_ollama_bare_model_name_matches_the_latest_tag():
    assert _backend(_server(tags=("qwen3:latest",)), model="qwen3").available


def test_ollama_http_and_model_errors_become_backend_errors():
    for chat in (httpx.Response(500, text="out of memory"),
                 httpx.Response(200, json={"error": "model failed to load"}),
                 httpx.Response(200, text="<html>not json</html>")):
        b = _backend(_server(chat=chat))
        try:
            b.complete("m", "s", "u")
            raise AssertionError(f"{chat.status_code} must raise BackendError")
        except B.BackendError:
            pass


def test_build_selects_ollama_from_config_and_from_the_environment():
    b = B.build({"backend": "ollama", "ollama_model": "qwen3:8b",
                 "ollama_url": "http://h:1"})
    assert isinstance(b, B.OllamaBackend) and (b.model, b.url) == ("qwen3:8b", "http://h:1")
    # Docker switches transport by environment, without editing config.yaml.
    old = {k: os.environ.get(k) for k in ("JOBSCRAPER_BACKEND", "JOBSCRAPER_OLLAMA_URL")}
    os.environ["JOBSCRAPER_BACKEND"] = "ollama"
    os.environ["JOBSCRAPER_OLLAMA_URL"] = "http://ollama:11434"
    try:
        b = B.build({"backend": "cli"})
        assert isinstance(b, B.OllamaBackend) and b.url == "http://ollama:11434"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert B.build({"backend": "cli", "cli_bin": "x"}).name == "cli"
