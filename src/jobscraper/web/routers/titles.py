"""`/api/titles` - the job titles the title filter searches for (M15).

`GET` answers what the Profile tab's title editor shows: the titles in use,
whether they are the user's or the resume's, the plan's limits and Qwen's last
recommendations. `PUT` replaces the user's titles; `DELETE` goes back to the
resume's. Recommendations are produced by a background job
(`POST /api/jobs/titles`), never here - the web layer does not reach a model.

Titles are stored in the settings table and read by the pipeline, which folds
them into the prefilter's cache key, so the next run re-checks the free
prefilter against them (and nothing else).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jobscraper.config import Config
from jobscraper.models import MAX_TITLE_CHARS, USER_TITLES_KEY, dedupe_titles
from jobscraper.web.control import titles_view
from jobscraper.web.deps import get_config, open_store

router = APIRouter(tags=["titles"])


class TitlesChange(BaseModel):
    """Body of `PUT /api/titles`: the full list, in the order to show it."""
    titles: list[str] = Field(..., max_length=200)


@router.get("/titles")
def get_titles(request: Request, cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Titles in use, their source (`custom` | `resume`), limits, recommendations."""
    with open_store(request) as store:
        return titles_view(cfg, store)


@router.put("/titles")
def put_titles(body: TitlesChange, request: Request,
               cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Replace the user's titles. `422` for an empty list, a title over
    MAX_TITLE_CHARS, or more titles than the plan allows."""
    too_long = [t for t in body.titles if len(" ".join(str(t).split())) > MAX_TITLE_CHARS]
    if too_long:
        raise HTTPException(status_code=422,
                            detail=f"a title can be at most {MAX_TITLE_CHARS} characters")
    titles = dedupe_titles(body.titles)
    if not titles:
        raise HTTPException(status_code=422,
                            detail="keep at least one job title - or reset to your resume's")
    limit = cfg.plan.max_target_titles
    if len(titles) > limit:
        raise HTTPException(
            status_code=422,
            detail=f"the {cfg.plan.name} plan allows {limit} job titles; got {len(titles)}")
    with open_store(request) as store:
        store.set_setting(USER_TITLES_KEY, json.dumps(titles))
        return titles_view(cfg, store)


@router.delete("/titles")
def reset_titles(request: Request, cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Forget the user's titles: the resume's are used again."""
    with open_store(request) as store:
        store.set_setting(USER_TITLES_KEY, None)
        return titles_view(cfg, store)
