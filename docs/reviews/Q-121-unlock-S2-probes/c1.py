"""C1: the consent grid. wording x shape x model class x consent profile x model behaviour. Fake model only.
Prints: totals, then every cell where an affirmative action (tick / Yes) is taken against the owner's consents (HIGH),
every optional / yes-no cell where the owner HAS consented and nothing is ticked (MISS), and every required box
that STOPS although the owner agrees (STOPOK)."""
import sys
import time
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa
import os
from wordings import W, W_UNKEYED, W_STATUS
if os.environ.get('S2_LIST') == 'unkeyed':
    W = W_UNKEYED
elif os.environ.get('S2_LIST') == 'all':
    W = W + W_UNKEYED
elif os.environ.get('S2_LIST') == 'status':
    W = W_STATUS

CLASSES = ["consent_privacy", "consent_retention", "marketing", "ordinary", "declaration:other", NO_CLASS]
SHAPES = [("box-opt", "CHECKBOX", (), False), ("box-req", "CHECKBOX", (), True),
          ("yn-req", "RADIO", YN, True), ("yn-opt", "RADIO", YN, False)]
BEHAVE = ["agree", "refuse", "none"]
only = sys.argv[1] if len(sys.argv) > 1 else ""
profs = {n: prof(n) for n in PROFILES}


def _match(o, word):
    for x in (o or []):
        if str(x).strip().lower() == word:
            return x
    return word


def faithful(q, w, o):
    """A confirmation / meaning reader that reads the WANTED statement right (the model's SECOND call is right)."""
    w = str(w)
    if w.startswith("If the applicant answers"):
        return _match(o, "no")
    return _match(o, "no" if ("not agree" in w.lower() or "does not" in w.lower()) else "yes")


PICK = (lambda q, w, o: _match(o, "yes")) if os.environ.get("S2_PICK") == "yes" else faithful
tot = 0
high, miss, stopok, negblank = [], [], [], []
recs = []
t0 = time.time()
_sl = os.environ.get('S2_SLICE')
for _i, (label, needs, neg) in enumerate(W):
    if _sl and _i % int(_sl.split('/')[1]) != int(_sl.split('/')[0]):
        continue
    if only and only not in label:
        continue
    for sname, ftype, opts, req in SHAPES:
        for pname, p in profs.items():
            cons = p["consents"]
            allowed = None if needs is None else (False if needs == "NEVER" else all(cons[SHORT[k]] for k in needs))
            for klass in CLASSES:
                for beh in BEHAVE:
                    yes, no = ("true", "false") if ftype == "CHECKBOX" else ("Yes", "No")
                    if beh == "agree":
                        rep = lie(yes, klass)
                    elif beh == "refuse":
                        rep = lie(no, klass)
                    else:
                        rep = say(None, "none", "", False, "optional", klass=klass)
                    ask = FakeAsk(lambda v, r=rep: r, pick=PICK, place="NONE")
                    try:
                        res = attempt(mk(label, ftype, opts, required=req), ask, p)
                    except Exception as e:  # noqa
                        res = None
                        high.append((label[:60], sname, pname, klass, beh, "EXC " + repr(e)[:80]))
                        continue
                    tot += 1
                    out = out_of(res)
                    isstop = out.startswith("STOP")
                    if ftype == "CHECKBOX":
                        acted = out == "true"
                        blank = not acted and not isstop
                    else:
                        acted = out == "Yes"
                        blank = out in ("-",)
                    if isstop:
                        agree_sem = False
                    elif neg:
                        agree_sem = (not acted) if ftype == "CHECKBOX" else (out == "No")
                    else:
                        agree_sem = acted
                    tag = (label[:58], sname, pname, klass[:12], beh, out[:22])
                    if allowed is False and agree_sem and not (neg and blank and ftype != "CHECKBOX"):
                        if neg and ftype == "CHECKBOX":
                            negblank.append(tag)
                            recs.append(('NEGBLANK',) + tag)     # unticked opt-out box = consent by default (site's default)
                        else:
                            high.append(tag)
                            recs.append(('HIGH',) + tag)
                    if allowed is True and not agree_sem and not isstop and (not req or ftype != "CHECKBOX") and not neg:
                        miss.append(tag)
                        recs.append(('MISS',) + tag)
                    if allowed is True and isstop:
                        stopok.append(tag)
                        recs.append(('STOPOK',) + tag)
print("cells", tot, "secs", int(time.time() - t0))
print("HIGH (affirmative against the owner's consents):", len(high))
for t in high[:60]:
    print("  ", t)
print("NEGBLANK (opt-out box left unticked = consent by site default, owner refuses):", len(negblank))
seen = set()
for t in negblank:
    k = (t[0], t[1], t[2])
    if k in seen:
        continue
    seen.add(k)
    print("  ", t)
print("MISS (owner agrees, optional/yn, nothing agreed):", len(miss))
seen = set()
for t in miss:
    k = (t[0], t[1], t[2])
    if k in seen:
        continue
    seen.add(k)
    print("  ", t)
print("STOPOK (owner agrees but stopped):", len(stopok))
seen = set()
for t in stopok:
    k = (t[0], t[1], t[2])
    if k in seen:
        continue
    seen.add(k)
    print("  ", t)

if os.environ.get('S2_TSV'):
    NL, TAB = chr(10), chr(9)
    open(os.environ['S2_TSV'], 'w', encoding='utf-8').write(NL.join(TAB.join(map(str, r)) for r in recs))
