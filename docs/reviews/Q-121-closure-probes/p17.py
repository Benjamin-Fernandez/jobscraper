"""The confirmation call for a status CHECKBOX, with a FAITHFUL confirmer: yes iff the box states the owner's truth."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
import re

TICK_RIGHT = {"I am a Singapore citizen": True, "I am a Singapore PR": False, "I am not a Singapore citizen": False,
              "I am a Singapore citizen or permanent resident": True, "I am a Singaporean": True}
cur = {}
def pick(q, w, o):
    w = str(w)
    right = TICK_RIGHT[cur["label"]]
    if w.startswith("If the applicant answers"):
        # meaning call: does answering X state the contradiction? ticking states the contradiction iff the box is false
        m = re.search(r"answers «(.*?)» to the tick box", w)
        v = (m.group(1).strip().lower() if m else "")
        ticks = v in ("ticked", "true", "yes")
        return "yes" if (ticks != right) else "no"
    return "yes" if right else "no"
for label in TICK_RIGHT:
    cur["label"] = label
    for mval in ("true", "false"):
        ask = FakeAsk(lambda v, mval=mval: lie(mval, "work_right"), pick=pick, place="NONE")
        res = attempt(mk(label, "CHECKBOX", (), required=True), ask)
        print(f"{label:50} model={mval:5} right_tick={TICK_RIGHT[label]!s:5} -> ticked={is_ticked(res)} | {what(res)[:150]} | calls={len(ask.picks)}")
