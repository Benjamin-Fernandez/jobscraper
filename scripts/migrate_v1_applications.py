"""One-off: carry the v1 application record into the v2 database (M3-T3b, D-14).

Why this exists. The user's own application history is the one thing in the v1
database that re-scraping cannot regenerate, so it is migrated even though jobs
and verdicts start clean (PRD section 6).

How rows are matched. v1 job ids hashed a company id that means nothing in v2,
so the durable link is the job URL. A row whose posting v2 has already scraped
lands on that job id; the rest are kept as orphans under their v1 id, with
company, role and URL on the row itself - and `Store.relink_orphan_applications`
moves them onto the real posting when a later run scrapes it.

Rules:
  - v1 `applied = 1` -> status `applied`, keeping v1's applied date exactly;
    `applied = 0` (ticked, then unticked) -> `to_apply`.
  - Rows whose URL has no real host (e.g. `https://e/4`) are v1 test fixtures
    that leaked into the live database; they are reported and skipped.
  - Re-running is safe: a row already migrated is left alone.

Usage:  python scripts/migrate_v1_applications.py [--v1-db PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.config import load_config  # noqa: E402
from jobscraper.store import Store  # noqa: E402

V1_DB = ROOT / "archive" / "v1-2026-09-23" / "data" / "jobscraper.db"
NOTE = "migrated from v1"


def is_fixture(url: str) -> bool:
    host = urlparse(url or "").hostname or ""
    return "." not in host


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--v1-db", type=Path, default=V1_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.v1_db.exists():
        print(f"no v1 database at {args.v1_db}")
        return 1
    v1 = sqlite3.connect(f"file:{args.v1_db.as_posix()}?mode=ro", uri=True)
    v1.row_factory = sqlite3.Row
    rows = v1.execute("SELECT * FROM applications ORDER BY updated_at").fetchall()
    v1.close()

    cfg = load_config()
    st = Store(cfg.db_path)
    added = kept = skipped = 0
    for r in rows:
        label = f"{r['company']} - {r['role']}"
        if is_fixture(r["url"]):
            print(f"  skip   {label}  ({r['url']}: test fixture, not a real posting)")
            skipped += 1
            continue
        job = st.find_job_by_url(r["url"])
        target = job["job_id"] if job else r["job_id"]
        if st.application(target) or st.application(r["job_id"]):
            print(f"  kept   {label}  (already migrated)")
            kept += 1
            continue
        status = "applied" if r["applied"] else "to_apply"
        where = "linked to scraped posting" if job else "orphan until re-scraped"
        print(f"  add    {label}  -> {status}, {where}")
        if not args.dry_run:
            st.set_application_status(
                target, status, NOTE, company=r["company"], role=r["role"],
                url=r["url"], at=r["updated_at"], applied_at=r["applied_at"])
        added += 1
    st.close()
    verb = "would add" if args.dry_run else "added"
    print(f"\n{verb} {added}, already present {kept}, skipped fixtures {skipped} "
          f"(of {len(rows)} v1 rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
