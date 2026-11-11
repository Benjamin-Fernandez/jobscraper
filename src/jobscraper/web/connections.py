"""The Connected accounts hub's data: everything JobScraper signs in to, as one
state vocabulary (Q-100, q100_ui_design §2.3, §3).

`compose` is pure: it reads the store and the facts it is handed and returns the
`GET /api/connections` body (schema v1, §3.1). It never speaks IMAP, never starts a
sync and never waits on the model: the mail runner's view, the job slot's view and
the model snapshot arrive as plain values, and the vault as a `vault_has` callable
that answers a boolean. So tests drive every mapping row with fakes, and the route
(`web/routers/connections.py`) stays a thin adapter. No fastapi import here.

ADR-0009 (D-191): no value read from the vault, nor anything derived from one,
leaves this module; `has_password` is a boolean. A failing source gives its item
`neutral · check_failed` with fixed copy, never exception text (a `VaultError`
names the service and host, §3.4). Edge facts carry no path: it holds the Windows
user name.

`ModelHealth` is the cached, non-blocking model check behind the model item
(§3.3): one lock, at most one daemon probe thread, a fresh backend per probe.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from jobscraper import backends, vault
from jobscraper.mailstatus.contracts import CONSENT_VERSION, SYNC_TEXTS, SyncCode
from jobscraper.store import TIME_FMT, shift

log = logging.getLogger(__name__)

VERSION = 1
NO_ACCOUNT_NEEDED = ["greenhouse", "lever", "ashby"]     # they apply as a guest
CHECK_FAILED_TEXT = "Couldn't check this just now. Try again in a moment."   # §4.4
RECENT_DAYS = 1                       # §2.3: "within 24 h"

# Worst first: the employer summary takes the worst row's state (§2.3).
_SEVERITY = {"attention": 0, "neutral": 1, "checking": 2, "connected": 3,
             "paused": 4, "not_set_up": 5}

VaultHas = Callable[[str, str], bool]


# ---------------------------------------------------------------- helpers

def _sync_text(code: Any) -> Optional[str]:
    """SYNC_TEXTS copy for a stored state_code: the same lookup as
    `routers/mail.py` `_sync_text`, kept local so web/ routers don't import each
    other (rule 3); a parity test pins the two together."""
    try:
        return SYNC_TEXTS.get(SyncCode(str(code)))
    except ValueError:
        return SYNC_TEXTS.get(SyncCode.INTERNAL)


def _counts(text: Any) -> dict[str, int]:
    try:
        v = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(v, dict):
        return {}
    out: dict[str, int] = {}
    for k, n in v.items():
        try:
            out[str(k)] = int(n)
        except (TypeError, ValueError):
            continue
    return out


def _item(id_: str, kind: str, state: str, code: str, *, optional: bool = False,
          stored_in: Optional[str] = None, message: Optional[str] = None,
          checked_at: Optional[str] = None, next_check_at: Optional[str] = None,
          last_ok_at: Optional[str] = None, retry_after: Optional[str] = None,
          facts: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {"id": id_, "kind": kind, "state": state, "code": code, "message": message,
            "optional": optional, "stored_in": stored_in, "checked_at": checked_at,
            "next_check_at": next_check_at, "last_ok_at": last_ok_at,
            "retry_after": retry_after, "facts": facts or {}}


def _failed(id_: str, kind: str, source: str, exc: BaseException, **kw: Any) -> dict[str, Any]:
    """`neutral · check_failed`. The log gets the exception's type only: a
    VaultError's text names the vault service."""
    log.warning("connections: %s could not be read (%s)", source, type(exc).__name__)
    return _item(id_, kind, "neutral", "check_failed", message=CHECK_FAILED_TEXT, **kw)


def _safe(fn: Callable[[], Any], default: Any, source: str) -> Any:
    try:
        return fn()
    except Exception as exc:
        log.warning("connections: %s could not be read (%s)", source, type(exc).__name__)
        return default


def lockfile_busy(profile_dir: str) -> bool:
    """Best effort (§2.3, minor 4; open question Q4): Chromium holds
    `<profile>/lockfile` open without read sharing while the profile is in use on
    Windows, so a lockfile that exists but can't be opened means an apply browser
    (maybe a CLI one) has it. Anything else says "free"."""
    path = os.path.join(profile_dir, "lockfile")
    if not os.path.exists(path):
        return False
    try:
        with open(path, "rb"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Gmail

def _gmail_item(row: dict[str, Any], mail_enabled: bool, runner: dict[str, Any],
                recent: str) -> dict[str, Any]:
    """One `mail_accounts` row (§2.3, Gmail rows, in order)."""
    state_code = row.get("state_code")
    st = str(row.get("state") or "ok")
    last_ok = row.get("last_ok_at")
    if not row.get("enabled"):
        state, code = "paused", "switched_off"
    elif row.get("consent_version") != CONSENT_VERSION:
        state, code = "attention", "consent"
    elif st == "paused":
        # The pausing codes per §2.3; D-195 (5): any other code on a paused row
        # also waits on the owner (only the owner resumes a paused mailbox).
        state, code = "attention", str(state_code or SyncCode.NOT_SET_UP.value)
    elif st in ("error", "backoff"):
        if last_ok and str(last_ok) >= recent:
            state, code = "connected", "retrying"
        else:
            state, code = "attention", str(state_code or SyncCode.INTERNAL.value)
    elif not mail_enabled:
        # D-195 (4): config switches email updates off for every mailbox.
        state, code = "paused", "switched_off"
    elif runner.get("timer_running"):
        state, code = "connected", "ok"
    else:
        state, code = "connected", "timer_off"
    return _item(
        f"gmail:{row['id']}", "gmail", state, code, optional=True,
        stored_in="credential_manager",
        # The same message as `routers/mail.py` account_view(row) (parity pin).
        message=_sync_text(state_code) if state_code else None,
        checked_at=row.get("last_sync_at"),
        next_check_at=((runner.get("status") or {}).get("next_at")
                       if row.get("enabled") else None),
        last_ok_at=last_ok, retry_after=row.get("retry_after"),
        facts={"address": row.get("address"),
               "enabled": bool(row.get("enabled")),
               "shared_with_apply": bool(row.get("shared_with_apply")),
               "counts": _counts(row.get("last_counts_json")),
               "consent_current": row.get("consent_version") == CONSENT_VERSION})


def _gmail_items(rows: Optional[list[dict[str, Any]]], error: Optional[BaseException],
                 mail_enabled: bool, runner: dict[str, Any], recent: str) -> list[dict]:
    facts_none = {"address": None, "enabled": False, "shared_with_apply": False,
                  "counts": {}, "consent_current": False}
    if error is not None:
        return [_failed("gmail", "gmail", "mail accounts", error, optional=True,
                        facts=facts_none)]
    if not rows:
        return [_item("gmail", "gmail", "not_set_up", "none", optional=True,
                      facts=facts_none)]
    return [_gmail_item(r, mail_enabled, runner, recent) for r in rows]


# ---------------------------------------------------------------- application mailbox

def _mailbox_item(id_: str, host: str, port: Any, user: str, backup_separate: bool,
                  vault_has: VaultHas, optional: bool) -> dict[str, Any]:
    """The D-72 mailbox apply reads codes from (§2.3): connected when host and
    username are set and the vault has the entry; the vault is asked for a yes
    or no only. The backup mailbox is always optional."""
    facts = {"host": host, "port": port, "username": user,
             "has_password": False, "backup_separate": backup_separate}
    if not user or not host:
        return _item(id_, "apply_mailbox", "not_set_up", "none", optional=True,
                     facts=facts)
    try:
        has = bool(vault_has(vault.imap_service(host), user))
    except Exception as exc:
        return _failed(id_, "apply_mailbox", "application mailbox vault entry", exc,
                       optional=optional, stored_in="credential_manager", facts=facts)
    facts["has_password"] = has
    return _item(id_, "apply_mailbox", "connected" if has else "attention",
                 "ok" if has else "no_password", optional=optional,
                 stored_in="credential_manager", facts=facts)


def _mailbox_items(cfg: Any, store: Any, vault_has: VaultHas) -> list[dict[str, Any]]:
    try:
        ac = cfg.apply.with_settings(store.get_setting)
        box = ac.mail
        host = (box.host or "").strip()
        user = (box.username or "").strip()
        bhost = (ac.mail_backup.host or "").strip() or host     # "" = the same server
        buser = (store.get_setting("apply.mail_backup.username")
                 or ac.mail_backup.username or "").strip()
    except Exception as exc:
        return [_failed("apply-mailbox", "apply_mailbox", "application mailbox settings",
                        exc, optional=True,
                        facts={"host": None, "port": None, "username": None,
                               "has_password": False, "backup_separate": False})]
    # The backup mailbox (contact.backup_email, D-70 §11.5) is always listed;
    # unset, it is an Optional not_set_up item (T0 fixture).
    separate = bool(buser) and (buser.lower() != user.lower()
                                or bhost.lower() != host.lower())
    return [_mailbox_item("apply-mailbox", host, box.port, user, separate, vault_has,
                          optional=False),
            _mailbox_item("apply-mailbox:backup", bhost, ac.mail_backup.port, buser,
                          separate, vault_has, optional=True)]


# ---------------------------------------------------------------- employer accounts

def _account_row(row: dict[str, Any], vault_has: VaultHas) -> dict[str, Any]:
    """One `ats_accounts` row (§2.3). `vault_service` is used to ask the vault
    and never sent."""
    status = str(row.get("status") or "")
    has = False
    failed = False
    try:
        has = bool(vault_has(str(row.get("vault_service") or ""),
                             str(row.get("email") or "")))
    except Exception as exc:
        log.warning("connections: employer account %s vault entry could not be read (%s)",
                    row.get("id"), type(exc).__name__)
        failed = True
    if status == "signin_failed":
        state, code = "attention", "signin_failed"
    elif status == "exists_no_password":
        state, code = "attention", "exists_no_password"
    elif status in ("created", "verified"):
        if failed:
            state, code = "neutral", "check_failed"
        elif not has:
            state, code = "attention", "password_missing"
        else:
            # D-195 (2): a failed last sign-in (last_signin_ok = 0) whose status
            # didn't move to signin_failed stays connected; the row's
            # `last_signin_ok: false` says so, and it raises no badge.
            state, code = "connected", "verified" if status == "verified" else "ok"
    else:                                          # creating / unknown / anything new
        state, code = "neutral", "unconfirmed"
    ok = row.get("last_signin_ok")
    return {"id": row.get("id"), "ats": row.get("ats"), "tenant_host": row.get("tenant_host"),
            "email": row.get("email"), "status": status, "state": state, "code": code,
            "has_password": bool(has), "created_at": row.get("created_at"),
            "verified_at": row.get("verified_at"), "last_signin_at": row.get("last_signin_at"),
            "last_signin_ok": None if ok is None else bool(ok),
            "exported_to_edge_at": row.get("exported_to_edge_at"),
            "created_by_attempt": row.get("created_by_attempt")}


def _employer(store: Any, vault_has: VaultHas) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        rows = store.accounts()
    except Exception as exc:
        return (_failed("employer-accounts", "employer_accounts", "employer accounts", exc,
                        optional=True, stored_in="credential_manager",
                        facts={"total": 0, "attention": 0}), [])
    accounts = [_account_row(r, vault_has) for r in rows]
    n_att = sum(1 for a in accounts if a["state"] == "attention")
    facts = {"total": len(accounts), "attention": n_att}
    if not accounts:
        return (_item("employer-accounts", "employer_accounts", "not_set_up", "none",
                      optional=True, stored_in="credential_manager", facts=facts), [])
    worst = min(accounts, key=lambda a: _SEVERITY.get(a["state"], 9))
    return (_item("employer-accounts", "employer_accounts", worst["state"], worst["code"],
                  optional=True, stored_in="credential_manager",
                  message=CHECK_FAILED_TEXT if worst["code"] == "check_failed" else None,
                  facts=facts), accounts)


# ---------------------------------------------------------------- Edge

def _edge_item(cfg: Any, current: dict[str, Any], attempts: Optional[dict[str, Any]],
               lockfile: Callable[[str], bool],
               dir_exists: Callable[[str], bool]) -> dict[str, Any]:
    """The apply browser's profile (§2.3). The path is read, never sent."""
    acfg = cfg.apply
    sync = bool(acfg.edge_sync)
    starts = [str(r.get("started_at")) for r in (attempts or {}).values()
              if r.get("started_at")]
    last_used = max(starts) if starts else None
    try:
        profile = os.path.expandvars(acfg.profile_dir)
        exists = bool(dir_exists(profile))
    except Exception as exc:
        return _failed("edge", "edge", "apply browser profile", exc, stored_in="edge_profile",
                       facts={"exists": False, "in_use": False, "sync": sync,
                              "last_used_at": last_used})
    in_use = False
    if exists:
        in_use = current.get("state") == "running" and current.get("kind") == "apply"
        if not in_use:
            in_use = bool(_safe(lambda: lockfile(profile), False, "apply browser lockfile"))
    facts = {"exists": exists, "in_use": in_use, "sync": sync, "last_used_at": last_used}
    if not exists:
        return _item("edge", "edge", "not_set_up", "none", stored_in="edge_profile",
                     facts=facts)
    return _item("edge", "edge", "connected", "in_use" if in_use else "ok",
                 stored_in="edge_profile", facts=facts)


# ---------------------------------------------------------------- model

def need_now(current: dict[str, Any], in_flight: Optional[list],
             attempts: Optional[dict[str, Any]], mail_rows: Optional[list[dict[str, Any]]],
             recent: str) -> bool:
    """§2.3 `need_now`: something is waiting on the model right now."""
    # (a) a running background job of any kind but the mailbox test
    if current.get("state") == "running" and current.get("kind") not in (None, "mailtest"):
        return True
    # (b) an apply attempt in flight
    if in_flight:
        return True
    # (c) an attempt ended model_unavailable in the last 24 h
    for r in (attempts or {}).values():
        if (r.get("reason_code") == "model_unavailable" and r.get("finished_at")
                and str(r["finished_at"]) >= recent):
            return True
    # (d) a mailbox has messages waiting for the model
    for r in mail_rows or []:
        if _counts(r.get("last_counts_json")).get("pending_model", 0) > 0:
            return True
    return False


def _model_item(cfg: Any, snapshot: Optional[dict[str, Any]], need: bool) -> dict[str, Any]:
    """`snapshot` is `ModelHealth.snapshot()`: the last probe, or None before the
    first answer. "off" and "misconfigured" are read from config here too, so a
    cached probe never hides a config change."""
    budget = cfg.budget or {}
    snapshot = snapshot or {}
    configured = backends.configured_code(budget)
    probe: Optional[dict[str, Any]] = (
        {"ok": False, "code": configured} if configured
        else (snapshot if "ok" in snapshot else None))
    local = backends.is_local_config(budget)
    facts = {"backend": snapshot.get("backend") or str(budget.get("backend") or "ollama"),
             "model": snapshot.get("model") or str(budget.get("ollama_model") or ""),
             "local": local, "need_now": need}
    # Only a remote Ollama (D-107) is not "this PC"; off/misconfigured run nothing elsewhere.
    remote = not configured and not local
    kw = {"stored_in": None if remote else "this_pc", "facts": facts,
          "checked_at": snapshot.get("checked_at"),
          "next_check_at": snapshot.get("next_check_at"),
          "last_ok_at": snapshot.get("last_ok_at")}
    if probe is None:
        return _item("model", "model", "checking", "probing", **kw)
    code = str(probe.get("code") or "")
    if probe.get("ok"):
        return _item("model", "model", "connected", "ok", **kw)
    if code == "off":
        return _item("model", "model", "paused", "ai_off", **kw)
    if code == "misconfigured":
        return _item("model", "model", "attention", "misconfigured", **kw)
    code = code if code in ("unreachable", "model_missing") else "unreachable"
    return _item("model", "model", "attention" if need else "neutral", code, **kw)


# ---------------------------------------------------------------- compose

def compose(cfg: Any, store: Any, mail_runner_view: dict[str, Any],
            job_view: dict[str, Any], model_snapshot: Optional[dict[str, Any]],
            vault_has: VaultHas, lockfile_busy: Callable[[str], bool] = lockfile_busy,
            now: Optional[str] = None,
            profile_dir_exists: Callable[[str], bool] = os.path.isdir) -> dict[str, Any]:
    """The `GET /api/connections` body (schema v1, §3.1).

    Input shapes (as in the T0 fixture `tests/fixtures/connections_rows.json`):
    - `mail_runner_view`: `{timer_running, status: MailSyncRunner.status()}`;
    - `job_view`: `{current: JobManager.current(tail=0) or None,
      attempts_in_flight: store.attempts_in_flight(),
      last_attempts: store.last_attempts()}`;
    - `model_snapshot`: `ModelHealth.snapshot()`, None before the first probe;
    - `vault_has(service, user)`: is there a vault entry (a boolean only);
    - `lockfile_busy(dir)`, `profile_dir_exists(dir)`: the Edge profile checks;
    - `now`: UTC in `store.TIME_FMT`.
    Store reads here: mail_accounts, settings, accounts. Each failing source
    degrades only its own item."""
    now = now or datetime.now(timezone.utc).strftime(TIME_FMT)
    recent = shift(now, days=-RECENT_DAYS)
    runner = mail_runner_view or {}
    jv = job_view or {}
    job = jv.get("current") or {}
    attempts = jv.get("last_attempts") or {}
    in_flight = jv.get("attempts_in_flight") or []

    mail_rows: Optional[list[dict[str, Any]]] = None
    mail_error: Optional[BaseException] = None
    try:
        mail_rows = list(store.mail_accounts())
    except Exception as exc:
        mail_error = exc
    try:
        mail_enabled = bool(cfg.mail_status.enabled)
    except Exception:
        mail_enabled = True

    employer_item, employer_rows = _employer(store, vault_has)
    items = (_gmail_items(mail_rows, mail_error, mail_enabled, runner, recent)
             + _mailbox_items(cfg, store, vault_has)
             + [_edge_item(cfg, job, attempts, lockfile_busy, profile_dir_exists),
                _model_item(cfg, model_snapshot,
                            need_now(job, in_flight, attempts, mail_rows, recent)),
                employer_item])
    for item in items:
        # Never configured: the chip reads "Optional", and nothing is stored yet
        # (the Edge profile's place is known before it exists). T0 sample.
        if item["state"] == "not_set_up":
            item["optional"] = True
            if item["kind"] != "edge":
                item["stored_in"] = None
    return {"version": VERSION, "checked_at": now,
            "attention": sum(1 for i in items if i["state"] == "attention"),
            "items": items, "employer_accounts": employer_rows,
            "no_account_needed": list(NO_ACCOUNT_NEEDED)}


# ---------------------------------------------------------------- model health

class ModelHealth:
    """The model item's cached probe (§3.3), on `app.state.model_health`.

    `snapshot()` returns at once. Inside one lock it decides whether the cached
    probe is stale (60 s after a success, 15 s after a failure) and, if so, marks
    `in_flight` before starting one daemon thread, so two requests never start
    two probes. The thread builds a fresh backend through `backends.probe` (one
    model-list request: no model is loaded, no GPU used), which closes its HTTP
    client, and clears `in_flight` in `finally`. "off" and "misconfigured" come
    from config alone and are never probed."""

    OK_TTL_S = 60.0
    FAIL_TTL_S = 15.0

    def __init__(self, budget: Callable[[], dict[str, Any]],
                 probe: Callable[[dict[str, Any]], Any] = backends.probe,
                 clock: Callable[[], float] = time.time,
                 ok_ttl_s: float = OK_TTL_S, fail_ttl_s: float = FAIL_TTL_S):
        self._budget = budget
        self._probe = probe
        self.clock = clock
        self.ok_ttl_s = float(ok_ttl_s)
        self.fail_ttl_s = float(fail_ttl_s)
        self._lock = threading.Lock()
        self._result: Optional[dict[str, Any]] = None
        self._at: Optional[float] = None        # clock() of the last probe answer
        self._last_ok: Optional[float] = None
        self._in_flight = False
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def _stamp(t: Optional[float]) -> Optional[str]:
        return None if t is None else datetime.fromtimestamp(t, timezone.utc).strftime(TIME_FMT)

    @property
    def in_flight(self) -> bool:
        with self._lock:
            return self._in_flight

    def _view(self) -> Optional[dict[str, Any]]:
        if self._result is None or self._at is None:
            return None
        ttl = self.ok_ttl_s if self._result.get("ok") else self.fail_ttl_s
        return {**self._result,
                "checked_at": self._stamp(self._at),
                "last_ok_at": self._stamp(self._last_ok),
                "next_check_at": self._stamp(self._at + ttl),
                "in_flight": self._in_flight}

    def snapshot(self, force: bool = False) -> Optional[dict[str, Any]]:
        """The cached result now, flat (`{ok, code, backend, model, local,
        checked_at, last_ok_at, next_check_at, in_flight}`), or None before the
        first answer. Starts a background probe when the cache is stale (or on
        `force`, the hub's "Check again") and none is running."""
        budget = self._budget() or {}
        code = backends.configured_code(budget)
        if code:
            return {"ok": False, "code": code,
                    "backend": "off" if code == "off" else "unknown", "model": "",
                    "local": False, "checked_at": self._stamp(self.clock()),
                    "last_ok_at": None, "next_check_at": None, "in_flight": False}
        start = False
        with self._lock:
            if not self._in_flight:
                stale = force or self._at is None or self._result is None
                if not stale:
                    ttl = self.ok_ttl_s if self._result.get("ok") else self.fail_ttl_s
                    stale = self.clock() - self._at >= ttl
                if stale:
                    self._in_flight = start = True
            view = self._view()
        if start:
            try:
                t = threading.Thread(target=self._run, args=(budget,),
                                     name="model-health-probe", daemon=True)
                t.start()
                self._thread = t
            except Exception:
                with self._lock:
                    self._in_flight = False
                raise
        return view

    def _run(self, budget: dict[str, Any]) -> None:
        result: dict[str, Any] = {"ok": False, "code": "unreachable",
                                  "backend": str(budget.get("backend") or "ollama"),
                                  "model": str(budget.get("ollama_model") or ""),
                                  "local": False}
        try:
            p = self._probe(budget)
            result = {"ok": bool(p.ok), "code": str(p.code or ""), "backend": p.backend,
                      "model": p.model, "local": bool(p.local)}
        except Exception as exc:
            log.warning("model health probe failed (%s)", type(exc).__name__)
        finally:
            at = self.clock()
            with self._lock:
                self._result, self._at = result, at
                if result.get("ok"):
                    self._last_ok = at
                self._in_flight = False
