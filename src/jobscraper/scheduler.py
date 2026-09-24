"""Who is due to be scraped, and when.

A company is due when it has never been scraped, or was last scraped more than
`cycle_days` ago. Each run takes the `batch_size` most-neglected due companies.

This replaces v1's global cursor. A cursor answers "how far through the list are
we"; it cannot answer "has *this company* been checked in the past two weeks",
which is the actual question - and the one that makes looping back to the first
company stop being a special case.

`last_scraped_at` is stamped on attempt, not success: a company that reliably
returns 403 must not monopolise every batch.

See PRD section 8.3[0]. The SQL lives in store.py; this module owns the policy
around it - the cut-off, the empty-queue answer, and the cadence report.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from .models import WatchedCompany
from .store import TIME_FMT, Store, shift, utcnow

SOON_DAYS = 7          # "due within 7 days" in the status report


def cutoff(now: str, cycle_days: int) -> str:
    """Anything last scraped at or before this moment is due again."""
    return shift(now, days=-cycle_days)


@dataclass
class Plan:
    due: list[WatchedCompany]
    next_due_at: Optional[str]   # set only when nothing is due: when something will be

    @property
    def empty(self) -> bool:
        return not self.due


def plan(store: Store, batch_size: int, cycle_days: int,
         now: Optional[str] = None) -> Plan:
    """This run's batch. Reads only; stamping happens after the run succeeds."""
    now = now or utcnow()
    due = store.due_companies(cutoff(now, cycle_days), batch_size)
    if due:
        return Plan(due, None)
    oldest = store.schedule_counts(cutoff(now, cycle_days), now)["oldest_scrape"]
    return Plan([], shift(oldest, days=cycle_days) if oldest else None)


def mark_attempted(store: Store, companies: Iterable[WatchedCompany],
                   now: Optional[str] = None) -> None:
    """Stamp the batch as attempted - failures included (D-9).

    The pipeline calls this last, after jobs, prefilter and decisions are
    persisted, so a crash mid-run leaves the queue as it was (PRD 8.3[0]).
    """
    store.stamp_scraped([c.id for c in companies], at=now or utcnow())


@dataclass
class Status:
    now: str
    enabled: int
    due_now: int
    due_soon: int
    never_scraped: int
    quarantined: list[WatchedCompany]
    next_due_at: Optional[str]
    runs_per_day: Optional[float]   # observed; None until a run has finished
    runs_needed: int
    projected_done: Optional[str]   # when today's due queue drains at that rate
    required_runs_per_day: float    # what a full sweep in cycle_days needs (R-7)


def status(store: Store, batch_size: int, cycle_days: int,
           now: Optional[str] = None) -> Status:
    now = now or utcnow()
    cut = cutoff(now, cycle_days)
    counts = store.schedule_counts(cut, shift(cut, days=SOON_DAYS))
    runs, first = store.finished_runs_since(cut)
    rate: Optional[float] = None
    if runs and first:
        # Rate over the window actually observed, floored at one day so a
        # couple of runs in the first hour do not project an absurd pace.
        span = (_dt(now) - _dt(first)).total_seconds() / 86400
        rate = runs / max(span, 1.0)
    needed = math.ceil(counts["due_now"] / batch_size) if batch_size else 0
    done = None
    if needed == 0:
        done = now
    elif rate:
        done = shift(now, days=needed / rate)
    oldest = counts["oldest_scrape"]
    return Status(
        now=now, enabled=counts["enabled"], due_now=counts["due_now"],
        due_soon=counts["due_soon"], never_scraped=counts["never_scraped"],
        quarantined=store.quarantined_companies(),
        next_due_at=(shift(oldest, days=cycle_days)
                     if counts["due_now"] == 0 and oldest else None),
        runs_per_day=rate, runs_needed=needed, projected_done=done,
        required_runs_per_day=(counts["enabled"] / batch_size / cycle_days
                               if batch_size and cycle_days else 0.0))


def describe(st: Status) -> str:
    """The `status` report: queue depth, cadence, and whether it keeps up."""
    lines = [
        f"due now        {st.due_now} of {st.enabled} enabled "
        f"({st.never_scraped} never scraped)",
        f"due in {SOON_DAYS} days   {st.due_soon}",
        f"quarantined    {len(st.quarantined)}",
    ]
    if st.due_now == 0 and st.next_due_at:
        lines.append(f"next due       {st.next_due_at} UTC - nothing to scrape yet")
    rate = f"{st.runs_per_day:.1f}/day" if st.runs_per_day else "no finished runs yet"
    lines.append(f"run rate       {rate}; a full sweep needs "
                 f"{st.required_runs_per_day:.1f}/day")
    if st.due_now:
        when = st.projected_done or "unknown until a run finishes"
        lines.append(f"queue drains   in {st.runs_needed} runs, projected {when}")
        if st.runs_per_day and st.runs_per_day < st.required_runs_per_day:
            lines.append("               below the sweep rate: the oldest companies "
                         "will go stale past the cycle (PRD R-7)")
    for c in st.quarantined[:15]:
        lines.append(f"  quarantined  {c.name:<26} {c.last_error_class or '':<10} "
                     f"{(c.last_error or '')[:40]}")
    return "\n".join(lines)


def _dt(stamp: str) -> datetime:
    return datetime.strptime(stamp, TIME_FMT)
