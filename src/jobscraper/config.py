"""Configuration loading. Paths in config.yaml are relative to the project root."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# src/jobscraper/config.py -> src/jobscraper -> src -> <root>
ROOT = Path(__file__).resolve().parents[2]


def _abs(p: str | os.PathLike) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


@dataclass
class Config:
    raw: dict[str, Any]

    @property
    def input_workbook(self) -> Path:
        return _abs(self.raw["paths"]["input_workbook"])

    @property
    def input_sheet(self) -> str:
        return self.raw["paths"].get("input_sheet", "Job Tracker")

    @property
    def db_path(self) -> Path:
        return _abs(self.raw["paths"]["db"])

    @property
    def output_dir(self) -> Path:
        return _abs(self.raw["paths"]["output_dir"])

    @property
    def run(self) -> dict[str, Any]:
        return self.raw["run"]

    @property
    def budget(self) -> dict[str, Any]:
        return self.raw["budget"]

    @property
    def output(self) -> dict[str, Any]:
        return self.raw.get("output", {})


@dataclass
class Profile:
    raw: dict[str, Any]
    allow_res: list[re.Pattern] = field(default_factory=list)
    deny_res: list[re.Pattern] = field(default_factory=list)
    loc_deny_re: Optional[re.Pattern] = None

    def __post_init__(self) -> None:
        t = self.raw.get("titles", {})
        self.allow_res = [re.compile(p) for p in t.get("allow_patterns", [])]
        self.deny_res = [re.compile(p) for p in t.get("deny_patterns", [])]
        # Word-boundary alternation so short tokens ("us", "ny", "uk") cannot
        # match inside longer words ("houston", "company", "ukraine").
        hints = sorted(self.loc_deny, key=len, reverse=True)
        self.loc_deny_re = re.compile(
            r"\b(?:" + "|".join(re.escape(h) for h in hints) + r")\b"
        ) if hints else None

    @property
    def version(self) -> int:
        return int(self.raw.get("profile_version", 1))

    @property
    def summary(self) -> str:
        return " ".join(self.raw["identity"]["summary"].split())

    @property
    def loc_allow(self) -> list[str]:
        return [s.lower() for s in self.raw["locations"]["allow"]]

    @property
    def loc_deny(self) -> list[str]:
        return [s.lower() for s in self.raw["locations"]["deny_hints"]]

    @property
    def loc_ambiguous(self) -> list[str]:
        return [s.lower() for s in self.raw["locations"]["ambiguous_hints"]]

    @property
    def thresholds(self) -> dict[str, Any]:
        return self.raw["thresholds"]

    @property
    def weights(self) -> dict[str, float]:
        return self.raw["weights"]

    @property
    def experience(self) -> dict[str, int]:
        return self.raw["experience"]

    def skill_groups(self) -> dict[str, list[str]]:
        return {k: [s.lower() for s in v] for k, v in self.raw["skills"].items()}

    def all_skills(self) -> list[str]:
        out: list[str] = []
        for v in self.skill_groups().values():
            out.extend(v)
        return out

    def category_prior(self, category: str) -> list[str]:
        return self.raw.get("category_priors", {}).get(category, [])


def load_config(path: str | os.PathLike | None = None) -> Config:
    p = _abs(path) if path else ROOT / "config" / "config.yaml"
    with open(p, "r", encoding="utf-8") as fh:
        return Config(yaml.safe_load(fh))


def load_profile(path: str | os.PathLike | None = None) -> Profile:
    p = _abs(path) if path else ROOT / "config" / "profile.yaml"
    with open(p, "r", encoding="utf-8") as fh:
        return Profile(yaml.safe_load(fh))
