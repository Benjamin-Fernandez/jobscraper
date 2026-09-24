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

from .models import RawJob, WatchedCompany

SCHEMA_VERSION = 2

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
    first_seen_run INTEGER, last_seen_run INTEGER, closed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);

CREATE TABLE IF NOT EXISTS prefilter (
    job_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    rules_hash TEXT NOT NULL,              -- a verdict is valid only for its rules
    passed INTEGER NOT NULL,
    reject_rule TEXT, reject_detail TEXT, overlap_score INTEGER,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, profile_version, rules_hash)
);

CREATE TABLE IF NOT EXISTS decisions (
    job_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    vital_hash TEXT NOT NULL,              -- a changed description is re-decided
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject')),
    is_singapore INTEGER, yoe_min INTEGER, reason TEXT, model TEXT,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (job_id, profile_version, vital_hash)
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

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

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
        - careers_url moved -> clear the cached resolution and the failure count:
                             a new URL is a new board
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
                       resolved_at = NULL, consecutive_failures = 0
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

    def rollback_failures(self, cids: Iterable[int]) -> None:
        """Global circuit breaker: undo this run's failure increments.

        When most of a batch fails at once the fault is local (network down),
        not the companies', so nobody should creep towards quarantine for it.
        """
        for cid in cids:
            self.conn.execute(
                """UPDATE companies SET consecutive_failures =
                   CASE WHEN consecutive_failures > 0
                        THEN consecutive_failures - 1 ELSE 0 END
                   WHERE id = ?""", (cid,))
        self.conn.commit()

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

    def defer_probation(self, cid: int, next_run: int) -> None:
        self.conn.execute(
            "UPDATE companies SET probation_due_run = ? WHERE id = ?", (next_run, cid))
        self.conn.commit()

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

    def coverage_for_run(self, run_no: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            """SELECT c.*, co.name, co.provider FROM coverage c
               JOIN companies co ON co.id = c.company_id
               WHERE c.run_no = ? ORDER BY co.name""", (run_no,))]

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
            self.conn.execute(
                """INSERT OR REPLACE INTO jobs (job_id, company_id, external_id,
                   title, location, url, posted_at, jd_hash, jd_text, vital_text,
                   first_seen_run, last_seen_run, closed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,NULL)""",
                (job_id, company_id, raw.external_id, raw.title, raw.location,
                 raw.url, raw.posted_at, raw.jd_hash(), raw.description,
                 run_no, run_no))
        else:
            self.conn.execute(
                "UPDATE jobs SET last_seen_run = ?, closed_at = NULL WHERE job_id = ?",
                (run_no, job_id))

    def close_missing(self, company_id: int, seen: set[str]) -> int:
        """Mark jobs absent from a SUCCESSFUL fetch as closed.

        Never call this after a failed or skipped fetch: a single timeout would
        otherwise mass-close a company's postings and corrupt the next delta.
        """
        stale = [r[0] for r in self.conn.execute(
            "SELECT job_id FROM jobs WHERE company_id = ? AND closed_at IS NULL",
            (company_id,)) if r[0] not in seen]
        now = utcnow()
        for jid in stale:
            self.conn.execute("UPDATE jobs SET closed_at = ? WHERE job_id = ?", (now, jid))
        self.conn.commit()
        return len(stale)

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        r = self.conn.execute(
            """SELECT j.*, co.name AS company FROM jobs j
               JOIN companies co ON co.id = j.company_id WHERE j.job_id = ?""",
            (job_id,)).fetchone()
        return dict(r) if r else None

    def jobs_seen_in_run(self, run_no: int, new_only: bool = False) -> list[dict[str, Any]]:
        col = "first_seen_run" if new_only else "last_seen_run"
        return [dict(r) for r in self.conn.execute(
            f"""SELECT j.*, co.name AS company FROM jobs j
                JOIN companies co ON co.id = j.company_id
                WHERE j.{col} = ? ORDER BY j.job_id""", (run_no,))]

    def set_vital(self, job_id: str, vital_text: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET vital_text = ? WHERE job_id = ?", (vital_text, job_id))
        self.conn.commit()

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

    def prefilter_rejections_by_rule(self, profile_version: int,
                                     rules_hash: str) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in self.conn.execute(
            """SELECT reject_rule, COUNT(*) FROM prefilter
               WHERE passed = 0 AND profile_version = ? AND rules_hash = ?
               GROUP BY reject_rule""", (profile_version, rules_hash))}

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

    def accepted_jobs(self, profile_version: int) -> list[dict[str, Any]]:
        """Every accepted posting for this profile, with the run that found it.

        The shortlist's raw material (M5-T1). Where a posting was decided more
        than once (its description changed) the newest decision wins.
        """
        return [dict(r) for r in self.conn.execute(
            """SELECT j.job_id, j.first_seen_run AS run_no, co.name AS company,
                      j.title, j.url, j.location, j.posted_at, j.closed_at,
                      d.yoe_min, d.reason, d.decided_at
                 FROM decisions d
                 JOIN jobs j       ON j.job_id = d.job_id
                 JOIN companies co ON co.id = j.company_id
                WHERE d.profile_version = ? AND d.decision = 'accept'
                  AND d.decided_at = (SELECT MAX(d2.decided_at) FROM decisions d2
                                       WHERE d2.job_id = d.job_id
                                         AND d2.profile_version = d.profile_version)
                ORDER BY j.job_id""", (profile_version,))]

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
                               applied_at: Optional[str] = None) -> bool:
        """Upsert an application; append to `app_events` only on a real change.

        Returns whether an event was appended - re-posting the same status is a
        no-op for the history (M6-T2), though `notes` still updates. `applied_at`
        is stamped the first time the status leaves NOT_YET_APPLIED and is never
        re-stamped afterwards. `applied_at` overrides that stamp's date - only
        for importing a record whose real date is known (M3-T3b).
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
                """INSERT INTO app_events (job_id, from_status, to_status, at)
                   VALUES (?,?,?,?)""", (job_id, prev_status, status, now))
        self.conn.commit()
        return changed

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
