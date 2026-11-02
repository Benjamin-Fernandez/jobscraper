"""Helpers for the lane-B apply tests (flow, CLI, e2e, Greenhouse fill). Not a test file:
the runner ignores it. Test files do `sys.path.insert(0, str(Path(__file__).parent))` first.

What is here:
  make_world()       a temp Config / Store / applicant profile / resume (nothing under data/)
  add_job()          a company + job row the flow can read
  FakeAdapter etc.   a scripted ATS adapter, fake page and fake browser session (flow unit tests)
  FixtureServer      a local http.server that stands in for the Greenhouse board and API
  EdgeSession        a headless Edge session that snapshots each page just before it closes
No network beyond 127.0.0.1; no model; synthetic applicant only.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper import applicant  # noqa: E402
from jobscraper.apply.classify import PageSignal  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus, ApplyFailure, Canonical, FieldType, FormField, FormPlan, Option, PasswordRules,
    StepResult, Tenant,
)
from jobscraper.config import Config  # noqa: E402
from jobscraper.models import RawJob  # noqa: E402
from jobscraper.store import Store  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "apply"
GH = FIX / "greenhouse"
SAMPLE = FIX / "applicant.sample.yaml"
RESUME_BYTES = b"%PDF-1.4\n% synthetic resume for tests\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

EMAIL = "alex.testcase@example.com"


# ---------------------------------------------------------------- world

@dataclass
class World:
    tmp: Path
    cfg: Config
    store: Store
    profile: dict
    cfg_path: Path
    resume: Optional[Path]

    @property
    def db_path(self) -> Path:
        return self.cfg.db_path

    def close(self) -> None:
        self.store.close()

    def attempt_rows(self) -> list[dict]:
        rows = self.store.conn.execute("SELECT id FROM apply_attempts ORDER BY id").fetchall()
        return [self.store.attempt(r[0]) for r in rows]

    def answers_by_key(self, attempt_id: int) -> dict[str, dict]:
        return {a["field_key"]: a for a in self.store.answers(attempt_id)}


def sample_profile(**contact) -> dict:
    p = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    p["contact"].update(contact)
    return p


def make_world(*, applicant_file: bool = True, resume: bool = True, tailor: bool = False,
               apply_block: Optional[dict] = None, profile: Optional[dict] = None) -> World:
    """A temp world. `applicant_file=False` = no applicant.yaml (profile_incomplete);
    `resume=False` = no resume file. Config is built in memory AND written to
    `config.yaml` (the CLI tests pass it with --config)."""
    saved = os.environ.pop("JOBSCRAPER_DB", None)        # never let a shell override the temp DB
    tmp = Path(tempfile.mkdtemp(prefix="apply_t_"))
    if saved is not None:
        os.environ["JOBSCRAPER_DB"] = saved
    data = tmp / "data"
    data.mkdir()
    prof = profile if profile is not None else sample_profile()
    if applicant_file:
        (data / "applicant.yaml").write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8")
    res = None
    if resume:
        res = data / "resume.pdf"
        res.write_bytes(RESUME_BYTES)
    (tmp / "watchlist.yaml").write_text("version: 1\ncompanies: []\n", encoding="utf-8")
    (tmp / "overrides.yaml").write_text("", encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    raw["paths"].update(
        watchlist=str(tmp / "watchlist.yaml"), rules=str(ROOT / "config" / "rules.yaml"),
        profile=str(data / "profile.derived.yaml"), profile_overrides=str(tmp / "overrides.yaml"),
        resume_dir=str(data), db=str(data / "jobscraper.db"), shortlist=str(data / "shortlist.json"),
        applicant=str(data / "applicant.yaml"), questions=str(ROOT / "config" / "questions.yaml"),
        aliases=str(ROOT / "config" / "aliases.yaml"), master_resume=str(data / "master_resume.json"),
        tailored_dir=str(data / "tailored"))
    raw["budget"].update(enable_llm=False, backend="off")
    raw["tailor"] = {**(raw.get("tailor") or {}), "enabled": bool(tailor)}
    raw["apply"] = dict(apply_block or {})
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = Config(raw)
    return World(tmp=tmp, cfg=cfg, store=Store(cfg.db_path), profile=prof, cfg_path=cfg_path,
                 resume=res)


def add_job(store: Store, *, key="dataiku", name="Dataiku", provider="greenhouse", slug="dataiku",
            external_id="6237419004", title="Senior Manager, Global Benefits", url=None,
            description="Plan and run global benefits programmes.",
            company_id: Optional[int] = None) -> tuple[int, str]:
    """(company_id, job_id). Reuses the company row when `company_id` is given."""
    if company_id is None:
        company_id = store.insert_company(key, name, f"https://{key}.example/careers",
                                          provider=provider, slug=slug)
    raw = RawJob(external_id, title,
                 url or f"https://job-boards.greenhouse.io/{slug}/jobs/{external_id}",
                 "Singapore", description=description)
    job_id = raw.job_id(company_id, provider)
    store.upsert_job(job_id, company_id, raw, 1, True)
    store.commit()
    return company_id, job_id


class Say:
    """A log sink: `.lines`, `.text`."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(str(line))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class NoModel:
    """A backend that is not there: tier 5 must not run."""
    available = False
    name = "none"
    model_id = ""

    def complete(self, *a, **k):
        raise AssertionError("the model must not be called")


# ---------------------------------------------------------------- fake adapter / page / session

def default_fields() -> list[FormField]:
    """Four tier-1 fields a sample profile can answer, one file (the resume)."""
    return [
        FormField("first_name", "First Name", FieldType.TEXT, True, canonical=Canonical.FIRST_NAME,
                  section="questions"),
        FormField("last_name", "Last Name", FieldType.TEXT, True, canonical=Canonical.LAST_NAME,
                  section="questions"),
        FormField("email", "Email", FieldType.TEXT, True, canonical=Canonical.EMAIL,
                  section="questions"),
        FormField("phone", "Phone", FieldType.TEXT, True, canonical=Canonical.PHONE,
                  section="questions"),
        FormField("resume", "Resume/CV", FieldType.FILE, True, canonical=Canonical.RESUME,
                  section="questions"),
    ]


def unknown_required(key="question_1", label="What was the name of your first pet?") -> FormField:
    """A required free-text question no tier answers when the model is off."""
    return FormField(key, label, FieldType.TEXT, True, section="questions")


def unknown_optional(key="question_2", label="What was the name of your first pet?") -> FormField:
    return FormField(key, label, FieldType.TEXT, False, section="questions")


class FakePage:
    """Just enough page for apply_flow: a URL, screenshots, HTML, close."""

    def __init__(self, url: str = "https://fake.example.com/apply") -> None:
        self.url = url
        self.closed = False

    def screenshot(self, path: str, full_page: bool = True) -> None:
        Path(path).write_bytes(b"\x89PNG fake")

    def content(self) -> str:
        return "<html><body>fake page</body></html>"

    def close(self) -> None:
        self.closed = True

    def wait_for_timeout(self, ms: float) -> None:
        pass


class FakeSession:
    def __init__(self, acfg: Any) -> None:
        self.acfg = acfg
        self.pages: list[FakePage] = []
        self.holds: list[float] = []
        self.closed = False

    def new_page(self) -> FakePage:
        p = FakePage()
        self.pages.append(p)
        return p

    def hold(self, seconds: float) -> None:
        self.holds.append(seconds)

    def close(self) -> None:
        self.closed = True


class FakeBrowserFactory:
    """`browser_factory` for apply_flow.run: counts how often the browser was started."""

    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self, acfg: Any) -> FakeSession:
        s = FakeSession(acfg)
        self.sessions.append(s)
        return s

    @property
    def started(self) -> int:
        return len(self.sessions)

    @property
    def pages(self) -> list[FakePage]:
        return [p for s in self.sessions for p in s.pages]


class FakeAdapter:
    """A scripted AtsAdapter named `fakeats` (REGISTRY key = watchlist provider).

    Knobs: `fields` (the schema plan; `plan=None` makes it a DOM adapter returning `fields` from
    read_step), `prefill_value` / `prefill_source` / `shown` (site prefill), `next_results`
    (a list of StepResult consumed in order, then the review page), `fill_failed` (keys the
    first fill reports), `submit_exc`, `after` (the value or a callable for after_submit),
    `on_submit` (a probe called inside submit()). Everything it is asked is in `.calls`.
    """
    name = "fakeats"
    needs_account = False
    password_rules = PasswordRules()
    mail_domains: tuple = ()
    otp_pattern = ""

    def __init__(self, fields: Optional[list[FormField]] = None, *, dom: bool = False) -> None:
        self.fields = list(fields if fields is not None else default_fields())
        self.dom = dom
        self.prefill_source = ""
        self.prefill_value = ""
        self.prefill_exc: Optional[BaseException] = None
        self.shown: dict[str, Any] = {}
        self.next_results: list[StepResult] = []
        self.fill_failed: list[list[str]] = []
        self.fill_log: list[dict[str, Any]] = []
        self.submit_exc: Optional[BaseException] = None
        self.after: Any = "confirmed:url"
        self.on_submit: Optional[Callable[[Any], None]] = None
        self.on_open: Optional[Callable[[Any, Any], None]] = None
        self.schema_exc: Optional[BaseException] = None
        self.log_in_open = ""
        self.calls: list[str] = []
        self.ctxs: list[Any] = []

    # tenant
    def match_url(self, url: str):
        return None

    def tenant_from_company(self, job: dict):
        return Tenant("fakeats", "fake.example.com", str(job.get("slug") or "co"), posting_id="1")

    def plan_from_schema(self, ctx):
        self.calls.append("plan_from_schema")
        self.ctxs.append(ctx)
        if self.schema_exc is not None:
            raise self.schema_exc
        if self.dom:
            return None
        return FormPlan(ats="fakeats", job_id=str(ctx.job.get("job_id", "")),
                        apply_url="https://fake.example.com/apply", source="schema",
                        fields=list(self.fields))

    # browser steps
    def open(self, page, ctx):
        self.calls.append("open")
        if self.log_in_open:
            ctx.log(self.log_in_open)
        if self.on_open:
            self.on_open(page, ctx)

    def account_wall(self, page):
        return None

    def prefill(self, page, ctx):
        self.calls.append("prefill")
        if self.prefill_exc is not None:
            raise self.prefill_exc
        return self.prefill_value

    def read_values(self, page, ctx, fields):
        self.calls.append("read_values")
        return {f.key: self.shown.get(f.key, "") for f in fields}

    def read_step(self, page, ctx):
        self.calls.append("read_step")
        return "application", list(self.fields)

    def fill(self, page, ctx, fields, answers):
        self.calls.append("fill")
        self.fill_log.append({k: a.value for k, a in answers.items()
                              if a.status is AnswerStatus.FILLED and a.value not in (None, "", [])})
        return self.fill_failed.pop(0) if self.fill_failed else []

    def next_step(self, page, ctx):
        self.calls.append("next_step")
        if self.next_results:
            return self.next_results.pop(0)
        return StepResult(step="application", is_review=True)

    def submit(self, page, ctx):
        self.calls.append("submit")
        if self.on_submit:
            self.on_submit(ctx)
        if self.submit_exc is not None:
            raise self.submit_exc

    def after_submit(self, page, ctx):
        self.calls.append("after_submit")
        got = self.after
        if isinstance(got, BaseException):
            raise got
        return got(page, ctx) if callable(got) else got

    def visible_errors(self, page):
        return ()

    def forget(self, ctx):
        self.calls.append("forget")


@contextlib.contextmanager
def registered(adapter: FakeAdapter):
    """Put `adapter` in the ATS registry for one block (detect() reads the same dict)."""
    from jobscraper.apply.ats import REGISTRY
    REGISTRY[adapter.name] = adapter
    try:
        yield adapter
    finally:
        REGISTRY.pop(adapter.name, None)


@contextlib.contextmanager
def page_signals(*signals: PageSignal, when: Optional[Callable[[Any], Optional[PageSignal]]] = None):
    """apply_flow.classify returns `signals` in order, then OK; or, with `when(page)`, that
    function's answer (None = OK). The fake page has no DOM to classify."""
    from jobscraper import apply_flow
    seq = list(signals)

    def fake(page, *a, **k):
        if when is not None:
            return when(page) or PageSignal.OK
        return seq.pop(0) if seq else PageSignal.OK
    saved = apply_flow.classify
    apply_flow.classify = fake
    try:
        yield
    finally:
        apply_flow.classify = saved


def stored_value(row: dict) -> Any:
    """`apply_answers.value_json` decoded when it is JSON (files, lists), else the raw text
    (the flow stores plain strings as they are)."""
    v = row["value_json"]
    if v is None:
        return None
    try:
        return json.loads(v)
    except ValueError:
        return v


def fake_world(**kw) -> tuple[World, FakeAdapter, int, str]:
    """A world with a `fakeats` company and one job: (world, adapter, company_id, job_id)."""
    w = make_world(**kw)
    cid, jid = add_job(w.store, key="fakeco", name="Fake Co", provider="fakeats", slug="fakeco",
                       external_id="1", url="https://fake.example.com/jobs/1")
    return w, FakeAdapter(), cid, jid


# ---------------------------------------------------------------- local Greenhouse (board + API)

class FixtureServer:
    """A local stand-in for job-boards.greenhouse.io and boards-api.greenhouse.io.

    GET /v1/boards/<board>/jobs/<id>?questions=true -> gh_<board>.json (else gh_dataiku.json), or
        `schema_status` when that is not 200.
    GET /<board>/jobs/<id> -> the fixture page set for that posting id (`postings`), default
        form.html. A page with a query (`?after=code`) is served by redirecting to it, because
        form.html reads its mode from location.search.
    Any other path: a file of that name in tests/fixtures/apply/greenhouse (recaptcha/ too), else 404.
    `.requests` lists every path asked (all of it localhost).
    """

    def __init__(self) -> None:
        self.postings: dict[str, tuple[str, str]] = {}
        self.default = ("form.html", "")
        self.schema_status = 200
        self.requests: list[str] = []
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._saved_env: dict[str, Optional[str]] = {}

    def set_posting(self, posting_id: str, page: str = "form.html", query: str = "") -> None:
        self.postings[str(posting_id)] = (page, query)

    @property
    def base(self) -> str:
        assert self._httpd is not None
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def start(self) -> "FixtureServer":
        fx = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):          # quiet
                pass

            def _send(self, status: int, body: bytes, ctype: str, extra: Optional[dict] = None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlsplit(self.path)
                fx.requests.append(self.path)
                m = re.fullmatch(r"/v1/boards/([^/]+)/jobs/(\d+)", u.path)
                if m:
                    if fx.schema_status != 200:
                        return self._send(fx.schema_status, b"{}", "application/json")
                    f = GH / f"gh_{m.group(1)}.json"
                    f = f if f.is_file() else GH / "gh_dataiku.json"
                    return self._send(200, f.read_bytes(), "application/json")
                m = re.fullmatch(r"/([^/]+)/jobs/(\d+)", u.path)
                if m:
                    page, query = fx.postings.get(m.group(2), fx.default)
                    if query and not u.query:
                        return self._send(302, b"", "text/plain", {"Location": f"{u.path}?{query}"})
                    return self._send(200, (GH / page).read_bytes(), "text/html; charset=utf-8")
                if "/recaptcha/" in u.path:
                    f = GH / "recaptcha" / u.path.rsplit("/", 1)[-1]
                else:
                    f = GH / u.path.rsplit("/", 1)[-1]
                if f.is_file() and f.suffix in (".html", ".json"):
                    return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
                return self._send(404, b"<html><head><title>404</title></head><body>Not found"
                                       b"</body></html>", "text/html; charset=utf-8")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        for k in ("JOBSCRAPER_GH_BOARD_BASE", "JOBSCRAPER_GH_API_BASE"):
            self._saved_env[k] = os.environ.get(k)
            os.environ[k] = self.base
        return self

    def stop(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "FixtureServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def only_local(self) -> bool:
        return all(r.startswith("/") for r in self.requests)


def local_http():
    """The app's HttpClient without pacing or robots: for a localhost API only."""
    from jobscraper.scrape.net import HttpClient
    return HttpClient(user_agent="jobscraper-test", timeout=10.0, delay=0.0, max_retries=1,
                      respect_robots=False)


# ---------------------------------------------------------------- headless Edge

_EDGE: dict[str, Any] = {}

SNAPSHOT_JS = """() => {
  const ids = (sel) => Array.from(document.querySelectorAll(sel));
  const values = {};
  ids('#application-form input[id], #application-form textarea[id]').forEach(e => {
    if (e.type === 'file' || e.type === 'checkbox' || e.classList.contains('select__input')) return;
    values[e.id] = e.value;
  });
  const selects = {};
  ids('.select').forEach(s => { selects[s.querySelector('.select__input').id] = s.dataset.value || ''; });
  const files = {};
  ['resume', 'cover_letter'].forEach(id => {
    const el = document.getElementById(id);
    files[id] = el && el.files.length ? el.files[0].name : '';
  });
  const checks = {};
  ids('#application-form input[type=checkbox]').forEach(e => { checks[e.id] = e.checked; });
  return {url: location.href, title: document.title,
          submitCount: document.body ? (document.body.dataset.submitCount || null) : null,
          submitted: window.__submitted || null, values, selects, files, checks,
          dialogOpen: !!document.getElementById('mygh_dialog'),
          inputs: window.__inputs || [],
          text: document.body ? document.body.innerText.slice(0, 600) : ''};
}"""

INPUT_RECORDER_JS = """() => {
  window.__inputs = [];
  document.addEventListener('input', e => { window.__inputs.push((e.target && e.target.id) || ''); }, true);
}"""


def edge_available() -> bool:
    """True if headless Edge starts here (cached). Says so on stdout when it doesn't."""
    if "ok" in _EDGE:
        return _EDGE["ok"]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel="msedge", headless=True)
            b.close()
        _EDGE["ok"] = True
    except Exception as exc:                      # no Playwright / no Edge: say so, never fake a pass
        print(f"  note: headless Edge not available ({type(exc).__name__}); browser tests not run")
        _EDGE["ok"] = False
    return _EDGE["ok"]


def edge_session_class():
    """BrowserSession that snapshots each page (form values, submit count, ...) just before it
    closes - the flow closes a finished attempt's page, so a test cannot look afterwards."""
    from jobscraper.apply.browser import BrowserSession

    class EdgeSession(BrowserSession):
        def __init__(self, cfg, *, profile_dir=None):
            super().__init__(cfg, profile_dir=profile_dir)
            self.snapshots: list[dict] = []
            self._snapped: set[int] = set()

        def _snap(self, page) -> None:
            if id(page) in self._snapped:
                return
            self._snapped.add(id(page))
            try:
                self.snapshots.append(page.evaluate(SNAPSHOT_JS))
            except Exception as exc:
                self.snapshots.append({"error": type(exc).__name__})

        def new_page(self):
            page = super().new_page()
            try:
                page.add_init_script("(" + INPUT_RECORDER_JS + ")()")
            except Exception:
                pass
            real_close = page.close

            def close(*a, **k):
                self._snap(page)
                return real_close(*a, **k)
            page.close = close
            return page

        def close(self):
            for p in list(self.context.pages) if self.context is not None else []:
                self._snap(p)
            super().close()

    return EdgeSession


def edge_acfg(base, profile_dir: str, **over):
    """An ApplyConfig for a headless test session: fast pacing, short waits, no dry-run hold."""
    import dataclasses
    return dataclasses.replace(
        base, headed=False, profile_dir=profile_dir, type_delay_ms=0, action_pause_ms=30,
        step_timeout_s=8, confirm_timeout_s=4, dry_run_hold_s=0, mygreenhouse_wait_s=8, **over)
