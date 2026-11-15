"""S2 on statement CHECKBOXes: current vs S2 switched off, model ticks (true), required box, faithful votes."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one

LABELS = [
    ("I am a Singapore citizen or permanent resident", "tick"),
    ("I am a Singapore citizen", "tick"),
    ("I am a Singaporean", "tick"),
    ("Tick here if you are a Singapore citizen", "tick"),
    ("I certify that I am a Singapore citizen and the information provided is true", "tick"),
    ("I confirm that I am not a Singapore citizen or PR and agree to the foreign applicant terms", "no"),
    ("I am a Singapore PR", "no"),
    ("I am a citizen of Singapore", "tick"),
    ("I am a Singapore citizen / PR", "tick"),
]
real = AL.status_question
for label, want in LABELS:
    out = []
    for off in (False, True):
        AL.status_question = (lambda *a, **k: None) if off else real
        for klass in ("work_right", "certification", "ordinary"):
            for required in (True, False):
                ask = FakeAsk(lambda v, klass=klass: lie("true", klass),
                              pick=lambda q, w, o: "no" if str(w).startswith("If the") else "Yes", place="NONE")
                res = attempt(mk(label, "CHECKBOX", (), required=required), ask)
                out.append("STOP" if is_stop(res) else ("T" if is_ticked(res) else "-"))
    AL.status_question = real
    print(f"{label[:84]:84} want={want:4} ON(wr,cert,ord x req,opt)={''.join(out[:6])}  OFF={''.join(out[6:])}")
sq = AL.status_question(mk("I am a Singapore citizen", "CHECKBOX", ()), "SG")
print("status_question for the checkbox:", sq)
