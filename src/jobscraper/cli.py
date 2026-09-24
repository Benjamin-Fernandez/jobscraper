"""Command-line surface.

    python -m jobscraper doctor     check config, watchlist, deps, judge
    python -m jobscraper sync       load the watchlist into the database
    python -m jobscraper status     who is due, run cadence, what is quarantined
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
from . import pipeline
from . import review as review_mod
from . import scheduler
from .config import load_config, load_profile
from . import watchlist
from .scrape.net import HttpClient
from .output import (cards_from_tracker, write_html_view,
                     write_needs_review, write_run_tracker)
from .scrape import discovery
from .runner import ensure_resolved, run_batch
from .serve import serve_view
from .store import Store as StoreV2
from .store_v1 import Store

BAR = "-" * 66


def _boot(args):
    cfg = load_config(getattr(args, "config", None))
    profile = load_profile(getattr(args, "profile", None))
    store = Store(cfg.db_path)
    return cfg, profile, store


def _boot_v2(args):
    """Config plus the v2 store. `_boot` above serves only the legacy commands."""
    cfg = load_config(getattr(args, "config", None))
    return cfg, StoreV2(cfg.db_path)


def _sync_watchlist(cfg, store) -> dict[str, int]:
    """Reconcile watchlist.yaml into `companies`, keyed on the stable `key`.

    Runs before anything reads the companies table, so a YAML edit - an added,
    renamed, disabled or removed company - is always seen by the next command.
    """
    return store.sync_watchlist(watchlist.load(cfg.watchlist_path))


def cmd_doctor(args) -> int:
    cfg, store = _boot_v2(args)
    print(BAR)
    print("JobScraper doctor")
    print(BAR)

    wl = cfg.watchlist_path
    print(f"watchlist      {wl}")
    try:
        counts = _sync_watchlist(cfg, store)
    except watchlist.WatchlistError as exc:
        print(f"               INVALID - {exc}")
        store.close()
        return 1
    s = store.stats()
    print(f"               OK - {s['enabled']} enabled of {s['companies']} "
          f"({counts['added']} new, {counts['url_changed']} moved, "
          f"{counts['disabled']} disabled)")

    derived = cfg.profile_path
    print(f"profile        {derived}")
    print("               " + ("present" if derived.exists()
                               else "missing - run `python -m jobscraper profile`"))
    print(f"database       {cfg.db_path}")
    print(f"               {s['companies']} companies, {s['resolved']} resolved, "
          f"{s['quarantined']} quarantined, {s['jobs']} jobs, "
          f"{s['applications']} applications")

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
    store.close()
    return 0


def cmd_sync(args) -> int:
    cfg, store = _boot_v2(args)
    c = _sync_watchlist(cfg, store)
    s = store.stats()
    print(f"synced {s['enabled']} enabled of {s['companies']} companies "
          f"({c['added']} new, {c['updated']} updated, {c['url_changed']} moved, "
          f"{c['disabled']} disabled)")
    store.close()
    return 0


def cmd_status(args) -> int:
    """Queue depth and cadence from the staleness scheduler (PRD 8.3[0])."""
    cfg, store = _boot_v2(args)
    _sync_watchlist(cfg, store)
    st = scheduler.status(store, cfg.batch_size, cfg.cycle_days)
    print(BAR)
    print(scheduler.describe(st))
    print(BAR)
    s = store.stats()
    print(f"jobs      {s['jobs']}   open {s['open_jobs']}   runs {s['runs']}   "
          f"applications {s['applications']}")
    store.close()
    return 0


def cmd_resolve(args) -> int:
    cfg, _profile, store = _boot(args)
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
    """One pipeline run over the most-neglected due companies (PRD 8.3)."""
    cfg, store = _boot_v2(args)
    try:
        rep = pipeline.run(cfg, store, dry_run=args.dry_run,
                           batch_size=args.batch_size)
    finally:
        store.close()
    print()
    print(BAR)
    if rep.status == "nothing_due":
        print(rep.message)
        print(BAR)
        return 0
    head = "Dry run (nothing written)" if rep.status == "dry_run" else f"Run #{rep.run_no}"
    print(f"{head}  {len(rep.due)} due"
          + (f" + {len(rep.probation)} on probation" if rep.probation else ""))
    print(f"  companies   ok {rep.ok}, failed {rep.failed}")
    print(f"  postings    {rep.postings} seen, {rep.new} new")
    if rep.quarantined:
        print(f"  quarantined {', '.join(rep.quarantined)}")
    if rep.relinked:
        print(f"  relinked    {rep.relinked} earlier application(s)")
    if rep.message:
        print(f"  {rep.message}")
    print(BAR)
    return 0 if rep.status in ("ok", "dry_run") else 1


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


def cmd_filter(args) -> int:
    """Tune the prefilter (PRD 8.3[3], M4-T1b). Both subcommands are read-only.

    `filter test` dry-runs the rules on a posting you type in: no scrape, no
    database. `filter explain <job_id>` re-runs them on a stored posting for the
    full per-rule trace, and shows the verdict stored in `prefilter` for the
    current rules and profile beside it.

    The profile is the derived one (data/profile.derived.yaml) when it exists.
    Without it there are no target titles or skills to match, so every rule that
    reads the profile is disabled for the run - and the output says so - rather
    than silently skipping or rejecting everything.

    Self-contained on purpose (PRD 0.6: a lane adds one verb, touches nothing
    else here), hence the local imports.
    """
    import dataclasses

    import yaml

    from . import filter as filter_mod
    from .store import SchemaMismatch
    from .store import Store as V2Store

    try:
        sys.stdout.reconfigure(errors="replace")      # JD text is not cp1252
    except (AttributeError, ValueError):
        pass
    cfg = load_config(args.config)
    rules_path = Path(getattr(args, "rules", None) or cfg.rules_path)
    try:
        ruleset = filter_mod.load_rules(rules_path)
    except (OSError, ValueError) as exc:
        print(f"cannot load rules: {exc}", file=sys.stderr)
        return 2
    rules_hash = ruleset.hash      # before any fallback disabling: the stored key

    profile: dict = {}
    profile_note = f"{cfg.profile_path}"
    if cfg.profile_path.exists():
        try:
            from .profile.resume_ingest import load_derived_profile
            profile = dict(load_derived_profile(cfg))
            profile_note += " (+ overrides)"
        except ImportError:                   # Lane D's loader not merged yet
            profile = yaml.safe_load(cfg.profile_path.read_text(encoding="utf-8")) or {}
            profile_note += " (overrides not applied: profile loader not built yet)"
    else:
        uses_profile = [r.id for r in ruleset.rules if r.enabled and any(
            str(v).startswith("profile.") for k, v in r.spec.items()
            if k in ("source", "aliases"))]
        ruleset = dataclasses.replace(ruleset, rules=tuple(
            dataclasses.replace(r, enabled=False) if r.id in uses_profile else r
            for r in ruleset.rules))
        profile_note = "none - fallback"
        print(f"WARNING: no derived profile at {cfg.profile_path}; rules that read "
              f"it are DISABLED for this run: {', '.join(uses_profile) or '-'}.\n"
              "         Build it with the resume ingest (M2) for a faithful result.",
              file=sys.stderr)

    try:
        from .profile.keywords import overlap as scorer
    except ImportError:                       # Lane D's matcher not merged yet
        scorer = None

    stored_line = None
    if args.filter_cmd == "explain":
        if not cfg.db_path.exists():
            print(f"no database at {cfg.db_path} - nothing has been scraped yet",
                  file=sys.stderr)
            return 1
        try:
            store = V2Store(cfg.db_path)
        except SchemaMismatch as exc:
            print(str(exc), file=sys.stderr)
            return 1
        try:
            job = store.get_job(args.job_id)
            if job is None:                   # a URL: re-read for the company name
                by_url = store.find_job_by_url(args.job_id)
                job = store.get_job(by_url["job_id"]) if by_url else None
            if job is None:
                print(f"no posting with id or url {args.job_id!r}", file=sys.stderr)
                return 1
            version = profile.get("profile_version")
            row = (store.get_prefilter(job["job_id"], int(version), rules_hash)
                   if version is not None else None)
        finally:
            store.close()
        if row:
            verdict = ("PASS" if row["passed"] else
                       f"REJECT by {row['reject_rule']}: {row['reject_detail']}")
            stored_line = f"{verdict}  (at {row['evaluated_at']})"
        elif version is None:
            stored_line = "unknown - no profile_version without a derived profile"
        else:
            stored_line = ("none for these rules + profile v"
                           f"{version} (never prefiltered, or the rules changed since)")
        posting = {"title": job.get("title"), "location": job.get("location"),
                   "description": job.get("jd_text")}
        print(f"job       {job['job_id']}  {job.get('company') or ''}  "
              f"{job.get('url') or ''}".rstrip())
    else:
        posting = {"title": args.title, "location": args.location,
                   "description": args.desc}

    result = filter_mod.evaluate(posting, ruleset, profile, scorer)
    print(f"title     {posting['title'] or ''}")
    print(f"location  {posting['location'] or '(blank)'}")
    print(f"desc      {len(posting['description'] or '')} chars")
    print(f"rules     {rules_path}  (hash {rules_hash[:12]})")
    print(f"profile   {profile_note}")
    if scorer is None and profile:
        print("scorer    none (profile/keywords.py not built yet) - overlap rules skip")
    if stored_line is not None:
        print(f"stored    {stored_line}")
    print(BAR)
    print(filter_mod.render(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper",
                                description="Fortnightly careers-site monitor")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("--profile", help="path to profile.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check setup").set_defaults(fn=cmd_doctor)
    sub.add_parser("sync", help="load the watchlist into the db").set_defaults(fn=cmd_sync)
    sub.add_parser("status", help="who is due, cadence, quarantine").set_defaults(fn=cmd_status)
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
    run.add_argument("--batch-size", type=int, default=None,
                     help="companies this run (default: run.batch_size)")
    run.add_argument("--dry-run", action="store_true",
                     help="fetch and report, write nothing, consume no queue")
    run.set_defaults(fn=cmd_run)

    flt = sub.add_parser("filter", help="tune the prefilter rules (dry run)")
    flt_sub = flt.add_subparsers(dest="filter_cmd", required=True)
    ft = flt_sub.add_parser("test", help="run the rules on one made-up posting; "
                                         "no scrape, no database")
    ft.add_argument("--title", required=True)
    ft.add_argument("--location", default="")
    ft.add_argument("--desc", default="", help="description text")
    ft.add_argument("--rules", help="rules file to test (default: config's)")
    fe = flt_sub.add_parser("explain", help="every rule's verdict for a stored "
                                            "posting, beside the stored verdict")
    fe.add_argument("job_id", help="job id, or the posting's URL")
    flt.set_defaults(fn=cmd_filter)
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
