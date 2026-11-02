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

from . import applicant, tailor_flow, vault
from .apply import browser as B
from .apply import mail
from .apply import resolve as R
from .apply.accounts import BOTH_NO_PASSWORD_DETAIL, NO_PASSWORD_DETAIL, SIGN_IN, choose_identity
from .apply.classify import PageSignal, classify
from .apply.contracts import (
    ALWAYS_OURS, CHOICE_TYPES, EMPLOYER_SPECIFIC_DECLARATIONS, POST_CLICK_STATES, PREFILL_POLICY,
    REASON_TEXTS, STATE_TEXTS, TERMINAL_STATES, TRANSITIONS, AccountStatus, Answer, AnswerSource,
    AnswerStatus, AnswerTier, ApplyFailure, AttemptContext, AttemptResult, AttemptState, Canonical,
    FieldType, FormField, PrefillPolicy, ReasonCode, ResolveContext, SignUpOutcome,
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
CODE_REQUIRED = "code_required"          # await_confirmation's note for §4.2's emailed code


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
    longest first (a full address before one of its words). A purely
    alphabetic value matches only as a whole word, so a short profile value
    such as a grade type does not eat the word "captcha"; a value with a digit
    or any other character (a phone, a postal code, an email) matches anywhere,
    so 91234567 is caught inside +6591234567 (review F6)."""
    for v in sorted({str(v).strip() for v in values if v and len(str(v).strip()) >= 3},
                    key=lambda s: (-len(s), s)):
        pat = re.escape(v)
        if re.fullmatch(r"[A-Za-z ]+", v):
            pat = r"(?<![A-Za-z])" + pat + r"(?![A-Za-z])"
        line = re.sub(pat, REDACTED, line, flags=re.I)
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
        self.tailored_id: Optional[int] = None

    # -- state

    def to(self, state: AttemptState, *, step: Optional[str] = None,
           reason: Optional[ReasonCode] = None, detail: Optional[str] = None, **cols: Any) -> None:
        if step is not None:
            self.step = step
        if detail:                     # the row, the result and the CLI table carry no profile value
            detail = redact(detail, self.log.values)
        self.store.set_attempt_state(self.id, state.value, step=step,
                                     reason=reason.value if reason else None,
                                     detail=detail, **cols)
        self.store.commit()
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
            self.store.commit()

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


# ---------------------------------------------------------------- prefill policies (D-70)
#
# A site may put values on the form before we type (MyGreenhouse autofill,
# Workday "Use My Last Application", a site default). Per field the flow then
# decides: "fill" (the field is empty: the planned answer as usual), "keep"
# (leave the site's value; audit row `prefilled`) or "overwrite" (our answer
# replaces it). KEEP = apply_design §9.1.1, OVERWRITE = §9.4.6.

KEEP, OVERWRITE, FILL = "keep", "overwrite", "fill"
_EMPLOYER_SPECIFIC = frozenset(d.value for d in EMPLOYER_SPECIFIC_DECLARATIONS)


def _is_empty(shown: Any) -> bool:
    return shown is None or (isinstance(shown, str) and not shown.strip()) or shown == []


def _employer_specific(a: Optional[Answer]) -> bool:
    """A tier-4 answer about THIS employer (prior/current employment, applied
    before, relatives, shareholding): a saved answer from elsewhere never stands."""
    if a is None or a.tier is not AnswerTier.DECLARATION:
        return False
    label = a.rule_id or a.source.split(":", 1)[-1]
    return label in _EMPLOYER_SPECIFIC


def keep_decision(field: FormField, answer: Optional[Answer], shown: Any, ctx_email: str) -> str:
    """PrefillPolicy.KEEP (MyGreenhouse, §9.1.1): keep every non-empty field
    except the always-ours ones - the resume, the email (it must be the
    watched mailbox), a single checkbox (unticked can't be told from "not
    answered") - and an employer-specific declaration. Empty fields are filled.
    `ctx_email` is the identity in use; an equal email needs no input (the
    flow notes "already on page")."""
    if field.type is FieldType.CHECKBOX:
        return OVERWRITE
    if field.canonical in ALWAYS_OURS or _employer_specific(answer):
        return FILL if _is_empty(shown) else OVERWRITE
    return FILL if _is_empty(shown) else KEEP


def overwrite_decision(field: FormField, answer: Optional[Answer], shown: Any) -> str:
    """PrefillPolicy.OVERWRITE (Workday, §9.4.6): our answer wins; a site
    value is kept only on an optional field we cannot answer. A required field
    with no answer stays `unknown` (fails closed: a value we cannot back up is
    not kept, even our own from a last application)."""
    if answer is not None and answer.fills:
        return OVERWRITE
    if field.required or _is_empty(shown):
        return FILL
    return KEEP


def _shown_form(f: FormField, a: Answer) -> Any:
    """How our answer reads back on the page (option labels, a file name)."""
    if f.type is FieldType.FILE:
        return Path(str(a.value)).name
    if f.type in CHOICE_TYPES and a.option_labels:
        return list(a.option_labels) if f.type is FieldType.MULTI_CHOICE else a.option_labels[0]
    if f.type is FieldType.CHECKBOX:
        return str(a.value).strip().lower()
    return a.value


def same_value(f: FormField, a: Answer, shown: Any) -> bool:
    """Does the page already show our answer? Text by §7.1 normalisation,
    multi-choice as sets, files by name."""
    ours = _shown_form(f, a)
    if isinstance(ours, list) or isinstance(shown, list):
        mine = {norm_label(str(x)) for x in (ours if isinstance(ours, list) else [ours])}
        theirs = {norm_label(str(x)) for x in (shown if isinstance(shown, list) else [shown])}
        return mine == theirs
    if f.type is FieldType.FILE:
        return str(ours) == str(shown)
    return norm_label(str(ours or "")) == norm_label(str(shown or ""))


def _prefilled(f: FormField, planned: Optional[Answer], shown: Any, source: str,
               confidence: float) -> Answer:
    """The audit answer for a site value that was kept: tier 0, the prefill
    source, the shown value; a note when the profile would have said otherwise."""
    note = ""
    if planned is not None and planned.fills and planned.tier in (
            AnswerTier.FIELD_MAP, AnswerTier.PROFILE_RULE, AnswerTier.MEMORY,
            AnswerTier.DECLARATION) and not same_value(f, planned, shown):
        note = f"differs from profile ({planned.source})"
    return Answer(field_key=f.key, value=shown, tier=AnswerTier.NONE, source=source,
                  confidence=confidence, status=AnswerStatus.PREFILLED,
                  sensitive=bool(planned and planned.sensitive)
                  or f.section in ("compliance", "demographic"), note=note)


def apply_prefill_policy(source: str, fields: Sequence[FormField], answers: dict[str, Answer],
                         shown: dict[str, Any], ctx_email: str
                         ) -> tuple[dict[str, Answer], dict[str, Answer]]:
    """(audit answers, answers to fill) for one step under the policy of
    `source`. A field whose page value already equals our answer is recorded
    `filled` with the note "already on page" and gets no input - never a file
    field: a same-named attached file is not proof it is ours (every tailored
    file has the same name), so our file is always uploaded (D-70 §9.1.1)."""
    policy = PREFILL_POLICY[AnswerSource(source)]
    audit: dict[str, Answer] = {}
    to_fill: dict[str, Answer] = {}
    for f in fields:
        a = answers.get(f.key)
        if a is None or f.type is FieldType.HIDDEN:
            if a is not None:
                audit[f.key] = a
            continue
        val = shown.get(f.key, "")
        if policy is PrefillPolicy.KEEP:
            what = keep_decision(f, a, val, ctx_email)
            conf = 0.95
        else:
            what = overwrite_decision(f, a, val)
            conf = 0.9
        if what == KEEP:
            audit[f.key] = _prefilled(f, a, val, source, conf)
            continue
        if what == OVERWRITE and a.fills and f.type is not FieldType.FILE                 and same_value(f, a, val):
            audit[f.key] = dataclasses.replace(a, note=_join(a.note, "already on page"))
            continue
        if what == OVERWRITE and a.fills and not _is_empty(val):
            a = dataclasses.replace(a, note=_join(a.note, "replaced site value"))
        audit[f.key] = to_fill[f.key] = a
    return audit, to_fill


def _join(*notes: str) -> str:
    return "; ".join(n for n in notes if n)


def _flagged(fields: Sequence[FormField], errors: Sequence[str]) -> list[FormField]:
    """The fields an error list names (labels compared after §7.1 normalisation)."""
    errs = [norm_label(e) for e in errors if e]
    out = []
    for f in fields:
        lab = norm_label(f.label)
        if lab and any(e == lab or (len(lab) > 3 and lab in e) or e == norm_label(f.key)
                       for e in errs):
            out.append(f)
    return out


# ---------------------------------------------------------------- run lock (review F4)

class RunLock:
    """One apply run at a time per database, across processes (the web job
    and a CLI run): an OS file lock on `<evidence root>/run.lock`. The OS
    drops it when the process dies, so a crashed run never blocks the next
    one, and only the lock holder may reap (§4.3: the reaper must not close
    a live attempt of another run)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None


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
        if self.acfg.captcha_wait_s > 0:              # review F7: accepted deferral, said out loud
            self.log("apply: captcha_wait_s is not supported yet; a CAPTCHA ends the attempt at once")
        self.rules = None
        self.seen: set[str] = set()
        self._resume_text: Optional[str] = None
        self._aliases = None

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
            cap = self.cap_refusal(job)
            if cap:
                raise cap
        if self.store.attempts_in_flight(exclude_id=at.id):
            raise ApplyFailure(ReasonCode.ERROR, "another application is in progress")

    def cap_refusal(self, job: dict[str, Any]) -> Optional[ApplyFailure]:
        """§12.1 (3): today's clicks against the caps (Asia/Singapore day)."""
        total, employer = self.store.apply_counts(job.get("company_id"), day_start_utc())
        if total >= self.acfg.daily_cap:
            return ApplyFailure(ReasonCode.CAP_REACHED, f"{total} of {self.acfg.daily_cap} today")
        if employer >= self.acfg.per_employer_daily_cap:
            return ApplyFailure(ReasonCode.CAP_REACHED,
                                f"{employer} of {self.acfg.per_employer_daily_cap} today at "
                                f"{job.get('company') or 'this employer'}")
        return None

    def claim_click(self, at: _Attempt, job: dict[str, Any]) -> None:
        """The pre-click write (NF-06, review F4), in one write transaction:
        re-run the duplicate and cap checks (state may have changed since the
        guards), then stamp `submit_clicked_at` only if the attempt is still a
        live, unclicked `filling` row (compare-and-set). Commits; raises
        ApplyFailure (nothing clicked) on a refusal."""
        st = self.store
        st.begin_immediate()
        try:
            dup = st.apply_duplicate(job["job_id"])
            refusal = ApplyFailure(ReasonCode.DUPLICATE, dup) if dup else self.cap_refusal(job)
            if refusal is None and not st.mark_submit_clicked(at.id, utcnow()):
                refusal = ApplyFailure(ReasonCode.ERROR, "the attempt was closed by another run")
        except BaseException:
            st.rollback()
            raise
        if refusal is not None:
            st.rollback()
            raise refusal
        st.commit()

    # -- resume (TD §12: the tailored file, else the original)

    def resume(self, at: _Attempt, job: dict[str, Any]) -> str:
        """`tailoring` when the tailor is on: the current tailored file (or a
        fresh one) in `apply.resume_format`; any tailor failure falls back to
        the original resume with a log line (never a failed attempt)."""
        original = applicant.resume_file(self.profile, self.cfg.resume_dir)
        if original is None:
            raise ApplyFailure(ReasonCode.PROFILE_INCOMPLETE, "documents.resume")
        if self.cfg.tailor.enabled:
            at.to(S.TAILORING, step="tailoring")
            try:
                res = tailor_flow.tailor_for_apply(self.cfg, self.store, job["job_id"],
                                                   backend=self.backend, say=None)
                path = tailor_flow.upload_path(res, self.acfg.resume_format)
                note = res.error or "no tailored file"
            except Exception as exc:                      # noqa: BLE001 - the original still works
                res, path, note = None, None, type(exc).__name__
            if path:
                p = Path(path)
                at.tailored_id = res.tailored_id
                self.store.update_attempt(at.id, resume_file=p.name, resume_sha256=sha256_file(p),
                                          resume_source="tailored", tailored_id=res.tailored_id)
                self.log(f"[attempt {at.id}] resume: tailored ({p.suffix.lstrip('.')}), "
                         f"coverage {res.coverage_before:.0%} -> {res.coverage_after:.0%}")
                return str(p)
            self.log(f"[attempt {at.id}] resume: original ({note[:120]})")
        self.store.update_attempt(at.id, resume_file=original.name,
                                  resume_sha256=sha256_file(original), resume_source="original")
        return str(original)

    # -- resolution (§7)

    def resume_text(self, resume_path: str) -> str:
        """The grounding corpus (§7.7, D-68): the tailor's parsed master, else
        the text extracted from the resume file; "" if neither can be read."""
        if self._resume_text is None:
            text = tailor_flow.master_text(self.cfg)
            if not text:
                original = applicant.resume_file(self.profile, self.cfg.resume_dir)
                try:
                    from .profile import resume_ingest
                    text = resume_ingest.extract_text(original) if original else ""
                except Exception:                         # noqa: BLE001 - an empty corpus fails closed
                    text = ""
            self._resume_text = text or ""
        return self._resume_text

    def resolve_ctx(self, job: dict[str, Any], tenant: Any, adapter: Any,
                    resume_path: str) -> ResolveContext:
        aliases = tuple(dict.fromkeys(a for a in (job.get("company_key"), tenant.board)
                                      if a and a != job.get("company")))
        if self._aliases is None:
            self._aliases = tailor_flow.alias_groups(self.cfg)
        groups, ambiguous = self._aliases
        # ResolveContext has no job title yet (Q-27): the company only.
        return ResolveContext(
            profile=self.profile, employer_name=str(job.get("company") or ""),
            employer_aliases=aliases,
            previously_applied=self.store.applied_to_company(job.get("company_id"), job["job_id"]),
            jd_text=str(job.get("jd_text") or ""), resume_text=self.resume_text(resume_path),
            resume_path=resume_path, ats=adapter.name, alias_groups=groups,
            alias_ambiguous=ambiguous,
            account_email=str(_profile_path(self.profile, "contact.email") or ""))

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
        self.store.commit()
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
            if at.clicked:                                # NF-06: never failed after the click
                self.unconfirmed(at, f"{exc.reason.value} after submit")
            else:
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
        """End before the click: evidence, the audit so far, `failed(reason)`.
        A row that is already terminal (closed by another run) is left as it is."""
        row = self.store.attempt(at.id)
        if row is not None and row["state"] in TERMINAL_ATTEMPT_STATES:
            self.log(f"[attempt {at.id}] stopped: {reason.value} {detail} "
                     f"(the row was already {row['state']})")
            at.state = at.result.state = S(row["state"])
            at.result.reason, at.result.reason_detail = reason, detail
            return
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
        if not hasattr(adapter, "read_step"):
            # D-78 lane N: a navigation-only module (Workday) is registered before the
            # page-filling loop that drives it (WP-N6). Until then it stops here,
            # before Edge opens: nothing is opened, typed or created on the site.
            raise ApplyFailure(ReasonCode.UNSUPPORTED_ATS,
                               f"{adapter.name}: form filling arrives with WP-N6",
                               step="planning")
        ctx = AttemptContext(
            attempt_id=at.id, job=job, tenant=tenant, dry_run=self.dry_run,
            email=str(_profile_path(self.profile, "contact.email") or ""),
            resume_path=resume_path, log=lambda line: self.log(f"[attempt {at.id}] {line}"),
            screenshot=at.shot,
            # D-81: Workday's wizard gets its own budget; both exclude the IMAP wait.
            deadline=time.monotonic() + (acfg.attempt_timeout_workday_s
                                         if adapter.name == "workday"
                                         else acfg.attempt_timeout_s),
            http=self.http,
            applied_on_tenant=self.store.applied_on_tenant(adapter.name, tenant.host))
        rctx = self.resolve_ctx(job, tenant, adapter, resume_path)
        plan = adapter.plan_from_schema(ctx)
        if plan is not None:
            self.store.update_attempt(at.id, plan_source=plan.source)
            answers = self.resolve(plan.fields, rctx, at)
            bad = _unanswerable(plan.fields, answers)
            if bad and self.prefill_may_answer(adapter):
                # D-70 §9.1.1: MyGreenhouse may hold the answer; re-checked after the prefill.
                self.log(f"[attempt {at.id}] planning: a required question has no answer yet; "
                         f"checked again after the {adapter.prefill_source} autofill")
            elif bad:
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
        if wall:                       # accounts, sign-in, sign-up, email check (WP-N4)
            rctx = self.account(page, ctx, adapter, at, job, rctx)
            self.check_page(page, at)
        at.to(S.FILLING, step="application")

        # prefill (D-70): the site's own autofill, once, before the first step
        try:
            ctx.prefill = adapter.prefill(page, ctx) or ctx.prefill or ""
        except Exception as exc:                          # noqa: BLE001 - fall back to the full fill
            self.log(f"[attempt {at.id}] prefill skipped: {self.log.exc(exc)}")
            ctx.prefill = ""
        if ctx.prefill:
            self.log(f"[attempt {at.id}] prefill: {ctx.prefill}")

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
            if ctx.prefill:
                shown = adapter.read_values(page, ctx, fields)
                audit, step_answers = apply_prefill_policy(ctx.prefill, fields, step_answers,
                                                           shown, ctx.email)
                at.answers.update(audit)
            bad = _unanswerable(fields, {f.key: at.answers[f.key] for f in fields
                                         if f.key in at.answers})
            if bad:
                raise bad
            self.check_page(page, at)
            self.fill(page, ctx, adapter, at, fields, step_answers)
            at.shot(page, step)
            self.check_page(page, at)
            res = adapter.next_step(page, ctx)
            if res.errors:                               # one corrective retry (§9.4.9)
                self.log(f"[attempt {at.id}] errors after Next: {', '.join(res.errors[:3])}")
                self.correct(page, ctx, adapter, at, fields, res.errors, rctx)
                res = adapter.next_step(page, ctx)
                if res.errors:
                    raise ApplyFailure(ReasonCode.VALIDATION_ERROR,
                                       ", ".join(e[:80] for e in res.errors[:3]), step=step)
            at.record(step, fields)
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

    def prefill_may_answer(self, adapter: Any) -> bool:
        """Is a planning-time unknown worth taking to the browser? Only when
        the adapter's own prefill is on (Greenhouse: `apply.mygreenhouse`)."""
        src = getattr(adapter, "prefill_source", "")
        return src == AnswerSource.MYGREENHOUSE.value and self.acfg.mygreenhouse

    def correct(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
                fields: Sequence[FormField], errors: Sequence[str], rctx: ResolveContext) -> None:
        """The flow's half of the corrective retry (§9.4.9 steps 2-3): re-fill a
        flagged field we answered; re-resolve one the site wants after all
        (blank or prefilled) as required; no answer -> unanswerable_required."""
        redo: dict[str, Answer] = {}
        for f in _flagged(fields, errors):
            a = at.answers.get(f.key)
            if a is not None and a.status is AnswerStatus.FILL_FAILED:
                a = dataclasses.replace(a, status=AnswerStatus.FILLED)
            if a is not None and a.fills:
                redo[f.key] = dataclasses.replace(a, note=_join(a.note, "re-filled after an error"))
                continue
            again = self.resolve([dataclasses.replace(f, required=True)], rctx, at)[f.key]
            if not again.fills:
                raise ApplyFailure(ReasonCode.UNANSWERABLE_REQUIRED, f.label[:120], step=at.step)
            redo[f.key] = dataclasses.replace(again, note=_join(again.note, "the site required it"))
        at.answers.update(redo)
        if redo:
            self.fill(page, ctx, adapter, at, [f for f in fields if f.key in redo], redo)

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
        # No button, no click: a missing Submit fails before anything is
        # recorded (review F3), instead of a clicked-but-unsent attempt.
        ready = getattr(adapter, "submit_ready", None)
        if ready is not None and not ready(page):
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"{adapter.name}: submit button",
                               step="review")
        # The click is recorded and committed BEFORE it happens (NF-06),
        # after a last duplicate + cap check (review F4).
        self.claim_click(at, job)
        at.clicked = True
        at.to(S.SUBMITTING, step="submit")
        try:
            adapter.submit(page, ctx)
            outcome, note = self.await_confirmation(page, ctx, adapter)
            if outcome is None and note == CODE_REQUIRED:
                outcome, note = self.code_after_submit(page, ctx, adapter, at, job)
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
        """The tailored file that was uploaded is now `sent` (TD §12)."""
        if at.tailored_id is not None:
            self.store.mark_tailored_sent(at.tailored_id)

    # -- accounts and mail (N-block; apply_design §10.2, §10.5, §11, §4.2;
    #    llm_fill_build_plan WP-N4 = WP-V4 without the entry rule and the review notes)

    def account(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
                job: dict[str, Any], rctx: ResolveContext) -> ResolveContext:
        """The account wall: choose the identity (§10.5), sign in or sign up,
        check the email when the site asks. `ctx.email` becomes the identity, and
        so does the returned ResolveContext's `account_email` (tier-1 EMAIL then
        answers with the address the account uses)."""
        tenant = ctx.tenant
        service = vault.service_for(adapter.name, tenant.host)
        primary = str(_profile_path(self.profile, "contact.email") or "").strip()
        backup = str(_profile_path(self.profile, "contact.backup_email") or "").strip()
        rows = self.store.accounts_for_tenant(adapter.name, tenant.host)
        ident = choose_identity(primary, backup, rows,
                                lambda e: vault.get(service, e) is not None)
        ctx.email = ident.email
        which = "backup" if backup and ident.email.lower() == backup.lower() else "main"
        self.log(f"[attempt {at.id}] account: {ident.action.replace('_', ' ')} with the {which} email")
        if ident.action == SIGN_IN:
            self.sign_in(page, ctx, adapter, at, job, service)
        else:
            self.sign_up(page, ctx, adapter, at, job, service, primary, backup)
        return dataclasses.replace(rctx, account_email=ctx.email)

    def _account_id(self, adapter: Any, ctx: AttemptContext, service: str, at: _Attempt,
                    status: str) -> int:
        row = self.store.account(adapter.name, ctx.tenant.host, ctx.email)
        if row is not None:
            return int(row["id"])
        return self.store.upsert_account(adapter.name, ctx.tenant.host, ctx.email, service,
                                         status, created_by_attempt=at.id)

    def sign_in(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
                job: dict[str, Any], service: str, *, after_check: bool = False) -> None:
        """One sign-in with the identity's vault password. A rejection marks the
        row `signin_failed` (never retried automatically: lock-out risk)."""
        at.to(S.SIGNING_IN, step="signing_in")
        secret = vault.get(service, ctx.email)
        if secret is None:
            raise ApplyFailure(ReasonCode.LOGIN_FAILED,
                               "JobScraper has no saved password for this account.")
        acc_id = self._account_id(adapter, ctx, service, at, AccountStatus.CREATED.value)
        try:
            adapter.sign_in(page, ctx, secret)
        except ApplyFailure as exc:
            if exc.reason is ReasonCode.LOGIN_FAILED:
                self.store.set_account_status(acc_id, AccountStatus.SIGNIN_FAILED.value,
                                              last_signin_ok=0)
            raise
        row = self.store.account(adapter.name, ctx.tenant.host, ctx.email)
        self.store.set_account_status(acc_id, row["status"] if row else AccountStatus.CREATED.value,
                                      last_signin_at=utcnow(), last_signin_ok=1)
        if not after_check and classify(page) is PageSignal.VERIFY_EMAIL:
            self.check_email(page, ctx, adapter, at, job, service)

    def sign_up(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
                job: dict[str, Any], service: str, primary: str, backup: str) -> None:
        """§10.2: the password is in the vault (read back) and the row is
        `creating` BEFORE the sign-up click. "Already registered" on the main
        email → one sign-up with the backup email (§10.5; the one allowed
        signing_up → signing_up). A field error rolls the vault entry and the row
        back; any other exception keeps both (`unknown`: the next attempt signs
        in with the stored password)."""
        if not _profile_path(self.profile, "consents.privacy_consent"):
            raise ApplyFailure(ReasonCode.UNANSWERABLE_REQUIRED, "account terms")
        host = ctx.tenant.host
        tried_backup = False
        while True:
            at.to(S.SIGNING_UP, step="signing_up")
            secret = vault.generate(adapter.password_rules)
            try:
                vault.put(service, ctx.email, secret)
            except vault.VaultError:
                raise ApplyFailure(ReasonCode.ERROR, "the password could not be stored") from None
            acc_id = self.store.upsert_account(adapter.name, host, ctx.email, service,
                                               AccountStatus.CREATING.value,
                                               created_by_attempt=at.id)
            try:
                outcome = adapter.sign_up(page, ctx, secret)
            except ApplyFailure as exc:
                if exc.reason is ReasonCode.VALIDATION_ERROR:     # refused before accepting
                    vault.delete(service, ctx.email)
                    self.store.delete_account(acc_id)
                else:
                    self.store.set_account_status(acc_id, AccountStatus.UNKNOWN.value)
                raise
            except Exception:
                self.store.set_account_status(acc_id, AccountStatus.UNKNOWN.value)
                raise
            if outcome != SignUpOutcome.ALREADY_REGISTERED.value:
                self.store.set_account_status(acc_id, AccountStatus.CREATED.value)
                break
            vault.delete(service, ctx.email)              # the generated password was never accepted
            self.store.set_account_status(acc_id, AccountStatus.EXISTS_NO_PASSWORD.value)
            rows = self.store.accounts_for_tenant(adapter.name, host)
            if (not tried_backup and backup and ctx.email.lower() == primary.lower()
                    and backup.lower() not in rows):
                tried_backup = True
                ctx.email = backup
                self.log(f"[attempt {at.id}] account: the main email is already registered "
                         "here; signing up with the backup email")
                continue
            raise ApplyFailure(ReasonCode.LOGIN_FAILED,
                               BOTH_NO_PASSWORD_DETAIL if backup else NO_PASSWORD_DETAIL)
        self.log(f"[attempt {at.id}] account: created ({outcome})")
        if outcome == SignUpOutcome.VERIFY_EMAIL.value or classify(page) is PageSignal.VERIFY_EMAIL:
            self.check_email(page, ctx, adapter, at, job, service)
        elif outcome == SignUpOutcome.SIGN_IN.value:
            self.sign_in(page, ctx, adapter, at, job, service)

    def check_email(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
                    job: dict[str, Any], service: str) -> None:
        """`verifying_email` before the click (AD §9.4.4): the link or code from
        the identity's mailbox, then sign in (once more) or reopen the posting.
        The row becomes `verified`."""
        at.to(S.VERIFYING_EMAIL, step="verifying_email")
        v = self.wait_for_mail(ctx, adapter, at, job, want="either")
        if v.kind == "link":
            page.goto(v.value, wait_until="domcontentloaded")
            B.settle(page)
        else:
            adapter.enter_code(page, ctx, v.value)
        acc_id = self._account_id(adapter, ctx, service, at, AccountStatus.CREATED.value)
        self.store.set_account_status(acc_id, AccountStatus.VERIFIED.value, verified_at=utcnow())
        self.check_page(page, at)
        wall = adapter.account_wall(page)
        if wall is None and getattr(adapter, "step_id", None) is not None \
                and not adapter.step_id(page, ctx):
            adapter.open(page, ctx)                       # candidate home or a notice: back to the posting
            self.check_page(page, at)
            wall = adapter.account_wall(page)
        if wall == "sign_in":
            self.sign_in(page, ctx, adapter, at, job, service, after_check=True)
        elif wall:
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED,
                               f"{adapter.name}: account form after the email check")

    def wait_for_mail(self, ctx: AttemptContext, adapter: Any, at: _Attempt,
                      job: dict[str, Any], *, want: str):
        """The verification mail for `ctx.email` (§11, §11.5): its own mailbox,
        `to_addr` = the identity, mail since the attempt started. The wait does
        not count against the attempt deadline (NF-07, review Q-35 M11).
        Raises ApplyFailure(MAIL_NOT_SET_UP / EMAIL_VERIFICATION_TIMEOUT)."""
        settings = mail.effective_settings(self.cfg, self.store.get_setting)
        watcher = mail.watcher_for(ctx.email, self.profile, settings)
        employer = mail.employer_domain(str(job.get("careers_url") or ""))
        extra = (employer,) if employer else ()
        links = (ctx.tenant.host,) + tuple(getattr(adapter, "link_domains", adapter.mail_domains)) + extra
        row = self.store.attempt(at.id) or {}
        started = row.get("started_at") or utcnow()
        since = datetime.strptime(started, TIME_FMT).replace(tzinfo=timezone.utc)
        t0 = time.monotonic()
        try:
            v = watcher.wait_for(since_utc=since,
                                 sender_domains=tuple(adapter.mail_domains) + extra,
                                 link_domains=links, otp_pattern=adapter.otp_pattern or None,
                                 want=want, wait_s=int(settings.get("apply.mail.wait_s") or 300),
                                 poll_s=int(settings.get("apply.mail.poll_s") or 10),
                                 to_addr=ctx.email)
        finally:
            ctx.deadline += time.monotonic() - t0
        self.log(f"[attempt {at.id}] verification mail found ({v.kind}) from {v.sender_domain}")
        return v

    def code_after_submit(self, page: Any, ctx: AttemptContext, adapter: Any, at: _Attempt,
                          job: dict[str, Any]):
        """§4.2 (Greenhouse): the emailed security code, entered once, then the
        same submission's Submit once more (`code_resubmits` ≤ 1). Any problem
        → (None, note): the caller ends `submitted_unconfirmed` (NF-06)."""
        row = self.store.attempt(at.id) or {}
        if int(row.get("code_resubmits") or 0) >= 1:
            return None, "a second security code was asked for"
        at.to(S.VERIFYING_EMAIL, step="verifying_email")
        try:
            v = self.wait_for_mail(ctx, adapter, at, job, want="code")
        except ApplyFailure as exc:
            if exc.reason is ReasonCode.MAIL_NOT_SET_UP:
                return None, "security code needed; mailbox not set up"
            return None, f"security code: {exc.reason.value}"
        adapter.enter_code(page, ctx, v.value)
        self.store.update_attempt(at.id, code_resubmits=int(row.get("code_resubmits") or 0) + 1)
        at.to(S.SUBMITTING, step="submit")
        adapter.submit(page, ctx)
        outcome, note = self.await_confirmation(page, ctx, adapter)
        if outcome is None and note == CODE_REQUIRED:
            return None, "a second security code was asked for"
        return outcome, note

    def await_confirmation(self, page: Any, ctx: AttemptContext, adapter: Any):
        """(confirmation signal, "") or (None, note) within `confirm_timeout_s`."""
        end = time.monotonic() + self.acfg.confirm_timeout_s
        while True:
            got = adapter.after_submit(page, ctx)
            if got and got.startswith("confirmed:"):
                return got.split(":", 1)[1], ""
            if got == "code_required":            # the emailed code (§4.2): code_after_submit
                return None, CODE_REQUIRED
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
        lock = RunLock(self.evidence / "run.lock")
        if not lock.acquire():
            self.log("apply: another apply run is in progress; nothing was started")
            return []
        results = []
        try:
            reaped = self.store.reap_attempts(utcnow())
            if reaped:
                self.log(f"apply: closed {reaped} interrupted attempt(s)")
            for job_id in job_ids:
                results.append(self.attempt(job_id))
            ready = [r for r in results if r.state is S.READY_TO_SUBMIT]
            if ready and self.session is not None and self.acfg.dry_run_hold_s > 0:
                self.log(f"apply: dry run - the filled form(s) stay open for up to "
                         f"{self.acfg.dry_run_hold_s} s; close the window to finish sooner")
                self.session.hold(self.acfg.dry_run_hold_s)
        finally:
            try:
                self.close()
            finally:
                lock.release()
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
