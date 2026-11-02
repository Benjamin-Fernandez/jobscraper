"""`/api/questions` - Questions from applications (F-13, F-38; questions_design §9.2).

An attempt that stopped on a required question nobody could answer leaves the
question in the store (`questions`, `question_sightings`; employer text only).
This router lists them grouped by key, saves the owner's answer, lets the
owner put one aside, and retries the applications that no longer wait on
anything.

The answer is never stored in the database (ADR-0005). It goes into
`data/applicant.yaml`: under `extra.<key>` (resolver tier 3 reads it on every
later form), or, for a profile gap, at the profile path itself. The write goes
through `applicant.save` with the same etag guard and write lock as the
Profile form, so the form and this card never overwrite each other.

The normalised labels and option norms come from the stored rows (the capture
stage computed them), so this router imports no stage code (NF-04).

Choice answers: `picks` maps a variant (question id) to the verbatim labels the
owner chose there. The norms chosen REPLACE that variant's earlier picks and
are unioned with the other variants' picks, so "Change answer" can un-pick an
option (lane U, D-76). `seen` grows with every option of every variant answered.
"""
from __future__ import annotations

from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jobscraper import applicant
from jobscraper.config import Config
from jobscraper.store import utcnow
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.jobs import JobBusy
from jobscraper.web.routers.applicant import PROFILE_WRITE_LOCK, invalid, load_for_write

router = APIRouter(tags=["questions"])

APPLY_MODE_KEY = "apply.mode"                 # the stored override of config apply.mode
MODES = ("auto", "dry_run")
VALUE_KINDS = ("yes_no", "text", "date", "number")
CHOICE_KINDS = ("choice", "multi")
RETRY_MAX = 20


class AnswerBody(BaseModel):
    key: str
    etag: str = ""
    employer: Optional[str] = None
    value: Any = None
    picks: Optional[dict[str, list[str]]] = None


class RetryBody(BaseModel):
    job_ids: list[str]


def _mode(cfg: Config, store: Any) -> str:
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


def _ready(store: Any) -> list[dict[str, Any]]:
    return [{k: c[k] for k in ("job_id", "attempt_id", "company", "title")}
            for c in store.retry_candidates() if c["open"] == 0 and c["dismissed"] == 0]


def _current(profile: dict, group: dict) -> Optional[dict[str, Any]]:
    """What the owner answered for an answered group: `extra[key]`'s value,
    picks and overrides, or the profile value at the group's target path."""
    if group["status"] != "answered":
        return None
    if group.get("target_path"):
        return {"value": applicant.json_safe(applicant.get_path(profile, group["target_path"])),
                "picks": [], "by_employer": {}}
    entry = (profile.get("extra") or {}).get(group["key"]) if isinstance(
        profile.get("extra"), dict) else None
    if not isinstance(entry, dict):
        return None
    return applicant.json_safe({"value": entry.get("value"), "picks": entry.get("picks") or [],
                                "by_employer": entry.get("by_employer") or {}})


@router.get("/questions")
def list_questions(request: Request, status: str = "open",
                   cfg: Config = Depends(get_config), jobs: Any = Depends(get_jobs)) -> Any:
    """The question groups (open, answered or all), the applications ready to
    retry and those still waiting, the apply mode and whether a job runs."""
    if status not in ("open", "answered", "all"):
        raise HTTPException(status_code=422, detail="status must be open, answered or all")
    try:
        profile = applicant.load(cfg.applicant_path)
    except applicant.ApplicantError:
        profile = {}
    with open_store(request) as store:
        groups = store.question_groups(status)
        for g in groups:
            g["current"] = _current(profile, g)
        cands = store.retry_candidates()
        mode = _mode(cfg, store)
    return {
        "mode": mode, "groups": groups,
        "ready": [{k: c[k] for k in ("job_id", "attempt_id", "company", "title")}
                  for c in cands if c["open"] == 0 and c["dismissed"] == 0],
        "waiting": [{k: c[k] for k in ("job_id", "company", "title", "open")}
                    for c in cands if c["open"] > 0],
        "busy": _busy(jobs),
    }


def _err(path: str, message: str) -> applicant.FieldError:
    return applicant.FieldError(path, message)


def _merge_picks(target: dict, rows_by_id: dict[int, dict], picks: dict[str, list[str]],
                 kind: str, errors: list) -> None:
    """Fold the chosen verbatim labels into `target` (an entry or an override)
    as normalised picks and seen. A variant's new picks replace its old ones."""
    seen = list(target.get("seen") or [])
    chosen = list(target.get("picks") or [])
    for qid_text, labels in picks.items():
        try:
            row = rows_by_id[int(qid_text)]
        except (KeyError, ValueError):
            errors.append(_err(f"picks.{qid_text}", "is not a question of this group"))
            continue
        options = row.get("options") or []
        by_label = {o.get("label"): o.get("norm") for o in options if isinstance(o, dict)}
        norms = [by_label.get(label) for label in labels]
        if any(n is None for n in norms):
            errors.append(_err(f"picks.{qid_text}", "is not one of this question's options"))
            continue
        if kind == "choice" and len(norms) != 1:
            errors.append(_err(f"picks.{qid_text}", "choose exactly one option"))
            continue
        variant = {o.get("norm") for o in options if isinstance(o, dict)}
        chosen = [p for p in chosen if p not in variant]
        for n in [o.get("norm") for o in options if isinstance(o, dict)]:
            if n and n not in seen:
                seen.append(n)
        for n in norms:
            if n not in chosen:
                chosen.append(n)
    target["value"] = None
    target["picks"] = chosen
    target["seen"] = seen


def _apply_answer(profile: dict, rows: list[dict], body: AnswerBody,
                  employers: list[dict[str, str]]) -> list[applicant.FieldError]:
    """QD 9.2 steps 2-3 on `profile`, in place. Returns the request's own
    errors (the profile's are `applicant.save`'s)."""
    first = rows[0]
    if first.get("target_path"):
        if body.picks:
            return [_err("picks", "a profile field takes a value, not options")]
        try:
            applicant.set_path(profile, first["target_path"], body.value)
        except ValueError:
            return [_err(first["target_path"], "cannot be written there")]
        return []
    kind = str(first.get("kind"))
    if kind in CHOICE_KINDS:
        if not body.picks:
            return [_err("picks", "choose an option")]
    elif body.value is None:
        return [_err("value", "give an answer")]
    extra = profile.get("extra")
    if extra is None:
        extra = profile["extra"] = {}
    if not isinstance(extra, dict):
        return [_err("extra", "must be a mapping")]
    entry = extra.get(body.key)
    if not isinstance(entry, dict):
        entry = extra[body.key] = {
            "title": first.get("title") or body.key, "description": first.get("description") or "",
            "kind": kind, "sensitive": any(bool(r.get("sensitive")) for r in rows),
            "labels": [], "value": None}
        if kind in CHOICE_KINDS:
            entry.update(picks=[], seen=[])
    labels = list(entry.get("labels") or [])
    for r in rows:
        if r.get("label_norm") and r["label_norm"] not in labels:
            labels.append(r["label_norm"])
    entry["labels"] = labels
    target = entry
    if body.employer:
        match = next((e for e in employers if e["name"] == body.employer), None)
        if match is None:
            return [_err("employer", "is not one of the employers that asked this")]
        norm = match["employer_norm"] or body.employer.strip().lower()
        overrides = entry.get("by_employer")
        if not isinstance(overrides, dict):
            overrides = entry["by_employer"] = {}
        target = overrides.get(norm)
        if not isinstance(target, dict):
            target = overrides[norm] = {"value": None, "picks": [], "seen": []} \
                if kind in CHOICE_KINDS else {"value": None}
    errors: list[applicant.FieldError] = []
    if kind in CHOICE_KINDS:
        _merge_picks(target, {int(r["id"]): r for r in rows}, body.picks or {}, kind, errors)
    else:
        target["value"] = body.value
    return errors


@router.post("/questions/answer")
def answer_question(body: AnswerBody, request: Request,
                    cfg: Config = Depends(get_config)) -> Any:
    """Save the owner's answer to a group (QD 9.2): 404 unknown key, 409
    changed/unreadable, 422 invalid (nothing saved on any of them)."""
    with PROFILE_WRITE_LOCK:
        profile = load_for_write(cfg, body.etag)
        with open_store(request) as store:
            rows = store.questions_by_key(body.key)
            if not rows:
                raise HTTPException(status_code=404, detail="unknown question key")
            errors = _apply_answer(profile, rows, body, store.question_employers(body.key))
            if errors:
                return invalid(errors)
            try:
                applicant.save(cfg.applicant_path, profile)
            except applicant.ApplicantError as exc:
                return invalid(exc.errors)
            store.set_questions_status(body.key, "answered", utcnow())
            ready = _ready(store)
        etag = applicant.etag(cfg.applicant_path)
    return {"answered": [int(r["id"]) for r in rows], "ready": ready, "etag": etag}


@router.post("/questions/{key}/dismiss", status_code=204)
def dismiss_question(key: str, request: Request) -> Response:
    """"I'll answer this one by hand": the group is never asked again and its
    applications are never retried. The profile is not touched."""
    with open_store(request) as store:
        if not store.questions_by_key(key):
            raise HTTPException(status_code=404, detail="unknown question key")
        store.set_questions_status(key, "dismissed", utcnow())
    return Response(status_code=204)


@router.post("/questions/retry", status_code=202)
def retry_applications(body: RetryBody, request: Request, jobs: Any = Depends(get_jobs)) -> Any:
    """Start a new `apply` job for applications that wait on nothing (F-38).
    No dry_run flag: `jobscraper apply` uses the effective mode (AD §14.1)."""
    ids = [str(j) for j in body.job_ids]
    if not 1 <= len(ids) <= RETRY_MAX:
        raise HTTPException(status_code=422, detail=f"send 1 to {RETRY_MAX} job_ids")
    with open_store(request) as store:
        ready = {r["job_id"] for r in _ready(store)}
    not_ready = [j for j in ids if j not in ready]
    if not_ready:
        return JSONResponse({"detail": "not_ready", "job_ids": not_ready}, status_code=422)
    try:
        job = jobs.start("apply", {"job_ids": ids})
    except JobBusy:
        return JSONResponse({"detail": "busy"}, status_code=409)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"job": job}
