import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT

for label, klass, mv in (("Do you hold dual citizenship?", "owner_fact", "No"), ("Do you hold dual citizenship?", "ordinary", "No"),
                         ("Were you born in Singapore?", "ordinary", "Yes"), ("Were you born in Singapore?", None, "Yes"),
                         ("Do you hold citizenship of another country?", "owner_fact", "No"),
                         ("Are you a PR holder?", "owner_fact", "No"), ("Have you ever been a permanent resident?", "owner_fact", "No")):
    ask = FakeAsk(lambda v, mv=mv, klass=klass: lie(mv, klass), pick=make_pick("faithful", mv, mv), place=place_reply)
    res = attempt(mk(label), ask, CIT)
    print(f"{label[:50]:50} {str(klass):10} -> {what(res)[:200]}")
