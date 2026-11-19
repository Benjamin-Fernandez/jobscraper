"""Q2 (d): status questions whose options are NOT Yes/No. What is picked for a citizen, a PR and a pass holder; and does the
canonical (0-call) write ever fire on a label that only resembles a frame (trailing text, two sentences, a hint)?
Cells per owner: [model right] [model WRONG, faithful calls] [model WRONG, confirmer repeats the model]; '!' = wrong option."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT, PR, EP

CASES = [
    ("What is your work status in Singapore?", ["Singapore Citizen", "Singapore PR", "Employment Pass", "S Pass", "Other"],
     ("Singapore Citizen", "Singapore PR", "Employment Pass")),
    ("Are you a Singapore citizen?", ["Citizen", "PR", "Employment Pass", "Other"], ("Citizen", "PR", "Employment Pass")),
    ("Residency status", ["Citizen", "Permanent Resident", "Foreigner"], ("Citizen", "Permanent Resident", "Foreigner")),
    ("Citizenship", ["Singapore", "Malaysia", "India", "Other"], ("Singapore", "Malaysia", "Malaysia")),
    ("Do you require work authorisation in Singapore?", ["No, I am a citizen or PR", "Yes, I hold an Employment Pass", "Yes, I need sponsorship"],
     ("No, I am a citizen or PR", "No, I am a citizen or PR", "Yes, I hold an Employment Pass")),
]
for label, opts, rights in CASES:
    row = []
    for (vn, prof), right in zip((("CIT", CIT), ("PR", PR), ("EP", EP)), rights):
        wrong = next(o for o in opts if o != right)
        cells = []
        for mv, conf in ((right, "faithful"), (wrong, "faithful"), (wrong, "follow")):
            pf = mk(label, "DROPDOWN" if len(opts) > 3 else "RADIO", opts)
            ask = FakeAsk(lambda v, mv=mv: lie(mv, "work_right"), pick=make_pick(conf, right, mv), place=place_reply)
            res = attempt(pf, ask, prof)
            w = "STOP" if is_stop(res) else (shown(res) or "-")
            cells.append(f"{w[:14]}{'!' if w not in (right, '-', 'STOP') else ''}")
        row.append(f"{vn}: " + " / ".join(cells))
    print(f"{label[:44]:44} | " + " | ".join(row))

print("\n== canonical frame lookalikes (0-call write): CIT owner, the model says the WRONG value (No); the fact is Yes")
LOOK = ["Are you a Singapore citizen?", "Are you a Singapore citizen? Please select one.", "Are you a Singapore citizen? (Y/N)",
        "Are you a Singapore citizen? If not, please state your visa type.", "Are you a Singapore citizen? Are you a Singapore PR?",
        "Are you a Singapore citizen?\nSelect Yes or No", "Singapore citizen?", "Are you a Singapore citizen *",
        "ARE YOU A SINGAPORE CITIZEN?", "Are you a Singapore citizen?  (this is required by law)",
        "Are you a Singapore citizen? Note: PRs answer No.", "Are you a Singapore citizen or PR? Required for the scholarship."]
for label in LOOK:
    ask = FakeAsk(lambda v: lie("No", "work_right"), pick=make_pick("faithful", "Yes", "No"), place=place_reply)
    res = attempt(mk(label), ask, CIT)
    print(f"  {label.replace(chr(10), ' / ')[:70]:70} model No -> {what(res)[:110]}  calls={len(ask.picks)}")
