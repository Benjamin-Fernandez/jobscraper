"""Q-126 WP-0 contract pins (D-214, D-217; docs/architecture/ollama_autostart_design.md §4.2, §5).

The six new model pauses exist with owner copy that says what the app tried and what
to do; the sets that `store.py` and the web read are consistent; there is no timed
resume anywhere (D-217 R1: a model pause lifts only on the owner's click); and the
test runner switches autostart off before any test imports (review C4).

Green now (the contract is already in the tree). Pure data: no network, no process.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from jobscraper.apply import contracts as C
from jobscraper.apply.contracts import QueuePause as QP

SRC = Path(__file__).resolve().parent.parent / "src"

NEW_SIX = (QP.MODEL_NOT_INSTALLED, QP.MODEL_START_FAILED, QP.MODEL_MISSING,
           QP.MODEL_PORT_TAKEN, QP.MODEL_LOAD_FAILED, QP.MODEL_NOT_ANSWERING)
SEVEN = set(NEW_SIX) | {QP.MODEL_UNAVAILABLE}


def _render(pause: QP, detail: str = "qwen3:14b") -> tuple[str, str]:
    rt = C.QUEUE_PAUSE_TEXTS[pause]
    return rt.text.format(detail=detail), rt.hint.format(detail=detail)


def test_the_six_new_pauses_exist_with_plain_string_values():
    assert {p.value for p in NEW_SIX} == {
        "model_not_installed", "model_start_failed", "model_missing",
        "model_port_taken", "model_load_failed", "model_not_answering"}
    for p in NEW_SIX:
        assert isinstance(p.value, str) and p in C.QUEUE_PAUSE_TEXTS


def test_every_model_pause_text_says_nothing_was_sent_and_what_to_do_next():
    for p in SEVEN:
        text, hint = _render(p)
        assert "{" not in text + hint and "}" not in text + hint, (p, text, hint)
        assert "queue is paused" in text.lower(), p
        assert "nothing was sent" in text.lower(), p
        assert hint.strip().endswith(".") and "resume" in hint.lower(), (p, hint)


def test_the_copy_says_what_the_app_tried():
    t = {p: _render(p)[0].lower() for p in SEVEN}
    assert "couldn't find ollama" in t[QP.MODEL_NOT_INSTALLED]
    assert "tried to start ollama" in t[QP.MODEL_START_FAILED]
    assert "isn't downloaded" in t[QP.MODEL_MISSING]
    assert "another program is using port" in t[QP.MODEL_PORT_TAKEN]
    assert "couldn't load the model" in t[QP.MODEL_LOAD_FAILED]
    assert "not answering in time" in t[QP.MODEL_NOT_ANSWERING]
    assert "isn't running" in t[QP.MODEL_UNAVAILABLE]


def test_the_copy_says_what_to_do():
    h = {p: _render(p)[1] for p in SEVEN}
    assert "ollama.com" in h[QP.MODEL_NOT_INSTALLED] and "ollama pull qwen3:14b" in h[QP.MODEL_NOT_INSTALLED]
    assert "Start menu" in h[QP.MODEL_START_FAILED]
    assert "ollama pull qwen3:14b" in h[QP.MODEL_MISSING]
    assert "budget.ollama_url" in h[QP.MODEL_PORT_TAKEN]
    assert "graphics card" in h[QP.MODEL_LOAD_FAILED] and "graphics card" in h[QP.MODEL_NOT_ANSWERING]
    # The old pause now says only that nothing listens and the app did not or may not
    # start it: it points at the Settings switch.
    assert "Settings" in h[QP.MODEL_UNAVAILABLE] and "Local AI" in h[QP.MODEL_UNAVAILABLE]


def test_no_model_copy_promises_a_resume_without_a_click():
    """D-217 R1 / T13f: nothing on the model pauses says the queue goes on by itself."""
    for p in SEVEN:
        text, hint = _render(p)
        blob = (text + " " + hint).lower()
        for banned in ("by itself", "automatically", "continues", "will resume", "retry in"):
            assert banned not in blob, (p, banned)


def test_the_detail_is_a_tag_a_port_or_fixed_words_never_a_path_or_url():
    for p in SEVEN:
        text, hint = _render(p, detail="11434")
        assert "http" not in text + hint and "\\" not in text + hint, p
    # A start_failed detail is the fixed words from the design, and fits its sentence.
    text, _ = _render(QP.MODEL_START_FAILED, detail="no answer after 60 seconds")
    assert "(no answer after 60 seconds)" in text


def test_returns_item_holds_the_six_new_pauses():
    assert set(NEW_SIX) <= set(C.RETURNS_ITEM)
    assert QP.MODEL_UNAVAILABLE in C.RETURNS_ITEM


def test_model_pause_sets_are_consistent():
    assert set(C.MODEL_PAUSES) == SEVEN
    assert C.MODEL_PAUSE_VALUES == frozenset(p.value for p in C.MODEL_PAUSES)
    assert all(type(v) is str for v in C.MODEL_PAUSE_VALUES)      # plain strings, not enum members
    assert set(C.MODEL_CLICK_RESUME) <= set(C.MODEL_PAUSES)
    # Pauses an Auto-apply click must never lift (they wait for Resume only).
    for p in (QP.OWNER, QP.CANCELLED, QP.BOT_CHECKS, QP.REPEATED_ERRORS, QP.RESTARTED,
              QP.APP_CLOSED, QP.DAILY_LIMIT):
        assert p not in C.MODEL_CLICK_RESUME and p not in C.MODEL_PAUSES, p


def test_model_pause_by_code_maps_every_non_ready_code_but_cancelled():
    expected = {"off", "not_running", "not_installed", "start_failed", "model_missing",
                "port_taken", "not_answering", "load_failed"}
    assert set(C.MODEL_PAUSE_BY_CODE) == expected
    assert "ready" not in C.MODEL_PAUSE_BY_CODE and "cancelled" not in C.MODEL_PAUSE_BY_CODE
    assert set(C.MODEL_PAUSE_BY_CODE.values()) <= set(C.MODEL_PAUSES)
    assert len(set(C.MODEL_PAUSE_BY_CODE.values())) == 7           # each pause is reachable


def test_there_is_no_timed_resume_anywhere_in_src():
    """D-217 R1: no timer, tick or probe lifts a pause. `MODEL_AUTO_RESUME` was removed
    from the design before it reached personal and must not come back."""
    assert not hasattr(C, "MODEL_AUTO_RESUME")
    hits = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
            if "MODEL_AUTO_RESUME" in p.read_text(encoding="utf-8", errors="replace")]
    assert hits == [], hits


def test_the_unavailable_applications_row_hint_points_at_runs():
    """T21 / C6: the Applications row hint says to try again and where the reason lives."""
    rt = C.REASON_TEXTS[C.ReasonCode.MODEL_UNAVAILABLE]
    assert "Try again" in rt.hint and "Runs" in rt.hint and "doctor" not in rt.hint


def test_the_runner_assigned_autostart_off_before_any_test_imported():
    """T15c / review C4: `tests/run_tests.py` ASSIGNS the variable, so a `1` left in the
    shell cannot switch autostart on for a suite. (When this file is run any other way
    the variable is simply absent: only a `1` is a failure.)"""
    assert os.environ.get("JOBSCRAPER_OLLAMA_AUTOSTART") != "1"
    runner = (Path(__file__).resolve().parent / "run_tests.py").read_text(encoding="utf-8")
    assert re.search(r'os\.environ\["JOBSCRAPER_OLLAMA_AUTOSTART"\]\s*=\s*"0"', runner)
    assert not re.search(r'setdefault\(\s*"JOBSCRAPER_OLLAMA_AUTOSTART"', runner)
