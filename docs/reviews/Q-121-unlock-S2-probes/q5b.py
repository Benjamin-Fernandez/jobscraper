"""Q5b: why does an ordinary required privacy box that says collect / use / STORE my personal data stop? (sample profile)"""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa
p = prof("sample")
for lab in ["I consent to Example Employer collecting, using and storing my personal data for the purpose of processing my application",
            "I agree to the collection, use and storage of my personal data as described in the Privacy Policy",
            "I consent to you storing my personal data for the purposes of recruitment",
            "I agree that Example Employer may store and process my personal information in connection with my application",
            "I consent to the processing and storage of my personal data for recruitment purposes",
            "I consent to Example Employer holding my personal data for the duration of the recruitment process",
            "I consent to my data being kept by Example Employer for the purpose of assessing my application",
            "I consent to the collection, use and retention of my personal data for recruitment purposes",
            "I agree that Example Employer will store my personal data securely and use it only for recruitment"]:
    k = AL.code_key_full(mk(lab, "CHECKBOX", (), required=True), ctx(p))
    ask = FakeAsk(lambda v: lie("true", "consent_privacy"), pick=lambda q, w, o: "yes", place="NONE")
    r = attempt(mk(lab, "CHECKBOX", (), required=True), ask, p)
    print(out_of(r), "|", [c.value for c in k.classes], "|", (r.detail if is_stop(r) else ""), "|", lab[:90])
