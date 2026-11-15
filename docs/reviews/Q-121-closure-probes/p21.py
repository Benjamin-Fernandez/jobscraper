"""H2 candidate: a CONSENT / certification / acknowledgement tick box that merely mentions a status word. The owner has all
four consents FALSE (profile). S2 makes the box a status question (truth = nationality = True). Does the box get ticked?
Model: ticks (true) under its own class; confirmer 'yes' to 'The applicant is a citizen of Singapore. Should the box be
ticked?' (what any reader of that sentence says); meaning call 'no'. S2 ON vs OFF."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one

def prof(**kw):
    p = _profile()
    for k, v in kw.items():
        p["consents"][k] = v
    return p
FALSE = prof(privacy_consent=False, data_retention_consent=False, talent_pool_opt_in=False, certify_true=False)
LABELS = [
    ("I consent to the collection and use of my personal data as a Singapore citizen or PR under the PDPA", "consent_privacy"),
    ("I agree to the privacy policy and confirm I am a Singapore citizen", "consent_privacy"),
    ("I certify that I am a Singapore citizen and that the information provided is true and complete", "certification"),
    ("I acknowledge that I have read the notice for Singapore citizen applicants", "acknowledgement"),
    ("Keep my application on file; I am a Singapore citizen", "consent_retention"),
    ("I am a Singapore citizen and agree to receive job alerts", "marketing"),
    ("I agree to share my details with partner firms. I am a Singapore PR", "consent_privacy"),
]
real = AL.status_question
for label, klass in LABELS:
    out = []
    for off in (False, True):
        AL.status_question = (lambda *a, **k: None) if off else real
        for required in (True, False):
            ask = FakeAsk(lambda v: lie("true", klass),
                          pick=lambda q, w, o: "no" if str(w).startswith("If the") else "yes", place="NONE")
            res = attempt(mk(label, "CHECKBOX", (), required=required), ask, FALSE)
            out.append("STOP:" + res.reason.value if is_stop(res) else ("TICKED" if is_ticked(res) else "-"))
    AL.status_question = real
    print(f"{label[:70]:70} {klass[:10]:10} ON req/opt={out[0]}/{out[1]}   OFF req/opt={out[2]}/{out[3]}")
