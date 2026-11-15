"""`/api/questions` - RETIRED (Q-127, D-215; q127_profile_questions_design B.3, B.5, M5).

The Profile page never shows a question tied to a company or an application. What used to be
the Questions cards is now each application's "What was sent" (`/api/applications/{job_id}/
attempts/{attempt_id}/answers`) with "Use a different answer next time" (`.../remember`), and
Settings -> Apply -> "Answers you corrected" (`/api/apply/remembered`).

Nothing is deleted: the `questions` and `question_sightings` rows stay in the store (the
capture stage still writes them; they feed readiness and, later, the topic counter). This module
only keeps the old URLs answering, so a SPA bundle loaded before the update does not break:

- `GET /api/questions` keeps the full old shape with every list empty and `retired: true`
  (M5: an old bundle must not throw on a missing key);
- every old writer (`answer`, `dismiss`, `retry`, `keep`, `change`) answers 410 `retired`
  with the contract's text and writes nothing. No application is queued by any of them. They go
  in the release after this one.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from jobscraper.apply.contracts import QUESTIONS_RETIRED, QUESTIONS_RETIRED_TEXT
from jobscraper.config import Config
from jobscraper.web.deps import get_config, get_jobs, open_store
from jobscraper.web.routers.applicant import model_sees_private

router = APIRouter(tags=["questions"])

APPLY_MODE_KEY = "apply.mode"                 # the stored override of config apply.mode
MODES = ("auto", "dry_run")
STATUSES = ("open", "answered", "assumed", "all")


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


@router.get("/questions")
def list_questions(request: Request, status: str = "open",
                   cfg: Config = Depends(get_config), jobs: Any = Depends(get_jobs)) -> Any:
    """The old list, emptied: the same keys as before (`mode`, `groups`, `counts`, `ready`,
    `waiting`, `busy`, `model_sees_private`) with every list empty and every count 0, plus
    `retired: true`. Reads nothing from the questions table."""
    if status not in STATUSES:
        raise HTTPException(status_code=422,
                            detail="status must be open, answered, assumed or all")
    with open_store(request) as store:
        mode = _mode(cfg, store)
    return {"mode": mode, "groups": [],
            "counts": {"open": 0, "assumed": 0, "answered": 0, "dismissed": 0},
            "ready": [], "waiting": [], "busy": _busy(jobs),
            "model_sees_private": model_sees_private(cfg), "retired": True}


def retired() -> JSONResponse:
    """410 for an old writer: nothing was saved, nothing was queued."""
    return JSONResponse({"detail": QUESTIONS_RETIRED, "text": QUESTIONS_RETIRED_TEXT},
                        status_code=410)


@router.post("/questions/answer")
def answer_question() -> JSONResponse:
    """Retired: answer from the application's What was sent."""
    return retired()


@router.post("/questions/retry")
def retry_applications() -> JSONResponse:
    """Retired: Try again on the Applications row queues through `POST /api/apply`."""
    return retired()


@router.post("/questions/{question_id}/keep")
def keep_assumed(question_id: str) -> JSONResponse:
    """Retired (Answered for you): What was sent shows every assumed answer."""
    return retired()


@router.post("/questions/{question_id}/change")
def change_assumed(question_id: str) -> JSONResponse:
    """Retired (Answered for you): use "Use a different answer next time"."""
    return retired()


@router.post("/questions/{key}/dismiss")
def dismiss_question(key: str) -> JSONResponse:
    """Retired: a question is no longer put aside by hand."""
    return retired()
