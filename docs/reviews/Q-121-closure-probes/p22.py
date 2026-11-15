"""Is 'I agree to share my details with partner firms.' ticked with all consents false on a model that says true? (S2-independent check)"""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile
p = _profile()
for k in ("privacy_consent", "data_retention_consent", "talent_pool_opt_in", "certify_true"):
    p["consents"][k] = False
for label, klass in [("I agree to share my details with partner firms.", "consent_privacy"),
                     ("I agree to share my details with partner firms.", "consent_retention"),
                     ("I agree to share my details with partner firms.", "marketing"),
                     ("I agree to share my details with partner firms.", "ordinary"),
                     ("I agree to share my details with partner firms. I am a Singapore PR", "consent_privacy")]:
    ask = FakeAsk(lambda v: lie("true", klass), pick=lambda q, w, o: "no" if str(w).startswith("If the") else "yes", place="NONE")
    res = attempt(mk(label, "CHECKBOX", (), required=False), ask, p)
    print(f"{label[:66]:66} {klass:18} -> {'STOP:'+res.reason.value if is_stop(res) else ('TICKED' if is_ticked(res) else '-')}  {'' if is_stop(res) else str(res.note)[:70]}")
