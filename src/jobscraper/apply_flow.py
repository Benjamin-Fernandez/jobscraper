"""Auto-apply orchestrator: queue -> guards -> tailor -> detect -> plan ->
resolve -> browser -> submit -> record (apply_design §3, KA-1).

`run()` is the only public entry point; `cmd_apply` calls it. One Edge
session serves the whole run, one tab per attempt, attempts run one after the
other. Every decision the design leaves to "the flow" lives here:

  - the guard order (§12.1): profile -> duplicate -> caps -> one in flight;
  - when the plan is resolved (§6): a schema plan in `planning`, before Edge
    opens; a DOM step before its first keystroke;
  - the NF-06 rule (§4.1, D-69): `submit_clicked_at` is committed BEFORE the
    click, and from then on every outcome, exception included, ends
    `submitted` or `submitted_unconfirmed`, never `failed`;
  - the audit (§7.8): one `apply_answers` row per field of every step, file
    fields as name + SHA-256, never the path;
  - the log (§17, NF-09): one line per state change, every line through
    `redact()` with the profile's values, so no answer, email or phone ever
    reaches the job log the Developer tab shows.

Stages do not import each other: this module composes `apply/` (detect,
resolve, classify, browser, the adapters) with the foundation (store, config,
applicant) and, for the resume, `tailor_flow` (the one orchestrator edge the
layering test allows, D-58).
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import urlsplit

from . import applicant
from .apply import browser as B
from .apply import resolve as R
from .apply.classify import PageSignal, classify
from .apply.contracts import (
    POST_CLICK_STATES, REASON_TEXTS, STATE_TEXTS, TERMINAL_STATES, TRANSITIONS, Answer,
    AnswerStatus, AnswerTier, ApplyFailure, AttemptContext, AttemptResult, AttemptState,
    Canonical, FieldType, FormField, ReasonCode, ResolveContext,
)
from .apply.detect import detect
from .apply.plan import norm_label
from .config import ApplyConfig, Config
from .scrape.net import HttpClient
from .store import (ATTEMPT_TRANSITIONS, POST_CLICK_ATTEMPT_STATES, TERMINAL_ATTEMPT_STATES,
                    TIME_FMT, Store, utcnow)

S = AttemptState
SG = timezone(timedelta(hours=8))        # Asia/Singapore: no DST since 1982, so a fixed offset
REDACTED = "[redacted]"
_BLANK = (None, "", [])


def check_attempt_table() -> None:
    """The store keeps the state machine as plain strings (it may not import a
    stage). Refuse to run if that copy has drifted from the contract."""
    contract = {k.value: frozenset(v.value for v in vs) for k, vs in TRANSITIONS.items()}
    if (contract != dict(ATTEMPT_TRANSITIONS)
            or {s.value for s in TERMINAL_STATES} != set(TERMINAL_ATTEMPT_STATES)
            or {s.value for s in POST_CLICK_STATES} != set(POST_CLICK_ATTEMPT_STATES)):
        raise RuntimeError("store.ATTEMPT_TRANSITIONS differs from apply/contracts.py TRANSITIONS")


check_attempt_table()


# ---------------------------------------------------------------- log (§17)

def redact(line: str, values: Sequence[str]) -> str:
    """`line` with every value replaced by "[redacted]", case-insensitive,
    longest first (a full address before one of its words). A value matches
    only as a whole run of characters (not inside a longer word), so a short
    profile value such as a grade type does not eat the word "captcha"."""
    for v in sorted({str(v).strip() for v in values if v and len(str(v).strip()) >= 3},
                    key=lambda s: (-len(s), s)):
        line = re.sub(r"(?<![0-9A-Za-z])" + re.escape(v) + r"(?![0-9A-Za-z])", REDACTED,
                      line, flags=re.I)
    return line


class _Log:
    """The job log: one line per event, redacted (NF-02, NF-09)."""

    def __init__(self, say: Callable[[str], None], values: Sequence[str] = ()):
        self.say = say
        self.values = list(values)

    def __call__(self, line: str) -> None:
        text = redact(str(line), self.values)
        try:
            self.say(text)
        except UnicodeEncodeError:              # a cp1252 console: never let a log line end an attempt
            self.say(text.encode("ascii", "replace").decode("ascii"))

    def exc(self, exc: BaseException) -> str:
        """`Type: first line`, redacted, at most 200 characters."""
        first = (str(exc).splitlines() or [""])[0]
        return redact(f"{type(exc).__name__}: {first}"[:200], self.values)


def _url_for_log(url: str) -> str:
    """Host + path, the query string dropped (§17)."""
    p = urlsplit(url or "")
    return f"{p.netloc}{p.path}" if p.netloc else (url or "").split("?", 1)[0]


# ---------------------------------------------------------------- helpers

def day_start_utc(now: Optional[datetime] = None) -> str:
    """Today's midnight in Singapore as a UTC store timestamp (the caps' day, §12.1)."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(SG).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).strftime(TIME_FMT)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def make_http(cfg: Config) -> HttpClient:
    """The app's HTTP client (as the pipeline builds it), for schema adapters."""
    rc = cfg.run
    return HttpClient(user_agent=rc.get("user_agent", "JobScraper/2.0"),
                      timeout=float(rc.get("request_timeout", 25)),
                      delay=float(rc.get("rate_limit_delay", 0.7)),
                      max_retries=int(rc.get("max_retries", 3)),
                      respect_robots=bool(rc.get("respect_robots", True)))


def default_browser_factory(acfg: ApplyConfig):
    """The §8.1 Edge session, started."""
    return B.BrowserSession(acfg).start()


def evidence_root(cfg: Config) -> Path:
    """`data/apply/` beside the database (a copied DB keeps its evidence beside it)."""
    return cfg.db_path.parent / "apply"


def _profile_path(profile: dict, dotted: str) -> Any:
    cur: Any = profile
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# Page signals that end an attempt before the click (§8.4, §4.4).
_SIGNAL_REASON = {
    PageSignal.CAPTCHA: (ReasonCode.CAPTCHA, ""),
    PageSignal.BOT_CHALLENGE: (ReasonCode.BOT_CHALLENGE, ""),
    PageSignal.TWO_FACTOR: (ReasonCode.SMS_OR_2FA, ""),
    PageSignal.CLOSED: (ReasonCode.POSTING_CLOSED, ""),
    PageSignal.ERROR_PAGE: (ReasonCode.PAGE_UNRECOGNISED, "error page"),
    # an email check in the middle of a form needs the mailbox (lane V, WP-V4)
    PageSignal.VERIFY_EMAIL: (ReasonCode.MAIL_NOT_SET_UP, ""),
}
# ...and after it: a note on submitted_unconfirmed (§4.1, D-69).
_SIGNAL_NOTE = {
    PageSignal.CAPTCHA: "captcha after submit",
    PageSignal.BOT_CHALLENGE: "bot check after submit",
    PageSignal.TWO_FACTOR: "two-step code after submit",
    PageSignal.ERROR_PAGE: "error page after submit",
}


# ---------------------------------------------------------------- one attempt

class _Attempt:
    """The bookkeeping of one attempt: state writes, evidence, audit rows."""

    def __init__(self, store: Store, log: _Log, attempt_id: int, job_id: str,
                 evidence: Path):
        self.store = store
        self.log = log
        self.id = attempt_id
        self.dir = evidence / str(attempt_id)
        self.result = AttemptResult(attempt_id=attempt_id, job_id=job_id, state=S.QUEUED)
        self.state = S.QUEUED
        self.step = ""
        self.ats = ""
        self.seq = 0
        self.clicked = False
        self.fields: dict[str, FormField] = {}
        self.answers: dict[str, Answer] = {}
        self.recorded: set[str] = set()
        self.page = None

    # -- state

    def to(self, state: AttemptState, *, step: Optional[str] = None,
           reason: Optional[ReasonCode] = None, detail: Optional[str] = None, **cols: Any) -> None:
        if step is not None:
            self.step = step
        self.store.set_attempt_state(self.id, state.value, step=step,
                                     reason=reason.value if reason else None,
                                     detail=detail, **cols)
        self.store.conn.commit()
        self.state = self.result.state = state
        if step is not None:
            self.result.step = step
        if reason is not None:
            self.result.reason = reason
        if detail is not None:
            self.result.reason_detail = detail
        if state is S.FAILED:
            self.log(f"[attempt {self.id}] failed reason={reason.value if reason else ''} "
                     f"step={self.step} detail={detail or ''}")
            rt = REASON_TEXTS.get(reason) if reason else None
            if rt:
                self.log(f"[attempt {self.id}] {rt.text.format(detail=detail or '')} {rt.hint}")
            return
        self.log(f"[attempt {self.id}] {state.value} step={self.step or '-'} "
                 f"ats={self.ats or '-'} {self.counts()}")
        if state in STATE_TEXTS:
            st = STATE_TEXTS[state]
            self.log(f"[attempt {self.id}] {st.text} {st.hint}"
                     + (f" ({detail})" if detail else ""))

    def counts(self) -> str:
        a = list(self.answers.values())
        n = lambda *st: sum(1 for x in a if x.status in st)        # noqa: E731
        tier5 = sum(1 for x in a if x.tier is AnswerTier.LLM and x.fills)
        return (f"fields={len(a)} filled={n(AnswerStatus.FILLED, AnswerStatus.PREFILLED)} "
                f"blank={n(AnswerStatus.BLANK_OPTIONAL)} "
                f"unknown={n(AnswerStatus.UNKNOWN, AnswerStatus.UNGROUNDED)} tier5={tier5}")

    # -- evidence (§8.3)

    def shot(self, page: Any, step: str) -> str:
        if page is None:
            return ""
        self.seq += 1
        path = B.screenshot(page, self.dir, self.seq, step)
        if path:
            self.result.screenshots.append(path)
        return path

    # -- audit (§7.8)

    def record(self, step: str, fields: Sequence[FormField]) -> None:
        rows = []
        for f in fields:
            if f.key in self.recorded:
                continue
            a = self.answers.get(f.key)
            if a is None:
                continue
            self.recorded.add(f.key)
            rows.append(audit_row(step, f, a))
        if rows:
            self.store.add_answers(self.id, rows)
            self.store.conn.commit()

    def record_all(self) -> None:
        """Every resolved field not recorded yet (an attempt that ends early)."""
        self.record(self.step, list(self.fields.values()))


def _sent_value(f: FormField, a: Answer) -> Any:
    """The exact value sent, for the audit: a file as name + SHA-256 (never
    the path); None when nothing is (or will be) on the page."""
    if a.value in _BLANK or a.status not in (AnswerStatus.FILLED, AnswerStatus.PREFILLED,
                                             AnswerStatus.FILL_FAILED):
        return None
    if f.type is FieldType.FILE and a.status is not AnswerStatus.PREFILLED:
        p = Path(str(a.value))
        try:
            return {"file": p.name, "sha256": sha256_file(p)}
        except OSError:
            return {"file": p.name, "sha256": ""}
    return a.value


def audit_row(step: str, f: FormField, a: Answer) -> dict[str, Any]:
    return {
        "step": step, "field_key": f.key, "label": f.label, "label_norm": norm_label(f.label),
        "field_type": f.type.value, "required": f.required, "section": f.section,
        "options_json": [{"label": o.label, "value": o.value} for o in f.options] or None,
        "value_json": _sent_value(f, a), "tier": int(a.tier), "source": a.source,
        "confidence": a.confidence, "status": a.status.value, "rule_id": a.rule_id,
        "model": a.model, "prompt_hash": a.prompt_hash, "note": a.note,
        "sensitive": a.sensitive or f.section in ("compliance", "demographic"),
    }


def _unanswerable(fields: Sequence[FormField], answers: dict[str, Answer]) -> Optional[ApplyFailure]:
    """The first required field with no answer we can back up (§4.4)."""
    for f in fields:
        a = answers.get(f.key)
        if f.required and a is not None and a.status in (AnswerStatus.UNKNOWN,
                                                         AnswerStatus.UNGROUNDED):
            detail = f.label[:120]
            if "model unavailable" in (a.note or ""):
                detail = f"{detail} (model unavailable)"
            return ApplyFailure(ReasonCode.UNANSWERABLE_REQUIRED, detail)
    return None


# ---------------------------------------------------------------- the run

class _Run:
    def __init__(self, cfg: Config, store: Store, *, dry_run: bool, backend: Any, http: Any,
                 browser_factory: Callable[[ApplyConfig], Any], acfg: ApplyConfig,
                 say: Callable[[str], None], evidence: Optional[Path]):
        self.cfg = cfg
        self.store = store
        self.dry_run = dry_run
        self.mode = "dry_run" if dry_run else "auto"
        self.backend = backend
        self.http = http
        self.browser_factory = browser_factory
        self.acfg = acfg
        self.evidence = evidence or evidence_root(cfg)
        self.session = None
        self.profile: dict = {}
        self.profile_error = ""
        try:
            self.profile = applicant.load(cfg.applicant_path)
        except applicant.ApplicantError as exc:
            self.profile_error = str(exc)
        self.log = _Log(say, applicant.redaction_values(self.profile))
        self.rules = None
        self.seen: set[str] = set()

    # -- browser

    def browser(self):
        if self.session is None:
            self.session = self.browser_factory(self.acfg)
        return self.session

    def close(self) -> None:
        if self.session is not None:
            try:
                self.session.close()
            finally:
                self.session = None

    # -- guards (§12.1)

    def guards(self, at: _Attempt, job: dict[str, Any]) -> None:
        if self.profile_error:
            raise ApplyFailure(ReasonCode.PROFILE_INCOMPLETE, "applicant.yaml could not be read")
        missing = applicant.missing_for_apply(self.profile, self.cfg.resume_dir)
        if missing:
            raise ApplyFailure(ReasonCode.PROFILE_INCOMPLETE, ", ".join(missing))
        if job["job_id"] in self.seen:
            raise ApplyFailure(ReasonCode.DUPLICATE, "the same job twice in this batch")
        dup = self.store.apply_duplicate(job["job_id"])
        if dup:
            raise ApplyFailure(ReasonCode.DUPLICATE, dup)
        if not self.dry_run:
            total, employer = self.store.apply_counts(job.get("company_id"), day_start_utc())
            if total >= self.acfg.daily_cap:
                raise ApplyFailure(ReasonCode.CAP_REACHED, f"{total} of {self.acfg.daily_cap} today")
            if employer >= self.acfg.per_employer_daily_cap:
                raise ApplyFailure(ReasonCode.CAP_REACHED,
                                   f"{employer} of {self.acfg.per_employer_daily_cap} today at "
                                   f"{job.get('company') or 'this employer'}")
        if self.store.attempts_in_flight(exclude_id=at.id):
            raise ApplyFailure(ReasonCode.ERROR, "another application is in progress")

    # -- resume (stub until WP-B9: the original resume)

    def resume(self, at: _Attempt, job: dict[str, Any]) -> str:
        path = applicant.resume_file(self.profile, self.cfg.resume_dir)
        if path is None:
            raise ApplyFailure(ReasonCode.PROFILE_INCOMPLETE, "documents.resume")
        self.store.update_attempt(at.id, resume_file=path.name, resume_sha256=sha256_file(path),
                                  resume_source="original")
        return str(path)

    # -- resolution (§7)

    def resolve_ctx(self, job: dict[str, Any], tenant: Any, adapter: Any,
                    resume_path: str) -> ResolveContext:
        aliases = tuple(dict.fromkeys(a for a in (job.get("company_key"), tenant.board)
                                      if a and a != job.get("company")))
        return ResolveContext(
            profile=self.profile, employer_name=str(job.get("company") or ""),
            employer_aliases=aliases,
            previously_applied=self.store.applied_to_company(job.get("company_id"), job["job_id"]),
            jd_text=str(job.get("jd_text") or ""), resume_path=resume_path, ats=adapter.name)

    def resolve(self, fields: Sequence[FormField], rctx: ResolveContext,
                at: _Attempt) -> dict[str, Answer]:
        if self.rules is None:
            self.rules = R.load_rules(self.cfg.questions_path)
        out = R.resolve_all(fields, rctx, backend=self.backend, rules=self.rules,
                            memory=self.store.answer_memory_get)
        for f in fields:
            at.fields[f.key] = f
            out[f.key] = self.cover_letter_file(f, out[f.key], at)
        at.answers.update(out)
        return out

    def cover_letter_file(self, f: FormField, a: Answer, at: _Attempt) -> Answer:
        """A required cover letter is answered with its text (lane P (f)); a
        file field needs a file, so the text goes to `cover_letter.txt`."""
        if f.type is not FieldType.FILE or f.canonical is not Canonical.COVER_LETTER or not a.fills:
            return a
        text = str(a.value)
        if Path(text).is_file():
            return a
        at.dir.mkdir(parents=True, exist_ok=True)
        path = at.dir / "cover_letter.txt"
        path.write_text(text, encoding="utf-8")
        return dataclasses.replace(a, value=str(path))

    # -- page checks

    def check_page(self, page: Any, at: _Attempt) -> None:
        sig = classify(page)
        if sig in _SIGNAL_REASON:
            reason, detail = _SIGNAL_REASON[sig]
            raise ApplyFailure(reason, detail, step=at.step)

    def check_deadline(self, ctx: AttemptContext) -> None:
        if time.monotonic() > ctx.deadline:
            raise ApplyFailure(ReasonCode.ERROR, "timed out")

    # -- one job

    def attempt(self, job_id: str) -> AttemptResult:
        job = self.store.job_for_apply(job_id)
        now = utcnow()
        attempt_id = self.store.create_attempt(job_id, job.get("company_id") if job else None,
                                               self.mode, now)
        self.store.conn.commit()
        at = _Attempt(self.store, self.log, attempt_id, job_id, self.evidence)
        self.log(f"[attempt {attempt_id}] queued job={job_id} mode={self.mode}")
        adapter = ctx = None
        try:
            if job is None:
                raise ApplyFailure(ReasonCode.ERROR, "no such job")
            self.guards(at, job)
            self.seen.add(job_id)
            adapter, ctx = self.body(at, job)
        except ApplyFailure as exc:
            self.seen.add(job_id)
            self.fail(at, exc.reason, exc.detail, exc.step)
        except Exception as exc:                          # noqa: BLE001 - any bug ends the attempt
            if at.clicked:
                self.unconfirmed(at, f"error after submit ({type(exc).__name__})")
            else:
                self.log(f"[attempt {at.id}] {self.log.exc(exc)}")
                self.fail(at, ReasonCode.ERROR, type(exc).__name__)
        except BaseException:                             # cancel (JobCancelled), Ctrl+C
            try:
                if at.state not in TERMINAL_STATES:
                    if at.clicked:
                        self.unconfirmed(at, "interrupted after submit")
                    else:
                        self.fail(at, ReasonCode.CANCELLED, "interrupted")
            finally:
                raise
        finally:
            if adapter is not None and ctx is not None and hasattr(adapter, "forget"):
                adapter.forget(ctx)
            if at.page is not None and at.state is not S.READY_TO_SUBMIT:
                try:
                    at.result.url = at.result.url or (at.page.url or "").split("?", 1)[0]
                    at.page.close()
                except Exception:
                    pass
        at.result.answers = list(at.answers.values())
        return at.result

    def fail(self, at: _Attempt, reason: ReasonCode, detail: str, step: str = "") -> None:
        """End before the click: evidence, the audit so far, `failed(reason)`."""
        if at.page is not None:
            at.shot(at.page, "failed")
            B.dump_html(at.page, at.dir)
        at.record_all()
        cols: dict[str, Any] = {}
        if at.page is not None:
            cols["end_url"] = (at.page.url or "").split("?", 1)[0]
        at.to(S.FAILED, step=step or at.step or None, reason=reason, detail=detail, **cols)

    def unconfirmed(self, at: _Attempt, note: str) -> None:
        """After the click every unhappy ending is this, never `failed` (NF-06)."""
        if at.page is not None:
            at.shot(at.page, "unconfirmed")
        at.record_all()
        if at.state not in TERMINAL_STATES:
            at.to(S.SUBMITTED_UNCONFIRMED, detail=note)

    def body(self, at: _Attempt, job: dict[str, Any]):
        acfg = self.acfg
        # tailoring -> planning
        resume_path = self.resume(at, job)
        at.to(S.PLANNING, step="planning")
        adapter, tenant = detect(job)
        at.ats = adapter.name
        self.store.update_attempt(at.id, ats=adapter.name, tenant_host=tenant.host)
        ctx = AttemptContext(
            attempt_id=at.id, job=job, tenant=tenant, dry_run=self.dry_run,
            email=str(_profile_path(self.profile, "contact.email") or ""),
            resume_path=resume_path, log=self.log, screenshot=at.shot,
            deadline=time.monotonic() + acfg.attempt_timeout_s, http=self.http)
        rctx = self.resolve_ctx(job, tenant, adapter, resume_path)
        plan = adapter.plan_from_schema(ctx)
        if plan is not None:
            self.store.update_attempt(at.id, plan_source=plan.source)
            answers = self.resolve(plan.fields, rctx, at)
            bad = _unanswerable(plan.fields, answers)
            if bad:
                raise bad
        else:
            self.store.update_attempt(at.id, plan_source="dom")
        self.check_deadline(ctx)

        # opening
        at.to(S.OPENING, step="opening")
        page = at.page = self.browser().new_page()
        adapter.open(page, ctx)
        at.shot(page, "open")
        self.check_page(page, at)
        wall = adapter.account_wall(page)
        if wall:                       # accounts, sign-in and sign-up: lane V (WP-V4)
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"{adapter.name}: account {wall}")
        at.to(S.FILLING, step="application")

        # filling, one step at a time
        for _ in range(max(1, acfg.max_wizard_steps)):
            self.check_deadline(ctx)
            step, fields = adapter.read_step(page, ctx)
            step = B.slug(step) or "application"
            if step != at.step:
                at.to(S.FILLING, step=step)
            if plan is None:
                self.resolve(fields, rctx, at)
            for f in fields:
                at.fields.setdefault(f.key, f)
            step_answers = {f.key: at.answers[f.key] for f in fields if f.key in at.answers}
            bad = _unanswerable(fields, step_answers)
            if bad:
                raise bad
            self.check_page(page, at)
            self.fill(page, ctx, adapter, at, fields, step_answers)
            at.record(step, fields)
            at.shot(page, step)
            self.check_page(page, at)
            res = adapter.next_step(page, ctx)
            if res.errors:
                raise ApplyFailure(ReasonCode.VALIDATION_ERROR, ", ".join(res.errors[:3]), step=step)
            if res.is_review:
                break
            at.to(S.FILLING, step=B.slug(res.step) or step)
        else:
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"{adapter.name}: too many steps")

        # review
        if self.dry_run:
            at.shot(page, "review")
            at.result.url = (page.url or "").split("?", 1)[0]
            at.to(S.READY_TO_SUBMIT, end_url=at.result.url)
            return adapter, ctx
        self.submit(page, ctx, adapter, at, job)
        return adapter, ctx

    def fill(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
             fields: Sequence[FormField], answers: dict[str, Answer]) -> None:
        """Fill, mark what would not take its value; a required one ends the attempt."""
        failed = adapter.fill(page, ctx, fields, answers) or []
        for k in failed:
            if k in at.answers:
                at.answers[k] = dataclasses.replace(at.answers[k], status=AnswerStatus.FILL_FAILED)
        bad = [f.label for f in fields if f.key in failed and f.required]
        if bad:
            at.record(at.step, fields)
            raise ApplyFailure(ReasonCode.VALIDATION_ERROR, ", ".join(b[:80] for b in bad[:3]),
                               step=at.step)

    # -- submit (auto mode; §4.1, NF-06)

    def submit(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
               job: dict[str, Any]) -> None:
        at.shot(page, "review")
        # The click is recorded and committed BEFORE it happens (NF-06).
        self.store.mark_submit_clicked(at.id, utcnow())
        self.store.conn.commit()
        at.clicked = True
        at.to(S.SUBMITTING, step="submit")
        try:
            adapter.submit(page, ctx)
            outcome, note = self.await_confirmation(page, ctx, adapter)
        except Exception as exc:                          # noqa: BLE001 - NF-06
            outcome, note = None, f"error after submit ({type(exc).__name__})"
        end_url = (page.url or "").split("?", 1)[0]
        at.result.url = end_url
        if outcome:
            at.shot(page, "confirmed")
            at.result.confirmation = outcome
            at.to(S.SUBMITTED, confirmation=outcome, end_url=end_url)
            self.store.set_application_status(
                job["job_id"], "applied", company=job.get("company"), role=job.get("title"),
                url=job.get("url"), by="jobscraper")
            self.after_submitted(at)
        else:
            at.shot(page, "unconfirmed")
            at.to(S.SUBMITTED_UNCONFIRMED, detail=note, end_url=end_url)

    def after_submitted(self, at: _Attempt) -> None:
        """The tailored file was sent (WP-B9)."""

    def await_confirmation(self, page: Any, ctx: AttemptContext, adapter: Any):
        """(confirmation signal, "") or (None, note) within `confirm_timeout_s`."""
        end = time.monotonic() + self.acfg.confirm_timeout_s
        while True:
            got = adapter.after_submit(page, ctx)
            if got and got.startswith("confirmed:"):
                return got.split(":", 1)[1], ""
            if got == "code_required":            # the emailed code needs the mailbox (lane V)
                return None, "security code needed; mailbox not set up"
            if got == "errors":
                return None, "errors after submit"
            sig = classify(page)
            if sig in _SIGNAL_NOTE:
                return None, _SIGNAL_NOTE[sig]
            if time.monotonic() >= end:
                return None, "no confirmation within the time limit"
            page.wait_for_timeout(1000)

    # -- the batch

    def run(self, job_ids: Sequence[str]) -> list[AttemptResult]:
        reaped = self.store.reap_attempts(utcnow())
        if reaped:
            self.log(f"apply: closed {reaped} interrupted attempt(s)")
        results = []
        try:
            for job_id in job_ids:
                results.append(self.attempt(job_id))
            ready = [r for r in results if r.state is S.READY_TO_SUBMIT]
            if ready and self.session is not None and self.acfg.dry_run_hold_s > 0:
                self.log(f"apply: dry run - the filled form(s) stay open for up to "
                         f"{self.acfg.dry_run_hold_s} s; close the window to finish sooner")
                self.session.hold(self.acfg.dry_run_hold_s)
        finally:
            self.close()
        return results


OPEN_PROFILE_URL = "https://my.greenhouse.io/"
OPEN_PROFILE_HOLD_S = 3600
OPEN_PROFILE_TEXT = ("Edge is open on the JobScraper profile. Sign in where you need to "
                     "(MyGreenhouse, a Workday site), then close the window.")
PROFILE_LOCKED_TEXT = "An apply run is using the profile; try again when it ends."


def _names_profile_dir(exc: BaseException, profile_dir: str) -> bool:
    """Does a launch error say the user-data directory is in use?"""
    msg = str(exc).lower()
    return (os.path.normcase(profile_dir).lower() in os.path.normcase(msg)
            or profile_dir.lower() in msg or "user data dir" in msg
            or "user-data-dir" in msg or "processsingleton" in msg)


def open_profile(acfg: ApplyConfig, url: str = "", *, say: Callable[[str], None] = print,
                 browser_factory: Optional[Callable[[ApplyConfig], Any]] = None) -> int:
    """`apply open-profile [URL]` (§14.1, D-70): a headed Edge on the
    JobScraper profile for the owner's own sign-ins (MyGreenhouse, Workday).
    Nothing is filled and nothing is logged beyond the one line. Returns the
    exit code: 0, or 1 when the profile is locked by a running apply job."""
    acfg = dataclasses.replace(acfg, headed=True)
    factory = browser_factory or default_browser_factory
    try:
        session = factory(acfg)
    except Exception as exc:                              # noqa: BLE001 - one message, exit 1
        if _names_profile_dir(exc, os.path.expandvars(acfg.profile_dir)):
            say(PROFILE_LOCKED_TEXT)
        else:
            say(f"Edge could not start: {type(exc).__name__}")
        return 1
    try:
        page = session.new_page()
        try:
            page.goto(url or OPEN_PROFILE_URL, wait_until="domcontentloaded")
        except Exception:                                 # noqa: BLE001 - the window is open anyway
            pass
        say(OPEN_PROFILE_TEXT)
        session.hold(OPEN_PROFILE_HOLD_S)
    finally:
        session.close()
    return 0


def run(cfg: Config, store: Store, job_ids: list[str], *, dry_run: bool, backend: Any,
        http: Any = None, browser_factory: Optional[Callable[[ApplyConfig], Any]] = None,
        apply_cfg: Optional[ApplyConfig] = None, say: Callable[[str], None] = print,
        evidence_dir: Optional[Path] = None) -> list[AttemptResult]:
    """Apply to each job in order (apply_design §3). `apply_cfg` is the
    effective settings (cmd_apply merges the settings table over config);
    `http` and `browser_factory` exist so tests inject fakes."""
    r = _Run(cfg, store, dry_run=dry_run, backend=backend,
             http=http if http is not None else make_http(cfg),
             browser_factory=browser_factory or default_browser_factory,
             acfg=apply_cfg or cfg.apply, say=say, evidence=evidence_dir)
    return r.run(job_ids)
