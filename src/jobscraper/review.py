"""The handoff review: Claude Code judges postings from inside a session.

The `cli` backend in backends.py shells out to `claude -p` and is fully
automatic. This module is the other way round - it lets the Claude Code session
you are already talking to do the judging, with no subprocess and no API key:

    python -m jobscraper review --export     writes output/review_queue.json
    (ask Claude Code to review that file and write review_verdicts.json)
    python -m jobscraper review --apply      folds the verdicts back in

Verdicts land in the same `llm_cache` table the automatic backends write, under
the same content-hash key, so the two paths are interchangeable and neither
re-judges what the other already decided. A posting whose description later
changes gets a new hash and comes back round for review.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config, Profile
from .llm import _key, _parse_json
from .matching import extract_requirements
from .models import Candidate, RawJob, ScoreBreakdown, Verdict
from .output import write_application_tracker, write_html_view
from .store_v1 import Store

QUEUE_NAME = "review_queue.json"
VERDICTS_NAME = "review_verdicts.json"

INSTRUCTIONS = (
    "You are screening job postings for the candidate described in "
    "candidate_profile. For every entry in `jobs`, decide how well it fits.\n"
    "Return one object per job with these keys: id (copy it verbatim), verdict, "
    "confidence (0-1), reason (at most 25 words, concrete - name the specific "
    "overlap or gap), concerns (array of at most 3 short strings, or []).\n"
    "verdict is one of: strong, possible, weak, reject.\n"
    "Reject roles requiring substantial professional experience, roles outside "
    "the candidate's allowed locations, internships, and non-engineering "
    "functions.\n"
    "Write {\"results\": [...]} to " + VERDICTS_NAME + " next to this file. "
    "Judge every job in the list; do not sample."
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- selection


def _pending_rows(store: Store, pv: int, lo: float, hi: float,
                  include_all: bool) -> list[dict[str, Any]]:
    """In-band postings that no transport has judged yet, best score first.

    Outside the band there is nothing to ask a model: above `hi` the local score
    already accepts, below `lo` it already rejects. --all widens to everything
    at or above `lo` so a judgement can also be put on the auto-accepts.
    """
    sql = """
        SELECT j.job_id, j.title, j.location, j.url, j.jd_text, j.jd_hash,
               j.posted_at, j.external_id, j.department, j.employment_type,
               j.company_id, s.total_score
        FROM scores s
        JOIN jobs j ON j.job_id = s.job_id
        WHERE s.profile_version = ?
          AND s.stage_a_pass = 1
          AND j.closed_at IS NULL
          AND s.total_score >= ?
    """
    params: list[Any] = [pv, lo]
    if not include_all:
        sql += " AND s.total_score <= ?"
        params.append(hi)
    sql += " ORDER BY s.total_score DESC"

    out: list[dict[str, Any]] = []
    for r in store.conn.execute(sql, params):
        row = dict(r)
        # Already judged at this profile version and this description? Skip.
        if store.get_cached(_key(row["job_id"], row["jd_hash"] or "", pv, "c2")):
            continue
        out.append(row)
    return out


def _rebuild(store: Store, row: dict[str, Any]) -> Optional[Candidate]:
    """Turn stored rows back into the Candidate the exporters expect."""
    company = store.get_company(row["company_id"])
    if company is None:
        return None
    raw = RawJob(
        external_id=row["external_id"] or "",
        title=row["title"] or "",
        url=row["url"] or "",
        location=row["location"] or "",
        department=row["department"] or "",
        employment_type=row["employment_type"] or "",
        posted_at=row["posted_at"] or "",
        description=row["jd_text"] or "")
    cand = Candidate(job_id=row["job_id"], company=company, raw=raw)
    cand.score = ScoreBreakdown(total=float(row["total_score"] or 0))
    return cand


# ---------------------------------------------------------------- export


def export_queue(cfg: Config, profile: Profile, store: Store, *,
                 limit: int = 0, include_all: bool = False) -> tuple[Path, int]:
    lo, hi = profile.thresholds["llm_band"]
    rows = _pending_rows(store, profile.version, float(lo), float(hi),
                         include_all)
    if limit > 0:
        rows = rows[:limit]

    chars = int(cfg.budget.get("jd_chars_for_verdict", 3000))
    jobs = []
    for r in rows:
        company = store.get_company(r["company_id"])
        jobs.append({
            "id": r["job_id"],
            "company": company.name if company else "(unknown)",
            "tier": company.tier if company else "",
            "category": company.category if company else "",
            "title": r["title"] or "",
            "location": r["location"] or "(unstated)",
            "url": r["url"] or "",
            "score": round(float(r["total_score"] or 0), 1),
            "description": extract_requirements(r["jd_text"] or "", chars)
                           or "NO DESCRIPTION AVAILABLE",
        })

    path = cfg.output_dir / QUEUE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utcnow(),
        "profile_version": profile.version,
        "candidate_profile": profile.summary,
        "instructions": INSTRUCTIONS,
        "verdict_values": ["strong", "possible", "weak", "reject"],
        "write_results_to": VERDICTS_NAME,
        "jobs": jobs,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path, len(jobs)


# ---------------------------------------------------------------- apply


def _read_verdicts(path: Path) -> list[dict[str, Any]]:
    data = _parse_json(path.read_text(encoding="utf-8"))
    if not data:
        raise SystemExit(f"{path.name} is not valid JSON")
    results = data.get("results")
    if not isinstance(results, list):
        raise SystemExit(
            f"{path.name} must hold {{\"results\": [...]}} - got keys "
            f"{sorted(data)[:6]}")
    return results


def apply_verdicts(cfg: Config, profile: Profile, store: Store, *,
                   path: Optional[Path] = None) -> dict[str, Any]:
    src = path or (cfg.output_dir / VERDICTS_NAME)
    if not src.exists():
        raise SystemExit(
            f"{src} not found - run `review --export` first, have Claude Code "
            f"judge {QUEUE_NAME}, then re-run this.")

    pv = profile.version
    results = _read_verdicts(src)

    # Index the postings the verdicts could refer to. Judged ones are excluded
    # from _pending_rows, so widen to every scored, open posting.
    rows = {r["job_id"]: dict(r) for r in store.conn.execute(
        """SELECT j.job_id, j.title, j.location, j.url, j.jd_text, j.jd_hash,
                  j.posted_at, j.external_id, j.department, j.employment_type,
                  j.company_id, s.total_score
           FROM scores s JOIN jobs j ON j.job_id = s.job_id
           WHERE s.profile_version = ? AND j.closed_at IS NULL""", (pv,))}

    stats: dict[str, Any] = {"applied": 0, "unknown_id": 0, "bad_verdict": 0}
    tally: dict[str, int] = {}
    judged: list[Candidate] = []
    allowed = {"strong", "possible", "weak", "reject", "contested"}

    for item in results:
        jid = str(item.get("id") or "")
        row = rows.get(jid)
        if row is None:
            stats["unknown_id"] += 1
            continue
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in allowed:
            stats["bad_verdict"] += 1
            continue

        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0

        v = Verdict(
            job_id=jid, verdict=verdict,
            confidence=max(0.0, min(1.0, confidence)),
            reason=str(item.get("reason") or "")[:220],
            concerns=[str(x)[:80] for x in (item.get("concerns") or [])][:3],
            model="claude-code:session", stage="c2")
        store.save_verdict_row(v, pv, _key(jid, row["jd_hash"] or "", pv, "c2"))

        cand = _rebuild(store, row)
        if cand is not None:
            cand.verdict = v
            judged.append(cand)
        stats["applied"] += 1
        tally[verdict] = tally.get(verdict, 0) + 1

    stats["tally"] = tally

    # Export exactly as a run would: same verdict allow-list, same score floor.
    keep = set(cfg.output.get("export_verdicts",
                              ["strong", "possible", "contested"]))
    floor = float(cfg.output.get("min_score_to_export", 25))
    matched = [c for c in judged
               if c.verdict and c.verdict.verdict in keep
               and c.score.total >= floor]
    matched.sort(key=lambda c: -c.score.total)

    run_no = store.last_run_no()
    out = cfg.output_dir
    stats["exported"] = write_application_tracker(
        out / "application_tracker.xlsx", matched, run_no, store)
    write_html_view(out / "reviewed_matches.html", matched, run_no,
                    f"reviewed in session ({len(matched)} matches)")
    stats["page"] = out / "reviewed_matches.html"
    return stats
