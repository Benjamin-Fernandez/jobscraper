"""Configuration loading. Paths in config.yaml are relative to the project root.

Every deployment-shaped value can be overridden by an environment variable
(`JOBSCRAPER_CONFIG`, `JOBSCRAPER_DB`, `JOBSCRAPER_HOST`, `JOBSCRAPER_PORT`).
That is what lets the same code run from a checkout and from a container without
editing the file - PRD section 8.6 treats it as a design-time constraint, and it
is far cheaper to honour now than to retrofit.

The candidate profile is not here: it is derived from the resume by
`profile/resume_ingest.py` (PRD 8.3[1]). v1's `Profile` / `config/profile.yaml`
retired at M9-T1 (kept at the v1-final tag).
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
# the multi-user PRD (mullti_user_prd.md section 11, in the jobscraper-cloud repo).
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


# ---------------- auto-apply (M20, apply_design §16) ----------------
#
# The `apply:` block of config.yaml. Every field has the design's default, used
# when the block (or a key) is absent. Settings → Apply (the `settings` table,
# keys `apply.<field>`) overrides some of these at run time; the CLI builds that
# effective copy with dataclasses.replace (apply_design §14.3).

@dataclass(frozen=True)
class ApplyMailConfig:
    host: str = "imap.gmail.com"
    port: int = 993
    username: str = ""          # never written to config.yaml (public repo): settings only
    wait_s: int = 300           # F-36
    poll_s: int = 10


@dataclass(frozen=True)
class ApplyConfig:
    mode: str = "dry_run"                   # auto | dry_run
    daily_cap: int = 10                     # D-61
    per_employer_daily_cap: int = 2         # D-61
    headed: bool = True                     # D-53
    captcha_wait_s: int = 0                 # F-38
    profile_dir: str = r"%LOCALAPPDATA%\JobScraper\apply-profile"
    edge_sync: bool = False                 # S-1: true drops --disable-sync
    edge_save_bubble: bool = False
    type_delay_ms: int = 60
    action_pause_ms: int = 250              # NF-05
    step_timeout_s: int = 45
    confirm_timeout_s: int = 60             # F-37
    attempt_timeout_s: int = 420            # NF-07
    dry_run_hold_s: int = 600               # F-37
    resume_format: str = "pdf"              # pdf | docx
    mygreenhouse: bool = True               # D-70: MyGreenhouse autofill, then fill the gaps (§9.1.1)
    mygreenhouse_wait_s: int = 20
    workday_entry: str = "auto"             # D-70 §9.4.2: auto | manual (lane V)
    max_wizard_steps: int = 15
    llm_text_temperature: float = 0.3
    mail: ApplyMailConfig = ApplyMailConfig()
    # D-70 §11.5: the mailbox for contact.backup_email; host "" = the same mailbox as `mail`.
    mail_backup: ApplyMailConfig = ApplyMailConfig(host="")

    @classmethod
    def from_raw(cls, raw: Any) -> "ApplyConfig":
        """Build from the yaml block; missing keys keep the defaults and values
        are coerced to each field's type (a quoted number still works)."""
        raw = raw if isinstance(raw, dict) else {}

        def block(key: str) -> dict[str, Any]:
            return raw.get(key) if isinstance(raw.get(key), dict) else {}
        backup = {"host": "", **block("mail_backup")}
        return cls(**_coerce(cls, raw, skip={"mail", "mail_backup"}),
                   mail=ApplyMailConfig(**_coerce(ApplyMailConfig, block("mail"))),
                   mail_backup=ApplyMailConfig(**_coerce(ApplyMailConfig, backup)))


def _coerce(klass: type, raw: dict[str, Any], skip: frozenset | set = frozenset()) -> dict[str, Any]:
    """The keys of `raw` that are fields of the dataclass `klass`, cast to the
    type of that field's default. Unknown keys are ignored."""
    out: dict[str, Any] = {}
    for name, f in klass.__dataclass_fields__.items():
        if name in skip or name not in raw or raw[name] is None:
            continue
        default, v = f.default, raw[name]
        if isinstance(default, bool):
            out[name] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int):
            out[name] = int(v)
        elif isinstance(default, float):
            out[name] = float(v)
        else:
            out[name] = str(v)
    return out

@dataclass(frozen=True)
class TailorConfig:
    """The `tailor:` block (tailor_design.md section 14), defaults included so a
    config.yaml without the block still works. `llm` is the M22 rewrite layer
    and stays False (D-67)."""
    enabled: bool = True
    llm: bool = False
    llm_terms: bool = True
    temperature: float = 0.25
    top_k: int = 20
    seed: int = 7
    headline: bool = True
    pdf: bool = True
    page_ceiling: Any = "auto"              # "auto" = the master's page count, or a number
    max_jd_chars: int = 12000
    draft_days: float = 7
    sent_days_after_close: float = 30
    closed_statuses: tuple[str, ...] = ("rejected", "withdrawn")


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
    def decide_batch(self) -> int:
        """Postings per judge call: `budget.decide_batch`, else 20."""
        return int(self.budget.get("decide_batch", 20))

    @property
    def per_run_timeout(self) -> float:
        """Seconds before a run still marked `running` is taken to have crashed:
        `run.per_run_timeout`, else 3600."""
        return float(self.run.get("per_run_timeout", 3600))

    @property
    def decide_deadline_s(self) -> Optional[float]:
        """Seconds a run may spend judging before it stops taking new batches,
        writes the shortlist and ends normally: `budget.decide_deadline_s`;
        unset or 0 = no deadline."""
        n = self.budget.get("decide_deadline_s")
        return float(n) if n else None

    @property
    def scrape(self) -> dict[str, Any]:
        return self.raw.get("scrape") or {}

    @property
    def scrape_locations(self) -> list[str]:
        """Locations adapters facet large boards for (D-33): Workday and
        SmartRecruiters query these instead of stopping at the 600-posting
        cap. Default Singapore."""
        locs = self.scrape.get("locations")
        if not locs:
            return ["Singapore"]
        return [str(x) for x in locs]

    @property
    def application_statuses(self) -> list[str]:
        """Ordered status vocabulary. Adding one is config, not a migration."""
        statuses = self.raw.get("applications", {}).get("statuses")
        return list(statuses) if statuses else [
            "to_apply", "applied", "interviewing", "offer", "rejected",
            "withdrawn"]

    # ---------------- apply (M20) ----------------

    @property
    def apply(self) -> ApplyConfig:
        """The `apply:` block with the design's defaults (apply_design §16)."""
        return ApplyConfig.from_raw(self.raw.get("apply"))

    # ---------------- tailor (M20) ----------------

    @property
    def tailor(self) -> TailorConfig:
        """The resume tailor's settings; unknown keys are ignored."""
        block = self.raw.get("tailor") or {}
        known = {k: block[k] for k in TailorConfig.__dataclass_fields__ if k in block}
        if "closed_statuses" in known:
            known["closed_statuses"] = tuple(str(s) for s in known["closed_statuses"] or ())
        return TailorConfig(**known)

    @property
    def aliases_path(self) -> Path:
        """Term variants for the tailor. Hand-edited; public data."""
        return self._path("aliases", "config/aliases.yaml")

    @property
    def master_resume_path(self) -> Path:
        """The resume parsed once into fields (gitignored)."""
        return self._path("master_resume", "data/master_resume.json")

    @property
    def tailored_dir(self) -> Path:
        """Per-job tailored resumes (gitignored; deleted per D-59)."""
        return self._path("tailored_dir", "data/tailored")


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

