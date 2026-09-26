"""Stored settings, and the one they exist for: companies per run (M11-T1).

The batch size used to be a line in config.yaml. Docker mounts `config/`
read-only, so a value the user changes from the web app has to live in the
database instead. These tests pin the resolution order every caller must agree
on - the `--batch-size` flag, else the stored setting, else `run.batch_size` -
for both `run` (what it plans) and `status` (the cadence it reports).

The pipeline is replaced by a spy that plans with the real scheduler and
returns "nothing due", so no test here touches the network or a model.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from jobscraper import cli, scheduler  # noqa: E402
from jobscraper.pipeline import RunReport  # noqa: E402
from jobscraper.store import Store  # noqa: E402

COMPANIES = 30
CONFIG_BATCH = 10


def _world() -> tuple[Path, str]:
    """A config whose watchlist holds 30 enabled companies, all never scraped."""
    tmp = Path(tempfile.mkdtemp())
    lines = ["version: 1", "companies:"]
    for i in range(COMPANIES):
        lines += [f"  - name: Company {i:02d}",
                  f"    careers_url: https://co{i:02d}.example/careers",
                  "    provider: greenhouse", f"    slug: co{i:02d}"]
    (tmp / "watchlist.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    raw = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    raw["paths"].update(watchlist=str(tmp / "watchlist.yaml"), resume_dir=str(tmp),
                        profile=str(tmp / "profile.derived.yaml"),
                        profile_overrides=str(tmp / "overrides.yaml"),
                        db=str(tmp / "t.db"), shortlist=str(tmp / "shortlist.json"))
    raw["run"]["batch_size"] = CONFIG_BATCH
    raw["budget"].update(enable_llm=False, backend="off")
    cfg = tmp / "config.yaml"
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return tmp, str(cfg)


@contextlib.contextmanager
def _spy_pipeline():
    """Swap `pipeline.run` for a spy that records the batch it was handed and
    how many companies the real scheduler plans for it."""
    seen: dict = {}
    real = cli.pipeline.run

    def spy(cfg, store, *, dry_run=False, batch_size=None, **_kw):
        store.sync_watchlist(cli.watchlist.load(cfg.watchlist_path))
        seen["batch_size"] = batch_size
        seen["planned"] = len(scheduler.plan(store, batch_size or cfg.batch_size,
                                             cfg.cycle_days).due)
        return RunReport(status="nothing_due", message="spy: nothing run")

    cli.pipeline.run = spy
    try:
        yield seen
    finally:
        cli.pipeline.run = real


def _cli(cfg: str, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main(["--config", cfg, *argv])
    return code, out.getvalue()


def _store_setting(tmp: Path, key: str, value) -> None:
    st = Store(tmp / "t.db")
    try:
        st.set_setting(key, value)
    finally:
        st.close()


# ---------------------------------------------------------------- the store

def test_settings_missing_key_answers_the_default():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "s.db")
        try:
            assert st.get_setting("batch_size") is None
            assert st.get_setting("batch_size", "7") == "7"
        finally:
            st.close()


def test_settings_round_trip_overwrite_and_survive_reopening():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "s.db"
        st = Store(db)
        st.set_setting("batch_size", 25)
        assert st.get_setting("batch_size") == "25"     # values are stored as text
        st.set_setting("batch_size", "40")
        assert st.get_setting("batch_size") == "40"     # an upsert, not a second row
        st.set_setting("other", "x")
        st.close()
        st = Store(db)
        try:
            assert st.get_setting("batch_size") == "40"
            assert st.get_setting("other") == "x"
        finally:
            st.close()


def test_settings_table_is_added_to_an_existing_database():
    """A database created before M11 gains the table on open - no migration."""
    import sqlite3
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "s.db"
        Store(db).close()
        conn = sqlite3.connect(str(db))
        conn.execute("DROP TABLE settings")
        conn.commit()
        conn.close()
        st = Store(db)
        try:
            st.set_setting("batch_size", 3)
            assert st.get_setting("batch_size") == "3"
        finally:
            st.close()


# ---------------------------------------------------------------- run / status

def test_settings_stored_batch_size_makes_run_plan_that_many():
    tmp, cfg = _world()
    _store_setting(tmp, "batch_size", 25)
    with _spy_pipeline() as seen:
        code, out = _cli(cfg, "run")
    assert code == 0, out
    assert seen["batch_size"] == 25
    assert seen["planned"] == 25


def test_settings_batch_size_flag_overrides_the_stored_setting():
    tmp, cfg = _world()
    _store_setting(tmp, "batch_size", 25)
    with _spy_pipeline() as seen:
        code, out = _cli(cfg, "run", "--batch-size", "4")
    assert code == 0, out
    assert seen["batch_size"] == 4
    assert seen["planned"] == 4


def test_settings_without_a_stored_value_run_uses_config():
    tmp, cfg = _world()
    with _spy_pipeline() as seen:
        code, out = _cli(cfg, "run")
    assert code == 0, out
    assert seen["batch_size"] == CONFIG_BATCH
    assert seen["planned"] == CONFIG_BATCH


def test_settings_status_reports_cadence_at_the_effective_batch_size():
    tmp, cfg = _world()
    seen: list[int] = []
    real = cli.scheduler.status

    def spy(store, batch_size, cycle_days, **kw):
        seen.append(batch_size)
        return real(store, batch_size, cycle_days, **kw)

    cli.scheduler.status = spy
    try:
        code, out = _cli(cfg, "status")
        assert code == 0 and seen[-1] == CONFIG_BATCH, out
        # 30 companies / 10 per run / 7 days
        assert "a full sweep needs 0.4/day" in out, out
        _store_setting(tmp, "batch_size", 25)
        code, out = _cli(cfg, "status")
        assert code == 0 and seen[-1] == 25, out
        assert "a full sweep needs 0.2/day" in out, out
    finally:
        cli.scheduler.status = real
