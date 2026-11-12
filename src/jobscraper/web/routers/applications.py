"""`/api/applications` - the user's own record: what they applied to, and when.

This is the only data the web app writes, and it goes to the store alone. The
shortlist is engine-owned and regenerated freely, so it must never hold user
state (D-5).

`POST` is idempotent by construction: the store appends an `app_events` row only
when the status actually changes, so re-sending "applied" (a double click, a
retried request) cannot put a duplicate into the history (M6-T2).
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from jobscraper.apply.contracts import (QUEUE_REFUSAL_TEXTS, REASON_TEXTS, STATE_TEXTS,
                                        TERMINAL_STATES, AttemptState, ReasonCode)
from jobscraper.config import Config
from jobscraper.web.data import load_shortlist
from jobscraper.web.deps import get_config, open_store
from jobscraper.web.mailsync import gmail_url

router = APIRouter(tags=["applications"])

# Shortlist ids are short hashes; anything else in the path is a mistake.
JOB_ID = Path(..., pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


class StatusChange(BaseModel):
    """Body of `POST /api/applications/{job_id}`.

    `company`, `role` and `url` are optional. When given, they are kept on the
    application row, so the record still describes the job after the posting
    has left the shortlist or the jobs table.
    """
    status: str = Field(..., min_length=1, max_length=40)
    notes: Optional[str] = Field(None, max_length=4000)
    company: Optional[str] = Field(None, max_length=200)
    role: Optional[str] = Field(None, max_length=300)
    url: Optional[str] = Field(None, max_length=2000)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: Optional[str]) -> Optional[str]:
        # The SPA renders this as a link: only a web address may be stored,
        # never javascript: or data: (C-22; the SPA's safeUrl is the other half).
        if value is not None and value != "":
            parsed = urlparse(value.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("url must be an http or https address")
        return value


@router.get("/applications")
def list_applications(request: Request,
                      cfg: Config = Depends(get_config)) -> list[dict[str, Any]]:
    """Everything with a status, newest change first, each with its timeline.

    `events` is the row's `app_events` history, oldest first - what the
    Applications tab draws (M8-T1). Where the store has no description of a job,
    the shortlist fills it in.
    """
    by_id = {str(j.get("id")): j for j in load_shortlist(cfg.shortlist_path)["jobs"]}
    with open_store(request) as store:
        rows = [dict(r) for r in store.applications()]
        for row in rows:
            row["events"] = [dict(e) for e in store.application_events(row["job_id"])]
        # F-50 (mail_status_design §11.1): an event an email made carries its
        # evidence, so the History timeline can quote it and offer Undo.
        evidence_for = getattr(store, "mail_evidence_for", None)
        evidence = evidence_for([r["job_id"] for r in rows]) if callable(evidence_for) else {}
        latest = store.last_attempts()      # one query for every row (Q-76), never N+1
        # Q-120 (apply_queue_design §3.5): where each waiting role stands in the queue.
        positions_of = getattr(store, "queue_positions", None)
        positions = positions_of() if callable(positions_of) else {}
    for row in rows:
        for event in row["events"]:
            event.setdefault("by", None)
            event["mail"] = _mail_view(evidence.get(event.get("evidence_id")))
    for row in rows:
        job = by_id.get(str(row["job_id"]), {})
        row["company"] = row.get("company") or job.get("company")
        row["role"] = row.get("role") or job.get("title")
        row["url"] = row.get("url") or job.get("url")
        row["run_no"] = job.get("run_no")
        last = latest.get(row["job_id"])
        row["last_attempt"] = attempt_view(last) if last else None
        row["attempts"] = int(last["attempts"]) if last else 0
        position = positions.get(row["job_id"])
        row["queue"] = {"position": position} if position else None
        if position:
            # Waiting for auto-apply: the pill says "Queued", not the earlier
            # attempt's outcome (that attempt stays in the role's history).
            row["last_attempt"] = _queued_view(row["last_attempt"])
        # What the detail panel shows; null once the job left the shortlist.
        row["posting"] = ({k: job.get(k) for k in _POSTING_KEYS} if job else None)
    return rows


# The shortlist fields the Applications detail needs beyond the row itself.
_POSTING_KEYS = ("reason", "matched_skills", "yoe_min", "decided_at", "closed")

# Failed attempts that wait for the owner's answer rather than ending for good.
_NEEDS_INPUT = {ReasonCode.UNANSWERABLE_REQUIRED.value, ReasonCode.PROFILE_INCOMPLETE.value}


def attempt_view(row: dict[str, Any]) -> dict[str, Any]:
    """One apply_attempts row as the SPA sees it (Q-76 N11).

    `kind` is what the pill shows; `text`/`hint` are the owner-facing copy from
    the contract. It leaves out `job_log`, `end_url`, `tenant_host` and
    `resume_sha256`, so the payload carries no path or URL. An old row with an
    unknown reason never raises: it reads as `stopped` with no text.
    """
    state = str(row.get("state") or "")
    reason = row.get("reason_code")
    text = hint = ""
    try:
        st = AttemptState(state)
    except ValueError:
        st = None
    if st is AttemptState.FAILED:
        kind = ("needs_input" if reason in _NEEDS_INPUT
                else "cancelled" if reason == ReasonCode.CANCELLED.value else "stopped")
        try:
            copy = REASON_TEXTS[ReasonCode(str(reason))]
            text = copy.text.format(detail=row.get("reason_detail") or "")
            hint = copy.hint
        except (ValueError, KeyError, IndexError):
            kind = "stopped"
    elif st is AttemptState.SUBMITTED:
        kind = "sent"
    elif st is AttemptState.SUBMITTED_UNCONFIRMED:
        kind = "unconfirmed"
    elif st is AttemptState.READY_TO_SUBMIT:
        kind = "dry_run"
    elif st is not None and st not in TERMINAL_STATES:
        kind = "running"
    else:
        kind = "stopped"
    if st in (AttemptState.SUBMITTED_UNCONFIRMED, AttemptState.READY_TO_SUBMIT):
        text, hint = STATE_TEXTS[st].text, STATE_TEXTS[st].hint
    return {"id": row.get("id"), "mode": row.get("mode"), "state": state, "kind": kind,
            "reason_code": reason, "text": text, "hint": hint,
            "queued_at": row.get("queued_at"), "finished_at": row.get("finished_at"),
            "submit_clicked_at": row.get("submit_clicked_at"),
            "resume_source": row.get("resume_source")}


def _queued_view(last: Optional[dict[str, Any]]) -> dict[str, Any]:
    """`last_attempt` for a role waiting in the auto-apply queue (Q-120 §3.5): kind
    `queued`, the same keys as `attempt_view`. No attempt row exists for a waiting
    role (I2), so the attempt fields are empty."""
    return {"id": None, "mode": None, "state": "queued", "kind": "queued",
            "reason_code": None, "text": "", "hint": "", "queued_at": None,
            "finished_at": None, "submit_clicked_at": None,
            "resume_source": (last or {}).get("resume_source")}


@router.get("/applications/{job_id}/attempts")
def list_attempts(request: Request, job_id: str = JOB_ID) -> list[dict[str, Any]]:
    """Every auto-apply attempt for a job, newest first. `[]` when there is none:
    an application need not have any, so this is never a 404."""
    with open_store(request) as store:
        rows = store.attempts_for_job(job_id)
    return [attempt_view(r) for r in reversed(rows)]


def _mail_view(ev: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The evidence behind an email-made event (MS §11.1), or None."""
    if not ev:
        return None
    return {"evidence_id": ev["id"], "kind": "auto" if ev["kind"] == "auto" else "accepted",
            "state": ev["state"], "quote": ev["quote"], "subject": ev["subject"],
            "sender_domain": ev["sender_domain"], "received_at": ev["received_at"],
            "gmail_url": gmail_url(ev.get("account_address"), ev["gm_msgid"]),
            "undoable": bool(ev.get("undoable"))}


@router.post("/applications/{job_id}")
def set_status(body: StatusChange, request: Request, job_id: str = JOB_ID,
               cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Upsert the application and append to its history on a real change."""
    allowed = cfg.application_statuses
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status {body.status!r}; expected one of {allowed}")
    with open_store(request) as store:
        appended = store.set_application_status(
            job_id, body.status, body.notes,
            company=body.company, role=body.role, url=body.url)
        application = store.application(job_id)
    return {"job_id": job_id, "status": body.status,
            "event_appended": bool(appended), "application": application}


@router.delete("/applications/{job_id}")
def untrack(request: Request, job_id: str = JOB_ID) -> Any:
    """Undo tracking: the role returns to the Inbox with no status (M13).

    Deleting what is not there is a 404, never a 500, so a double click on Undo
    is harmless.

    Auto-apply (Q-120 H3): a role waiting in the queue leaves it in the same
    transaction (the store). A role being applied to right now is refused with
    409 `in_progress` and nothing is deleted: a cancel could land after the
    Submit click, and that attempt's audit should keep its application row.
    """
    with open_store(request) as store:
        live_of = getattr(store, "live_attempt", None)
        if callable(live_of) and live_of(job_id) is not None:
            copy = QUEUE_REFUSAL_TEXTS["in_progress"]
            return JSONResponse({"detail": "in_progress", "text": copy.text,
                                 "hint": copy.hint}, status_code=409)
        deleted = store.delete_application(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"no application for {job_id!r}")
    return {"job_id": job_id, "deleted": True}
