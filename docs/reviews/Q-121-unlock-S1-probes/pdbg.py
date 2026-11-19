import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa

for label in ("I am a Singapore citizen", "I am legally authorised to work in Singapore"):
    pf = mk(label, "CHECKBOX", (), required=True)
    ask = FakeAsk(lambda v: lie("true", "work_right"), pick=make_pick("faithful", "Yes", "true"), place=place_reply)
    res = attempt(pf, ask, None)
    print(label, "->", what(res))
    print("  picks:", [(str(q)[:50], str(w)[:90], o) for q, w, o in ask.picks])
    print("  sq:", AL.status_question(pf))
