"""Neighbours of the known open defect (no country, another tense, 'a status wording under owner_fact'): status wordings the
no-country shapes do NOT recognise, with the model WRONG under three classes and a faithful confirmer. CIT owner.
'!' = a wrong value is written; the cell shows what is written and whether it is marked assumed (*)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT, PR

L = [
    ("Have you ever been a permanent resident?", "No"),
    ("Will you be a permanent resident by the start date?", "No"),
    ("Have you been a citizen since birth?", "Yes"),
    ("Are you a citizen as of today?", "Yes"),
    ("Do you currently hold PR?", "No"),
    ("Do you have PR status?", "No"),
    ("Do you have a PR?", "No"),
    ("Are you permanently resident in Singapore?", "Yes"),
    ("Are you a citizen, or do you hold a work pass?", "Yes"),
    ("Are you a PR, or do you hold a work pass?", "No"),
    ("Are you a citizen? Yes/No", "Yes"),
    ("Are you presently a PR?", "No"),
    ("Are you now a permanent resident?", "No"),
    ("Is the applicant a PR?", "No"),
    ("Do you hold dual citizenship?", "No"),
    ("Do you hold citizenship of another country?", "No"),
    ("Have you ever held citizenship of another country?", "No"),
    ("Were you born in Singapore?", "Yes"),
    ("Are you a naturalised citizen?", "No"),
    ("Are you a first-generation PR?", "No"),
    ("Are you a PR holder?", "No"),
    ("Are you a citizen/PR?", "Yes"),
    ("Are you a SG citizen?", "Yes"),
    ("Are you a SC or PR?", "Yes"),
    ("Do you hold SG citizenship?", "Yes"),
    ("Are you a Singapore Citizen / PR?", "Yes"),
]
opp = lambda v: "No" if v == "Yes" else "Yes"
bad = 0
for label, right in L:
    row = []
    for klass in ("work_right", "owner_fact", "ordinary"):
        r = run(label, opp(right), klass, "faithful", right, "RADIO", YN, CIT)
        w = r["written"]
        wrong = w in ("Yes", "No") and w != right
        bad += wrong
        row.append(f"{klass[:5]}:{w[:4]}{'*' if r['assumed'] else ''}{'!' if wrong else ''}")
    sq = AL.status_question(mk(label), "SG")
    print(f"{label[:56]:56} right={right:3} sq={'-' if sq is None else ('plain' if sq.plain else 'G3')}  | " + "  ".join(row))
print("wrong values written from ONE wrong model answer:", bad)
