"""Command-line surface.

    python -m jobscraper doctor      check config, watchlist, profile, judge
    python -m jobscraper run         one batch: scrape, filter, decide, shortlist
    python -m jobscraper status      who is due, run cadence, what is quarantined
    python -m jobscraper web         the web app: Inbox and Applications
    python -m jobscraper watchlist   list | add | disable watched companies
    python -m jobscraper profile     build or show the resume-derived profile
    python -m jobscraper filter      test | explain the prefilter rules
    python -m jobscraper titles      show | suggest the job titles searched for
    python -m jobscraper companies   show | search your own list of companies
    python -m jobscraper reresolve   forget a company's cached ATS
    python -m jobscraper sync        reconcile watchlist.yaml into the database
    python -m jobscraper purge       delete job descriptions past their time to live
    python -m jobscraper applicant   check the applicant profile for application forms
    python -m jobscraper mail        store the mailbox app password, test the mailbox
    python -m jobscraper apply       auto-apply (dry run, show, open-profile)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
from pathlib import Path

from . import backends
from . import pipeline
from . import scheduler
from . import tailor_flow
from .config import CYCLE_DAYS_KEY, load_config
from . import watchlist
from .store import Store as StoreV2, utcnow

BAR = "-" * 66
EXIT_CANCELLED = 143        # 128 + SIGTERM: the job was cancelled (C-4)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _Handler(logging.StreamHandler):
    """The package's own stderr handler: its type says it is already there."""


def configure_logging() -> None:
    """Send log records to stderr, once (C-6).

    Every command goes through `main`, `web` included, so this is the one
    place logging is set up. The level comes from JOBSCRAPER_LOG_LEVEL
    (default INFO). Calling it again changes nothing but the level: a second
    handler would print every line twice. A web-started job's child process
    inherits the environment, and its stderr is the job log, so that log gets
    the same records.
    """
    root = logging.getLogger()
    name = os.environ.get("JOBSCRAPER_LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelNamesMapping().get(name)
    root.setLevel(level if level is not None else logging.INFO)
    if not any(isinstance(h, _Handler) for h in root.handlers):
        handler = _Handler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    # httpx logs every request at INFO: a run's hundreds of fetches and model
    # calls would bury what matters. Kept unless DEBUG is asked for.
    quiet = logging.DEBUG if root.level <= logging.DEBUG else logging.WARNING
    for chatty in ("httpx", "httpcore"):
        logging.getLogger(chatty).setLevel(quiet)
    if level is None:
        # A typo must not hide itself: say what was used instead.
        logging.getLogger(__name__).warning(
            "JOBSCRAPER_LOG_LEVEL=%r is not a level; using INFO", name)


def _boot_v2(args):
    """Config plus the v2 store."""
    cfg = load_config(getattr(args, "config", None))
    return cfg, StoreV2(cfg.db_path)


def _sync_watchlist(cfg, store) -> dict[str, int]:
    """Reconcile watchlist.yaml into `companies`, keyed on the stable `key`.

    Runs before anything reads the companies table, so a YAML edit - an added,
    renamed, disabled or removed company - is always seen by the next command.
    """
    return store.sync_watchlist(watchlist.all_entries(cfg.watchlist_path, store))


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
    print(f"model          backend={backend.name} (judge and resume parser)")
    if backend.available:
        print(f"               OK - {backend.describe()}")
    else:
        print(f"               UNAVAILABLE - {backend.unavailable_reason}")
        print("               (runs still work; survivors wait for the model)")

    print(f"budget         llm={'on' if cfg.budget.get('enable_llm') else 'off'}, "
          f"{int(cfg.budget.get('decide_batch', 20))} postings per decide call")
    print(f"batch          {_batch_size(cfg, store)} companies per run, "
          f"{_cycle_days(cfg, store)}-day cycle (plan: {cfg.plan.name})")
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


def _positive_int(text: str) -> int:
    """argparse type for --batch-size: a run of 0 companies is not a run."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def _batch_size(cfg, store, flag=None) -> int:
    """Companies per run (M11): the flag, else the stored setting the web app
    writes, else `run.batch_size` in config. `run` and `status` both use this,
    so the cadence `status` reports is the one `run` actually keeps."""
    if flag is not None:            # an explicit flag always wins (argparse
        return int(flag)            # already refused anything below 1)
    stored = store.get_setting("batch_size")
    if stored and stored.isdigit() and int(stored) > 0:
        return int(stored)
    return cfg.batch_size


def _cycle_days(cfg, store) -> int:
    """Days before a company is due again (M15): the cycle the user chose in the
    web app when the plan allows it, else `run.cycle_days`."""
    return cfg.effective_cycle_days(store.get_setting(CYCLE_DAYS_KEY))


def cmd_status(args) -> int:
    """Queue depth and cadence from the staleness scheduler (PRD 8.3[0])."""
    cfg, store = _boot_v2(args)
    _sync_watchlist(cfg, store)
    st = scheduler.status(store, _batch_size(cfg, store), _cycle_days(cfg, store))
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
    # Jobs started from the web app re-invoke the CLI; they must use the same
    # config the web app was started with (`--config X web`).
    uvicorn.run(create_app(cfg, config_path=getattr(args, "config", None)),
                host=host, port=port, log_level="warning")
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

    # The job titles the user chose in the web app replace the resume's (M15),
    # and the stored verdict is keyed with them - as a run would do.
    if profile and cfg.db_path.exists():
        from .profile import titles as titles_mod
        try:
            tstore = V2Store(cfg.db_path)
        except SchemaMismatch:
            tstore = None
        if tstore is not None:
            try:
                user_titles = titles_mod.parse_user_titles(
                    tstore.get_setting(titles_mod.USER_TITLES_KEY))
            finally:
                tstore.close()
            if user_titles:
                profile = titles_mod.apply(profile, user_titles)
                rules_hash = titles_mod.prefilter_key(rules_hash, user_titles)
                profile_note += f" (+ your {len(user_titles)} job titles)"

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


def cmd_titles(args) -> int:
    """M15: the job titles the title filter searches for, and Qwen's
    recommendations. `show` prints them; `suggest` asks Qwen for more (up to the
    plan's limit) and stores them for the web app's Profile tab, which starts
    this command as a background job."""
    import json
    from . import filter as filter_mod
    from .profile import resume_ingest as ri
    from .profile import titles as t

    cfg, store = _boot_v2(args)
    try:
        plan = cfg.plan
        user = t.parse_user_titles(store.get_setting(t.USER_TITLES_KEY))
        try:
            profile = ri.load_derived_profile(cfg)
        except ri.ProfileError as exc:
            print(f"titles: {exc}", file=sys.stderr)
            return 1
        current = user or t.dedupe(profile.get("target_titles") or [])

        if args.titles_cmd == "suggest":
            limit = min(args.limit or t.SUGGEST_BATCH, plan.max_title_suggestions)
            try:
                resume = ri.load_resume(cfg.resume_dir, force=True)
            except RuntimeError as exc:                 # ResumeError
                print(f"titles: {exc}", file=sys.stderr)
                return 1
            backend = backends.build(cfg.budget)
            ceiling = filter_mod.load_rules(cfg.rules_path).ceiling_years or 3
            print(f"recommending {limit} new titles with "
                  f"{backend.model_id or backend.name} ...", flush=True)
            previous = None
            raw_prev = store.get_setting(t.SUGGESTIONS_KEY)
            if raw_prev:
                try:
                    previous = json.loads(raw_prev)
                except ValueError:
                    previous = None
            try:
                judge = cfg.raw.get("judge") or {}
                result = t.recommend(backend, resume.text, profile, current, previous,
                                     limit=limit, ceiling_years=int(ceiling),
                                     interests=list(judge.get("interests") or []))
            except ri.ProfileError as exc:
                print(f"titles: {exc}", file=sys.stderr)
                return 1
            store.set_setting(t.SUGGESTIONS_KEY, json.dumps(result))
            print(BAR)
            print(f"field of study: {result['field_of_study'] or '-'}")
            for e in result["experience"]:
                print(f"experience:     {e}")
            if result.get("repeated"):
                print("nothing new found - showing earlier recommendations again")
            print(f"{len(result['suggestions'])} recommended titles:")
            for item in result["suggestions"]:
                print(f"  + {item['title']:<42} {item['why']}")
            print(BAR)
            return 0

        print(BAR)
        source = "yours (set in the web app)" if user else "from your resume"
        cap = plan.max_target_titles
        print(f"titles {source}: {len(current)}"
              + (f" of {cap}" if cap is not None else " (no limit)")
              + f" (plan: {plan.name})")
        for title in current:
            print(f"  - {title}")
        raw = store.get_setting(t.SUGGESTIONS_KEY)
        if raw:
            last = json.loads(raw)
            print(f"last recommendations ({last.get('generated_at', '?')}):")
            for item in last.get("suggestions", []):
                print(f"  + {item.get('title')}")
        print(BAR)
        return 0
    finally:
        store.close()


def cmd_purge(args) -> int:
    """M17: delete stored job descriptions past their time to live (config
    `retention.description_days`, 7 by default) and give the space back to the
    disk. Every run does this at its end; this does it now."""
    cfg, store = _boot_v2(args)
    try:
        days = args.days if args.days is not None else pipeline.description_days(cfg)
        before = cfg.db_path.stat().st_size
        purged = store.purge_descriptions(days) if days > 0 else 0
        compacted = store.compact() if (purged or args.compact) else False
        after = cfg.db_path.stat().st_size
        print(f"descriptions older than {days:g} days deleted: {purged}")
        note = "" if compacted or not purged else \
            " (not compacted: the database is in use - the next run retries)"
        print(f"database file: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB{note}")
        print(f"tailored files deleted: {tailor_flow.purge(cfg, store, utcnow())}")
        return 0
    finally:
        store.close()


def cmd_tailor(args) -> int:
    """M20: tailor the resume to one job (docs/architecture/tailor_design.md 13.1).

    `--report` stops after "JD keyword coverage" before tailoring: it prints
    each job term and whether the resume has it, and writes no file and no row.
    Without it the resume is tailored (swaps to the job's own spelling of terms
    the resume already has, most relevant bullets first), rendered to DOCX and
    PDF under data/tailored/<job_id>/, and coverage before -> after is printed.
    Exit 1 on failure. Never prints resume text.
    """
    cfg, store = _boot_v2(args)
    try:
        backend = backends.build(cfg.budget)
        res = tailor_flow.tailor(cfg, store, args.job_id, backend=backend,
                                 report_only=args.report, force=args.force, say=print)
        if not res.ok:
            print(f"tailor failed: {res.error}", file=sys.stderr)
            return 1
        if args.report:
            print(f"{'term':<28} {'need':<10} {'status':<16} variant / related")
            for t in res.terms:
                extra = t.variant or (f"related: {t.related}" if t.related else "")
                print(f"{t.term[:28]:<28} {'required' if t.required else 'preferred':<10} "
                      f"{t.status.value:<16} {extra}")
            print(f"JD keyword coverage: {res.coverage_before:.0%}")
            for k in res.knockouts:
                print(f"application question to expect: {k[:120]}")
            return 0
        print(f"JD keyword coverage: {res.coverage_before:.0%} -> {res.coverage_after:.0%}")
        n = lambda src: sum(1 for c in res.changes if c.source == src)      # noqa: E731
        print(f"bullets changed {n('swap')}, kept original {n('fallback')}, trimmed {n('trimmed')}")
        missing = [t.term for t in res.terms if t.status.value == "missing"]
        if missing:
            print("missing terms (not on your resume, not added): " + ", ".join(missing))
        d = f"data/tailored/{args.job_id}"
        for p in (res.docx_path, res.pdf_path):
            if p:
                print(f"file: {d}/{Path(p).name}")
        for i in res.issues:
            print(f"note: {i.code.value} {i.detail}".rstrip())
        return 0
    finally:
        store.close()


def cmd_companies(args) -> int:
    """M16: the user's own list of companies. `show` prints it with each search
    result; `search` finds careers sites for the ones not searched yet (Qwen
    suggests the site, discovery proves it), in the user's order. The web app's
    Companies tab starts `search` as a background job after an upload."""
    from . import company_search

    cfg, store = _boot_v2(args)
    try:
        if args.companies_cmd == "search":
            counts = company_search.search(cfg, store)
            print(BAR)
            print("  ".join(f"{k} {v}" for k, v in counts.items()))
            print(BAR)
            return 0
        rows = store.company_list()
        print(BAR)
        if not rows:
            print("no list uploaded - add one on the web app's Companies tab")
        for r in rows:
            print(f"{r['position']:>4}. {r['name']:<34} {r['status']:<10} {r.get('detail') or ''}")
        print(BAR)
        return 0
    finally:
        store.close()


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


def cmd_applicant(args) -> int:
    """M20 lane P (apply_design §14.1): `applicant check` loads the applicant
    profile, validates it and lists what auto-apply still needs.

    Prints each error as `path: message` (messages never repeat a value), the
    missing paths, the completeness meter and the resume file's name. Exit 0
    only when there are no errors and nothing is missing. `applicant init` is
    M21 (WP-W1)."""
    from . import applicant

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    cfg = load_config(getattr(args, "config", None))
    path = Path(args.file) if getattr(args, "file", None) else cfg.applicant_path
    if not path.exists():
        print(f"applicant: no profile at {path} - copy config/applicant.example.yaml "
              "there and fill it in", file=sys.stderr)
        return 1
    try:
        profile = applicant.load(path)
    except applicant.ApplicantError as exc:
        print(f"applicant: {exc}", file=sys.stderr)
        return 1
    errors = applicant.validate(profile)
    missing = applicant.missing_for_apply(profile, cfg.resume_dir)
    filled, needed = applicant.completeness(profile)
    print(BAR)
    print(f"applicant profile  {path}")
    print(BAR)
    for e in errors:
        print(f"{e.path}: {e.message}")
    print(f"errors: {len(errors)}")
    print("missing: " + (", ".join(missing) if missing else "nothing"))
    print(f"completeness {filled}/{needed}")
    resume = applicant.resume_file(profile, cfg.resume_dir)
    print(f"Resume: {resume.name} ok" if resume else "Resume: not found")
    print(BAR)
    return 0 if not errors and not missing else 1


def cmd_mail(args) -> int:
    """M20 lane V (apply_design §11.4, §11.5, §14.1): the read-only mailbox
    that verification mail is fetched from.

    `mail set-password [--backup]` prompts with getpass and stores the app
    password in the vault as `jobscraper:imap:<host>` under the mailbox's
    username; `--host/--user` override the settings and are saved into them
    (the username lives only in the settings table, never in config.yaml).
    `mail test [--backup] [--find-from DOMAIN]` logs in, EXAMINEs INBOX and
    prints the message count; `--find-from` prints only the time of the newest
    message from that domain. Neither prints the username, the password, a
    subject or a body: the web `mailtest` job's log shows this output.
    """
    import getpass
    from . import vault
    from .apply import mail
    from .apply.contracts import Secret

    cfg, store = _boot_v2(args)
    try:
        backup = bool(getattr(args, "backup", False))
        pre = "apply.mail_backup." if backup else "apply.mail."
        which = "backup mailbox" if backup else "mailbox"
        if args.mail_cmd == "set-password":
            if args.host:
                store.set_setting(pre + "host", args.host.strip().lower())
            if args.user:
                store.set_setting(pre + "username", args.user.strip())
            settings = mail.effective_settings(cfg, store.get_setting)
            box = mail.mailbox_settings(settings, backup=backup)
            if not (box.host and box.username):
                print(f"mail: the {which} has no host or username yet; pass --host and "
                      "--user (saved to settings)", file=sys.stderr)
                return 1
            pw = "".join(getpass.getpass(f"App password for the {which} on {box.host}: ")
                         .split())                    # Gmail shows it in groups of 4
            if not pw:
                print("mail: no password entered; nothing stored", file=sys.stderr)
                return 1
            try:
                vault.put(vault.imap_service(box.host), box.username, Secret(pw))
            except vault.VaultError as exc:
                print(f"mail: {exc}", file=sys.stderr)
                return 1
            print(f"stored the {which} app password for {box.host} in Credential Manager")
            print("check it with: python -m jobscraper mail test" + (" --backup" if backup else ""))
            return 0

        # mail test
        settings = mail.effective_settings(cfg, store.get_setting)
        if backup and not mail.backup_is_separate(settings):
            print("no separate backup mailbox is set (apply.mail_backup): the backup "
                  "address is read from the main mailbox; testing that")
            backup = False
        box = mail.mailbox_settings(settings, backup=backup)
        if not (box.host and box.username):
            print(f"mail: the {which} is not set up (host or username missing); "
                  "run `python -m jobscraper mail set-password --host H --user U`",
                  file=sys.stderr)
            return 1
        pw = mail.mailbox_password(box)
        if pw is None:
            print(f"mail: no app password stored for the {which} on {box.host}; run "
                  "`python -m jobscraper mail set-password`" + (" --backup" if backup else ""),
                  file=sys.stderr)
            return 1
        try:
            out = mail.test_connection(box.host, box.port, box.username, pw)
            print(f"Connected, read-only ({box.host}:{box.port}): {out.removeprefix('ok: ')}")
            if args.find_from:
                when = mail.newest_from(box.host, box.port, box.username, pw, args.find_from)
                print(f"found from {args.find_from} at {when} UTC" if when
                      else f"no message from {args.find_from} in INBOX or Spam")
        except mail.MailError as exc:
            print(f"mail: {exc}", file=sys.stderr)
            return 1
        return 0
    finally:
        store.close()


EDGE_IMPORT_STEPS = ("Import it into Edge: Settings > Profiles > Import browser data > "
                     "Import from other password managers > Passwords (CSV file).")
EDGE_FIRST_NOTE = "Check with one account first: import, then look for it in Edge's passwords."
EDGE_CONFIRM_HINT = ("When it is imported, run `python -m jobscraper accounts export-edge "
                     "--confirm` to delete the file (it holds passwords).")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _account_tenant(url: str):
    """(ats, Tenant) for an ATS whose sites need an account, or None. The
    navigators' own `match_url` decides (apply_design §10.4: Workday forms A
    and B, one canonical host per tenant)."""
    from .apply.ats import REGISTRY
    from .apply.contracts import Tenant

    for name, nav in REGISTRY.items():
        if not getattr(nav, "needs_account", False):
            continue
        tenant = nav.match_url(url)
        if tenant is not None:
            return name, tenant
    # Until the Workday navigator is registered (WP-N2): apply_design §9.4.1 form A.
    m = re.match(r"^https?://(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com"
                 r"(?:/[a-z]{2}[-_][a-z]{2})?/(?P<site>[^/?#]+)", url or "", re.I)
    if m:
        host = f"{m['tenant']}.{m['wd']}.myworkdayjobs.com".lower()
        return "workday", Tenant("workday", host, m["tenant"].lower(), site=m["site"])
    return None


def cmd_accounts(args) -> int:
    """M20 lane V / D-78 lane N (apply_design §10.3, §10.4, §14.1): the ATS
    accounts JobScraper made or was given. Passwords live only in Windows
    Credential Manager and are never printed.

    `accounts list` prints ATS, tenant, email, status and the dates;
    `accounts add --url URL --email ADDRESS` stores a password you already have
    (prompted with getpass) and marks the account `created`, which also
    clears a `signin_failed` / `exists_no_password` row (a `verified` row stays
    verified); exit 2 when the URL is no known ATS that needs an account.
    `accounts export-edge` writes the CSV for Edge's password import (data/,
    gitignored); `--confirm` deletes the newest export and stamps its rows.
    """
    import getpass
    from . import vault
    from .apply.contracts import AccountStatus, Secret

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    cfg, store = _boot_v2(args)
    data_dir = cfg.db_path.parent
    try:
        if args.accounts_cmd == "list":
            rows = store.accounts()
            print(BAR)
            print(f"{'ats':<10} {'tenant':<40} {'status':<18} created / verified / exported")
            print(BAR)
            for r in rows:
                print(f"{r['ats']:<10} {r['tenant_host'][:40]:<40} {r['status']:<18} "
                      f"{r['created_at'] or '-'} / {r['verified_at'] or '-'} / "
                      f"{r['exported_to_edge_at'] or '-'}")
                print(f"{'':<10} {r['email']}")
            if not rows:
                print("no accounts yet")
            print(BAR)
            return 0

        if args.accounts_cmd == "add":
            found = _account_tenant(args.url)
            if found is None:
                print("accounts add: not the URL of an ATS that needs an account "
                      "(a Workday posting or careers-site URL)", file=sys.stderr)
                return 2
            ats, tenant = found
            email = (args.email or "").strip()
            if not _EMAIL_RE.match(email):
                print("accounts add: --email is not an email address", file=sys.stderr)
                return 2
            pw = getpass.getpass(f"Password for your {ats} account on {tenant.host}: ")
            if not pw:
                print("accounts add: no password entered; nothing stored", file=sys.stderr)
                return 1
            service = vault.service_for(ats, tenant.host)
            try:
                vault.put(service, email, Secret(pw))
            except vault.VaultError as exc:
                print(f"accounts add: {exc}", file=sys.stderr)
                return 1
            row = store.account(ats, tenant.host, email)
            if row is not None and row["status"] == AccountStatus.VERIFIED.value:
                store.upsert_account(ats, tenant.host, email, service, AccountStatus.VERIFIED.value)
                status = AccountStatus.VERIFIED.value
            else:
                store.upsert_account(ats, tenant.host, email, service, AccountStatus.CREATED.value)
                status = AccountStatus.CREATED.value
            print(f"stored the password for {ats} {tenant.host} in Credential Manager "
                  f"(account {status})")
            return 0

        # export-edge
        vault.purge_stale_exports(data_dir)
        if args.confirm:
            exports = sorted(data_dir.glob(vault.EXPORT_GLOB), key=lambda p: p.stat().st_mtime)
            if not exports:
                print("accounts export-edge --confirm: no export file to delete", file=sys.stderr)
                return 1
            newest = exports[-1]
            # The rows the export held: not yet exported, and a password in the vault.
            ids = [r["id"] for r in store.accounts_to_export()
                   if vault.get(r["vault_service"] or vault.service_for(r["ats"], r["tenant_host"]),
                                r["email"]) is not None]
            vault.delete_export(newest)
            store.mark_exported(ids, utcnow())
            print(f"deleted {newest.name}; {len(ids)} account(s) marked as imported into Edge")
            return 0
        first = not any(r["exported_to_edge_at"] for r in store.accounts())
        rows = store.accounts_to_export()
        if not rows:
            print("nothing to export: every account is already in Edge (or has no password)")
            return 0
        path = vault.export_edge_csv(rows, data_dir)
        print(f"wrote {path}")
        print(EDGE_IMPORT_STEPS)
        if first:
            print(EDGE_FIRST_NOTE)
        print(EDGE_CONFIRM_HINT)
        return 0
    except vault.VaultError as exc:
        print(f"accounts: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


APPLY_ID_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
APPLY_MAX_IDS = 20


def _effective_apply(cfg, store):
    """`apply:` from config with Settings → Apply on top (apply_design §14.3)."""
    return cfg.apply.with_settings(store.get_setting)


def cmd_apply(args) -> int:
    """M20 lane B (apply_design §14.1). `apply <job_id>... [--dry-run]` applies
    to each job in order (dry run: everything is filled, nothing is sent);
    `apply show <job_id|attempt_id>` prints the audit of one attempt;
    `apply open-profile [URL]` opens Edge on the JobScraper profile for the
    owner's own sign-ins. Exit 0 when every attempt ended submitted or
    ready_to_submit, 1 otherwise, 2 on bad arguments."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    words = list(args.words)
    if words[0] == "show":
        return _apply_show(args, words[1:])
    if words[0] == "open-profile":
        return _apply_open_profile(args, words[1:])
    bad = [w for w in words if not APPLY_ID_RE.match(w)]
    if bad or len(words) > APPLY_MAX_IDS:
        print(f"apply: give 1-{APPLY_MAX_IDS} job ids (letters, digits, : _ -)"
              + (f"; not a job id: {bad[0][:80]}" if bad else ""), file=sys.stderr)
        return 2
    from . import apply_flow

    cfg, store = _boot_v2(args)
    try:
        acfg = _effective_apply(cfg, store)
        dry_run = bool(args.dry_run) or acfg.mode != "auto"
        results = apply_flow.run(cfg, store, words, dry_run=dry_run,
                                 backend=backends.build(cfg.budget), apply_cfg=acfg)
        print(BAR)
        print(f"{'job id':<28} {'attempt':>7}  {'state':<22} reason")
        for r in results:
            reason = f"{r.reason.value} {r.reason_detail}".strip() if r.reason else r.reason_detail
            print(f"{r.job_id[:28]:<28} {r.attempt_id:>7}  {r.state.value:<22} {reason[:80]}")
        print(BAR)
        return 0 if results and all(r.ok for r in results) else 1
    finally:
        store.close()


def _apply_show(args, rest: list[str]) -> int:
    """The owner's audit of one attempt (D-68 A-3): header, one line per
    answer (the exact value sent, sensitive ones included: this is the owner's
    own terminal; files as name + SHA-256), then the evidence files. Nothing
    goes to a job log."""
    if len(rest) != 1:
        print("apply show: give one job id or attempt id", file=sys.stderr)
        return 2
    from . import apply_flow

    cfg, store = _boot_v2(args)
    try:
        key = rest[0]
        if key.isdigit():
            at = store.attempt(int(key))
        else:
            rows = store.attempts_for_job(key)
            at = rows[-1] if rows else None
        if at is None:
            print(f"apply show: no attempt for {key}", file=sys.stderr)
            return 1
        job = store.job_for_apply(at["job_id"]) or {}
        print(BAR)
        print(f"attempt {at['id']}  job {at['job_id']}  "
              f"{job.get('company') or '?'} - {job.get('title') or '?'}")
        print(f"ats {at['ats'] or '-'}  mode {at['mode']}  state {at['state']}"
              + (f"  reason {at['reason_code']}" if at["reason_code"] else "")
              + (f": {at['reason_detail']}" if at["reason_detail"] else ""))
        if at["resume_file"]:
            print(f"resume {at['resume_file']} ({at['resume_source'] or '?'})")
        print(f"queued {at['queued_at']}  started {at['started_at'] or '-'}  "
              f"submit clicked {at['submit_clicked_at'] or '-'}  finished {at['finished_at'] or '-'}")
        print(BAR)
        for a in store.answers(at["id"]):
            print(f"[{a['step'] or '-'}] {a['label']}{' *' if a['required'] else ''}")
            src = a["source"] + (f" ({a['rule_id']})" if a["rule_id"] else "")
            print(f"    = {_shown_answer(a['value_json'])}")
            print(f"    tier {a['tier']}  conf {a['confidence']:.2f}  {src}  {a['status']}"
                  + (f"  note: {a['note']}" if a["note"] else ""))
        folder = apply_flow.evidence_root(cfg) / str(at["id"])
        files = sorted(folder.glob("*.png")) + sorted(folder.glob("failed.html"))
        print(BAR)
        for f in files:
            print(f"evidence {f}")
        if not files:
            print("evidence: none")
        return 0
    finally:
        store.close()


def _shown_answer(value_json) -> str:
    if value_json is None:
        return "(blank)"
    try:
        v = json.loads(value_json)
    except ValueError:
        return str(value_json)
    if isinstance(v, dict) and "file" in v:
        return f"file {v['file']} sha256 {v.get('sha256') or '?'}"
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v)


def _apply_open_profile(args, rest: list[str]) -> int:
    """`apply open-profile [URL]` (D-70): headed Edge on the JobScraper
    profile, held until the owner closes it."""
    if len(rest) > 1:
        print("apply open-profile: at most one URL", file=sys.stderr)
        return 2
    from . import apply_flow

    cfg, store = _boot_v2(args)
    try:
        acfg = _effective_apply(cfg, store)
    finally:
        store.close()
    return apply_flow.open_profile(acfg, rest[0] if rest else "")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper",
                                description="Weekly careers-site monitor")
    p.add_argument("--config", help="path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check setup").set_defaults(fn=cmd_doctor)
    sub.add_parser("sync", help="load the watchlist into the db").set_defaults(fn=cmd_sync)
    sub.add_parser("status", help="who is due, cadence, quarantine").set_defaults(fn=cmd_status)
    pg = sub.add_parser("purge", help="delete job descriptions past their time to live")
    pg.add_argument("--days", type=float, default=None,
                    help="time to live in days (default: config retention.description_days)")
    pg.add_argument("--compact", action="store_true", help="compact the database even if nothing was deleted")
    pg.set_defaults(fn=cmd_purge)
    rr = sub.add_parser("reresolve", help="forget a company's cached ATS")
    rr.add_argument("key", help="the company's watchlist key, or its exact name")
    rr.set_defaults(fn=cmd_reresolve)

    run = sub.add_parser("run", help="process the next batch of companies")
    run.add_argument("--batch-size", type=_positive_int, default=None,
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

    tl = sub.add_parser("titles", help="job titles to search for, and Qwen's recommendations")
    tl_sub = tl.add_subparsers(dest="titles_cmd")
    tl_sub.add_parser("show", help="the titles in use and the last recommendations")
    ts = tl_sub.add_parser("suggest", help="ask Qwen for more titles (stored for the web app)")
    ts.add_argument("--limit", type=_positive_int, default=0,
                    help="at most this many (capped by the plan)")
    tl.set_defaults(fn=cmd_titles, titles_cmd="show")

    cl = sub.add_parser("companies", help="your own list of companies: show it, or search it")
    cl_sub = cl.add_subparsers(dest="companies_cmd")
    cl_sub.add_parser("show", help="the list, each with its search result")
    cl_sub.add_parser("search", help="find careers sites for the companies not searched yet")
    cl.set_defaults(fn=cmd_companies, companies_cmd="show")

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

    # --- applicant (M20 lane P)
    ap = sub.add_parser("applicant", help="the applicant profile for application forms")
    ap_sub = ap.add_subparsers(dest="applicant_cmd", required=True)
    apc = ap_sub.add_parser("check", help="validate the profile and list what "
                                          "auto-apply still needs")
    apc.add_argument("--file", help="profile to check (default paths.applicant)")
    ap.set_defaults(fn=cmd_applicant)

    # --- tailor (M20 lane T)
    tl_p = sub.add_parser("tailor", help="tailor your resume to one job (DOCX + PDF)")
    tl_p.add_argument("job_id", help="the job's id (as in the Inbox / jobs table)")
    tl_p.add_argument("--report", action="store_true",
                      help="print JD keyword coverage and each term's status; write nothing")
    tl_p.add_argument("--force", action="store_true",
                      help="tailor again even if a current file exists")
    tl_p.set_defaults(fn=cmd_tailor)

    # --- mail (M20 lane V)
    ml = sub.add_parser("mail", help="the read-only mailbox for verification emails")
    ml_sub = ml.add_subparsers(dest="mail_cmd", required=True)
    mls = ml_sub.add_parser("set-password", help="store the mailbox app password "
                                                 "(prompted, never echoed)")
    mls.add_argument("--backup", action="store_true",
                     help="the mailbox of contact.backup_email (apply.mail_backup)")
    mls.add_argument("--host", help="IMAP host, saved to settings (default: settings)")
    mls.add_argument("--user", help="IMAP username, saved to settings (default: settings)")
    mlt = ml_sub.add_parser("test", help="log in read-only and count INBOX messages")
    mlt.add_argument("--backup", action="store_true",
                     help="test the backup mailbox (apply.mail_backup)")
    mlt.add_argument("--find-from", metavar="DOMAIN",
                     help="also print the time of the newest message from DOMAIN")
    ml.set_defaults(fn=cmd_mail)
    # --- accounts (M20 lane V, D-78 lane N WP-N1)
    ac = sub.add_parser("accounts", help="ATS accounts: list, add one you have, export to Edge")
    ac_sub = ac.add_subparsers(dest="accounts_cmd", required=True)
    ac_sub.add_parser("list", help="every account (never a password)")
    aca = ac_sub.add_parser("add", help="store the password of an account you already have "
                                        "(prompted, never echoed)")
    aca.add_argument("--url", required=True, help="a posting or careers-site URL on that tenant")
    aca.add_argument("--email", required=True, help="the account's email address")
    ace = ac_sub.add_parser("export-edge", help="write a CSV for Edge's password import")
    ace.add_argument("--confirm", action="store_true",
                     help="the export is imported: delete the newest file and mark its accounts")
    ac.set_defaults(fn=cmd_accounts)
    # --- apply (M20 lane B)
    apl = sub.add_parser("apply", help="auto-apply to jobs (dry run: fill, never send); "
                                       "`apply show ID`, `apply open-profile [URL]`")
    apl.add_argument("words", nargs="+", metavar="JOB_ID",
                     help="job ids (up to 20); or `show <job_id|attempt_id>`; "
                          "or `open-profile [URL]`")
    apl.add_argument("--dry-run", action="store_true",
                     help="fill every form and stop before Submit (wins over apply.mode)")
    apl.set_defaults(fn=cmd_apply)
    return p


def _install_cancel_handler() -> None:
    """The web app's Cancel ends a job through its `finally` blocks, so the run
    is marked failed ("cancelled") instead of left `running` (C-4).

    Windows: the web app starts each job in its own process group and sends it
    CTRL_BREAK_EVENT, which Python sees as SIGBREAK. POSIX: SIGTERM. Either way
    the handler raises `pipeline.JobCancelled` and the command exits 143. If the
    job does not stop within the grace period the web app kills it outright.

    One-shot: once it has fired, the signal is ignored so a second one cannot
    interrupt the cleanup."""
    sig = getattr(signal, "SIGBREAK", None) if sys.platform == "win32" else signal.SIGTERM
    if sig is None:
        return

    def handler(signum, frame):
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (ValueError, OSError):
            pass
        raise pipeline.JobCancelled("cancelled")
    try:
        signal.signal(sig, handler)
    except (ValueError, OSError):       # not the main thread, or no such signal here
        pass


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    if getattr(args, "fn", None) is not cmd_web:    # uvicorn handles the server's own signals
        _install_cancel_handler()
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except pipeline.JobCancelled:
        print("\ncancelled", file=sys.stderr)
        return EXIT_CANCELLED


if __name__ == "__main__":
    raise SystemExit(main())
