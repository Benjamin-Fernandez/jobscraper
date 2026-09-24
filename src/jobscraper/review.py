"""The handoff review: the Claude Code session you are talking to does the judging.

`budget.backend: cli` shells out to `claude -p` and is fully automatic. This is
the other transport for the same decide step (PRD 8.3[5]) - no subprocess, no
API key, and the one that works inside Docker, which has no `claude` binary
(D-11, R-8):

    python -m jobscraper review --export   writes data/review_queue.json
    (ask Claude Code to judge that file and write data/review_verdicts.json)
    python -m jobscraper review --apply    folds the answers back in

It asks exactly what the automatic path asks - the same system prompt, the same
extracts, the same JSON contract - and its answers go through the same `guard()`
and into the same `decisions` rows under the same (profile_version, vital_hash)
key. So the two paths are interchangeable: neither re-judges what the other
decided, and a posting whose extract later changes comes back round.

Rewritten for the v2 schema at M9-T1; v1's version judged `scores` bands into
`llm_cache` and wrote spreadsheets.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import decide, shortlist
from . import filter as prefilter
from .config import Config
from .store import Store

QUEUE_NAME = "review_queue.json"
VERDICTS_NAME = "review_verdicts.json"


def _paths(cfg: Config) -> tuple[Path, Path]:
    base = cfg.shortlist_path.parent            # data/, beside the shortlist
    return base / QUEUE_NAME, base / VERDICTS_NAME


def pending(store: Store, profile: dict[str, Any], ruleset: prefilter.RuleSet,
            limit: int) -> list[decide.Posting]:
    """Prefilter survivors with no decision for their current extract.

    Only postings a run has already prefiltered qualify - review judges, it does
    not scrape or filter. The extract is recomputed if a run has not stored one.
    """
    pv = int(profile.get("profile_version", 1))
    out: list[decide.Posting] = []
    for job in store.jobs_passed_prefilter(pv, ruleset.hash):
        vital = job["vital_text"] or decide.vital_extract(
            job["title"] or "", job["location"] or "", job["jd_text"] or "")
        if store.get_decision(job["job_id"], pv, decide.vital_hash(vital)):
            continue
        out.append(decide.Posting(job["job_id"], job["title"] or "", vital))
        if len(out) >= limit:
            break
    return out


def export_queue(cfg: Config, store: Store, profile: dict[str, Any],
                 ruleset: prefilter.RuleSet, *, limit: int = 200) -> tuple[Path, int]:
    """Write the queue a Claude Code session judges. Returns (path, count)."""
    queue, verdicts = _paths(cfg)
    posts = pending(store, profile, ruleset, limit)
    ceiling = int(ruleset.ceiling_years or 3)
    doc = {
        "instructions": (
            f"Judge every posting below, following `system_prompt` exactly, and "
            f"write the JSON object it asks for to {verdicts.name} next to this "
            "file. One object per id; do not sample, do not add prose."),
        "write_results_to": verdicts.name,
        "profile_version": int(profile.get("profile_version", 1)),
        "ids": [p.job_id for p in posts],
        "system_prompt": decide.SYSTEM_PROMPT.format(ceiling=ceiling),
        "user_prompt": decide._user_prompt(str(profile.get("summary") or ""), posts),
    }
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    return queue, len(posts)


def apply_verdicts(cfg: Config, store: Store, profile: dict[str, Any],
                   ruleset: prefilter.RuleSet, *,
                   path: Optional[Path] = None) -> dict[str, int]:
    """Fold a verdicts file back in through the same guard as the automatic path.

    An id that is not pending (unknown, or already decided for its current
    extract) is skipped, never overwritten: the review cannot rewrite history.
    """
    queue, default = _paths(cfg)
    src = path or default
    if not src.exists():
        raise FileNotFoundError(
            f"no verdicts at {src}. Ask Claude Code to judge {queue.name} first.")
    answers = decide.parse_decisions(src.read_text(encoding="utf-8"))
    pv = int(profile.get("profile_version", 1))
    ceiling = int(ruleset.ceiling_years or 3)
    open_now = {p.job_id: p for p in pending(store, profile, ruleset, 10**9)}
    stats = {"applied": 0, "accepted": 0, "rejected_by_postcondition": 0,
             "not_pending": 0}
    for job_id, raw in answers.items():
        post = open_now.get(job_id)
        if post is None:
            stats["not_pending"] += 1
            continue
        final, reason, downgraded = decide.guard(
            raw["decision"], raw["is_singapore"], raw["yoe_min"], raw["reason"],
            ceiling)
        store.save_decision(job_id, pv, decide.vital_hash(post.vital_text), final,
                            raw["is_singapore"], raw["yoe_min"], reason,
                            "claude-code-session")
        stats["applied"] += 1
        stats["accepted"] += int(final == "accept")
        stats["rejected_by_postcondition"] += int(downgraded)
    doc = shortlist.write(store, cfg.shortlist_path, pv)
    stats["shortlisted"] = len(doc["jobs"])
    return stats
