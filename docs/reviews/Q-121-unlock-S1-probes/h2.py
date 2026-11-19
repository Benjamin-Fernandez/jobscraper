"""Reviewer probe harness (Q-121 unlock review, part S1: work rights / place / status).
Run from the worktree root: python docs/reviews/Q-121-unlock-S1-probes/<probe>.py  (fake models only; no network).

run(label, ...) -> dict(written, src, assumed, calls, stop, note, value)
  model     : what the (fake) model answers: "Yes" / "No" / "true" / "false"
  klass     : the class the model names ("work_right", "ordinary", "owner_fact", ...; None = the code key's class)
  conf      : 'faithful' = the confirmation / meaning calls say what a faithful reader says given `right`
              'follow'   = the confirmation repeats the model's own answer (a second wrong call)
              'none'     = every call unusable
  right     : the correct answer for the owner ("Yes" / "No" / None = nothing settles it)
"""
import os
import re
import sys

os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"
ROOT = os.getcwd()
sys.path[:0] = [ROOT + "/tests", ROOT + "/src"]
from always_a1_support import *  # noqa: E402,F401,F403
import llm_fill_t2 as T  # noqa: E402
from jobscraper import applicant  # noqa: E402
from jobscraper.apply import always as AL, briefing as BR  # noqa: E402
from test_always_fill import TODAY, _profile, _pf, _run, _one  # noqa: E402
import place_quote  # noqa: E402

_MV = re.compile(r"answers «(.*?)» to the (?:question|tick box)")
STATUS_WORD = re.compile(r"citizen|\bpr\b|permanent resident|national|resident|foreign|pass|visa|permit|singapor|passport", re.I)


def place_reply(label):
    if STATUS_WORD.search(label) and not re.search(r"\b(work|working|employ)\b.*\b(in|at)\b", label, re.I):
        return "NONE"           # the real model: NONE for status wordings (D-222)
    return place_quote.sensible_quote(label)


def make_pick(conf, right, model):
    def pick(q, w, o):
        r = _pick(q, w, o)
        for x in (o or ()):                      # a box's options are lower-case ("yes" / "no")
            if str(x).lower() == str(r).lower():
                return x
        return r

    def _pick(q, w, o):
        w = str(w)
        if conf == "none":
            return ""
        if w.startswith("If the applicant answers") or "other than these facts say" in w:
            m = _MV.search(w)
            v = (m.group(1).strip().lower() if m else "")
            v = {"ticked": "yes", "unticked": "no"}.get(v, v)
            if right is None:
                return "no"
            return "no" if v == right.lower() else "yes"
        if conf == "follow":
            return {"true": "Yes", "false": "No"}.get(model, model)
        return right or ""
    return pick


def mk(label, ftype="RADIO", options=YN, required=True, key="u", **kw):
    return _pf(key, label, ftype, required=required, options=options, **kw)


def run(label, model="Yes", klass="work_right", conf="faithful", right=None, ftype="RADIO", options=YN,
        profile=None, job="SG", required=True, basis="assumption", assumed=True):
    pf = mk(label, ftype, options if ftype != "CHECKBOX" else (), required=required)
    ask = FakeAsk(lambda v: lie(model, klass, basis=basis, assumed=assumed), pick=make_pick(conf, right, model),
                  place=place_reply)
    res = attempt(pf, ask, profile, rctx_kw={"job_country": job})
    calls = len(ask.picks) + len(ask.place_calls)
    if is_stop(res):
        return dict(written="STOP", src="", assumed=None, calls=calls, stop=True, note=res.reason.value, value=None)
    w = shown(res)
    if ftype == "CHECKBOX":
        w = "TICK" if is_ticked(res) else "-"
    return dict(written=w or "-", src=str(res.source), assumed=res.assumed, calls=calls, stop=False,
                note=str(res.note)[:60], value=res.value)


def cell(r):
    s = r["written"]
    s = {"Yes": "Y", "No": "N"}.get(s, s)
    return s + ("*" if r.get("assumed") else "")


def sourced_from_fact(r):
    return "singapore_status" in r["src"] or "nationality" in r["src"]
