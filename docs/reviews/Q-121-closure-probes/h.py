"""Reviewer probe helpers (Q-121 closure review). Run from the worktree root with PYTHONPATH unset:
python docs/reviews/Q-121-closure-probes/<probe>.py  (fake models only; no network, no model)."""
import os
import sys

os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"
ROOT = os.getcwd()
sys.path[:0] = [ROOT + "/tests", ROOT + "/src"]
from always_a1_support import *  # noqa: E402,F401,F403
import llm_fill_t2 as T  # noqa: E402
from jobscraper import applicant  # noqa: E402
from jobscraper.apply import always as AL, briefing as BR  # noqa: E402
from test_always_fill import TODAY, _profile, _pf, _run, _one  # noqa: E402


def ctx(p=None):
    p = p if p is not None else _profile()
    r = T.rctx(p)
    return AL.PageCtx(brief=BR.build(p, r, today=TODAY), rctx=r, profile=applicant.normalise(dict(p)),
                      ask=FakeAsk(), rules=T.rules(), today=TODAY, step_title="Application")


def mk(label, ftype="RADIO", options=YN, required=True, key="u", **kw):
    return _pf(key, label, ftype, required=required, options=options, **kw)
