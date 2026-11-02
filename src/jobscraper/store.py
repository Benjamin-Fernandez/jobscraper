"""v2 SQLite persistence - and the only module in the package that contains SQL.

Why one module: every other module asks this one for data instead of writing a
query, which is what makes the Postgres path in PRD section 8.4 one file's work
rather than a search-and-replace (the layering guard enforces it). Plain SQL is
preferred over SQLite dialect wherever an ANSI form exists; the few exceptions
are named where they occur.

Who owns what. The watchlist YAML says *which* companies exist; this database
owns their *history* - staleness, failures, quarantine - and everything the
pipeline derives (jobs, prefilter verdicts, decisions) plus the one thing that
cannot be regenerated: the user's application record.

All writes happen on the orchestrator thread. Fetch workers never touch the DB.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import RawJob, WatchedCompany, posting_key

SCHEMA_VERSION = 3

# A posting closes after this many successful fetches in a row leave it out (H1-1).
CLOSE_AFTER_MISSES = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,              -- stable identity; never the display name
    name TEXT NOT NULL,
    careers_url TEXT NOT NULL,
    provider TEXT, slug TEXT, feed_url TEXT,
    resolve_method TEXT, resolved_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_scraped_at TEXT,                  -- D-9: stamped on ATTEMPT
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_class TEXT, last_error TEXT,
    quarantined_at TEXT, probation_due_run INTEGER
);
CREATE INDEX IF NOT EXISTS idx_companies_due ON companies(enabled, last_scraped_at);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL,
    external_id TEXT, title TEXT, location TEXT, url TEXT, posted_at TEXT,
    jd_hash TEXT, jd_text TEXT, vital_text TEXT,
    jd_fetched_at TEXT,                    -- when jd_text was stored; it expires (M17)
    first_seen_run INTEGER, last_seen_run INTEGER, closed_at TEXT,
    missed_runs INTEGER NOT NULL DEFAULT 0 -- fetches in a row that left it out (H1-1)
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_run);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_run);

CREATE TABLE IF NOT EXISTS prefilter (
    job_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    rules_hash TEXT NOT NULL,              -- a verdict is valid only for its rules
    passed INTEGER NOT NULL,
    reject_rule TEXT, reject_detail TEXT, overlap_score INTEGER,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, profile_version, rules_hash)
);
CREATE INDEX IF NOT EXISTS idx_prefilter_rules
    ON prefilter(profile_version, rules_hash, passed);

CREATE TABLE IF NOT EXISTS decisions (
    job_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    vital_hash TEXT NOT NULL,              -- a changed description is re-decided
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject')),
    is_singapore INTEGER, yoe_min INTEGER, reason TEXT, model TEXT,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (job_id, profile_version, vital_hash)
);
CREATE INDEX IF NOT EXISTS idx_decisions_profile
    ON decisions(profile_version, decision, decided_at);

-- Times the model's answer for a posting could not be read, alone (AWS-2). At
-- 3 the posting is "undecidable" and is no longer sent. Keyed like a decision
-- plus the model, so a changed extract or a different model starts again.
CREATE TABLE IF NOT EXISTS decision_failures (
    job_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    vital_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    last_failed_at TEXT NOT NULL,
    PRIMARY KEY (job_id, profile_version, vital_hash, model)
);

CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    applied_at TEXT, notes TEXT,
    -- Kept on the row itself so an application whose posting is never scraped
    -- again (a migrated v1 row, D-14, or a closed role) still says what it was.
    company TEXT, role TEXT, url TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    from_status TEXT, to_status TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_events_job ON app_events(job_id, id);

CREATE TABLE IF NOT EXISTS runs (
    run_no INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL,                  -- running | ok | failed | aborted_unhealthy
    stats_json TEXT
);

CREATE TABLE IF NOT EXISTS coverage (
    run_no INTEGER NOT NULL, company_id INTEGER NOT NULL,
    status TEXT, postings_found INTEGER, new_count INTEGER, accepted_count INTEGER,
    http_status INTEGER, error_class TEXT, error TEXT, checked_at TEXT,
    PRIMARY KEY (run_no, company_id)
);

-- Values the user changes from the web app (M11). They cannot live in
-- config.yaml: Docker mounts config/ read-only. Values are text; the caller
-- that owns a key parses it.
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);

-- Roles marked "Not interested" in the Inbox (M17). They stay listed, in their
-- own section at the bottom, instead of coming back as new after a restart.
CREATE TABLE IF NOT EXISTS dismissals (
    job_id TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL
);

-- The user's own list of companies (M16), in their order of preference.
-- A found company also becomes a watched company: it is synced into
-- `companies` beside watchlist.yaml's entries (watchlist.all_entries).
CREATE TABLE IF NOT EXISTS company_list (
    position INTEGER PRIMARY KEY,      -- 1 = most wanted
    name TEXT NOT NULL,
    status TEXT NOT NULL,              -- pending | searching | found | watched | failed | over_limit
    company_key TEXT,                  -- the companies.key it is watched as
    careers_url TEXT, provider TEXT, slug TEXT, feed_url TEXT,
    postings INTEGER,                  -- open roles on the board when searched
    detail TEXT,                       -- what was found, or why the search failed
    searched_at TEXT
);

-- M20 apply (apply_design §13)
-- One row per auto-apply attempt. `state` is an AttemptState value (apply/contracts.py);
-- set_attempt_state refuses a transition the contract's table does not allow.
CREATE TABLE IF NOT EXISTS apply_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    company_id INTEGER,                    -- jobs.company_id at queue time (per-employer cap)
    ats TEXT, tenant_host TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('auto', 'dry_run')),
    state TEXT NOT NULL,                   -- AttemptState values
    step TEXT,                             -- current or last step id
    reason_code TEXT, reason_detail TEXT,  -- ReasonCode value; detail has no personal values
    end_url TEXT,                          -- page URL at the end, query string dropped
    plan_source TEXT,                      -- schema | dom
    resume_file TEXT, resume_sha256 TEXT,  -- file name only, and its hash
    resume_source TEXT,                    -- tailored | original
    tailored_id INTEGER,                   -- tailored.id when resume_source = tailored
    confirmation TEXT,                     -- signal that matched, or 'owner'
    code_resubmits INTEGER NOT NULL DEFAULT 0,
    queued_at TEXT NOT NULL, started_at TEXT, submit_clicked_at TEXT, finished_at TEXT,
    job_log TEXT                           -- the web job id (data/jobs/<id>.log), if started from the web
);
CREATE INDEX IF NOT EXISTS idx_attempts_job ON apply_attempts(job_id, id);
CREATE INDEX IF NOT EXISTS idx_attempts_clicked ON apply_attempts(submit_clicked_at);
-- NF-06: a posting can succeed only once.
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_one_success
    ON apply_attempts(job_id) WHERE state IN ('submitted', 'submitted_unconfirmed');

-- Every field of every attempt: what was asked, what was sent, where the answer came from (F-39).
CREATE TABLE IF NOT EXISTS apply_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    step TEXT NOT NULL DEFAULT '',
    field_key TEXT NOT NULL,
    label TEXT NOT NULL, label_norm TEXT NOT NULL,
    field_type TEXT NOT NULL, required INTEGER NOT NULL,
    section TEXT,
    options_json TEXT,                     -- [{"label":..,"value":..}] as offered
    value_json TEXT,                       -- exact value sent (JSON); NULL when blank
    tier INTEGER NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
    status TEXT NOT NULL,                  -- AnswerStatus values
    rule_id TEXT, model TEXT, prompt_hash TEXT, note TEXT,
    sensitive INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL,
    corrected_json TEXT, corrected_at TEXT -- M22 (F-12): the owner's correction
);
CREATE INDEX IF NOT EXISTS idx_answers_attempt ON apply_answers(attempt_id, id);

-- ATS accounts (M21, F-35). Never a password: that lives in Windows Credential Manager.
CREATE TABLE IF NOT EXISTS ats_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ats TEXT NOT NULL, tenant_host TEXT NOT NULL, email TEXT NOT NULL,
    vault_service TEXT NOT NULL,           -- the Credential Manager target; never the password
    status TEXT NOT NULL,                  -- creating | created | verified | signin_failed | unknown
    created_at TEXT NOT NULL, verified_at TEXT,
    last_signin_at TEXT, last_signin_ok INTEGER,
    exported_to_edge_at TEXT,
    created_by_attempt INTEGER,
    UNIQUE (ats, tenant_host, email)
);

-- Answers the owner corrected and asked to remember (resolver tier 3; M22 writes, M20 reads).
CREATE TABLE IF NOT EXISTS answer_memory (
    label_norm TEXT NOT NULL,
    field_type TEXT NOT NULL,
    ats TEXT NOT NULL DEFAULT '*',
    value_json TEXT NOT NULL,              -- choice fields: option label(s)
    source_answer_id INTEGER,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (label_norm, field_type, ats)
);

-- M20 tailor (tailor_design §11)
CREATE TABLE IF NOT EXISTS tailored (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,             -- §11.2
    resume_hash TEXT NOT NULL, jd_hash TEXT NOT NULL,
    mode TEXT NOT NULL,                    -- deterministic | llm
    model TEXT, options_json TEXT,         -- {"temperature":0.25,"top_k":20,"seed":7,"template":1}
    status TEXT NOT NULL CHECK (status IN ('draft', 'sent', 'failed')),
    created_at TEXT NOT NULL, sent_at TEXT, files_deleted_at TEXT,
    docx_name TEXT, docx_sha256 TEXT, pdf_name TEXT, pdf_sha256 TEXT,
    coverage_before REAL, coverage_after REAL, title_match INTEGER,
    terms_json TEXT,                       -- [{term, canonical, required, source, status, variant, via, related, attested}]
    knockouts_json TEXT,
    changes_json TEXT,                     -- BulletChange list + summary before/after; cleared when files are purged
    issues_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tailored_job ON tailored(job_id, id);

-- M20 questions (questions_design §7)
-- Required questions no resolver tier could answer, grouped by `key`. Employer text
-- only: the owner's answers live in data/applicant.yaml `extra:` (ADR-0005).
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sig TEXT NOT NULL UNIQUE,               -- questions_design §5.1
    key TEXT NOT NULL,                      -- extra key, or a profile path when target_path is set
    target_path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,                     -- QuestionKind
    label TEXT NOT NULL,                    -- verbatim, first seen (employer text)
    label_norm TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',-- [{"label": verbatim, "norm": normalised}] as first seen
    sensitive INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,                   -- QuestionReason, latest sighting
    named_by TEXT NOT NULL DEFAULT 'rule',  -- rule | model | profile
    status TEXT NOT NULL DEFAULT 'open',    -- QuestionStatus
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, answered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_questions_key ON questions(key);
CREATE TABLE IF NOT EXISTS question_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    attempt_id INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    company_id INTEGER,
    employer_norm TEXT NOT NULL DEFAULT '',
    ats TEXT NOT NULL DEFAULT '',
    step TEXT NOT NULL DEFAULT '',
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,                    -- verbatim as seen here
    required INTEGER NOT NULL,
    seen_at TEXT NOT NULL,
    UNIQUE (question_id, attempt_id, field_key)
);
CREATE INDEX IF NOT EXISTS idx_sightings_attempt ON question_sightings(attempt_id);
CREATE INDEX IF NOT EXISTS idx_sightings_question ON question_sightings(question_id);
"""

# The one status that does not mean "an application went out". Moving to any
# other status stamps `applied_at` the first time, and it is never re-stamped:
# the date you applied does not change because you later got an interview.
NOT_YET_APPLIED = frozenset({"to_apply"})

TIME_FMT = "%Y-%m-%dT%H:%M:%S"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime(TIME_FMT)


def shift(stamp: str, *, days: float = 0, seconds: float = 0) -> str:
    """`stamp` moved by a duration, in the same sortable text format.

    Cut-offs are computed here rather than with SQLite's `datetime('now', ...)`
    so the comparison stays plain SQL and tests can pin the clock.
    """
    t = datetime.strptime(stamp, TIME_FMT) + timedelta(days=days, seconds=seconds)
    return t.strftime(TIME_FMT)


def _b(v: Any) -> Optional[int]:
    return None if v is None else int(bool(v))


class SchemaMismatch(RuntimeError):
    """The file on disk is not a v2 database."""


class Store:
    def __init__(self, path: Path, check_same_thread: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        self._refuse_v1()
        # WAL lets the web app read while a run writes. SQLite-specific, and
        # harmless to drop on any other engine.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),))
        self.conn.commit()

    def _refuse_v1(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(companies)")}
        if cols and "key" not in cols:
            self.conn.close()
            raise SchemaMismatch(
                f"{self.path} holds the v1 schema. v2 does not migrate it: move it "
                "to archive/ and let the next run create a fresh database "
                "(PRD section 0.5).")

    def _migrate(self) -> None:
        """Columns added after a database was created: CREATE TABLE IF NOT
        EXISTS never changes a table that is already there."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        if "jd_fetched_at" not in cols:
            # When each stored description arrived. The posting's first run is
            # the best record an older database has.
            self.conn.execute("ALTER TABLE jobs ADD COLUMN jd_fetched_at TEXT")
            self.conn.execute(
                """UPDATE jobs SET jd_fetched_at = COALESCE(
                       (SELECT started_at FROM runs WHERE runs.run_no = jobs.first_seen_run), ?)
                    WHERE jd_text IS NOT NULL""", (utcnow(),))
        if "missed_runs" not in cols:
            # H1-1: every open posting starts from zero misses.
            self.conn.execute(
                "ALTER TABLE jobs ADD COLUMN missed_runs INTEGER NOT NULL DEFAULT 0")
        # M20 apply (apply_design §13, D-65): who wrote an application event.
        # NULL = the owner; 'jobscraper' = auto-apply ("Applied by JobScraper", F-37).
        ev_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(app_events)")}
        if "by" not in ev_cols:
            self.conn.execute("ALTER TABLE app_events ADD COLUMN by TEXT")
        # The new tables come from SCHEMA's CREATE TABLE IF NOT EXISTS; record the
        # version they belong to (an upsert: an older database already has a row).
        # Never downgrade: an older build opening a newer database keeps its number.
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = "
            "CAST(MAX(CAST(COALESCE(meta.value, '0') AS INTEGER), "
            "CAST(excluded.value AS INTEGER)) AS TEXT)",
            (str(SCHEMA_VERSION),))

    def ping(self) -> None:
        """Raise if the database cannot be read (GET /api/healthz, C-6)."""
        self.conn.execute("SELECT COUNT(*) FROM meta").fetchone()

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        """Drop uncommitted writes (a run that is being cancelled, C-4)."""
        self.conn.rollback()

    # ---------------- companies ----------------

    def _company(self, row: sqlite3.Row) -> WatchedCompany:
        return WatchedCompany(**{k: row[k] for k in row.keys()})

    def insert_company(self, key: str, name: str, careers_url: str,
                       provider: Optional[str] = None, slug: Optional[str] = None,
                       feed_url: Optional[str] = None, enabled: bool = True) -> int:
        """A brand-new company: `last_scraped_at` is NULL, so it is due at once."""
        cur = self.conn.execute(
            """INSERT INTO companies (key, name, careers_url, provider, slug,
               feed_url, enabled) VALUES (?,?,?,?,?,?,?)""",
            (key, name, careers_url, provider, slug, feed_url, int(enabled)))
        self.conn.commit()
        return int(cur.lastrowid)

    def sync_watchlist(self, entries: Iterable[Any]) -> dict[str, int]:
        """Reconcile the watchlist YAML into `companies` (PRD 8.4, normative).

        `entries` are watchlist entries (anything with key, name, careers_url,
        provider, slug, feed_url, enabled). Identity is `key`, never `name`:
        matching on the display name is exactly the bug this replaces - renaming
        "Shopee" silently made a new row, reset its staleness and orphaned its
        failure counters.

        - new key          -> insert; `last_scraped_at` NULL, so due next run
        - known key        -> update descriptive fields only; history untouched
        - careers_url moved -> clear the cached resolution, failure count,
                             quarantine and last_scraped_at: a new URL is a new
                             board, never checked, so it is due next run (D-9)
        - key gone from YAML -> enabled = 0, never deleted: jobs, decisions and
                             applications still point at the row
        """
        existing = {c.key: c for c in self.companies()}
        seen: set[str] = set()
        counts = {"added": 0, "updated": 0, "disabled": 0, "url_changed": 0}
        for e in entries:
            seen.add(e.key)
            row = existing.get(e.key)
            if row is None:
                self.conn.execute(
                    """INSERT INTO companies (key, name, careers_url, provider, slug,
                       feed_url, enabled) VALUES (?,?,?,?,?,?,?)""",
                    (e.key, e.name, e.careers_url, e.provider, e.slug, e.feed_url,
                     int(bool(e.enabled))))
                counts["added"] += 1
                continue
            if e.careers_url != row.careers_url:
                # Only what the YAML itself states survives a URL change;
                # anything discovery learned about the old board is void.
                self.conn.execute(
                    """UPDATE companies SET name = ?, careers_url = ?, enabled = ?,
                       provider = ?, slug = ?, feed_url = ?, resolve_method = NULL,
                       resolved_at = NULL, consecutive_failures = 0,
                       last_error_class = NULL, last_error = NULL,
                       quarantined_at = NULL, probation_due_run = NULL,
                       last_scraped_at = NULL
                       WHERE id = ?""",
                    (e.name, e.careers_url, int(bool(e.enabled)), e.provider,
                     e.slug, e.feed_url, row.id))
                counts["url_changed"] += 1
            else:
                # A resolution the YAML does not state is one discovery learned;
                # keep it rather than making the next run rediscover it.
                self.conn.execute(
                    """UPDATE companies SET name = ?, enabled = ?,
                       provider = COALESCE(?, provider), slug = COALESCE(?, slug),
                       feed_url = COALESCE(?, feed_url) WHERE id = ?""",
                    (e.name, int(bool(e.enabled)), e.provider, e.slug, e.feed_url,
                     row.id))
            counts["updated"] += 1
        for key, row in existing.items():
            if key not in seen and row.enabled:
                self.conn.execute(
                    "UPDATE companies SET enabled = 0 WHERE id = ?", (row.id,))
                counts["disabled"] += 1
        self.conn.commit()
        return counts

    def companies(self, enabled_only: bool = False) -> list[WatchedCompany]:
        sql = "SELECT * FROM companies"
        if enabled_only:
            sql += " WHERE enabled = 1"
        return [self._company(r) for r in self.conn.execute(sql + " ORDER BY id")]

    def get_company(self, cid: int) -> Optional[WatchedCompany]:
        r = self.conn.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
        return self._company(r) if r else None

    def company_by_key(self, key: str) -> Optional[WatchedCompany]:
        r = self.conn.execute("SELECT * FROM companies WHERE key = ?", (key,)).fetchone()
        return self._company(r) if r else None

    def set_resolution(self, cid: int, provider: str, slug: Optional[str],
                       feed_url: Optional[str], method: str) -> None:
        self.conn.execute(
            """UPDATE companies SET provider = ?, slug = ?, feed_url = ?,
               resolve_method = ?, resolved_at = ? WHERE id = ?""",
            (provider, slug, feed_url, method, utcnow(), cid))
        self.conn.commit()

    def clear_resolution(self, cid: int) -> None:
        """Forget a cached ATS resolution so discovery runs again."""
        self.conn.execute(
            """UPDATE companies SET provider = NULL, slug = NULL, feed_url = NULL,
               resolve_method = NULL, resolved_at = NULL WHERE id = ?""", (cid,))
        self.conn.commit()

    def record_success(self, cid: int) -> None:
        self.conn.execute(
            """UPDATE companies SET consecutive_failures = 0, last_success_at = ?,
               last_error_class = NULL, last_error = NULL,
               quarantined_at = NULL, probation_due_run = NULL WHERE id = ?""",
            (utcnow(), cid))
        self.conn.commit()

    def record_failure(self, cid: int, error_class: str, error: str) -> int:
        """Count a failed fetch; returns the new consecutive-failure count."""
        self.conn.execute(
            """UPDATE companies SET consecutive_failures = consecutive_failures + 1,
               last_error_class = ?, last_error = ? WHERE id = ?""",
            (error_class, (error or "")[:500], cid))
        self.conn.commit()
        r = self.conn.execute(
            "SELECT consecutive_failures FROM companies WHERE id = ?", (cid,)).fetchone()
        return int(r[0])

    def quarantine(self, cid: int, probation_due_run: int) -> None:
        self.conn.execute(
            """UPDATE companies SET quarantined_at = ?, probation_due_run = ?
               WHERE id = ?""", (utcnow(), probation_due_run, cid))
        self.conn.commit()

    def due_probation(self, run_no: int) -> list[WatchedCompany]:
        rows = self.conn.execute(
            """SELECT * FROM companies WHERE enabled = 1
               AND quarantined_at IS NOT NULL AND probation_due_run IS NOT NULL
               AND probation_due_run <= ? ORDER BY id""", (run_no,))
        return [self._company(r) for r in rows]

    def due_companies(self, cutoff: str, limit: int) -> list[WatchedCompany]:
        """The due query (PRD 8.3[0]): never-scraped first, then longest-neglected.

        `cutoff` is "now minus cycle_days"; anything last scraped at or before it
        is due. Quarantined companies are excluded here - they come back only
        through probation (`due_probation`), exactly as in v1. The CASE is the
        portable spelling of "NULLs first"; the id is a stable tie-break.
        Served by idx_companies_due.
        """
        rows = self.conn.execute(
            """SELECT * FROM companies
                WHERE enabled = 1 AND quarantined_at IS NULL
                  AND (last_scraped_at IS NULL OR last_scraped_at <= ?)
                ORDER BY CASE WHEN last_scraped_at IS NULL THEN 0 ELSE 1 END,
                         last_scraped_at, id
                LIMIT ?""", (cutoff, limit))
        return [self._company(r) for r in rows]

    def schedule_counts(self, cutoff: str, soon_cutoff: str) -> dict[str, Any]:
        """Numbers for the `status` report. `soon_cutoff` = cutoff + 7 days."""
        live = "enabled = 1 AND quarantined_at IS NULL"

        def q(where: str, *params: Any) -> int:
            return int(self.conn.execute(
                f"SELECT COUNT(*) FROM companies WHERE {where}", params).fetchone()[0])
        oldest = self.conn.execute(
            f"""SELECT MIN(last_scraped_at) FROM companies
                WHERE {live} AND last_scraped_at IS NOT NULL""").fetchone()[0]
        return {
            "enabled": q("enabled = 1"),
            "never_scraped": q(f"{live} AND last_scraped_at IS NULL"),
            "due_now": q(f"{live} AND (last_scraped_at IS NULL "
                         "OR last_scraped_at <= ?)", cutoff),
            "due_soon": q(f"{live} AND last_scraped_at > ? AND last_scraped_at <= ?",
                          cutoff, soon_cutoff),
            "quarantined": q("enabled = 1 AND quarantined_at IS NOT NULL"),
            "oldest_scrape": oldest,
        }

    def quarantined_companies(self) -> list[WatchedCompany]:
        return [self._company(r) for r in self.conn.execute(
            """SELECT * FROM companies WHERE enabled = 1
               AND quarantined_at IS NOT NULL ORDER BY name""")]

    def finished_runs_since(self, since: str) -> tuple[int, Optional[str]]:
        """(count, earliest start) of runs that reached the end since `since`.

        The observed run rate behind the sweep projection. A run that died is
        not a run that covered anything, so only `ok` counts.
        """
        r = self.conn.execute(
            """SELECT COUNT(*), MIN(started_at) FROM runs
               WHERE status = 'ok' AND started_at >= ?""", (since,)).fetchone()
        return int(r[0]), r[1]

    def stamp_scraped(self, cids: Iterable[int], at: Optional[str] = None) -> None:
        """Record an ATTEMPT (D-9). Called last in a run, so a crash stamps nothing."""
        stamp = at or utcnow()
        for cid in cids:
            self.conn.execute(
                "UPDATE companies SET last_scraped_at = ? WHERE id = ?", (stamp, cid))
        self.conn.commit()

    # ---------------- runs ----------------

    def start_run(self, at: Optional[str] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            (at or utcnow(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_no: int, status: str, stats: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, stats_json = ? WHERE run_no = ?",
            (utcnow(), status, json.dumps(stats, sort_keys=True), run_no))
        self.conn.commit()

    def reap_stale_runs(self, older_than_seconds: float,
                        now: Optional[str] = None) -> int:
        """Crash recovery (PRD 8.3[0]): a run still `running` past its timeout died.

        Its `last_scraped_at` stamps are deliberately left alone - re-fetching
        early would let a crash loop monopolise the queue.
        """
        cutoff = shift(now or utcnow(), seconds=-older_than_seconds)
        cur = self.conn.execute(
            """UPDATE runs SET status = 'failed', finished_at = ?
               WHERE status = 'running' AND started_at <= ?""",
            (now or utcnow(), cutoff))
        self.conn.commit()
        return cur.rowcount

    def fail_running_runs(self, since: str, reason: str) -> int:
        """Mark every run still `running` that started at or after `since`
        failed, with `stats.reason` set (its other stats kept). For a run whose
        process was killed before its own `finally` could say so (the web
        app's Cancel, D-64). Returns how many rows changed."""
        rows = self.conn.execute(
            "SELECT run_no, stats_json FROM runs WHERE status = 'running' AND started_at >= ?",
            (since,)).fetchall()
        now = utcnow()
        for run_no, stats_json in rows:
            try:
                stats = json.loads(stats_json or "{}")
            except ValueError:
                stats = {}
            stats = stats if isinstance(stats, dict) else {}
            stats["reason"] = reason
            self.conn.execute(
                """UPDATE runs SET status = 'failed', finished_at = ?, stats_json = ?
                   WHERE run_no = ? AND status = 'running'""",
                (now, json.dumps(stats, sort_keys=True), run_no))
        self.conn.commit()
        return len(rows)

    def last_run_no(self) -> int:
        v = self.conn.execute("SELECT MAX(run_no) FROM runs").fetchone()[0]
        return int(v or 0)

    def list_runs(self) -> list[dict[str, Any]]:
        """Newest first, with `stats` parsed. Feeds the web app's run selector."""
        out = []
        for r in self.conn.execute("SELECT * FROM runs ORDER BY run_no DESC"):
            d = dict(r)
            d["stats"] = json.loads(d.pop("stats_json") or "{}")
            out.append(d)
        return out

    def record_coverage(self, run_no: int, company_id: int, status: str,
                        postings: int, new: int, accepted: int,
                        http_status: Optional[int], error_class: Optional[str],
                        error: Optional[str]) -> None:
        # INSERT OR REPLACE is SQLite dialect; a re-recorded company in the same
        # run simply supersedes its earlier row.
        self.conn.execute(
            """INSERT OR REPLACE INTO coverage (run_no, company_id, status,
               postings_found, new_count, accepted_count, http_status,
               error_class, error, checked_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_no, company_id, status, postings, new, accepted, http_status,
             error_class, (error or "")[:500], utcnow()))
        self.conn.commit()

    # ---------------- jobs ----------------

    def known_job_ids(self, company_id: int) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT job_id FROM jobs WHERE company_id = ?", (company_id,))}

    def upsert_job(self, job_id: str, company_id: int, raw: RawJob,
                   run_no: int, is_new: bool) -> None:
        """Insert a new posting, or mark a known one seen (and reopened) this run.

        Does not commit: a run persists a company's jobs as one batch.
        """
        if is_new:
            # ON CONFLICT rather than INSERT OR REPLACE: should the caller's
            # "is new" ever be stale, a replace would silently reset
            # first_seen_run; this degrades to "seen again" instead.
            self.conn.execute(
                """INSERT INTO jobs (job_id, company_id, external_id,
                   title, location, url, posted_at, jd_hash, jd_text, vital_text,
                   jd_fetched_at, first_seen_run, last_seen_run, closed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?,NULL)
                   ON CONFLICT (job_id) DO UPDATE SET
                       last_seen_run = excluded.last_seen_run, closed_at = NULL,
                       missed_runs = 0""",
                (job_id, company_id, raw.external_id, raw.title, raw.location,
                 raw.url, raw.posted_at, raw.jd_hash(), raw.description,
                 utcnow() if raw.description else None, run_no, run_no))
        else:
            self.conn.execute(
                """UPDATE jobs SET last_seen_run = ?, closed_at = NULL, missed_runs = 0
                   WHERE job_id = ?""",
                (run_no, job_id))

    def close_missing(self, company_id: int, seen: set[str], *,
                      after: int = CLOSE_AFTER_MISSES) -> int:
        """Count a miss for each open job absent from a SUCCESSFUL fetch, and
        close the ones missed `after` fetches in a row. Returns how many closed.

        One miss is not enough (H1-1): a board can leave a posting out of one
        answer - a paging blip, a facet edge - without taking it down. Never
        call this after a failed, skipped, empty or capped fetch: those say
        nothing about what was taken down, and would otherwise mass-close a
        company's postings and corrupt the next delta. Seeing a job again
        (upsert_job) resets its count. "In a row" means successful fetches in a
        row: a failed fetch between two misses neither counts nor resets, since
        it says nothing either way.
        """
        rows = [(r[0], r[1]) for r in self.conn.execute(
            "SELECT job_id, missed_runs FROM jobs WHERE company_id = ? AND closed_at IS NULL",
            (company_id,)) if r[0] not in seen]
        now = utcnow()
        closed = 0
        for jid, missed in rows:
            missed = (missed or 0) + 1
            if missed >= after:
                self.conn.execute("UPDATE jobs SET missed_runs = ?, closed_at = ? WHERE job_id = ?",
                                  (missed, now, jid))
                closed += 1
            else:
                self.conn.execute("UPDATE jobs SET missed_runs = ? WHERE job_id = ?", (missed, jid))
        self.conn.commit()
        return closed

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            """SELECT j.*, co.name AS company FROM jobs j
               JOIN companies co ON co.id = j.company_id WHERE j.job_id = ?""",
            (job_id,)).fetchone()
        return dict(r) if r else None

    _JOB_WITH_COMPANY = """SELECT j.*, co.name AS company, co.key AS company_key,
                                  co.provider, co.slug, co.feed_url, co.careers_url
                             FROM jobs j JOIN companies co ON co.id = j.company_id"""

    def jobs_pending_prefilter(self, profile_version: int,
                               rules_hash: str) -> list[dict[str, Any]]:
        """Open postings with no verdict for these rules and this profile.

        Not "this run's new postings": anything unevaluated qualifies, so a
        rules edit (new rules_hash) re-checks the whole open corpus for free,
        and a run that died before its prefilter is caught up by the next.
        """
        return [dict(r) for r in self.conn.execute(
            self._JOB_WITH_COMPANY + """
             WHERE j.closed_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM prefilter p
                                WHERE p.job_id = j.job_id AND p.profile_version = ?
                                  AND p.rules_hash = ?)
             ORDER BY j.job_id""", (profile_version, rules_hash))]

    def jobs_passed_prefilter(self, profile_version: int,
                              rules_hash: str) -> list[dict[str, Any]]:
        """Open postings the current rules let through: the decide stage's input."""
        return [dict(r) for r in self.conn.execute(
            self._JOB_WITH_COMPANY + """
              JOIN prefilter p ON p.job_id = j.job_id
             WHERE j.closed_at IS NULL AND p.passed = 1
               AND p.profile_version = ? AND p.rules_hash = ?
             ORDER BY j.job_id""", (profile_version, rules_hash))]

    def set_description(self, job_id: str, text: str) -> None:
        """Store a description fetched after the listing (hydration)."""
        self.conn.execute("UPDATE jobs SET jd_text = ?, jd_fetched_at = ? WHERE job_id = ?",
                          (text, utcnow() if text else None, job_id))
        self.conn.commit()

    def set_vital(self, job_id: str, vital_text: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET vital_text = ? WHERE job_id = ?", (vital_text, job_id))
        self.conn.commit()

    def purge_descriptions(self, older_than_days: float, now: Optional[str] = None) -> int:
        """Delete stored descriptions older than their time to live (M17), to
        keep the database small. Kept: roles the judge accepted - the Inbox
        shows their description - and roles with an application. Each
        posting's short `vital_text`, what the judge reads, is never deleted,
        so nothing is re-judged; a purged posting that passes the prefilter
        again simply has its description fetched again."""
        cutoff = shift(now or utcnow(), days=-float(older_than_days))
        cur = self.conn.execute(
            """UPDATE jobs SET jd_text = NULL, jd_fetched_at = NULL
                WHERE jd_text IS NOT NULL AND jd_fetched_at < ?
                  AND job_id NOT IN (SELECT job_id FROM decisions WHERE decision = 'accept')
                  AND job_id NOT IN (SELECT job_id FROM applications)""", (cutoff,))
        self.conn.commit()
        return int(cur.rowcount or 0)

    def compact(self) -> bool:
        """Give freed space back to the disk (VACUUM). False when another
        connection is using the database; the next run tries again."""
        try:
            self.conn.execute("VACUUM")
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except sqlite3.OperationalError:
            return False

    def find_job_by_url(self, url: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            "SELECT * FROM jobs WHERE url = ? ORDER BY first_seen_run LIMIT 1",
            (url,)).fetchone()
        return dict(r) if r else None

    # ---------------- prefilter ----------------

    def save_prefilter(self, job_id: str, profile_version: int, rules_hash: str,
                       passed: bool, reject_rule: Optional[str] = None,
                       reject_detail: Optional[str] = None,
                       overlap_score: Optional[int] = None) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO prefilter (job_id, profile_version, rules_hash,
               passed, reject_rule, reject_detail, overlap_score, evaluated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, profile_version, rules_hash, int(passed), reject_rule,
             reject_detail, overlap_score, utcnow()))
        self.conn.commit()

    def get_prefilter(self, job_id: str, profile_version: int,
                      rules_hash: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            """SELECT * FROM prefilter WHERE job_id = ? AND profile_version = ?
               AND rules_hash = ?""", (job_id, profile_version, rules_hash)).fetchone()
        return dict(r) if r else None

    # ---------------- decisions ----------------

    def get_decision(self, job_id: str, profile_version: int,
                     vital_hash: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            """SELECT * FROM decisions WHERE job_id = ? AND profile_version = ?
               AND vital_hash = ?""", (job_id, profile_version, vital_hash)).fetchone()
        return dict(r) if r else None

    def save_decision(self, job_id: str, profile_version: int, vital_hash: str,
                      decision: str, is_singapore: Optional[bool],
                      yoe_min: Optional[int], reason: str, model: str) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO decisions (job_id, profile_version, vital_hash,
               decision, is_singapore, yoe_min, reason, model, decided_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, profile_version, vital_hash, decision, _b(is_singapore),
             yoe_min, reason, model, utcnow()))
        self.conn.commit()

    def decision_failures(self, job_id: str, profile_version: int, vital_hash: str,
                          model: str) -> int:
        """How many times this model's answer for this extract was unreadable."""
        r = self.conn.execute(
            """SELECT failures FROM decision_failures WHERE job_id = ?
               AND profile_version = ? AND vital_hash = ? AND model = ?""",
            (job_id, profile_version, vital_hash, model)).fetchone()
        return int(r[0]) if r else 0

    def add_decision_failure(self, job_id: str, profile_version: int,
                             vital_hash: str, model: str) -> int:
        """Count one more unreadable answer; returns the new total."""
        self.conn.execute(
            """INSERT INTO decision_failures (job_id, profile_version, vital_hash,
               model, failures, last_failed_at) VALUES (?,?,?,?,1,?)
               ON CONFLICT (job_id, profile_version, vital_hash, model)
               DO UPDATE SET failures = failures + 1, last_failed_at = excluded.last_failed_at""",
            (job_id, profile_version, vital_hash, model, utcnow()))
        self.conn.commit()
        return self.decision_failures(job_id, profile_version, vital_hash, model)

    def accepted_jobs(self, profile_version: int,
                      rules_hash: Optional[str] = None) -> list[dict[str, Any]]:
        """Every accepted posting for this profile, with the run that found it.

        The shortlist's raw material (M5-T1). Where a posting was decided more
        than once (its description changed) the newest decision wins. With
        `rules_hash`, a posting must also pass the CURRENT prefilter: a rules
        edit that would now reject a role withdraws it from the shortlist rather
        than leaving it standing on a decision made under the old rules.
        """
        current = ""
        params: tuple = (profile_version,)
        if rules_hash is not None:
            current = """
                  AND EXISTS (SELECT 1 FROM prefilter p
                               WHERE p.job_id = j.job_id AND p.passed = 1
                                 AND p.profile_version = ? AND p.rules_hash = ?)"""
            params = (profile_version, profile_version, rules_hash)
        return [dict(r) for r in self.conn.execute(
            """SELECT j.job_id, j.first_seen_run AS run_no, co.name AS company,
                      j.title, j.url, j.location, j.posted_at, j.closed_at,
                      d.yoe_min, d.reason, d.decided_at
                 FROM decisions d
                 JOIN jobs j       ON j.job_id = d.job_id
                 JOIN companies co ON co.id = j.company_id
                WHERE d.profile_version = ? AND d.decision = 'accept'
                  -- Newest wins; rowid breaks a same-second tie (SQLite's
                  -- implicit row id - a Postgres port would use a serial).
                  AND d.rowid = (SELECT d2.rowid FROM decisions d2
                                  WHERE d2.job_id = d.job_id
                                    AND d2.profile_version = d.profile_version
                                  ORDER BY d2.decided_at DESC, d2.rowid DESC
                                  LIMIT 1)""" + current + """
                ORDER BY j.job_id""", params)]

    # ---------------- applications ----------------

    def application(self, job_id: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        return dict(r) if r else None

    def set_application_status(self, job_id: str, status: str,
                               notes: Optional[str] = None, *,
                               company: Optional[str] = None,
                               role: Optional[str] = None,
                               url: Optional[str] = None,
                               at: Optional[str] = None,
                               applied_at: Optional[str] = None,
                               by: Optional[str] = None) -> bool:
        """Upsert an application; append to `app_events` only on a real change.

        Returns whether an event was appended - re-posting the same status is a
        no-op for the history (M6-T2), though `notes` still updates. `applied_at`
        is stamped the first time the status leaves NOT_YET_APPLIED and is never
        re-stamped afterwards. `applied_at` overrides that stamp's date - only
        for importing a record whose real date is known (M3-T3b). `by` names who
        made the change on the event row: None is the owner, 'jobscraper' is
        auto-apply (M20, apply_design §13).
        """
        now = at or utcnow()
        prev = self.application(job_id)
        prev_status = prev["status"] if prev else None
        stamp = applied_at
        applied_at = prev["applied_at"] if prev else None
        if applied_at is None and status not in NOT_YET_APPLIED:
            applied_at = stamp or now[:10]

        if prev is None:
            self.conn.execute(
                """INSERT INTO applications (job_id, status, applied_at, notes,
                   company, role, url, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                (job_id, status, applied_at, notes, company, role, url, now))
        else:
            self.conn.execute(
                """UPDATE applications SET status = ?, applied_at = ?,
                   notes = COALESCE(?, notes), company = COALESCE(?, company),
                   role = COALESCE(?, role), url = COALESCE(?, url),
                   updated_at = ? WHERE job_id = ?""",
                (status, applied_at, notes, company, role, url, now, job_id))

        changed = prev_status != status
        if changed:
            self.conn.execute(
                """INSERT INTO app_events (job_id, from_status, to_status, at, by)
                   VALUES (?,?,?,?,?)""", (job_id, prev_status, status, now, by))
        self.conn.commit()
        return changed

    def delete_application(self, job_id: str) -> bool:
        """Forget an application and its history: the role is untracked again.

        This is the web app's Undo for "Mark applied" / "Save" (M13) - the role
        goes back to the Inbox as if it had never been touched. Returns whether
        there was anything to delete.
        """
        cur = self.conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
        self.conn.execute("DELETE FROM app_events WHERE job_id = ?", (job_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def relink_orphan_applications(self) -> int:
        """Point applications at their posting once it has been scraped.

        A migrated v1 application (D-14) carries a v1 job id that no v2 job has,
        because v1 hashed ids with a company id that no longer means anything.
        Its URL is the durable link: when a scraped job has the same URL, the
        application and its history move onto that job id. Safe to run every
        run; returns how many moved.
        """
        orphans = self.conn.execute(
            """SELECT a.job_id, a.url FROM applications a
               WHERE a.url IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_id = a.job_id)"""
        ).fetchall()
        moved = 0
        for o in orphans:
            job = self.find_job_by_url(o["url"])
            if not job or self.application(job["job_id"]):
                continue
            self.conn.execute("UPDATE applications SET job_id = ? WHERE job_id = ?",
                              (job["job_id"], o["job_id"]))
            self.conn.execute("UPDATE app_events SET job_id = ? WHERE job_id = ?",
                              (job["job_id"], o["job_id"]))
            moved += 1
        self.conn.commit()
        return moved

    # ---------------- Not interested (M17) ----------------

    def dismissals(self) -> dict[str, str]:
        """Job id -> when it was marked Not interested."""
        return {r["job_id"]: r["dismissed_at"] for r in self.conn.execute(
            "SELECT job_id, dismissed_at FROM dismissals")}

    def dismiss(self, job_id: str) -> str:
        """Mark a role Not interested; marking it again keeps the first time."""
        self.conn.execute(
            "INSERT INTO dismissals (job_id, dismissed_at) VALUES (?, ?) "
            "ON CONFLICT (job_id) DO NOTHING", (job_id, utcnow()))
        self.conn.commit()
        return self.conn.execute(
            "SELECT dismissed_at FROM dismissals WHERE job_id = ?", (job_id,)).fetchone()[0]

    def undismiss(self, job_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM dismissals WHERE job_id = ?", (job_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---------------- company health (M17) ----------------

    def company_health(self) -> list[dict[str, Any]]:
        """Every enabled company with its failure record and its latest scan."""
        return [dict(r) for r in self.conn.execute(
            """SELECT co.key, co.name, co.careers_url, co.provider, co.slug, co.feed_url,
                      co.last_scraped_at, co.last_success_at, co.consecutive_failures,
                      co.last_error_class, co.last_error, co.quarantined_at,
                      cv.status AS last_status, cv.postings_found AS last_postings,
                      cv.http_status AS last_http_status
                 FROM companies co
                 LEFT JOIN coverage cv ON cv.company_id = co.id
                  AND cv.run_no = (SELECT MAX(run_no) FROM coverage WHERE company_id = co.id)
                WHERE co.enabled = 1
                ORDER BY co.name COLLATE NOCASE""")]

    def applications(self) -> list[dict[str, Any]]:
        """Everything with a status, newest change first.

        LEFT JOINs, so an application whose posting is not (or no longer) in
        `jobs` still appears, described by the fields kept on its own row.
        """
        return [dict(r) for r in self.conn.execute(
            """SELECT a.job_id, a.status, a.applied_at, a.notes, a.updated_at,
                      COALESCE(a.company, co.name) AS company,
                      COALESCE(a.role, j.title)    AS role,
                      COALESCE(a.url, j.url)       AS url,
                      j.location, j.closed_at
                 FROM applications a
                 LEFT JOIN jobs j       ON j.job_id = a.job_id
                 LEFT JOIN companies co ON co.id = j.company_id
                ORDER BY a.updated_at DESC, a.job_id""")]

    def application_statuses(self) -> dict[str, str]:
        """job_id -> status. What the web app joins onto the shortlist (D-5)."""
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT job_id, status FROM applications")}

    def application_events(self, job_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            """SELECT id, job_id, from_status, to_status, at FROM app_events
               WHERE job_id = ? ORDER BY id""", (job_id,))]

    # ---------------- settings ----------------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """The stored value for `key` as text, or `default` when it is unset."""
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?",
                                (key,)).fetchone()
        return default if row is None or row["value"] is None else str(row["value"])

    def set_setting(self, key: str, value: Any) -> None:
        """Store `value` (as text) under `key`, replacing any earlier value.

        `ON CONFLICT ... DO UPDATE` is the upsert both SQLite and Postgres
        speak, so this stays portable (PRD 8.4).
        """
        self.conn.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT (key) DO UPDATE
               SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, None if value is None else str(value), utcnow()))
        self.conn.commit()

    # ---------------- the user's company list (M16) ----------------

    COMPANY_LIST_FIELDS = ("status", "company_key", "careers_url", "provider", "slug",
                           "feed_url", "postings", "detail", "searched_at")

    def company_list(self) -> list[dict[str, Any]]:
        """The uploaded list, in the user's order of preference."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM company_list ORDER BY position")]

    def replace_company_list(self, names: list[str]) -> dict[str, int]:
        """Store a new list, in the order given. A name searched before keeps
        its result (matched ignoring case), so re-uploading an edited list only
        searches what is new; one left mid-search or over the plan's limit is
        searched again. Returns how many results were kept, how many names are
        new, and how many of the old list were dropped."""
        old = {r["name"].lower(): r for r in self.company_list()}
        rows, kept = [], 0
        for i, name in enumerate(names, 1):
            prev = old.get(name.lower())
            if prev and prev["status"] in ("found", "watched", "failed"):
                rows.append(dict(prev, position=i, name=name))
                kept += 1
            else:
                rows.append({"position": i, "name": name, "status": "pending"})
        self.conn.execute("DELETE FROM company_list")
        cols = ("position", "name") + self.COMPANY_LIST_FIELDS
        for row in rows:
            self.conn.execute(
                f"INSERT INTO company_list ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                tuple(row.get(c) for c in cols))
        self.conn.commit()
        dropped = len({n for n in old} - {n.lower() for n in names})
        return {"kept": kept, "new": len(rows) - kept, "dropped": dropped}

    def update_company_list_entry(self, position: int, **fields: Any) -> None:
        cols = [c for c in fields if c in self.COMPANY_LIST_FIELDS]
        if not cols:
            return
        self.conn.execute(
            f"UPDATE company_list SET {', '.join(f'{c} = ?' for c in cols)} "
            "WHERE position = ?", tuple(fields[c] for c in cols) + (position,))
        self.conn.commit()

    def company_list_ranks(self) -> dict[str, int]:
        """Company name (lowercase) -> the user's rank, for every company of the
        uploaded list that is watched. Both the name the user typed and the
        name it is watched under count, so a job from "OKX" ranks whether the
        user wrote "OKX" or "okx.com"."""
        out: dict[str, int] = {}
        for r in self.conn.execute(
                """SELECT l.position, l.name, c.name AS company FROM company_list l
                   LEFT JOIN companies c ON c.key = l.company_key
                   WHERE l.status IN ('found', 'watched') ORDER BY l.position"""):
            for n in (r["name"], r["company"]):
                if n:
                    out.setdefault(n.lower(), r["position"])
        return out

    # ---------------- reporting ----------------

    def stats(self) -> dict[str, int]:
        def q(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])
        return {
            "companies": q("SELECT COUNT(*) FROM companies"),
            "enabled": q("SELECT COUNT(*) FROM companies WHERE enabled = 1"),
            "resolved": q("SELECT COUNT(*) FROM companies WHERE provider IS NOT NULL"),
            "quarantined": q(
                "SELECT COUNT(*) FROM companies WHERE quarantined_at IS NOT NULL"),
            "jobs": q("SELECT COUNT(*) FROM jobs"),
            "open_jobs": q("SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL"),
            "runs": q("SELECT COUNT(*) FROM runs"),
            "applications": q("SELECT COUNT(*) FROM applications"),
        }

    # ---------------- apply (M20) ----------------
    #
    # Auto-apply attempts, their audit rows, ATS accounts and answer memory
    # (apply_design §13). States and reason codes are the string values of
    # apply/contracts.py's AttemptState / ReasonCode: the store is the bottom
    # of the stack and may not import a stage package (tests/test_layering.py),
    # so it keeps the transition table as plain strings in ATTEMPT_TRANSITIONS
    # below, and apply_flow checks at import that it equals the contract's.

    def job_for_apply(self, job_id: str) -> Optional[dict[str, Any]]:
        """A job with its company's name, key, provider and slug (what ATS
        detection reads, apply_design §9.0), or None."""
        r = self.conn.execute(self._JOB_WITH_COMPANY + " WHERE j.job_id = ?",
                              (job_id,)).fetchone()
        return dict(r) if r else None

    def create_attempt(self, job_id: str, company_id: Optional[int], mode: str,
                       now: str) -> int:
        """A new `queued` attempt. Does not commit."""
        cur = self.conn.execute(
            """INSERT INTO apply_attempts (job_id, company_id, mode, state, queued_at)
               VALUES (?,?,?,'queued',?)""", (job_id, company_id, mode, now))
        return int(cur.lastrowid)

    def set_attempt_state(self, attempt_id: int, state: Any, *,
                          step: Optional[str] = None, reason: Any = None,
                          detail: Optional[str] = None, **cols: Any) -> None:
        """Move an attempt to `state`, refusing what the contract forbids.

        Raises ValueError for a transition `TRANSITIONS` does not allow, and for
        any state but the post-click ones once `submit_clicked_at` is set (NF-06,
        D-69: a clicked attempt ends only submitted or submitted_unconfirmed).
        `cols` sets other `apply_attempts` columns in the same write (names are
        checked against the table). A terminal state stamps `finished_at`, the
        first move out of `queued` stamps `started_at`. Does not commit.
        """
        dst = _state(state)
        row = self.conn.execute(
            "SELECT state, submit_clicked_at FROM apply_attempts WHERE id = ?",
            (attempt_id,)).fetchone()
        if row is None:
            raise ValueError(f"no attempt {attempt_id}")
        src, clicked = row["state"], row["submit_clicked_at"] is not None
        if not attempt_transition_allowed(src, dst, clicked=clicked):
            raise ValueError(f"attempt {attempt_id}: {src} -> {dst} is not allowed"
                             + (" after the Submit click" if clicked else ""))
        sets: dict[str, Any] = {"state": dst}
        if step is not None:
            sets["step"] = step
        if reason is not None:
            sets["reason_code"] = _state(reason)
        if detail is not None:
            sets["reason_detail"] = detail
        for k, v in cols.items():
            if k not in _ATTEMPT_COLUMNS:
                raise ValueError(f"apply_attempts has no column {k!r}")
            sets[k] = v
        now = utcnow()
        if dst in TERMINAL_ATTEMPT_STATES and "finished_at" not in sets:
            sets["finished_at"] = now
        assignments = ", ".join(f"{k} = ?" for k in sets)
        if src == "queued":
            assignments += ", started_at = COALESCE(started_at, ?)"
            params = [*sets.values(), now, attempt_id]
        else:
            params = [*sets.values(), attempt_id]
        self.conn.execute(f"UPDATE apply_attempts SET {assignments} WHERE id = ?", params)

    def update_attempt(self, attempt_id: int, **cols: Any) -> None:
        """Set columns other than `state` (the resume file, the end URL).
        Does not commit."""
        bad = [k for k in cols if k not in _ATTEMPT_COLUMNS or k == "state"]
        if bad:
            raise ValueError(f"cannot set {bad} on apply_attempts here")
        if cols:
            self.conn.execute(
                f"UPDATE apply_attempts SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                [*cols.values(), attempt_id])

    def mark_submit_clicked(self, attempt_id: int, now: str) -> bool:
        """Record that Submit is about to be clicked. The caller commits this
        BEFORE the click (NF-06): from here the attempt can only end
        submitted or submitted_unconfirmed, and it counts against the caps.

        A compare-and-set (review F4): it stamps only a live `filling` attempt
        that has no click yet, and returns whether it did. False means the row
        was closed meanwhile (e.g. reaped) or already clicked: do not click."""
        cur = self.conn.execute(
            "UPDATE apply_attempts SET submit_clicked_at = ? "
            "WHERE id = ? AND state = 'filling' AND submit_clicked_at IS NULL", (now, attempt_id))
        return cur.rowcount == 1

    def begin_immediate(self) -> None:
        """Start a write transaction now (SQLite BEGIN IMMEDIATE), so checks
        read in it cannot be overtaken by another writer before the commit
        (the pre-click duplicate + cap re-check, review F4). Commits anything
        pending first."""
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")

    def attempt(self, attempt_id: int) -> Optional[dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM apply_attempts WHERE id = ?",
                              (attempt_id,)).fetchone()
        return dict(r) if r else None

    def attempts_for_job(self, job_id: str) -> list[dict[str, Any]]:
        """A job's attempts, oldest first."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM apply_attempts WHERE job_id = ? ORDER BY id", (job_id,))]

    def attempts_in_flight(self, exclude_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Attempts in a non-terminal state other than `queued` (apply_design
        §12.1 (4): one in flight)."""
        live = sorted(set(ATTEMPT_TRANSITIONS) - TERMINAL_ATTEMPT_STATES - {"queued"})
        marks = ",".join("?" * len(live))
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM apply_attempts WHERE state IN ({marks}) AND id != ? ORDER BY id",
            (*live, -1 if exclude_id is None else exclude_id))]

    def reap_attempts(self, now: str) -> int:
        """Close attempts left in a non-terminal state by a run that died or was
        cancelled (apply_design §4.3). The caller makes sure no apply job is
        running. Clicked → submitted_unconfirmed (never failed, never
        resubmitted); not clicked → failed(cancelled). An attempt in a
        post-click-only state (`submitting`; `verifying_email` also occurs before a click) counts
        as clicked even without a stamp (review F2: a missed stamp must never
        free the posting). Returns how many. Commits."""
        live = sorted(set(ATTEMPT_TRANSITIONS) - TERMINAL_ATTEMPT_STATES)
        marks = ",".join("?" * len(live))
        rows = self.conn.execute(
            f"SELECT id, state, submit_clicked_at FROM apply_attempts WHERE state IN ({marks})",
            live).fetchall()
        for r in rows:
            if r["submit_clicked_at"] or r["state"] == "submitting":
                self.conn.execute(
                    """UPDATE apply_attempts SET state = 'submitted_unconfirmed',
                       reason_detail = COALESCE(reason_detail, 'interrupted after submit'),
                       finished_at = ? WHERE id = ?""", (now, r["id"]))
            else:
                self.conn.execute(
                    """UPDATE apply_attempts SET state = 'failed', reason_code = 'cancelled',
                       reason_detail = 'interrupted', finished_at = ? WHERE id = ?""",
                    (now, r["id"]))
        self.conn.commit()
        return len(rows)

    def apply_duplicate(self, job_id: str) -> Optional[str]:
        """Why this job must not be applied to again, or None (apply_design
        §12.1 (2), NF-06). Checks, in order: the job's own application; a twin
        (another job id with the same posting URL, M17) that is applied; an
        attempt for the job or a twin that clicked Submit or succeeded."""
        app = self.application(job_id)
        if app and app["status"] not in NOT_YET_APPLIED:
            return f"applied {app['applied_at'] or ''}".strip()
        job = self.get_job(job_id)
        key = posting_key(job["url"]) if job else ""
        if key:
            for a in self.conn.execute(
                    """SELECT a.job_id, COALESCE(a.url, j.url) AS url,
                              COALESCE(a.company, co.name) AS company,
                              COALESCE(a.role, j.title) AS role
                         FROM applications a
                         LEFT JOIN jobs j ON j.job_id = a.job_id
                         LEFT JOIN companies co ON co.id = j.company_id
                        WHERE a.status NOT IN ('to_apply') AND a.job_id != ?""", (job_id,)):
                if posting_key(a["url"]) == key:
                    return f"same posting as {a['company'] or '?'} · {a['role'] or '?'}"
        for a in self.conn.execute(
                """SELECT at.job_id, j.url FROM apply_attempts at
                     LEFT JOIN jobs j ON j.job_id = at.job_id
                    WHERE at.submit_clicked_at IS NOT NULL
                       OR at.state IN ('submitted', 'submitted_unconfirmed')"""):
            if a["job_id"] == job_id or (key and posting_key(a["url"]) == key):
                return "already submitted by JobScraper"
        return None

    def apply_counts(self, company_id: Optional[int], day_start: str) -> tuple[int, int]:
        """(today_total, today_at_this_employer): attempts whose Submit was
        clicked at or after `day_start` (UTC text; the caller computes the
        Asia/Singapore midnight). Dry runs never click, so never count (D-61)."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM apply_attempts WHERE submit_clicked_at >= ?",
            (day_start,)).fetchone()[0]
        employer = self.conn.execute(
            "SELECT COUNT(*) FROM apply_attempts WHERE submit_clicked_at >= ? AND company_id = ?",
            (day_start, company_id)).fetchone()[0]
        return int(total), int(employer)

    def applied_to_company(self, company_id: Optional[int], exclude_job_id: str) -> bool:
        """Has the owner applied to this employer before, for another job
        (apply_design §12.3, the resolver's `previously_applied`)?"""
        if company_id is None:
            return False
        r = self.conn.execute(
            """SELECT 1 FROM applications a JOIN jobs j ON j.job_id = a.job_id
                WHERE j.company_id = ? AND a.job_id != ? AND a.status NOT IN ('to_apply')
               UNION ALL
               SELECT 1 FROM apply_attempts at
                WHERE at.company_id = ? AND at.job_id != ? AND at.submit_clicked_at IS NOT NULL
               LIMIT 1""", (company_id, exclude_job_id, company_id, exclude_job_id)).fetchone()
        return r is not None

    _ANSWER_COLUMNS = ("step", "field_key", "label", "label_norm", "field_type", "required",
                       "section", "options_json", "value_json", "tier", "source",
                       "confidence", "status", "rule_id", "model", "prompt_hash", "note",
                       "sensitive", "recorded_at")

    def add_answers(self, attempt_id: int, rows: Iterable[dict[str, Any]]) -> int:
        """Append audit rows (apply_design §7.8). Each row is a dict with the
        `apply_answers` columns; `options_json` / `value_json` may be given as
        Python values (they are JSON-encoded here). Does not commit."""
        n = 0
        cols = ", ".join(("attempt_id",) + self._ANSWER_COLUMNS)
        marks = ",".join("?" * (len(self._ANSWER_COLUMNS) + 1))
        for row in rows:
            vals = []
            for c in self._ANSWER_COLUMNS:
                v = row.get(c)
                if c in ("options_json", "value_json") and v is not None and not isinstance(v, str):
                    v = json.dumps(v, ensure_ascii=False)
                elif c in ("required", "sensitive"):
                    v = int(bool(v))
                elif c == "step":
                    v = v or ""
                elif c == "recorded_at":
                    v = v or utcnow()
                vals.append(v)
            self.conn.execute(f"INSERT INTO apply_answers ({cols}) VALUES ({marks})",
                              (attempt_id, *vals))
            n += 1
        return n

    def answers(self, attempt_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM apply_answers WHERE attempt_id = ? ORDER BY id", (attempt_id,))]

    def answer_memory_get(self, label_norm: str, field_type: str, ats: str) -> Optional[str]:
        """The remembered value (JSON text) for a question, this ATS first,
        then any ATS ('*') (apply_design §7.4)."""
        for key in (ats, "*"):
            r = self.conn.execute(
                "SELECT value_json FROM answer_memory WHERE label_norm = ? AND field_type = ? "
                "AND ats = ?", (label_norm, field_type, key)).fetchone()
            if r:
                return r[0]
        return None

    def answer_memory_put(self, label_norm: str, field_type: str, value_json: str, *,
                          ats: str = "*", source_answer_id: Optional[int] = None,
                          now: Optional[str] = None) -> None:
        """Remember an answer (M22's correction UI). Commits."""
        now = now or utcnow()
        self.conn.execute(
            """INSERT INTO answer_memory (label_norm, field_type, ats, value_json,
                   source_answer_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (label_norm, field_type, ats) DO UPDATE SET
                   value_json = excluded.value_json,
                   source_answer_id = excluded.source_answer_id,
                   updated_at = excluded.updated_at""",
            (label_norm, field_type, ats, value_json, source_answer_id, now, now))
        self.conn.commit()

    _ACCOUNT_COLUMNS = frozenset({"vault_service", "status", "verified_at", "last_signin_at",
                                  "last_signin_ok", "exported_to_edge_at", "created_by_attempt"})

    def upsert_account(self, ats: str, tenant_host: str, email: str, vault_service: str,
                       status: str, *, now: Optional[str] = None,
                       created_by_attempt: Optional[int] = None) -> int:
        """Create the account row, or update its status and vault target.
        Never a password (NF-02). Commits; returns the row id."""
        now = now or utcnow()
        self.conn.execute(
            """INSERT INTO ats_accounts (ats, tenant_host, email, vault_service, status,
                   created_at, created_by_attempt) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (ats, tenant_host, email) DO UPDATE SET
                   vault_service = excluded.vault_service, status = excluded.status""",
            (ats, tenant_host.lower(), email, vault_service, status, now, created_by_attempt))
        self.conn.commit()
        return int(self.account(ats, tenant_host, email)["id"])

    def account(self, ats: str, tenant_host: str, email: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            "SELECT * FROM ats_accounts WHERE ats = ? AND tenant_host = ? AND email = ?",
            (ats, tenant_host.lower(), email)).fetchone()
        return dict(r) if r else None

    def accounts(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM ats_accounts ORDER BY created_at, id")]

    def set_account_status(self, account_id: int, status: str, **cols: Any) -> None:
        """Commits."""
        bad = [k for k in cols if k not in self._ACCOUNT_COLUMNS]
        if bad:
            raise ValueError(f"ats_accounts has no settable column {bad}")
        sets = {"status": status, **cols}
        self.conn.execute(
            f"UPDATE ats_accounts SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
            [*sets.values(), account_id])
        self.conn.commit()

    def delete_account(self, account_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM ats_accounts WHERE id = ?", (account_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def accounts_to_export(self) -> list[dict[str, Any]]:
        """Accounts not yet exported to Edge's password manager (apply_design §10.3)."""
        return [dict(r) for r in self.conn.execute(
            """SELECT * FROM ats_accounts WHERE exported_to_edge_at IS NULL
                 AND status IN ('created', 'verified') ORDER BY id""")]

    def mark_exported(self, ids: Iterable[int], now: str) -> None:
        for i in ids:
            self.conn.execute("UPDATE ats_accounts SET exported_to_edge_at = ? WHERE id = ?",
                              (now, i))
        self.conn.commit()

    # ---------------- tailored (M20) ----------------

    _TAILORED_COLS = (
        "job_id", "inputs_hash", "resume_hash", "jd_hash", "mode", "model", "options_json",
        "status", "created_at", "sent_at", "files_deleted_at", "docx_name", "docx_sha256",
        "pdf_name", "pdf_sha256", "coverage_before", "coverage_after", "title_match",
        "terms_json", "knockouts_json", "changes_json", "issues_json", "error")

    def add_tailored(self, row: dict[str, Any]) -> int:
        """Insert one tailoring attempt (tailor_design §11.1); returns its id.
        Unknown keys are ignored; `created_at` defaults to now."""
        data = {k: row.get(k) for k in self._TAILORED_COLS if k in row}
        data.setdefault("created_at", utcnow())
        cur = self.conn.execute(
            f"INSERT INTO tailored ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
            tuple(data.values()))
        self.conn.commit()
        return int(cur.lastrowid)

    def get_tailored(self, tailored_id: int) -> Optional[dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM tailored WHERE id = ?", (tailored_id,)).fetchone()
        return dict(r) if r else None

    def latest_tailored(self, job_id: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            "SELECT * FROM tailored WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        return dict(r) if r else None

    def current_tailored(self, job_id: str, inputs_hash: str,
                         files_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
        """The newest draft/sent row for these inputs whose files were not
        purged (§11.2). With `files_dir` (the job's directory) the DOCX must
        also be on disk with the recorded SHA-256."""
        import hashlib
        r = self.conn.execute(
            """SELECT * FROM tailored
                WHERE job_id = ? AND inputs_hash = ? AND status IN ('draft', 'sent')
                  AND files_deleted_at IS NULL
                ORDER BY id DESC LIMIT 1""", (job_id, inputs_hash)).fetchone()
        if r is None:
            return None
        row = dict(r)
        if files_dir is not None:
            p = Path(files_dir) / (row["docx_name"] or "")
            try:
                if hashlib.sha256(p.read_bytes()).hexdigest() != row["docx_sha256"]:
                    return None
            except OSError:
                return None
        return row

    def mark_tailored_sent(self, tailored_id: int, now: Optional[str] = None) -> None:
        self.conn.execute("UPDATE tailored SET status = 'sent', sent_at = ? WHERE id = ?",
                          (now or utcnow(), tailored_id))
        self.conn.commit()

    def tailored_to_purge(self, now: str, draft_days: float, sent_days: float,
                          closed_statuses: Iterable[str]) -> list[dict[str, Any]]:
        """Rows whose files are due for deletion (D-59): drafts older than
        `draft_days`, and sent rows whose application has been in a closed
        status (the latest transition to it, from app_events) for more than
        `sent_days`. Rows already purged are not returned."""
        closed = list(closed_statuses)
        out = [dict(r) for r in self.conn.execute(
            """SELECT * FROM tailored WHERE status = 'draft' AND files_deleted_at IS NULL
                  AND created_at < ? ORDER BY id""", (shift(now, days=-float(draft_days)),))]
        if closed:
            marks = ", ".join("?" * len(closed))
            out += [dict(r) for r in self.conn.execute(
                f"""SELECT t.* FROM tailored t
                      JOIN applications a ON a.job_id = t.job_id
                     WHERE t.status = 'sent' AND t.files_deleted_at IS NULL
                       AND a.status IN ({marks})
                       AND (SELECT MAX(e.at) FROM app_events e
                             WHERE e.job_id = t.job_id AND e.to_status = a.status) < ?
                     ORDER BY t.id""",
                (*closed, shift(now, days=-float(sent_days))))]
        return out

    def mark_tailored_purged(self, tailored_id: int, now: Optional[str] = None) -> None:
        """Files are gone: stamp it and clear the bullet diff. The row stays."""
        self.conn.execute(
            "UPDATE tailored SET files_deleted_at = ?, changes_json = NULL WHERE id = ?",
            (now or utcnow(), tailored_id))
        self.conn.commit()

    # ---------------- questions (M20 lane Q) ----------------
    #
    # Questions from applications (questions_design §7, F-13): one `questions` row
    # per distinct question (its `sig`), one sighting per time an attempt met it.
    # Rows sharing a `key` are one group, answered once. No answer value is ever
    # stored here (ADR-0005). `apply_attempts` belongs to lane B; until that table
    # exists, retry candidates are simply none.

    _QUESTION_STATUSES = ("open", "answered", "dismissed")

    @staticmethod
    def _question_dict(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        try:
            d["options"] = json.loads(d.get("options_json") or "[]")
        except ValueError:
            d["options"] = []
        d["sensitive"] = bool(d.get("sensitive"))
        return d

    def upsert_question(self, q: dict[str, Any], now: str) -> int:
        """Insert a question by its `sig`, or mark it seen again. A row seen
        again after it was answered reopens (the saved answer did not fit this
        time); a dismissed row stays dismissed. Returns the row id.

        `q` holds the `questions` columns (sig, key, target_path, title,
        description, kind, label, label_norm, sensitive, reason, named_by) and
        the options as `options` ([{label, norm}]) or as `options_json` text."""
        r = self.conn.execute("SELECT id, status FROM questions WHERE sig = ?",
                              (q["sig"],)).fetchone()
        if r is not None:
            status = "open" if r["status"] == "answered" else r["status"]
            self.conn.execute(
                "UPDATE questions SET last_seen_at = ?, reason = ?, status = ? WHERE id = ?",
                (now, q.get("reason") or "no_rule", status, r["id"]))
            self.conn.commit()
            return int(r["id"])
        options_json = q.get("options_json")
        if options_json is None:
            options_json = json.dumps(list(q.get("options") or []), ensure_ascii=False)
        cur = self.conn.execute(
            """INSERT INTO questions (sig, key, target_path, title, description, kind, label,
                   label_norm, options_json, sensitive, reason, named_by, status,
                   first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (q["sig"], q["key"], q.get("target_path") or "", q.get("title") or q["label"][:60],
             q.get("description") or "", q["kind"], q["label"], q["label_norm"], options_json,
             int(bool(q.get("sensitive"))), q.get("reason") or "no_rule",
             q.get("named_by") or "rule", now, now))
        self.conn.commit()
        return int(cur.lastrowid)

    def add_sighting(self, question_id: int, attempt_id: int, job_id: str,
                     company_id: Optional[int], employer_norm: str, ats: str, step: str,
                     field_key: str, label: str, required: bool, now: str) -> None:
        """One appearance of a question in an attempt; a repeat is ignored."""
        self.conn.execute(
            """INSERT OR IGNORE INTO question_sightings (question_id, attempt_id, job_id,
                   company_id, employer_norm, ats, step, field_key, label, required, seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (question_id, attempt_id, job_id, company_id, employer_norm or "", ats or "",
             step or "", field_key, label, int(bool(required)), now))
        self.conn.commit()

    def question_rows(self) -> list[dict[str, Any]]:
        """Every `questions` row, newest sighting first (key assignment and the
        naming prompt's existing fields, questions_design §5.2-§5.3)."""
        return [self._question_dict(r) for r in self.conn.execute(
            "SELECT * FROM questions ORDER BY last_seen_at DESC, id DESC")]

    def question_keys(self) -> list[tuple[str, str, str, bool]]:
        """(key, title, kind, sensitive) per key, the oldest row's title and kind."""
        out: dict[str, tuple[str, str, str, bool]] = {}
        for r in self.conn.execute("SELECT key, title, kind, sensitive FROM questions ORDER BY id"):
            k = r["key"]
            if k in out:
                if r["sensitive"] and not out[k][3]:
                    out[k] = (*out[k][:3], True)
                continue
            out[k] = (k, r["title"], r["kind"], bool(r["sensitive"]))
        return list(out.values())

    def questions_by_key(self, key: str) -> list[dict[str, Any]]:
        """The rows of one group, oldest first, each with its `options` parsed."""
        return [self._question_dict(r) for r in self.conn.execute(
            "SELECT * FROM questions WHERE key = ? ORDER BY id", (key,))]

    def question_employers(self, key: str) -> list[dict[str, str]]:
        """The employers that asked a group, by first sighting: [{name,
        employer_norm}] (name = the company's display name, else the
        normalised one). An employer-scoped answer is keyed by employer_norm."""
        out: dict[str, dict[str, str]] = {}
        for r in self.conn.execute(
                """SELECT c.name AS company, s.employer_norm FROM question_sightings s
                     JOIN questions q ON q.id = s.question_id
                     LEFT JOIN jobs j ON j.job_id = s.job_id
                     LEFT JOIN companies c ON c.id = COALESCE(s.company_id, j.company_id)
                    WHERE q.key = ? ORDER BY s.seen_at, s.id""", (key,)):
            name = r["company"] or r["employer_norm"] or ""
            if name and name not in out:
                out[name] = {"name": name, "employer_norm": r["employer_norm"] or ""}
        return list(out.values())

    def set_questions_status(self, key: str, status: str, now: str) -> int:
        """Set every row of a group to `status`; `answered` stamps answered_at.
        Returns the number of rows changed."""
        if status not in self._QUESTION_STATUSES:
            raise ValueError(f"unknown question status {status!r}")
        cur = self.conn.execute(
            "UPDATE questions SET status = ?, answered_at = CASE WHEN ? = 'answered' "
            "THEN ? ELSE answered_at END WHERE key = ?", (status, status, now, key))
        self.conn.commit()
        return cur.rowcount

    def retry_candidates(self) -> list[dict[str, Any]]:
        """Jobs whose newest attempt failed `unanswerable_required` with at least
        one question sighting: {job_id, attempt_id, company, title, open,
        dismissed}, where open/dismissed count that attempt's questions by
        status. Ready to retry = open == 0 and dismissed == 0."""
        try:
            rows = self.conn.execute(
                """SELECT a.job_id, a.id AS attempt_id, c.name AS company, j.title AS title,
                          COUNT(DISTINCT CASE WHEN q.status = 'open' THEN q.id END) AS open,
                          COUNT(DISTINCT CASE WHEN q.status = 'dismissed' THEN q.id END)
                              AS dismissed
                     FROM apply_attempts a
                     JOIN question_sightings s ON s.attempt_id = a.id
                     JOIN questions q ON q.id = s.question_id
                     LEFT JOIN jobs j ON j.job_id = a.job_id
                     LEFT JOIN companies c ON c.id = COALESCE(a.company_id, j.company_id)
                    WHERE a.state = 'failed' AND a.reason_code = 'unanswerable_required'
                      AND a.id = (SELECT MAX(b.id) FROM apply_attempts b WHERE b.job_id = a.job_id)
                    GROUP BY a.id ORDER BY a.id""").fetchall()
        except sqlite3.OperationalError:          # no apply_attempts table yet (lane B)
            return []
        return [{"job_id": r["job_id"], "attempt_id": int(r["attempt_id"]),
                 "company": r["company"] or "", "title": r["title"] or "",
                 "open": int(r["open"]), "dismissed": int(r["dismissed"])} for r in rows]

    def question_groups(self, status: str = "open") -> list[dict[str, Any]]:
        """One dict per key (questions_design §7.1): key, title, description,
        kind, sensitive, target_path, status, named_by, reason (of the latest
        sighting), labels (verbatim, distinct), variants ([{question_id, label,
        options, employers}], one per option set), employers (company names,
        by first sighting), waiting (jobs ready-or-not in retry_candidates with
        a sighting here), first_seen_at, last_seen_at. `status` = open |
        answered | all; a group is open if any of its rows is."""
        if status not in ("open", "answered", "all"):
            raise ValueError(f"status must be open, answered or all, not {status!r}")
        rows = [self._question_dict(r) for r in self.conn.execute(
            "SELECT * FROM questions ORDER BY id")]
        sightings: dict[int, list[dict[str, Any]]] = {}
        for s in self.conn.execute(
                """SELECT s.question_id, s.attempt_id, s.job_id, s.employer_norm, s.label,
                          s.seen_at, s.id, c.name AS company
                     FROM question_sightings s
                     LEFT JOIN jobs j ON j.job_id = s.job_id
                     LEFT JOIN companies c ON c.id = COALESCE(s.company_id, j.company_id)
                    ORDER BY s.seen_at, s.id"""):
            sightings.setdefault(int(s["question_id"]), []).append(dict(s))
        candidates = {int(c["attempt_id"]) for c in self.retry_candidates()}
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(r["key"], []).append(r)

        def names(ss: list[dict[str, Any]]) -> list[str]:
            out: list[str] = []
            for s in ss:
                n = s.get("company") or s.get("employer_norm") or ""
                if n and n not in out:
                    out.append(n)
            return out

        out = []
        for key, grp in groups.items():
            statuses = {r["status"] for r in grp}
            gstatus = ("open" if "open" in statuses else
                       "answered" if "answered" in statuses else "dismissed")
            if status != "all" and gstatus != status:
                continue
            first, latest = grp[0], max(grp, key=lambda r: (r["last_seen_at"], r["id"]))
            all_s = sorted((s for r in grp for s in sightings.get(r["id"], [])),
                           key=lambda s: (s["seen_at"], s["id"]))
            labels: list[str] = []
            for lab in [r["label"] for r in grp] + [s["label"] for s in all_s]:
                if lab and lab not in labels:
                    labels.append(lab)
            out.append({
                "key": key, "title": first["title"], "description": first["description"],
                "kind": first["kind"], "sensitive": any(r["sensitive"] for r in grp),
                "target_path": first["target_path"], "status": gstatus,
                "named_by": first["named_by"], "reason": latest["reason"],
                "labels": labels,
                "variants": [{"question_id": r["id"], "label": r["label"],
                              "options": r["options"],
                              "employers": names(sightings.get(r["id"], []))} for r in grp],
                "employers": names(all_s),
                "waiting": len({s["job_id"] for s in all_s if s["attempt_id"] in candidates}),
                "first_seen_at": min(r["first_seen_at"] for r in grp),
                "last_seen_at": max(r["last_seen_at"] for r in grp),
            })
        return out

# ---------------- apply (M20): the attempt state machine as plain strings ----------------
#
# A copy of apply/contracts.py's TRANSITIONS / TERMINAL_STATES / POST_CLICK_STATES,
# because store.py may not import a stage package. apply_flow asserts at import
# that this copy equals the contract (`check_attempt_table`), so a contract change
# that is not mirrored here stops every apply run instead of drifting silently.

TERMINAL_ATTEMPT_STATES = frozenset({"submitted", "submitted_unconfirmed",
                                     "ready_to_submit", "failed"})
POST_CLICK_ATTEMPT_STATES = frozenset({"submitting", "verifying_email",
                                       "submitted", "submitted_unconfirmed"})

ATTEMPT_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"tailoring", "planning", "failed"}),
    "tailoring": frozenset({"planning", "failed"}),
    "planning": frozenset({"opening", "failed"}),
    "opening": frozenset({"signing_in", "signing_up", "filling", "failed"}),
    "signing_in": frozenset({"verifying_email", "filling", "failed"}),
    # signing_up -> signing_up: the one backup-email retry (D-70, contract v3)
    "signing_up": frozenset({"signing_up", "verifying_email", "signing_in", "filling", "failed"}),
    "verifying_email": frozenset({"signing_in", "filling", "submitting",
                                  "submitted_unconfirmed", "failed"}),
    "filling": frozenset({"filling", "submitting", "ready_to_submit", "failed"}),
    "submitting": frozenset({"verifying_email", "submitted", "submitted_unconfirmed"}),
    "submitted": frozenset(),
    "submitted_unconfirmed": frozenset(),
    "ready_to_submit": frozenset(),
    "failed": frozenset(),
}

_ATTEMPT_COLUMNS = frozenset({
    "job_id", "company_id", "ats", "tenant_host", "mode", "state", "step", "reason_code",
    "reason_detail", "end_url", "plan_source", "resume_file", "resume_sha256",
    "resume_source", "tailored_id", "confirmation", "code_resubmits", "queued_at",
    "started_at", "submit_clicked_at", "finished_at", "job_log"})


def _state(v: Any) -> str:
    """An enum member's value, or the text itself."""
    return str(getattr(v, "value", v))


# States that need a recorded Submit click (contract `can_transition`, clicked=False).
CLICK_REQUIRED_ATTEMPT_STATES = frozenset({"submitting", "submitted", "submitted_unconfirmed"})


def attempt_transition_allowed(src: str, dst: str, *, clicked: bool) -> bool:
    """The contract's `can_transition(src, dst, clicked=...)`, on strings,
    both halves (apply_design §4.1, review F2): after the click only the
    post-click states (never `failed`); without a recorded click never
    `submitting` / `submitted` / `submitted_unconfirmed`."""
    if dst not in ATTEMPT_TRANSITIONS.get(src, frozenset()):
        return False
    if clicked:
        return dst in POST_CLICK_ATTEMPT_STATES
    return dst not in CLICK_REQUIRED_ATTEMPT_STATES
