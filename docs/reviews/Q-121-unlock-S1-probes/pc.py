"""Q2 (c)(d)(e): three owner variants x status / work-rights labels. Cells per variant: [model right] [model WRONG, faithful
calls] [model WRONG, confirmer repeats the model]. '!' = a value differing from the right one is written ('!!' in the
faithful column = ONE model mistake wrote a wrong value). '-' = empty / left for the site.
Owner variants: CIT = sample (Singapore citizen); PR = Malaysian permanent resident; EP = Malaysian, Employment Pass."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from h2 import _profile

CIT = profile_with()
PR = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pr",
                  singapore_status__authorised_to_work={"SG": True}, singapore_status__requires_sponsorship={"SG": False})
EP = profile_with(singapore_status__nationality="MY", singapore_status__residency_status="foreigner",
                  singapore_status__work_pass="ep", singapore_status__authorised_to_work={"SG": True},
                  singapore_status__requires_sponsorship={"SG": False})
VARS = (("CIT", CIT), ("PR", PR), ("EP", EP))

Y, N = "Yes", "No"
# label -> (right for CIT, PR, EP)
L = [
    ("Are you a Singapore citizen?", (Y, N, N)),
    ("Are you a Singapore citizen or PR?", (Y, Y, N)),
    ("Are you a Singapore PR?", (N, Y, N)),
    ("Are you a citizen or permanent resident?", (Y, Y, N)),
    ("Are you a PR?", (N, Y, N)),
    ("Are you a foreigner?", (N, Y, Y)),
    ("Are you a non-citizen?", (N, Y, Y)),
    ("Are you a non-Singapore citizen?", (N, Y, Y)),
    ("Do you hold an Employment Pass?", (N, N, Y)),
    ("Do you hold a Singapore Employment Pass?", (N, N, Y)),
    ("Do you hold a valid Singapore work pass?", (N, N, Y)),
    ("Are you a Malaysian?", (N, Y, Y)),
    ("Are you a Malaysian citizen?", (N, Y, Y)),
    ("Are you a US citizen?", (N, N, N)),
    ("Do you hold a Singapore passport?", (Y, N, N)),
    ("Do you hold Singapore citizenship?", (Y, N, N)),
    ("Are you a Singapore resident?", (Y, Y, None)),
    ("Do you have the right to work in Singapore?", (Y, Y, Y)),
    ("Are you legally authorised to work in Singapore?", (Y, Y, Y)),
    ("Will you now or in the future require sponsorship to work in Singapore?", (N, N, N)),
    ("Do you require a visa to work in Singapore?", (N, N, N)),
    ("Do you require an employment pass or work visa?", (N, N, N)),
    ("Are you a citizen?", (Y, N, N)),
]


def opp(v):
    return N if v == Y else Y


def evaluate(label, rights, ftype="RADIO", options=YN, job="SG", klass="work_right"):
    out = []
    bad = []
    for (vn, prof), right in zip(VARS, rights):
        cells = []
        for m, conf in (("right", "faithful"), ("wrong", "faithful"), ("wrong", "follow")):
            if right is None:
                mv = Y if m == "right" else N
            else:
                mv = right if m == "right" else opp(right)
            if ftype == "CHECKBOX":
                mv = {Y: "true", N: "false"}[mv]
            r = run(label, mv, klass, conf, right, ftype, options if ftype == "RADIO" else (), prof, job,
                    required=(ftype == "RADIO"))
            w = r["written"]
            s = {"Yes": "Y", "No": "N", "TICK": "T"}.get(w, w) + ("*" if r["assumed"] else "")
            if ftype == "CHECKBOX":
                wr = {"TICK": Y, "-": None}.get(w)
                wrong = right is not None and wr is not None and wr != right
                # an unticked box for a Yes-right is not a wrong value (silent), a ticked box for a No-right is
            else:
                wrong = right is not None and w in (Y, N) and w != right
            mark = "!" if wrong else ""
            if wrong and conf == "faithful" and m == "wrong":
                mark = "!!"
            if wrong and m == "right":
                mark = "!R"
            cells.append(s + mark)
            if mark:
                bad.append((label, ftype, vn, m, conf, w, r["src"], r["assumed"]))
        out.append(f"{vn}: " + " ".join(f"{c:7}" for c in cells))
    return out, bad


if __name__ == "__main__":
    allbad = []
    for ft in ("RADIO", "CHECKBOX"):
        for label, rights in L:
            if ft == "CHECKBOX" and not label.startswith(("Are you", "Do you hold")):
                continue
            out, bad = evaluate(label, rights, ft)
            allbad += bad
            print(f"{ft[:5]} {label[:58]:58} | " + " | ".join(out))
    print("\nBAD:")
    for b in allbad:
        print(b)
    print("\n--- job country MY / US with the CIT owner (job_country is never set in production: default SG)")
    for job in ("MY", "US"):
        for label, rights in (("Are you a citizen?", (None,)), ("Are you a PR?", (None,)), ("Are you a foreigner?", (None,)),
                              ("Are you a citizen or permanent resident?", (None,)), ("Do you hold an Employment Pass?", (None,)),
                              ("Are you authorised to work in this country?", (None,)),
                              ("Do you require sponsorship to work in this country?", (None,))):
            r = run(label, Y, "work_right", "faithful", None, "RADIO", YN, CIT, job)
            r2 = run(label, N, "work_right", "faithful", None, "RADIO", YN, CIT, job)
            print(job, f"{label:56}", "model Yes ->", cell(r), r["src"][:50], "| model No ->", cell(r2), r2["src"][:50])
