"""F-50 application status from email: the orchestrator (mail_status_design §4, §5).

`sync` reads every switched-on mailbox after its stored cursor, one message at a
time, and stores each message's outcome together with the cursor advance
(`store.mail_record`, one transaction, F-50s). `connect` and `set_password` test
a read-only login before anything is stored (F-50a).

Why an orchestrator. It wires five things that may not know each other: the
vault (the app password), `imapread` (the read-only transport), the store, the
pure `mailstatus` stage (gates, matcher, classifier, transitions, model prompt)
and `backends` (the local model). The stage never touches IMAP or the model; it
gets parsed headers, plain body text and store rows from here (MS §2.1).

Privacy (MS §13, F-50r). Logs and the report carry account ids, counts,
`SyncCode` / `Reason` values and exception class names only: never an address,
display name, subject, quote, body, URL, X-GM-MSGID or password. An exception's
message can hold mail text, so the catch-all logs its class and its stack frames
(file, line, function), never `str(exc)`.

Single flight (MS §10.2): `store.mail_run_begin` takes the lease under BEGIN
IMMEDIATE; the run renews it after each scan, every 100 messages and before each
model call, and stops at a message boundary when it has lost it.
"""
from __future__ import annotations

import logging
import os
import re
import time
import traceback
from dataclasses import replace
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Union

from . import applicant, imapread, vault
from .apply.contracts import Secret
from .mailstatus import match as mmatch
from .mailstatus import model as mmodel
from .mailstatus import rules as mrules
from .mailstatus import transition as mtrans
from .mailstatus.contracts import (ADDRESS_PATTERN, CONSENT_VERSION, GMAIL_HOST, GMAIL_PORT,
                                   NOTE_CODES, PAUSING_CODES, QUOTE_MAX, SUBJECT_MAX,
                                   TIME_FMT, AccountReport, AccountState, AppCandidate,
                                   Category, ChangeKind, Cursor, MailBody, MailFailure,
                                   MailHeader, MailboxRole, MatchKind, Outcome, Reason,
                                   SyncCode, SyncReport, Verdict)

log = logging.getLogger(__name__)

# Triggers that may try a PAUSED mailbox once (MS §5.1): the owner asked.
OWNER_TRIGGERS = frozenset({"manual", "cli", "connect"})
TRIGGERS = ("startup", "timer", "manual", "connect", "cli")
HEARTBEAT_EVERY = 100           # messages between lease renewals
_NO_TRACE_REASONS = frozenset({Reason.NOT_JOB_MAIL, Reason.OWN_MAIL, Reason.TOO_OLD})

Clock = Union[None, str, Callable[[], str]]
TransportFactory = Callable[[dict, Secret], Any]


class _Stop(Exception):
    """Stop the account's scan before this message (a cap, the deadline, a
    lost lease, or the account disconnected meanwhile): the run ends `partial`
    and the next one continues here."""


class _Wedged(Exception):
    """MAX_MESSAGE_FAILURES messages in a row failed: something is wrong beyond
    one email, so the account stops as `internal` (MS §12, D-157 a)."""


MAX_MESSAGE_FAILURES = 3        # consecutive per-message failures before the account stops


def _clock(now: Clock) -> Callable[[], str]:
    if callable(now):
        return now
    if isinstance(now, str):
        return lambda: now
    return lambda: datetime.utcnow().strftime(TIME_FMT)


def _shift(stamp: str, **delta: float) -> str:
    return (datetime.strptime(stamp, TIME_FMT) + timedelta(**delta)).strftime(TIME_FMT)


def _default_transport(row: dict, password: Secret) -> Any:
    return imapread.ImapTransport(row.get("host") or GMAIL_HOST, int(row.get("port") or GMAIL_PORT),
                                  row["address"], password)


def _open_store(cfg: Any, store: Any) -> tuple[Any, bool]:
    if store is not None:
        return store, False
    from .store import Store
    return Store(cfg.db_path), True


def _log_crash(what: str, exc: BaseException) -> None:
    """The traceback without the exception's message (it may hold mail text)."""
    frames = "".join(traceback.format_tb(exc.__traceback__))
    log.error("%s: %s\n%s", what, type(exc).__name__, frames)


# ---------------------------------------------------------------- shared context

def _apply_boxes(cfg: Any, st: Any) -> tuple[Any, str]:
    """The effective apply.mail (settings over config) and the backup username."""
    ac = cfg.apply.with_settings(st.get_setting)
    backup = st.get_setting("apply.mail_backup.username") or ac.mail_backup.username
    return ac.mail, str(backup or "")


def own_addresses(cfg: Any, st: Any) -> frozenset[str]:
    """The owner's own addresses (MS §6.2 own_mail): every connected mailbox,
    apply.mail / apply.mail_backup, and the profile's contact addresses."""
    out = {str(a["address"]).lower() for a in st.mail_accounts()}
    box, backup = _apply_boxes(cfg, st)
    out |= {u.strip().lower() for u in (box.username, backup) if u}
    try:
        profile = applicant.load(cfg.applicant_path)
    except Exception:                               # noqa: BLE001 - no profile yet is fine
        profile = {}
    contact = profile.get("contact") if isinstance(profile, dict) else None
    if isinstance(contact, dict):
        out |= {str(contact[k]).strip().lower() for k in ("email", "backup_email")
                if contact.get(k)}
    return frozenset(a for a in out if a)


def candidates(st: Any, rules: Any) -> list[AppCandidate]:
    """`store.mail_match_context` as AppCandidates. Employer domains are the
    registrable domains of the job, application and careers hosts, with every
    platform, tenant-site and job-board domain dropped (D-154 a,
    `match.employer_domains`); tenants come from `match.tenants_from_hosts` (E1)."""
    out = []
    for c in st.mail_match_context():
        hosts = mmatch.employer_domains(c["employer_hosts"], rules)
        regs = mmatch.employer_domains(
            [imapread.registrable_domain(h) for h in hosts], rules)
        out.append(AppCandidate(
            job_id=c["job_id"], status=c["status"], company_names=tuple(c["company_names"]),
            role=c["role"], employer_domains=tuple(r for r in regs if r),
            tenants=mmatch.tenants_from_hosts(c["tenant_hosts"], rules),
            board_slugs=tuple(c["board_slugs"]), req_ids=tuple(c["req_ids"]),
            threads=tuple(c["threads"]), owner_changed_at=c["owner_changed_at"],
            last_event_at=c["last_event_at"],
            # D-157 h: when the application was entered (a backfill shows up as
            # an entry later than the mail: a `backfilled` suggestion).
            first_event_at=c.get("first_event_at")))
    return out


def _utc_stamp(value: Any) -> Optional[str]:
    """A stored date or time as UTC TIME_FMT text, or None when unreadable
    (review FL-10: `applied_at` may carry an offset, microseconds or "Z")."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime(TIME_FMT)


def first_sync_from(cfg: Any, st: Any, now: str) -> str:
    """MS §5.3 / F-50f: the earliest open application's date minus a day,
    clamped to [now - first_sync_max_days, now - 1 day]. An unreadable date
    counts as the widest window (FL-10): nothing is missed, nothing crashes."""
    terminal = set(cfg.mail_status.terminal)
    lo = _shift(now, days=-float(cfg.mail_status.first_sync_max_days))
    starts = []
    for c in st.mail_match_context():
        if c["status"] in terminal:
            continue
        stamp = c["first_event_at"] if c["status"] == "to_apply" else c["applied_at"]
        if stamp:
            starts.append(_utc_stamp(stamp) or _shift(lo, days=1))
    hi = _shift(now, days=-1)
    start = _shift(min(starts), days=-1) if starts else hi
    return max(lo, min(start, hi))


# ---------------------------------------------------------------- one sync

class _Account:
    """The state of one mailbox's pass through `sync`."""

    def __init__(self, flow: "_Sync", row: dict, transport: Any):
        self.flow, self.row, self.t = flow, row, transport
        self.id = int(row["id"])
        self.report = AccountReport(self.id)
        self.c = self.report.counts
        self.failures_in_row = 0
        self.refresh()

    def refresh(self) -> None:
        """Re-read the applications after a write, so the next message sees the
        status and threads this run just stored."""
        self.apps = candidates(self.flow.st, self.flow.rules)
        self.by_id = {a.job_id: a for a in self.apps}
        self.threads = frozenset(t for a in self.apps for t in a.threads)
        self.employer_regs = frozenset(d for a in self.apps for d in a.employer_domains)


class _Sync:
    def __init__(self, cfg: Any, st: Any, rules: Any, *, trigger: str, defer_model: bool,
                 backend: Any, factory: TransportFactory, now: Callable[[], str], run_id: int):
        self.cfg, self.st, self.rules = cfg, st, rules
        self.ms = cfg.mail_status
        self.trigger, self.defer_model = trigger, defer_model
        self.backend, self.factory, self.now, self.run_id = backend, factory, now, run_id
        self.policy = mtrans.build_policy(cfg.application_statuses, self.ms)
        self.own = own_addresses(cfg, st)
        self.deadline = time.monotonic() + float(self.ms.sync_timeout_s)
        self.model_calls = 0
        self.call_failed = False
        self.model_down = not self.ms.model or backend is None or not _available(backend)

    # ---------------------------------------------------------------- lease

    def beat(self) -> None:
        if not self.st.mail_run_heartbeat(self.run_id, self.now()):
            log.warning("mail sync run %s lost its lease; stopping", self.run_id)
            raise _Stop("lease")

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise _Stop("deadline")

    # ---------------------------------------------------------------- an account

    def account(self, row: dict) -> AccountReport:
        rep = AccountReport(int(row["id"]))
        try:
            pw = vault.get(row["vault_service"], row["address"])
        except vault.VaultError:
            rep.code = SyncCode.VAULT_ERROR
            return rep
        if pw is None:
            rep.code = SyncCode.NOT_SET_UP
            return rep
        transport = self.factory(row, pw)
        acc = None
        try:
            info = transport.open()
            rep.notes = tuple(n for n in info.notes if n in NOTE_CODES)
            acc = _Account(self, row, transport)
            acc.report.notes = rep.notes
            rep = acc.report
            folders = info.folders
            roles = [MailboxRole.ALL if MailboxRole.ALL in folders else MailboxRole.INBOX]
            if MailboxRole.JUNK in folders:
                roles.append(MailboxRole.JUNK)
            budget = int(self.ms.max_headers_per_sync)
            for role in roles:
                if role not in folders:
                    continue
                budget = self.scan_role(acc, role, budget)
            self.retry_pending(acc)
        except _Stop:
            rep.code = SyncCode.PARTIAL
        except _Wedged:
            log.error("mail sync account %s: %s messages in a row failed; stopping",
                      row["id"], MAX_MESSAGE_FAILURES)
            rep.code = SyncCode.INTERNAL
        except MailFailure as exc:
            rep.code = exc.code
        except Exception as exc:                    # noqa: BLE001 - per account (MS §12)
            if _db_busy(exc):
                rep.code = SyncCode.DB_BUSY
            else:
                _log_crash(f"mail sync account {row['id']}", exc)
                rep.code = SyncCode.INTERNAL
        finally:
            try:
                transport.close()
            except Exception:                       # noqa: BLE001
                pass
        return rep

    def scan_role(self, acc: _Account, role: MailboxRole, budget: int) -> int:
        stored = self.st.mail_cursor(acc.id, role)
        cursor = None
        if stored:
            cursor = Cursor(acc.id, role, stored["mailbox"], int(stored["uidvalidity"]),
                            int(stored["last_uid"]), stored["last_scan_at"])
        if budget <= 0:
            raise _Stop("headers cap")
        scan = acc.t.scan(role, cursor, account_id=acc.id,
                          window_start=acc.row["first_sync_from"], limit=budget, now=self.now())
        self.beat()
        acc.c["scanned"] += len(scan.headers)
        seen = self.st.mail_seen_many(acc.id, [h.gm_msgid for h in scan.headers])
        for i, h in enumerate(scan.headers):
            self.check_time()
            if i and i % HEARTBEAT_EVERY == 0:
                self.beat()
            if h.gm_msgid in seen:
                self.cursor(h.cursor_after)
                acc.c["duplicates"] += 1
                continue
            res, msg = self.isolated(acc, h, lambda: self.record(acc, h))
            seen.add(h.gm_msgid)
            self.count(acc, res["outcome"])
            if res["event_id"] or (msg and msg.get("job_id")):
                acc.refresh()
        if not scan.complete:
            raise _Stop("headers cap")
        if scan.end_cursor is not None:
            self.cursor(scan.end_cursor)
        return budget - len(scan.headers)

    def cursor(self, cursor: Cursor) -> None:
        """Move a cursor; an account disconnected meanwhile stops the scan (D-158 4)."""
        if self.st.mail_cursor_set(cursor) is False:
            raise _Stop("gone")

    def record(self, acc: _Account, h: MailHeader) -> tuple[dict, dict]:
        """Steps 2-8 for one new header: decide, then store with the cursor."""
        msg, change, evidence = self.process(acc, h)
        res = self.st.mail_record(account_id=acc.id, message=msg, cursor=h.cursor_after,
                                  change=change, evidence=evidence, now=self.now())
        return res, msg

    def isolated(self, acc: _Account, h: MailHeader, work: Callable[[], tuple],
                 fallback: Optional[Callable[[dict], dict]] = None) -> tuple:
        """Run one message's work so that one bad email can't wedge the mailbox
        (review FL-1, D-157 a). A failure is logged by class and frames only,
        the message is stored as a minimal `skipped / internal` row with its
        cursor (one transaction; no text), and counted in `errors`; after
        MAX_MESSAGE_FAILURES in a row the account stops. A cap, the deadline, a
        lost lease (`_Stop`), a transport failure and a locked database are the
        account's business, not the message's, and pass through. An account
        disconnected meanwhile (`gone`, FL-3) stops the scan. `fallback(row)`
        stores the minimal row (default: `mail_record` with the cursor)."""
        try:
            res, msg = work()
        except (_Stop, MailFailure):
            raise
        except Exception as exc:                    # noqa: BLE001 - this message only
            if _db_busy(exc):
                raise                               # D-158 3: the run ends and retries
            _log_crash(f"mail sync account {acc.id}: one message failed", exc)
            acc.c["errors"] += 1
            acc.failures_in_row += 1
            row = self.failed_row(h)
            res = (fallback(row) if fallback is not None else self.st.mail_record(
                account_id=acc.id, message=row, cursor=h.cursor_after, now=self.now()))
            msg = None
            if res["outcome"] != "gone" and acc.failures_in_row >= MAX_MESSAGE_FAILURES:
                raise _Wedged() from None
        else:
            acc.failures_in_row = 0
        if res["outcome"] == "gone":
            log.info("mail sync account %s was disconnected during the sync; stopping", acc.id)
            raise _Stop("gone")
        return res, msg

    @staticmethod
    def failed_row(h: MailHeader) -> dict:
        """The minimal row for a message whose processing failed: position and
        date only, no domain, no text (MS §12 as amended, D-157 a)."""
        return {"gm_msgid": h.gm_msgid, "gm_thrid": None, "role": h.ref.role,
                "validity": h.ref.validity, "uid": h.ref.uid, "received_at": h.received_at,
                "sender_domain": "", "outcome": Outcome.SKIPPED, "reason": Reason.INTERNAL,
                "category": None, "tier": None, "rule_id": None, "job_id": None,
                "match_json": None}

    @staticmethod
    def count(acc: _Account, outcome: Any) -> None:
        key = {"skipped": "skipped", "unmatched": "unmatched", "applied": "applied",
               "suggested": "suggested", "pending_model": "pending_model"}.get(str(outcome))
        if key:
            acc.c[key] += 1

    # ---------------------------------------------------------------- one message (MS §5.4)

    def process(self, acc: _Account, h: MailHeader, *, expired: bool = False
                ) -> tuple[dict, Optional[dict], Optional[dict]]:
        """Steps 2-7 for one header: the message row, the change and the evidence
        `mail_record` stores. `expired` (a pending row out of retries) turns an
        undecided verdict into a `model_unavailable` suggestion with no target."""
        reason = mrules.header_gate(h, self.rules, own=self.own,
                                    window_start=acc.row["first_sync_from"],
                                    threads=acc.threads, employer_regs=acc.employer_regs)
        if reason is not None:
            return self.row(h, Outcome.SKIPPED, reason), None, None
        if acc.c["bodies"] >= int(self.ms.max_bodies_per_sync):
            raise _Stop("bodies cap")
        body = acc.t.fetch_body(h.ref, int(self.ms.max_body_bytes))
        acc.c["bodies"] += 1
        if body is None:
            return self.row(h, Outcome.NO_CHANGE, Reason.VANISHED), None, None
        in_thread = h.gm_thrid in acc.threads
        reason = mrules.content_gate(h, body, self.rules, in_matched_thread=in_thread)
        if reason is not None:
            return self.row(h, Outcome.SKIPPED, reason), None, None
        m = mmatch.match(h, body, acc.apps, self.rules)
        if m.kind is MatchKind.NONE:
            return self.row(h, Outcome.UNMATCHED, Reason.NO_APPLICATION, m=m), None, None
        acc.c["matched"] += 1
        verdict = mrules.classify(h, body, self.rules)
        if mrules.needs_model(verdict):
            verdict = self.ask_model(acc, h, body, verdict, expired)
            if verdict is None:
                why = Reason.MODEL_DEFERRED if self.defer_model else Reason.MODEL_UNAVAILABLE
                return self.row(h, Outcome.PENDING_MODEL, why, m=m), None, None
        return self.decide(acc, h, m, verdict, expired)

    def ask_model(self, acc: _Account, h: MailHeader, body: MailBody, verdict: Verdict,
                  expired: bool) -> Optional[Verdict]:
        """The model tier (MS §6.5) through `backends`; None = pending. Expired
        rows and `mail_status.model: false` get no call: an unclear suggestion."""
        self.call_failed = False
        if expired or not self.ms.model:
            return replace(verdict, category=Category.UNKNOWN, status_words=True)
        if (self.defer_model or self.model_down
                or self.model_calls >= int(self.ms.model_max_calls)):
            return None
        self.beat()
        self.model_calls += 1
        acc.c["model_calls"] += 1
        try:
            reply = self.backend.complete(
                mmodel.SYSTEM, mmodel.user_prompt(h, body, int(self.ms.model_max_chars)),
                max_tokens=mmodel.MAX_TOKENS, format=mmodel.SCHEMA,
                temperature=mmodel.TEMPERATURE, seed=mmodel.SEED,
                timeout=float(self.ms.model_timeout_s))
        except Exception as exc:                    # noqa: BLE001 - BackendError, a timeout
            # The message may echo the server's reply: the class name only.
            log.warning("mail model call failed (%s); the rest wait for the next sync",
                        type(exc).__name__)
            self.model_down = True
            self.call_failed = True                 # FL-5: this is a try that counts
            return None
        return mmodel.parse(getattr(reply, "text", reply), h, body,
                            str(getattr(self.backend, "model_id", "") or ""))

    def decide(self, acc: _Account, h: MailHeader, m: Any, verdict: Verdict, expired: bool
               ) -> tuple[dict, Optional[dict], Optional[dict]]:
        ambiguous = m.kind is MatchKind.AMBIGUOUS
        cands = [acc.by_id[j] for j in m.candidates if j in acc.by_id] if ambiguous else []
        app = (cands[0] if cands else None) if ambiguous else acc.by_id.get(m.job_id)
        change = mtrans.decide(app, verdict, m, h, self.policy, candidates=cands)
        if expired and change.kind is ChangeKind.SUGGEST and change.reason is Reason.UNCLEAR:
            change = replace(change, reason=Reason.MODEL_UNAVAILABLE, to_status=None)
        # The thread signal (MS §7) only for a confident, unique match; a weak or
        # ambiguous one gets its job_id when the owner accepts it (MS §8).
        job_id = m.job_id if m.kind is MatchKind.STRONG else None
        # Row 7a (D-161): a question with no target. Even a STRONG match must not
        # attach the thread to the closed application, or a later rejection in it
        # would match by `thread` and stay silent.
        untracked = change.reason is Reason.MAYBE_UNTRACKED
        if untracked:
            job_id = None
        kind = change.kind
        if kind is ChangeKind.NONE:
            return self.row(h, Outcome.NO_CHANGE, change.reason, m=m, v=verdict,
                            job_id=job_id), None, None
        evidence = {"subject": h.subject[:SUBJECT_MAX],
                    "quote": (verdict.quote or h.subject)[:QUOTE_MAX],
                    "category": verdict.category, "tier": verdict.tier,
                    "rule_id": verdict.rule_id or None, "model": verdict.model or None,
                    "reason": change.reason, "from_status": change.from_status,
                    "to_status": change.to_status}
        if kind is ChangeKind.AUTO:
            ch = {"kind": "auto", "job_id": m.job_id, "from_status": change.from_status,
                  "to_status": change.to_status, "applied_at": h.received_at[:10]}
            return (self.row(h, Outcome.APPLIED, change.reason, m=m, v=verdict, job_id=m.job_id),
                    ch, evidence)
        if untracked and not ambiguous:
            matched = [app] if app is not None else []
            evidence.update(job_id=None, from_status=None,
                            candidates_json=[{"job_id": a.job_id, "status": a.status}
                                             for a in matched])
        elif ambiguous:
            left = mtrans.remaining_candidates(app, verdict, m, h, self.policy, candidates=cands)
            # An unclear / check-the-portal suggestion has no target, so row 4
            # settles nothing: the owner still picks among every match.
            left = left or tuple(cands)
            evidence.update(job_id=None, from_status=None,
                            candidates_json=[{"job_id": a.job_id, "status": a.status} for a in left])
        else:
            evidence["job_id"] = m.job_id
        ch = {"kind": "suggest", "job_id": evidence.get("job_id"),
              "from_status": evidence.get("from_status"), "to_status": change.to_status}
        return (self.row(h, Outcome.SUGGESTED, change.reason, m=m, v=verdict, job_id=job_id),
                ch, evidence)

    @staticmethod
    def row(h: MailHeader, outcome: Outcome, reason: Reason, *, m: Any = None,
            v: Optional[Verdict] = None, job_id: Optional[str] = None) -> dict:
        """The `mail_messages` row: no subject, no address, no text (MS §9)."""
        match_json = None
        if m is not None:
            match_json = {"kind": m.kind.value, "signals": [s.value for s in m.signals],
                          "candidates": list(m.candidates)}
        return {"gm_msgid": h.gm_msgid, "gm_thrid": h.gm_thrid, "role": h.ref.role,
                "validity": h.ref.validity, "uid": h.ref.uid, "received_at": h.received_at,
                "sender_domain": "" if reason in _NO_TRACE_REASONS else h.from_domain,
                "outcome": outcome, "reason": reason,
                "category": v.category if v else None, "tier": v.tier if v else None,
                "rule_id": (v.rule_id or None) if v else None, "job_id": job_id,
                "match_json": match_json}

    # ---------------------------------------------------------------- pending model (MS §5.5)

    def retry_pending(self, acc: _Account) -> None:
        """MS §5.5 as amended (D-157 d, review FL-5): a `pending_model` row is
        retried when the model can be asked. A retry counts only when a call
        was made and gave no usable answer; a deferred run, a model that is off
        or down, or the call budget leaves the row as it is, so only its age
        (`retry_model_days`) expires it. An expired row becomes a
        `model_unavailable` suggestion with no target."""
        rows = self.st.mail_pending(acc.id, self.now(), float(self.ms.retry_model_days))
        for p in rows:
            self.check_time()
            expired = bool(p["expired"])
            # model: false settles every row now (an unclear suggestion, below).
            if not expired and self.ms.model and (
                    self.defer_model or self.model_down
                    or self.model_calls >= int(self.ms.model_max_calls)):
                continue                            # no call: no try is used up
            h = acc.t.refind(p["gm_msgid"])
            if h is None:
                res = self.st.mail_resolve_pending(
                    acc.id, p["gm_msgid"], {"outcome": "no_change", "reason": "vanished"},
                    now=self.now())
                if res["outcome"] == "gone":
                    raise _Stop("gone")
                self.count(acc, res["outcome"])
                continue
            retries = int(p.get("retries") or 0)

            def work(h=h, expired=expired, retries=retries):
                msg, change, evidence = self.process(acc, h, expired=expired)
                if msg["outcome"] is Outcome.PENDING_MODEL:
                    msg = {"outcome": "pending_model", "reason": _value(msg["reason"]),
                           "retries": retries + 1 if self.call_failed else retries}
                return self.st.mail_resolve_pending(acc.id, h.gm_msgid, msg, change, evidence,
                                                    now=self.now()), msg

            def fallback(row, gm_msgid=p["gm_msgid"]):
                return self.st.mail_resolve_pending(acc.id, gm_msgid, row, now=self.now())

            try:
                res, _msg = self.isolated(acc, h, work, fallback)
            except _Stop as stop:
                if str(stop) == "bodies cap":
                    return                          # the next sync retries the rest
                raise
            if res["outcome"] != "pending_model":
                self.count(acc, res["outcome"])
            if res["event_id"]:
                acc.refresh()

    # ---------------------------------------------------------------- the account row

    def settle(self, row: dict, rep: AccountReport) -> None:
        """MS §12: the account state, its code, the backoff and the counts."""
        now = self.now()
        code = rep.code
        fails = int(row.get("fail_count") or 0)
        fields: dict[str, Any] = {"last_sync_at": now, "notes": [n.value for n in rep.notes],
                                  "last_counts_json": rep.counts}
        if code is SyncCode.DB_BUSY:
            # D-158 3: not the mailbox's fault; no backoff, the next sync retries.
            self.st.mail_account_set(int(row["id"]), last_sync_at=now)
            return
        if code in (SyncCode.OK, SyncCode.PARTIAL):
            fields.update(state=AccountState.OK.value, state_code=None, fail_count=0,
                          retry_after=None, last_ok_at=now)
        elif code in PAUSING_CODES:
            fields.update(state=AccountState.PAUSED.value, state_code=code.value,
                          fail_count=fails + 1, retry_after=None)
        elif code is SyncCode.RATE_LIMITED:
            fields.update(state=AccountState.BACKOFF.value, state_code=code.value,
                          fail_count=fails + 1, retry_after=_shift(now, minutes=60))
        elif code is SyncCode.NOT_GMAIL:
            fields.update(state=AccountState.ERROR.value, state_code=code.value,
                          fail_count=fails + 1, retry_after=_shift(now, hours=24))
        else:
            n = fails + 1
            wait = float(self.ms.interval_min) * min(2 ** (n - 1), 6)
            fields.update(state=AccountState.ERROR.value, state_code=code.value,
                          fail_count=n, retry_after=_shift(now, minutes=wait))
        self.st.mail_account_set(int(row["id"]), **fields)


def _db_busy(exc: BaseException) -> bool:
    """A locked or busy database (another writer held it past the timeout): not
    the message's fault, so the run ends and the next one retries (D-158 3)."""
    text = str(exc).lower() if isinstance(exc, sqlite3.OperationalError) else ""
    return "locked" in text or "busy" in text


def _value(v: Any) -> str:
    return str(getattr(v, "value", v))


def _available(backend: Any) -> bool:
    try:
        return bool(backend.available)
    except Exception:                               # noqa: BLE001
        return False


def _eligible(row: dict, trigger: str, now: str, account_id: Optional[int]) -> bool:
    """MS §5.1: switched on, consent current, and, unless the owner asked (Check
    now, the CLI, a connect), not PAUSED and not waiting out a backoff. D-157 e
    (review FL-6, supersedes D-156 (2)): an owner trigger tries once more even
    in backoff, since a silent no-op is worse than one extra login."""
    if account_id is not None and int(row["id"]) != int(account_id):
        return False
    if not row["enabled"] or row.get("consent_version") != CONSENT_VERSION:
        return False
    if trigger in OWNER_TRIGGERS:
        return True
    if row.get("state") == AccountState.PAUSED.value:
        return False
    return not row.get("retry_after") or row["retry_after"] <= now


def _overall(reports: list[AccountReport]) -> SyncCode:
    """The run's code: the first hard failure, else partial, else ok."""
    for r in reports:
        if r.code not in (SyncCode.OK, SyncCode.PARTIAL):
            return r.code
    return SyncCode.PARTIAL if any(r.code is SyncCode.PARTIAL for r in reports) else SyncCode.OK


def sync(cfg: Any, *, trigger: str, account_id: Optional[int] = None, defer_model: bool = False,
         store: Any = None, transport_factory: Optional[TransportFactory] = None,
         backend: Any = None, now: Clock = None) -> SyncReport:
    """One sync of every eligible mailbox (MS §5.1). `backend` defaults to the
    configured one (`backends.build`); `transport_factory(account_row, password)`
    to `imapread.ImapTransport`. Never raises for a mailbox problem: each
    account's code is in the report and on its row."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    ms = cfg.mail_status
    if not ms.enabled:
        return SyncReport(None, SyncCode.DISABLED)
    clock = _clock(now)
    st, owned = _open_store(cfg, store)
    try:
        run_id = st.mail_run_begin(trigger, os.getpid(), clock(),
                                   float(ms.sync_timeout_s) + 60)
        if run_id is None:
            log.info("mail sync: another sync holds the lease")
            return SyncReport(None, SyncCode.BUSY)
        report = SyncReport(run_id, SyncCode.OK)
        try:
            try:
                rules = mrules.load_rules(cfg.mail_rules_path)
            except mrules.RulesError as exc:
                log.error("mail sync: the rules file is invalid (entry %s)",
                          getattr(exc, "entry_id", "?"))
                report.code = SyncCode.RULES_INVALID
                return report
            if backend is None and ms.model and not defer_model:
                from . import backends
                backend = backends.build(cfg.budget)
            flow = _Sync(cfg, st, rules, trigger=trigger, defer_model=defer_model,
                         backend=backend, factory=transport_factory or _default_transport,
                         now=clock, run_id=run_id)
            for row in st.mail_accounts(enabled_only=True):
                if not _eligible(row, trigger, clock(), account_id):
                    continue
                rep = flow.account(row)
                flow.settle(row, rep)
                report.accounts.append(rep)
                if rep.code is SyncCode.DB_BUSY:
                    log.info("mail sync: the database is busy; the next sync retries")
                    break
                c = rep.counts
                log.info("mail sync account %s: %s scanned, %s read, %s updated, %s to review, "
                         "%s unmatched, %s waiting for the model, %s failed (%s)", rep.account_id,
                         c["scanned"], c["bodies"], c["applied"], c["suggested"], c["unmatched"],
                         c["pending_model"], c.get("errors", 0), rep.code.value)
            report.code = _overall(report.accounts)
            st.mail_supersede(clock())          # FL-7: reads no longer do this
            st.mail_purge(clock())
        except Exception as exc:                    # noqa: BLE001 - the run row must close
            import sqlite3
            if isinstance(exc, sqlite3.OperationalError):
                report.code = SyncCode.DB_BUSY
            else:
                _log_crash("mail sync", exc)
                report.code = SyncCode.INTERNAL
        finally:
            state = ("ok" if report.code is SyncCode.OK else
                     "partial" if report.code is SyncCode.PARTIAL else "failed")
            keys = list(dict.fromkeys(k for a in report.accounts for k in a.counts))
            totals = {k: sum(a.counts.get(k, 0) for a in report.accounts) for k in keys}
            try:
                st.mail_run_end(run_id, state, report.code.value, totals, clock())
            except Exception as exc:                # noqa: BLE001
                log.error("mail sync: could not close run %s (%s)", run_id, type(exc).__name__)
        return report
    finally:
        if owned:
            st.close()


# ---------------------------------------------------------------- connect (MS §4)

def _test_login(factory: TransportFactory, address: str, password: Secret) -> Optional[SyncCode]:
    """Open and close a read-only session; the failure code, or None."""
    t = factory({"host": GMAIL_HOST, "port": GMAIL_PORT, "address": address}, password)
    try:
        t.open()
    except MailFailure as exc:
        return exc.code
    except Exception as exc:                        # noqa: BLE001
        _log_crash("mail login test", exc)
        return SyncCode.INTERNAL
    finally:
        try:
            t.close()
        except Exception:                           # noqa: BLE001
            pass
    return None


def connect(cfg: Any, *, address: Optional[str] = None, password: Optional[Secret] = None,
            use_application: bool = False, consent_version: str, store: Any = None,
            transport_factory: Optional[TransportFactory] = None,
            now: Clock = None) -> tuple[str, Optional[int]]:
    """Connect a mailbox (F-50a, F-50b): test the login, then store the password
    (vault) and the account row with the consent. Nothing is stored on a
    failure. Returns `(result, account_id)`: result is "ok", "exists" or a
    `SyncCode` value. Raises ValueError for an unusable address, password or
    consent version (the CLI and web check those first)."""
    if consent_version != CONSENT_VERSION:
        raise ValueError("the consent version is not the current one")
    clock = _clock(now)
    factory = transport_factory or _default_transport
    st, owned = _open_store(cfg, store)
    try:
        box, backup = _apply_boxes(cfg, st)
        apply_users = {u.strip().lower() for u in (box.username, backup) if u}
        if use_application:
            if (box.host or "").strip().lower() != GMAIL_HOST or not box.username:
                return SyncCode.NOT_SET_UP.value, None
            addr = box.username.strip().lower()
            try:
                password = vault.get(vault.imap_service(box.host), box.username)
            except vault.VaultError:
                return SyncCode.VAULT_ERROR.value, None
            if password is None:
                return SyncCode.NOT_SET_UP.value, None
        else:
            addr = (address or "").strip().lower()
            if not re.fullmatch(ADDRESS_PATTERN, addr):
                raise ValueError("not an email address")
            if not isinstance(password, Secret):
                raise ValueError("the password must be a Secret")
            password = Secret("".join(password.reveal().split()))   # Gmail shows groups of 4
            if not password.reveal():
                raise ValueError("no password")
        if any(a["address"] == addr for a in st.mail_accounts()):
            return "exists", None
        failed = _test_login(factory, addr, password)
        if failed is not None:
            log.info("mail connect: login test failed (%s)", failed.value)
            return failed.value, None
        service = vault.imap_service(GMAIL_HOST)
        if not use_application:
            try:
                vault.put(service, addr, password)
            except vault.VaultError:
                return SyncCode.VAULT_ERROR.value, None
        stamp = clock()
        try:
            account_id = st.mail_account_add(
                addr, host=GMAIL_HOST, port=GMAIL_PORT, vault_service=service,
                shared_with_apply=use_application or addr in apply_users,
                consent_version=consent_version, first_sync_from=first_sync_from(cfg, st, stamp),
                now=stamp)
        except ValueError:
            return "exists", None
        log.info("mail connect: account %s added", account_id)
        return "ok", account_id
    finally:
        if owned:
            st.close()


def set_password(cfg: Any, account_id: int, password: Secret, *, store: Any = None,
                 transport_factory: Optional[TransportFactory] = None,
                 now: Clock = None) -> SyncCode:
    """Change a mailbox's app password (MS §4): test the login, store it, and
    clear a pause. Raises ValueError for an unknown account or an empty password."""
    clock = _clock(now)
    st, owned = _open_store(cfg, store)
    try:
        row = st.mail_account(int(account_id))
        if row is None:
            raise ValueError("no such mailbox")
        if not isinstance(password, Secret):
            raise ValueError("the password must be a Secret")
        password = Secret("".join(password.reveal().split()))
        if not password.reveal():
            raise ValueError("no password")
        failed = _test_login(transport_factory or _default_transport, row["address"], password)
        if failed is not None:
            log.info("mail set-password account %s: login test failed (%s)", row["id"],
                     failed.value)
            return failed
        try:
            vault.put(row["vault_service"], row["address"], password)
        except vault.VaultError:
            return SyncCode.VAULT_ERROR
        st.mail_account_set(int(row["id"]), state=AccountState.OK.value, state_code=None,
                            fail_count=0, retry_after=None, updated_at=clock())
        log.info("mail set-password account %s: stored", row["id"])
        return SyncCode.OK
    finally:
        if owned:
            st.close()


def summary_line(rep: AccountReport) -> str:
    """The CLI's line per account (MS §10.3): ids and counts only."""
    c = rep.counts
    return (f"account {rep.account_id}: {c['scanned']} scanned, {c['bodies']} read, "
            f"{c['applied']} updated, {c['suggested']} to review, {c['unmatched']} unmatched "
            f"({rep.code.value})")


__all__ = ["sync", "connect", "set_password", "candidates", "own_addresses",
           "first_sync_from", "summary_line", "TRIGGERS", "OWNER_TRIGGERS"]
