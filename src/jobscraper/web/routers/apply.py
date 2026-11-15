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
no job is started and nothing else is touched. Q-121 W1 adds two (llm_first_fill_design
section 7.2): `fill_policy` ("always" = the local AI answers every field, "strict" = it
stops and asks) and `always_trial_runs` (0..20: the first N applications are filled but
not sent), and, read-only, what is in force: `fill_policy_effective`,
`fill_policy_inactive` (why "always" is not active, plain words) and the trial's count.
D-223 release lock: `always_available` (read-only, from config.yaml `apply.always_available`,
default false) is in the read payload; while false "always" is never in force and a save
of `fill_policy: "always"` answers 422 with nothing stored.

Responses of `POST /api/apply`:
- 202 `{queued: [{job_id, position}], accepted, refused, mode, paused, started,
  disabled, lifted, job}` - at least one id was queued (`accepted` kept for older
  callers); `lifted` is the model pause this click cleared (Q-126 §4.4) or null;
- 422 `{detail: "profile_incomplete", missing}` - nothing queued, details missing;
- 422 `{detail: "refused", refused}` - every id was refused. Never 409.

A refusal is `{job_id, reason_code, text, hint}`; the copy is the contract's
`REASON_TEXTS` or `QUEUE_REFUSAL_TEXTS`, so the Inbox and the Applications tab say
the same thing. The queue row records the effective mode at the click; the worker
never applies in a stronger mode than that (I5).
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from jobscraper import applicant, backends
from jobscraper.apply.contracts import (EXTRA_EMPLOYER_FIELD, MODEL_CLICK_RESUME,
                                        MODEL_PAUSE_VALUES, QUEUE_PAUSE_TEXTS,
                                        QUEUE_REFUSAL_TEXTS, REASON_TEXTS, REMEMBER_SCOPE_TEXTS,
                                        QueuePause, ReasonCode, RememberScope)
from jobscraper.config import ApplyConfig
from jobscraper.store import TIME_FMT, utcnow
from jobscraper.web.applyqueue import fill_detail, slot_of
from jobscraper.web import remember as remembering
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.jobs import JobIdle, JobNotOurs, JobStuck
from jobscraper.web.routers.applicant import (PROFILE_WRITE_LOCK, details_needed, invalid,
                                              load_for_write, needed_by, profile_or_empty,
                                              waiting_roles)
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


def _needed_by_item(by_path: dict[str, int]) -> dict[str, int]:
    """`needed_by` with each form item once: the first path of the item, the larger count
    (a role waiting on `pay.expected_salary.amount` and one on `pay.expected_salary` need the
    same field, so the item is needed by the larger of the two)."""
    key_of = {p: applicant.form_item_key(p) for p in by_path}
    first = {}
    for p, k in key_of.items():
        first.setdefault(k, p)
    out: dict[str, int] = {}
    for p, n in by_path.items():
        keep = first[key_of[p]]
        out[keep] = max(out.get(keep, 0), n)
    return out


@router.get("/apply/status")
def apply_status(request: Request, cfg: Any = Depends(get_config),
                 jobs: Any = Depends(get_jobs)) -> dict[str, Any]:
    """`mode`, `missing`, `busy` keep their meaning (`busy` = a job holds the
    slot); `queue` is additive (Q-120): `{waiting, applying, paused}`; so is `fill`
    (Q-121): `{fill_policy_effective, fill_policy_inactive, always_trial_runs,
    always_trial_left}`. Reads only.

    Q-127 (additive): `details_needed` is what the Profile badge counts, `missing` then the
    path of every waiting application that is still empty (de-duplicated, in that order), and
    `details_needed_by` is `{path: applications waiting}` for the paths a waiting application
    needs. Paths and counts only: never an employer's question wording."""
    runner = _runner(request)
    slot, _cur = slot_of(jobs)
    profile = profile_or_empty(cfg)
    with open_store(request) as store:
        mode = _mode(cfg, store)
        paused = _pause_view(store, runner)
        waiting = len(store.queue_positions())
        fill = fill_state(cfg, store)
        waiting_on = waiting_roles(store, profile)
    missing = _missing(cfg)
    return {"mode": mode, "missing": missing, "busy": slot != "free",
            "details_needed": applicant.dedupe_by_item(details_needed(missing, profile, waiting_on)),
            "details_needed_by": _needed_by_item(needed_by(profile, waiting_on)),
            "queue": {"waiting": waiting, "applying": slot == "apply",
                      "paused": paused["reason"] if paused else None},
            # Q-121 (additive): how forms are answered, as it will run, and the trial's state
            # (the Inbox chip: "Trial: the next 3 are filled, not sent").
            "fill": {k: fill[k] for k in ("fill_policy_effective", "fill_policy_inactive",
                                          "always_trial_runs", "always_trial_left")}}


FILL_POLICIES = ("always", "strict")
TRIAL_MAX = 20
# Why a configured "always" is not in force (design section 7.2, K2): plain words for Settings.
# D-223: the release lock (`apply.always_available`, config file only). The same sentence is the
# 422 message when a save asks for "always" while locked.
INACTIVE_NOT_RELEASED = "Always answer isn't available yet: it is still being checked."
INACTIVE_NOT_LOCAL = "Always answer is off for now: the AI model isn't on this computer."
INACTIVE_NOT_LLM = ("Always answer is off for now: form filling by the AI model is switched "
                    "off in the configuration.")


def fill_state(cfg: Any, store: Any) -> dict[str, Any]:
    """What is in force for how forms are answered, from the settings table over
    config.yaml: the configured policy, the effective one (`always` needs `apply.fill:
    llm` and a model on this computer, as `apply_flow.effective_policy` decides at run
    time; the web may not import it, so this reads the same two facts), the plain reason
    when they differ, and the first-use trial's count."""
    ac = cfg.apply.with_settings(store.get_setting)
    effective, inactive = ac.fill_policy, None
    if ac.fill_policy == "always":
        if ac.always_available is not True:                  # D-223 release lock, checked first
            effective, inactive = "strict", INACTIVE_NOT_RELEASED
        elif ac.fill != "llm":
            effective, inactive = "strict", INACTIVE_NOT_LLM
        elif not backends.is_local_config(getattr(cfg, "budget", None) or {}):
            effective, inactive = "strict", INACTIVE_NOT_LOCAL
    used = store.always_trial_used()
    n = ac.always_trial_runs
    left = max(0, n - used)
    return {"fill_policy": ac.fill_policy, "fill_policy_effective": effective,
            "fill_policy_inactive": inactive, "always_trial_runs": n,
            "always_trial_used": used, "always_trial_left": left,
            "always_trial_text": trial_text(n, left)}


def trial_text(n: int, left: int) -> str:
    """The Settings value for the trial row: "Off", "Next 3 not sent", "Next 3 not sent
    (2 left)", "Next 3 not sent (done)"."""
    if n <= 0:
        return "Off"
    if left >= n:
        return f"Next {n} not sent"
    return f"Next {n} not sent ({left} left)" if left else f"Next {n} not sent (done)"


def _settings_view(cfg: Any, store: Any) -> dict[str, Any]:
    """The eight owner-editable apply settings: the effective values (settings table
    over config.yaml) and, as `defaults`, what config.yaml alone gives; plus the
    read-only `fill_state` fields (Q-121)."""
    def six(ac: Any) -> dict[str, Any]:
        return {"mode": ac.mode, "daily_cap": ac.daily_cap,
                "per_employer_daily_cap": ac.per_employer_daily_cap,
                "headed": ac.headed, "captcha_wait_s": ac.captcha_wait_s,
                "compose_enabled": ac.compose.enabled,
                "fill_policy": ac.fill_policy, "always_trial_runs": ac.always_trial_runs}
    state = fill_state(cfg, store)
    return {**six(cfg.apply.with_settings(store.get_setting)), "writable": True,
            "always_available": cfg.apply.always_available is True,    # D-223, read-only
            "defaults": six(cfg.apply),
            **{k: state[k] for k in ("fill_policy_effective", "fill_policy_inactive",
                                     "always_trial_used", "always_trial_left",
                                     "always_trial_text")}}


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
    "fill_policy": (lambda v: v in FILL_POLICIES,
                    'How forms are answered must be "always" (the local AI answers every field) '
                    'or "strict" (it stops and asks)'),
    "always_trial_runs": _whole(0, TRIAL_MAX, "Trial applications", "; 0 means off"),
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
    [{field, message}]}` and changes nothing. Takes effect on the next apply job.

    Q-121 (Coordinator ruling on the trial): a NEW `always_trial_runs` (different from the
    effective value before this save) starts a new trial: the used counter goes back to 0.
    Saving the value already in force changes nothing."""
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
            elif (field == "fill_policy" and value == "always"
                  and cfg.apply.always_available is not True):
                # D-223 release lock: nothing is stored while the config file hasn't released it
                errors.append({"field": field, "message": INACTIVE_NOT_RELEASED})
    if errors:
        return JSONResponse({"detail": "invalid", "errors": errors}, status_code=422)
    with open_store(request) as store:
        trial_before = cfg.apply.with_settings(store.get_setting).always_trial_runs
        for field, value in body.items():
            store.set_setting(_SETTING_KEYS[field],
                              str(value).lower() if isinstance(value, bool) else value)
        if "always_trial_runs" in body and body["always_trial_runs"] != trial_before:
            store.set_setting(store.ALWAYS_TRIAL_USED, 0)         # a new trial starts
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


def _lift_model_pause(store: Any, runner: Any) -> Optional[str]:
    """The Auto-apply click lifts a MODEL pause, and only that (Q-126 §4.4, D-217 R1).

    One store call, one compare-and-clear: a pause that is not in
    `MODEL_CLICK_RESUME` (the owner's own, cancelled, bot checks, restarted, ...) is
    left as it is, and `resumed_at` is not written (`keep_window`), so the bot-check
    streak survives. The route never waits for the model: the worker this click
    kicks runs the start-and-wait service before its first take and stores the
    precise pause again if the model still isn't ready. A runner that is off, or
    whose restart gate is still closed (D-200), never lifts anything. Returns the
    cleared reason or None."""
    if not _enabled(runner) or runner.gate_closed:
        return None
    return store.queue_resume_if({r.value for r in MODEL_CLICK_RESUME}, utcnow(),
                                 keep_window=MODEL_PAUSE_VALUES)


def enqueue(request: Request, cfg: Any, job_ids: list[str], source: str, *,
            lift_model_pause: bool = False) -> JSONResponse:
    """The enqueue helper of §3.5, shared by `POST /api/apply` and
    `POST /api/questions/retry`. Never a 409: a running job only means the role waits.
    `lift_model_pause` is True only for the owner's Inbox Auto-apply click (§4.4):
    the Questions retry path never lifts a pause.

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
    lifted: Optional[str] = None
    if lift_model_pause:                  # the rows are committed; the kick is next
        with open_store(request) as store:
            lifted = _lift_model_pause(store, runner)
    started = bool(runner.kick()) if _enabled(runner) else False
    slot, cur = slot_of(request.app.state.jobs)
    with open_store(request) as store:
        paused = _pause_view(store, runner) is not None
    return JSONResponse({
        "queued": queued, "accepted": [q["job_id"] for q in queued], "refused": refused,
        "mode": mode, "paused": paused and _enabled(runner), "started": started,
        "disabled": not _enabled(runner), "lifted": lifted,
        "job": cur if slot == "apply" else None}, status_code=202)


@router.post("/apply", status_code=202)
def start_apply(body: StartBody, request: Request, cfg: Any = Depends(get_config)) -> Any:
    """Queue the clicked roles for auto-apply (D-205). 202 even while a job runs.
    The owner's click also lifts a stored MODEL pause (Q-126 §4.4); any other
    pause stays until Resume."""
    return enqueue(request, cfg, body.job_ids, body.source, lift_model_pause=True)


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
    return {"reason": reason, "text": fill_detail(copy.text, detail),
            "hint": fill_detail(copy.hint, detail), "since": since}


def _model_view(store: Any, slot: str) -> Optional[dict[str, Any]]:
    """`{state, since}` while the worker is bringing the local model up
    ("starting" | "loading"), else None (Q-126 §4.1). Only while the apply worker
    holds the slot: a row left by a worker that died is never shown as live (the
    next worker clears it). Reads only."""
    if slot != "apply":
        return None
    view = store.queue_model_view()
    if not view or view.get("state") not in ("starting", "loading"):
        return None
    return {"state": view["state"], "since": view.get("since")}


def queue_view(request: Request) -> dict[str, Any]:
    """`GET /api/apply/queue`'s body. Reads only (M1): no reaper, no kick, no write."""
    runner = _runner(request)
    slot, _cur = slot_of(request.app.state.jobs)
    with open_store(request) as store:
        paused = _pause_view(store, runner)
        live = store.live_attempt()
        waiting = store.queue_items()
        recent = store.recent_attempts(RECENT_MAX)
        assumed = store.assumed_counts([r["id"] for r in recent])
        notes = store.entries_notes([r["id"] for r in recent])
        paths = store.attempt_question_paths([r["id"] for r in recent])   # A1-W, one query
        model = _model_view(store, slot)
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
        v = attempt_view(row, assumed=assumed.get(row.get("id"), 0),
                         entries_note=notes.get(row.get("id")),
                         owner_fact_path=paths.get(row.get("id")))
        done.append({"attempt_id": row.get("id"), "job_id": row.get("job_id"),
                     "company": row.get("company"), "role": row.get("role"),
                     "mode": row.get("mode"), "kind": v["kind"], "text": v["text"],
                     "assumed": v["assumed"], "assumed_text": v["assumed_text"],
                     "entries_note": v["entries_note"], "trial": v["trial"],
                     "trial_text": v["trial_text"], "owner_fact_path": v["owner_fact_path"],
                     "finished_at": row.get("finished_at")})
    return {"paused": paused, "now": now, "slot": slot,
            "run_pending": bool(runner is not None and runner.pending_run is not None),
            "waiting": waiting, "recent": done, "model": model}


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
    `attempt_id` is still the attempt in flight AND the job holding the slot is an
    `apply` job, else 409 `already_finished` (the queue stays paused and nothing
    else is cancelled). Review F6: after a restart the live row may be a leftover
    (`interrupted`), or a hand-run CLI `apply` may own it while a search run holds
    the slot; cancelling then would kill the search run, not the application."""
    with open_store(request) as store:
        store.queue_pause(QueuePause.CANCELLED, None, utcnow())
        live = store.live_attempt()
    if not live or live.get("id") != body.attempt_id:
        return JSONResponse({"detail": "already_finished"}, status_code=409)
    if slot_of(jobs)[0] != "apply":
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
    now = utcnow()
    with open_store(request) as store:
        # One compare-and-clear. A model pause is lifted WITHOUT `resumed_at`, so
        # the bot-check streak survives (Q-126 §4.4); any other pause is cleared and
        # stamped as before. Nothing stored: stamp anyway, as Resume always did.
        if store.queue_resume_if(None, now, keep_window=MODEL_PAUSE_VALUES) is None:
            store.queue_resume(now)
    runner.open_gate()
    runner.kick()
    return queue_view(request)


@router.post("/apply/queue/clear")
def clear_queue(request: Request) -> dict[str, Any]:
    """Remove every waiting role (never an attempt). They stay in Applications."""
    with open_store(request) as store:
        removed = store.queue_clear()
    return {"removed": removed, "queue": queue_view(request)}


# ----------------------------------------------------------------------------------------------
# Settings -> Apply -> "Answers you corrected" (Q-127, design B.2b, B.5). The saved answers that
# "Use a different answer next time" writes (and the ones the old cards saved) as `extra` entries.
# Forget removes one at the owner's click. A promoted topic (Release 2) is not listed.
# ----------------------------------------------------------------------------------------------

REMEMBERED_KEY = Path(..., pattern=r"^[a-z][a-z0-9_]{1,39}$")


def _scope_text(entry: dict[str, Any]) -> str:
    """"Every application" or "Only {employer}". An entry the old cards saved with per-employer
    overrides (`by_employer`) also says how many employers differ."""
    scoped = str(entry.get(EXTRA_EMPLOYER_FIELD) or "").strip()
    if scoped:
        return REMEMBER_SCOPE_TEXTS[RememberScope.EMPLOYER].format(employer=scoped)
    text = REMEMBER_SCOPE_TEXTS[RememberScope.EVERY]
    by = entry.get("by_employer")
    n = len(by) if isinstance(by, dict) else 0
    return f"{text}, with {n} {'employer' if n == 1 else 'employers'} answered differently" if n else text


def remembered_view(profile: dict) -> list[dict[str, Any]]:
    """The saved answers, newest written first: `{key, title, value_text, scope_text, employer,
    kind, sensitive, needs_attention}`. `needs_attention` marks an entry the resolver skips (it
    fails validation); its key and wording are the owner's own and appear only here."""
    extra = profile.get("extra")
    out = []
    for key, entry in reversed(list(extra.items()) if isinstance(extra, dict) else []):
        if not remembering.forgettable(entry):
            continue
        out.append({"key": str(key), "title": str(entry.get("title") or key),
                    "value_text": remembering.entry_value_text(entry),
                    "scope_text": _scope_text(entry),
                    "employer": str(entry.get(EXTRA_EMPLOYER_FIELD) or ""),
                    "kind": str(entry.get("kind") or ""),
                    "sensitive": entry.get("sensitive") is True,
                    "needs_attention": bool(applicant.extra_entry_errors(key, entry))})
    return out


@router.get("/apply/remembered")
def get_remembered(cfg: Any = Depends(get_config)) -> dict[str, Any]:
    """`{items, count, etag, unreadable}`: the answers saved for next time and the profile's
    etag, which Forget sends back. Reads only; nothing from the vault, no path."""
    try:
        profile, etag = applicant.load_with_etag(cfg.applicant_path)
    except applicant.ApplicantError as exc:
        return {"items": [], "count": 0, "etag": exc.etag, "unreadable": True}
    items = remembered_view(profile)
    return {"items": items, "count": len(items), "etag": etag, "unreadable": False}


@router.delete("/apply/remembered/{key}")
def forget_remembered(key: str = REMEMBERED_KEY, etag: str = "",
                      cfg: Any = Depends(get_config)) -> Any:
    """Forget one saved answer: the entry leaves `applicant.yaml` and JobScraper answers that
    question from the owner's details again. `?etag=` is the profile's, as `GET` gave it: 409
    `changed` / `unreadable` when stale, 404 when there is no such saved answer (a double click
    is harmless), 422 when the file would not validate. Nothing else is touched."""
    with PROFILE_WRITE_LOCK:
        current = load_for_write(cfg, etag)
        extra = current.get("extra")
        if not (isinstance(extra, dict) and remembering.forgettable(extra.get(key))):
            return JSONResponse({"detail": "not_found"}, status_code=404)
        profile = copy.deepcopy(current)
        del profile["extra"][key]
        try:
            applicant.save(cfg.applicant_path, profile, tolerate_unchanged_extra=current)
        except applicant.ApplicantError as exc:
            return invalid(exc.errors)
    return {"key": key, "forgotten": True, "etag": applicant.etag(cfg.applicant_path)}
