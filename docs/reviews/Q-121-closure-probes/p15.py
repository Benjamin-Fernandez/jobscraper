"""S2 on CHECKBOXes (statement boxes and consent boxes that merely MENTION a status word)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa

LABELS = [
    # label, correct tick for the sample owner (SG citizen, no PR, no pass); None = depends / consent
    ("I am a Singapore citizen or permanent resident", True),
    ("I am a Singapore citizen", True),
    ("I am not a Singapore citizen", False),
    ("I am not a Singapore citizen or permanent resident and I will need a work pass", False),
    ("I confirm I hold a valid Singapore work pass", False),
    ("I hold a Singapore Employment Pass", False),
    ("I am a Singapore PR", False),
    ("I am a Singaporean", True),
    ("I consent to the collection of my personal data as a Singapore citizen or PR under the PDPA", None),
    ("I agree to the terms and confirm I am a Singapore citizen", None),
    ("I confirm that I am not a Singapore citizen or PR and agree to the foreign applicant terms", False),
    ("I understand that a Singapore citizen referee is required", None),
    ("Please tick if you are a Singapore PR", False),
    ("Tick here if you are a Singapore citizen", True),
    ("Tick if you are not a Singapore citizen", False),
    ("Tick here if you hold a work pass", None),
    ("Tick if you hold a Singapore work pass", False),
    ("I certify that I am a Singapore citizen and the information provided is true", None),
    ("I acknowledge that I have read the notice for Singapore citizen applicants", None),
    ("I am applying as a Singapore citizen for a scholarship and agree to the bond", None),
]
for label, want in LABELS:
    row = []
    for klass in ("work_right", "certification", "acknowledgement", "consent_privacy", "ordinary"):
        for mval in ("true", "false"):
            for required in (True, False):
                ask = FakeAsk(lambda v, mval=mval, klass=klass: lie(mval, klass),
                              pick=lambda q, w, o: "no" if str(w).startswith("If the") else "Yes", place="NONE")
                res = attempt(mk(label, "CHECKBOX", (), required=required), ask)
                s = "STOP" if is_stop(res) else ("T" if is_ticked(res) else "-")
                row.append(s)
    # row order: klass x mval x required
    flag = ""
    if want is True:
        pass
    if want is False and "T" in row:
        flag = "  <== TICKED a false statement"
    print(f"{label[:80]:80} want={want!s:5} | " + "".join(row) + flag)
print("order: for class in (work_right, certification, acknowledgement, consent_privacy, ordinary): for model in (true,false): for required in (req,opt)")
