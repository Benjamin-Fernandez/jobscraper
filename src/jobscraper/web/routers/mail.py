"""`/api/mail` - application status from email (F-50; mail_status_design Â§11.1).

The routes read and write the store, the vault (a local Credential Manager
read, no network) and the `MailSyncRunner` on `app.state.mail`. They never speak
IMAP: connecting and syncing happen in child processes (MS Â§4, Â§10), so `web/`
imports neither `imapread` nor the orchestrator (MS Â§2.2 rule 4).

The password routes parse the JSON body themselves. No pydantic model ever
holds the app password, so a validation error can't echo it back (FastAPI's 422
puts the `input` in the response), and it is wrapped in `Secret` the moment it
is read. Every error here is `{code, detail}` with fixed text, never the input.
Writes are covered by `CrossSiteWriteGuard` like every other `/api` write.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Path, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from jobscraper import vault
from jobscraper.apply.contracts import Secret
from jobscraper.mailstatus.contracts import (ADDRESS_PATTERN, CONSENT_TEXT, CONSENT_VERSION,
                                             GMAIL_HOST, REASON_TEXTS, SYNC_TEXTS, Reason,
                                             SyncCode)
from jobscraper.web.deps import open_store
from jobscraper.web.mailsync import MailBusy, gmail_url

router = APIRouter(tags=["mail"])

def _id() -> Any:
    """A row id in the path (a fresh Path per route: FastAPI must not share one)."""
    return Path(..., ge=1, le=2**53)

BAD_INPUT = "Enter your Gmail address and app password, and tick the box."
EXISTS = "This mailbox is already connected."
CHANGED = "This application changed after the email. Set the status by hand if you still want this."
NOT_LATEST = "Can't undo: the status changed after this email. Set it by hand."
NOT_OPEN = "This suggestion is already closed."
NOT_FOUND = "Not found."
NO_MAILBOX = "Switch a mailbox on first, then check again."
MAX_BODY = 4096                      # bytes; an address, a 16-char password and a version


def _problem(status: int, code: str, detail: Optional[str] = None) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status)


def _sync_text(code: Any) -> Optional[str]:
    try:
        return SYNC_TEXTS.get(SyncCode(str(code)))
    except ValueError:
        return SYNC_TEXTS.get(SyncCode.INTERNAL)


async def _json_body(request: Request) -> Optional[dict[str, Any]]:
    """The body as a dict, or None for anything else (too big, not JSON, not an
    object). Never raises, never echoes."""
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return None
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _password(body: dict[str, Any]) -> Optional[Secret]:
    """The app password as a `Secret`, spaces removed (Gmail shows it in groups
    of 4); None when missing, not text or empty."""
    v = body.get("app_password")
    if not isinstance(v, str):
        return None
    pw = Secret("".join(v.split()))
    return pw if pw.reveal() else None


def _runner(request: Request) -> Any:
    return request.app.state.mail


# ---------------------------------------------------------------- views

def _mailboxes(cfg: Any, store: Any) -> tuple[Any, Any]:
    """The effective `apply.mail` and `apply.mail_backup` (settings over config)."""
    ac = cfg.apply.with_settings(store.get_setting)
    backup = ac.mail_backup
    backup_user = store.get_setting("apply.mail_backup.username") or backup.username
    return ac.mail, (backup.host, backup_user)


def _application_mailbox(cfg: Any, store: Any, accounts: list[dict[str, Any]]) -> Optional[dict]:
    """F-50b: offered when apply.mail is a Gmail box with a username; `ready`
    when the vault holds its entry (a local read)."""
    box, _ = _mailboxes(cfg, store)
    user = (box.username or "").strip()
    if (box.host or "").strip().lower() != GMAIL_HOST or not user:
        return None
    try:
        ready = vault.get(vault.imap_service(box.host), user) is not None
    except vault.VaultError:
        ready = False
    connected = any(a["address"] == user.lower() for a in accounts)
    return {"address": user, "ready": ready, "connected": connected}


def _counts(text: Any) -> dict[str, int]:
    try:
        v = json.loads(text) if text else {}
    except ValueError:
        return {}
    return {str(k): int(n) for k, n in v.items()} if isinstance(v, dict) else {}


def account_view(row: dict[str, Any]) -> dict[str, Any]:
    """One `mail_accounts` row as the card shows it (MS Â§11.1)."""
    code = row.get("state_code")
    notes = [n for n in str(row.get("notes") or "").split(",") if n]
    return {
        "id": row["id"], "address": row["address"], "enabled": bool(row["enabled"]),
        "shared_with_apply": bool(row["shared_with_apply"]), "state": row["state"],
        "code": code, "message": _sync_text(code) if code else None,
        "notes": [{"code": n, "message": _sync_text(n)} for n in notes],
        "last_sync_at": row.get("last_sync_at"), "last_ok_at": row.get("last_ok_at"),
        "first_sync_from": row.get("first_sync_from"),
        "counts": _counts(row.get("last_counts_json")),
        # MS Â§4 consent record: a version other than CONSENT_VERSION is skipped
        # by the sync until the owner ticks the box again.
        "consent_current": row.get("consent_version") == CONSENT_VERSION,
    }


@router.get("/mail")
def get_mail(request: Request) -> dict[str, Any]:
    cfg = request.app.state.cfg
    ms = cfg.mail_status
    with open_store(request) as store:
        rows = store.mail_accounts()
        app_box = _application_mailbox(cfg, store, rows)
        last = store.mail_last_run()
        open_n = len(store.mail_suggestions())
    status = _runner(request).status()
    return {
        "enabled": ms.enabled, "interval_min": ms.interval_min,
        "consent": {"version": CONSENT_VERSION, "text": CONSENT_TEXT},
        "application_mailbox": app_box,
        "accounts": [account_view(r) for r in rows],
        "sync": {**status, "last": ({"state": last["state"], "code": last["code"],
                                     "finished_at": last["finished_at"]} if last else None)},
        "open_suggestions": open_n,
    }


# ---------------------------------------------------------------- accounts

def _child_answer(result: dict[str, Any]) -> JSONResponse:
    code = str(result.get("result") or "internal")
    if code == "ok":
        return JSONResponse({"ok": True, "account_id": result.get("account_id")})
    if code == "exists":
        return _problem(409, "exists", EXISTS)
    return _problem(400, code, _sync_text(code))


@router.post("/mail/accounts")
async def add_account(request: Request) -> JSONResponse:
    """Connect another Gmail (F-50a): the child tests the login first and stores
    nothing when it fails. `{address, app_password, consent_version}`."""
    body = await _json_body(request)
    if body is None:
        return _problem(400, "bad_input", BAD_INPUT)
    address, pw = body.get("address"), _password(body)
    if (not isinstance(address, str) or not re.fullmatch(ADDRESS_PATTERN, address.strip())
            or body.get("consent_version") != CONSENT_VERSION or pw is None):
        return _problem(400, "bad_input", BAD_INPUT)
    address = address.strip().lower()
    with open_store(request) as store:
        if any(a["address"] == address for a in store.mail_accounts()):
            return _problem(409, "exists", EXISTS)
    result = await run_in_threadpool(_runner(request).connect, address, pw, CONSENT_VERSION)
    return _child_answer(result)


@router.post("/mail/accounts/application")
async def add_application_account(request: Request) -> JSONResponse:
    """"Use this mailbox" (F-50b): reuses the apply.mail vault entry."""
    body = await _json_body(request)
    if body is None or body.get("consent_version") != CONSENT_VERSION:
        return _problem(400, "bad_input", BAD_INPUT)
    result = await run_in_threadpool(_runner(request).use_application, CONSENT_VERSION)
    return _child_answer(result)


@router.put("/mail/accounts/{account_id}/password")
async def set_account_password(request: Request, account_id: int = _id()) -> JSONResponse:
    """Change the app password: the child tests the login, then stores it."""
    body = await _json_body(request)
    pw = _password(body) if body is not None else None
    if pw is None:
        return _problem(400, "bad_input", BAD_INPUT)
    with open_store(request) as store:
        if store.mail_account(account_id) is None:
            return _problem(404, "not_found", NOT_FOUND)
    result = await run_in_threadpool(_runner(request).set_password, account_id, pw)
    return _child_answer(result)


@router.patch("/mail/accounts/{account_id}")
async def switch_account(request: Request, account_id: int = _id()) -> JSONResponse:
    """The owner's switch (MS Â§4): a store write only; the cursor is kept."""
    body = await _json_body(request)
    if body is None or not isinstance(body.get("enabled"), bool):
        return _problem(400, "bad_input", "Send enabled: true or false.")
    with open_store(request) as store:
        if store.mail_account(account_id) is None:
            return _problem(404, "not_found", NOT_FOUND)
        store.mail_account_set(account_id, enabled=body["enabled"])
        return JSONResponse(account_view(store.mail_account(account_id)))


@router.delete("/mail/accounts/{account_id}")
def delete_account(request: Request, account_id: int = _id()) -> JSONResponse:
    """Disconnect (F-50c): the vault entry goes too, unless email verification
    for auto-apply uses the same mailbox (`shared_with_apply`, or the address is
    apply.mail / apply.mail_backup)."""
    cfg = request.app.state.cfg
    with open_store(request) as store:
        row = store.mail_account(account_id)
        if row is None:
            return _problem(404, "not_found", NOT_FOUND)
        box, (_bhost, buser) = _mailboxes(cfg, store)
        used_by_apply = {u.strip().lower() for u in (box.username, buser) if u}
        keep = bool(row["shared_with_apply"]) or row["address"] in used_by_apply
        if not keep:
            try:
                vault.delete(row["vault_service"], row["address"])
            except vault.VaultError:
                return _problem(400, "vault_error", _sync_text("vault_error"))
        store.mail_account_delete(account_id)
    return JSONResponse({"ok": True, "vault_kept": keep})


# ---------------------------------------------------------------- sync

@router.post("/mail/sync")
def start_sync(request: Request) -> JSONResponse:
    """"Check now": spawns a sync now. Paused mailboxes are tried once too
    (MS Â§5.1: the manual trigger)."""
    cfg = request.app.state.cfg
    if not cfg.mail_status.enabled:
        return _problem(400, "disabled", _sync_text("disabled"))
    with open_store(request) as store:
        if not store.mail_accounts(enabled_only=True):
            return _problem(400, "no_mailbox", NO_MAILBOX)
    try:
        _runner(request).trigger("manual")
    except MailBusy:
        return _problem(409, "busy", _sync_text("busy"))
    return JSONResponse({"started": True}, status_code=202)


# ---------------------------------------------------------------- suggestions and undo

def _reason_text(reason: Any) -> Optional[str]:
    try:
        return REASON_TEXTS.get(Reason(str(reason)))
    except ValueError:
        return None


def suggestion_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "job_id": row["job_id"], "company": row.get("company"),
        "role": row.get("role"), "status": row.get("current_status"),
        "to_status": row["to_status"], "category": row["category"], "reason": row["reason"],
        "reason_text": _reason_text(row["reason"]), "quote": row["quote"],
        "subject": row["subject"], "sender_domain": row["sender_domain"],
        "received_at": row["received_at"],
        "candidates": [{"job_id": c["job_id"], "company": c.get("company"), "role": c.get("role"),
                        "status": c.get("current_status")} for c in row.get("candidates") or []],
        "gmail_url": gmail_url(row.get("account_address"), row["gm_msgid"]),
    }


@router.get("/mail/suggestions")
def list_suggestions(request: Request) -> dict[str, Any]:
    with open_store(request) as store:
        return {"suggestions": [suggestion_view(r) for r in store.mail_suggestions()]}


_ACCEPT_ERRORS = {"changed": (409, CHANGED), "not_open": (409, NOT_OPEN),
                  "not_found": (404, NOT_FOUND)}


@router.post("/mail/suggestions/{evidence_id}/accept")
async def accept_suggestion(request: Request, evidence_id: int = _id()) -> JSONResponse:
    """`{job_id?}`; the store re-checks the status and the direction (F-50n)."""
    body = await _json_body(request)
    if body is None or not isinstance(body.get("job_id", None), (str, type(None))):
        return _problem(400, "bad_input", "Send the job_id of the application, or nothing.")
    ms = request.app.state.cfg.mail_status
    with open_store(request) as store:
        ok, code = store.mail_accept(evidence_id, body.get("job_id"),
                                     ranks=dict(ms.ranks), terminal=ms.terminal)
        if not ok:
            status, text = _ACCEPT_ERRORS.get(code, (409, CHANGED))
            return _problem(status, code, text)
        status = _current_status(store, evidence_id)
    return JSONResponse({"ok": True, "status": status})


def _current_status(store: Any, evidence_id: int) -> Optional[str]:
    """The application's status after an accept or an undo."""
    ev = store.mail_evidence(evidence_id)
    return ev["current_status"] if ev else None


@router.post("/mail/suggestions/{evidence_id}/dismiss")
def dismiss_suggestion(request: Request, evidence_id: int = _id()) -> JSONResponse:
    with open_store(request) as store:
        ok, code = store.mail_dismiss(evidence_id)
    if not ok:
        status, text = _ACCEPT_ERRORS.get(code, (409, NOT_OPEN))
        return _problem(status, code, text)
    return JSONResponse({"ok": True})


@router.post("/mail/evidence/{evidence_id}/undo")
def undo_change(request: Request, evidence_id: int = _id()) -> JSONResponse:
    """F-50m: only while the email's event is the application's latest."""
    with open_store(request) as store:
        ok, code = store.mail_undo(evidence_id)
        if not ok:
            if code == "not_latest":
                return _problem(409, code, NOT_LATEST)
            status, text = _ACCEPT_ERRORS.get(code, (409, NOT_OPEN))
            return _problem(status, code, text)
        status = _current_status(store, evidence_id)
    return JSONResponse({"ok": True, "status": status})
