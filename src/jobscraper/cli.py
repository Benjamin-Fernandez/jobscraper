"""Command-line surface.

    python -m jobscraper doctor      check config, watchlist, profile, judge
    python -m jobscraper run         one batch: scrape, filter, decide, shortlist
    python -m jobscraper status      who is due, run cadence, what is quarantined
    python -m jobscraper web         the web app: Inbox and Applications
    python -m jobscraper watchlist   list | add | disable watched companies
    python -m jobscraper profile     build or show the resume-derived profile
    python -m jobscraper filter      test | explain the prefilter rules
    python -m jobscraper review      judge postings inside a Claude Code session
    python -m jobscraper reresolve   forget a company's cached ATS
    python -m jobscraper sync        reconcile watchlist.yaml into the database
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import backends
from . import pipeline
from . import review as review_mod
from . import scheduler
from .config import load_config
from . import watchlist
from .store import Store as StoreV2

BAR = "-" * 66


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


def _batch_size(cfg, store, flag=None) -> int:
    """Companies per run (M11): the flag, else the stored setting the web app
    writes, else `run.batch_size` in config. `run` and `status` both use this,
    so the cadence `status` reports is the one `run` actually keeps."""
    if flag:
        return int(flag)
    stored = store.get_setting("batch_size")
    if stored and stored.isdigit() and int(stored) > 0:
        return int(stored)
    return cfg.batch_size


def cmd_status(args) -> int:
    """Queue depth and cadence from the staleness scheduler (PRD 8.3[0])."""
    cfg, store = _boot_v2(args)
    _sync_watchlist(cfg, store)
    st = scheduler.status(store, _batch_size(cfg, store), cfg.cycle_days)
    print(BAR)
    print(scheduler.describe(st))
    print(BAR)
    s = store.stats()
    print(f"jobs      {s['jobs']}   open {s['open_jobs']}   runs {s['runs']}   "
          f"applications {s['applications']}")
    store.close()
    return 0


def cmd_run(args) -> int:
    """One pipeline run over the most-neglected due companies (PRD 8.3)."""
    cfg, store = _boot_v2(args)
    try:
        rep = pipeline.run(cfg, store, dry_run=args.dry_run,
                           batch_size=_batch_size(cfg, store, args.batch_size))
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


def _profile_and_rules(cfg):
    """The merged profile and the loaded rules, or a printed reason why not."""
    from . import filter as prefilter
    from .profile import resume_ingest
    try:
        profile = resume_ingest.load_derived_profile(cfg)
    except RuntimeError as exc:                 # ProfileError
        print(str(exc), file=sys.stderr)
        return None, None
    return profile, prefilter.load_rules(cfg.rules_path)


def cmd_review(args) -> int:
    """Hand the decide step to the Claude Code session you are talking to."""
    cfg, store = _boot_v2(args)
    try:
        profile, rules = _profile_and_rules(cfg)
        if profile is None:
            return 1
        if args.apply:
            try:
                st = review_mod.apply_verdicts(
                    cfg, store, profile, rules,
                    path=Path(args.file) if args.file else None)
            except FileNotFoundError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(f"applied {st['applied']} decisions ({st['accepted']} accepted, "
                  f"{st['rejected_by_postcondition']} downgraded by the guard); "
                  f"{st['not_pending']} skipped as not pending")
            print(f"shortlist  {st['shortlisted']} roles -> {cfg.shortlist_path}")
            return 0
        path, n = review_mod.export_queue(cfg, store, profile, rules,
                                          limit=args.limit or 200)
    finally:
        store.close()
    if n == 0:
        print("nothing to review - every prefilter survivor already has a decision.")
        print("Run `python -m jobscraper run` to bring in new postings first.")
        return 0
    print(BAR)
    print(f"{n} postings need a decision -> {path}")
    print(BAR)
    print("Ask Claude Code, in this directory:")
    print(f'  "judge {path.name} and write the answer to {review_mod.VERDICTS_NAME}"')
    print("Then fold it back in:")
    print("  python -m jobscraper review --apply")
    print(BAR)
    return 0


def cmd_reresolve(args) -> int:
    """Forget a company's cached ATS, so the next run rediscovers it.

    For a board that moved without its careers URL changing. To point a company
    at a board by hand instead, set provider / slug / feed_url in watchlist.yaml.
    """
    cfg, store = _boot_v2(args)
    try:
        _sync_watchlist(cfg, store)
        c = store.company_by_key(args.key)
        if c is None:
            matches = [x for x in store.companies() if x.name.lower() == args.key.lower()]
            c = matches[0] if len(matches) == 1 else None
        if c is None:
            print(f"no company with key or name {args.key!r} - see "
                  "`python -m jobscraper watchlist list`", file=sys.stderr)
            return 1
        store.clear_resolution(c.id)
        print(f"{c.name}: cached ATS cleared (was {c.provider or 'unresolved'}); "
              "the next run that schedules it will rediscover it")
        return 0
    finally:
        store.close()


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
        except RuntimeError as exc:           # ProfileError: malformed profile/overrides
            print(f"cannot load the profile: {exc}", file=sys.stderr)
            return 2
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


def cmd_profile(args) -> int:
    """Lane D's verb (PRD 0.6): build, show or bump the resume-derived profile.

    Bare `profile` re-derives only if the resume or overrides changed, then
    shows. `--show` only reads; `--refresh` forces the model call; `--bump`
    invalidates every cached decision without re-deriving.
    """
    from .profile import resume_ingest as ri

    cfg = load_config(getattr(args, "config", None))
    try:
        if args.bump:
            print(f"profile_version bumped to {ri.bump_profile_version(cfg)}")
        elif args.refresh or not args.show:
            ri.ingest(cfg, force=args.refresh)
        p = ri.load_derived_profile(cfg)
    except (ri.ProfileError, ri.ResumeError) as exc:
        print(f"profile: {exc}", file=sys.stderr)
        return 1

    print(BAR)
    print(f"profile          {cfg.profile_path}")
    print(f"overrides        {cfg.profile_overrides_path}")
    print(f"profile_version: {p['profile_version']}")
    print(f"years_experience: {p['years_experience']}   "
          f"graduation: {p.get('graduation') or '-'}")
    print(f"summary: {p['summary']}")
    print(f"skills ({len(p['skills'])}): {', '.join(p['skills'])}")
    print(f"target_titles ({len(p['target_titles'])}):")
    for t in p["target_titles"]:
        print(f"  - {t}")
    if p["title_aliases"]:
        print("title_aliases: " + ", ".join(
            f"{k} -> {v}" for k, v in sorted(p["title_aliases"].items())))
    print(BAR)
    return 0


def cmd_watchlist(args) -> int:
    """Lane E's verb (PRD 0.6, M1-T5): list, add or disable watched companies.

    `add` and `disable` are targeted text edits to config/watchlist.yaml that
    keep every comment, and re-validate the file before writing it. Neither
    touches the database or runs discovery: the next `run` syncs the file and
    resolves a new company's provider like any other.
    """
    try:
        sys.stdout.reconfigure(errors="replace")      # company names are not cp1252
    except (AttributeError, ValueError):
        pass
    path = (Path(args.file) if args.file
            else load_config(getattr(args, "config", None)).watchlist_path)
    try:
        if args.watchlist_cmd == "add":
            e = watchlist.add_entry(path, args.name, args.url, key=args.key)
            print(f"added {e.name} (key {e.key}) to {path}")
            print("its provider is discovered on the next `run`")
        elif args.watchlist_cmd == "disable":
            e, changed = watchlist.disable_entry(path, args.key)
            print(f"disabled {e.name} (key {e.key}) in {path}" if changed
                  else f"{e.name} (key {e.key}) is already disabled")
        else:
            entries = watchlist.load(path)
            width = max(len(e.key) for e in entries)
            for e in entries:
                print(f"{'on ' if e.enabled else 'off'}  {e.key:<{width}}  "
                      f"{e.provider or '-':<15}  {e.name}")
            print(f"{len(entries)} companies, "
                  f"{len(watchlist.enabled_only(entries))} enabled")
    except watchlist.WatchlistError as exc:
        print(f"watchlist: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper",
                                description="Fortnightly careers-site monitor")
    p.add_argument("--config", help="path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check setup").set_defaults(fn=cmd_doctor)
    sub.add_parser("sync", help="load the watchlist into the db").set_defaults(fn=cmd_sync)
    sub.add_parser("status", help="who is due, cadence, quarantine").set_defaults(fn=cmd_status)
    rev = sub.add_parser("review",
                         help="judge postings inside a Claude Code session")
    rev.add_argument("--export", action="store_true",
                     help="write the queue of postings needing a decision "
                          "(the default)")
    rev.add_argument("--apply", action="store_true",
                     help="read review_verdicts.json back in")
    rev.add_argument("--file", help="path to the verdicts JSON, with --apply")
    rev.add_argument("--limit", type=int, default=0,
                     help="queue at most this many postings (default 200)")
    rev.set_defaults(fn=cmd_review)

    rr = sub.add_parser("reresolve", help="forget a company's cached ATS")
    rr.add_argument("key", help="the company's watchlist key, or its exact name")
    rr.set_defaults(fn=cmd_reresolve)

    run = sub.add_parser("run", help="process the next batch of companies")
    run.add_argument("--batch-size", type=int, default=None,
                     help="companies this run (default: the web app's "
                          "setting, else run.batch_size)")
    run.add_argument("--dry-run", action="store_true",
                     help="fetch and report, write nothing, consume no queue")
    run.set_defaults(fn=cmd_run)

    sub.add_parser("web", help="serve the web app (inbox, applications)"
                   ).set_defaults(fn=cmd_web)

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

    prof = sub.add_parser("profile",
                          help="build or show the profile derived from your resume")
    prof.add_argument("--show", action="store_true",
                      help="print the merged profile; never calls the model")
    prof.add_argument("--refresh", action="store_true",
                      help="re-derive from the resume even if it is unchanged")
    prof.add_argument("--bump", action="store_true",
                      help="bump profile_version: every cached decision goes stale")
    prof.set_defaults(fn=cmd_profile)

    wl = sub.add_parser("watchlist", help="list, add or disable watched companies")
    wl_file = argparse.ArgumentParser(add_help=False)
    wl_file.add_argument("--file", help="watchlist file (default: paths.watchlist)")
    wl_sub = wl.add_subparsers(dest="watchlist_cmd", required=True)
    wl_sub.add_parser("list", parents=[wl_file],
                      help="every company with its key, provider and state")
    wla = wl_sub.add_parser("add", parents=[wl_file],
                            help="append a two-line entry; comments are kept")
    wla.add_argument("name", help="display name, e.g. \"Jane Street\"")
    wla.add_argument("url", help="the careers page URL")
    wla.add_argument("--key", help="stable id (default: a slug of the name)")
    wld = wl_sub.add_parser("disable", parents=[wl_file],
                            help="set enabled: false on one entry")
    wld.add_argument("key", help="the entry's key, or its exact name")
    wl.set_defaults(fn=cmd_watchlist)
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
