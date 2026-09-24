"""Command-line surface.

    python -m jobscraper doctor     check config, watchlist, deps, judge
    python -m jobscraper sync       load the watchlist into the database
    python -m jobscraper status     where the cursor is, what is quarantined
    python -m jobscraper run        process the next batch of companies
    python -m jobscraper resolve    resolve ATS providers without fetching jobs
    python -m jobscraper export     rewrite the trackers from the database
    python -m jobscraper review     judge postings inside a Claude Code session
    python -m jobscraper view       open the match page and tick off applications
    python -m jobscraper pin        point a company at a feed URL by hand
    python -m jobscraper reresolve  redo ATS discovery for a company
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import backends
from . import cursor as cursor_mod
from . import review as review_mod
from .config import load_config, load_profile
from . import watchlist
from .net import HttpClient
from .output import (cards_from_tracker, write_html_view,
                     write_needs_review, write_run_tracker)
from . import discovery
from .runner import ensure_resolved, run_batch
from .serve import serve_view
from .store_v1 import Store

BAR = "-" * 66


def _boot(args):
    cfg = load_config(getattr(args, "config", None))
    profile = load_profile(getattr(args, "profile", None))
    store = Store(cfg.db_path)
    return cfg, profile, store


def _sync(cfg, store):
    """Load the watchlist into the companies table.

    A bridge, not the final design. It feeds watchlist entries through v1's
    `sync_companies`, which still keys rows on the display name and carries
    tier/category columns v2 has dropped. M3-T1b replaces it with
    `store.sync_watchlist`, which keys on the stable `key` so that renaming a
    company cannot reset its scrape history (PRD 8.4).

    It exists now because M1-T4 removed the Excel workbook from the config, and
    leaving every command raising AttributeError until M3 is not an option.
    """
    entries = watchlist.load(cfg.watchlist_path)
    rows = [{"ordinal": i,
             "name": e.name,
             "tier": "",
             "category": "",
             "careers_url": e.careers_url,
             "role_type_hint": ""}
            for i, e in enumerate(watchlist.enabled_only(entries), start=1)]
    added, updated = store.sync_companies(rows)
    return len(rows), added, updated


def cmd_doctor(args) -> int:
    cfg, profile, store = _boot(args)
    print(BAR)
    print("JobScraper doctor")
    print(BAR)

    wl = cfg.watchlist_path
    print(f"watchlist      {wl}")
    try:
        total, added, updated = _sync(cfg, store)
    except watchlist.WatchlistError as exc:
        print(f"               INVALID - {exc}")
        store.close()
        return 1
    print(f"               OK - {total} enabled companies "
          f"({added} new, {updated} updated)")

    print(f"profile        v{profile.version}, {len(profile.all_skills())} skills, "
          f"locations={','.join(profile.loc_allow)}")
    print(f"database       {cfg.db_path}")
    s = store.stats()
    print(f"               {s['companies']} companies, {s['resolved']} resolved, "
          f"{s['quarantined']} quarantined, {s['jobs']} jobs, "
          f"{s['exported']} exported")

    backend = backends.build(cfg.budget)
    print(f"judge          backend={backend.name}")
    if backend.available:
        print(f"               OK - {backend.describe()}")
        if backend.name == "cli":
            print("               judging runs through Claude Code; "
                  "no API key needed")
    else:
        print(f"               UNAVAILABLE - {backend.unavailable_reason}")
        print("               (runs still work; they fall back to rules only)")
        print("               or judge in-session: "
              "`python -m jobscraper review --export`")

    print(f"budget         model={cfg.budget.get('model', '(unset)')}, "
          f"llm={'on' if cfg.budget.get('enable_llm') else 'off'}, "
          f"ceiling={int(cfg.budget.get('max_tokens_per_run', 0)):,} tokens/run")
    print(f"batch          {cfg.run['batch_size']} companies per run, "
          f"{cfg.run['cycle_days']}-day cycle")
    print(BAR)
    print(cursor_mod.describe(store, total, int(cfg.run["cycle_days"]),
                              int(cfg.run["batch_size"])))
    print(BAR)
    store.close()
    return 0


def cmd_sync(args) -> int:
    cfg, _profile, store = _boot(args)
    total, added, updated = _sync(cfg, store)
    print(f"synced {total} companies ({added} new, {updated} updated)")
    store.close()
    return 0


def cmd_status(args) -> int:
    cfg, _profile, store = _boot(args)
    total = len(store.all_companies())
    print(BAR)
    print(cursor_mod.describe(store, total, int(cfg.run["cycle_days"]),
                              int(cfg.run["batch_size"])))
    print(BAR)
    s = store.stats()
    print(f"companies {s['companies']}   resolved {s['resolved']}   "
          f"quarantined {s['quarantined']}")
    print(f"jobs      {s['jobs']}   open {s['open_jobs']}   "
          f"exported {s['exported']}   runs {s['runs']}")
    q = store.quarantined()
    if q:
        print(f"\nQuarantined ({len(q)}) - see output/needs_review.xlsx")
        for c in q[:15]:
            print(f"  [{c.ordinal:>3}] {c.name:<26} {c.last_error_class or '':<10} "
                  f"{(c.last_error or '')[:46]}")
        if len(q) > 15:
            print(f"  ... and {len(q) - 15} more")
    store.close()
    return 0


def cmd_resolve(args) -> int:
    cfg, _profile, store = _boot(args)
    _sync(cfg, store)
    rc = cfg.run
    client = HttpClient(user_agent=rc["user_agent"],
                        timeout=float(rc["request_timeout"]),
                        delay=float(rc["rate_limit_delay"]),
                        max_retries=int(rc["max_retries"]),
                        respect_robots=bool(rc.get("respect_robots", True)))
    targets = [c for c in store.all_companies() if not c.provider]
    if args.limit:
        targets = targets[:args.limit]
    print(f"resolving {len(targets)} unresolved companies\n")
    counts: dict[str, int] = {}
    try:
        for c in targets:
            print(f"  [{c.ordinal:>3}] {c.name}")
            updated = ensure_resolved(client, store, c, verbose=True)
            key = updated.provider or "unresolved"
            counts[key] = counts.get(key, 0) + 1
    finally:
        client.close()
    print("\nresolution summary")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<18} {v}")
    store.close()
    return 0


def cmd_run(args) -> int:
    cfg, profile, store = _boot(args)
    _sync(cfg, store)
    rep = run_batch(cfg, profile, store, force=args.force,
                    batch_size=args.batch_size, dry_run=args.dry_run)

    print("\n" + BAR)
    if rep.status == "blocked":
        print(rep.message)
        print(BAR)
        store.close()
        return 0

    print(f"Run #{rep.run_no}  {rep.batch_label}")
    print(f"  companies   {rep.companies}  (ok {rep.ok}, failed {rep.failed})")
    print(f"  postings    {rep.postings} seen, {rep.new} new")
    print(f"  matched     {rep.matched}, exported {rep.exported}")
    if rep.ledger and rep.ledger.calls:
        print(f"  tokens      {rep.ledger.input_tokens:,} in / "
              f"{rep.ledger.output_tokens:,} out over {rep.ledger.calls} calls")
    if rep.quarantined:
        print(f"  quarantined {', '.join(rep.quarantined)}")
    if rep.errors:
        print("\n  skipped due to fetch errors:")
        for name, err in rep.errors:
            print(f"    - {name}: {err[:80]}")
    if rep.status == "aborted_unhealthy":
        print(f"\n  {rep.message}")

    out = cfg.output_dir
    if not args.dry_run:
        print(f"\n  tracker     {out / 'application_tracker.xlsx'}")
        print(f"  quick view  {out / 'latest_matches.html'}")
        print(f"  run log     {out / 'run_tracker.xlsx'}")
    print(BAR)
    total = len(store.all_companies())
    print(cursor_mod.describe(store, total, int(cfg.run["cycle_days"]),
                              int(cfg.run["batch_size"])))
    print(BAR)
    store.close()
    return 0


def cmd_export(args) -> int:
    cfg, _profile, store = _boot(args)
    write_run_tracker(cfg.output_dir / "run_tracker.xlsx", store)
    n = write_needs_review(cfg.output_dir / "needs_review.xlsx", store)
    print(f"wrote run_tracker.xlsx and needs_review.xlsx ({n} quarantined rows)")
    store.close()
    return 0


def cmd_view(args) -> int:
    cfg, _profile, store = _boot(args)
    store.close()                    # the viewer opens its own connection
    out = cfg.output_dir
    tracker = out / "application_tracker.xlsx"

    if args.latest:
        page = out / "latest_matches.html"
        if not page.exists():
            print("No match page yet - run `.\run.ps1` first.")
            return 1
    else:
        # Everything matched so far, rebuilt from the tracker. This is the
        # useful default: last run's page goes stale the moment you run again.
        cards = cards_from_tracker(tracker)
        if not cards:
            print(f"Nothing to show - {tracker.name} has no matches yet.")
            return 1
        page = out / "all_matches.html"
        write_html_view(page, cards, 0, f"{len(cards)} match(es) in your tracker",
                        heading="All matches")

    return serve_view(cfg.db_path, page, tracker,
                      port=args.port, open_browser=not args.no_browser)


def _pick(store, needle: str):
    """Resolve a name fragment to exactly one company, or explain why not."""
    hits = store.find_companies(needle)
    if not hits:
        print(f"no company matching {needle!r}")
        return None
    # "DRW" also matches "Cumberland (DRW)" - an exact name wins outright.
    exact = [c for c in hits if c.name.lower() == needle.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(hits) > 1:
        print(f"{needle!r} matches {len(hits)} companies - be more specific:")
        for c in hits[:12]:
            print(f"   [{c.ordinal:>3}] {c.name}")
        return None
    return hits[0]


def cmd_pin(args) -> int:
    cfg, _profile, store = _boot(args)
    company = _pick(store, args.company)
    if company is None:
        store.close()
        return 1

    if args.needs_feed:
        store.mark_needs_feed(company.id, args.note or
                              "no supported ATS; needs a feed URL by hand")
        print(f"{company.name}: parked for review - {args.note or 'needs a feed URL'}")
    else:
        store.set_resolution(company.id, args.provider or "generic_html",
                             args.slug, args.url, "manual")
        store.unmark_needs_feed(company.id)
        print(f"{company.name}: pinned -> {args.provider or 'generic_html'}"
              f"{'/' + args.slug if args.slug else ''}  {args.url or ''}")

    if args.purge:
        n = store.purge_company_jobs(company.id)
        print(f"{company.name}: purged {n} postings scraped from the old board")

    write_needs_review(cfg.output_dir / "needs_review.xlsx", store)
    store.close()
    return 0


def cmd_reresolve(args) -> int:
    cfg, _profile, store = _boot(args)
    rc = cfg.run
    targets = []
    for needle in args.company:
        c = _pick(store, needle)
        if c is None:
            store.close()
            return 1
        targets.append(c)

    client = HttpClient(user_agent=rc["user_agent"],
                        timeout=float(rc["request_timeout"]),
                        delay=float(rc["rate_limit_delay"]),
                        max_retries=int(rc["max_retries"]),
                        respect_robots=bool(rc["respect_robots"]))
    for company in targets:
        if args.purge:
            n = store.purge_company_jobs(company.id)
            print(f"{company.name}: purged {n} postings from the old board")
        store.clear_resolution(company.id)
        res = discovery.resolve(client, store.get_company(company.id))
        if res.ok:
            store.set_resolution(company.id, res.provider, res.slug,
                                 res.feed_url, res.method)
            store.unmark_needs_feed(company.id)
            print(f"{company.name}: -> {res.provider}"
                  f"{'/' + res.slug if res.slug else ''} ({res.method})")
        else:
            store.mark_needs_feed(company.id, res.note or "unresolved")
            print(f"{company.name}: UNRESOLVED - {res.note}")

    write_needs_review(cfg.output_dir / "needs_review.xlsx", store)
    store.close()
    return 0


def cmd_review(args) -> int:
    """Hand postings to the Claude Code session you are already talking to."""
    cfg, profile, store = _boot(args)
    out = cfg.output_dir

    if args.apply:
        src = Path(args.file) if args.file else None
        stats = review_mod.apply_verdicts(cfg, profile, store, path=src)
        tally = ", ".join(f"{k} {v}" for k, v in sorted(stats["tally"].items()))
        print(f"applied {stats['applied']} verdicts" + (f"  ({tally})" if tally else ""))
        if stats["unknown_id"]:
            print(f"  {stats['unknown_id']} skipped: id not found in the database")
        if stats["bad_verdict"]:
            print(f"  {stats['bad_verdict']} skipped: verdict not one of "
                  "strong/possible/weak/reject")
        print(f"tracker    {out / 'application_tracker.xlsx'} "
              f"(+{stats['exported']} rows)")
        print(f"page       {stats['page']}")
        store.close()
        return 0

    path, n = review_mod.export_queue(cfg, profile, store, limit=args.limit,
                                      include_all=args.all)
    store.close()
    if n == 0:
        print("nothing to review - every scored posting already has a verdict.")
        print("Run `python -m jobscraper run` to bring in new postings first.")
        return 0
    print(BAR)
    print(f"{n} postings need a verdict -> {path}")
    print(BAR)
    print("Ask Claude Code, in this directory:")
    print(f'  "review {path.name} and write the verdicts to '
          f'{review_mod.VERDICTS_NAME}"')
    print("Then fold them back in:")
    print("  python -m jobscraper review --apply")
    print(BAR)
    return 0


def cmd_web(args) -> int:
    """Serve the one-page web app (PRD 8.5) on `web.host`:`web.port`.

    FastAPI and uvicorn are imported here, not at the top of the module, so
    every other verb keeps working on a machine without the web dependencies.
    The bind address comes from config (env-overridable) and defaults to
    127.0.0.1: there is no authentication (PRD R-9).
    """
    import uvicorn

    from .web.api import create_app

    cfg = load_config(getattr(args, "config", None))
    host, port = cfg.web["host"], int(cfg.web["port"])
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: binding {host} - this app has no authentication",
              file=sys.stderr)
    print(f"JobScraper web: http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper",
                                description="Fortnightly careers-site monitor")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("--profile", help="path to profile.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check setup").set_defaults(fn=cmd_doctor)
    sub.add_parser("sync", help="load the watchlist into the db").set_defaults(fn=cmd_sync)
    sub.add_parser("status", help="cursor and health").set_defaults(fn=cmd_status)
    sub.add_parser("export", help="rewrite trackers").set_defaults(fn=cmd_export)

    r = sub.add_parser("resolve", help="resolve ATS providers only")
    r.add_argument("--limit", type=int, default=0)
    r.set_defaults(fn=cmd_resolve)

    v = sub.add_parser("view", help="open the match page and record applications")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--no-browser", action="store_true",
                   help="serve without opening a browser window")
    v.add_argument("--latest", action="store_true",
                   help="show only the last run's matches, not everything")
    v.set_defaults(fn=cmd_view)

    pin = sub.add_parser("pin", help="point a company at a feed URL by hand")
    pin.add_argument("company", help="company name or a unique fragment of it")
    pin.add_argument("--url", help="the feed or careers URL to scrape")
    pin.add_argument("--provider", help="greenhouse, lever, workday, generic_html, ...")
    pin.add_argument("--slug", help="the board slug, for ATS providers")
    pin.add_argument("--needs-feed", action="store_true",
                     help="park it for review instead of pinning a URL")
    pin.add_argument("--note", help="why, shown in needs_review.xlsx")
    pin.add_argument("--purge", action="store_true",
                     help="also delete postings already scraped for it")
    pin.set_defaults(fn=cmd_pin)

    rr = sub.add_parser("reresolve", help="redo ATS discovery for a company")
    rr.add_argument("company", nargs="+")
    rr.add_argument("--purge", action="store_true",
                    help="delete postings from the old board first")
    rr.set_defaults(fn=cmd_reresolve)

    rev = sub.add_parser("review",
                         help="judge postings inside a Claude Code session")
    rev.add_argument("--export", action="store_true",
                     help="write the queue of postings needing a verdict "
                          "(the default)")
    rev.add_argument("--apply", action="store_true",
                     help="read review_verdicts.json back in and re-export")
    rev.add_argument("--file", help="path to the verdicts JSON, with --apply")
    rev.add_argument("--limit", type=int, default=0,
                     help="queue at most this many postings")
    rev.add_argument("--all", action="store_true",
                     help="include postings the local score already accepts, "
                          "not just the undecided band")
    rev.set_defaults(fn=cmd_review)

    run = sub.add_parser("run", help="process the next batch of companies")
    run.add_argument("--force", action="store_true",
                     help="start a new cycle before the 14 days are up")
    run.add_argument("--batch-size", type=int, default=None)
    run.add_argument("--dry-run", action="store_true",
                     help="do everything except write the output files")
    run.set_defaults(fn=cmd_run)

    sub.add_parser("web", help="serve the web app (inbox, applications)"
                   ).set_defaults(fn=cmd_web)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
