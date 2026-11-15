"""Q2 round 2: second place = an UNRECOGNISED place (a city) joined to Singapore by words other than and/or.
Model quotes just 'Singapore' and answers Yes (Singapore truth). Prints written value; '-' = empty."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa

TAILS = [
    "as well as Mumbai", "along with Mumbai", "together with Mumbai", "including Mumbai", "then Mumbai",
    ", Mumbai", ", Mumbai or Delhi", "/ Mumbai", "& Mumbai", "- Mumbai", "(Mumbai)", "and/or Mumbai",
    "as well as in Mumbai", "plus Mumbai", "in addition to Mumbai", "rather than Mumbai", "instead of Mumbai",
    "versus Mumbai", "compared with Mumbai", "after Mumbai", "after working in Mumbai", "from Mumbai",
    "to Mumbai", "after moving to Mumbai", "unlike Mumbai", "at our Mumbai hub", "for the Mumbai team",
    "while in Mumbai", "when in Mumbai", "if based in Mumbai", "on assignment in Mumbai", "during a Mumbai posting",
    "as opposed to Mumbai", "but not Mumbai", "except Mumbai", "other than Mumbai", "excluding Mumbai",
    "or Mumbai", "and Mumbai", "also Mumbai", "also in Mumbai", "Mumbai and Singapore",
]
for t in TAILS:
    label = f"Are you authorised to work in Singapore {t}?" if not t.startswith(",") and not t.startswith("/") else f"Are you authorised to work in Singapore{t}?"
    pf = mk(label)
    qp = AL.quoted_place("Singapore", label, "SG")
    cp = AL.code_place(pf, "SG")
    ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=lambda q, w, o: "no" if str(w).startswith("If the") else "Yes", place="Singapore")
    res = attempt(pf, ask)
    out = "STOP" if is_stop(res) else (shown(res) or "-")
    print(f"{label[:80]:80} qp={qp or '-':3} code_place=({','.join(sorted(cp[0])) or '-'},{int(cp[1])},{int(cp[2])}) -> {out}{'   <== WRITTEN' if out not in ('-','STOP') else ''}")
