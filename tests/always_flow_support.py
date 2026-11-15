"""Harness for the Q-121 flow oracles (tests/test_always_flow.py; not a test file).

The seam (llm_first_fill_design §13, rev L4): a REAL `OllamaBackend` whose address is
127.0.0.1:11434, so `backends.is_local` is true, but whose client is an `httpx.MockTransport`
scripted per test. Nothing reaches a model or a network. Every request is recorded, so a test
can look at every body that would have left the machine.

The page is scripted: `apply_flow.fill_page` is replaced by a function that either returns a
`PageOutcome` or runs the REAL `always.fill_page_always` over synthetic `PageField`s with an
`ask` that goes through the real backend (so the prompt check, the briefing and the fallback
limits are the shipped code). The ATS is `FakeNav` of test_apply_flow_n6a.py; the browser is
the fake session. A test config replaces the whole `apply:` block (apply_flow_support).

Nothing here can start a real application: the navigator's `submit` only counts, the backend is
a mock, the DB is a temp file, the employer is "Example Co".
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import (  # noqa: E402
    EMAIL, FakeBrowserFactory, Say, add_job, make_world, page_signals, registered,
)

import httpx  # noqa: E402

from jobscraper import apply_flow, backends  # noqa: E402
from jobscraper.apply import always as AL  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerStatus, AnswerTier, FieldType, FormField, PageField, PageOutcome, PasswordRules,
    Secret, StepResult, Tenant, ValueOrigin,
)
from jobscraper.backends import OllamaBackend  # noqa: E402

NOW = 1_793_700_000.0
MODEL = "qwen3:14b"
MODELS = (MODEL, "qwen3:cloud", "gpt-oss:120b-cloud")      # what the mock Ollama "has pulled"
FIELDS_HEAD = "== FIELDS (JSON) =="
HOST = "fake.example.com"


# ------------------------------------------------------------------ the scripted Ollama

class Net:
    """The MockTransport handler. `.log` = [(method, path, body_text)] of every request.
    `chat(body)` -> httpx.Response overrides the reply of /api/chat; `down` makes the model
    routes (/api/chat, /api/generate) answer 500; `warm_ok` keeps the warm-up working while
    `down` is set (a warm-up has num_predict 1)."""

    def __init__(self, chat=None, *, down=False, warm_ok=False):
        self.log: list[tuple[str, str, str]] = []
        self.chat, self.down, self.warm_ok = chat, down, warm_ok

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", "replace") if request.content else ""
        self.log.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in MODELS]})
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": []})
        if path in ("/api/chat", "/api/generate"):
            warm = False
            try:
                warm = int((json.loads(body).get("options") or {}).get("num_predict", 0)) == 1
            except ValueError:
                pass
            if self.down and not (self.warm_ok and warm):
                return httpx.Response(500, text="model gone")
            if self.chat is not None and not warm:
                return self.chat(json.loads(body))
            return httpx.Response(200, json={"message": {"content": "{}"}, "done_reason": "stop"})
        return httpx.Response(404)

    @property
    def model_requests(self) -> list[tuple[str, str, str]]:
        return [r for r in self.log if r[1] in ("/api/chat", "/api/generate")]

    @property
    def chats(self) -> list[dict]:
        return [json.loads(b) for _m, p, b in self.log if p == "/api/chat"]

    def carries(self, *needles: str) -> bool:
        """True when ANY recorded request body holds one of the needles."""
        return any(n and n in b for _m, _p, b in self.log for n in needles)


def backend(net: Net, url: str = "http://127.0.0.1:11434", model: str = MODEL) -> OllamaBackend:
    return OllamaBackend(url, model, client=httpx.Client(transport=httpx.MockTransport(net)))


def forms(secret: str) -> tuple[str, ...]:
    """The ways a registered secret can show up: as written and JSON-escaped."""
    return (secret, json.dumps(secret)[1:-1])


def answering(basis: str = "assumption", value: str = "Dummy answer"):
    """A `chat` for Net: answer every field of a FIELDS call as an assumption."""
    def chat(body: dict) -> httpx.Response:
        user = body["messages"][-1]["content"]
        i = user.find(FIELDS_HEAD)
        out: dict = {}
        if i >= 0:
            views = json.JSONDecoder().raw_decode(user[i + len(FIELDS_HEAD) + 1:])[0]
            for v in views:
                out[v["id"]] = {"value": value, "basis": basis, "ref": "", "assumed": basis == "assumption",
                                "reason": "dummy"}
        return httpx.Response(200, json={"message": {"content": json.dumps(out)}, "done_reason": "stop"})
    return chat


# ------------------------------------------------------------------ the ATS and the pages

def _u():
    import test_apply_flow_n6a as U
    return U


def nav_class():
    U = _u()

    class Nav(U.FakeNav):
        """FakeNav that counts submits (the only thing that would send an application)."""

        def __init__(self, steps=("one", "review"), wall=()):
            super().__init__(steps)
            self.submits = 0
            self.wall = list(wall)
            self.signed_up: list[str] = []
            self.signed_in: list[str] = []
            self.needs_account = bool(wall)

        def tenant_from_company(self, job):
            return Tenant("fakenav", HOST, "exampleco", posting_id="1")

        def account_wall(self, page):
            return self.wall.pop(0) if self.wall else None

        def sign_up(self, page, ctx, password):
            self.signed_up.append(password.reveal() if hasattr(password, "reveal") else password)
            return "created"

        def sign_in(self, page, ctx, password):
            self.signed_in.append(password.reveal() if hasattr(password, "reveal") else password)

        def submit(self, page, ctx):
            self.submits += 1

    return Nav


def make(n: int = 1, *, profile=None):
    """(world, company_id, [job ids]) with `n` to_apply jobs at Example Co."""
    w = make_world(profile=profile)
    cid, j1 = add_job(w.store, key="exampleco", name="Example Co", provider="fakenav",
                      slug="exampleco", external_id="1", url="https://fake.example.com/jobs/1")
    jobs = [j1]
    for i in range(2, n + 1):
        jobs.append(add_job(w.store, key="exampleco", name="Example Co", provider="fakenav",
                            slug="exampleco", external_id=str(i), company_id=cid,
                            url=f"https://fake.example.com/jobs/{i}")[1])
    for j in jobs:
        w.store.set_application_status(j, "to_apply")
    w.store.commit()
    return w, cid, jobs


def acfg_for(w, **over):
    base = dict(dry_run_hold_s=0, confirm_timeout_s=0, daily_cap=0, per_employer_daily_cap=0, fill="llm",
                always_available=True)       # D-223: the release lock is open for these suites; tests/test_always_lock.py pins it shut
    return dataclasses.replace(w.cfg.apply, **{**base, **over})


def page(step: str = "one", n: int = 1, *, prefix: str = "f") -> PageOutcome:
    """An ordinary scripted page: n fields, each answered from the profile."""
    U = _u()
    fields = [U.pf(f"{prefix}{i}", f"Field {prefix}{i}") for i in range(n)]
    return U.outcome(step, fields)


@contextlib.contextmanager
def scripted(script):
    """Replace `apply_flow.fill_page`; `script(nav, services, ctx, rctx)` -> PageOutcome (it may
    raise AlwaysStop). Records the contexts it was called with in `.calls`."""
    calls: list[dict] = []

    def fake(pg, nav, ctx, rctx, services):
        calls.append({"step": nav.step_id(pg, ctx), "rctx": rctx, "services": services, "job": ctx.job["job_id"]})
        return script(nav, services, ctx, rctx)
    saved = apply_flow.fill_page
    apply_flow.fill_page = fake
    try:
        yield calls
    finally:
        apply_flow.fill_page = saved


@contextlib.contextmanager
def scan(hits=()):
    """Stand in for `page.scan_required` (the reader needs a real DOM): `hits` is a tuple, or a
    callable(call_no) -> tuple. `.n` counts the scans."""
    from jobscraper.apply import page as P
    saved = P.scan_required
    state = type("S", (), {"n": 0})()

    def fake(pg, scope=""):
        state.n += 1
        return tuple(hits(state.n) if callable(hits) else hits)
    P.scan_required = fake
    try:
        yield state
    finally:
        P.scan_required = saved


def run_batch(w, jids, nav, be, script=None, *, dry_run=True, signals=(), hits=(), **acfg):
    """apply_flow.run over the fakes. Returns (results, browser factory, log)."""
    factory, say = FakeBrowserFactory(), Say()
    with registered(nav), page_signals(*signals), scripted(script or (lambda n, s, c, r: page())) as calls, \
            scan(hits):
        res = apply_flow.run(w.cfg, w.store, list(jids), dry_run=dry_run, backend=be, http=object(),
                             browser_factory=factory, apply_cfg=acfg_for(w, **acfg), say=say,
                             evidence_dir=w.tmp / "evidence", now=lambda: NOW)
    say.calls = calls
    return res, factory, say


def ready_ensurer(code: str = "ready", *, calls: list | None = None):
    """A scripted `model_ensurer` (the Q-126 seam, ollama_autostart_design §6 rule 7): it answers
    `backends.ModelReady(code)` at once and never touches a socket. `calls` records the keywords."""
    def ensurer(budget, **kw):
        if calls is not None:
            calls.append(kw)
        return backends.ModelReady(code, started=False, detail="d" if code != "ready" else "")
    return ensurer


def run_q(w, cid, jobs, nav, be, script=None, *, item_mode="dry_run", force=False, ensurer=None, **acfg):
    """apply_flow.run_queue over the fakes: the jobs are queued, then the worker drains them.

    `be` is a real `OllamaBackend` over a mock transport, so since Q-126 the worker's precheck
    would call `backends.ensure_model_running` and ping the REAL port 11434. `ensurer` is the
    injected model service: default `ready_ensurer()` ("ready"); pass `ready_ensurer("not_running")`
    (or any not-ready code) to test the pause. `tests/test_no_real_model_port.py` guards this."""
    from jobscraper.store import utcnow
    for j in jobs:
        assert w.store.queue_add(j, cid, item_mode, "inbox", utcnow()) is not None
    w.store.commit()
    factory, say = FakeBrowserFactory(), Say()
    cfg = acfg_for(w, **acfg)
    with registered(nav), page_signals(), scripted(script or (lambda n, s, c, r: page())) as calls, scan(()):
        out = apply_flow.run_queue(w.cfg, w.store, backend=be, apply_cfg_fn=lambda: cfg, http=object(),
                                   browser_factory=factory, say=say, evidence_dir=w.tmp / "evidence",
                                   force_dry_run=force, model_ensurer=ensurer or ready_ensurer())
    say.calls = calls
    return out, factory, say


# ------------------------------------------------------------------ real always.py pages

def req_numbers(prefix: str, n: int, step: str = "one") -> list[PageField]:
    """n REQUIRED number fields no profile row answers: with a model that says nothing, each one
    ends in a last-resort guess (F2-F6)."""
    import llm_fill_t2 as T
    return [T.pf(f"{prefix}{i}", f"Dummy count question {prefix}{i}: how many widgets?", FieldType.NUMBER,
                 required=True) for i in range(n)]


def real_page(fields, step: str, *, ask_wrap=None):
    """A scripted page that runs the REAL `always.fill_page_always` over `fields` with an `ask`
    through the services' backend (so the prompt check and the model route are the shipped ones)."""
    def script(nav, services, ctx, rctx):
        ask = AL.backend_ask(services.backend)
        if ask_wrap is not None:
            ask = ask_wrap(ask)
        return AL.fill_page_always(list(fields), brief=services.briefing, rctx=rctx, ask=ask,
                                   rules=services.rules, today=services.today(), cfg=services.cfg,
                                   step_title=step,
                                   attempt_fallbacks=int(getattr(services, "attempt_fallbacks", 0) or 0))
    return script


def stop_with(reason, detail, **kw):
    """A scripted page that stops the way always.fill_page_always does."""
    def script(nav, services, ctx, rctx):
        raise AL.AlwaysStop(reason, detail, **kw)
    return script


def row_of(w, attempt_id: int) -> dict:
    return w.store.attempt(attempt_id)


def put_account(w, nav, email: str, secret: str) -> str:
    """A vault entry (in-memory keyring: call inside `memory_keyring()`) plus the account row."""
    from jobscraper import vault
    service = vault.service_for(nav.name, HOST)
    vault.put(service, email, Secret(secret))
    w.store.upsert_account(nav.name, HOST, email, service, "created")
    return service
