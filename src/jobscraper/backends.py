"""Judge transports: how the match funnel reaches a model.

The funnel needs exactly one thing from a model: given a system prompt and a
user prompt, hand back text. Prompt assembly, batching, caching and parsing are
transport-agnostic and stay in llm.py, so swapping transports changes nothing
about how a posting is judged.

Four transports:

  cli   Runs `claude -p` as a subprocess. Authenticates through the Claude Code
        subscription already signed in on this machine - no ANTHROPIC_API_KEY,
        no per-token billing. This is the default.
  api   The anthropic SDK. Needs ANTHROPIC_API_KEY. Kept for whoever has one.
  ollama A local open model (Qwen3) served by Ollama on this machine's GPU.
        No key, no login - the transport the Docker setup uses.
  off   No model at all. The funnel falls back to local scoring alone.

There is a fourth path that is deliberately NOT a backend: the handoff review in
review.py, where Claude Code judges postings inside an interactive session. That
one is two-phase - dump a queue, come back later with verdicts - and cannot be
expressed as a blocking call, so it lives as its own command.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Optional


class BackendError(RuntimeError):
    """A transport failed. The caller logs it and moves on to the next batch."""


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


# Claude Code takes short aliases or full model names. config.yaml carries full
# API model ids so the cli and api transports can read the same two keys; map
# them onto aliases the CLI is guaranteed to understand.
_ALIASES = (("haiku", "haiku"), ("sonnet", "sonnet"), ("opus", "opus"),
            ("fable", "fable"))


def cli_model_alias(model: str) -> str:
    low = (model or "").lower()
    for needle, alias in _ALIASES:
        if needle in low:
            return alias
    return model


class Backend:
    name = "none"
    unavailable_reason = ""

    @property
    def available(self) -> bool:
        return False

    def describe(self) -> str:
        return self.name

    def complete(self, model: str, system: str, user: str,
                 max_tokens: int = 4096) -> Completion:
        raise BackendError("no transport configured")


class OffBackend(Backend):
    name = "off"

    def __init__(self, reason: str = "disabled in config"):
        self.unavailable_reason = reason


class ClaudeCliBackend(Backend):
    """`claude -p` as a subprocess.

    The prompt goes in on stdin rather than as an argv element: job descriptions
    run to thousands of characters and Windows caps a command line at ~32k.

    The subprocess runs in a temp directory, not the project. Claude Code
    auto-discovers CLAUDE.md and project settings from its working directory,
    and none of that is wanted here - it would cost tokens on every call and let
    unrelated project config change how postings are judged.
    """

    name = "cli"

    def __init__(self, binary: str = "", timeout: float = 300.0,
                 extra_args: Optional[list[str]] = None):
        self.binary = binary or shutil.which("claude") or ""
        self.timeout = timeout
        # --restricted drops the tools that run code. These prompts are pure
        # classification and need no tools at all; this keeps a stray tool call
        # from turning a six-second judgement into a long agentic detour.
        self.extra_args = (list(extra_args) if extra_args is not None
                           else ["--restricted"])
        self._dropped_extra = False
        if not self.binary:
            self.unavailable_reason = (
                "the `claude` CLI is not on PATH - install Claude Code, or set "
                "budget.backend to `api` or `off` in config/config.yaml")

    @property
    def available(self) -> bool:
        return bool(self.binary)

    def describe(self) -> str:
        return f"cli ({self.binary})"

    def _argv(self, model: str) -> list[str]:
        return [self.binary, "-p", "--output-format", "json",
                "--model", cli_model_alias(model)] + self.extra_args

    def _run(self, argv: list[str], user: str,
             system: str) -> subprocess.CompletedProcess:
        """Run the CLI, passing the system prompt as a FILE, never an argument.

        On Windows `claude` is `claude.CMD`, a batch wrapper, and cmd.exe cuts
        an argument at its first newline. Measured 2026-09-24: a two-line
        `--system-prompt` reached the model as its first line only, so every
        instruction after it - output format included - was silently dropped.
        `--system-prompt-file` sidesteps the command line entirely.
        """
        fd, path = tempfile.mkstemp(prefix="jobscraper-sys-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(system)
            return subprocess.run(
                argv + ["--system-prompt-file", path],
                input=user,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout, cwd=tempfile.gettempdir())
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def complete(self, model: str, system: str, user: str,
                 max_tokens: int = 4096) -> Completion:
        if not self.available:
            raise BackendError(self.unavailable_reason)

        try:
            proc = self._run(self._argv(model), user, system)
        except subprocess.TimeoutExpired:
            raise BackendError(f"`claude -p` timed out after {self.timeout:.0f}s")
        except OSError as exc:
            raise BackendError(f"could not start {self.binary}: {exc}")

        # An older CLI may not know a flag we passed. Drop the optional ones
        # once and retry, rather than failing every call for the whole run.
        if (proc.returncode != 0 and self.extra_args and not self._dropped_extra
                and "unknown option" in (proc.stderr or "").lower()):
            self._dropped_extra = True
            self.extra_args = []
            try:
                proc = self._run(self._argv(model), user, system)
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise BackendError(f"retry without optional flags failed: {exc}")

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:300]
            raise BackendError(f"`claude -p` exited {proc.returncode}: {err}")

        env = _envelope(proc.stdout)
        if env.get("is_error"):
            raise BackendError(
                f"claude reported an error: {str(env.get('result'))[:200]}")

        usage = env.get("usage") or {}
        # Cached and freshly-written prompt tokens are still tokens spent, so
        # the run's budget guard has to see them.
        in_tok = (_i(usage.get("input_tokens"))
                  + _i(usage.get("cache_read_input_tokens"))
                  + _i(usage.get("cache_creation_input_tokens")))
        return Completion(text=str(env.get("result") or ""),
                          input_tokens=in_tok,
                          output_tokens=_i(usage.get("output_tokens")))


class ApiBackend(Backend):
    """The original transport: the anthropic SDK against ANTHROPIC_API_KEY."""

    name = "api"

    def __init__(self) -> None:
        self.client = None
        if not os.environ.get("ANTHROPIC_API_KEY"):
            self.unavailable_reason = "ANTHROPIC_API_KEY not set"
            return
        try:
            import anthropic
            self.client = anthropic.Anthropic()
        except Exception as exc:
            self.unavailable_reason = f"anthropic SDK unavailable: {exc}"

    @property
    def available(self) -> bool:
        return self.client is not None

    def complete(self, model: str, system: str, user: str,
                 max_tokens: int = 4096) -> Completion:
        if not self.available:
            raise BackendError(self.unavailable_reason)
        try:
            resp = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            raise BackendError(str(exc))
        usage = getattr(resp, "usage", None)
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", "") == "text")
        return Completion(
            text=text,
            input_tokens=_i(getattr(usage, "input_tokens", 0)) if usage else 0,
            output_tokens=_i(getattr(usage, "output_tokens", 0)) if usage else 0)


class OllamaBackend(Backend):
    """A local open model (e.g. Qwen3) served by Ollama: no API key, no login.

    Ollama runs the model on this machine's GPU and serves it over HTTP
    (default http://127.0.0.1:11434). That is what lets the app run in Docker
    with no Claude credentials in the container: the container talks to an
    Ollama service instead (D-11, R-8).

    Every call asks for no "thinking" (Qwen3 reasons at length by default - slow,
    and pointless for a yes/no screen) and for JSON output, which Ollama enforces
    while the model generates, so a malformed answer is unlikely rather than
    merely discouraged. Temperature 0: the same posting gets the same answer.

    The model is `budget.ollama_model`, not `budget.model`: the latter names a
    Claude model for the other transports.
    """

    name = "ollama"

    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "qwen3:14b",
                 timeout: float = 600.0, num_ctx: int = 16384,
                 client: Any = None):
        import httpx
        self.url = url.rstrip("/")
        self.model = model
        self.num_ctx = int(num_ctx)
        self._http = client or httpx.Client(timeout=timeout)
        self._probed: Optional[bool] = None

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
            wanted = self.model if ":" in self.model else f"{self.model}:latest"
            if wanted not in names:
                self.unavailable_reason = (
                    f"model {self.model!r} is not pulled into Ollama - run "
                    f"`ollama pull {self.model}`")
                self._probed = False
            else:
                self._probed = True
        return self._probed

    @property
    def available(self) -> bool:
        return self._probe()

    def describe(self) -> str:
        return f"ollama ({self.model} at {self.url})"

    def complete(self, model: str, system: str, user: str,
                 max_tokens: int = 4096) -> Completion:
        if not self.available:
            raise BackendError(self.unavailable_reason)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": self.num_ctx,
                        "num_predict": max_tokens},
        }
        try:
            resp = self._http.post(f"{self.url}/api/chat", json=body)
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
                          output_tokens=_i(data.get("eval_count")))


def build(budget: dict[str, Any]) -> Backend:
    """Pick a transport from the `budget` block of config.yaml.

    `JOBSCRAPER_BACKEND` and `JOBSCRAPER_OLLAMA_URL` override the file, which is
    how the Docker setup switches to its Ollama service without editing config.
    """
    if not budget.get("enable_llm", True):
        return OffBackend("disabled in config (budget.enable_llm: false)")

    kind = str(os.environ.get("JOBSCRAPER_BACKEND")
               or budget.get("backend", "cli")).strip().lower()
    if kind in ("off", "none", ""):
        return OffBackend("budget.backend is `off`")
    if kind == "api":
        return ApiBackend()
    if kind == "ollama":
        return OllamaBackend(
            url=str(os.environ.get("JOBSCRAPER_OLLAMA_URL")
                    or budget.get("ollama_url") or "http://127.0.0.1:11434"),
            model=str(budget.get("ollama_model") or "qwen3:14b"),
            timeout=float(budget.get("ollama_timeout", 600)),
            num_ctx=int(budget.get("ollama_num_ctx", 16384)))
    if kind == "cli":
        return ClaudeCliBackend(
            binary=str(budget.get("cli_bin", "") or ""),
            timeout=float(budget.get("cli_timeout", 300)),
            extra_args=budget.get("cli_extra_args"))
    return OffBackend(f"unknown budget.backend {kind!r} "
                      "(expected cli, api, ollama or off)")


def _envelope(stdout: str) -> dict[str, Any]:
    """Parse `--output-format json`. Tolerates a stray banner line before it."""
    raw = (stdout or "").strip()
    if not raw:
        raise BackendError("`claude -p` produced no output")
    try:
        return json.loads(raw)
    except Exception:
        pass
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                continue
    raise BackendError(f"could not parse CLI output: {raw[:200]}")


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0
