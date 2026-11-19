"""K1: which consent-like wordings does code leave UNKEYED (L7 territory)? Prints code_key class per wording (checkbox),
and, for the unkeyed ones, what the filler does with the owner's consents ALL FALSE when the model ticks and calls it ordinary."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa
L = [
 "I agree to the Terms and Conditions", "I accept the terms of use", "I agree to the Example Employer Code of Conduct",
 "Yes, send me updates", "I'd like to hear about career opportunities", "Allow Example Employer to reach out to me with similar roles",
 "Can we contact you by phone?", "I am open to being contacted by recruiters", "Opt in to SMS notifications",
 "I want to be notified of new openings", "Notify me when new jobs are posted", "Sign me up for the careers newsletter",
 "Add me to your mailing list", "I would like to stay connected with Example Employer", "Keep in touch", "Send me similar jobs",
 "I agree to be contacted by Example Employer's recruitment team", "I agree to receive emails from Example Employer",
 "I consent to Example Employer contacting me about opportunities", "I would like to be considered for future roles",
 "I agree to my data being used to improve the recruitment process", "I consent to the use of my data for research and analytics",
 "I agree to have my interview recorded", "I consent to automated decision-making in the screening of my application",
 "I authorise Example Employer to verify my qualifications", "I agree to the use of cookies",
 "I consent to receive communications from Example Employer", "Send me a copy of my application by email",
 "I would like to receive emails with career tips", "Yes, I want to receive Example Employer updates",
 "I agree to the use of AI tools in evaluating my application", "I agree to be added to the Example Employer talent network",
 "Text me about new roles", "WhatsApp me about openings", "I'd like to be part of the Example Employer alumni network",
 "Example Employer may contact me about similar positions", "I agree to be contacted for market research surveys",
]
p = prof("allfalse")
c = ctx(p)
unkeyed = []
for lab in L:
    k = AL.code_key_full(mk(lab, "CHECKBOX", (), required=False), c)
    nm = (k.klass.value if k.klass else None)
    print(f"{lab[:78]:78} -> {nm}{':' + k.which if k.which else ''}")
    if nm is None:
        unkeyed.append(lab)
print("\nUNKEYED, model ticks + class ordinary, all consents false, optional box / required box / yes-no:")
for lab in unkeyed:
    res = []
    for ft, opts, req in (("CHECKBOX", (), False), ("CHECKBOX", (), True), ("RADIO", YN, True)):
        yes = "true" if ft == "CHECKBOX" else "Yes"
        ask = FakeAsk(lambda v: lie(yes, "ordinary"), pick=lambda q, w, o: "Yes", place="NONE")
        r = attempt(mk(lab, ft, opts, required=req), ask, p)
        res.append(out_of(r) + ("(assumed)" if (not is_stop(r) and r.assumed) else ""))
    print(f"{lab[:70]:70} {res}")
