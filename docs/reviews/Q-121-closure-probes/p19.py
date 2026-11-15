"""H1 regression proof: S2 ON vs OFF for labels that contain a status word but ask something else. The model answers what
is RIGHT for the owner; the confirmer is faithful to the question when it can be (here: it answers the RIGHT value); the
meaning call is faithful. Shows what S2 does to a RIGHT model."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one
import re

def prof_ns(ns):
    p = _profile()
    p["singapore_status"]["ns_status"] = ns
    return p

# label, right answer for ns=completed, right answer for ns=exempt
CASES = [
    ("Have you completed Singapore National Service?", "Yes", "No"),
    ("Have you completed your Singapore National Service obligations?", "Yes", "No"),
    ("Are you exempted from Singapore National Service?", "No", "Yes"),
    ("Are you currently serving Singapore National Service?", "No", "No"),
    ("Do you hold a Singapore passport that expires within 6 months?", None, None),
    ("Are you a Singapore national scholarship holder?", None, None),
]
real = AL.status_question
for label, r1, r2 in CASES:
    out = []
    for off in (False, True):
        AL.status_question = (lambda *a, **k: None) if off else real
        for ns, right in (("completed", r1), ("exempt", r2)):
            if right is None:
                right = "No"
            def pick(q, w, o, right=right):
                w = str(w)
                if w.startswith("If the applicant answers"):
                    m = re.search(r"answers «(.*?)» to the question", w)
                    return "no" if m and m.group(1).strip() == right else "yes"
                return right
            ask = FakeAsk(lambda v, right=right: lie(right, None), pick=pick, place="NONE")
            res = attempt(mk(label), ask, prof_ns(ns))
            s = "STOP" if is_stop(res) else (shown(res) or "-")
            src = "" if is_stop(res) else str(res.source).split(":")[-1][:12]
            out.append(f"{ns[:4]}(right={right[:3]})={s}[{src}]")
    AL.status_question = real
    print(f"{label[:62]:62} ON: {out[0]} {out[1]} | OFF: {out[2]} {out[3]}")
