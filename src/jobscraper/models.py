"""Plain data structures shared across the pipeline."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Error classes drive the retry policy. See DESIGN.md 3.9.
TRANSIENT = "transient"
BLOCKED = "blocked"
GONE = "gone"
SCHEMA = "schema"
UNKNOWN = "unknown"

RETRYABLE = {TRANSIENT}


@dataclass
class Company:
    id: int
    ordinal: int
    name: str
    tier: str
    category: str
    careers_url: str
    role_type_hint: str = ""
    provider: Optional[str] = None
    slug: Optional[str] = None
    feed_url: Optional[str] = None
    resolve_method: Optional[str] = None
    resolved_at: Optional[str] = None
    consecutive_failures: int = 0
    last_success_at: Optional[str] = None
    last_error_class: Optional[str] = None
    last_error: Optional[str] = None
    quarantined_at: Optional[str] = None
    probation_due_run: Optional[int] = None
    active: int = 1


@dataclass
class WatchedCompany:
    """A v2 `companies` row: a watchlist entry plus the history the DB owns.

    Identity is `key`, never `name` (PRD section 8.4). The v1 `Company` above
    lives on only for the legacy modules and goes in M9-T1. The adapters and
    discovery read `name`, `careers_url`, `provider`, `slug` and `feed_url`, so
    this satisfies them unchanged.
    """
    id: int
    key: str
    name: str
    careers_url: str
    provider: Optional[str] = None
    slug: Optional[str] = None
    feed_url: Optional[str] = None
    resolve_method: Optional[str] = None
    resolved_at: Optional[str] = None
    enabled: int = 1
    last_scraped_at: Optional[str] = None
    last_success_at: Optional[str] = None
    consecutive_failures: int = 0
    last_error_class: Optional[str] = None
    last_error: Optional[str] = None
    quarantined_at: Optional[str] = None
    probation_due_run: Optional[int] = None


@dataclass
class RawJob:
    external_id: str
    title: str
    url: str
    location: str = ""
    department: str = ""
    employment_type: str = ""
    posted_at: str = ""
    description: str = ""

    def job_id(self, company_id: int, provider: str) -> str:
        key = self.external_id or self.url
        if key:
            basis = f"{company_id}|{provider}|{key}"
        else:
            basis = f"{company_id}|{_norm(self.title)}|{_norm(self.location)}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    def jd_hash(self) -> str:
        body = f"{self.title}\n{self.location}\n{self.description}"
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


@dataclass
class FetchOutcome:
    """Result of attempting one company. Never raises past the orchestrator."""
    company_id: int
    ok: bool
    jobs: list[RawJob] = field(default_factory=list)
    error_class: Optional[str] = None
    error: Optional[str] = None
    http_status: Optional[int] = None
    provider: Optional[str] = None
    duration_s: float = 0.0


@dataclass
class JobFacts:
    """Stage C1 output: structured fields extracted once, reused forever."""
    job_id: str
    countries: list[str] = field(default_factory=list)
    is_singapore: Optional[bool] = None
    seniority: str = "unknown"
    yoe_min: Optional[int] = None
    yoe_max: Optional[int] = None
    intake_year: Optional[int] = None
    is_graduate_programme: Optional[bool] = None
    sponsorship: str = "unclear"
    role_family: str = "other"
    tech_stack: list[str] = field(default_factory=list)
    requires_clearance: Optional[bool] = None
    model: str = ""


@dataclass
class Verdict:
    job_id: str
    verdict: str = "unknown"      # strong | possible | weak | reject | contested
    confidence: float = 0.0
    reason: str = ""
    concerns: list[str] = field(default_factory=list)
    model: str = ""
    stage: str = "c2"


@dataclass
class ScoreBreakdown:
    total: float = 0.0
    bm25: float = 0.0
    skill_overlap: float = 0.0
    title_affinity: float = 0.0
    tier_bonus: float = 0.0
    category_prior: float = 0.0


@dataclass
class Candidate:
    """A new posting travelling through the match funnel."""
    job_id: str
    company: Company
    raw: RawJob
    stage_a_pass: bool = True
    filter_reason: str = ""
    location_ambiguous: bool = False
    score: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    facts: Optional[JobFacts] = None
    verdict: Optional[Verdict] = None

    @property
    def exportable_reason(self) -> str:
        if self.verdict and self.verdict.reason:
            return self.verdict.reason
        bits = []
        if self.score.skill_overlap:
            bits.append(f"skills {self.score.skill_overlap:.0f}")
        if self.score.title_affinity:
            bits.append(f"title {self.score.title_affinity:.0f}")
        return "rule match: " + ", ".join(bits) if bits else "rule match"


@dataclass
class CycleState:
    cycle_id: int
    cycle_started_at: str
    cursor: int
    total_companies: int
    last_run_no: int = 0


@dataclass
class TokenLedger:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, i: int, o: int) -> None:
        self.input_tokens += i
        self.output_tokens += o
        self.calls += 1

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
        }
