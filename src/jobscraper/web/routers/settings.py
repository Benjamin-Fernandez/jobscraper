"""`/api/settings` and `/api/profile` - what the Settings and Profile tabs show (M11-T2).

Companies per run is a stored setting, not a config edit: Docker mounts
`config/` read-only, and a value the user changes in the browser has to survive
a restart. `PUT` validates against the enabled company count - a batch larger
than the watchlist is a typo, not a plan - and answers `422` for anything else.

`/api/profile` never fails for a missing profile: before the first resume
upload there is none, and the tab needs to say so rather than show an error.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictInt

from jobscraper.config import Config
from jobscraper.web.control import BATCH_SIZE_KEY, profile_view, settings_view
from jobscraper.web.deps import get_config, open_store

router = APIRouter(tags=["settings"])


class SettingsChange(BaseModel):
    """Body of `PUT /api/settings`. Strict: `"12"`, `2.5` and `true` are refused."""
    batch_size: StrictInt


@router.get("/settings")
def get_settings(request: Request,
                 cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Companies per run, its config default, and the cadence it implies."""
    with open_store(request) as store:
        return settings_view(cfg, store)


@router.put("/settings")
def put_settings(body: SettingsChange, request: Request,
                 cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Store companies per run; 1 <= n <= enabled companies, else `422`."""
    with open_store(request) as store:
        enabled = int(store.stats()["enabled"])
        if not 1 <= body.batch_size <= enabled:
            raise HTTPException(
                status_code=422,
                detail=f"batch_size must be between 1 and {enabled} "
                       f"(the enabled companies); got {body.batch_size}")
        store.set_setting(BATCH_SIZE_KEY, body.batch_size)
        return settings_view(cfg, store)


@router.get("/profile")
def get_profile(cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """The derived profile plus `judge.interests`; `present: false` if none yet."""
    return profile_view(cfg)
