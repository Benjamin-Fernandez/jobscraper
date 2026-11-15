"""1(b): other-person labels. Current code vs S2 switched off (status_question -> None, the pre-D-222 S2 behaviour),
model classes other_person / work_right / ordinary, model answers Yes or No, confirmer 'follow'."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one
import re

LABELS = [
    "Is your spouse a Singapore citizen?",
    "Is your referee a US citizen?",
    "Does the role require a Singapore citizen?",
    "Is your father a Singaporean?",
    "Is your mother a Singapore citizen or PR?",
    "Do you have a family member who is a Singapore citizen?",
    "Is your emergency contact a Singapore citizen?",
    "Is the person you referred a Singapore citizen?",
    "Is your spouse a Singapore PR?",
    "Has any member of your family held a Singapore work pass?",
    "Does your partner hold a Singapore Employment Pass?",
]

def pick(q, w, o):
    w = str(w)
    if w.startswith("If the applicant answers"):
        return "no"
    return "Yes"

def go(label, mval, klass, off):
    real = AL.status_question
    if off:
        AL.status_question = lambda *a, **k: None
    try:
        ask = FakeAsk(lambda v: lie(mval, klass), pick=pick, place="NONE")
        res = attempt(mk(label), ask)
        return res, ask
    finally:
        AL.status_question = real

for label in LABELS:
    out = []
    for klass in ("other_person", "work_right", "ordinary"):
        for mval in ("Yes", "No"):
            for off in (False, True):
                res, ask = go(label, mval, klass, off)
                s = "STOP" if is_stop(res) else (shown(res) or "-")
                a = "" if is_stop(res) else ("a" if res.assumed else "")
                out.append(f"{klass[:5]}/{mval[0]}/{'off' if off else 'ON '}={s}{a}")
    print(label[:55])
    print("   " + "  ".join(out))
