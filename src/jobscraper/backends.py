"""Model transports: how JobScraper reaches a model.

Two stages need one: resume parsing (profile/resume_ingest.py) and the decide
step of the match funnel (decide.py). Both need exactly one thing - given a
system prompt and a user prompt, hand back text. Prompt assembly, batching,
caching and parsing live with those stages, so a transport changes nothing about
how a resume is read or a posting judged.

Two transports:

  ollama  Qwen3 (an open model) served by Ollama on this machine's GPU, or by
          an Ollama service next to the app in Docker. No key, no login.
  off     No model at all. Runs still work: the free prefilter decides alone and
          survivors wait, undecided, until a model is available.

Qwen replaced Claude Haiku as the judge on 2026-09-24 (D-16) and as the resume
parser on 2026-09-28; the Claude CLI and API transports went with it (M14).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional


class BackendError(RuntimeError):
    """A transport failed. The caller logs it and moves on to the next batch."""


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_eval_ns: int = 0     # Ollama's own timings, in nanoseconds: reading the
    eval_ns: int = 0            # prompt, then writing the answer (0 = not reported)
    done_reason: str = ""       # Ollama's: "stop", or "length" when the output cap cut it


class Backend:
    name = "none"
    unavailable_reason = ""
    model_id = ""       # recorded on every decision (see OllamaBackend.model_id)

    @property
    def available(self) -> bool:
        return False

    def describe(self) -> str:
        return self.name

    def complete(self, system: str, user: str, max_tokens: int = 4096,
                 schema: Optional[dict] = None,
                 timeout: Optional[float] = None, *,
                 format: Optional[dict] = None,
                 temperature: Optional[float] = None,
                 seed: Optional[int] = None,
                 top_k: Optional[int] = None,
                 keep_alive: Any = None) -> Completion:
        """`schema`, when given, is a JSON schema the answer must follow;
        `timeout` caps this call's seconds below the transport's own.

        Per-call options (apply_design §7.6, M20 WP-P1), keyword only so every
        existing caller is untouched: `format` is a JSON schema dict (the same
        thing as `schema`; `format` wins when both are given; neither = plain
        "json"); `temperature=None` means 0; `seed` and `top_k` reach the
        model only when given. The resolver's two-run agreement check and the
        tailor's sampling need these. `keep_alive` (D-78 form filling,
        llm_fill_design §13.2) is how long the model stays loaded after the call
        ("15m"); sent only when given."""
        raise BackendError(self.unavailable_reason or "no model transport configured")

    def warm(self, keep_alive: Any = None) -> None:
        """Load the model before it is needed (llm_fill_design §13.1). A transport
        with nothing to load only checks that it can answer."""
        if not self.available:
            raise BackendError(self.unavailable_reason or "no model transport configured")


class OffBackend(Backend):
    name = "off"

    def __init__(self, reason: str = "disabled in config"):
        self.unavailable_reason = reason


class OllamaBackend(Backend):
    """Qwen3 served by Ollama: no API key, no login.

    Ollama runs the model on this machine's GPU and serves it over HTTP
    (default http://127.0.0.1:11434). In Docker the app talks to an Ollama
    service instead (D-11, R-8).

    Every call asks for no "thinking" where the model has one (Qwen3 reasons at
    length by default - slow, and pointless for a yes/no screen or a resume
    summary) and for JSON output - or a JSON schema, when the caller has one -
    which Ollama enforces while the model generates, so a malformed answer is
    unlikely rather than merely discouraged. Temperature 0: the same input gets
    the same answer.

    `model_id` is the Ollama tag (e.g. `qwen3:14b`). It is stored with every
    decision, and a cached decision is reused only when the same model made it,
    so changing the tag re-judges instead of trusting another model's answers.
    """

    name = "ollama"

    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "qwen3:14b",
                 timeout: float = 600.0, num_ctx: int = 16384,
                 client: Any = None):
        import httpx
        self.url = url.rstrip("/")
        self.model_id = model
        self.num_ctx = int(num_ctx)
        self.timeout = float(timeout)
        self._http = client or httpx.Client(timeout=self.timeout)
        self._probed: Optional[bool] = None
        self._thinks: Optional[bool] = None     # does the model have a thinking mode?

    def _probe(self) -> bool:
        """Is Ollama up, and is the model pulled? Asked once, then remembered."""
        if self._probed is None:
            try:
                resp = self._http.get(f"{self.url}/api/tags", timeout=5.0)
                resp.raise_for_status()
                names = {m.get("name", "") for m in resp.json().get("models", [])}
            except Exception as exc:
                self.unavailable_reason = (
                    f"Ollama is not reachable at {self.url} ({type(exc).__name__}) - "
                    "install it from https://ollama.com and start it")
                self._probed = False
                return False
            wanted = self.model_id if ":" in self.model_id else f"{self.model_id}:latest"
            if wanted not in names:
                self.unavailable_reason = (
                    f"model {self.model_id!r} is not pulled into Ollama - run "
                    f"`ollama pull {self.model_id}`")
                self._probed = False
            else:
                self._probed = True
        return self._probed

    @property
    def available(self) -> bool:
        return self._probe()

    def describe(self) -> str:
        return f"ollama ({self.model_id} at {self.url})"

    def _has_thinking(self) -> bool:
        """Does `/api/show` list the `thinking` capability? Asked once.

        Ollama refuses `think: false` (HTTP 400) for a model with no thinking
        mode, such as the Qwen3 instruct-2507 builds. If Ollama cannot say (an
        older server, or the call fails) we assume it does, which is the request
        this app always sent."""
        if self._thinks is None:
            try:
                resp = self._http.post(f"{self.url}/api/show",
                                       json={"model": self.model_id}, timeout=10.0)
                resp.raise_for_status()
                caps = resp.json().get("capabilities")
                self._thinks = "thinking" in caps if isinstance(caps, list) else True
            except Exception:
                self._thinks = True
        return self._thinks

    def complete(self, system: str, user: str, max_tokens: int = 4096,
                 schema: Optional[dict] = None,
                 timeout: Optional[float] = None, *,
                 format: Optional[dict] = None,
                 temperature: Optional[float] = None,
                 seed: Optional[int] = None,
                 top_k: Optional[int] = None,
                 keep_alive: Any = None) -> Completion:
        if not self.available:
            raise BackendError(self.unavailable_reason)
        body = {
            "model": self.model_id,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            # A schema makes Ollama constrain every token to it (ids limited to
            # an enum, say); plain "json" only promises valid JSON.
            "format": _format(format, schema),
            "options": {"temperature": 0 if temperature is None else temperature,
                        "num_ctx": self.num_ctx, "num_predict": max_tokens},
        }
        if seed is not None:
            body["options"]["seed"] = seed
        if top_k is not None:
            body["options"]["top_k"] = top_k
        if self._has_thinking():
            body["think"] = False
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        try:
            resp = self._http.post(f"{self.url}/api/chat", json=body,
                                   timeout=min(self.timeout, timeout) if timeout
                                   else self.timeout)
        except Exception as exc:
            raise BackendError(f"Ollama request failed: {type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            raise BackendError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError:
            raise BackendError(f"Ollama sent non-JSON: {resp.text[:200]}")
        if data.get("error"):
            raise BackendError(f"Ollama error: {str(data['error'])[:200]}")
        return Completion(text=str((data.get("message") or {}).get("content") or ""),
                          input_tokens=_i(data.get("prompt_eval_count")),
                          output_tokens=_i(data.get("eval_count")),
                          prompt_eval_ns=_i(data.get("prompt_eval_duration")),
                          eval_ns=_i(data.get("eval_duration")),
                          done_reason=str(data.get("done_reason") or ""))

    def warm(self, keep_alive: Any = None) -> None:
        """Load the model now (a cold load costs ~33 s, S-5b) so the first form page
        doesn't pay for it. Ollama loads a model on a generate request with no
        prompt; `keep_alive` (sent only when given) holds it loaded. It sends the same
        `num_ctx` as `complete` (apply's cli sets `llm_fill.num_ctx` on this object
        first): Ollama reloads a model whose context size differs, which would put
        the cold load back on the first form page."""
        if not self.available:
            raise BackendError(self.unavailable_reason)
        body: dict[str, Any] = {"model": self.model_id, "options": {"num_ctx": self.num_ctx}}
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        try:
            resp = self._http.post(f"{self.url}/api/generate", json=body, timeout=self.timeout)
        except Exception as exc:
            raise BackendError(f"Ollama warm-up failed: {type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            raise BackendError(f"Ollama returned HTTP {resp.status_code} on warm-up")


def warm(backend: Backend, keep_alive: Any = None) -> None:
    """Load `backend`'s model before an apply attempt opens the browser (D-81): a
    failure here (Ollama not running, model not pulled) raises BackendError, so the
    attempt ends `model_unavailable` before Edge opens (llm_fill_design §11)."""
    fn = getattr(backend, "warm", None)
    if callable(fn):
        fn(keep_alive)
    elif not getattr(backend, "available", False):
        raise BackendError(getattr(backend, "unavailable_reason", "") or "no model transport")


def build(budget: dict[str, Any]) -> Backend:
    """Pick a transport from the `budget` block of config.yaml.

    `JOBSCRAPER_BACKEND` and `JOBSCRAPER_OLLAMA_URL` override the file, which is
    how the Docker setup points at its Ollama service without editing config.
    """
    if not budget.get("enable_llm", True):
        return OffBackend("disabled in config (budget.enable_llm: false)")

    kind = str(os.environ.get("JOBSCRAPER_BACKEND")
               or budget.get("backend", "ollama")).strip().lower()
    if kind in ("off", "none", ""):
        return OffBackend("budget.backend is `off`")
    if kind == "ollama":
        return OllamaBackend(
            url=str(os.environ.get("JOBSCRAPER_OLLAMA_URL")
                    or budget.get("ollama_url") or "http://127.0.0.1:11434"),
            model=str(budget.get("ollama_model") or "qwen3:14b"),
            timeout=float(budget.get("ollama_timeout", 600)),
            num_ctx=int(budget.get("ollama_num_ctx", 16384)))
    return OffBackend(f"unknown budget.backend {kind!r} (expected ollama or off)")


# D-105 (q74_model_sees_sensitive.md §1, ADR-0008): hosts that mean "this computer".
# A Docker service name (`http://ollama:11434`), a LAN IP or any other host is remote.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _target_is_local(url: str, model: str) -> bool:
    """The rule behind `is_local`, on a resolved URL and Ollama model tag.

    Two checks. The host must be this computer. And the model tag must not be an
    Ollama cloud model: a tag ending in `-cloud` or `:cloud` is served by a local
    Ollama but forwarded to ollama.com, so a prompt would leave the machine (D-107).
    Anything unparseable is not local."""
    from urllib.parse import urlparse
    try:
        host = urlparse(str(url or "")).hostname or ""
    except ValueError:
        return False
    tag = str(model or "").strip().lower()
    if tag.endswith("-cloud") or tag.endswith(":cloud"):
        return False
    return host.lower() in LOCAL_HOSTS


def is_local(backend: Backend) -> bool:
    """True when `backend` is Ollama running on this computer, with a model that
    runs on it too (an Ollama `-cloud` / `:cloud` tag is not: D-107).

    The owner's switch `apply.model_sees_sensitive` lets private profile values into
    prompts only when this holds, so a later remote backend can never receive them
    silently. Reads the URL `build` already resolved (the `JOBSCRAPER_OLLAMA_URL`
    override wins there); makes no network call. `OffBackend` and anything else: False.
    """
    if not isinstance(backend, OllamaBackend):
        return False
    return _target_is_local(backend.url, backend.model_id)


def is_local_config(budget: dict[str, Any]) -> bool:
    """`is_local(build(budget))` without building a backend (no `httpx.Client`):
    for the web routers, which ask on every GET. Same resolution as `build`."""
    budget = budget or {}
    if not budget.get("enable_llm", True):
        return False
    kind = str(os.environ.get("JOBSCRAPER_BACKEND")
               or budget.get("backend", "ollama")).strip().lower()
    if kind != "ollama":
        return False
    url = str(os.environ.get("JOBSCRAPER_OLLAMA_URL")
              or budget.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")
    return _target_is_local(url, str(budget.get("ollama_model") or "qwen3:14b"))


def _format(format: Optional[dict], schema: Optional[dict]) -> Any:
    """The request's `format`: a JSON schema dict when the caller gave one
    (`format` first, then the older `schema` argument), else plain "json"."""
    if isinstance(format, dict) and format:
        return format
    return schema if schema else "json"


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0
