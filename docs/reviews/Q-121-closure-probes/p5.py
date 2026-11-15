"""1(d)/(e): pass, passport and ID fields end to end. A model that INVENTS (wrong value, no ground) under several classes."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one

PASS_LIST = ("Employment Pass", "S Pass", "Work Permit", "Dependant's Pass", "Not applicable", "None", "Citizen")
NAT_LIST = ("Singapore", "Malaysia", "India", "United States", "Other")
CASES = [
    # label, type, options, invented value, ok-set (what is acceptable)
    ("Do you hold a valid work pass?", "RADIO", YN, "Yes", {"No", "", "STOP"}),
    ("Do you hold a valid Employment Pass?", "RADIO", YN, "Yes", {"No", "", "STOP"}),
    ("Do you require a work pass?", "RADIO", YN, "Yes", {"No", "", "STOP"}),
    ("What type of work pass do you hold?", "DROPDOWN", PASS_LIST, "Employment Pass", {"Not applicable", "None", "Citizen", "", "STOP"}),
    ("Type of pass held", "DROPDOWN", PASS_LIST, "S Pass", {"Not applicable", "None", "Citizen", "", "STOP"}),
    ("Employment Pass expiry date", "DATE", (), "2027-05-01", {"", "STOP"}),
    ("Employment Pass expiry date", "TEXT", (), "01/05/2027", {"", "STOP"}),
    ("Work pass expiry", "TEXT", (), "2027-05-01", {"", "STOP"}),
    ("FIN number", "TEXT", (), "G1234567X", {"", "STOP"}),
    ("NRIC / FIN", "TEXT", (), "S1234567A", {"", "STOP"}),
    ("Passport number", "TEXT", (), "K1234567", {"", "STOP"}),
    ("Passport", "TEXT", (), "K1234567", {"", "STOP"}),
    ("Passport nationality", "DROPDOWN", NAT_LIST, "Malaysia", {"Singapore", "", "STOP"}),
    ("Passport expiry date", "DATE", (), "2030-01-01", {"", "STOP"}),
    ("Do you hold a Singapore passport?", "RADIO", YN, "No", {"Yes", "", "STOP"}),
    ("Do you hold a Singapore passport?", "RADIO", YN, "Yes", {"Yes", "", "STOP"}),
    ("Nationality", "DROPDOWN", NAT_LIST, "Malaysia", {"Singapore", "", "STOP"}),
    ("Citizenship", "TEXT", (), "Malaysian", {"Singapore", "Singaporean", "SG", "", "STOP"}),
    ("Country of citizenship", "DROPDOWN", NAT_LIST, "India", {"Singapore", "", "STOP"}),
    ("Singapore Citizenship Status", "DROPDOWN", ("Citizen", "Permanent Resident", "Employment Pass", "S Pass", "Other"), "Permanent Resident", {"Citizen", "", "STOP"}),
    ("Are you a Singapore citizen?", "CHECKBOX", (), "true", {"true", "", "STOP"}),
]
for label, ft, opts, val, okset in CASES:
    row = []
    for klass in ("work_right", "owner_fact", "ordinary", NO_CLASS):
        for confirm in ("follow-model", "right"):
            def pick(q, w, o, val=val):
                w = str(w)
                if w.startswith("If the applicant answers"):
                    return "no"
                return val if confirm == "follow-model" else (o[0] if o else "")
            ask = FakeAsk(lambda v, val=val, klass=klass: lie(val, klass), pick=pick, place="NONE")
            res = attempt(mk(label, ft, opts), ask)
            s = "STOP" if is_stop(res) else shown(res)
            a = "" if is_stop(res) else ("a" if res.assumed else "")
            bad = "" if s in okset else " !"
            row.append(f"{klass[:4]}/{confirm[:3]}={s[:14]}{a}{bad}")
    print(f"{label[:44]:44} {ft[:5]:5} inv={val[:12]:12} | " + "  ".join(row))
