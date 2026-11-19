"""Q2 (e): tick boxes. Required and optional boxes, three owner variants, what is ticked. A box that states a status
the owner does NOT have must never end ticked (stop or unticked); a box that states the owner's own status may be ticked.
Cells: [model true] [model false] under the faithful reader. T = ticked, - = left unticked/empty, STOP."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT, PR, EP

BOXES = [
    # (label, truth of the STATEMENT for CIT, PR, EP)
    ("I am a Singapore citizen", (True, False, False)),
    ("I confirm I am a Singapore citizen", (True, False, False)),
    ("I confirm that I am a Singapore citizen", (True, False, False)),
    ("I am a Singapore citizen or PR", (True, True, False)),
    ("I am a citizen or PR", (True, True, False)),
    ("I am a citizen or permanent resident", (True, True, False)),
    ("I am a Singapore PR", (False, True, False)),
    ("I am not a Singapore citizen", (False, True, True)),
    ("I am not a citizen", (False, True, True)),
    ("I am a foreigner", (False, True, True)),
    ("I am not a Singapore citizen or PR", (False, False, True)),
    ("I hold an Employment Pass", (False, False, True)),
    ("I do not hold a work pass", (True, True, False)),
    ("I am a Singapore citizen (required)", (True, False, False)),
    ("I am a Singapore citizen or hold a valid work pass", (True, True, True)),
    ("I am a Singapore citizen and agree to the terms", (None, None, None)),
    ("I confirm I am a Singapore citizen and have read the privacy notice", (None, None, None)),
    ("I am legally authorised to work in Singapore", (True, True, True)),
    ("I require sponsorship to work in Singapore", (False, False, False)),
    ("I do not require sponsorship to work in Singapore", (True, True, True)),
    ("I am a Singaporean", (True, False, False)),
    ("I am a Malaysian", (False, True, True)),
]
if __name__ == "__main__":
    for req in (True, False):
        for label, truths in BOXES:
            row = []
            for (vn, prof), t in zip((("CIT", CIT), ("PR", PR), ("EP", EP)), truths):
                cells = []
                for mv in ("true", "false"):
                    r = run(label, mv, "work_right", "faithful", ("Yes" if t else "No") if t is not None else None,
                            "CHECKBOX", (), prof, "SG", required=req)
                    if r["stop"]:
                        c = "STOP"
                    else:
                        c = "T" if r["written"] == "TICK" else "-"
                    bad = (c == "T" and t is False)
                    cells.append(c + ("!!" if bad else "") + ("*" if r["assumed"] and c == "T" else ""))
                row.append(f"{vn} t={str(t)[0]}: " + "/".join(f"{c:5}" for c in cells))
            print(("REQ" if req else "opt"), f"{label[:62]:62} | " + " | ".join(row))
