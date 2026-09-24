"""The command line, end to end: every verb through `cli.main`, as typed.

The CLI had no tests, and it is where lanes meet: three lanes each added a verb
to cli.py, and a merge once silently dropped a `return 0` so `filter` reported
failure on success. These run each command against a throwaway config - temp
watchlist, database, profile and shortlist, the model switched off - so nothing
touches `data/`, the network, or the model.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from jobscraper import cli  # noqa: E402
from jobscraper.store import Store  # noqa: E402

PROFILE = {"profile_version": 1, "summary": "New graduate backend engineer.",
           "skills": ["python", "kubernetes"], "years_experience": 0,
           "target_titles": ["backend engineer", "software engineer"],
           "title_aliases": {}}


def _world(with_profile=True):
    """A config file whose every path points into a fresh temp dir."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "watchlist.yaml").write_text(
        "version: 1\ncompanies:\n"
        "  - name: Acme\n    careers_url: https://acme.example/careers\n"
        "    provider: greenhouse\n    slug: acme\n"
        "  - name: Beta Labs\n    careers_url: https://beta.example/jobs\n",
        encoding="utf-8")
    (tmp / "overrides.yaml").write_text("", encoding="utf-8")
    if with_profile:
        (tmp / "profile.derived.yaml").write_text(yaml.safe_dump(PROFILE),
                                                  encoding="utf-8")
    raw = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    raw["paths"].update(
        watchlist=str(tmp / "watchlist.yaml"), rules=str(ROOT / "config" / "rules.yaml"),
        profile=str(tmp / "profile.derived.yaml"),
        profile_overrides=str(tmp / "overrides.yaml"), resume_dir=str(tmp),
        db=str(tmp / "t.db"), shortlist=str(tmp / "shortlist.json"))
    raw["budget"].update(enable_llm=False, backend="off")
    cfg = tmp / "config.yaml"
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return tmp, str(cfg)


def run(cfg, *argv) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--config", cfg, *argv])
    return code, out.getvalue() + err.getvalue()


def test_cli_doctor_and_sync_and_status():
    tmp, cfg = _world()
    code, out = run(cfg, "doctor")
    assert code == 0 and "OK - 2 enabled of 2" in out, out
    code, out = run(cfg, "sync")
    assert code == 0 and "synced 2 enabled of 2" in out, out
    code, out = run(cfg, "status")
    assert code == 0 and "due now        2 of 2" in out, out


def test_cli_run_with_nothing_due_exits_zero_without_the_network():
    tmp, cfg = _world()
    run(cfg, "sync")
    st = Store(tmp / "t.db")
    st.stamp_scraped([c.id for c in st.companies()])
    st.close()
    code, out = run(cfg, "run")
    assert code == 0 and "nothing is due" in out, out


def test_cli_filter_test_exits_zero_on_success():
    """The merge regression: output was right but the exit code was not."""
    tmp, cfg = _world()
    code, out = run(cfg, "filter", "test", "--title", "Senior Backend Engineer",
                    "--location", "Singapore")
    assert code == 0 and "REJECT by title_deny: senior" in out, out


def test_cli_watchlist_list_add_disable_round_trip():
    tmp, cfg = _world()
    code, out = run(cfg, "watchlist", "list")
    assert code == 0 and "2 companies, 2 enabled" in out, out
    code, out = run(cfg, "watchlist", "add", "Gamma Co", "https://gamma.example/careers")
    assert code == 0, out
    code, out = run(cfg, "watchlist", "disable", "beta-labs")
    assert code == 0, out
    code, out = run(cfg, "watchlist", "list")
    assert "3 companies, 2 enabled" in out, out
    code, out = run(cfg, "watchlist", "disable", "no-such-key")
    assert code != 0


def test_cli_profile_show_reads_without_a_model():
    tmp, cfg = _world()
    code, out = run(cfg, "profile", "--show")
    assert code == 0 and "backend engineer" in out and "profile_version: 1" in out, out


def test_cli_review_needs_a_profile_then_exports_and_applies():
    tmp, cfg = _world(with_profile=False)
    code, out = run(cfg, "review", "--export")
    assert code == 1 and "no derived profile" in out, out

    tmp, cfg = _world()
    code, out = run(cfg, "review", "--export")
    assert code == 0 and "nothing to review" in out, out
    code, out = run(cfg, "review", "--apply")
    assert code == 1 and "no verdicts" in out, out
    (tmp / "review_verdicts.json").write_text(json.dumps({"decisions": []}),
                                              encoding="utf-8")
    code, out = run(cfg, "review", "--apply")
    assert code == 0 and "applied 0 decisions" in out, out


def test_cli_reresolve_clears_a_cached_provider():
    tmp, cfg = _world()
    code, out = run(cfg, "reresolve", "acme")
    assert code == 0 and "was greenhouse" in out, out
    st = Store(tmp / "t.db")
    assert st.company_by_key("acme").provider is None
    st.close()
    code, out = run(cfg, "reresolve", "nobody")
    assert code == 1 and "no company" in out, out


def test_cli_every_verb_is_wired():
    """Each registered verb has a handler; a verb that parses but has no `fn`
    would only fail when someone types it."""
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    for verb, sp in sub.choices.items():
        assert callable(sp.get_default("fn")), verb
