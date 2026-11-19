"""Neighbour check: another person's status under the model class work_right (S2 ON and OFF), CIT and PR owners."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT, PR

real = AL.status_question
for label in ("Is your emergency contact a Singapore citizen?", "Is your referee a Singapore citizen?",
              "Is your spouse a Singapore citizen?", "Is your next of kin a Singapore PR?",
              "Is your emergency contact a Malaysian citizen?", "Does your partner hold a Singapore work pass?"):
    for vn, prof in (("CIT", CIT), ("PR", PR)):
        out = []
        for off in (False, True):
            AL.status_question = (lambda *a, **k: None) if off else real
            for klass in ("work_right", "other_person", "ordinary"):
                for mv in ("Yes", "No"):
                    ask = FakeAsk(lambda v, mv=mv, klass=klass: lie(mv, klass), pick=make_pick("faithful", None, mv), place=place_reply)
                    res = attempt(mk(label), ask, prof)
                    out.append(f"{'off' if off else 'ON '}/{klass[:5]}/{mv[0]}->{(shown(res) or '-')[:5]}{'a' if getattr(res, 'assumed', False) else ''}[{str(getattr(res, 'source', ''))[-14:]}]")
        AL.status_question = real
        print(f"{label[:52]:52} {vn}: " + " ".join(out[:6]))
