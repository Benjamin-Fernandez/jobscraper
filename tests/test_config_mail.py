"""WP-T5 oracles: the `mail_status:` config block (mail_status_design.md 10.4; D-154 g, D-156).
Verify: `python tests/run_tests.py -k config_mail`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import ROOT, WAITING, assert_live, needs, note_waiting  # noqa: E402

_W0 = len(WAITING)
CFG = "jobscraper.config:MailStatusConfig"


def _ms(raw):
    from jobscraper.config import MailStatusConfig
    return MailStatusConfig.from_raw(raw)


@needs(CFG)
def test_config_mail_defaults_follow_the_design():
    m = _ms(None)
    assert (m.enabled, m.interval_min, m.startup_delay_s, m.catchup_delay_s) == (True, 10, 60, 60)
    assert (m.first_sync_max_days, m.max_headers_per_sync, m.max_bodies_per_sync) == (180, 2000, 200)
    assert (m.max_body_bytes, m.sync_timeout_s, m.model, m.model_max_calls) == (5_000_000, 600, True, 20)
    assert (m.model_max_chars, m.model_timeout_s, m.retry_model_days, m.require_auth) == (6000, 60, 3, True)
    assert dict(m.ranks) == {"to_apply": 0, "applied": 1, "assessment": 2, "interviewing": 3, "offer": 4}
    assert tuple(m.terminal) == ("rejected", "withdrawn")
    assert dict(m.category_status)["interview"] == "interviewing"
    assert dict(m.category_status)["kept_on_file"] == "rejected"
    assert tuple(m.suggest_only) == ("posting_closed", "kept_on_file") and tuple(m.junk_auto) == ("acknowledged",)
    assert _ms({}) == m and _ms("not a mapping") == m and _ms([1, 2]) == m


@needs(CFG)
def test_config_mail_clamps_ignores_unknown_keys_and_keeps_defaults_for_junk():
    assert _ms({"interval_min": 1}).interval_min == 5
    assert _ms({"interval_min": 500}).interval_min == 120
    assert _ms({"interval_min": "30"}).interval_min == 30
    assert _ms({"interval_min": 7.9}).interval_min == 7
    assert _ms({"startup_delay_s": -5}).startup_delay_s == 0
    assert _ms({"max_bodies_per_sync": 0}).max_bodies_per_sync == 1
    assert _ms({"model_max_calls": -1}).model_max_calls == 0
    assert _ms({"interval_min": "soon"}).interval_min == 10
    assert _ms({"interval_min": None}).interval_min == 10
    assert _ms({"no_such_key": 3, "interval_min": 15}).interval_min == 15
    m = _ms({"ranks": {"applied": "1", "offer": "x"}, "terminal": ["rejected", None]})
    assert dict(m.ranks) == {"applied": 1} and tuple(m.terminal) == ("rejected",)
    assert tuple(_ms({"terminal": "rejected"}).terminal) == ("rejected", "withdrawn")


@needs(CFG)
def test_config_mail_an_infinite_number_keeps_the_default():
    """DEFECT pin (LOW, lane F): config.py MailStatusConfig.from_raw does `int(float(v))` and
    catches only TypeError/ValueError. YAML `.inf` (or the text "inf", "1e400") raises
    OverflowError, so a typo in config.yaml crashes every command that reads `cfg.mail_status`
    instead of keeping the default as MS 10.4 says for unreadable values."""
    for v in (float("inf"), "inf", "1e400", float("-inf")):
        try:
            m = _ms({"interval_min": v, "max_body_bytes": v})
        except OverflowError as exc:
            raise AssertionError(f"{v!r}: {type(exc).__name__}") from None
        assert m.interval_min in (5, 10, 120), (v, m.interval_min)


@needs(CFG)
def test_config_mail_booleans_read_text():
    for raw, want in (("false", False), ("No", False), (" 0 ", False), ("off", False), (0, False),
                      ("true", True), ("YES", True), (1, True), (True, True), (False, False)):
        m = _ms({"enabled": raw, "model": raw, "require_auth": raw})
        assert (m.enabled, m.model, m.require_auth) == (want, want, want), raw
    m = _ms({"enabled": "maybe", "model": [], "require_auth": "nope"})
    assert (m.enabled, m.model, m.require_auth) == (True, True, True), "unreadable keeps the default"


@needs("jobscraper.config:Config")
def test_config_mail_statuses_and_rules_path():
    from jobscraper.config import Config
    cfg = Config({})
    assert "assessment" in cfg.application_statuses
    st = cfg.application_statuses
    assert st.index("applied") < st.index("assessment") < st.index("interviewing")
    assert cfg.mail_rules_path == (ROOT / "config" / "mail_rules.yaml").resolve() or \
        cfg.mail_rules_path.name == "mail_rules.yaml"
    assert Config({"paths": {"mail_rules": "elsewhere/r.yaml"}}).mail_rules_path.name == "r.yaml"
    assert Config({"mail_status": {"interval_min": 30}}).mail_status.interval_min == 30


def test_config_mail_oracles_are_live():
    assert_live(CFG, _W0, "test_config_mail")


note_waiting("test_config_mail", _W0)
