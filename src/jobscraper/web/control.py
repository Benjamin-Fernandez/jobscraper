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

import json
from typing import Any, Optional

import yaml

from jobscraper.config import CYCLE_DAYS_KEY, Config
from jobscraper.models import (SUGGESTIONS_KEY, USER_TITLES_KEY, dedupe_titles,
                               parse_titles_json)

BATCH_SIZE_KEY = "batch_size"

PROFILE_FIELDS = ("profile_version", "source_file", "parsed_at", "parsed_by",
                  "summary", "skills", "target_titles")


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


def effective_cycle_days(cfg: Config, store: Any) -> int:
    """Days before a company is due again (M15): the stored choice when the plan
    offers it, else `run.cycle_days` - the same resolution the pipeline uses."""
    return cfg.effective_cycle_days(store.get_setting(CYCLE_DAYS_KEY))


def settings_view(cfg: Config, store: Any) -> dict[str, Any]:
    """The `/api/settings` answer (PRD M11 contract, M15 cycle fields).

    `cycle_day_options` and `plan` come from the plan in force, so the Settings
    tab only ever offers what the server will accept (tier-ready, M15-D1)."""
    enabled = int(store.stats()["enabled"])
    batch = effective_batch_size(cfg, store)
    cycle = effective_cycle_days(cfg, store)
    return {"batch_size": batch, "batch_size_default": cfg.batch_size,
            "enabled_companies": enabled, "cycle_days": cycle,
            "cycle_days_default": cfg.cycle_days,
            "cycle_day_options": list(cfg.plan.cycle_day_options),
            "plan": cfg.plan.name,
            "runs_per_day_needed": runs_per_day_needed(enabled, batch, cycle)}


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
    # parsed_by: the model that read the resume (Qwen since M14); absent on a
    # profile derived before then.
    for key in ("source_file", "parsed_at", "parsed_by", "summary"):
        out[key] = None if doc.get(key) is None else str(doc[key])
    try:
        out["profile_version"] = int(doc.get("profile_version"))
    except (TypeError, ValueError):
        out["profile_version"] = None
    for key in ("skills", "target_titles"):
        items = doc.get(key)
        out[key] = [str(i) for i in items] if isinstance(items, list) else []
    return out


def titles_view(cfg: Config, store: Any) -> dict[str, Any]:
    """The `/api/titles` answer (M15): the titles the title filter searches for,
    where they come from, the plan's limits, and Qwen's last recommendations.

    `resume_titles` are the derived profile's (the corrections file is merged
    at run time and not reflected here, as with `/api/profile`). A
    recommendation the user has since chosen is left out.
    """
    plan = cfg.plan
    resume = dedupe_titles(profile_view(cfg)["target_titles"])
    user = parse_titles_json(store.get_setting(USER_TITLES_KEY))
    titles = user or resume
    suggestions = None
    raw = store.get_setting(SUGGESTIONS_KEY)
    if raw:
        try:
            doc = json.loads(raw)
        except (TypeError, ValueError):
            doc = None
        if isinstance(doc, dict):
            taken = {t.lower() for t in titles}
            items = [i for i in (doc.get("suggestions") or [])
                     if isinstance(i, dict) and str(i.get("title", "")).lower() not in taken]
            suggestions = {
                "generated_at": doc.get("generated_at"),
                "model": doc.get("model"),
                "field_of_study": doc.get("field_of_study") or "",
                "experience": [str(e) for e in (doc.get("experience") or [])],
                "items": items[:plan.max_title_suggestions],
            }
    return {"titles": titles, "source": "custom" if user else "resume",
            "resume_titles": resume, "max_titles": plan.max_target_titles,
            "max_suggestions": plan.max_title_suggestions, "plan": plan.name,
            "suggestions": suggestions}


# ---------------------------------------------------------------- the user's company list (M16)

COMPANY_STATUSES = ("pending", "searching", "found", "watched", "failed", "over_limit")


def companies_view(cfg: Config, store: Any) -> dict[str, Any]:
    """The `/api/companies/list` answer: the list in the user's order, each
    company's search result, the counts, and the plan's cap on companies.

    `searched` is what the cap counts - companies found or already watched;
    a failed search does not count (M16)."""
    rows = store.company_list()
    counts = {s: 0 for s in COMPANY_STATUSES}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    fields = ("position", "name", "status", "careers_url", "provider", "postings",
              "detail", "searched_at")
    return {"items": [{f: r.get(f) for f in fields} for r in rows],
            "counts": counts,
            "searched": counts["found"] + counts["watched"],
            "max_companies": cfg.plan.max_companies,
            "plan": cfg.plan.name}
