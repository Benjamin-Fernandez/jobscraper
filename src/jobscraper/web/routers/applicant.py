"""`/api/applicant` - Profile -> Application details (F-10, F-11; questions_design §9.1).

The form edits `data/applicant.yaml` (gitignored), the facts an employer's
application form asks for. Everything about the file - the schema the form is
drawn from (`applicant.FORM`), validation, what is missing, what is sensitive,
the atomic save - lives in the `applicant` foundation module; this router only
moves it over HTTP.

Two guards, because more than one thing writes the file (this form, a second
tab, the Questions card, a hand edit):

- **etag** (`applicant.etag`): GET returns it, PUT must send it back. A
  mismatch is `409 {"detail": "changed"}` and nothing is written.
- **unreadable file**: GET still answers 200, with `file.error` set, so the tab
  can say what is wrong; PUT is `409 {"detail": "unreadable"}`, so a broken file
  is never overwritten by a form that could not show it.

An invalid profile is `422 {"detail": "invalid", "errors": [{path, message}]}`
(top level, not nested under `detail`, so the form can mark each path). Keys
the form does not know round-trip untouched: the UI edits a deep copy of the
whole profile and sends all of it back. Because a whole-file PUT can replace
everything, `applicant.save` keeps the version it replaces as
`applicant.prev.yaml` beside the profile (one rolling copy, Q-30 F7); GET reads
the profile and its etag from one read of the file (Q-30 F6).

`POST /api/applicant/check` (Q-71 G5) runs the same validation on a posted profile
and writes nothing, so the form can flag a field when it loses focus. GET also
carries `documents_status` (the resume and transcript in use: name, size,
modified; never a path).

`GET/POST /api/applicant/refresh` (Q-44, q44_refresh_from_resume.md §4): the
"Update your application details" panel. The profile job leaves the resume-side
facts in `applicant.refresh.json` beside the profile; GET computes the plan
against the current file on every call (so a form edit never leaves it stale),
POST applies the ticked change ids under the same etag guard and lock as PUT.
Entries and skills are shown in the UI only and never logged.
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jobscraper import applicant
from jobscraper.config import Config
from jobscraper.web.deps import get_config

router = APIRouter(tags=["applicant"])

# One writer at a time: the etag check and the save must not interleave with
# another request's (the Questions router takes the same lock).
PROFILE_WRITE_LOCK = threading.Lock()


class ApplicantChange(BaseModel):
    """Body of `PUT /api/applicant`: the whole profile and the etag it was read at."""
    profile: dict[str, Any]
    etag: str = ""


class ApplicantCheck(BaseModel):
    """Body of `POST /api/applicant/check`: a profile to validate, nothing else
    (no etag: it is never written)."""
    profile: dict[str, Any]


class RefreshSave(BaseModel):
    """Body of `POST /api/applicant/refresh`: the change ids the owner ticked and
    the etag of the profile the plan was shown against."""
    etag: str = ""
    accept: list[str] = []


def _from_resume(profile: dict) -> list[str]:
    """Paths of the entries pre-filled from the resume (`from_resume: true`)."""
    out: list[str] = []

    def walk(v: Any, path: str) -> None:
        if isinstance(v, dict):
            if v.get("from_resume") is True and path:
                out.append(path)
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    walk(profile, "")
    return out


def sensitive_paths(profile: dict) -> list[str]:
    """Every leaf path that is an S path (§5.3), plus `extra.<key>` for the
    entries the owner marked `sensitive: true`."""
    out = [p for p, _v in applicant.walk_leaves(profile)
           if not p.startswith("extra.") and applicant.is_sensitive(p)]
    extra = profile.get("extra")
    if isinstance(extra, dict):
        out += [f"extra.{k}" for k, e in extra.items()
                if isinstance(e, dict) and e.get("sensitive") is True]
    return out


def errors_json(errors: list[applicant.FieldError]) -> list[dict[str, str]]:
    return [{"path": e.path, "message": e.message} for e in errors]


def applicant_view(cfg: Config) -> dict[str, Any]:
    """The GET payload (questions_design §9.1)."""
    path = cfg.applicant_path
    error = None
    try:
        # One read: the profile and the etag come from the same bytes (Q-30 F6).
        profile, etag = applicant.load_with_etag(path)
    except applicant.ApplicantError as exc:
        profile, etag, error = {}, exc.etag, str(exc)
    filled, needed = applicant.completeness(profile)
    return {
        "profile": applicant.json_safe(profile),
        "etag": etag,
        "errors": errors_json(applicant.validate(profile)) if error is None else [],
        "missing": applicant.missing_for_apply(profile, cfg.resume_dir),
        "completeness": {"filled": filled, "needed": needed},
        "documents_status": applicant.documents_status(profile, cfg.resume_dir),
        "from_resume": _from_resume(profile),
        "sensitive": sensitive_paths(profile),
        "form": applicant.form_json(),
        "file": {"exists": path.is_file(), "has_comments": applicant.has_comments(path),
                 "error": error},
    }


def invalid(errors: list[applicant.FieldError]) -> JSONResponse:
    return JSONResponse({"detail": "invalid", "errors": errors_json(errors)},
                        status_code=422)


def load_for_write(cfg: Config, sent_etag: str) -> dict:
    """The current profile, once the etag matches. 409 `unreadable` for a file
    that cannot be read, 409 `changed` when it changed since `sent_etag`.
    Call with PROFILE_WRITE_LOCK held."""
    try:
        current, current_etag = applicant.load_with_etag(cfg.applicant_path)
    except applicant.ApplicantError:
        raise HTTPException(status_code=409, detail="unreadable")
    if (sent_etag or "") != current_etag:
        raise HTTPException(status_code=409, detail="changed")
    return current


def with_version(profile: dict) -> dict:
    """`version` is not on the form; it is always written as 1, in place when
    the profile has it, else first."""
    if "version" in profile:
        profile["version"] = applicant.SCHEMA_VERSION
        return profile
    return {"version": applicant.SCHEMA_VERSION, **profile}


@router.get("/applicant")
def get_applicant(cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """The profile, its etag, what is missing or wrong, and the form schema."""
    return applicant_view(cfg)


@router.put("/applicant")
def put_applicant(body: ApplicantChange, cfg: Config = Depends(get_config)) -> Any:
    """Save the whole profile: 409 on a stale etag or an unreadable file,
    422 naming each invalid path; nothing is written on either."""
    with PROFILE_WRITE_LOCK:
        load_for_write(cfg, body.etag)
        profile = with_version(dict(body.profile))
        try:
            applicant.save(cfg.applicant_path, profile)
        except applicant.ApplicantError as exc:
            return invalid(exc.errors)
    return applicant_view(cfg)


@router.post("/applicant/check")
def check_applicant(body: ApplicantCheck) -> dict[str, Any]:
    """Validate a profile the way PUT would, without writing it (Q-71 G5): the
    form calls this when a field loses focus, so a mistake shows under the field
    and not only after Save. No etag and no write lock, because nothing is read
    from or written to the file; `{errors: [{path, message}]}`, empty when valid."""
    profile = with_version(dict(body.profile))
    return {"errors": errors_json(applicant.validate(profile))}


def _proposals_state(cfg: Config) -> tuple[str, dict | None]:
    """("ready", proposals) or (no_profile | none | stale, None)."""
    if not cfg.applicant_path.is_file():
        return "no_profile", None
    props = applicant.load_proposals(applicant.proposals_path(cfg.applicant_path))
    if props is None:
        return "none", None
    if props.get("resume_hash") != applicant.original_resume_hash(cfg.resume_dir):
        return "stale", None
    return "ready", props


@router.get("/applicant/refresh")
def get_refresh(cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """The plan: `{state: "ready", source_name, created_at, resume_hash, etag,
    changes, skills}`, or `{state}` for no_profile | none | stale | unreadable."""
    state, props = _proposals_state(cfg)
    if props is None:
        return {"state": state}
    try:
        profile, etag = applicant.load_with_etag(cfg.applicant_path)
    except applicant.ApplicantError:
        return {"state": "unreadable"}
    plan = applicant.refresh_plan(profile, props, applicant.load_template())
    return {"state": "ready", "source_name": str(props.get("source_name") or ""),
            "created_at": props.get("created_at"), "resume_hash": props.get("resume_hash"),
            "etag": etag, "changes": applicant.json_safe(plan["changes"]),
            "skills": plan["skills"]}


@router.post("/applicant/refresh")
def save_refresh(body: RefreshSave, cfg: Config = Depends(get_config)) -> Any:
    """Apply the ticked changes: 409 on a stale etag, an unreadable file, or
    proposals that are gone or older than the resume (`detail` says which);
    422 naming each invalid path; nothing is written on any of them. Ids the
    plan does not offer now are not applied and come back in `ignored`."""
    with PROFILE_WRITE_LOCK:
        state, props = _proposals_state(cfg)
        if props is None:
            raise HTTPException(status_code=409, detail=state)
        current = load_for_write(cfg, body.etag)
        new, ignored = applicant.apply_refresh(current, props, body.accept,
                                               applicant.load_template())
        saved = len([a for a in dict.fromkeys(body.accept) if a not in ignored])
        if saved:
            try:
                applicant.save(cfg.applicant_path, with_version(new))
            except applicant.ApplicantError as exc:
                return invalid(exc.errors)
    return {**applicant_view(cfg), "saved": saved, "ignored": ignored}
