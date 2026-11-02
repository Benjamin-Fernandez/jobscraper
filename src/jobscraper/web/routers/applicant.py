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
