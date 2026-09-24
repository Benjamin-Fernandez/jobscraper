"""The batch cursor.

Each invocation processes exactly `batch_size` companies and then stops. The cursor
advances so the next invocation picks up where this one left off:

    Mon  run -> companies 1-10
    Tue  run -> companies 11-20
    Tue  run -> companies 21-30

When the cursor reaches the end of the list the cycle is complete. A new cycle (back
to company 1) may not start until `cycle_days` have elapsed since the cycle's first
batch. If that time has not passed, `run` reports the date the next cycle opens and
exits without processing. `--force` overrides the wait.

Deliberate choice: reaching the 14-day mark mid-list does NOT reset the cursor. The
list is finished first, so every company is checked exactly once per cycle. Resetting
on the clock alone would mean companies late in the list were rarely checked at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import Company, CycleState
from .store_v1 import Store


@dataclass
class BatchPlan:
    companies: list[Company]
    start_ordinal: int
    end_ordinal: int
    cycle: CycleState
    fresh_cycle: bool = False
    blocked: bool = False
    message: str = ""
    next_cycle_opens: Optional[str] = None


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def plan_batch(store: Store, companies: list[Company], batch_size: int,
               cycle_days: int, force: bool = False,
               now: Optional[datetime] = None) -> BatchPlan:
    now = now or datetime.now(timezone.utc)
    total = len(companies)
    state = store.get_cycle()
    fresh = False

    if state is None:
        state = CycleState(cycle_id=1,
                           cycle_started_at=now.strftime("%Y-%m-%dT%H:%M:%S"),
                           cursor=0, total_companies=total, last_run_no=0)
        fresh = True

    # The workbook may have grown or shrunk since the cycle began.
    state.total_companies = total

    if state.cursor >= total:
        elapsed = now - _parse(state.cycle_started_at)
        due = _parse(state.cycle_started_at) + timedelta(days=cycle_days)
        if elapsed >= timedelta(days=cycle_days) or force:
            state = CycleState(cycle_id=state.cycle_id + 1,
                               cycle_started_at=now.strftime("%Y-%m-%dT%H:%M:%S"),
                               cursor=0, total_companies=total,
                               last_run_no=state.last_run_no)
            fresh = True
        else:
            remaining = due - now
            hours = int(remaining.total_seconds() // 3600)
            return BatchPlan(
                companies=[], start_ordinal=0, end_ordinal=0, cycle=state,
                blocked=True,
                next_cycle_opens=due.strftime("%Y-%m-%d %H:%M UTC"),
                message=(
                    f"Cycle {state.cycle_id} is complete - all {total} companies "
                    f"checked. The next cycle opens in {hours}h "
                    f"({due.strftime('%Y-%m-%d %H:%M UTC')}). "
                    "Use --force to start it now."),
            )

    batch = companies[state.cursor:state.cursor + batch_size]
    return BatchPlan(
        companies=batch,
        start_ordinal=state.cursor + 1,
        end_ordinal=state.cursor + len(batch),
        cycle=state,
        fresh_cycle=fresh,
    )


def advance(store: Store, plan: BatchPlan, run_no: int) -> CycleState:
    """Move the cursor past the batch just processed and persist it.

    Called even when companies in the batch failed: a failed company is skipped,
    not retried in place, so the cursor always moves forward.
    """
    st = plan.cycle
    st.cursor = min(st.cursor + len(plan.companies), st.total_companies)
    st.last_run_no = run_no
    store.save_cycle(st)
    return st


def describe(store: Store, total: int, cycle_days: int, batch_size: int = 10) -> str:
    st = store.get_cycle()
    if st is None:
        return (f"No runs yet. Next run will process companies "
                f"1-{min(batch_size, total)} of {total}.")
    done = min(st.cursor, st.total_companies)
    pct = (done / st.total_companies * 100) if st.total_companies else 0
    started = _parse(st.cycle_started_at)
    due = started + timedelta(days=cycle_days)
    lines = [
        f"Cycle {st.cycle_id}  started {started.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Progress  {done}/{st.total_companies} companies ({pct:.0f}%)",
        f"Last run  #{st.last_run_no}",
    ]
    if done >= st.total_companies:
        now = datetime.now(timezone.utc)
        if now >= due:
            lines.append("Status    cycle complete; next run starts a new cycle at #1")
        else:
            lines.append(
                f"Status    cycle complete; next cycle opens "
                f"{due.strftime('%Y-%m-%d %H:%M UTC')}")
    else:
        nxt = done + 1
        lines.append(
            f"Next run  companies {nxt}-"
            f"{min(nxt + batch_size - 1, st.total_companies)}")
    return "\n".join(lines)
