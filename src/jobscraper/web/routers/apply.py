"""`/api/apply` - start auto-apply from the Inbox, the only trigger (F-30, D-200).

Auto-apply never starts by itself: the owner clicks "Auto-apply" on a role and
the SPA posts that job id here. `GET /api/apply/status` tells the button what
to show (the effective mode, what the profile still lacks, whether another job
is running). `POST /api/apply` runs the cheap guards of apply_design §12.2 in
the orchestrator's own order, so a refusal reaches the owner as a plain
sentence at click time instead of as a failed attempt minutes later, then
starts an `apply` job. The orchestrator re-runs every guard (the child process
is the authority); this is only the early, friendly answer.

`GET/PUT /api/apply/settings` (Q-111, apply_design section 14.3) read and change the
owner's six knobs: mode, the two daily caps (0 = no limit, D-204), the browser
window, the human-check wait and the cover-letter opt-in. They live in the
settings table (`apply.<field>`) and override config.yaml at the next apply job;
no job is started and nothing else is touched.

Responses of `POST`:
- 202 `{job, accepted, refused, mode}` - at least one id was started;
- 422 `{detail: "profile_incomplete", missing}` - nothing started, details missing;
- 422 `{detail: "refused", refused}` - every id was refused;
- 409 `{detail: "busy"}` - another job (run, profile, apply ...) is running.

A refusal is `{job_id, reason_code, text, hint}`; the copy is the contract's
`REASON_TEXTS`, so the Inbox and the Applications tab say the same thing.
No `dry_run` flag is sent: `jobscraper apply` uses the effective mode (§14.1).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from jobscraper import applicant
from jobscraper.apply.contracts import REASON_TEXTS, ReasonCode
from jobscraper.config import ApplyConfig
from jobscraper.store import TIME_FMT
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.jobs import JobBusy

router = APIRouter(tags=["apply"])

APPLY_MODE_KEY = "apply.mode"                 # the stored override of config apply.mode
MODES = ("auto", "dry_run")
START_MAX = 20
_JOB_ID = re.compile(r"[A-Za-z0-9:_-]{1,80}")       # same rule as web/jobs.py `apply`
_SG = timezone(timedelta(hours=8))                  # Asia/Singapore, no DST


class StartBody(BaseModel):
    job_ids: list[str]

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


def _busy(jobs: Any) -> bool:
    try:
        return jobs.current(tail=0).get("state") == "running"
    except TypeError:                        # a manager whose current() takes no tail
        return jobs.current().get("state") == "running"


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
    with open_store(request) as store:
        mode = _mode(cfg, store)
    return {"mode": mode, "missing": _missing(cfg), "busy": _busy(jobs)}


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


@router.post("/apply", status_code=202)
def start_apply(body: StartBody, request: Request, cfg: Any = Depends(get_config),
                jobs: Any = Depends(get_jobs)) -> Any:
    """Check the ids (§12.2, the orchestrator's order) and start one `apply` job."""
    missing = _missing(cfg)                                        # (1) profile
    if missing:
        return JSONResponse({"detail": "profile_incomplete", "missing": missing},
                            status_code=422)
    accepted: list[str] = []
    refused: list[dict[str, str]] = []
    with open_store(request) as store:
        mode = _mode(cfg, store)
        caps = cfg.apply.with_settings(store.get_setting)
        day_start = _day_start_utc()
        for job_id in body.job_ids:                                # (2) job, duplicate
            job = store.get_job(job_id)
            if job is None:
                refused.append({"job_id": job_id, "reason_code": "not_found",
                                "text": "This role is no longer in the database", "hint": ""})
                continue
            if job_id in accepted:
                refused.append(_refusal(job_id, ReasonCode.DUPLICATE,
                                        "the same job twice in this batch"))
                continue
            dup = store.apply_duplicate(job_id)
            if dup:
                refused.append(_refusal(job_id, ReasonCode.DUPLICATE, dup))
                continue
            if mode == "auto":                                     # (3) caps (0 = no limit, D-204); dry runs never click
                total, employer = store.apply_counts(job.get("company_id"), day_start)
                if caps.daily_cap > 0 and total >= caps.daily_cap:
                    refused.append(_refusal(job_id, ReasonCode.CAP_REACHED,
                                            f"{total} of {caps.daily_cap} today"))
                    continue
                if caps.per_employer_daily_cap > 0 and employer >= caps.per_employer_daily_cap:
                    refused.append(_refusal(
                        job_id, ReasonCode.CAP_REACHED,
                        f"{employer} of {caps.per_employer_daily_cap} today at "
                        f"{job.get('company') or 'this employer'}"))
                    continue
            accepted.append(job_id)
    if _busy(jobs):                                                # (4) one job at a time
        return JSONResponse({"detail": "busy"}, status_code=409)
    if not accepted:
        return JSONResponse({"detail": "refused", "refused": refused}, status_code=422)
    try:
        job_view = jobs.start("apply", {"job_ids": accepted})
    except JobBusy:
        return JSONResponse({"detail": "busy"}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    return {"job": job_view, "accepted": accepted, "refused": refused, "mode": mode}
