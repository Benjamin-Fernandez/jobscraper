"""H2 on a Yes/No RADIO: consent question that mentions a status word, owner consents all false."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile
p = _profile()
for k in ("privacy_consent", "data_retention_consent", "talent_pool_opt_in", "certify_true"):
    p["consents"][k] = False
real = AL.status_question
for label, klass in [("Do you consent to the processing of your personal data as a Singapore citizen?", "consent_privacy"),
                     ("As a Singapore citizen, do you agree to be contacted about other roles?", "marketing"),
                     ("Do you agree to keep your application on file? (Singapore citizens only)", "consent_retention"),
                     ("Are you a Singapore citizen and do you agree to receive our newsletter?", "marketing")]:
    out = []
    for off in (False, True):
        AL.status_question = (lambda *a, **k: None) if off else real
        # faithful confirmer: says Yes only when the WANTED line says the applicant IS (a citizen); otherwise No
        def pick(q, w, o):
            w = str(w)
            if w.startswith("If the"):
                return "no"
            return "Yes" if "is a citizen" in w or "consents" in w and "not" not in w else "No"
        ask = FakeAsk(lambda v: lie("Yes", klass), pick=pick, place="NONE")
        res = attempt(mk(label), ask, p)
        out.append("STOP:" + res.reason.value if is_stop(res) else (shown(res) or "-"))
    AL.status_question = real
    print(f"{label[:80]:80} {klass[:10]:10} ON={out[0]:10} OFF={out[1]}")
