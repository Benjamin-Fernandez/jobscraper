"""The due test keeps a weekly schedule (C-7 grace): a company attempted at
03:05 Monday is due next Monday 03:05 and a little earlier, never skipped
because last week's run took a few minutes longer. Ported from the cloud's
test_schedule_rule.py; the runs_per_cycle half is not ported (personal keeps
batch-size/cycle settings, no runs_per_cycle).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper import scheduler  # noqa: E402
from jobscraper.store import Store, shift  # noqa: E402

# ---------------- the due test keeps a weekly schedule (grace) ----------------

MON = "2026-09-28T03:05:00"            # a Monday, 03:05 UTC (the run's own time)


def _store(n=3):
    st = Store(Path(tempfile.mkdtemp()) / "t.db")
    for i in range(n):
        st.insert_company(f"c{i}", f"C{i}", "https://x/careers")
    return st


def test_a_company_attempted_monday_0305_is_due_next_monday_0305_and_a_bit_earlier():
    st = _store(1)
    scheduler.mark_attempted(st, st.due_companies(MON, 5), now=MON)
    for minutes in (0, -4, -60, -11 * 60):         # next Monday, a little early
        now = shift(MON, days=7, seconds=minutes * 60)
        assert [c.key for c in scheduler.plan(st, 5, 7, now=now).due] == ["c0"], minutes


def test_the_grace_has_an_edge_twelve_hours_inside_the_cycle():
    st = _store(1)
    scheduler.mark_attempted(st, st.due_companies(MON, 5), now=MON)
    edge = shift(MON, days=7, seconds=-12 * 3600)
    assert [c.key for c in scheduler.plan(st, 5, 7, now=edge).due] == ["c0"]
    just_before = shift(edge, seconds=-1)
    assert scheduler.plan(st, 5, 7, now=just_before).due == []


def test_cutoff_is_cycle_minus_grace_and_grace_shrinks_for_a_one_day_cycle():
    assert scheduler.cutoff(MON, 7) == shift(MON, days=-7, seconds=12 * 3600)
    # A daily cycle must not collapse to twelve hours.
    assert shift(MON, days=-1, seconds=3600) < scheduler.cutoff(MON, 1) < MON


def test_next_due_agrees_with_the_graced_cutoff():
    st = _store(1)
    scheduler.mark_attempted(st, st.due_companies(MON, 5), now=MON)
    p = scheduler.plan(st, 5, 7, now=shift(MON, days=1))
    assert p.due == [] and p.next_due_at == shift(MON, days=7, seconds=-12 * 3600)
    # ...and at that moment the plan really does hand the company out.
    assert [c.key for c in scheduler.plan(st, 5, 7, now=p.next_due_at).due] == ["c0"]
