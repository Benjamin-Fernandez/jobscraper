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
    # Why the transport can't answer, as a fixed word the web hub can show
    # (q100_ui_design §3.3): "off", "misconfigured", "unreachable", "model_missing",
    # or "" while nothing is known to be wrong. `unavailable_reason` is the
    # human sentence and names the URL, so it never leaves the server.
    unavailable_code = ""
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

    def warm(self, keep_alive: Any = None, *, timeout: Optional[float] = None) -> None:
        """Load the model before it is needed (llm_fill_design §13.1). A transport
        with nothing to load only checks that it can answer. `timeout` (Q-126, keyword
        only) caps the load request's seconds below the transport's own."""
        if not self.available:
            raise BackendError(self.unavailable_reason or "no model transport configured")

    def close(self) -> None:
        """Release what the transport holds open (an HTTP client). Nothing here."""


class OffBackend(Backend):
    name = "off"

    def __init__(self, reason: str = "disabled in config", code: str = "off"):
        self.unavailable_reason = reason
        self.unavailable_code = code    # "off" (switched off) or "misconfigured"


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
        self._owns_http = client is None
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
                self.unavailable_code = "unreachable"
                self._probed = False
                return False
            wanted = self.model_id if ":" in self.model_id else f"{self.model_id}:latest"
            if wanted not in names:
                self.unavailable_reason = (
                    f"model {self.model_id!r} is not pulled into Ollama - run "
                    f"`ollama pull {self.model_id}`")
                self.unavailable_code = "model_missing"
                self._probed = False
            else:
                self.unavailable_code = ""
                self._probed = True
        return self._probed

    @property
    def available(self) -> bool:
        return self._probe()

    def reset_probe(self) -> None:
        """Forget the cached probe and the thinking flag (Q-126). The cache is right
        for one process that only asks, but after `ensure_model_running` started
        Ollama it would keep reporting the earlier "not reachable"."""
        self._probed = None
        self._thinks = None

    def describe(self) -> str:
        return f"ollama ({self.model_id} at {self.url})"

    def close(self) -> None:
        """Close the HTTP client this backend made. A client handed in by the
        caller (tests) is the caller's to close. Safe to call twice."""
        if self._owns_http:
            try:
                self._http.close()
            except Exception:
                pass

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

    def warm(self, keep_alive: Any = None, *, timeout: Optional[float] = None) -> None:
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
            resp = self._http.post(f"{self.url}/api/generate", json=body,
                                   timeout=self.timeout if timeout is None else timeout)
        except Exception as exc:
            raise BackendError(f"Ollama warm-up failed: {type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            raise BackendError(f"Ollama returned HTTP {resp.status_code} on warm-up")


def warm(backend: Backend, keep_alive: Any = None, *, timeout: Optional[float] = None) -> None:
    """Load `backend`'s model before an apply attempt opens the browser (D-81): a
    failure here (Ollama not running, model not pulled) raises BackendError, so the
    attempt ends `model_unavailable` before Edge opens (llm_fill_design §11).
    `timeout` (Q-126, keyword only) is passed on only when given, so a transport
    whose `warm` takes no such argument still works."""
    fn = getattr(backend, "warm", None)
    if callable(fn):
        if timeout is None:
            fn(keep_alive)
        else:
            fn(keep_alive, timeout=timeout)
    elif not getattr(backend, "available", False):
        raise BackendError(getattr(backend, "unavailable_reason", "") or "no model transport")


def build(budget: dict[str, Any]) -> Backend:
    """Pick a transport from the `budget` block of config.yaml.

    `JOBSCRAPER_BACKEND` and `JOBSCRAPER_OLLAMA_URL` override the file, which is
    how the Docker setup points at its Ollama service without editing config.
    """
    if not budget.get("enable_llm", True):
        return OffBackend("disabled in config (budget.enable_llm: false)", "off")

    kind = str(os.environ.get("JOBSCRAPER_BACKEND")
               or budget.get("backend", "ollama")).strip().lower()
    if kind in ("off", "none", ""):
        return OffBackend("budget.backend is `off`", "off")
    if kind == "ollama":
        return OllamaBackend(
            url=str(os.environ.get("JOBSCRAPER_OLLAMA_URL")
                    or budget.get("ollama_url") or "http://127.0.0.1:11434"),
            model=str(budget.get("ollama_model") or "qwen3:14b"),
            timeout=float(budget.get("ollama_timeout", 600)),
            num_ctx=int(budget.get("ollama_num_ctx", 16384)))
    return OffBackend(f"unknown budget.backend {kind!r} (expected ollama or off)",
                      "misconfigured")


def configured_code(budget: dict[str, Any]) -> str:
    """What `build(budget)` would say from config alone, without building anything:
    "off" (switched off), "misconfigured" (an unknown `budget.backend`), or ""
    (Ollama, which only a probe can judge). Same resolution as `build`, so the web
    hub can answer "off" at once instead of starting a probe thread."""
    budget = budget or {}
    if not budget.get("enable_llm", True):
        return "off"
    kind = str(os.environ.get("JOBSCRAPER_BACKEND")
               or budget.get("backend", "ollama")).strip().lower()
    if kind in ("off", "none", ""):
        return "off"
    return "" if kind == "ollama" else "misconfigured"


@dataclass(frozen=True)
class Probe:
    """One health check of the configured model transport (q100_ui_design §3.3).

    `code` is "" when `ok`, else "off", "misconfigured", "unreachable" or
    "model_missing". No reason text: that names the Ollama URL, and a Probe is
    what the web hub sends to the browser."""
    ok: bool
    code: str
    backend: str
    model: str
    local: bool
    # Q-126: is an Ollama program installed here (a local Ollama only; None = not asked).
    installed: Optional[bool] = None


def probe(budget: dict[str, Any]) -> Probe:
    """Build a transport from `budget`, ask whether it can answer, and close it.

    For Ollama this is one `GET /api/tags` (5 s cap): it lists the pulled models,
    so no model is loaded and no GPU is used. The backend's HTTP client is closed
    in `finally`, so a health check repeated every minute leaks nothing. Any
    other failure while asking counts as "unreachable"."""
    budget = budget or {}
    be = build(budget)
    try:
        try:
            ok = bool(be.available)
        except Exception:
            ok = False
            if not be.unavailable_code:
                be.unavailable_code = "unreachable"
        code = "" if ok else (be.unavailable_code or "unreachable")
        if isinstance(be, OllamaBackend):
            model = be.model_id
        else:
            model = str(budget.get("ollama_model") or "") if code != "off" else ""
        local = is_local(be)
        installed: Optional[bool] = None
        if local:
            try:
                installed = find_ollama(budget) is not None
            except Exception:
                installed = None
        return Probe(ok=ok, code=code, backend=be.name if code != "misconfigured"
                     else "unknown", model=model, local=local, installed=installed)
    finally:
        be.close()


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


# =============================================================================
# Q-126 / D-214: the app brings the local model up (ollama_autostart_design.md, ADR-0013)
#
# One service for every process that is about to use the model: is Ollama running,
# and if nothing listens, start it (never anything else), then check the model is
# pulled and, when asked, load it. It never pulls a model and never stops or kills
# an Ollama. Library defaults are off: `autostart` has no default here, and only
# `cli.py` turns it on, after `autostart_allowed_here` and the owner's switch.
# =============================================================================
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[2]    # src/jobscraper/backends.py -> the checkout


@dataclass(frozen=True)
class ModelReady:
    """What `ensure_model_running` found. `code` is one of "ready", "off",
    "not_running", "not_installed", "start_failed", "port_taken", "not_answering",
    "model_missing", "load_failed" or "cancelled" (`should_stop` turned true: no pause,
    the caller returns). `detail` is a model tag, a port number or fixed words, never
    a path or a URL (it reaches the owner's banner)."""
    code: str
    started: bool = False       # this call launched `ollama serve`
    detail: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code == "ready"


class _Stop(Exception):
    """`should_stop` turned true inside a wait (internal)."""


def running_from_worktree(source_dir: Optional[os.PathLike | str] = None) -> bool:
    """Whether this code runs from a git worktree, not the owner's main checkout.

    `source_dir` is the checkout the code was imported from (default: this file's
    repository root). A linked worktree has a `.git` FILE (a `gitdir:` pointer); the
    main checkout has a `.git` directory. The path test (`/.claude/worktrees/`)
    catches the agents' worktrees even when `.git` cannot be read. No `.git` at all
    (a plain copy) is not a worktree. (Moved here from `web/applyqueue.py`.)"""
    root = Path(source_dir) if source_dir is not None else _REPO_ROOT
    if "/.claude/worktrees/" in root.resolve().as_posix().lower() + "/":
        return True
    return (root / ".git").is_file()


def autostart_allowed_here(*, db_path: Any, env: Optional[Any] = None,
                           config_given: bool = False,
                           source_dir: Optional[os.PathLike | str] = None) -> bool:
    """May THIS process start an Ollama? (design §6 rule 6, C4.)

    `JOBSCRAPER_OLLAMA_AUTOSTART=0` is off and `=1` is allowed (the one-command-line
    override of the manual check; no code and no test ever sets it). Unset: allowed
    only on the repository's own data: `db_path` is the checkout's `data/jobscraper.db`
    (a `JOBSCRAPER_DB` copy or any test DB is not), no `JOBSCRAPER_CONFIG` and no
    `--config` (`config_given`), and the code does not run from a git worktree."""
    env = os.environ if env is None else env
    flag = str(env.get("JOBSCRAPER_OLLAMA_AUTOSTART", "")).strip()
    if flag in ("0", "1"):
        return flag == "1"
    if config_given or str(env.get("JOBSCRAPER_CONFIG", "")).strip():
        return False
    if running_from_worktree(source_dir):
        return False
    root = Path(source_dir) if source_dir is not None else _REPO_ROOT
    try:
        return Path(db_path).resolve() == (root / "data" / "jobscraper.db").resolve()
    except (OSError, TypeError, ValueError):
        return False


def autostart_switch(budget: dict[str, Any], get: Optional[Callable[[str], Any]] = None) -> bool:
    """The owner's switch "Start the local AI model when it is needed": the settings
    row `budget.ollama_autostart` (`get(key)`, the web's store lookup) over
    `budget.ollama_autostart` in config.yaml over the code default True. Only this
    boolean is ever read from the settings table (never `budget.ollama_path`)."""
    def _bool(v: Any) -> Optional[bool]:
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower() if v is not None else ""
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        return None
    if get is not None:
        try:
            stored = _bool(get("budget.ollama_autostart"))
        except Exception:
            stored = None
        if stored is not None:
            return stored
    cfg = _bool((budget or {}).get("ollama_autostart"))
    return True if cfg is None else cfg


def _is_windows() -> bool:
    return os.name == "nt"


def _ollama_file_ok(p: Path) -> bool:
    """A real file named exactly `ollama.exe` (Windows, any case) or `ollama` (elsewhere).
    A `.cmd`/`.bat` shim and the tray app `ollama app.exe` never count."""
    name = p.name.lower() if _is_windows() else p.name
    want = "ollama.exe" if _is_windows() else "ollama"
    try:
        return name == want and p.is_file()
    except OSError:
        return False


def find_ollama(budget: dict[str, Any], env: Optional[Any] = None, *,
                cwd: Optional[os.PathLike | str] = None,
                checkout: Optional[os.PathLike | str] = None) -> Optional[str]:
    """The Ollama program to start, or None (design §2, C3, R3).

    It never calls `shutil.which`: on Windows that searches the current directory
    first, so a planted `ollama.exe` there would run. Order:
      1. `budget.ollama_path` (config.yaml only; callers pass the file's budget, never
         one overlaid with settings rows). Set and failing the file rule -> None:
         fatal, never a fall-through to another program. It must be absolute.
      2. The default install locations of this platform.
      3. Each absolute `PATH` entry that is neither the current directory nor the
         checkout nor below the checkout.
    Every candidate is resolved first; a failing candidate in (2) or (3) is skipped."""
    env = os.environ if env is None else env
    configured = str((budget or {}).get("ollama_path") or "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            return None
        try:
            p = p.resolve()
        except (OSError, RuntimeError):
            return None
        return str(p) if _ollama_file_ok(p) else None

    cands: list[Path] = []
    if _is_windows():
        for var, rest in (("LOCALAPPDATA", ("Programs", "Ollama", "ollama.exe")),
                          ("ProgramFiles", ("Ollama", "ollama.exe"))):
            base = str(env.get(var, "")).strip()
            if base:
                cands.append(Path(base).joinpath(*rest))
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                  Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama")]
    else:
        cands += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]

    here = (Path(cwd) if cwd is not None else Path.cwd()).resolve()
    root = (Path(checkout) if checkout is not None else _REPO_ROOT).resolve()
    exe_name = "ollama.exe" if _is_windows() else "ollama"
    for entry in str(env.get("PATH", "")).split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not Path(entry).is_absolute():
            continue
        try:
            d = Path(entry).resolve()
        except (OSError, RuntimeError):
            continue
        if d == here or d == root or root in d.parents:
            continue
        cands.append(d / exe_name)

    for c in cands:
        try:
            c = c.resolve()
        except (OSError, RuntimeError):
            continue
        if _ollama_file_ok(c):
            return str(c)
    return None


# A fixed program text for the Windows launcher: it starts argv[1:] detached from every
# job tree, then exits. Cancel kills a job with `taskkill /T /F`, which walks parent
# PIDs; a server whose parent has already exited is outside every JobScraper tree.
_LAUNCHER = (
    "import subprocess, sys\n"
    "D = subprocess.DEVNULL\n"
    "F = 0x00000200 | 0x08000000 | 0x01000000\n"   # NEW_PROCESS_GROUP | NO_WINDOW | BREAKAWAY
    "kw = dict(stdin=D, stdout=D, stderr=D, close_fds=True)\n"
    "try:\n"
    "    subprocess.Popen(sys.argv[1:], creationflags=F, **kw)\n"
    "except OSError:\n"
    "    subprocess.Popen(sys.argv[1:], creationflags=F & ~0x01000000, **kw)\n"
)


def _launch_detached_windows(argv: list[str], env: dict[str, str]) -> None:
    """Run `_LAUNCHER` hidden and wait up to 15 s for it to exit 0 (it only starts the
    program). Raises OSError when it can't."""
    import subprocess
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", _LAUNCHER, *argv], env=env, shell=False,
        creationflags=0x08000000,                          # CREATE_NO_WINDOW
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True)
    try:
        rc = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        raise OSError("the launcher did not finish")
    if rc != 0:
        raise OSError(f"the launcher failed ({rc})")


def _spawn_detached(argv: list[str], env: dict[str, str]) -> None:
    """Start `argv` (always `[exe, "serve"]`) as a program JobScraper never kills.

    REFUSES (OSError, which the service reports as `start_failed`) before anything
    else when autostart is off here: `JOBSCRAPER_OLLAMA_AUTOSTART=0`, a loaded test
    runner, or (variable unset) a process that does not run on the repository's own
    data: a `JOBSCRAPER_DB` copy, `JOBSCRAPER_CONFIG`, or a git worktree (review C4).
    `JOBSCRAPER_OLLAMA_AUTOSTART=1` on one command line is the explicit override.
    No shell, hidden, no console, no admin."""
    flag = str(os.environ.get("JOBSCRAPER_OLLAMA_AUTOSTART", "")).strip()
    # `tests/run_tests.py` runs as `__main__`, so "run_tests" is never in sys.modules
    # under our own runner: its script name is checked too (review C4b).
    runner = Path(sys.argv[0] if sys.argv and sys.argv[0] else "").name.lower()
    if (flag == "0" or "run_tests" in sys.modules or "pytest" in sys.modules
            or runner in ("run_tests.py", "pytest", "pytest.exe")):
        raise OSError("autostart is off here")
    if flag != "1":
        db = (str(os.environ.get("JOBSCRAPER_DB", "")).strip()
              or str(_REPO_ROOT / "data" / "jobscraper.db"))
        if not autostart_allowed_here(db_path=db):
            raise OSError("autostart is off here")
    if _is_windows():
        _launch_detached_windows(list(argv), env)
        return
    import subprocess
    subprocess.Popen(list(argv), env=env, shell=False, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)


def _resolve_target(budget: dict[str, Any]) -> tuple[str, str]:
    """The URL and model tag exactly as `build` resolves them."""
    budget = budget or {}
    url = str(os.environ.get("JOBSCRAPER_OLLAMA_URL")
              or budget.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")
    return url, str(budget.get("ollama_model") or "qwen3:14b")


def _url_host_port(url: str) -> tuple[str, Optional[int]]:
    try:
        u = urlparse(url)
        return (u.hostname or ""), u.port
    except ValueError:
        return "", None


def _ping_try(client: Any, url: str, timeout: float = 5.0) -> str:
    """One `GET /api/version`: "ollama" (200 with a JSON `version` string), "refused"
    (ConnectError), "timeout" (any httpx timeout) or "other" (anything else)."""
    import httpx
    try:
        resp = client.get(f"{url}/api/version", timeout=timeout)
    except httpx.ConnectError:
        return "refused"
    except httpx.TimeoutException:
        return "timeout"
    except Exception:
        return "other"
    try:
        if resp.status_code == 200 and isinstance(resp.json().get("version"), str):
            return "ollama"
    except Exception:
        pass
    return "other"


def _stop_check(should_stop: Callable[[], bool]) -> None:
    if should_stop():
        raise _Stop()


def _ping(client: Any, url: str, sleep: Callable[[float], Any],
          should_stop: Callable[[], bool]) -> str:
    """Up to 3 tries, 1 s apart (C7); the first "ollama" wins at once. Three "refused"
    -> "refused", three "other" -> "other", three "timeout" or any mix -> "timeout"."""
    answers: list[str] = []
    for i in range(3):
        _stop_check(should_stop)
        a = _ping_try(client, url)
        if a == "ollama":
            return a
        answers.append(a)
        if i < 2:
            sleep(1.0)
    if all(a == "refused" for a in answers):
        return "refused"
    if all(a == "other" for a in answers):
        return "other"
    return "timeout"


def _lock_state(path: Path, *, wall: Callable[[], float],
                pid_alive: Optional[Callable[[int], bool]], max_age: float,
                seen: Optional[dict] = None,
                clock: Optional[Callable[[], float]] = None) -> str:
    """"missing", "stale" or "live" (C8). Stale at once when the creator is dead, or
    when the file holds no PID 2 s after it was made (by the file's age, or, in a
    caller that keeps `seen`, by how long WE have watched it unreadable); also when
    older than `max_age`."""
    try:
        age = wall() - path.stat().st_mtime
    except OSError:
        return "missing"
    if age > max_age:
        return "stale"
    try:
        pid: Optional[int] = int(path.read_text(encoding="ascii", errors="ignore").strip())
    except (OSError, ValueError):
        pid = None
    if pid is None:
        if age > 2.0:
            return "stale"
        if seen is not None and clock is not None:
            first = seen.setdefault("unreadable_since", clock())
            if clock() - first > 2.0:
                return "stale"
        return "live"
    if seen is not None:
        seen.pop("unreadable_since", None)
    if pid_alive is not None:
        try:
            if not pid_alive(pid):
                return "stale"
        except Exception:
            pass
    return "live"


def _lock_create(path: Path) -> str:
    """"ours" (made, holds our PID), "exists", or "unavailable" (the folder can't be
    written: go on without a lock rather than not start)."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return "exists"
    except OSError:
        return "unavailable"
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    finally:
        os.close(fd)
    return "ours"


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def ensure_model_running(
        budget: dict[str, Any], *, autostart: bool, backend: Optional[Backend] = None,
        load: bool = False, keep_alive: Any = None,
        on_state: Optional[Callable[[str], Any]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        start_wait_s: float = 60.0, load_wait_s: float = 330.0,
        spawn: Optional[Callable[[list[str], dict[str, str]], Any]] = None,
        find: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
        http: Any = None, pid_alive: Optional[Callable[[int], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        lock_dir: Optional[os.PathLike | str] = None,
        wall: Callable[[], float] = time.time) -> ModelReady:
    """Make sure the local model answers, starting Ollama only when nothing listens.

    Steps (design §2): ping (3 tries); a start only after the port REFUSED three
    times, only for a local URL with an explicit port, only the program `find_ollama`
    names, under a per-port lock file holding the creator's PID; wait up to
    `start_wait_s` for it to answer; check the model tag is pulled (never pull);
    reset `backend`'s cached probe; when `load`, load the model (`backend.warm`, at
    most `load_wait_s`). A server that answers, however slowly, is alive: never
    restarted. Never stops or kills Ollama.

    `should_stop` is polled at least every 2 s in every wait; true returns
    `ModelReady("cancelled")` at once (a lock we hold is released). `on_state` hears
    "starting" and "loading". The seams (`spawn`, `find`, `http`, `pid_alive`, `clock`,
    `sleep`, `lock_dir`, `wall`) let a test drive it with fakes; `wall` is the wall
    clock for the lock file's age."""
    t0 = clock()
    on_state = on_state or (lambda s: None)
    should_stop = should_stop or (lambda: False)
    st = {"started": False, "owned": False}     # shared with `bring_up`
    lock_path: list[Path] = []

    def done(code: str, detail: str = "") -> ModelReady:
        return ModelReady(code, st["started"], detail, round(max(0.0, clock() - t0), 1))

    if configured_code(budget):
        return done("off")
    url, model = _resolve_target(budget)
    if isinstance(backend, OllamaBackend):
        url, model = backend.url, backend.model_id
    owns_http = http is None
    if owns_http:
        import httpx
        http = httpx.Client(timeout=5.0)

    def bring_up() -> Optional[ModelReady]:
        """Ping; start when nothing listens; wait. None = the server answers."""
        answer = _ping(http, url, sleep, should_stop)
        if answer == "ollama":
            return None
        host, port = _url_host_port(url)
        if answer == "other":
            return done("port_taken", str(port or ""))
        if answer == "timeout":
            return done("not_answering")
        # refused three times: may we start it?
        if not autostart or not _target_is_local(url, model) or port is None or not host:
            return done("not_running")
        exe = (find or find_ollama)(budget)
        if not exe:
            return done("not_installed", model)
        env = dict(os.environ)
        env["OLLAMA_HOST"] = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        do_spawn = spawn or _spawn_detached
        max_age = start_wait_s + 30.0
        lp = Path(lock_dir if lock_dir is not None else tempfile.gettempdir()) \
            / f"jobscraper-ollama-{port}.lock"
        lock_path.append(lp)

        seen: dict = {}

        def take() -> str:
            """"ours" / "unavailable" (we may start) or "held" (a live creator)."""
            r = _lock_create(lp)
            if r == "exists" and _lock_state(lp, wall=wall, pid_alive=pid_alive,
                                             max_age=max_age, seen=seen,
                                             clock=clock) in ("stale", "missing"):
                _unlink(lp)
                r = _lock_create(lp)
            if r == "ours":
                st["owned"] = True
            return "held" if r == "exists" else r

        def start() -> Optional[ModelReady]:
            on_state("starting")
            try:
                do_spawn([exe, "serve"], env)
            except OSError:
                return done("start_failed", "the program wouldn't start")
            st["started"] = True
            return None

        waiter = take() == "held"
        if waiter:
            on_state("starting")        # someone else is starting it: only wait
        else:
            again = _ping(http, url, sleep, should_stop)    # started a moment ago?
            if again == "ollama":
                return None
            if again == "other":
                return done("port_taken", str(port))
            if again == "timeout":
                return done("not_answering")
            bad = start()
            if bad:
                return bad
        delay = 0.5
        deadline = clock() + start_wait_s
        while True:
            _stop_check(should_stop)
            last = _ping_try(http, url, timeout=2.0)
            if last == "ollama":
                return None
            if waiter and last == "refused" and _lock_state(
                    lp, wall=wall, pid_alive=pid_alive, max_age=max_age, seen=seen,
                    clock=clock) in ("missing", "stale"):
                # the creator vanished: take over, once
                _unlink(lp)
                if take() != "held":
                    waiter = False
                    bad = start()
                    if bad:
                        return bad
                    deadline = clock() + start_wait_s
            if clock() >= deadline:
                if last == "other":
                    return done("port_taken", str(port))
                if last == "timeout":
                    return done("not_answering")
                return done("start_failed", f"no answer after {int(start_wait_s)} seconds")
            sleep(delay)
            delay = min(delay * 2, 2.0)

    try:
        try:
            bad = bring_up()
            if bad:
                return bad
            # The server answers: forget the cached "not reachable", then check the model.
            if backend is not None and hasattr(backend, "reset_probe"):
                backend.reset_probe()
            _stop_check(should_stop)
            missing = _model_missing(http, url, model)
            if missing:
                return done(missing, model if missing == "model_missing" else "")
            if load:
                failed = _load_model(budget, backend, keep_alive, load_wait_s, on_state,
                                     should_stop, clock, sleep)
                if failed:
                    return done(failed, model)
            return done("ready")
        except _Stop:
            return done("cancelled")
    finally:
        if st["owned"] and lock_path:
            _unlink(lock_path[0])
        if owns_http:
            try:
                http.close()
            except Exception:
                pass


def _model_missing(http: Any, url: str, model: str) -> str:
    """"" when `/api/tags` lists the model; "model_missing" when it doesn't;
    "not_answering" when the list itself can't be read. Never pulls anything."""
    try:
        resp = http.get(f"{url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        names = {m.get("name", "") for m in resp.json().get("models", [])}
    except Exception:
        return "not_answering"
    wanted = model if ":" in model else f"{model}:latest"
    return "" if wanted in names else "model_missing"


def _load_model(budget: dict[str, Any], backend: Optional[Backend], keep_alive: Any,
                load_wait_s: float, on_state: Callable[[str], Any],
                should_stop: Callable[[], bool], clock: Callable[[], float],
                sleep: Callable[[float], Any] = time.sleep) -> str:
    """Load the model in a daemon thread so `should_stop` is polled while it loads.
    Returns "" when loaded, "load_failed" when the load failed or ran past
    `load_wait_s` (+5 s); raises `_Stop` when `should_stop` turned true (the request
    may finish in its thread; the process is about to exit)."""
    own: Optional[Backend] = None
    be = backend
    if be is None:
        be = own = build(budget)
    on_state("loading")
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            warm(be, keep_alive, timeout=load_wait_s)
        except BaseException as exc:    # a transport error: reported as load_failed
            box["error"] = exc

    th = threading.Thread(target=run, name="ollama-load", daemon=True)
    deadline = clock() + load_wait_s + 5.0
    th.start()
    try:
        while th.is_alive():
            _stop_check(should_stop)
            if clock() >= deadline:
                return "load_failed"
            th.join(0.05)
            if th.is_alive():
                sleep(0.5)          # the seam, so a fake clock moves while it loads
    finally:
        if own is not None and not th.is_alive():
            own.close()
    return "load_failed" if "error" in box else ""
