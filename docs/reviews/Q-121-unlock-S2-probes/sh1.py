"""SH1: the third-party sharing reader. For each wording: share_frame / internal_share_frame (pure functions, no model), the
resulting key kind, and the outcome for a required tick box with the sample profile (model agrees, class consent_privacy)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa

E = "Example Employer"
RECIPIENTS = [
    "sister companies", "our network", "hiring partners", "customers", "portfolio companies", "our parent company",
    "franchisees", "background-check vendors", "background screening providers", "government agencies", "referees",
    "subsidiaries", "other employers", "recruiters", "staffing agencies", "our clients", "partners", "trusted partners",
    "business partners", "affiliates", "affiliated companies", "related corporations", "other companies", "other organisations",
    "universities", "the government", "regulators", "law enforcement", "insurers", "payroll providers", "marketing partners",
    "advertisers", "data brokers", "analytics providers", "our sponsors", "investors", "joint venture partners", "peers",
    "headhunters", "job boards", "consultants", "professional advisers", "auditors", "service providers", "our vendors",
]
FRAMES = [
    "I agree that {E} may share my personal data with {R}",
    "I consent to {E} sharing my details with {R}",
    "{E} may disclose my application to {R}. I agree.",
    "I agree to my CV being passed to {R}",
    "I consent to {R} having access to my application",
]
p = prof("sample")
c = ctx(p)
bad = []
n = 0
for r in RECIPIENTS:
    for fr in FRAMES:
        lab = fr.format(E=E, R=r)
        n += 1
        k = AL.code_key_full(mk(lab, "CHECKBOX", (), required=True), c)
        kind = "share" if k.share else ("internal" if k.internal else (k.klass.value if k.klass else "none"))
        ask = FakeAsk(lambda v: lie("true", "consent_privacy"), pick=lambda q, w, o: "yes", place="NONE")
        res = attempt(mk(lab, "CHECKBOX", (), required=True), ask, p)
        if kind != "share":
            bad.append((r, kind, out_of(res), lab))
print("wordings", n, "not caught as third-party share:", len(bad))
seen = {}
for r, kind, out, lab in bad:
    seen.setdefault((r, kind, out), []).append(lab)
for (r, kind, out), labs in sorted(seen.items()):
    print(f"{r:28} kind={kind:15} out={out:22} n={len(labs)}  e.g. {labs[0][:110]}")
