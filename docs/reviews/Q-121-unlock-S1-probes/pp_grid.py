"""Q4: 10 code readings x 10 model place replies, end to end. The model answers what the facts of the label's EXPECTED country
say (SG authorised: Yes; US authorised: No); the class it names is work_right; the confirmer is faithful to that country.
A cell prints S (written from Singapore's facts), U (from the US facts), - (empty), X (written from another / unclear source).
'!' = a value is written from a country other than the one the label asks about (a wrong country's facts), 'E' = the label
asks about one country and the cell is empty (safe but lost)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa

LABELS = [
    ("Are you legally authorised to work in Singapore?", "SG"),
    ("Are you legally authorised to work in the United States?", "US"),
    ("Are you authorised to work in Singapore or the United States?", None),
    ("Are you authorised to work in the EU?", None),
    ("Are you authorised to work in the country where this role is based?", "SG"),
    ("Are you authorised to work in your country of residence?", None),
    ("Are you authorised to work in Atlantis?", None),
    ("Are you authorised to work in the country you are applying to?", "SG"),
    ("Are you authorised to work outside Singapore?", None),
    ("Are you authorised to work?", "SG"),
]
REPLIES = ["NONE", "Singapore", "the United States", "United States", "outside Singapore", "Malaysia",
           "Singapore and the US", "in Singapore", "the States", "xyz"]
VAL = {"SG": "Yes", "US": "No", None: "Yes"}


def where(r):
    if r["written"] in ("-", "STOP"):
        return "-"
    s = r["src"]
    if s.endswith(".US") or "US" in s.split(".")[-1:]:
        return "U"
    if s.endswith(".SG"):
        return "S"
    if "authorised_to_work" in s and "derive" in s:
        return "S"            # derived from nationality / residency for the job's country
    return "X"


def grid(label_list, replies, show_src=False):
    bad = []
    for label, exp in label_list:
        row = []
        for rep in replies:
            r = run(label, VAL[exp], "work_right", "faithful", VAL[exp] if exp else None, "RADIO", YN, None, "SG")
            # run() uses make_place: override with a constant reply
            pf = mk(label)
            ask = FakeAsk(lambda v: lie(VAL[exp], "work_right"), pick=make_pick("faithful", VAL[exp] if exp else None, VAL[exp]),
                          place=rep)
            res = attempt(pf, ask, None)
            if is_stop(res):
                w, src = "STOP", ""
            else:
                w, src = (shown(res) or "-"), str(res.source)
            r = {"written": w, "src": src}
            c = where(r)
            mark = ""
            if c in ("S", "U", "X"):
                if exp is None or {"S": "SG", "U": "US"}.get(c) != exp:
                    mark = "!"
            elif exp is not None:
                mark = "e"
            row.append(c + mark)
            if mark == "!":
                bad.append((label, rep, w, src))
        print(f"{label[:62]:62} exp={exp or '--':3} | " + " ".join(f"{c:3}" for c in row))
    return bad


if __name__ == "__main__":
    print(" " * 71 + " ".join(f"{i:3}" for i in range(len(REPLIES))))
    for i, r in enumerate(REPLIES):
        print(f"  reply {i}: {r}")
    bad = grid(LABELS, REPLIES)
    print("\nWRONG-COUNTRY CELLS:", bad)
