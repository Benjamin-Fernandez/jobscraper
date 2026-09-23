"""One-off: build config/watchlist.yaml from the archived v1 database.

Run once, commit the result, and the YAML is the source of truth from then on.
This script is not part of the package and is never imported by it.

    python scripts/seed_watchlist.py [--force]

Why seed rather than start empty (PRD D-4): all 229 v1 companies already have a
resolved ATS provider, and 133 have a working feed URL. That resolution cost a
full discovery crawl. Throwing it away would mean paying for it twice, and
pruning a real list is easier than building one from nothing.

What is deliberately NOT carried over: jobs, scores, verdicts. Those were
produced by rules v2 replaces, so they would be misleading rather than useful.

The five companies v1 quarantined come across `enabled: false` with the v1 error
in a note. They are unscrapable for a reason that has not changed - JavaScript
careers pages with no public feed - and rediscovering that costs a crawl and a
quarantine cycle each.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.watchlist import (WatchlistEntry, parse,  # noqa: E402
                                  render_entry, slugify)

SOURCE_DB = ROOT / "archive" / "v1-2026-09-23" / "data" / "jobscraper.db"
TARGET = ROOT / "config" / "watchlist.yaml"

HEADER = """\
# The companies JobScraper watches.
#
# A minimal entry is two lines:
#
#   - name: Jane Street
#     careers_url: https://www.janestreet.com/join-jane-street/open-roles/
#
# Optional fields:
#   key         stable identity; defaults to a slug of the name. Set this by
#               hand if you ever rename a company, so its scrape history and
#               failure counts survive the rename.
#   provider    ATS: greenhouse | lever | ashby | workday | smartrecruiters |
#               workable | recruitee | generic_html. Discovered automatically
#               if omitted.
#   slug        the board identifier on that ATS.
#   feed_url    the exact endpoint to fetch, when discovery cannot find it.
#   enabled     false to keep the entry but skip it. Default true.
#   notes       free text, ignored by the engine.
#
# Seeded from the v1 database: {total} companies, {resolved} with a resolved
# provider, {feeds} with a cached feed URL. Prune freely - fewer companies means
# the fortnightly sweep completes more comfortably.
#
# Edited by hand. Regenerating this file is not part of the normal workflow.
version: 1
companies:
"""


def build_entries(db_path: Path) -> list[WatchlistEntry]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT name, careers_url, provider, slug, feed_url, active,
                  last_error_class, last_error
           FROM companies
           ORDER BY name COLLATE NOCASE""").fetchall()
    conn.close()

    entries: list[WatchlistEntry] = []
    seen: dict[str, str] = {}

    for r in rows:
        name = (r["name"] or "").strip()
        url = (r["careers_url"] or "").strip()
        if not name or not url:
            print(f"  skipped {name or '(unnamed)'}: no careers_url")
            continue

        key = slugify(name)
        if key in seen:
            # Would be rejected by the loader anyway; say so here, where the fix
            # is obvious, rather than at the first run after committing.
            print(f"  !! {name!r} and {seen[key]!r} both slug to {key!r} - "
                  "giving the second an explicit key")
            key = f"{key}-2"
        seen[key] = name

        notes = ""
        enabled = bool(r["active"])
        if not enabled:
            reason = (r["last_error"] or r["last_error_class"] or "").strip()
            # One line only: this becomes a YAML scalar, not a paragraph.
            notes = (f"v1 could not scrape this: {reason.splitlines()[0][:150]}"
                     if reason else "disabled in v1")

        entries.append(WatchlistEntry(
            key=key,
            name=name,
            careers_url=url,
            provider=(r["provider"] or "").strip() or None,
            slug=(r["slug"] or "").strip() or None,
            feed_url=(r["feed_url"] or "").strip() or None,
            enabled=enabled,
            notes=notes))

    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seed_watchlist")
    ap.add_argument("--db", default=str(SOURCE_DB), help="archived v1 database")
    ap.add_argument("--out", default=str(TARGET), help="watchlist to write")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing watchlist")
    args = ap.parse_args(argv)

    db_path, out_path = Path(args.db), Path(args.out)

    if not db_path.exists():
        print(f"no such database: {db_path}\n"
              "M0-T2 archives it there; check it was not deleted.", file=sys.stderr)
        return 1

    if out_path.exists() and not args.force:
        print(f"{out_path} already exists. This file is hand-edited and "
              "regenerating it would discard your edits.\n"
              "Pass --force if you really mean to overwrite it.", file=sys.stderr)
        return 1

    entries = build_entries(db_path)
    if not entries:
        print("no companies found in the source database", file=sys.stderr)
        return 1

    resolved = sum(1 for e in entries if e.provider)
    feeds = sum(1 for e in entries if e.feed_url)
    disabled = sum(1 for e in entries if not e.enabled)

    body = "\n\n".join(render_entry(e) for e in entries)
    text = (HEADER.format(total=len(entries), resolved=resolved, feeds=feeds)
            + body + "\n")

    # Never write a file the loader would reject: seeding a broken watchlist
    # would fail at the next run, far from the cause.
    reparsed = parse(text, source=out_path.name)
    assert len(reparsed) == len(entries), (
        f"round trip lost entries: wrote {len(entries)}, read {len(reparsed)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8", newline="\n")

    print(f"wrote {out_path}")
    print(f"  {len(entries)} companies  ({len(entries) - disabled} enabled, "
          f"{disabled} disabled)")
    print(f"  {resolved} with a resolved provider, {feeds} with a cached feed URL")
    print("  validated by re-parsing the file that was written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
