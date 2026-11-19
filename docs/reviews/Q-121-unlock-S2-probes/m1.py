"""M1: the owner HAS consented (sample profile: privacy, retention, certify true). The model refuses or is silent (basis none) on an
optional consent box / yes-no, under the RIGHT class. Does code write the owner's truth (both keys known)?"""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa

p = prof("sample")
CASES = [
    ("I have read and agree to the Privacy Policy", "consent_privacy"),
    ("I agree to the processing of my personal data for recruitment purposes", "consent_privacy"),
    ("I consent to the collection, use and disclosure of my personal data as described in the Privacy Notice", "consent_privacy"),
    ("Keep my application on file for future opportunities", "consent_retention"),
    ("I agree that Example Employer may retain my CV for up to 24 months", "consent_retention"),
    ("I certify that the information provided is true and complete", "certification"),
    ("I accept the terms of use", "acknowledgement"),
    ("I agree to the Terms and Conditions", "acknowledgement"),
]
for lab, klass in CASES:
    k = AL.code_key_full(mk(lab, "CHECKBOX", (), required=False), ctx(p))
    row = []
    for shape, ft, opts, req, yes, no in (("box-opt", "CHECKBOX", (), False, "true", "false"), ("yn-opt", "RADIO", YN, False, "Yes", "No"),
                                          ("yn-req", "RADIO", YN, True, "Yes", "No")):
        for beh, rep in (("refuse", lie(no, klass)), ("none", say(None, "none", "", False, "x", klass=klass))):
            if beh == "none" and req:
                continue
            ask = FakeAsk(lambda v, r=rep: r, pick=lambda q, w, o: "yes" if shape.startswith("box") else "Yes", place="NONE")
            row.append(f"{shape}/{beh}={out_of(attempt(mk(lab, ft, opts, required=req), ask, p))}")
    print(f"{(k.klass.value if k.klass else None)!s:16} {[c.value for c in k.classes]!s:44} {lab[:62]:62} {row}")
