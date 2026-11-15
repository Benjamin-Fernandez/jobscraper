"""Q-126 lane E1 pins: the store half (ollama_autostart_design.md §4.4, §5 Store, §9 T13c/d,
T14, T3 state). RED UNTIL eng/Q-126-E1 MERGES: each test calls a store method that does not
exist yet, so it fails with AttributeError (a per-test count, not an import error).

What is pinned, and why it matters in mode `auto`:
  * `queue_resume_if(reasons, now, *, keep_window=())` lifts a pause in one compare-and-clear
    transaction and writes `resumed_at` only when the cleared reason is NOT in `keep_window`,
    so lifting a model pause (by Resume or by an Auto-apply click) never wipes the bot-check /
    repeated-error streak window (R1, review C2.1).
  * `queue_pause_if_waiting(reason, now, *, replace=())` can overwrite a stored model pause
    at start-up (D-200: across a restart a click never lifts `restarted`).
  * `queue_model_state` / `queue_model_view` are two settings rows; no schema change.

Temp databases only: no web app, no job runs, no network, never data/.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import make_job  # noqa: E402

from jobscraper.apply.contracts import MODEL_PAUSE_VALUES  # noqa: E402
from jobscraper.store import SCHEMA_VERSION, Store  # noqa: E402

T0 = "2026-11-15T08:00:00Z"
OLD = "2026-11-14T09:00:00Z"       # an earlier Resume: the streak window start
NOW = "2026-11-15T09:00:00Z"

MODEL = sorted(MODEL_PAUSE_VALUES)
NON_MODEL = ["owner", "cancelled", "bot_checks", "repeated_errors", "restarted",
             "app_closed", "daily_limit"]


@contextmanager
def _world(roles: int = 0):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "jobscraper.db"
        st = Store(path, check_same_thread=False)
        cid = st.insert_company("fakeco", "Fake Co", "https://fakeco.example")
        for n in range(1, roles + 1):
            j = make_job(st, cid, n)
            st.set_application_status(j, "to_apply")
            st.queue_add(j, cid, "dry_run", "inbox", T0)
        st.commit()
        try:
            yield st, path
        finally:
            st.close()


def _resumed_at(st):
    return st.get_setting(Store.QUEUE_RESUMED_AT)


def test_no_schema_change():
    assert SCHEMA_VERSION == 6


def test_lifting_a_model_pause_never_writes_resumed_at_so_the_streak_survives():
    for reason in MODEL:
        with _world() as (st, _p):
            st.queue_resume(OLD)                                   # an earlier acknowledged ending
            assert st.queue_pause(reason, "qwen3:14b", T0) is True
            assert st.queue_resume_if(None, NOW, keep_window=MODEL_PAUSE_VALUES) == reason
            assert st.queue_pause_state() is None
            assert st.get_setting(Store.QUEUE_PAUSED_DETAIL) is None
            assert st.get_setting(Store.QUEUE_PAUSED_AT) is None
            assert _resumed_at(st) == OLD, reason                  # unchanged
        with _world() as (st, _p):                                 # never stamped when it was unset
            st.queue_pause(reason, None, T0)
            assert st.queue_resume_if(set(MODEL_PAUSE_VALUES), NOW,
                                      keep_window=MODEL_PAUSE_VALUES) == reason
            assert _resumed_at(st) is None, reason


def test_lifting_any_other_pause_stamps_resumed_at_as_before():
    for reason in NON_MODEL:
        with _world() as (st, _p):
            st.queue_pause(reason, None, T0)
            assert st.queue_resume_if(None, NOW, keep_window=MODEL_PAUSE_VALUES) == reason
            assert st.queue_pause_state() is None
            assert _resumed_at(st) == NOW, reason


def test_without_keep_window_a_model_pause_is_stamped_like_queue_resume():
    with _world() as (st, _p):
        st.queue_pause("model_missing", "qwen3:14b", T0)
        assert st.queue_resume_if(None, NOW) == "model_missing"
        assert _resumed_at(st) == NOW


def test_a_pause_outside_the_reasons_set_is_never_lifted():
    """An Auto-apply click lifts only model pauses: everything else waits for Resume."""
    for reason in NON_MODEL:
        with _world() as (st, _p):
            st.queue_resume(OLD)
            st.queue_pause(reason, "d", T0)
            assert st.queue_resume_if(set(MODEL_PAUSE_VALUES), NOW,
                                      keep_window=MODEL_PAUSE_VALUES) is None
            state = st.queue_pause_state()
            assert state["reason"] == reason and state["detail"] == "d" and state["since"] == T0
            assert _resumed_at(st) == OLD


def test_nothing_stored_means_nothing_cleared_and_nothing_stamped():
    with _world() as (st, _p):
        assert st.queue_resume_if(None, NOW, keep_window=MODEL_PAUSE_VALUES) is None
        assert st.queue_resume_if(set(MODEL_PAUSE_VALUES), NOW) is None
        assert _resumed_at(st) is None and st.queue_pause_state() is None


def test_compare_and_clear_if_the_reason_changed_under_the_click():
    """T13d: the click read `model_missing`, then the owner paused: the clear must not
    take the owner's pause away. (The compare happens in the same transaction as the clear.)"""
    with _world() as (a, path):
        b = Store(path, check_same_thread=False)
        try:
            a.queue_pause("model_missing", "qwen3:14b", T0)
            b.queue_resume(OLD)
            assert b.queue_pause("owner", None, T0) is True        # another connection won
            assert a.queue_resume_if(set(MODEL_PAUSE_VALUES), NOW,
                                     keep_window=MODEL_PAUSE_VALUES) is None
            assert a.queue_pause_state()["reason"] == "owner"
        finally:
            b.close()


def test_the_clear_is_visible_to_another_connection_at_once():
    with _world() as (a, path):
        a.queue_pause("model_start_failed", "x", T0)
        a.queue_resume_if(None, NOW, keep_window=MODEL_PAUSE_VALUES)
        b = Store(path)
        try:
            assert b.queue_pause_state() is None
        finally:
            b.close()


def test_queue_resume_is_unchanged():
    with _world() as (st, _p):
        st.queue_pause("model_missing", None, T0)
        st.queue_resume(NOW)
        assert st.queue_pause_state() is None and _resumed_at(st) == NOW


# ---- start-up: a stored model pause with waiting roles becomes `restarted` ----

def test_startup_replace_overwrites_a_model_pause_only_when_roles_wait():
    for reason in MODEL:
        with _world(roles=1) as (st, _p):
            st.queue_pause(reason, "qwen3:14b", T0)
            assert st.queue_pause_if_waiting("restarted", NOW, replace=MODEL_PAUSE_VALUES) is True
            state = st.queue_pause_state()
            assert state["reason"] == "restarted" and state["since"] == NOW, reason
            assert state["detail"] in (None, ""), reason
        with _world(roles=0) as (st, _p):                          # no roles: the pause stays
            st.queue_pause(reason, "qwen3:14b", T0)
            assert st.queue_pause_if_waiting("restarted", NOW, replace=MODEL_PAUSE_VALUES) is False
            assert st.queue_pause_state()["reason"] == reason


def test_startup_replace_leaves_other_pauses_and_the_old_call_alone():
    with _world(roles=1) as (st, _p):
        st.queue_pause("owner", None, T0)
        assert st.queue_pause_if_waiting("restarted", NOW, replace=MODEL_PAUSE_VALUES) is False
        assert st.queue_pause_state()["reason"] == "owner"
    with _world(roles=1) as (st, _p):                              # no `replace`: as today
        st.queue_pause("model_unavailable", None, T0)
        assert st.queue_pause_if_waiting("restarted", NOW) is False
        assert st.queue_pause_state()["reason"] == "model_unavailable"
    with _world(roles=1) as (st, _p):                              # an unpaused queue: as today
        assert st.queue_pause_if_waiting("restarted", NOW, replace=MODEL_PAUSE_VALUES) is True
        assert st.queue_pause_state()["reason"] == "restarted"


def test_after_the_restart_a_click_set_never_lifts_restarted():
    with _world(roles=1) as (st, _p):
        st.queue_pause("model_missing", "qwen3:14b", T0)
        st.queue_pause_if_waiting("restarted", NOW, replace=MODEL_PAUSE_VALUES)
        assert st.queue_resume_if(set(MODEL_PAUSE_VALUES), NOW,
                                  keep_window=MODEL_PAUSE_VALUES) is None
        assert st.queue_pause_state()["reason"] == "restarted"


# ---- the model's working state, shown while the worker starts it ----

def test_model_state_and_view_round_trip_and_clear():
    with _world() as (st, path):
        assert st.queue_model_view() is None
        st.queue_model_state("starting", T0)
        assert st.queue_model_view() == {"state": "starting", "since": T0}
        assert st.get_setting("apply_queue.model") == "starting"
        assert st.get_setting("apply_queue.model_at") == T0
        other = Store(path)                                        # committed, not pending
        try:
            assert other.queue_model_view() == {"state": "starting", "since": T0}
        finally:
            other.close()
        st.queue_model_state("loading", NOW)
        assert st.queue_model_view() == {"state": "loading", "since": NOW}
        st.queue_model_state(None, NOW)
        assert st.queue_model_view() is None
        assert st.get_setting("apply_queue.model") is None
        assert st.get_setting("apply_queue.model_at") is None


def test_model_state_never_touches_the_pause_rows():
    with _world() as (st, _p):
        st.queue_pause("owner", None, T0)
        st.queue_model_state("starting", NOW)
        st.queue_model_state(None, NOW)
        assert st.queue_pause_state()["reason"] == "owner" and _resumed_at(st) is None
