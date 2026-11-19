"""Q-121 unlock review S2 probe helpers. Run from the worktree root:
JOBSCRAPER_OLLAMA_AUTOSTART=0 python docs/reviews/Q-121-unlock-S2-probes/<probe>.py   (fake models only)."""
import os
import sys

os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"
ROOT = os.getcwd()
sys.path[:0] = [ROOT + "/tests", ROOT + "/src"]
from always_a1_support import *  # noqa: E402,F401,F403
import llm_fill_t2 as T  # noqa: E402
from jobscraper import applicant  # noqa: E402
from jobscraper.apply import always as AL, briefing as BR  # noqa: E402
from jobscraper.apply.contracts import ValueOrigin  # noqa: E402
from test_always_fill import TODAY, _profile, _pf, _run, _one  # noqa: E402

KEYS = ("privacy_consent", "data_retention_consent", "talent_pool_opt_in", "certify_true")
SHORT = {"privacy": "privacy_consent", "retention": "data_retention_consent", "talent": "talent_pool_opt_in",
         "cert": "certify_true"}
PROFILES = {
    "allfalse": dict(privacy_consent=False, data_retention_consent=False, talent_pool_opt_in=False, certify_true=False),
    "sample": dict(privacy_consent=True, data_retention_consent=True, talent_pool_opt_in=False, certify_true=True),
    "alltrue": dict(privacy_consent=True, data_retention_consent=True, talent_pool_opt_in=True, certify_true=True),
}


def prof(name):
    p = _profile()
    for k, v in PROFILES[name].items():
        p["consents"][k] = v
    return p


def ctx(p=None):
    p = p if p is not None else _profile()
    r = T.rctx(p)
    return AL.PageCtx(brief=BR.build(p, r, today=TODAY), rctx=r, profile=applicant.normalise(dict(p)),
                      ask=FakeAsk(), rules=T.rules(), today=TODAY, step_title="Application")


def mk(label, ftype="RADIO", options=YN, required=True, key="u", **kw):
    return _pf(key, label, ftype, required=required, options=options, **kw)


def out_of(res):
    """option / 'true' = chosen; '-' = nothing; STOP:<reason>"""
    if is_stop(res):
        return "STOP:" + res.reason.value
    s = shown(res)
    return s if s else "-"
