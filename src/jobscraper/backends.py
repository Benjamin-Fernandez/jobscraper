"""Judge transports: how the match funnel reaches a model.

The funnel needs exactly one thing from a model: given a system prompt and a
user prompt, hand back text. Prompt assembly, batching, caching and parsing are
transport-agnostic and stay in llm.py, so swapping transports changes nothing
about how a posting is judged.

Three transports:

  cli   Runs `claude -p` as a subprocess. Authenticates through the Claude Code
        subscription already signed in on this machine - no ANTHROPIC_API_KEY,
        no per-token billing. This is the default.
  api   The anthropic SDK. Needs ANTHROPIC_API_KEY. Kept for whoever has one.
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
        return subprocess.run(
            argv + ["--system-prompt", system],
            input=user,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=self.timeout, cwd=tempfile.gettempdir())

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


def build(budget: dict[str, Any]) -> Backend:
    """Pick a transport from the `budget` block of config.yaml."""
    if not budget.get("enable_llm", True):
        return OffBackend("disabled in config (budget.enable_llm: false)")

    kind = str(budget.get("backend", "cli")).strip().lower()
    if kind in ("off", "none", ""):
        return OffBackend("budget.backend is `off`")
    if kind == "api":
        return ApiBackend()
    if kind == "cli":
        return ClaudeCliBackend(
            binary=str(budget.get("cli_bin", "") or ""),
            timeout=float(budget.get("cli_timeout", 300)),
            extra_args=budget.get("cli_extra_args"))
    return OffBackend(f"unknown budget.backend {kind!r} "
                      "(expected cli, api or off)")


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
