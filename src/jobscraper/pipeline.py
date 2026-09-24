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

from . import backends, decide, scheduler, shortlist, watchlist
from . import filter as prefilter
from .config import Config
from .models import FetchOutcome, RawJob, WatchedCompany
from .profile import keywords, resume_ingest
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
        client: Optional[HttpClient] = None, backend: Optional[backends.Backend] = None,
        profile: Optional[dict[str, Any]] = None, verbose: bool = True) -> RunReport:
    """One run: sync, schedule, scrape, persist, stamp.

    `--dry-run` fetches and reports but writes nothing that a run produces -
    no run row, no jobs, no coverage, no failure counts, no resolution, and
    above all no `last_scraped_at` - so a dry run never consumes the queue.
    (The watchlist sync still runs: it reconciles configuration, is
    idempotent, and without it a just-added company would be invisible.)

    `fetcher`, `resolver`, `client`, `backend` and `profile` exist so tests
    can run the whole sequence without a network or a model.
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

        # One posting listed twice (overlapping pages) is one posting.
        for c in resolved:
            out = outcomes[c.id]
            if out.ok:
                uniq: dict[str, RawJob] = {}
                for raw in out.jobs:
                    uniq.setdefault(raw.job_id(c.id, c.provider or ""), raw)
                out.jobs = list(uniq.values())

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

        # ---- [1] profile, [3] prefilter, [4] extract, [5] decide, [6] shortlist ----
        _funnel(cfg, store, rep, client, backend, profile, say)

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


def _funnel(cfg: Config, store: Store, rep: RunReport, client: HttpClient,
            backend: Optional[backends.Backend], profile: Optional[dict[str, Any]],
            say) -> None:
    """Stages [1] and [3]-[6], over everything still pending - not just this run.

    Work is selected by what is missing, not by run number: postings with no
    prefilter verdict for the current rules and profile, and survivors with no
    decision for their current extract. So a rules edit re-checks the corpus, a
    failed model call is retried next run, and a crash loses nothing - each
    verdict is content-keyed and durable the moment it is written.
    """
    if profile is None:
        try:
            resume_ingest.ingest(cfg, log=say)
            profile = resume_ingest.load_derived_profile(cfg)
        except (resume_ingest.ProfileError, resume_ingest.ResumeError) as exc:
            rep.message = (f"profile unavailable ({exc}); postings were stored and "
                           "will be filtered on the next run that has one")
            say(f"  !! {rep.message}")
            return
    ruleset = prefilter.load_rules(cfg.rules_path)
    pv = int(profile.get("profile_version", 1))

    # ---- [3] prefilter: free. Descriptions are fetched only for survivors ----
    pending = store.jobs_pending_prefilter(pv, ruleset.hash)
    rejected: dict[str, int] = {}
    passed = hydrated = 0
    for job in pending:
        posting = {"title": job["title"], "location": job["location"],
                   "description": job["jd_text"] or ""}
        res = prefilter.evaluate(posting, ruleset, profile, keywords.overlap)
        if res.passed and not posting["description"]:
            text = _hydrate(client, store, job)
            if text:
                hydrated += 1
                posting["description"] = text
                res = prefilter.evaluate(posting, ruleset, profile, keywords.overlap)
        store.save_prefilter(job["job_id"], pv, ruleset.hash, res.passed,
                             res.reject_rule, res.reject_detail, res.overlap_score)
        if res.passed:
            passed += 1
        else:
            key = res.reject_rule or "?"
            rejected[key] = rejected.get(key, 0) + 1
    rep.stats.update(prefilter_evaluated=len(pending), prefilter_passed=passed,
                     prefilter_rejected_by_rule=rejected, hydrated=hydrated)
    say(f"  prefilter: {len(pending)} evaluated, {passed} passed"
        + (f", {hydrated} descriptions fetched" if hydrated else ""))

    # ---- [4] vital extract ----
    limit = int(cfg.budget.get("vital_chars", 800))
    postings = []
    for job in store.jobs_passed_prefilter(pv, ruleset.hash):
        vital = decide.vital_extract(job["title"] or "", job["location"] or "",
                                     job["jd_text"] or "", limit=limit)
        if vital != job["vital_text"]:
            store.set_vital(job["job_id"], vital)
        postings.append(decide.Posting(job["job_id"], job["title"] or "", vital))
    sizes = sorted(len(p.vital_text) for p in postings)
    if sizes:
        rep.stats.update(vital_chars_p50=sizes[len(sizes) // 2],
                         vital_chars_max=sizes[-1])

    # ---- [5] decide: the only paid step ----
    budget = cfg.budget
    backend = backend or backends.build(budget)
    if not budget.get("enable_llm", True) or not backend.available:
        why = ("disabled in config" if not budget.get("enable_llm", True)
               else backend.unavailable_reason or "no model transport")
        rep.stats["awaiting_model"] = len(postings)
        say(f"  decide: skipped ({why}); {len(postings)} postings wait for a model")
    else:
        def save(d: decide.Decision) -> None:
            store.save_decision(d.job_id, pv, d.vital_hash, d.decision,
                                d.is_singapore, d.yoe_min, d.reason, d.model)
        _, ds = decide.decide(
            postings, summary=str(profile.get("summary") or ""), backend=backend,
            model=str(budget.get("model", "")),
            lookup=lambda job_id, h: store.get_decision(job_id, pv, h), save=save,
            batch_size=int(budget.get("decide_batch", 20)),
            ceiling_years=int(ruleset.ceiling_years or 3),
            max_consecutive_failures=int(budget.get("max_consecutive_failures", 3)))
        rep.stats.update(judged=ds.judged, decisions_cached=ds.cached,
                         undecided=ds.undecided, accepted_total=ds.accepted,
                         rejected_by_postcondition=ds.rejected_by_postcondition,
                         model_calls=ds.model_calls, input_tokens=ds.input_tokens,
                         output_tokens=ds.output_tokens)
        say(f"  decide: {ds.judged} judged in {ds.model_calls} call(s), "
            f"{ds.cached} cached, {ds.undecided} undecided; "
            f"{ds.input_tokens:,} tokens in")
        for err in ds.errors[:3]:
            say(f"  !! model: {err}")

    # ---- [6] shortlist ----
    doc = shortlist.write(store, cfg.shortlist_path, pv)
    rep.stats["shortlisted"] = len(doc["jobs"])
    say(f"  shortlist: {len(doc['jobs'])} roles -> {cfg.shortlist_path}")


def _hydrate(client: HttpClient, store: Store, job: dict[str, Any]) -> str:
    """Fetch a survivor's full description, when its listing came without one.

    Only postings that already passed the title and location rules get here, so
    no detail request is spent on a role the free rules would reject (v1's
    discipline). A failure just leaves the posting description-less.
    """
    adapter = get_adapter(job["provider"])
    company = store.get_company(job["company_id"])
    if adapter is None or company is None:
        return ""
    raw = RawJob(external_id=job["external_id"] or "", title=job["title"] or "",
                 url=job["url"] or "", location=job["location"] or "")
    try:
        adapter.hydrate(client, company, raw)
    except Exception:           # an adapter bug must not sink the run
        return ""
    if raw.description:
        store.set_description(job["job_id"], raw.description)
    return raw.description
