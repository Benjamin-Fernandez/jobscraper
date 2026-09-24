"""The staleness scheduler (PRD 8.3[0], D-9) - the 14-day cycle per company.

The first three tests are v1's cursor tests restated for staleness: the
behaviour they protected (ten at a time, nothing re-scraped inside 14 days,
round again afterwards) survives; the global cursor that implemented it does
not. v1's `--force` has no equivalent - a queue ordered by staleness has no
cycle boundary to force past - so its test is retired rather than ported.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper import scheduler as S
from jobscraper.store import Store, shift

T0 = "2026-09-14T09:00:00"


def _store(n=25) -> Store:
    st = Store(Path(tempfile.mkdtemp()) / "t.db")
    for i in range(1, n + 1):
        st.insert_company(f"c{i:02d}", f"C{i:02d}", "https://x/careers")
    return st


def _run(st: Store, now: str, batch=10) -> list[str]:
    """One run's worth of scheduling: plan, then stamp what was attempted."""
    p = S.plan(st, batch, 14, now=now)
    S.mark_attempted(st, p.due, now=now)
    return [c.key for c in p.due]


def test_scheduler_takes_ten_at_a_time():
    st = _store(25)
    assert _run(st, T0) == [f"c{i:02d}" for i in range(1, 11)]
    assert _run(st, shift(T0, days=1)) == [f"c{i:02d}" for i in range(11, 21)]
    assert _run(st, shift(T0, days=1, seconds=7200)) == [f"c{i:02d}" for i in range(21, 26)]


def test_scheduler_nothing_rescraped_inside_the_cycle():
    st = _store(25)
    for d in (0, 1, 1):
        _run(st, shift(T0, days=d))
    assert _run(st, shift(T0, days=2)) == []
    assert _run(st, shift(T0, days=13, seconds=23 * 3600)) == []


def test_scheduler_loops_back_to_company_one():
    """No special case: company 1 is simply the oldest row again."""
    st = _store(25)
    for d in (0, 1, 1):
        _run(st, shift(T0, days=d))
    assert _run(st, shift(T0, days=14, seconds=60)) == [f"c{i:02d}" for i in range(1, 11)]


def test_scheduler_13_days_not_due_15_days_due():
    st = _store(1)
    _run(st, T0)
    assert S.plan(st, 10, 14, now=shift(T0, days=13)).due == []
    assert [c.key for c in S.plan(st, 10, 14, now=shift(T0, days=15)).due] == ["c01"]


def test_scheduler_never_scraped_sorts_ahead_of_stale():
    st = _store(3)
    st.stamp_scraped([1], at=shift(T0, days=-20))    # stale
    st.stamp_scraped([2], at=shift(T0, days=-30))    # staler
    # c03 never scraped: first, then longest-neglected.
    assert [c.key for c in S.plan(st, 10, 14, now=T0).due] == ["c03", "c02", "c01"]


def test_scheduler_failed_fetch_still_stamps():
    """Stamped on ATTEMPT, so a 403 company cannot eat every batch."""
    st = _store(1)
    p = S.plan(st, 10, 14, now=T0)
    st.record_failure(p.due[0].id, "blocked", "403")
    S.mark_attempted(st, p.due, now=T0)
    assert st.company_by_key("c01").last_scraped_at == T0
    assert S.plan(st, 10, 14, now=shift(T0, days=1)).due == []


def test_scheduler_all_fresh_reports_next_due_date():
    st = _store(229)
    for d in range(23):                               # 23 runs sweep 229 companies
        _run(st, shift(T0, seconds=d * 60))
    p = S.plan(st, 10, 14, now=shift(T0, days=1))
    assert p.empty
    assert p.next_due_at == shift(T0, days=14)        # the oldest stamp + 14 days


def test_scheduler_skips_disabled_and_quarantined():
    st = _store(3)
    st.conn.execute("UPDATE companies SET enabled = 0 WHERE key = 'c01'")
    st.quarantine(2, probation_due_run=5)
    assert [c.key for c in S.plan(st, 10, 14, now=T0).due] == ["c03"]


def test_scheduler_status_report_counts_and_projection():
    st = _store(30)
    for d in (0, 1):
        run = st.start_run(at=shift(T0, days=d))
        _run(st, shift(T0, days=d))
        st.finish_run(run, "ok", {})
    now = shift(T0, days=2)
    rep = S.status(st, 10, 14, now=now)
    assert rep.enabled == 30 and rep.due_now == 10 and rep.never_scraped == 10
    assert rep.runs_needed == 1
    assert rep.runs_per_day == 1.0                    # 2 runs over 2 days
    assert rep.projected_done == shift(now, days=1)
    text = S.describe(rep)
    assert "due now        10 of 30" in text and "below the sweep rate" not in text


def test_scheduler_status_flags_a_rate_below_the_sweep():
    st = _store(229)
    run = st.start_run(at=T0)
    _run(st, T0)
    st.finish_run(run, "ok", {})
    rep = S.status(st, 10, 14, now=shift(T0, days=3))   # 1 run in 3 days
    assert rep.required_runs_per_day > 1.6 - 0.01
    assert "below the sweep rate" in S.describe(rep)
