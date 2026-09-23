"""SQLite persistence. Source of truth; Excel is only a surface.

All writes happen on the orchestrator thread. Fetch workers never touch the DB.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Candidate, Company, CycleState, JobFacts, RawJob, Verdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    ordinal INTEGER NOT NULL,
    name TEXT NOT NULL,
    tier TEXT, category TEXT, careers_url TEXT, role_type_hint TEXT,
    provider TEXT, slug TEXT, feed_url TEXT, resolve_method TEXT, resolved_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT, last_error_class TEXT, last_error TEXT,
    quarantined_at TEXT, probation_due_run INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name ON companies(name);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL,
    external_id TEXT, title TEXT, location TEXT, url TEXT,
    department TEXT, employment_type TEXT, posted_at TEXT,
    jd_hash TEXT, jd_text TEXT,
    first_seen_run INTEGER, last_seen_run INTEGER, closed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);

CREATE TABLE IF NOT EXISTS job_facts (
    job_id TEXT PRIMARY KEY,
    profile_version INTEGER,
    countries_json TEXT, is_singapore INTEGER, seniority TEXT,
    yoe_min INTEGER, yoe_max INTEGER, intake_year INTEGER,
    is_graduate_programme INTEGER, sponsorship TEXT, role_family TEXT,
    tech_stack_json TEXT, requires_clearance INTEGER,
    model TEXT, extracted_at TEXT
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    job_id TEXT, profile_version INTEGER, stage TEXT,
    payload_json TEXT, model TEXT,
    input_tokens INTEGER, output_tokens INTEGER, created_at TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    job_id TEXT, profile_version INTEGER,
    bm25 REAL, skill_overlap REAL, title_affinity REAL, total_score REAL,
    stage_a_pass INTEGER, filter_reason TEXT, scored_at TEXT,
    PRIMARY KEY (job_id, profile_version)
);

CREATE TABLE IF NOT EXISTS runs (
    run_no INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER, batch_from INTEGER, batch_to INTEGER,
    started_at TEXT, finished_at TEXT, status TEXT, stats_json TEXT
);

CREATE TABLE IF NOT EXISTS coverage (
    run_no INTEGER, company_id INTEGER,
    status TEXT, postings_found INTEGER, new_count INTEGER, matched_count INTEGER,
    http_status INTEGER, error_class TEXT, error TEXT, checked_at TEXT,
    PRIMARY KEY (run_no, company_id)
);

CREATE TABLE IF NOT EXISTS exported (
    job_id TEXT PRIMARY KEY, exported_run INTEGER, exported_at TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    role TEXT, company TEXT, url TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS cycle_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cycle_id INTEGER, cycle_started_at TEXT, cursor INTEGER,
    total_companies INTEGER, last_run_no INTEGER
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _b(v: Any) -> Optional[int]:
    return None if v is None else int(bool(v))


class Store:
    def __init__(self, path: Path, check_same_thread: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path),
                                    check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------------- companies ----------------

    def sync_companies(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        """Upsert the workbook into `companies`. Preserves resolution and health state."""
        added = updated = 0
        for r in rows:
            cur = self.conn.execute("SELECT id FROM companies WHERE name = ?", (r["name"],))
            hit = cur.fetchone()
            if hit:
                self.conn.execute(
                    """UPDATE companies SET ordinal=?, tier=?, category=?, careers_url=?,
                       role_type_hint=? WHERE id=?""",
                    (r["ordinal"], r["tier"], r["category"], r["careers_url"],
                     r["role_type_hint"], hit["id"]),
                )
                updated += 1
            else:
                self.conn.execute(
                    """INSERT INTO companies (ordinal, name, tier, category, careers_url,
                       role_type_hint) VALUES (?,?,?,?,?,?)""",
                    (r["ordinal"], r["name"], r["tier"], r["category"],
                     r["careers_url"], r["role_type_hint"]),
                )
                added += 1
        self.conn.commit()
        return added, updated

    def _company(self, row: sqlite3.Row) -> Company:
        return Company(**{k: row[k] for k in row.keys()})

    def all_companies(self) -> list[Company]:
        cur = self.conn.execute("SELECT * FROM companies ORDER BY ordinal")
        return [self._company(r) for r in cur.fetchall()]

    def get_company(self, cid: int) -> Optional[Company]:
        cur = self.conn.execute("SELECT * FROM companies WHERE id=?", (cid,))
        r = cur.fetchone()
        return self._company(r) if r else None

    def quarantined(self) -> list[Company]:
        cur = self.conn.execute(
            "SELECT * FROM companies WHERE active=0 ORDER BY ordinal")
        return [self._company(r) for r in cur.fetchall()]

    def set_resolution(self, cid: int, provider: str, slug: Optional[str],
                       feed_url: Optional[str], method: str) -> None:
        self.conn.execute(
            """UPDATE companies SET provider=?, slug=?, feed_url=?, resolve_method=?,
               resolved_at=? WHERE id=?""",
            (provider, slug, feed_url, method, utcnow(), cid))
        self.conn.commit()

    def record_success(self, cid: int) -> None:
        self.conn.execute(
            """UPDATE companies SET consecutive_failures=0, last_success_at=?,
               last_error_class=NULL, last_error=NULL, active=1,
               quarantined_at=NULL, probation_due_run=NULL WHERE id=?""",
            (utcnow(), cid))
        self.conn.commit()

    def record_failure(self, cid: int, error_class: str, error: str) -> int:
        self.conn.execute(
            """UPDATE companies SET consecutive_failures = consecutive_failures + 1,
               last_error_class=?, last_error=? WHERE id=?""",
            (error_class, (error or "")[:500], cid))
        self.conn.commit()
        cur = self.conn.execute(
            "SELECT consecutive_failures FROM companies WHERE id=?", (cid,))
        return int(cur.fetchone()[0])

    def rollback_failures(self, cids: Iterable[int]) -> None:
        """Global circuit breaker: undo this run's failure increments."""
        for cid in cids:
            self.conn.execute(
                """UPDATE companies
                   SET consecutive_failures = MAX(consecutive_failures - 1, 0)
                   WHERE id=?""", (cid,))
        self.conn.commit()

    def quarantine(self, cid: int, probation_due_run: int) -> None:
        self.conn.execute(
            """UPDATE companies SET active=0, quarantined_at=?, probation_due_run=?
               WHERE id=?""", (utcnow(), probation_due_run, cid))
        self.conn.commit()

    def due_probation(self, run_no: int) -> list[Company]:
        cur = self.conn.execute(
            """SELECT * FROM companies WHERE active=0 AND probation_due_run IS NOT NULL
               AND probation_due_run <= ? ORDER BY ordinal""", (run_no,))
        return [self._company(r) for r in cur.fetchall()]

    def defer_probation(self, cid: int, next_run: int) -> None:
        self.conn.execute(
            "UPDATE companies SET probation_due_run=? WHERE id=?", (next_run, cid))
        self.conn.commit()

    # ---------------- cycle ----------------

    def get_cycle(self) -> Optional[CycleState]:
        cur = self.conn.execute("SELECT * FROM cycle_state WHERE id=1")
        r = cur.fetchone()
        if not r:
            return None
        return CycleState(r["cycle_id"], r["cycle_started_at"], r["cursor"],
                          r["total_companies"], r["last_run_no"])

    def save_cycle(self, st: CycleState) -> None:
        self.conn.execute(
            """INSERT INTO cycle_state (id, cycle_id, cycle_started_at, cursor,
                                        total_companies, last_run_no)
               VALUES (1,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET cycle_id=excluded.cycle_id,
                   cycle_started_at=excluded.cycle_started_at, cursor=excluded.cursor,
                   total_companies=excluded.total_companies,
                   last_run_no=excluded.last_run_no""",
            (st.cycle_id, st.cycle_started_at, st.cursor, st.total_companies,
             st.last_run_no))
        self.conn.commit()

    # ---------------- runs ----------------

    def start_run(self, cycle_id: int, batch_from: int, batch_to: int) -> int:
        cur = self.conn.execute(
            """INSERT INTO runs (cycle_id, batch_from, batch_to, started_at, status)
               VALUES (?,?,?,?,'running')""",
            (cycle_id, batch_from, batch_to, utcnow()))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_no: int, status: str, stats: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats_json=? WHERE run_no=?",
            (utcnow(), status, json.dumps(stats), run_no))
        self.conn.commit()

    def last_run_no(self) -> int:
        cur = self.conn.execute("SELECT MAX(run_no) FROM runs")
        v = cur.fetchone()[0]
        return int(v or 0)

    def all_runs(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM runs ORDER BY run_no").fetchall()

    def record_coverage(self, run_no: int, company_id: int, status: str,
                        postings: int, new: int, matched: int,
                        http_status: Optional[int], error_class: Optional[str],
                        error: Optional[str]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO coverage (run_no, company_id, status,
               postings_found, new_count, matched_count, http_status,
               error_class, error, checked_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_no, company_id, status, postings, new, matched, http_status,
             error_class, (error or "")[:500], utcnow()))
        self.conn.commit()

    def coverage_rows(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT c.*, co.name, co.tier, co.provider, co.feed_url, co.careers_url
               FROM coverage c JOIN companies co ON co.id = c.company_id
               ORDER BY c.run_no DESC, co.ordinal""").fetchall()

    # ---------------- jobs ----------------

    def known_job_ids(self, company_id: int) -> set[str]:
        cur = self.conn.execute(
            "SELECT job_id FROM jobs WHERE company_id=?", (company_id,))
        return {r[0] for r in cur.fetchall()}

    def upsert_job(self, job_id: str, company_id: int, raw: RawJob,
                   run_no: int, is_new: bool) -> None:
        if is_new:
            self.conn.execute(
                """INSERT OR REPLACE INTO jobs (job_id, company_id, external_id, title,
                   location, url, department, employment_type, posted_at, jd_hash,
                   jd_text, first_seen_run, last_seen_run, closed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (job_id, company_id, raw.external_id, raw.title, raw.location, raw.url,
                 raw.department, raw.employment_type, raw.posted_at, raw.jd_hash(),
                 raw.description, run_no, run_no))
        else:
            self.conn.execute(
                "UPDATE jobs SET last_seen_run=?, closed_at=NULL WHERE job_id=?",
                (run_no, job_id))

    def commit(self) -> None:
        self.conn.commit()

    def close_missing(self, company_id: int, seen: set[str]) -> int:
        """Mark jobs absent from a SUCCESSFUL fetch as closed.

        Never call this after a failed or skipped fetch: a single timeout would
        otherwise mass-close a company's postings and corrupt the next delta.
        """
        cur = self.conn.execute(
            "SELECT job_id FROM jobs WHERE company_id=? AND closed_at IS NULL",
            (company_id,))
        stale = [r[0] for r in cur.fetchall() if r[0] not in seen]
        for jid in stale:
            self.conn.execute(
                "UPDATE jobs SET closed_at=? WHERE job_id=?", (utcnow(), jid))
        self.conn.commit()
        return len(stale)

    def save_score(self, cand: Candidate, profile_version: int) -> None:
        s = cand.score
        self.conn.execute(
            """INSERT OR REPLACE INTO scores (job_id, profile_version, bm25,
               skill_overlap, title_affinity, total_score, stage_a_pass,
               filter_reason, scored_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (cand.job_id, profile_version, s.bm25, s.skill_overlap, s.title_affinity,
             s.total, int(cand.stage_a_pass), cand.filter_reason, utcnow()))
        self.conn.commit()

    # ---------------- facts & verdicts ----------------

    def get_facts(self, job_id: str, pv: int) -> Optional[JobFacts]:
        cur = self.conn.execute(
            "SELECT * FROM job_facts WHERE job_id=? AND profile_version=?", (job_id, pv))
        r = cur.fetchone()
        if not r:
            return None
        return JobFacts(
            job_id=r["job_id"],
            countries=json.loads(r["countries_json"] or "[]"),
            is_singapore=None if r["is_singapore"] is None else bool(r["is_singapore"]),
            seniority=r["seniority"] or "unknown",
            yoe_min=r["yoe_min"], yoe_max=r["yoe_max"], intake_year=r["intake_year"],
            is_graduate_programme=None if r["is_graduate_programme"] is None
            else bool(r["is_graduate_programme"]),
            sponsorship=r["sponsorship"] or "unclear",
            role_family=r["role_family"] or "other",
            tech_stack=json.loads(r["tech_stack_json"] or "[]"),
            requires_clearance=None if r["requires_clearance"] is None
            else bool(r["requires_clearance"]),
            model=r["model"] or "")

    def save_facts(self, f: JobFacts, pv: int) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO job_facts (job_id, profile_version, countries_json,
               is_singapore, seniority, yoe_min, yoe_max, intake_year,
               is_graduate_programme, sponsorship, role_family, tech_stack_json,
               requires_clearance, model, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f.job_id, pv, json.dumps(f.countries), _b(f.is_singapore), f.seniority,
             f.yoe_min, f.yoe_max, f.intake_year, _b(f.is_graduate_programme),
             f.sponsorship, f.role_family, json.dumps(f.tech_stack),
             _b(f.requires_clearance), f.model, utcnow()))
        self.conn.commit()

    def get_cached(self, cache_key: str) -> Optional[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT payload_json, model FROM llm_cache WHERE cache_key=?", (cache_key,))
        r = cur.fetchone()
        if not r:
            return None
        d = json.loads(r["payload_json"])
        d["_model"] = r["model"]
        return d

    def save_cached(self, cache_key: str, job_id: str, pv: int, stage: str,
                    payload: dict[str, Any], model: str,
                    in_tok: int, out_tok: int) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO llm_cache (cache_key, job_id, profile_version,
               stage, payload_json, model, input_tokens, output_tokens, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (cache_key, job_id, pv, stage, json.dumps(payload), model,
             in_tok, out_tok, utcnow()))
        self.conn.commit()

    def save_verdict_row(self, v: Verdict, pv: int, cache_key: str) -> None:
        self.save_cached(cache_key, v.job_id, pv, v.stage, {
            "verdict": v.verdict, "confidence": v.confidence,
            "reason": v.reason, "concerns": v.concerns}, v.model, 0, 0)

    # ---------------- export guard ----------------

    def already_exported(self, job_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM exported WHERE job_id=?", (job_id,))
        return cur.fetchone() is not None

    def mark_exported(self, job_id: str, run_no: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO exported (job_id, exported_run, exported_at) "
            "VALUES (?,?,?)", (job_id, run_no, utcnow()))
        self.conn.commit()

    # ---------------- repair ----------------

    def find_companies(self, needle: str) -> list[Company]:
        """Case-insensitive substring match on the company name."""
        rows = self.conn.execute(
            "SELECT * FROM companies WHERE lower(name) LIKE ? ORDER BY ordinal",
            (f"%{needle.lower()}%",))
        return [self._company(r) for r in rows]

    def purge_company_jobs(self, cid: int) -> int:
        """Delete every posting scraped for a company, and everything derived.

        Used when a company was resolved to the wrong board: those postings are
        another company's, so leaving them would poison future dedup and let a
        stale row reappear in the tracker.
        """
        ids = [r["job_id"] for r in self.conn.execute(
            "SELECT job_id FROM jobs WHERE company_id=?", (cid,))]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        for table in ("scores", "job_facts", "llm_cache", "exported",
                      "applications"):
            self.conn.execute(
                f"DELETE FROM {table} WHERE job_id IN ({marks})", ids)
        self.conn.execute("DELETE FROM jobs WHERE company_id=?", (cid,))
        self.conn.commit()
        return len(ids)

    def clear_resolution(self, cid: int) -> None:
        """Forget a cached ATS resolution so the ladder runs again."""
        self.conn.execute(
            """UPDATE companies SET provider=NULL, slug=NULL, feed_url=NULL,
               resolve_method=NULL, resolved_at=NULL WHERE id=?""", (cid,))
        self.conn.commit()

    def mark_needs_feed(self, cid: int, note: str) -> None:
        """Park a company that cannot be resolved automatically.

        It stops being retried every run and shows up in needs_review.xlsx with
        the reason, waiting for a feed URL you paste in yourself.
        """
        self.conn.execute(
            """UPDATE companies SET active=0, quarantined_at=?,
               last_error_class='needs_feed', last_error=?,
               consecutive_failures=? WHERE id=?""",
            (utcnow(), note, 999, cid))
        self.conn.commit()

    def unmark_needs_feed(self, cid: int) -> None:
        self.conn.execute(
            """UPDATE companies SET active=1, quarantined_at=NULL,
               last_error_class=NULL, last_error=NULL, consecutive_failures=0,
               probation_due_run=NULL WHERE id=?""", (cid,))
        self.conn.commit()

    # ---------------- applications ----------------

    def set_applied(self, job_id: str, applied: bool, role: str = "",
                    company: str = "", url: str = "",
                    applied_at: Optional[str] = None) -> dict[str, Any]:
        """Mark a posting applied / not applied. Returns the stored row.

        The applied date is set once, on the first tick, and is preserved if the
        box is ticked again later. Un-ticking clears it.
        """
        cur = self.conn.execute(
            "SELECT applied_at FROM applications WHERE job_id=?", (job_id,))
        row = cur.fetchone()
        if applied:
            stamp = applied_at or (row["applied_at"] if row and row["applied_at"]
                                   else datetime.now(timezone.utc)
                                   .strftime("%Y-%m-%d"))
        else:
            stamp = None
        self.conn.execute("""
            INSERT INTO applications
                (job_id, applied, applied_at, role, company, url, updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                applied=excluded.applied,
                applied_at=excluded.applied_at,
                role=COALESCE(NULLIF(excluded.role,''), applications.role),
                company=COALESCE(NULLIF(excluded.company,''),
                                 applications.company),
                url=COALESCE(NULLIF(excluded.url,''), applications.url),
                updated_at=excluded.updated_at
        """, (job_id, 1 if applied else 0, stamp, role, company, url, utcnow()))
        self.conn.commit()
        return self.get_application(job_id) or {}

    def get_application(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def applied_map(self) -> dict[str, dict[str, Any]]:
        """job_id -> row, for every posting currently marked applied."""
        return {r["job_id"]: dict(r) for r in self.conn.execute(
            "SELECT * FROM applications WHERE applied=1")}

    def applied_rows(self) -> list[sqlite3.Row]:
        """Applied postings, oldest first, enriched with tier and score."""
        return list(self.conn.execute("""
            SELECT a.*, c.tier AS tier, c.category AS category,
                   s.total_score AS score
              FROM applications a
              LEFT JOIN jobs j      ON j.job_id = a.job_id
              LEFT JOIN companies c ON c.id = j.company_id
              LEFT JOIN scores s    ON s.job_id = a.job_id
             WHERE a.applied = 1
             GROUP BY a.job_id
             ORDER BY a.applied_at, a.company, a.role
        """))

    def stats(self) -> dict[str, int]:
        def q(s: str) -> int:
            return int(self.conn.execute(s).fetchone()[0])
        return {
            "companies": q("SELECT COUNT(*) FROM companies"),
            "resolved": q("SELECT COUNT(*) FROM companies WHERE provider IS NOT NULL"),
            "quarantined": q("SELECT COUNT(*) FROM companies WHERE active=0"),
            "jobs": q("SELECT COUNT(*) FROM jobs"),
            "open_jobs": q("SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL"),
            "exported": q("SELECT COUNT(*) FROM exported"),
            "runs": q("SELECT COUNT(*) FROM runs"),
        }
