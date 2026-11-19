"""The rehearsal tool (`tests/manual/always_rehearsal.py`) and the release lock (D-223): the tool opens `apply.always_available` ONLY in its own
in-memory apply config, ONLY after every hard-safety check has passed, never writes config/config.yaml, and can never run (or score) the
strict filler by mistake. Fakes only: the tool's functions are called directly (no server, no browser, no model, no process).
Verify: python tests/run_tests.py -k always_rehearsal_lock
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]

from jobscraper.config import ApplyConfig  # noqa: E402

TOOL = HERE / "manual" / "always_rehearsal.py"
_spec = importlib.util.spec_from_file_location("always_rehearsal_under_test", TOOL)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def _args(**kw):
    base = dict(mode="dry_run", target_url="http://127.0.0.1/")
    base.update(kw)
    return Namespace(**base)


def _world(tmp: Path):
    return tmp / "jobs.db", tmp / "edge-profile", R.SAMPLE_PROFILE


def _refused(fn) -> bool:
    """True when `fn` ends in the tool's refusal: SystemExit with code 3 (and prints REFUSED to stderr, which we let through)."""
    try:
        fn()
    except SystemExit as exc:
        return exc.code == 3
    return False


def test_the_lock_is_opened_in_memory_only_when_every_check_holds():
    """Check 7: `open_lock` returns a COPY of the apply config with `always_available` True when the six earlier checks hold (dry run,
    127.0.0.1 target, temp database, temp Edge profile, a profile under tests/fixtures/, JOBSCRAPER_DB unset); the original object stays
    locked. Each failing check alone ends in exit 3: a live mode, a foreign host, a database or Edge profile outside the temp
    directory, a profile outside tests/fixtures/, JOBSCRAPER_DB set."""
    saved = os.environ.pop("JOBSCRAPER_DB", None)
    try:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            db, edge, prof = _world(tmp)
            locked = ApplyConfig.from_raw({"mode": "dry_run", "fill": "llm", "fill_policy": "always"})
            assert locked.always_available is False
            opened = R.open_lock(_args(), tmp, db, edge, prof, locked)
            assert opened.always_available is True and locked.always_available is False
            auto = ApplyConfig.from_raw({"mode": "auto", "fill": "llm", "fill_policy": "always"})
            cases = {
                "live mode (config)": lambda: R.open_lock(_args(), tmp, db, edge, prof, auto),
                "live mode (flag)": lambda: R.open_lock(_args(mode="auto"), tmp, db, edge, prof, locked),
                "foreign host": lambda: R.open_lock(_args(target_url="https://jobs.example.com/"), tmp, db, edge, prof, locked),
                "database outside the temp dir": lambda: R.open_lock(_args(), tmp, HERE / "x.db", edge, prof, locked),
                "Edge profile outside the temp dir": lambda: R.open_lock(_args(), tmp, db, HERE / "edge", prof, locked),
                "profile outside tests/fixtures": lambda: R.open_lock(_args(), tmp, db, edge, HERE.parent / "README.md", locked),
            }
            bad = [name for name, fn in cases.items() if not _refused(fn)]
            os.environ["JOBSCRAPER_DB"] = str(tmp / "other.db")
            if not _refused(lambda: R.open_lock(_args(), tmp, db, edge, prof, locked)):
                bad.append("JOBSCRAPER_DB set")
    finally:
        os.environ.pop("JOBSCRAPER_DB", None)
        if saved is not None:
            os.environ["JOBSCRAPER_DB"] = saved
    assert not bad, f"these did not exit 3: {bad}"


def test_a_config_that_arrives_with_the_lock_already_open_is_refused():
    """Check 7, the other half: `preflight` refuses an apply config whose `always_available` is True unless it came out of `open_lock`
    (`lock_open=True`), so no code path can start a run on a lock somebody else opened."""
    saved = os.environ.pop("JOBSCRAPER_DB", None)
    try:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            db, edge, prof = _world(tmp)
            opened = ApplyConfig.from_raw({"mode": "dry_run", "fill": "llm", "fill_policy": "always", "always_available": True})
            assert opened.always_available is True
            assert _refused(lambda: R.preflight(_args(), tmp, db, edge, prof, opened))
            R.preflight(_args(), tmp, db, edge, prof, opened, lock_open=True)           # the same config through the gate: fine
    finally:
        if saved is not None:
            os.environ["JOBSCRAPER_DB"] = saved


def test_the_header_names_the_policy_and_the_strict_log_line_is_the_flows_own_sentence():
    """The RUN header carries `policy=always (lock opened in memory)`; the post-run guard's pattern matches the flow's real "not released"
    sentence (`apply_flow.POLICY_NOT_RELEASED`), so a locked run is caught by its own log if the pre-run check were ever skipped."""
    from jobscraper import apply_flow
    assert R.LOCK_LINE == "policy=always (lock opened in memory)"
    assert R.STRICT_LOG.search(apply_flow.POLICY_NOT_RELEASED), apply_flow.POLICY_NOT_RELEASED
    assert f"{R.LOCK_LINE}" in TOOL.read_text(encoding="utf-8")


def test_the_tool_never_writes_the_config_file_and_the_file_stays_locked():
    """The tool only READS config/config.yaml (the model name and URL); no write, replace or remove names it; its exit compares a hash of the
    file. The file itself still says `always_available: false` (the release lock: `tests/test_always_lock.py` pins the same)."""
    src = TOOL.read_text(encoding="utf-8")
    assert not re.search(r"CONFIG\.(write_text|write_bytes|unlink|rename|replace)", src)
    assert not re.search(r"open\(\s*CONFIG[^)]*['\"][wa+]", src)
    assert "_config_hash() != cfg_hash" in src
    cfg = (HERE.parent / "config" / "config.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s*always_available:\s*false\b", cfg, re.M), "config/config.yaml must stay locked"
