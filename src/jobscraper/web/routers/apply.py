"""`/api/apply` - queue auto-apply from the Inbox, the only trigger (F-30, D-200, D-205).

Auto-apply never starts by itself: the owner clicks "Auto-apply" on a role and
the SPA posts that job id here. `GET /api/apply/status` tells the button what
to show (the effective mode, what the profile still lacks, whether a job holds
the slot, and the queue's size and pause). `POST /api/apply` runs the cheap
guards of apply_design §12.2 in the orchestrator's own order, so a refusal
reaches the owner as a plain sentence at click time instead of as a failed
attempt minutes later, then adds the role to the auto-apply queue
(apply_queue_design §3.5) and kicks the `ApplyQueueRunner`, which starts the
worker when the slot is free. A running job never refuses a click: the role
waits. The worker re-runs every guard at pick time (it is the authority); this
is only the early, friendly answer.

`/api/apply/queue` (Runs): the view (GET, no side effects, review M1), Remove,
Pause, Stop (the attempt in flight, M3), Resume (the owner's fresh click after a
restart, D-200) and Clear.

`GET/PUT /api/apply/settings` (Q-111, apply_design section 14.3) read and change the
owner's six knobs: mode, the two daily caps (0 = no limit, D-204), the browser
window, the human-check wait and the cover-letter opt-in. They live in the
settings table (`apply.<field>`) and override config.yaml at the next apply job;
no job is started and nothing else is touched.

Responses of `POST /api/apply`:
- 202 `{queued: [{job_id, position}], accepted, refused, mode, paused, started,
  disabled, job}` - at least one id was queued (`accepted` kept for older callers);
- 422 `{detail: "profile_incomplete", missing}` - nothing queued, details missing;
- 422 `{detail: "refused", refused}` - every id was refused. Never 409.

A refusal is `{job_id, reason_code, text, hint}`; the copy is the contract's
`REASON_TEXTS` or `QUEUE_REFUSAL_TEXTS`, so the Inbox and the Applications tab say
the same thing. The queue row records the effective mode at the click; the worker
never applies in a stronger mode than that (I5).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from jobscraper import applicant
from jobscraper.apply.contracts import (QUEUE_PAUSE_TEXTS, QUEUE_REFUSAL_TEXTS, REASON_TEXTS,
                                        QueuePause, ReasonCode)
from jobscraper.config import ApplyConfig
from jobscraper.store import TIME_FMT, utcnow
from jobscraper.web.applyqueue import slot_of
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.jobs import JobIdle, JobNotOurs, JobStuck
from jobscraper.web.routers.applications import attempt_view

router = APIRouter(tags=["apply"])

APPLY_MODE_KEY = "apply.mode"                 # the stored override of config apply.mode
MODES = ("auto", "dry_run")
START_MAX = 20
QUEUE_MAX = 100                               # waiting roles (`queue_full`, §3.5)
RECENT_MAX = 10                               # Runs "Recently finished"
QUEUE_JOB_ID = Path(..., pattern=r"^[A-Za-z0-9:_-]{1,80}$")
_JOB_ID = re.compile(r"[A-Za-z0-9:_-]{1,80}")       # same rule as web/jobs.py `apply`
_SG = timezone(timedelta(hours=8))                  # Asia/Singapore, no DST


class StartBody(BaseModel):
    job_ids: list[str]
    # Where the click came from (the queue row's `source`): the Inbox, or "Try
    # again" in Applications. Optional; the Questions retry has its own route.
    source: Literal["inbox", "applications"] = "inbox"

    @field_validator("job_ids")
    @classmethod
    def _ids(cls, ids: list[str]) -> list[str]:
        if not 1 <= len(ids) <= START_MAX:
            raise ValueError(f"send 1 to {START_MAX} job_ids")
        if not all(_JOB_ID.fullmatch(j) for j in ids):
            raise ValueError("job_ids are letters, digits, : _ -")
        return ids


def _mode(cfg: Any, store: Any) -> str:
    """The effective apply mode, as the Questions router and the CLI see it."""
    stored = store.get_setting(APPLY_MODE_KEY)
    if stored in MODES:
        return stored
    mode = getattr(getattr(cfg, "apply", None), "mode", "dry_run")
    return mode if mode in MODES else "dry_run"


def _missing(cfg: Any) -> list[str]:
    """What the profile still lacks. A missing or unreadable file lacks everything
    (never a 500): the empty profile is checked against the same required paths."""
    try:
        profile = applicant.load(cfg.applicant_path)
    except applicant.ApplicantError:
        profile = {}
    return applicant.missing_for_apply(profile, cfg.resume_dir)


def _day_start_utc() -> str:
    """Today's midnight in Singapore as a UTC store timestamp (the caps' day).
    Same as apply_flow.day_start_utc; web may not import the orchestrator."""
    local = datetime.now(timezone.utc).astimezone(_SG).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).strftime(TIME_FMT)


def _refusal(job_id: str, code: ReasonCode, detail: str) -> dict[str, str]:
    copy = REASON_TEXTS[code]
    return {"job_id": job_id, "reason_code": code.value,
            "text": copy.text.format(detail=detail), "hint": copy.hint}


@router.get("/apply/status")
def apply_status(request: Request, cfg: Any = Depends(get_config),
                 jobs: Any = Depends(get_jobs)) -> dict[str, Any]:
    """`mode`, `missing`, `busy` keep their meaning (`busy` = a job holds the
    slot); `queue` is additive (Q-120): `{waiting, applying, paused}`. Reads only."""
    runner = _runner(request)
    slot, _cur = slot_of(jobs)
    with open_store(request) as store:
        mode = _mode(cfg, store)
        paused = _pause_view(store, runner)
        waiting = len(store.queue_positions())
    return {"mode": mode, "missing": _missing(cfg), "busy": slot != "free",
            "queue": {"waiting": waiting, "applying": slot == "apply",
                      "paused": paused["reason"] if paused else None}}


def _settings_view(cfg: Any, store: Any) -> dict[str, Any]:
    """The six owner-editable apply settings: the effective values (settings table
    over config.yaml) and, as `defaults`, what config.yaml alone gives."""
    def six(ac: Any) -> dict[str, Any]:
        return {"mode": ac.mode, "daily_cap": ac.daily_cap,
                "per_employer_daily_cap": ac.per_employer_daily_cap,
                "headed": ac.headed, "captcha_wait_s": ac.captcha_wait_s,
                "compose_enabled": ac.compose.enabled}
    return {**six(cfg.apply.with_settings(store.get_setting)), "writable": True,
            "defaults": six(cfg.apply)}


def _whole(lo: int, hi: int, what: str, zero_note: str = "") -> tuple[Any, str]:
    return (lambda v: type(v) is int and lo <= v <= hi,
            f"{what} must be a whole number from {lo} to {hi}{zero_note}")


# field -> (is this value allowed?, the plain-words message when it is not)
_SETTING_RULES: dict[str, tuple[Any, str]] = {
    "mode": (lambda v: v in MODES,
             'Mode must be "auto" (submits applications) or "dry_run" (fills only)'),
    "daily_cap": _whole(0, 500, "Applications a day", "; 0 means no limit"),
    "per_employer_daily_cap": _whole(0, 100, "Applications per employer a day", "; 0 means no limit"),
    "headed": (lambda v: type(v) is bool, "Show the browser window must be true or false"),
    "captcha_wait_s": _whole(0, 600, "The human-check wait (seconds)", "; 0 means do not wait"),
    "compose_enabled": (lambda v: type(v) is bool, "Cover letters must be true or false"),
}
# field -> the settings-table key (`ApplyConfig.with_settings` reads these back)
_SETTING_KEYS = {k: f"apply.{k}" for k in _SETTING_RULES}
_SETTING_KEYS["compose_enabled"] = f"apply.{ApplyConfig.COMPOSE_SETTING_KEY}"


@router.get("/apply/settings")
def get_apply_settings(request: Request, cfg: Any = Depends(get_config)) -> dict[str, Any]:
    with open_store(request) as store:
        return _settings_view(cfg, store)


@router.put("/apply/settings")
def put_apply_settings(request: Request, body: Any = Body(...),
                       cfg: Any = Depends(get_config)) -> Any:
    """Store any non-empty subset of the six settings. All values are checked
    before any is written; a bad one answers 422 `{detail: "invalid", errors:
    [{field, message}]}` and changes nothing. Takes effect on the next apply job."""
    errors: list[dict[str, str]] = []
    if not isinstance(body, dict) or not body:
        errors.append({"field": "", "message": "Send at least one setting to change"})
    else:
        for field, value in body.items():
            rule = _SETTING_RULES.get(field)
            if rule is None:
                errors.append({"field": str(field), "message": f"{field} is not an apply setting"})
            elif not rule[0](value):
                errors.append({"field": field, "message": rule[1]})
    if errors:
        return JSONResponse({"detail": "invalid", "errors": errors}, status_code=422)
    with open_store(request) as store:
        for field, value in body.items():
            store.set_setting(_SETTING_KEYS[field],
                              str(value).lower() if isinstance(value, bool) else value)
        return _settings_view(cfg, store)


def _queue_refusal(job_id: str, code: str) -> dict[str, str]:
    copy = QUEUE_REFUSAL_TEXTS[code]
    return {"job_id": job_id, "reason_code": code, "text": copy.text, "hint": copy.hint}


def _runner(request: Request) -> Any:
    """The app's `ApplyQueueRunner`, or None (an app built without one: disabled)."""
    return getattr(request.app.state, "apply_queue", None)


def _enabled(runner: Any) -> bool:
    return bool(runner is not None and runner.enabled)


def _check_one(store: Any, job_id: str, mode: str, caps: Any,
               day_start: str) -> tuple[Optional[dict[str, Any]], Optional[dict[str, str]]]:
    """The enqueue checks for one id, in §3.5's order: (job, None) or (None, refusal)."""
    job = store.get_job(job_id)
    if job is None:
        return None, _queue_refusal(job_id, "not_found")
    if job_id in store.queue_positions():
        return None, _queue_refusal(job_id, "already_queued")
    if store.live_attempt(job_id) is not None:
        return None, _queue_refusal(job_id, "in_progress")
    dup = store.apply_duplicate(job_id)
    if dup:
        return None, _refusal(job_id, ReasonCode.DUPLICATE, dup)
    if mode == "auto":                    # caps (0 = no limit, D-204); dry runs never click
        total, employer = store.apply_counts(job.get("company_id"), day_start)
        if caps.daily_cap > 0 and total >= caps.daily_cap:
            return None, _refusal(job_id, ReasonCode.CAP_REACHED,
                                  f"{total} of {caps.daily_cap} today")
        if caps.per_employer_daily_cap > 0 and employer >= caps.per_employer_daily_cap:
            return None, _refusal(job_id, ReasonCode.CAP_REACHED,
                                  f"{employer} of {caps.per_employer_daily_cap} today at "
                                  f"{job.get('company') or 'this employer'}")
    if len(store.queue_positions()) >= QUEUE_MAX:
        return None, _queue_refusal(job_id, "queue_full")
    return job, None


def enqueue(request: Request, cfg: Any, job_ids: list[str], source: str) -> JSONResponse:
    """The enqueue helper of §3.5, shared by `POST /api/apply` and
    `POST /api/questions/retry`. Never a 409: a running job only means the role waits.

    Per id, in one write transaction (BEGIN IMMEDIATE, so the worker's `queue_take`
    can't slip between the checks and the write): the checks, then `queue_add` and,
    for a role with no application row, its `to_apply` row (the owner's click; the
    worker takes only `to_apply` roles), committed together (L6). Then one kick.
    The orchestrator re-runs every guard at pick time; these are the early answers."""
    missing = _missing(cfg)
    if missing:
        return JSONResponse({"detail": "profile_incomplete", "missing": missing},
                            status_code=422)
    queued: list[dict[str, Any]] = []
    refused: list[dict[str, str]] = []
    with open_store(request) as store:
        mode = _mode(cfg, store)
        caps = cfg.apply.with_settings(store.get_setting)
        day_start = _day_start_utc()
        for job_id in job_ids:
            store.begin_immediate()
            try:
                job, refusal = _check_one(store, job_id, mode, caps, day_start)
                position = None
                if job is not None:
                    position = store.queue_add(job_id, job.get("company_id"), mode, source,
                                               utcnow())
                    if position is None:          # raced: waiting or taken meanwhile (I2)
                        refusal = _queue_refusal(job_id, "already_queued")
                    elif store.application(job_id) is None:
                        store.set_application_status(       # commits the queue row too
                            job_id, "to_apply", company=job.get("company"),
                            role=job.get("title"), url=job.get("url"))
                store.commit()
            except BaseException:
                store.rollback()
                raise
            if refusal is not None:
                refused.append(refusal)
            else:
                queued.append({"job_id": job_id, "position": position})
    if not queued:
        return JSONResponse({"detail": "refused", "refused": refused}, status_code=422)
    runner = _runner(request)
    started = bool(runner.kick()) if _enabled(runner) else False
    slot, cur = slot_of(request.app.state.jobs)
    with open_store(request) as store:
        paused = _pause_view(store, runner) is not None
    return JSONResponse({
        "queued": queued, "accepted": [q["job_id"] for q in queued], "refused": refused,
        "mode": mode, "paused": paused and _enabled(runner), "started": started,
        "disabled": not _enabled(runner),
        "job": cur if slot == "apply" else None}, status_code=202)


@router.post("/apply", status_code=202)
def start_apply(body: StartBody, request: Request, cfg: Any = Depends(get_config)) -> Any:
    """Queue the clicked roles for auto-apply (D-205). 202 even while a job runs."""
    return enqueue(request, cfg, body.job_ids, body.source)


# ------------------------------------------------------------------ the queue (§3.5)


def _pause_view(store: Any, runner: Any) -> Optional[dict[str, Any]]:
    """`{reason, text, hint, since}` or None. `disabled` (H2) and a closed restart
    gate (M2: the start-up pause could not be written) are shown, never stored."""
    if not _enabled(runner):
        return _pause_copy(QueuePause.DISABLED.value, None, None)
    state = store.queue_pause_state()
    if state:
        return _pause_copy(state["reason"], state.get("detail"), state.get("since"))
    if runner.gate_closed:
        return _pause_copy(QueuePause.RESTARTED.value, None, None)
    return None


def _pause_copy(reason: str, detail: Optional[str], since: Optional[str]) -> dict[str, Any]:
    try:
        copy = QUEUE_PAUSE_TEXTS[QueuePause(reason)]
    except ValueError:                       # a reason from a newer build: plain "paused"
        copy = QUEUE_PAUSE_TEXTS[QueuePause.OWNER]
    try:
        text = copy.text.format(detail=detail or "")
    except (KeyError, IndexError):
        text = copy.text
    return {"reason": reason, "text": text, "hint": copy.hint, "since": since}


def queue_view(request: Request) -> dict[str, Any]:
    """`GET /api/apply/queue`'s body. Reads only (M1): no reaper, no kick, no write."""
    runner = _runner(request)
    slot, _cur = slot_of(request.app.state.jobs)
    with open_store(request) as store:
        paused = _pause_view(store, runner)
        live = store.live_attempt()
        waiting = store.queue_items()
        recent = store.recent_attempts(RECENT_MAX)
    now = None
    if live:
        now = {"attempt_id": live.get("id"), "job_id": live.get("job_id"),
               "company": live.get("company"), "role": live.get("role"),
               "mode": live.get("mode"), "state": live.get("state"),
               "started_at": live.get("started_at"),
               # a live row with no worker: the next worker's reaper closes it (§4.2)
               "interrupted": slot != "apply"}
    done = []
    for row in recent:
        v = attempt_view(row)
        done.append({"attempt_id": row.get("id"), "job_id": row.get("job_id"),
                     "company": row.get("company"), "role": row.get("role"),
                     "mode": row.get("mode"), "kind": v["kind"], "text": v["text"],
                     "finished_at": row.get("finished_at")})
    return {"paused": paused, "now": now, "slot": slot,
            "run_pending": bool(runner is not None and runner.pending_run is not None),
            "waiting": waiting, "recent": done}


@router.get("/apply/queue")
def get_queue(request: Request) -> dict[str, Any]:
    """Now / next / paused / recently finished (Runs). No side effects (M1)."""
    return queue_view(request)


@router.delete("/apply/queue/{job_id}", status_code=204)
def remove_from_queue(request: Request, job_id: str = QUEUE_JOB_ID) -> Response:
    """Take a waiting role out (P5). 404 `not_waiting` once it has started or left."""
    with open_store(request) as store:
        removed = store.queue_remove(job_id)
    if not removed:
        return JSONResponse({"detail": "not_waiting"}, status_code=404)
    return Response(status_code=204)


@router.post("/apply/queue/pause")
def pause_queue(request: Request) -> dict[str, Any]:
    """Pause (reason `owner`); idempotent - an existing pause keeps its reason (L3).
    The application in progress finishes first: the worker stops before its next take."""
    with open_store(request) as store:
        store.queue_pause(QueuePause.OWNER, None, utcnow())
    return queue_view(request)


class StopBody(BaseModel):
    attempt_id: int


@router.post("/apply/queue/stop")
def stop_application(body: StopBody, request: Request, jobs: Any = Depends(get_jobs)) -> Any:
    """Stop the application in flight (M3). The `cancelled` pause is committed
    first, so the worker can take nothing more; the worker is cancelled only when
    `attempt_id` is still the attempt in flight, else 409 `already_finished` (the
    queue stays paused and nothing else is cancelled)."""
    with open_store(request) as store:
        store.queue_pause(QueuePause.CANCELLED, None, utcnow())
        live = store.live_attempt()
    if not live or live.get("id") != body.attempt_id:
        return JSONResponse({"detail": "already_finished"}, status_code=409)
    try:
        jobs.cancel()
    except JobIdle:
        return JSONResponse({"detail": "already_finished"}, status_code=409)
    except JobNotOurs as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    except JobStuck as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)
    return queue_view(request)


@router.post("/apply/queue/resume")
def resume_queue(request: Request, cfg: Any = Depends(get_config)) -> Any:
    """Resume: the owner's fresh click (D-200). 409 `disabled` in a copy with the
    worker switched off (H2); 422 while the profile lacks details. A committed
    Resume opens the restart gate (M2), then the worker may start."""
    runner = _runner(request)
    if not _enabled(runner):
        return JSONResponse({"detail": "disabled"}, status_code=409)
    missing = _missing(cfg)
    if missing:
        return JSONResponse({"detail": "profile_incomplete", "missing": missing},
                            status_code=422)
    with open_store(request) as store:
        store.queue_resume(utcnow())
    runner.open_gate()
    runner.kick()
    return queue_view(request)


@router.post("/apply/queue/clear")
def clear_queue(request: Request) -> dict[str, Any]:
    """Remove every waiting role (never an attempt). They stay in Applications."""
    with open_store(request) as store:
        removed = store.queue_clear()
    return {"removed": removed, "queue": queue_view(request)}
