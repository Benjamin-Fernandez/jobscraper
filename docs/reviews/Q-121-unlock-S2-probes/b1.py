"""B1: BUNDLED boxes: a privacy / keep-on-file consent AND a contact (talent-pool) request. Sample profile (privacy + retention true,
talent_pool_opt_in FALSE): the right outcome is NOT ticked (optional) / consent_refused stop (required) / No. The model says the
right class AND refuses (the best case for the filler): a tick here is written by CODE.
Counts per contact phrase; prints the ones ticked."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa

E = "Example Employer"
LEAD = [
    "I agree to the processing of my personal data and {c}",
    "I consent to the collection and use of my data by {E}, and {c}",
    "I have read the Privacy Policy and {c}",
    "I agree to the privacy notice and {c}",
]
CONTACT = [
    "to receive job alerts", "to be contacted about other vacancies", "to being contacted about other vacancies",
    "to being contacted about future opportunities", "to {E} contacting me about future opportunities",
    "to {E} contacting me about other roles", "for {E} to contact me about future roles", "to be contacted by {E} about similar roles",
    "to receive emails from {E}", "to receive communications from {E}", "to receive updates", "to receive our newsletter",
    "to receive marketing communications", "to receive SMS messages", "to stay in touch", "to hear about career opportunities",
    "to receive information about events", "to be added to your talent community", "to be contacted by recruiters",
    "to {E} keeping in touch with me about vacancies", "to be emailed about new openings", "to be sent job recommendations",
]
p = prof("sample")
n = bad = 0
rows = []
for lead in LEAD:
    for c in CONTACT:
        lab = lead.format(c=c.format(E=E), E=E)
        n += 1
        k = AL.code_key_full(mk(lab, "CHECKBOX", (), required=False), ctx(p))
        classes = [x.value for x in k.classes]
        res = []
        for beh, v in (("agree", "true"), ("refuse", "false")):
            ask = FakeAsk(lambda x, v=v: lie(v, "consent_privacy"), pick=lambda q, w, o: "no" if "not agree" in str(w) else "yes", place="NONE")
            res.append(out_of(attempt(mk(lab, "CHECKBOX", (), required=False), ask, p)))
        ask = FakeAsk(lambda x: lie("true", "consent_privacy"), pick=lambda q, w, o: "yes", place="NONE")
        rq = out_of(attempt(mk(lab, "CHECKBOX", (), required=True), ask, p))
        ticked = res[0] == "true" or res[1] == "true" or rq == "true"
        bad += ticked
        rows.append((ticked, classes, res, rq, lab))
print("bundles", n, "ticked against talent_pool_opt_in=false:", bad)
for t, cl, res, rq, lab in rows:
    print(("TICK " if t else "ok   "), cl, "opt agree/refuse:", res, "req:", rq, "|", lab[:110])
