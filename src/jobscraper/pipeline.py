"""Wires the stages together. The only module that knows the whole sequence.

    sync watchlist -> schedule -> scrape -> prefilter -> vital extract
    -> decide -> shortlist

Stages never import each other; they are composed here. That is what keeps each
one testable alone and lets the order change without touching any of them.

The order is chosen so a crash is never worse than a no-op: the scrape timestamp
is written last, after the work it stands for is already durable.

Replaces v1's runner.py, and keeps its hard-won failure policy:
  - every company fetch is isolated; no exception escapes
  - a failure is classified, counted, and the company is skipped for this run
  - `quarantine_threshold` consecutive failures -> one automatic re-resolution
    attempt (ATS migrations) -> quarantine
  - quarantined companies retry once every `probation_every_n_runs` runs
  - if more than `global_failure_abort_pct` of the batch fails, the fault is
    local (the network, not the companies): nobody is charged a failure, nobody
    is quarantined, and nobody is stamped - so re-running retries the same batch

See PRD sections 8.2 and 8.3.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import scheduler, watchlist
from .config import Config
from .models import FetchOutcome, WatchedCompany
from .scrape import discovery
from .scrape.adapters import get_adapter
from .scrape.net import FetchError, HttpClient
from .store import Store

Fetcher = Callable[[HttpClient, WatchedCompany], FetchOutcome]
Resolver = Callable[[HttpClient, WatchedCompany], "discovery.Resolution"]


@dataclass
class RunReport:
    status: str = "ok"          # ok | nothing_due | aborted_unhealthy | dry_run
    run_no: int = 0             # 0 when no run row was written
    due: list[str] = field(default_factory=list)
    probation: list[str] = field(default_factory=list)
    ok: int = 0
    failed: int = 0
    postings: int = 0
    new: int = 0
    quarantined: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    relinked: int = 0
    next_due_at: Optional[str] = None
    message: str = ""
    stats: dict[str, Any] = field(default_factory=dict)


def fetch_one(client: HttpClient, company: WatchedCompany) -> FetchOutcome:
    """Fetch one company's listings. Returns an outcome; never raises."""
    started = time.monotonic()
    try:
        adapter = get_adapter(company.provider)
        if adapter is None:
            return FetchOutcome(company.id, False, error_class="schema",
                                error=f"no adapter for provider {company.provider!r}",
                                duration_s=time.monotonic() - started)
        jobs = adapter.fetch(client, company)
        return FetchOutcome(company.id, True, jobs=jobs, provider=company.provider,
                            duration_s=time.monotonic() - started)
    except FetchError as exc:
        return FetchOutcome(company.id, False, error_class=exc.kind,
                            error=exc.message, http_status=exc.status,
                            duration_s=time.monotonic() - started)
    except Exception as exc:  # adapter bug, unexpected payload shape, anything
        return FetchOutcome(company.id, False, error_class="schema",
                            error=f"{type(exc).__name__}: {exc}",
                            duration_s=time.monotonic() - started)


def make_client(cfg: Config) -> HttpClient:
    rc = cfg.run
    return HttpClient(
        user_agent=rc["user_agent"], timeout=float(rc["request_timeout"]),
        delay=float(rc["rate_limit_delay"]), max_retries=int(rc["max_retries"]),
        respect_robots=bool(rc.get("respect_robots", True)))


def run(cfg: Config, store: Store, *, dry_run: bool = False,
        batch_size: Optional[int] = None, now: Optional[str] = None,
        fetcher: Fetcher = fetch_one, resolver: Optional[Resolver] = None,
        client: Optional[HttpClient] = None, verbose: bool = True) -> RunReport:
    """One run: sync, schedule, scrape, persist, stamp.

    `--dry-run` fetches and reports but writes nothing that a run produces -
    no run row, no jobs, no coverage, no failure counts, no resolution, and
    above all no `last_scraped_at` - so a dry run never consumes the queue.
    (The watchlist sync still runs: it reconciles configuration, is
    idempotent, and without it a just-added company would be invisible.)

    `fetcher`, `resolver` and `client` exist so tests can run the whole
    sequence without a network.
    """
    rc = cfg.run
    say = print if verbose else (lambda *a, **k: None)
    resolve = resolver or discovery.resolve

    if not dry_run:
        reaped = store.reap_stale_runs(float(rc.get("per_run_timeout", 3600)), now=now)
        if reaped:
            say(f"marked {reaped} crashed run(s) failed")
    store.sync_watchlist(watchlist.load(cfg.watchlist_path))

    plan = scheduler.plan(store, batch_size or cfg.batch_size, cfg.cycle_days, now=now)
    next_run = store.last_run_no() + 1
    in_batch = {c.id for c in plan.due}
    probation = [c for c in store.due_probation(next_run) if c.id not in in_batch]
    batch = list(plan.due) + probation
    rep = RunReport(due=[c.name for c in plan.due],
                    probation=[c.name for c in probation])

    if not batch:
        rep.status = "nothing_due"
        rep.next_due_at = plan.next_due_at
        rep.message = ("nothing is due" + (f"; next company due {plan.next_due_at} UTC"
                                           if plan.next_due_at else ""))
        say(rep.message)
        return rep

    say(f"\nRun plan: {len(plan.due)} due" +
        (f" + {len(probation)} on probation" if probation else "") +
        (" (dry run - nothing will be written)" if dry_run else ""))
    if not dry_run:
        rep.run_no = store.start_run(at=now)

    own_client = client is None
    client = client or make_client(cfg)
    try:
        # ---- resolve (sequential: cheap, and it mutates the DB) ----
        resolved: list[WatchedCompany] = []
        for c in batch:
            say(f"  {c.name}")
            resolved.append(_ensure_resolved(client, store, c, resolve, dry_run, say))

        # ---- fetch (parallel, isolated) ----
        outcomes: dict[int, FetchOutcome] = {}
        with ThreadPoolExecutor(max_workers=max(1, int(rc["max_workers"]))) as pool:
            futures = {pool.submit(fetcher, client, c): c for c in resolved}
            for fut in as_completed(futures):
                c = futures[fut]
                try:
                    outcomes[c.id] = fut.result()
                except Exception as exc:     # a fetcher that broke its own contract
                    outcomes[c.id] = FetchOutcome(c.id, False, error_class="transient",
                                                  error=f"worker error: {exc}")

        failures = [c for c in resolved if not outcomes[c.id].ok]
        unhealthy = (len(failures) / max(len(resolved), 1)
                     > float(rc["global_failure_abort_pct"]))

        # ---- delta per company ----
        new_by_company: dict[int, int] = {}
        for c in resolved:
            out = outcomes[c.id]
            if not out.ok:
                rep.failed += 1
                rep.errors.append((c.name, f"{out.error_class}: {out.error}"))
                say(f"  !! {c.name}: {out.error_class} - {(out.error or '')[:90]}")
                continue
            rep.ok += 1
            known = store.known_job_ids(c.id)
            new = sum(1 for raw in out.jobs
                      if raw.job_id(c.id, c.provider or "") not in known)
            new_by_company[c.id] = new
            rep.postings += len(out.jobs)
            rep.new += new
            say(f"  -> {c.name}: {len(out.jobs)} postings, {new} new")

        rep.stats = {
            "companies_due": len(plan.due), "companies_probation": len(probation),
            "companies_fetched": rep.ok, "companies_failed": rep.failed,
            "postings_seen": rep.postings, "postings_new": rep.new,
        }
        if dry_run:
            rep.status = "dry_run"
            return rep

        # ---- persist: coverage, failure policy, jobs ----
        for c in resolved:
            out = outcomes[c.id]
            if out.ok:
                store.record_coverage(rep.run_no, c.id, "ok" if out.jobs else "empty",
                                      len(out.jobs), new_by_company[c.id], 0,
                                      None, None, None)
            else:
                store.record_coverage(rep.run_no, c.id, "failed", 0, 0, 0,
                                      out.http_status, out.error_class, out.error)

        if unhealthy and failures:
            rep.status = "aborted_unhealthy"
            rep.message = (
                f"{len(failures)}/{len(resolved)} companies failed - treating this "
                "as a local network fault. No failures were counted, nobody was "
                "quarantined, and the batch was not stamped: re-run to retry it.")
            say(f"\n  !! {rep.message}")
        else:
            for c in failures:
                out = outcomes[c.id]
                count = store.record_failure(c.id, out.error_class or "unknown",
                                             out.error or "")
                if count >= int(rc["quarantine_threshold"]):
                    if not _try_reresolve(client, store, c, resolve, say):
                        store.quarantine(
                            c.id, rep.run_no + int(rc["probation_every_n_runs"]))
                        rep.quarantined.append(c.name)
                        say(f"  ** quarantined {c.name} after {count} failures")

        probation_ids = {c.id for c in probation}
        for c in resolved:
            out = outcomes[c.id]
            if not out.ok:
                continue
            store.record_success(c.id)
            if c.id in probation_ids:
                say(f"  ** {c.name} recovered from quarantine")
            # close_missing runs ONLY after a successful fetch: a timeout must
            # never mass-close a company's postings.
            known = store.known_job_ids(c.id)
            seen: set[str] = set()
            for raw in out.jobs:
                jid = raw.job_id(c.id, c.provider or "")
                seen.add(jid)
                store.upsert_job(jid, c.id, raw, rep.run_no, jid not in known)
            store.commit()
            store.close_missing(c.id, seen)

        rep.relinked = store.relink_orphan_applications()
        if rep.relinked:
            say(f"  linked {rep.relinked} earlier application(s) to their postings")

        # ---- [3]-[6] prefilter, vital extract, decide, shortlist: M4-M5 ----

        # ---- last: stamp the attempt and close the run ----
        if rep.status == "ok":
            scheduler.mark_attempted(store, resolved, now=now)
        store.finish_run(rep.run_no, rep.status, rep.stats)
        return rep
    finally:
        if own_client:
            client.close()


def _ensure_resolved(client: HttpClient, store: Store, company: WatchedCompany,
                     resolve: Resolver, dry_run: bool, say) -> WatchedCompany:
    """Find the company's ATS if it has none cached. A dry run does not keep it."""
    if company.provider:
        return company
    res = resolve(client, company)
    if not res.provider:
        say(f"        unresolved: {res.note}")
        return company
    tail = "/" + res.slug if res.slug else ""
    say(f"        resolved -> {res.provider}{tail} ({res.method})")
    if dry_run:
        company.provider, company.slug, company.feed_url = res.provider, res.slug, res.feed_url
        return company
    store.set_resolution(company.id, res.provider, res.slug, res.feed_url, res.method)
    return store.get_company(company.id) or company


def _try_reresolve(client: HttpClient, store: Store, company: WatchedCompany,
                   resolve: Resolver, say) -> bool:
    """One automatic re-resolution attempt before quarantine (ATS migrations)."""
    res = resolve(client, company)
    if res.provider and res.provider != company.provider:
        store.set_resolution(company.id, res.provider, res.slug, res.feed_url,
                             f"reresolve:{res.method}")
        say(f"  ** re-resolved {company.name} -> {res.provider}")
        return True
    return False
