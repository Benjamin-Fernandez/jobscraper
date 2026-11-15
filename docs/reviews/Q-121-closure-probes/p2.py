"""1(a): end to end. For each label that status_question fires on, my own CORRECT answer for the owner (a Singapore
citizen, not PR, no work pass, sample profile); then 8 fake-model combinations. A cell prints what is written
(Y / N / '' empty / STOP) and a '!' when it differs from the correct answer."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one
import re

# label -> correct answer (None = unknowable / no right answer: any written value is an invention)
CASES = [
    ("Are you a Singapore citizen?", "Yes"),
    ("Is your spouse a Singapore citizen?", None),
    ("Is your referee a US citizen?", None),
    ("Does the role require a Singapore citizen?", None),
    ("Have you ever renounced Singapore citizenship?", "No"),
    ("Were you a Singapore PR before becoming a citizen?", None),
    ("Do you intend to apply for Singapore citizenship?", "No"),
    ("Are you a former Singapore citizen?", "No"),
    ("Are you not a Singapore citizen?", "No"),
    ("Are you a non-Singapore citizen?", "No"),
    ("Would you like to become a Singapore citizen?", "No"),
    ("Will you be a Singapore citizen by the start date?", "Yes"),
    ("Do you have a family member who is a Singapore citizen?", None),
    ("Is your emergency contact a Singapore citizen?", None),
    ("Is your mother a Singapore citizen or PR?", None),
    ("Are you a non-resident of Singapore?", "No"),
    ("Are you a Singapore PR?", "No"),
    ("Are you a Singapore citizen or PR?", "Yes"),
    ("Do you hold a valid Singapore work pass?", "No"),
    ("Do you hold a UK visa?", "No"),
    ("Are you a Singapore citizen working in Malaysia?", None),
    ("Are you a Singapore citizen? Are you eligible for the Singapore government scholarship?", None),
    ("Are you a Singapore citizen who has completed National Service?", None),
    ("Have you held Singapore PR status for more than 2 years?", "No"),
]

def opp(v):
    return "No" if v == "Yes" else "Yes"

def run(label, mval, confirmer, meaning, klass):
    """mval: the model's answer; confirmer: 'follow' (answers per the WANTED text as if it were the answer to the
    question) | 'right' (the correct answer, or opposite of the model when unknowable) | 'yes' | 'no';
    meaning: 'faithful' | 'yes' | 'no'."""
    correct = dict(CASES)[label]
    sq = AL.status_question(mk(label), "SG")
    truth = AL.status_truth(sq, ctx())[0] if sq and sq.country else None
    follow_val = ("Yes" if truth else "No") if truth is not None else "Yes"
    def pick(q, w, o):
        w = str(w)
        if w.startswith("If the applicant answers"):
            m = re.search(r"answers «(.*?)» to the question", w)
            v = m.group(1).strip() if m else ""
            if meaning == "yes": return "yes"
            if meaning == "no": return "no"
            ref = correct if correct else follow_val
            return "no" if v.lower() == ref.lower() else "yes"
        if confirmer == "follow": return follow_val
        if confirmer == "right": return correct or follow_val
        return "Yes" if confirmer == "yes" else "No"
    ask = FakeAsk(lambda v: lie(mval, klass), pick=pick, place="NONE")
    res = attempt(mk(label), ask)
    return res, ask

if __name__ == "__main__":
    combos = [("model right", "right"), ("model wrong", "wrong")]
    for label, correct in CASES:
        row = []
        for conf in ("follow", "right", "yes", "no"):
            for meaning in ("faithful", "no"):
                for mname in ("m=C", "m=W"):
                    if correct is None and mname == "m=W":
                        mval = "No"
                    elif correct is None:
                        mval = "Yes"
                    else:
                        mval = correct if mname == "m=C" else opp(correct)
                    res, ask = run(label, mval, conf, meaning, "work_right")
                    s = "STOP" if is_stop(res) else shown(res)
                    s = {"Yes": "Y", "No": "N", "": "-"}.get(s, s)
                    bad = "!" if (correct is not None and s in ("Y", "N") and {"Y": "Yes", "N": "No"}[s] != correct) else ("?" if correct is None and s in ("Y", "N") else "")
                    row.append(f"{s}{bad}")
        print(f"{label[:70]:70} correct={correct!s:5} | " + " ".join(row))
    print("cols: confirmer(follow,right,yes,no) x meaning(faithful,no) x model(correct|Yes, wrong|No)")
