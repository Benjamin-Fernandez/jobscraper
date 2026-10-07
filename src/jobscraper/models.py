"""Plain data structures shared across the pipeline."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

# Error classes drive the retry and quarantine policy (pipeline.py, store.py).
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


# ---------------- job titles (M15) ----------------
#
# The user's job titles and Qwen's recommendations are stored in the settings
# table as JSON. The engine (profile/titles.py) and the web app both read and
# write them, and the web app may not import a stage (PRD 8.2), so the shared
# rules live here, in the one module both may import.

USER_TITLES_KEY = "target_titles"
SUGGESTIONS_KEY = "title_suggestions"
# New titles asked for per "Recommend" (M17): always aim for this many that
# are neither chosen nor suggested before.
SUGGEST_BATCH = 5
MAX_TITLE_CHARS = 80


def normalise_title(title: object) -> str:
    """One title as the filter should see it: single spaces, no stray
    punctuation at the ends. '' when there is nothing usable."""
    t = re.sub(r"\s+", " ", str(title or "")).strip(" \t,.;:-/|")
    return t if 0 < len(t) <= MAX_TITLE_CHARS else ""


def dedupe_titles(titles) -> list[str]:
    """Normalised, first spelling kept, repeats dropped ignoring case."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in titles:
        t = normalise_title(raw)
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def parse_titles_json(raw: Optional[str]) -> Optional[list[str]]:
    """The stored titles, or None when unset, unreadable or empty - which all
    mean "use the resume's titles"."""
    import json
    if not raw:
        return None
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    return dedupe_titles(items) or None


# ---------------- the user's company list (M16) ----------------
#
# The web app parses an uploaded list (TXT or DOCX, one company per line) and
# the engine reads it back, so the rule lives here, in the module both import.

MAX_COMPANY_NAME = 120
MAX_COMPANY_LINES = 2000

# A list bullet or number at the start of a line: "- ", "* ", "\u2022 ", "1. ",
# "2) ", "(3) ", "4 - ". A name that starts with a digit ("2C2P", "3M",
# "7-Eleven", "99 Group") is left alone.
_LIST_MARK = re.compile(
    r"^\s*(?:[-*\u2022\u00b7\u25aa\u25e6\u2013\u2014]+\s+"
    r"|\(?\d{1,4}[.)\]]\s*|\d{1,4}\s+[-\u2013\u2014]\s+)")


def parse_company_lines(text: str) -> list[str]:
    """Company names from a list, one per line, in the order written. Bullets
    and numbering are dropped, blank lines skipped, a repeat (ignoring case)
    kept once - its first place is its rank."""
    names: list[str] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        name = _LIST_MARK.sub("", line)
        name = re.sub(r"\s+", " ", name).strip().strip(",;|").strip()
        if not name or len(name) > MAX_COMPANY_NAME or name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name)
        if len(names) >= MAX_COMPANY_LINES:
            break
    return names
