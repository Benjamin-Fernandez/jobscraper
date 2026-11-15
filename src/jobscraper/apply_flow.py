"""Auto-apply orchestrator: queue -> guards -> tailor -> detect -> plan ->
resolve -> browser -> submit -> record (apply_design §3, KA-1).

`run()` (the batch, `apply <ids>`) and `run_queue()` (the auto-apply queue
worker, `apply queue`, apply_queue_design §3.2) are the public entry points;
`cmd_apply` calls them. One Edge
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

from . import applicant, backends, tailor_flow, vault
from .apply import always as AL
from .apply import briefing as BR
from .apply import browser as B
from .apply import declarations
from .apply import llm_fill
from .apply import facts as F
from .apply import mail
from .apply import page as P
from .apply import questions as Q
from .apply import resolve as R
from .apply.accounts import BOTH_NO_PASSWORD_DETAIL, NO_PASSWORD_DETAIL, SIGN_IN, choose_identity
from .apply.classify import PageSignal, classify
from .apply.contracts import (
    ALWAYS_OURS, CHOICE_TYPES, EMPLOYER_SPECIFIC_DECLARATIONS, POST_CLICK_STATES, PREFILL_POLICY,
    REASON_TEXTS, STATE_TEXTS, TERMINAL_STATES, TRANSITIONS, AccountStatus, Answer, AnswerSource,
    AnswerStatus, AnswerTier, ApplyFailure, AttemptContext, AttemptResult, AttemptState, Canonical,
    FieldType, FillPolicy, FormField, PageOutcome, PrefillPolicy, QuestionReason, ReasonCode,
    ResolveContext, SignUpOutcome,
)
from .apply.contracts import (FIELD_CLASS_CHOICES, FIELD_CLASS_SEP, MODEL_PAUSE_BY_CODE,
                              QUEUE_PAUSE_TEXTS, RETURNS_ITEM, FieldClass, QueuePause,
                              extra_entry_applies)
from .apply.contracts import CONSENT_REFUSED_DETAILS, CONTENT_FAILURE_MARKERS, CONTENT_FAILURE_TEXT
from .apply.detect import detect
from .apply.pagefill import (ENTRY_NOTE_PREFIX, ENTRY_NOTE_TAIL, TYPED_BEFORE_STOP_NOTE, fill_page,
                             stored_quote)
from .apply.plan import norm_label
from .config import ApplyConfig, Config, fill_policy_value
from .scrape.net import HttpClient
from .tailor.contracts import ComposeRequest
from .store import (ATTEMPT_TRANSITIONS, POST_CLICK_ATTEMPT_STATES, TERMINAL_ATTEMPT_STATES,
                    TIME_FMT, Store, shift, utcnow)

S = AttemptState
SG = timezone(timedelta(hours=8))        # Asia/Singapore: no DST since 1982, so a fixed offset
REDACTED = "[redacted]"
_BLANK = (None, "", [])
CODE_REQUIRED = "code_required"          # await_confirmation's note for §4.2's emailed code
# pagefill's always-path line after a short "Add another" (`_always_adds`, rev L7; review F5)
_E5_SHORT = re.compile(r"^E5: (?P<added>\d+) of (?P<wanted>\d+) (?P<section>[a-z][a-z ]{0,40}?) "
                       r"entries added\b")


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
    """`line` with every value replaced by "[redacted]" (the scrubber lives in
    `applicant.scrub`, so the resolver can share it; see there for the matching
    rules, review F6)."""
    return applicant.scrub(line, values, REDACTED)


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
        # D-202: the values blanked in a stored unchecked model quote (`facts.quote_s_values`),
        # set from every ResolveContext the attempt fills with, before its first `record`
        self.quote_values: tuple[str, ...] = ()
        self.always = False           # Q-121: the attempt fills under the effective policy `always`
        self.trial = False            # Q-121 §12: a first-use trial attempt (a dry run under `always`)
        # Q-121 review F5: "1 of 2 education entries added" per section whose Add fell short
        # under `always` (a note, not a stop); stored as `apply_attempts.entries_note`
        self.entries: dict[str, str] = {}

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
            if reason is ReasonCode.UNANSWERABLE_REQUIRED and is_content_failure(
                    {"state": S.FAILED.value, "reason_code": reason.value, "reason_detail": detail}):
                rt = CONTENT_FAILURE_TEXT           # A1 §17.6: not the "answer it in Profile" copy
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
        out = (f"fields={len(a)} filled={n(AnswerStatus.FILLED, AnswerStatus.PREFILLED)} "
               f"blank={n(AnswerStatus.BLANK_OPTIONAL)} "
               f"unknown={n(AnswerStatus.UNKNOWN, AnswerStatus.UNGROUNDED)} tier5={tier5}")
        if self.always:                   # Q-121 §6.2: the attempt summary counts assumptions
            out += f" assumed={self.assumed_count()}"
            if self.entries:              # review F5: and says when an Add fell short
                out += f" entries=\"{self.entries_note()}\""
        return out

    def entries_note(self) -> str:
        """The F5 note: "1 of 2 education entries added" (sections joined with "; ")."""
        return "; ".join(self.entries.values())

    def entries_short(self, line: str) -> None:
        """Record pagefill's always-path E5 log line ("E5: 1 of 2 education entries added
        (<why>)") on the attempt and its row (`entries_note`); the latest count per section
        wins (a page filled again). The why is not kept (counts only, K10). Never raises."""
        m = _E5_SHORT.match(str(line or ""))
        if not m:
            return
        self.entries[m["section"]] = f"{m['added']} of {m['wanted']} {m['section']} entries added"
        try:
            self.store.update_attempt(self.id, entries_note=self.entries_note()[:200])
            self.store.commit()
        except Exception:                                 # noqa: BLE001 - a note never changes an outcome
            pass

    def assumed_count(self) -> int:
        """Answers put on the page with an assumption (§6.2; counts only, K10)."""
        return sum(1 for x in self.answers.values() if getattr(x, "assumed", False)
                   and x.status in (AnswerStatus.FILLED, AnswerStatus.PREFILLED))

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
            rows.append(audit_row(step, f, a, self.quote_values))
        if rows:
            self.store.add_answers(self.id, rows)
            self.store.commit()

    def record_all(self) -> None:
        """Every resolved field not recorded yet (an attempt that ends early)."""
        self.record(self.step, list(self.fields.values()))


COMPOSED_FILE_NOTE = "composed file: "          # locks L8: the note that names the uploaded letter


def _composed_file(f: FormField, a: Answer) -> bool:
    """A composed FILE row: its value is the letter's TEXT (LF 19.5), not a path; the file's
    name is in the note and its real path is `ctx.composed_files[key]`."""
    return f.type is FieldType.FILE and a.source == AnswerSource.COMPOSED.value


def _composed_note(path: str) -> str:
    """`composed file: <name> (sha256 <hex>)`: what the audit row says about the uploaded letter."""
    p = Path(path)
    try:
        return f"{COMPOSED_FILE_NOTE}{p.name} (sha256 {sha256_file(p)})"
    except OSError:
        return f"{COMPOSED_FILE_NOTE}{p.name}"


def _sent_value(f: FormField, a: Answer) -> Any:
    """The exact value sent, for the audit: a file as name + SHA-256 (never
    the path); None when nothing is (or will be) on the page."""
    if a.value in _BLANK or a.status not in (AnswerStatus.FILLED, AnswerStatus.PREFILLED,
                                             AnswerStatus.FILL_FAILED):
        return None
    if _composed_file(f, a):                          # LF 19.5: the audit holds the whole text
        return a.value
    if f.type is FieldType.FILE and a.status is not AnswerStatus.PREFILLED:
        p = Path(str(a.value))
        try:
            return {"file": p.name, "sha256": sha256_file(p)}
        except OSError:
            return {"file": p.name, "sha256": ""}
    return a.value


def stored_class(a: Answer) -> str:
    """Q-127 B.5 (H3): the field class a row is stored with, a FIELD_CLASS_CHOICES string or "".
    The class the filler decided (`Answer.field_class`, `always`) wins. Without one (`strict`,
    or a path that does not stamp it) a tier-4 declaration answer, whose source is
    `declaration:<label>` and which the code's declaration reader wrote, is `declaration:<label>`:
    `web/` may not import `apply.declarations`, so the class is written at fill time and
    "Use a different answer next time" can refuse it by class, not only by source. A class the
    reader names that has no class of its own is `declaration:other` (an agreed set "a+b" takes
    its first label with a class), disability is a self-ID. Anything else is "" (NULL-like)."""
    if a.field_class:
        return a.field_class
    if a.source_kind is not AnswerSource.DECLARATION:
        return ""
    for name in (a.source.split(":", 1)[1] if ":" in a.source else "").split("+"):
        if name == "disability":
            return f"{FieldClass.SELF_ID.value}{FIELD_CLASS_SEP}disability"
        choice = f"{FieldClass.DECLARATION.value}{FIELD_CLASS_SEP}{name}"
        if choice in FIELD_CLASS_CHOICES:
            return choice
    return f"{FieldClass.DECLARATION.value}{FIELD_CLASS_SEP}other"


def audit_row(step: str, f: FormField, a: Answer,
              quote_values: Sequence[str] = ()) -> dict[str, Any]:
    """One `apply_answers` row. `evidence` (D-202): a quote the guards checked on a field
    that took a value is kept verbatim, any other with `quote_values` redacted
    (`pagefill.stored_quote`); rows with no quote stay None. `field_class` (Q-127): see
    `stored_class`; "" when none is known, NULL on rows written before schema v9."""
    return {
        "step": step, "field_key": f.key, "label": f.label, "label_norm": norm_label(f.label),
        "field_type": f.type.value, "required": f.required, "section": f.section,
        "options_json": [{"label": o.label, "value": o.value} for o in f.options] or None,
        "value_json": _sent_value(f, a), "tier": int(a.tier), "source": a.source,
        "confidence": a.confidence, "status": a.status.value, "rule_id": a.rule_id,
        "model": a.model, "prompt_hash": a.prompt_hash, "note": a.note,
        "sensitive": a.sensitive or f.section in ("compliance", "demographic"),
        # D-78 columns (llm_fill_design §14): local DB only; empty on the pre-D-78 path.
        "evidence": stored_quote(a.evidence, a, quote_values) or None,
        "shown_json": a.shown if a.shown not in _BLANK else None,
        "shown_origin": a.origin or None, "entry": a.entry or None,
        "assumed": bool(getattr(a, "assumed", False)),         # Q-121 §6.1 (always 0 under strict)
        "field_class": stored_class(a),                        # Q-127 v9 (H3)
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
    if _composed_file(f, a):                          # the value is the text; the page shows the file
        name = (a.note or "").partition(COMPOSED_FILE_NOTE)[2].split(" (", 1)[0].strip()
        return name or a.value
    if f.type is FieldType.FILE:
        return Path(str(a.value)).name
    if f.fit_type in CHOICE_TYPES and a.option_labels:
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


def _entry_problem(a: Any) -> str:
    """The section note pagefill put on a row after a failed E5 Add ("another work experience
    entry could not be added (<why>)"), else ""."""
    note = (getattr(a, "note", "") or "")
    i = note.find(ENTRY_NOTE_PREFIX)
    if i < 0:
        return ""
    return note[i + len("E5: "):].split(ENTRY_NOTE_TAIL)[0].strip()


def _transport_cause(outcome: PageOutcome, watch: Any = None) -> str:
    """What the first "transport: ..." row note says (N6a F5): "model unavailable", "timed
    out", ... so a model that died mid-attempt isn't reported as a timeout. When no row
    carries one (the `always` path writes no such notes), what the backend watch saw
    (`_RefusalWatch.failure`, review D4); the old wording when neither says."""
    for pf in outcome.fields:
        a = outcome.answers.get(pf.field.key)
        note = (a.note if a is not None else "") or ""
        if note.lower().startswith("transport:"):
            return note.split(":", 1)[1].strip().split(";")[0].strip() or "timed out"
    seen = getattr(watch, "failure", "") if isinstance(watch, _RefusalWatch) else ""
    return seen or "timed out"


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


# ---------------------------------------------------------------- fill policy (Q-121, D-208)
#
# llm_first_fill_design §2 K2, §7.2: `apply.fill_policy: always` takes effect only with the
# local model (backends.is_local) and the LLM page filler (`apply.fill: llm`); otherwise the
# attempt runs `strict`, today's path, and the log says why. The code default is `strict`.

POLICY_NOT_LOCAL = "fill_policy always ignored: model not on this computer"
POLICY_NOT_LLM = "fill_policy always ignored: apply.fill is not llm"
# D-223 release lock: `always` is also ignored until the config file releases it
# (`apply.always_available: true`; no settings row, route or flag can set that).
POLICY_NOT_RELEASED = "fill_policy always ignored: not released on this install"
PROMPT_CHECK = "prompt check"            # §9 / K1: the `error` detail when a prompt held a secret
TRIAL_NOTE = "Trial: filled, not sent"   # §12 rev H3
NEUTRAL_TEXT = ("I am applying for the {title} role at {employer}. My resume, attached, sets "
                "out my education and experience.")     # §4.8: the last-resort composed text


def effective_policy(acfg: ApplyConfig, backend: Any) -> tuple[FillPolicy, str]:
    """(the effective fill policy, why `always` was not applied or ""). `always` only when
    configured, released on this install (D-223), the model is on this computer (K2) and
    forms go through the LLM page filler. Anything unreadable is `strict`. The one place
    every reader of the policy goes through (`choose_policy`)."""
    if fill_policy_value(getattr(acfg, "fill_policy", "strict")) != FillPolicy.ALWAYS.value:
        return FillPolicy.STRICT, ""
    if getattr(acfg, "always_available", False) is not True:
        return FillPolicy.STRICT, POLICY_NOT_RELEASED
    if getattr(acfg, "fill", "llm") != "llm":
        return FillPolicy.STRICT, POLICY_NOT_LLM
    if not backends.is_local(backend):
        return FillPolicy.STRICT, POLICY_NOT_LOCAL
    return FillPolicy.ALWAYS, ""


class _RefusalWatch:
    """The page filler's backend (both policies since review D2): the same backend, but a
    `PromptRefused` (K1) is remembered, because pagefill reports every BackendError as a
    transport failure and the flow must end the attempt `error` "prompt check", not
    `model_unavailable` (a refusal is never retried as transport)."""

    def __init__(self, backend: Any):
        self._backend = backend
        self.refused = False
        self.failure = ""         # review D4: what the last failed call was ("timed out" | "model unavailable")

    def complete(self, *args: Any, **kw: Any) -> Any:
        try:
            return self._backend.complete(*args, **kw)
        except backends.PromptRefused:
            self.refused = True
            raise
        except TimeoutError:
            self.failure = "timed out"
            raise
        except backends.BackendError as exc:
            self.failure = "timed out" if "timeout" in str(exc).lower().replace("timed out", "timeout") \
                else "model unavailable"
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


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


# ---------------------------------------------------------------- D-78: pages, services, capture (WP-N6a)
#
# `apply.fill: llm` (default): the ATS module only navigates (SiteNavigator); the
# generic page filler (`apply.pagefill.fill_page`) reads each page, asks the local
# model and types. This section holds what the flow owes it: one FillServices per
# attempt (the model, the rules, the clock, the deadline, the classifier) and the
# capture of the required questions nobody could answer (questions_design §4.1,
# llm_fill_design §11). The loop itself is `_Run.body_llm`.

NOT_APPLIED_NOTE = "not applied: the page stopped"
REVIEW_SCAN_FAILED = "review: could not check the required fields"
REVIEW_RESUME_MISSING = "review: resume not shown"


def _squash(text: str) -> str:
    """Lower-case with whitespace collapsed, for the review text check."""
    return " ".join(str(text or "").lower().split())


def _is_navigator(adapter: Any) -> bool:
    """A SiteNavigator (contracts v5): it reads no fields itself. A pre-D-78 adapter
    (`read_step`/`fill`) and a test fake without these members take the old path."""
    return all(hasattr(adapter, n) for n in ("step_id", "scope", "entry_sections",
                                             "choose_entry", "precheck"))


class _FillServices:
    """`FillServices` (contracts v5) for one attempt. The pure steps are module
    functions in `apply/`; this holds what only the flow knows, among it the decision
    cache (`fill_cache`, llm_fill_design §13.3; WP-N6b)."""

    def __init__(self, run: "_Run", at: _Attempt, ctx: AttemptContext, rules: Any,
                 now: Optional[Callable[[], float]] = None):
        self.run, self.at, self.ctx = run, at, ctx
        self.backend = _RefusalWatch(run.backend)       # K1 under both policies (review D2)
        self.model = str(getattr(run.backend, "model_id", "") or getattr(run.backend, "name", ""))
        self.rules = rules
        self.cfg: dict[str, Any] = dataclasses.asdict(run.acfg.llm_fill)
        self.compose_enabled = bool(run.acfg.compose.enabled)     # pagefill step 7b (Q-45, section 19.2)
        self._now = now or run.now

    def now(self) -> float:
        return float(self._now())

    def today(self) -> str:
        return F.today_sg(self.now())

    def deadline_left(self) -> float:
        """Seconds to the attempt deadline; the IMAP wait was added back to it (D-81)."""
        return self.ctx.deadline - time.monotonic()

    def classify(self, page: Any) -> None:
        self.run.check_page(page, self.at)          # raises ApplyFailure; never solves anything

    def cache_get(self, job_id: str, sigs: Sequence[str], prompt_version: str, model: str,
                  inputs_hash: str) -> dict[str, dict[str, Any]]:
        """The job's stored decisions among `sigs` (the caller checks `facts_used_hash`).
        The cache is an optimisation: a store error is a miss, said by type only."""
        try:
            return self.run.store.fill_cache_get(job_id, sigs, prompt_version, model, inputs_hash)
        except Exception as exc:                          # noqa: BLE001 - a miss never fails the attempt
            self.log(f"decision cache unavailable ({type(exc).__name__})")
            return {}

    def cache_put(self, job_id: str, rows: Sequence[dict[str, Any]]) -> None:
        """Keep the page's decisions (a ModelDecision only, never a private value); stamped
        with the attempt's clock so the 30-day purge and tests share one seam (TR-5)."""
        try:
            self.run.store.fill_cache_put(job_id, rows, _stamp(self.now()))
        except Exception as exc:                          # noqa: BLE001 - nothing is lost but a replay
            self.log(f"decision cache not kept ({type(exc).__name__})")

    def log(self, line: str) -> None:
        if self.at.always:                                # review F5: keep the E5 shortfall
            self.at.entries_short(line)
        self.run.log(f"[attempt {self.at.id}] {line}")


FILL_CACHE_DAYS = 30                                      # llm_fill_design §13.3: purged at run start


def _stamp(epoch: float) -> str:
    """UTC epoch seconds as the store's sortable text time."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime(TIME_FMT)


def _fill_services(run: "_Run", at: _Attempt, ctx: AttemptContext, *,
                   now: Optional[Callable[[], float]] = None) -> _FillServices:
    """The FillServices of one attempt (llm_fill_design §8). `now` is the UTC clock
    (`apply_flow.run(..., now=)`, default `time.time`)."""
    return _FillServices(run, at, ctx, run.load_rules(), now)


def _naming_wanted(q: Any, extra: Any, rows: Sequence[dict[str, Any]]) -> bool:
    """Would `assign_key` reach the model (QD §5.2 rule 4)? Not for a profile gap, a
    sensitive question, or a label an `extra` entry or a stored row already holds.
    Never for an "Answered for you" question (reason `assumed`, Q-121 review F2): the
    model's `same_as` could give it another question's key, and Keep would then write the
    AI's guess over the owner's own answer there; it keeps its exact label or a new slug
    (rules 2, 3, 5), and no naming call is spent inside the fill loop."""
    if q.sensitive or q.target_path or getattr(q, "reason", None) is QuestionReason.ASSUMED:
        return False
    for e in Q.existing_keys(extra, rows):
        if e.in_extra and q.label_norm in e.labels:
            return False
    kind = q.kind.value
    return not any(r.get("label_norm") == q.label_norm and str(r.get("kind")) == kind
                   and not r.get("target_path") for r in rows)


def _capture_questions(store: Store, cfg: Config, backend: Any, at: _Attempt, job: dict[str, Any],
                       fields: Sequence[Any], answers: dict[str, Answer], rctx: ResolveContext,
                       rules: Any, *, page: bool = False,
                       found: Optional[Sequence[Any]] = None) -> int:
    """Questions from applications (questions_design §4.1, llm_fill_design §11): every
    required field no tier could answer becomes a `questions` row plus a sighting, so
    the owner answers it once in Profile -> Application details. `fields`/`answers` are
    the resolved FormFields (pre-D-78 path) or, with `page=True`, the PageFields of the
    stopped page. The model only names (never answers, never sees a sensitive question
    or a profile value). Capture can never change an outcome: any exception is logged
    by type only and the attempt ends as it would have. Returns how many were captured.
    `found` (Q-121): CapturedQuestions already chosen (an owner-fact stop, the assumed
    answers of a page under `always`); `fields`/`answers` are then not read."""
    qc = cfg.question_capture
    if not qc.enabled:
        return 0
    try:
        if found is None:
            found = (Q.capture_page if page else Q.capture)(fields, answers, rctx, rules)
        extra = rctx.profile.get("extra") if isinstance(rctx.profile, dict) else None
        calls, said = 0, False
        for q in found:
            rows = store.question_rows()
            suggestion = None
            if (qc.llm_naming and calls < qc.naming_max_per_attempt
                    and not any(r.get("sig") == Q.signature(q) for r in rows)
                    and _naming_wanted(q, extra, rows)):
                calls += 1
                suggestion = Q.ask_model(backend, q, Q.existing_keys(extra, rows),
                                         timeout=qc.naming_timeout_s)
                if suggestion is None and not said:
                    said = True
                    at.log(f"[attempt {at.id}] question naming unavailable")
            choice = Q.assign_key(q, extra, rows, suggestion=suggestion)
            now = utcnow()
            qid = store.upsert_question(Q.question_row(q, choice), now)
            store.add_sighting(qid, at.id, str(job["job_id"]), job.get("company_id"),
                               q.employer_norm, q.ats, q.step, q.field_key, q.label, q.required, now)
            at.log(f"[attempt {at.id}] question captured key={choice.key} kind={q.kind.value} "
                   f"reason={q.reason.value}")
        return len(found)
    except Exception as exc:                          # noqa: BLE001 - capture never changes the outcome
        at.log(f"[attempt {at.id}] question capture failed: {type(exc).__name__}")
        return 0


def _signature(outcome: PageOutcome) -> frozenset:
    """What a page asks, for the loop guard (llm_fill_design §8): label, type and entry."""
    return frozenset((norm_label(pf.field.label), pf.field.type.value, pf.group)
                     for pf in outcome.fields)


# ---------------------------------------------------------------- the run

class _Run:
    def __init__(self, cfg: Config, store: Store, *, dry_run: bool, backend: Any, http: Any,
                 browser_factory: Callable[[ApplyConfig], Any], acfg: ApplyConfig,
                 say: Callable[[str], None], evidence: Optional[Path],
                 now: Optional[Callable[[], float]] = None):
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
        self.now = now or time.time           # UTC epoch seconds: the clock of FillServices (TR-5)
        self.reopened = False                 # check_email sent the page back to the posting (F7)
        self.seen: set[str] = set()
        self._resume_text: Optional[str] = None
        self._resume_entries: Optional[tuple[tuple[str, str, str], ...]] = None
        self._aliases = None
        self.compose_files: dict[str, str] = {}               # audit key -> path of the composed letter file
        self.compose_meta: dict[str, tuple[str, str]] = {}    # audit key -> (model, prompt hash) of a composed text
        # The auto-apply queue (apply_queue_design §3.2); the batch `run()` never sets these.
        self.queue = False                    # run_queue() is driving: reopen a closed window
        self.last_cap = ""                    # "daily" | "employer": which cap refused (review M5)
        self.browser_failed = ""              # why Edge could not start (pause browser_unavailable)
        self.kept_tabs: list[Any] = []        # dry-run tabs left open on a filled form (§5)
        self.item: Optional[dict[str, Any]] = None             # the queue item in flight
        self.apply_cfg_fn: Callable[[], ApplyConfig] = lambda: self.acfg
        self.should_stop: Callable[[], bool] = lambda: False   # the web parent is gone
        self.force_dry_run = False
        # Q-121 (D-208): the effective fill policy of the attempt in flight (K2), set by
        # `attempt` from the item's settings; `strict` keeps every pre-Q-121 behaviour.
        self.policy = FillPolicy.STRICT
        self.compose_assumed: dict[str, str] = {}             # audit key -> why a composed text is assumed
        # Q-126 (D-214, ollama_autostart_design §3): the worker brings the local model up.
        self.model_autostart = False          # library default: never start (cli turns it on)
        self.model_ensurer: Optional[Callable[..., Any]] = None   # None = backends.ensure_model_running
        self.model_pid_alive: Optional[Callable[[int], bool]] = None
        self.model_retried: set[str] = set()  # jobs already sent round once after a model ending
        self.model_retries = 0                # automatic retries this worker run (cap 2, C5)

    # -- browser

    def browser(self):
        if self.session is not None and self.queue and not _session_alive(self.session):
            self.log("apply: the Edge window was closed; opening a new one")
            self.kept_tabs = []
            self.close()
        if self.session is None:
            try:
                self.session = self.browser_factory(self.acfg)
            except Exception as exc:
                self.browser_failed = (
                    "the JobScraper Edge profile is in use"
                    if _names_profile_dir(exc, os.path.expandvars(self.acfg.profile_dir))
                    else f"Edge could not start ({type(exc).__name__})")
                raise
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
        """§12.1 (3): today's clicks against the caps (Asia/Singapore day).
        A cap of 0 means no limit (D-204). `last_cap` says which one refused
        (the queue pauses on the daily one only, review M5)."""
        total, employer = self.store.apply_counts(job.get("company_id"), day_start_utc())
        if self.acfg.daily_cap > 0 and total >= self.acfg.daily_cap:
            self.last_cap = "daily"
            return ApplyFailure(ReasonCode.CAP_REACHED, f"{total} of {self.acfg.daily_cap} today")
        if self.acfg.per_employer_daily_cap > 0 and employer >= self.acfg.per_employer_daily_cap:
            self.last_cap = "employer"
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

    def other_employers(self, job: dict[str, Any], aliases: Sequence[str],
                        groups: Sequence[Sequence[str]]) -> tuple[str, ...]:
        """G12 (llm_fill_design §7): the names a kept or cited text must not carry here: the
        watchlist's companies and the employers question sightings came from, minus this
        employer, its aliases and every spelling in its aliases.yaml group. Names only."""
        mine = [m for m in (str(job.get("company") or ""), *aliases) if m]
        for g in groups:
            if any(declarations.company_match(m, v) for m in mine for v in g):
                mine += [v for v in g if v]
        names = [c.name for c in self.store.companies()] + self.store.sighting_employers()
        return tuple(dict.fromkeys(
            n for n in (str(x).strip() for x in names)
            if n and not any(declarations.company_match(n, m) for m in mine)))

    def profile_here(self, employer: str, aliases: Sequence[str]) -> dict[str, Any]:
        """Q-127 F1: the profile as this employer's attempt may read it. A remembered answer
        saved "only for applications to <employer>" (`extra.<k>.employer`) is dropped from
        `extra` for every other employer, so no reader (tier 3, the briefing, the FACTS list,
        the guards) can reach it, whatever it looks up by key. The same object when nothing
        is dropped."""
        extra = self.profile.get("extra") if isinstance(self.profile, dict) else None
        if not isinstance(extra, dict) or all(
                extra_entry_applies(e, employer, aliases) for e in extra.values()):
            return self.profile
        return {**self.profile, "extra": {k: e for k, e in extra.items()
                                          if extra_entry_applies(e, employer, aliases)}}

    def resolve_ctx(self, job: dict[str, Any], tenant: Any, adapter: Any,
                    resume_path: str, attempt_id: Any = None) -> ResolveContext:
        aliases = tuple(dict.fromkeys(a for a in (job.get("company_key"), tenant.board)
                                      if a and a != job.get("company")))
        if self._aliases is None:
            self._aliases = tailor_flow.alias_groups(self.cfg)
        groups, ambiguous = self._aliases
        if self._resume_entries is None:
            self._resume_entries = tailor_flow.resume_entries(self.cfg)
        # D-105 (q74_model_sees_sensitive.md §1): the owner's switch counts only when
        # the model runs on this computer; computed once per attempt. A remote backend
        # keeps S values out of prompts, and the log says so (no URL, no values).
        sees_s = bool(self.acfg.model_sees_sensitive) and backends.is_local(self.backend)
        if self.acfg.model_sees_sensitive and not sees_s:
            prefix = f"[attempt {attempt_id}] " if attempt_id is not None else ""
            self.log(f"{prefix}model_sees_sensitive ignored: model backend is not on this computer")
        extra: dict[str, Any] = {}
        if self.policy is FillPolicy.ALWAYS:
            # Q-121 §7.2: under `always` (local model only, K2) the model reads the whole
            # profile; strict contexts are built exactly as before (no new argument).
            extra = {"fill_policy": FillPolicy.ALWAYS, "model_sees_sensitive": True}
        return ResolveContext(
            profile=self.profile_here(str(job.get("company") or ""), aliases),
            employer_name=str(job.get("company") or ""),
            job_title=str(job.get("title") or ""),
            employer_aliases=aliases,
            resume_entries=self._resume_entries,
            other_employers=self.other_employers(job, aliases, groups),
            previously_applied=self.store.applied_to_company(job.get("company_id"), job["job_id"]),
            jd_text=str(job.get("jd_text") or ""), resume_text=self.resume_text(resume_path),
            resume_path=resume_path, ats=adapter.name, alias_groups=groups,
            alias_ambiguous=ambiguous,
            account_email=str(_profile_path(self.profile, "contact.email") or ""),
            **{"model_sees_sensitive": sees_s, **extra})

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

    def check_deadline(self, ctx: AttemptContext, step: str = "") -> None:
        if time.monotonic() > ctx.deadline:
            raise ApplyFailure(ReasonCode.ERROR, f"timed out on {step}" if step else "timed out",
                               step=step)

    def context(self, at: _Attempt, job: dict[str, Any], adapter: Any, tenant: Any,
                resume_path: str) -> AttemptContext:
        """The per-attempt services an adapter gets. D-81: Workday's wizard has its
        own budget; both exclude the IMAP wait (`wait_for_mail` adds it back)."""
        acfg = self.acfg
        return AttemptContext(
            attempt_id=at.id, job=job, tenant=tenant, dry_run=self.dry_run,
            email=str(_profile_path(self.profile, "contact.email") or ""),
            resume_path=resume_path, log=lambda line: self.log(f"[attempt {at.id}] {line}"),
            screenshot=at.shot,
            deadline=time.monotonic() + (acfg.attempt_timeout_workday_s
                                         if adapter.name == "workday"
                                         else acfg.attempt_timeout_s),
            http=self.http,
            applied_on_tenant=self.store.applied_on_tenant(adapter.name, tenant.host))

    # -- one job

    def attempt(self, job_id: str, *, attempt_id: Optional[int] = None) -> AttemptResult:
        """One job. The batch creates the attempt row here; the queue worker passes
        the `queued` row `queue_take` created (its mode already set by `set_mode`)."""
        job = self.store.job_for_apply(job_id)
        taken = attempt_id is not None
        base_mode = (self.mode, self.dry_run)
        # review F14 (c): the composed-text bookkeeping is one attempt's (audit keys repeat
        # across jobs of one ATS), in a batch `apply` run as in the queue (`begin_item`)
        self.compose_files, self.compose_meta, self.compose_assumed = {}, {}, {}
        trial = self.choose_policy()
        if trial:                                      # §12 rev H3: an upper bound, never auto
            self.mode, self.dry_run = "dry_run", True
        # A1-W (§17.7): a trial attempt is marked on its row (`trial = 1`) so Applications and
        # Runs can say "Trial: filled, not sent"; every other attempt keeps the column's 0.
        if attempt_id is None:
            attempt_id = self.store.create_attempt(job_id, job.get("company_id") if job else None,
                                                   self.mode, utcnow())
            if trial:
                self.store.update_attempt(attempt_id, trial=1)
            self.store.commit()
        elif trial:
            self.store.update_attempt(attempt_id, mode=self.mode, trial=1)
            self.store.commit()
        at = _Attempt(self.store, self.log, attempt_id, job_id, self.evidence)
        at.always, at.trial = self.policy is FillPolicy.ALWAYS, trial
        self.log(f"[attempt {attempt_id}] queued job={job_id} mode={self.mode}")
        if at.always:
            nth = "?"
            if trial:
                try:                                      # review F14 (b): a log line never fails the attempt
                    nth = str(self.store.always_trial_used() + 1)
                except Exception:                         # noqa: BLE001 - choose_policy already failed closed
                    pass
            self.log(f"[attempt {attempt_id}] fill policy: always (local model)"
                     + (f"; {TRIAL_NOTE.lower()} (trial {nth} of {self.acfg.always_trial_runs})"
                        if trial else ""))
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
                if taken and at.state is S.QUEUED:        # never started: back to the front (M3)
                    self.unstarted(attempt_id, job_id, job.get("company_id") if job else None)
                elif at.state not in TERMINAL_STATES:
                    if at.clicked:
                        self.unconfirmed(at, "interrupted after submit")
                    else:
                        self.fail(at, ReasonCode.CANCELLED, "interrupted")
            finally:
                raise
        finally:
            self.clear_secrets()                          # K1: the registry lives one attempt
            self.mode, self.dry_run = base_mode           # a trial lowered this attempt only
            if adapter is not None and ctx is not None and hasattr(adapter, "forget"):
                adapter.forget(ctx)
            if at.page is not None and at.state is not S.READY_TO_SUBMIT:
                try:
                    at.result.url = at.result.url or (at.page.url or "").split("?", 1)[0]
                    at.page.close()
                except Exception:
                    pass
            elif at.page is not None and taken:            # a dry run's filled tab stays (§5)
                self.kept_tabs.append(at.page)
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
        if at.always:
            # K1, review F7: the known secrets are registered before ANY prompt of the
            # attempt, the tailor's included (`resume` below). `detect` is pure; when it
            # cannot name the site only the mailbox passwords are registered here (planning
            # then ends the attempt as before).
            try:
                nav0, tenant0 = detect(job)
            except ApplyFailure:
                nav0 = tenant0 = None
            self.forbid_known_secrets(at, nav0, tenant0)
        # tailoring -> planning
        resume_path = self.resume(at, job)
        at.to(S.PLANNING, step="planning")
        adapter, tenant = detect(job)
        at.ats = adapter.name
        self.store.update_attempt(at.id, ats=adapter.name, tenant_host=tenant.host)
        if acfg.fill == "llm" and _is_navigator(adapter):
            return self.body_llm(at, job, adapter, tenant, resume_path)       # D-78 (WP-N6a)
        if not hasattr(adapter, "read_step"):
            # A navigation-only module (Workday) is driven by the LLM page filler
            # only (`apply.fill: llm`); with `rules` it stops here, before Edge
            # opens: nothing is opened, typed or created on the site.
            raise ApplyFailure(ReasonCode.UNSUPPORTED_ATS,
                               f"{adapter.name}: form filling arrives with WP-N6",
                               step="planning")
        ctx = self.context(at, job, adapter, tenant, resume_path)
        rctx = self.resolve_ctx(job, tenant, adapter, resume_path, attempt_id=at.id)
        at.quote_values = tuple(F.quote_s_values(rctx, F.today_sg(self.now())))      # D-202
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
                self.capture(at, job, plan.fields, answers, rctx)
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
            now_answers = {f.key: at.answers[f.key] for f in fields if f.key in at.answers}
            bad = _unanswerable(fields, now_answers)
            if bad:
                self.capture(at, job, fields, now_answers, rctx)
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

    # -- D-78: the LLM filling loop (WP-N6a; llm_fill_design §8 flow part, §11, §13.1)

    def load_rules(self) -> Any:
        if self.rules is None:
            self.rules = R.load_rules(self.cfg.questions_path)
        return self.rules

    def capture(self, at: _Attempt, job: dict[str, Any], fields: Sequence[Any],
                answers: dict[str, Answer], rctx: ResolveContext, *, page: bool = False,
                akeys: Optional[dict[str, str]] = None) -> int:
        """`akeys` (page stops; the reader key -> audit key map `stage` returns): the sightings
        are then stored under the AUDIT key, the one `apply_answers` rows carry, so "Answer for
        next time" finds the captured question (`store.attempt_field_question`, review M1).
        Only the stored field key changes; what was filled or submitted does not."""
        if page and akeys:
            fields = [dataclasses.replace(pf, field=dataclasses.replace(
                pf.field, key=akeys.get(pf.field.key) or pf.field.key)) for pf in fields]
            answers = {akeys.get(k) or k: a for k, a in answers.items()}
        return _capture_questions(self.store, self.cfg, self.backend, at, job, fields, answers,
                                  rctx, self.load_rules(), page=page)

    # -- Q-121 (D-208): the fill policy, the briefing, secrets (llm_first_fill_design §2, §3, §12)

    def choose_policy(self) -> bool:
        """Set `self.policy` for the attempt about to start (K2: `always` only with the local
        model) and say whether the attempt is a first-use trial (§12 rev H3): the policy is
        `always`, this attempt would submit (`auto`), `always_trial_runs` > 0 and fewer trial
        attempts than that reached the review page. A counter that cannot be read counts as
        a trial (the reading that sends less)."""
        self.policy, why = effective_policy(self.acfg, self.backend)
        if why:
            self.log(f"apply: {why}")
        if self.policy is not FillPolicy.ALWAYS or self.dry_run:
            return False
        n = int(getattr(self.acfg, "always_trial_runs", 0) or 0)
        if n <= 0:
            return False
        try:
            return self.store.always_trial_used() < n
        except Exception as exc:                          # noqa: BLE001 - fail towards not sending
            self.log(f"apply: WARNING the trial counter could not be read ({type(exc).__name__}); "
                     "this attempt runs as a dry run")
            return True

    def forbid(self, *secrets: Any) -> None:
        """K1: register secrets with the backend's prompt check the moment they exist (a
        generated account password, a vault password read for sign-in, the IMAP app
        password), so no prompt of this attempt can carry them (`clear_secrets` at its end).
        A value too short to guard ends the attempt `error` "prompt check" under `always`;
        under `strict` it is logged and the attempt goes on as before."""
        fn = getattr(self.backend, "forbid", None)
        vals = [s.reveal() if hasattr(s, "reveal") else s for s in secrets if s is not None]
        vals = [v for v in vals if isinstance(v, str) and v]
        if not callable(fn) or not vals:
            return
        try:
            fn(vals)
        except (TypeError, ValueError):
            if self.policy is FillPolicy.ALWAYS:
                raise ApplyFailure(ReasonCode.ERROR, PROMPT_CHECK) from None
            self.log("apply: a secret is too short for the prompt check (not registered)")

    def forbid_known_secrets(self, at: _Attempt, nav: Any, tenant: Any) -> None:
        """K1 under `always`, before the first prompt (the warm-up sends the briefing): the
        vault passwords of this site's known accounts and the IMAP app passwords of the
        profile's mailboxes are registered now, not only when sign-in or the mail reads them,
        so no prompt of the attempt can carry one even if it was pasted into the profile.
        A vault that cannot be read is skipped (sign-in and the mail read it again later)."""
        secrets: list[Any] = []
        try:
            service = vault.service_for(nav.name, tenant.host)
            rows = self.store.accounts_for_tenant(nav.name, tenant.host) or {}
            mine = [str(_profile_path(self.profile, k) or "").strip()
                    for k in ("contact.email", "contact.backup_email")]
            for email in dict.fromkeys([*(m for m in mine if m and m.lower() in rows), *rows]):
                secrets.append(vault.get(service, email))
        except Exception:                                 # noqa: BLE001 - read again at sign-in
            pass
        try:
            settings = mail.effective_settings(self.cfg, self.store.get_setting)
            for key in ("contact.email", "contact.backup_email"):
                address = str(_profile_path(self.profile, key) or "").strip()
                box = mail.mailbox_for(address, self.profile, settings) if address else None
                if box is not None:
                    secrets.append(mail.mailbox_password(box))
        except Exception:                                 # noqa: BLE001 - read again by the mail step
            pass
        self.forbid(*secrets)
        n = sum(1 for s in secrets if s is not None)
        if n:
            self.log(f"[attempt {at.id}] prompt check: {n} secret(s) registered")

    def clear_secrets(self) -> None:
        """K1: forget the registered secrets (the end of every attempt)."""
        fn = getattr(self.backend, "clear_forbidden", None)
        if callable(fn):
            try:
                fn()
            except Exception:                             # noqa: BLE001 - nothing to lose
                pass

    def always_services(self, at: _Attempt, services: "_FillServices",
                        rctx: ResolveContext) -> list[dict[str, str]]:
        """What pagefill's `always` branch reads from FillServices (WP-C1): the briefing,
        built once per attempt from the profile and this ResolveContext (§3.1, §7.1;
        deterministic), the attempt's F2-F6 count (§4.6), the backend behind the K1 refusal
        watch, `max_entries` as a mapping. Returns the warm-up messages (§3.5): the system
        text and the user prefix (BRIEFING + JOB) every call of the attempt starts with. A
        profile key named like a secret ends the attempt `error` "prompt check" (K1)."""
        today = services.today()
        try:
            brief = BR.build(rctx.profile, rctx, today=today,
                             max_tokens=int(self.acfg.llm_fill.briefing_max_tokens))
        except BR.BriefingRefused:
            self.log(f"[attempt {at.id}] briefing refused: a profile key looks like a secret")
            raise ApplyFailure(ReasonCode.ERROR, PROMPT_CHECK, step="planning") from None
        services.briefing = brief
        services.attempt_fallbacks = 0
        services.page_fallbacks, services.last_page_step = {}, ""     # review F13: per page
        services.cfg["max_entries"] = dict(services.cfg.get("max_entries") or ())
        self.log(f"[attempt {at.id}] briefing ready ({brief.tokens} tokens)")
        return [{"role": "system", "content": AL.SYSTEM_ALWAYS},
                {"role": "user", "content": AL.user_prefix(brief, BR.job_block(rctx, today=today))}]

    def warm_up(self, at: _Attempt, messages: Optional[list[dict[str, str]]] = None) -> None:
        """Load the model before Edge opens (D-81: a cold load costs ~33 s). A model that
        is not there ends the attempt `model_unavailable` with nothing opened (§11). Under
        `always` the warm-up sends the shared prefix (`messages`, §3.5) so later calls reuse
        it; a prefix the prompt check refuses ends the attempt `error` "prompt check" (K1)."""
        t0 = time.monotonic()
        try:
            if messages:
                backends.warm(self.backend, self.acfg.llm_fill.keep_alive or None, messages=messages)
            else:
                backends.warm(self.backend, self.acfg.llm_fill.keep_alive or None)
        except backends.PromptRefused:
            self.log(f"[attempt {at.id}] model warm-up refused by the prompt check")
            raise ApplyFailure(ReasonCode.ERROR, PROMPT_CHECK, step="planning") from None
        except backends.BackendError as exc:
            self.log(f"[attempt {at.id}] model warm-up failed ({type(exc).__name__})")
            raise ApplyFailure(ReasonCode.MODEL_UNAVAILABLE,
                               (str(exc).splitlines() or ["not running"])[0][:120] or "not running",
                               step="planning") from None
        self.log(f"[attempt {at.id}] model ready ({time.monotonic() - t0:.0f} s)")

    def choose_entry(self, page: Any, ctx: AttemptContext, nav: Any, at: _Attempt) -> None:
        """The site's own import (Workday "Autofill with Resume", MyGreenhouse), then the
        origin later pages carry in `ctx.prefill` (D-78; the navigator also fills
        `ctx.pre_import`). Anything but a page signal falls back to "fill everything"."""
        try:
            origin = nav.choose_entry(page, ctx) or ""
        except ApplyFailure:
            raise
        except Exception as exc:                          # noqa: BLE001 - the generic fill still works
            self.log(f"[attempt {at.id}] entry choice skipped: {self.log.exc(exc)}")
            origin = ""
        ctx.prefill = origin or ctx.prefill or ""
        if ctx.prefill:
            self.log(f"[attempt {at.id}] prefill: {ctx.prefill}")

    def body_llm(self, at: _Attempt, job: dict[str, Any], nav: Any, tenant: Any, resume_path: str):
        """The D-78 attempt: warm-up -> open -> the site's import -> account wall -> one
        `fill_page` per step -> review. Same states, guards, evidence and submit rules as
        the pre-D-78 body; only the middle differs."""
        acfg = self.acfg
        ctx = self.context(at, job, nav, tenant, resume_path)
        rctx = self.resolve_ctx(job, tenant, nav, resume_path, attempt_id=at.id)
        at.quote_values = tuple(F.quote_s_values(rctx, F.today_sg(self.now())))      # D-202
        self.store.update_attempt(at.id, plan_source="page")
        nav.precheck(ctx)                                 # POSTING_CLOSED before the model or Edge
        self.check_deadline(ctx)
        services = _fill_services(self, at, ctx, now=self.now)
        warm_msgs = None
        if at.always:                                     # K1: secrets registered in `body` (F7)
            warm_msgs = self.always_services(at, services, rctx)
        t_warm = time.monotonic()
        self.warm_up(at, warm_msgs)
        ctx.deadline += time.monotonic() - t_warm         # the model load is not the attempt's time (N6a F3)

        # opening
        at.to(S.OPENING, step="opening")
        page = at.page = self.browser().new_page()
        nav.open(page, ctx)
        at.shot(page, "open")
        self.check_page(page, at)
        self.choose_entry(page, ctx, nav, at)
        self.check_page(page, at)
        if nav.account_wall(page):                        # accounts, sign-in, sign-up, email check (WP-N4)
            self.reopened = False
            rctx = self.account(page, ctx, nav, at, job, rctx)
            self.check_page(page, at)
            if self.reopened:                             # the email check reopened the posting (F7)
                self.choose_entry(page, ctx, nav, at)
                self.check_page(page, at)
        at.to(S.FILLING, step="application")

        # filling, one step at a time (loop guard: the same step with the same fields twice)
        seen: set = set()
        try:
            for _ in range(max(1, acfg.max_wizard_steps)):
                self.check_deadline(ctx, at.step)
                self.check_page(page, at)
                outcome = fill_page(page, nav, ctx, rctx, services)
                if outcome.compose_needed:                # Q-45: write the texts, then once more (section 19.3)
                    outcome = self.compose_step(at, page, nav, ctx, rctx, services, job, outcome)
                step = self.page_result(at, page, outcome, rctx, services, job)
                if not outcome.fields and step != "review":
                    raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"no fields on {step}", step=step)
                sig = (step, _signature(outcome))
                if sig in seen:
                    raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"{step} shown again", step=step)
                seen.add(sig)
                at.shot(page, step)
                self.check_page(page, at)
                res = nav.next_step(page, ctx)
                if res.errors:                            # one corrective pass (llm_fill_design §8)
                    self.log(f"[attempt {at.id}] errors after Next: {', '.join(res.errors[:3])}")
                    if at.always:
                        self.refill_base(services)        # review F13: this page is counted once
                    again = fill_page(page, nav, ctx, rctx, services)
                    self.page_result(at, page, again, rctx, services, job)
                    res = nav.next_step(page, ctx)
                    if res.errors:
                        raise ApplyFailure(ReasonCode.VALIDATION_ERROR,
                                           ", ".join(e[:80] for e in res.errors[:3]), step=step)
                at.record(step, list(at.fields.values()))
                if res.is_review:
                    break
                at.to(S.FILLING, step=B.slug(res.step) or step)
            else:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"{nav.name}: too many steps")

            # review: the pre-Submit scan and the review text check (llm_fill_design §8, H7), then,
            # unchanged, a dry run stops here and auto mode submits (NF-06). Auto mode reaches
            # `submit` only through a passing scan (replaces the N6a review-F1 stop). Under
            # `always` a required field the scan finds empty gets one more A8 round first (K8).
            at.shot(page, "review")
            at.result.url = (page.url or "").split("?", 1)[0]
            self.check_page(page, at)                      # a bot check after the last Next ends as one (review F2)
            refill = None
            if at.always:
                def refill() -> None:
                    self.refill_base(services)            # review F13: this page is counted once
                    again = fill_page(page, nav, ctx, rctx, services)
                    self.page_result(at, page, again, rctx, services, job)
                    at.record(at.step, list(at.fields.values()))
            self.pre_submit_scan(page, nav, ctx, at, refill=refill)
        except AL.AlwaysStop as stop:                      # §9: only the `always` path raises it
            self.always_stop(at, page, nav, ctx, job, rctx, stop)
        if self.dry_run:
            at.to(S.READY_TO_SUBMIT, end_url=at.result.url)
            if at.trial:
                self.trial_used(at)
            return nav, ctx
        self.submit(page, ctx, nav, at, job)
        return nav, ctx

    def trial_used(self, at: _Attempt) -> None:
        """§12 rev H3: a trial attempt reached the review page: count it, say so."""
        try:
            n = self.store.count_always_trial()
        except Exception as exc:                          # noqa: BLE001 - the attempt is done
            self.log(f"[attempt {at.id}] trial counter not updated ({type(exc).__name__})")
            return
        self.log(f"[attempt {at.id}] {TRIAL_NOTE} (trial {n} of {self.acfg.always_trial_runs}); "
                 f"{at.assumed_count()} answer(s) assumed")

    def always_stop(self, at: _Attempt, page: Any, nav: Any, ctx: AttemptContext,
                    job: dict[str, Any], rctx: ResolveContext, stop: Any) -> None:
        """A per-role or content stop under `always` (llm_first_fill_design §9; raised by
        `always.fill_page_always` through `fill_page`, before anything on that page is
        typed, or from a reveal / Add / A8 round after typing). `owner_fact_missing`: the
        field is captured for the owner (`profile_gap` with its profile path, else
        `no_rule`; sensitive), the attempt waits ("Needs your answers") and the queue goes on
        (`pause_for`). `document_missing`: per role, nothing captured. The content failure
        (`unanswerable_required`, the detail starting with a marker): `fill_failed`, not
        returned. Never returns.

        Review F4: the stored detail says WHAT stopped it: the step, and for an owner-fact or
        document stop the form's own label (employer text, never a value): "date of birth
        (“Date of Birth” on my_information)". `owner_fact_of` reads the fact back for the
        queue's same-fact rule. The stopped page has no audit rows: `AlwaysStop` carries no
        decided answers (always.py), so there is nothing to stage with applied=False.

        `consent_refused` (A1 §17.6: a consent the form requires and the profile refuses)
        ends exactly like `owner_fact_missing`: the field is captured (target
        `consents.<key>`, the stop's `target_path`), the role waits for the owner and is not
        returned, the queue goes on. Its detail is the contract's plain words for that key
        (`consent_refused_detail`), so the same consent reads the same on every role and the
        same-detail streak rule in `pause_for` can name it."""
        reason, detail = stop.reason, " ".join(str(stop.detail or "").split())
        step = B.slug(getattr(stop, "step", "") or "") or at.step
        label = " ".join(str(getattr(stop, "label", "") or "").split())[:80]
        if reason is ReasonCode.OWNER_FACT_MISSING:
            self.capture_owner_fact(at, page, nav, ctx, job, rctx, stop)
            detail = owner_fact_detail(detail or label or "a fact", label, step)
        elif reason is ReasonCode.CONSENT_REFUSED:
            self.capture_owner_fact(at, page, nav, ctx, job, rctx, stop)
            detail = consent_refused_detail(getattr(stop, "target_path", ""), detail)
        elif reason is ReasonCode.DOCUMENT_MISSING:
            detail = f"{detail or label or 'document'} (on {step})"
        elif reason is ReasonCode.UNANSWERABLE_REQUIRED:
            if not any(detail.lower().startswith(m) for m in CONTENT_FAILURE_DETAILS):
                detail = content_failure_detail(FILL_WOULD_BE_GUESSES, detail)  # never a guessed field label
            title = " ".join(str(getattr(stop, "step", "") or "").split())
            if step not in detail and (not title or title not in detail):
                detail = f"{detail} on {step}"
        self.log(f"[attempt {at.id}] always: {reason.value} on {step}")
        raise ApplyFailure(reason, detail[:200], step=step)

    def capture_owner_fact(self, at: _Attempt, page: Any, nav: Any, ctx: AttemptContext,
                           job: dict[str, Any], rctx: ResolveContext, stop: Any) -> None:
        """§4.6: capture the owner-only fact (date of birth, a grade, ...) as a question;
        A1 §17.6: also the consent a `consent_refused` stop names (its `target_path` is
        `consents.<key>`, which the Profile form edits). The PageField is read again by its
        key (the reader's marks are stable) for its type and options; without it the stop's
        label stands. Never changes the outcome."""
        pf = None
        try:
            scope = nav.scope(page, ctx)
            pf = next((p for p in P.read_page(page, scope=scope)
                       if p.field.key == stop.field_key), None)
        except Exception:                                 # noqa: BLE001 - the label is enough
            pf = None
        try:
            q = Q.capture_owner_fact(stop.detail, rctx, field=pf, field_key=stop.field_key,
                                     label=stop.label, target_path=stop.target_path, step=at.step)
        except Exception as exc:                          # noqa: BLE001 - capture never changes the outcome
            self.log(f"[attempt {at.id}] question capture failed: {type(exc).__name__}")
            return
        _capture_questions(self.store, self.cfg, self.backend, at, job, [], {}, rctx,
                           self.load_rules(), found=[q])

    def pre_submit_scan(self, page: Any, nav: Any, ctx: AttemptContext, at: _Attempt, *,
                        refill: Optional[Callable[[], None]] = None) -> None:
        """Before Submit (llm_fill_design §8, review H7). (1) `page.scan_required` over the whole
        form (Greenhouse: the one page; Workday: the review page shows no inputs, so the last
        step's scan before Next stands): a required control empty or in error ->
        `validation_error`, nothing sent. (2) The review text check: when this attempt uploaded
        the resume, its file name must be on the page ("review: resume not shown"). (3) Required
        text answers the page does not show: a log line only. Fail closed: a scan that cannot
        run stops an auto-mode attempt (a dry run, which sends nothing, says so and goes on).
        Raises ApplyFailure; never clicks anything; no field value is logged.

        Q-121 K8 (`always` only): with `refill`, a scan hit first gets one more A8 round on
        the page (`refill`: fill_page + page_result), then the scan runs again and stays the
        final gate: still a hit -> `validation_error`, nothing sent."""
        try:
            scope = nav.scope(page, ctx)
            hits = P.scan_required(page, scope)
        except Exception as exc:                          # noqa: BLE001 - fail closed (NF-06)
            self.log(f"[attempt {at.id}] pre-Submit scan could not run ({type(exc).__name__})")
            if not self.dry_run:
                raise ApplyFailure(ReasonCode.VALIDATION_ERROR, REVIEW_SCAN_FAILED,
                                   step="review") from None
            return
        if hits and refill is not None:
            self.log(f"[attempt {at.id}] pre-Submit scan: {len(hits)} required field(s) empty; "
                     "one more round (A8)")
            refill()
            try:
                scope = nav.scope(page, ctx)
                hits = P.scan_required(page, scope)
            except Exception as exc:                      # noqa: BLE001 - fail closed (NF-06)
                self.log(f"[attempt {at.id}] pre-Submit scan could not run "
                         f"({type(exc).__name__})")
                if not self.dry_run:
                    raise ApplyFailure(ReasonCode.VALIDATION_ERROR, REVIEW_SCAN_FAILED,
                                       step="review") from None
                return
        if hits:
            labels = self._labels_of(page, scope, hits)
            raise ApplyFailure(ReasonCode.VALIDATION_ERROR,
                               ("review: " + ", ".join(x[:80] for x in labels[:3]))[:200],
                               step="review")
        name = Path(ctx.resume_path).name if ctx.resume_path else ""
        text = _squash(P.page_text(page, scope))
        if name and name in ctx.uploaded and _squash(name) not in text:
            raise ApplyFailure(ReasonCode.VALIDATION_ERROR, REVIEW_RESUME_MISSING, step="review")
        unseen = 0
        for key, a in at.answers.items():
            f = at.fields.get(key)
            if (f is None or not f.required or a.status is not AnswerStatus.FILLED
                    or f.type not in (FieldType.TEXT, FieldType.TEXTAREA)
                    or not isinstance(a.value, str) or len(a.value.strip()) < 3):
                continue
            if _squash(a.value)[:60] not in text:
                unseen += 1
        if unseen:
            self.log(f"[attempt {at.id}] review: {unseen} required text value(s) not shown on "
                     "the review page (note only)")
        self.log(f"[attempt {at.id}] pre-Submit scan passed")

    def _labels_of(self, page: Any, scope: str, keys: Sequence[str]) -> list[str]:
        """The labels of scan hits (the reader's marks are stable, so a second read maps
        keys to labels); the keys themselves when that read fails."""
        try:
            by_key = {pf.field.key: pf.field.label for pf in P.read_page(page, scope=scope, options=False)}
        except Exception:                                 # noqa: BLE001 - labels are a courtesy
            by_key = {}
        return [by_key.get(k) or k for k in keys]

    def page_result(self, at: _Attempt, page: Any, outcome: PageOutcome, rctx: ResolveContext,
                    services: _FillServices, job: dict[str, Any]) -> str:
        """What one `fill_page` outcome means (llm_fill_design §8, §11): a transport failure
        or the deadline ends the attempt (never captured), a required unknown is captured
        and ends it `unanswerable_required`, a required field the page would not take is a
        `validation_error`. Returns the step id. The audit rows are staged first, so every
        ending keeps them (R3 F10: a stop's answers are marked not applied)."""
        step = B.slug(outcome.step) if outcome.step else "form"
        if step != at.step:
            at.to(S.FILLING, step=step)
        self.log(f"[attempt {at.id}] page {step}: {len(outcome.fields)} fields, "
                 f"{outcome.model_calls} model calls, {outcome.model_seconds:.0f} s")
        by_key = {pf.field.key: pf for pf in outcome.fields}
        if outcome.transport_failed:
            self.stage(at, page, outcome, step, applied=False)
            # K1 (Q-121; both policies since review D2): a prompt that held a registered
            # secret was refused before it was sent; pagefill reports it as transport, the
            # flow ends `error` "prompt check" (never `model_unavailable`, never retried).
            if getattr(services.backend, "refused", False) is True:
                raise ApplyFailure(ReasonCode.ERROR, PROMPT_CHECK, step=step)
            # An expired deadline is reported by pagefill as transport "timed out": it is
            # the attempt's time that ran out, not the model (N1; llm_fill_design §11).
            if services.deadline_left() <= 0:
                raise ApplyFailure(ReasonCode.ERROR, f"timed out on {step}", step=step)
            raise ApplyFailure(ReasonCode.MODEL_UNAVAILABLE,
                               f"{_transport_cause(outcome, services.backend)} on {step}", step=step)
        if outcome.compose_needed:
            # the texts were written and the page still asks for them (section 19.3 step 4): never again
            self.stage(at, page, outcome, step, applied=False)
            raise ApplyFailure(ReasonCode.ERROR, f"compose loop on {step}", step=step)
        if outcome.unknown_required:
            akeys = self.stage(at, page, outcome, step, applied=False)
            self.capture(at, job, outcome.fields, outcome.answers, rctx, page=True, akeys=akeys)
            first = by_key.get(outcome.unknown_required[0])
            label = first.field.label if first else outcome.unknown_required[0]
            raise ApplyFailure(ReasonCode.UNANSWERABLE_REQUIRED, label[:120], step=step)
        akeys = self.stage(at, page, outcome, step, applied=True)
        if at.always:
            self.always_page_done(at, job, outcome, akeys, rctx, services)
        # R3 F14 (D-173, D-174): a failed E5 Add is the section's problem, not a field's: say so,
        # and stop on it even when every field in the section is optional (fewer entries than
        # the profile has must never be submitted). Any other optional fill_failed row is not a stop.
        failed = [k for k in outcome.fill_failed if k in by_key]
        added = next((s for s in (_entry_problem(outcome.answers.get(k)) for k in failed) if s), "")
        if added and at.always:
            # Q-121 §4.5 (rev L7): under `always` a failed Add is an attempt note, not a stop.
            self.log(f"[attempt {at.id}] E5: {added[:120]} (a note under fill policy always)")
            added = ""
        req = [k for k in failed if by_key[k].field.required]
        bad = [by_key[k].field.label for k in req if not _entry_problem(outcome.answers.get(k))]
        if added or bad:
            detail = "; ".join(([added] if added else []) + ([", ".join(b[:80] for b in bad[:3])] if bad else []))
            raise ApplyFailure(ReasonCode.VALIDATION_ERROR, detail[:200], step=step)
        return step

    def always_page_done(self, at: _Attempt, job: dict[str, Any], outcome: PageOutcome,
                         akeys: dict[str, str], rctx: ResolveContext,
                         services: "_FillServices") -> None:
        """After a page under `always` was staged: add its F2-F6 answers to the attempt's
        count (§4.6 `last_resort_max_attempt`; F0/F1 are not assumed) and capture its assumed
        answers as "Answered for you" questions (§6.3), keyed by the audit key so the card
        finds the sent value in `apply_answers`. Capture never changes an outcome."""
        guesses = sum(1 for k in outcome.fallback
                      if getattr(outcome.answers.get(k), "assumed", False))
        # review F13: per page, once; the same page filled again (Next errors, the pre-Submit
        # round) replaces its count instead of adding to it
        counts = getattr(services, "page_fallbacks", None)
        if not isinstance(counts, dict):
            counts = services.page_fallbacks = {}
        counts[at.step] = guesses
        services.last_page_step = at.step
        services.attempt_fallbacks = sum(counts.values())
        if not outcome.assumed:
            return
        pfs, answers = [], {}
        for pf in outcome.fields:
            key = akeys.get(pf.field.key) or pf.field.key
            if key in at.answers:
                pfs.append(dataclasses.replace(pf, field=dataclasses.replace(pf.field, key=key)))
                answers[key] = at.answers[key]
        try:
            found = Q.capture_assumptions(pfs, answers, rctx, self.load_rules())
        except Exception as exc:                          # noqa: BLE001 - capture never changes the outcome
            self.log(f"[attempt {at.id}] assumption capture failed: {type(exc).__name__}")
            return
        if found:
            _capture_questions(self.store, self.cfg, self.backend, at, job, [], {}, rctx,
                               self.load_rules(), found=found)

    def refill_base(self, services: "_FillServices") -> None:
        """Before the same page is filled again under `always` (review F13): the attempt's
        F2-F6 count without that page's own, so `last_resort_max_attempt` sees it once."""
        counts = getattr(services, "page_fallbacks", None) or {}
        last = getattr(services, "last_page_step", "")
        services.attempt_fallbacks = sum(n for s, n in counts.items() if s != last)

    def stage(self, at: _Attempt, page: Any, outcome: PageOutcome, step: str, *,
              applied: bool) -> dict[str, str]:
        """Put a page's fields and answers into the attempt under their audit keys
        (`apply.page.audit_keys`). `applied=False` (a stop or a transport failure) marks the
        rows that were only decided: nothing is on the page for them (R3 F10). Returns the
        reader key -> audit key map ({} when the page could not give one)."""
        try:
            akeys = P.audit_keys(page, outcome.fields, step) if outcome.fields else {}
        except Exception:                                 # noqa: BLE001 - the reader keys still work
            akeys = {}
        for pf in outcome.fields:
            a = outcome.answers.get(pf.field.key)
            if a is None:
                continue
            key = akeys.get(pf.field.key) or pf.field.key
            f = dataclasses.replace(pf.field, key=key)
            a = dataclasses.replace(
                a, field_key=key, shown=a.shown if a.shown is not None else (pf.shown or None),
                origin=a.origin or pf.origin.value, entry=a.entry or pf.group)
            if not applied and a.status is AnswerStatus.FILLED and TYPED_BEFORE_STOP_NOTE not in (a.note or ""):
                a = dataclasses.replace(a, status=AnswerStatus.SKIPPED,
                                        note=_join(a.note, NOT_APPLIED_NOTE))
            meta = self.compose_meta.get(key)
            if meta and a.source == AnswerSource.COMPOSED.value:
                a = dataclasses.replace(a, model=meta[0], prompt_hash=meta[1])   # audit (section 19.5)
            path = self.compose_files.get(key)
            if path and f.type is FieldType.FILE and a.source == AnswerSource.COMPOSED.value:
                a = dataclasses.replace(a, note=_composed_note(path))   # name and SHA-256 of the real file
            why = self.compose_assumed.get(key)
            if why is not None and a.source == AnswerSource.COMPOSED.value:
                # Q-121 §4.8: a pruned or neutral composed text is assumed; the reason is its evidence
                a = dataclasses.replace(a, assumed=True, evidence=a.evidence or why)
            at.fields[key] = f
            at.answers[key] = a
        return akeys

    # -- Q-45: composed texts (llm_fill_design section 19.3)

    def compose_step(self, at: _Attempt, page: Any, nav: Any, ctx: AttemptContext,
                     rctx: ResolveContext, services: _FillServices, job: dict[str, Any],
                     outcome: PageOutcome) -> PageOutcome:
        """The page stopped at step 7b with nothing changed: write the text of each compose
        target, in page order (the owner's saved answer when there is one, else the tailor's
        checked composition), put it into `ctx.composed` (a FILE target also gets a letter
        file in `ctx.composed_files`), then run `fill_page` again on the same step, once. A
        draft that failed its checks or a missing master is captured (`compose_needed: failed
        check` / `no master`) and ends the attempt `unanswerable_required`; a transport failure
        ends it `model_unavailable` with nothing captured. No text is ever logged."""
        step = B.slug(outcome.step) if outcome.step else "form"
        by_key = {pf.field.key: pf for pf in outcome.fields}
        try:
            akeys = P.audit_keys(page, outcome.fields, step) if outcome.fields else {}
        except Exception:                                 # noqa: BLE001 - the reader keys still work
            akeys = {}
        for key in outcome.compose_needed:
            pf = by_key.get(key)
            if pf is None:
                continue
            if services.deadline_left() <= 0:
                self.stage(at, page, outcome, step, applied=False)
                raise ApplyFailure(ReasonCode.ERROR, f"timed out on {step}", step=step)
            f, akey = pf.field, akeys.get(key) or key
            text, meta = Q.owner_compose_text(f, rctx), ("", "")
            if not text:
                # Q-121 §4.8: under `always` a REQUIRED target is composed even with the
                # cover-letter toggle off (the tailor gets the policy; strict calls it as before).
                forced = at.always and f.required
                if not self.acfg.compose.enabled and not forced:
                    self.compose_stop(at, page, job, rctx, outcome, step, key, Q.COMPOSE_OFF)
                kw: dict[str, Any] = {}
                if at.always:
                    kw = {"policy": FillPolicy.ALWAYS.value,
                          "enabled": bool(self.acfg.compose.enabled), "required": bool(f.required)}
                res = tailor_flow.compose(self.cfg, self.compose_request(f, rctx),
                                          backend=self.backend, redact=llm_fill.redact,
                                          timeout=max(1.0, services.deadline_left()),   # D-184
                                          **kw)
                if not res.ok:
                    err = res.error or ""
                    if err.startswith("transport") and "PromptRefused" in err:
                        self.stage(at, page, outcome, step, applied=False)       # K1, §9
                        raise ApplyFailure(ReasonCode.ERROR, PROMPT_CHECK, step=step)
                    if err.startswith("transport"):
                        self.stage(at, page, outcome, step, applied=False)
                        raise ApplyFailure(ReasonCode.MODEL_UNAVAILABLE,
                                           f"{res.error[:60]} on {step}", step=step)
                    if not at.always:
                        self.compose_stop(at, page, job, rctx, outcome, step, key,
                                          Q.COMPOSE_NO_MASTER if res.error == "no master"
                                          else Q.COMPOSE_FAILED)
                text, meta = (res.text if res.ok else ""), (res.model, res.prompt_hash)
                if at.always:
                    why = "; ".join(x for x in (
                        "pruned after its checks" if getattr(res, "pruned", False) else "",
                        "a neutral text" if getattr(res, "neutral", False) else "",
                        str(getattr(res, "reason", "") or "")) if x)
                    if not (text or "").strip():          # §4.8: a required text is never left empty
                        text, why = self.neutral_text(rctx), why or "a neutral text"
                    if getattr(res, "assumed", False) or why:
                        self.compose_assumed[akey] = f"composed: {why or 'assumed'}"[:120]
                    flags = len(getattr(res, "flags", ()) or ())
                    if flags:
                        self.log(f"[attempt {at.id}] composed text: {flags} check flag(s)")
            ctx.composed[akey] = text
            if f.type is FieldType.FILE:
                ctx.composed_files[akey] = self.compose_files[akey] = self.write_letter(at, ctx, text)
            self.compose_meta[akey] = meta
            self.log(f"[attempt {at.id}] composed 1 text ({len(text.split())} words)")
        return fill_page(page, nav, ctx, rctx, services)

    def neutral_text(self, rctx: ResolveContext) -> str:
        """§4.8's code-built text (the tailor's `neutral_text` wording; apply_flow may not
        import tailor/compose): used only when a required composed text came back empty."""
        return NEUTRAL_TEXT.format(title=rctx.job_title or "advertised",
                                   employer=rctx.employer_name or "your company")

    def compose_request(self, f: FormField, rctx: ResolveContext) -> ComposeRequest:
        """The tailor's request (section 19.3 step 1): employer text and limits, and the S
        values that must be redacted from the prompt and absent from the text."""
        cc, kind = self.acfg.compose, Q.compose_kind(f)
        letter = kind == "letter"
        return ComposeRequest(
            kind=kind, question=" ".join(x for x in (f.label, f.description) if x).strip(),
            employer=rctx.employer_name, employer_aliases=tuple(rctx.employer_aliases),
            job_title=rctx.job_title, jd_text=rctx.jd_text or "",
            max_words=int(cc.letter_max_words if letter else cc.answer_max_words),
            max_chars=int(f.max_length or (4000 if letter else 1500)),
            s_values=tuple(dict.fromkeys([*F.s_values(rctx.profile, rctx.account_email),
                                          *F.enum_s_values(rctx.profile)])),
            other_employers=tuple(" ".join(t) for t in F.other_employers(rctx, composed=True)))

    def write_letter(self, at: _Attempt, ctx: AttemptContext, text: str) -> str:
        """`data/apply/<attempt id>/cover_letter.<docx|txt>` (`cover_letter-2.docx` for a
        second one): plain paragraphs in the tailor's font, no name, no contact block."""
        fmt = self.acfg.compose.file_format if self.acfg.compose.file_format in ("docx", "txt") else "docx"
        n = len(ctx.composed_files) + 1
        name = "cover_letter" if n == 1 else f"cover_letter-{n}"
        return tailor_flow.write_letter(text, at.dir / f"{name}.{fmt}", fmt)

    def compose_stop(self, at: _Attempt, page: Any, job: dict[str, Any], rctx: ResolveContext,
                     outcome: PageOutcome, step: str, key: str, why: str) -> None:
        """Capture the compose target `key` (reason `compose_needed`, note `compose_needed:
        <why>`) and end the attempt `unanswerable_required` (section 19.3 step 3). Never returns."""
        old = outcome.answers.get(key)
        note = f"{Q.COMPOSE_NOTE}: {why}"
        ans = dataclasses.replace(old, value=None, status=AnswerStatus.UNKNOWN, note=note) \
            if old is not None else Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="",
                                           confidence=0.0, status=AnswerStatus.UNKNOWN, note=note)
        stopped = dataclasses.replace(outcome, answers={**outcome.answers, key: ans},
                                      compose_needed=(), unknown_required=(key,))
        akeys = self.stage(at, page, stopped, step, applied=False)
        self.capture(at, job, stopped.fields, {key: ans}, rctx, page=True, akeys=akeys)
        self.log(f"[attempt {at.id}] compose_needed: {why} on {step}")
        pf = next((p for p in stopped.fields if p.field.key == key), None)
        raise ApplyFailure(ReasonCode.UNANSWERABLE_REQUIRED,
                           (pf.field.label if pf else key)[:120], step=step)

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
        swapped = dataclasses.replace(rctx, account_email=ctx.email)
        at.quote_values = tuple(F.quote_s_values(swapped, F.today_sg(self.now())))   # D-202 (F3)
        return swapped

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
        self.forbid(secret)                               # K1: read from the vault -> no prompt holds it
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
            self.forbid(secret)                           # K1: registered the moment it exists
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
            self.reopened = True
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
        self.forbid_mail_password(ctx.email, settings)
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

    def forbid_mail_password(self, address: str, settings: Any) -> None:
        """K1: the IMAP app password is registered when the mail loads (before the watcher
        holds it). A mailbox that is not set up is `watcher_for`'s to report. `always` only:
        under `strict` the vault is read exactly as before (once, by `watcher_for`)."""
        if self.policy is not FillPolicy.ALWAYS:
            return
        try:
            box = mail.mailbox_for(address, self.profile, settings)
            pw = mail.mailbox_password(box) if box else None
        except Exception:                                 # noqa: BLE001 - watcher_for reports it
            return
        self.forbid(pw)

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

    def purge_fill_cache(self) -> None:
        """Drop decision-cache rows older than 30 days (llm_fill_design §13.3), by the
        run's clock (TR-5). Housekeeping: it never stops a run."""
        try:
            n = self.store.fill_cache_purge(shift(_stamp(self.now()), days=-FILL_CACHE_DAYS))
            if n:
                self.log(f"apply: purged {n} old cached decision(s)")
        except Exception as exc:                          # noqa: BLE001
            self.log(f"apply: decision cache purge skipped ({type(exc).__name__})")

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
            self.purge_fill_cache()
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

    # -- the auto-apply queue (apply_queue_design §3.2, §4, §5; D-205, ADR-0010)

    def set_mode(self, mode: str) -> None:
        """The mode of the item about to run. Anything but exactly "auto" is a dry run
        (I5): `_Run.dry_run` is what decides the click."""
        self.mode = "auto" if mode == "auto" else "dry_run"
        self.dry_run = self.mode != "auto"

    def begin_item(self) -> None:
        """Fresh per-item state (§3.2, review L1/P15): the profile is read again, so an
        answer the owner added mid-queue is seen by the next role; the caches the batch
        keeps for a whole run are dropped. `seen` is reset: the queue's UNIQUE(job_id)
        and live-attempt checks (I2) replace the batch-duplicate guard. The redaction
        list keeps the earlier values too (a value removed from the profile must still
        never reach the log)."""
        self.profile, self.profile_error = {}, ""
        try:
            self.profile = applicant.load(self.cfg.applicant_path)
        except applicant.ApplicantError as exc:
            self.profile_error = str(exc)
        self.log.values = list(dict.fromkeys(
            [*self.log.values, *applicant.redaction_values(self.profile)]))
        self.rules = None
        self._resume_text = None
        self._resume_entries = None
        self._aliases = None
        self.reopened = False
        self.compose_files = {}
        self.compose_meta = {}
        self.compose_assumed = {}
        self.last_cap = ""
        self.browser_failed = ""
        self.seen = set()

    def unstarted(self, attempt_id: int, job_id: str, company_id: Optional[int]) -> None:
        """An item interrupted while its attempt row is still `queued` (nothing was done
        on the site): the row ends failed(cancelled) and the role goes back to the front
        with the mode it was queued with (review M3). Idempotent; never raises."""
        try:
            row = self.store.attempt(attempt_id)
            if row is not None and row["state"] == S.QUEUED.value:
                self.store.set_attempt_state(attempt_id, S.FAILED.value,
                                             reason=ReasonCode.CANCELLED.value,
                                             detail="interrupted before start")
                self.store.commit()
            item = self.item or {}
            self.store.queue_return(job_id, company_id, item.get("item_mode") or "dry_run",
                                    "returned: interrupted before start", utcnow())
            self.log(f"[attempt {attempt_id}] interrupted before start; back at the front")
        except Exception as exc:                          # noqa: BLE001 - the interrupt goes on
            self.log(f"[attempt {attempt_id}] could not return the role ({type(exc).__name__})")

    def queue_waiting(self) -> bool:
        return bool(self.store.queue_positions())

    def pause(self, reason: QueuePause, detail: Optional[str] = None) -> None:
        """Pause the queue (first reason wins) and say why in the job log."""
        detail = redact(detail, self.log.values) if detail else detail
        wrote = self.store.queue_pause(reason.value, detail, utcnow())
        rt = QUEUE_PAUSE_TEXTS.get(reason)
        text = ""
        if rt:
            try:                                          # the model hints hold {detail} too (§4.2)
                text = f" {rt.text.format(detail=detail or '')} {rt.hint.format(detail=detail or '')}"
            except (KeyError, IndexError, ValueError):    # a stray brace never breaks the pause
                text = f" {rt.text} {rt.hint}"
        self.log(f"queue: paused reason={reason.value}"
                 + ("" if wrote else " (already paused)") + text)

    def precheck(self) -> Optional[tuple[QueuePause, str]]:
        """The system checks made BEFORE a take (§4.1), so a known stop leaves no
        failed row and the head stays where it is."""
        if self.profile_error:
            return QueuePause.PROFILE_INCOMPLETE, "applicant.yaml could not be read"
        missing = applicant.missing_for_apply(self.profile, self.cfg.resume_dir)
        if missing:
            return QueuePause.PROFILE_INCOMPLETE, ", ".join(missing)
        if self.acfg.fill == "llm":
            if self.real_model():
                r = self.ensure_model(load=True)              # Q-126: start and wait, then take
                if r.code == "cancelled":                     # the app is closing: nothing is taken
                    return QueuePause.APP_CLOSED, None
                if not r.ok:
                    return self.model_pause(r)
            elif not getattr(self.backend, "available", False):
                return (QueuePause.MODEL_UNAVAILABLE,
                        str(getattr(self.backend, "unavailable_code", "") or "not running"))
        return None

    # -- the local model (Q-126, D-214; ollama_autostart_design §3)

    def real_model(self) -> bool:
        """A real Ollama backend: the only kind the start-and-wait service may drive. A
        fake backend keeps the old `available` rule (pin P6)."""
        return isinstance(self.backend, backends.OllamaBackend)

    @staticmethod
    def model_pause(r: Any) -> tuple[QueuePause, Optional[str]]:
        """The pause a not-ready `ModelReady` causes, with its detail (a tag, a port or
        fixed words; never a path; empty for `model_unavailable`). Unknown codes fall back to `model_unavailable`."""
        why = MODEL_PAUSE_BY_CODE.get(r.code, QueuePause.MODEL_UNAVAILABLE)
        return why, (r.detail or None)

    def ensure_model(self, *, load: bool = True) -> Any:
        """Start Ollama when nothing listens and wait until the model answers (and, with
        `load`, is loaded), writing the worker's model state for the Runs panel. Never
        raises: an unexpected error is a `not_running` result. `should_stop` is polled
        inside every wait, so closing the app cancels it."""
        state = {"set": False}

        def on_state(s: str) -> None:
            state["set"] = True
            self.store.queue_model_state(s, utcnow())
            self.log("model: starting Ollama" if s == "starting"
                     else f"model: loading {getattr(self.backend, 'model_id', '') or 'the model'}")
        ensurer = self.model_ensurer or backends.ensure_model_running
        extra = {"pid_alive": self.model_pid_alive} if self.model_pid_alive else {}
        try:
            r = ensurer(self.cfg.budget, autostart=bool(self.model_autostart),
                        backend=self.backend, load=load,
                        keep_alive=(self.acfg.llm_fill.keep_alive or None),
                        on_state=on_state, should_stop=self.should_stop, **extra)
        except Exception as exc:                          # noqa: BLE001 - fail closed, never a crash
            self.log(f"model: the check failed ({type(exc).__name__})")
            r = backends.ModelReady("not_running")
        finally:
            if state["set"]:
                try:
                    self.store.queue_model_state(None, utcnow())
                except Exception:                         # noqa: BLE001
                    pass
        if r.ok:
            if r.started:
                self.log(f"model: Ollama answered after {int(r.seconds)} s")
            self.log(f"model: ready ({int(r.seconds)} s)")
        elif r.code != "cancelled":
            self.log(f"model: {r.code}" + (f" {r.detail}" if r.detail else ""))
        return r

    def model_retry_wanted(self, why: QueuePause, row: dict[str, Any]) -> bool:
        """Only a `model_unavailable` ending of a real Ollama backend whose row is
        `failed` with no Submit click (read from the store, NF-06) is retried."""
        return (why is QueuePause.MODEL_UNAVAILABLE and self.real_model()
                and row.get("state") == S.FAILED.value
                and row.get("submit_clicked_at") is None)

    def clear_model_state(self) -> None:
        """Drop the Runs panel's "starting / loading" state (worker start and end)."""
        try:
            self.store.queue_model_state(None, utcnow())
        except Exception:                                 # noqa: BLE001 - a display state only
            pass

    def model_retry(self, item: dict[str, Any], row: dict[str, Any]
                    ) -> Optional[tuple[QueuePause, Optional[str]]]:
        """A role ended `failed/model_unavailable` with no Submit click (§3 row 3, NF-06):
        bring the model up again, then send the role round once. Returns None when it
        goes again (the role is back at the front with the note "the local AI model
        restarted", no pause), else the pause to store. The role is returned in every
        case (RETURNS_ITEM). At most one retry per role and 2 per worker run (C5)."""
        job_id = item["job_id"]
        mode = item.get("item_mode") or "dry_run"
        company_id = row.get("company_id")

        def back(note: str) -> None:
            self.store.queue_return(job_id, company_id, mode, note, utcnow())

        r = self.ensure_model(load=True)
        if r.code == "cancelled" or self.should_stop():       # R2: never go on after a close
            back(f"returned: {QueuePause.MODEL_UNAVAILABLE.value}")
            self.log(f"queue: job={job_id} is back at the front")
            return QueuePause.APP_CLOSED, None
        if not r.ok:
            why, detail = self.model_pause(r)
            back(f"returned: {why.value}")
            self.log(f"queue: job={job_id} is back at the front")
            return why, detail
        if job_id in self.model_retried or self.model_retries >= 2:
            back(f"returned: {QueuePause.MODEL_NOT_ANSWERING.value}")
            self.log(f"queue: job={job_id} is back at the front")
            return QueuePause.MODEL_NOT_ANSWERING, None
        self.model_retried.add(job_id)
        self.model_retries += 1
        back("the local AI model restarted")                  # C11: exactly these words
        self.log(f"queue: the local AI model stopped answering; it is ready again, "
                 f"so job={job_id} goes again (once)")
        return None

    def keep_tabs(self) -> None:
        """At most DRY_RUN_TABS filled dry-run tabs stay open; a newer one closes the
        oldest (§5)."""
        while len(self.kept_tabs) > DRY_RUN_TABS:
            old = self.kept_tabs.pop(0)
            try:
                old.close()
            except Exception:                             # noqa: BLE001 - the owner may have closed it
                pass
            self.log(f"queue: closed the oldest dry-run tab (at most {DRY_RUN_TABS} stay open)")

    def hold(self) -> bool:
        """With the queue empty and a filled dry-run tab open, keep the window for up
        to `dry_run_hold_s`, in 5 s slices (§5). True = go round the loop again (a role
        is waiting, a yield is asked for or the parent is gone: the loop top handles
        those); False = finish (paused, window closed, time up, nothing to hold)."""
        if not self.kept_tabs or self.session is None or self.acfg.dry_run_hold_s <= 0:
            return False
        self.log(f"apply: dry run - the filled form(s) stay open for up to "
                 f"{self.acfg.dry_run_hold_s} s; close the window to finish sooner")
        for _ in range(max(1, -(-int(self.acfg.dry_run_hold_s) // HOLD_SLICE_S))):
            if self.should_stop():
                return True
            if self.store.queue_pause_state():
                self.log("queue: paused; the dry-run hold ends")
                return False
            if self.store.get_setting(Store.QUEUE_YIELD):
                return True
            if self.queue_waiting():
                return True
            if self.session.hold(HOLD_SLICE_S) is False:
                self.log("queue: the Edge window was closed; the dry-run hold ends")
                self.kept_tabs = []
                return False
        return False

    def run_queue(self) -> "QueueOutcome":
        """Drain the queue one role at a time (§3.2). At most one attempt in flight
        (RunLock + one loop), a role is taken in the store's own transaction, its
        mode is `pick_mode`'s, and every ending is judged by `pause_for` from the
        store row. Orderly ends (drained, paused, yielded) return normally."""
        out = QueueOutcome()
        lock = RunLock(self.evidence / "run.lock")
        if not lock.acquire():
            self.log("apply: another apply run is in progress; the queue waits")
            out.lock_refused = True
            return out
        self.queue = True
        self.clear_model_state()
        try:
            reaped = self.store.reap_attempts(utcnow())           # THE reaper of the web path (M1)
            if reaped:
                self.log(f"apply: closed {reaped} interrupted attempt(s)")
            self.purge_fill_cache()
            while True:
                if self.should_stop():
                    self.pause(QueuePause.APP_CLOSED)
                    break
                if self.store.queue_take_yield():
                    self.log("queue: a search run goes first; the queue continues after it")
                    out.yielded = True
                    break
                state = self.store.queue_pause_state()
                if state:
                    self.log(f"queue: paused reason={state['reason']}; nothing taken")
                    break
                self.acfg = self.apply_cfg_fn()                    # L1: caps, timeouts, fill per item
                self.begin_item()
                if self.queue_waiting():
                    stop = self.precheck()
                    if stop:
                        self.pause(*stop)
                        break
                if self.should_stop():                             # R2/C1: a model wait can be long
                    self.pause(QueuePause.APP_CLOSED)
                    break
                self.item = None
                item, dropped = self.store.queue_take(utcnow())
                for job_id in dropped:
                    self.log(f"queue: job={job_id} no longer To apply; skipped")
                if item is None:
                    if self.hold():
                        continue
                    break
                self.item = item
                try:
                    mode = pick_mode(item.get("item_mode"), self.acfg.mode, self.force_dry_run)
                    self.set_mode(mode)
                    self.store.update_attempt(item["attempt_id"], mode=self.mode)
                    self.store.commit()
                except BaseException:
                    job = self.store.job_for_apply(item["job_id"]) or {}
                    self.unstarted(item["attempt_id"], item["job_id"], job.get("company_id"))
                    raise
                r = self.attempt(item["job_id"], attempt_id=item["attempt_id"])
                out.results.append(r)
                row = self.store.attempt(r.attempt_id) or {}
                reason = row.get("reason_code") or ""
                self.log(f"queue: job={item['job_id']} attempt={r.attempt_id} mode={self.mode} "
                         f"-> {row.get('state') or r.state.value}"
                         + (f" reason={reason}" if reason else ""))
                if row.get("state") == S.READY_TO_SUBMIT.value:
                    self.keep_tabs()
                streak = self.store.queue_streak(self.window_start(), limit=3)
                p = pause_for(row, self.last_cap, streak, browser_failed=self.browser_failed)
                if p is None:
                    continue
                why, detail = p
                if self.model_retry_wanted(why, row):             # Q-126: one retry (§3 row 3)
                    p = self.model_retry(item, row)               # returns the role itself
                    if p is None:
                        continue
                    self.pause(*p)
                    break
                if (why in RETURNS_ITEM and row.get("state") == S.FAILED.value
                        and row.get("submit_clicked_at") is None):
                    self.store.queue_return(item["job_id"], row.get("company_id"),
                                            item.get("item_mode") or "dry_run",
                                            f"returned: {why.value}", utcnow())
                    self.log(f"queue: job={item['job_id']} is back at the front")
                self.pause(why, detail)
                break
        except Exception as exc:                          # a worker bug: fail closed, then crash
            try:
                self.pause(QueuePause.WORKER_FAILED, type(exc).__name__)
            except Exception:                             # noqa: BLE001
                pass
            raise
        except BaseException:                             # cancel / Ctrl+C: nothing more is taken
            try:
                self.pause(QueuePause.CANCELLED)
            except Exception:                             # noqa: BLE001
                pass
            raise
        finally:
            self.clear_model_state()
            try:
                self.close()
            finally:
                lock.release()
        st = self.store.queue_pause_state()
        out.paused = st["reason"] if st else ""
        out.waiting = len(self.store.queue_positions())
        return out

    def window_start(self) -> str:
        """The streak window (§4.1): the later of the last Resume and 24 h ago."""
        day_ago = shift(_stamp(self.now()), days=-1)
        resumed = self.store.get_setting(Store.QUEUE_RESUMED_AT) or ""
        return max(day_ago, resumed)


# ---------------------------------------------------------------- the queue's rules (§2 I5, §4.1)

DRY_RUN_TABS = 3                 # filled dry-run tabs kept open (§5)
HOLD_SLICE_S = 5                 # the dry-run hold checks the queue this often (§5)


@dataclasses.dataclass
class QueueOutcome:
    """What `run_queue` did (internal to the flow and the CLI)."""
    results: list = dataclasses.field(default_factory=list)
    lock_refused: bool = False   # another apply run holds RunLock: cli exits 3 (L2)
    yielded: bool = False        # a search run goes first (§6)
    paused: str = ""             # the stored pause reason at the end, "" when not paused
    waiting: int = 0             # roles still waiting at the end


def pick_mode(item_mode: Any, effective_mode: Any, force_dry_run: bool) -> str:
    """I5 (review H4): "auto" only when the item was queued in exactly "auto", the
    effective mode at pick is exactly "auto" and no --dry-run; anything else,
    an unknown or empty value included, is "dry_run". Never a string min/max."""
    if not force_dry_run and item_mode == "auto" and effective_mode == "auto":
        return "auto"
    return "dry_run"


# Fill CONTENT failures (the model gave no usable answers, or a page would be guesses:
# Q-121 A6), not transport ones: they pause `fill_failed` and the role is NOT returned,
# since it would fail the same page on every Resume (Coordinator, 2026-11-12).
# Review F3: the signal is data, not prose found anywhere. The filler that stops on such a
# failure writes one of these constants as the START of the attempt's own `reason_detail`
# (build it with `content_failure_detail`); `pause_for` matches nothing else. A1 (§17.6,
# F10): the spellings live in the contract (`CONTENT_FAILURE_MARKERS`, v8), which the
# always-answer stage and the web renderers read too, so there is no copy to drift and no
# import-time check any more. The names below are the contract's values, in its order.
FILL_NO_USABLE_ANSWERS, FILL_WOULD_BE_GUESSES, FILL_LAST_RESORT = CONTENT_FAILURE_MARKERS
CONTENT_FAILURE_DETAILS = tuple(CONTENT_FAILURE_MARKERS)   # the earlier name, same values
# A `validation_error` detail is the employer's own error text (`res.errors`), so it is
# never read as a content failure even when that text happens to begin with a marker.
_PAGE_TEXT_REASONS = frozenset({ReasonCode.VALIDATION_ERROR.value})
TRANSPORT_FAILURE_MARKERS = ("model unavailable",)


def content_failure_detail(marker: str, rest: str = "") -> str:
    """The `reason_detail` a content-failure stop writes: the marker first, then an
    optional plain note (no personal value). Raises on a marker not in the list."""
    if marker not in CONTENT_FAILURE_DETAILS:
        raise ValueError(f"not a content-failure marker: {marker!r}")
    return f"{marker}: {rest}" if rest else marker


def is_content_failure(row: dict) -> bool:
    """A failed attempt whose own `reason_detail` STARTS with a content-failure marker
    (review F3). A marker later in the text, or in a page-text detail, does not count."""
    if row.get("state") != S.FAILED.value or row.get("reason_code") in _PAGE_TEXT_REASONS:
        return False
    detail = str(row.get("reason_detail") or "").lstrip().lower()
    return any(detail.startswith(m) for m in CONTENT_FAILURE_DETAILS)
_BOT_REASONS = frozenset({ReasonCode.CAPTCHA.value, ReasonCode.BOT_CHALLENGE.value})
_BOT_NOTES = ("captcha after submit", "bot check after submit")
# Per-role endings before any form or account: never a "same way three times" pause.
_NOT_REPEATED = frozenset({ReasonCode.DUPLICATE.value, ReasonCode.POSTING_CLOSED.value,
                           ReasonCode.CAP_REACHED.value, ReasonCode.CANCELLED.value,
                           ReasonCode.UNSUPPORTED_ATS.value})


def _bot_ending(r: dict) -> bool:
    detail = str(r.get("reason_detail") or "").lower()
    return (r.get("state") == S.FAILED.value and r.get("reason_code") in _BOT_REASONS) or \
        any(n in detail for n in _BOT_NOTES)


def pause_for(row: Optional[dict], last_cap: str, streak: Sequence[dict], *,
              browser_failed: str = "") -> Optional[tuple[QueuePause, Optional[str]]]:
    """§4.1, checked top to bottom: the pause one finished item causes, with its
    detail, or None (the queue goes on). `row` is the store row (M5), `streak`
    `queue_streak`'s newest-first finished attempts in the window (M4). Whether the
    role goes back is the caller's: RETURNS_ITEM, a `failed` row, no Submit click.
    Deterministic, no model."""
    if not row:
        return QueuePause.WORKER_FAILED, "the attempt row is missing"
    reason = str(row.get("reason_code") or "")
    detail = str(row.get("reason_detail") or "")
    low = detail.lower()
    failed = row.get("state") == S.FAILED.value
    if reason == ReasonCode.PROFILE_INCOMPLETE.value:
        return QueuePause.PROFILE_INCOMPLETE, detail or None
    if is_content_failure(row):
        return QueuePause.FILL_FAILED, None
    if reason == ReasonCode.MODEL_UNAVAILABLE.value or (
            failed and any(m in low for m in TRANSPORT_FAILURE_MARKERS)):
        return QueuePause.MODEL_UNAVAILABLE, None
    if browser_failed:
        return QueuePause.BROWSER_UNAVAILABLE, browser_failed
    if reason == ReasonCode.CAP_REACHED.value and last_cap == "daily":
        return QueuePause.DAILY_LIMIT, detail or None
    recent = list(streak)
    if len(recent) >= 2 and all(_bot_ending(r) for r in recent[:2]):
        return QueuePause.BOT_CHECKS, None
    last3 = recent[:3]
    if len(last3) == 3 and all(r.get("state") == S.FAILED.value
                               and r.get("reason_code") == ReasonCode.ERROR.value for r in last3):
        return QueuePause.REPEATED_ERRORS, None
    # Q-121 §4.6: `owner_fact_missing` is per role (the queue goes on); only the SAME fact
    # missing on the last 3 roles pauses, naming it. It never joins the generic streak.
    # A1 §17.6 (review C8): `consent_refused` joins this branch: the same refused consent on
    # the last 3 roles pauses naming it; different consents, or a mix of the two reasons,
    # return None and never fall into the generic "consent refused" streak below.
    if (len(last3) == 3 and all(r.get("state") == S.FAILED.value
                                and r.get("reason_code") in _PER_ROLE_NAMED for r in last3)):
        codes = {r.get("reason_code") for r in last3}
        facts = {owner_fact_of(r.get("reason_detail")).lower() for r in last3}
        if len(codes) == 1 and len(facts) == 1 and next(iter(facts)):
            fact = owner_fact_of(last3[0].get("reason_detail"))
            return QueuePause.REPEATED_FAILURES, f"{fact} {_PER_ROLE_NAMED[next(iter(codes))]}"
        return None
    if (len(last3) == 3 and all(r.get("state") == S.FAILED.value for r in last3)
            and len({r.get("reason_code") for r in last3}) == 1):
        same = str(last3[0].get("reason_code") or "")
        if same and same not in _NOT_REPEATED and same != ReasonCode.ERROR.value:
            return QueuePause.REPEATED_FAILURES, same.replace("_", " ")
    return None


_OWNER_FACT = ReasonCode.OWNER_FACT_MISSING.value
_CONSENT_REFUSED = ReasonCode.CONSENT_REFUSED.value
# The per-role reasons that wait for the owner and pause only when the same detail repeats
# 3 times, with the words after the detail in the pause text (§4.6, A1 §17.6).
_PER_ROLE_NAMED = {_OWNER_FACT: "is missing from your profile",
                   _CONSENT_REFUSED: "is refused in your profile"}


def consent_refused_detail(target_path: Any, detail: Any = "") -> str:
    """A `consent_refused` reason_detail (A1 §17.6): the contract's plain words for the
    refused key (`CONSENT_REFUSED_DETAILS`, keyed by "consents.<key>", e.g. "keeping your
    details on file for future roles"), else the stop's own detail, else a generic phrase.
    Read through REASON_TEXTS[CONSENT_REFUSED] ("This form needs you to agree to {detail},
    and your profile says no."). Never a value: a consent's words, not the owner's answer."""
    words = CONSENT_REFUSED_DETAILS.get(str(target_path or "").strip())
    if words:
        return words
    return " ".join(str(detail or "").split()) or "a consent this form requires"


def owner_fact_detail(fact: str, label: str = "", step: str = "") -> str:
    """An `owner_fact_missing` reason_detail (review F4): the fact in plain words first (the
    contract's "This form asks for your {detail}"), then where the form asked it, in the
    form's own words: "date of birth (“Date of Birth” on my_information)". Never a value."""
    fact = " ".join(str(fact or "").split())
    where = " ".join(x for x in (f"“{label}”" if label else "", f"on {step}" if step else "") if x)
    return f"{fact} ({where})" if where else fact


def owner_fact_of(detail: Any) -> str:
    """The fact of an `owner_fact_missing` detail (`owner_fact_detail`'s first part; a
    detail written before review F4 is the fact alone)."""
    text = " ".join(str(detail or "").split())
    return text.split(" (", 1)[0].strip()


def _session_alive(session: Any) -> bool:
    """`session.alive()` when the session has one (a fake may not: then it is alive)."""
    alive = getattr(session, "alive", None)
    if alive is None:
        return True
    try:
        return bool(alive())
    except Exception:                                     # noqa: BLE001 - unknown = reopen
        return False


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
        evidence_dir: Optional[Path] = None,
        now: Optional[Callable[[], float]] = None) -> list[AttemptResult]:
    """Apply to each job in order (apply_design §3). `apply_cfg` is the
    effective settings (cmd_apply merges the settings table over config);
    `http`, `browser_factory` and `now` (UTC epoch seconds, default `time.time`;
    the clock of the FillServices, TR-5) exist so tests inject fakes."""
    r = _Run(cfg, store, dry_run=dry_run, backend=backend,
             http=http if http is not None else make_http(cfg),
             browser_factory=browser_factory or default_browser_factory,
             acfg=apply_cfg or cfg.apply, say=say, evidence=evidence_dir, now=now)
    return r.run(job_ids)


def run_queue(cfg: Config, store: Store, *, backend: Any,
              apply_cfg_fn: Callable[[], ApplyConfig], http: Any = None,
              browser_factory: Optional[Callable[[ApplyConfig], Any]] = None,
              say: Callable[[str], None] = print, evidence_dir: Optional[Path] = None,
              now: Optional[Callable[[], float]] = None,
              should_stop: Optional[Callable[[], bool]] = None,
              force_dry_run: bool = False, model_autostart: bool = False,
              model_ensurer: Optional[Callable[..., Any]] = None,
              model_pid_alive: Optional[Callable[[int], bool]] = None) -> QueueOutcome:
    """The auto-apply queue worker (apply_queue_design §3.2, D-205): take the head
    role, apply to it, judge the ending (§4.1), repeat until the queue is empty,
    paused or a search run asks to go first. `apply_cfg_fn` gives the effective
    settings and is called again for every role (L1); `should_stop` is True once
    the web process that started the worker is gone (§3.3); `force_dry_run` is
    `apply queue --dry-run`. The mode of each role is `pick_mode`'s (I5).

    Q-126 (D-214): with a real Ollama backend the worker brings the model up before
    every take (`backends.ensure_model_running`; `model_ensurer` is the test seam).
    `model_autostart` (default off: only the CLI turns it on, after the process rule
    and the owner's switch) lets it START Ollama; `model_pid_alive` is the lock's
    liveness check."""
    acfg = apply_cfg_fn()
    r = _Run(cfg, store, dry_run=True, backend=backend,
             http=http if http is not None else make_http(cfg),
             browser_factory=browser_factory or default_browser_factory,
             acfg=acfg, say=say, evidence=evidence_dir, now=now)
    r.apply_cfg_fn = apply_cfg_fn
    r.should_stop = should_stop or (lambda: False)
    r.force_dry_run = bool(force_dry_run)
    r.model_autostart = bool(model_autostart)
    r.model_ensurer = model_ensurer
    r.model_pid_alive = model_pid_alive
    return r.run_queue()
