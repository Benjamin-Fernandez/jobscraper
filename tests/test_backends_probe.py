"""Q-100 T1-A oracles: the model health probe behind the hub's Local AI item
(q100_ui_design section 3.3): `backends.probe`, `configured_code`, `Backend.close`.
Verify: `python tests/run_tests.py -k backends_probe`.

No network: `httpx.Client` is replaced by a fake that records every call and counts close().
"""
from __future__ import annotations

import contextlib
import dataclasses
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

URL = "http://secret-host.test:11434"
LOCAL = {"enable_llm": True, "backend": "ollama", "ollama_model": "example-model:8b"}
ENV_KEYS = ("JOBSCRAPER_BACKEND", "JOBSCRAPER_OLLAMA_URL")


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status, self.body = status, body or {}

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.body


class FakeHttp:
    """An httpx.Client stand-in: only GET /api/tags is expected; anything else is recorded in
    `other` (and the test fails on it), because the probe must not load a model."""

    def __init__(self, models=("example-model:8b",), status=200, error=None):
        self.models, self.status, self.error = list(models), status, error
        self.gets, self.other, self.close_calls = [], [], 0

    def get(self, url, **kw):
        self.gets.append((url, kw))
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status, {"models": [{"name": m} for m in self.models]})

    def close(self):
        self.close_calls += 1

    def __getattr__(self, name):                       # post, stream, send, request ...
        def record(*a, **k):
            self.other.append(name)
            raise AssertionError(f"the probe called client.{name}")
        return record


@contextlib.contextmanager
def _env(**env):
    saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        yield
    finally:
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


@contextlib.contextmanager
def _http(*clients, **env):
    """Every httpx.Client() the code under test makes is the next fake in `clients`
    (a fresh default FakeHttp when they run out); the list of those made is yielded."""
    import httpx
    made = []
    pool = list(clients)

    def factory(*a, **k):
        c = pool.pop(0) if pool else FakeHttp()
        made.append(c)
        return c
    real = httpx.Client
    httpx.Client = factory
    try:
        with _env(**env):
            yield made
    finally:
        httpx.Client = real


def _probe(budget=None, *clients, **env):
    from jobscraper import backends
    with _http(*clients, **env) as made:
        return backends.probe(LOCAL if budget is None else budget), made


# ------------------------------------------------------------------ the client is closed

def test_backends_probe_closes_the_client_it_built_on_every_outcome():
    cases = (FakeHttp(),                                          # ok
             FakeHttp(models=["other:1b"]),                       # model_missing
             FakeHttp(error=ConnectionError("down")),             # unreachable
             FakeHttp(status=500))                                # unreachable (HTTP error)
    for fake in cases:
        p, made = _probe(None, fake)
        assert made == [fake], "one client per probe"
        assert fake.close_calls == 1, (p, fake.close_calls)
        assert fake.other == [], "the probe only lists models"


def test_backends_probe_closes_the_client_even_when_asking_raises():
    from jobscraper import backends
    fake = FakeHttp()
    real = backends.OllamaBackend._probe

    def explode(self):
        raise RuntimeError("boom")
    backends.OllamaBackend._probe = explode
    try:
        p, made = _probe(None, fake)
    finally:
        backends.OllamaBackend._probe = real
    assert (p.ok, p.code) == (False, "unreachable"), p
    assert fake.close_calls == 1


def test_backends_probe_repeated_every_minute_leaks_no_client():
    from jobscraper import backends
    fakes = [FakeHttp() for _ in range(6)]
    with _http(*fakes) as made:
        for _ in range(6):
            backends.probe(LOCAL)
    assert made == fakes and [f.close_calls for f in fakes] == [1] * 6


def test_backends_probe_asks_one_model_list_and_loads_nothing():
    fake = FakeHttp()
    p, _ = _probe(None, fake)
    assert p.ok
    assert len(fake.gets) == 1
    url, kw = fake.gets[0]
    assert url == "http://127.0.0.1:11434/api/tags" and kw.get("timeout") == 5.0
    assert fake.other == []


def test_backends_close_never_closes_a_client_handed_in():
    from jobscraper import backends
    handed = FakeHttp()
    be = backends.OllamaBackend(client=handed)
    be.available            # asks once, through the handed-in client
    assert len(handed.gets) == 1
    be.close()
    be.close()
    assert handed.close_calls == 0, "the caller's client stays open"


def test_backends_close_closes_its_own_client_once_per_call_and_is_safe_twice():
    from jobscraper import backends
    own = FakeHttp()
    with _http(own):
        be = backends.OllamaBackend()
    be.close()
    assert own.close_calls == 1
    be.close()                                        # safe to repeat
    assert own.close_calls == 2

    class Boom(FakeHttp):
        def close(self):
            raise OSError("already closed")
    with _http(Boom()):
        be = backends.OllamaBackend()
    be.close()                                        # swallows


def test_backends_close_is_a_no_op_on_the_base_and_the_off_backend():
    from jobscraper import backends
    backends.Backend().close()
    backends.OffBackend("why").close()


# ------------------------------------------------------------------ codes

def test_backends_probe_ok_has_an_empty_code_and_the_model():
    p, _ = _probe(None, FakeHttp(models=["example-model:8b", "other:1b"]))
    assert (p.ok, p.code, p.backend, p.model, p.local) == (True, "", "ollama", "example-model:8b", True)


def test_backends_probe_a_model_tag_without_a_colon_matches_latest():
    p, _ = _probe({**LOCAL, "ollama_model": "tiny"}, FakeHttp(models=["tiny:latest"]))
    assert p.ok and p.code == ""
    p, _ = _probe({**LOCAL, "ollama_model": "tiny"}, FakeHttp(models=["tiny:1b"]))
    assert (p.ok, p.code) == (False, "model_missing")


def test_backends_probe_unreachable_and_http_errors():
    for fake in (FakeHttp(error=ConnectionError("refused")), FakeHttp(error=TimeoutError()), FakeHttp(status=503)):
        p, _ = _probe(None, fake)
        assert (p.ok, p.code, p.backend, p.model) == (False, "unreachable", "ollama", "example-model:8b"), p


def test_backends_probe_model_missing():
    p, _ = _probe(None, FakeHttp(models=["something-else:7b"]))
    assert (p.ok, p.code, p.backend, p.model, p.local) == (False, "model_missing", "ollama", "example-model:8b", True)
    p, _ = _probe(None, FakeHttp(models=[]))
    assert p.code == "model_missing"


def test_backends_probe_off_never_touches_the_network():
    for budget in ({"enable_llm": False, "backend": "ollama", "ollama_model": "m"},
                   {"enable_llm": True, "backend": "off", "ollama_model": "m"},
                   {"enable_llm": True, "backend": "none"},
                   {"enable_llm": True, "backend": ""}):
        p, made = _probe(budget)
        assert (p.ok, p.code, p.local) == (False, "off", False), (budget, p)
        assert made == [], "no client for an Off backend"
    p, _ = _probe({"enable_llm": False, "backend": "ollama", "ollama_model": "m"})
    assert p.backend == "off" and p.model == ""


def test_backends_probe_misconfigured_for_an_unknown_backend():
    p, made = _probe({"enable_llm": True, "backend": "mystery", "ollama_model": "m"})
    assert (p.ok, p.code, p.backend, p.local) == (False, "misconfigured", "unknown", False), p
    assert made == []


def test_backends_probe_local_is_false_for_a_remote_url_or_a_cloud_tag():
    p, _ = _probe({**LOCAL, "ollama_url": URL})
    assert p.ok and p.local is False
    p, _ = _probe({**LOCAL, "ollama_model": "big:cloud"}, FakeHttp(models=["big:cloud"]))
    assert p.local is False


def test_backends_probe_reads_the_env_overrides_like_build():
    p, made = _probe(LOCAL, JOBSCRAPER_BACKEND="off")
    assert p.code == "off" and made == []
    p, made = _probe(LOCAL, FakeHttp(), JOBSCRAPER_OLLAMA_URL=URL)
    assert p.ok and p.local is False and made[0].gets[0][0] == f"{URL}/api/tags"


def test_backends_probe_tolerates_an_empty_budget():
    p, made = _probe({})
    assert p.backend == "ollama" and p.code in ("", "model_missing"), p
    assert len(made) == 1 and made[0].close_calls == 1


# ------------------------------------------------------------------ configured_code

def test_backends_configured_code_is_config_only_and_builds_no_client():
    from jobscraper import backends
    table = (
        ({"enable_llm": False, "backend": "ollama"}, "off"),
        ({"enable_llm": True, "backend": "off"}, "off"),
        ({"enable_llm": True, "backend": "OFF"}, "off"),
        ({"enable_llm": True, "backend": "none"}, "off"),
        ({"enable_llm": True, "backend": ""}, "off"),
        ({"enable_llm": True, "backend": "mystery"}, "misconfigured"),
        ({"enable_llm": True, "backend": "ollama"}, ""),
        ({"enable_llm": True, "backend": "Ollama"}, ""),
        ({}, ""),
        (None, ""),
    )
    with _http() as made:
        for budget, want in table:
            assert backends.configured_code(budget) == want, budget
        assert made == [], "no httpx.Client was built"
    with _http() as made:
        assert backends.configured_code(LOCAL) == "" and made == []


def test_backends_configured_code_follows_the_backend_env_override():
    from jobscraper import backends
    with _env(JOBSCRAPER_BACKEND="off"):
        assert backends.configured_code(LOCAL) == "off"
    with _env(JOBSCRAPER_BACKEND="mystery"):
        assert backends.configured_code(LOCAL) == "misconfigured"
    with _env(JOBSCRAPER_BACKEND="ollama"):
        assert backends.configured_code({"enable_llm": True, "backend": "off"}) == ""


def test_backends_configured_code_agrees_with_what_build_makes():
    from jobscraper import backends
    for budget in ({"enable_llm": False}, {"backend": "off"}, {"backend": "mystery"}, {"backend": "ollama"}):
        with _http(), _env():
            be = backends.build(budget)
            try:
                want = backends.configured_code(budget)
                assert be.unavailable_code == want, (budget, be.unavailable_code, want)
            finally:
                be.close()


# ------------------------------------------------------------------ nothing sensitive in a Probe

def test_backends_a_probe_has_no_reason_text_and_never_the_url():
    from jobscraper import backends
    names = {f.name for f in dataclasses.fields(backends.Probe)}
    assert names == {"ok", "code", "backend", "model", "local"}, names
    assert not any("reason" in n or "url" in n or "message" in n for n in names)
    for fake in (FakeHttp(error=ConnectionError(f"cannot reach {URL}")), FakeHttp(models=["x:1"])):
        p, _ = _probe({**LOCAL, "ollama_url": URL}, fake)
        flat = repr(dataclasses.asdict(p))
        assert "secret-host" not in flat and "11434" not in flat and URL not in flat, flat
    p = backends.Probe(ok=True, code="", backend="ollama", model="m", local=True)
    try:
        p.ok = False
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("a Probe is frozen")


def test_backends_unavailable_code_is_a_fixed_word_while_the_reason_names_the_url():
    from jobscraper import backends
    fake = FakeHttp(error=ConnectionError("down"))
    with _http(fake), _env():
        be = backends.OllamaBackend(url=URL, model="m")
        assert be.unavailable_code == "" and be.available is False
        assert be.unavailable_code == "unreachable"
        assert "secret-host" in be.unavailable_reason, "the sentence stays server-side"
        be.close()
    ok = FakeHttp(models=["m:latest"])
    with _http(ok), _env():
        be = backends.OllamaBackend(url=URL, model="m")
        assert be.available is True and be.unavailable_code == ""
        be.close()
    miss = FakeHttp(models=[])
    with _http(miss), _env():
        be = backends.OllamaBackend(url=URL, model="m")
        assert be.available is False and be.unavailable_code == "model_missing"
        be.close()
    assert backends.Backend.unavailable_code == ""
    assert backends.OffBackend("x").unavailable_code == "off"
    assert backends.OffBackend("x", "misconfigured").unavailable_code == "misconfigured"
