"""1(c)/(d): the status truth for four profiles; pass / PR rules; list and date fields; passport paths."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one
import copy

def prof(nat, res, wp):
    p = _profile()
    p["singapore_status"]["nationality"] = nat
    if res is None:
        p["singapore_status"].pop("residency_status", None)
    else:
        p["singapore_status"]["residency_status"] = res
    if wp is None:
        p["singapore_status"].pop("work_pass", None)
    else:
        p["singapore_status"]["work_pass"] = wp
    return p

PROFILES = {
    "citizen": prof("SG", "citizen", "none_required"),
    "PR(MY nat)": prof("MY", "pr", "none_required"),
    "EP holder(IN)": prof("IN", "foreigner", "ep"),
    "S Pass(IN)": prof("IN", "foreigner", "s_pass"),
    "no res status, MY nat": prof("MY", None, None),
    "no res status, SG nat": prof("SG", None, None),
    "nat unset": prof("", None, None),
}
LABELS = ["Are you a Singapore citizen?", "Are you a Singapore PR?", "Are you a Singapore citizen or PR?",
          "Are you a Singapore resident?", "Do you hold a valid Singapore work pass?",
          "Do you hold a Singapore Employment Pass?", "Do you hold a Singapore S Pass?",
          "Do you hold a Singapore Dependant's Pass?", "Do you hold a Singapore work visa?",
          "Are you a Malaysian citizen?", "Do you hold a Malaysian passport?", "Are you a Malaysian PR?",
          "Do you hold a UK visa?", "Are you a Singaporean?", "Do you hold a Singapore passport?"]
for pname, p in PROFILES.items():
    c = ctx(p)
    print("==", pname)
    for lab in LABELS:
        sq = AL.status_question(mk(lab), "SG")
        if sq is None:
            print(f"   {lab[:48]:48} -> no status question")
            continue
        t = AL.status_truth(sq, c)
        print(f"   {lab[:48]:48} -> truth={t[0]} src={t[1].split(':')[-1]} kind={t[2]}")
