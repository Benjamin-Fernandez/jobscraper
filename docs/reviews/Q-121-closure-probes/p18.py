"""Words that CONTAIN a status word without asking a status question: National Service, NRIC, scholarship, 'resident' (tax / physical)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one
import re

def prof_ns(ns):
    p = _profile()
    p["singapore_status"]["ns_status"] = ns
    return p

LABELS = [
    "Have you completed Singapore National Service?",
    "Have you completed your Singapore National Service obligations?",
    "Are you currently serving Singapore National Service?",
    "Are you exempted from Singapore National Service?",
    "Are you a Singapore National Serviceman?",
    "Have you completed national service in Singapore?",
    "Do you have a Singapore National Registration Identity Card?",
    "Are you a Singapore national scholarship holder?",
    "Do you have a Singapore national certification?",
    "Are you a tax resident of Singapore?",
    "Are you a resident of Singapore for tax purposes?",
    "Have you been a Singapore resident for the last 2 years?",
    "Have you been a Singapore PR for at least 2 years?",
    "Do you hold a Singapore permit to work?",
    "Do you hold a Singapore driving permit?",
    "Do you hold a Singapore visa for travel?",
    "Do you hold a valid Singapore passport with at least 6 months validity?",
    "Do you hold a Singapore passport that expires within 6 months?",
]
for label in LABELS:
    sq = AL.status_question(mk(label), "SG")
    row = []
    for ns, right in (("completed", "Yes"), ("exempt", "No")):
        # model answers the CORRECT answer for an NS-completed owner ("Yes") or invents; confirmer follows the WANTED text
        for mval in ("Yes", "No"):
            ask = FakeAsk(lambda v, mval=mval: lie(mval, None), pick=lambda q, w, o: "no" if str(w).startswith("If the") else ("Yes" if "applicant is" in str(w) and "not" not in str(w) else "No"), place="NONE")
            res = attempt(mk(label), ask, prof_ns(ns))
            row.append(("STOP" if is_stop(res) else (shown(res) or "-")))
    print(f"{label[:66]:66} sq={'-' if sq is None else (sq.country, sorted(sq.kinds))} | ns=completed m=Yes/No -> {row[0]}/{row[1]} ; ns=exempt m=Yes/No -> {row[2]}/{row[3]}")
