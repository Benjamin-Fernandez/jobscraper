"""Q6: the disagreement grid (code reading x place reply) through work_place, plus extra rows for the new S1/S2 code.
Cell = countries work_place ends on ([] = empty), '/n' = number of place calls."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
import dataclasses

ROWS = [
    ("no place", "Do you have the right to work there?"),
    ("job country", "Are you unable to work in Singapore?"),
    ("other country", "Are you authorised to work in the US?"),
    ("region", "Are you authorised to work in the EU?"),
    ("unrecognised", "Are you authorised to work in Atlantis?"),
    ("two countries", "Are you authorised to work in Singapore and the US?"),
    ("home country", "Are you authorised to work in your home country?"),
    ("residence", "Are you authorised to work in your country of residence?"),
    ("status+other country", "Are you a Singapore citizen working in Malaysia?"),
    ("status other country", "Are you a US citizen?"),
    ("status no place", "Are you a Singapore citizen?"),
    ("job phrase", "Are you authorised to work in the country in which you are applying?"),
    ("job phrase+other", "Are you authorised to work in the country you are applying to or the US?"),
    ("pass other", "Do you hold a UK work visa?"),
]
REPLIES = ["NONE", "Singapore", "the US", "US", "the EU", "Atlantis", "@garbage", "not in label", "", "unable to work",
           "Malaysia", "the country in which you are applying", "your home country"]
base = ctx()
bad = []
print(f"{'row':22}" + "".join(f"{r[:12]:>14}" for r in REPLIES))
for name, label in ROWS:
    cells = []
    for rep in REPLIES:
        calls = []
        def ask(messages, schema, *, max_tokens, temperature=0.0, seed=7, rep=rep, calls=calls):
            import json
            calls.append(1)
            q = "xq!!@@##$$" if rep == "@garbage" else rep
            return {"text": json.dumps({"quote": q}), "done_reason": "stop"}
        c = dataclasses.replace(base, ask=ask, places={})
        AL._WORK_PLACE_CACHE = getattr(AL, "_WORK_PLACE_CACHE", None)
        wp = AL.work_place(mk(label), c)
        cells.append((wp[0], len(calls)))
        s = ",".join(wp[0]) or "EMPTY"
        # the Singapore facts may be used only when SG is a country the label names or points at
        if "SG" in wp[0] and name in ("other country", "region", "unrecognised", "two countries", "home country", "residence",
                                      "status+other country", "status other country", "pass other", "job phrase+other"):
            bad.append((name, rep, s))
        if wp[0] and wp[0] != ["SG"] and name in ("no place", "job country", "region", "unrecognised", "two countries",
                                                   "home country", "residence", "status+other country", "status no place", "job phrase"):
            bad.append((name, rep, s))
    print(f"{name:22}" + "".join(f"{(','.join(w) or 'EMPTY')+'/'+str(n):>14}" for w, n in cells))
print("VIOLATIONS:", bad or "none")
