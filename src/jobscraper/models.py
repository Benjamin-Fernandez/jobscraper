"""Plain data structures shared across the pipeline."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

# Error classes drive the retry policy. See DESIGN.md 3.9.
TRANSIENT = "transient"
BLOCKED = "blocked"
GONE = "gone"
SCHEMA = "schema"
UNKNOWN = "unknown"

RETRYABLE = {TRANSIENT}


@dataclass
class WatchedCompany:
    """A v2 `companies` row: a watchlist entry plus the history the DB owns.

    Identity is `key`, never `name` (PRD section 8.4). The adapters and
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
