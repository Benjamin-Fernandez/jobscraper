"""M2: consent asked as a DROP-DOWN / radio list of statements. Model picks the agreeing option, class right or wrong.
Profiles allfalse / sample. Prints what was chosen."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa

CASES = [
    ("Would you like us to keep your data for future roles?", ("Yes, keep my data", "No, delete it after this application"), "consent_retention", "retention"),
    ("Talent community", ("Yes, add me to the talent community", "No thanks"), "marketing", "talent"),
    ("Job alerts", ("Yes, send me job alerts", "No, I do not want alerts"), "marketing", "talent"),
    ("Privacy notice", ("I agree", "I do not agree"), "consent_privacy", "privacy"),
    ("Do you want to hear from us about other opportunities?", ("Yes please", "No thank you"), "marketing", "talent"),
    ("Communication preferences", ("Email me about new roles", "Do not email me"), "marketing", "talent"),
    ("Contact preference", ("Yes, you may contact me about other vacancies", "No, only about this application"), "ordinary", "talent"),
    ("Receive emails from Example Employer", ("Subscribe", "Do not subscribe"), "marketing", "talent"),
    ("Sharing", ("Yes, share my profile with our partner companies", "No"), "consent_privacy", "NEVER"),
]
for pname in ("allfalse", "sample"):
    p = prof(pname)
    cons = p["consents"]
    for lab, opts, klass, need in CASES:
        allowed = False if need == "NEVER" else cons[SHORT[need]]
        out = []
        for k in (klass, "ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, o=opts, k=k: lie(o[0], k), pick=lambda q, w, o: "No" if "not agree" in str(w) else "Yes", place="NONE")
            r = attempt(mk(lab, "DROPDOWN", opts, required=True), ask, p)
            out.append(out_of(r)[:34])
        flag = "  <-- agreed against owner" if (not allowed and any(x.startswith(opts[0][:12]) for x in out)) else ""
        print(f"{pname:8} owner={allowed!s:5} {lab[:44]:44} first-option-picked? {out}{flag}")
