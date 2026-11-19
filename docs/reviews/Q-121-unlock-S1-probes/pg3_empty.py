"""G3 wordings where the model is RIGHT (Yes for the sample citizen) and the facts line does / does not settle it:
confirm '' (the facts do not settle: a faithful reader) vs 'Yes' (the facts do settle it). Shows what a REQUIRED field becomes."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT

for label in ("Are you a Singapore resident?", "Are you a tax resident of Singapore?",
              "Have you been a Singapore resident for the last 2 years?",
              "Do you hold a valid Singapore passport with at least 6 months validity?",
              "Do you have a Singapore National Registration Identity Card?",
              "Are you a Singapore citizen by birth?", "Are you also a Singapore citizen?",
              "Are you a Singapore citizen currently residing in Singapore?"):
    row = []
    for conf in ("", "Yes"):
        def pick(q, w, o, conf=conf):
            w = str(w)
            if w.startswith("If the applicant answers") or "other than these facts say" in w:
                return "no"
            for x in (o or ()):
                if str(x).lower() == conf.lower():
                    return x
            return conf
        ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=pick, place=place_reply)
        res = attempt(mk(label), ask, CIT)
        row.append(f"confirm '{conf}' -> " + (what(res)[:60] if not is_stop(res) else what(res)[:70]))
    sq = AL.status_question(mk(label), "SG")
    print(f"{label[:60]:60} sq={'-' if sq is None else ('plain' if sq.plain else 'G3')} | " + " | ".join(row))
