"""Orchestration: plan a batch, fetch it, match it, write the trackers.

Failure policy (DESIGN.md 3.9):
  - every company fetch is isolated; no exception escapes
  - a failure is classified, counted, and the company is SKIPPED for this run
  - 3 consecutive failures -> one automatic re-resolution attempt -> quarantine
  - quarantined companies retry once every Nth run (probation)
  - if more than half the batch fails, treat it as a local fault: quarantine
    nobody and roll the failure counters back
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from . import cursor as cursor_mod
from . import discovery
from .adapters import get_adapter
from .config import Config, Profile
from .llm import Judge
from .matching import apply_facts, score_batch, stage_a
from .models import Candidate, Company, FetchOutcome, TokenLedger
from .net import FetchError, HttpClient
from .output import (write_application_tracker, write_html_view,
                     write_needs_review, write_run_tracker)
from .store_v1 import Store


@dataclass
class RunReport:
    run_no: int = 0
    status: str = "ok"
    batch_label: str = ""
    companies: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    postings: int = 0
    new: int = 0
    matched: int = 0
    exported: int = 0
    quarantined: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    ledger: Optional[TokenLedger] = None
    message: str = ""


def _fetch_one(client: HttpClient, company: Company) -> FetchOutcome:
    """Fetch one company. Returns an outcome; never raises."""
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


def ensure_resolved(client: HttpClient, store: Store, company: Company,
                    verbose: bool = True) -> Company:
    if company.provider:
        return company
    res = discovery.resolve(client, company)
    if res.provider:
        store.set_resolution(company.id, res.provider, res.slug, res.feed_url,
                             res.method)
        if verbose:
            tail = "/" + res.slug if res.slug else ""
            print(f"        resolved -> {res.provider}{tail} ({res.method})")
        return store.get_company(company.id) or company
    if verbose:
        print(f"        unresolved: {res.note}")
    return company


def run_batch(cfg: Config, profile: Profile, store: Store, *,
              force: bool = False, batch_size: Optional[int] = None,
              dry_run: bool = False, verbose: bool = True) -> RunReport:
    rc = cfg.run
    size = batch_size or int(rc["batch_size"])
    companies = store.all_companies()

    plan = cursor_mod.plan_batch(store, companies, size, int(rc["cycle_days"]),
                                 force=force)
    if plan.blocked:
        return RunReport(status="blocked", message=plan.message)

    # Probation: quarantined companies get one retry every Nth run.
    next_run_no = store.last_run_no() + 1
    in_batch = {b.id for b in plan.companies}
    probation = [c for c in store.due_probation(next_run_no) if c.id not in in_batch]
    batch = list(plan.companies) + probation

    label = (f"companies {plan.start_ordinal}-{plan.end_ordinal} "
             f"of {len(companies)} (cycle {plan.cycle.cycle_id})")
    if probation:
        label += f" + {len(probation)} on probation"

    rep = RunReport(batch_label=label, companies=len(batch))
    ledger = TokenLedger()
    rep.ledger = ledger

    if verbose:
        print(f"\nRun plan: {label}")
        if plan.fresh_cycle:
            print(f"  new cycle {plan.cycle.cycle_id} starts now")

    run_no = store.start_run(plan.cycle.cycle_id, plan.start_ordinal,
                             plan.end_ordinal)
    rep.run_no = run_no

    client = HttpClient(
        user_agent=rc["user_agent"], timeout=float(rc["request_timeout"]),
        delay=float(rc["rate_limit_delay"]), max_retries=int(rc["max_retries"]),
        respect_robots=bool(rc.get("respect_robots", True)))

    try:
        # ---- resolve (sequential: cheap, and it mutates the DB) ----
        resolved: list[Company] = []
        for c in batch:
            if verbose:
                print(f"  [{c.ordinal:>3}] {c.name}")
            resolved.append(ensure_resolved(client, store, c, verbose))

        # ---- fetch (parallel, isolated) ----
        outcomes: dict[int, FetchOutcome] = {}
        workers = max(1, int(rc["max_workers"]))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_one, client, c): c for c in resolved}
            for fut in as_completed(futures):
                c = futures[fut]
                try:
                    out = fut.result(timeout=float(rc["per_company_timeout"]))
                except Exception as exc:
                    out = FetchOutcome(c.id, False, error_class="transient",
                                       error=f"worker timeout: {exc}")
                outcomes[c.id] = out

        failures = [c for c in resolved if not outcomes[c.id].ok]
        unhealthy = (len(failures) / max(len(resolved), 1)
                     > float(rc["global_failure_abort_pct"]))

        # ---- per-company bookkeeping + delta ----
        all_new: list[Candidate] = []
        by_id = {c.id: c for c in resolved}

        for cid, out in outcomes.items():
            company = by_id[cid]
            if not out.ok:
                rep.failed += 1
                rep.errors.append((company.name, f"{out.error_class}: {out.error}"))
                if verbose:
                    print(f"  !! {company.name}: {out.error_class} - "
                          f"{(out.error or '')[:90]}")
                store.record_coverage(run_no, cid, "failed", 0, 0, 0,
                                      out.http_status, out.error_class, out.error)
                continue

            rep.ok += 1
            known = store.known_job_ids(cid)
            new_here: list[Candidate] = []
            for raw in out.jobs:
                jid = raw.job_id(cid, company.provider or "")
                if jid not in known:
                    new_here.append(Candidate(job_id=jid, company=company, raw=raw))

            rep.postings += len(out.jobs)
            rep.new += len(new_here)
            all_new.extend(new_here)

            store.record_coverage(run_no, cid, "ok" if out.jobs else "empty",
                                  len(out.jobs), len(new_here), 0, None, None, None)
            if verbose:
                print(f"  -> {company.name}: {len(out.jobs)} postings, "
                      f"{len(new_here)} new")

        # ---- failure policy ----
        if unhealthy and failures:
            store.rollback_failures([c.id for c in failures])
            rep.status = "aborted_unhealthy"
            rep.message = (
                f"{len(failures)}/{len(resolved)} companies failed - treating this "
                "as a local network fault. No company was quarantined and failure "
                "counters were rolled back. Check your connection and re-run.")
            if verbose:
                print(f"\n  !! {rep.message}")
        else:
            for c in failures:
                out = outcomes[c.id]
                count = store.record_failure(c.id, out.error_class or "unknown",
                                             out.error or "")
                if count >= int(rc["quarantine_threshold"]):
                    if not _try_reresolve(client, store, c, verbose):
                        store.quarantine(
                            c.id, run_no + int(rc["probation_every_n_runs"]))
                        rep.quarantined.append(c.name)
                        if verbose:
                            print(f"  ** quarantined {c.name} after {count} failures")

        probation_ids = {p.id for p in probation}
        for c in resolved:
            if outcomes[c.id].ok:
                was_quarantined = c.id in probation_ids
                store.record_success(c.id)
                if was_quarantined and verbose:
                    print(f"  ** {c.name} recovered from quarantine")

        # ---- match funnel ----
        matched = _match(all_new, profile, cfg, store, ledger, verbose)
        rep.matched = len(matched)

        # Persist jobs after matching so hydrated descriptions are stored.
        # close_missing runs only for SUCCESSFUL fetches.
        for cid, out in outcomes.items():
            if not out.ok:
                continue
            known = store.known_job_ids(cid)
            seen: set[str] = set()
            for raw in out.jobs:
                jid = raw.job_id(cid, by_id[cid].provider or "")
                seen.add(jid)
                store.upsert_job(jid, cid, raw, run_no, jid not in known)
            store.commit()
            store.close_missing(cid, seen)

        for cand in all_new:
            store.save_score(cand, profile.version)

        # ---- outputs ----
        out_dir = cfg.output_dir
        if not dry_run:
            rep.exported = write_application_tracker(
                out_dir / "application_tracker.xlsx", matched, run_no, store)
            write_html_view(out_dir / f"matches_run{run_no}.html", matched,
                            run_no, label)
            write_html_view(out_dir / "latest_matches.html", matched, run_no, label)

        stats = {
            "companies": rep.companies, "ok": rep.ok, "failed": rep.failed,
            "skipped": rep.skipped, "postings": rep.postings, "new": rep.new,
            "matched": rep.matched, "exported": rep.exported,
            **ledger.as_dict(),
        }
        store.finish_run(run_no, rep.status, stats)
        cursor_mod.advance(store, plan, run_no)

        if not dry_run:
            write_run_tracker(out_dir / "run_tracker.xlsx", store)
            write_needs_review(out_dir / "needs_review.xlsx", store)

        return rep
    finally:
        client.close()


def _try_reresolve(client: HttpClient, store: Store, company: Company,
                   verbose: bool) -> bool:
    """One automatic re-resolution attempt before quarantine (ATS migrations)."""
    res = discovery.resolve(client, company)
    if res.provider and res.provider != company.provider:
        store.set_resolution(company.id, res.provider, res.slug, res.feed_url,
                             f"reresolve:{res.method}")
        if verbose:
            print(f"  ** re-resolved {company.name} -> {res.provider}")
        return True
    return False


def _match(cands: list[Candidate], profile: Profile, cfg: Config, store: Store,
           ledger: TokenLedger, verbose: bool) -> list[Candidate]:
    if not cands:
        return []

    survivors = [c for c in cands if stage_a(c, profile)]
    if verbose:
        print(f"\n  Stage A: {len(cands)} new -> {len(survivors)} survive")
    if not survivors:
        return []

    # Hydrate descriptions only for survivors: no detail request is ever spent
    # on a posting the title filter already rejected.
    rc = cfg.run
    client = HttpClient(user_agent=rc["user_agent"],
                        timeout=float(rc["request_timeout"]),
                        delay=float(rc["rate_limit_delay"]), max_retries=2,
                        respect_robots=bool(rc.get("respect_robots", True)))
    try:
        for c in survivors:
            if c.raw.description:
                continue
            adapter = get_adapter(c.company.provider)
            if adapter is None:
                continue
            try:
                adapter.hydrate(client, c.company, c.raw)
            except Exception:
                pass
    finally:
        client.close()

    score_batch(survivors, profile)

    judge = Judge(profile, store, cfg.budget, ledger, verbose)
    if verbose:
        if judge.enabled:
            print(f"  Judge: {judge.describe()}")
        else:
            print(f"  Judge stage skipped: {judge.disabled_reason}")
            print("  (scoring locally; `python -m jobscraper review --export` "
                  "to judge these in a Claude Code session)")

    if judge.enabled:
        judge.extract(survivors)
        survivors = [c for c in survivors if apply_facts(c, profile)]
        if verbose:
            print(f"  Stage C1: {len(survivors)} survive extraction")

    th = profile.thresholds
    lo, hi = th["llm_band"]
    band = [c for c in survivors if lo <= c.score.total <= hi]
    auto_ids = {id(c) for c in survivors if c.score.total > hi}

    if judge.enabled and band:
        if verbose:
            print(f"  Stage C2: adjudicating {len(band)} in band [{lo}, {hi}]")
        judge.adjudicate(band)

    keep_verdicts = set(cfg.output.get("export_verdicts",
                                       ["strong", "possible", "contested"]))
    min_score = float(cfg.output.get("min_score_to_export", 25))

    matched: list[Candidate] = []
    for c in survivors:
        if c.score.total < min_score:
            continue
        if id(c) in auto_ids:
            matched.append(c)
        elif c.verdict:
            if c.verdict.verdict in keep_verdicts:
                matched.append(c)
        elif c.score.total >= th["auto_reject_below"]:
            # No LLM available: fall back to the local score alone.
            matched.append(c)

    if verbose:
        print(f"  Matched: {len(matched)}")
    return matched
