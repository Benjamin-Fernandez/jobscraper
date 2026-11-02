"""Shared helpers for the D-78 llm_fill oracles (Q-35 WP-T1; not a test file).

FakeFillBackend: a scripted local model. ASSUMED call shapes (tester outbox TR-4, review M6),
one place to change when lane M pins them:
  * the user prompt holds `FIELDS (JSON):` followed by one JSON value: a list of field views, or
    an object keyed by field id; each view has `id`, `question`, optional `group_title`,
    `site_error`. A reply key is `"<group_title>|<question>"` ("" outside entries), so replies
    don't depend on the reader's random ids or on call order;
  * the call kind comes from the system prompt (llm_fill.PICK_SYSTEM / RECHECK_SYSTEM when the
    module exports them, else the phrases below), temperature 0.7 (second opinion), a field view
    with `site_error` (corrective) or `RESUME ENTRY` in the user prompt (entry);
  * pick / recheck replies are the reply entry's `raw` object, JSON-encoded as is.
Reply entries: {"kind", "reply": {key: decision}} | {"kind", "match": "<text in the user prompt>",
"raw": {...}} | plus "raise": "BackendError"|"timeout", "done_reason": "length", "text": "<raw>".
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
import threading
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jobscraper.backends import Backend, BackendError, Completion  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "apply" / "llm_fill"
SAMPLE = ROOT / "tests" / "fixtures" / "apply" / "applicant.sample.yaml"
KINDS = ("page", "entry", "pick", "recheck", "second", "corrective")
SOURCES = ("profile", "extra", "standing", "resume", "job", "keep", "unknown")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _system_constants() -> dict[str, str]:
    try:
        m = importlib.import_module("jobscraper.apply.llm_fill")
    except ModuleNotFoundError:
        return {}
    return {k: getattr(m, a) for k, a in (("pick", "PICK_SYSTEM"), ("recheck", "RECHECK_SYSTEM"))
            if isinstance(getattr(m, a, None), str)}


def field_views(user: str) -> list[dict]:
    """The field views of the FIELDS (JSON) block (ASSUMED layout, see the module docstring)."""
    i = user.find("FIELDS (JSON):")
    if i < 0:
        return []
    j = user.find("[", i)
    k = user.find("{", i)
    starts = [x for x in (j, k) if x >= 0]
    if not starts:
        return []
    val, _ = json.JSONDecoder().raw_decode(user[min(starts):])
    if isinstance(val, dict):
        val = [dict(v, id=v.get("id", key)) for key, v in val.items()]
    return [v for v in val if isinstance(v, dict)]


def view_key(v: dict) -> str:
    return f'{norm(v.get("group_title", ""))}|{norm(v.get("question", v.get("label", "")))}'


@dataclass
class FakeCall:
    kind: str
    system: str
    user: str
    format: Any
    kwargs: dict
    keys: tuple[str, ...]
    prompt_hash: str


@dataclass
class FakeFillBackend(Backend):
    replies: list[dict] = field(default_factory=list)
    strict: bool = True
    calls: list[FakeCall] = field(default_factory=list)
    used: set = field(default_factory=set)
    name: str = "fake"
    model_id: str = "fake-fill:1"

    @property
    def available(self) -> bool:
        return True

    @classmethod
    def from_file(cls, path: Path, **kw) -> "FakeFillBackend":
        return cls(replies=json.loads(Path(path).read_text(encoding="utf-8"))["calls"], **kw)

    def kind_of(self, system: str, user: str, temperature: Optional[float], views: list[dict]) -> str:
        consts = _system_constants()
        if consts.get("pick") and system.strip() == consts["pick"].strip():
            return "pick"
        if consts.get("recheck") and system.strip() == consts["recheck"].strip():
            return "recheck"
        low = system.lower()
        if "pick the one option" in low:
            return "pick"
        if "belongs to entry" in (low + user.lower()) and len(views) <= 1:
            return "recheck"
        if temperature is not None and abs(temperature - 0.7) < 1e-9:
            return "second"
        if any(v.get("site_error") for v in views):
            return "corrective"
        if "RESUME ENTRY" in user:
            return "entry"
        return "page"

    def complete(self, system: str, user: str, max_tokens: int = 4096, schema: Optional[dict] = None,
                 timeout: Optional[float] = None, *, format: Optional[dict] = None,
                 temperature: Optional[float] = None, seed: Optional[int] = None, **kw) -> Completion:
        views = field_views(user)
        kind = self.kind_of(system, user, temperature, views)
        keys = tuple(view_key(v) for v in views)
        self.calls.append(FakeCall(kind, system, user, format if format is not None else schema,
                                   dict(kw, max_tokens=max_tokens, timeout=timeout, temperature=temperature,
                                        seed=seed), keys,
                                   hashlib.sha256((system + user).encode("utf-8")).hexdigest()[:16]))
        entry = self._match(kind, user, keys)
        if entry is None:
            if self.strict:
                raise AssertionError(f"FakeFillBackend: no reply for a {kind} call on {list(keys) or user[-200:]}")
            return Completion(text="{}", done_reason="stop")
        if entry.get("raise") == "timeout":
            raise TimeoutError("fake model timed out")
        if entry.get("raise"):
            raise BackendError("fake model unavailable")
        if "text" in entry:
            text = entry["text"]
        elif "raw" in entry:
            text = json.dumps(entry["raw"])
        else:
            by_key = entry["reply"]
            text = json.dumps({v["id"]: by_key[view_key(v)] for v in views if view_key(v) in by_key})
        return Completion(text=text, input_tokens=len(user) // 4, output_tokens=len(text) // 4,
                          done_reason=entry.get("done_reason", "stop"))

    def _match(self, kind: str, user: str, keys: tuple[str, ...]) -> Optional[dict]:
        for i, e in enumerate(self.replies):
            if (i in self.used and not e.get("repeat")) or e.get("kind", "page") != kind:
                continue
            if "match" in e:
                ok = e["match"] in user
            else:
                ok = bool(set(keys) & set(e.get("reply", {}))) or (not keys and not e.get("reply"))
            if ok:
                self.used.add(i)
                return e
        return None

    # ---- what the model saw
    def prompts_text(self) -> str:
        return "\n".join(c.system + "\n" + c.user + "\n" + json.dumps(c.format, ensure_ascii=False)
                         for c in self.calls)

    def assert_no_secrets(self, deny: Iterable[str]) -> None:
        leaks = find_secrets(self.prompts_text(), deny)
        assert not leaks, f"S values reached a prompt: {len(leaks)} hit(s)"   # never print the values


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def find_secrets(text: str, deny: Iterable[str]) -> list[str]:
    """Deny-list entries present in `text` (case-insensitive; numbers also as digits only)."""
    low, digits = text.lower(), _digits(text)
    hits = []
    for d in deny:
        d = (d or "").strip()
        if len(d) < 3:
            continue
        if d.lower() in low or (len(_digits(d)) >= 6 and _digits(d) == re.sub(r"\D", "", d) and _digits(d) in digits):
            hits.append(d)
    return hits


def sample_secrets(profile: Optional[dict] = None, account_email: str = "") -> list[str]:
    """Every S-path value of the sample profile worth scanning for (AD §5.3), in the forms a
    prompt could carry it. Enum codes (decline, citizen, completed) are not scanned: they are
    ordinary words that options legitimately contain."""
    p = profile or yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    c, i, s = p["contact"], p["identity"], p["singapore_status"]
    out = [c["email"], c["phone_number"], c["phone_country_code"] + c["phone_number"],
           c["phone_country_code"] + " " + c["phone_number"][:4] + " " + c["phone_number"][4:],
           c["address_line1"], c["address_line2"], c["postal_code"], i["date_of_birth"], s.get("nric_last4") or "",
           s.get("ord_date") or "", account_email]
    y, m, d = i["date_of_birth"].split("-")
    out += [f"{d}/{m}/{y}", f"{int(d)}/{int(m)}/{y}", f"{m}/{d}/{y}"]
    return [x for x in out if x]


# ---- fixtures on disk
def steps(tenant: str) -> list[Path]:
    return sorted(p for p in (FIX / tenant).iterdir() if p.is_dir())


def load_step(step_dir: Path) -> tuple[Path, list[dict], list[dict]]:
    return (step_dir / "page.html", json.loads((step_dir / "fields.json").read_text(encoding="utf-8")),
            json.loads((step_dir / "reply.json").read_text(encoding="utf-8"))["calls"])


class FixtureDir:
    """Serves tests/fixtures/apply/llm_fill on 127.0.0.1 (port 0) for one `with` block."""

    def __init__(self, root: Path = FIX):
        self.root = root
        self.httpd: Optional[ThreadingHTTPServer] = None

    def __enter__(self) -> "FixtureDir":
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401
                pass
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(self.root)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def url(self, rel: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/{rel}"

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def browser_page():
    """(playwright, browser, page) with headless Edge, or None when unavailable. Caller closes."""
    try:
        from apply_flow_support import edge_available
        if not edge_available():
            return None
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        b = pw.chromium.launch(channel="msedge", headless=True)
        return pw, b, b.new_page()
    except Exception as exc:          # never fake a pass: say why
        print(f"  note: browser not available ({type(exc).__name__}); browser tests not run")
        return None
