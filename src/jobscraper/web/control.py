"""What the web app needs to know to control the engine without importing it (M11).

The web layer may not import a pipeline stage (PRD 8.2), yet the Runs, Profile
and Settings tabs need two answers a stage would normally give: how many
companies the next run takes, and what the current profile says. Both are
answered here from the same stored facts the engine reads - the `settings`
table and `data/profile.derived.yaml` - so the numbers on screen are the ones a
run actually uses.

`effective_batch_size` must agree with `cli._batch_size`: flag, else the stored
setting, else `run.batch_size`. The web app has no flag - it passes the value it
resolved here to the CLI as `--batch-size`.
"""
from __future__ import annotations

from typing import Any, Optional

import yaml

from jobscraper.config import Config

BATCH_SIZE_KEY = "batch_size"

PROFILE_FIELDS = ("profile_version", "source_file", "parsed_at", "summary",
                  "skills", "target_titles")


def stored_batch_size(store: Any) -> Optional[int]:
    """The batch size the user saved, or None if unset or not a positive integer."""
    raw = store.get_setting(BATCH_SIZE_KEY)
    if raw is None or not str(raw).isdigit() or int(raw) < 1:
        return None
    return int(raw)


def effective_batch_size(cfg: Config, store: Any) -> int:
    """Companies per run: the stored setting, else `run.batch_size` in config."""
    return stored_batch_size(store) or cfg.batch_size


def runs_per_day_needed(enabled: int, batch_size: int, cycle_days: int) -> float:
    """Runs a day to scrape every enabled company once per cycle (PRD R-7)."""
    if batch_size < 1 or cycle_days < 1:
        return 0.0
    return round(enabled / batch_size / cycle_days, 1)


def settings_view(cfg: Config, store: Any) -> dict[str, Any]:
    """The `/api/settings` answer (PRD M11 contract)."""
    enabled = int(store.stats()["enabled"])
    batch = effective_batch_size(cfg, store)
    return {"batch_size": batch, "batch_size_default": cfg.batch_size,
            "enabled_companies": enabled, "cycle_days": cfg.cycle_days,
            "runs_per_day_needed": runs_per_day_needed(enabled, batch,
                                                       cfg.cycle_days)}


def interests(cfg: Config) -> list[str]:
    """`judge.interests` from config: what the judge counts as a fit."""
    judge = cfg.raw.get("judge") or {}
    items = judge.get("interests") if isinstance(judge, dict) else None
    return [str(i) for i in items] if isinstance(items, list) else []


def profile_view(cfg: Config) -> dict[str, Any]:
    """The `/api/profile` answer: the derived profile as the engine wrote it.

    Read directly rather than through `profile.resume_ingest`, which is a stage
    the web layer may not import. So this is the derived file itself; the
    corrections in `config/profile.overrides.yaml` are merged in at run time
    and are not reflected here. A missing, unreadable or malformed file is
    `present: false` - the Profile tab's "upload a resume" state, not an error.
    """
    out: dict[str, Any] = {"present": False, **{k: None for k in PROFILE_FIELDS},
                           "skills": [], "target_titles": [],
                           "interests": interests(cfg)}
    try:
        doc = yaml.safe_load(cfg.profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return out
    if not isinstance(doc, dict):
        return out
    out["present"] = True
    for key in ("source_file", "parsed_at", "summary"):
        out[key] = None if doc.get(key) is None else str(doc[key])
    try:
        out["profile_version"] = int(doc.get("profile_version"))
    except (TypeError, ValueError):
        out["profile_version"] = None
    for key in ("skills", "target_titles"):
        items = doc.get(key)
        out[key] = [str(i) for i in items] if isinstance(items, list) else []
    return out
