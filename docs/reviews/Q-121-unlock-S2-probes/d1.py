"""D1: the declaration grid. Owner's truth: every declaration "none applies" (sample profile), NDA willingness true.
For each label: `adverse` = the option that states something adverse (Yes for "Have you ever been convicted?", No for
"Can you confirm you have no criminal record?"); a box labelled as a statement: adverse is "true" (ticked) unless noted.
Model value x model class x vote replies (faithful / confirm flipped / meaning flipped / both flipped).
SINGLE-fault cells (one wrong model call) that write the adverse option = HIGH; TWO-fault cells = the accepted residual (counted)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa
from g import _profile

# (label, shape, adverse, kind)  shape: R radio Yes/No, B checkbox
D = [
 ("Have you ever been convicted of a criminal offence?", "R", "Yes"),
 ("Are you a politically exposed person?", "R", "Yes"),
 ("Do you have any conflict of interest with Example Employer?", "R", "Yes"),
 ("Do you have a spouse, partner or relative working at Example Employer?", "R", "Yes"),
 ("Is your partner employed by Example Employer?", "R", "Yes"),
 ("Do you have a family member or partner who works at Example Employer?", "R", "Yes"),
 ("Do you have any personal relationship with an employee of Example Employer?", "R", "Yes"),
 ("Are you related to any director or employee of Example Employer?", "R", "Yes"),
 ("Are you a partner in any law firm or business?", "R", "Yes"),
 ("Are you bound by a non-compete agreement?", "R", "Yes"),
 ("Are you subject to any restrictive covenants or non-solicitation agreements?", "R", "Yes"),
 ("Have you signed a non-disclosure agreement with a previous employer?", "R", "Yes"),
 ("Are you subject to a confidentiality agreement with your current employer?", "R", "Yes"),
 ("Are you currently or have you been a government employee?", "R", "Yes"),
 ("Have you ever been declared bankrupt?", "R", "Yes"),
 ("Have you ever been dismissed from a job?", "R", "Yes"),
 ("Have you ever been subject to disciplinary action?", "R", "Yes"),
 ("Are you currently under investigation by any regulator?", "R", "Yes"),
 ("Do you hold shares in Example Employer?", "R", "Yes"),
 ("Have you ever been refused a visa to any country?", "R", "Yes"),
 ("Are you a director of any company?", "R", "Yes"),
 ("Do you currently work for a competitor of Example Employer?", "R", "Yes"),
 ("Have you ever been the subject of a regulatory enforcement action?", "R", "Yes"),
 ("Do you have any pending litigation?", "R", "Yes"),
 ("Have you ever had a professional licence revoked?", "R", "Yes"),
 ("Have you been convicted of a crime in the last 7 years?", "R", "Yes"),
 ("Do you have any criminal convictions that are not spent?", "R", "Yes"),
 ("Have you ever been terminated for cause?", "R", "Yes"),
 ("Do you have any outside business interests?", "R", "Yes"),
 ("Can you confirm you have no criminal record?", "R", "No"),
 ("Do you have no conflict of interest?", "R", "No"),
 ("Is it true that you have never been bankrupt?", "R", "No"),
 ("Are you free of any non-compete obligations?", "R", "No"),
 ("Do you confirm that no relative or partner of yours works at Example Employer?", "R", "No"),
 ("I have been convicted of a criminal offence", "B", "true"),
 ("I am a politically exposed person", "B", "true"),
 ("I have a spouse or partner working at Example Employer", "B", "true"),
 ("I am bound by a non-compete agreement", "B", "true"),
]
# D-87 truth-true control: willingness to sign an NDA is Yes (ordinary, D9); asked as an obligation it is No.
CONTROL = [
 ("Are you willing to sign a non-disclosure agreement?", "R", "No"),
 ("Are you willing to sign a confidentiality agreement as a condition of employment?", "R", "No"),
 ("Would you be willing to sign an NDA?", "R", "No"),
]
CLASSES = ["declaration:other", "ordinary", NO_CLASS]
p = _profile()
tot = 0
viol1, viol2, ok2 = [], [], 0
for label, shape, adverse in D:
    ftype, opts = ("RADIO", YN) if shape == "R" else ("CHECKBOX", ())
    for req in (True, False):
        non = ("No" if adverse == "Yes" else "Yes") if shape == "R" else "false"
        for mval in (adverse, non):
            for klass in CLASSES:
                for pname in ("F", "C1", "M1", "BOTH"):
                    if pname == "F":
                        pick = pick_faithful(non, non)
                    elif pname == "C1":
                        pick = pick_faithful(adverse, non)
                    elif pname == "M1":
                        pick = pick_by(non, "no")
                    else:
                        pick = pick_by(adverse, "no")
                    ask = FakeAsk(lambda v, a=mval, k=klass: lie(a, k), pick=pick, place="NONE")
                    res = attempt(mk(label, ftype, opts, required=req), ask, p)
                    tot += 1
                    out = out_of(res)
                    is_adv = (out == adverse) if shape == "R" else (out == "true")
                    if not is_adv:
                        continue
                    faults = (1 if mval == adverse else 0) + {"F": 0, "C1": 1, "M1": 1, "BOTH": 2}[pname]
                    # a flipped confirm is only a fault when the model value was non-adverse (else it agrees with the model)
                    tag = (label[:60], shape, "req" if req else "opt", "model=" + str(mval), klass[:10], pname, out)
                    (viol1 if faults <= 1 else viol2).append(tag)
print("cells", tot)
print("adverse written with <=1 wrong call (HIGH):", len(viol1))
for t in viol1[:40]:
    print("  ", t)
print("adverse written with >=2 wrong calls (accepted residual):", len(viol2))
seen = set()
for t in viol2[:400]:
    k = (t[0], t[3], t[5])
    if k in seen:
        continue
    seen.add(k)
print("  distinct labels with a double-fault cell:", len({t[0] for t in viol2}))
for lab in sorted({t[0] for t in viol2}):
    print("    ", lab)

print("\nCONTROL: willingness to sign an NDA (truth: Yes). Model Yes / No, class ordinary / none:")
for label, shape, wrong in CONTROL:
    row = []
    for mval in ("Yes", "No"):
        for klass in ("ordinary", NO_CLASS):
            ask = FakeAsk(lambda v, a=mval, k=klass: lie(a, k), pick=pick_by("Yes", "no"), place="NONE")
            row.append(f"{mval}/{klass[:4]}->" + out_of(attempt(mk(label, "RADIO", YN), ask, p)))
    print(f"  {label[:70]:70} {row}")
