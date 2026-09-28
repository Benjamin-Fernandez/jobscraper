"""Configuration loading. Paths in config.yaml are relative to the project root.

Every deployment-shaped value can be overridden by an environment variable
(`JOBSCRAPER_CONFIG`, `JOBSCRAPER_DB`, `JOBSCRAPER_HOST`, `JOBSCRAPER_PORT`).
That is what lets the same code run from a checkout and from a container without
editing the file - PRD section 8.6 treats it as a design-time constraint, and it
is far cheaper to honour now than to retrofit.

The candidate profile is not here: it is derived from the resume by
`profile/resume_ingest.py` (PRD 8.3[1]). v1's `Profile` / `config/profile.yaml`
retired at M9-T1 (archive/v1-src/).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

# src/jobscraper/config.py -> src/jobscraper -> src -> <root>
ROOT = Path(__file__).resolve().parents[2]


def _abs(p: str | os.PathLike) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


# ---------------- plans (M15) ----------------
#
# Every limit a paid tier could change lives on a Plan, and nowhere else: the
# server validates against it and the web app draws its choices from it, so a
# tier is a row in PLANS, not a code change. The tier names and numbers follow
# the multi-user PRD (mullti_user_prd.md section 11).
#
# `local` is the owner's own install - the only user today - and always has the
# highest privileges: every cycle option, and no cap (None) on job titles or on
# the companies searched from an uploaded list. A cap of None means unlimited
# everywhere it is checked.

@dataclass(frozen=True)
class Plan:
    name: str
    cycle_day_options: tuple[int, ...]     # how often the company cycle may restart
    max_target_titles: Optional[int]        # job titles the filter searches for; None = no cap
    max_title_suggestions: int              # titles one recommendation returns
    max_companies: Optional[int]            # companies found from an uploaded list (M16);
                                            # failed searches do not count; None = no cap


PLANS: dict[str, Plan] = {
    "free": Plan("free", (7, 14, 30), 5, 5, 20),
    "plus": Plan("plus", (3, 7, 14, 30), 10, 10, 60),
    "pro": Plan("pro", (1, 3, 7, 14, 30), 20, 20, 200),
    "local": Plan("local", (1, 3, 7, 14, 30), None, 20, None),
}

CYCLE_DAYS_KEY = "cycle_days"               # the settings-table key (M15)


@dataclass
class Config:
    raw: dict[str, Any]

    def _path(self, key: str, default: str) -> Path:
        return _abs(self.raw.get("paths", {}).get(key, default))

    # ---------------- paths ----------------

    @property
    def watchlist_path(self) -> Path:
        """The companies to watch. Hand-edited; see watchlist.py."""
        return self._path("watchlist", "config/watchlist.yaml")

    @property
    def rules_path(self) -> Path:
        """The prefilter rules. Hand-edited; see filter.py."""
        return self._path("rules", "config/rules.yaml")

    @property
    def profile_path(self) -> Path:
        """The profile derived from the resume. Generated; do not hand-edit."""
        return self._path("profile", "data/profile.derived.yaml")

    @property
    def profile_overrides_path(self) -> Path:
        """Your corrections to the derived profile. Never regenerated."""
        return self._path("profile_overrides", "config/profile.overrides.yaml")

    @property
    def resume_dir(self) -> Path:
        return self._path("resume_dir", "data")

    @property
    def shortlist_path(self) -> Path:
        """The accepted queue the web app reads. Regenerated every run."""
        return self._path("shortlist", "data/shortlist.json")

    @property
    def db_path(self) -> Path:
        override = os.environ.get("JOBSCRAPER_DB")
        if override:
            return _abs(override)
        return self._path("db", "data/jobscraper.db")

    # ---------------- blocks ----------------

    @property
    def run(self) -> dict[str, Any]:
        return self.raw.get("run", {})

    @property
    def budget(self) -> dict[str, Any]:
        return self.raw.get("budget", {})

    @property
    def batch_size(self) -> int:
        """Companies per run (D-13)."""
        return int(self.run.get("batch_size", 10))

    @property
    def cycle_days(self) -> int:
        """Days before a company is due again, as config says (D-9).

        The cycle actually used is `effective_cycle_days`: the user's choice
        from the web app when the plan allows it, else this."""
        return int(self.run.get("cycle_days", 7))

    @property
    def plan(self) -> Plan:
        """The limits in force (M15). `plan:` in config.yaml; unknown -> local."""
        return PLANS.get(str(self.raw.get("plan", "local")).strip().lower(), PLANS["local"])

    def effective_cycle_days(self, stored: str | None) -> int:
        """The cycle the engine keeps: the stored setting (`cycle_days`, written
        by the web app) when it is one the plan offers, else `run.cycle_days`.

        Pure - the caller passes `store.get_setting(CYCLE_DAYS_KEY)` - so the
        pipeline, the CLI and the web app resolve it the same way without the
        web layer importing an engine module (PRD 8.2)."""
        if stored is not None and str(stored).strip().isdigit():
            n = int(str(stored).strip())
            if n in self.plan.cycle_day_options:
                return n
        return self.cycle_days

    @property
    def web(self) -> dict[str, Any]:
        """Bind address and port, env-overridable for containers (8.6)."""
        block = dict(self.raw.get("web", {}))
        block.setdefault("host", "127.0.0.1")
        block.setdefault("port", 8765)
        if os.environ.get("JOBSCRAPER_HOST"):
            block["host"] = os.environ["JOBSCRAPER_HOST"]
        if os.environ.get("JOBSCRAPER_PORT"):
            try:
                block["port"] = int(os.environ["JOBSCRAPER_PORT"])
            except ValueError as exc:
                raise SystemExit(
                    f"JOBSCRAPER_PORT must be a number, got "
                    f"{os.environ['JOBSCRAPER_PORT']!r}") from exc
        return block

    @property
    def application_statuses(self) -> list[str]:
        """Ordered status vocabulary. Adding one is config, not a migration."""
        statuses = self.raw.get("applications", {}).get("statuses")
        return list(statuses) if statuses else [
            "to_apply", "applied", "interviewing", "offer", "rejected",
            "withdrawn"]


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load config.yaml. An explicit path wins, then JOBSCRAPER_CONFIG."""
    if path:
        p = _abs(path)
    elif os.environ.get("JOBSCRAPER_CONFIG"):
        p = _abs(os.environ["JOBSCRAPER_CONFIG"])
    else:
        p = ROOT / "config" / "config.yaml"
    if not p.exists():
        raise SystemExit(f"config not found: {p}")
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise SystemExit(f"{p} must be a mapping, got {type(raw).__name__}")
    return Config(raw)

