"""Q3 / Q5: (1) G3 compound wordings where the facts settle only the STATUS part: a facts-biased confirmer (answers from the
status part alone, as a reader of "Facts about the applicant: nationality Singapore; residency status: citizen" may) and a
meaning call that reads "No" as contradicting the facts; the model is RIGHT (it knows the other part is false).
(2) National Service precedence: citizen who has / has not completed NS, non-citizen (PR), wordings that mention NS."""
import re
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from pc import CIT, PR, EP


def biased(status_yes):
    """confirmation: the status part of the question decides (Yes when the applicant holds the status); meaning call: 'yes'
    (it contradicts the facts) exactly for the value that is the opposite of the status answer."""
    def pick(q, w, o):
        w = str(w)
        r = None
        if w.startswith("If the applicant answers") or "other than these facts say" in w:
            m = re.search(r"answers «(.*?)» to the question", w)
            v = (m.group(1).strip().lower() if m else "")
            r = "no" if v == ("yes" if status_yes else "no") else "yes"
        else:
            r = "Yes" if status_yes else "No"
        for x in (o or ()):
            if str(x).lower() == r.lower():
                return x
        return r
    return pick


G3C = [("Are you a Singapore citizen and a university student?", "No"),
       ("Are you a Singapore citizen and willing to relocate?", "No"),
       ("Are you a Singapore citizen who is able to work night shifts?", "No"),
       ("Are you a Singapore citizen with a driving licence?", "No"),
       ("Are you a Singapore citizen aged 25 or above?", "No")]
print("== G3 compound wordings, CIT owner, the model is RIGHT (No: the other part is false), the confirmer is facts-biased")
for label, mv in G3C:
    ask = FakeAsk(lambda v: lie(mv, "work_right"), pick=biased(True), place=place_reply)
    res = attempt(mk(label), ask, CIT)
    print(f"  {label:62} model {mv} -> {what(res)[:120]}")
print("== same, PR owner (status part False), the model is right (No)")
for label, mv in G3C[:2]:
    ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=biased(False), place=place_reply)
    res = attempt(mk(label), ask, PR)
    print(f"  {label:62} model Yes(wrong) confirmer-biased No -> {what(res)[:120]}")

print("\n== NS precedence: what is written (model answers per ns_status; faithful)")
NS = [("Are you a Singapore citizen who has completed National Service?", "citizen+NS"),
      ("Have you completed National Service?", "NS"),
      ("Are you a Singapore citizen or PR who has served National Service?", "citizen/PR + NS"),
      ("Are you a Singapore citizen (NS-liable)?", "NS-liable"),
      ("Are you a Singapore citizen subject to National Service obligations?", "subject to NS"),
      ("As a Singapore citizen, have you completed your National Service?", "As a citizen NS"),
      ("Are you a Singapore citizen? Have you completed National Service?", "two sentences"),
      ("Are you a Singapore PR who is exempt from National Service?", "PR exempt NS"),
      ("Are you a Singapore citizen eligible for National Service deferment?", "deferment")]
import copy
variants = (("CIT ns=completed", profile_with(singapore_status__ns_status="completed")),
            ("CIT ns=exempt", profile_with(singapore_status__ns_status="exempt")),
            ("PR (no NS)", profile_with(singapore_status__nationality="MY", singapore_status__residency_status="pr",
                                         singapore_status__ns_status="not_applicable")))
for label, tag in NS:
    sq = AL.status_question(mk(label), "SG")
    row = []
    for vn, prof in variants:
        for mv in ("Yes", "No"):
            ask = FakeAsk(lambda v, mv=mv: lie(mv, "work_right"), pick=make_pick("faithful", None, mv), place=place_reply)
            res = attempt(mk(label), ask, prof)
            row.append(f"{vn[:7]}/{mv}->{cell({'written': 'STOP' if is_stop(res) else shown(res) or '-', 'assumed': getattr(res, 'assumed', None)})}")
    print(f"  {label[:70]:70} sq={'-' if sq is None else 'FIRES'} | " + " ".join(row))
