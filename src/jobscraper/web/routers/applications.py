"""`/api/applications` - the user's own record: what they applied to, and when.

This is the only data the web app writes, and it goes to the store alone. The
shortlist is engine-owned and regenerated freely, so it must never hold user
state (D-5).

`POST` is idempotent by construction: the store appends an `app_events` row only
when the status actually changes, so re-sending "applied" (a double click, a
retried request) cannot put a duplicate into the history (M6-T2).
"""
from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from jobscraper import applicant
from jobscraper.apply.contracts import (CONTENT_FAILURE_MARKERS, CONTENT_FAILURE_TEXT,
                                        NO_FIELD_FACT_TITLES, OWNER_FACT_NO_FIELD_TEXT,
                                        QUEUE_REFUSAL_TEXTS, REASON_TEXTS, STATE_TEXTS,
                                        TERMINAL_STATES, AnswerStatus, AttemptState, ReasonCode,
                                        RememberRefusal, SentFieldStatus, basis_text)
from jobscraper.config import Config
from jobscraper.web import remember as remembering
from jobscraper.web.data import load_shortlist
from jobscraper.web.deps import get_config, open_store
from jobscraper.web.mailsync import gmail_url
from jobscraper.web.routers.applicant import profile_or_empty, ready_to_retry_jobs

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
        assumed = store.assumed_counts([a['id'] for a in latest.values()])   # Q-121, one query
        notes = store.entries_notes([a['id'] for a in latest.values()])      # Q-121, one query
        unanswered = store.not_answered_counts([a['id'] for a in latest.values()])   # Q-128, one query
        paths = store.attempt_question_paths([a['id'] for a in latest.values()])  # A1-W, one query
        # Q-127 B.2e: the jobs whose stopped attempt can be tried again now (never one that was sent).
        ready = ready_to_retry_jobs(store, profile_or_empty(cfg))
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
        row["last_attempt"] = (attempt_view(last, assumed=assumed.get(last['id'], 0),
                                            entries_note=notes.get(last['id']),
                                            owner_fact_path=paths.get(last['id']),
                                            ready_to_retry=row["job_id"] in ready,
                                            not_answered=unanswered.get(last['id'], 0))
                               if last else None)
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
_NEEDS_INPUT = {ReasonCode.UNANSWERABLE_REQUIRED.value, ReasonCode.PROFILE_INCOMPLETE.value,
                ReasonCode.OWNER_FACT_MISSING.value,       # Q-121: a fact only the owner has
                ReasonCode.CONSENT_REFUSED.value}          # A1 section 17.6: a consent the profile refuses

# The reasons whose captured question names a Profile field (`owner_fact_path`): the fact,
# or the consent (`consents.<key>`) the owner would change to go on.
_PROFILE_PATH_REASONS = {ReasonCode.OWNER_FACT_MISSING.value, ReasonCode.CONSENT_REFUSED.value}


def content_failure(reason: Any, detail: Any) -> bool:
    """An `unanswerable_required` whose `reason_detail` STARTS with a content-failure marker
    (contract v8 `CONTENT_FAILURE_MARKERS`, A1 section 17.6, review C8): the local AI could
    not answer the form without guessing. Nothing was captured, so the view says
    `CONTENT_FAILURE_TEXT` with kind `stopped`, never "Needs your answers". A marker later in
    the text does not count (the flow's `is_content_failure` reads the start too)."""
    if reason != ReasonCode.UNANSWERABLE_REQUIRED.value:
        return False
    text = str(detail or "").lstrip().lower()
    return any(text.startswith(m) for m in CONTENT_FAILURE_MARKERS)


def assumed_text(n: int) -> str:
    """"3 answers assumed" (the Applications pill's second half, Q-121 section 6.2), or ""."""
    return f"{n} answer{'s' if n != 1 else ''} assumed" if n > 0 else ""


TRIAL_TEXT = "Trial: filled, not sent"       # llm_first_fill_design section 12 (rev H3)


def attempt_view(row: dict[str, Any], assumed: int = 0,
                 entries_note: Optional[str] = None,
                 owner_fact_path: Optional[str] = None,
                 ready_to_retry: bool = False, not_answered: int = 0) -> dict[str, Any]:
    """One apply_attempts row as the SPA sees it (Q-76 N11).

    `kind` is what the pill shows; `text`/`hint` are the owner-facing copy from
    the contract. It leaves out `job_log`, `end_url`, `tenant_host` and
    `resume_sha256`, so the payload carries no path or URL. An old row with an
    unknown reason never raises: it reads as `stopped` with no text.

    Q-121 (additive): `assumed` is how many of its answers JobScraper had to assume
    (`store.assumed_counts`; the caller passes it so a list stays one query) and
    `assumed_text` its words ("3 answers assumed", "" for none). Also additive:
    `entries_note` (e.g. "1 of 2 education entries added"; the caller passes
    `store.entries_notes`, None = nothing to say); `trial` / `trial_text` (an attempt that ran
    as a first-use trial; the row's `trial` column, schema v8) and `owner_fact_path` (the
    Profile path of the fact an `owner_fact_missing` attempt lacked, or of the consent a
    `consent_refused` attempt was refused; the caller passes `store.attempt_question_paths`,
    else the row's own `owner_fact_path` is read; None for every other reason).

    A1 (section 17.6): `consent_refused` is `needs_input` with the contract's text, the
    detail filled ("This form needs you to agree to keeping your details on file for future
    roles, and your profile says no. Nothing was sent."). A content failure
    (`content_failure`) is kind `stopped` with `CONTENT_FAILURE_TEXT`: nothing was captured,
    so there is nothing to answer. `trial` is true for any attempt that ran as a trial;
    `trial_text` ("Trial: filled, not sent") only when it reached the review page
    (kind `dry_run`), since a trial that stopped earlier was not filled.

    Q-127 (additive): `ready_to_retry` (the caller passes `ready_to_retry_jobs`; True only
    for a stopped attempt whose missing details are now filled or whose questions are all
    answered, never for a job that was sent) and `no_field`: an `owner_fact_missing` stop for a
    fact the profile has no field for (`NO_FIELD_FACT_TITLES`, B.2d) is kind `stopped` with the
    contract's `OWNER_FACT_NO_FIELD_TEXT` (its hint is `OWNER_FACT_NO_FIELD_HINT`), since there
    is nothing to add in Your details.

    Q-128 (additive): `not_answered` is how many of the attempt's audit rows "What was filled"
    marks "Not answered" (`store.not_answered_counts`; the caller passes it so a list stays one
    query). The Applications chip of a strict stop reads "Stopped: {n} questions had no answer"
    from it without the panel being opened.
    """
    state = str(row.get("state") or "")
    reason = row.get("reason_code")
    trial = bool(row.get("trial"))
    text = hint = ""
    no_field = False
    try:
        st = AttemptState(state)
    except ValueError:
        st = None
    if st is AttemptState.FAILED:
        kind = ("needs_input" if reason in _NEEDS_INPUT
                else "cancelled" if reason == ReasonCode.CANCELLED.value else "stopped")
        try:
            copy = REASON_TEXTS[ReasonCode(str(reason))]
            if content_failure(reason, row.get("reason_detail")):
                kind, copy = "stopped", CONTENT_FAILURE_TEXT
            elif (reason == ReasonCode.OWNER_FACT_MISSING.value
                  and str(row.get("reason_detail") or "").strip() in NO_FIELD_FACT_TITLES):
                kind, copy, no_field = "stopped", OWNER_FACT_NO_FIELD_TEXT, True
            text = copy.text.format(detail=str(row.get("reason_detail") or "").strip()
                                    if no_field else row.get("reason_detail") or "")
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
            "resume_source": row.get("resume_source"),
            "assumed": int(assumed or 0), "assumed_text": assumed_text(int(assumed or 0)),
            "entries_note": entries_note or row.get("entries_note") or None,
            "trial": trial, "trial_text": TRIAL_TEXT if trial and kind == "dry_run" else "",
            "owner_fact_path": (owner_fact_path or row.get("owner_fact_path") or None)
            if reason in _PROFILE_PATH_REASONS and st is AttemptState.FAILED
            and not no_field else None,
            "ready_to_retry": bool(ready_to_retry) and st is AttemptState.FAILED and not no_field,
            "no_field": no_field, "not_answered": max(0, int(not_answered or 0))}


def _queued_view(last: Optional[dict[str, Any]]) -> dict[str, Any]:
    """`last_attempt` for a role waiting in the auto-apply queue (Q-120 §3.5): kind
    `queued`, the same keys as `attempt_view`. No attempt row exists for a waiting
    role (I2), so the attempt fields are empty."""
    return {"id": None, "mode": None, "state": "queued", "kind": "queued",
            "reason_code": None, "text": "", "hint": "", "queued_at": None,
            "finished_at": None, "submit_clicked_at": None,
            "resume_source": (last or {}).get("resume_source"),
            "assumed": 0, "assumed_text": "", "entries_note": None, "trial": False,
            "trial_text": "", "owner_fact_path": None, "ready_to_retry": False,
            "no_field": False, "not_answered": 0}


@router.get("/applications/{job_id}/attempts")
def list_attempts(request: Request, job_id: str = JOB_ID) -> list[dict[str, Any]]:
    """Every auto-apply attempt for a job, newest first. `[]` when there is none:
    an application need not have any, so this is never a 404."""
    with open_store(request) as store:
        rows = store.attempts_for_job(job_id)
        assumed = store.assumed_counts([r['id'] for r in rows])
        notes = store.entries_notes([r['id'] for r in rows])
        paths = store.attempt_question_paths([r['id'] for r in rows])
        unanswered = store.not_answered_counts([r['id'] for r in rows])
    return [attempt_view(r, assumed=assumed.get(r['id'], 0), entries_note=notes.get(r['id']),
                         owner_fact_path=paths.get(r['id']), not_answered=unanswered.get(r['id'], 0))
            for r in reversed(rows)]


# ----------------------------------------------------------------------------------------------
# What was sent (Q-127, design B.2b / B.5): one attempt's answers, and "Use a different answer
# next time". No path, URL, log line, vault value or employer question wording beyond the field's
# own label ever leaves here; the answers are the owner's own, shown to the owner.
# ----------------------------------------------------------------------------------------------

_SENT_STATES = (AttemptState.SUBMITTED.value, AttemptState.SUBMITTED_UNCONFIRMED.value)
_NOT_ANSWERED = (AnswerStatus.UNKNOWN.value, AnswerStatus.UNGROUNDED.value)
# Audit rows the page leaves out: a hidden field, one that was never shown or used, and an
# optional field left blank. Everything else is a field the form asked.
_NOT_LISTED = (AnswerStatus.SKIPPED.value, AnswerStatus.BLANK_OPTIONAL.value)
_JSON_TYPES = ("multi_choice", "checkbox", "file")        # the field types stored as JSON (the store)
_REASON_MAX = 300


def _decoded(raw: Any, ftype: str) -> Any:
    """An audit value as the store wrote it: text as written; a list, a tick or a file record as
    JSON. A file shows its name only, never the folder it came from."""
    if raw is None:
        return None
    if ftype in _JSON_TYPES and isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return raw
    if isinstance(raw, dict):
        name = str(raw.get("file") or raw.get("name") or "").replace("\\", "/").rsplit("/", 1)[-1]
        return name or None
    return raw


def _sent_text(raw: Any, ftype: str) -> str:
    value = _decoded(raw, ftype)
    if isinstance(value, str) and ftype == "checkbox":
        value = {"true": True, "false": False}.get(value.strip().lower(), value)
    return remembering.shown(value)


def _corrected_text(raw: Any) -> str:
    """`corrected_json` in words: what the owner chose to use next time ("" when none)."""
    if raw is None or raw == "":
        return ""
    try:
        return remembering.shown(json.loads(raw))
    except (ValueError, TypeError):
        return remembering.shown(raw)


def _reason(row: dict[str, Any]) -> str:
    """The model's one-line reason for an assumed answer; "" when none or redacted (D-202)."""
    why = " ".join(str(row.get("evidence") or "").split())
    return "" if not why or "redacted" in why.lower() else why[:_REASON_MAX]


def _form_label(source: str) -> str:
    """The Profile form's wording of the field a `profile:<path>` answer came from."""
    head, _, path = (source or "").partition(":")
    if head != "profile" or not path:
        return ""
    item, sub = applicant.form_item(path)
    chosen = sub or item
    return chosen.label if chosen is not None else ""


def sent_field(row: dict[str, Any], attempt_sent: bool, captured: Optional[dict[str, Any]],
               extra: Any) -> dict[str, Any]:
    """One `ANSWERS_FIELD_KEYS` item for an audit row."""
    ftype = str(row.get("field_type") or "")
    status = str(row.get("status") or "")
    assumed = bool(row.get("assumed"))
    reason = _reason(row) if assumed else ""
    if status in _NOT_ANSWERED:
        shown_status = SentFieldStatus.NOT_ANSWERED
    elif attempt_sent and status in (AnswerStatus.FILLED.value, AnswerStatus.PREFILLED.value):
        shown_status = SentFieldStatus.SENT
    else:
        shown_status = SentFieldStatus.NOT_SENT
    refusal = remembering.remember_refusal(row, captured=captured, extra=extra)
    return {
        "id": int(row["id"]), "step": str(row.get("step") or ""),
        "label": str(row.get("label") or ""), "type": ftype,
        "required": bool(row.get("required")),
        "value_text": "" if status in _NOT_ANSWERED else _sent_text(row.get("value_json"), ftype),
        "basis_text": basis_text(str(row.get("source") or ""), status=status, assumed=assumed,
                                 reason=reason, form_label=_form_label(str(row.get("source") or ""))),
        "assumed": assumed, "reason_text": reason, "status": shown_status.value,
        "remembered_text": _corrected_text(row.get("corrected_json")),
        "can_remember": refusal is None,
        "refusal": refusal.value if refusal else "",
        "options": remembering.option_labels(row, captured),
    }


@router.get("/applications/{job_id}/attempts/{attempt_id}/answers")
def attempt_answers(request: Request, attempt_id: int, job_id: str = JOB_ID,
                    cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """What was sent (or filled) for one attempt: `{attempt, employer, fields}` as the contract's
    `ANSWERS_ATTEMPT_KEYS` / `ANSWERS_FIELD_KEYS` name them. Reads only. 404 when the attempt
    is not this application's. `can_remember` / `refusal` say whether "Use a different answer
    next time" is offered for a field and, when not, why (`RememberRefusal`)."""
    with open_store(request) as store:
        att = store.attempt(attempt_id)
        if att is None or str(att.get("job_id")) != job_id:
            raise HTTPException(status_code=404, detail="no such attempt for this application")
        rows = store.answers(attempt_id)
        employer = remembering.employer_of(store, job_id)
        extra = profile_or_empty(cfg).get("extra")
        sent = str(att.get("state")) in _SENT_STATES
        fields = []
        for row in rows:
            if str(row.get("field_type") or "") == "hidden" or row.get("status") in _NOT_LISTED:
                continue
            # A field that follows the details is refused whatever was captured for it.
            protected = remembering.remember_refusal(row) is RememberRefusal.FOLLOWS_YOUR_DETAILS
            captured = (None if protected
                        else store.attempt_field_question(attempt_id, row["field_key"]))
            fields.append(sent_field(row, sent, captured, extra if isinstance(extra, dict) else {}))
    view = attempt_view(att)
    return {"attempt": {"id": att["id"], "kind": view["kind"], "state": view["state"],
                        "finished_at": att.get("finished_at"), "trial": bool(att.get("trial")),
                        "entries_note": view["entries_note"]},
            "employer": employer, "fields": fields}


class RememberBody(BaseModel):
    """Body of `POST .../answers/{answer_id}/remember`. `value` (yes_no true/false, text,
    number, date) or `picks` (the option labels as offered, for a choice) and the profile's
    `etag` as `GET /api/applicant` last gave it. `only_employer` (default true) saves the answer
    for this employer only."""
    value: Any = None
    picks: Optional[list[str]] = None
    only_employer: bool = True
    etag: str = ""


@router.post("/applications/{job_id}/attempts/{attempt_id}/answers/{answer_id}/remember")
def remember_answer(body: RememberBody, request: Request, attempt_id: int, answer_id: int,
                    job_id: str = JOB_ID, cfg: Config = Depends(get_config)) -> Any:
    """"Use a different answer next time": save the owner's answer as an `extra` entry for this
    question's exact wording (never another entry's key), mark the attempt's captured questions
    answered, and report whether the application can be tried again. 404 not this attempt's
    answer; 409 `shared_answer` or a stale / unreadable profile; 422 `follows_your_details`,
    `too_general` or `invalid` (nothing written on any). Starts no application."""
    with open_store(request) as store:
        try:
            return remembering.remember(cfg, store, job_id=job_id, attempt_id=attempt_id,
                                        answer_id=answer_id, value=body.value, picks=body.picks,
                                        only_employer=body.only_employer, etag=body.etag)
        except remembering.RememberError as exc:
            out: dict[str, Any] = {"detail": exc.code}
            if exc.text:
                out["text"] = exc.text
            if exc.errors:
                out["errors"] = [{"path": e.path, "message": e.message} for e in exc.errors]
            return JSONResponse(out, status_code=exc.status)


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

    The check and the delete are one write transaction (review F5): BEGIN
    IMMEDIATE takes SQLite's write lock before the check, so the worker's
    `queue_take` (itself BEGIN IMMEDIATE) either committed before it - and the
    role reads as in flight - or waits until the role and its queue row are gone,
    and then finds nothing to take.
    """
    with open_store(request) as store:
        begin = getattr(store, "begin_immediate", None)
        live_of = getattr(store, "live_attempt", None)
        rollback = getattr(store, "rollback", None)
        if callable(begin):
            begin()
        try:
            if callable(live_of) and live_of(job_id) is not None:
                if callable(rollback):
                    rollback()                              # release the write lock
                copy = QUEUE_REFUSAL_TEXTS["in_progress"]
                return JSONResponse({"detail": "in_progress", "text": copy.text,
                                     "hint": copy.hint}, status_code=409)
            deleted = store.delete_application(job_id)      # commits the transaction
        except BaseException:
            if callable(rollback):
                rollback()
            raise
    if not deleted:
        raise HTTPException(status_code=404, detail=f"no application for {job_id!r}")
    return {"job_id": job_id, "deleted": True}
